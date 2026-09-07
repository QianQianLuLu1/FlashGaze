"""VLMClient：VLM 场景补偿客户端。

封装 Qwen-VL / GPT-4o / Claude 3 / Ollama 等 VLM 调用，仅作 ±max_adjustment 的微调。
- 所有 provider（qwen/openai/anthropic/ollama）默认走自建 requests 直连层：构造期
  解析并 pin 单一 IP，请求直连该 IP + Host 头 pin + SNI pin（HTTPS）+ 禁重定向，
  彻底消除 DNS 重绑定 TOCTOU 绕过面（含云元数据 169.254.169.254 / 私网）；零新依赖。
- 代理与 pin-IP 互斥：直连层 Session 一律 trust_env=False，HTTP_PROXY / HTTPS_PROXY /
  ALL_PROXY / NO_PROXY 与 REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE **不生效**（否则代理会
  代为解析目标主机、或替换信任根，使上述 pin 整体旁路）。检测到这些环境变量时构造期
  打一次 WARNING。
- litellm 仅作显式 opt-in 兜底（use_litellm=True）；opt-in 时仍保留构造期静态防护，
  但请求由 litellm 及其底层 HTTP 客户端发出，**不享有**上述 pin-IP 直连与代理互斥保证
  （是否走环境代理取决于 litellm 自身行为，不在本模块控制范围内）。

含指数退避重试、超时控制、429 限流处理、JSON 解析容错。
所有失败路径统一返回 VLMResult(ok=False)，由 HybridScorer 自动回退纯 CV。
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import urlparse

import requests

from flashgaze.defaults import (
    DEFAULT_VLM_BREAKER_THRESHOLD,
    DEFAULT_VLM_SEED,
    DEFAULT_VLM_TEMPERATURE,
    SUPPORTED_VLM_PROVIDERS,
    VLM_REASON_MAX_CHARS,
)
from flashgaze.models.schemas import Config, CVResult, VLMResult
from flashgaze.utils.image_io import encode_image_b64
from flashgaze.utils.logging import get_logger

logger = get_logger()

# ── LiteLLM 可选依赖探测 ───────────────────────────────
# litellm 为可选依赖：默认路径（pin-IP 直连）不依赖 litellm，任何 provider 均可用；
# 仅 use_litellm=True 的 opt-in 后端需要 litellm（未安装时 _call_litellm 返回 None，降级 retry_exhausted）
try:
    import litellm

    _LITELLM_AVAILABLE = True
except ImportError:
    # cast(Any)：装/不装 litellm 两种环境下 mypy 都通过（见 pyproject 的 mypy overrides）
    litellm = cast(Any, None)
    _LITELLM_AVAILABLE = False

# 仅对瞬时异常重试（#5-4）：超时/连接错误值得重试；鉴权/参数/内容过滤等
# 非瞬时错误应立即降级，不应消耗重试预算拉长延迟。
try:
    from litellm.exceptions import (
        APIConnectionError as _LitellmConn,
    )
    from litellm.exceptions import (
        Timeout as _LitellmTimeout,
    )

    _TRANSIENT_EXC: tuple[type[BaseException], ...] = (
        _LitellmTimeout,
        _LitellmConn,
        requests.Timeout,
        requests.ConnectionError,
        ConnectionError,
        TimeoutError,
    )
except Exception:  # noqa: BLE001 — litellm 未安装时仅用标准库瞬时异常
    _TRANSIENT_EXC = (
        requests.Timeout,
        requests.ConnectionError,
        ConnectionError,
        TimeoutError,
    )

# ── json5 容错解析 ────────────────────────────────────
# json5 已列入 install_requires；保留 ImportError 回退，是因为 vlm_client 处于
# core 主链路上，旧环境未重装依赖时硬 import 会让整个包无法 import。
# 显式声明 Optional：except 分支的 None 回退才能被 mypy 视为可达路径
json5_loads: Callable[[str], Any] | None = None
try:
    from json5 import loads as json5_loads
except ImportError:  # pragma: no cover - 仅旧环境缺依赖时走到
    pass

# 从混杂文本中截取首个 JSON 对象/数组（仅无 json5 时的回退路径使用）
_JSON_BLOB_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)

# ── VLM 批量熔断（批级共享故障信号）─────────────────────
# 熔断开启后 judge 的 error 标签：下游 ImageScore.vlm_error / cleanup 报告据此
# 区分「网络耗尽重试」与「熔断跳过」，两种情况均为纯 CV 口径。
VLM_CIRCUIT_OPEN = "circuit_open"
# 失败率熔断的最小样本量：样本不足时不做比例判定，避免批次开头个别失败误熔断。
BREAKER_MIN_SAMPLE = 20
# 失败率熔断阈值：样本量足够后失败率超过此值即熔断（覆盖「端点半死、失败分散、
# 凑不满连续失败」的场景；连续失败熔断由 breaker_threshold 负责）。
BREAKER_FAILURE_RATE = 0.8


def _strip_fences(text: str) -> str:
    """剥离 VLM 返回内容外层的 ```json ... ``` 代码围栏。

    qwen / gpt-4o / claude 普遍把 JSON 包在围栏里，裸 json.loads 必抛
    JSONDecodeError，被上层吞掉后 adjustment 恒为 0，场景补偿形同虚设。
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    # 去掉首行围栏标记（```json / ```JSON / ```）
    t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    t = t.rstrip()
    t = t.removesuffix("```")
    return t.strip()


def _loads_lenient(content: Any) -> Any:
    """容错解析 VLM 文本：去围栏 + json5（尾逗号/注释/单引号均可）。

    json5 失败（如带前后缀说明文字/前缀围栏）时回退 _JSON_BLOB_RE 截取 JSON
    主体 + stdlib json，与无 json5 环境的回退路径容错强度一致。
    解析失败抛 ValueError / TypeError，由 _parse_response 统一降级为 0 补偿。
    """
    if not isinstance(content, str):
        raise TypeError(f"content 需为 str，实际为 {type(content).__name__}")
    text = _strip_fences(content)
    if json5_loads is not None:
        try:
            return json5_loads(text)
        except ValueError:
            pass  # json5 无法解析（前后缀混杂文本等）→ 与无 json5 路径同回退
    # 回退：stdlib json，先用正则截取 JSON 主体以容忍前后缀说明文字
    m = _JSON_BLOB_RE.search(text)
    return json.loads(m.group(0) if m else text)


# ── 场景化提示词表（M5）────────────────────────────────
# auto 模式不额外调用 VLM 做场景识别（避免双倍 token），
# 而是把"请自行判断"写进提示词，由 VLM 一次完成
SCENE_PROMPTS: dict[str, str] = {
    "auto": (
        "请先自行判断图片场景类型（人像 / 风光 / 静物 / 其他），"
        "再依据该场景的常见艺术手法进行补偿判断。"
    ),
    "portrait": (
        "本图为【人像】场景。重点关注：背景虚化是否突出主体、"
        "逆光剪影是否有意为之、人脸区域清晰度是否达标。"
        "浅景深虚化属于艺术手法，应给正补偿。"
    ),
    "landscape": (
        "本图为【风光】场景。重点关注：长曝光流水/云层是否为艺术处理、"
        "逆光剪影山形、暗调氛围。慢门流水属于艺术手法，应给正补偿。"
    ),
    "still_life": (
        "本图为【静物】场景。重点关注：景深控制、布光氛围、"
        "暗调质感。整体偏暗但质感细腻属于艺术手法，应给正补偿。"
    ),
}


def _to_litellm_model(provider: str, model: str) -> str:
    """将 (provider, model) 映射为 LiteLLM 的模型字符串。

    LiteLLM 通过模型前缀路由到不同提供商，无需写任何厂商适配代码：
      qwen      -> "{model}"（DashScope 已是 OpenAI 兼容，沿用原 api_base）
      openai    -> "openai/{model}"
      anthropic -> "anthropic/{model}"
      ollama    -> "ollama/{model}"
    """
    if provider == "qwen":
        return model
    return f"{provider}/{model}"


@dataclass
class _PinnedTarget:
    """pin 后的连接目标。

    请求直连 connect_host（已解析 pin 的 IP），但 Host 头与 TLS SNI/证书校验
    仍使用原始 host_header，使"连 IP"与"针对原主机名做虚拟主机/证书校验"并存。
    """

    scheme: str
    host_header: str
    connect_host: str
    port: int
    path: str  # 去尾斜杠的 base path


def _validate_api_base_static(api_base: str) -> tuple[str, str, int | None, str]:
    """无 DNS 静态校验（#5-3 改造）。

    拒绝 scheme 非 http/https、缺少主机名、0.0.0.0/:: 这类非法连接目标。
    返回 (scheme, host, port, path)；port 为 None 表示未显式指定，由调用方按 scheme 回退。
    """
    if not api_base:
        # 空 api_base 表示使用 provider 默认端点（litellm 路径显式支持），无需校验
        return ("", "", None, "")
    parsed = urlparse(api_base)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"api_base scheme 必须为 http/https，已拒绝以防 SSRF: {api_base!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"api_base 缺少主机名，已拒绝: {api_base!r}")
    # 0.0.0.0 / :: 不是合法连接目标，拒绝
    if host in ("0.0.0.0", "::"):
        raise ValueError(f"api_base 主机 {host!r} 不是合法连接目标，已拒绝")
    return (parsed.scheme, host, parsed.port, parsed.path.rstrip("/"))


def _resolve_pinned_target(
    api_base: str, allow_private: bool = False
) -> list[_PinnedTarget] | None:
    """DNS 解析 + 范围校验 + 候选 IP 列表（消除 SSRF TOCTOU，#5-3）。

    原实现仅在构造期校验、请求期用主机名重新解析 DNS；DNS 重绑定可让
    "校验时公网 IP（通过）、请求时 169.254.169.254/内网 IP（绕过）"。本函数把
    解析结果固定为已校验的候选 IP 列表，请求时直连候选 IP，使校验与连接强一致。

    - 任一非回环解析 IP 为 私网/链路本地/保留/组播 → 默认抛 ValueError（覆盖云元数据
      169.254.169.254 与内网 10.x/192.168.x/172.16.x/172.17.x）。
    - 当 allow_private=True（ollama 自托管或显式 allow_private_targets 配置）时，上述受限
      地址不再拒绝，而是与公网/回环一并收集进候选池并仍走 pin-IP 直连（DNS 重绑定 TOCTOU
      防护完整保留，安全不依赖网段白名单）。
    - 回环（127.x/::1）始终放行以兼容本地 Ollama（与 allow_private 无关）。
    - 返回全部合法候选 IP（优先级 公网 > 受限私网 > 回环），供调用方轮询/重解析以提升
      长时服务可用性（CDN 轮换/单点宕机时仍有健康候选）。
    - 不可解析（gaierror 等）→ 返回 None，由调用方延迟解析/回退主机名（兼容测试占位主机）。
    """
    scheme, host, port, path = _validate_api_base_static(api_base)
    if not scheme:
        return None  # 空 api_base（litellm 默认端点），无需 pin
    default_port = 443 if scheme == "https" else 80
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # 无法解析的主机（如测试占位符或真实不存在域名）延迟到请求期再决定
        return None
    if not infos:
        return None
    public_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    loopback_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    private_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        # 回环放行（本地 Ollama）；与 allow_private 无关
        if ip.is_loopback:
            loopback_ips.append(ip)
            continue
        # 受限地址：默认拒绝阻断重绑定到内网/元数据；allow_private 时收集进候选池
        # 仍走 pin-IP 直连（DNS 重绑定 TOCTOU 防护完整保留）
        if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            if not allow_private:
                raise ValueError(
                    f"api_base 主机 {host!r} 解析为受限地址 {ip}，已拒绝以防 SSRF"
                    "（自托管请改用 ollama provider 或设置 allow_private_targets）"
                )
            private_ips.append(ip)
            continue
        public_ips.append(ip)
    # 优先级：公网 > 受限私网（仅 allow_private 时可能存在）> 回环（如 localhost）
    pool = public_ips or private_ips or loopback_ips
    if not pool:
        return None
    candidates: list[_PinnedTarget] = []
    for ip in pool:
        pinned_ip = str(ip)
        # IPv6 在 URL 中需用 [] 包裹
        connect_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        candidates.append(
            _PinnedTarget(
                scheme=scheme,
                host_header=host,
                connect_host=connect_host,
                port=port if port is not None else default_port,
                path=path,
            )
        )
    return candidates


@dataclass
class _ProviderRequestSpec:
    """按 provider 收敛端点/认证/报文差异，供统一 pin-IP 直连层消费。

    所有 provider 统一走构造期已 pin 的直连连接（Host 头 pin + SNI pin +
    allow_redirects=False），避免 litellm 在请求期重新解析 DNS 导致的重绑定绕过。
    - qwen/openai：OpenAI 兼容 /chat/completions，Bearer 认证
    - ollama：OpenAI 兼容 /v1/chat/completions，Bearer 认证
    - anthropic：/v1/messages，x-api-key + anthropic-version，请求体/响应需归一
    """

    path_suffix: str
    auth_name: str  # 认证头名，如 "Authorization" / "x-api-key"
    auth_prefix: str  # 拼到 api_key 前的固定前缀，如 "Bearer " 或 ""
    is_anthropic: bool = False
    # ── 采样参数规格（可复现性，PLAN-vlm-sampling-reproducibility）──
    # effective_sampling_params 据此注入/裁剪 payload 采样参数，报告回显同源。
    min_temperature: float = 0.0  # 不支持 0 的 provider 在此声明最小值（0 请求被抬升）
    max_temperature: float = 2.0  # OpenAI 兼容上限 2.0；anthropic 协议上限 1.0
    supports_seed: bool = False  # 协议是否支持 seed；不支持则静默裁剪，绝不注入


# 受支持 provider 的端点规格；与 SUPPORTED_VLM_PROVIDERS 一一对应。
# 采样规格：qwen/openai 走 OpenAI 兼容协议，支持 seed（qwen 为 DashScope 兼容模式，
# 文档声明 seed 参数）；ollama 的 OpenAI 兼容层未承诺 seed，保守不注入；
# anthropic /v1/messages 协议无 seed 且 temperature 上限 1.0。
_PROVIDER_SPECS: dict[str, _ProviderRequestSpec] = {
    "qwen": _ProviderRequestSpec(
        "/chat/completions", "Authorization", "Bearer ", supports_seed=True
    ),
    "openai": _ProviderRequestSpec(
        "/chat/completions", "Authorization", "Bearer ", supports_seed=True
    ),
    "ollama": _ProviderRequestSpec("/v1/chat/completions", "Authorization", "Bearer "),
    "anthropic": _ProviderRequestSpec(
        "/v1/messages", "x-api-key", "", is_anthropic=True, max_temperature=1.0
    ),
}


def effective_sampling_params(
    provider: str,
    temperature: float | None,
    seed: int | None,
) -> dict[str, Any]:
    """计算给定 provider 实际注入 payload 的采样参数（可复现性单一真源）。

    - temperature：None = 不注入（沿用服务端默认）；否则钳制到该 provider 规格的
      [min_temperature, max_temperature]——对不支持 0 的 provider，0 会被抬升到
      min_temperature（「取最小值」机制）。
    - seed：None 或 provider 协议不支持（supports_seed=False）时静默裁剪，不注入。
    返回 dict 只包含实际注入的键；空 dict 表示不注入任何采样参数（旧行为逃生舱）。
    供 VLMClient 构造期与报告回显（sampling_params_for_config）共用，
    保证报告展示与实际请求一致。
    """
    spec = _PROVIDER_SPECS.get(provider)
    params: dict[str, Any] = {}
    if spec is None:
        return params
    if temperature is not None:
        params["temperature"] = max(
            spec.min_temperature, min(spec.max_temperature, float(temperature))
        )
    if seed is not None and spec.supports_seed:
        params["seed"] = int(seed)
    return params


def sampling_params_for_config(config: Config) -> dict[str, Any] | None:
    """按 Config 计算 VLM 实际生效的采样参数（报告回显用）；VLM 未启用返回 None。

    启用判定与 core/factory.py::make_scorer 逐字一致（no_vlm 或缺 api_key → None），
    参数计算与 VLMClient 构造期走同一 effective_sampling_params 真源，保证
    报告 summary.vlm_sampling 展示与实际请求体一致。CLI / MCP / WebUI 三入口共用。
    """
    if config.no_vlm or not config.api_key:
        return None
    params = effective_sampling_params(
        config.vlm_provider, config.vlm_temperature, config.vlm_seed
    )
    return {"provider": config.vlm_provider, **params}

# FIX(H-5): 与 pin-IP 直连互斥的环境变量（按大写名匹配，Windows/Linux 大小写
# 变体一并覆盖）。这些变量存在时 trust_env 已关闭，它们不会被读取——此处仅用于
# 构造期一次性告警提示，不阻断不抛错（配置代理是合法运维行为，只是与 pin-IP 互斥）。
_PROXY_CA_ENV_KEYS = frozenset(
    {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
)

# FIX(H-5): 显式禁用代理（None = 该 scheme 无代理），随每次直连 POST 一并传入。
# 类型标注为 dict[str, Any] 是因 requests 的 proxies 形参标注为 Mapping[str, str]，
# 而运行时 None 值才表达「禁用该 scheme」——两者不一致，故以 Any 值类型声明。
_NO_PROXIES: dict[str, Any] = {"http": None, "https": None}


def _build_anthropic_payload(openai_payload: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 兼容报文 -> Anthropic /v1/messages 报文（只重排结构，内容不变）。

    OpenAI: content = [{"type":"text","text":...},
                       {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,XXX"}}]
    Anthropic: content = [{"type":"text","text":...},
                          {"type":"image","source":{"type":"base64",
                                                     "media_type":"image/jpeg","data":XXX}}]
    采样参数：temperature 是 Anthropic 协议字段，存在即透传；seed 不在 Anthropic
    协议中（supports_seed=False 已在 effective_sampling_params 源头裁剪），绝不透传。
    """
    messages: list[dict[str, Any]] = []
    for msg in openai_payload.get("messages", []):
        blocks: list[dict[str, Any]] = []
        for item in msg.get("content", []):
            if item.get("type") == "text":
                blocks.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                data_url = item["image_url"]["url"]
                media_type = "image/jpeg"
                if data_url.startswith("data:") and ";" in data_url:
                    media_type = data_url.split(";")[0].split(":", 1)[1]
                b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    }
                )
        messages.append({"role": msg.get("role", "user"), "content": blocks})
    payload: dict[str, Any] = {
        "model": openai_payload.get("model", ""),
        "max_tokens": openai_payload.get("max_tokens", 200),
        "messages": messages,
    }
    if "temperature" in openai_payload:
        payload["temperature"] = openai_payload["temperature"]
    return payload


def _normalize_anthropic_response(data: dict[str, Any]) -> dict[str, Any]:
    """Anthropic 响应 -> OpenAI 格式，使 _parse_response 可复用。"""
    text_parts: list[str] = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return {"choices": [{"message": {"content": "".join(text_parts)}}]}


class _PinnedIPAdapter(requests.adapters.HTTPAdapter):
    """连 IP 时固定 TLS SNI 与证书主机名为原 host（HTTPS pin 必需）。

    请求 URL 用 pin 的 IP，但 SNI 与证书主机名校验仍需针对原始主机名，
    否则 HTTPS 连 IP 会因 SNI=IP / 证书 SAN 不含 IP 而握手失败。仅在 https:// 上挂载。
    """

    def __init__(self, host: str, **kwargs: Any) -> None:
        self._sni_host = host
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["server_hostname"] = self._sni_host
        kwargs["assert_hostname"] = self._sni_host
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["server_hostname"] = self._sni_host
        kwargs["assert_hostname"] = self._sni_host
        return super().proxy_manager_for(*args, **kwargs)


class VLMClient:
    """VLM 场景补偿客户端。

    所有 provider（qwen/openai/anthropic/ollama）默认走自建 pin-IP 直连层：
    构造期解析并 pin 单一 IP，请求直连该 IP + Host 头 pin + SNI pin + 禁重定向，
    彻底消除 DNS 重绑定绕过面。litellm 仅作显式 opt-in 兜底（use_litellm=True）。

    代理与 pin-IP 互斥：直连层 Session 置 trust_env=False，环境代理变量
    （HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY）与 CA 变量
    （REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE）一律忽略，不享有例外配置。
    """

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        timeout_sec: int = 30,
        max_retries: int = 3,
        max_adjustment: float = 10.0,
        provider: str = "qwen",
        scene: str = "auto",
        use_litellm: bool = False,
        reresolve_threshold: int | None = None,
        allow_private_targets: bool = False,
        breaker_threshold: int = DEFAULT_VLM_BREAKER_THRESHOLD,
        temperature: float | None = DEFAULT_VLM_TEMPERATURE,
        seed: int | None = DEFAULT_VLM_SEED,
    ) -> None:
        if not api_key:
            raise ValueError("VLMClient 需要 api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.use_litellm = use_litellm
        # FIX(#5-3): 静态校验 + 解析 pin，拒绝 localhost/私网/链路本地等 SSRF 风险主机；
        # 解析结果缓存为候选 IP 列表 self._candidates，请求时直连候选 IP，消除 DNS 重绑定 TOCTOU。
        # 对所有 provider 生效（非 qwen 路径现也消费 self._candidates 直连，不再交由
        # litellm 在请求期重新解析 DNS）。候选列表支持轮询 + 阈值重解析以提升长时可用性。
        _scheme, host, _port, _path = _validate_api_base_static(self.api_base)
        self._host = host  # 原始主机名，用于 Host 头与 HTTPS SNI
        # provider 感知 SSRF 放行：ollama 天然自托管→默认放行受限地址；
        # 其余 provider 仅当用户显式 allow_private_targets 时放行（自托管兼容端点）。
        # 放行后仍走 pin-IP 直连，DNS 重绑定 TOCTOU 防护完整保留。
        self._allow_private = (provider == "ollama") or allow_private_targets
        if self._allow_private:
            logger.info(
                "VLM 私网/链路本地目标放行已启用（provider=%s, allow_private_targets=%s）；"
                "仍走 pin-IP 直连，DNS 重绑定 TOCTOU 防护保留",
                provider,
                allow_private_targets,
            )
        # FIX(H-5): 代理/CA 环境变量与 pin-IP 直连互斥——Session 已置 trust_env=False，
        # 下列环境变量不会被读取、不会改道；此处仅一次性告警提示，不阻断不抛错。
        detected_proxy_env = sorted(
            k for k in os.environ if k.upper() in _PROXY_CA_ENV_KEYS and os.environ[k]
        )
        if detected_proxy_env:
            logger.warning(
                "检测到代理/CA 环境变量（%s）；其与 pin-IP 直连互斥，已被整体忽略"
                "（trust_env=False），请求仍直连 pin 的 IP。如需经代理访问 VLM 端点，"
                "请改用 use_litellm=True 逃生舱",
                ", ".join(detected_proxy_env),
            )
        # 候选池：构造期解析全部已校验公网 IP（回环场景回退回环）；空列表表示占位/不可解析主机，
        # 请求期回退主机名 URL（兼容测试占位主机 http://x）。allow_private 控制受限地址是否被收集。
        self._candidates: list[_PinnedTarget] = (
            _resolve_pinned_target(self.api_base, allow_private=self._allow_private) or []
        )
        # 轮询指针：跨 judge 调用持久，使连续请求分布到不同候选 IP。
        self._candidate_idx: int = 0
        # 连续 ConnectionError 计数：达阈值时触发重解析以适配 CDN 轮换/单点宕机。
        self._conn_fail_streak: int = 0
        self._reresolve_threshold: int = reresolve_threshold or max(1, max_retries)
        # 共享可变状态锁：ThreadPoolExecutor 多 worker 并发调用 judge 时，
        # _candidate_idx / _conn_fail_streak / _candidates 的读改写必须串行化，
        # 否则 RMW（(idx+1)%len）会丢失更新、选错候选或误触发重解析。
        self._state_lock = threading.Lock()
        # ── 批量熔断状态（与上方候选管理共用 _state_lock）──────
        # _conn_fail_streak 只服务于候选轮换/重解析（连接级、达阈值即复位）；
        # 熔断是其上层的批级共享故障信号：跨图累积、触发后本批 sticky，
        # 剩余图 judge 直接早退，避免端点宕机时每图重复烧满重试预算。
        self._breaker_threshold = breaker_threshold
        self._breaker_tripped = False
        self._breaker_streak = 0  # 连续失败张数（任一成功即复位）
        self._breaker_total = 0  # 已完成的网络请求数（样本量）
        self._breaker_failures = 0  # 其中失败张数（失败率分母同 _breaker_total）
        self._breaker_logged = False  # 熔断告警日志只打一次
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.max_adjustment = max_adjustment
        self.provider = provider
        self.scene = scene
        # ── 采样参数（可复现性）──构造期按 provider 规格算定（钳制/裁剪只发生一次），
        # judge() 原样注入 payload；报告回显走同一 effective_sampling_params 真源。
        self.sampling: dict[str, Any] = effective_sampling_params(provider, temperature, seed)
        # 每线程 Session 存储（threading.local）：构造期不再持有全局 Session，
        # 而是延迟到各 worker 线程首次发起请求时经 _get_session() 惰性创建。
        # 这样 stage-2 ThreadPoolExecutor 的每个线程都独享自己的 Session/连接池，
        # 彻底规避 requests/urllib3 在跨线程共享 Session 连接池下的竞态隐患，
        # 同时保留 phase-2 并发吞吐（无需全局加锁串行化 POST）。
        self._session_store = threading.local()

    # --- pin-IP 候选管理（#5-3 续：多 IP 轮询 + 阈值重解析）---
    # 以下所有对 _candidate_idx / _conn_fail_streak / _candidates 的读改写均经
    # self._state_lock 串行化，使同一实例可被多线程并发调用（hybrid_scorer phase2
    # 的 ThreadPoolExecutor）。锁仅覆盖极短的整型/列表赋值，不包裹网络请求本身，
    # 因此不会因加锁而牺牲并发吞吐。

    def _select_target(self) -> _PinnedTarget | None:
        """线程安全：按轮询指针取当前候选 IP；候选池为空（占位/不可解析主机）返回 None。"""
        with self._state_lock:
            if not self._candidates:
                return None
            return self._candidates[self._candidate_idx % len(self._candidates)]

    def _reset_conn_fail_streak(self) -> None:
        """线程安全：成功响应后复位连续连接失败计数。"""
        with self._state_lock:
            self._conn_fail_streak = 0

    def _adopt_candidates(self, fresh: list[_PinnedTarget]) -> None:
        """线程安全：请求期惰性解析成功后填入候选池并复位轮询指针（占位主机场景）。"""
        with self._state_lock:
            self._candidates = fresh
            self._candidate_idx = 0

    def _on_connection_error(self) -> None:
        """连续 ConnectionError 处理：累加计数→轮换候选→达阈值重解析。

        锁仅覆盖极短的整型/取模状态变更（计数自增、候选轮换、阈值判定），
        不再包裹慢速 DNS 解析（_resolve_pinned_target / socket.getaddrinfo），
        否则一次 DNS 抖动（最长为 timeout_sec）会持锁阻塞所有并发线程的
        _select_target()/_on_connection_error()，整批 VLM 调用被串行化、触发假性超时。

        达阈值时，DNS 解析在**锁外**并行执行，随后以"乐观回写"模式重入锁：
        仅当 _conn_fail_streak 仍处阈值状态（未被成功路径 _reset_conn_fail_streak
        复位、未被其它线程重解析覆盖）时才采纳新候选池，避免写入过期候选。
        重解析仍走 _resolve_pinned_target 的安全校验（受限地址一律拒绝），
        绝不回退到主机名直连；若重解析失败（含受限校验抛错或不可解析），
        保留旧候选池、复位计数以避免 DNS 风暴。
        """
        with self._state_lock:
            self._conn_fail_streak += 1
            if self._candidates:
                self._candidate_idx = (self._candidate_idx + 1) % len(self._candidates)
            need_reresolve = self._conn_fail_streak >= self._reresolve_threshold
        # 锁外做慢速 DNS 解析，不再阻塞并发线程的 _select_target()/_on_connection_error()
        if not need_reresolve:
            return
        try:
            fresh = _resolve_pinned_target(self.api_base, allow_private=self._allow_private)
        except ValueError:
            fresh = None
        # 乐观回写：仅在计数仍处阈值状态时才采纳，避免与成功路径/其它线程重解析竞争
        with self._state_lock:
            if fresh and self._conn_fail_streak >= self._reresolve_threshold:
                self._candidates = fresh
                self._candidate_idx = 0
            # 无论重解析成功与否，复位计数避免无限重解析
            self._conn_fail_streak = 0

    # --- 批量熔断（批级共享故障信号，与候选管理共用 _state_lock）---

    def _is_breaker_open(self) -> bool:
        """熔断是否已开启。开启后 judge 入口直接早退，零网络零重试。"""
        with self._state_lock:
            return self._breaker_tripped

    def _record_vlm_outcome(self, ok: bool) -> None:
        """记录单次网络请求的结果并评估熔断条件（线程安全）。

        只统计发起过网络请求的 judge 结果：
        - unsupported_provider / 图片编码失败属预检失败（零网络成本、非端点健康
          信号），在 judge 中不经过本方法，避免污染端点健康判定与误熔断；
        - 成功复位连续失败计数；失败累加连续计数与失败率样本。

        熔断条件（二选一，先到先熔断）：
        1. 连续失败张数 >= breaker_threshold（硬宕机快速止损）；
        2. 样本量 >= BREAKER_MIN_SAMPLE 且失败率 >= BREAKER_FAILURE_RATE
           （端点半死、失败分散、凑不满连续失败的场景）。

        触发后本批 sticky（实例由 make_scorer 每批新建，实例级 = 批级作用域），
        告警日志只打一次且在锁外发出。
        """
        first_trip = False
        with self._state_lock:
            self._breaker_total += 1
            if ok:
                self._breaker_streak = 0
            else:
                self._breaker_failures += 1
                self._breaker_streak += 1
            # 阈值已关 / 已熔断 / 未启用：无需再评估
            if self._breaker_tripped or self._breaker_threshold <= 0:
                return
            tripped = self._breaker_streak >= self._breaker_threshold
            if not tripped and self._breaker_total >= BREAKER_MIN_SAMPLE:
                tripped = self._breaker_failures / self._breaker_total >= BREAKER_FAILURE_RATE
            if tripped:
                self._breaker_tripped = True
                first_trip = not self._breaker_logged
                self._breaker_logged = True
        if first_trip:
            logger.warning(
                "VLM 熔断触发：连续失败 %d 张（样本 %d 张失败 %d 张），"
                "剩余图片跳过 VLM 评分，将采用纯 CV 口径",
                self._breaker_streak,
                self._breaker_total,
                self._breaker_failures,
            )

    def judge(
        self,
        img_path: str,
        cv_result: CVResult,
        pre_encoded_b64: str | None = None,
    ) -> VLMResult:
        """对单图判断模糊/偏暗是否为艺术手法，返回 ±max_adjustment 补偿。

        pre_encoded_b64 非 None 时直接用于请求体（阶段 1 已编码好的 base64），
        跳过 encode_image_b64 的重复读盘解码；否则回退原路径重新编码。

        批量熔断：开启后直接返回 error="circuit_open" 的失败结果（零网络零重试），
        剩余图秒级降级为纯 CV，不再逐图烧满重试预算（假性挂起数小时）。
        熔断统计只覆盖发起过网络请求的路径——unsupported_provider 与编码失败
        属预检失败，不计入（零网络成本、非端点健康信号）。
        """
        if self._is_breaker_open():
            return VLMResult(
                0.0,
                "",
                ok=False,
                error=VLM_CIRCUIT_OPEN,
                provider=self.provider,
                scene=self.scene,
            )

        # 不支持的 provider 直接降级（不抛异常）
        if self.provider not in SUPPORTED_VLM_PROVIDERS:
            return VLMResult(
                0.0,
                "",
                ok=False,
                error="unsupported_provider",
                provider=self.provider,
                scene=self.scene,
            )

        if pre_encoded_b64 is not None:
            b64 = pre_encoded_b64
        else:
            try:
                b64 = encode_image_b64(img_path)
            except Exception as e:  # noqa: BLE001 — 单图 base64 编码失败降级为错误结果
                return VLMResult(
                    0.0,
                    "图片编码失败",
                    ok=False,
                    error=str(e),
                    provider=self.provider,
                    scene=self.scene,
                )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_prompt(cv_result, self.scene)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 200,
            # 采样参数（temperature/seed，可复现性）：构造期已按 provider 规格算定，
            # None 语义的键不在此出现（旧行为逃生舱）
            **self.sampling,
        }
        data = self._post_with_retry(payload)
        if data is None:
            # 网络级失败（重试耗尽/4xx/非 dict JSON）：计入熔断统计
            self._record_vlm_outcome(False)
            return VLMResult(
                0.0,
                "API 调用失败",
                ok=False,
                error="retry_exhausted",
                provider=self.provider,
                scene=self.scene,
            )
        result = self._parse_response(data)
        # 解析成败均计入：成功复位连续计数；解析失败说明端点返回异常内容，
        # 同属端点健康信号（失败率熔断据此覆盖「有响应但全不可用」的场景）。
        self._record_vlm_outcome(result.ok)
        return result

    def _build_prompt(self, cv: CVResult, scene: str = "auto") -> str:
        scene_hint = SCENE_PROMPTS.get(scene, SCENE_PROMPTS["auto"])
        return (
            "你是摄影评分助手。下面给出该图的客观指标："
            f"清晰度={cv.sharpness}/100，曝光度={cv.exposure}/100。"
            f"{scene_hint}"
            "请判断图片中的'模糊'或'偏暗'是否为艺术手法（如背景虚化、逆光剪影、暗调氛围）。"
            "若是艺术手法，给正补偿；若是技术失误，给负补偿。"
            f"补偿值范围 -{self.max_adjustment} 到 +{self.max_adjustment}。"
            "理由必须不超过 20 个汉字，超出将被截断。"
            '仅返回 JSON：{"adjustment": 数字, "reason": "20字以内理由"}'
        )

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """统一调度入口。

        - 默认（use_litellm=False）：所有 provider 走自建 pin-IP 直连层，消除重绑定绕过面
        - use_litellm=True：回退 LiteLLM 兼容逃生舱（仍保留构造期静态防护）
        """
        if self.use_litellm:
            return self._call_litellm(payload)
        return self._post_pinned_requests(payload)

    def _get_session(self) -> requests.Session:
        """线程局部 Session：每线程首次调用时惰性创建并挂载 pin 适配器。

        ThreadPoolExecutor 下各 worker 线程经此拿到各自独立的 Session 实例
        （各自持有独立 urllib3 连接池），从根上消除跨线程共享 Session 的
        连接池竞态。挂载的 _PinnedIPAdapter 与原全局单例逐字等价——HTTPS
        连 IP 时固定 SNI/证书主机名为原 host；self._host 为空（占位主机）
        时不挂载，与原 __init__ 行为一致。
        """
        try:
            return cast(requests.Session, self._session_store.session)
        except AttributeError:
            s = requests.Session()
            # FIX(H-5): 关闭环境变量信任——requests 的 env 合并集中在
            # merge_environment_settings 且全部受 trust_env 门控，置 False 后
            # HTTP(S)_PROXY/ALL_PROXY/NO_PROXY（代理改道，由代理解析目标主机名，
            # 使 pin-IP/Host pin/SNI pin 全部失效）与 REQUESTS_CA_BUNDLE/
            # CURL_CA_BUNDLE（替换信任根使证书校验失效）两条旁路在源头一并关闭。
            s.trust_env = False
            if self._host:
                s.mount("https://", _PinnedIPAdapter(host=self._host))
            self._session_store.session = s
            return s

    def _post_pinned_requests(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """统一 pin-IP 直连 POST（所有 provider 共用，消除重绑定绕过面）。

        与 qwen 原路径一致：URL 直连候选池中的 IP（self._candidates），Host 头保留原
        主机名，HTTPS 经 _PinnedIPAdapter 固定 SNI/证书主机名，allow_redirects=False
        阻断重定向型 SSRF。anthropic 经 spec 归一为 OpenAI 报文后复用 _parse_response。

        长时可靠性（#5-3 续）：重试循环内每次尝试现选候选、现拼 url/Host 头；
        ConnectionError 触发 _on_connection_error（轮换候选 + 达阈值重解析以适配
        CDN 轮换/单点宕机），成功即复位连续失败计数。

        候选池为空（构造期不可解析主机）时不再裸交给 requests 在请求期重新解析
        DNS（那会重新引入 DNS 重绑定 TOCTOU）；改为请求期惰性解析：解析成功则
        填入候选池走 pin-IP 直连、受限地址（私网/元数据）抛 ValueError 安全降级、
        始终不可解析的占位主机（http://x）才回退主机名 URL 以保持兼容。
        """
        spec = _PROVIDER_SPECS.get(self.provider)
        if spec is None:
            return None
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if spec.auth_name:
            headers[spec.auth_name] = spec.auth_prefix + self.api_key
        if spec.is_anthropic:
            headers["anthropic-version"] = "2023-06-01"
        # anthropic 报文归一（OpenAI -> Anthropic），其余 provider 原样透传
        req_payload = _build_anthropic_payload(payload) if spec.is_anthropic else payload
        for attempt in range(self.max_retries):
            # 熔断已开：在途图不再烧剩余重试预算（最坏多付一个 attempt 的代价），
            # 立即降级返回 None → judge 记为 retry_exhausted
            if self._is_breaker_open():
                return None
            target = self._select_target()
            if target is None:
                # FIX(P1): 候选池为空（构造期不可解析主机）时，绝不在请求期裸交给
                # requests 重新解析 DNS——那会重新引入 DNS 重绑定 TOCTOU，使 pin-IP
                # 抗重绑定的核心收益在该路径被绕过。改为请求期惰性解析：
                #   ① 解析成功 → 填入候选池、取首个 pin IP 直连（与正常路径强一致）；
                #   ② 受限地址（私网/链路本地/保留）抛 ValueError → 安全降级拒绝、
                #      绝不发起裸请求；
                #   ③ 仍不可解析（占位主机 http://x）→ 保留原回退主机名行为，兼容测试。
                # 每次 attempt 都重新惰性解析，以兼容"构造期不可解析、请求期才上线"
                # 的 fast-flux/延迟内网场景；解析成功后候选池持久化，后续 attempt 复用轮询。
                try:
                    fresh = _resolve_pinned_target(self.api_base, allow_private=self._allow_private)
                except ValueError:
                    # 受限地址：DNS 重绑定攻击面，安全降级、绝不裸请求
                    return None
                if fresh:
                    self._adopt_candidates(fresh)
                    target = self._select_target()
            if target is None:
                # 不可解析占位主机（http://x）：回退主机名行为（兼容测试契约）
                url = f"{self.api_base}{spec.path_suffix}"
                headers.pop("Host", None)
            else:
                url = f"{target.scheme}://{target.connect_host}:{target.port}{target.path}{spec.path_suffix}"
                headers["Host"] = target.host_header
            try:
                resp = self._get_session().post(
                    url,
                    headers=headers,
                    json=req_payload,
                    timeout=self.timeout_sec,
                    allow_redirects=False,
                    # FIX(H-5): belt-and-suspenders——显式禁用代理，防未来 trust_env
                    # 被误改回 True 时代理旁路防线完全消失（None = 该 scheme 无代理）。
                    proxies=_NO_PROXIES,
                )
                # 200/可连接即视为候选可达，复位连续 ConnectionError 计数
                self._reset_conn_fail_streak()
                try:
                    if resp.status_code == 429:
                        # 429 限流：尊重 Retry-After 退避后重试；退避前先看熔断，
                        # 避免为已熔断的端点白睡最长 60s 的 Retry-After
                        if self._is_breaker_open() or attempt >= self.max_retries - 1:
                            return None
                        retry_after = self._parse_retry_after(resp)
                        time.sleep(retry_after)
                        continue
                    if resp.status_code >= 500:
                        # 5xx 服务端瞬时错误（502/503/504 等）：复用 max_retries
                        # 指数退避重试，避免单次网关抖动即整批退回纯 CV 而缺失语义评分。
                        # 4xx（非 429）不在此分支，立即降级（见下方 raise_for_status）。
                        if attempt < self.max_retries - 1:
                            time.sleep(2**attempt)
                            continue
                        return None
                    resp.raise_for_status()
                    data = resp.json()
                    # 200 + 非 dict JSON（数组/字符串等）无法进入 _parse_response，按降级处理
                    if not isinstance(data, dict):
                        return None
                    return (
                        _normalize_anthropic_response(data)
                        if spec.is_anthropic
                        else data
                    )
                finally:
                    # FIX(#5-2): 无论哪条分支返回/异常，都释放响应连接回池，
                    # 避免 429/5xx/HTTPError 分支直接丢弃响应导致连接泄漏。
                    resp.close()
            except requests.Timeout:
                # 超时按原退避重试，不轮换/不重解析（与用户明确范围一致）
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2**attempt)
            except requests.ConnectionError:
                # 连接失败：轮换候选 + 连续计数，达阈值重解析刷新 IP 池
                self._on_connection_error()
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2**attempt)
            except requests.HTTPError:
                # 仅 4xx（非 429）落此分支（429 与 5xx 已在上方显式处理/重试），
                # 客户端错误（鉴权/参数等）重试无效，立即降级为纯 CV。
                return None
            # FIX(#5-1): 200 + 非 JSON 响应时 resp.json() 抛 JSONDecodeError
            # （ValueError 子类，非 HTTPError），须降级而非冒泡崩溃评分。
            except requests.exceptions.JSONDecodeError:
                return None
            except requests.exceptions.RequestException:
                # M-5: 其余传输异常（ChunkedEncodingError 响应流截断等）同样瞬时，
                # 与超时同等待遇退避重试；更具体的 Timeout/ConnectionError/HTTPError/
                # JSONDecodeError 分支保持前置优先匹配，语义不变。
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2**attempt)
        return None

    def _call_litellm(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """通过 LiteLLM 统一调用层发起请求。

        LiteLLM 内部根据 model 前缀路由到对应厂商，自动处理：
        - 认证 header 拼接（Bearer / x-api-key 等）
        - URL 改写（OpenAI / Anthropic / Ollama 端点）
        - 响应字段名统一为 OpenAI 格式

        任何异常（含依赖缺失、网络错误、解析失败）统一返回 None 触发降级。
        """
        if not _LITELLM_AVAILABLE:
            return None
        litellm_model = _to_litellm_model(self.provider, payload.get("model", self.model))
        # LiteLLM 的 messages 结构与 OpenAI 兼容，原样透传
        messages = payload.get("messages", [])
        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "timeout": self.timeout_sec,
            "api_key": self.api_key,
        }
        # api_base 仅在非空时透传：Anthropic 等留空时走 LiteLLM 默认端点
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if "max_tokens" in payload:
            kwargs["max_tokens"] = payload["max_tokens"]
        # 采样参数透传（可复现性）：payload 存在才传——anthropic 协议无 seed 的
        # 裁剪已在构造期 effective_sampling_params 完成，此处不会收到 seed
        if "temperature" in payload:
            kwargs["temperature"] = payload["temperature"]
        if "seed" in payload:
            kwargs["seed"] = payload["seed"]

        for attempt in range(self.max_retries):
            # 熔断已开：与 pin-IP 路径同等待遇，不再烧剩余重试预算
            if self._is_breaker_open():
                return None
            try:
                resp = litellm.completion(**kwargs)
                # LiteLLM 返回 ModelResponse 对象，统一转换为 dict 以复用 _parse_response
                if isinstance(resp, dict):
                    return resp
                # litellm.ModelResponse 支持 model_dump() / to_dict()，
                # 两者按契约均返回 dict；litellm 在 ignore_missing_imports 下
                # 返回值为 Any，此处 cast 收敛类型
                if hasattr(resp, "model_dump"):
                    return cast(dict[str, Any], resp.model_dump())
                if hasattr(resp, "to_dict"):
                    return cast(dict[str, Any], resp.to_dict())
                # 兜底：尝试 json.loads(json.dumps(...)) 强制序列化
                return cast(dict[str, Any], json.loads(json.dumps(resp, default=str)))
            except _TRANSIENT_EXC:
                # FIX(#5-4): 仅对瞬时异常（超时/连接错误）重试；非瞬时（鉴权/参数/
                # 内容过滤）重试无用且浪费预算，直接降级。
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2**attempt)
            except Exception:  # noqa: BLE001 — 非瞬时错误立即降级，不消耗重试预算
                # 非瞬时错误：立即降级，不消耗重试预算
                return None
        return None

    @staticmethod
    def _parse_retry_after(resp: requests.Response) -> float:
        """解析 Retry-After header。支持秒数和 HTTP 日期格式。"""
        raw = resp.headers.get("Retry-After")
        if not raw:
            return 1.0  # 默认 1 秒
        try:
            # FIX(#vlm-retry-after): 整数秒分支同样钳制 [1, 60]：上限防恶意超大值
            # 使 worker 不可中断长睡（可用性 DoS）；下限 max(1.0, …) 对齐日期分支，
            # 消除负值/0 造成 time.sleep ValueError（NaN 亦归 1.0）。
            # 与下方日期分支保持一致。
            return max(1.0, min(float(raw), 60.0))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
                if dt is None:  # typeshed 标注非 Optional，此处纯防御个别运行时
                    return 1.0  # type: ignore[unreachable]
                now = datetime.now(timezone.utc)
                diff = (dt - now).total_seconds()
                return max(1.0, min(diff, 60.0))
            except Exception:  # noqa: BLE001 — 解析失败降级为 1.0（满惩罚）
                return 1.0

    def _parse_response(self, data: dict[str, Any]) -> VLMResult:
        """解析 VLM 返回的 JSON。容错：超范围 clamp，超长理由截断，解析失败返回 0 补偿。"""
        try:
            # M-4: 防御式取值——空 choices / message 为 null / choices 元素非 dict
            # 等畸形响应一律取不到 content，落入下方 except 降级，而非 IndexError 上抛
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            parsed = _loads_lenient(content)
            adj = float(parsed["adjustment"])
            if not math.isfinite(adj):
                # M-2: NaN/Inf 不参与 clamp——NaN 经 min/max 比较恒假，会穿透成
                # +max 满额补偿；非有限值与解析失败同路降级为 0
                raise ValueError(f"adjustment 非有限值: {adj}")
            adj = max(-self.max_adjustment, min(self.max_adjustment, adj))  # ±max 硬上限
            # L2/N-C1: reason=null 归空（勿产出字面量 "None"）；保留 str() 强转防
            # 非 str 值在切片处抛 TypeError 把整条成功响应降级；截断后清洗孤立
            # 代理项（\ud83d 等不可 UTF-8 编码字符），避免下游落盘 UnicodeEncodeError
            reason = str(parsed.get("reason") or "")[:VLM_REASON_MAX_CHARS]
            reason = reason.encode("utf-8", "ignore").decode("utf-8")
            return VLMResult(
                adjustment=round(adj, 2),
                reason=reason,
                ok=True,
                provider=self.provider,
                scene=self.scene,
            )
        except (
            KeyError,
            IndexError,
            AttributeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
        ) as e:
            return VLMResult(
                0.0,
                "解析失败",
                ok=False,
                error=str(e),
                provider=self.provider,
                scene=self.scene,
            )

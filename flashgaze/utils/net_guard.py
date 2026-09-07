"""api_base 端点可信性判定（H-6 端点白名单）。

职责边界（刻意收敛）：
- **纯静态判定**：只解析 URL 字面量与 IP 字面量，**不调用 `socket.getaddrinfo`**，
  避免配置装配期引入网络依赖与超时。域名→IP 的受限地址校验仍由
  `core/vlm_client._resolve_pinned_target`（请求期 pin-IP 直连）负责，两者互不替代。
- **不抛异常、不改配置**：判定结果仅供 `utils/config.build_config` 告警使用。
  非白名单端点**仅告警放行**（用户裁定零破坏性），是否阻断由策略层决定。

匹配口径：白名单条目按「主机名精确匹配，或以 `.条目` 结尾」锚定，因此
`dashscope.aliyuncs.com.evil.com` 这类后缀欺骗不会误命中（有专门反例用例）。
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

# 主机名层面的「本机」字面量（IP 形式的回环由 ipaddress 判定）
_LOCAL_HOST_NAMES = frozenset({"localhost"})

_HTTP_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class ApiBaseVerdict:
    """端点判定结果。

    host：归一化后的小写主机名（无法解析时为 ""）。
    trusted：True = 白名单命中 / 已显式确认 / 私网豁免 / 空端点。
    reason：人类可读判定原因，直接进入告警文案。
    """

    host: str
    trusted: bool
    reason: str


def api_base_host(api_base: str) -> str:
    """提取小写主机名（去端口、去 IPv6 方括号、去尾部点）。

    无法解析（空串 / 畸形 URL）时返回 ""，由调用方按「缺少主机名」处理。
    无 scheme 的输入（如 `localhost:11434`）补中性前缀后仍能解析出主机名，
    scheme 合法性留给 `check_api_base` 单独判定。
    """
    raw = (api_base or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = f"//{raw}"
    try:
        host = urlparse(raw).hostname
    except ValueError:
        # 畸形端口（如 http://host:notaport）会让 urlparse 抛 ValueError
        return ""
    return (host or "").strip().strip(".").lower()


def is_private_or_loopback_host(host: str) -> bool:
    """主机是否为私网 / 回环 / 链路本地的 IP 字面量，或 localhost。

    仅判定字面量：域名（如 my-nas.internal）一律返回 False，其真实 IP 由
    请求期 pin-IP 解析与 SSRF 校验负责，装配期不做 DNS。
    """
    h = (host or "").strip().strip(".").lower()
    if h in _LOCAL_HOST_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


def _normalize_entry(entry: object) -> str:
    """归一化单个白名单条目；非字符串一律视为空条目（由调用方跳过）。

    形参标注为 `object` 而非 `str`：配置来源（JSON 数组）可能混入数字/null，
    此处必须保留运行时类型防御；若标注为 str，mypy（warn_unreachable）会把
    isinstance 判定视为恒真并报错，反而逼人删掉这层防御。
    """
    if not isinstance(entry, str):
        return ""
    return entry.strip().strip(".").lower()


def is_host_allowlisted(host: str, allowlist: Sequence[str]) -> bool:
    """主机名是否命中白名单（精确匹配或以 `.条目` 结尾，大小写不敏感）。

    空条目与非字符串条目一律忽略——配置来源（env 逗号分隔、JSON 数组）可能
    带入 `""` 或数字，若不过滤会让空条目命中任意主机、白名单整体失效。
    """
    h = (host or "").strip().strip(".").lower()
    if not h:
        return False
    for entry in allowlist:
        e = _normalize_entry(entry)
        if not e:
            continue
        if h == e or h.endswith(f".{e}"):
            return True
    return False


def check_api_base(
    api_base: str,
    *,
    provider: str,
    allow_private_targets: bool,
    allowlist: Sequence[str],
    allow_untrusted: bool,
) -> ApiBaseVerdict:
    """判定 api_base 是否可信。纯函数、零网络、不抛异常。

    判定顺序（先到先返回）：
    1. 空端点 → trusted（litellm 默认端点路径，与 `_validate_api_base_static`
       对空值的豁免对齐）；
    2. scheme 非 http/https 或缺主机名 → untrusted；
    3. 私网/回环/链路本地主机 → `allow_private_targets` 或 `provider == "ollama"`
       时 trusted（自托管豁免），否则 untrusted（提示将被 SSRF 防护拒绝）；
    4. 命中白名单 → trusted；
    5. 已显式确认（allow_untrusted）→ trusted；
    6. 其余（公网非白名单）→ untrusted。
    """
    raw = (api_base or "").strip()
    if not raw:
        return ApiBaseVerdict("", True, "api_base 为空，使用 provider 默认端点")

    host = api_base_host(raw)
    if "//" in raw:
        scheme = (urlparse(raw).scheme or "").lower()
    else:
        scheme = ""
    # 无 scheme 的输入（localhost:11434）按协议缺失处理：vlm_client 构造期同样拒绝
    if scheme not in _HTTP_SCHEMES:
        return ApiBaseVerdict(
            host, False, f"api_base scheme 非 http/https（当前 {scheme or '缺失'}）"
        )
    if not host:
        return ApiBaseVerdict("", False, "api_base 缺少主机名")

    if is_private_or_loopback_host(host):
        if allow_private_targets or provider == "ollama":
            return ApiBaseVerdict(host, True, "私网/回环目标，已按自托管豁免")
        return ApiBaseVerdict(
            host,
            False,
            "私网/回环目标，当前未放行（将被 SSRF 防护拒绝）",
        )

    if is_host_allowlisted(host, allowlist):
        return ApiBaseVerdict(host, True, "端点命中白名单")

    if allow_untrusted:
        return ApiBaseVerdict(host, True, "端点已显式确认为可信")

    return ApiBaseVerdict(host, False, "公网端点不在白名单内")

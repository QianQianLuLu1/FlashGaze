"""VLMClient：VLM 场景补偿客户端。

封装 Qwen-VL / GPT-4o / Claude 3 / Ollama 等 VLM 调用，仅作 ±max_adjustment 的微调。
- provider=qwen（默认）：走 requests.post 直发 OpenAI 兼容端点，零新依赖，100% 向后兼容
- provider=openai/anthropic/ollama：走 LiteLLM 统一调用层，无需任何厂商专属适配代码

含指数退避重试、超时控制、429 限流处理、JSON 解析容错。
所有失败路径统一返回 VLMResult(ok=False)，由 HybridScorer 自动回退纯 CV。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from flashgaze.defaults import (
    SUPPORTED_VLM_PROVIDERS,
    VLM_REASON_MAX_CHARS,
)
from flashgaze.models.schemas import CVResult, VLMResult
from flashgaze.utils.image_io import encode_image_b64

# ── LiteLLM 可选依赖探测 ───────────────────────────────
# 未安装 litellm 时，provider=qwen 路径仍可用（走 requests）；
# provider=其他 时直接降级为 VLMResult(ok=False)
try:
    import litellm
    _LITELLM_AVAILABLE = True
except ImportError:
    litellm = None  # type: ignore[assignment]
    _LITELLM_AVAILABLE = False


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


class VLMClient:
    """VLM 场景补偿客户端。

    provider=qwen 时走 requests.post 直发 OpenAI 兼容端点；
    其他 provider 走 LiteLLM 统一调用层（需 pip install litellm）。
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
    ):
        if not api_key:
            raise ValueError("VLMClient 需要 api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.max_adjustment = max_adjustment
        self.provider = provider
        self.scene = scene

    def judge(self, img_path: str, cv_result: CVResult) -> VLMResult:
        """对单图判断模糊/偏暗是否为艺术手法，返回 ±max_adjustment 补偿。"""
        # 不支持的 provider 直接降级（不抛异常）
        if self.provider not in SUPPORTED_VLM_PROVIDERS:
            return VLMResult(
                0.0, "", ok=False,
                error="unsupported_provider",
                provider=self.provider, scene=self.scene,
            )
        # 非 qwen 提供商必须有 litellm
        if self.provider != "qwen" and not _LITELLM_AVAILABLE:
            return VLMResult(
                0.0, "", ok=False,
                error="litellm_not_installed",
                provider=self.provider, scene=self.scene,
            )

        try:
            b64 = encode_image_b64(img_path)
        except Exception as e:
            return VLMResult(
                0.0, "图片编码失败", ok=False, error=str(e),
                provider=self.provider, scene=self.scene,
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
        }
        data = self._post_with_retry(payload)
        if data is None:
            return VLMResult(
                0.0, "API 调用失败", ok=False,
                error="retry_exhausted",
                provider=self.provider, scene=self.scene,
            )
        return self._parse_response(data)

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
            "仅返回 JSON：{\"adjustment\": 数字, \"reason\": \"20字以内理由\"}"
        )

    def _post_with_retry(self, payload: dict) -> Optional[dict]:
        """统一调度入口：qwen 走 requests，其他走 LiteLLM。

        - provider=qwen：保留原 requests.post 路径（DashScope 兼容协议，性能更好且零新依赖）
        - 其他 provider：走 _call_litellm，LiteLLM 内部统一处理厂商差异
        """
        if self.provider != "qwen":
            return self._call_litellm(payload)
        return self._post_with_retry_requests(payload)

    def _post_with_retry_requests(self, payload: dict) -> Optional[dict]:
        """POST 请求，对超时/连接错误/429 限流重试。4xx(非429)/5xx 不重试。

        429 时优先使用 Retry-After header 指定的等待时间，否则指数退避。
        """
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout_sec
                )
                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp)
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    return None
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)
            except requests.HTTPError:
                return None
        return None

    def _call_litellm(self, payload: dict) -> Optional[dict]:
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
        kwargs: dict = {
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

        for attempt in range(self.max_retries):
            try:
                resp = litellm.completion(**kwargs)
                # LiteLLM 返回 ModelResponse 对象，统一转换为 dict 以复用 _parse_response
                if isinstance(resp, dict):
                    return resp
                # litellm.ModelResponse 支持 model_dump() / to_dict()
                if hasattr(resp, "model_dump"):
                    return resp.model_dump()
                if hasattr(resp, "to_dict"):
                    return resp.to_dict()
                # 兜底：尝试 json.loads(json.dumps(...)) 强制序列化
                return json.loads(json.dumps(resp, default=str))
            except Exception:
                # 任意异常（含 litellm.exceptions.* / 网络错误 / 超时）统一降级
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)
        return None

    @staticmethod
    def _parse_retry_after(resp: requests.Response) -> float:
        """解析 Retry-After header。支持秒数和 HTTP 日期格式。"""
        raw = resp.headers.get("Retry-After")
        if not raw:
            return 1.0  # 默认 1 秒
        try:
            return float(raw)
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
                if dt is None:
                    return 1.0
                now = datetime.now(timezone.utc)
                diff = (dt - now).total_seconds()
                return max(1.0, min(diff, 60.0))
            except Exception:
                return 1.0

    def _parse_response(self, data: dict) -> VLMResult:
        """解析 VLM 返回的 JSON。容错：超范围 clamp，超长理由截断，解析失败返回 0 补偿。"""
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            adj = float(parsed["adjustment"])
            adj = max(-self.max_adjustment, min(self.max_adjustment, adj))  # ±max 硬上限
            # 20 字硬截断（按字符数计，不按字节）
            reason = str(parsed.get("reason", ""))[:VLM_REASON_MAX_CHARS]
            return VLMResult(
                adjustment=round(adj, 2),
                reason=reason,
                ok=True,
                provider=self.provider,
                scene=self.scene,
            )
        except (KeyError, json.JSONDecodeError, ValueError, TypeError) as e:
            return VLMResult(
                0.0, "解析失败", ok=False, error=str(e),
                provider=self.provider, scene=self.scene,
            )

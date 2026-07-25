"""VLMClient：VLM 场景补偿客户端。

封装 Qwen-VL / GPT-4o-mini 等 OpenAI 兼容 API，仅作 ±max_adjustment 的微调。
含指数退避重试、超时控制、429 限流处理、JSON 解析容错、prompt 国际化。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from flashgaze.defaults import DEFAULT_VLM_LANG, SUPPORTED_VLM_LANGS
from flashgaze.models.schemas import CVResult, VLMResult
from flashgaze.utils.image_io import encode_image_b64

# prompt 模板抽为模块级常量，便于多语言切换与外部审计。
# 占位符 {sharpness}/{exposure}/{max_adj} 由 _build_prompt 注入。
# JSON 字面量的花括号用 {{ }} 转义，避免被 str.format 误解析。
_PROMPT_TEMPLATES: dict[str, str] = {
    "zh": (
        "你是摄影评分助手。下面给出该图的客观指标："
        "清晰度={sharpness}/100，曝光度={exposure}/100。"
        "请判断图片中的'模糊'或'偏暗'是否为艺术手法"
        "（如背景虚化、逆光剪影、暗调氛围）。"
        "若是艺术手法，给正补偿；若是技术失误，给负补偿。"
        "补偿值范围 -{max_adj} 到 +{max_adj}。"
        "仅返回 JSON：{{\"adjustment\": 数字, \"reason\": \"一句话理由\"}}"
    ),
    "en": (
        "You are a photography scoring assistant. "
        "Objective metrics for this image: "
        "sharpness={sharpness}/100, exposure={exposure}/100. "
        "Judge whether 'blurriness' or 'darkness' in the image is an artistic technique "
        "(e.g., background bokeh, backlit silhouette, moody low-key). "
        "If it is an artistic technique, give positive compensation; "
        "if it is a technical flaw, give negative compensation. "
        "Compensation range: -{max_adj} to +{max_adj}. "
        "Return only JSON: {{\"adjustment\": number, \"reason\": \"one-sentence reason\"}}"
    ),
}


class VLMClient:
    """VLM 场景补偿客户端。"""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        timeout_sec: int = 30,
        max_retries: int = 3,
        max_adjustment: float = 10.0,
        vlm_lang: str = DEFAULT_VLM_LANG,
    ):
        if not api_key:
            raise ValueError("VLMClient 需要 api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.max_adjustment = max_adjustment
        # 非法语言静默回落到默认（zh），保证向后兼容
        self.vlm_lang = vlm_lang if vlm_lang in SUPPORTED_VLM_LANGS else DEFAULT_VLM_LANG

    def judge(self, img_path: str, cv_result: CVResult) -> VLMResult:
        """对单图判断模糊/偏暗是否为艺术手法，返回 ±max_adjustment 补偿。"""
        try:
            b64 = encode_image_b64(img_path)
        except Exception as e:
            return VLMResult(0.0, "图片编码失败", ok=False, error=str(e))

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_prompt(cv_result)},
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
            return VLMResult(0.0, "API 调用失败", ok=False, error="retry_exhausted")
        return self._parse_response(data)

    def _build_prompt(self, cv: CVResult) -> str:
        """根据 self.vlm_lang 选择中英文模板并注入 CV 指标。"""
        template = _PROMPT_TEMPLATES.get(self.vlm_lang, _PROMPT_TEMPLATES[DEFAULT_VLM_LANG])
        return template.format(
            sharpness=cv.sharpness,
            exposure=cv.exposure,
            max_adj=self.max_adjustment,
        )

    def _post_with_retry(self, payload: dict) -> dict | None:
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
        """解析 VLM 返回的 JSON。容错：超范围 clamp，解析失败返回 0 补偿。"""
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            adj = float(parsed["adjustment"])
            adj = max(-self.max_adjustment, min(self.max_adjustment, adj))
            return VLMResult(round(adj, 2), parsed.get("reason", ""), ok=True)
        except (KeyError, json.JSONDecodeError, ValueError, TypeError) as e:
            return VLMResult(0.0, "解析失败", ok=False, error=str(e))

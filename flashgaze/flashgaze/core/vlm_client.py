"""VLMClient：VLM 场景补偿客户端。

封装 Qwen-VL / GPT-4o-mini 等 OpenAI 兼容 API，仅作 ±max_adjustment 的微调。
含指数退避重试、超时控制、JSON 解析容错。
"""

from __future__ import annotations

import json
import time
from typing import Optional

import requests

from flashgaze.models.schemas import CVResult, VLMResult
from flashgaze.utils.image_io import encode_image_b64


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
    ):
        if not api_key:
            raise ValueError("VLMClient 需要 api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.max_adjustment = max_adjustment

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
        return (
            "你是摄影评分助手。下面给出该图的客观指标："
            f"清晰度={cv.sharpness}/100，曝光度={cv.exposure}/100。"
            "请判断图片中的'模糊'或'偏暗'是否为艺术手法（如背景虚化、逆光剪影、暗调氛围）。"
            "若是艺术手法，给正补偿；若是技术失误，给负补偿。"
            f"补偿值范围 -{self.max_adjustment} 到 +{self.max_adjustment}。"
            "仅返回 JSON：{\"adjustment\": 数字, \"reason\": \"一句话理由\"}"
        )

    def _post_with_retry(self, payload: dict) -> Optional[dict]:
        """POST 请求，仅对超时/连接错误重试。4xx/5xx 不重试（不可恢复）。"""
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
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)  # 1s, 2s（max_retries=3 时）
            except requests.HTTPError:
                return None
        return None

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

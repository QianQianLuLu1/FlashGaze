"""VLMClient 测试。

全部用 monkeypatch mock requests.post，不发起真实网络请求。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from flashgaze.core.vlm_client import VLMClient
from flashgaze.models.schemas import CVResult


def _make_cv() -> CVResult:
    return CVResult(sharpness=80.0, exposure=70.0, composition=None)


def _ok_response(adjustment: float, reason: str = "ok") -> MagicMock:
    """构造一个成功的 HTTP 响应 mock。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"adjustment": adjustment, "reason": reason})
                }
            }
        ]
    }
    return resp


def _rate_limit_response(retry_after: str = "2") -> MagicMock:
    """构造 429 限流响应。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 429
    resp.headers = {"Retry-After": retry_after}
    return resp


# ---------- 构造与校验 ----------

def test_init_requires_api_key():
    with pytest.raises(ValueError):
        VLMClient(api_key="", api_base="http://x", model="m")


def test_init_strips_trailing_slash():
    client = VLMClient(api_key="k", api_base="http://x/", model="m")
    assert client.api_base == "http://x"


# ---------- 正常调用 ----------

def test_judge_parses_valid_response(sharp_img: str, monkeypatch):
    """正常 JSON 响应解析为 VLMResult，adjustment 原样返回。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(5.0, "背景虚化"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 5.0
    assert result.reason == "背景虚化"


def test_judge_clamps_over_range_adjustment(sharp_img: str, monkeypatch):
    """adjustment 超出 ±max 应被 clamp。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(50.0),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_adjustment=10.0)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 10.0  # clamp 到上限


def test_judge_clamps_negative_over_range(sharp_img: str, monkeypatch):
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(-30.0),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.adjustment == -10.0


# ---------- 重试逻辑 ----------

def test_retry_on_timeout_then_success(sharp_img: str, monkeypatch):
    """超时后重试成功：前两次 Timeout，第三次成功。"""
    calls = {"n": 0}

    def fake_post(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.Timeout("simulated")
        return _ok_response(2.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 2.0
    assert calls["n"] == 3


def test_retry_exhausted_returns_failure(sharp_img: str, monkeypatch):
    """重试耗尽返回 ok=False。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("nope")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0
    assert result.error == "retry_exhausted"


def test_http_error_does_not_retry(sharp_img: str, monkeypatch):
    """4xx/5xx 不重试，直接返回失败。"""
    calls = {"n": 0}

    def fake_post(*a, **kw):
        calls["n"] += 1
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.headers = {}
        resp.raise_for_status.side_effect = requests.HTTPError("401")
        return resp

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert calls["n"] == 1  # 未重试


def test_429_rate_limit_retries_then_success(sharp_img: str, monkeypatch):
    """429 限流后重试成功：第一次 429，第二次成功。"""
    calls = {"n": 0}

    def fake_post(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _rate_limit_response("1")
        return _ok_response(3.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 3.0
    assert calls["n"] == 2


def test_429_rate_limit_exhausted(sharp_img: str, monkeypatch):
    """429 限流重试耗尽返回失败。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _rate_limit_response("1"),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=2)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"


# ---------- 解析容错 ----------

def test_parse_non_json_content(sharp_img: str, monkeypatch):
    """VLM 返回非 JSON 文本时容错。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": "这不是JSON"}}]
    }
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0


def test_parse_missing_choices(sharp_img: str, monkeypatch):
    """响应结构异常时容错。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"error": "internal"}
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False


# ---------- 图片编码失败 ----------

def test_judge_handles_corrupted_image(corrupted_img: str, monkeypatch):
    """损坏图编码失败时返回 ok=False，不调用 API。"""
    called = {"post": False}

    def fake_post(*a, **kw):
        called["post"] = True
        return _ok_response(1.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(corrupted_img, _make_cv())
    assert result.ok is False
    assert called["post"] is False  # 编码失败前不应发起请求


# ---------- VLM 扩展（M1-M6）----------

def test_init_defaults_provider_and_scene():
    """未传 provider/scene 时使用默认值 qwen / auto。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    assert client.provider == "qwen"
    assert client.scene == "auto"


def test_init_accepts_provider_and_scene():
    """构造时显式传入 provider/scene 被记录。"""
    client = VLMClient(
        api_key="k", api_base="http://x", model="m",
        provider="openai", scene="portrait",
    )
    assert client.provider == "openai"
    assert client.scene == "portrait"


def test_judge_success_fills_provider_and_scene(sharp_img: str, monkeypatch):
    """成功调用时 VLMResult 包含 provider/scene 字段。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(5.0, "ok"),
    )
    client = VLMClient(
        api_key="k", api_base="http://x", model="m",
        provider="qwen", scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.provider == "qwen"
    assert result.scene == "portrait"


def test_judge_failure_fills_provider_and_scene(sharp_img: str, monkeypatch):
    """失败调用时 VLMResult 仍带 provider/scene，便于日志追踪。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("nope")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(
        api_key="k", api_base="http://x", model="m",
        provider="qwen", scene="landscape",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.provider == "qwen"
    assert result.scene == "landscape"


# ---------- 理由 20 字截断 ----------

def test_parse_truncates_long_reason(sharp_img: str, monkeypatch):
    """VLM 返回超长理由时被截断到 20 字。"""
    long_reason = "这是一个非常非常非常非常非常非常非常非常非常长的理由语句超过二十字"
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(2.0, long_reason),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert len(result.reason) <= 20
    # 截断后是前 20 个字符
    assert result.reason == long_reason[:20]


def test_parse_keeps_short_reason(sharp_img: str, monkeypatch):
    """短理由原样保留。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(2.0, "背景虚化"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.reason == "背景虚化"


# ---------- 场景化提示词 ----------

def test_build_prompt_auto_contains_self_judge_keyword():
    """auto 场景提示词要求 VLM 自行判断场景。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="auto")
    prompt = client._build_prompt(_make_cv(), "auto")
    assert "自行判断" in prompt


def test_build_prompt_portrait_contains_keyword():
    """portrait 场景提示词包含'人像'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="portrait")
    prompt = client._build_prompt(_make_cv(), "portrait")
    assert "人像" in prompt


def test_build_prompt_landscape_contains_keyword():
    """landscape 场景提示词包含'风光'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="landscape")
    prompt = client._build_prompt(_make_cv(), "landscape")
    assert "风光" in prompt


def test_build_prompt_still_life_contains_keyword():
    """still_life 场景提示词包含'静物'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="still_life")
    prompt = client._build_prompt(_make_cv(), "still_life")
    assert "静物" in prompt


def test_build_prompt_unknown_scene_falls_back_to_auto():
    """非法 scene 回退到 auto 提示词（防御性）。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    prompt = client._build_prompt(_make_cv(), "unknown_scene")
    assert "自行判断" in prompt


def test_build_prompt_includes_reason_length_constraint():
    """提示词要求理由不超过 20 个汉字。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    prompt = client._build_prompt(_make_cv(), "auto")
    assert "20" in prompt


# ---------- provider 路由 ----------

def test_qwen_provider_uses_requests_not_litellm(sharp_img: str, monkeypatch):
    """provider=qwen 时走 requests.post，不调用 litellm.completion。"""
    called = {"requests": False, "litellm": False}

    def fake_post(*a, **kw):
        called["requests"] = True
        return _ok_response(1.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)

    # 即使 litellm 可用，qwen 仍走 requests 路径
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )

    def fake_litellm_completion(**kw):
        called["litellm"] = True
        return {"choices": [{"message": {"content": '{"adjustment": 1.0}'}}]}

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)

    client = VLMClient(api_key="k", api_base="http://x", model="m", provider="qwen")
    client.judge(sharp_img, _make_cv())
    assert called["requests"] is True
    assert called["litellm"] is False


def test_non_qwen_provider_without_litellm_falls_back(sharp_img: str, monkeypatch):
    """provider=openai 且未安装 litellm 时直接降级，不抛异常。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", False, raising=False
    )
    # requests.post 不应被调用
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: pytest.fail("requests.post 不应被调用"),
    )
    client = VLMClient(
        api_key="k", api_base="http://x", model="m",
        provider="openai", scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "litellm_not_installed"
    assert result.provider == "openai"
    assert result.scene == "portrait"


def test_unsupported_provider_falls_back(sharp_img: str, monkeypatch):
    """不支持的 provider 直接返回 ok=False，不调用任何 API。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: pytest.fail("requests.post 不应被调用"),
    )
    # 构造时绕过校验（直接设置 self.provider）
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    client.provider = "unsupported_xyz"
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "unsupported_provider"


# ---------- LiteLLM 路径（mock litellm.completion）----------

def _litellm_response(adjustment: float, reason: str = "ok"):
    """构造一个 mock litellm ModelResponse dict（OpenAI 兼容格式）。"""
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"adjustment": adjustment, "reason": reason})
                }
            }
        ]
    }


def test_litellm_openai_provider_calls_litellm_completion(sharp_img: str, monkeypatch):
    """provider=openai 且 litellm 可用时，调用 litellm.completion 而非 requests.post。"""
    called = {"litellm": False, "requests": False}

    def fake_litellm_completion(**kw):
        called["litellm"] = True
        # 验证 LiteLLM 收到的 model 前缀
        assert kw["model"] == "openai/gpt-4o"
        return _litellm_response(3.0, "曝光准确")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: pytest.fail("requests.post 不应被调用"),
    )

    client = VLMClient(
        api_key="k", api_base="https://api.openai.com/v1",
        model="gpt-4o", provider="openai", scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert called["litellm"] is True
    assert called["requests"] is False
    assert result.ok is True
    assert result.adjustment == 3.0
    assert result.reason == "曝光准确"
    assert result.provider == "openai"
    assert result.scene == "portrait"


def test_litellm_anthropic_provider_route(sharp_img: str, monkeypatch):
    """provider=anthropic 时 LiteLLM 收到 anthropic/ 前缀。"""
    captured = {}

    def fake_litellm_completion(**kw):
        captured["model"] = kw["model"]
        return _litellm_response(-2.0, "逆光剪影")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )

    client = VLMClient(
        api_key="sk-ant-xxx", api_base="",  # 留空走 LiteLLM 默认端点
        model="claude-3-5-sonnet-20241022",
        provider="anthropic", scene="still_life",
    )
    result = client.judge(sharp_img, _make_cv())
    assert captured["model"] == "anthropic/claude-3-5-sonnet-20241022"
    assert result.ok is True
    assert result.adjustment == -2.0
    assert result.provider == "anthropic"


def test_litellm_ollama_provider_route(sharp_img: str, monkeypatch):
    """provider=ollama 时 LiteLLM 收到 ollama/ 前缀。"""
    captured = {}

    def fake_litellm_completion(**kw):
        captured["model"] = kw["model"]
        captured["api_base"] = kw.get("api_base")
        return _litellm_response(0.0, "无明显艺术手法")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )

    client = VLMClient(
        api_key="ollama", api_base="http://localhost:11434",
        model="llama3.2-vision", provider="ollama",
    )
    result = client.judge(sharp_img, _make_cv())
    assert captured["model"] == "ollama/llama3.2-vision"
    assert captured["api_base"] == "http://localhost:11434"
    assert result.ok is True
    assert result.provider == "ollama"


def test_litellm_exception_falls_back(sharp_img: str, monkeypatch):
    """LiteLLM 抛任意异常时返回 ok=False，不向上传播。"""
    fake_litellm = MagicMock()
    fake_litellm.completion.side_effect = RuntimeError("network error")
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(
        api_key="k", api_base="http://x", model="gpt-4o",
        provider="openai", max_retries=2,
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"
    assert result.adjustment == 0.0


def test_litellm_timeout_then_success(sharp_img: str, monkeypatch):
    """LiteLLM 第一次抛超时，第二次成功：重试机制生效。"""
    calls = {"n": 0}

    def fake_litellm_completion(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated timeout")
        return _litellm_response(4.0, "重试成功")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(
        api_key="k", api_base="http://x", model="gpt-4o",
        provider="openai", max_retries=3,
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 4.0
    assert calls["n"] == 2


# ---------- 回归：原有 requests 路径在新结构下仍可用 ----------

def test_qwen_provider_regression_existing_behavior(sharp_img: str, monkeypatch):
    """provider=qwen 走 requests.post，所有原有行为保持不变（回归测试）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.post",
        lambda *a, **kw: _ok_response(7.0, "构图佳"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 7.0
    assert result.reason == "构图佳"
    assert result.provider == "qwen"
    assert result.scene == "auto"

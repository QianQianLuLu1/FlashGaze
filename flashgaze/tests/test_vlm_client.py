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
        resp.raise_for_status.side_effect = requests.HTTPError("401")
        return resp

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert calls["n"] == 1  # 未重试


# ---------- 解析容错 ----------

def test_parse_non_json_content(sharp_img: str, monkeypatch):
    """VLM 返回非 JSON 文本时容错。"""
    resp = MagicMock(spec=requests.Response)
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

"""VLMClient 测试。

全部用 monkeypatch mock requests.post，不发起真实网络请求。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from requests.utils import select_proxy

from flashgaze.core.vlm_client import (
    VLMClient,
    _loads_lenient,
    _PinnedIPAdapter,
    _resolve_pinned_target,
    _strip_fences,
)
from flashgaze.models.schemas import CVResult
from flashgaze.utils.image_io import encode_image_b64


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
            {"message": {"content": json.dumps({"adjustment": adjustment, "reason": reason})}}
        ]
    }
    return resp


def _raw_content_response(content: str) -> MagicMock:
    """构造 message.content 为任意原始文本的成功响应 mock。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _rate_limit_response(retry_after: str = "2") -> MagicMock:
    """构造 429 限流响应。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 429
    resp.headers = {"Retry-After": retry_after}
    return resp


def _server_error_response(code: int = 503) -> MagicMock:
    """构造 5xx 服务端错误响应（502/503/504 等瞬时错误，应有限重试）。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = code
    resp.headers = {}
    resp.raise_for_status.side_effect = requests.HTTPError(str(code))
    return resp


# ---------- 构造与校验 ----------


def test_init_requires_api_key() -> None:
    with pytest.raises(ValueError):
        VLMClient(api_key="", api_base="http://x", model="m")


def test_init_strips_trailing_slash() -> None:
    client = VLMClient(api_key="k", api_base="http://x/", model="m")
    assert client.api_base == "http://x"


# ---------- 正常调用 ----------


def test_judge_parses_valid_response(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """正常 JSON 响应解析为 VLMResult，adjustment 原样返回。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(5.0, "背景虚化"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 5.0
    assert result.reason == "背景虚化"


def test_judge_clamps_over_range_adjustment(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adjustment 超出 ±max 应被 clamp。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(50.0),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_adjustment=10.0)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 10.0  # clamp 到上限


def test_judge_clamps_negative_over_range(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(-30.0),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.adjustment == -10.0


# ---------- 重试逻辑 ----------


def test_retry_on_timeout_then_success(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """超时后重试成功：前两次 Timeout，第三次成功。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.Timeout("simulated")
        return _ok_response(2.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 2.0
    assert calls["n"] == 3


def test_retry_exhausted_returns_failure(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """重试耗尽返回 ok=False。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("nope")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0
    assert result.error == "retry_exhausted"


def test_http_error_does_not_retry(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """4xx/5xx 不重试，直接返回失败。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.headers = {}
        resp.raise_for_status.side_effect = requests.HTTPError("401")
        return resp

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert calls["n"] == 1  # 未重试


def test_429_rate_limit_retries_then_success(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 限流后重试成功：第一次 429，第二次成功。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return _rate_limit_response("1")
        return _ok_response(3.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 3.0
    assert calls["n"] == 2


def test_429_rate_limit_exhausted(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """429 限流重试耗尽返回失败。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _rate_limit_response("1"),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=2)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"


def _retry_after_response(retry_after: str | None) -> MagicMock:
    """构造带任意 Retry-After 头的响应（用于 _parse_retry_after 单测）。"""
    resp = MagicMock(spec=requests.Response)
    resp.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return resp


def test_parse_retry_after_huge_integer_clamped() -> None:
    """整数秒分支必须钳制 60s 上限，防止超大值造成 worker 长时间阻塞（可用性 DoS）。"""
    val = VLMClient._parse_retry_after(_retry_after_response("1000000000"))
    assert val == 60.0


def test_parse_retry_after_normal_integer_passthrough() -> None:
    """正常整数秒（<=60）应保持原值。"""
    assert VLMClient._parse_retry_after(_retry_after_response("5")) == 5.0
    assert VLMClient._parse_retry_after(_retry_after_response("60")) == 60.0


def test_parse_retry_after_boundary_61_clamped() -> None:
    """略超 60 的整数秒应被钳制到 60。"""
    assert VLMClient._parse_retry_after(_retry_after_response("61")) == 60.0


def test_parse_retry_after_http_date_branch_unchanged() -> None:
    """日期分支行为不变（已 min(diff, 60.0)），且不超 60。"""
    # 未来 120s 的 HTTP 日期应被钳制到 60.0
    future = datetime.now(timezone.utc).timestamp() + 120
    from email.utils import formatdate

    dt_header = formatdate(timeval=future, usegmt=True)
    assert VLMClient._parse_retry_after(_retry_after_response(dt_header)) == 60.0


def test_parse_retry_after_missing_defaults_to_1() -> None:
    """缺省 Retry-After 回退 1.0。"""
    assert VLMClient._parse_retry_after(_retry_after_response(None)) == 1.0


def test_4xx_does_not_retry(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """4xx（非 429）客户端错误不重试，立即降级（如鉴权失败重试无效）。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        return _client_error_response(401)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert calls["n"] == 1  # 未重试


def test_5xx_retries_then_success(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """瞬时 5xx（503）有限重试：前两次 503，第三次 200 成功。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] < 3:
            return _server_error_response(503)
        return _ok_response(4.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 4.0
    assert calls["n"] == 3


def test_5xx_retry_exhausted(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx 重试耗尽返回失败（网关持续不可用）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _server_error_response(502),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"


def _client_error_response(code: int = 401) -> MagicMock:
    """构造 4xx 客户端错误响应（非 429，应立即降级）。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = code
    resp.headers = {}
    resp.raise_for_status.side_effect = requests.HTTPError(str(code))
    return resp


# ---------- 解析容错 ----------


def test_parse_non_json_content(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """VLM 返回非 JSON 文本时容错。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": "这不是JSON"}}]}
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0


def test_parse_json_wrapped_in_code_fence(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """```json 围栏包裹的 JSON 必须能解析——这是场景补偿失效的根因。"""
    content = '```json\n{"quality":80,"adjustment":5,"reason":"清晰"}\n```'
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(content),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 5.0
    assert result.reason == "清晰"


def test_parse_bare_code_fence_without_language(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无语言标记的 ``` 围栏同样要能解析。"""
    content = '```\n{"adjustment": -3, "reason": "过曝"}\n```'
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(content),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == -3.0


def test_parse_json_with_trailing_comma(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """尾逗号（模型高频笔误）不应导致解析失败。"""
    content = '{"adjustment": 4, "reason": "暗调氛围",}'
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(content),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 4.0
    assert result.reason == "暗调氛围"


def test_parse_fenced_json_with_trailing_comma(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """围栏 + 尾逗号组合（真实模型输出最常见形态）。"""
    content = '```json\n{\n  "adjustment": 6,\n  "reason": "背景虚化",\n}\n```'
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(content),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 6.0
    assert result.reason == "背景虚化"


def test_parse_garbage_degrades_safely(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 JSON 内容安全降级：adjustment=0、ok=False，且不向上抛异常。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response("抱歉，我无法判断这张图片。"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())  # 不抛异常即为通过
    assert result.ok is False
    assert result.adjustment == 0.0


def test_parse_none_content_degrades_safely(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """content 为 None（部分网关的异常返回）时也不能崩。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(None),  # type: ignore[arg-type]
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('```json\n{"a":1}\n```', '{"a":1}'),
        ('```\n{"a":1}\n```', '{"a":1}'),
        ('  ```json\n{"a":1}\n```  ', '{"a":1}'),
        ('```{"a":1}```', '{"a":1}'),
        ('{"a":1}', '{"a":1}'),  # 无围栏原样返回
    ],
)
def test_strip_fences_variants(raw: str, expected: str) -> None:
    """_strip_fences 覆盖常见围栏写法。"""
    assert _strip_fences(raw) == expected


def test_parse_missing_choices(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """响应结构异常时容错。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"error": "internal"}
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False


# ---------- 图片编码失败 ----------


def test_judge_handles_corrupted_image(corrupted_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """损坏图编码失败时返回 ok=False，不调用 API。"""
    called = {"post": False}

    def fake_post(*a: Any, **kw: Any) -> Any:
        called["post"] = True
        return _ok_response(1.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(corrupted_img, _make_cv())
    assert result.ok is False
    assert called["post"] is False  # 编码失败前不应发起请求


# ---------- VLM 扩展（M1-M6）----------


def test_init_defaults_provider_and_scene() -> None:
    """未传 provider/scene 时使用默认值 qwen / auto。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    assert client.provider == "qwen"
    assert client.scene == "auto"


def test_init_accepts_provider_and_scene() -> None:
    """构造时显式传入 provider/scene 被记录。"""
    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="m",
        provider="openai",
        scene="portrait",
    )
    assert client.provider == "openai"
    assert client.scene == "portrait"


def test_judge_success_fills_provider_and_scene(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功调用时 VLMResult 包含 provider/scene 字段。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(5.0, "ok"),
    )
    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="m",
        provider="qwen",
        scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.provider == "qwen"
    assert result.scene == "portrait"


def test_judge_failure_fills_provider_and_scene(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败调用时 VLMResult 仍带 provider/scene，便于日志追踪。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("nope")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="m",
        provider="qwen",
        scene="landscape",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.provider == "qwen"
    assert result.scene == "landscape"


# ---------- 理由 20 字截断 ----------


def test_parse_truncates_long_reason(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """VLM 返回超长理由时被截断到 20 字。"""
    long_reason = "这是一个非常非常非常非常非常非常非常非常非常长的理由语句超过二十字"
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(2.0, long_reason),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert len(result.reason) <= 20
    # 截断后是前 20 个字符
    assert result.reason == long_reason[:20]


# ---------- pin-IP 多候选 / 重解析（#5-3 续：长时可靠性）----------


def _fake_getaddrinfo(ips: list[str]) -> Any:
    """构造 socket.getaddrinfo 的固定返回（IPv4 元组列表）。"""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


def test_resolve_returns_all_public_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """多 A 记录：返回全部公网候选 IP，而非只取一个。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1", "2.2.2.2"]),
    )
    cands = _resolve_pinned_target("http://example.com")
    assert cands is not None
    assert {c.connect_host for c in cands} == {"1.1.1.1", "2.2.2.2"}


def test_resolve_rejects_restricted_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一解析 IP 为私网/受限地址时抛 ValueError（安全校验不退化）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["10.0.0.1"]),
    )
    with pytest.raises(ValueError):
        _resolve_pinned_target("http://example.com")


def test_resolve_rejects_metadata_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """链路本地（云元数据 169.254.169.254）同样被拒绝。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["169.254.169.254"]),
    )
    with pytest.raises(ValueError):
        _resolve_pinned_target("http://example.com")


def test_resolve_loopback_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """全回环（localhost/Ollama）回退为回环候选，不报错。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["127.0.0.1"]),
    )
    cands = _resolve_pinned_target("http://localhost")
    assert cands is not None
    assert cands[0].connect_host == "127.0.0.1"


def test_resolve_private_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """私网 IP（192.168.x）默认仍按 SSRF 拒绝（保护 qwen/openai/anthropic 公网 API）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["192.168.1.10"]),
    )
    with pytest.raises(ValueError):
        _resolve_pinned_target("http://192.168.1.10:11434")


def test_resolve_private_allowed_when_allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_private=True 时私网 IP（192.168.x）被放行并收集进候选池（仍 pin-IP）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["192.168.1.10"]),
    )
    cands = _resolve_pinned_target("http://192.168.1.10:11434", allow_private=True)
    assert cands is not None
    assert cands[0].connect_host == "192.168.1.10"


def test_resolve_link_local_allowed_when_allow_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_private=True 时链路本地（169.254.x，含 docker 网关）被放行。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["169.254.169.254"]),
    )
    cands = _resolve_pinned_target("http://metadata.internal", allow_private=True)
    assert cands is not None
    assert cands[0].connect_host == "169.254.169.254"


def test_ollama_private_target_allowed_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ollama provider 默认放行局域网 Ollama（192.168.x），构造不抛、候选含该 IP。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["192.168.1.10"]),
    )
    client = VLMClient(
        api_key="k", api_base="http://192.168.1.10:11434", model="m", provider="ollama"
    )
    assert client._allow_private is True
    assert any(c.connect_host == "192.168.1.10" for c in client._candidates)


def test_qwen_private_target_rejected_unless_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """qwen provider 私网仍拒绝；仅显式 allow_private_targets=True 才放行。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["10.0.0.1"]),
    )
    with pytest.raises(ValueError):
        VLMClient(api_key="k", api_base="http://10.0.0.1", model="m", provider="qwen")
    client = VLMClient(
        api_key="k",
        api_base="http://10.0.0.1",
        model="m",
        provider="qwen",
        allow_private_targets=True,
    )
    assert client._allow_private is True
    assert any(c.connect_host == "10.0.0.1" for c in client._candidates)


def test_candidate_rotation_on_connection_error(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首个候选 IP 连接失败时轮换到下一个候选并成功（单次调用内恢复）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1", "2.2.2.2"]),
    )
    seen: list[str] = []

    def fake_post(*a: Any, **kw: Any) -> Any:
        # requests.Session.post(self, url, ...) 的 url 为位置参数 a[1]，非关键字参数
        url = a[1]
        seen.append(url)
        if "1.1.1.1" in url:
            raise requests.ConnectionError("down")
        return _ok_response(7.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert len(seen) == 2
    assert "1.1.1.1" in seen[0]
    assert "2.2.2.2" in seen[1]
    # 跨调用轮询：下一次 judge 从轮换后的指针（2.2.2.2）起始
    seen.clear()
    r2 = client.judge(sharp_img, _make_cv())
    assert r2.ok is True
    assert "2.2.2.2" in seen[0]


def test_reresolve_on_conn_error_threshold_then_recovers(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连续 ConnectionError 达阈值触发重解析，取到新健康 IP 后下一次调用成功。"""
    state = {"ga_calls": 0}

    def fake_getaddrinfo(*a: Any, **kw: Any) -> Any:
        state["ga_calls"] += 1
        # 首次解析给已宕机 IP；重解析给健康 IP（模拟 CDN 轮换/单点恢复）
        if state["ga_calls"] == 1:
            return _fake_getaddrinfo(["1.1.1.1"])
        return _fake_getaddrinfo(["2.2.2.2"])

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=3)
    r1 = client.judge(sharp_img, _make_cv())
    assert r1.ok is False
    # 连续失败达默认阈值（=max_retries）后触发了重解析
    assert state["ga_calls"] >= 2
    assert client._candidates[0].connect_host == "2.2.2.2"

    # 重解析后候选已是健康 IP，下一次 judge 应成功
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(4.0, "背景虚化"),
    )
    r2 = client.judge(sharp_img, _make_cv())
    assert r2.ok is True
    assert "2.2.2.2" in client._candidates[0].connect_host


def test_reresolve_keeps_old_pool_when_restricted(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重解析若只解析到受限地址（DNS 重绑定攻击），应拒绝并保留旧候选池，不回退主机名。"""
    state = {"ga_calls": 0}

    def fake_getaddrinfo(*a: Any, **kw: Any) -> Any:
        state["ga_calls"] += 1
        # 首次：公网 IP；重解析：攻击者将解析指向内网（受限）
        if state["ga_calls"] == 1:
            return _fake_getaddrinfo(["1.1.1.1"])
        return _fake_getaddrinfo(["10.0.0.5"])

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=3)
    r = client.judge(sharp_img, _make_cv())
    assert r.ok is False
    # 重解析被安全校验拒绝，候选池保持原公网 IP，未被替换为内网地址
    assert client._candidates[0].connect_host == "1.1.1.1"


# ---------- 候选池为空（构造期不可解析主机）回退路径重绑定防护（P1）----------


def test_fallback_lazy_resolve_pins_ip_at_request_time(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候选池为空（构造期不可解析）时，请求期惰性解析命中公网 IP 应走 pin-IP 直连
    （URL 含解析 IP、Host 头=原主机），而非裸交给 requests 在请求期重新解析。

    覆盖 fast-flux / 延迟上线的内网服务场景：构造期 gaierror（不可解析），
    请求期主机上线解析到公网 IP——此处必须仍 pin 该 IP 直连，否则重绑定 TOCTOU 绕过面重生。
    """
    state = {"calls": 0}

    def fake_getaddrinfo(*a: Any, **kw: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 1:
            # 构造期：不可解析（模拟延迟上线的内网/fast-flux）
            raise socket.gaierror("temporary failure in name resolution")
        # 请求期：主机上线，解析到公网 IP
        return _fake_getaddrinfo(["1.2.3.4"])

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_post(*a: Any, **kw: Any) -> Any:
        url = a[1]
        seen.append((url, kw.get("headers", {})))
        return _ok_response(6.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    # 构造期 getaddrinfo 抛 gaierror → 候选池为空（占位）
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    assert client._candidates == []
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    # 请求期惰性解析出的 IP 被 pin 进 URL，且 Host 头保留原主机名
    assert len(seen) == 1
    url, headers = seen[0]
    assert "1.2.3.4" in url
    assert headers.get("Host") == "x"
    # 候选池已被填充并持久化（后续调用复用轮询）
    assert client._candidates
    assert client._candidates[0].connect_host == "1.2.3.4"


def test_fallback_lazy_resolve_rejects_restricted_at_request_time(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候选池为空时，请求期惰性解析若命中受限地址（DNS 重绑定攻击），应安全降级、
    绝不发起裸请求。

    回归点：旧实现在 target is None 时直接 requests.post(api_base)，会先校验再在
    请求时刻裸解析——这里要求请求期惰性解析的受限校验同样生效，无请求外泄。
    """
    state = {"calls": 0}

    def fake_getaddrinfo(*a: Any, **kw: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 1:
            raise socket.gaierror("temporary failure")
        # 攻击者将解析指向内网（受限）
        return _fake_getaddrinfo(["10.0.0.1"])

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)
    posted: list[Any] = []

    def fake_post(*a: Any, **kw: Any) -> Any:
        posted.append(a[1])
        return _ok_response(6.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False  # 安全降级
    assert posted == []  # 受限地址绝不裸请求


def test_placeholder_host_fallback_url_unchanged(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """始终不可解析的占位主机（http://x）仍回退主机名 URL、无 Host 头（兼容契约）。

    验证修复未破坏原有占位主机的回退行为：惰性解析仍不可解析时保留旧逻辑。
    """
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_post(*a: Any, **kw: Any) -> Any:
        url = a[1]
        seen.append((url, dict(kw.get("headers", {}))))
        return _ok_response(3.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert len(seen) == 1
    url, headers = seen[0]
    assert url == "http://x/chat/completions"
    assert "Host" not in headers


def test_parse_keeps_short_reason(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """短理由原样保留。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(2.0, "背景虚化"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.reason == "背景虚化"


# ---------- 场景化提示词 ----------


def test_build_prompt_auto_contains_self_judge_keyword() -> None:
    """auto 场景提示词要求 VLM 自行判断场景。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="auto")
    prompt = client._build_prompt(_make_cv(), "auto")
    assert "自行判断" in prompt


def test_build_prompt_portrait_contains_keyword() -> None:
    """portrait 场景提示词包含'人像'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="portrait")
    prompt = client._build_prompt(_make_cv(), "portrait")
    assert "人像" in prompt


def test_build_prompt_landscape_contains_keyword() -> None:
    """landscape 场景提示词包含'风光'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="landscape")
    prompt = client._build_prompt(_make_cv(), "landscape")
    assert "风光" in prompt


def test_build_prompt_still_life_contains_keyword() -> None:
    """still_life 场景提示词包含'静物'关键词。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", scene="still_life")
    prompt = client._build_prompt(_make_cv(), "still_life")
    assert "静物" in prompt


def test_build_prompt_unknown_scene_falls_back_to_auto() -> None:
    """非法 scene 回退到 auto 提示词（防御性）。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    prompt = client._build_prompt(_make_cv(), "unknown_scene")
    assert "自行判断" in prompt


def test_build_prompt_includes_reason_length_constraint() -> None:
    """提示词要求理由不超过 20 个汉字。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    prompt = client._build_prompt(_make_cv(), "auto")
    assert "20" in prompt


# ---------- provider 路由 ----------


def test_qwen_provider_uses_requests_not_litellm(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=qwen 时走 requests.post，不调用 litellm.completion。"""
    called = {"requests": False, "litellm": False}

    def fake_post(*a: Any, **kw: Any) -> Any:
        called["requests"] = True
        return _ok_response(1.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)

    # 即使 litellm 可用，qwen 仍走 requests 路径
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)

    def fake_litellm_completion(**kw: Any) -> Any:
        called["litellm"] = True
        return {"choices": [{"message": {"content": '{"adjustment": 1.0}'}}]}

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)

    client = VLMClient(api_key="k", api_base="http://x", model="m", provider="qwen")
    client.judge(sharp_img, _make_cv())
    assert called["requests"] is True
    assert called["litellm"] is False


def test_non_qwen_provider_without_litellm_uses_pinned_path(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=openai 且未安装 litellm 时，默认走自建 pin-IP 直连层（不再硬依赖 litellm）。"""
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", False, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(2.0, "曝光准确"),
    )
    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="m",
        provider="openai",
        scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 2.0
    assert result.provider == "openai"
    assert result.scene == "portrait"


def test_unsupported_provider_falls_back(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """不支持的 provider 直接返回 ok=False，不调用任何 API。"""
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: pytest.fail("requests.post 不应被调用"),
    )
    # 构造时绕过校验（直接设置 self.provider）
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    client.provider = "unsupported_xyz"
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "unsupported_provider"


# ---------- 非 qwen provider 也走 pin-IP 直连（消除重绑定绕过面）----------


def _anthropic_ok_response(adjustment: float, reason: str = "ok") -> Any:
    """构造一个 mock Anthropic /v1/messages 响应（content block 列表）。"""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [
            {"type": "text", "text": json.dumps({"adjustment": adjustment, "reason": reason})}
        ]
    }
    resp.raise_for_status = lambda: None
    resp.close = lambda: None
    return resp


def test_openai_provider_pinned_direct(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=openai 默认走 pin-IP 直连：URL 直连 pin 的 IP、Host 头保留原主机名、禁重定向。"""
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["url"] = a[1] if len(a) > 1 else kw.get("url")
        captured["host"] = kw.get("headers", {}).get("Host")
        captured["redirects"] = kw.get("allow_redirects")
        captured["auth"] = kw.get("headers", {}).get("Authorization")
        return _ok_response(1.5, "曝光准确")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(
        api_key="k",
        api_base="https://api.openai.com/v1",
        model="gpt-4o",
        provider="openai",
        scene="portrait",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 1.5
    # 直连 pin 的 IP（api.openai.com 解析为公共 IP），而非请求期重新解析主机名
    assert "api.openai.com" not in (captured["url"] or "")
    assert captured["host"] == "api.openai.com"
    assert captured["redirects"] is False
    assert captured["auth"] == "Bearer k"


def test_ollama_provider_pinned_direct_path(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=ollama 默认走 OpenAI 兼容 /v1/chat/completions 直连（回环 127.0.0.1 pin）。"""
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["url"] = a[1] if len(a) > 1 else kw.get("url")
        return _ok_response(0.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(
        api_key="ollama",
        api_base="http://localhost:11434",
        model="llama3.2-vision",
        provider="ollama",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert captured["url"].endswith("/v1/chat/completions")


def test_anthropic_provider_pinned_endpoint_and_auth(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=anthropic 默认走 /v1/messages 直连，使用 x-api-key + anthropic-version 认证。"""
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["url"] = a[1] if len(a) > 1 else kw.get("url")
        captured["headers"] = kw.get("headers", {})
        return _anthropic_ok_response(-1.0, "逆光剪影")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(
        api_key="sk-ant-xxx",
        api_base="https://api.anthropic.com",
        model="claude-3-5-sonnet-20241022",
        provider="anthropic",
        scene="still_life",
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == -1.0
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"].get("x-api-key") == "sk-ant-xxx"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    # OpenAI 兼容的 Bearer 认证不应出现
    assert "Authorization" not in captured["headers"]


def test_non_qwen_rejects_restricted_ip_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """openai provider 构造期对私网/元数据地址同样拒绝（pin 对所有 provider 生效）。"""

    def fake_getaddrinfo(
        host: str, port: str | int | None, *a: Any, **kw: Any
    ) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        VLMClient(
            api_key="k",
            api_base="http://internal.example.com",
            model="m",
            provider="openai",
        )


def test_non_qwen_dns_rebinding_pinned_to_public_ip(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openai provider 在构造期 pin 公共 IP，请求期 DNS 被重绑到私网也不受影响。

    模拟攻击：构造期解析为公共 IP 并 pin；请求期若重新解析会命中 169.254.169.254
    （云元数据），但因已 pin，请求直连 pin 的公共 IP，绕过面被消除。
    """

    def fake_getaddrinfo(
        host: str, port: str | int | None, *a: Any, **kw: Any
    ) -> list[tuple[Any, ...]]:
        # 构造期（仅一次）返回公共 IP；仅作演示，不实际重绑
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    calls: dict[str, int] = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        url = a[1] if len(a) > 1 else kw.get("url")
        # 关键断言：URL 直连 pin 的公共 IP，而不是重新解析主机名
        assert "internal.example.com" not in (url or "")
        return _ok_response(0.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(
        api_key="k",
        api_base="http://internal.example.com",
        model="m",
        provider="openai",
    )
    assert client.judge(sharp_img, _make_cv()).ok is True
    # 仅在构造期解析一次，请求期不再解析（消除 TOCTOU）
    assert calls["n"] == 1


# ---------- LiteLLM 路径（mock litellm.completion，需显式 use_litellm=True）----------


def _litellm_response(adjustment: float, reason: str = "ok") -> dict[str, Any]:
    """构造一个 mock litellm ModelResponse dict（OpenAI 兼容格式）。"""
    return {
        "choices": [
            {"message": {"content": json.dumps({"adjustment": adjustment, "reason": reason})}}
        ]
    }


def test_litellm_openai_provider_calls_litellm_completion(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=openai 且显式 opt-in litellm 时，调用 litellm.completion 而非 requests.post。"""
    called = {"litellm": False, "requests": False}

    def fake_litellm_completion(**kw: Any) -> Any:
        called["litellm"] = True
        # 验证 LiteLLM 收到的 model 前缀
        assert kw["model"] == "openai/gpt-4o"
        return _litellm_response(3.0, "曝光准确")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: pytest.fail("requests.post 不应被调用"),
    )

    client = VLMClient(
        api_key="k",
        api_base="https://api.openai.com/v1",
        model="gpt-4o",
        provider="openai",
        scene="portrait",
        use_litellm=True,
    )
    result = client.judge(sharp_img, _make_cv())
    assert called["litellm"] is True
    assert called["requests"] is False
    assert result.ok is True
    assert result.adjustment == 3.0
    assert result.reason == "曝光准确"
    assert result.provider == "openai"
    assert result.scene == "portrait"


def test_litellm_anthropic_provider_route(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=anthropic 时 LiteLLM 收到 anthropic/ 前缀。"""
    captured = {}

    def fake_litellm_completion(**kw: Any) -> Any:
        captured["model"] = kw["model"]
        return _litellm_response(-2.0, "逆光剪影")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)

    client = VLMClient(
        api_key="sk-ant-xxx",
        api_base="",  # 留空走 LiteLLM 默认端点
        model="claude-3-5-sonnet-20241022",
        provider="anthropic",
        scene="still_life",
        use_litellm=True,
    )
    result = client.judge(sharp_img, _make_cv())
    assert captured["model"] == "anthropic/claude-3-5-sonnet-20241022"
    assert result.ok is True
    assert result.adjustment == -2.0
    assert result.provider == "anthropic"


def test_litellm_ollama_provider_route(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=ollama 时 LiteLLM 收到 ollama/ 前缀。"""
    captured = {}

    def fake_litellm_completion(**kw: Any) -> Any:
        captured["model"] = kw["model"]
        captured["api_base"] = kw.get("api_base")
        return _litellm_response(0.0, "无明显艺术手法")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)

    client = VLMClient(
        api_key="ollama",
        api_base="http://localhost:11434",
        model="llama3.2-vision",
        provider="ollama",
        use_litellm=True,
    )
    result = client.judge(sharp_img, _make_cv())
    assert captured["model"] == "ollama/llama3.2-vision"
    assert captured["api_base"] == "http://localhost:11434"
    assert result.ok is True
    assert result.provider == "ollama"


def test_litellm_exception_falls_back(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """LiteLLM 抛任意异常时返回 ok=False，不向上传播。"""
    fake_litellm = MagicMock()
    fake_litellm.completion.side_effect = RuntimeError("network error")
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="gpt-4o",
        provider="openai",
        max_retries=2,
        use_litellm=True,
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"
    assert result.adjustment == 0.0


def test_litellm_timeout_then_success(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """LiteLLM 第一次抛超时，第二次成功：重试机制生效。"""
    calls = {"n": 0}

    def fake_litellm_completion(**kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated timeout")
        return _litellm_response(4.0, "重试成功")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    client = VLMClient(
        api_key="k",
        api_base="http://x",
        model="gpt-4o",
        provider="openai",
        max_retries=3,
        use_litellm=True,
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 4.0
    assert calls["n"] == 2


# ---------- 回归：原有 requests 路径在新结构下仍可用 ----------


def test_qwen_provider_regression_existing_behavior(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=qwen 走 requests.post，所有原有行为保持不变（回归测试）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(7.0, "构图佳"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 7.0
    assert result.reason == "构图佳"
    assert result.provider == "qwen"
    assert result.scene == "auto"


# ─────────────────────────────────────────────────────────────────────────────
# P3 边界回归：VLM 围栏 / json5 尾逗号 / 非 JSON 容错
#
# 直接命中 _parse_response / _loads_lenient 解析层，不依赖网络 mock。
# 目的：防止后续改动（如改回裸 json.loads、误删 _strip_fences /
# _loads_lenient、或让 json5 回退路径失效）悄悄让场景补偿恒为 0 或让
# 尾逗号崩溃。judge() 层的集成测试见上方 test_parse_* 系列，这里再在
# 解析单元层钉死契约，形成双重防护。
# ─────────────────────────────────────────────────────────────────────────────


def test_p3_parse_fenced_json_adjustment_not_zero() -> None:
    """P3(a)：content 带 ```json 围栏时，parsed["adjustment"] 必须被正确解析，
    而不是因裸 json.loads 抛错被上层吞掉、导致场景补偿恒为 0。

    关键断言：adjustment == 7.5（非 0），证明围栏根因已修复。
    """
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    data = {
        "choices": [
            {"message": {"content": '```json\n{"adjustment": 7.5, "reason": "景深虚化"}\n```'}}
        ]
    }
    result = client._parse_response(data)
    assert result.ok is True
    assert result.adjustment == 7.5  # 关键：不再恒为 0
    assert result.reason == "景深虚化"
    assert result.error is None


def test_p3_parse_trailing_comma_via_json5() -> None:
    """P3(b)：content 含尾逗号时，借 json5 仍能解析（模型高频笔误）。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    data = {"choices": [{"message": {"content": '{"adjustment": 4, "reason": "暗调氛围",}'}}]}
    result = client._parse_response(data)
    assert result.ok is True
    assert result.adjustment == 4.0
    assert result.reason == "暗调氛围"


def test_p3_loads_lenient_trailing_comma() -> None:
    """P3(b) 单元级：_loads_lenient 直接吃尾逗号 JSON（json5 路径），
    证明尾逗号不是靠巧合解析成功。"""
    parsed = _loads_lenient('{"adjustment": 9, "reason": "逆光剪影",}')
    assert parsed["adjustment"] == 9
    assert parsed["reason"] == "逆光剪影"


def test_p3_parse_non_json_safe_degrade() -> None:
    """P3(c)：content 为非 JSON 文本时安全降级 —— adjustment=0、ok=False，
    且不得向上抛异常。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    data = {"choices": [{"message": {"content": "抱歉，我无法判断这张图片的内容。"}}]}
    result = client._parse_response(data)  # 不抛异常即为通过
    assert result.ok is False
    assert result.adjustment == 0.0
    assert result.error is not None


# ─────────────────────────────────────────────────────────────────────────────
# P4 边界回归：judge 接受预编码 base64（PLAN-vlm-decode-once）
#
# 阶段 1 子进程把整图 base64 带回，阶段 2 judge 直接复用，避免主进程重复读盘。
# 这三个用例钉死契约：(a) 传 pre_encoded_b64 时原样进请求体且不调 encode_image_b64；
# (b) 不传时回退原路径；(c) 预编码路径与回退路径的请求体 base64 逐字节相等。
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_uses_pre_encoded_b64(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """传入 pre_encoded_b64 时直接进请求体，且不调用 encode_image_b64。"""
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["payload"] = kw.get("json")
        return _ok_response(5.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    # 若回退路径被触发（不该触发），encode_image_b64 抛错直接暴露
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.encode_image_b64",
        lambda *a, **kw: pytest.fail("pre_encoded_b64 已传，不应再调用 encode_image_b64"),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv(), pre_encoded_b64="Zm9v")
    assert result.ok is True
    url = captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert url == "data:image/jpeg;base64,Zm9v"


def test_judge_falls_back_when_pre_encoded_b64_none(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不传 pre_encoded_b64 时回退 encode_image_b64 路径，行为与原实现一致。"""
    called = {"encode": False}

    def fake_encode(*a: Any, **kw: Any) -> Any:
        called["encode"] = True
        return "encodedfallback"

    monkeypatch.setattr("flashgaze.core.vlm_client.encode_image_b64", fake_encode)
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["payload"] = kw.get("json")
        return _ok_response(3.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert called["encode"] is True
    url = captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert url == "data:image/jpeg;base64,encodedfallback"


def test_judge_pre_encoded_b64_matches_reencode(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pre_encoded_b64=encode_image_b64(p) 与默认路径的请求体 base64 完全相等（逐字节等价）。"""
    captured: dict[str, Any] = {"payloads": []}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["payloads"].append(kw.get("json"))
        return _ok_response(1.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    x = encode_image_b64(sharp_img)
    client.judge(sharp_img, _make_cv())  # 默认路径
    client.judge(sharp_img, _make_cv(), pre_encoded_b64=x)  # 预编码路径
    default_url = captured["payloads"][0]["messages"][0]["content"][1]["image_url"]["url"]
    pre_url = captured["payloads"][1]["messages"][0]["content"][1]["image_url"]["url"]
    assert default_url == pre_url


# ---------- SSRF / DNS 重绑定（#5-3 TOCTOU 修复）----------


def test_dns_rebinding_pinned_to_public_ip(monkeypatch: pytest.MonkeyPatch, sharp_img: str) -> None:
    """DNS 重绑定时仍直连构造期 pin 的公网 IP，不因请求期解析到元数据 IP 而绕过。"""
    public = "93.184.216.34"
    meta = "169.254.169.254"
    state = {"n": 0}
    calls: dict[str, Any] = {}

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        # 模拟攻击者：首次（构造期校验）返公网，之后（请求期）改为云元数据 IP
        state["n"] += 1
        ip = meta if state["n"] > 1 else public
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["url"] = a[1] if len(a) > 1 else kw.get("url")
        calls["headers"] = kw.get("headers")
        calls["allow_redirects"] = kw.get("allow_redirects")
        return _ok_response(5.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://api.example.com", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    # 关键：URL 用 pin 的公网 IP，而非请求期重新解析出的元数据 IP
    assert public in calls["url"]
    assert meta not in calls["url"]
    # 仅在构造期解析一次，请求期不再解析（TOCTOU 窗口被消除）
    assert state["n"] == 1
    # Host 头与重定向限制到位
    assert calls["headers"].get("Host") == "api.example.com"
    assert calls["allow_redirects"] is False


def test_validate_rejects_private_ip_at_construction() -> None:
    """构造期解析到私网 IP 立即拒绝（快速失败）。"""
    with pytest.raises(ValueError):
        VLMClient(api_key="k", api_base="http://10.0.0.1", model="m")


def test_validate_rejects_cloud_metadata_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """解析到云元数据地址 169.254.169.254 立即拒绝。"""

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        VLMClient(api_key="k", api_base="http://metadata.internal", model="m")


def test_loopback_allowed_and_pinned(monkeypatch: pytest.MonkeyPatch, sharp_img: str) -> None:
    """回环地址放行（兼容本地 Ollama），且请求直连 pin 的 127.0.0.1 + Host: localhost。"""
    calls: dict[str, Any] = {}

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["url"] = a[1] if len(a) > 1 else kw.get("url")
        calls["headers"] = kw.get("headers")
        return _ok_response(5.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://localhost", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert "127.0.0.1" in calls["url"]
    assert calls["headers"].get("Host") == "localhost"


def test_https_pins_ip_preserves_path_and_host_header(
    monkeypatch: pytest.MonkeyPatch, sharp_img: str
) -> None:
    """HTTPS 端点：URL 用 pin 的 IP、保留 base path，Host 头为原主机名，禁用重定向。"""
    calls: dict[str, Any] = {}

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["url"] = a[1] if len(a) > 1 else kw.get("url")
        calls["headers"] = kw.get("headers")
        calls["allow_redirects"] = kw.get("allow_redirects")
        return _ok_response(5.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(
        api_key="k", api_base="https://dashscope.aliyuncs.com/compatible-mode/v1", model="m"
    )
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert "93.184.216.34" in calls["url"]
    assert "/compatible-mode/v1/chat/completions" in calls["url"]
    assert calls["headers"].get("Host") == "dashscope.aliyuncs.com"
    assert calls["allow_redirects"] is False


def test_unresolvable_host_falls_back_to_hostname(
    monkeypatch: pytest.MonkeyPatch, sharp_img: str
) -> None:
    """不可解析主机（如测试占位 http://x）回退原主机名行为，不崩溃。"""
    calls: dict[str, Any] = {}

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["url"] = a[1] if len(a) > 1 else kw.get("url")
        return _ok_response(5.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert calls["url"] == "http://x/chat/completions"


def test_rebind_to_restricted_at_request_degrades(
    monkeypatch: pytest.MonkeyPatch, sharp_img: str
) -> None:
    """构造期不可解析、请求期重绑定到受限地址：安全降级，绝不发起请求。"""
    state = {"n": 0}
    posted = {"called": False}

    def fake_getaddrinfo(host: str, port: object, *a: Any, **k: Any) -> list[Any]:
        state["n"] += 1
        if state["n"] == 1:
            raise socket.gaierror("unresolved at init")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", fake_getaddrinfo)

    def fake_post(*a: Any, **kw: Any) -> Any:
        posted["called"] = True
        return _ok_response(5.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://evil.internal", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert posted["called"] is False


# ---------- 并发安全（多 worker 共享同一 VLMClient）----------


def test_concurrent_judge_success_path_is_safe(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ThreadPoolExecutor 多 worker 并发调用同一 VLMClient.judge 的成功路径，
    不抛异常、不触发索引越界，且 _candidate_idx / _conn_fail_streak 始终在合法范围内。

    回归点：修复前候选选择/计数无锁，RMW 在高并发下可能丢失更新或越界；此处
    施加 GIL 竞争压力验证加锁后的线程安全契约。
    """
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1", "2.2.2.2", "3.3.3.3"]),
    )
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _ok_response(6.0, "背景虚化"),
    )
    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=3)

    def worker(_: int) -> bool:
        res = client.judge(sharp_img, _make_cv())
        # 内部索引/计数必须始终在合法范围内
        assert 0 <= client._candidate_idx < len(client._candidates)
        assert client._conn_fail_streak == 0
        return res.ok

    with ThreadPoolExecutor(max_workers=16) as ex:
        ok_flags = list(ex.map(worker, range(128)))

    assert all(ok_flags)
    assert client._conn_fail_streak == 0


def test_concurrent_judge_conn_error_path_is_safe(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发连接失败路径：多 worker 同时触发 _on_connection_error 的 RMW（计数自增 +
    候选轮换 + 阈值重解析），须无死锁、无 IndexError，且最终状态一致。

    覆盖 phase2 ThreadPoolExecutor 在端点全网下时的真实并发失败场景。
    """
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1"]),
    )
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=2)

    def worker(_: int) -> bool:
        res = client.judge(sharp_img, _make_cv())
        # 候选池恒为单 IP（重解析仍返回 1.1.1.1），索引必须始终合法、不越界
        assert 0 <= client._candidate_idx < len(client._candidates)
        return res.ok

    with ThreadPoolExecutor(max_workers=16) as ex:
        ok_flags = list(ex.map(worker, range(128)))

    assert not any(ok_flags)  # 全网下：所有调用均耗尽重试降级
    assert 0 <= client._candidate_idx < len(client._candidates)


def test_concurrent_dns_resolution_not_serialized_by_lock(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归点：DNS 解析在 _on_connection_error 中已移出 _state_lock。

    模拟 DNS 抖动（getaddrinfo 睡眠），让每次连接失败均达重解析阈值触发慢速 DNS。
    若 DNS 仍在锁内，N 个并发重解析会被串行化，总耗时 ~ N × sleep；
    修复后 DNS 在锁外并行，总耗时 ~ sleep。断言并发阶段耗时显著小于 N × sleep，
    证明一次 DNS 抖动不再阻塞所有并发线程的 _select_target()/_on_connection_error()。
    """
    dns_sleep = 0.2
    n_workers = 8

    def slow_getaddrinfo(*a: Any, **kw: Any) -> Any:
        time.sleep(dns_sleep)
        return _fake_getaddrinfo(["1.1.1.1"])

    monkeypatch.setattr("flashgaze.core.vlm_client.socket.getaddrinfo", slow_getaddrinfo)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)

    # 构造期也会触发一次慢速解析，先于计时完成，避免计入并发阶段
    client = VLMClient(api_key="k", api_base="http://example.com", model="m", max_retries=1)

    def worker(_: int) -> bool:
        return client.judge(sharp_img, _make_cv()).ok

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        ok_flags = list(ex.map(worker, range(n_workers)))
    elapsed = time.monotonic() - start

    # 全网下：所有调用均耗尽单次重试降级
    assert not any(ok_flags)
    # 关键断言：DNS 已并行，耗时远低于串行化下限 N × dns_sleep
    assert elapsed < n_workers * dns_sleep / 2


def test_session_per_thread_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """每线程 Session 隔离：多个 worker 线程各自首次调用 _get_session() 拿到独立的
    requests.Session 实例（各自独立连接池），从根上消除跨线程共享 Session 的 urllib3
    连接池竞态隐患。

    同时验证：每个每线程 Session 仍是真实 requests.Session、且在 self._host 非空时
    已挂载 _PinnedIPAdapter（HTTPS 连 IP 的 SNI/证书主机名固定语义逐字等价）。
    """
    import threading

    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1"]),
    )
    client = VLMClient(api_key="k", api_base="https://dashscope.aliyuncs.com", model="m")

    # 用显式 Thread 确保 N 个真正不同的线程，各自持有独立 threading.local 槽位
    # （ThreadPoolExecutor.map 可能复用同一线程，无法稳定触发隔离语义）。
    sessions: list[requests.Session] = []
    collected: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        s = client._get_session()
        with lock:
            sessions.append(s)
            collected.append(True)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(collected) == 8
    # 8 个不同线程 → 8 个互不相同 Session 实例
    assert len({id(s) for s in sessions}) == 8
    # 每个都是真实 requests.Session
    assert all(isinstance(s, requests.Session) for s in sessions)
    # 有 host 时每个 Session 都挂了 pin 适配器（HTTPS 语义保持）
    assert all(isinstance(s.get_adapter("https://"), _PinnedIPAdapter) for s in sessions)
    # 同一线程复用同一实例：主线程再取一次不与任何 worker 实例相同（主线程独立）
    assert client._get_session() is not sessions[0]


def test_session_no_global_instance_in_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造期不再持有全局 Session：skip 尚未惰性创建前，主线程无残留 Session 属性。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.1.1.1"]),
    )
    client = VLMClient(api_key="k", api_base="http://example.com", model="m")
    # 构造期不应创建任何 Session（惰性延迟到 worker 线程）
    assert not hasattr(client._session_store, "session")
    # 首次调用才创建且可复用
    s1 = client._get_session()
    s2 = client._get_session()
    assert s1 is s2


# ─────────────────────────────────────────────────────────────────────────────
# H-5：trust_env 代理/CA 环境变量旁路 pin-IP（审查报告 docs/review/…:218-248）
# 全部 mock 网络，不发起真实请求。
# ─────────────────────────────────────────────────────────────────────────────

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)


def _fake_send_capture(captured: dict[str, Any], resp: MagicMock) -> Any:
    """替换 requests.Session.send，捕获 merge_environment_settings 合并后的实际参数。"""

    def fake_send(self: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> Any:
        captured["url"] = request.url
        captured["proxies"] = kwargs.get("proxies")
        captured["verify"] = kwargs.get("verify")
        return resp

    return fake_send


def test_proxy_env_does_not_bypass_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """H-5 缺陷修复回归：设置代理/CA 环境变量后，pin-IP 直连层不得被旁路。

    - Session 必须关闭 trust_env：HTTP(S)_PROXY/ALL_PROXY 不得经
      merge_environment_settings 注入 proxies（否则 TCP 改道代理、由代理解析
      目标主机名，pin-IP/Host pin/SNI pin 全部失效）；
    - REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE 不得替换信任根（verify 仍为 True）；
    - 请求仍直连 pin 的 IP（URL 主机为候选 IP 而非原主机名）。
    """
    for var in _PROXY_ENV_VARS:
        monkeypatch.setenv(var, "http://attacker-proxy.example.com:8080")
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.2.3.4"]),
    )
    client = VLMClient(api_key="k", api_base="https://dashscope.aliyuncs.com", model="m")
    session = client._get_session()
    # Session 级开关必须关闭（修复前 trust_env 默认 True → 红灯）
    assert session.trust_env is False

    captured: dict[str, Any] = {}
    fake_send = _fake_send_capture(captured, _ok_response(1.0))
    monkeypatch.setattr(requests.Session, "send", fake_send)
    result = client.judge("unused.jpg", _make_cv(), pre_encoded_b64="cHJl")
    assert result.ok

    # 合并后的 proxies 不得选中任何代理（修复前 env 代理被注入 → select_proxy
    # 会返回攻击者代理 URL → 红灯）；None 值 = 显式禁用该 scheme 的代理
    assert captured["proxies"] is not None
    for scheme in ("http", "https"):
        assert select_proxy(captured["url"], captured["proxies"]) is None
    # 信任根不得指向 env CA 路径（修复前 verify 会被替换为 env 路径 → 红灯）
    assert captured["verify"] is True
    # 仍直连 pin 的 IP，而非经代理或主机名
    assert captured["url"].startswith("https://1.2.3.4:")
    # Host 头 pin 语义保持
    assert captured["url"] is not None


def test_proxy_env_detection_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """构造期检测到代理/CA 环境变量时，须输出一次「代理与 pin-IP 互斥」告警。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:3128")
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.2.3.4"]),
    )
    import flashgaze.core.vlm_client as vlm_mod

    with caplog.at_level("WARNING", logger=vlm_mod.logger.name):
        VLMClient(api_key="k", api_base="https://dashscope.aliyuncs.com", model="m")
    warnings = [r for r in caplog.records if r.levelno == 30]
    assert any("代理" in r.getMessage() and "忽略" in r.getMessage() for r in warnings)


def test_no_proxy_env_no_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """反例（不应被命中）：无任何代理/CA 环境变量时，构造期不得误报代理告警。"""
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        lambda *a, **kw: _fake_getaddrinfo(["1.2.3.4"]),
    )
    import flashgaze.core.vlm_client as vlm_mod

    with caplog.at_level("WARNING", logger=vlm_mod.logger.name):
        VLMClient(api_key="k", api_base="https://dashscope.aliyuncs.com", model="m")
    assert not any("代理" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# 单图降级收口（M-3/M-4/M-5/M-2/L1/L2）：降级链路每个洞逐一钉死。
# 全部 mock 网络，不发起真实请求。
# ─────────────────────────────────────────────────────────────────────────────


def test_loads_lenient_prefixed_text_blob() -> None:
    """M-3：json5 失败（带前后缀说明文字）时回退 blob 正则截取 + stdlib json。"""
    assert _loads_lenient('结果：{"a": 1}') == {"a": 1}


def test_parse_prefixed_fence_json(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-3：前缀说明文字 + ```json 围栏的 content 也能解析（json5 失败后 blob 回退兜底）。"""
    content = '好的，以下是判断结果：\n```json\n{"adjustment": 5, "reason": "背景虚化"}\n```'
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response(content),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 5.0
    assert result.reason == "背景虚化"


def test_degrade_nan_adjustment(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-2：adjustment 为 NaN 字面量（json5/stdlib json 均能解析出 float('nan')）
    时必须解析失败降级，而不是经 clamp 穿透成 +max 满额补偿。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response('{"adjustment": NaN, "reason": "虚化"}'),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_adjustment=10.0)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0  # 绝不允许出现 +10 满额


def test_degrade_infinity_adjustment(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-2：Infinity 字面量与 "inf" 字符串均为非有限值，同路降级。"""
    for content in ('{"adjustment": Infinity}', '{"adjustment": "inf"}'):
        monkeypatch.setattr(
            "flashgaze.core.vlm_client.requests.Session.post",
            lambda *a, c=content, **kw: _raw_content_response(c),
        )
        client = VLMClient(api_key="k", api_base="http://x", model="m", max_adjustment=10.0)
        result = client.judge(sharp_img, _make_cv())
        assert result.ok is False
        assert result.adjustment == 0.0


def test_degrade_empty_choices(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-4：`{"choices": []}` 必须降级而非 IndexError 上抛炸掉整个评分。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": []}
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())  # 不抛异常即为通过
    assert result.ok is False
    assert result.adjustment == 0.0


def test_degrade_null_message(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-4：choices[0].message 为 null 时经 AttributeError 兜底降级，不上抛。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": None}]}
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", lambda *a, **kw: resp)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())  # 不抛异常即为通过
    assert result.ok is False
    assert result.adjustment == 0.0


def test_chunked_encoding_error_retries_then_success(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-5：ChunkedEncodingError（响应流截断）按瞬时异常退避重试，第二次成功。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ChunkedEncodingError("response truncated")
        return _ok_response(5.0, "背景虚化")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=3)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 5.0
    assert calls["n"] == 2


def test_chunked_encoding_error_retry_exhausted(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-5：ChunkedEncodingError 重试耗尽后安全降级，不上抛。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: (_ for _ in ()).throw(
            requests.exceptions.ChunkedEncodingError("response truncated")
        ),
    )
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    client = VLMClient(api_key="k", api_base="http://x", model="m", max_retries=2)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.adjustment == 0.0
    assert result.error == "retry_exhausted"


def test_parse_null_reason_becomes_empty(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """L2：reason=null 时归空串，不得产出字面量 "None"，且整体仍成功。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response('{"adjustment": 3, "reason": null}'),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.adjustment == 3.0
    assert result.reason == ""


def test_parse_reason_lone_surrogate_sanitized(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-C1：reason 中的孤立代理项（\\ud83d 等坏转义）被清洗，落盘可 UTF-8 编码。"""
    # JSON 文本中的 \ud83d 转义（缺少低代理）会被 json/json5 解析成孤立代理字符
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.requests.Session.post",
        lambda *a, **kw: _raw_content_response('{"adjustment": 2, "reason": "虚化\\ud83d"}'),
    )
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert result.reason == "虚化"  # 孤立代理被剔除
    result.reason.encode("utf-8")  # 不抛 UnicodeEncodeError 即为通过


def test_parse_retry_after_negative_clamps_to_1() -> None:
    """L1：负值/0 的 Retry-After 归 1.0 下限，消除 time.sleep ValueError。"""
    assert VLMClient._parse_retry_after(_retry_after_response("-3")) == 1.0
    assert VLMClient._parse_retry_after(_retry_after_response("0")) == 1.0


# ---------- 批量熔断 ----------


def test_breaker_trips_after_consecutive_failures(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连续失败达阈值后熔断：后续 judge 零网络早退，error=circuit_open。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        raise requests.ConnectionError("dead endpoint")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=3, breaker_threshold=5
    )

    # 前 5 张：每张烧满 3 次尝试后降级为 retry_exhausted
    for _ in range(5):
        result = client.judge(sharp_img, _make_cv())
        assert result.ok is False
        assert result.error == "retry_exhausted"
    assert calls["n"] == 15  # 5 张 × 3 次

    # 第 6 张：熔断已开，零网络早退
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "circuit_open"
    assert result.adjustment == 0.0
    assert result.provider == "qwen"
    assert calls["n"] == 15  # 未再发起网络请求


def test_breaker_streak_resets_on_success(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """任一成功即复位连续计数：4 败 1 成功 4 败不触发熔断。"""
    calls = {"n": 0}
    script = ["fail", "fail", "fail", "fail", "ok"]  # 每张图一个结果（max_retries=1）

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        idx = calls["n"] - 1
        if idx < len(script) and script[idx] == "fail":
            raise requests.ConnectionError("flaky")
        return _ok_response(1.0)

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=1, breaker_threshold=5
    )

    results = [client.judge(sharp_img, _make_cv()) for _ in range(10)]
    # 前 4 张失败、第 5 张成功复位计数，后续全部成功；连续失败最多 4 < 5，永不熔断
    assert [r.ok for r in results[:5]] == [False, False, False, False, True]
    assert all(r.ok for r in results[5:])
    assert all(r.error != "circuit_open" for r in results)


def test_breaker_disabled_with_zero_threshold(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """breaker_threshold=0 关闭熔断（等价旧行为），失败永不短路。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        raise requests.ConnectionError("dead endpoint")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=1, breaker_threshold=0
    )

    for _ in range(10):
        result = client.judge(sharp_img, _make_cv())
        assert result.ok is False
        assert result.error == "retry_exhausted"
    assert calls["n"] == 10  # 每张都真实发起请求


def test_breaker_rate_guard_trips_on_high_failure_rate(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败分散但失败率超阈值：样本 20 张失败率 >= 0.8 时熔断。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        # 每 5 张里前 4 张失败、第 5 张成功：连续失败最多 4（< 5 不触发连续熔断），
        # 前 20 张样本失败率 0.8 → 触发失败率熔断
        if calls["n"] % 5 == 0:
            return _ok_response(1.0)
        raise requests.ConnectionError("half-dead")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=1, breaker_threshold=5
    )

    for i in range(20):
        result = client.judge(sharp_img, _make_cv())
        assert result.error != "circuit_open", f"第 {i + 1} 张不应提前熔断"

    # 第 21 张：失败率熔断已开，零网络早退
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "circuit_open"
    assert calls["n"] == 20


def test_breaker_early_exit_in_retry_loop(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """在途图在重试间隙感知熔断：不再烧满剩余重试预算。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # 模拟并发 worker 的 judge 恰在此时耗尽重试（streak=1 达阈值）触发熔断
            client._record_vlm_outcome(False)
        raise requests.Timeout("slow death")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=3, breaker_threshold=1
    )

    result = client.judge(sharp_img, _make_cv())
    assert result.ok is False
    assert result.error == "retry_exhausted"
    # attempt 0 发出请求（随后熔断开启），attempt 1 循环顶部早退——
    # 未烧满 3 次重试预算
    assert calls["n"] == 1


def test_breaker_ignores_unsupported_provider(sharp_img: str) -> None:
    """预检失败（unsupported_provider）不计入熔断统计：零网络成本、非端点健康信号。"""
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", provider="bad", breaker_threshold=1
    )
    for _ in range(5):
        result = client.judge(sharp_img, _make_cv())
        assert result.error == "unsupported_provider"
    assert not client._is_breaker_open()


def test_breaker_ignores_encode_failure(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """预检失败（图片编码失败）不计入熔断统计，且不污染后续正常请求路径。"""
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        raise requests.ConnectionError("dead endpoint")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=1, breaker_threshold=1
    )

    # 编码失败：judge 失败但熔断不开
    for _ in range(3):
        result = client.judge("/nonexistent/img.jpg", _make_cv())
        assert result.ok is False
        assert result.error != "circuit_open"
    assert not client._is_breaker_open()
    # 正常网络路径未被污染：请求照常发起（此处端点已死，error=retry_exhausted）
    result = client.judge(sharp_img, _make_cv())
    assert result.error == "retry_exhausted"
    assert calls["n"] == 1


def test_breaker_thread_safety_trip(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """多线程并发失败下熔断正确开启，所有结果合法，无竞态异常。"""
    calls = {"n": 0}
    lock = threading.Lock()

    def fake_post(*a: Any, **kw: Any) -> Any:
        with lock:
            calls["n"] += 1
        raise requests.ConnectionError("dead endpoint")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", max_retries=1, breaker_threshold=5
    )

    def worker(_: int) -> str:
        return client.judge(sharp_img, _make_cv()).error or ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        errors = list(pool.map(worker, range(40)))

    assert client._is_breaker_open()
    # 每个结果要么真实重试耗尽、要么熔断早退，绝不出现其他错误
    assert all(e in ("retry_exhausted", "circuit_open") for e in errors)
    # 熔断后不再有新请求：总请求数远小于朴素全量 40
    assert calls["n"] < 40


# ─────────────────────────────────────────────────────────────────────────────
# VLM 采样参数固定（PLAN-vlm-sampling-reproducibility）
#
# 可复现性原则要求启用 VLM 时采样随机性可收敛：默认注入 temperature=0 与固定
# seed（provider 支持范围内），None = 不注入（旧行为逃生舱）。全部为增强类用例：
# 注入实现落地前 payload 无这些键，断言失败（红灯）。
# ─────────────────────────────────────────────────────────────────────────────


def _capture_payload(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """捕获 Session.post 收到的请求体（pin-IP 直连层唯一出口）。"""
    captured: dict[str, Any] = {}

    def fake_post(*a: Any, **kw: Any) -> Any:
        captured["payload"] = kw.get("json") or {}
        return _ok_response(1.0, "ok")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    return captured


def test_judge_payload_qwen_default_temperature_and_seed(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """qwen 默认注入 temperature=0.0 与固定 seed=42（可复现性默认口径）。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    client.judge(sharp_img, _make_cv())
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["seed"] == 42


def test_judge_payload_openai_provider_carries_seed(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openai 与 qwen 同为支持 seed 的 OpenAI 兼容协议，默认注入一致。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m", provider="openai")
    client.judge(sharp_img, _make_cv())
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["seed"] == 42


def test_judge_payload_anthropic_temperature_no_seed(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """anthropic 报文归一后携带 temperature，且绝不出现 seed（协议无该字段）。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m", provider="anthropic")
    client.judge(sharp_img, _make_cv())
    assert captured["payload"]["temperature"] == 0.0
    assert "seed" not in captured["payload"]


def test_judge_payload_ollama_temperature_no_seed(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ollama OpenAI 兼容层对 seed 未承诺，保守裁剪：temperature 注入、seed 不注入。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m", provider="ollama")
    client.judge(sharp_img, _make_cv())
    assert captured["payload"]["temperature"] == 0.0
    assert "seed" not in captured["payload"]


def test_judge_payload_none_disables_sampling(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """temperature=None 且 seed=None 时不注入任何采样参数（旧行为逃生舱）。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m", temperature=None, seed=None)
    client.judge(sharp_img, _make_cv())
    assert "temperature" not in captured["payload"]
    assert "seed" not in captured["payload"]


def test_judge_payload_temperature_clamped_per_provider(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """temperature 按 provider 规格钳制：qwen 上限 2.0、anthropic 上限 1.0。"""
    captured = _capture_payload(monkeypatch)
    client = VLMClient(api_key="k", api_base="http://x", model="m", temperature=5.0)
    client.judge(sharp_img, _make_cv())
    assert captured["payload"]["temperature"] == 2.0

    captured2 = _capture_payload(monkeypatch)
    client = VLMClient(
        api_key="k", api_base="http://x", model="m", provider="anthropic", temperature=1.5
    )
    client.judge(sharp_img, _make_cv())
    assert captured2["payload"]["temperature"] == 1.0


def test_effective_sampling_params_min_temperature_lifts_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「不支持 0 的 provider 取最小值」机制：spec.min_temperature>0 时 0 被抬升。"""
    from dataclasses import replace as dc_replace

    from flashgaze.core.vlm_client import _PROVIDER_SPECS, effective_sampling_params

    monkeypatch.setitem(
        _PROVIDER_SPECS, "qwen", dc_replace(_PROVIDER_SPECS["qwen"], min_temperature=0.05)
    )
    assert effective_sampling_params("qwen", 0.0, None) == {"temperature": 0.05}


def test_litellm_kwargs_carry_sampling(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """use_litellm=True 时 temperature/seed 透传给 litellm.completion。"""
    captured: dict[str, Any] = {}

    def fake_litellm_completion(**kw: Any) -> Any:
        captured.update(kw)
        return _litellm_response(1.0, "ok")

    fake_litellm = MagicMock()
    fake_litellm.completion = fake_litellm_completion
    monkeypatch.setattr("flashgaze.core.vlm_client.litellm", fake_litellm, raising=False)
    monkeypatch.setattr("flashgaze.core.vlm_client._LITELLM_AVAILABLE", True, raising=False)

    client = VLMClient(api_key="k", api_base="http://x", model="m", use_litellm=True)
    result = client.judge(sharp_img, _make_cv())
    assert result.ok is True
    assert captured["temperature"] == 0.0
    assert captured["seed"] == 42


# ─────────────────────────────────────────────────────────────────────────────
# sampling_params_for_config：报告回显与 payload 注入同源（可复现性）
# ─────────────────────────────────────────────────────────────────────────────


def test_sampling_params_for_config_enabled() -> None:
    """启用 VLM 时返回 provider + 实际生效采样参数（与 payload 注入同源）。"""
    from flashgaze.core.vlm_client import sampling_params_for_config
    from flashgaze.models.schemas import Config

    cfg = Config(directory=".", api_key="k", vlm_provider="qwen")
    assert sampling_params_for_config(cfg) == {
        "provider": "qwen",
        "temperature": 0.0,
        "seed": 42,
    }
    # anthropic：seed 已裁剪，仅回显实际会注入的键
    cfg2 = Config(directory=".", api_key="k", vlm_provider="anthropic")
    assert sampling_params_for_config(cfg2) == {"provider": "anthropic", "temperature": 0.0}


def test_sampling_params_for_config_disabled_no_vlm() -> None:
    """反例：no_vlm=True 时不产生采样参数（--no-vlm 报告永不出现 vlm_sampling 小节）。"""
    from flashgaze.core.vlm_client import sampling_params_for_config
    from flashgaze.models.schemas import Config

    cfg = Config(directory=".", api_key="k", no_vlm=True)
    assert sampling_params_for_config(cfg) is None


def test_sampling_params_for_config_disabled_no_api_key() -> None:
    """反例：缺 api_key 时 VLM 未启用，不产生采样参数。"""
    from flashgaze.core.vlm_client import sampling_params_for_config
    from flashgaze.models.schemas import Config

    cfg = Config(directory=".", api_key=None)
    assert sampling_params_for_config(cfg) is None

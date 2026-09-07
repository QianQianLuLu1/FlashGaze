"""factory.make_scorer 装配验证：allow_private_targets 透传与 SSRF 默认拒绝。"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest

from flashgaze.core.factory import make_scorer
from flashgaze.models.schemas import Config


def _fake_getaddrinfo(ips: list[str]) -> Callable[..., list[tuple[Any, ...]]]:
    def _fake(*_a: Any, **_kw: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in ips]

    return _fake


def test_make_scorer_plumbs_allow_private_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """config.allow_private_targets=True 透传到 VLMClient._allow_private，私网被放行。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        _fake_getaddrinfo(["10.0.0.1"]),
    )
    cfg = Config(
        directory=".",
        api_key="k",
        api_base="http://10.0.0.1",
        model="m",
        vlm_provider="qwen",
        allow_private_targets=True,
    )
    scorer = make_scorer(cfg)
    assert scorer.vlm_client is not None
    assert scorer.vlm_client._allow_private is True
    assert any(c.connect_host == "10.0.0.1" for c in scorer.vlm_client._candidates)


def test_make_scorer_qwen_private_rejected_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """qwen provider 私网默认仍按 SSRF 拒绝（经 factory 装配路径）。"""
    monkeypatch.setattr(
        "flashgaze.core.vlm_client.socket.getaddrinfo",
        _fake_getaddrinfo(["10.0.0.1"]),
    )
    cfg = Config(
        directory=".",
        api_key="k", api_base="http://10.0.0.1", model="m", vlm_provider="qwen"
    )
    with pytest.raises(ValueError):
        make_scorer(cfg)


def test_make_scorer_plumbs_vlm_sampling() -> None:
    """config.vlm_temperature / vlm_seed 透传到 VLMClient.sampling（构造期算定）。"""
    cfg = Config(
        directory=".",
        api_key="k",
        api_base="http://x",
        model="m",
        vlm_provider="qwen",
        vlm_temperature=0.3,
        vlm_seed=7,
    )
    scorer = make_scorer(cfg)
    assert scorer.vlm_client is not None
    assert scorer.vlm_client.sampling == {"temperature": 0.3, "seed": 7}


def test_make_scorer_vlm_sampling_none_yields_empty() -> None:
    """Config 采样字段为 None（配置文件 null「不注入」）时 sampling 为空 dict。"""
    cfg = Config(
        directory=".",
        api_key="k",
        api_base="http://x",
        model="m",
        vlm_provider="qwen",
        vlm_temperature=None,
        vlm_seed=None,
    )
    scorer = make_scorer(cfg)
    assert scorer.vlm_client is not None
    assert scorer.vlm_client.sampling == {}

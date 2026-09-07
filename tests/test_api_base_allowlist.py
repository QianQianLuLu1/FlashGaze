"""api_base 端点白名单回归测试（H-6）。

覆盖两个层次：
1. `flashgaze.utils.net_guard` 纯判定函数（零网络、零依赖）；
2. `flashgaze.utils.config.build_config` 装配卡口（CLI / env / 配置文件 / WebUI /
   MCP 四条来源在此汇聚）。

处置口径（用户裁定）：非白名单端点**仅告警放行**——不阻断、不改退出码、不改写
配置值。故每条「异常」用例都同时断言「有 WARNING」与「build_config 正常返回且
api_base 原样保留」。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from flashgaze.defaults import DEFAULT_API_BASE_ALLOWLIST
from flashgaze.utils.config import build_config
from flashgaze.utils.net_guard import (
    ApiBaseVerdict,
    api_base_host,
    check_api_base,
    is_host_allowlisted,
    is_private_or_loopback_host,
)

QWEN_OFFICIAL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EVIL = "https://evil.example.com/v1"

# 全部用例共用：把可能污染判定的环境变量清空
_ENV_VARS = (
    "FLASHGAZE_API_BASE",
    "FLASHGAZE_API_BASE_ALLOWLIST",
    "FLASHGAZE_ALLOW_UNTRUSTED_API_BASE",
    "FLASHGAZE_ALLOW_PRIVATE_TARGETS",
    "FLASHGAZE_VLM_PROVIDER",
    "FLASHGAZE_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ── 1. api_base_host ────────────────────────────────────────────────


def test_api_base_host_lowercases_and_strips_port() -> None:
    assert api_base_host("https://API.OpenAI.com:8443/v1") == "api.openai.com"


def test_api_base_host_handles_ipv6() -> None:
    assert api_base_host("http://[::1]:11434") == "::1"


def test_api_base_host_missing_scheme_still_resolves() -> None:
    """无 scheme 的 api_base 仍解析出主机名（scheme 合法性由 check_api_base 判定）。"""
    assert api_base_host("localhost:11434") == "localhost"


def test_api_base_host_empty_returns_empty() -> None:
    assert api_base_host("") == ""
    assert api_base_host("   ") == ""


# ── 2. is_private_or_loopback_host ──────────────────────────────────


def test_private_or_loopback_detects_ip_literals() -> None:
    assert is_private_or_loopback_host("127.0.0.1") is True
    assert is_private_or_loopback_host("::1") is True
    assert is_private_or_loopback_host("10.0.0.1") is True
    assert is_private_or_loopback_host("192.168.1.10") is True
    assert is_private_or_loopback_host("172.17.0.1") is True
    assert is_private_or_loopback_host("169.254.169.254") is True


def test_private_or_loopback_detects_localhost() -> None:
    assert is_private_or_loopback_host("localhost") is True


def test_private_or_loopback_rejects_public_host() -> None:
    """反例：公网域名与公网 IP 都不是私网/回环，不得被误判为自托管。"""
    assert is_private_or_loopback_host("api.openai.com") is False
    assert is_private_or_loopback_host("8.8.8.8") is False


# ── 3. is_host_allowlisted（含后缀欺骗反例）─────────────────────────


def test_allowlist_exact_match() -> None:
    assert is_host_allowlisted("api.openai.com", ("api.openai.com",)) is True


def test_allowlist_subdomain_match() -> None:
    assert is_host_allowlisted("proxy.api.openai.com", ("api.openai.com",)) is True


def test_allowlist_suffix_spoof_rejected() -> None:
    """反例：dashscope.aliyuncs.com.evil.com 不得因 endswith 误命中白名单。"""
    assert (
        is_host_allowlisted("dashscope.aliyuncs.com.evil.com", ("dashscope.aliyuncs.com",)) is False
    )
    assert is_host_allowlisted("evildashscope.aliyuncs.com", ("dashscope.aliyuncs.com",)) is False


def test_allowlist_case_insensitive() -> None:
    assert is_host_allowlisted("API.OpenAI.com", ("api.openai.com",)) is True


def test_allowlist_empty_entry_ignored() -> None:
    assert is_host_allowlisted("api.openai.com", ("", "  ")) is False


def test_allowlist_builtin_contains_official_domains() -> None:
    for host in ("dashscope.aliyuncs.com", "api.openai.com", "api.anthropic.com", "localhost"):
        assert is_host_allowlisted(host, DEFAULT_API_BASE_ALLOWLIST) is True


# ── 4. check_api_base ───────────────────────────────────────────────


def _verdict(
    api_base: str,
    *,
    provider: str = "qwen",
    allow_private_targets: bool = False,
    allowlist: tuple[str, ...] = DEFAULT_API_BASE_ALLOWLIST,
    allow_untrusted: bool = False,
) -> ApiBaseVerdict:
    return check_api_base(
        api_base,
        provider=provider,
        allow_private_targets=allow_private_targets,
        allowlist=allowlist,
        allow_untrusted=allow_untrusted,
    )


def test_check_empty_api_base_is_trusted() -> None:
    """空 api_base（anthropic 走 litellm 默认端点）不告警，与既有静态校验一致。"""
    v = _verdict("")
    assert v.trusted is True
    assert v.host == ""


def test_check_bad_scheme_untrusted() -> None:
    v = _verdict("ftp://evil.example.com")
    assert v.trusted is False


def test_check_missing_host_untrusted() -> None:
    v = _verdict("https://")
    assert v.trusted is False


def test_check_evil_public_host_untrusted() -> None:
    v = _verdict(EVIL)
    assert v.trusted is False
    assert v.host == "evil.example.com"


def test_check_custom_allowlist_trusted() -> None:
    v = _verdict("https://my.vlm.internal/v1", allowlist=("my.vlm.internal",))
    assert v.trusted is True


def test_check_allow_untrusted_confirmation() -> None:
    """已显式确认的端点视为可信（逃生舱），不再告警。"""
    assert _verdict(EVIL, allow_untrusted=True).trusted is True


def test_check_private_host_without_optin_untrusted() -> None:
    v = _verdict("http://10.0.0.1:11434")
    assert v.trusted is False
    assert "SSRF" in v.reason or "allow_private" in v.reason


def test_check_private_host_with_allow_private_trusted() -> None:
    v = _verdict("http://10.0.0.1:11434", allow_private_targets=True)
    assert v.trusted is True


def test_check_private_host_with_ollama_provider_trusted() -> None:
    """ollama 视为自托管 provider，私网/回环免白名单（保住 README 的 LAN 场景）。"""
    v = _verdict("http://192.168.1.10:11434", provider="ollama")
    assert v.trusted is True


def test_check_localhost_ollama_trusted() -> None:
    v = _verdict("http://localhost:11434", provider="ollama")
    assert v.trusted is True


def test_check_public_non_allowlisted_under_ollama_still_untrusted() -> None:
    """反例：ollama 只豁免私网/回环，公网非白名单主机仍必须告警。"""
    assert _verdict(EVIL, provider="ollama").trusted is False


def test_check_suffix_spoof_under_ollama_untrusted() -> None:
    """反例：后缀欺骗在私网豁免分支也不得被误放行。"""
    assert (
        _verdict("https://dashscope.aliyuncs.com.evil.com/v1", provider="ollama").trusted is False
    )


# ── 5. build_config 集成：默认路径不告警（反例基线）───────────────────


def test_build_config_default_api_base_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    cfg = build_config("/tmp")
    assert cfg.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    with caplog.at_level(logging.WARNING):
        cfg = build_config("/tmp")
    assert cfg.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "端点" not in caplog.text


def test_build_config_allowlist_default_is_builtin() -> None:
    assert build_config("/tmp").api_base_allowlist == DEFAULT_API_BASE_ALLOWLIST
    assert build_config("/tmp").allow_untrusted_api_base is False


# ── 6. build_config 集成：四条来源的非白名单端点均告警且不阻断 ──────────


def _warnings(caplog: pytest.LogCaptureFixture, **kwargs: Any) -> tuple[Any, str]:
    with caplog.at_level(logging.WARNING):
        cfg = build_config("/tmp", **kwargs)
    return cfg, caplog.text


def test_cli_override_untrusted_warns_without_blocking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg, text = _warnings(caplog, api_base=EVIL)
    assert "evil.example.com" in text
    assert "FLASHGAZE_API_BASE_ALLOWLIST" in text
    assert "FLASHGAZE_ALLOW_UNTRUSTED_API_BASE" in text
    # 不阻断：配置照常装配、端点原样保留
    assert cfg.api_base == EVIL


def test_env_source_untrusted_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("FLASHGAZE_API_BASE", EVIL)
    cfg, text = _warnings(caplog)
    assert "evil.example.com" in text
    assert cfg.api_base == EVIL


def test_config_file_source_untrusted_warns(caplog: pytest.LogCaptureFixture) -> None:
    """配置文件劫持（clone 第三方仓库携带配置）必须在日志中可见。"""
    cfg, text = _warnings(caplog, file_cfg={"api_base": EVIL})
    assert "evil.example.com" in text
    assert cfg.api_base == EVIL


def test_bad_scheme_warns(caplog: pytest.LogCaptureFixture) -> None:
    _, text = _warnings(caplog, api_base="ftp://evil.example.com")
    assert "evil.example.com" in text


def test_private_target_without_optin_warns(caplog: pytest.LogCaptureFixture) -> None:
    _, text = _warnings(caplog, api_base="http://10.0.0.1:11434")
    assert "10.0.0.1" in text


# ── 7. build_config 集成：反例（不应被命中/触发告警）───────────────────


def test_official_endpoint_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """反例 1：官方端点不得告警。"""
    cfg, text = _warnings(caplog, api_base=QWEN_OFFICIAL)
    assert "端点" not in text
    assert cfg.api_base == QWEN_OFFICIAL


def test_suffix_spoof_warns(caplog: pytest.LogCaptureFixture) -> None:
    """反例 1b：dashscope.aliyuncs.com.evil.com 必须告警（不得因后缀误命中）。"""
    _, text = _warnings(caplog, api_base="https://dashscope.aliyuncs.com.evil.com/v1")
    assert "dashscope.aliyuncs.com.evil.com" in text


def test_ollama_localhost_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """反例 2：本地 Ollama（provider=ollama）不得告警。"""
    _, text = _warnings(caplog, api_base="http://localhost:11434", vlm_provider="ollama")
    assert "端点" not in text


def test_lan_ollama_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """反例 3：README 文档化的 LAN Ollama 场景不得告警。"""
    _, text = _warnings(caplog, api_base="http://192.168.1.10:11434", vlm_provider="ollama")
    assert "端点" not in text


def test_self_hosted_with_allow_private_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """反例 4：非 ollama 自托管 + FLASHGAZE_ALLOW_PRIVATE_TARGETS 不得告警。"""
    _, text = _warnings(caplog, api_base="http://192.168.1.10:11434", allow_private_targets=True)
    assert "端点" not in text


def test_empty_api_base_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """反例 5：空 api_base（anthropic 走 litellm 默认端点）不得告警。"""
    cfg, text = _warnings(caplog, api_base="", vlm_provider="anthropic")
    assert "端点" not in text
    assert cfg.api_base == ""


def test_allow_untrusted_env_suppresses_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """反例 6：显式确认后不再告警（逃生舱）。"""
    monkeypatch.setenv("FLASHGAZE_ALLOW_UNTRUSTED_API_BASE", "1")
    _, text = _warnings(caplog, api_base=EVIL)
    assert "evil.example.com" not in text


def test_custom_allowlist_env_suppresses_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """反例 7：自定义白名单命中的端点不告警。"""
    monkeypatch.setenv("FLASHGAZE_API_BASE_ALLOWLIST", "my.vlm.internal, other.internal")
    cfg, text = _warnings(caplog, api_base="https://my.vlm.internal/v1")
    assert "端点" not in text
    assert cfg.api_base_allowlist == ("my.vlm.internal", "other.internal")


def test_unrelated_warnings_not_treated_as_endpoint_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """反例 8：其它字段的既有告警不得被误判为端点告警。"""
    _, text = _warnings(caplog, unknown_key_xyz=1)
    assert "忽略未知配置键" in text
    assert "端点" not in text

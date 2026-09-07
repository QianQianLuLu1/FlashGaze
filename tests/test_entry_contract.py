"""三入口契约测试门控（F-02）。

以 `knobs_for(entry)` 为唯一契约源，断言 CLI / WebUI 两入口各自暴露的评分旋钮集合
等于 `knobs_for(entry)`。任一入口漏接或多接旋钮，测试即失败（漏接旋钮 = 构建失败）。

MCP 入口的契约断言见 tests/test_mcp_server.py::TestAllMcpToolsExposeMcpKnobs。
"""

from __future__ import annotations

import pytest

from flashgaze.cli.parser import _OPTION_DESTS, CLIParser
from flashgaze.models.options import (
    ENTRY_CLI,
    ENTRY_WEBUI,
    knobs_for,
)


def test_cli_exposes_exactly_cli_knobs() -> None:
    """CLI 泛型收集的旋钮集合（_OPTION_DESTS + weights）必须等于 knobs_for(cli)。"""
    expected = set(knobs_for(ENTRY_CLI))
    parser = CLIParser()
    ns = parser.parse_namespace(["score", "/tmp"])
    # 仅统计 parser 实际挂了 add_argument 的旋钮；entries=() 的 timeout 类不挂，保持 None
    provided = {d for d in _OPTION_DESTS if hasattr(ns, d)}
    provided.add("weights")  # --weights JSON 单独提供，属 CLI 旋钮
    assert provided == expected


def test_webui_exposes_exactly_webui_knobs() -> None:
    """WebUI 表单适配器（_options_from_inputs）产出的旋钮必须等于 knobs_for(webui)。"""
    pytest.importorskip("gradio")
    from flashgaze.webui.app import _options_from_inputs

    expected = set(knobs_for(ENTRY_WEBUI))
    # 全部传真值，确保 knob 集合（而非被 None 折叠的子集）完整暴露
    opts = _options_from_inputs(
        True,
        True,
        "auto",
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        8,
        "qwen",
        2,
        "k",
        "b",
        "m",
        {"sharpness": 0.5},
    )
    exposed = set(opts.to_config_kwargs().keys())
    assert exposed == expected

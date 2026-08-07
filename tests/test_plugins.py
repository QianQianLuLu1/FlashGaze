"""插件系统测试。

覆盖点：插件发现、evaluate 正常/异常降级、cleanup 不抛、损坏模块不阻塞发现。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from flashgaze.plugins import discover_plugins
from flashgaze.plugins.base import PluginScore, ScoringPlugin
from flashgaze.plugins.builtin.example_aesthetics import AestheticsPlugin


def test_discover_builtin():
    """discover_plugins() 能发现内置 example_aesthetics。"""
    plugins = discover_plugins()
    names = [p.name for p in plugins]
    assert "aesthetics" in names
    assert any(isinstance(p, AestheticsPlugin) for p in plugins)


def test_plugin_evaluate(fixtures_dir: Path, tmp_path: Path):
    """对有效图（sharp.jpg）evaluate 返回 PluginScore，且分数在 0-100。

    注：本环境 OpenCV 无法读取含中文/空格的路径，故先复制到 ASCII 临时目录
    （与项目 photo_dir fixture 约定一致），再对拷贝调用 evaluate。
    """
    src = fixtures_dir / "sharp.jpg"
    dst = tmp_path / "sharp.jpg"
    shutil.copy2(src, dst)
    plugin = AestheticsPlugin()
    r = plugin.evaluate(str(dst))
    assert isinstance(r, PluginScore)
    assert 0.0 <= r.score <= 100.0
    assert r.weight == 0.1
    assert r.name == "aesthetics"


def test_plugin_evaluate_invalid():
    """不存在路径 evaluate 返回 None（不抛）。"""
    plugin = AestheticsPlugin()
    assert plugin.evaluate("/nonexistent/path/x.jpg") is None


def test_plugin_cleanup():
    """cleanup 不抛异常（默认空实现）。"""
    plugin = AestheticsPlugin()
    plugin.cleanup()  # 不应抛出


def test_discover_skips_broken_module(tmp_path: Path):
    """损坏的插件模块只产生 warning，不阻塞发现；内置插件仍被发现。"""
    broken = tmp_path / "broken_plugin.py"
    broken.write_text(
        "import a_module_that_does_not_exist_12345\n", encoding="utf-8",
    )
    plugins = discover_plugins(str(tmp_path))
    # 内置 aesthetics 仍被发现，且整体不抛异常
    assert any(p.name == "aesthetics" for p in plugins)

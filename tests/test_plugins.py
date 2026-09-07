"""插件系统测试。

覆盖点：插件发现、evaluate 正常/异常降级、cleanup 不抛、损坏模块不阻塞发现。
新增（修复插件评分顺序 bug）：验证插件加分后入选判定已反映插件后分数；
以及示例插件改用 load_image_color 后中文/全角路径不再静默失效。
新增（H-1）：插件返回的 score/weight 为 NaN/Inf/越界时的有限性与区间校验。
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config, ImageScore
from flashgaze.plugins import discover_plugins
from flashgaze.plugins.base import PluginScore, ScoringPlugin
from flashgaze.plugins.builtin.example_aesthetics import AestheticsPlugin


def _config(**overrides: Any) -> Config:
    """构造测试用 Config，默认纯 CV（no_vlm=True），可复现。"""
    base: dict[str, Any] = {
        "directory": ".",
        "top": 30,
        "no_vlm": True,
        "weights": {"sharpness": 0.5, "exposure": 0.5},
    }
    base.update(overrides)
    return Config(**base)


def _make_fake_run_plugins(
    target_path: str, target_score: float, other_score: float
) -> Callable[[HybridScorer, list[ImageScore]], None]:
    """返回一个假 _run_plugins：把目标图分数设为 target_score、其余图设为 other_score。

    用于模拟"某插件把目标图从 60 拉到 95"的场景，验证入选判定是否跟随插件后分数。
    直接设置绝对分数（而非叠加），使断言与真实 CV 分差无关，确定性强。
    """

    def _fake_run_plugins(self: HybridScorer, results: list[ImageScore]) -> None:
        for i, s in enumerate(results):
            new = target_score if s.path == target_path else other_score
            results[i] = replace(s, score=new)

    return _fake_run_plugins


def test_discover_builtin() -> None:
    """discover_plugins() 能发现内置 example_aesthetics。"""
    plugins = discover_plugins()
    names = [p.name for p in plugins]
    assert "aesthetics" in names
    assert any(isinstance(p, AestheticsPlugin) for p in plugins)


def test_plugin_evaluate(fixtures_dir: Path, tmp_path: Path) -> None:
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


def test_plugin_evaluate_invalid() -> None:
    """不存在路径 evaluate 返回 None（不抛）。"""
    plugin = AestheticsPlugin()
    assert plugin.evaluate("/nonexistent/path/x.jpg") is None


def test_plugin_cleanup() -> None:
    """cleanup 不抛异常（默认空实现）。"""
    plugin = AestheticsPlugin()
    plugin.cleanup()  # 不应抛出


def test_discover_skips_broken_module(tmp_path: Path) -> None:
    """损坏的插件模块只产生 warning，不阻塞发现；内置插件仍被发现。"""
    broken = tmp_path / "broken_plugin.py"
    broken.write_text(
        "import a_module_that_does_not_exist_12345\n",
        encoding="utf-8",
    )
    plugins = discover_plugins(str(tmp_path))
    # 内置 aesthetics 仍被发现，且整体不抛异常
    assert any(p.name == "aesthetics" for p in plugins)


# ---------- C-03：自定义插件必须声明 __flashgaze_plugin__ 标记 ----------


def test_discover_skips_undeclared_module(tmp_path: Path) -> None:
    """未声明 __flashgaze_plugin__ 的随机脚本被拒绝加载，且内置插件不受影响（C-03）。"""
    rogue = tmp_path / "rogue.py"
    rogue.write_text(
        "print('side-effect that must NOT run as a plugin')\n"
        "from flashgaze.plugins.base import ScoringPlugin\n"
        "class Rogue(ScoringPlugin):\n"
        "    name = 'rogue'\n"
        "    def evaluate(self, p):\n"
        "        return None\n",
        encoding="utf-8",
    )
    plugins = discover_plugins(str(tmp_path))
    names = [p.name for p in plugins]
    assert "rogue" not in names
    assert any(p.name == "aesthetics" for p in plugins)


def test_discover_loads_declared_module(tmp_path: Path) -> None:
    """声明 __flashgaze_plugin__ = True 的自定义插件被正常发现（C-03）。"""
    declared = tmp_path / "my_plugin.py"
    declared.write_text(
        "__flashgaze_plugin__ = True\n"
        "from flashgaze.plugins.base import ScoringPlugin, PluginScore\n"
        "class MyPlugin(ScoringPlugin):\n"
        "    name = 'my_custom'\n"
        "    def evaluate(self, img_path):\n"
        "        return PluginScore(name='my_custom', score=10.0)\n",
        encoding="utf-8",
    )
    plugins = discover_plugins(str(tmp_path))
    names = [p.name for p in plugins]
    assert "my_custom" in names
    assert any(isinstance(p, ScoringPlugin) and p.name == "my_custom" for p in plugins)


# ---------- 插件评分顺序修复（M4 顺序 bug）----------


def _pick_valid_path(photo_dir: str) -> str:
    """用插件关闭的基线跑一次，返回任意一张有效图的路径。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert valid, "fixture 中必须有有效图"
    return valid[0].path


def test_plugin_score_reflected_in_selection(
    monkeypatch: pytest.MonkeyPatch, photo_dir: str
) -> None:
    """插件加分后，入选判定必须反映插件后的分数。

    修复前：selected 在 _run_plugins 之前定案，插件加分对入选无效。
    本测试模拟一个把目标图从 60 拉到 95 的插件（其余图保持 60 基线），
    top=1 时目标图应为唯一入选，证明 selected 已基于插件后分数。
    """
    target_path = _pick_valid_path(photo_dir)

    config = _config(directory=photo_dir, enable_plugins=True, top=1)
    scorer = HybridScorer(CVEngine(), None, config)

    # 直接设定插件后分数：目标=95（其余=60），与真实 CV 分差无关，确定性强
    fake = _make_fake_run_plugins(target_path, target_score=95.0, other_score=60.0)
    monkeypatch.setattr(HybridScorer, "_run_plugins", fake)

    results = scorer.score_batch(photo_dir)
    target = next(r for r in results if r.path == target_path)
    assert target.score == 95.0
    assert target.selected is True
    # top=1 仅目标图入选
    selected = [r for r in results if r.selected]
    assert len(selected) == 1
    assert selected[0].path == target_path


def test_plugin_low_score_excluded_from_selection(
    monkeypatch: pytest.MonkeyPatch, photo_dir: str
) -> None:
    """反向验证：插件把目标图降到 50（其余 60 基线）时，top=1 下不应入选。

    与上一个用例互为对照，证明入选确实跟随插件后分数、而非定值。
    """
    target_path = _pick_valid_path(photo_dir)

    config = _config(directory=photo_dir, enable_plugins=True, top=1)
    scorer = HybridScorer(CVEngine(), None, config)

    fake = _make_fake_run_plugins(target_path, target_score=50.0, other_score=60.0)
    monkeypatch.setattr(HybridScorer, "_run_plugins", fake)

    results = scorer.score_batch(photo_dir)
    target = next(r for r in results if r.path == target_path)
    assert target.score == 50.0
    assert target.selected is False


# ---------- 示例插件 Windows 中文路径修复 ----------


def test_plugin_evaluate_chinese_path(fixtures_dir: Path, tmp_path: Path) -> None:
    """示例插件改用 load_image_color 后，中文/全角路径也能正常解码。

    修复前 cv2.imread 在 Windows 中文/全角路径下返回 None 而静默失效；
    现走 Pillow 原生支持 Unicode 路径，evaluate 应正常返回 PluginScore。
    """
    src = fixtures_dir / "sharp.jpg"
    # 含中文与全角括号的目录名，正是 cv2.imread 在 Windows 下的失效场景
    cn_dir = tmp_path / "测试目录（样例）"
    cn_dir.mkdir()
    dst = cn_dir / "测试图.jpg"
    shutil.copy2(src, dst)
    plugin = AestheticsPlugin()
    r = plugin.evaluate(str(dst))
    assert isinstance(r, PluginScore)
    assert 0.0 <= r.score <= 100.0
    assert r.name == "aesthetics"


# ---------- H-1：插件分数 / 权重的有限性与区间校验 ----------


class _FixedPlugin(ScoringPlugin):
    """固定返回 (score, weight) 的测试插件，用于注入非法值或边界值。"""

    def __init__(self, score: float, weight: float, name: str = "fixed") -> None:
        self.name = name
        self._score = score
        self._weight = weight

    def evaluate(self, img_path: str) -> PluginScore | None:
        return PluginScore(name=self.name, score=self._score, weight=self._weight)


# 单图累计插件增量的预期上限，须与 hybrid_scorer.PLUGIN_MAX_TOTAL_ADDED 保持一致
_EXPECTED_TOTAL_CAP = 30.0


def _scores_with_plugins(
    monkeypatch: pytest.MonkeyPatch,
    photo_dir: str,
    plugins: list[ScoringPlugin],
) -> dict[str, float]:
    """注入指定插件跑一次批量评分，返回 {图片路径: 最终分}。

    `_run_plugins` 内部是函数级 `from flashgaze.plugins import discover_plugins`，
    故 monkeypatch 目标必须是 `flashgaze.plugins.discover_plugins`（不是本模块导入的别名）。
    传空列表即「插件不存在」的基线，与带插件的运行走完全相同的代码路径，便于逐位比对。
    """

    def _fake_discover(plugin_dir: str | None = None) -> list[ScoringPlugin]:
        return list(plugins)

    monkeypatch.setattr("flashgaze.plugins.discover_plugins", _fake_discover)
    config = _config(directory=photo_dir, enable_plugins=True)
    scorer = HybridScorer(CVEngine(), None, config)
    results = scorer.score_batch(photo_dir)
    return {r.path: r.score for r in results}


def _assert_not_saturated(scores: dict[str, float], baseline: dict[str, float]) -> None:
    """校验「全批并列满分 100」这一 H-1 症状未出现。

    修复前 NaN/Inf 经 `min(100.0, nan)` 恒假兜底，所有图被钳成 100.0 并列；
    基线（无插件）本身不应是并列 100，故二者结合可钉死该症状。
    """
    assert baseline, "photo_dir 中必须有被评分的图"
    # 基线里至少要有一张非满分图，否则「不并列 100」的断言失去意义
    assert any(s != 100.0 for s in baseline.values())
    assert not all(s == 100.0 for s in scores.values())


def test_plugin_nan_score_skipped(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """H-1 回归：插件返回 NaN 分数时该次返回值不参与计分。

    修复前：`min(100.0, nan)` 恒返回 100.0，全批图并列满分、排序退化为按文件名。
    修复后：NaN 不可采信，分数与「无插件」基线逐位一致。
    """
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(float("nan"), 0.5)])
    assert scores == baseline
    _assert_not_saturated(scores, baseline)


def test_plugin_inf_score_skipped(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """H-1 回归：插件返回 ±inf 分数时该次返回值不参与计分（与 NaN 同路）。"""
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    for inf in (float("inf"), float("-inf")):
        scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(inf, 0.5)])
        assert scores == baseline
        _assert_not_saturated(scores, baseline)


def test_plugin_non_finite_weight_skipped(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """H-1 回归：分数合规但权重为 NaN/inf 时同样不参与计分。"""
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    for bad_weight in (float("nan"), float("inf"), float("-inf")):
        scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(50.0, bad_weight)])
        assert scores == baseline
        _assert_not_saturated(scores, baseline)


@pytest.mark.parametrize("bad_score", [1e9, -5.0])
def test_plugin_out_of_range_score_skipped(
    monkeypatch: pytest.MonkeyPatch, photo_dir: str, bad_score: float
) -> None:
    """H-1 回归：有限但越界（score 不在 0-100）的分数不参与计分。

    越界值按「违反契约」处理（跳过而非钳制）：钳制 1e9 → 100 仍会让全批并列满分。
    """
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(bad_score, 0.5)])
    assert scores == baseline
    _assert_not_saturated(scores, baseline)


def test_plugin_excessive_weight_skipped(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """H-1 回归：|weight| 超过约定上限（1e9）时不参与计分。"""
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    for bad_weight in (1e9, -1e9):
        scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(50.0, bad_weight)])
        assert scores == baseline
        _assert_not_saturated(scores, baseline)


def test_plugin_total_added_capped(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """H-1 回归：单图累计插件增量封顶（两个合规插件各 +100 → 累计仅 +30）。

    单个插件的返回值都合规（score=100、weight=1.0），叠加才是风险来源：
    修复前每张图 +200 后被钳成 100，全批并列满分。
    """
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    plugins: list[ScoringPlugin] = [
        _FixedPlugin(100.0, 1.0, name="cap_a"),
        _FixedPlugin(100.0, 1.0, name="cap_b"),
    ]
    scores = _scores_with_plugins(monkeypatch, photo_dir, plugins)
    deltas = [scores[p] - baseline[p] for p in baseline]
    assert all(d <= _EXPECTED_TOTAL_CAP + 1e-9 for d in deltas)
    # 至少一张低分图吃满封顶（增量恰为 +30），证明上限真实生效而非被 0-100 钳制掩盖
    assert any(abs(d - _EXPECTED_TOTAL_CAP) < 1e-9 for d in deltas)


def test_plugin_invalid_score_warns_once(
    monkeypatch: pytest.MonkeyPatch,
    photo_dir: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """H-1 回归：违规返回值须告警，且同一插件在同一批次内只告警一次（不刷屏）。

    photo_dir 有 4 张图，4 次违规应只产生 1 条 WARNING。
    """
    with caplog.at_level(logging.WARNING, logger="flashgaze"):
        _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(float("nan"), 0.5)])
    warnings = [r for r in caplog.records if "违反评分契约" in r.message]
    assert len(warnings) == 1
    assert "fixed" in warnings[0].message


def test_plugin_valid_score_applied(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """防误伤对照（**非**回归用例，修复前后均应通过）：合规插件加分结果逐位不变。

    score=100.0 / weight=0.1 → 每图 +10；最终分仍钳在 0-100。
    本用例锁定「校验不得误伤合规插件」，与 H-1 回归用例互为对照。
    """
    baseline = _scores_with_plugins(monkeypatch, photo_dir, [])
    added = 100.0 * 0.1  # 与生产同式：score * weight
    scores = _scores_with_plugins(monkeypatch, photo_dir, [_FixedPlugin(100.0, 0.1)])
    for path, base in baseline.items():
        expected = round(max(0.0, min(100.0, base + added)), 2)
        assert scores[path] == expected

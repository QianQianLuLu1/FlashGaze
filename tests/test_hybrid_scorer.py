"""HybridScorer 测试。

用真实 CVEngine（确定性）+ mock VLMClient，验证合并逻辑、权重、并发、选取。
测试目录用 tmp_path + 复制 fixture 图，避免污染 fixtures 目录。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config, CVResult, ImageScore, VLMResult


def _config(**overrides) -> Config:
    """构造测试用 Config，默认 no_vlm=True（纯 CV，可复现）。"""
    base = dict(
        directory=".",
        top=30,
        no_vlm=True,
        weights={"sharpness": 0.5, "exposure": 0.5},
    )
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/dark/corrupted 到临时目录，作为评分目标。"""
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


# ---------- score_batch 基础 ----------

def test_score_batch_returns_sorted_descending(photo_dir: str):
    """结果按综合分降序排列。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    assert len(results) == 4
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_score_batch_empty_directory_returns_empty(tmp_path: str):
    """空目录返回空列表。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path)))
    assert scorer.score_batch(str(tmp_path)) == []


def test_score_batch_nonexistent_directory_returns_empty():
    """不存在的目录返回空列表。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory="nonexistent"))
    assert scorer.score_batch("nonexistent") == []


# ---------- 异常处理 ----------

def test_score_batch_handles_corrupted_image(photo_dir: str):
    """corrupted.jpg 不中断流程，标记 error 且 score=0。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    corrupted = [r for r in results if r.file == "corrupted.jpg"]
    assert len(corrupted) == 1
    assert corrupted[0].error is not None
    assert corrupted[0].score == 0.0


# ---------- 选取逻辑 ----------

def test_top_selection(photo_dir: str):
    """top=2 时，前 2 名有效图被选中，corrupted 不选中。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, top=2))
    results = scorer.score_batch(photo_dir)
    selected = [r for r in results if r.selected]
    assert len(selected) == 2
    # corrupted 不应被选中
    assert all(r.error is None for r in selected)


def test_threshold_selection(photo_dir: str):
    """threshold 模式：高于阈值的全部选中。"""
    scorer = HybridScorer(
        CVEngine(), None, _config(directory=photo_dir, threshold=50.0)
    )
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None:
            assert r.selected == (r.score >= 50.0)
        else:
            assert r.selected is False


def test_top_larger_than_valid_count(photo_dir: str):
    """top > 有效图数时，全部有效图选中。"""
    scorer = HybridScorer(
        CVEngine(), None, _config(directory=photo_dir, top=100)
    )
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    selected = [r for r in results if r.selected]
    assert len(selected) == len(valid)


# ---------- VLM 微调 ----------

def test_vlm_adjustment_applied(photo_dir: str):
    """VLM 补偿被加到最终分数上。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(adjustment=5.0, reason="艺术虚化", ok=True)
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    # 有效图的 vlm_adjustment 应为 5.0
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_adjustment == 5.0 for r in valid)


def test_vlm_failure_falls_back_to_cv_only(photo_dir: str):
    """VLM 调用失败时，vlm_adjustment=0，不中断。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=0.0, reason="失败", ok=False, error="timeout"
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_adjustment == 0.0 for r in valid)


# ---------- VLM 可解释性字段透传（M4）----------

def test_vlm_success_propagates_reason_and_provider(photo_dir: str):
    """VLM 成功时 ImageScore.vlm_reason / vlm_provider 被填充。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=5.0, reason="背景虚化", ok=True,
        provider="qwen", scene="portrait",
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_reason == "背景虚化" for r in valid)
    assert all(r.vlm_provider == "qwen" for r in valid)
    assert all(r.vlm_adjustment == 5.0 for r in valid)


def test_vlm_failure_empty_reason_and_provider(photo_dir: str):
    """VLM 失败时 ImageScore.vlm_reason / vlm_provider 为空串。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=0.0, reason="失败", ok=False, error="timeout",
        provider="qwen", scene="auto",
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    # 失败时 vlm_adj 归零，reason/provider 为空串（向后兼容）
    assert all(r.vlm_adjustment == 0.0 for r in valid)
    assert all(r.vlm_reason == "" for r in valid)
    assert all(r.vlm_provider == "" for r in valid)


def test_no_vlm_mode_empty_reason_and_provider(photo_dir: str):
    """--no-vlm 模式下 vlm_reason / vlm_provider 为空串。"""
    config = _config(directory=photo_dir, no_vlm=True)
    scorer = HybridScorer(CVEngine(), None, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_reason == "" for r in valid)
    assert all(r.vlm_provider == "" for r in valid)
    assert all(r.vlm_adjustment == 0.0 for r in valid)


def test_score_clamped_to_0_100(photo_dir: str):
    """VLM 补偿导致超范围时 clamp 到 0-100。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(adjustment=100.0, reason="过补", ok=True)
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    assert all(0.0 <= r.score <= 100.0 for r in results)


# ---------- 权重 ----------

def test_weighted_score_with_default_weights(photo_dir: str):
    """默认权重 0.5/0.5 时，综合分 = 0.5*sharpness + 0.5*exposure（无 VLM）。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None:
            expected = round(0.5 * r.sharpness + 0.5 * r.exposure, 2)
            assert r.score == expected


def test_weighted_score_with_composition_normalized(photo_dir: str):
    """启用 composition 且三维权重时，综合分 = 加权和 / 权重和（归一化）。"""
    weights = {"sharpness": 0.4, "exposure": 0.4, "composition": 0.2}
    config = _config(
        directory=photo_dir, enable_composition=True, weights=weights
    )
    scorer = HybridScorer(CVEngine(enable_composition=True), None, config)
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None and r.composition is not None:
            expected = round(
                (r.sharpness * 0.4 + r.exposure * 0.4 + r.composition * 0.2) / 1.0, 2
            )
            assert r.score == expected, f"权重归一化失败: {r.file}"



# ---------- 可复现性 ----------

def test_score_batch_is_deterministic_without_vlm(photo_dir: str):
    """no_vlm 模式下，连续 10 次评分结果完全一致。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    runs = [scorer.score_batch(photo_dir) for _ in range(10)]
    base_scores = [(r.file, r.score) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score) for r in run] == base_scores

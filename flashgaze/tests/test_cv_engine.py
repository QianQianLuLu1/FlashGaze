"""CVEngine 测试。

覆盖 sharpness / exposure / composition / evaluate。
"""

from __future__ import annotations

from flashgaze.core.cv_engine import CVEngine
from flashgaze.utils.image_io import ImageReadError


# ---------- 清晰度 ----------

def test_sharpness_returns_float_in_range(sharp_img: str):
    """清晰度返回 0-100 的 float。"""
    score = CVEngine().compute_sharpness(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_sharp_image_scores_higher_than_blurry(sharp_img: str, blurry_img: str):
    """高频噪声图的清晰度必须显著高于强模糊图。"""
    engine = CVEngine()
    sharp_score = engine.compute_sharpness(sharp_img)
    blurry_score = engine.compute_sharpness(blurry_img)
    assert sharp_score > blurry_score
    assert sharp_score > 80.0
    assert blurry_score < 20.0


def test_sharpness_is_deterministic(sharp_img: str):
    """同一张图多次调用清晰度必须完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_sharpness(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"清晰度不稳定: {scores}"


# ---------- 曝光度 ----------

def test_exposure_returns_float_in_range(sharp_img: str):
    """曝光度返回 0-100 的 float。"""
    score = CVEngine().compute_exposure(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_dark_image_gets_low_exposure(dark_img: str):
    """全黑图像素全在极端暗区，曝光分应接近 0。"""
    score = CVEngine().compute_exposure(dark_img)
    assert score < 5.0, f"全黑图曝光分应极低，实际: {score}"


def test_exposure_is_deterministic(sharp_img: str):
    """曝光度可复现。"""
    engine = CVEngine()
    scores = [engine.compute_exposure(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"曝光度不稳定: {scores}"


# ---------- 构图 ----------

def test_composition_returns_float_in_range(sharp_img: str):
    """构图分返回 0-100 的 float。"""
    score = CVEngine().compute_composition(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_composition_is_deterministic(sharp_img: str):
    """构图分可复现。"""
    engine = CVEngine()
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"构图分不稳定: {scores}"


# ---------- evaluate 汇总 ----------

def test_evaluate_without_composition(sharp_img: str):
    """evaluate 默认不启用构图，composition 应为 None。"""
    result = CVEngine(enable_composition=False).evaluate(sharp_img)
    assert result.error is None
    assert result.composition is None
    assert result.sharpness > 0
    assert result.exposure >= 0


def test_evaluate_with_composition(sharp_img: str):
    """启用构图时 composition 非 None。"""
    result = CVEngine(enable_composition=True).evaluate(sharp_img)
    assert result.error is None
    assert result.composition is not None


def test_evaluate_handles_corrupted_image(corrupted_img: str):
    """损坏图 evaluate 返回带 error 的 CVResult，不抛异常。"""
    result = CVEngine().evaluate(corrupted_img)
    assert result.error is not None
    assert result.sharpness == 0.0

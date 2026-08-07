"""CVEngine 色彩丰富度评分测试（M3）。

覆盖 HSV 直方图分布算法：色彩多样图 > 纯灰图，分数范围 [0, 100]，
启用开关与默认行为一致性。
"""

from __future__ import annotations

from flashgaze.core.cv_engine import CVEngine


# ---------- 范围与类型 ----------

def test_color_returns_float_in_range(colorful_img: str):
    """色彩丰富度返回 0-100 的 float。"""
    score = CVEngine().compute_color_richness(colorful_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


# ---------- 算法正确性 ----------

def test_colorful_scores_higher_than_gray(colorful_img: str, gray_img: str):
    """多色块图色彩丰富度必须显著高于纯灰图。"""
    engine = CVEngine()
    colorful_score = engine.compute_color_richness(colorful_img)
    gray_score = engine.compute_color_richness(gray_img)
    assert colorful_score > gray_score
    assert colorful_score > 50.0  # 多色块应有较高分


def test_gray_image_score_is_zero(gray_img: str):
    """纯灰图饱和度=0，色彩丰富度应为 0.0。"""
    score = CVEngine().compute_color_richness(gray_img)
    assert score == 0.0


# ---------- 可复现性 ----------

def test_color_is_deterministic(colorful_img: str):
    """色彩丰富度 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_color_richness(colorful_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"色彩丰富度不稳定: {scores}"


# ---------- evaluate 集成 ----------

def test_evaluate_without_color_returns_none(sharp_img: str):
    """未启用色彩维度时，evaluate 的 color 字段为 None。"""
    result = CVEngine(enable_color=False).evaluate(sharp_img)
    assert result.error is None
    assert result.color is None


def test_evaluate_with_color_returns_score(sharp_img: str):
    """启用色彩维度时，evaluate 的 color 字段非 None。"""
    result = CVEngine(enable_color=True).evaluate(sharp_img)
    assert result.error is None
    assert result.color is not None
    assert 0.0 <= result.color <= 100.0


def test_evaluate_with_color_does_not_affect_default(sharp_img: str):
    """enable_color=False 时 evaluate 行为与未启用时完全一致。"""
    engine_off = CVEngine(enable_color=False)
    engine_on = CVEngine(enable_color=True)
    off_result = engine_off.evaluate(sharp_img)
    on_result = engine_on.evaluate(sharp_img)
    # 清晰度/曝光度/构图/error 必须一致
    assert off_result.sharpness == on_result.sharpness
    assert off_result.exposure == on_result.exposure
    assert off_result.composition == on_result.composition
    assert off_result.error == on_result.error

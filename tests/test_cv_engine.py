"""CVEngine 测试。

覆盖 sharpness / exposure / composition / evaluate。
"""

from __future__ import annotations

import cv2
import numpy as np

from flashgaze.core.cv_engine import CVEngine
from flashgaze.defaults import EXPOSURE_BRIGHT_THRESHOLD, EXPOSURE_DARK_THRESHOLD
from flashgaze.utils.image_io import ImageReadError, load_image_grayscale

# cv2.saliency 模块探测（仅 opencv-contrib-python 提供）
_HAS_SALIENCY = hasattr(cv2, "saliency")


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


def test_exposure_boundary_excludes_threshold(tmp_path):
    """C-06：边界语义为"不含阈值本身"。

    构造一张全 EXPOSURE_BRIGHT_THRESHOLD(225) 值的图：
    - 旧逻辑 hist[BRIGHT:] 会把 225 算入 over_bright → 曝光分低
    - 新逻辑 hist[BRIGHT+1:] 不含 225 → 225 属于 mid 区 → 曝光分高
    """
    boundary = EXPOSURE_BRIGHT_THRESHOLD  # 225
    img = np.full((64, 64), boundary, dtype=np.uint8)
    p = str(tmp_path / "boundary.png")
    cv2.imwrite(p, img)
    score = CVEngine().compute_exposure(p)
    # 225 属于中间灰度，曝光分应较高（不被判为过曝）
    assert score > 60.0, f"边界值 {boundary} 应属中间灰度，曝光分应高，实际: {score}"


def test_exposure_boundary_dark_threshold(tmp_path):
    """C-06：DARK_THRESHOLD(30) 边界——值为 30 不算过暗。"""
    boundary = EXPOSURE_DARK_THRESHOLD  # 30
    img = np.full((64, 64), boundary, dtype=np.uint8)
    p = str(tmp_path / "dark_boundary.png")
    cv2.imwrite(p, img)
    score = CVEngine().compute_exposure(p)
    # 30 属于中间灰度（[:DARK] 不含 30），曝光分应高于全黑图
    black = np.zeros((64, 64), dtype=np.uint8)
    p_black = str(tmp_path / "black.png")
    cv2.imwrite(p_black, black)
    black_score = CVEngine().compute_exposure(p_black)
    assert score > black_score, f"值 {boundary} 不应被算作过暗"


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


# ---------- 三分法（抽取后的私有方法）----------

def test_compute_thirds_returns_float_in_range(sharp_img: str):
    """三分法私有方法返回 0-100 的 float。"""
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._compute_thirds(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_compute_thirds_is_deterministic(sharp_img: str):
    """三分法可复现。"""
    gray = load_image_grayscale(sharp_img)
    engine = CVEngine()
    scores = [engine._compute_thirds(gray) for _ in range(5)]
    assert len(set(scores)) == 1


# ---------- 引导线检测 ----------

def test_leading_lines_returns_float_in_range(sharp_img: str):
    """引导线检测返回 0-100 的 float。"""
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._detect_leading_lines(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_leading_lines_is_deterministic(sharp_img: str):
    """引导线检测可复现。"""
    gray = load_image_grayscale(sharp_img)
    engine = CVEngine()
    scores = [engine._detect_leading_lines(gray) for _ in range(5)]
    assert len(set(scores)) == 1


def test_leading_lines_no_edges_returns_base_score(dark_img: str):
    """无直线的图（全黑）返回基础分 20，不抛异常。"""
    gray = load_image_grayscale(dark_img)
    score = CVEngine()._detect_leading_lines(gray)
    assert score == 20.0


# ---------- 对称性 ----------

def test_symmetry_returns_float_in_range(sharp_img: str):
    """对称性返回 0-100 的 float。"""
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._compute_symmetry(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_symmetry_is_deterministic(sharp_img: str):
    """对称性可复现。"""
    gray = load_image_grayscale(sharp_img)
    scores = [CVEngine()._compute_symmetry(gray) for _ in range(5)]
    assert len(set(scores)) == 1


def test_symmetry_uniform_image_is_perfect(dark_img: str):
    """全黑图（像素完全一致）水平/垂直翻转后差异为 0，对称性满分。"""
    gray = load_image_grayscale(dark_img)
    score = CVEngine()._compute_symmetry(gray)
    assert score == 100.0


# ---------- 显著性 ----------

def test_saliency_behavior_adapts_to_cv2_availability(sharp_img: str):
    """saliency 行为随 cv2.saliency 模块可用性自适应：
    - 可用（opencv-contrib-python）→ 返回 0-100 float
    - 不可用（仅 opencv-python）→ 返回 None
    """
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._compute_saliency(gray)
    if _HAS_SALIENCY:
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0
    else:
        assert score is None


def test_saliency_is_deterministic(sharp_img: str):
    """saliency 可复现（可用时返回相同 float，不可用时返回相同 None）。"""
    gray = load_image_grayscale(sharp_img)
    scores = [CVEngine()._compute_saliency(gray) for _ in range(5)]
    assert len(set(scores)) == 1


# ---------- 综合构图（增强后）----------

def test_composition_still_in_range_after_enhancement(sharp_img: str):
    """增强后的构图分仍在 0-100 范围内。"""
    score = CVEngine(enable_composition=True).compute_composition(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_composition_is_deterministic_after_enhancement(sharp_img: str):
    """增强后的构图分 10 次调用完全一致（确定性算法保证）。"""
    engine = CVEngine(enable_composition=True)
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"构图分不稳定: {scores}"


def test_composition_works_on_dark_image(dark_img: str):
    """全黑图也能正常评分（不抛异常，返回 0-100）。"""
    score = CVEngine(enable_composition=True).compute_composition(dark_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

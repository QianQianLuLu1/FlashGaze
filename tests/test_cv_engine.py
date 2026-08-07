"""CVEngine 测试。

覆盖 sharpness / exposure / composition / evaluate / 降采样。
"""

from __future__ import annotations

import hashlib

import cv2
import numpy as np

from flashgaze.core.cv_engine import CVEngine
from flashgaze.defaults import (
    DOWNSCALE_THRESHOLD,
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
)
from flashgaze.utils.image_io import ImageReadError, downscale_if_needed


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


# ---------- 降采样 ----------
# 大图（长边 > DOWNSCALE_THRESHOLD）评分时启用降采样以降低内存占用。
# 以下测试验证：1) 辅助函数行为正确；2) 降采样前后评分相对排序不变；
# 3) 降采样不修改原文件。

_LARGE_LONG_SIDE = 3000  # 大于 DOWNSCALE_THRESHOLD(2048)，触发降采样


def _make_large_noise_img(path: str, size: tuple[int, int], seed: int) -> None:
    """生成大尺寸高频噪声图（高拉普拉斯方差，清晰度高）。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=size, dtype=np.uint8)
    cv2.imwrite(path, noise)


def _make_large_blurry_img(path: str, size: tuple[int, int], seed: int) -> None:
    """生成大尺寸强模糊图（低拉普拉斯方差，清晰度低）。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=size, dtype=np.uint8)
    blurred = cv2.GaussianBlur(noise, (51, 51), 0)
    cv2.imwrite(path, blurred)


def _make_large_dark_img(path: str, size: tuple[int, int]) -> None:
    """生成大尺寸全黑图（曝光度极低）。"""
    cv2.imwrite(path, np.zeros(size, dtype=np.uint8))


def _make_large_midgray_img(path: str, size: tuple[int, int]) -> None:
    """生成大尺寸中间灰度图（曝光度良好）。"""
    cv2.imwrite(path, np.full(size, 128, dtype=np.uint8))


def _file_hash(path: str) -> str:
    """计算文件 SHA256，用于验证降采样不修改原文件。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ----- downscale_if_needed 辅助函数 -----

def test_downscale_if_needed_none_disables():
    """max_long_side=None 时返回原数组（不降采样）。"""
    img = np.zeros((100, 100), dtype=np.uint8)
    result = downscale_if_needed(img, None)
    assert result is img  # 同一对象


def test_downscale_if_needed_small_image_unchanged():
    """长边未超阈值时返回原数组。"""
    img = np.zeros((100, 200), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    assert result is img  # 长边 200 < 2048，原样返回


def test_downscale_if_needed_scales_large_image():
    """长边超阈值时按比例缩小到阈值。"""
    img = np.zeros((1000, 3000), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    assert result.shape[0] < 1000 or result.shape[1] < 3000  # 至少一边缩小
    assert max(result.shape) <= 2048  # 长边不超阈值


def test_downscale_if_needed_preserves_aspect_ratio():
    """降采样保持宽高比。"""
    h, w = 2000, 3000
    img = np.zeros((h, w), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    orig_ratio = w / h
    new_h, new_w = result.shape[:2]
    new_ratio = new_w / new_h
    assert abs(orig_ratio - new_ratio) < 0.01  # 宽高比基本不变


def test_downscale_if_needed_does_not_mutate_input():
    """降采样不修改输入数组（返回新数组）。"""
    img = np.full((3000, 3000), 128, dtype=np.uint8)
    _ = downscale_if_needed(img, 2048)
    assert img.shape == (3000, 3000)  # 原数组尺寸不变
    assert (img == 128).all()  # 原数组内容不变


# ----- CVEngine 降采样开关 -----

def test_cv_engine_default_enables_downscale():
    """CVEngine() 默认启用降采样（_eval_max_long_side 为阈值）。"""
    engine = CVEngine()
    assert engine._eval_max_long_side == DOWNSCALE_THRESHOLD


def test_cv_engine_downscale_false_disables():
    """downscale=False 时禁用降采样（_eval_max_long_side 为 None）。"""
    engine = CVEngine(downscale=False)
    assert engine._eval_max_long_side is None


# ----- 清晰度评分：降采样前后排序一致性 -----

def test_sharpness_ranking_preserved_with_downscale(tmp_path):
    """降采样前后清晰度相对排序不变：清晰图 > 模糊图 在两种模式下均成立。"""
    sharp_p = str(tmp_path / "large_sharp.jpg")
    blurry_p = str(tmp_path / "large_blurry.jpg")
    size = (_LARGE_LONG_SIDE, 2000)
    _make_large_noise_img(sharp_p, size, seed=42)
    _make_large_blurry_img(blurry_p, size, seed=42)

    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    sharp_on = engine_on.compute_sharpness(sharp_p)
    blurry_on = engine_on.compute_sharpness(blurry_p)
    sharp_off = engine_off.compute_sharpness(sharp_p)
    blurry_off = engine_off.compute_sharpness(blurry_p)

    # 两种模式下清晰图分数都必须高于模糊图
    assert sharp_on > blurry_on, f"降采样模式排序异常: sharp={sharp_on} blurry={blurry_on}"
    assert sharp_off > blurry_off, f"原分辨率模式排序异常: sharp={sharp_off} blurry={blurry_off}"


def test_sharpness_score_consistency_downscale_vs_original(tmp_path):
    """降采样与原分辨率的清晰度分数接近（双重缩放偏差可控）。"""
    img_p = str(tmp_path / "large_sharp.jpg")
    _make_large_noise_img(img_p, (_LARGE_LONG_SIDE, 2000), seed=42)

    score_on = CVEngine(downscale=True).compute_sharpness(img_p)
    score_off = CVEngine(downscale=False).compute_sharpness(img_p)

    # 两种模式最终都归一化到 SHARPNESS_NORMALIZE_SIZE(1024)，
    # 两步缩放 vs 一步缩放的拉普拉斯方差差异应在 10 分以内
    assert abs(score_on - score_off) < 10.0, (
        f"降采样前后清晰度分数差异过大: downscale={score_on} original={score_off}"
    )


# ----- 曝光度评分：降采样前后排序一致性 -----

def test_exposure_ranking_preserved_with_downscale(tmp_path):
    """降采样前后曝光度相对排序不变：中间灰度图 > 全黑图 在两种模式下均成立。"""
    midgray_p = str(tmp_path / "large_midgray.jpg")
    dark_p = str(tmp_path / "large_dark.jpg")
    size = (_LARGE_LONG_SIDE, 2000)
    _make_large_midgray_img(midgray_p, size)
    _make_large_dark_img(dark_p, size)

    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    mid_on = engine_on.compute_exposure(midgray_p)
    dark_on = engine_on.compute_exposure(dark_p)
    mid_off = engine_off.compute_exposure(midgray_p)
    dark_off = engine_off.compute_exposure(dark_p)

    assert mid_on > dark_on, f"降采样模式曝光排序异常: mid={mid_on} dark={dark_on}"
    assert mid_off > dark_off, f"原分辨率模式曝光排序异常: mid={mid_off} dark={dark_off}"


def test_exposure_score_consistency_downscale_vs_original(tmp_path):
    """降采样与原分辨率的曝光度分数高度一致（直方图分布近似不变）。"""
    img_p = str(tmp_path / "large_midgray.jpg")
    _make_large_midgray_img(img_p, (_LARGE_LONG_SIDE, 2000))

    score_on = CVEngine(downscale=True).compute_exposure(img_p)
    score_off = CVEngine(downscale=False).compute_exposure(img_p)

    # 曝光度基于直方图分布，降采样仅是子采样，分布近似不变
    assert abs(score_on - score_off) < 1.0, (
        f"降采样前后曝光度分数差异过大: downscale={score_on} original={score_off}"
    )


# ----- 降采样不修改原文件 -----

def test_downscale_does_not_modify_original_file(tmp_path):
    """评分（含降采样）后原图片文件字节不变。"""
    img_p = str(tmp_path / "large_sharp.jpg")
    _make_large_noise_img(img_p, (_LARGE_LONG_SIDE, 2000), seed=42)

    before = _file_hash(img_p)
    _ = CVEngine(downscale=True).evaluate(img_p)
    after = _file_hash(img_p)

    assert before == after, "降采样评分修改了原图片文件"


# ----- 小图（长边 <= 2048）降采样不生效 -----

def test_small_image_scores_identical_with_or_without_downscale(sharp_img: str):
    """小图（512x512）降采样开关不影响评分（两种模式分数完全一致）。"""
    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    assert engine_on.compute_sharpness(sharp_img) == engine_off.compute_sharpness(sharp_img)
    assert engine_on.compute_exposure(sharp_img) == engine_off.compute_exposure(sharp_img)

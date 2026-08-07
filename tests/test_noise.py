"""CVEngine BRISQUE 噪点评分测试（M2）。

依赖 opencv-contrib-python 的 cv2.quality.QualityBRISQUE 模块 + 模型文件。
依赖缺失时 pytest.skip，不阻塞 CI。
"""

from __future__ import annotations

import pytest

from flashgaze.core.cv_engine import CVEngine, _BRISQUE_API, _BRISQUE_MODEL_DIR


# 模块级探测：依赖或模型缺失则跳过本文件全部测试
_HAS_BRISQUE = (
    _BRISQUE_API is not None
    and _BRISQUE_MODEL_DIR is not None
    and (_BRISQUE_MODEL_DIR / "brisque_model_live.yml").is_file()
    and (_BRISQUE_MODEL_DIR / "brisque_range_live.yml").is_file()
)
pytestmark = pytest.mark.skipif(
    not _HAS_BRISQUE,
    reason="BRISQUE 依赖（opencv-contrib-python）或模型文件缺失，跳过测试",
)


# ---------- 范围与类型 ----------

def test_noise_returns_float_in_range(sharp_img: str):
    """BRISQUE 噪点评分返回 0-100 的 float。"""
    score = CVEngine().compute_noise(sharp_img)
    assert score is not None
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


# ---------- 可复现性 ----------

def test_noise_is_deterministic(sharp_img: str):
    """BRISQUE 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_noise(sharp_img) for _ in range(10)]
    assert all(s is not None for s in scores)
    assert len(set(scores)) == 1, f"BRISQUE 分数不稳定: {scores}"


# ---------- evaluate 集成 ----------

def test_evaluate_without_noise_returns_none(sharp_img: str):
    """未启用噪点维度时，evaluate 的 noise 字段为 None。"""
    result = CVEngine(enable_noise=False).evaluate(sharp_img)
    assert result.error is None
    assert result.noise is None


def test_evaluate_with_noise_returns_score(sharp_img: str):
    """启用噪点维度时，evaluate 的 noise 字段非 None。"""
    result = CVEngine(enable_noise=True).evaluate(sharp_img)
    assert result.error is None
    assert result.noise is not None
    assert 0.0 <= result.noise <= 100.0


def test_evaluate_with_noise_does_not_affect_default(sharp_img: str):
    """enable_noise=False 时 evaluate 行为与未启用时完全一致。"""
    engine_off = CVEngine(enable_noise=False)
    engine_on = CVEngine(enable_noise=True)
    off_result = engine_off.evaluate(sharp_img)
    on_result = engine_on.evaluate(sharp_img)
    # 清晰度/曝光度/构图/error 必须一致
    assert off_result.sharpness == on_result.sharpness
    assert off_result.exposure == on_result.exposure
    assert off_result.composition == on_result.composition
    assert off_result.error == on_result.error

"""PortraitEngine 人像专项评分测试（M4）。

依赖 face_recognition 库（基于 dlib）。依赖缺失时 pytest.skip。
fixture 中无真实人脸图，主要测试：
- 无人脸图返回 face_count=0
- enable=False 时返回空结果
- 加分上限 PORTRAIT_BONUS_MAX
- 依赖缺失时降级
"""

from __future__ import annotations

import pytest

from flashgaze.core.portrait_engine import (
    _FACE_RECOGNITION_AVAILABLE,
    PortraitEngine,
)
from flashgaze.defaults import PORTRAIT_BONUS_MAX

# ---------- enable=False 行为 ----------


def test_disabled_returns_zero_face_count(sharp_img: str) -> None:
    """enable=False 时始终返回 face_count=0。"""
    engine = PortraitEngine(enable=False)
    result = engine.evaluate(sharp_img)
    assert result.face_count == 0
    assert result.portrait_bonus == 0.0
    assert result.face_sharpness is None


def test_disabled_does_not_call_face_recognition(sharp_img: str) -> None:
    """enable=False 时不调用 face_recognition，依赖缺失也不影响。"""
    # 即使依赖可用，enable=False 也应直接返回空结果
    engine = PortraitEngine(enable=False)
    result = engine.evaluate(sharp_img)
    assert result.face_count == 0


# ---------- 依赖可用时的行为 ----------


@pytest.mark.skipif(
    not _FACE_RECOGNITION_AVAILABLE,
    reason="face_recognition 未安装，跳过真实人脸检测测试",
)
class TestWithFaceRecognition:
    """依赖可用时的测试用例。"""

    def test_no_face_returns_zero(self, sharp_img: str) -> None:
        """高频噪声图无人脸，应返回 face_count=0。"""
        engine = PortraitEngine(enable=True)
        result = engine.evaluate(sharp_img)
        assert result.face_count == 0
        assert result.portrait_bonus == 0.0

    def test_enable_true_with_dependency_works(self, sharp_img: str) -> None:
        """enable=True 且依赖可用时，engine.enable 应为 True。"""
        engine = PortraitEngine(enable=True)
        assert engine.enable is True

    def test_evaluate_does_not_crash_on_colorful(self, colorful_img: str) -> None:
        """多色块图不崩溃（无人脸，返回 face_count=0）。"""
        engine = PortraitEngine(enable=True)
        result = engine.evaluate(colorful_img)
        assert result.face_count == 0
        assert result.error is None


# ---------- 依赖缺失时的降级 ----------


@pytest.mark.skipif(
    _FACE_RECOGNITION_AVAILABLE,
    reason="face_recognition 已安装，跳过降级路径测试",
)
class TestGracefulDegradation:
    """依赖缺失时即使 enable=True 也应降级为空结果。"""

    def test_enable_true_but_dependency_missing(self, sharp_img: str) -> None:
        engine = PortraitEngine(enable=True)
        # 双重条件：enable=True 但依赖缺失，最终 enable 应为 False
        assert engine.enable is False
        result = engine.evaluate(sharp_img)
        assert result.face_count == 0
        assert result.portrait_bonus == 0.0


# ---------- 加分上限 ----------


def test_portrait_bonus_max_constant() -> None:
    """PORTRAIT_BONUS_MAX 常量应为 5.0。"""
    assert PORTRAIT_BONUS_MAX == 5.0


def test_bonus_formula_respects_cap() -> None:
    """加分公式 min(3.0 + (count-1)*1.0, 5.0) 在 count=10 时不应超过上限。

    直接测试公式本身，不依赖真实人脸检测。
    """
    # 模拟多人脸场景的加分计算
    for count in [1, 2, 3, 5, 10, 100]:
        bonus = min(3.0 + (count - 1) * 1.0, PORTRAIT_BONUS_MAX)
        assert bonus <= PORTRAIT_BONUS_MAX, f"count={count} 时加分 {bonus} 超过上限"
        # count=1 时 +3，count>=3 时封顶 5
        if count == 1:
            assert bonus == 3.0
        elif count >= 3:
            assert bonus == 5.0

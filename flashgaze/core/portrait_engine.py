"""PortraitEngine：人像专项评分。

基于 face_recognition 库（dlib HOG + SVM 人脸检测）。
依赖缺失时所有方法返回空结果，不阻塞主流程。
"""

from __future__ import annotations

from typing import Any, cast

import cv2
import numpy as np
import numpy.typing as npt

from flashgaze.defaults import PORTRAIT_BONUS_MAX
from flashgaze.models.schemas import PortraitResult
from flashgaze.utils.image_io import load_image_color

# 模块级探测 face_recognition 依赖
# 缺失时 PortraitEngine(enable=True) 也会降级为空结果，不抛异常
try:
    import face_recognition

    _FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    # cast(Any)：装/不装 face_recognition 两种环境下 mypy 都通过（见 mypy overrides）
    face_recognition = cast(Any, None)
    _FACE_RECOGNITION_AVAILABLE = False


class PortraitEngine:
    """人像专项评分引擎。

    依赖 face_recognition 库（基于 dlib）。依赖缺失或 enable=False 时
    evaluate() 返回 face_count=0 的空结果，不阻塞主流程。
    """

    def __init__(self, enable: bool = False) -> None:
        # 双重条件：必须显式启用 且 依赖可用
        self.enable = enable and _FACE_RECOGNITION_AVAILABLE

    def evaluate(
        self,
        img_path: str,
        preloaded_color: npt.NDArray[np.uint8] | None = None,
    ) -> PortraitResult:
        """对单图执行人像专项评估。

        返回 PortraitResult：
        - 无人脸：face_count=0, portrait_bonus=0.0
        - 有人脸：face_count=N, face_sharpness=区域清晰度, portrait_bonus=加分
        - 依赖缺失或异常：返回空结果（face_count=0）

        preloaded_color 为调用方已解码的全分辨率 BGR 数组（与
        load_image_color(img_path) 等价）时直接复用，避免二次磁盘解码；
        为 None 时维持原 load_image_color 路径。enable=False 时不解码、
        不使用该参数，关闭人像的默认路径行为完全不变。
        """
        if not self.enable:
            return PortraitResult(face_count=0)
        try:
            # 复用上游已解码数组（消除二次解码）；None 时退回原路径
            color = preloaded_color if preloaded_color is not None else load_image_color(img_path)
            # face_recognition 期望 RGB 输入
            rgb = color[:, :, ::-1]
            locations = face_recognition.face_locations(rgb, model="hog")
            count = len(locations)
            if count == 0:
                return PortraitResult(face_count=0)
            face_sharpness = self._compute_face_sharpness(color, locations)
            # 首张人脸 +3，每多一张 +1，封顶 PORTRAIT_BONUS_MAX
            bonus = min(3.0 + (count - 1) * 1.0, PORTRAIT_BONUS_MAX)
            return PortraitResult(
                face_count=count,
                face_sharpness=face_sharpness,
                portrait_bonus=bonus,
            )
        except Exception as e:  # noqa: BLE001 — 单图人像评分失败降级为 error 字段，不抛出
            return PortraitResult(face_count=0, error=f"人像评分失败: {e}")

    def _compute_face_sharpness(
        self,
        color: npt.NDArray[np.uint8],
        locations: list[tuple[int, int, int, int]],
    ) -> float:
        """计算人脸区域的清晰度（拉普拉斯方差，归一化到 0-100）。

        locations 是 face_recognition 返回的 (top, right, bottom, left) 元组列表。
        取最大的一张脸评估，避免多人脸时被小脸拉低分数。
        """
        # 选面积最大的人脸。
        # loc = (top, right, bottom, left)，宽 = right - left > 0、高 = bottom - top > 0，
        # 故面积用 (bottom-top)*(right-left)（C-07 修复：原 (left-right) 符号取反，
        # 导致 max() 挑中面积最小脸）。
        top, right, bottom, left = max(
            locations,
            key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]),
        )
        face_region = color[top:bottom, left:right]
        if face_region.size == 0:
            return 0.0
        gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        # float() 收敛 numpy 标量类型（与 compute_sharpness 同因）
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        # 与 compute_sharpness 一致的映射上限
        from flashgaze.defaults import SHARPNESS_VARIANCE_CEIL

        score = min(variance / SHARPNESS_VARIANCE_CEIL * 100.0, 100.0)
        return float(round(score, 2))

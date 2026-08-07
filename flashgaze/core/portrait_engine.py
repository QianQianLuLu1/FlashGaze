"""PortraitEngine：人像专项评分。

基于 face_recognition 库（dlib HOG + SVM 人脸检测）。
依赖缺失时所有方法返回空结果，不阻塞主流程。
"""

from __future__ import annotations

import cv2
import numpy as np

from flashgaze.defaults import PORTRAIT_BONUS_MAX
from flashgaze.models.schemas import PortraitResult
from flashgaze.utils.image_io import load_image_color

# 模块级探测 face_recognition 依赖
# 缺失时 PortraitEngine(enable=True) 也会降级为空结果，不抛异常
try:
    import face_recognition  # type: ignore
    _FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None  # type: ignore
    _FACE_RECOGNITION_AVAILABLE = False


class PortraitEngine:
    """人像专项评分引擎。

    依赖 face_recognition 库（基于 dlib）。依赖缺失或 enable=False 时
    evaluate() 返回 face_count=0 的空结果，不阻塞主流程。
    """

    def __init__(self, enable: bool = False) -> None:
        # 双重条件：必须显式启用 且 依赖可用
        self.enable = enable and _FACE_RECOGNITION_AVAILABLE

    def evaluate(self, img_path: str) -> PortraitResult:
        """对单图执行人像专项评估。

        返回 PortraitResult：
        - 无人脸：face_count=0, portrait_bonus=0.0
        - 有人脸：face_count=N, face_sharpness=区域清晰度, portrait_bonus=加分
        - 依赖缺失或异常：返回空结果（face_count=0）
        """
        if not self.enable:
            return PortraitResult(face_count=0)
        try:
            color = load_image_color(img_path)
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
        except Exception as e:
            return PortraitResult(face_count=0, error=f"人像评分失败: {e}")

    def _compute_face_sharpness(
        self,
        color: np.ndarray,
        locations: list[tuple[int, int, int, int]],
    ) -> float:
        """计算人脸区域的清晰度（拉普拉斯方差，归一化到 0-100）。

        locations 是 face_recognition 返回的 (top, right, bottom, left) 元组列表。
        取最大的一张脸评估，避免多人脸时被小脸拉低分数。
        """
        # 选面积最大的人脸
        top, right, bottom, left = max(
            locations,
            key=lambda loc: (loc[2] - loc[0]) * (loc[3] - loc[1]),
        )
        face_region = color[top:bottom, left:right]
        if face_region.size == 0:
            return 0.0
        gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        # 与 compute_sharpness 一致的映射上限
        from flashgaze.defaults import SHARPNESS_VARIANCE_CEIL
        score = min(variance / SHARPNESS_VARIANCE_CEIL * 100.0, 100.0)
        return float(round(score, 2))

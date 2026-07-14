"""CVEngine：客观评分引擎。

清晰度（拉普拉斯方差）、曝光度（直方图分布）、构图（三分法，实验性）。
所有方法对同一图片多次调用结果恒定（无随机性），保证可复现。
"""

from __future__ import annotations

import cv2

from flashgaze.defaults import (
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    SHARPNESS_VARIANCE_CEIL,
)
from flashgaze.models.schemas import CVResult
from flashgaze.utils.image_io import ImageReadError, load_image_color, load_image_grayscale


class CVEngine:
    """CV 客观评分引擎。"""

    def __init__(self, enable_composition: bool = False):
        self.enable_composition = enable_composition

    def evaluate(self, img_path: str) -> CVResult:
        """对单图执行完整 CV 评估。失败时返回带 error 的 CVResult，不抛异常。"""
        try:
            sharpness = self.compute_sharpness(img_path)
            exposure = self.compute_exposure(img_path)
            composition = (
                self.compute_composition(img_path) if self.enable_composition else None
            )
            return CVResult(sharpness, exposure, composition)
        except ImageReadError as e:
            return CVResult(0.0, 0.0, None, error=str(e))
        except Exception as e:
            return CVResult(0.0, 0.0, None, error=f"CV 评估失败: {e}")

    def compute_sharpness(self, img_path: str) -> float:
        """拉普拉斯方差 → 0-100。方差越大越清晰。

        映射：variance 0 ~ SHARPNESS_VARIANCE_CEIL 线性映射到 0 ~ 100，
        超过 CEIL 封顶 100。
        """
        gray = load_image_grayscale(img_path)
        variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        score = min(variance / SHARPNESS_VARIANCE_CEIL * 100.0, 100.0)
        return float(round(score, 2))

    def compute_exposure(self, img_path: str) -> float:
        """直方图分布 → 0-100。

        理想分布集中在中间灰度区。极端暗（<EXPOSURE_DARK_THRESHOLD）与
        极端亮（>EXPOSURE_BRIGHT_THRESHOLD）的像素占比越低，分越高。
        """
        gray = load_image_grayscale(img_path)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total = hist.sum()
        if total == 0:
            return 0.0
        hist = hist / total
        over_dark = hist[:EXPOSURE_DARK_THRESHOLD].sum()
        over_bright = hist[EXPOSURE_BRIGHT_THRESHOLD:].sum()
        mid_ratio = 1.0 - over_dark - over_bright
        score = max(0.0, mid_ratio * 100.0)
        return float(round(score, 2))

    def compute_composition(self, img_path: str) -> float:
        """三分法（实验性）→ 0-100。

        用 Otsu 阈值分割前景并计算质心，质心越靠近三分线交点分越高。
        无法分割时返回中位分 50。
        """
        color = load_image_color(img_path)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        moments = cv2.moments(thresh)
        if moments["m00"] == 0:
            return 50.0
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
        thirds_x = [w / 3, 2 * w / 3]
        thirds_y = [h / 3, 2 * h / 3]
        min_dist = min(
            abs(cx - tx) + abs(cy - ty) for tx in thirds_x for ty in thirds_y
        )
        diag = (w**2 + h**2) ** 0.5
        score = max(0.0, 100.0 - (min_dist / diag) * 300.0)
        return float(round(score, 2))

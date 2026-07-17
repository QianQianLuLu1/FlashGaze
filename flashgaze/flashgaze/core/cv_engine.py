"""CVEngine：客观评分引擎。

清晰度（拉普拉斯方差 + 尺寸归一化）、曝光度（直方图分布 + 均值偏差）、构图（三分法，实验性）。
所有方法对同一图片多次调用结果恒定（无随机性），保证可复现。
"""

from __future__ import annotations

import cv2
import numpy as np

from flashgaze.defaults import (
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    SHARPNESS_NORMALIZE_SIZE,
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

    def _normalize_size(self, gray: np.ndarray) -> np.ndarray:
        """将图片长边缩放到 SHARPNESS_NORMALIZE_SIZE，消除分辨率对评分的影响。"""
        h, w = gray.shape[:2]
        long_side = max(h, w)
        if long_side <= SHARPNESS_NORMALIZE_SIZE:
            return gray
        scale = SHARPNESS_NORMALIZE_SIZE / long_side
        new_size = (int(w * scale), int(h * scale))
        return cv2.resize(gray, new_size, interpolation=cv2.INTER_AREA)

    def compute_sharpness(self, img_path: str) -> float:
        """拉普拉斯方差 → 0-100。方差越大越清晰。

        先将图片长边归一化到 SHARPNESS_NORMALIZE_SIZE（默认 1024），
        再计算拉普拉斯方差，消除分辨率差异对评分的影响。
        映射：variance 0 ~ SHARPNESS_VARIANCE_CEIL 线性映射到 0 ~ 100，
        超过 CEIL 封顶 100。
        """
        gray = load_image_grayscale(img_path)
        gray = self._normalize_size(gray)
        variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        score = min(variance / SHARPNESS_VARIANCE_CEIL * 100.0, 100.0)
        return float(round(score, 2))

    def compute_exposure(self, img_path: str) -> float:
        """直方图分布 + 均值偏差 → 0-100。

        两部分综合：
        1. 中间灰度像素占比（极端暗/亮越少分越高），权重 0.6
        2. 均值偏离 127.5 的程度（越接近中间灰度分越高），权重 0.4

        比单纯中间灰度占比更能区分欠曝/过曝。
        """
        gray = load_image_grayscale(img_path)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total = hist.sum()
        if total == 0:
            return 0.0
        hist = hist / total
        # 边界语义统一为"不含阈值本身"：dark 区间 [0, DARK)，bright 区间 (BRIGHT, 255]
        # 即 DARK=30 表示 0-29 为暗，BRIGHT=225 表示 226-255 为亮
        over_dark = hist[:EXPOSURE_DARK_THRESHOLD].sum()
        over_bright = hist[EXPOSURE_BRIGHT_THRESHOLD + 1:].sum()
        mid_ratio = 1.0 - over_dark - over_bright

        mean_val = float(gray.mean())
        mean_deviation = abs(mean_val - 127.5) / 127.5
        mean_score = max(0.0, 1.0 - mean_deviation)

        score = (mid_ratio * 0.6 + mean_score * 0.4) * 100.0
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

"""CVEngine：客观评分引擎。

清晰度（拉普拉斯方差 + 尺寸归一化）、曝光度（直方图分布 + 均值偏差）、
构图（三分法 + 引导线 + 对称性 + 显著性，实验性）。
所有方法对同一图片多次调用结果恒定（无随机性），保证可复现。
"""

from __future__ import annotations

import cv2
import numpy as np

from flashgaze.defaults import (
    COMPOSITION_WEIGHT_LEADING_LINES,
    COMPOSITION_WEIGHT_SALIENCY,
    COMPOSITION_WEIGHT_SYMMETRY,
    COMPOSITION_WEIGHT_THIRDS,
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    LEADING_LINES_CANNY_HIGH,
    LEADING_LINES_CANNY_LOW,
    LEADING_LINES_HOUGH_MAX_LINE_GAP,
    LEADING_LINES_HOUGH_MIN_LINE_LEN,
    LEADING_LINES_HOUGH_THRESHOLD,
    SALIENCY_MAP_CEIL,
    SHARPNESS_NORMALIZE_SIZE,
    SHARPNESS_VARIANCE_CEIL,
    SYMMETRY_DIFF_CEIL,
)
from flashgaze.models.schemas import CVResult
from flashgaze.utils.image_io import ImageReadError, load_image_color, load_image_grayscale

# cv2.saliency 模块探测：仅 opencv-contrib-python 提供，项目依赖 opencv-python
# 时该模块不存在。模块级探测一次，避免每张图重复 hasattr 开销。
_SALIENCY_API: object | None = None
try:
    if hasattr(cv2, "saliency"):
        # 优先用标准 API 名 StaticSaliencySpectralResidual_create
        if hasattr(cv2.saliency, "StaticSaliencySpectralResidual_create"):
            _SALIENCY_API = cv2.saliency.StaticSaliencySpectralResidual_create
        # 兼容历史/非标准命名
        elif hasattr(cv2.saliency, "Saliency_staticSpectralResidual_create"):
            _SALIENCY_API = cv2.saliency.Saliency_staticSpectralResidual_create
        elif hasattr(cv2.saliency, "SaliencySpectralResidual_create"):
            _SALIENCY_API = cv2.saliency.SaliencySpectralResidual_create
except Exception:
    _SALIENCY_API = None


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
        """综合构图评分（三分法 + 引导线 + 对称性 + 显著性）→ 0-100。

        四项加权平均：三分法 0.3 + 引导线 0.2 + 对称性 0.2 + 显著性 0.3。
        cv2.saliency 模块不可用时跳过显著性，按 thirds/leading/symmetry
        三项归一化加权（保持权重相对比例）。
        """
        color = load_image_color(img_path)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

        thirds = self._compute_thirds(gray)
        leading = self._detect_leading_lines(gray)
        symmetry = self._compute_symmetry(gray)
        saliency = self._compute_saliency(gray)

        if saliency is None:
            # cv2.saliency 不可用：三项归一化，保持相对权重比例
            total_w = (
                COMPOSITION_WEIGHT_THIRDS
                + COMPOSITION_WEIGHT_LEADING_LINES
                + COMPOSITION_WEIGHT_SYMMETRY
            )
            score = (
                thirds * (COMPOSITION_WEIGHT_THIRDS / total_w)
                + leading * (COMPOSITION_WEIGHT_LEADING_LINES / total_w)
                + symmetry * (COMPOSITION_WEIGHT_SYMMETRY / total_w)
            )
        else:
            score = (
                thirds * COMPOSITION_WEIGHT_THIRDS
                + leading * COMPOSITION_WEIGHT_LEADING_LINES
                + symmetry * COMPOSITION_WEIGHT_SYMMETRY
                + saliency * COMPOSITION_WEIGHT_SALIENCY
            )
        return float(round(min(max(score, 0.0), 100.0), 2))

    def _compute_thirds(self, gray: np.ndarray) -> float:
        """三分法 → 0-100。质心越靠近三分线交点分越高，无法分割返回 50。"""
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

    def _detect_leading_lines(self, gray: np.ndarray) -> float:
        """Canny + HoughLinesP 检测引导线 → 0-100。

        统计直线段方向分布：多条直线汇聚向画面中心区域给高分；
        直线稀少或方向散乱给低分。无直线时给基础分 20（避免过度惩罚
        无直线的场景，如纯天空、纯纹理图）。
        """
        h, w = gray.shape[:2]
        edges = cv2.Canny(gray, LEADING_LINES_CANNY_LOW, LEADING_LINES_CANNY_HIGH)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=LEADING_LINES_HOUGH_THRESHOLD,
            minLineLength=LEADING_LINES_HOUGH_MIN_LINE_LEN,
            maxLineGap=LEADING_LINES_HOUGH_MAX_LINE_GAP,
        )
        if lines is None:
            return 20.0

        cx_img, cy_img = w / 2, h / 2
        diag = (w**2 + h**2) ** 0.5
        converging_count = 0
        total = len(lines)
        for ln in lines:
            # HoughLinesP 返回形状因 OpenCV 版本而异：(N,1,4) 或 (N,4)。
            # ravel 统一展平为 4 元素一维数组。
            x1, y1, x2, y2 = np.ravel(ln)
            # 直线两端到画面中心的平均距离，归一化后判断收敛性
            dist = (
                abs(x1 - cx_img) + abs(y1 - cy_img)
                + abs(x2 - cx_img) + abs(y2 - cy_img)
            ) / 4
            if dist / diag < 0.3:
                converging_count += 1
        # 汇聚比例 + 直线数量共同决定分数
        ratio = converging_count / total if total > 0 else 0
        count_factor = min(total / 10.0, 1.0)  # 10 条直线封顶
        score = (ratio * 0.6 + count_factor * 0.4) * 100.0
        return float(round(min(score, 100.0), 2))

    def _compute_symmetry(self, gray: np.ndarray) -> float:
        """翻转差异计算对称性 → 0-100。

        水平翻转 + 垂直翻转，取两者中较小差异（较高对称性）。
        差异 0 → 满分 100；差异 >= SYMMETRY_DIFF_CEIL → 0 分。
        """
        h_flip = cv2.flip(gray, 1)  # 水平翻转（左右对称检测）
        v_flip = cv2.flip(gray, 0)  # 垂直翻转（上下对称检测）
        diff_h = float(cv2.mean(cv2.absdiff(gray, h_flip))[0])
        diff_v = float(cv2.mean(cv2.absdiff(gray, v_flip))[0])
        min_diff = min(diff_h, diff_v)
        score = max(0.0, 100.0 - (min_diff / SYMMETRY_DIFF_CEIL) * 100.0)
        return float(round(score, 2))

    def _compute_saliency(self, gray: np.ndarray) -> float | None:
        """谱残差显著性检测 → 0-100。

        依赖 cv2.saliency（仅 opencv-contrib-python 提供）。
        项目当前依赖 opencv-python，模块级 _SALIENCY_API 为 None 时
        直接返回 None，由 compute_composition 跳过该维度并按三项归一化。
        """
        if _SALIENCY_API is None:
            return None
        try:
            saliency_obj = _SALIENCY_API()
            # computeSaliency 接收单通道 float32/gray，返回 (success, map)
            success, saliency_map = saliency_obj.computeSaliency(gray)
            if not success or saliency_map is None:
                return None
            # OpenCV saliency 返回 0-1 float 图（部分版本为 0-255）
            sm = np.asarray(saliency_map, dtype=np.float64)
            s_min, s_max = float(sm.min()), float(sm.max())
            if s_max - s_min < 1e-8:
                return 50.0  # 平坦图，无显著区域
            sm_norm = (sm - s_min) / (s_max - s_min)
            mean_sal = float(sm_norm.mean())
            score = min(mean_sal / SALIENCY_MAP_CEIL * 100.0, 100.0)
            return float(round(score, 2))
        except Exception:
            # 任何运行时异常都降级为"不可用"，不破坏评分流程
            return None

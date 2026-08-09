"""CVEngine：客观评分引擎。

清晰度（拉普拉斯方差 + 尺寸归一化）、曝光度（直方图分布 + 均值偏差）、构图（三分法，实验性）。
可选维度：噪点（BRISQUE 无参考 IQA）、色彩丰富度（HSV 直方图分布）。
所有方法对同一图片多次调用结果恒定（无随机性），保证可复现。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from flashgaze.defaults import (
    DOWNSCALE_THRESHOLD,
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    SHARPNESS_NORMALIZE_SIZE,
    SHARPNESS_VARIANCE_CEIL,
)
from flashgaze.models.schemas import CVResult
from flashgaze.utils.image_io import ImageReadError, load_image_color, load_image_grayscale

# 模块级探测 BRISQUE 依赖（opencv-contrib-python 的 cv2.quality.QualityBRISQUE）
# 基础 opencv-python 不含此模块，缺失时 compute_noise 返回 None，不阻塞主流程。
_BRISQUE_API = None
_BRISQUE_MODEL_DIR: Path | None = None
try:
    from cv2.quality import QualityBRISQUE as _BRISQUE_API  # type: ignore
    # 包内资源目录：用 importlib.resources.files() 按包的导入位置解析，
    # 与进程当前工作目录无关。可编辑安装（源码目录）与 wheel 安装（site-packages）都正确。
    from importlib.resources import files as _package_files
    _BRISQUE_MODEL_DIR = _package_files("flashgaze.models") / "brisque"
except Exception:
    # 依赖缺失或资源定位异常，一律降级，绝不阻塞 import flashgaze
    _BRISQUE_API = None
    _BRISQUE_MODEL_DIR = None


class CVEngine:
    """CV 客观评分引擎。"""

    def __init__(
        self,
        enable_composition: bool = False,
        enable_noise: bool = False,
        enable_color: bool = False,
        downscale: bool = True,
    ):
        self.enable_composition = enable_composition
        self.enable_noise = enable_noise
        self.enable_color = enable_color
        # 评分时加载图片的降采样阈值：downscale=True 时长边超 DOWNSCALE_THRESHOLD
        # 的图按比例缩小（仅内存中，不改原文件）；False 时按原分辨率加载
        self._eval_max_long_side: int | None = (
            DOWNSCALE_THRESHOLD if downscale else None
        )
        # BRISQUE 模型在 __init__ 中加载一次并缓存，避免 compute_noise 每次调用
        # 都重新从磁盘读取模型文件（批量评分时严重浪费 IO）。
        # 仅在 enable_noise=True 且依赖与模型文件齐全时加载；任一条件不满足时
        # 置 None，compute_noise 将返回 None（保持原有降级行为）。
        self._brisque_obj = None
        if enable_noise and _BRISQUE_API is not None and _BRISQUE_MODEL_DIR is not None:
            model_path = _BRISQUE_MODEL_DIR / "brisque_model_live.yml"
            range_path = _BRISQUE_MODEL_DIR / "brisque_range_live.yml"
            if model_path.is_file() and range_path.is_file():
                try:
                    self._brisque_obj = _BRISQUE_API(str(model_path), str(range_path))
                except Exception:
                    self._brisque_obj = None

    def evaluate(self, img_path: str) -> CVResult:
        """对单图执行完整 CV 评估。失败时返回带 error 的 CVResult，不抛异常。"""
        try:
            sharpness = self.compute_sharpness(img_path)
            exposure = self.compute_exposure(img_path)
            composition = (
                self.compute_composition(img_path) if self.enable_composition else None
            )
            noise = self.compute_noise(img_path) if self.enable_noise else None
            color = self.compute_color_richness(img_path) if self.enable_color else None
            return CVResult(
                sharpness=sharpness,
                exposure=exposure,
                composition=composition,
                noise=noise,
                color=color,
            )
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
        gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
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
        gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
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
        color = load_image_color(img_path, max_long_side=self._eval_max_long_side)
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

    def compute_noise(self, img_path: str) -> float | None:
        """BRISQUE 无参考 IQA → 0-100。

        原始 BRISQUE 分数越低质量越好（典型范围 0-100），故归一化为：
            normalized = 100 - raw_score（clamp 到 [0, 100]）

        依赖缺失（opencv-contrib-python 未安装）或模型文件缺失时返回 None，
        上层逻辑应将 None 视为未评分，不参与权重计算。
        模型对象在 __init__ 中加载并缓存为 self._brisque_obj，此处直接复用，
        避免每次调用都从磁盘重新读取模型文件。
        """
        if self._brisque_obj is None:
            return None
        try:
            gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
            gray = self._normalize_size(gray)
            score = self._brisque_obj.compute(gray)[0]
            # BRISQUE 越低质量越好，反转并 clamp
            normalized = max(0.0, min(100.0, 100.0 - float(score)))
            return round(normalized, 2)
        except Exception:
            return None

    def compute_color_richness(self, img_path: str) -> float:
        """HSV 直方图分布 → 0-100。

        综合两部分：
        1. H 通道直方图熵（信息熵，反映色相分布广度），权重 0.6
        2. S 通道均值（饱和度水平），权重 0.4

        纯灰图（饱和度=0）返回 0.0。
        """
        color = load_image_color(img_path, max_long_side=self._eval_max_long_side)
        hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
        h, s, _ = cv2.split(hsv)
        # H 通道直方图熵（180 bin，OpenCV HSV 中 H 范围 0-179）
        hist_h = cv2.calcHist([h], [0], None, [180], [0, 180]).flatten()
        total = hist_h.sum()
        if total == 0:
            return 0.0
        p = hist_h / total
        p_nonzero = p[p > 0]
        entropy = -float(np.sum(p_nonzero * np.log2(p_nonzero)))
        max_entropy = float(np.log2(180))
        entropy_score = min(entropy / max_entropy * 100.0, 100.0)
        # S 通道均值归一化
        s_mean = float(s.mean())
        s_score = min(s_mean / 255.0 * 100.0, 100.0)
        score = entropy_score * 0.6 + s_score * 0.4
        return round(min(max(score, 0.0), 100.0), 2)

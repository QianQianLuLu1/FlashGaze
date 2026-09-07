"""示例插件：基于 HSV 饱和度均值的美学评分。

仅作示例。请勿与内置 enable_color（HSV 色彩丰富度）同时启用，避免维度重叠。
"""

from __future__ import annotations

import cv2

from flashgaze.plugins.base import PluginScore, ScoringPlugin
from flashgaze.utils.image_io import load_image_color
from flashgaze.utils.logging import get_logger

# 显式声明为 FlashGaze 插件（C-03 契约：自定义插件需声明此标记才会被加载）。
# 内置插件由包内 import_module 自动发现，声明此标记仅为示范与一致。
__flashgaze_plugin__ = True

# 示例插件 evaluate 自身 bug 不应被静默吞掉（C-23）：同一进程内只告警一次，避免刷屏。
_warn_once = False


class AestheticsPlugin(ScoringPlugin):
    name = "aesthetics"
    version = "0.1.0"

    def evaluate(self, img_path: str) -> PluginScore | None:
        try:
            # 走项目统一解码（Pillow，原生支持 Unicode 路径），
            # 避免 cv2.imread 在 Windows 中文/全角路径下静默返回 None。
            img = load_image_color(img_path)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            sat_mean = float(hsv[:, :, 1].mean())  # S 通道 0-255
            score = min(100.0, sat_mean * 1.5)
            return PluginScore(
                name=self.name,
                score=score,
                weight=0.1,
                reason=f"饱和度均值{int(sat_mean)}",
            )
        except Exception as e:  # noqa: BLE001 — 示例插件自身 bug 降级为 None 且首次告警，不掩盖也不抛出
            # 任何异常都降级为 None，不抛出；但至少告警一次，避免插件自身 bug 被静默掩盖
            global _warn_once
            if not _warn_once:
                _warn_once = True
                get_logger().warning("示例插件 %s.evaluate 异常，已降级为 None: %s", self.name, e)
            return None

    # cleanup 用基类默认空实现即可

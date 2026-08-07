"""示例插件：基于 HSV 饱和度均值的美学评分。

仅作示例。请勿与内置 enable_color（HSV 色彩丰富度）同时启用，避免维度重叠。
"""

from __future__ import annotations

from typing import Optional

import cv2

from flashgaze.plugins.base import PluginScore, ScoringPlugin


class AestheticsPlugin(ScoringPlugin):
    name = "aesthetics"
    version = "0.1.0"

    def evaluate(self, img_path: str) -> Optional[PluginScore]:
        try:
            img = cv2.imread(img_path)
            if img is None:                      # 读不到 / 损坏
                return None
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            sat_mean = float(hsv[:, :, 1].mean())  # S 通道 0-255
            score = min(100.0, sat_mean * 1.5)
            return PluginScore(
                name=self.name,
                score=score,
                weight=0.1,
                reason=f"饱和度均值{int(sat_mean)}",
            )
        except Exception:
            # 任何异常都降级为 None，不抛出
            return None

    # cleanup 用基类默认空实现即可

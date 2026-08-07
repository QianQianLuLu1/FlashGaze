"""插件接口定义。

子类只需实现 evaluate()，禁止抛未捕获异常（失败返回 None）。
统一用标准库实现，无第三方依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PluginScore:
    """插件返回的评分单元。"""

    name: str                       # 维度名（如 "aesthetics"）
    score: float                    # 0-100
    weight: float = 0.0             # 建议权重；默认 0.0 = 仅记录，不改最终分
    reason: str = ""                # 可选说明


class ScoringPlugin:
    """插件基类。子类实现 evaluate()，可选重写 cleanup()。"""

    name: str = "base"
    version: str = "0.1.0"

    def evaluate(self, img_path: str) -> Optional[PluginScore]:
        """返回 PluginScore，失败返回 None。禁止抛异常。"""
        raise NotImplementedError

    def cleanup(self) -> None:
        """可选资源释放。默认空实现。"""
        pass

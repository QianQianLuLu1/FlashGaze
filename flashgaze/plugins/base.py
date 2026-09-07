"""插件接口定义。

子类只需实现 evaluate()，禁止抛未捕获异常（失败返回 None）。
统一用标准库实现，无第三方依赖。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginScore:
    """插件返回的评分单元。

    score / weight 的取值是**强制契约**（由 `core/hybrid_scorer._plugin_added`
    在消费侧统一强制，H-1）：

    - `score`：必须是有限值且落在 **0-100**；
    - `weight`：必须是有限值且 **|weight| ≤ 1.0**（默认 0.0 = 仅记录，不改最终分）；
    - 非有限值（`NaN` / `±inf`）或越界的返回值**不被采信**：该次返回值跳过、
      不参与加分，并记 WARNING（同一插件在同一批次内只告警一次）。

    越界值按「跳过」而非「钳制」处理：钳制会把 1e9 变成 100，配合大权重仍让
    全批图片并列满分（`min(100.0, nan)` 因 `nan < 100.0` 恒为 False 同样返回
    100.0），比跳过更危险且无从排查。此外，单张图上所有插件的**累计**增量受
    `hybrid_scorer.PLUGIN_MAX_TOTAL_ADDED`（±30）封顶，防止多个各自合规的插件
    叠加后把整批图推到 0/100 边界而丢失排序信息。
    """

    name: str  # 维度名（如 "aesthetics"）
    score: float  # 0-100（强制：须为有限值，越界即跳过该次加分）
    weight: float = 0.0  # 权重；默认 0.0 = 仅记录，不改最终分（强制：|weight| ≤ 1.0）
    reason: str = ""  # 可选说明


class ScoringPlugin(ABC):
    """插件基类。子类必须实现 evaluate()，可选重写 cleanup()。

    基类 evaluate 声明为 @abstractmethod（C-22）：与"禁止抛未捕获异常"契约一致，
    同时让"未实现即实例化"在开发期直接报错，而不是运行时抛 NotImplementedError
    被上层兜底逻辑掩盖。评分失败由子类在 evaluate 内部捕获并返回 None。
    """

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def evaluate(self, img_path: str) -> PluginScore | None:
        """返回 PluginScore，失败返回 None。禁止抛异常。"""
        raise NotImplementedError

    def cleanup(self) -> None:
        """可选资源释放。默认空实现。"""

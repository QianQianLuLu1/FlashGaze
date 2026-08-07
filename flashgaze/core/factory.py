"""Scorer 装配工厂。

将 CVEngine + VLMClient + HybridScorer 的装配逻辑收敛到单一入口，
消除 CLI / MCP / WebUI 三处的重复代码。

factory 不做 api_key 缺失的错误处理：
- config.no_vlm 为 True 或 api_key 为空时，vlm_client=None，返回纯 CV 评分器
- api_key 缺失是否报错由调用方决定（CLI 返回 CONFIG_ERROR，MCP/WebUI 各自处理）
"""

from __future__ import annotations

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.core.vlm_client import VLMClient
from flashgaze.models.schemas import Config


def make_scorer(config: Config) -> HybridScorer:
    """根据 config 装配 HybridScorer（CVEngine + VLMClient）。"""
    cv_engine = CVEngine(
        enable_composition=config.enable_composition,
        enable_noise=config.enable_noise,
        enable_color=config.enable_color,
        downscale=not config.no_downscale,
    )
    vlm_client: VLMClient | None = None
    if not config.no_vlm and config.api_key:
        vlm_client = VLMClient(
            api_key=config.api_key,
            api_base=config.api_base,
            model=config.model,
            timeout_sec=config.timeout_sec,
            max_retries=config.max_retries,
            max_adjustment=config.vlm_max_adjustment,
            provider=config.vlm_provider,
            scene=config.scene,
        )
    return HybridScorer(cv_engine, vlm_client, config)

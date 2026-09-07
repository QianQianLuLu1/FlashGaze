"""WebUI 测试共享构造器。

供 test_webui.py（纯逻辑）与 test_webui_components.py（组件级）复用，
用于构造 ImageScore / ScoringResult，避免两处维护同一套字段默认值。
"""

from __future__ import annotations

from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import Config, ImageScore
from flashgaze.webui.runner import ScoringResult, build_run_config


def make_score(
    file: str,
    path: str,
    *,
    score: float = 80.0,
    selected: bool = False,
    sharpness: float = 70.0,
    exposure: float = 60.0,
    composition: float | None = None,
    noise: float | None = None,
    color: float | None = None,
    face_count: int = 0,
    face_sharpness: float | None = None,
    portrait_bonus: float = 0.0,
    vlm_adjustment: float = 0.0,
    vlm_reason: str = "",
    vlm_provider: str = "",
    deduped: bool = False,
    error: str | None = None,
) -> ImageScore:
    """构造单个 ImageScore（填齐字段，便于 to_rows / gallery 测试）。"""
    return ImageScore(
        file=file,
        path=path,
        sharpness=sharpness,
        exposure=exposure,
        composition=composition,
        vlm_adjustment=vlm_adjustment,
        score=score,
        selected=selected,
        error=error,
        noise=noise,
        color=color,
        face_count=face_count,
        face_sharpness=face_sharpness,
        portrait_bonus=portrait_bonus,
        deduped=deduped,
        vlm_reason=vlm_reason,
        vlm_provider=vlm_provider,
    )


def make_result(scored: list[ImageScore], config: Config | None = None) -> ScoringResult:
    """构造 ScoringResult（用于 to_rows / gallery / filter_rows / 导出测试）。"""
    if config is None:
        config = build_run_config(".", ScoringOptions(no_vlm=True))
    return ScoringResult(scored=scored, elapsed_ms=100, config=config)

"""评分任务调度：复用 build_config / HybridScorer / Exporter 装配链。

不引入新的评分代码路径——所有调用都通过核心模块完成，GUI 仅作为上层封装。
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from flashgaze.core.exporter import Exporter
from flashgaze.core.factory import make_scorer
from flashgaze.models.schemas import Config, ExitCode, ImageScore
from flashgaze.utils.config import build_config
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger

logger = get_logger()

# 进度回调签名：(done, total, stage_text) -> None
ProgressFn = Callable[[int, int, str], None]


def build_run_config(
    directory: str,
    *,
    top: Optional[int] = None,
    threshold: Optional[float] = None,
    no_vlm: bool = False,
    enable_composition: bool = False,
    enable_noise: bool = False,
    enable_color: bool = False,
    enable_portrait: bool = False,
    dedup: bool = False,
    dedup_threshold: Optional[int] = None,
    no_downscale: bool = False,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model: Optional[str] = None,
    vlm_provider: Optional[str] = None,
    scene: Optional[str] = None,
    workers: Optional[int] = None,
    weights: Optional[dict[str, float]] = None,
) -> Config:
    """装配 Config。参数语义与 CLI 完全一致，None 表示不覆盖下层配置。"""
    return build_config(
        directory=directory,
        top=top,
        threshold=threshold,
        no_vlm=no_vlm or None,
        enable_composition=enable_composition or None,
        enable_noise=enable_noise or None,
        enable_color=enable_color or None,
        enable_portrait=enable_portrait or None,
        dedup=dedup or None,
        dedup_threshold=dedup_threshold,
        no_downscale=no_downscale or None,
        api_key=api_key,
        api_base=api_base,
        model=model,
        vlm_provider=vlm_provider,
        scene=scene,
        workers=workers,
        weights=weights,
    )


class ScoringResult:
    """单次评分的最终产物，缓存到 Gradio State 供后续导出复用。"""

    def __init__(self, scored: list[ImageScore], elapsed_ms: int, config: Config):
        self.scored = scored
        self.elapsed_ms = elapsed_ms
        self.config = config

    @property
    def summary(self) -> dict[str, Any]:
        return Exporter.build_report(self.scored, self.elapsed_ms)["summary"]

    def to_rows(self) -> list[list[Any]]:
        """转成表格行（与 CSV 列顺序一致，便于 UI 展示与导出对齐）。"""
        rows: list[list[Any]] = []
        for s in self.scored:
            rows.append([
                s.file,
                round(s.score, 2),
                round(s.sharpness, 2),
                round(s.exposure, 2),
                "" if s.composition is None else round(s.composition, 2),
                "" if s.noise is None else round(s.noise, 2),
                "" if s.color is None else round(s.color, 2),
                s.face_count,
                "" if s.face_sharpness is None else round(s.face_sharpness, 2),
                round(s.portrait_bonus, 2),
                round(s.vlm_adjustment, 2),
                s.vlm_reason,
                s.vlm_provider,
                "✓" if s.selected else "",
                "✓" if s.deduped else "",
                "" if s.error is None else s.error,
            ])
        return rows


def run_scoring(
    directory: str,
    *,
    top: Optional[int] = None,
    threshold: Optional[float] = None,
    no_vlm: bool = False,
    enable_composition: bool = False,
    enable_noise: bool = False,
    enable_color: bool = False,
    enable_portrait: bool = False,
    dedup: bool = False,
    dedup_threshold: Optional[int] = None,
    no_downscale: bool = False,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model: Optional[str] = None,
    vlm_provider: Optional[str] = None,
    scene: Optional[str] = None,
    workers: Optional[int] = None,
    weights: Optional[dict[str, float]] = None,
    progress: Optional[ProgressFn] = None,
) -> tuple[int, str, Optional[ScoringResult]]:
    """同步执行评分。返回 (exit_code, message, result)。

    progress 回调用于实时反馈进度：progress(done, total, stage_text)。
    """
    directory = directory.strip() if isinstance(directory, str) else directory
    if not directory:
        return ExitCode.PARAM_ERROR, "请输入图片目录", None
    if not Path(directory).is_dir():
        return ExitCode.NO_IMAGES, f"目录不存在: {directory}", None

    # 装配 Config（build_config 内部会校验 vlm_provider / scene 并回退到默认值）
    config = build_run_config(
        directory, top=top, threshold=threshold, no_vlm=no_vlm,
        enable_composition=enable_composition, enable_noise=enable_noise,
        enable_color=enable_color, enable_portrait=enable_portrait,
        dedup=dedup, dedup_threshold=dedup_threshold, no_downscale=no_downscale,
        api_key=api_key, api_base=api_base, model=model,
        vlm_provider=vlm_provider, scene=scene, workers=workers, weights=weights,
    )

    # VLM 前置校验：与 CLI 一致——未禁用 VLM 且缺 key 直接退出
    if not config.no_vlm and not config.api_key:
        return (
            ExitCode.CONFIG_ERROR,
            "未配置 API Key，请在界面填入或勾选「禁用 VLM」走纯离线模式",
            None,
        )

    # 收集图片列表
    if progress:
        progress(0, 1, "扫描目录...")
    images = list(iter_images(directory))
    if not images:
        return ExitCode.NO_IMAGES, "目录中无支持格式的图片", None

    # 进度回调桥接：HybridScorer 调用 progress_callback(done, total)
    def _cb(done: int, total: int) -> None:
        if progress:
            progress(done, total, f"{done}/{total}")

    if progress:
        progress(0, len(images), f"开始评分（共 {len(images)} 张）")

    start = time.time()
    try:
        scorer = make_scorer(config)
        scored = scorer.score_paths(images, progress_callback=_cb)
    except Exception as e:
        logger.exception("评分过程异常")
        return ExitCode.IMAGE_ERROR, f"评分过程异常: {e}", None
    elapsed_ms = int((time.time() - start) * 1000)

    if not scored:
        return ExitCode.NO_IMAGES, "评分结果为空", None

    if progress:
        progress(len(scored), len(scored), "完成")

    result = ScoringResult(scored, elapsed_ms, config)
    msg = f"完成: 共 {len(scored)} 张，入选 {result.summary.get('selected', 0)} 张，耗时 {elapsed_ms} ms"
    return ExitCode.SUCCESS, msg, result


# ── 导出操作（复用 Exporter，不复制导出代码） ────────────────────


def export_to_dir(
    result: ScoringResult,
    dest_dir: str,
    move: bool = False,
) -> tuple[int, str]:
    """复制/移动高分图到 dest_dir。返回 (exported_count, message)。"""
    if not result or not result.scored:
        return 0, "无可导出的结果"
    from dataclasses import replace
    config = replace(result.config, export=True, move=move)
    try:
        exporter = Exporter(config)
        exported = exporter.export_images(result.scored, dest_dir)
        action = "移动" if move else "复制"
        return exported, f"{action} {exported} 张到 {Path(dest_dir).resolve()}"
    except OSError as e:
        return 0, f"导出失败: {e}"


def export_manifest(
    result: ScoringResult,
    fmt: str,
    path: str,
) -> tuple[bool, str]:
    """生成 JSON / CSV 清单。返回 (ok, message)。"""
    if not result or not result.scored:
        return False, "无可导出的结果"
    try:
        Exporter(result.config).write_manifest(result.scored, fmt, path)
        return True, f"已写入 {path}"
    except (OSError, ValueError) as e:
        return False, f"导出失败: {e}"


def build_json_text(result: ScoringResult) -> str:
    """构造 JSON 文本（与 CLI stdout 输出一致），供前端下载预览。"""
    import json
    report = Exporter.build_report(result.scored, result.elapsed_ms)
    return json.dumps(report, ensure_ascii=False, indent=2)

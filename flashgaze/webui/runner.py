"""评分任务调度：复用 build_config / HybridScorer / Exporter 装配链。

不引入新的评分代码路径——所有调用都通过核心模块完成，GUI 仅作为上层封装。
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from flashgaze.core.cleanup import exclusion_dirs, is_within_directory
from flashgaze.core.exporter import Exporter
from flashgaze.core.factory import make_scorer
from flashgaze.core.vlm_client import sampling_params_for_config
from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import Config, ExitCode, ImageScore
from flashgaze.utils.config import build_config
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger

logger = get_logger()

# 进度回调签名：(done, total, stage_text) -> None
ProgressFn = Callable[[int, int, str], None]


def build_run_config(
    directory: str,
    options: ScoringOptions | None = None,
) -> Config:
    """装配 Config。options 中值为 None 的字段表示不覆盖下层配置。

    WebUI 的"未勾选复选框 = 不覆盖"约定由调用方（app.py 的 _options_from_inputs）
    在装配 ScoringOptions 时完成，这里不再做隐式的 `x or None` 转换。
    """
    opts = options or ScoringOptions()
    return build_config(directory=directory, **opts.to_config_kwargs())


class ScoringResult:
    """单次评分的最终产物，缓存到 Gradio State 供后续导出复用。"""

    def __init__(self, scored: list[ImageScore], elapsed_ms: int, config: Config) -> None:
        self.scored = scored
        self.elapsed_ms = elapsed_ms
        self.config = config
        # 阶段1看门狗统计（HybridScorer.phase1_stats）；无池路径时全零，
        # summary 中不出现 phase1_timeout 小节（与既有报告结构一致）。
        self.phase1_stats: dict[str, int] = {"timed_out": 0, "pool_exhausted": 0, "rebuilds": 0}

    @property
    def summary(self) -> dict[str, Any]:
        # build_report 的 summary 小节恒为 dict（内部构造），cast 收敛索引访问的 Any
        return cast(
            "dict[str, Any]",
            Exporter.build_report(
                self.scored,
                self.elapsed_ms,
                phase1_stats=self.phase1_stats,
                vlm_sampling=sampling_params_for_config(self.config),
            )["summary"],
        )

    def to_rows(self) -> list[list[Any]]:
        """转成表格行（展示格式，与 app.TABLE_HEADERS 列数对齐）。
        逐行委托 ImageScore.to_display_row()，避免与 gallery 重复构造（C-09）。"""
        return [s.to_display_row() for s in self.scored]


def run_scoring(
    directory: str,
    *,
    options: ScoringOptions | None = None,
    progress: ProgressFn | None = None,
    allowed_roots: list[str] | None = None,
) -> tuple[int, str, ScoringResult | None]:
    """同步执行评分。返回 (exit_code, message, result)。

    progress 回调用于实时反馈进度：progress(done, total, stage_text)。
    """
    directory = directory.strip() if isinstance(directory, str) else directory
    if not directory:
        return ExitCode.PARAM_ERROR, "请输入图片目录", None
    if not Path(directory).is_dir():
        return ExitCode.NO_IMAGES, f"目录不存在: {directory}", None

    # 图片目录白名单（WebUI --allow-root）：运维显式提供时才生效，封堵任意目录枚举。
    # 不传则保持本地无限制（向后兼容）。
    if allowed_roots:
        resolved_dir = Path(directory).resolve()
        if not any(is_within_directory(resolved_dir, Path(r).resolve()) for r in allowed_roots):
            return (
                ExitCode.PARAM_ERROR,
                f"图片目录不在允许的访问范围内: {directory}",
                None,
            )

    # 装配 Config（build_config 内部会校验 vlm_provider / scene 并回退到默认值）
    config = build_run_config(directory, options)

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
    # C-01：与 CLI/cleanup/MCP 对齐，扫描时排除导出副本目录与 EXIF 备份目录，
    # 避免把 ./精选 副本或 .flashgaze_backup 备份图重新评分、污染统计并生成重复导出文件。
    ws = Path(config.directory).resolve()
    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
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
    # 透传阶段1看门狗统计：score_paths 成功返回后 scorer 必已创建，
    # 且 phase1_stats 在 score_paths 入口重置，读取安全。
    result.phase1_stats = dict(scorer.phase1_stats)
    msg = f"完成: 共 {len(scored)} 张，入选 {result.summary.get('selected', 0)} 张，耗时 {elapsed_ms} ms"
    return ExitCode.SUCCESS, msg, result


# ── 导出操作（复用 Exporter，不复制导出代码） ────────────────────


def export_to_dir(
    result: ScoringResult,
    dest_dir: str,
    move: bool = False,
) -> tuple[int, str]:
    """复制/移动高分图到 dest_dir。返回 (exported_count, message)。

    存在导出失败项（磁盘满 / 权限不足 / 源文件在评分后被外部删除 / 目标是普通文件）
    时，message 在成功文案后追加「，N 张导出失败（前 3 项 file: error）」并打
    ERROR 汇总日志——与 CLI 退出码 5 / MCP `status="partial"` 同语义：结果照常
    产出，但「声称入选 N 张、实际导出 M 张」必须可见。零失败时文案逐字不变。
    """
    if not result or not result.scored:
        return 0, "无可导出的结果"
    # 导出越界硬拒绝：目标目录必须落在本次评分目录（workspace）内，
    # 杜绝 move=True 把高分图甩到 workspace 外的任意绝对路径（与 MCP 同强度）。
    # N-1 契约对齐：相对 dest_dir 以评分目录为基准解析（与 CLI _safe_output_path
    # 同源），Gradio 进程 CWD ≠ 评分目录时默认 ./精选 也能正确落盘。
    ws = Path(result.config.directory).resolve()
    dest = Path(dest_dir)
    dest = (ws / dest).resolve() if not dest.is_absolute() else dest.resolve()
    if not is_within_directory(dest, ws):
        return (
            0,
            f"导出目录 {dest_dir} 位于评分目录 {result.config.directory} 之外（路径穿越风险，已拒绝）",
        )
    from dataclasses import replace

    config = replace(result.config, export=True, move=move)
    try:
        exporter = Exporter(config)
        exported = exporter.export_images(result.scored, str(dest))
        action = "移动" if move else "复制"
        msg = f"{action} {exported} 张到 {dest}"
        if exporter.last_failures:
            # H-9：导出数只给成功数，状态栏此前对「入选 N 张、实际导出 M 张」完全
            # 无感知。摘要只放前 3 项，完整明细走 ERROR 日志，避免长清单刷爆状态栏。
            failed = len(exporter.last_failures)
            items = [f"{f['file'] or f['path']}: {f['error']}" for f in exporter.last_failures]
            logger.error(
                "导出部分失败：%d/%d 张未导出（%s）",
                failed,
                exporter.last_expected,
                "；".join(items),
            )
            return exported, f"{msg}，{failed} 张导出失败（{'；'.join(items[:3])}）"
        return exported, msg
    except Exception as e:
        # 导出可能抛非 OSError（如路径校验/权限异常），一律转成友好消息返回，
        # 不让异常冒泡冲垮 Gradio 事件回调（错误必须被处理，不静默）。
        logger.exception("导出失败")
        return 0, f"导出失败: {e}"


def export_manifest(
    result: ScoringResult,
    fmt: str,
    path: str,
) -> tuple[bool, str]:
    """生成 JSON / CSV 清单。返回 (ok, message)。

    path 仅允许位于评分目录（workspace）或系统临时目录（tempfile.gettempdir()，
    与 app.py 下载临时文件的 mkstemp 同源）内：越界（含 `..` 逃逸与符号链接解析
    后逃逸）在落盘前硬拒绝，不创建任何父目录。相对路径以评分目录为基准解析
    （N-1 契约，与 export_to_dir / CLI _safe_output_path 同源）。
    """
    if not result or not result.scored:
        return False, "无可导出的结果"
    # 落盘路径收敛（M-10）：允许根 = workspace ∪ 系统临时目录。校验必须先于
    # write_manifest——原子写会 mkdir(parents=True)，后置校验拦不住「借导出创建
    # 任意目录」。拒绝文案不含「导出失败」字样（安全拦截语义，与 export_to_dir
    # 的「已拒绝」同族）。
    ws = Path(result.config.directory).resolve()
    dest = Path(path)
    dest = (ws / dest).resolve() if not dest.is_absolute() else dest.resolve()
    if not (
        is_within_directory(dest, ws) or is_within_directory(dest, Path(tempfile.gettempdir()))
    ):
        return (
            False,
            f"清单路径 {path} 位于评分目录 {result.config.directory} 或系统临时目录之外（路径穿越风险，已拒绝）",
        )
    try:
        Exporter(result.config).write_manifest(result.scored, fmt, str(dest))
        return True, f"已写入 {dest}"
    except (OSError, ValueError) as e:
        return False, f"导出失败: {e}"


def build_json_text(result: ScoringResult) -> str:
    """构造 JSON 文本（与 CLI stdout 输出一致），供前端下载预览。"""
    import json

    report = Exporter.build_report(
        result.scored,
        result.elapsed_ms,
        phase1_stats=result.phase1_stats,
        vlm_sampling=sampling_params_for_config(result.config),
    )
    return json.dumps(report, ensure_ascii=False, indent=2)

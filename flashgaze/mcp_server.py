"""FlashGaze MCP Server。

将 flashgaze 的图片评分能力暴露为 MCP 工具，供 Claude Code、TRAE、Cursor、
Codex 等支持 MCP 的 AI Agent 直接调用。

支持三种工作模式：
1. 目录评分模式 — 对指定目录下所有图片评分（递归子目录）
2. 上传评分模式 — 对 Agent 上传的图片路径列表评分
3. 工作空间清理模式 — 评分后原地删除低分图（仅限工作空间目录内）

传输方式：stdio（本地启动，最通用）。
启动命令：python -m flashgaze.mcp_server
"""

from __future__ import annotations

import json
import stat
import time
from dataclasses import asdict, replace
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.exporter import Exporter
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.core.vlm_client import VLMClient
from flashgaze.defaults import SUPPORTED_EXTENSIONS
from flashgaze.models.schemas import Config
from flashgaze.utils.config import build_config
from flashgaze.utils.image_io import iter_images

mcp = FastMCP("flashgaze")


# ── 公共辅助 ──────────────────────────────────────────


def _build_config(
    directory: str,
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    workers: int | None = None,
) -> Config:
    """MCP 参数作为 overrides 传给 build_config。

    所有参数默认 None，build_config 内部跳过 None 值，
    自然回落到 env > file > default，保证 FLASHGAZE_WORKERS
    等环境变量在 MCP 模式生效。MCP 调用方未显式传参时，
    不强制覆盖，与 CLI 行为一致。
    """
    return build_config(
        directory=directory,
        top=top,
        threshold=threshold,
        no_vlm=no_vlm,
        enable_composition=enable_composition,
        workers=workers,
    )


def _make_vlm_client(config: Config) -> VLMClient | None:
    """根据 config 构建 VLMClient。缺 key 时返回 None。"""
    if config.no_vlm or not config.api_key:
        return None
    return VLMClient(
        api_key=config.api_key,
        api_base=config.api_base,
        model=config.model,
        timeout_sec=config.timeout_sec,
        max_retries=config.max_retries,
        max_adjustment=config.vlm_max_adjustment,
        vlm_lang=config.vlm_lang,
    )


def _error(code: int, message: str) -> str:
    """生成标准错误 JSON（六字段统一 Schema，缺失字段用 null/空容器占位）。"""
    return json.dumps(
        {
            "status": "error",
            "code": code,
            "message": message,
            "summary": {},
            "images": None,
            "details": None,
        },
        ensure_ascii=False,
    )


def _success(
    summary: dict,
    images: list | None = None,
    details: dict | None = None,
) -> str:
    """生成标准成功 JSON（六字段统一 Schema）。

    - summary: 必有，统计字段
    - images: 评分类工具返回数组；导出/清理返回 None
    - details: 工具特有字段（dest_dir/deleted_files 等），无则为 None
    """
    return json.dumps(
        {
            "status": "success",
            "code": 0,
            "message": None,
            "summary": summary,
            "images": images,
            "details": details,
        },
        ensure_ascii=False,
        indent=2,
    )


def _validate_vlm(config: Config) -> str | None:
    """检查 VLM 模式的前置条件。返回错误 JSON 或 None。"""
    if not config.no_vlm and not config.api_key:
        return _error(6, "未配置 FLASHGAZE_API_KEY 环境变量")
    return None


def _make_scorer(config: Config) -> HybridScorer:
    """根据 config 构建 HybridScorer（复用 CVEngine + VLMClient 装配逻辑）。"""
    cv_engine = CVEngine(enable_composition=config.enable_composition)
    vlm_client = _make_vlm_client(config)
    return HybridScorer(cv_engine, vlm_client, config)


def _is_within_directory(file_path: Path, root: Path) -> bool:
    """安全检查：file_path 是否严格在 root 目录内（防止路径穿越）。"""
    try:
        file_path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _filter_image_files(paths: list[str]) -> tuple[list[str], list[str]]:
    """从路径列表中筛出有效图片文件。返回 (有效图片, 被跳过的路径)。"""
    valid = []
    skipped = []
    for p in paths:
        pp = Path(p)
        if not pp.is_file():
            skipped.append(f"{p} (文件不存在)")
            continue
        if pp.suffix.lower() not in SUPPORTED_EXTENSIONS:
            skipped.append(f"{p} (不支持的格式)")
            continue
        valid.append(str(pp.resolve()))
    return valid, skipped


def _build_report(
    scored: list,
    elapsed_ms: int,
    extra: dict | None = None,
    details: dict | None = None,
) -> str:
    """统一构造 JSON 报告字符串，复用 Exporter.build_report 静态方法。

    build_report 已返回六字段 Schema（status/code/message/summary/images/details），
    此处仅需合并 extra 到 summary，并覆盖 details（默认 None 时保持不变）。
    """
    report = Exporter.build_report(scored, elapsed_ms=elapsed_ms)
    if extra:
        report["summary"].update(extra)
    if details is not None:
        report["details"] = details
    return json.dumps(report, ensure_ascii=False, indent=2)


# ── MCP 工具：目录评分模式 ────────────────────────────


@mcp.tool()
def score_images(
    directory: str,
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    workers: int | None = None,
) -> str:
    """对目录下的图片进行批量评分（递归子目录），返回 JSON 格式的评分报告。

    Args:
        directory: 图片所在目录的绝对路径
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top（如 75.0 表示 >=75 分入选）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False，有 API Key 时启用 VLM）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        workers: 并发线程数（默认 4）

    Returns:
        JSON 字符串，包含 summary 和 images 数组。
    """
    if not Path(directory).is_dir():
        return _error(3, f"目录不存在: {directory}")

    images = list(iter_images(directory))
    if not images:
        return _error(3, "目录中无支持格式的图片")

    config = _build_config(
        directory, top, threshold, no_vlm, enable_composition, workers
    )

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scored = _make_scorer(config).score_paths(images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    return _build_report(scored, elapsed_ms)


@mcp.tool()
def score_single_image(
    image_path: str,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
) -> str:
    """对单张图片进行评分，返回该图的详细评分数据。

    Args:
        image_path: 图片文件的绝对路径
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）

    Returns:
        JSON 字符串，包含该图的 sharpness/exposure/score 等字段。
    """
    p = Path(image_path)
    if not p.is_file():
        return _error(3, f"文件不存在: {image_path}")

    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return _error(3, f"不支持的图片格式: {p.suffix}")

    config = _build_config(
        directory=str(p.parent), no_vlm=no_vlm, enable_composition=enable_composition
    )

    if err := _validate_vlm(config):
        return err

    try:
        # 复用 _make_scorer 保证 CVEngine/VLMClient 装配逻辑与其他工具一致
        # 注意：必须用 config.enable_composition（已解析为 bool），
        # 不能直接用 enable_composition 参数（可能是 None）
        start = time.time()
        result = _make_scorer(config).score_one(image_path)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    # 单图模式：返回 images:[result] 单元素数组，summary.selected 恒为 0
    # （单图不判断入选，selected 字段无意义，调用方应依据 score 自行决策）
    return _success(
        summary={
            "total": 1,
            "selected": 0,
            "avg_score": result.score,
            "elapsed_ms": int((time.time() - start) * 1000),
        },
        images=[asdict(result)],
    )


@mcp.tool()
def export_selected_images(
    directory: str,
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    dest_dir: str = "./flashgaze_selected",
    move: bool = False,
    workers: int | None = None,
) -> str:
    """评分后自动将高分图复制或移动到目标目录（同名文件自动追加序号后缀）。

    Args:
        directory: 源图片目录路径
        top: 选取前 N 张（默认 30）
        threshold: 分数阈值（替代 top）
        no_vlm: 是否禁用 VLM（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        dest_dir: 目标目录路径（默认 ./flashgaze_selected）
        move: True 移动文件，False 复制文件（默认 False）
        workers: 并发线程数

    Returns:
        JSON 字符串，包含评分摘要和导出数量。
    """
    if not Path(directory).is_dir():
        return _error(3, f"目录不存在: {directory}")

    images = list(iter_images(directory))
    if not images:
        return _error(3, "目录中无支持格式的图片")

    config = replace(
        _build_config(
            directory, top, threshold, no_vlm, enable_composition, workers=workers
        ),
        export=True,
        move=move,
    )

    if err := _validate_vlm(config):
        return err

    try:
        scored = _make_scorer(config).score_paths(images)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    try:
        exporter = Exporter(config)
        exported_count = exporter.export_images(scored, dest_dir)
    except OSError as e:
        return _error(5, f"导出失败: {e}")

    selected = [s for s in scored if s.selected]
    return _success(
        summary={
            "total": len(scored),
            "selected": len(selected),
            "exported": exported_count,
        },
        details={
            "dest_dir": str(Path(dest_dir).resolve()),
            "mode": "move" if move else "copy",
        },
    )


# ── MCP 工具：上传评分模式 ────────────────────────────


@mcp.tool()
def score_uploaded_images(
    image_paths: list[str],
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    workers: int | None = None,
) -> str:
    """对上传的图片路径列表进行评分，返回 JSON 评分报告。

    适用于 AI Agent 收到用户上传的图片后，直接传入路径列表进行评分。
    不依赖目录结构，按给定的图片路径逐一评分。

    Args:
        image_paths: 图片文件路径列表（绝对路径）
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        workers: 并发线程数（默认 4）

    Returns:
        JSON 字符串，包含 summary 和 images 数组。
        skipped 字段列出不存在的路径或不支持的格式。
    """
    if not image_paths:
        return _error(1, "image_paths 为空，请提供至少一个图片路径")

    valid_images, skipped = _filter_image_files(image_paths)

    if not valid_images:
        return _error(3, f"无有效图片文件。跳过: {'; '.join(skipped)}")

    config = _build_config(
        directory=str(Path(valid_images[0]).parent),
        top=top,
        threshold=threshold,
        no_vlm=no_vlm,
        enable_composition=enable_composition,
        workers=workers,
    )

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scored = _make_scorer(config).score_paths(valid_images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    return _build_report(
        scored, elapsed_ms, details={"skipped": skipped}
    )


# ── MCP 工具：工作空间清理模式 ────────────────────────


@mcp.tool()
def cleanup_workspace_images(
    workspace: str,
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    dry_run: bool = True,
    workers: int | None = None,
) -> str:
    """对指定工作空间目录下的图片评分，并原地删除不符合要求的低分图。

    递归扫描子目录。安全保证：
    - 仅删除 workspace 目录内的图片文件，绝不影响目录外任何文件
    - 严格路径穿越检查，防止符号链接或 ../ 路径逃逸
    - 默认 dry_run=True 只报告不删除，确认后设 dry_run=False 才真正删除
    - 删除前再次校验路径在工作空间内

    Args:
        workspace: 工作空间目录的绝对路径（所有删除操作严格限制在此目录内）
        top: 保留前 N 张高分图，其余删除（默认 30）
        threshold: 分数阈值，低于此值的图片将被删除（替代 top）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        dry_run: 试运行模式，只报告将要删除哪些文件，不实际删除（默认 True）
        workers: 并发线程数

    Returns:
        JSON 字符串，包含评分摘要和将要删除/已删除的文件列表。
        损坏图（评分 error）既不删除也不入选，归入 unevaluated_files，
        需用户手动处理。
    """
    ws = Path(workspace).resolve()

    if not ws.is_dir():
        return _error(3, f"工作空间目录不存在: {workspace}")

    images = list(iter_images(str(ws)))
    if not images:
        return _error(3, "工作空间中无支持格式的图片")

    config = _build_config(
        directory=str(ws),
        top=top,
        threshold=threshold,
        no_vlm=no_vlm,
        enable_composition=enable_composition,
        workers=workers,
    )

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scored = _make_scorer(config).score_paths(images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    to_delete = [s for s in scored if not s.selected and s.error is None]
    selected = [s for s in scored if s.selected]
    # F-03：损坏图（有 error）既不删除也不入选，单独归类保证去向可追溯
    unevaluated = [s for s in scored if s.error is not None]

    deleted_files = []
    blocked_files = []
    deleted_count = 0

    for s in to_delete:
        file_path = Path(s.path).resolve()

        if not _is_within_directory(file_path, ws):
            blocked_files.append(f"{s.path} (路径在工作空间外，已拦截)")
            continue

        # TOCTOU 防护：删除前最终校验文件类型，拒绝符号链接/设备文件/目录
        # 防止检查与删除之间的时间窗口内文件被替换为指向外部的链接
        try:
            st = file_path.stat()
            if not stat.S_ISREG(st.st_mode):
                blocked_files.append(f"{s.file} (非常规文件，已跳过)")
                continue
        except OSError as e:
            blocked_files.append(f"{s.file} (stat 失败: {e})")
            continue

        if dry_run:
            deleted_files.append(s.file)
        else:
            try:
                file_path.unlink()
                deleted_files.append(s.file)
                deleted_count += 1
            except OSError as e:
                blocked_files.append(f"{s.file} (删除失败: {e})")

    return _success(
        summary={
            "workspace": str(ws),
            "total": len(scored),
            "selected": len(selected),
            "to_delete": len(to_delete),
            "deleted": deleted_count if not dry_run else 0,
            "unevaluated": len(unevaluated),  # 损坏图计数，需用户手动处理
            "mode": "dry_run" if dry_run else "actual_delete",
            "elapsed_ms": elapsed_ms,
        },
        details={
            "kept_images": [asdict(s) for s in scored if s.selected],
            "deleted_files": deleted_files,
            "blocked_files": blocked_files,
            "unevaluated_files": [asdict(s) for s in unevaluated],
        },
    )


if __name__ == "__main__":
    mcp.run()

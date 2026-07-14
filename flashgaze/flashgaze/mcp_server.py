"""FlashGaze MCP Server。

将 flashgaze 的图片评分能力暴露为 MCP 工具，供 Claude Code、TRAE、Cursor、
Codex 等支持 MCP 的 AI Agent 直接调用。

支持三种工作模式：
1. 目录评分模式 — 对指定目录下所有图片评分
2. 上传评分模式 — 对 Agent 上传的图片路径列表评分
3. 工作空间清理模式 — 评分后原地删除低分图（仅限工作空间目录内）

传输方式：stdio（本地启动，最通用）。
启动命令：python -m flashgaze.mcp_server
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

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
    top: int = 30,
    threshold: Optional[float] = None,
    no_vlm: bool = True,
    enable_composition: bool = False,
    workers: int = 4,
) -> Config:
    """从参数 + 环境变量构建 Config。函数参数覆盖环境变量。

    统一调用 build_config 装配（与 CLI 行为一致），消除重复的 env 读取逻辑。
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
    )


def _error(code: int, message: str) -> str:
    """生成标准错误 JSON。"""
    return json.dumps(
        {"status": "error", "code": code, "message": message},
        ensure_ascii=False,
    )


def _validate_vlm(config: Config) -> str | None:
    """检查 VLM 模式的前置条件。返回错误 JSON 或 None。"""
    if not config.no_vlm and not config.api_key:
        return _error(6, "未配置 FLASHGAZE_API_KEY 环境变量")
    return None


def _new_scorer(config: Config) -> HybridScorer:
    """根据 config 构建 HybridScorer（CV + 可选 VLM）。"""
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


# ── MCP 工具：目录评分模式 ────────────────────────────


@mcp.tool()
def score_images(
    directory: str,
    top: int = 30,
    threshold: Optional[float] = None,
    no_vlm: bool = True,
    enable_composition: bool = False,
    workers: int = 4,
) -> str:
    """对目录下的图片进行批量评分，返回 JSON 格式的评分报告。

    Args:
        directory: 图片所在目录的绝对路径
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top（如 75.0 表示 >=75 分入选）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 True，零成本零 API 调用）
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
        scored = _new_scorer(config).score_paths(images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    selected = [s for s in scored if s.selected]
    valid = [s for s in scored if s.error is None]
    avg = sum(s.score for s in valid) / max(len(valid), 1)

    data = {
        "status": "success",
        "code": 0,
        "summary": {
            "total": len(scored),
            "selected": len(selected),
            "avg_score": round(avg, 2),
            "elapsed_ms": elapsed_ms,
        },
        "images": [s.__dict__ for s in scored],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def score_single_image(
    image_path: str,
    no_vlm: bool = True,
    enable_composition: bool = False,
) -> str:
    """对单张图片进行评分，返回该图的详细评分数据。

    Args:
        image_path: 图片文件的绝对路径
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 True）
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

    cv_engine = CVEngine(enable_composition=enable_composition)
    vlm_client = _make_vlm_client(config)

    try:
        scorer = HybridScorer(cv_engine, vlm_client, config)
        result = scorer.score_one(image_path)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    return json.dumps(
        {
            "status": "success",
            "code": 0,
            "image": result.__dict__,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def export_selected_images(
    directory: str,
    top: int = 30,
    threshold: Optional[float] = None,
    no_vlm: bool = True,
    dest_dir: str = "./精选",
    move: bool = False,
    workers: int = 4,
) -> str:
    """评分后自动将高分图复制或移动到目标目录。

    Args:
        directory: 源图片目录路径
        top: 选取前 N 张（默认 30）
        threshold: 分数阈值（替代 top）
        no_vlm: 是否禁用 VLM（默认 True）
        dest_dir: 目标目录路径（默认 ./精选）
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

    config = _build_config(directory, top, threshold, no_vlm, workers=workers)
    config.move = move

    if err := _validate_vlm(config):
        return err

    try:
        scorer = _new_scorer(config)
        scored = scorer.score_batch(directory)
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
    return json.dumps(
        {
            "status": "success",
            "code": 0,
            "summary": {
                "total": len(scored),
                "selected": len(selected),
                "exported": exported_count,
                "dest_dir": str(Path(dest_dir).resolve()),
                "mode": "move" if move else "copy",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


# ── MCP 工具：上传评分模式 ────────────────────────────


@mcp.tool()
def score_uploaded_images(
    image_paths: list[str],
    top: int = 30,
    threshold: Optional[float] = None,
    no_vlm: bool = True,
    enable_composition: bool = False,
    workers: int = 4,
) -> str:
    """对上传的图片路径列表进行评分，返回 JSON 评分报告。

    适用于 AI Agent 收到用户上传的图片后，直接传入路径列表进行评分。
    不依赖目录结构，按给定的图片路径逐一评分。

    Args:
        image_paths: 图片文件路径列表（绝对路径）
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 True）
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
        scored = _new_scorer(config).score_paths(valid_images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    selected = [s for s in scored if s.selected]
    valid = [s for s in scored if s.error is None]
    avg = sum(s.score for s in valid) / max(len(valid), 1)

    data = {
        "status": "success",
        "code": 0,
        "summary": {
            "total": len(scored),
            "selected": len(selected),
            "avg_score": round(avg, 2),
            "elapsed_ms": elapsed_ms,
            "skipped": skipped,
        },
        "images": [s.__dict__ for s in scored],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── MCP 工具：工作空间清理模式 ────────────────────────


@mcp.tool()
def cleanup_workspace_images(
    workspace: str,
    top: int = 30,
    threshold: Optional[float] = None,
    no_vlm: bool = True,
    dry_run: bool = True,
    workers: int = 4,
) -> str:
    """对指定工作空间目录下的图片评分，并原地删除不符合要求的低分图。

    安全保证：
    - 仅删除 workspace 目录内的图片文件，绝不影响目录外任何文件
    - 严格路径穿越检查，防止符号链接或 ../ 路径逃逸
    - 默认 dry_run=True 只报告不删除，确认后设 dry_run=False 才真正删除
    - 删除前再次校验路径在工作空间内

    Args:
        workspace: 工作空间目录的绝对路径（所有删除操作严格限制在此目录内）
        top: 保留前 N 张高分图，其余删除（默认 30）
        threshold: 分数阈值，低于此值的图片将被删除（替代 top）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 True）
        dry_run: 试运行模式，只报告将要删除哪些文件，不实际删除（默认 True）
        workers: 并发线程数

    Returns:
        JSON 字符串，包含评分摘要和将要删除/已删除的文件列表。
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
        workers=workers,
    )

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scored = _new_scorer(config).score_paths(images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    # 未入选的图片将被删除
    to_delete = [s for s in scored if not s.selected and s.error is None]
    selected = [s for s in scored if s.selected]

    deleted_files = []
    blocked_files = []
    deleted_count = 0

    for s in to_delete:
        file_path = Path(s.path).resolve()

        # 双重安全检查：确认路径在工作空间内
        if not _is_within_directory(file_path, ws):
            blocked_files.append(
                f"{s.path} (路径在工作空间外，已拦截)"
            )
            continue

        # 确保是文件不是目录
        if not file_path.is_file():
            blocked_files.append(f"{s.path} (不是文件，已跳过)")
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

    data = {
        "status": "success",
        "code": 0,
        "summary": {
            "workspace": str(ws),
            "total": len(scored),
            "selected": len(selected),
            "to_delete": len(to_delete),
            "deleted": deleted_count if not dry_run else 0,
            "mode": "dry_run" if dry_run else "actual_delete",
            "elapsed_ms": elapsed_ms,
        },
        "kept_images": [s.__dict__ for s in scored if s.selected],
        "deleted_files": deleted_files,
        "blocked_files": blocked_files,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()

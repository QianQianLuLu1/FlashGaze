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
import os
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from flashgaze.core.cleanup import (
    CleanupError,
    _resolve_scored,
    classify_and_delete,
    exclusion_dirs,
    is_within_directory,
)
from flashgaze.core.exporter import Exporter
from flashgaze.core.factory import make_scorer
from flashgaze.core.vlm_client import sampling_params_for_config
from flashgaze.defaults import ENV_MCP_ALLOWED_ROOTS, SUPPORTED_EXTENSIONS
from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import Config, ExitCode, ImageScore
from flashgaze.utils.config import build_config
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger

mcp = FastMCP("flashgaze")

# 注意：下方 @mcp.tool 的形参名、顺序、默认值与类型注解属于对外契约——
# FastMCP 通过 inspect.signature 反射生成 JSON Schema 暴露给 Agent，
# 改动会让已接入的调用方失效，须同步 CHANGELOG。
# 工具签名保持扁平显式参数，内部统一转成 ScoringOptions 再装配 Config。


# ── 公共辅助 ──────────────────────────────────────────


def _config_from(directory: str, opts: ScoringOptions) -> Config:
    """MCP 参数作为 overrides 传给 build_config。

    未显式传参的字段为 None，build_config 内部跳过 None 值，
    自然回落到 env > file > default，保证 FLASHGAZE_WORKERS
    等环境变量在 MCP 模式生效。MCP 调用方未显式传参时，
    不强制覆盖，与 CLI 行为一致。
    """
    # FIX(#14-2): 上传评分模式（score_uploaded_images）刻意以 directory="" 调用，
    # 走「按显式路径评分、不扫描目录」的契约：build_config 对空目录不报错，仅作占位。
    # 显式落日志使其可被观测，并警示：切勿在此加 `if not directory: raise`，
    # 否则会与上传模式契约冲突（脆弱点已在 score_uploaded_images 注释中说明）。
    if not directory:
        get_logger().debug("MCP: directory 为空，走上传评分契约（按显式路径评分，不扫描目录）")
    return build_config(directory=directory, **opts.to_config_kwargs())


def _error(
    code: int,
    message: str,
    summary: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    status: str = "error",
) -> str:
    """生成标准错误 JSON（六字段统一 Schema，缺失字段用 null/空容器占位）。

    `summary` / `details` 可选填充：清理护栏拦截（M-11）这类「部分结果仍需可读」
    的场景要带上完整统计与被拦文件清单，否则 Agent 无从排查。`status` 可显式
    传 `"blocked"`（非 0 码 + 语义化状态，区别于通用 `error`）；导出部分失败
    （M-13）传 `"partial"`——结果已部分落盘，但成功数与预期不符。
    """
    return json.dumps(
        {
            "status": status,
            "code": code,
            "message": message,
            "summary": summary or {},
            "images": None,
            "details": details,
        },
        ensure_ascii=False,
    )


def _success(
    summary: dict[str, Any],
    images: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
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


# 别名：路径边界校验的唯一实现已迁至 core/cleanup.is_within_directory，
# 保留此名供既有单测（test_mcp_server.TestIsWithinDirectory）引用，避免逻辑分叉。
_is_within_directory = is_within_directory


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


def _allowed_scan_roots() -> list[Path]:
    """H-12：读取允许扫描根（逗号分隔），未配置时回退为进程启动目录。

    上传/单图评分只允许读取允许根内的图片，防止 MCP 调用方把磁盘上任意
    路径的图片（文档、截图、私密照片）读取解码后送往外发 VLM 端点。
    """
    raw = os.environ.get(ENV_MCP_ALLOWED_ROOTS, "")
    roots: list[Path] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        root = Path(part).resolve()
        if root not in roots:
            roots.append(root)
    # 未配置时的兜底边界：把服务器启动目录当作默认 workspace（fail-closed）
    return roots or [Path.cwd()]


def _reject_outside_roots(paths: list[str], roots: list[Path]) -> tuple[list[str], list[str]]:
    """H-12：路径包含性过滤。返回 (允许根内的原始路径, 被拒描述列表)。

    复用 is_within_directory（resolve + relative_to，防 ../ 与符号链接逃逸）；
    拒绝发生在任何文件系统访问之前，越界路径不会被 stat、解码或送 VLM。
    """
    accepted: list[str] = []
    skipped: list[str] = []
    for p in paths:
        if any(is_within_directory(Path(p), root) for root in roots):
            accepted.append(p)
        else:
            skipped.append(f"{p} (位于允许扫描根之外)")
            get_logger().warning("MCP: 拒绝允许扫描根之外的路径: %s", p)
    return accepted, skipped


def _build_report(
    scored: list[ImageScore],
    elapsed_ms: int,
    extra: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    phase1_stats: dict[str, int] | None = None,
) -> str:
    """统一构造 JSON 报告字符串，复用 Exporter.build_report 静态方法并补齐六字段。

    phase1_stats：HybridScorer.phase1_stats；未传入或全零时报告中不出现
    phase1_timeout 小节（与既有响应契约一致）。
    """
    report = Exporter.build_report(scored, elapsed_ms=elapsed_ms, phase1_stats=phase1_stats)
    if extra:
        report["summary"].update(extra)
    # 补齐六字段统一 Schema
    report["message"] = None
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
    enable_noise: bool | None = None,
    enable_color: bool | None = None,
    enable_portrait: bool | None = None,
    dedup: bool | None = None,
    dedup_threshold: int | None = None,
    workers: int | None = None,
    vlm_provider: str | None = None,
    scene: str | None = None,
    no_downscale: bool = False,
) -> str:
    """对目录下的图片进行批量评分（递归子目录），返回 JSON 格式的评分报告。

    Args:
        directory: 图片所在目录的绝对路径
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top（如 75.0 表示 >=75 分入选）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False，有 API Key 时启用 VLM）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        enable_noise: 是否启用 BRISQUE 噪点评分（需 opencv-contrib-python，默认 False）
        enable_color: 是否启用色彩丰富度评分（默认 False）
        enable_portrait: 是否启用人像专项评分（需 face_recognition，默认 False）
        dedup: 是否启用 PHash 图片去重（需 imagededup，默认 False）
        dedup_threshold: PHash 汉明距离阈值（默认 8，越小越严格）
        workers: 并发线程数（默认 4）
        vlm_provider: VLM 提供商（qwen / openai / anthropic / ollama，默认 qwen；所有 provider 走内置 pin-IP 直连层，无需 litellm，litellm 仅可选兜底）
        scene: 场景模式（auto / portrait / landscape / still_life，默认 auto 由 VLM 自行判断）
        no_downscale: 是否禁用降采样（长边缩至 1024），默认 False（启用降采样，与现行为一致）；True 时使用原始分辨率

    Returns:
        JSON 字符串，包含 summary 和 images 数组。
    """
    if top is not None and top < 1:
        return _error(1, "top 必须 >= 1，禁止传 0（会清空整个工作空间）")

    if not Path(directory).is_dir():
        return _error(3, f"目录不存在: {directory}")

    # 先构建 config 以解析导出副本目录（C-01），扫描阶段排除导出目录与 EXIF
    # 备份目录，避免把 ./精选 副本或 .flashgaze_backup 备份图重新评分、污染统计
    # （与 cleanup_workspace_images / run_cleanup 行为对齐）。
    # FIX(#3-6): 配置装配单独包 try——build_config 在此之前可能因非法数值
    # （如配置来源的 inf）等异常失败，裸抛会击穿六字段错误 JSON 契约。
    try:
        config = _config_from(
            directory,
            ScoringOptions(
                top=top,
                threshold=threshold,
                no_vlm=no_vlm,
                enable_composition=enable_composition,
                enable_noise=enable_noise,
                enable_color=enable_color,
                enable_portrait=enable_portrait,
                dedup=dedup,
                dedup_threshold=dedup_threshold,
                workers=workers,
                no_downscale=no_downscale,
                vlm_provider=vlm_provider,
                scene=scene,
            ),
        )
    except Exception as e:  # noqa: BLE001 — 配置装配兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(1, f"配置装配失败: {e}")
    ws = Path(directory).resolve()
    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
    if not images:
        return _error(3, "目录中无支持格式的图片")

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scorer = make_scorer(config)
        scored = scorer.score_paths(images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:  # noqa: BLE001 — 工具入口兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    # 可复现性回显：VLM 实际生效采样参数进 summary.vlm_sampling（未启用时为 None，
    # extra 不并入，报告结构与既有契约一致）
    sampling = sampling_params_for_config(config)
    extra = {"vlm_sampling": sampling} if sampling is not None else None
    return _build_report(
        scored, elapsed_ms, extra=extra, phase1_stats=scorer.phase1_stats
    )


@mcp.tool()
def score_single_image(
    image_path: str,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    enable_noise: bool | None = None,
    enable_color: bool | None = None,
    enable_portrait: bool | None = None,
    dedup_threshold: int | None = None,
    vlm_provider: str | None = None,
    scene: str | None = None,
    no_downscale: bool | None = None,
) -> str:
    """对单张图片进行评分，返回该图的详细评分数据。

    仅允许读取「允许扫描根」内的图片（环境变量 FLASHGAZE_MCP_ALLOWED_ROOTS
    配置，逗号分隔多个根；未配置时默认仅限服务器启动目录），越界路径拒绝（code 1）。

    Args:
        image_path: 图片文件的绝对路径（必须位于允许扫描根内）
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        enable_noise: 是否启用 BRISQUE 噪点评分（需 opencv-contrib-python，默认 False）
        enable_color: 是否启用色彩丰富度评分（默认 False）
        enable_portrait: 是否启用人像专项评分（需 face_recognition，默认 False）
        dedup_threshold: PHash 汉明距离阈值（默认 8，单图模式仅用于配置一致性）
        vlm_provider: VLM 提供商（qwen / openai / anthropic / ollama，默认 qwen；所有 provider 走内置 pin-IP 直连层，无需 litellm，litellm 仅可选兜底）
        scene: 场景模式（auto / portrait / landscape / still_life，默认 auto 由 VLM 自行判断）
        no_downscale: 是否禁用降采样（长边缩至 1024），默认 None（不覆盖，回落到 env/default 启用降采样，与现行为一致）；True 时使用原始分辨率

    Returns:
        JSON 字符串，包含该图的 sharpness/exposure/score 等字段。
    """
    # H-12：边界校验先于存在性检查，越界路径不做任何文件系统访问
    p = Path(image_path)
    roots = _allowed_scan_roots()
    if not any(is_within_directory(p, root) for root in roots):
        get_logger().warning("MCP: 拒绝允许扫描根之外的路径: %s", image_path)
        return _error(
            1,
            f"image_path {image_path} 位于允许扫描根之外，已拒绝。"
            f"当前允许扫描根: {', '.join(str(r) for r in roots)}"
            f"（可用环境变量 {ENV_MCP_ALLOWED_ROOTS} 配置）",
        )

    if not p.is_file():
        return _error(3, f"文件不存在: {image_path}")

    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return _error(3, f"不支持的图片格式: {p.suffix}")

    # 单图模式无 top / threshold / workers / dedup，对应旋钮留空即可
    try:
        config = _config_from(
            str(p.parent),
            ScoringOptions(
                no_vlm=no_vlm,
                enable_composition=enable_composition,
                enable_noise=enable_noise,
                enable_color=enable_color,
                enable_portrait=enable_portrait,
                dedup_threshold=dedup_threshold,
                no_downscale=no_downscale,
                vlm_provider=vlm_provider,
                scene=scene,
            ),
        )
    except Exception as e:  # noqa: BLE001 — 配置装配兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(1, f"配置装配失败: {e}")

    if err := _validate_vlm(config):
        return err

    try:
        # 复用 make_scorer 保证 CVEngine/VLMClient 装配逻辑与其他工具一致
        # 注意：必须用 config.enable_*（已解析为 bool），
        # 不能直接用参数本身（可能是 None）
        result = make_scorer(config).score_one(image_path)
    except Exception as e:  # noqa: BLE001 — 工具入口兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(4, f"评分过程异常: {e}")

    # 单图模式：返回 images:[result] 单元素数组，summary.selected 恒为 0
    # （单图不判断入选，selected 字段无意义，调用方应依据 score 自行决策）
    return _success(
        summary={
            "total": 1,
            "selected": 0,
            "avg_score": result.score,
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
    enable_noise: bool | None = None,
    enable_color: bool | None = None,
    enable_portrait: bool | None = None,
    dedup: bool | None = None,
    dedup_threshold: int | None = None,
    dest_dir: str = "./精选",
    move: bool = False,
    workers: int | None = None,
    vlm_provider: str | None = None,
    scene: str | None = None,
    no_downscale: bool = False,
) -> str:
    """评分后自动将高分图复制或移动到目标目录（同名文件自动追加序号后缀）。

    Args:
        directory: 源图片目录路径
        top: 选取前 N 张（默认 30）
        threshold: 分数阈值（替代 top）
        no_vlm: 是否禁用 VLM（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        enable_noise: 是否启用 BRISQUE 噪点评分（需 opencv-contrib-python，默认 False）
        enable_color: 是否启用色彩丰富度评分（默认 False）
        enable_portrait: 是否启用人像专项评分（需 face_recognition，默认 False）
        dedup: 是否启用 PHash 图片去重（需 imagededup，默认 False）
        dedup_threshold: PHash 汉明距离阈值（默认 8，越小越严格）
        dest_dir: 目标目录路径（默认 ./精选；相对路径以 directory 为基准解析，与 CLI --export-dir 一致）
        move: True 移动文件，False 复制文件（默认 False）
        workers: 并发线程数
        vlm_provider: VLM 提供商（qwen / openai / anthropic / ollama，默认 qwen；所有 provider 走内置 pin-IP 直连层，无需 litellm，litellm 仅可选兜底）
        scene: 场景模式（auto / portrait / landscape / still_life，默认 auto 由 VLM 自行判断）

    Returns:
        JSON 字符串，包含评分摘要和导出数量。零失败时 status="success"、
        code=0、summary.export_failed=0；存在未导出的入选图时 status="partial"、
        code=5（与 CLI 退出码 5 同义），summary 含 export_failed 计数，
        details.failures 给出逐项 {file, path, error} 明细。
    """
    if not Path(directory).is_dir():
        return _error(3, f"目录不存在: {directory}")

    if not dest_dir or not dest_dir.strip():
        return _error(1, "dest_dir 不能为空")

    # M2 路径穿越防护：dest_dir 来自不可信 Agent，必须落在 workspace 内。
    # 越界即硬拒绝（与 "dest_dir 不能为空" 同为参数错误 code=1），杜绝把选中图
    # 写出 workspace 到任意绝对路径。N-1 契约对齐：相对 dest_dir 以 workspace 为
    # 基准解析（与 CLI _safe_output_path 同源），服务进程 CWD ≠ workspace 时
    # 默认 ./精选 也解析到 ws 内并放行。
    ws = Path(directory).resolve()
    dest_dir = (
        str((ws / dest_dir).resolve())
        if not Path(dest_dir).is_absolute()
        else str(Path(dest_dir).resolve())
    )
    if not is_within_directory(Path(dest_dir), ws):
        return _error(
            1,
            f"dest_dir {dest_dir} 位于工作目录 {ws} 之外（路径穿越风险，已拒绝）",
        )

    # export / move 属导出域，不进 ScoringOptions，仍由 replace 叠加
    try:
        base_config = _config_from(
            directory,
            ScoringOptions(
                top=top,
                threshold=threshold,
                no_vlm=no_vlm,
                enable_composition=enable_composition,
                enable_noise=enable_noise,
                enable_color=enable_color,
                enable_portrait=enable_portrait,
                dedup=dedup,
                dedup_threshold=dedup_threshold,
                workers=workers,
                vlm_provider=vlm_provider,
                scene=scene,
                no_downscale=no_downscale,
            ),
        )
    except Exception as e:  # noqa: BLE001 — 配置装配兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(1, f"配置装配失败: {e}")
    config = replace(base_config, export=True, move=move)

    # C-01：与 cleanup / score_images 对齐，扫描阶段排除导出副本目录与 EXIF 备份
    # 目录，避免把已导出的 ./精选 副本重新扫描评分、再导出带序号后缀的重复文件，
    # 并防止备份图污染入选统计。ws 已在 M2 校验处解析（单次 resolve，复用）。
    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
    if not images:
        return _error(3, "目录中无支持格式的图片")

    if err := _validate_vlm(config):
        return err

    try:
        scored = make_scorer(config).score_paths(images)
    except Exception as e:  # noqa: BLE001 — 工具入口兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    try:
        exporter = Exporter(config)
        exported_count = exporter.export_images(scored, dest_dir)
    except OSError as e:
        return _error(5, f"导出失败: {e}")
    except Exception as e:  # noqa: BLE001 — 非 OSError 异常同样收敛为六字段错误响应（MED-2）：
        # 与其余 4 个工具的统一响应契约对齐，绝不向 MCP 框架裸抛非六字段结构。
        return _error(5, f"导出过程异常: {e}")

    selected = [s for s in scored if s.selected]
    # H-9/M-13：返回值只给成功数——「声称入选 30 张、实际导出 12 张」此前仍以
    # status="success" / code=0 收场，Agent 不会重试也不会告警，用户拿到一份
    # 不完整的精选集却毫不知情。存在失败项时报非 0（code=5，与 CLI 退出码同义）
    # + status="partial"（复用 _error 既有 status 形参，与 M-11 "blocked" 同机制），
    # 六字段 Schema 与 summary/details 完整保留。
    if exporter.last_failures:
        return _error(
            int(ExitCode.EXPORT_ERROR),
            f"导出部分失败：{len(exporter.last_failures)}/{exporter.last_expected} "
            "张未导出（详见 details.failures）",
            summary={
                "total": len(scored),
                "selected": len(selected),
                "exported": exported_count,
                "export_failed": len(exporter.last_failures),
            },
            details={
                "dest_dir": str(Path(dest_dir).resolve()),
                "mode": "move" if move else "copy",
                "failures": exporter.last_failures,
            },
            status="partial",
        )
    return _success(
        summary={
            "total": len(scored),
            "selected": len(selected),
            "exported": exported_count,
            # 零失败也显式给 0（不是缺失）：Agent 可对两个 status 统一读取同一键
            "export_failed": 0,
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
    enable_noise: bool | None = None,
    enable_color: bool | None = None,
    enable_portrait: bool | None = None,
    dedup: bool | None = None,
    dedup_threshold: int | None = None,
    workers: int | None = None,
    vlm_provider: str | None = None,
    scene: str | None = None,
    no_downscale: bool = False,
) -> str:
    """对上传的图片路径列表进行评分，返回 JSON 评分报告。

    适用于 AI Agent 收到用户上传的图片后，直接传入路径列表进行评分。
    不依赖目录结构，按给定的图片路径逐一评分。
    仅允许读取「允许扫描根」内的图片（环境变量 FLASHGAZE_MCP_ALLOWED_ROOTS
    配置，逗号分隔多个根；未配置时默认仅限服务器启动目录），越界路径列入 skipped。

    Args:
        image_paths: 图片文件路径列表（绝对路径，必须位于允许扫描根内）
        top: 选取前 N 张高分图（默认 30）
        threshold: 分数阈值，设置后忽略 top
        no_vlm: 是否禁用 VLM 仅用 CV 评分（默认 False）
        enable_composition: 是否启用构图评分（实验性，默认 False）
        enable_noise: 是否启用 BRISQUE 噪点评分（需 opencv-contrib-python，默认 False）
        enable_color: 是否启用色彩丰富度评分（默认 False）
        enable_portrait: 是否启用人像专项评分（需 face_recognition，默认 False）
        dedup: 是否启用 PHash 图片去重（需 imagededup，默认 False）
        dedup_threshold: PHash 汉明距离阈值（默认 8，越小越严格）
        workers: 并发线程数（默认 4）
        vlm_provider: VLM 提供商（qwen / openai / anthropic / ollama，默认 qwen；所有 provider 走内置 pin-IP 直连层，无需 litellm，litellm 仅可选兜底）
        scene: 场景模式（auto / portrait / landscape / still_life，默认 auto 由 VLM 自行判断）
        no_downscale: 是否禁用降采样（长边缩至 1024），默认 False（启用降采样，与现行为一致）；True 时使用原始分辨率

    Returns:
        JSON 字符串，包含 summary 和 images 数组。
        skipped 字段列出允许扫描根之外的路径、不存在的路径或不支持的格式。
    """
    if not image_paths:
        return _error(1, "image_paths 为空，请提供至少一个图片路径")

    # H-12：先做允许根包含性过滤，再走格式过滤；越界路径在 stat 前即被拒
    roots = _allowed_scan_roots()
    in_roots, rejected = _reject_outside_roots(image_paths, roots)
    valid_images, skipped = _filter_image_files(in_roots)
    skipped = rejected + skipped

    if not valid_images:
        message = f"无有效图片文件。跳过: {'; '.join(skipped)}"
        if rejected:
            message += (
                f"。允许扫描根: {', '.join(str(r) for r in roots)}"
                f"（可用环境变量 {ENV_MCP_ALLOWED_ROOTS} 配置）"
            )
        return _error(3, message)

    # 上传模式按显式路径评分（见下方 score_paths），不依赖任何目录扫描，
    # 故 directory 留空。绝不能填首图父目录：那会让人误以为它决定评分范围，
    # 一旦将来有人据此改成 iter_images(config.directory)，就会漏掉其它目录的
    # 上传图、并误吞该目录下不属于本次上传的图。留空能让这种误用立刻暴露。
    try:
        config = _config_from(
            directory="",
            opts=ScoringOptions(
                top=top,
                threshold=threshold,
                no_vlm=no_vlm,
                enable_composition=enable_composition,
                enable_noise=enable_noise,
                enable_color=enable_color,
                enable_portrait=enable_portrait,
                dedup=dedup,
                dedup_threshold=dedup_threshold,
                workers=workers,
                no_downscale=no_downscale,
                vlm_provider=vlm_provider,
                scene=scene,
            ),
        )
    except Exception as e:  # noqa: BLE001 — 配置装配兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(1, f"配置装配失败: {e}")

    if err := _validate_vlm(config):
        return err

    try:
        start = time.time()
        scorer = make_scorer(config)
        scored = scorer.score_paths(valid_images)
        elapsed_ms = int((time.time() - start) * 1000)
    except Exception as e:  # noqa: BLE001 — 工具入口兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    sampling = sampling_params_for_config(config)
    extra = {"vlm_sampling": sampling} if sampling is not None else None
    return _build_report(
        scored,
        elapsed_ms,
        extra=extra,
        details={"skipped": skipped},
        phase1_stats=scorer.phase1_stats,
    )


# ── MCP 工具：工作空间清理模式 ────────────────────────


@mcp.tool()
def cleanup_workspace_images(
    workspace: str,
    top: int | None = None,
    threshold: float | None = None,
    no_vlm: bool | None = None,
    enable_composition: bool | None = None,
    enable_noise: bool | None = None,
    enable_color: bool | None = None,
    enable_portrait: bool | None = None,
    dedup: bool | None = None,
    dedup_threshold: int | None = None,
    dry_run: bool = True,
    workers: int | None = None,
    vlm_provider: str | None = None,
    scene: str | None = None,
    no_downscale: bool = False,
    scored: list[ImageScore] | None = None,
    trust_scored: bool = False,
    force: bool = False,
    confirm_fingerprint: str | None = None,
    recycle: bool = True,
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
        enable_noise: 是否启用 BRISQUE 噪点评分（需 opencv-contrib-python，默认 False）
        enable_color: 是否启用色彩丰富度评分（默认 False）
        enable_portrait: 是否启用人像专项评分（需 face_recognition，默认 False）
        dedup: 是否启用 PHash 图片去重（需 imagededup，默认 False）
        dedup_threshold: PHash 汉明距离阈值（默认 8，越小越严格）
        dry_run: 试运行模式，只报告将要删除哪些文件，不实际删除（默认 True）
        workers: 并发线程数
        vlm_provider: VLM 提供商（qwen / openai / anthropic / ollama，默认 qwen；所有 provider 走内置 pin-IP 直连层，无需 litellm，litellm 仅可选兜底）
        scene: 场景模式（auto / portrait / landscape / still_life，默认 auto 由 VLM 自行判断）
        scored: 预评分结果（ImageScore 列表，通常来自先前的 score_images 调用）。**默认
            不信任入参分数**：仅复用损坏标记（error 非 None 的图归入 unevaluated、不重
            解码），分数一律重算（C-09：防伪造预评分指定删除集合——伪造分数 + top=N
            即可让「除伪造高分外全部被删」）。显式传 trust_scored=True 才按路径索引
            复用入参分数、仅对磁盘新出现的图重算；此时 top/threshold 对**全部**图片
            （含复用项）统一生效：复用项的 selected 会按当前 top/threshold 重算，
            不再沿用评分报告中的旧标志，与"无 scored 时 top/threshold 生效"行为完全
            对称。为 None 时全量重算（默认）。
        trust_scored: 显式信任复用 scored 中的分数（默认 False）。传入分数须为有限值
            且落在 [0, 100]，任一违反整体拒绝执行（不静默钳制）；实际口径以
            summary.scored_source 透明标注（engine / caller / engine_with_caller_errors）。
        force: 显式确认开关（默认 False）。实际删除（dry_run=False）时若待删比例
            超过 95% 且图片数不少于 20，护栏会整批拦截、一张不删，全部候选进入
            blocked_files 且 summary.force_required=True；确认无误后须**同时**传
            force=True 与已核对的清单指纹 confirm_fingerprint 才会真正删除。
        confirm_fingerprint: 待删清单指纹（取自上一次 dry_run 报告的
            summary.fingerprint）。force=True 时必填：缺失或与当前待删清单不符
            → status="blocked"，一张不删。两步确认：先 dry_run 核对、后 force 放行。
        recycle: 默认 True，删除的图片同卷移入 workspace 内 .flashgaze_deleted/
            回收站（字节完整可恢复），并逐张落盘 .flashgaze_deleted_*.jsonl 审计
            清单（原路径/回收站路径/SHA256）。False 时直接删除（无回滚点），仍写审计。

    Returns:
        JSON 字符串，包含评分摘要和将要删除/已删除的文件列表。
        损坏图（评分 error）既不删除也不入选，归入 unevaluated_files，
        需用户手动处理。

        存在删除失败项（文件被占用 / 只读 / 跨卷）时不以成功收场：返回
        `status="partial"`、`code=5`（与 CLI `flashgaze cleanup` 的退出码同义），
        `summary.delete_failures` 给出未删除张数、`details.delete_failures` 给出
        逐项 `{path, reason}`；其余图照常处理。全部删除成功时 `status="success"`、
        `code=0`，且 `summary.delete_failures` 显式为 0。
    """
    if top is not None and top < 1:
        return _error(1, "top 必须 >= 1，禁止传 0（会清空整个工作空间）")

    ws = Path(workspace).resolve()

    if not ws.is_dir():
        return _error(3, f"工作空间目录不存在: {workspace}")

    # FIX(#14-1): 与 CLI run_cleanup 对齐——先构建 config 以解析导出副本目录，
    # 并在扫描阶段排除导出副本目录与 EXIF 备份目录，避免把精选副本/备份图重新扫描、
    # 评分并纳入删除候选。此前 MCP 清理未排除这两类目录，与 CLI 安全约定不一致。
    # 排除逻辑统一走 exclusion_dirs 单一真源（相对 export_dir 解析到 ws、backup 做
    # resolve），与 score_images / export_selected_images / run_cleanup 行为一致。
    try:
        config = _config_from(
            str(ws),
            ScoringOptions(
                top=top,
                threshold=threshold,
                no_vlm=no_vlm,
                enable_composition=enable_composition,
                enable_noise=enable_noise,
                enable_color=enable_color,
                enable_portrait=enable_portrait,
                dedup=dedup,
                dedup_threshold=dedup_threshold,
                workers=workers,
                vlm_provider=vlm_provider,
                scene=scene,
                no_downscale=no_downscale,
            ),
        )
    except Exception as e:  # noqa: BLE001 — 配置装配兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(1, f"配置装配失败: {e}")

    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
    if not images:
        return _error(3, "工作空间中无支持格式的图片")

    if err := _validate_vlm(config):
        return err

    # 复用清理核心的 _resolve_scored（C-09 来源可信度分级）：scored 为 None 时全量
    # 重算；默认（trust_scored=False）仅复用损坏标记、分数一律重算；显式
    # trust_scored=True 才复用入参分数（校验 [0,100] 有限值，非法整体拒绝）。
    try:
        scored, scored_source = _resolve_scored(images, scored, config, trust_scored=trust_scored)
    except Exception as e:  # noqa: BLE001 — 工具入口兜底：任何异常收敛为错误响应，不向 MCP 框架裸抛
        return _error(4, f"评分过程异常: {e}")

    if not scored:
        return _error(3, "评分结果为空")

    # 删除与安全校验逻辑委托给 core/cleanup（与 CLI 共用，护栏逐字保留）
    try:
        result = classify_and_delete(
            ws,
            scored,
            dry_run=dry_run,
            force=force,
            recycle=recycle,
            confirm_fingerprint=confirm_fingerprint,
        )
    except CleanupError as e:
        return _error(e.code, str(e))

    # C-09：实际口径透明标注（blocked/partial/success 分支均复制 summary，自动携带）
    result["summary"]["scored_source"] = scored_source

    deleted_files = [
        d["file"] for d in (result["deleted"] if not dry_run else result["pending_delete"])
    ]
    blocked_files = [f"{b['path']} ({b['reason']})" for b in result["blocked"]]
    details = {
        "kept_images": result["kept"],
        "deleted_files": deleted_files,
        "blocked_files": blocked_files,
        "unevaluated_files": result["unevaluated"],
    }

    # M-11：删除护栏触发（待删比例超阈值且未显式 force）时一张未删，绝不能报
    # success——否则 Agent 会误判「已按要求清理」。返回非 0 码 + status="blocked"，
    # 与 CLI（`flashgaze cleanup` 护栏触发 → 退出码 1）的程序化约定对齐。
    # summary/details 原样保留，调用方仍可读 force_required 与完整拦截清单。
    if result["summary"].get("force_required"):
        return _error(
            int(ExitCode.PARAM_ERROR),
            "删除护栏已拦截：未删除任何文件。请核对 details.blocked_files，"
            "确认无误后先以 dry_run=True 取 summary.fingerprint 核对待删清单，"
            "再传 force=True 与 confirm_fingerprint 重新执行",
            summary=result["summary"],
            details=details,
            status="blocked",
        )

    # force 指纹强绑定（两步确认）：force=True 而指纹缺失/不符时同样一张未删，
    # 与 CLI（退出码 1）的 blocked 语义对齐，六字段 Schema 不变。
    if result["summary"].get("confirm_required"):
        return _error(
            int(ExitCode.PARAM_ERROR),
            "删除确认拦截：force=True 缺少已核对的清单指纹，未删除任何文件。"
            f"请先以 dry_run=True 核对待删清单，再传 force=True 与 "
            f"confirm_fingerprint={result['summary']['fingerprint']} 重新执行",
            summary=result["summary"],
            details=details,
            status="blocked",
        )

    # H-10：删除失败（文件被占用 / 只读 / 跨卷）此前一律以 status="success" / code=0
    # 收场——Agent 读到「清理已完成」并据此汇报，而低分图仍在磁盘上，唯一线索只有
    # details.blocked_files 里「路径 (删除失败: …)」的文本拼接，无任何程序化信号。
    # 现按 blocked[].kind 结构化判定（与 CLI 的 LOW-2 约定同源），复用 M-13 导出部分
    # 失败的响应形态：非 0 码 + status="partial" + summary.delete_failures 整数计数
    # + details.delete_failures 逐项明细。六字段 Schema、既有 summary/details 键与
    # blocked_files 文本格式零变化。判据保留 not dry_run 只为与 CLI 逐字同构：
    # classify_and_delete 在 dry_run 下只写 pending_list，结构上不产生该 kind。
    delete_failures = [
        {"path": b["path"], "reason": b.get("reason", "")}
        for b in result["blocked"]
        if b.get("kind") == "delete_failure"
    ]
    if not dry_run and delete_failures:
        failed_summary: dict[str, Any] = dict(result["summary"])
        failed_summary["delete_failures"] = len(delete_failures)
        failed_details: dict[str, Any] = dict(details)
        failed_details["delete_failures"] = delete_failures
        return _error(
            int(ExitCode.EXPORT_ERROR),
            f"删除部分失败：{len(delete_failures)} 张未删除（详见 details.delete_failures）",
            summary=failed_summary,
            details=failed_details,
            status="partial",
        )
    ok_summary: dict[str, Any] = dict(result["summary"])
    # 零失败也显式给 0（不是缺失）：Agent 可对 success / partial 统一读取同一键（M-13）
    ok_summary["delete_failures"] = 0
    return _success(summary=ok_summary, details=details)


if __name__ == "__main__":
    mcp.run()

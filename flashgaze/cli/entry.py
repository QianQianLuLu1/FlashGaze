"""CLI 主入口。

编排 CVEngine / VLMClient / HybridScorer / Exporter，映射返回码。
stdout 只输出 JSON 数据（--json 时），日志一律走 stderr。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from flashgaze.cli.parser import CLIParser
from flashgaze.core.exporter import Exporter
from flashgaze.core.factory import make_scorer
from flashgaze.defaults import DEFAULT_CSV_OUTPUT, DEFAULT_XLSX_OUTPUT
from flashgaze.models.schemas import ExitCode
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger, set_verbose


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    logger = get_logger()

    # 参数解析
    try:
        config = CLIParser().parse(argv)
    except SystemExit as e:
        # argparse 在 --version / --help 时 code=0，参数错误时 code=2
        return ExitCode.PARAM_ERROR if e.code else ExitCode.SUCCESS

    set_verbose(config.verbose)

    start = time.time()

    # 一次性遍历目录图片列表（缓存复用，避免 entry 预检查 + score_batch 双重遍历）
    images = list(iter_images(config.directory))
    if not images:
        logger.error("目录无效或无支持图片: %s", config.directory)
        return ExitCode.NO_IMAGES

    # VLM 前置校验：未禁用 VLM 且缺 key 直接退出（错误处理留在 CLI 调用方）
    if not config.no_vlm and not config.api_key:
        logger.error("未配置 API Key，请设置 FLASHGAZE_API_KEY 或传 --api-key")
        return ExitCode.CONFIG_ERROR

    # 评分（复用已缓存的图片列表，verbose 时输出进度到 stderr）
    scorer = make_scorer(config)

    def _progress(done: int, total: int) -> None:
        logger.info("进度 %d/%d", done, total)

    try:
        scored = scorer.score_paths(images, progress_callback=_progress)
    except Exception as e:
        logger.error("评分失败: %s", e)
        return ExitCode.IMAGE_ERROR
    if not scored:
        logger.error("评分结果为空")
        return ExitCode.NO_IMAGES

    # EXIF 元数据写入（M2）：评分完成后、导出之前
    if config.exif:
        try:
            from flashgaze.core.exif_writer import ExifWriter
            writer = ExifWriter(preserve_original=not config.no_exif_backup)
            results = writer.write_batch(scored)
            success = sum(1 for r in results if r.ok)
            logger.info("EXIF 写入: %d/%d 成功", success, len(results))
        except ImportError:
            logger.error("piexif 未安装，请运行 pip install -e \".[exif]\"")
            return ExitCode.CONFIG_ERROR

    elapsed_ms = int((time.time() - start) * 1000)

    # 导出与清单
    exporter = Exporter(config)
    if config.export:
        try:
            exported = exporter.export_images(scored, config.export_dir)
            logger.info("导出 %d 张至 %s", exported, config.export_dir)
        except OSError as e:
            logger.error("导出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    # JSON 走 stdout（供 Agent 消费）
    if config.output_json:
        try:
            _emit_json(exporter, scored, elapsed_ms, config)
        except OSError as e:
            logger.error("JSON 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    if config.output_csv:
        csv_path = config.csv_output_path or DEFAULT_CSV_OUTPUT
        try:
            exporter.write_manifest(scored, "csv", csv_path)
        except OSError as e:
            logger.error("CSV 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    # XLSX 清单（M3）：lazy import，未装 openpyxl 时明确报错退出，不污染其他导出
    if config.output_xlsx:
        xlsx_path = config.xlsx_output_path or DEFAULT_XLSX_OUTPUT
        try:
            from flashgaze.core.xlsx_exporter import XlsxExporter
            XlsxExporter().write(scored, xlsx_path)
            logger.info("XLSX 清单已写入 %s", xlsx_path)
        except ImportError:
            logger.error("openpyxl 未安装，请运行 pip install -e \".[xlsx]\"")
            return ExitCode.CONFIG_ERROR
        except OSError as e:
            logger.error("XLSX 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    logger.info("完成: %d 张图，耗时 %d ms", len(scored), elapsed_ms)
    return ExitCode.SUCCESS


def _emit_json(exporter, scored, elapsed_ms: int, config) -> None:
    """输出 JSON 到 stdout 或文件。复用 Exporter.build_report 统一序列化。"""
    data = exporter.build_report(scored, elapsed_ms)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if config.output_path:
        Path(config.output_path).write_text(text, encoding="utf-8")
    else:
        print(text)  # stdout


if __name__ == "__main__":
    sys.exit(main())

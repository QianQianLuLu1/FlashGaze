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
from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.exporter import Exporter
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.core.vlm_client import VLMClient
from flashgaze.defaults import DEFAULT_CSV_OUTPUT
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

    # 引擎装配
    cv_engine = CVEngine(enable_composition=config.enable_composition)
    vlm_client = None
    if not config.no_vlm:
        if not config.api_key:
            logger.error("未配置 API Key，请设置 FLASHGAZE_API_KEY 或传 --api-key")
            return ExitCode.CONFIG_ERROR
        vlm_client = VLMClient(
            api_key=config.api_key,
            api_base=config.api_base,
            model=config.model,
            timeout_sec=config.timeout_sec,
            max_retries=config.max_retries,
            max_adjustment=config.vlm_max_adjustment,
            vlm_lang=config.vlm_lang,
        )

    # 评分（复用已缓存的图片列表，verbose 时输出进度到 stderr）
    scorer = HybridScorer(cv_engine, vlm_client, config)

    def _progress(done: int, total: int) -> None:
        # 总数超过 50 张时，即使非 verbose 也每 10 张输出一次进度到 stderr，
        # 让用户在大批量评分时能感知处理进度，避免长时间无输出的"卡死"错觉
        if total > 50 and done % 10 == 0:
            print(f"进度: {done}/{total}", file=sys.stderr)
        logger.info("进度 %d/%d", done, total)

    scored = scorer.score_paths(images, progress_callback=_progress)
    if not scored:
        logger.error("评分结果为空")
        return ExitCode.NO_IMAGES

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
        _emit_json(exporter, scored, elapsed_ms, config)

    if config.output_csv:
        csv_path = config.csv_output_path or DEFAULT_CSV_OUTPUT
        exporter.write_manifest(scored, "csv", csv_path)

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

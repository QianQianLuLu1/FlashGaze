"""CLI 主入口。

编排 CVEngine / VLMClient / HybridScorer / Exporter / cleanup，映射返回码。
stdout 只输出 JSON 数据（--json 时），日志一律走 stderr。

子命令：
- score   ：目录评分（默认，向后兼容 `flashgaze <目录>`）
- cleanup ：评分后原地删除低分图（默认 --dry-run，显式 --apply 才删除）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flashgaze.cli.parser import CLIParser
from flashgaze.cli.progress import make_progress_reporter
from flashgaze.core.cleanup import (
    CleanupError,
    exclusion_dirs,
    restore_from_manifest,
    run_cleanup,
)
from flashgaze.core.cv_engine import BrisqueIntegrityError
from flashgaze.core.exporter import Exporter, ExportOutcome
from flashgaze.core.factory import make_scorer
from flashgaze.core.vlm_client import sampling_params_for_config
from flashgaze.defaults import DEFAULT_CSV_OUTPUT, DEFAULT_XLSX_OUTPUT
from flashgaze.models.schemas import Config, ExitCode, ImageScore
from flashgaze.utils.atomic_write import atomic_write_text, cleanup_stale_tmp
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger, set_verbose

if TYPE_CHECKING:
    # 仅类型检查期导入：piexif 属可选依赖，exif_writer 运行时须 lazy import（见 _cmd_score）
    from flashgaze.core.exif_writer import ExifWriteResult


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    logger = get_logger()

    # 参数解析（兼容垫片在 parser 内：无子命令的旧用法补成 score）
    try:
        clp = CLIParser()
        ns = clp.parse_namespace(argv)
    except SystemExit as e:
        # argparse 在 --version / --help 时 code=0，参数错误时 code=2
        return ExitCode.PARAM_ERROR if e.code else ExitCode.SUCCESS

    set_verbose(getattr(ns, "verbose", False))

    command = ns.command or "score"
    try:
        if command == "cleanup":
            return _cmd_cleanup(clp, ns, logger)
        if command == "restore":
            return _cmd_restore(clp, ns, logger)
        return _cmd_score(clp, ns, logger)
    except SystemExit as e:
        # 配置装配的范围校验（--top/--threshold）与 LOW-1 输出路径前置校验
        # （score 全部落盘点 / cleanup 报告路径）都可能 sys.exit(2)，此处统一收敛
        return ExitCode.PARAM_ERROR if e.code else ExitCode.SUCCESS
    # 无 noqa: BLE001——本处理器逐句为「记录异常后返回退出码」，ruff 的盲捕获
    # 规则对此形态豁免（改成分支结构后会重新触发，届时须补回 noqa）。
    except Exception as e:  # 最后防线：杜绝裸 traceback（H-8）
        # H-8：子命令未自行收敛的异常此前穿透 main() 直达解释器，进程以 traceback
        # 终结并返回 Python 默认的 1，与 PARAM_ERROR 数值重叠导致 Agent/CI 误判。
        # 此处统一转为单行结构化日志 + 专用退出码；堆栈降级到 DEBUG（--verbose 才
        # 展开），兼顾「无 traceback」与「可诊断」。SystemExit 属 BaseException，
        # 由上方分支处理，参数错误通道不受影响。
        logger.error("未预期的内部错误（%s）: %s", type(e).__name__, e)
        logger.debug("内部错误堆栈", exc_info=True)
        return ExitCode.INTERNAL_ERROR


def _cmd_score(clp: CLIParser, ns: argparse.Namespace, logger: logging.Logger) -> int:
    """目录评分（原默认行为，逻辑不变）。"""
    try:
        config = clp._config_from_ns(ns)
    except Exception as e:  # noqa: BLE001 — 入口兜底：非 SystemExit 异常统一收敛为 CONFIG_ERROR（FIX #12-2）
        # FIX(#12-2): 配置装配（build_config 及范围校验外的逻辑）若抛非 SystemExit
        # 异常，原会冒泡为裸 traceback + exit 1；统一收敛为 CONFIG_ERROR 并保留日志。
        # （参数错误经 sys.exit(2) 抛 SystemExit，由 main 的 except SystemExit 映射为
        #  PARAM_ERROR，不在此捕获，避免重复处理。）
        logger.error("配置装配失败: %s", e)
        return ExitCode.CONFIG_ERROR
    # 输出路径未搭配对应开关 → 硬拒绝：三个落盘分支的启用条件只看开关字段
    # （output_json/output_csv/output_xlsx，见下方落盘点），路径旗标单独存在时
    # 本会静默丢弃并以退出码 0 结束——Agent 按退出码去读结果文件只会得到次生的
    # 「文件不存在」，用户以为已落盘，一次评分（含可能的 VLM 费用）白跑。
    # 判定源为装配后的 effective Config（与下游落盘 gate 逐字同源）：配置文件
    # 只给路径不给开关同样拦截，配置文件/CLI 启用开关则不误伤。放在扫描/评分
    # 之前：零 VLM 费用、零算力消耗（与 LOW-1 / H-2 同纪律）。
    if config.output_path and not config.output_json:
        logger.error("--output 需搭配 --json（仅提供路径不会启用 JSON 输出）；已中止，未进行评分")
        return ExitCode.PARAM_ERROR
    if config.csv_output_path and not config.output_csv:
        logger.error("--csv-output 需搭配 --csv（仅提供路径不会启用 CSV 输出）；已中止，未进行评分")
        return ExitCode.PARAM_ERROR
    if config.xlsx_output_path and not config.output_xlsx:
        logger.error(
            "--xlsx-output 需搭配 --xlsx（仅提供路径不会启用 .xlsx 输出）；已中止，未进行评分"
        )
        return ExitCode.PARAM_ERROR
    # M-07：--move / --export-dir 单独给出（未开 --export）时导出分支根本不进入，
    # 两参数静默无效、exit 0——按「已移动」做的后续清理会误删源文件。判定源与
    # 导出 gate（if config.export:）同源：move 看 effective Config（配置文件来源
    # 同样覆盖）；export_dir 的有效值恒被默认填充，显式提供与否只能看原始
    # 命名空间（配置文件来源的 export_dir 不在本校验范围，属已知缺口）。
    if config.move and not config.export:
        logger.error(
            "--move 需搭配 --export（单独提供不会启用导出，源文件不会被移动）；已中止，未进行评分"
        )
        return ExitCode.PARAM_ERROR
    if getattr(ns, "export_dir", None) is not None and not config.export:
        logger.error("--export-dir 需搭配 --export（仅提供目录不会启用导出）；已中止，未进行评分")
        return ExitCode.PARAM_ERROR
    # LOW-1: 全部输出路径的越界校验前置到评分之前——原先 export/csv/xlsx/json 的
    # 硬拒绝发生在 score_paths 之后，一次完整评分（VLM 费用 + 数分钟算力）白跑
    # 才报参数错误。越界在消耗任何资源前即以 PARAM_ERROR 退出。
    _prevalidate_output_paths(config, logger)

    # H-2：无回滚点的原地改写是显式危险操作——--exif 且关闭备份（CLI --no-exif-backup
    # 或配置文件 exif_backup: false，判定真源为 exif_backup）时必须加 --force 确认。
    # 与 cleanup 的 --force 护栏同语义。放在扫描/评分之前：与 LOW-1 同构，在消耗任何
    # 算力（VLM 费用 + 数分钟评分）之前先拒错，且绝不构造 ExifWriter（一张都不落笔）。
    if config.exif and not config.exif_backup and not getattr(ns, "force", False):
        logger.error(
            "--exif --no-exif-backup 将原地改写原图且不留 .flashgaze_backup 回滚点；"
            "确认后请加 --force 显式放行，或去掉 --no-exif-backup 保留备份"
        )
        return ExitCode.PARAM_ERROR

    _cleanup_output_tmp(config, logger)

    start = time.time()

    # 一次性遍历目录图片列表（缓存复用，避免 entry 预检查 + score_batch 双重遍历）
    # C-01：与 cleanup 对齐，扫描时排除导出副本目录与 EXIF 备份目录，避免重复运行
    # 时把 ./精选 副本或 .flashgaze_backup 备份图重新评分并污染统计。
    ws = Path(config.directory).resolve()
    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
    if not images:
        logger.error("目录无效或无支持图片: %s", config.directory)
        return ExitCode.NO_IMAGES

    # VLM 前置校验：未禁用 VLM 且缺 key 直接退出
    if not config.no_vlm and not config.api_key:
        logger.error("未配置 API Key，请设置 FLASHGAZE_API_KEY 或传 --api-key")
        return ExitCode.CONFIG_ERROR

    # 评分（复用已缓存的图片列表；进度展示三档：终端进度条 / verbose 日志行 / 静默）
    # H-8：make_scorer 必须与 score_paths 同处一个收敛块——CVEngine.__init__ 在
    # --enable-noise 下会加载 BRISQUE 模型（可抛 BrisqueIntegrityError），VLMClient
    # 构造亦会因端点被 SSRF 拒绝等抛 ValueError。此前它在 try 之外，构造期异常穿透
    # main() 直达解释器：裸 traceback + Python 默认退出码 1，与 PARAM_ERROR 数值重叠，
    # 依赖 stderr 解析的 Agent/CI 完全无法处理。reporter 提到 try 之前构造，
    # 保证 finally 的 close() 在任何失败路径都可达（close 幂等）。
    reporter = make_progress_reporter(verbose=bool(getattr(ns, "verbose", False)))
    constructing = True
    try:
        scorer = make_scorer(config)
        constructing = False
        scored = scorer.score_paths(images, progress_callback=reporter.update)
    except BrisqueIntegrityError as e:
        # 供应链信号（模型哈希不符）必须响亮失败，日志语义与 _cmd_cleanup 逐字一致
        # （M-05）。必须排在 Exception 之前：它是 RuntimeError 子类，后置会被通用
        # 分支抢先捕获、错标成「评分失败」。
        logger.error("模型完整性校验失败: %s", e)
        return ExitCode.IMAGE_ERROR
    except Exception as e:  # noqa: BLE001 — 评分/装配失败收敛为退出码，不向调用方裸抛
        if constructing:
            # 构造期失败 ≠ 评分失败：成因是配置/环境不可用（端点被拒、provider 非法、
            # 依赖缺失），与同文件「缺 API Key」「piexif 未安装」同族映射 CONFIG_ERROR，
            # 避免占用 README 标注为保留码的 IMAGE_ERROR。
            logger.error("评分器构造失败: %s", e)
            return ExitCode.CONFIG_ERROR
        logger.error("评分失败: %s", e)
        return ExitCode.IMAGE_ERROR
    finally:
        reporter.close()
    if not scored:
        logger.error("评分结果为空")
        return ExitCode.NO_IMAGES

    # EXIF 元数据写入：评分完成后、导出之前
    exif_results = None
    exif_failed = 0
    if config.exif:
        try:
            from flashgaze.core.exif_writer import ExifWriter

            # exif_backup 为单一真源（CLI --no-exif-backup 已在 build_config 归一化）。
            # H-2：关闭备份时同步传入差异撤销日志落点（.flashgaze_undo/）——即便没有
            # .flashgaze_backup 字节级回滚点，也保留「写入前 SHA256 + 原 UserComment」
            # 的最小可回退信息；备份开启时传 None，不产生额外磁盘痕迹。
            writer = ExifWriter(
                preserve_original=config.exif_backup,
                undo_log=None if config.exif_backup else _exif_undo_log_path(ws),
            )
            results = writer.write_batch(scored)
            success = sum(1 for r in results if r.ok)
            exif_failed = len(results) - success
            logger.info("EXIF 写入: %d/%d 成功", success, len(results))
            if exif_failed:
                # H-2/M-15：失败必须响亮且程序化可见（退出码 7 + summary.exif_failed），
                # 不再仅以 INFO 一笔带过、退出码 0 谎报完全成功。
                logger.error(
                    "EXIF 写入失败 %d/%d 张（详见 JSON summary.exif.failures 与 summary.exif_failed）",
                    exif_failed,
                    len(results),
                )
            exif_results = results
        except ImportError:
            logger.error('piexif 未安装，请运行 pip install -e ".[exif]"')
            return ExitCode.CONFIG_ERROR

    elapsed_ms = int((time.time() - start) * 1000)

    # 导出与清单
    exporter = Exporter(config)
    # H-9：导出部分失败的判定状态。「exported + len(failures) != 入选数」等式不作
    # 主判据——自定义 Exporter 的返回值口径可能与入选数不同（如按 scored 全量计数），
    # 等式会把这类成功场景误判为失败；以「存在本应导出却没导出的图」为准。
    export_failed = 0
    export_outcome: ExportOutcome | None = None
    if config.export:
        # 越界导出目录与 --output/--csv/--xlsx 统一硬拒绝：原 M2 决策（可信用户仅
        # warning 放行）与 FIX(#12-4) 的输出路径防护双强度不一致，路径同样可能来自
        # 不可信配置/上游脚本，现统一拒绝；破坏性变更已在 CHANGELOG [未发布] 声明。
        # N-1: 相对 export_dir 统一以 workspace 为基准解析，校验结果即落盘路径
        # （与 exclusion_dirs 的排除基准同源）——原先 export_images 收原始相对值、
        # 按落盘时 CWD 解析，CWD≠workspace 时导出会悄悄落到 workspace 之外。
        try:
            export_path = _safe_output_path(config.export_dir, config.directory)
        except UnsafeOutputPathError as e:
            logger.error("拒绝越界导出目录: %s", e)
            sys.exit(2)
        # 防御：export_dir 为空串时 _safe_output_path 返回 None，回退原值保持旧行为
        dest = str(export_path) if export_path is not None else config.export_dir
        try:
            exported = exporter.export_images(scored, dest)
            logger.info("导出 %d 张至 %s", exported, config.export_dir)
        except OSError as e:
            logger.error("导出失败: %s", e)
            return ExitCode.EXPORT_ERROR
        # H-9：返回值只给成功数，无法区分「入选 3 张全成」与「入选 30 张只成 3 张」。
        # last_failures 非空即存在本应导出却没导出的图（磁盘满 / 权限不足 / 源文件
        # 被外部删除 / 导出目标是普通文件），此前一律以退出码 0 收场。
        export_outcome = ExportOutcome(
            expected=exporter.last_expected,
            exported=exported,
            failures=exporter.last_failures,
        )
        if exporter.last_failures:
            export_failed = len(exporter.last_failures)
            logger.error(
                "导出部分失败：%d/%d 张未导出（详见 JSON summary.export_failed 与 "
                "summary.export.failures）",
                export_failed,
                exporter.last_expected,
            )
        elif exported != exporter.last_expected:
            # 计数不一致但无失败记录：仅告警，不进退出码（见上方判据说明）。
            logger.warning(
                "导出数 %d 与预期入选数 %d 不一致（无失败记录）", exported, exporter.last_expected
            )

    # JSON 走 stdout（供 Agent 消费）
    if config.output_json:
        try:
            _emit_json(
                exporter,
                scored,
                elapsed_ms,
                config,
                exif_results=exif_results,
                export=export_outcome,
                phase1_stats=scorer.phase1_stats,
                vlm_sampling=sampling_params_for_config(config),
            )
        except OSError as e:
            logger.error("JSON 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    if config.output_csv:
        try:
            csv_path = _safe_output_path(
                config.csv_output_path or DEFAULT_CSV_OUTPUT, config.directory
            )
        except UnsafeOutputPathError as e:
            logger.error("拒绝越界 CSV 输出路径: %s", e)
            sys.exit(2)
        try:
            exporter.write_manifest(scored, "csv", str(csv_path))
        except OSError as e:
            logger.error("CSV 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    # XLSX 清单：lazy import，未装 openpyxl 时明确报错退出
    if config.output_xlsx:
        try:
            xlsx_path = _safe_output_path(
                config.xlsx_output_path or DEFAULT_XLSX_OUTPUT, config.directory
            )
        except UnsafeOutputPathError as e:
            logger.error("拒绝越界 XLSX 输出路径: %s", e)
            sys.exit(2)
        try:
            from flashgaze.core.xlsx_exporter import XlsxExporter

            XlsxExporter().write(scored, str(xlsx_path))
            logger.info("XLSX 清单已写入 %s", xlsx_path)
        except ImportError:
            logger.error('openpyxl 未安装，请运行 pip install -e ".[xlsx]"')
            return ExitCode.CONFIG_ERROR
        except OSError as e:
            logger.error("XLSX 输出失败: %s", e)
            return ExitCode.EXPORT_ERROR

    logger.info("完成: %d 张图，耗时 %d ms", len(scored), elapsed_ms)
    # H-9：导出存在失败项时不再以 SUCCESS 收场——JSON/清单已照常产出（结果可观测
    # 优先于提前中止），由退出码 5 让 CI/Agent 程序化感知「声称导出 30 张、实际 12 张」。
    # 导出是用户显式要求的主产物，故优先于下方的 EXIF 失败（7）表达；两类失败都已
    # 各自打了 ERROR 日志，退出码只取其一不影响可观测性。
    if export_failed:
        return ExitCode.EXPORT_ERROR
    # H-2/M-15：EXIF 存在失败项时不再以 SUCCESS 收场——导出/清单已照常产出
    # （结果可观测优先于提前中止），由独立退出码 7 让 CI/Agent 程序化感知。
    if exif_failed:
        return ExitCode.EXIF_ERROR
    return ExitCode.SUCCESS


def _cmd_cleanup(clp: CLIParser, ns: argparse.Namespace, logger: logging.Logger) -> int:
    """工作空间清理：评分后原地删除低分图（默认 dry_run）。"""
    try:
        config = clp._config_from_ns(ns)
    except Exception as e:  # noqa: BLE001 — 入口兜底：配置装配异常统一收敛为 CONFIG_ERROR（FIX #12-2）
        # FIX(#12-2): 同 _cmd_score，配置装配异常统一收敛为 CONFIG_ERROR。
        logger.error("配置装配失败: %s", e)
        return ExitCode.CONFIG_ERROR

    # cleanup 报告落盘的启用条件以命名空间为源（与 _render_cleanup_report 逐字
    # 一致）：--output 单独存在时报告会被静默丢弃、退出码由删除结果决定，Agent
    # 无法感知报告从未产出。在 run_cleanup 之前拒绝，零评分算力、零删除副作用
    # （与下方 LOW-1(cleanup) / H-2 同纪律；不基于 config 判定的原因见下）。
    if getattr(ns, "output_path", None) and not getattr(ns, "output_json", False):
        logger.error("--output 需搭配 --json（cleanup 报告仅在 --json 下落盘）；已中止，未执行清理")
        return ExitCode.PARAM_ERROR

    # LOW-1(cleanup): 报告输出路径越界校验前置到 run_cleanup 之前——原校验只在
    # _render_cleanup_report 内部，评分（VLM 费用/数分钟算力）乃至 --apply 实删
    # 全部完成后才 sys.exit(2)，退出码 PARAM_ERROR 与「删除已成功」矛盾，且 JSON
    # 模式下报告只写文件不打印 stdout，唯一的机器可读结果记录随之丢失。与 score
    # 的 LOW-1 对齐：先拒错、后干活；判定以 ns 为源，启用条件与
    # _render_cleanup_report 逐字一致（不整体复用 _prevalidate_output_paths：
    # 它基于 config，会把配置文件里 cleanup 不消费的 export/csv/xlsx 路径也拿去
    # 校验，对原本可运行的 cleanup 造成误拒）。
    if getattr(ns, "output_json", False):
        try:
            _safe_output_path(getattr(ns, "output_path", None), ns.directory)
        except UnsafeOutputPathError as e:
            logger.error("拒绝越界报告输出路径: %s", e)
            sys.exit(2)

    # top>=1 护栏：禁止 0 或负值清空整个工作空间（CONFIG_ERROR/PARAM_ERROR 约定）
    if config.top < 1:
        logger.error("top 必须 >= 1，禁止传 0（会清空整个工作空间）")
        return ExitCode.PARAM_ERROR

    # VLM 前置校验：未禁用 VLM 且缺 key 直接退出
    if not config.no_vlm and not config.api_key:
        logger.error("未配置 API Key，请设置 FLASHGAZE_API_KEY 或传 --api-key")
        return ExitCode.CONFIG_ERROR

    dry_run = not ns.apply
    # FIX(#sec-threshold): 95% 删除护栏的显式确认开关。force 是"本次动作确认"而非
    # 评分旋钮，故不进 Config，只从命名空间逐层透传。
    force = bool(getattr(ns, "force", False))
    confirm_fingerprint = getattr(ns, "confirm_fingerprint", None)
    no_recycle = bool(getattr(ns, "no_recycle", False))

    # 不可逆删除防护（两步确认）：--force 必须与「已人工核对过的 dry_run 清单指纹」
    # 同行，--no-recycle（无回收站 = 无回滚点）同样属危险操作。与 H-2
    # （--exif --no-exif-backup 须 --force）同款纪律：**在评分之前先拒错**，
    # 不在必然被拦截的输入上白烧评分算力（VLM 费用 + 数分钟）。
    if force and not confirm_fingerprint:
        logger.error(
            "--force 必须配合 --confirm-fingerprint <指纹>：请先执行 dry_run 核对待删清单，"
            "再从报告 summary.fingerprint 取指纹回填"
        )
        return ExitCode.PARAM_ERROR
    if no_recycle and not force:
        logger.error("--no-recycle 直接删除且不进回收站（无回滚点），须配合 --force 显式确认")
        return ExitCode.PARAM_ERROR

    try:
        result = run_cleanup(
            ns.directory,
            config,
            dry_run=dry_run,
            force=force,
            recycle=not no_recycle,
            confirm_fingerprint=confirm_fingerprint,
        )
    except CleanupError as e:
        logger.error(str(e))
        return ExitCode.NO_IMAGES
    except BrisqueIntegrityError as e:
        # 供应链信号（模型哈希不符）必须响亮失败，保留图片处理错误码可见性。
        # 必须排在 RuntimeError 之前：BrisqueIntegrityError 是其子类，
        # 后捕获会被错标成「评分失败」日志（退出码相同，仅日志语义错位）。
        logger.error("模型完整性校验失败: %s", e)
        return ExitCode.IMAGE_ERROR
    except RuntimeError as e:
        # run_cleanup 把评分阶段异常统一包装为 RuntimeError("评分过程异常: ...")
        # FIX(#12-3): 仅评分阶段错误沿用「评分失败」标签与 IMAGE_ERROR，
        # 不再把分类/删除阶段的真实故障也错标为「评分失败」。
        logger.error("评分失败: %s", e)
        return ExitCode.IMAGE_ERROR
    except Exception as e:  # noqa: BLE001 — 入口兜底：清理阶段异常单独收敛为 EXPORT_ERROR（FIX #12-3）
        # FIX(#12-3): 评分之外的意外（分类/删除阶段或基础设施异常）单独标签，
        # 映射导出/IO 类错误码，调用方可区分「评分失败」与「清理/删除失败」。
        logger.error("清理阶段异常: %s", e)
        return ExitCode.EXPORT_ERROR

    _render_cleanup_report(result, ns, dry_run)

    # FIX(#sec-threshold): 护栏拦截时一张未删，返回参数错误码让脚本/Agent 可程序化
    # 识别（与 top<1 的既有处理一致），并提示补齐 --force 的正确做法。
    if result["summary"].get("force_required"):
        logger.error(
            "删除护栏已拦截：待删比例超过 95%，未删除任何文件。"
            "请核对上方待删列表，确认无误后先 dry_run 取指纹，"
            "再加 --force --confirm-fingerprint <指纹> 重新执行"
        )
        return ExitCode.PARAM_ERROR

    # force 指纹强绑定：指纹缺失/不符时一张未删，返回参数错误码让脚本/Agent
    # 程序化识别（与上方 force_required 同族），并给出当前清单指纹供回填。
    if result["summary"].get("confirm_required"):
        logger.error(
            "删除确认拦截：--confirm-fingerprint 缺失或与当前待删清单不符，未删除任何文件。"
            "请先执行 dry_run 核对待删列表，再加 --force --confirm-fingerprint %s 重新执行",
            result["summary"]["fingerprint"],
        )
        return ExitCode.PARAM_ERROR

    # 退出码：实际删除模式下若有"删除失败"类拦截，映射为 EXPORT_ERROR；
    # 路径/类型类安全拦截（dry_run 或实际）视为已安全处理，仍 SUCCESS。
    # LOW-2: 用 blocked 项的结构化 kind 字段判定，不再与 reason 文案前缀强耦合
    # （文案改动曾会静默破坏退出码语义；kind 由 classify_and_delete 统一写入）。
    has_delete_failure = any(b.get("kind") == "delete_failure" for b in result["blocked"])
    if not dry_run and has_delete_failure:
        return ExitCode.EXPORT_ERROR
    return ExitCode.SUCCESS


def _cmd_restore(clp: CLIParser, ns: argparse.Namespace, logger: logging.Logger) -> int:
    """删除恢复：按审计清单把回收站文件搬回原路径（删除不可逆防护的回滚闭环）。"""
    del clp  # restore 不消费评分配置，仅为与其它子命令同构的签名占位

    try:
        result = restore_from_manifest(ns.manifest, dry_run=bool(getattr(ns, "dry_run", False)))
    except CleanupError as e:
        logger.error(str(e))
        return ExitCode.PARAM_ERROR
    except Exception as e:  # noqa: BLE001 — 入口兜底：恢复阶段异常统一收敛为 EXPORT_ERROR
        logger.error("恢复阶段异常: %s", e)
        return ExitCode.EXPORT_ERROR

    s = result["summary"]
    dry_run = s["mode"] == "dry_run"
    mode_label = "试运行（不移动）" if dry_run else "实际恢复"
    print("=== FlashGaze 删除恢复 ===")
    print(f"模式: {mode_label}")
    print(f"审计清单: {s['manifest']}")
    stat_line = (
        f"记录总数 {s['total']} | {'可恢复' if dry_run else '已恢复'} "
        f"{s['pending'] if dry_run else s['restored']} | 失败 {s['failed']}"
    )
    print(stat_line)
    for r in result["restored"]:
        print(f"  → {r['original_path']}")
    for f in result["failed"]:
        print(f"  ✗ {f['path']} ({f['reason']})")

    if result["failed"]:
        # 失败明细已逐条打印（kind 结构化），退出码让脚本/Agent 程序化感知部分失败
        logger.error("存在 %d 条未能恢复的记录，详见上方清单", s["failed"])
        return ExitCode.EXPORT_ERROR
    return ExitCode.SUCCESS


def _render_cleanup_report(result: dict[str, Any], ns: argparse.Namespace, dry_run: bool) -> None:
    """渲染清理报告：--json 输出结构化结果，否则输出人类可读报告。"""
    if getattr(ns, "output_json", False):
        text = json.dumps(result, ensure_ascii=False, indent=2)
        try:
            out_path = _safe_output_path(getattr(ns, "output_path", None), ns.directory)
        except UnsafeOutputPathError as e:
            # 纵深防御：越界校验已前置到 _cmd_cleanup（LOW-1(cleanup)），正常 CLI 流
            # 不会再走到这里；保留以防绕过入口的直接调用与未来改动破坏前置顺序。
            get_logger().error("拒绝越界报告输出路径: %s", e)
            sys.exit(2)
        if out_path is not None:
            try:
                atomic_write_text(out_path, text)
            except OSError as e:
                # 兜底：报告落盘失败（权限/磁盘满等）时降级打印到 stdout，保证已删除
                # 结果的机器可读记录永不丢失；退出码仍由删除结果决定，不因写盘失败
                # 谎报失败（与 score 的 JSON 输出 OSError → EXPORT_ERROR 不同：此处
                # 评分/删除已发生，数据降级可达比失败码更重要）。
                get_logger().warning("清理报告写入 %s 失败，降级输出到 stdout: %s", out_path, e)
                print(text)
        else:
            print(text)
        return

    s = result["summary"]
    mode_label = "试运行（不删除）" if dry_run else "实际删除"
    stat_line = (
        f"评分总数 {s['total']} | 入选(保留) {s['selected']} | "
        f"待删除/已删 {s['to_delete']} | 损坏图 {s['unevaluated']} | 拦截 {s['blocked']}"
    )
    lines = [
        "=== FlashGaze 工作空间清理 ===",
        f"模式: {mode_label}",
        f"工作空间: {s['workspace']}",
        stat_line,
    ]

    # 评分口径行：部分 VLM 失败降级会使批内删除决策置信度不均一，显式提示。
    # vlm_error 非空 = "VLM 已尝试但失败"（含熔断跳过）；--no-vlm 时两计数均为 0，不输出。
    vlm_applied = s.get("vlm_applied", 0)
    vlm_degraded = s.get("vlm_degraded", 0)
    if vlm_degraded > 0:
        if vlm_applied == 0:
            caliber_line = (
                f"评分口径: 本批 VLM 全部失败/已熔断（{vlm_degraded} 张），删除决策全部基于纯 CV 分"
            )
        else:
            caliber_line = (
                f"评分口径: {vlm_applied} 张含 VLM 补偿 | {vlm_degraded} 张降级为纯 CV"
                "（VLM 失败/熔断，删除决策置信度较低）"
            )
        lines.append(caliber_line)

    if dry_run:
        lines.append("")
        lines.append(f"待删除（--apply 后才会真正删除）: {s['to_delete']} 张")
        for d in result["pending_delete"]:
            marker = "  [纯CV]" if d.get("vlm_error") else ""
            lines.append(f"  - {d['file']}  ({d['path']}){marker}")
    else:
        lines.append("")
        lines.append(f"已删除: {s['deleted']} 张")
        for d in result["deleted"]:
            marker = "  [纯CV]" if d.get("vlm_error") else ""
            lines.append(f"  - {d['file']}{marker}")

    if result["blocked"]:
        lines.append("")
        lines.append(f"已拦截（未删除）: {s['blocked']} 张")
        for b in result["blocked"]:
            lines.append(f"  - {b['path']} ({b['reason']})")

    if result["unevaluated"]:
        lines.append("")
        lines.append(f"损坏图（需手动处理）: {s['unevaluated']} 张")
        for u in result["unevaluated"]:
            lines.append(f"  - {u['file']} ({u.get('error')})")

    print("\n".join(lines))


def _prevalidate_output_paths(config: Config, logger: logging.Logger) -> None:
    """评分前统一校验全部输出路径的 workspace 包含性（LOW-1）。

    与下游各落盘点的启用条件逐字一致（export 仅在 --export 时、output_path 仅在
    --json 且提供了 --output 时校验），越界即 sys.exit(2)（经 main 的 SystemExit
    映射为 PARAM_ERROR）。下游落盘点保留既有校验作为纵深防御，此处前置只为
    「先拒错、后干活」；两侧判定逻辑同源（_safe_output_path），不会出现一边放行
    一边拒绝的分叉。
    """
    checks: list[tuple[str, str | None]] = []
    if config.export:
        checks.append(("导出目录", config.export_dir))
    if config.output_json and config.output_path:
        checks.append(("JSON 输出路径", config.output_path))
    if config.output_csv:
        checks.append(("CSV 输出路径", config.csv_output_path or DEFAULT_CSV_OUTPUT))
    if config.output_xlsx:
        checks.append(("XLSX 输出路径", config.xlsx_output_path or DEFAULT_XLSX_OUTPUT))
    for label, raw in checks:
        try:
            _safe_output_path(raw, config.directory)
        except UnsafeOutputPathError as e:
            logger.error("拒绝越界%s: %s", label, e)
            sys.exit(2)


def _cleanup_output_tmp(config: Config, logger: logging.Logger) -> None:
    """清理上次异常退出遗留的原子写临时文件。

    只扫本次真正会写入的目录，避免误删无关目录下的隐藏文件。
    清理失败不应阻断评分主流程，故所有异常都在 cleanup_stale_tmp 内吞掉。
    """
    dirs = set()
    # 先经 _safe_output_path 校验，越界则跳过该目录（越界写由下游调用点硬性拒绝），
    # 避免清理逻辑扫描 workspace 之外的目录。
    candidates: list[tuple[str | None, str | Path]] = []
    if config.output_json and config.output_path:
        candidates.append((config.output_path, config.directory))
    if config.output_csv:
        candidates.append((config.csv_output_path or DEFAULT_CSV_OUTPUT, config.directory))
    if config.output_xlsx:
        candidates.append((config.xlsx_output_path or DEFAULT_XLSX_OUTPUT, config.directory))
    for raw, workspace in candidates:
        try:
            safe = _safe_output_path(raw, workspace)
        except UnsafeOutputPathError:
            continue
        if safe is not None:
            dirs.add(safe.parent)
    for d in dirs:
        removed = cleanup_stale_tmp(d)
        if removed:
            logger.info("清理残留临时文件 %d 个于 %s", removed, d)


def _exif_undo_log_path(ws: Path) -> Path:
    """H-2：返回本次运行的差异撤销日志落点 <ws>/.flashgaze_undo/exif_undo_<UTC>_<pid>.jsonl。

    放隐藏目录 .flashgaze_undo/：iter_images 整体跳过以 . 开头的目录，不会污染
    下次扫描/清理；.jsonl 非图片后缀，cleanup 亦不触碰。文件名带 UTC 时间戳与
    pid，同工作空间多次运行互不覆盖，历史记录可留档审计。
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ws / ".flashgaze_undo" / f"exif_undo_{ts}_{os.getpid()}.jsonl"


class UnsafeOutputPathError(Exception):
    """输出路径越出允许根目录（workspace），存在路径穿越/越界覆盖风险。"""


def _safe_output_path(raw: str | None, workspace: str | Path) -> Path | None:
    """规范化输出路径并做 workspace 包含性校验（默认拒绝越界）。

    允许根目录为 workspace（被扫描/清理的目录）：相对路径解析基准为 workspace，
    仅允许写入 workspace 及其子目录；`..` 逃逸或 workspace 之外的绝对路径一律
    拒绝（路径穿越防护）。原先仅 warning 后继续写文件属空操作防护，现已改为硬拒绝。

    返回 None 表示未提供输出路径（仅打印到 stdout）。越界抛 UnsafeOutputPathError，
    由调用方 sys.exit(2) 收敛为 ExitCode.PARAM_ERROR。
    """
    if not raw:
        return None
    base = Path(workspace).resolve()
    # 相对路径以 workspace 为基准解析（默认输出文件名随之落在被操作目录内）；
    # 绝对路径直接规范化。两者最终都须落在 base 之内，否则视为路径穿越。
    p = (base / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        # FIX(#12-4): 原仅 warning 后返回原路径，防护形同空操作；CLI 的
        # --output/--csv/--json/--xlsx 可越出工作区写任意可写路径（尤其路径来自
        # 不可信的配置文件/上游 agent 脚本时）。现改为越界即拒绝，杜绝越界覆盖。
        raise UnsafeOutputPathError(
            f"输出路径 {p} 位于工作目录 {base} 之外（路径穿越风险，已拒绝）"
        )
    return p


def _emit_json(
    exporter: Exporter,
    scored: list[ImageScore],
    elapsed_ms: int,
    config: Config,
    exif_results: list[ExifWriteResult] | None = None,
    export: ExportOutcome | None = None,
    phase1_stats: dict[str, int] | None = None,
    vlm_sampling: dict[str, Any] | None = None,
) -> None:
    """输出 JSON：始终打印到 stdout，若有 output_path 则原子写入文件。stdout 仅含 JSON。

    export：本次导出的结果汇总（H-9）；未启用 --export 时为 None，报告中不出现
    export 小节（与既有报告结构一致）。
    phase1_stats：HybridScorer.phase1_stats；未传入或全零时报告中不出现
    phase1_timeout 小节（与既有报告结构一致）。
    vlm_sampling：VLM 实际生效采样参数（sampling_params_for_config 的返回）；
    VLM 未启用（--no-vlm / 缺 api_key）时为 None，报告中不出现 vlm_sampling 小节。
    """
    data = exporter.build_report(
        scored,
        elapsed_ms,
        exif_results=exif_results,
        export=export,
        phase1_stats=phase1_stats,
        vlm_sampling=vlm_sampling,
    )
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if config.output_path:
        try:
            out_path = _safe_output_path(config.output_path, config.directory)
        except UnsafeOutputPathError as e:
            get_logger().error("拒绝越界 JSON 输出路径: %s", e)
            sys.exit(2)
        if out_path is not None:
            atomic_write_text(out_path, text)
    print(text)


if __name__ == "__main__":  # pragma: no cover — 直跑守卫；正式入口是 flashgaze/__main__.py
    sys.exit(main())

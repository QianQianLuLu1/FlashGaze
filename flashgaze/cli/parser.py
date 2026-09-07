"""CLIParser：命令行参数解析与校验。

支持两种子命令（兼容垫片保证旧用法 `flashgaze <目录>` 等价于 `flashgaze score <目录>`）：
- score   ：目录评分（原默认行为，承载全部既有参数）
- cleanup ：工作空间清理（评分后原地删除低分图，默认 --dry-run）

纯函数式，parse() 返回 Config dataclass（评分/导出域）。配置优先级：CLI > env > file > default。
cleanup 子命令特有的 dry_run/apply 等开关不进入 Config，由 entry 直接从命名空间读取。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import fields as _dc_fields
from dataclasses import replace as _dc_replace
from pathlib import Path

from flashgaze import __version__
from flashgaze.defaults import (
    CLEANUP_GUARD_MIN_SAMPLE,
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_EXPORT_DIR,
    DEFAULT_TOP,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import Config
from flashgaze.utils.config import _parse_weights, build_config, load_config_file
from flashgaze.utils.logging import get_logger

# 每个 argparse dest 都与 ScoringOptions 字段同名，故可泛型收集，
# 新增开关只需写一行 add_argument(dest=<字段名>)。
# weights 例外：CLI 侧是 JSON 字符串，需先解析成 Mapping 再装入。
_OPTION_DESTS = tuple(f.name for f in _dc_fields(ScoringOptions) if f.name != "weights")

# 子命令集合；兼容垫片据此判断 argv[0] 是否已是子命令。
_SUBCOMMANDS = ("score", "cleanup", "restore")


def _read_api_key_file(spec: str, logger: logging.Logger) -> str:
    """从文件（spec 为 "-" 时从 stdin）读取 API Key（M-26）。

    `--api-key KEY` 会把密钥写进进程命令行——`ps`、任务管理器、shell history 与
    进程审计日志均可见。本函数提供等价的文件/管道来源，读取结果 strip 首尾空白
    （密钥文件与管道常带尾部换行）。

    任何失败（文件缺失/不可读/非 UTF-8/内容为空）一律 `logger.error` +
    `sys.exit(2)`：与 `--weights` 非法同风格，拒绝静默失败——空密钥若被静默
    放行，故障会推迟到鉴权阶段才暴露，且表现为难以定位的 401。
    """
    try:
        raw = sys.stdin.read() if spec == "-" else Path(spec).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.error("读取 --api-key-file 失败（%s）: %s", spec, e)
        sys.exit(2)
    key = raw.strip()
    if not key:
        logger.error("--api-key-file 内容为空（%s），请检查密钥文件或管道输入", spec)
        sys.exit(2)
    return key


def _resolve_command(argv: list[str]) -> tuple[list[str], str]:
    """兼容垫片：旧用法 `flashgaze <目录> [flags]` 等价于 `flashgaze score <目录> [flags]`。

    若 argv[0] 已是子命令（score/cleanup）则原样返回；否则在头部插入 "score"。
    首元素为路径或 --flag 时一律按 score 处理，确保既有调用方零改动。
    """
    if argv and argv[0] in _SUBCOMMANDS:
        return argv, argv[0]
    return ["score", *argv], "score"


class CLIParser:
    """命令行参数解析器。"""

    def __init__(self) -> None:
        self.parser = self._build_parser()

    def _build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="flashgaze",
            description="瞬选灵眸 - AI 辅助图片评分 CLI",
        )
        sub = p.add_subparsers(dest="command", required=False)

        score_sp = sub.add_parser("score", help="目录评分（默认模式）")
        self._add_score_args(score_sp)

        cleanup_sp = sub.add_parser("cleanup", help="工作空间清理：评分后原地删除低分图")
        self._add_cleanup_args(cleanup_sp)

        restore_sp = sub.add_parser(
            "restore", help="按删除审计清单把回收站文件恢复到原路径"
        )
        self._add_restore_args(restore_sp)

        return p

    # ── 评分旋钮（score 与 cleanup 共用，新增开关只写一处）──

    def _add_scoring_args(self, p: argparse.ArgumentParser) -> None:
        """写入评分相关开关。dest 与 ScoringOptions/Config 字段逐字对齐。"""
        p.add_argument(
            "--top", type=int, default=None, help=f"选取前 N 张高分图（默认 {DEFAULT_TOP}）"
        )
        p.add_argument("--threshold", type=float, default=None, help="分数阈值（替代 --top）")
        p.add_argument(
            "--no-vlm", dest="no_vlm", action="store_true", default=None, help="禁用 VLM，仅用 CV"
        )
        p.add_argument(
            "--enable-composition",
            dest="enable_composition",
            action="store_true",
            default=None,
            help="启用构图评分（实验性）",
        )
        p.add_argument(
            "--enable-noise",
            dest="enable_noise",
            action="store_true",
            default=None,
            help="启用 BRISQUE 无参考噪点评分（需 opencv-contrib-python + 模型文件）",
        )
        p.add_argument(
            "--enable-color",
            dest="enable_color",
            action="store_true",
            default=None,
            help="启用色彩丰富度评分（HSV 直方图分布）",
        )
        p.add_argument(
            "--enable-portrait",
            dest="enable_portrait",
            action="store_true",
            default=None,
            help="启用人像专项评分（人脸检测 + 区域清晰度，需 face_recognition）",
        )
        p.add_argument(
            # dest 与 Config/ScoringOptions 字段名 dedup 保持一致（选项名 --enable-dedup 不变）
            "--enable-dedup",
            dest="dedup",
            action="store_true",
            default=None,
            help="启用 PHash 图片去重（相似图保留最高分，需 imagededup）",
        )
        p.add_argument(
            "--dedup-threshold",
            dest="dedup_threshold",
            type=int,
            default=None,
            help=f"PHash 汉明距离阈值（默认 {DEFAULT_DEDUP_THRESHOLD}，越小越严格）",
        )
        p.add_argument(
            "--no-downscale",
            dest="no_downscale",
            action="store_true",
            default=None,
            help="禁用大图降采样，使用原始分辨率处理（默认长边超 2048px 时降采样以降低内存占用）",
        )
        p.add_argument("--workers", type=int, default=None, help="并发线程数")
        p.add_argument(
            "--guard-min-sample",
            dest="cleanup_guard_min_sample",
            type=int,
            default=None,
            help=f"删除护栏最小样本量：评分图少于此数量时不启用 95%% 比例护栏"
            f"（默认 {CLEANUP_GUARD_MIN_SAMPLE}，下限 1，护栏不可关闭）",
        )
        p.add_argument(
            "--vlm-provider",
            dest="vlm_provider",
            default=None,
            choices=list(SUPPORTED_VLM_PROVIDERS),
            help="VLM 提供商（默认 qwen，所有 provider 均走内置 pin-IP 直连层，无需 litellm；litellm 仅作可选兜底）",
        )
        p.add_argument(
            "--scene",
            dest="scene",
            default=None,
            choices=list(SUPPORTED_SCENES),
            help="场景化评分模式（默认 auto，由 VLM 自行判断场景）",
        )
        p.add_argument(
            "--weights",
            default=None,
            help='评分权重 JSON（如 \'{"sharpness":0.7,"exposure":0.3}\'）',
        )
        p.add_argument(
            "--config-file", dest="config_file", default=None, help="配置文件路径（JSON）"
        )
        p.add_argument(
            "--api-key",
            dest="api_key",
            default=None,
            help="VLM API Key（会进入进程命令行，建议改用 --api-key-file）",
        )
        # M-26：密钥免进进程命令行（ps / 任务管理器 / shell history 均可见明文）。
        # 与 --api-key 互斥：同时提供即中止，拒绝静默择一。
        p.add_argument(
            "--api-key-file",
            dest="api_key_file",
            default=None,
            help="从文件读取 VLM API Key（'-' 表示从 stdin 读取），避免密钥进入进程命令行",
        )
        p.add_argument("--api-base", dest="api_base", default=None, help="API 端点")
        p.add_argument("--model", default=None, help="模型名称")

    def _add_score_args(self, p: argparse.ArgumentParser) -> None:
        """score 子解析器：目录位置参数 + 评分旋钮 + 全部输出/导出开关（行为 100% 不变）。"""
        p.add_argument("directory", help="待评分图片目录")
        self._add_scoring_args(p)
        p.add_argument(
            "--export",
            action="store_true",
            default=None,
            help=f"复制高分图至导出目录（默认 {DEFAULT_EXPORT_DIR}）",
        )
        p.add_argument(
            "--export-dir",
            dest="export_dir",
            default=None,
            help=f"导出目标目录（默认 {DEFAULT_EXPORT_DIR}；需搭配 --export）",
        )
        p.add_argument(
            "--move", action="store_true", default=None, help="移动而非复制（需搭配 --export）"
        )
        p.add_argument(
            "--json", dest="output_json", action="store_true", default=None, help="输出 JSON 清单"
        )
        p.add_argument(
            "--csv", dest="output_csv", action="store_true", default=None, help="输出 CSV 清单"
        )
        p.add_argument("--output", dest="output_path", default=None, help="JSON 清单输出路径（需搭配 --json）")
        p.add_argument(
            "--csv-output",
            dest="csv_output_path",
            default=None,
            help="CSV 清单输出路径（默认 flashgaze_result.csv；需搭配 --csv）",
        )
        p.add_argument(
            "--exif",
            dest="exif",
            action="store_true",
            default=None,
            help="将评分结果写入图片 EXIF（需安装 piexif，仅 JPEG/WebP）",
        )
        p.add_argument(
            "--no-exif-backup",
            dest="no_exif_backup",
            action="store_true",
            default=None,
            help="写入 EXIF 时不创建 .flashgaze_backup 原文件备份（危险：须配合 --force 确认）",
        )
        # H-2：--no-exif-backup = 无回滚点原地改写原图，属显式危险操作，与 cleanup 的
        # --force（护栏确认开关）同语义复用：不进 Config，只从命名空间透传到 entry。
        p.add_argument(
            "--force",
            dest="force",
            action="store_true",
            default=False,
            help="确认执行 --no-exif-backup 的无回滚点原地改写（仅在已知风险后使用）",
        )
        p.add_argument(
            "--xlsx",
            dest="output_xlsx",
            action="store_true",
            default=None,
            help="输出 .xlsx 评分清单（需安装 openpyxl）",
        )
        p.add_argument(
            "--xlsx-output",
            dest="xlsx_output_path",
            default=None,
            help=".xlsx 清单输出路径（默认 flashgaze_result.xlsx；需搭配 --xlsx）",
        )
        p.add_argument(
            "--enable-plugins",
            dest="enable_plugins",
            action="store_true",
            default=None,
            help="启用插件评分阶段",
        )
        p.add_argument("--plugin-dir", dest="plugin_dir", default=None, help="额外插件目录")
        p.add_argument("--verbose", action="store_true", default=None, help="详细日志（stderr）")
        p.add_argument("--version", action="version", version=f"flashgaze {__version__}")

    def _add_cleanup_args(self, p: argparse.ArgumentParser) -> None:
        """cleanup 子解析器：目录位置参数 + 评分旋钮 + 清理专用开关。"""
        p.add_argument("directory", help="待清理工作空间目录（所有删除严格限制在此目录内）")
        self._add_scoring_args(p)
        # 互斥组：默认 --dry-run（绝不默认删除），显式 --apply 才真正 unlink
        grp = p.add_mutually_exclusive_group()
        grp.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=None,
            help="试运行：只报告将删除的文件，不实际删除（默认）",
        )
        grp.add_argument(
            "--apply",
            dest="apply",
            action="store_true",
            default=False,
            help="实际删除低分图（确认无误后使用）",
        )
        # FIX(#sec-threshold): 95% 删除护栏的显式确认开关。待删比例超过 95% 且
        # 图片数 >= 20 时护栏会整批拦截（一张不删），确认无误后加 --force 才放行。
        p.add_argument(
            "--force",
            dest="force",
            action="store_true",
            default=False,
            help="跳过 95%% 批量删除护栏（须与 --confirm-fingerprint 同行）",
        )
        p.add_argument(
            "--confirm-fingerprint",
            dest="confirm_fingerprint",
            default=None,
            help="dry_run 报告中 summary.fingerprint 的待删清单指纹；"
            "--force 必须同时提供，证明该清单已人工核对过",
        )
        p.add_argument(
            "--no-recycle",
            dest="no_recycle",
            action="store_true",
            default=False,
            help="直接删除而非移入 .flashgaze_deleted/ 回收站（无回滚点，须配合 --force）",
        )
        p.add_argument(
            "--json",
            dest="output_json",
            action="store_true",
            default=None,
            help="结构化输出到 stdout（供 Agent）",
        )
        p.add_argument("--output", dest="output_path", default=None, help="报告写入文件（需搭配 --json）")
        p.add_argument("--verbose", action="store_true", default=None, help="详细日志（stderr）")
        p.add_argument("--version", action="version", version=f"flashgaze {__version__}")

    def _add_restore_args(self, p: argparse.ArgumentParser) -> None:
        """restore 子解析器：审计清单位置参数 + --dry-run。"""
        p.add_argument(
            "manifest",
            help="删除审计清单路径（cleanup --apply 生成的 .flashgaze_deleted_*.jsonl）",
        )
        p.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help="试运行：只报告将恢复哪些文件，不实际移动",
        )
        p.add_argument("--verbose", action="store_true", default=None, help="详细日志（stderr）")
        p.add_argument("--version", action="version", version=f"flashgaze {__version__}")

    def parse_namespace(self, argv: list[str]) -> argparse.Namespace:
        """解析参数（应用兼容垫片），返回原始命名空间，供 entry 按 command 分发。"""
        shimmed, _ = _resolve_command(argv)
        return self.parser.parse_args(shimmed)

    def parse(self, argv: list[str]) -> Config:
        """解析参数并装配 Config。优先级：CLI > env > file > default。

        向后兼容：测试与 WebUI 直接调用，返回 Config。
        """
        return self._config_from_ns(self.parse_namespace(argv))

    def _config_from_ns(self, args: argparse.Namespace) -> Config:
        """从命名空间装配 Config（评分核心 + CLI 输出域 + 导出域）。"""
        # 参数范围校验：与 argparse 错误处理一致，校验失败 sys.exit(2)
        logger = get_logger()
        if args.top is not None and args.top < 1:
            logger.error("--top 必须 >= 1")
            sys.exit(2)
        if args.threshold is not None and (args.threshold < 0 or args.threshold > 100):
            logger.error("--threshold 必须在 0-100 之间")
            sys.exit(2)

        # 配置文件层
        file_cfg = load_config_file(args.config_file) if getattr(args, "config_file", None) else {}

        # 解析 --weights CLI 参数：复用 _parse_weights 统一处理所有可选 key
        weights_override = None
        if getattr(args, "weights", None):
            try:
                raw = json.loads(args.weights)
                weights_override = _parse_weights(raw)
            except (json.JSONDecodeError, ValueError, TypeError):
                # FIX(#12-1): 显式传入 --weights 却非法（JSON 格式/类型错误）时，
                # 原实现仅 warning 后静默回退默认权重并以 exit 0 退出，Agent/CI
                # 无法感知权重未生效。改为参数错误码中止，拒绝静默失败。
                logger.error("--weights 参数非法（JSON 格式错误），已中止")
                sys.exit(2)
            if weights_override is None:
                # JSON 合法但权重语义非法（缺必填维度/负值/NaN 等）：同样拒绝静默回退
                logger.error("--weights 权重非法（缺必填维度或含负值/NaN），已中止")
                sys.exit(2)

        # 评分旋钮统一走 ScoringOptions：dest 与字段同名，故泛型收集即可。
        # hasattr 过滤掉 CLI 未暴露的字段，它们保持 None，由 env/配置文件兜底。
        # store_true 旗默认 default=None：未传时 override 为 None，build_config 跳过，
        # 从而让 env/配置文件里的同名值生效；显式传旗则为 True，正常覆盖。
        # 该约定覆盖全部旗（含 exif / output_xlsx / enable_plugins），无一例外。
        opts = ScoringOptions(
            weights=weights_override,
            **{d: getattr(args, d) for d in _OPTION_DESTS if hasattr(args, d)},
        )

        # M-26：--api-key-file 与 --api-key 互斥，命中后覆盖 opts.api_key
        # （二者都只在显式提供时非 None，故未传时不会覆盖下层 env/配置文件）。
        raw_api_key = getattr(args, "api_key", None)
        api_key_file = getattr(args, "api_key_file", None)
        if api_key_file and raw_api_key:
            logger.error("--api-key 与 --api-key-file 只能二选一（密钥来源不可二义）")
            sys.exit(2)
        if api_key_file:
            opts = _dc_replace(opts, api_key=_read_api_key_file(api_key_file, logger))

        # 统一调用 build_config 装配（CLI args 作为 overrides 覆盖 env/file/default）
        # 仅评分旋钮以外的字段用 getattr 兜底，cleanup 等子命令缺省字段回落默认。
        # exif/output_xlsx/no_exif_backup 的兜底同为 None（未传 = 不覆盖下层配置）。
        return build_config(
            directory=args.directory,
            file_cfg=file_cfg,
            **opts.to_config_kwargs(),
            export=getattr(args, "export", False),
            export_dir=getattr(args, "export_dir", None),
            move=getattr(args, "move", False),
            output_json=getattr(args, "output_json", False),
            output_csv=getattr(args, "output_csv", False),
            output_path=getattr(args, "output_path", None),
            csv_output_path=getattr(args, "csv_output_path", None),
            exif=getattr(args, "exif", None),
            # --no-exif-backup 原样下传，由 build_config 归一化为唯一真源 exif_backup
            # （True → exif_backup=False；None → 跳过，让 env/配置文件/默认值生效），
            # 不另传 exif_backup，也不让 no_exif_backup 进入 Config。
            no_exif_backup=getattr(args, "no_exif_backup", None),
            output_xlsx=getattr(args, "output_xlsx", None),
            xlsx_output_path=getattr(args, "xlsx_output_path", None),
            verbose=getattr(args, "verbose", False),
        )

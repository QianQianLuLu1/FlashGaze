"""CLIParser：命令行参数解析与校验。

纯函数式，parse() 返回 Config dataclass。配置优先级：CLI > env > file > default。
"""

from __future__ import annotations

import argparse
import json
import sys

from flashgaze import __version__
from flashgaze.defaults import (
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_EXPORT_DIR,
    DEFAULT_TOP,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.schemas import Config
from flashgaze.utils.config import _parse_weights, build_config, load_config_file
from flashgaze.utils.logging import get_logger


class CLIParser:
    """命令行参数解析器。"""

    def __init__(self) -> None:
        self.parser = self._build_parser()

    def _build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="flashgaze",
            description="瞬选灵眸 - AI 辅助图片评分 CLI",
        )
        p.add_argument("directory", help="待评分图片目录")
        p.add_argument("--top", type=int, default=None, help=f"选取前 N 张高分图（默认 {DEFAULT_TOP}）")
        p.add_argument("--threshold", type=float, default=None, help="分数阈值（替代 --top）")
        p.add_argument("--export", action="store_true", help=f"复制高分图至导出目录（默认 {DEFAULT_EXPORT_DIR}）")
        p.add_argument("--export-dir", dest="export_dir", default=None, help=f"导出目标目录（默认 {DEFAULT_EXPORT_DIR}）")
        p.add_argument("--move", action="store_true", help="移动而非复制（需配合 --export）")
        p.add_argument("--json", dest="output_json", action="store_true", help="输出 JSON 清单")
        p.add_argument("--csv", dest="output_csv", action="store_true", help="输出 CSV 清单")
        p.add_argument("--output", dest="output_path", default=None, help="JSON 清单输出路径")
        p.add_argument("--csv-output", dest="csv_output_path", default=None, help="CSV 清单输出路径（默认 flashgaze_result.csv）")
        p.add_argument("--no-vlm", dest="no_vlm", action="store_true", help="禁用 VLM，仅用 CV")
        p.add_argument(
            "--enable-composition", dest="enable_composition",
            action="store_true", help="启用构图评分（实验性）",
        )
        p.add_argument(
            "--enable-noise", dest="enable_noise",
            action="store_true", help="启用 BRISQUE 无参考噪点评分（需 opencv-contrib-python + 模型文件）",
        )
        p.add_argument(
            "--enable-color", dest="enable_color",
            action="store_true", help="启用色彩丰富度评分（HSV 直方图分布）",
        )
        p.add_argument(
            "--enable-portrait", dest="enable_portrait",
            action="store_true", help="启用人像专项评分（人脸检测 + 区域清晰度，需 face_recognition）",
        )
        p.add_argument(
            "--enable-dedup", dest="enable_dedup",
            action="store_true", help="启用 PHash 图片去重（相似图保留最高分，需 imagededup）",
        )
        p.add_argument(
            "--dedup-threshold", dest="dedup_threshold", type=int, default=None,
            help=f"PHash 汉明距离阈值（默认 {DEFAULT_DEDUP_THRESHOLD}，越小越严格）",
        )
        p.add_argument(
            "--no-downscale", dest="no_downscale",
            action="store_true",
            help="禁用大图降采样，使用原始分辨率处理（默认长边超 2048px 时降采样以降低内存占用）",
        )
        p.add_argument(
            "--exif", dest="exif", action="store_true",
            help="将评分结果写入图片 EXIF（需安装 piexif: pip install -e \".[exif]\"，仅 JPEG/TIFF）",
        )
        p.add_argument(
            "--no-exif-backup", dest="no_exif_backup", action="store_true",
            help="写入 EXIF 时不创建 .flashgaze_backup 原文件备份",
        )
        p.add_argument(
            "--xlsx", dest="output_xlsx", action="store_true",
            help="输出 .xlsx 评分清单（需安装 openpyxl: pip install -e \".[xlsx]\"）",
        )
        p.add_argument(
            "--xlsx-output", dest="xlsx_output_path", default=None,
            help=".xlsx 清单输出路径（默认 flashgaze_result.xlsx）",
        )
        p.add_argument(
            "--enable-plugins", dest="enable_plugins", action="store_true",
            help="启用插件评分阶段（自动发现 flashgaze/plugins/builtin/ 与 ~/.flashgaze/plugins/）",
        )
        p.add_argument(
            "--plugin-dir", dest="plugin_dir", default=None,
            help="额外插件目录（绝对/相对路径），与内置及用户目录合并发现",
        )
        p.add_argument("--api-key", dest="api_key", default=None, help="VLM API Key")
        p.add_argument("--api-base", dest="api_base", default=None, help="API 端点")
        p.add_argument("--model", default=None, help="模型名称")
        p.add_argument(
            "--vlm-provider", dest="vlm_provider", default=None,
            choices=list(SUPPORTED_VLM_PROVIDERS),
            help="VLM 提供商（默认 qwen，向后兼容；非 qwen 需安装 litellm）",
        )
        p.add_argument(
            "--scene", dest="scene", default=None,
            choices=list(SUPPORTED_SCENES),
            help="场景化评分模式（默认 auto，由 VLM 自行判断场景）",
        )
        p.add_argument("--workers", type=int, default=None, help="并发线程数")
        p.add_argument(
            "--weights", default=None,
            help='评分权重 JSON（如 \'{"sharpness":0.7,"exposure":0.3}\' 或 '
                 '\'{"sharpness":0.5,"exposure":0.3,"composition":0.2}\'），'
                 '可选 key：composition / noise / color，也可用环境变量 FLASHGAZE_WEIGHTS',
        )
        p.add_argument("--config-file", dest="config_file", default=None, help="配置文件路径（JSON）")
        p.add_argument("--verbose", action="store_true", help="详细日志（stderr）")
        p.add_argument("--version", action="version", version=f"flashgaze {__version__}")
        return p

    def parse(self, argv: list[str]) -> Config:
        """解析参数并装配 Config。优先级：CLI > env > file > default。"""
        args = self.parser.parse_args(argv)

        # 参数范围校验：与 argparse 错误处理一致，校验失败 sys.exit(2)
        logger = get_logger()
        if args.top is not None and args.top < 1:
            logger.error("--top 必须 >= 1")
            sys.exit(2)
        if args.threshold is not None and (args.threshold < 0 or args.threshold > 100):
            logger.error("--threshold 必须在 0-100 之间")
            sys.exit(2)

        # 配置文件层
        file_cfg = load_config_file(args.config_file) if args.config_file else {}

        # 解析 --weights CLI 参数：复用 _parse_weights 统一处理所有可选 key
        weights_override = None
        if args.weights:
            try:
                raw = json.loads(args.weights)
                weights_override = _parse_weights(raw)
            except (json.JSONDecodeError, ValueError, TypeError):
                get_logger().warning("--weights 参数解析失败，已忽略并使用默认权重")

        # 统一调用 build_config 装配（CLI args 作为 overrides 覆盖 env/file/default）
        # 注意：args 中未传的可选参数为 None，build_config 会跳过 None 值
        return build_config(
            directory=args.directory,
            file_cfg=file_cfg,
            top=args.top,
            threshold=args.threshold,
            export=args.export,
            export_dir=args.export_dir,
            move=args.move,
            output_json=args.output_json,
            output_csv=args.output_csv,
            output_path=args.output_path,
            csv_output_path=args.csv_output_path,
            no_vlm=args.no_vlm,
            enable_composition=args.enable_composition,
            enable_noise=args.enable_noise,
            enable_color=args.enable_color,
            enable_portrait=args.enable_portrait,
            dedup=args.enable_dedup,
            dedup_threshold=args.dedup_threshold,
            no_downscale=args.no_downscale,
            api_key=args.api_key,
            api_base=args.api_base,
            model=args.model,
            vlm_provider=args.vlm_provider,
            scene=args.scene,
            workers=args.workers,
            weights=weights_override,
            exif=args.exif,
            no_exif_backup=args.no_exif_backup,
            output_xlsx=args.output_xlsx,
            xlsx_output_path=args.xlsx_output_path,
            enable_plugins=args.enable_plugins,
            plugin_dir=args.plugin_dir,
            verbose=args.verbose,
        )

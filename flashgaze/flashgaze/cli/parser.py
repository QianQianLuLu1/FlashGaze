"""CLIParser：命令行参数解析与校验。

纯函数式，parse() 返回 Config dataclass。配置优先级：CLI > env > file > default。
"""

from __future__ import annotations

import argparse
import json

from flashgaze import __version__
from flashgaze.defaults import DEFAULT_EXPORT_DIR, DEFAULT_TOP
from flashgaze.models.schemas import Config
from flashgaze.utils.config import build_config, load_config_file


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
        p.add_argument("--api-key", dest="api_key", default=None, help="VLM API Key")
        p.add_argument("--api-base", dest="api_base", default=None, help="API 端点")
        p.add_argument("--model", default=None, help="模型名称")
        p.add_argument("--workers", type=int, default=None, help="并发线程数")
        p.add_argument(
            "--weights", default=None,
            help='评分权重 JSON（如 \'{"sharpness":0.7,"exposure":0.3}\' 或 \'{"sharpness":0.5,"exposure":0.3,"composition":0.2}\'），'
                 'composition 可选，也可用环境变量 FLASHGAZE_WEIGHTS',
        )
        p.add_argument("--config-file", dest="config_file", default=None, help="配置文件路径（JSON）")
        p.add_argument("--verbose", action="store_true", help="详细日志（stderr）")
        p.add_argument("--version", action="version", version=f"flashgaze {__version__}")
        return p

    def parse(self, argv: list[str]) -> Config:
        """解析参数并装配 Config。优先级：CLI > env > file > default。"""
        args = self.parser.parse_args(argv)

        # 配置文件层
        file_cfg = load_config_file(args.config_file) if args.config_file else {}

        # 解析 --weights CLI 参数
        weights_override = None
        if args.weights:
            try:
                raw = json.loads(args.weights)
                if isinstance(raw, dict) and "sharpness" in raw and "exposure" in raw:
                    s = float(raw["sharpness"])
                    e = float(raw["exposure"])
                    # F-05：composition 为可选 key，存在时一并归一化
                    c = float(raw["composition"]) if "composition" in raw else 0.0
                    total = s + e + c
                    if total > 0:
                        weights_override = {"sharpness": s / total, "exposure": e / total}
                        if "composition" in raw:
                            weights_override["composition"] = c / total
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

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
            api_key=args.api_key,
            api_base=args.api_base,
            model=args.model,
            workers=args.workers,
            weights=weights_override,
            verbose=args.verbose,
        )

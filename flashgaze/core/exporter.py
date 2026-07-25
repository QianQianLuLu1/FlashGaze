"""Exporter：高分图复制/移动 + 评分清单生成。

支持 JSON / CSV 两种清单格式。导出目录默认 ./flashgaze_selected。
同名文件冲突时自动追加序号后缀（如 IMG_001_1.jpg），不覆盖。
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from flashgaze.models.schemas import Config, ImageScore


class Exporter:
    """处理文件复制/移动及清单生成。"""

    def __init__(self, config: Config):
        self.config = config

    def export_images(
        self,
        scored: list[ImageScore],
        dest_dir: str | None = None,
    ) -> int:
        """复制/移动 selected 的图片到 dest_dir。返回处理数量。

        同名文件冲突时自动追加序号后缀（如 IMG_001_1.jpg），不覆盖。
        一次性读取目标目录已有文件名集合，冲突查找 O(1)，避免大量同名时 O(n²) 磁盘 IO。

        dest_dir 为 None 时回落到 self.config.export_dir，使 CLI 不传参时
        与 config.export_dir 保持一致；MCP 调用方显式传参则覆盖之。
        """
        if dest_dir is None:
            dest_dir = self.config.export_dir
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        # 一次性加载目标目录已有文件名（C-14：避免 _resolve_conflict 每次都 stat）
        existing = {p.name for p in dest.iterdir()}
        moved = 0
        for s in scored:
            if not s.selected or s.error:
                continue
            src = Path(s.path)
            if not src.exists():
                continue
            dst_name = self._resolve_conflict_fast(s.file, existing)
            existing.add(dst_name)  # 登记新文件，避免本轮内同名再次冲突
            dst = dest / dst_name
            if self.config.move:
                shutil.move(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            moved += 1
        return moved

    @staticmethod
    def _resolve_conflict_fast(filename: str, existing: set[str]) -> str:
        """如果目标目录已存在同名文件，追加序号后缀。集合查找 O(1)。"""
        if filename not in existing:
            return filename
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = f"{stem}_{counter}{suffix}"
            if candidate not in existing:
                return candidate
            counter += 1

    def write_manifest(self, scored: list[ImageScore], fmt: str, path: str) -> None:
        """生成评分清单。fmt: 'json' 或 'csv'。"""
        if fmt == "json":
            self._write_json(scored, path)
        elif fmt == "csv":
            self._write_csv(scored, path)
        else:
            raise ValueError(f"不支持的清单格式: {fmt}")

    @staticmethod
    def build_report(
        scored: list[ImageScore], elapsed_ms: int | None = None
    ) -> dict:
        """统一构造 JSON 报告 dict。供 _emit_json / _write_json / MCP 共用。

        纯函数式，不依赖 self.config 状态，故设为 staticmethod。
        """
        selected = [s for s in scored if s.selected]
        valid = [s for s in scored if s.error is None]
        avg = sum(s.score for s in valid) / max(len(valid), 1)
        summary: dict = {
            "total": len(scored),
            "selected": len(selected),
            "avg_score": round(avg, 2),
        }
        if elapsed_ms is not None:
            summary["elapsed_ms"] = elapsed_ms
        # CLI 与 MCP 输出格式统一为六字段 Schema（status/code/message/summary/images/details）
        return {
            "status": "success",
            "code": 0,
            "message": None,
            "summary": summary,
            "images": [asdict(s) for s in scored],
            "details": None,
        }

    def _write_json(self, scored: list[ImageScore], path: str) -> None:
        data = self.build_report(scored)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_csv(self, scored: list[ImageScore], path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "file",
                    "path",
                    "sharpness",
                    "exposure",
                    "composition",
                    "vlm_adjustment",
                    "score",
                    "selected",
                    "error",
                ]
            )
            for s in scored:
                writer.writerow(
                    [
                        s.file,
                        s.path,
                        s.sharpness,
                        s.exposure,
                        s.composition if s.composition is not None else "",
                        s.vlm_adjustment,
                        s.score,
                        s.selected,
                        s.error if s.error is not None else "",
                    ]
                )

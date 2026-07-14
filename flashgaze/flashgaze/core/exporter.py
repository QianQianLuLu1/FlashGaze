"""Exporter：高分图复制/移动 + 评分清单生成。

支持 JSON / CSV 两种清单格式。导出目录默认 ./精选。
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from flashgaze.defaults import DEFAULT_EXPORT_DIR
from flashgaze.models.schemas import Config, ImageScore


class Exporter:
    """处理文件复制/移动及清单生成。"""

    def __init__(self, config: Config):
        self.config = config

    def export_images(self, scored: list[ImageScore], dest_dir: str = DEFAULT_EXPORT_DIR) -> int:
        """复制/移动 selected 的图片到 dest_dir。返回处理数量。"""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        moved = 0
        for s in scored:
            if not s.selected or s.error:
                continue
            src = Path(s.path)
            if not src.exists():
                continue
            dst = dest / s.file
            if self.config.move:
                shutil.move(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            moved += 1
        return moved

    def write_manifest(self, scored: list[ImageScore], fmt: str, path: str) -> None:
        """生成评分清单。fmt: 'json' 或 'csv'。"""
        if fmt == "json":
            self._write_json(scored, path)
        elif fmt == "csv":
            self._write_csv(scored, path)
        else:
            raise ValueError(f"不支持的清单格式: {fmt}")

    def build_report(
        self, scored: list[ImageScore], elapsed_ms: int | None = None
    ) -> dict:
        """统一构造 JSON 报告 dict。供 _emit_json / _write_json / MCP 共用。"""
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
        return {
            "status": "success",
            "code": 0,
            "summary": summary,
            "images": [s.__dict__ for s in scored],
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

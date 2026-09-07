"""Exporter：高分图复制/移动 + 评分清单生成。

支持 JSON / CSV 两种清单格式。导出目录默认 ./精选。
同名文件冲突时自动追加序号后缀（如 IMG_001_1.jpg），不覆盖。
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flashgaze.defaults import DEFAULT_EXPORT_DIR
from flashgaze.models.schemas import MANIFEST_COLUMNS, Config, ImageScore
from flashgaze.utils.atomic_write import atomic_write_bytes, atomic_write_text
from flashgaze.utils.logging import get_logger

if TYPE_CHECKING:
    # 仅类型检查期导入：piexif 属可选依赖，exif_writer 运行时须 lazy import
    from flashgaze.core.exif_writer import ExifWriteResult

logger = get_logger()


@dataclass(frozen=True)
class ExportOutcome:
    """一次 export_images 的结果汇总，供 build_report 在 summary 暴露部分失败（H-9）。

    与 exif_writer.ExifWriteResult 同层同风格：frozen 保证结果不可变、可安全跨线程收集。
    expected 与 failures 的差额即「声称入选、实际没导出」的张数。
    """

    expected: int  # 预期入选数（selected 且 error 为空）
    exported: int  # 实际成功导出数
    failures: list[dict[str, str]]  # 逐项 {file, path, error}


class Exporter:
    """处理文件复制/移动及清单生成。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        # 最近一次 export_images 失败的明细（每次调用前重置），供调用方程序化获取失败清单
        self.last_failures: list[dict[str, str]] = []
        # H-9：预期入选数（每次调用前重置）。与 last_failures 合起来才是「导出是否
        # 部分失败」的完整判据——只有失败清单而不知道应选多少张，无法判断失败比例。
        self.last_expected: int = 0

    def export_images(
        self,
        scored: list[ImageScore],
        dest_dir: str = DEFAULT_EXPORT_DIR,
    ) -> int:
        """复制/移动 selected 的图片到 dest_dir。返回处理数量。

        同名文件冲突时自动追加序号后缀（如 IMG_001_1.jpg），不覆盖。
        一次性读取目标目录已有文件名集合，冲突查找 O(1)，避免大量同名时 O(n²) 磁盘 IO。

        调用后可从实例读取本次导出的两个状态：`last_expected`（预期入选数，口径
        与下方跳过条件一致）与 `last_failures`（逐项失败明细）；二者合起来判定
        「部分导出失败」——返回值只给成功数，无法区分「入选 3 张全成」与「入选 30
        张只成 3 张」。
        """
        self.last_failures = []  # 重置本次调用的失败明细
        # H-9：预期入选数，口径与下方跳过条件 `not s.selected or s.error` 逐字一致。
        # 带 error 的图属评分失败而非导出失败，不计入预期（避免退出码被评分错误二次放大）。
        self.last_expected = sum(1 for s in scored if s.selected and s.error is None)
        dest = Path(dest_dir)
        # FIX(#9-1): dest 若已是普通文件（如 --export-dir 误指向某文件），
        # mkdir(exist_ok=True) 会抛 FileExistsError 使整批导出崩溃；先守卫并优雅跳过。
        if dest.exists() and not dest.is_dir():
            logger.warning("导出目标 %s 已存在且不是目录，跳过本次导出", dest)
            # H-9：此前本分支只记 WARNING 后 return 0，是三种失败里唯一零记录的一种
            # ——调用方连「导出根本没发生」都无从得知。有待导出图时记入失败清单；
            # 无待导出图（last_expected == 0）则用户未损失任何产物，保持不记失败。
            if self.last_expected:
                self.last_failures.append(
                    {"file": "", "path": str(dest), "error": "dest_not_directory"}
                )
            return 0
        dest.mkdir(parents=True, exist_ok=True)
        # 一次性加载目标目录已有文件名（C-14：避免 _resolve_conflict 每次都 stat）
        existing = {p.name for p in dest.iterdir()}
        moved = 0
        for s in scored:
            if not s.selected or s.error:
                continue
            src = Path(s.path)
            if not src.exists():
                # LOW-3: 源文件已消失（评分后被外部删除/移动）不再静默跳过——
                # 导出数与入选数的差额需可观测，进入 last_failures 供调用方告警。
                logger.warning("入选图源文件已不存在，跳过导出: %s", src)
                self.last_failures.append(
                    {"file": s.file, "path": str(src), "error": "source_missing"}
                )
                continue
            dst_name = self._resolve_conflict_fast(s.file, existing)
            existing.add(dst_name)  # 登记新文件，避免本轮内同名再次冲突
            dst = dest / dst_name
            try:
                if self.config.move:
                    # N-2: 同卷时 os.rename 是真正的原子移动——一步完成，元数据与
                    # 权限原样保留，且无「整图读入内存 + 重写落盘」的开销与中间态。
                    try:
                        os.rename(src, dst)
                    except OSError:
                        # 跨卷（POSIX EXDEV / Windows WinError 17）或其它 rename
                        # 失败时，回退到 FIX(#9-2) 的「原子写目标后再删源」路径，
                        # 保持不变式：要么源仍在、要么目标完整，杜绝跨卷中断丢源。
                        # FIX(#2-3 补漏): 目标是新文件，preserve_mode 不生效；显式传
                        # 源文件 st_mode，与 copy2 分支（copy2 保留源权限）语义对齐，
                        # 0600 源图 move 后不再放宽成 0644。
                        atomic_write_bytes(dst, src.read_bytes(), mode=src.stat().st_mode)
                        src.unlink()
                else:
                    shutil.copy2(str(src), str(dst))
                moved += 1
            except OSError as e:
                logger.warning("导出失败，跳过 %s: %s", s.file, e)
                # FIX(#9-3): 单张失败原仅 warning 后跳过，调用方无法程序化获取失败清单；
                # 记录到 last_failures 供调用方读取（如导出报告/告警）。
                self.last_failures.append({"file": s.file, "path": str(src), "error": str(e)})
                continue
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
        """生成评分清单。fmt: 'json' / 'csv' / 'xlsx'。"""
        if fmt == "json":
            self._write_json(scored, path)
        elif fmt == "csv":
            self._write_csv(scored, path)
        elif fmt == "xlsx":
            # FIX(#13-2): 复用既有 XlsxExporter 生成 .xlsx 清单，与 CLI --xlsx 对等；
            # 延迟导入避免基础安装缺 openpyxl 时 WebUI 导入即失败（与 entry.py 一致）。
            from flashgaze.core.xlsx_exporter import XlsxExporter

            XlsxExporter().write(scored, path)
        else:
            raise ValueError(f"不支持的清单格式: {fmt}")

    @staticmethod
    def build_report(
        scored: list[ImageScore],
        elapsed_ms: int | None = None,
        exif_results: list[ExifWriteResult] | None = None,
        export: ExportOutcome | None = None,
        phase1_stats: dict[str, int] | None = None,
        vlm_sampling: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """统一构造 JSON 报告 dict。供 _emit_json / _write_json / MCP 共用。

        纯函数式，不依赖 self.config 状态，故设为 staticmethod。
        exif_results：ExifWriter.write_batch 的返回（含 .ok/.path/.error 的鸭子类型
        对象）；仅当调用方传入时才在 summary 写入 exif 小节，错误不静默。
        export：ExportOutcome（Exporter.export_images 后的结果汇总）；仅当调用方
        传入时才在 summary 写入 export 小节。两个参数均为可选——不传时输出与既有
        契约逐字节一致（MCP 评分报告 / WebUI summary / 清单 JSON 零变化）。
        phase1_stats：HybridScorer.phase1_stats（阶段1看门狗统计：timed_out /
        pool_exhausted / rebuilds）；仅当传入且任一计数非零时才在 summary 写入
        phase1_timeout 小节（含被判死数量占总图片数百分比 pool_exhausted_pct），
        零计数或不传时不出现该键（向后兼容，与 exif/export 小节同模式）。
        vlm_sampling：VLM 实际生效的采样参数（core/vlm_client.sampling_params_for_config
        的返回，provider/temperature/seed）；仅当调用方传入时才在 summary 写入
        vlm_sampling 小节（可复现性回显，--no-vlm / 未传时不出现该键，与上方
        各可选小节同模式）。
        """
        selected = [s for s in scored if s.selected]
        valid = [s for s in scored if s.error is None]
        avg = sum(s.score for s in valid) / max(len(valid), 1)
        summary: dict[str, Any] = {
            "total": len(scored),
            "selected": len(selected),
            "avg_score": round(avg, 2),
        }
        if elapsed_ms is not None:
            summary["elapsed_ms"] = elapsed_ms
        if exif_results is not None:
            ok = sum(1 for r in exif_results if r.ok)
            # H-2/M-15：失败数同时挂到 summary 顶层（exif_failed），让 Agent 用
            # 一个键即可判定「是否存在 EXIF 写入失败」，无需下钻 summary.exif 子节。
            # 既有 summary.exif（含 failures 明细）保持不变，向后兼容。
            summary["exif_failed"] = len(exif_results) - ok
            # 失败项单独列出 path + error，确保写入失败在报告中可见、不静默
            failures = [{"path": r.path, "error": r.error} for r in exif_results if not r.ok]
            summary["exif"] = {
                "total": len(exif_results),
                "ok": ok,
                "failed": len(exif_results) - ok,
                "failures": failures,
            }
        if export is not None:
            # H-9：与上方 exif 小节同构——顶层 export_failed 让 Agent 用一个键即可
            # 判定「是否存在导出部分失败」，子节给出预期/成功/失败与逐项明细。
            summary["export_failed"] = len(export.failures)
            summary["export"] = {
                "expected": export.expected,
                "exported": export.exported,
                "failed": len(export.failures),
                "failures": export.failures,
            }
        if phase1_stats is not None and any(
            phase1_stats.get(k, 0) for k in ("timed_out", "pool_exhausted", "rebuilds")
        ):
            pool_exhausted = int(phase1_stats.get("pool_exhausted", 0))
            # 阶段1看门狗统计小节：Agent 用单键判定「本批是否发生过挂起隔离/
            # 池耗尽被判死」，被判死占比用单个键直接可读，无需自行计算。
            summary["phase1_timeout"] = {
                "timed_out": int(phase1_stats.get("timed_out", 0)),
                "pool_exhausted": pool_exhausted,
                "rebuilds": int(phase1_stats.get("rebuilds", 0)),
                "pool_exhausted_pct": round(100.0 * pool_exhausted / max(len(scored), 1), 2),
            }
        if vlm_sampling is not None:
            # 可复现性回显：VLM 实际生效的采样参数（provider/temperature/seed），
            # 使同批图两次运行的得分差异可归因到采样口径
            summary["vlm_sampling"] = dict(vlm_sampling)
        return {
            "status": "success",
            "code": 0,
            "summary": summary,
            "images": [asdict(s) for s in scored],
        }

    def _write_json(self, scored: list[ImageScore], path: str) -> None:
        data = self.build_report(scored)
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

    def _write_csv(self, scored: list[ImageScore], path: str) -> None:
        # 先在内存组装再原子落盘。用 bytes 而非 text：CSV 的 \r\n 行结束符
        # 经文本模式换行转换会变成 \r\r\n，编码为 utf-8-sig 后按字节写可保持原样。
        # 每行取值统一走 ImageScore.to_row()（C-09 单一来源），消除与 XLSX 的重复。
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerow(list(MANIFEST_COLUMNS))
        for s in scored:
            writer.writerow(s.to_row())
        atomic_write_bytes(path, buf.getvalue().encode("utf-8-sig"))

"""EXIF 写入器：将 ImageScore 评分写入图片 EXIF（JPEG / TIFF）。

仅依赖可选库 piexif（pip install -e ".[exif]"）。piexif 未安装时导入本模块会
抛 ImportError，由 cli/entry.py 捕获并提示安装、退出码 CONFIG_ERROR(6)。

字段落位（对齐 EXIF 2.32 标准）：
  - ImageDescription / Software 属于 0th IFD（piexif.ImageIFD）
  - UserComment 属于 Exif IFD（piexif.ExifIFD）
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import piexif  # 可选依赖；缺失时 ImportError 由调用方处理
import piexif.helper  # UserComment 编解码；需显式导入子模块

from flashgaze.models.schemas import ImageScore
from flashgaze.utils.logging import get_logger

logger = get_logger()

# 仅这些后缀支持 EXIF 写入（piexif 底层只支持 JPEG / TIFF）
_SUPPORTED_SUFFIXES = (".jpg", ".jpeg", ".tif", ".tiff")
# vlm_reason 写入 ImageDescription 时的最大长度（ASCII），超出截断
_DESCRIPTION_MAX_CHARS = 200


@dataclass(frozen=True)
class ExifWriteResult:
    """单张图片 EXIF 写入结果。frozen 保证结果不可变、可安全跨线程收集。"""

    path: str
    ok: bool
    error: Optional[str] = None  # 失败原因；成功时为 None


class ExifWriter:
    """将 ImageScore 写入图片 EXIF。失败不中断批处理。

    preserve_original=True 时，写入前先把原文件复制到图片同目录的
    .flashgaze_backup/ 下，便于回滚。no_exif_backup 由调用方传
    preserve_original=False 关闭。
    """

    def __init__(self, preserve_original: bool = True) -> None:
        self.preserve_original = preserve_original

    def write_one(self, scored: ImageScore) -> ExifWriteResult:
        """单张写入。仅支持 JPEG/TIFF，其它格式返回 ok=False。"""
        path = scored.path
        try:
            ext = Path(path).suffix.lower()
            if ext not in _SUPPORTED_SUFFIXES:
                return ExifWriteResult(path, False, "unsupported_format")

            if self.preserve_original:
                # 备份失败只告警，不阻断写入（优雅降级）
                self._backup(path)

            exif_dict = piexif.load(path)
            self._fill(exif_dict, scored)
            piexif.insert(piexif.dump(exif_dict), path)
            return ExifWriteResult(path, True)
        except Exception as e:  # noqa: BLE001 - 单张失败必须被捕获并返回结果
            # 不静默吞掉：把异常转成可读 error 字符串返回
            return ExifWriteResult(path, False, str(e))

    def write_batch(self, scored_list: list[ImageScore]) -> list[ExifWriteResult]:
        """批量写入，仅处理 selected=True 且 error 为 None 的图片。

        逐张调用 write_one，单张失败不影响其它；每个被处理的 scored 产生一个
        ExifWriteResult。未入选或带 error 的图片直接跳过（不产生结果条目）。
        """
        results: list[ExifWriteResult] = []
        for scored in scored_list:
            if not scored.selected or scored.error is not None:
                continue
            results.append(self.write_one(scored))
        return results

    def _backup(self, path: str) -> None:
        """把原文件复制到 <同目录>/.flashgaze_backup/<文件名>。

        备份目录创建或复制失败仅记 warning 到 stderr，不抛异常、不阻断写入。
        """
        src = Path(path)
        backup_dir = src.parent / ".flashgaze_backup"
        try:
            backup_dir.mkdir(exist_ok=True)
            shutil.copy2(src, backup_dir / src.name)
        except OSError as e:
            logger.warning("EXIF 备份失败（不影响写入）%s: %s", src.name, e)

    @staticmethod
    def _fill(exif_dict: dict, scored: ImageScore) -> None:
        """按字段映射把评分写入 exif_dict（就地修改）。"""
        # ── UserComment（ExifIFD）：评分键值对 ──
        parts = [
            f"FlashGazeScore={scored.score:.2f}",
            f"Sharpness={scored.sharpness:.2f}",
            f"Exposure={scored.exposure:.2f}",
        ]
        # 可选子项：存在则追加，保持向后兼容
        if scored.composition is not None:
            parts.append(f"Composition={scored.composition:.2f}")
        if scored.noise is not None:
            parts.append(f"Noise={scored.noise:.2f}")
        if scored.color is not None:
            parts.append(f"Color={scored.color:.2f}")
        comment = ";".join(parts)
        # piexif 的 UserComment 需带 charset 前缀；helper 自动生成 ASCII 前缀，
        # 避免读取时乱码 / 编码报错
        exif_dict.setdefault("Exif", {})[piexif.ExifIFD.UserComment] = (
            piexif.helper.UserComment.dump(comment, encoding="ascii")
        )

        # ── ImageDescription / Software（0th IFD）──
        # 注意：ImageDescription 与 Software 在 EXIF 标准中属于 0th IFD
        # （piexif.ImageIFD），并非 ExifIFD。写入时须放 exif_dict["0th"]，
        # 否则 piexif.dump 会忽略或报错。字段语义与需求一致。
        zeroth = exif_dict.setdefault("0th", {})
        reason = (scored.vlm_reason or "")[:_DESCRIPTION_MAX_CHARS]
        if reason:
            zeroth[piexif.ImageIFD.ImageDescription] = reason.encode("ascii", "ignore")

        provider = scored.vlm_provider or "cv-only"
        zeroth[piexif.ImageIFD.Software] = f"FlashGaze/{provider}".encode("ascii", "ignore")

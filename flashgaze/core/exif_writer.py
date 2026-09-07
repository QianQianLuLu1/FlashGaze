"""EXIF 写入器：将 ImageScore 评分写入图片 EXIF（JPEG / WebP）。

仅依赖可选库 piexif（pip install -e ".[exif]"）。piexif 未安装时导入本模块会
抛 ImportError，由 cli/entry.py 捕获并提示安装、退出码 CONFIG_ERROR(6)。

字段落位（对齐 EXIF 2.32 标准）：
  - ImageDescription / Software 属于 0th IFD（piexif.ImageIFD）
  - UserComment 属于 Exif IFD（piexif.ExifIFD）

段保留契约（M2 修复）：
  - JPEG：EXIF 写回走自写纯 Python 段重组（_insert_exif_jpeg），仅移除旧 Exif
    APP1 并在 SOI 之后插入新 Exif APP1，**原样保留其余全部 APP 段**（XMP APP1、
    IPTC APP13、JFIF APP0 等），彻底规避 piexif.merge_segments 在"XMP 排在 Exif
    之前"时生成重复 Exif 段、或在 JFIF+Exif 顺序下丢弃 JFIF 的脆弱行为。
  - 写入前检测 XMP/IPTC 等 sidecar 段存在即记 WARNING 审计；默认仍保留全部段
    并写入 FlashGaze EXIF（不跳过）。写入前落盘原图到
    `.flashgaze_backup/<文件名>.flashgaze_bak.<pid>.<seq>` 提供进程级可逆回滚：
    写入成功即删除该 .bak（清理失败仅 DEBUG，不影响成功结论），失败则保留并记
    WARNING 含恢复路径（C-01 加固）；序号单调递增，二次备份不覆盖最初回滚点。
  - WebP：现改用与 JPEG 对称的纯 Python 段重组 `_insert_exif_webp`：先提取原图
    XMP/ICCP sidecar 原始 chunk，再借 piexif.insert 写入 EXIF（内部正确处理 VP8X
    提升），最后把 sidecar **幂等重挂**回首个图像 chunk（VP8/VP8L/VP8X）之后——
    重挂前先按 fourcc 集合从 piexif 输出移除同 fourcc chunk，故无论 piexif.insert
    随版本漂移是否保留 XMP/ICCP，**输出中每个 fourcc 恒为恰好一个 chunk**、绝不
    重复（数据损坏），并同步更新 RIFF 容器 size 字段。ALPH/ANIM/ANMF 等全部其它
    chunk 由 piexif 原样保留。
  - WebP 无 EXIF chunk（导出型 WebP 常见）时，piexif.load 会抛 "doesnot have
    exif"；write_one 捕获该特定异常后以空 EXIF 字典起步再 piexif.insert 写入，
    不再被外层兜底静默判失败（功能崩溃类缺陷已修复）。

差异撤销日志（H-2）：
  - 关闭备份（preserve_original=False）时，调用方可传 undo_log 落点，write_one
    在覆盖原图前的最后时点追加一条 JSONL 记录：写入前原文件 SHA256 + 写入前
    UserComment（无则 null）。这是「仅含差异」的最小补偿：SHA256 可与外部副本
    比对证明/定位原始字节，UserComment 支持元数据级回退。
  - **字节级回滚仍只能靠 .flashgaze_backup**——撤销日志不是等价回滚点，这正是
    关闭备份须由调用方要求显式确认（CLI --force）的原因。
  - 撤销日志是 best-effort：落盘/读原图失败只记 WARNING（每进程一次），不阻断
    EXIF 写入、不改变 result.ok。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import tempfile as _tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import piexif  # 可选依赖；缺失时 ImportError 由调用方处理
import piexif.helper  # UserComment 编解码；需显式导入子模块

from flashgaze.defaults import VLM_REASON_MAX_CHARS
from flashgaze.models.schemas import ImageScore
from flashgaze.utils.atomic_write import atomic_write_bytes
from flashgaze.utils.logging import get_logger

logger = get_logger()

# 仅这些后缀支持 EXIF 写入（piexif 底层只支持 JPEG / WebP）
_SUPPORTED_SUFFIXES = (".jpg", ".jpeg", ".webp")


def _split_jpeg_segments(data: bytes) -> list[bytes]:
    """把 JPEG 按 APP/其它段切分为完整段列表（与 piexif.split_into_segments 对齐）。

    段[0] 固定为 SOI（b"\\xff\\xd8"）；SOS（b"\\xff\\xda"）之后的压缩扫描数据
    （含 EOI）整体作为最后一段，避免误切压缩流。返回所有段原样，便于重组时
    100% 保留 XMP/IPTC/JFIF 等 sidecar 段。
    """
    if data[0:2] != b"\xff\xd8":
        raise ValueError("Not a JPEG (missing SOI marker)")
    head = 2
    segments = [b"\xff\xd8"]
    n = len(data)
    while head < n:
        if data[head : head + 2] == b"\xff\xda":  # SOS：剩余全部作为扫描数据段
            segments.append(data[head:])
            break
        if head + 4 > n:
            raise ValueError("Truncated JPEG segment header")
        length = struct.unpack(">H", data[head + 2 : head + 4])[0]
        if length < 2:
            raise ValueError("Invalid JPEG segment length")
        end = head + length + 2
        if end > n:
            raise ValueError("Truncated JPEG segment")
        segments.append(data[head:end])
        head = end
    return segments


def _insert_exif_jpeg(jpeg_bytes: bytes, exif_bytes: bytes) -> bytes:
    """纯 Python 把 exif_bytes 写回 JPEG，保留全部其它 APP 段（M2 修复）。

    仅移除旧的 Exif APP1（marker b"\\xff\\xe1" 且内容以 b"Exif\\x00\\x00" 开头，
    无论其在哪个位置），再于 SOI 之后插入新的 Exif APP1。XMP APP1、IPTC APP13、
    JFIF APP0 等一律原样保留。exif_bytes 须以 b"Exif\\x00\\x00" 开头（即
    piexif.dump 的产物），否则抛 ValueError。
    """
    if exif_bytes[0:6] != b"Exif\x00\x00":
        raise ValueError("Given data is not exif data (missing 'Exif\\x00\\x00' header)")
    segments = _split_jpeg_segments(jpeg_bytes)
    kept = [s for s in segments if not (s[0:2] == b"\xff\xe1" and s[4:10] == b"Exif\x00\x00")]
    exif_app1 = b"\xff\xe1" + struct.pack(">H", len(exif_bytes) + 2) + exif_bytes
    kept.insert(1, exif_app1)  # 紧跟 SOI 之后
    return b"".join(kept)


def _extract_sidecar_chunks(webp_bytes: bytes, fourccs: tuple[bytes, ...]) -> list[bytes]:
    """提取指定 fourcc 的完整 chunk（含可能的 1 字节 padding），保持原顺序。

    用于 WebP 写回前把 XMP/ICCP sidecar 暂存，待 piexif 完成 EXIF 写入与 VP8X
    提升后重新挂回。重挂前 _insert_exif_webp 会按 fourcc 集合幂等去重，故本函数
    仅负责"提取权威副本"，无需关心 piexif.insert 是否保留 sidecar（版本漂移安全）。
    """
    chunks: list[bytes] = []
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        return chunks
    body = webp_bytes[12:]
    n = len(body)
    i = 0
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        chunk = body[i : i + 8 + size]
        if size & 1:
            chunk += body[i + 8 + size : i + 8 + size + 1]  # 含 padding
        if fourcc in fourccs:
            chunks.append(chunk)
        i += 8 + size + (size & 1)
    return chunks


def _insert_chunks_after_first(webp_bytes: bytes, chunks: list[bytes]) -> bytes:
    """在首个 chunk 之后插入给定 chunk 列表（满足 WebP '首个 chunk 须为 VP8X' 约束），

    并重写 RIFF 容器 4 字节 size 字段。chunks 已是完整 chunk 字节（含 padding）。
    无 chunk 时原样返回（仅重写 RIFF size，等价）。
    """
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        raise ValueError("Not a WebP (missing RIFF/WEBP marker)")
    if not chunks:
        return webp_bytes
    body = webp_bytes[12:]
    n = len(body)
    i = 0
    out = bytearray()
    inserted = False
    while i + 8 <= n:
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        end = i + 8 + size + (size & 1)
        out += body[i:end]
        if not inserted:
            for c in chunks:
                out += c
            inserted = True
        i = end
    new_body = bytes(out)
    return b"RIFF" + struct.pack("<I", len(new_body)) + b"WEBP" + new_body


def _remove_chunks_by_fourcc(webp_bytes: bytes, fourccs: tuple[bytes, ...]) -> bytes:
    """从 WebP body 移除指定 fourcc 的全部 chunk（含可能的 1 字节 padding），重写 RIFF size。

    用于 _insert_exif_webp 重挂 sidecar 前的幂等去重：无论 piexif.insert 是否保留
    XMP/ICCP，先按 sidecar 的 fourcc 集合从 piexif 输出中移除对应 chunk，再挂回从
    原图提取的权威副本，保证输出中每个 fourcc 至多一个 chunk，杜绝重复（数据损坏）。
    EXIF fourcc 不在此列，故不会被误删。
    """
    if not fourccs:
        return webp_bytes
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        return webp_bytes
    body = webp_bytes[12:]
    n = len(body)
    i = 0
    out = bytearray()
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        end = i + 8 + size + (size & 1)
        if fourcc not in fourccs:
            out += body[i:end]
        i = end
    new_body = bytes(out)
    return b"RIFF" + struct.pack("<I", len(new_body)) + b"WEBP" + new_body


def _insert_exif_webp(webp_bytes: bytes, exif_bytes: bytes) -> bytes:
    """把 EXIF 写回 WebP，同时保证 XMP/ICCP sidecar 不丢失且不重复（幂等修正）。

    简单 WebP（VP8/VP8L）须提升为 VP8X 扩展格式才能合法承载 EXIF（piexif.load
    仅支持 VP8X 容器读回）。piexif.insert 对 WebP sidecar 的处理随版本漂移（旧版
    丢弃 XMP/ICCP、新版保留），故本函数分三步、且重挂前幂等去重：
      1. 先从原图提取 XMP/ICCP sidecar 原始 chunk（_extract_sidecar_chunks）；
      2. 交给 piexif.insert 写入 EXIF（内部正确处理 VP8X 提升，产出合法容器）；
      3. 先按 sidecar 的 fourcc 集合从 piexif 输出移除同 fourcc chunk
         （_remove_chunks_by_fourcc），再把提取的 sidecar 重新挂回（插入到首个
         chunk 之后）。无论 post 是否已含 sidecar，输出恒为恰好一个 XMP/ICCP chunk，
         且保留全部其它 chunk，重写 RIFF size。
    exif_bytes 须以 b"Exif\\x00\\x00" 开头。
    """
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        raise ValueError("Not a WebP (missing RIFF/WEBP marker)")
    if exif_bytes[0:6] != b"Exif\x00\x00":
        raise ValueError("Given data is not exif data (missing 'Exif\\x00\\x00' header)")

    sidecars = _extract_sidecar_chunks(webp_bytes, (b"XMP ", b"ICCP"))

    # 借助 piexif 完成 EXIF 写入与 VP8X 提升（写入临时文件再读回）。
    fd, tmpp = _tempfile.mkstemp(suffix=".webp")
    os.close(fd)
    try:
        Path(tmpp).write_bytes(webp_bytes)
        piexif.insert(exif_bytes, tmpp)
        post = Path(tmpp).read_bytes()
    finally:
        try:
            os.unlink(tmpp)
        except OSError:
            pass

    # piexif.insert 对 WebP sidecar 的处理随版本漂移（旧版丢弃 XMP/ICCP、新版保留）。
    # 重挂前先按 sidecar 的 fourcc 集合从 post 幂等移除同 fourcc chunk，再挂回从
    # 原图提取的权威副本：无论 post 是否已含 XMP/ICCP，输出恒为恰好一个 chunk，
    # 杜绝重复（数据损坏）。sidecars 为空时跳过去重，等价原行为。
    if sidecars:
        drop_fourccs = tuple(c[0:4] for c in sidecars)
        post = _remove_chunks_by_fourcc(post, drop_fourccs)
    return _insert_chunks_after_first(post, sidecars)


def _detect_webp_sidecar_segments(webp_bytes: bytes) -> set[str]:
    """扫描 WebP chunk，识别 sidecar 元数据段类型（审计用，默认仍保留并写入）。

    返回子集 {"xmp"} / {"iccp"} / {"xmp", "iccp"} / set()。
      - xmp：fourcc 为 b"XMP " 且含 XMP 命名空间 b"http://ns.adobe.com/xap/1.0/"
      - iccp：fourcc 为 b"ICCP"
    解析异常时不抛错，返回空集（不阻断写入）。
    """
    found: set[str] = set()
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        return found
    body = webp_bytes[12:]
    n = len(body)
    i = 0
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        if fourcc == b"XMP " and b"http://ns.adobe.com/xap/1.0/" in body[i + 8 : i + 8 + size]:
            found.add("xmp")
        elif fourcc == b"ICCP":
            found.add("iccp")
        i += 8 + size + (size & 1)
    return found


def _detect_sidecar_segments(jpeg_bytes: bytes) -> set[str]:
    """扫描 JPEG 段，识别 sidecar 元数据段类型（审计用，默认仍保留并写入）。

    返回子集 {"xmp"} / {"iptc"} / {"xmp", "iptc"} / set()。
      - xmp：APP1 含 XMP 命名空间 b"http://ns.adobe.com/xap/1.0/"
      - iptc：APP13 含 Adobe Photoshop 标记 b"Photoshop 3.0"
    解析异常时不抛错，返回空集（不阻断写入）。
    """
    found: set[str] = set()
    try:
        segments = _split_jpeg_segments(jpeg_bytes)
    except (ValueError, struct.error, IndexError):
        return found
    for s in segments:
        if s[0:2] == b"\xff\xe1" and b"http://ns.adobe.com/xap/1.0/" in s:
            found.add("xmp")
        elif s[0:2] == b"\xff\xed" and s[4 : 4 + 13] == b"Photoshop 3.0":
            found.add("iptc")
    return found


@dataclass(frozen=True)
class ExifWriteResult:
    """单张图片 EXIF 写入结果。frozen 保证结果不可变、可安全跨线程收集。"""

    path: str
    ok: bool
    error: str | None = None  # 失败原因；成功时为 None


class BackupFailed(Exception):
    """EXIF 写入前备份原图失败（preserve_original=True 时）。

    备份失败意味着原图没有任何回滚点，必须中止写入而非覆盖原图，
    否则可能造成不可逆的原图损坏（C-02）。
    """


class ExifWriter:
    """将 ImageScore 写入图片 EXIF。失败不中断批处理。

    preserve_original=True 时，写入前先把原文件原子落盘到图片同目录的
    .flashgaze_backup/<文件名>.flashgaze_bak.<pid>.<seq> 下，便于回滚。写入成功即
    删除该 .bak；写入失败则保留并记 WARNING 含恢复路径。exif_backup=False
    （调用方经 parser 反向映射 --no-exif-backup 得到）由调用方传
    preserve_original=False 关闭。

    undo_log：关闭备份时由调用方传入的差异撤销日志落点（JSONL）。None（默认）
    表示不记录。见模块 docstring「差异撤销日志（H-2）」的语义与局限。
    """

    def __init__(self, preserve_original: bool = True, undo_log: Path | None = None) -> None:
        self.preserve_original = preserve_original
        self.undo_log = undo_log
        # 撤销日志的提示/告警各只发一次，避免逐图刷屏
        self._undo_log_announced = False
        self._undo_log_warned = False

    def write_one(self, scored: ImageScore) -> ExifWriteResult:
        """单张写入。仅支持 JPEG/WebP，其它格式返回 ok=False。

        安全不变式（C-02）：preserve_original=True 时，备份原图是写入的前置条件——
        备份失败意味着原图没有任何回滚点，此时必须中止写入（不覆盖原图），
        返回 ok=False, error="backup_failed"；绝不允许"以为有备份、实则原图被覆盖"。
        """
        path = scored.path
        bak: Path | None = None
        try:
            ext = Path(path).suffix.lower()
            if ext not in _SUPPORTED_SUFFIXES:
                return ExifWriteResult(path, False, "unsupported_format")

            if self.preserve_original:
                # 备份失败 = 无回滚点：中止该张写入，绝不覆盖原图（C-02）
                try:
                    bak = self._backup(path)
                except BackupFailed:
                    return ExifWriteResult(path, False, "backup_failed")

            if ext == ".webp":
                try:
                    exif_dict = piexif.load(path)
                except Exception as e:
                    if "doesnot have exif" in str(e):
                        # 导出型 WebP 常无 EXIF chunk：piexif.load 会抛 "doesnot have exif"。
                        # 以空字典起步，_fill 后 piexif.insert 写入新 EXIF，避免被外层
                        # except 静默判失败（功能崩溃类缺陷）。
                        exif_dict = {}
                        logger.debug(
                            "WebP 无 EXIF chunk，将以空 EXIF 起步写入 FlashGaze 评分: %s",
                            path,
                        )
                    else:
                        raise
            else:
                exif_dict = piexif.load(path)
            if self.undo_log is not None:
                # H-2：覆盖原图前的最后时点记录前态（SHA256 + 原 UserComment）。
                # 必须在 _fill 之前——_fill 会就地修改 exif_dict。
                self._record_undo(path, exif_dict)
            self._fill(exif_dict, scored)
            exif_bytes = piexif.dump(exif_dict)
            # 先在临时副本上插入 EXIF，校验成功后再原子替换原图，避免原地覆盖
            # 中途异常留下半截损坏原图且无回滚（C-02）。
            src = Path(path)
            tmp = src.parent / f".{src.name}.exif.tmp.{os.getpid()}"
            try:
                shutil.copy2(src, tmp)
                tmp_bytes = tmp.read_bytes()
                if ext == ".webp":
                    # WebP：自写段重组，仅替换 EXIF chunk，保留全部其它 chunk
                    # （XMP/ICCP/ALPH/ANIM/ANMF 等）。重挂前按 fourcc 幂等去重，
                    # 无论 piexif.insert 是否保留 sidecar，输出恒为恰好一个、
                    # 绝不重复（数据损坏）。
                    # 审计：检测到 sidecar 段时记 WARNING，但默认仍保留并写入。
                    sidecars = _detect_webp_sidecar_segments(tmp_bytes)
                    if sidecars:
                        logger.warning(
                            "图片含 sidecar 元数据(%s)，已保留全部 chunk 写入 FlashGaze EXIF: %s",
                            ",".join(sorted(sidecars)),
                            path,
                        )
                    tmp.write_bytes(_insert_exif_webp(tmp_bytes, exif_bytes))
                else:
                    # JPEG：自写段重组，保留全部 APP 段（XMP/IPTC/JFIF 等）。
                    # 审计：检测到 sidecar 段时记 WARNING，但默认仍保留并写入。
                    sidecars = _detect_sidecar_segments(tmp_bytes)
                    if sidecars:
                        logger.warning(
                            "图片含 sidecar 元数据(%s)，已保留全部 APP 段写入 FlashGaze EXIF: %s",
                            ",".join(sorted(sidecars)),
                            path,
                        )
                    tmp.write_bytes(_insert_exif_jpeg(tmp_bytes, exif_bytes))
                atomic_write_bytes(src, tmp.read_bytes())
            finally:
                tmp.unlink(missing_ok=True)
            # 写入成功：原图已被原子替换，本次精确回滚点 .bak 不再需要，删除之。
            # M-12: 清理失败（文件被占用/权限等）不得经外层 except 把「写入成功」
            # 误判为失败——原图已安全落盘，仅 DEBUG 记录供排查；残留的 bak 带
            # 单调序号，不会被下一次备份覆盖（见 _bak_path），回滚点不受影响。
            if bak is not None:
                try:
                    bak.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug("EXIF 备份清理失败（不影响写入结果）: %s: %s", bak, e)
            return ExifWriteResult(path, True)
        except Exception as e:  # noqa: BLE001 - 单张失败必须被捕获并返回结果
            # 不静默吞掉：把异常转成可读 error 字符串返回
            # C-01 加固：写入失败则保留 .bak 原图备份供回滚，并记 WARNING 含恢复路径
            if bak is not None and bak.exists():
                logger.warning(
                    "EXIF 写入失败，原图备份已保留可回滚（覆盖原图前）: %s -> %s",
                    path,
                    bak,
                )
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

    def _record_undo(self, path: str, exif_dict: dict[str, Any]) -> None:
        """记录本次覆盖的前态差异（仅撤销日志启用时调用，见模块 docstring）。

        内容是「只含差异」的最小可回退信息：原文件 SHA256（可与外部副本比对证明
        或定位原始字节）+ 写入前 UserComment（支持元数据级回退）。

        任何失败都只告警不阻断：用户已显式接受无回滚点（CLI --force），撤销日志
        是 best-effort 补偿，不是写入的前置条件——否则只读目录/磁盘满会让原本
        可成功的写入全部失败，把安全增强变成可用性回退。
        """
        src = Path(path)
        try:
            digest = hashlib.sha256()
            with src.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError as e:
            self._undo_warning("撤销日志：读取原图计算 SHA256 失败，跳过该条记录: %s: %s", path, e)
            return
        try:
            resolved = str(src.resolve())
        except OSError:
            resolved = str(src)
        self._append_undo_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pid": os.getpid(),
                "path": resolved,
                "sha256_before": digest.hexdigest(),
                "user_comment_before": self._user_comment_before(exif_dict),
            }
        )

    @staticmethod
    def _user_comment_before(exif_dict: dict[str, Any]) -> str | None:
        """取出写入前的 UserComment 明文；不存在或解码失败返回 None。

        第三方工具写入的 UserComment 可能是任意字节，解码失败（非致命）时以
        null 落盘，其余字段照记——撤销日志不得因单个字段畸形而整体丢失。
        """
        raw = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment)
        if raw is None:
            return None
        try:
            return str(piexif.helper.UserComment.load(bytes(raw)))
        except Exception as e:  # noqa: BLE001 - 畸形 UserComment 不得阻断撤销日志
            logger.debug("撤销日志：原 UserComment 解码失败，记为 null: %s", e)
            return None

    def _append_undo_log(self, record: dict[str, Any]) -> None:
        """把一条前态记录追加到撤销日志（JSONL，追加写非原子但单条极小）。

        首次成功落盘时 INFO 打印路径供用户查找；落盘失败走 _undo_warning（只告警
        一次）并继续，不影响本次 EXIF 写入结论。
        """
        if self.undo_log is None:
            return
        try:
            self.undo_log.parent.mkdir(parents=True, exist_ok=True)
            with self.undo_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            self._undo_warning(
                "撤销日志写入失败（继续写入 EXIF，本次无回滚点补偿）: %s: %s", self.undo_log, e
            )
            return
        if not self._undo_log_announced:
            self._undo_log_announced = True
            logger.info("EXIF 差异撤销日志（含写入前 SHA256 与原 UserComment）: %s", self.undo_log)

    def _undo_warning(self, msg: str, *args: object) -> None:
        """撤销日志告警：每进程仅一次，避免逐图刷屏淹没真正的失败原因。"""
        if self._undo_log_warned:
            return
        self._undo_log_warned = True
        logger.warning(msg, *args)

    def _bak_path(self, path: str) -> Path:
        """返回进程级精确回滚点路径：
        <同目录>/.flashgaze_backup/<文件名>.flashgaze_bak.<pid>.<seq>。

        落点复用 .flashgaze_backup/ 隐藏目录，天然被 cleanup.exclusion_dirs 与
        iter_images 隐藏目录跳过排除，不会污染下次 score；.<pid>.<seq> 后缀为纯
        数字，即便被递归遍历也不匹配图片扩展名，且同图并发（不同 pid）互不覆盖。
        M-12: <seq> 单调递增（从 1 起取首个空闲名）——同进程对同图二次写入、或
        上次异常退出残留了同 pid 备份时，新备份让位为更高序号，绝不覆盖最初
        回滚点（最初那份 .bak 保存的才是未改动的原图）。
        """
        src = Path(path)
        backup_dir = src.parent / ".flashgaze_backup"
        stem = f"{src.name}.flashgaze_bak.{os.getpid()}"
        seq = 1
        while (bak := backup_dir / f"{stem}.{seq}").exists():
            seq += 1
        return bak

    def _backup(self, path: str) -> Path:
        """把原文件原子落盘到 .flashgaze_backup/<文件名>.flashgaze_bak.<pid>.<seq>。

        备份是写入的前置安全条件：OSError（目录不可建/复制失败）一律上抛
        BackupFailed，由 write_one 中止写入，避免无回滚点覆盖原图（C-02）。
        用 atomic_write_bytes 落盘，复制中途失败不会残留不完整 .bak（C-01）。
        权限与原图一致（FIX #2-3 补漏）：.bak 是新建文件，atomic_write 的
        preserve_mode「已存在目标继承」分支不生效，须显式传源文件 st_mode，
        否则 0600 原图会按默认 umask 备份成 0644——写入失败路径特意保留的
        回滚点恰以放宽权限留存原图内容。
        返回 .bak 绝对路径；write_one 视成败决定删除（成功）或保留（失败）。
        """
        src = Path(path)
        bak = self._bak_path(path)
        try:
            st = src.stat()
            bak.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(bak, src.read_bytes(), mode=st.st_mode)
        except OSError as e:
            raise BackupFailed(path) from e
        return bak

    @staticmethod
    def _fill(exif_dict: dict[str, Any], scored: ImageScore) -> None:
        """按字段映射把评分写入 exif_dict（就地修改）。

        中文等 UTF-8 文本落位策略：
        - UserComment（ExifIFD）：承载完整 vlm_reason（含中文），是非 ASCII 文本
          唯一可靠的落点——主流看图软件按 EXIF 规范解析，绝不丢数据。
        - ImageDescription（0th IFD）：仅放 ASCII 安全摘要；纯中文理由无 ASCII
          字符时此处留空，完整中文已在 UserComment，不再因非 ASCII 而丢数据。
        """
        # ── UserComment（ExifIFD）：评分键值对 + 完整 vlm_reason ──
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

        # 完整 vlm_reason 一并写入（长度受控），保留中文等非 ASCII 文本。
        # 早期截断已在 VLMResult 构造处完成（≤20 字），此处复用同一上限作兜底，
        # 避免撑爆 EXIF UserComment，与 JSON/CSV 输出长度一致。
        reason = (scored.vlm_reason or "")[:VLM_REASON_MAX_CHARS]
        if reason:
            # 转义 reason 内的 ; 与 \，避免与字段分隔符冲突、破坏回读解析
            parts.append(f"Reason={_escape_value(reason)}")

        comment = ";".join(parts)
        # 注意：piexif.helper.UserComment.dump 仅支持 ascii/jis/unicode，并不支持
        # 字面的 "utf-8"（传 "utf-8" 会直接 ValueError）。EXIF 2.32 的 UserComment
        # "UNICODE" CharacterCode 即 UTF-16BE，可无损存放中文，且经
        # piexif.helper.UserComment.load 能原样读回——这就是“用 UTF-8 承载中文”
        # 在 piexif 下的标准等价实现：完整中文不会丢，也能被主流看图软件读取。
        exif_dict.setdefault("Exif", {})[piexif.ExifIFD.UserComment] = (
            piexif.helper.UserComment.dump(comment, encoding="unicode")
        )

        # ── ImageDescription / Software（0th IFD）──
        # ImageDescription 与 Software 在 EXIF 标准中属于 0th IFD（piexif.ImageIFD），
        # 写入时须放 exif_dict["0th"]，否则 piexif.dump 会忽略或报错。
        # ImageDescription 只放 ASCII 安全摘要：过滤非 ASCII 并截断，保证写入不失败；
        # 完整（含中文）理由已进 UserComment，此处不再因非 ASCII 丢数据。
        zeroth = exif_dict.setdefault("0th", {})
        ascii_reason = "".join(ch for ch in (scored.vlm_reason or "") if ord(ch) < 128)
        ascii_reason = ascii_reason[:VLM_REASON_MAX_CHARS]
        if ascii_reason:
            zeroth[piexif.ImageIFD.ImageDescription] = ascii_reason.encode("ascii")

        provider = scored.vlm_provider or "cv-only"
        zeroth[piexif.ImageIFD.Software] = f"FlashGaze/{provider}".encode("ascii", "ignore")


def _escape_value(s: str) -> str:
    """转义值内的 \\ 与 ;：\\ → \\\\，; → \\;。

    与 _split_escaped / parse_user_comment 构成对称契约：写入侧转义，
    回读侧按“未转义分号”切分即可无损还原，消除 UserComment 以 ; 连接
    多字段时 reason 内含 ; 造成的解析歧义。
    """
    return s.replace("\\", "\\\\").replace(";", "\\;")


def _split_escaped(text: str, sep: str = ";") -> list[str]:
    """按未转义的分隔符切分。

    单遍扫描：遇到 \\ 时跳过转义符并把下一字符原样并入当前段（无论其是否
    为分隔符），从而正确处理转义后的 ; 与 \\。sep 必须为单字符。
    """
    parts: list[str] = []
    cur = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            cur += text[i + 1]
            i += 2
            continue
        if ch == sep:
            parts.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return parts


def parse_user_comment(comment: str) -> dict[str, str]:
    """将 ; 连接的 key=value 解析为字典，供 EXIF 回读使用。

    按未转义分号切分（_split_escaped），每段按首个 '=' 拆出 key/value。
    反转义由 _split_escaped 在单遍扫描中完成（遇到转义符 \\ 时跳过并原样
    并入下一字符，故 \\;→;、 \\\\→\\），因此此处拿到的 val 已是原始未转义值，
    可直接无损重建，无需（也严禁）再做一次反转义，否则会双重解码损坏数据。
    空段与不含 '=' 的段跳过。
    """
    result: dict[str, str] = {}
    for part in _split_escaped(comment, ";"):
        if not part or "=" not in part:
            continue
        key, _, val = part.partition("=")
        result[key] = val
    return result

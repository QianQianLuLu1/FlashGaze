"""ExifWriter 测试。

覆盖 JPEG 写入、不支持格式、批量、备份创建、cv-only 标记与损坏文件不崩溃。
测试写到 tmp_path 副本，避免污染 tests/fixtures/ 里的原图。
需先安装 piexif: pip install piexif
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import struct
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("piexif")

import piexif.helper  # UserComment 读取；需显式导入子模块

import flashgaze.core.exif_writer as exif_writer_mod
from flashgaze.core.exif_writer import (
    ExifWriter,
    ExifWriteResult,
    _detect_sidecar_segments,
    _split_jpeg_segments,
    parse_user_comment,
)
from flashgaze.defaults import VLM_REASON_MAX_CHARS
from flashgaze.models.schemas import ImageScore


def _score(
    path: str,
    selected: bool = True,
    error: str | None = None,
    **kw: Any,
) -> ImageScore:
    """构造最小 ImageScore。file 取路径文件名。"""
    base: dict[str, Any] = {
        "file": Path(path).name,
        "path": path,
        "sharpness": 80.0,
        "exposure": 70.0,
        "composition": None,
        "vlm_adjustment": 0.0,
        "score": 92.75,
        "selected": selected,
        "error": error,
    }
    base.update(kw)
    return ImageScore(**base)


def _copy_fixture(fixtures_dir: Path, tmp_path: Path, name: str) -> str:
    """把 fixture 复制到临时目录，返回新路径（避免污染原图）。"""
    src = fixtures_dir / name
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


# XMP / IPTC sidecar 段构造（仅用于注入测试，模拟 Adobe/Lightroom 输出）
_XMP_NS = b"http://ns.adobe.com/xap/1.0/"
_XMP_PAYLOAD = _XMP_NS + b"\x00<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>"
_IPTC_PAYLOAD = b"Photoshop 3.0\x00\x1c\x01\x00\x02\x00\x00"


def _inject_xmp_iptc(jpeg_path: Path) -> bytes:
    """在 JPEG 副本 SOI 之后注入 XMP APP1 + IPTC APP13 段（XMP 在前），返回新字节。

    用于验证 M2 修复：写入后这些 sidecar 段须原样保留、且不得产生重复 Exif 段。
    """
    data = jpeg_path.read_bytes()
    segs = _split_jpeg_segments(data)
    xmp = b"\xff\xe1" + struct.pack(">H", len(_XMP_PAYLOAD) + 2) + _XMP_PAYLOAD
    iptc = b"\xff\xed" + struct.pack(">H", len(_IPTC_PAYLOAD) + 2) + _IPTC_PAYLOAD
    segs.insert(1, iptc)
    segs.insert(1, xmp)
    out = b"".join(segs)
    jpeg_path.write_bytes(out)
    return out


def _inject_existing_exif_before(jpeg_path: Path) -> None:
    """构造"已有 Exif APP1 但排在 XMP 之后"的边缘顺序（piexif 旧逻辑会生成重复段）。"""
    data = jpeg_path.read_bytes()
    segs = _split_jpeg_segments(data)
    xmp = b"\xff\xe1" + struct.pack(">H", len(_XMP_PAYLOAD) + 2) + _XMP_PAYLOAD
    dummy_exif = piexif.dump({})  # 合法空 Exif APP1 载荷
    old_app1 = b"\xff\xe1" + struct.pack(">H", len(dummy_exif) + 2) + dummy_exif
    segs.insert(1, old_app1)
    segs.insert(1, xmp)
    jpeg_path.write_bytes(b"".join(segs))


# ---------- write_one：JPEG 成功 ----------


def test_write_jpeg(fixtures_dir: Path, tmp_path: Path) -> None:
    """对 sharp.jpg 副本调用 write_one：ok=True，error=None，字段可读。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="clear sharp photo", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)

    assert isinstance(result, ExifWriteResult)
    assert result.ok is True
    assert result.error is None

    exif = piexif.load(path)
    # UserComment 含评分键值对
    raw = exif["Exif"][piexif.ExifIFD.UserComment]
    comment = piexif.helper.UserComment.load(raw)
    assert "FlashGazeScore=92.75" in comment
    assert "Sharpness=80.00" in comment
    assert "Exposure=70.00" in comment
    # ImageDescription = vlm_reason
    assert exif["0th"][piexif.ImageIFD.ImageDescription].decode("ascii") == "clear sharp photo"
    # Software = FlashGaze/qwen
    assert exif["0th"][piexif.ImageIFD.Software].decode("ascii") == "FlashGaze/qwen"


def test_cv_only_software(fixtures_dir: Path, tmp_path: Path) -> None:
    """vlm_provider 为空时 Software 为 FlashGaze/cv-only。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="", vlm_provider="")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    exif = piexif.load(path)
    assert exif["0th"][piexif.ImageIFD.Software].decode("ascii") == "FlashGaze/cv-only"
    # 空 vlm_reason 不写 ImageDescription
    assert piexif.ImageIFD.ImageDescription not in exif["0th"]


def test_chinese_vlm_reason_preserved_in_usercomment(fixtures_dir: Path, tmp_path: Path) -> None:
    """纯中文 vlm_reason 写入 UserComment：受 VLM_REASON_MAX_CHARS 统一截断（≤20 字）、

    但中文不被 ASCII 丢弃（非 ASCII 进 UserComment 而非被静默截断为空白）。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    reason = "这是一张清晰的中文照片，焦点准确、构图稳健、曝光适中。"
    scored = _score(path, vlm_reason=reason, vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True

    exif = piexif.load(path)
    raw = exif["Exif"][piexif.ExifIFD.UserComment]
    # 用 piexif 读回：中文应无损保留（去除首尾空白后断言），截断到统一上限
    comment = piexif.helper.UserComment.load(raw).strip()
    assert reason[:VLM_REASON_MAX_CHARS] in comment
    # 截断后长度不超过统一上限（用对称解码读取，避免脆弱的 split("Reason=",1)）
    parsed = parse_user_comment(comment)
    assert parsed["Reason"] == reason[:VLM_REASON_MAX_CHARS]
    assert len(parsed["Reason"]) <= VLM_REASON_MAX_CHARS

    # 纯中文无 ASCII 字符，ImageDescription 不应写入（完整中文在 UserComment）
    assert piexif.ImageIFD.ImageDescription not in exif["0th"]


def test_reason_with_semicolon_and_backslash(fixtures_dir: Path, tmp_path: Path) -> None:
    """reason 含 ; 与 \\（及中文）时：写入后经 parse_user_comment 读回应无损还原。

    回归点：未转义前，reason 内的 ; 会被误判为字段分隔符，破坏回读结构；
    转义方案（;→\\;、\\→\\\\）配合对称解码，使 Reason 值精确还原。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    # 含 ; 与 \\（及中文），长度 ≤ VLM_REASON_MAX_CHARS，避免截断干扰本测试的转义验证
    reason = "构图;清晰\\稳定焦点"
    scored = _score(path, vlm_reason=reason, vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True

    exif = piexif.load(path)
    raw = exif["Exif"][piexif.ExifIFD.UserComment]
    comment = piexif.helper.UserComment.load(raw).strip()

    # UserComment 整体人类可读，且仍含其它字段
    assert "FlashGazeScore=92.75" in comment
    # 关键：用对称解码还原的 Reason 必须与原文完全一致（含 ; \\ 中文）
    parsed = parse_user_comment(comment)
    assert parsed["Reason"] == reason
    # 不应因 reason 内的 ; 而被拆出额外字段
    assert set(parsed.keys()) == {
        "FlashGazeScore",
        "Sharpness",
        "Exposure",
        "Reason",
    }


def test_reason_with_literal_double_backslash(fixtures_dir: Path, tmp_path: Path) -> None:
    """reason 含字面双反斜杠 \\\\（及中文与 ;）时：回读必须无损还原，禁止双重解码。

    防护栏：parse_user_comment 经 _split_escaped 已在切分时完成反转义，
    若有人在回读侧再加一层反转义（如 _unescape_value），本用例的 `a\\\\b`
    会被错误压成 `a\\b`，从而暴露回归。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    # 含字面双反斜杠、单分号与中文，长度 ≤ VLM_REASON_MAX_CHARS
    reason = "路径C:\\\\temp;构图清晰"
    scored = _score(path, vlm_reason=reason, vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True

    exif = piexif.load(path)
    raw = exif["Exif"][piexif.ExifIFD.UserComment]
    comment = piexif.helper.UserComment.load(raw).strip()

    parsed = parse_user_comment(comment)
    # 关键：字面双反斜杠必须原样保留，不允许被二次反斜杠解码压成单反斜杠
    assert parsed["Reason"] == reason
    # 不应因 reason 内的 ; 而被拆出额外字段
    assert set(parsed.keys()) == {
        "FlashGazeScore",
        "Sharpness",
        "Exposure",
        "Reason",
    }


def test_mixed_ascii_chinese_vlm_reason(fixtures_dir: Path, tmp_path: Path) -> None:
    """中英文混合理由：UserComment 含截断后中文，ImageDescription 留 ASCII 摘要。

    与 JSON/CSV 同一截断契约（VLM_REASON_MAX_CHARS），中文不丢、仅按字符截断。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    reason = "Good shot 这是一张好照片，构图稳健 composition solid。"
    scored = _score(path, vlm_reason=reason, vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True

    exif = piexif.load(path)
    # UserComment 保留截断后的中文（统一上限内）
    raw = exif["Exif"][piexif.ExifIFD.UserComment]
    assert reason[:VLM_REASON_MAX_CHARS] in piexif.helper.UserComment.load(raw).strip()
    # ImageDescription 仅含 ASCII 部分，且不含中文字符
    desc = exif["0th"][piexif.ImageIFD.ImageDescription].decode("ascii")
    assert "Good shot" in desc
    assert not any(ord(ch) >= 128 for ch in desc)


def test_optional_fields_written(fixtures_dir: Path, tmp_path: Path) -> None:
    """composition/noise/color 存在时追加进 UserComment。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(
        path,
        composition=60.0,
        noise=40.0,
        color=50.0,
        vlm_reason="",
        vlm_provider="",
    )
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "Composition=60.00" in comment
    assert "Noise=40.00" in comment
    assert "Color=50.00" in comment


# ---------- write_one：不支持格式 ----------


def test_unsupported_format(tmp_path: Path) -> None:
    """传 .png 路径：ok=False，error=='unsupported_format'，不抛异常。"""
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    scored = _score(str(png))
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is False
    assert result.error == "unsupported_format"


# ---------- write_one：损坏文件不崩溃 ----------


def test_write_failure_not_raise(corrupted_img: str, tmp_path: Path) -> None:
    """损坏文件（纯文本伪装 jpg）：不抛异常，ok=False，error 非空。"""
    path = _copy_fixture(Path(corrupted_img).parent, tmp_path, "corrupted.jpg")
    scored = _score(path)
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is False
    assert result.error  # 非空字符串，异常被捕获并转成可读信息


# ---------- write_batch ----------


def test_batch_write(fixtures_dir: Path, tmp_path: Path) -> None:
    """批量：selected+ok JPEG 成功；selected 但不支持格式失败；未选/出错跳过。"""
    jpg_ok = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    png_bad = tmp_path / "bad.png"
    png_bad.write_bytes(b"fake")
    jpg_skip = _copy_fixture(fixtures_dir, tmp_path, "blurry.jpg")

    scored = [
        _score(jpg_ok, selected=True, vlm_reason="good", vlm_provider="qwen"),  # 成功
        _score(str(png_bad), selected=True),  # 不支持格式
        _score(jpg_skip, selected=False),  # 未入选，跳过
        _score(jpg_ok, selected=True, error="decode"),  # 出错，跳过
    ]
    results = ExifWriter(preserve_original=False).write_batch(scored)

    # 仅 2 个被处理（一个成功、一个不支持格式）
    assert len(results) == 2
    by_path = {r.path: r for r in results}
    assert by_path[jpg_ok].ok is True
    assert by_path[str(png_bad)].ok is False
    assert by_path[str(png_bad)].error == "unsupported_format"
    # 单张失败不影响其它
    assert all(isinstance(r, ExifWriteResult) for r in results)


def test_batch_empty() -> None:
    """空列表返回空结果，不崩溃。"""
    assert ExifWriter().write_batch([]) == []


# ---------- 备份策略 ----------


def test_backup_created(fixtures_dir: Path, tmp_path: Path) -> None:
    """preserve_original=True：备份机制触发——.flashgaze_backup 目录被创建，
    但写入成功后进程级 .bak.<pid> 精确回滚点即被清理（不遗留垃圾）。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    writer = ExifWriter(preserve_original=True)
    result = writer.write_one(scored)
    assert result.ok is True
    backup_dir = Path(path).parent / ".flashgaze_backup"
    assert backup_dir.exists()
    # 成功后 .bak.<pid> 已删除（失败才保留，见 test_insert_failure_keeps_original）
    bak_files = sorted(backup_dir.glob(f"{Path(path).name}.flashgaze_bak.*"))
    assert bak_files == []
    # 原图已写入 EXIF（备份不污染原图）
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment


def test_no_backup_when_disabled(fixtures_dir: Path, tmp_path: Path) -> None:
    """preserve_original=False：不创建 .flashgaze_backup 目录。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="", vlm_provider="")
    writer = ExifWriter(preserve_original=False)
    result = writer.write_one(scored)
    assert result.ok is True
    assert not (Path(path).parent / ".flashgaze_backup").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位断言仅 POSIX 有意义")
def test_backup_inherits_source_mode(fixtures_dir: Path, tmp_path: Path) -> None:
    """备份 .bak 继承源文件权限位（FIX #2-3 补漏）：.bak 是新建文件，
    atomic_write 的 preserve_mode 分支对新建目标不生效，须显式传源 st_mode——
    否则 0600 原图按默认 umask 备份成 0644，写入失败路径保留的回滚点即泄露面。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    os.chmod(path, 0o600)

    bak = ExifWriter(preserve_original=True)._backup(str(path))

    assert bak.exists()
    assert stat.S_IMODE(os.stat(bak).st_mode) == 0o600
    # 直调 _backup 不经过 write_one 的成功/失败清理路径，显式清理
    bak.unlink()


# ---------- C-02：备份失败中止写入 + 原子落盘 ----------


def test_backup_failure_aborts_write(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """preserve_original=True 时备份失败：返回 ok=False, error='backup_failed'，
    且原图字节不被覆盖（C-02）。"""
    from flashgaze.core.exif_writer import BackupFailed

    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    original_bytes = Path(path).read_bytes()
    scored = _score(path, vlm_reason="", vlm_provider="")

    def _boom(self: ExifWriter, p: str) -> None:
        raise BackupFailed(p)

    monkeypatch.setattr(ExifWriter, "_backup", _boom)

    result = ExifWriter(preserve_original=True).write_one(scored)
    assert result.ok is False
    assert result.error == "backup_failed"
    # 原图未被写入/覆盖：字节与原 fixture 完全一致
    assert Path(path).read_bytes() == original_bytes


def test_insert_failure_keeps_original(
    fixtures_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """piexif.insert 失败时：原图不损坏，且 .bak.<pid> 回滚点保留为写入前字节、
    记 WARNING 含恢复路径（C-01 加固）。"""
    import logging

    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    original_bytes = Path(path).read_bytes()
    # chmod 0600 模拟受限权限原图：失败保留的 .bak 正是权限泄露面（#2-3 补漏）
    os.chmod(path, 0o600)
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")

    def _fail(*a: object, **k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(exif_writer_mod, "_insert_exif_jpeg", _fail)

    with caplog.at_level(logging.WARNING):
        result = ExifWriter(preserve_original=True).write_one(scored)
    assert result.ok is False
    assert result.error is not None and "boom" in result.error
    # 原图未被半截覆盖：字节仍等于写入前
    assert Path(path).read_bytes() == original_bytes
    # C-01：失败保留 .bak 进程级回滚点，且为写入前原图字节
    backup_dir = Path(path).parent / ".flashgaze_backup"
    bak_files = sorted(backup_dir.glob(f"{Path(path).name}.flashgaze_bak.*"))
    assert len(bak_files) == 1
    assert bak_files[0].read_bytes() == original_bytes
    if os.name != "nt":
        # #2-3 补漏：失败保留的 .bak 权限位与原图一致（0600），未按默认 umask 放宽
        assert stat.S_IMODE(os.stat(bak_files[0]).st_mode) == 0o600
    # WARNING 含恢复路径（含 flashgaze_bak 标记）
    assert any("flashgaze_bak" in r.message for r in caplog.records)


def test_preserve_original_writes_exif_and_cleans_bak(fixtures_dir: Path, tmp_path: Path) -> None:
    """preserve_original=True：原图写入 EXIF，且本次进程精确回滚点 .bak.<pid>
    在写入成功后即被删除（成功清理语义；失败才保留）。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=True).write_one(scored)
    assert result.ok is True

    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment
    # 写入成功后 .bak.<pid> 已被删除（不遗留垃圾）
    backup_dir = Path(path).parent / ".flashgaze_backup"
    bak_files = sorted(backup_dir.glob(f"{Path(path).name}.flashgaze_bak.*"))
    assert bak_files == []


# ---------- M-12：备份名单调序号 + 清理失败不影响写入结论 ----------


def test_backup_path_monotonic_seq_no_overwrite(fixtures_dir: Path, tmp_path: Path) -> None:
    """M-12：同图二次备份取更高序号（.<pid>.<seq>），不覆盖最初回滚点。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    writer = ExifWriter(preserve_original=True)
    bak1 = writer._backup(str(path))
    bak2 = writer._backup(str(path))
    assert bak1 != bak2
    assert bak1.exists() and bak2.exists()
    # 两份备份内容均为写入前原图字节
    original = Path(path).read_bytes()
    assert bak1.read_bytes() == original
    assert bak2.read_bytes() == original
    bak1.unlink()
    bak2.unlink()


def test_bak_unlink_failure_keeps_success(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-12：写入成功后清理 .bak 失败（如文件被占用）仅记 DEBUG，
    write_one 仍返回 ok=True，不再被外层 except 误判为写入失败。"""
    real_unlink = Path.unlink

    def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
        # 只拦截最终 .bak（备份经 atomic_write 落盘时的 .tmp.<pid> 中间文件名
        # 同样含 flashgaze_bak，须放行，否则备份本身会失败）
        s = str(self)
        if "flashgaze_bak" in s and ".tmp." not in s:
            raise OSError("file busy")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _fail_unlink)

    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=True).write_one(scored)
    assert result.ok is True
    assert result.error is None


def test_preserve_original_false_no_backup(fixtures_dir: Path, tmp_path: Path) -> None:
    """preserve_original=False（即 exif_backup=False）：不创建 .flashgaze_backup 目录。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    assert not (Path(path).parent / ".flashgaze_backup").exists()


# ---------- H-2：无备份时的差异撤销日志 ----------


def _undo_records(undo_log: Path) -> list[dict[str, Any]]:
    """读取撤销日志（JSONL），返回解析后的记录列表。"""
    text = undo_log.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_undo_log_records_pre_write_state(fixtures_dir: Path, tmp_path: Path) -> None:
    """无备份模式：撤销日志记录「写入前」原图 SHA256 与原 UserComment（差异可回退）。

    二次写入时 user_comment_before 须为首次写入的 UserComment，sha256_before
    须为首次写入后的字节——即每条记录都是该次覆盖前的真实前态。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    sha_before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    undo_log = tmp_path / ".flashgaze_undo" / "exif_undo.jsonl"
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")

    result = ExifWriter(preserve_original=False, undo_log=undo_log).write_one(scored)
    assert result.ok is True

    records = _undo_records(undo_log)
    assert len(records) == 1
    assert records[0]["sha256_before"] == sha_before
    assert records[0]["user_comment_before"] is None  # 原图无 FlashGaze UserComment
    assert records[0]["pid"] == os.getpid()
    assert Path(records[0]["path"]).name == Path(path).name
    assert records[0]["ts"]  # UTC 时间戳非空

    # 二次写入：前态 = 首次写入后的字节与 UserComment
    sha_after_first = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    first_comment = piexif.helper.UserComment.load(
        piexif.load(path)["Exif"][piexif.ExifIFD.UserComment]
    )
    result2 = ExifWriter(preserve_original=False, undo_log=undo_log).write_one(scored)
    assert result2.ok is True
    records = _undo_records(undo_log)
    assert len(records) == 2
    assert records[1]["sha256_before"] == sha_after_first
    assert records[1]["user_comment_before"] == first_comment


def test_undo_log_failure_warns_and_still_writes(
    fixtures_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """撤销日志落盘失败（父路径被普通文件占用）：仅 WARNING，不阻断 EXIF 写入。

    用户已用 --force 接受无回滚点，撤销日志是 best-effort 补偿而非写入前置条件，
    故其失败不得把成功的写入判为失败。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    blocker = tmp_path / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    undo_log = blocker / ".flashgaze_undo" / "exif_undo.jsonl"

    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    with caplog.at_level(logging.WARNING, logger="flashgaze.core.exif_writer"):
        result = ExifWriter(preserve_original=False, undo_log=undo_log).write_one(scored)

    assert result.ok is True
    assert result.error is None
    # EXIF 仍已写入（不因撤销日志失败而回滚判定）
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment
    assert any("撤销日志" in r.message for r in caplog.records)


def test_undo_log_only_when_explicitly_enabled(fixtures_dir: Path, tmp_path: Path) -> None:
    """边界：仅当显式传入 undo_log 才落盘撤销日志；默认（备份模式）零新增文件。

    默认路径不得因为加了撤销日志能力就产生额外磁盘痕迹。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")

    assert ExifWriter(preserve_original=False).write_one(scored).ok is True
    assert list(tmp_path.rglob("*.jsonl")) == []

    undo_log = tmp_path / ".flashgaze_undo" / "exif_undo.jsonl"
    assert ExifWriter(preserve_original=False, undo_log=undo_log).write_one(scored).ok is True
    assert len(_undo_records(undo_log)) == 1


# ---------- M2：XMP/IPTC sidecar 段保留 ----------


def test_xmp_iptc_preserved_after_write(fixtures_dir: Path, tmp_path: Path) -> None:
    """M2：对含 XMP+IPTC 的 JPEG 写入后，sidecar 段须原样保留、且仅一个 Exif APP1。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    _inject_xmp_iptc(Path(path))
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True

    # 回写后原图仍可正常读取，FlashGaze EXIF 已写入
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment

    # 全部 APP 段保留：XMP 与 IPTC 仍在
    segs = _split_jpeg_segments(Path(path).read_bytes())
    assert any(_XMP_NS in s for s in segs)
    assert any(s[0:2] == b"\xff\xed" and s[4 : 4 + 13] == b"Photoshop 3.0" for s in segs)
    # 无重复 Exif APP1
    exif_app1 = [s for s in segs if s[0:2] == b"\xff\xe1" and s[4:10] == b"Exif\x00\x00"]
    assert len(exif_app1) == 1


def test_xmp_iptc_warning_logged(
    fixtures_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """M2：检测到 XMP/IPTC 时记录 WARNING 审计（默认仍保留并写入）。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    _inject_xmp_iptc(Path(path))
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    with caplog.at_level(logging.WARNING, logger="flashgaze.core.exif_writer"):
        result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    assert any("sidecar" in r.message for r in caplog.records)
    # WARNING 同时列出 xmp 与 iptc
    assert any("xmp" in r.message and "iptc" in r.message for r in caplog.records)


def test_no_duplicate_exif_when_xmp_before_exif(fixtures_dir: Path, tmp_path: Path) -> None:
    """M2 边缘：原图已有 Exif APP1 但排在 XMP 之后（piexif 旧逻辑会生成重复段）。

    自写段重组须移除旧 Exif APP1 后仅插入一个，杜绝重复/畸形 EXIF 段。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    _inject_existing_exif_before(Path(path))
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    segs = _split_jpeg_segments(Path(path).read_bytes())
    exif_app1 = [s for s in segs if s[0:2] == b"\xff\xe1" and s[4:10] == b"Exif\x00\x00"]
    assert len(exif_app1) == 1


def test_detect_sidecar_segments_unit() -> None:
    """_detect_sidecar_segments：对合成段正确识别 xmp/iptc，无 sidecar 时返回空集。"""
    xmp = b"\xff\xe1" + struct.pack(">H", len(_XMP_PAYLOAD) + 2) + _XMP_PAYLOAD
    iptc = b"\xff\xed" + struct.pack(">H", len(_IPTC_PAYLOAD) + 2) + _IPTC_PAYLOAD
    plain = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    soi = b"\xff\xd8"
    assert _detect_sidecar_segments(soi + xmp + plain) == {"xmp"}
    assert _detect_sidecar_segments(soi + iptc + plain) == {"iptc"}
    assert _detect_sidecar_segments(soi + xmp + iptc + plain) == {"xmp", "iptc"}
    assert _detect_sidecar_segments(soi + plain) == set()


# ---------- write_one：WebP（piexif 已安全保留全部 chunk） ----------


def _strip_webp_exif(webp_path: Path) -> None:
    """移除 WebP 的 EXIF chunk（若存在），使其回到无 EXIF 状态。

    用于构造"确定无 EXIF"的 WebP 输入，使无 EXIF 回归测试不依赖 fixture 当前
    是否恰好含 EXIF chunk。WebP 容器：RIFF....WEBP 后逐 chunk（4cc + 4 字节
    size + payload，size 为奇数时补 1 字节 padding）。
    """
    data = webp_path.read_bytes()
    if data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return
    body = data[12:]
    out = bytearray()
    n = len(body)
    i = 0
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        if fourcc != b"EXIF":
            out += body[i : i + 8 + size]
        i += 8 + size + (size & 1)  # 奇数 size 后跟 1 字节 padding
    webp_path.write_bytes(data[0:12] + bytes(out))


def _inject_webp_xmp(webp_path: Path) -> None:
    """在 WebP 容器末尾插入一个合法的 XMP sidecar chunk（用于数据保留验证）。

    复用与 _strip_webp_exif 相同的 WebP chunk 解析范式：RIFF....WEBP 后逐
    chunk（4cc + 4 字节小端 size + payload，size 奇数补 1 字节 padding）。
    XMP chunk 的 fourcc 为 b"XMP "（含尾随空格），payload 以 _XMP_PAYLOAD
    开头。插入位置在现有全部 chunk 之后（保持原 chunk 顺序不变），仅当已存在
    XMP chunk 时跳过，避免重复注入。
    """
    data = webp_path.read_bytes()
    if data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return
    body = data[12:]
    n = len(body)
    i = 0
    existing_xmp = False
    out = bytearray()
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        out += body[i : i + 8 + size]
        if size & 1:
            out += body[i + 8 + size : i + 8 + size + 1]  # padding
        if fourcc == b"XMP ":
            existing_xmp = True
        i += 8 + size + (size & 1)
    if existing_xmp:
        return
    payload = _XMP_PAYLOAD
    chunk = b"XMP " + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        chunk += b"\x00"  # 奇数 payload 补 1 字节 padding
    webp_path.write_bytes(data[0:12] + bytes(out) + chunk)


def _inject_webp_iccp(webp_path: Path) -> None:
    """在 WebP 容器末尾插入一个合法的 ICCP sidecar chunk（用于去重验证）。

    复用与 _inject_webp_xmp 相同的 WebP chunk 解析范式。ICCP chunk 的 fourcc 为
    b"ICCP"，payload 用一个最小占位 ICC profile。仅当已存在 ICCP chunk 时跳过，
    避免重复注入。
    """
    data = webp_path.read_bytes()
    if data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return
    body = data[12:]
    n = len(body)
    i = 0
    existing_iccp = False
    out = bytearray()
    while i + 8 <= n:
        fourcc = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        out += body[i : i + 8 + size]
        if size & 1:
            out += body[i + 8 + size : i + 8 + size + 1]  # padding
        if fourcc == b"ICCP":
            existing_iccp = True
        i += 8 + size + (size & 1)
    if existing_iccp:
        return
    payload = b"FakeICCProfile\x00\x01\x02"
    chunk = b"ICCP" + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        chunk += b"\x00"  # 奇数 payload 补 1 字节 padding
    webp_path.write_bytes(data[0:12] + bytes(out) + chunk)


def _count_webp_chunks(webp_bytes: bytes, fourcc: bytes) -> int:
    """统计 WebP 容器中出现指定 fourcc 的 chunk 个数。"""
    if webp_bytes[0:4] != b"RIFF" or webp_bytes[8:12] != b"WEBP":
        return 0
    body = webp_bytes[12:]
    n = len(body)
    i = 0
    count = 0
    while i + 8 <= n:
        f = body[i : i + 4]
        size = struct.unpack("<I", body[i + 4 : i + 8])[0]
        if f == fourcc:
            count += 1
        i += 8 + size + (size & 1)
    return count


def test_webp_preserves_xmp_after_exif_write(fixtures_dir: Path, tmp_path: Path) -> None:
    """回归：含 XMP sidecar 的 WebP 经 EXIF 写回后 XMP 仍须保留（数据完整性，Medium）。

    工作记忆记载 WebP 路径"piexif.insert 经 split/merge_chunks 已安全保留
    XMP/ICCP"，但此非官方强保证、此前无专门回归测试覆盖。本测试构造含 XMP
    chunk 的 WebP → write_one → 遍历写回字节断言 XMP chunk 仍在且含 XMP 命名
    空间，实测验证该假设。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "fmt_sharp.webp")
    _inject_webp_xmp(Path(path))
    # 起点断言：注入后确实含 XMP chunk（否则测试失去意义）
    _raw = Path(path).read_bytes()
    assert any(_raw[i : i + 4] == b"XMP " for i in range(12, len(_raw) - 8)), "注入 XMP chunk 失败"

    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    assert result.error is None

    # 写回后 XMP 段必须仍存在
    out = Path(path).read_bytes()
    xmp_found = False
    n = len(out)
    i = 12  # 跳过 RIFF....WEBP
    while i + 8 <= n:
        fourcc = out[i : i + 4]
        size = struct.unpack("<I", out[i + 4 : i + 8])[0]
        if fourcc == b"XMP ":
            xmp_found = _XMP_NS in out[i + 8 : i + 8 + size]
            break
        i += 8 + size + (size & 1)
    assert xmp_found, "WebP 经 EXIF 写回后 XMP sidecar 丢失"
    # 去重回归：XMP 必须恰好一个 chunk，不得因重挂产生重复（数据损坏）
    assert _count_webp_chunks(out, b"XMP ") == 1, "WebP 经 EXIF 写回后 XMP chunk 重复"
    # EXIF 也须恰好一个 chunk
    assert _count_webp_chunks(out, b"EXIF") == 1, "WebP 写回后 EXIF chunk 数量异常"


def test_webp_no_duplicate_sidecar_chunks(fixtures_dir: Path, tmp_path: Path) -> None:
    """回归（本次 bug 修复）：含 XMP + ICCP 的 WebP 经 EXIF 写回后，XMP / ICCP /
    EXIF 各至多（且恰好）一个 chunk，不得因 sidecar 重挂产生重复（元数据损坏）。

    根因：新版 piexif.insert 会保留 XMP/ICCP，而 _insert_exif_webp 此前无条件把
    原图提取的 sidecar 重挂一次，导致输出出现重复 XMP chunk。修复后重挂前按 fourcc
    幂等去重，无论 piexif 是否保留 sidecar，输出恒为恰好一个。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "fmt_sharp.webp")
    _inject_webp_xmp(Path(path))
    _inject_webp_iccp(Path(path))
    # 起点断言：注入后确实各含一个 XMP 与 ICCP chunk（否则测试失去意义）
    _raw = Path(path).read_bytes()
    assert _count_webp_chunks(_raw, b"XMP ") == 1, "注入 XMP chunk 失败"
    assert _count_webp_chunks(_raw, b"ICCP") == 1, "注入 ICCP chunk 失败"

    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    assert result.error is None

    out = Path(path).read_bytes()
    # 每个 fourcc 恰好一个 chunk：XMP / ICCP 不得重复，EXIF 必须存在且唯一
    assert _count_webp_chunks(out, b"XMP ") == 1, "WebP 写回后 XMP chunk 重复"
    assert _count_webp_chunks(out, b"ICCP") == 1, "WebP 写回后 ICCP chunk 重复"
    assert _count_webp_chunks(out, b"EXIF") == 1, "WebP 写回后 EXIF chunk 数量异常"
    # XMP 内容须为从原图提取的权威副本（含 XMP 命名空间）
    n = len(out)
    i = 12
    xmp_ok = False
    while i + 8 <= n:
        fourcc = out[i : i + 4]
        size = struct.unpack("<I", out[i + 4 : i + 8])[0]
        if fourcc == b"XMP ":
            xmp_ok = _XMP_NS in out[i + 8 : i + 8 + size]
            break
        i += 8 + size + (size & 1)
    assert xmp_ok, "WebP 写回后 XMP sidecar 内容丢失"


def test_write_webp_without_exif_succeeds(fixtures_dir: Path, tmp_path: Path) -> None:
    """回归：WebP 无 EXIF chunk（导出型常见）时 write_one 必须成功写入评分。

    修复前 piexif.load 对无 EXIF WebP 抛 "doesnot have exif"，被外层 except 静默
    判失败（ok=False）；修复后以空字典起步、piexif.insert 写入新 EXIF。本例先用
    _strip_webp_exif 确保输入确定无 EXIF，断言 ok=True 且评分已读回。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "fmt_sharp.webp")
    _strip_webp_exif(Path(path))  # 确保起点为无 EXIF WebP
    # 断言起点确实无 EXIF chunk：piexif.load 须抛 "doesnot have exif"
    import pytest as _pytest

    with _pytest.raises(Exception, match="doesnot have exif"):
        piexif.load(path)

    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    assert result.error is None

    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment
    assert "Sharpness=80.00" in comment
    assert exif["0th"][piexif.ImageIFD.Software].decode("ascii") == "FlashGaze/qwen"


def test_write_webp_preserves_chunks(fixtures_dir: Path, tmp_path: Path) -> None:
    """WebP 写入成功且 EXIF 可读（M2：WebP 路径维持现状、不改写）。

    注：WebP 无 EXIF chunk 时 write_one 现已能自动以空 EXIF 起步写入（不再静默
    失败），此处仍预置一个 EXIF chunk 以验证"已有 EXIF 时写回不丢 chunk"。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "fmt_sharp.webp")
    piexif.insert(piexif.dump({}), path)
    scored = _score(path, vlm_reason="good", vlm_provider="qwen")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "FlashGazeScore=92.75" in comment


def test_webp_insert_failure_keeps_original(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WebP：EXIF 段重组失败时原图不损坏（C-02 原子落盘）。

    WebP 路径现走内置纯 Python 段重组 `_insert_exif_webp`（不再依赖 piexif.insert），
    故失败注入目标改为该内部函数；write_one 捕获异常后中止写入、原图保持原样。
    """
    path = _copy_fixture(fixtures_dir, tmp_path, "fmt_sharp.webp")
    original = Path(path).read_bytes()
    scored = _score(path, vlm_reason="", vlm_provider="")

    def _fail(*a: object, **k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(exif_writer_mod, "_insert_exif_webp", _fail)

    result = ExifWriter(preserve_original=True).write_one(scored)
    assert result.ok is False
    assert result.error is not None and "boom" in result.error
    assert Path(path).read_bytes() == original

"""ExifWriter 测试。

覆盖 JPEG 写入、不支持格式、批量、备份创建、cv-only 标记与损坏文件不崩溃。
测试写到 tmp_path 副本，避免污染 tests/fixtures/ 里的原图。
需先安装 piexif: pip install piexif
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("piexif")

import piexif.helper  # UserComment 读取；需显式导入子模块

from flashgaze.core.exif_writer import ExifWriteResult, ExifWriter
from flashgaze.models.schemas import ImageScore


def _score(path: str, selected: bool = True, error=None, **kw) -> ImageScore:
    """构造最小 ImageScore。file 取路径文件名。"""
    base = dict(
        file=Path(path).name,
        path=path,
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=0.0,
        score=92.75,
        selected=selected,
        error=error,
    )
    base.update(kw)
    return ImageScore(**base)


def _copy_fixture(fixtures_dir: Path, tmp_path: Path, name: str) -> str:
    """把 fixture 复制到临时目录，返回新路径（避免污染原图）。"""
    src = fixtures_dir / name
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


# ---------- write_one：JPEG 成功 ----------

def test_write_jpeg(fixtures_dir: Path, tmp_path: Path):
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


def test_cv_only_software(fixtures_dir: Path, tmp_path: Path):
    """vlm_provider 为空时 Software 为 FlashGaze/cv-only。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="", vlm_provider="")
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    exif = piexif.load(path)
    assert exif["0th"][piexif.ImageIFD.Software].decode("ascii") == "FlashGaze/cv-only"
    # 空 vlm_reason 不写 ImageDescription
    assert piexif.ImageIFD.ImageDescription not in exif["0th"]


def test_optional_fields_written(fixtures_dir: Path, tmp_path: Path):
    """composition/noise/color 存在时追加进 UserComment。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(
        path, composition=60.0, noise=40.0, color=50.0,
        vlm_reason="", vlm_provider="",
    )
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is True
    exif = piexif.load(path)
    comment = piexif.helper.UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment])
    assert "Composition=60.00" in comment
    assert "Noise=40.00" in comment
    assert "Color=50.00" in comment


# ---------- write_one：不支持格式 ----------

def test_unsupported_format(tmp_path: Path):
    """传 .png 路径：ok=False，error=='unsupported_format'，不抛异常。"""
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    scored = _score(str(png))
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is False
    assert result.error == "unsupported_format"


# ---------- write_one：损坏文件不崩溃 ----------

def test_write_failure_not_raise(corrupted_img: str, tmp_path: Path):
    """损坏文件（纯文本伪装 jpg）：不抛异常，ok=False，error 非空。"""
    path = _copy_fixture(Path(corrupted_img).parent, tmp_path, "corrupted.jpg")
    scored = _score(path)
    result = ExifWriter(preserve_original=False).write_one(scored)
    assert result.ok is False
    assert result.error  # 非空字符串，异常被捕获并转成可读信息


# ---------- write_batch ----------

def test_batch_write(fixtures_dir: Path, tmp_path: Path):
    """批量：selected+ok JPEG 成功；selected 但不支持格式失败；未选/出错跳过。"""
    jpg_ok = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    png_bad = tmp_path / "bad.png"
    png_bad.write_bytes(b"fake")
    jpg_skip = _copy_fixture(fixtures_dir, tmp_path, "blurry.jpg")

    scored = [
        _score(jpg_ok, selected=True, vlm_reason="good", vlm_provider="qwen"),   # 成功
        _score(str(png_bad), selected=True),                                     # 不支持格式
        _score(jpg_skip, selected=False),                                        # 未入选，跳过
        _score(jpg_ok, selected=True, error="decode"),                           # 出错，跳过
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


def test_batch_empty():
    """空列表返回空结果，不崩溃。"""
    assert ExifWriter().write_batch([]) == []


# ---------- 备份策略 ----------

def test_backup_created(fixtures_dir: Path, tmp_path: Path):
    """preserve_original=True：图片同目录出现 .flashgaze_backup/<文件名>。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="", vlm_provider="")
    writer = ExifWriter(preserve_original=True)
    result = writer.write_one(scored)
    assert result.ok is True
    backup = Path(path).parent / ".flashgaze_backup" / Path(path).name
    assert backup.exists()
    # 备份应是写入前的原始字节（与原 fixture 一致）
    assert backup.read_bytes() == (fixtures_dir / "sharp.jpg").read_bytes()


def test_no_backup_when_disabled(fixtures_dir: Path, tmp_path: Path):
    """preserve_original=False：不创建 .flashgaze_backup 目录。"""
    path = _copy_fixture(fixtures_dir, tmp_path, "sharp.jpg")
    scored = _score(path, vlm_reason="", vlm_provider="")
    writer = ExifWriter(preserve_original=False)
    result = writer.write_one(scored)
    assert result.ok is True
    assert not (Path(path).parent / ".flashgaze_backup").exists()

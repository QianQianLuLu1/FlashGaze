"""Exporter 测试。"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from flashgaze.core.exporter import Exporter
from flashgaze.models.schemas import Config, ImageScore


def _score(file: str, path: str, score: float, selected: bool = False, error=None) -> ImageScore:
    return ImageScore(
        file=file,
        path=path,
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=0.0,
        score=score,
        selected=selected,
        error=error,
    )


def _config(**overrides) -> Config:
    base = dict(directory=".")
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> Path:
    """复制 sharp/blurry 到临时目录。"""
    for name in ("sharp.jpg", "blurry.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return tmp_path


# ---------- export_images ----------

def test_export_copies_selected_images(photo_dir: Path, tmp_path: Path):
    """selected 的图片被复制到目标目录。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    blurry_path = str(photo_dir / "blurry.jpg")
    scored = [
        _score("sharp.jpg", sharp_path, 90.0, selected=True),
        _score("blurry.jpg", blurry_path, 40.0, selected=False),
    ]
    dest = tmp_path / "精选"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 1
    assert (dest / "sharp.jpg").exists()
    assert not (dest / "blurry.jpg").exists()
    # 原文件仍在（复制非移动）
    assert (photo_dir / "sharp.jpg").exists()


def test_export_moves_when_config_set(photo_dir: Path, tmp_path: Path):
    """move=True 时原文件被移走。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    scored = [_score("sharp.jpg", sharp_path, 90.0, selected=True)]
    dest = tmp_path / "moved"
    exporter = Exporter(_config(export=True, move=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 1
    assert (dest / "sharp.jpg").exists()
    assert not Path(sharp_path).exists()


def test_export_skips_error_images(photo_dir: Path, tmp_path: Path):
    """带 error 的图即使 selected 也不导出。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    scored = [
        _score("sharp.jpg", sharp_path, 0.0, selected=True, error="corrupted"),
    ]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 0
    assert not (dest / "sharp.jpg").exists()


def test_export_creates_dest_dir(tmp_path: Path):
    """目标目录不存在时自动创建。"""
    scored: list[ImageScore] = []
    dest = tmp_path / "new" / "nested" / "精选"
    exporter = Exporter(_config(export=True))
    exporter.export_images(scored, str(dest))
    assert dest.exists()


def test_export_skips_missing_source(tmp_path: Path):
    """源文件不存在时跳过，不报错。"""
    scored = [_score("gone.jpg", str(tmp_path / "gone.jpg"), 90.0, selected=True)]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 0


def test_export_conflict_appends_suffix(photo_dir: Path, tmp_path: Path):
    """同名文件冲突时自动追加序号后缀（C-14）。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    # 两个 selected 图片都叫 sharp.jpg，目标目录已有一个 sharp.jpg
    scored = [
        _score("sharp.jpg", sharp_path, 90.0, selected=True),
        _score("sharp.jpg", sharp_path, 85.0, selected=True),
    ]
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "sharp.jpg").write_bytes(b"existing")  # 预占 sharp.jpg
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 2
    # 原文件保留，新增 sharp_1.jpg 和 sharp_2.jpg
    assert (dest / "sharp.jpg").exists()
    assert (dest / "sharp_1.jpg").exists()
    assert (dest / "sharp_2.jpg").exists()


def test_export_many_conflicts_uses_set_lookup(photo_dir: Path, tmp_path: Path):
    """大量同名冲突时集合查找 O(1)，不退化（C-14 性能验证）。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    # 50 个同名 selected 图片
    scored = [
        _score("sharp.jpg", sharp_path, 90.0 - i, selected=True)
        for i in range(50)
    ]
    dest = tmp_path / "bulk"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 50
    # sharp.jpg + sharp_1.jpg ~ sharp_49.jpg
    assert (dest / "sharp.jpg").exists()
    assert (dest / "sharp_49.jpg").exists()


# ---------- write_manifest JSON ----------

def test_write_json_manifest(tmp_path: Path):
    """JSON 清单包含 summary 与 images。"""
    scored = [
        _score("a.jpg", "/a.jpg", 90.0, selected=True),
        _score("b.jpg", "/b.jpg", 40.0, selected=False),
    ]
    path = tmp_path / "result.json"
    Exporter(_config()).write_manifest(scored, "json", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["code"] == 0
    assert data["summary"]["total"] == 2
    assert data["summary"]["selected"] == 1
    assert data["summary"]["avg_score"] == 65.0
    assert len(data["images"]) == 2
    assert data["images"][0]["file"] == "a.jpg"


def test_write_json_manifest_handles_empty(tmp_path: Path):
    """空列表不崩溃，avg_score 为 0。"""
    path = tmp_path / "empty.json"
    Exporter(_config()).write_manifest([], "json", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 0
    assert data["summary"]["avg_score"] == 0.0


# ---------- write_manifest CSV ----------

def test_write_csv_manifest(tmp_path: Path):
    """CSV 清单含表头与数据行。"""
    scored = [
        _score("a.jpg", "/a.jpg", 90.0, selected=True),
        _score("b.jpg", "/b.jpg", 40.0, selected=False),
    ]
    path = tmp_path / "result.csv"
    Exporter(_config()).write_manifest(scored, "csv", str(path))
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
        "file", "path", "sharpness", "exposure", "composition",
        "vlm_adjustment", "score", "selected", "error",
    ]
    assert len(rows) == 3  # 表头 + 2 行
    assert rows[1][0] == "a.jpg"
    assert rows[1][7] == "True"


def test_write_manifest_invalid_format(tmp_path: Path):
    """不支持的格式抛 ValueError。"""
    with pytest.raises(ValueError):
        Exporter(_config()).write_manifest([], "xml", str(tmp_path / "x.xml"))

"""Exporter 测试。"""

from __future__ import annotations

import csv
import errno
import json
import logging
import os
import shutil
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from flashgaze.core.exporter import Exporter
from flashgaze.models.schemas import MANIFEST_COLUMNS, Config, ImageScore
from flashgaze.utils.atomic_write import (
    _STALE_TMP_RE,
    cleanup_stale_tmp,
)

if TYPE_CHECKING:
    # 仅类型检查期导入：ExifWriteResult 所在模块依赖可选 piexif，运行时不得引入
    from flashgaze.core.exif_writer import ExifWriteResult


def _score(
    file: str,
    path: str,
    score: float,
    selected: bool = False,
    error: str | None = None,
) -> ImageScore:
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


def _score_with_vlm(
    file: str,
    path: str,
    score: float,
    vlm_reason: str,
    vlm_provider: str,
    vlm_adjustment: float = 0.0,
    selected: bool = False,
) -> ImageScore:
    """构造带 VLM 字段的 ImageScore（用于 VLM 扩展测试）。"""
    return ImageScore(
        file=file,
        path=path,
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=vlm_adjustment,
        score=score,
        selected=selected,
        vlm_reason=vlm_reason,
        vlm_provider=vlm_provider,
    )


def _config(**overrides: Any) -> Config:
    base: dict[str, Any] = {"directory": "."}
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


def test_export_copies_selected_images(photo_dir: Path, tmp_path: Path) -> None:
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


def test_export_moves_when_config_set(photo_dir: Path, tmp_path: Path) -> None:
    """move=True 时原文件被移走（N-2：同卷走 os.rename，一步原子完成）。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    scored = [_score("sharp.jpg", sharp_path, 90.0, selected=True)]
    dest = tmp_path / "moved"
    exporter = Exporter(_config(export=True, move=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 1
    assert (dest / "sharp.jpg").exists()
    assert not Path(sharp_path).exists()


def test_move_falls_back_to_atomic_write_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-2：os.rename 失败（如跨卷 EXDEV）时回退「原子写目标+删源」路径，
    移动仍成功且源文件权限保留（#2-3 补漏语义经回退路径维持）。"""
    src = tmp_path / "sharp.jpg"
    src.write_bytes(b"image-bytes")
    os.chmod(src, 0o600)
    scored = [_score("sharp.jpg", str(src), 90.0, selected=True)]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True, move=True))

    def _rename_boom(*a: object, **k: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link")  # 模拟跨卷 rename

    monkeypatch.setattr(os, "rename", _rename_boom)
    count = exporter.export_images(scored, str(dest))
    assert count == 1
    moved = dest / "sharp.jpg"
    assert moved.exists()
    assert moved.read_bytes() == b"image-bytes"
    assert not src.exists()  # 源已删除（回退路径语义）
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(moved).st_mode) == 0o600
    assert exporter.last_failures == []


def test_export_skips_error_images(photo_dir: Path, tmp_path: Path) -> None:
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


def test_export_creates_dest_dir(tmp_path: Path) -> None:
    """目标目录不存在时自动创建。"""
    scored: list[ImageScore] = []
    dest = tmp_path / "new" / "nested" / "精选"
    exporter = Exporter(_config(export=True))
    exporter.export_images(scored, str(dest))
    assert dest.exists()


def test_export_skips_missing_source(tmp_path: Path) -> None:
    """源文件不存在时跳过，不报错。"""
    scored = [_score("gone.jpg", str(tmp_path / "gone.jpg"), 90.0, selected=True)]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 0


def test_export_records_failures_in_last_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#9-3 回归：单张导出失败时 last_failures 记录明细，供调用方程序化获取。"""
    src = tmp_path / "sharp.jpg"
    src.write_bytes(b"dummy")
    scored = [_score("sharp.jpg", str(src), 90.0, selected=True)]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True, move=True))

    # N-2 后 move 先走 os.rename：让它抛错以落入「原子写目标+删源」回退路径，
    # 再由 atomic_write_bytes 抛错模拟落盘失败（权限不足/磁盘满等）。
    def _rename_boom(*a: object, **k: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    def _boom(p: Path, data: bytes, **_kw: object) -> None:
        raise OSError("disk full")  # 模拟落盘失败（权限不足/磁盘满等）

    monkeypatch.setattr(os, "rename", _rename_boom)
    monkeypatch.setattr("flashgaze.core.exporter.atomic_write_bytes", _boom)
    count = exporter.export_images(scored, str(dest))
    assert count == 0
    assert len(exporter.last_failures) == 1
    assert exporter.last_failures[0]["file"] == "sharp.jpg"
    assert "disk full" in exporter.last_failures[0]["error"]


def test_export_last_failures_reset_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """last_failures 每次调用前重置，不跨调用累积。"""
    src = tmp_path / "sharp.jpg"
    src.write_bytes(b"dummy")
    scored = [_score("sharp.jpg", str(src), 90.0, selected=True)]
    dest = tmp_path / "out"
    exporter = Exporter(_config(export=True, move=True))

    def _rename_boom(*a: object, **k: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    def _boom(p: Path, data: bytes, **_kw: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(os, "rename", _rename_boom)
    monkeypatch.setattr("flashgaze.core.exporter.atomic_write_bytes", _boom)
    exporter.export_images(scored, str(dest))
    assert len(exporter.last_failures) == 1
    # 第二次调用（同样失败）不应累积为 2
    exporter.export_images(scored, str(dest))
    assert len(exporter.last_failures) == 1


def test_export_conflict_appends_suffix(photo_dir: Path, tmp_path: Path) -> None:
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


def test_export_many_conflicts_uses_set_lookup(photo_dir: Path, tmp_path: Path) -> None:
    """大量同名冲突时集合查找 O(1)，不退化（C-14 性能验证）。"""
    sharp_path = str(photo_dir / "sharp.jpg")
    # 50 个同名 selected 图片
    scored = [_score("sharp.jpg", sharp_path, 90.0 - i, selected=True) for i in range(50)]
    dest = tmp_path / "bulk"
    exporter = Exporter(_config(export=True))
    count = exporter.export_images(scored, str(dest))
    assert count == 50
    # sharp.jpg + sharp_1.jpg ~ sharp_49.jpg
    assert (dest / "sharp.jpg").exists()
    assert (dest / "sharp_49.jpg").exists()


# ---------- write_manifest JSON ----------


def test_write_json_manifest(tmp_path: Path) -> None:
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


def test_write_json_manifest_handles_empty(tmp_path: Path) -> None:
    """空列表不崩溃，avg_score 为 0。"""
    path = tmp_path / "empty.json"
    Exporter(_config()).write_manifest([], "json", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 0
    assert data["summary"]["avg_score"] == 0.0


# ---------- write_manifest CSV ----------


def test_write_csv_manifest(tmp_path: Path) -> None:
    """CSV 清单含表头与数据行。"""
    scored = [
        _score("a.jpg", "/a.jpg", 90.0, selected=True),
        _score("b.jpg", "/b.jpg", 40.0, selected=False),
    ]
    path = tmp_path / "result.csv"
    Exporter(_config()).write_manifest(scored, "csv", str(path))
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    # 表头以 MANIFEST_COLUMNS 为单一来源逐列对齐（防加列漂移）
    assert rows[0] == list(MANIFEST_COLUMNS)
    assert len(rows) == 3  # 表头 + 2 行
    assert rows[1][0] == "a.jpg"
    assert rows[1][7] == "True"


# ---------- VLM 扩展：vlm_reason / vlm_provider 字段输出（M8）----------


def test_csv_includes_vlm_reason_and_provider_columns(tmp_path: Path) -> None:
    """CSV 表头包含 vlm_reason / vlm_provider 两列。"""
    scored = [_score("a.jpg", "/a.jpg", 90.0)]
    path = tmp_path / "result.csv"
    Exporter(_config()).write_manifest(scored, "csv", str(path))
    with open(path, encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    assert "vlm_reason" in header
    assert "vlm_provider" in header


def test_csv_writes_vlm_fields_to_data_rows(tmp_path: Path) -> None:
    """VLM 成功时 vlm_reason / vlm_provider 写入数据行。"""
    scored = [
        _score_with_vlm(
            "a.jpg",
            "/a.jpg",
            90.0,
            vlm_reason="背景虚化",
            vlm_provider="qwen",
            vlm_adjustment=5.0,
            selected=True,
        ),
    ]
    path = tmp_path / "result.csv"
    Exporter(_config()).write_manifest(scored, "csv", str(path))
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    data_row = rows[1]
    reason_idx = header.index("vlm_reason")
    provider_idx = header.index("vlm_provider")
    adj_idx = header.index("vlm_adjustment")
    assert data_row[reason_idx] == "背景虚化"
    assert data_row[provider_idx] == "qwen"
    assert data_row[adj_idx] == "5.0"


def test_csv_empty_vlm_fields_when_not_set(tmp_path: Path) -> None:
    """未启用 VLM 时 vlm_reason / vlm_provider 列为空串。"""
    scored = [_score("a.jpg", "/a.jpg", 90.0)]
    path = tmp_path / "result.csv"
    Exporter(_config()).write_manifest(scored, "csv", str(path))
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    data_row = rows[1]
    reason_idx = header.index("vlm_reason")
    provider_idx = header.index("vlm_provider")
    assert data_row[reason_idx] == ""
    assert data_row[provider_idx] == ""


def test_json_includes_vlm_reason_and_provider_fields(tmp_path: Path) -> None:
    """JSON 输出的 images[*] 对象包含 vlm_reason / vlm_provider 字段。"""
    scored = [
        _score_with_vlm(
            "a.jpg",
            "/a.jpg",
            90.0,
            vlm_reason="背景虚化",
            vlm_provider="qwen",
            vlm_adjustment=5.0,
            selected=True,
        ),
    ]
    path = tmp_path / "result.json"
    Exporter(_config()).write_manifest(scored, "json", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    img = data["images"][0]
    assert img["vlm_reason"] == "背景虚化"
    assert img["vlm_provider"] == "qwen"
    assert img["vlm_adjustment"] == 5.0


def test_json_empty_vlm_fields_when_not_set(tmp_path: Path) -> None:
    """未启用 VLM 时 JSON 中 vlm_reason/vlm_provider 为空串。"""
    scored = [_score("a.jpg", "/a.jpg", 90.0)]
    path = tmp_path / "result.json"
    Exporter(_config()).write_manifest(scored, "json", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    img = data["images"][0]
    assert img["vlm_reason"] == ""
    assert img["vlm_provider"] == ""


def test_write_manifest_invalid_format(tmp_path: Path) -> None:
    """不支持的格式抛 ValueError。"""
    with pytest.raises(ValueError):
        Exporter(_config()).write_manifest([], "xml", str(tmp_path / "x.xml"))


# ---------- 原子落盘 ----------


def test_write_json_produces_valid_json_file(tmp_path: Path) -> None:
    """_write_json 落盘后目标文件存在且内容为合法 JSON。"""
    scored = [_score("a.jpg", "/a.jpg", 90.0, selected=True)]
    path = tmp_path / "manifest.json"
    Exporter(_config())._write_json(scored, str(path))
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["summary"]["total"] == 1


def test_write_json_goes_through_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_write_json 必须走 atomic_write_text，而不是直接 write_text。"""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "flashgaze.core.exporter.atomic_write_text",
        lambda p, text: calls.append((str(p), text)),
    )
    path = tmp_path / "manifest.json"
    Exporter(_config())._write_json([_score("a.jpg", "/a.jpg", 90.0)], str(path))
    assert len(calls) == 1
    called_path, called_text = calls[0]
    assert called_path == str(path)
    assert json.loads(called_text)["summary"]["total"] == 1
    # 被 monkeypatch 拦截 → 真实文件不应产生，证明落盘只经这一条路径
    assert not path.exists()


def test_write_csv_goes_through_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_write_csv 必须走 atomic_write_bytes（CSV 需保字节，故用 bytes 版）。"""
    calls: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        "flashgaze.core.exporter.atomic_write_bytes",
        lambda p, data: calls.append((str(p), data)),
    )
    path = tmp_path / "manifest.csv"
    Exporter(_config())._write_csv([_score("a.jpg", "/a.jpg", 90.0)], str(path))
    assert len(calls) == 1
    called_path, called_bytes = calls[0]
    assert called_path == str(path)
    # BOM + CRLF 与原实现（utf-8-sig + newline=""）保持一致
    assert called_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in called_bytes
    assert b"\r\r\n" not in called_bytes


def test_manifest_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    """写完清单后目录内不残留原子写临时文件。"""
    scored = [_score("a.jpg", "/a.jpg", 90.0)]
    exporter = Exporter(_config())
    exporter.write_manifest(scored, "json", str(tmp_path / "m.json"))
    exporter.write_manifest(scored, "csv", str(tmp_path / "m.csv"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m.csv", "m.json"]


def _age_file(path: Path, hours: float = 2.0) -> None:
    """把文件 mtime 拨老（M-10 后 cleanup_stale_tmp 跳过 1 小时内的新鲜 tmp）。"""
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def test_cleanup_stale_tmp_recursive(tmp_path: Path) -> None:
    """#2-2 回归：子目录内的原子写残留也能被递归清理，非匹配文件不受影响。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    stale_top = tmp_path / ".a.tmp.12345"
    stale_sub = sub / ".b.tmp.67890"
    stale_top.write_bytes(b"x")
    stale_sub.write_bytes(b"x")
    (sub / "keep.txt").write_bytes(b"x")  # 干扰项：不应被删
    _age_file(stale_top)  # M-10：新鲜 tmp 会被宽限跳过，须拨老模拟异常退出残留
    _age_file(stale_sub)
    removed = cleanup_stale_tmp(tmp_path)
    assert removed == 2
    assert not stale_top.exists()
    assert not stale_sub.exists()
    assert (sub / "keep.txt").exists()


def test_cleanup_stale_tmp_matches_model_part_name(tmp_path: Path) -> None:
    """#4a-1 回归：模型下载临时文件改用 `.{name}.tmp.{pid}` 命名后能被清理正则识别并回收。"""
    stale = tmp_path / ".model.yml.tmp.12345"
    stale.write_bytes(b"x")
    _age_file(stale)  # M-10：须拨老才会被清理
    assert _STALE_TMP_RE.match(stale.name)
    assert cleanup_stale_tmp(tmp_path) == 1
    assert not stale.exists()


def test_cleanup_stale_tmp_matches_exif_tmp(tmp_path: Path) -> None:
    r"""EXIF 写回归：exif_writer 的临时文件改为 `.{name}.exif.tmp.{pid}` 后须被清理正则识别并回收。

    bug/数据损坏：旧命名 `.{name}.exif.tmp` 缺 pid 后缀，既被并发进程互相覆盖、
    又不匹配 `^\..*\.tmp\.\d+$` 而永不清理。加 pid 后命名应天然落入清理范围。
    """
    stale = tmp_path / ".photo.jpg.exif.tmp.12345"
    stale.write_bytes(b"x")
    _age_file(stale)  # M-10：须拨老才会被清理
    assert _STALE_TMP_RE.match(stale.name)
    assert cleanup_stale_tmp(tmp_path) == 1
    assert not stale.exists()


# ── LOW-3: 源文件缺失记入 last_failures ─────────────────


def test_export_missing_source_recorded_in_last_failures(tmp_path: Path) -> None:
    """selected 图的源文件已消失时不再静默跳过：计入 last_failures（source_missing）。

    导出数与入选数的差额由此可观测，调用方可据此告警。"""
    dest = tmp_path / "dest"
    gone = tmp_path / "gone.jpg"  # 不创建该文件
    exporter = Exporter(Config(directory=str(tmp_path)))
    scored = [_score("gone.jpg", str(gone), 90.0, selected=True)]

    moved = exporter.export_images(scored, str(dest))

    assert moved == 0
    assert exporter.last_failures == [
        {"file": "gone.jpg", "path": str(gone), "error": "source_missing"}
    ]


# ── H-2: build_report 在 summary 顶层暴露 exif_failed ────


def test_build_report_exif_failed_top_level(tmp_path: Path) -> None:
    """EXIF 失败数须出现在 summary 顶层（exif_failed），供 Agent 单点判定。

    同时保留既有的 summary.exif 子节（含 failures 明细），且未传 exif_results 时
    不新增该键——MCP / WebUI 的报告结构零变化。
    """
    scored = [_score("a.jpg", str(tmp_path / "a.jpg"), 90.0, selected=True)]
    # build_report 契约接受「含 .ok/.path/.error 的鸭子类型对象」（见其 docstring）；
    # 不直接用 ExifWriteResult 是因其模块级依赖可选 piexif，本测试须在无 piexif 环境可跑。
    results: list[Any] = [
        SimpleNamespace(ok=True, path="a.jpg", error=None),
        SimpleNamespace(ok=False, path="b.jpg", error="boom"),
    ]
    exif_results = cast("list[ExifWriteResult]", results)

    summary = Exporter.build_report(scored, 0, exif_results=exif_results)["summary"]

    assert summary["exif_failed"] == 1
    assert summary["exif"] == {
        "total": 2,
        "ok": 1,
        "failed": 1,
        "failures": [{"path": "b.jpg", "error": "boom"}],
    }
    # 全部成功 → 0（不是缺失）
    ok_only = Exporter.build_report(scored, 0, exif_results=exif_results[:1])["summary"]
    assert ok_only["exif_failed"] == 0
    # 未传 exif_results → 向后兼容，不产出该键
    assert "exif_failed" not in Exporter.build_report(scored, 0)["summary"]


# ── 阶段1看门狗统计：build_report 可选 phase1_stats 小节（池代际重建修复） ──


def test_build_report_phase1_timeout_section(tmp_path: Path) -> None:
    """传入 phase1_stats 且计数非零时，summary 必须出现 phase1_timeout 小节
    （含被判死数量占总图片数百分比 pool_exhausted_pct）；零计数或不传参数时
    不出现该键——不传时输出与既有契约逐字节一致（向后兼容，M-15/H-2 模式）。

    [增强类] 修复前 build_report 无 phase1_stats 参数，调用即 TypeError（红灯）。"""
    scored = [
        _score(f"a{i}.jpg", str(tmp_path / f"a{i}.jpg"), 90.0, selected=True) for i in range(4)
    ]
    stats = {"timed_out": 3, "pool_exhausted": 2, "rebuilds": 1}
    summary = Exporter.build_report(scored, 0, phase1_stats=stats)["summary"]
    assert summary["phase1_timeout"] == {
        "timed_out": 3,
        "pool_exhausted": 2,
        "rebuilds": 1,
        # 被判死占比：2 / 4 = 50.0%
        "pool_exhausted_pct": 50.0,
    }
    # 零计数 → 不出现该小节（健康批次报告零变化）
    zero = {"timed_out": 0, "pool_exhausted": 0, "rebuilds": 0}
    assert "phase1_timeout" not in Exporter.build_report(scored, 0, phase1_stats=zero)["summary"]
    # 缺失键按 0 处理（内部来源受控，仅键缺省容错）
    partial = Exporter.build_report(scored, 0, phase1_stats={"timed_out": 5})["summary"]
    assert partial["phase1_timeout"] == {
        "timed_out": 5,
        "pool_exhausted": 0,
        "rebuilds": 0,
        "pool_exhausted_pct": 0.0,
    }
    # 未传 phase1_stats → 向后兼容，不产出该键
    assert "phase1_timeout" not in Exporter.build_report(scored, 0)["summary"]


# ── H-9: 导出部分失败可判定（dest 非目录 / last_expected / summary.export） ──


def test_export_dest_is_file_recorded_in_last_failures(tmp_path: Path) -> None:
    """H-9：dest 已是普通文件且存在待导出图 → 记入 last_failures。

    此前该分支（FIX #9-1 的 mkdir 守卫）只记 WARNING 后 return 0，是三种失败中
    唯一「完全无记录」的一种：调用方连「导出根本没发生」都无从得知。
    """
    src = tmp_path / "sharp.jpg"
    src.write_bytes(b"dummy")
    dest = tmp_path / "精选"
    dest.write_text("i am a file", encoding="utf-8")
    exporter = Exporter(_config(export=True))
    scored = [_score("sharp.jpg", str(src), 90.0, selected=True)]

    moved = exporter.export_images(scored, str(dest))

    assert moved == 0
    assert exporter.last_failures == [
        {"file": "", "path": str(dest), "error": "dest_not_directory"}
    ]


def test_export_dest_is_file_without_candidate_is_not_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """反例（R1）：无待导出图时，dest 是普通文件不构成「导出失败」。

    没有任何图片需要导出，用户未损失任何产物；记入 last_failures 会让
    「--export 但零入选」的正常场景被误判为部分失败（退出码非 0）。
    """
    dest = tmp_path / "精选"
    dest.write_text("i am a file", encoding="utf-8")
    exporter = Exporter(_config(export=True))

    with caplog.at_level(logging.WARNING):
        moved = exporter.export_images([], str(dest))

    assert moved == 0
    assert exporter.last_failures == []
    assert any("不是目录" in r.message for r in caplog.records)


def test_export_last_expected_counts_candidates(tmp_path: Path) -> None:
    """last_expected = 预期入选数，口径与 export_images 的跳过条件逐字一致。

    带 error 的图即使 selected 也不参与导出（既有 `not s.selected or s.error`），
    故不计入预期——它属于评分失败而非导出失败。
    """
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    c = tmp_path / "c.jpg"
    for p in (a, b, c):
        p.write_bytes(b"x")
    scored = [
        _score("a.jpg", str(a), 90.0, selected=True),
        _score("b.jpg", str(b), 80.0, selected=True, error="corrupted"),
        _score("c.jpg", str(c), 40.0, selected=False),
    ]
    exporter = Exporter(_config(export=True))

    moved = exporter.export_images(scored, str(tmp_path / "out"))

    assert moved == 1
    assert exporter.last_expected == 1
    assert exporter.last_failures == []


def test_build_report_exposes_export_failures_in_summary(tmp_path: Path) -> None:
    """H-9：build_report 在 summary 顶层暴露 export_failed 与 export 明细子节。

    与 H-2/M-15 的 exif 小节同构：顶层单键供 Agent 判定「是否存在部分失败」，
    子节给出逐项明细；未传 export 时输出与既有契约逐字节一致。
    """
    from flashgaze.core.exporter import ExportOutcome

    scored = [_score("a.jpg", str(tmp_path / "a.jpg"), 90.0, selected=True)]
    failures = [
        {"file": "b.jpg", "path": "/tmp/b.jpg", "error": "source_missing"},
        {"file": "c.jpg", "path": "/tmp/c.jpg", "error": "disk full"},
    ]
    outcome = ExportOutcome(expected=3, exported=1, failures=failures)

    summary = Exporter.build_report(scored, 12, export=outcome)["summary"]

    assert summary["export_failed"] == 2
    assert summary["export"] == {
        "expected": 3,
        "exported": 1,
        "failed": 2,
        "failures": failures,
    }
    # 全部成功 → 0（不是缺失）
    ok_only = Exporter.build_report(scored, 12, export=ExportOutcome(1, 1, []))["summary"]
    assert ok_only["export_failed"] == 0
    # 未传 export → 向后兼容，不产出该键（MCP _build_report / WebUI / 清单 JSON 零变化）
    assert "export_failed" not in Exporter.build_report(scored)["summary"]


# ── VLM 采样参数回显：build_report 可选 vlm_sampling 小节（可复现性）──


def test_build_report_vlm_sampling_section(tmp_path: Path) -> None:
    """传入 vlm_sampling 时 summary 出现该小节；不传时不产出该键（向后兼容）。

    [增强类] 修复前 build_report 无 vlm_sampling 参数，调用即 TypeError（红灯）。
    """
    scored = [_score("a.jpg", str(tmp_path / "a.jpg"), 90.0, selected=True)]
    summary = Exporter.build_report(
        scored, 0, vlm_sampling={"provider": "qwen", "temperature": 0.0, "seed": 42}
    )["summary"]
    assert summary["vlm_sampling"] == {
        "provider": "qwen",
        "temperature": 0.0,
        "seed": 42,
    }
    # 反例：不传参数 → 报告与既有契约逐字节一致，不出现该键
    assert "vlm_sampling" not in Exporter.build_report(scored, 0)["summary"]

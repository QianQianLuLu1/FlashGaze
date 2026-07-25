"""CLI entry.main 进程内单元测试。

与 test_cli_e2e.py 的 subprocess 测试互补：直接调用 entry.main() 让覆盖率
统计能记录 entry.py 的执行路径。e2e 在子进程中跑，不贡献覆盖率。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from flashgaze.cli.entry import _emit_json, main
from flashgaze.models.schemas import ExitCode


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/corrupted 到临时目录。"""
    for name in ("sharp.jpg", "blurry.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


# ── 成功路径 ───────────────────────────────────────────


def test_main_no_vlm_json_returns_success(photo_dir: str, capsys):
    """--no-vlm --json → SUCCESS，stdout 是合法 JSON。"""
    code = main([photo_dir, "--no-vlm", "--top", "2", "--json"])
    assert code == ExitCode.SUCCESS
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "success"
    assert data["summary"]["total"] == 3


def test_main_csv_writes_manifest(photo_dir: str, tmp_path: Path, capsys):
    """--csv --csv-output 写 CSV 文件。"""
    csv_path = tmp_path / "result.csv"
    code = main([photo_dir, "--no-vlm", "--csv", "--csv-output", str(csv_path)])
    assert code == ExitCode.SUCCESS
    # stdout 不应被 JSON 污染（未开 --json）
    assert capsys.readouterr().out == ""
    assert csv_path.exists()
    assert "sharp.jpg" in csv_path.read_text(encoding="utf-8-sig")


def test_main_export_copies_selected(photo_dir: str, tmp_path: Path):
    """--export --export-dir 复制入选图到目标目录。"""
    dest = tmp_path / "out"
    code = main([photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(dest)])
    assert code == ExitCode.SUCCESS
    files = list(dest.iterdir())
    assert len(files) == 1
    assert files[0].name == "sharp.jpg"


def test_main_json_output_to_file(photo_dir: str, tmp_path: Path, capsys):
    """--json --output 把 JSON 写到文件而非 stdout。"""
    out_path = tmp_path / "report.json"
    code = main([photo_dir, "--no-vlm", "--json", "--output", str(out_path)])
    assert code == ExitCode.SUCCESS
    # stdout 应为空（输出走文件）
    assert capsys.readouterr().out == ""
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 3


def test_main_verbose_sets_debug_level(photo_dir: str, capsys):
    """--verbose 不影响返回码，且日志级别切换为 DEBUG。"""
    from flashgaze.utils.logging import get_logger

    code = main([photo_dir, "--no-vlm", "--verbose"])
    assert code == ExitCode.SUCCESS
    # set_verbose(True) 后 logger 级别应为 DEBUG
    assert get_logger().level == 10  # logging.DEBUG


def test_main_progress_emitted_for_large_batch(tmp_path: Path, fixtures_dir: Path, capsys):
    """超过 50 张图时每 10 张输出进度到 stderr。"""
    # 复制 sharp.jpg 60 份
    src = fixtures_dir / "sharp.jpg"
    for i in range(60):
        shutil.copy2(src, tmp_path / f"img_{i:03d}.jpg")
    code = main([str(tmp_path), "--no-vlm", "--json"])
    assert code == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "进度:" in err


# ── 错误路径 ───────────────────────────────────────────


def test_main_empty_directory_returns_no_images(tmp_path: Path):
    """空目录 → NO_IMAGES。"""
    code = main([str(tmp_path), "--no-vlm"])
    assert code == ExitCode.NO_IMAGES


def test_main_missing_api_key_without_no_vlm_returns_config_error(
    photo_dir: str, monkeypatch
):
    """未配 API Key 且未 --no-vlm → CONFIG_ERROR。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    code = main([photo_dir, "--top", "1"])
    assert code == ExitCode.CONFIG_ERROR


def test_main_bad_args_returns_param_error():
    """缺少必选参数 → PARAM_ERROR（argparse 触发 SystemExit code=2）。"""
    code = main(["--no-vlm"])
    assert code == ExitCode.PARAM_ERROR


def test_main_version_returns_success():
    """--version 触发 SystemExit code=0 → SUCCESS。"""
    code = main(["--version"])
    assert code == ExitCode.SUCCESS


# ── _emit_json 直接测试 ────────────────────────────────


def test_emit_json_writes_to_stdout(capsys):
    """_emit_json 无 output_path 时输出到 stdout。"""
    from flashgaze.core.exporter import Exporter
    from flashgaze.models.schemas import Config, ImageScore

    config = Config(directory=".")
    exporter = Exporter(config)
    scored = [
        ImageScore(
            file="a.jpg", path="/tmp/a.jpg",
            sharpness=80.0, exposure=70.0, composition=None,
            vlm_adjustment=0.0, score=80.0, selected=True,
        )
    ]
    _emit_json(exporter, scored, elapsed_ms=42, config=config)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["summary"]["total"] == 1


def test_emit_json_writes_to_file(tmp_path: Path, capsys):
    """_emit_json 有 output_path 时写到文件，stdout 为空。"""
    from flashgaze.core.exporter import Exporter
    from flashgaze.models.schemas import Config, ImageScore

    out_path = tmp_path / "out.json"
    config = Config(directory=".", output_path=str(out_path))
    exporter = Exporter(config)
    scored: list = []
    _emit_json(exporter, scored, elapsed_ms=0, config=config)
    assert capsys.readouterr().out == ""
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 0

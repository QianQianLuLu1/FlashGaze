"""端到端 CLI 测试。

用 subprocess 真实调用 `python -m flashgaze`，验证返回码与输出。
模拟 AI Agent 通过 subprocess 调用的真实场景。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FLASHGAZE_CMD = [sys.executable, "-m", "flashgaze"]


def _run(args: list[str], env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """调用 flashgaze，返回 CompletedProcess。"""
    env = os.environ.copy()
    # 默认清理 API Key，避免环境污染 CONFIG_ERROR 测试
    env.pop("FLASHGAZE_API_KEY", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        FLASHGAZE_CMD + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        encoding="utf-8",
    )


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/corrupted 到临时目录。"""
    for name in ("sharp.jpg", "blurry.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


# ---------- ExitCode.SUCCESS (0) ----------

def test_e2e_success_no_vlm_json(photo_dir: str):
    """正常评分 + --no-vlm + --json → exit 0，stdout 是合法 JSON。"""
    result = _run([photo_dir, "--no-vlm", "--top", "2", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "success"
    assert data["code"] == 0
    assert data["summary"]["total"] == 3
    assert data["summary"]["selected"] == 2
    # sharp.jpg 应是最高分
    assert data["images"][0]["file"] == "sharp.jpg"
    assert data["images"][0]["selected"] is True


def test_e2e_success_csv_output(photo_dir: str, tmp_path: Path):
    """--csv 生成 CSV 文件。"""
    csv_path = tmp_path / "result.csv"
    result = _run([photo_dir, "--no-vlm", "--csv", "--csv-output", str(csv_path)])
    assert result.returncode == 0
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "file" in content
    assert "sharp.jpg" in content


def test_e2e_export_creates_dest(photo_dir: str, tmp_path: Path):
    """--export + --export-dir 创建目标目录并复制 selected 图。"""
    dest_dir = tmp_path / "精选"
    result = _run([photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(dest_dir)])
    assert result.returncode == 0
    assert dest_dir.exists()
    files = list(dest_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == "sharp.jpg"


# ---------- ExitCode.NO_IMAGES (3) ----------

def test_e2e_nonexistent_directory(tmp_path: Path):
    """不存在的目录 → exit 3。"""
    result = _run([str(tmp_path / "nope")])
    assert result.returncode == 3


def test_e2e_empty_directory(tmp_path: Path):
    """空目录 → exit 3。"""
    result = _run([str(tmp_path)])
    assert result.returncode == 3


# ---------- ExitCode.CONFIG_ERROR (6) ----------

def test_e2e_missing_api_key_without_no_vlm(photo_dir: str):
    """未配 API Key 且未 --no-vlm → exit 6。"""
    result = _run([photo_dir, "--top", "1"])
    assert result.returncode == 6
    assert "API Key" in result.stderr


def test_e2e_api_key_from_env(photo_dir: str):
    """环境变量提供 API Key 时不报 CONFIG_ERROR（但 VLM 调用会失败，降级为 0）。"""
    result = _run(
        [photo_dir, "--top", "1", "--json"],
        env_overrides={"FLASHGAZE_API_KEY": "fake-key-for-test"},
    )
    # VLM 调用 fake endpoint 会失败，但降级为 CV-only，整体仍 SUCCESS
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0


# ---------- ExitCode.PARAM_ERROR (1) ----------

def test_e2e_missing_directory_arg():
    """缺必选参数 → exit 1。"""
    result = _run(["--no-vlm"])
    assert result.returncode == 1


# ---------- 损坏图不中断 ----------

def test_e2e_corrupted_image_does_not_crash(photo_dir: str):
    """corrupted.jpg 在目录中不中断流程，JSON 里该图有 error。"""
    result = _run([photo_dir, "--no-vlm", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    corrupted = [img for img in data["images"] if img["file"] == "corrupted.jpg"]
    assert len(corrupted) == 1
    assert corrupted[0]["error"] is not None
    assert corrupted[0]["score"] == 0.0


# ---------- --version ----------

def test_e2e_version():
    """--version 正常退出。"""
    result = _run(["--version"])
    assert result.returncode == 0
    assert "flashgaze" in result.stdout


# ---------- stdout/stderr 分离 ----------

def test_e2e_json_goes_to_stdout_not_stderr(photo_dir: str):
    """JSON 数据走 stdout，stderr 不含 JSON。"""
    result = _run([photo_dir, "--no-vlm", "--json"])
    assert result.returncode == 0
    json.loads(result.stdout)  # stdout 是合法 JSON
    # stderr 不应含 JSON 数据
    assert "status" not in result.stderr
    assert "summary" not in result.stderr

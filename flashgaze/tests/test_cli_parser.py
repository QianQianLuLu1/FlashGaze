"""CLIParser 单元测试。

验证参数解析与配置优先级：CLI > env > file > default。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashgaze.cli.parser import CLIParser
from flashgaze.models.schemas import ExitCode


def _parse(argv: list[str]):
    return CLIParser().parse(argv)


# ---------- 基础参数 ----------

def test_parse_basic_directory():
    cfg = _parse(["./photos"])
    assert cfg.directory == "./photos"
    assert cfg.top == 30  # 默认
    assert cfg.no_vlm is False
    assert cfg.export is False


def test_parse_top_override():
    cfg = _parse(["./photos", "--top", "50"])
    assert cfg.top == 50


def test_parse_threshold():
    cfg = _parse(["./photos", "--threshold", "75.5"])
    assert cfg.threshold == 75.5


def test_parse_export_and_move():
    cfg = _parse(["./photos", "--export", "--move"])
    assert cfg.export is True
    assert cfg.move is True


def test_parse_json_csv_flags():
    cfg = _parse(["./photos", "--json", "--csv"])
    assert cfg.output_json is True
    assert cfg.output_csv is True


def test_parse_no_vlm():
    cfg = _parse(["./photos", "--no-vlm"])
    assert cfg.no_vlm is True


def test_parse_enable_composition():
    cfg = _parse(["./photos", "--enable-composition"])
    assert cfg.enable_composition is True


def test_parse_output_path():
    cfg = _parse(["./photos", "--output", "report.json"])
    assert cfg.output_path == "report.json"


def test_parse_workers():
    cfg = _parse(["./photos", "--workers", "8"])
    assert cfg.workers == 8


# ---------- 配置优先级 ----------

def test_priority_cli_over_env(monkeypatch):
    """CLI 参数优先于环境变量。"""
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-key")
    monkeypatch.setenv("FLASHGAZE_MODEL", "env-model")
    cfg = _parse(["./photos", "--api-key", "cli-key", "--model", "cli-model"])
    assert cfg.api_key == "cli-key"
    assert cfg.model == "cli-model"


def test_priority_env_over_file(monkeypatch, tmp_path: Path):
    """环境变量优先于配置文件。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps({"api_key": "file-key", "model": "file-model"}), encoding="utf-8"
    )
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-key")
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.api_key == "env-key"
    assert cfg.model == "file-model"  # env 未设置 model，回退到 file


def test_priority_file_over_default(tmp_path: Path):
    """配置文件优先于默认值。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps({
            "api_base": "https://custom.api/v1",
            "model": "custom-model",
            "workers": 12,
        }),
        encoding="utf-8",
    )
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.api_base == "https://custom.api/v1"
    assert cfg.model == "custom-model"
    assert cfg.workers == 12


def test_env_api_key_used_when_no_cli(monkeypatch):
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-only-key")
    cfg = _parse(["./photos"])
    assert cfg.api_key == "env-only-key"


def test_defaults_when_nothing_provided(monkeypatch):
    """无任何配置时使用 defaults.py 的默认值。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    monkeypatch.delenv("FLASHGAZE_API_BASE", raising=False)
    monkeypatch.delenv("FLASHGAZE_MODEL", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen-vl-max"
    assert cfg.workers == 4
    assert cfg.timeout_sec == 30
    assert cfg.api_key is None


def test_config_file_not_exist_uses_defaults(tmp_path: Path):
    """配置文件不存在时不报错，用默认值。"""
    cfg = _parse(["./photos", "--config-file", str(tmp_path / "nope.json")])
    assert cfg.model == "qwen-vl-max"


def test_config_file_corrupted_uses_defaults(tmp_path: Path):
    """配置文件格式错误时用默认值，不抛异常。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    cfg = _parse(["./photos", "--config-file", str(bad)])
    assert cfg.model == "qwen-vl-max"


def test_weights_from_config_file(tmp_path: Path):
    """权重从配置文件加载。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps({"weights": {"sharpness": 0.7, "exposure": 0.3}}),
        encoding="utf-8",
    )
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.weights == {"sharpness": 0.7, "exposure": 0.3}


# ---------- 参数错误 ----------

def test_missing_directory_returns_param_error(capsys):
    """缺必选参数 directory 时返回 PARAM_ERROR。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse([])
    # argparse 缺必选参数时 exit code=2
    assert exc_info.value.code == 2


def test_version_flag_exits_zero():
    """--version 正常退出（code=0）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["--version"])
    assert exc_info.value.code == 0

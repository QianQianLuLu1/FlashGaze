"""CLIParser 单元测试。

验证参数解析与配置优先级：CLI > env > file > default。
"""

from __future__ import annotations

import json
import os
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


def test_parse_no_downscale_default_false():
    """默认 no_downscale=False，即启用降采样。"""
    cfg = _parse(["./photos"])
    assert cfg.no_downscale is False


def test_parse_no_downscale_flag():
    """--no-downscale 被正确解析为 True。"""
    cfg = _parse(["./photos", "--no-downscale"])
    assert cfg.no_downscale is True


def test_parse_enable_composition():
    cfg = _parse(["./photos", "--enable-composition"])
    assert cfg.enable_composition is True


def test_parse_output_path():
    cfg = _parse(["./photos", "--output", "report.json"])
    assert cfg.output_path == "report.json"


def test_parse_workers(monkeypatch):
    # workers 会被钳制到 min(cpu_count, 16)；钉住核数，本用例才只检验解析本身而非运行机器
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    cfg = _parse(["./photos", "--workers", "8"])
    assert cfg.workers == 8


# ---------- VLM 扩展：--vlm-provider / --scene 参数（M3/M7）----------

def test_parse_vlm_provider_default_qwen(monkeypatch):
    """不传 --vlm-provider 时默认 qwen。"""
    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.vlm_provider == "qwen"


def test_parse_vlm_provider_openai():
    """--vlm-provider openai 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "openai"])
    assert cfg.vlm_provider == "openai"


def test_parse_vlm_provider_anthropic():
    """--vlm-provider anthropic 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "anthropic"])
    assert cfg.vlm_provider == "anthropic"


def test_parse_vlm_provider_ollama():
    """--vlm-provider ollama 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "ollama"])
    assert cfg.vlm_provider == "ollama"


def test_parse_vlm_provider_invalid_choice_rejected(capsys):
    """--vlm-provider 不在 choices 中时 argparse 报错（exit code=2）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["./photos", "--vlm-provider", "claude"])
    assert exc_info.value.code == 2


def test_parse_scene_default_auto(monkeypatch):
    """不传 --scene 时默认 auto。"""
    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.scene == "auto"


def test_parse_scene_portrait():
    """--scene portrait 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "portrait"])
    assert cfg.scene == "portrait"


def test_parse_scene_landscape():
    """--scene landscape 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "landscape"])
    assert cfg.scene == "landscape"


def test_parse_scene_still_life():
    """--scene still_life 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "still_life"])
    assert cfg.scene == "still_life"


def test_parse_scene_invalid_choice_rejected(capsys):
    """--scene 不在 choices 中时 argparse 报错（exit code=2）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["./photos", "--scene", "macro"])
    assert exc_info.value.code == 2


def test_parse_vlm_provider_and_scene_combined():
    """同时传 --vlm-provider 与 --scene。"""
    cfg = _parse([
        "./photos", "--vlm-provider", "openai", "--scene", "portrait",
    ])
    assert cfg.vlm_provider == "openai"
    assert cfg.scene == "portrait"


def test_priority_cli_vlm_provider_over_env(monkeypatch):
    """CLI --vlm-provider 优先于环境变量。"""
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "anthropic")
    cfg = _parse(["./photos", "--vlm-provider", "openai"])
    assert cfg.vlm_provider == "openai"


def test_priority_env_vlm_provider_over_default(monkeypatch):
    """环境变量 FLASHGAZE_VLM_PROVIDER 优先于默认值。"""
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "ollama")
    cfg = _parse(["./photos"])
    assert cfg.vlm_provider == "ollama"


def test_priority_env_scene_over_default(monkeypatch):
    """环境变量 FLASHGAZE_SCENE 优先于默认值。"""
    monkeypatch.setenv("FLASHGAZE_SCENE", "landscape")
    cfg = _parse(["./photos"])
    assert cfg.scene == "landscape"


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


def test_priority_file_over_default(monkeypatch, tmp_path: Path):
    """配置文件优先于默认值。"""
    # 同上：钉住核数，否则 workers=12 在少核机器上会被钳制，掩盖真正要验的优先级语义
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
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


def test_weights_cli_with_composition():
    """--weights 含 composition 时三键归一化（F-05）。"""
    cfg = _parse([
        "./photos",
        "--weights", '{"sharpness": 0.5, "exposure": 0.3, "composition": 0.2}',
    ])
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.3
    assert cfg.weights["composition"] == 0.2


def test_weights_cli_composition_normalized():
    """--weights 非归一化输入时正确归一化（F-05）。"""
    cfg = _parse([
        "./photos",
        "--weights", '{"sharpness": 3, "exposure": 1, "composition": 1}',
    ])
    assert cfg.weights["sharpness"] == 0.6  # 3/5
    assert cfg.weights["exposure"] == 0.2   # 1/5
    assert cfg.weights["composition"] == 0.2  # 1/5


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

"""utils/config.py 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from flashgaze.utils.config import default_config_dict, load_config_file, merge_env
from flashgaze.defaults import DEFAULT_API_BASE, DEFAULT_MODEL, DEFAULT_WORKERS


# ---------- load_config_file ----------

def test_load_config_file_valid(tmp_path: Path):
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"api_key": "k", "model": "m", "workers": 8}),
        encoding="utf-8",
    )
    cfg = load_config_file(cfg_file)
    assert cfg["api_key"] == "k"
    assert cfg["model"] == "m"
    assert cfg["workers"] == 8


def test_load_config_file_not_exist(tmp_path: Path):
    """文件不存在返回空 dict。"""
    assert load_config_file(tmp_path / "nope.json") == {}


def test_load_config_file_corrupted(tmp_path: Path):
    """格式错误返回空 dict。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    assert load_config_file(bad) == {}


def test_load_config_file_empty(tmp_path: Path):
    """空文件返回空 dict。"""
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert load_config_file(empty) == {}


# ---------- merge_env ----------

def test_merge_env_reads_all_vars(monkeypatch):
    """所有环境变量被正确读取。"""
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-key")
    monkeypatch.setenv("FLASHGAZE_API_BASE", "https://env.api/v1")
    monkeypatch.setenv("FLASHGAZE_MODEL", "env-model")
    monkeypatch.setenv("FLASHGAZE_TIMEOUT", "60")
    monkeypatch.setenv("FLASHGAZE_WORKERS", "16")
    cfg = merge_env()
    assert cfg["api_key"] == "env-key"
    assert cfg["api_base"] == "https://env.api/v1"
    assert cfg["model"] == "env-model"
    assert cfg["timeout_sec"] == 60
    assert cfg["workers"] == 16


def test_merge_env_empty_when_no_vars(monkeypatch):
    """无环境变量时返回空 dict。"""
    for var in ("FLASHGAZE_API_KEY", "FLASHGAZE_API_BASE", "FLASHGAZE_MODEL",
                "FLASHGAZE_TIMEOUT", "FLASHGAZE_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    assert merge_env() == {}


def test_merge_env_invalid_timeout_ignored(monkeypatch):
    """非数字的 TIMEOUT 被忽略。"""
    monkeypatch.setenv("FLASHGAZE_TIMEOUT", "not-a-number")
    cfg = merge_env()
    assert "timeout_sec" not in cfg


def test_merge_env_invalid_workers_ignored(monkeypatch):
    """非数字的 WORKERS 被忽略。"""
    monkeypatch.setenv("FLASHGAZE_WORKERS", "abc")
    cfg = merge_env()
    assert "workers" not in cfg


# ---------- default_config_dict ----------

def test_default_config_dict_values():
    """默认配置与 defaults.py 一致。"""
    cfg = default_config_dict()
    assert cfg["api_base"] == DEFAULT_API_BASE
    assert cfg["model"] == DEFAULT_MODEL
    assert cfg["workers"] == DEFAULT_WORKERS
    assert "weights" in cfg
    assert "vlm_max_adjustment" in cfg

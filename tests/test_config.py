"""utils/config.py 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashgaze.utils.config import default_config_dict, load_config_file, merge_env
from flashgaze.defaults import DEFAULT_API_BASE, DEFAULT_MODEL, DEFAULT_WEIGHTS, DEFAULT_WORKERS


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


# ---------- C-07: DEFAULT_WEIGHTS 不可变性 ----------

def test_default_weights_is_immutable():
    """DEFAULT_WEIGHTS 是 MappingProxyType，原地修改应抛 TypeError。"""
    with pytest.raises(TypeError):
        DEFAULT_WEIGHTS["sharpness"] = 0.9  # type: ignore[index]


def test_default_weights_read_compatible():
    """MappingProxyType 读取接口与 dict 兼容。"""
    assert DEFAULT_WEIGHTS["sharpness"] == 0.5
    assert DEFAULT_WEIGHTS.get("exposure") == 0.5
    assert dict(DEFAULT_WEIGHTS) == {"sharpness": 0.5, "exposure": 0.5}


# ---------- F-05: weights composition key ----------

def test_merge_env_weights_with_composition(monkeypatch):
    """FLASHGAZE_WEIGHTS 含 composition 时三键归一化。"""
    monkeypatch.setenv(
        "FLASHGAZE_WEIGHTS",
        json.dumps({"sharpness": 0.5, "exposure": 0.3, "composition": 0.2}),
    )
    cfg = merge_env()
    w = cfg["weights"]
    assert w["sharpness"] == 0.5  # 0.5/1.0
    assert w["exposure"] == 0.3   # 0.3/1.0
    assert w["composition"] == 0.2  # 0.2/1.0


def test_merge_env_weights_without_composition(monkeypatch):
    """FLASHGAZE_WEIGHTS 不含 composition 时仍为两键（向后兼容）。"""
    monkeypatch.setenv(
        "FLASHGAZE_WEIGHTS",
        json.dumps({"sharpness": 0.7, "exposure": 0.3}),
    )
    cfg = merge_env()
    w = cfg["weights"]
    assert w["sharpness"] == 0.7
    assert w["exposure"] == 0.3
    assert "composition" not in w


def test_merge_env_weights_composition_normalized(monkeypatch):
    """composition 权重非归一化输入时正确归一化。"""
    monkeypatch.setenv(
        "FLASHGAZE_WEIGHTS",
        json.dumps({"sharpness": 2, "exposure": 2, "composition": 1}),
    )
    cfg = merge_env()
    w = cfg["weights"]
    assert w["sharpness"] == 0.4  # 2/5
    assert w["exposure"] == 0.4   # 2/5
    assert w["composition"] == 0.2  # 1/5


# ---------- VLM 语言环境变量 ----------

def test_merge_env_reads_vlm_lang(monkeypatch):
    """FLASHGAZE_VLM_LANG=en 被正确读取。"""
    monkeypatch.setenv("FLASHGAZE_VLM_LANG", "en")
    cfg = merge_env()
    assert cfg.get("vlm_lang") == "en"


def test_merge_env_reads_vlm_lang_case_insensitive(monkeypatch):
    """FLASHGAZE_VLM_LANG 大小写不敏感（EN → en）。"""
    monkeypatch.setenv("FLASHGAZE_VLM_LANG", "EN")
    cfg = merge_env()
    assert cfg.get("vlm_lang") == "en"


def test_merge_env_ignores_invalid_vlm_lang(monkeypatch):
    """非法 FLASHGAZE_VLM_LANG 被静默忽略，不写入 cfg。"""
    monkeypatch.setenv("FLASHGAZE_VLM_LANG", "fr")
    cfg = merge_env()
    assert "vlm_lang" not in cfg  # 非法值被静默忽略


def test_default_config_dict_includes_vlm_lang():
    """default_config_dict 包含 vlm_lang 默认值。"""
    cfg = default_config_dict()
    assert cfg["vlm_lang"] == "zh"

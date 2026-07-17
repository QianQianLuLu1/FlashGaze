"""配置加载工具。

优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值（defaults.py）。
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Any, Optional

from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_VLM_MAX_ADJUSTMENT,
    DEFAULT_WEIGHTS,
    DEFAULT_WORKERS,
    ENV_API_BASE,
    ENV_API_KEY,
    ENV_MAX_RETRIES,
    ENV_MODEL,
    ENV_TIMEOUT,
    ENV_VLM_MAX_ADJUSTMENT,
    ENV_WEIGHTS,
    ENV_WORKERS,
)
from flashgaze.models.schemas import Config


def load_config_file(path: str | Path) -> dict[str, Any]:
    """加载 JSON 配置文件。文件不存在或格式错误返回空 dict（不抛异常）。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def merge_env() -> dict[str, Any]:
    """从环境变量读取配置。未设置的字段不包含在返回 dict 中。非法值静默忽略。"""
    cfg: dict[str, Any] = {}
    if os.environ.get(ENV_API_KEY):
        cfg["api_key"] = os.environ[ENV_API_KEY]
    if os.environ.get(ENV_API_BASE):
        cfg["api_base"] = os.environ[ENV_API_BASE]
    if os.environ.get(ENV_MODEL):
        cfg["model"] = os.environ[ENV_MODEL]
    if os.environ.get(ENV_TIMEOUT):
        try:
            cfg["timeout_sec"] = int(os.environ[ENV_TIMEOUT])
        except ValueError:
            pass
    if os.environ.get(ENV_WORKERS):
        try:
            cfg["workers"] = int(os.environ[ENV_WORKERS])
        except ValueError:
            pass
    if os.environ.get(ENV_MAX_RETRIES):
        try:
            cfg["max_retries"] = int(os.environ[ENV_MAX_RETRIES])
        except ValueError:
            pass
    if os.environ.get(ENV_VLM_MAX_ADJUSTMENT):
        try:
            cfg["vlm_max_adjustment"] = float(os.environ[ENV_VLM_MAX_ADJUSTMENT])
        except ValueError:
            pass
    if os.environ.get(ENV_WEIGHTS):
        try:
            raw = json.loads(os.environ[ENV_WEIGHTS])
            if isinstance(raw, dict) and "sharpness" in raw and "exposure" in raw:
                s = float(raw["sharpness"])
                e = float(raw["exposure"])
                # F-05：composition 为可选 key，存在时一并归一化
                c = float(raw["composition"]) if "composition" in raw else 0.0
                total = s + e + c
                if total > 0:
                    weights = {"sharpness": s / total, "exposure": e / total}
                    if "composition" in raw:
                        weights["composition"] = c / total
                    cfg["weights"] = weights
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return cfg


def default_config_dict() -> dict[str, Any]:
    """返回 defaults.py 中的默认配置 dict。"""
    return {
        "api_base": DEFAULT_API_BASE,
        "model": DEFAULT_MODEL,
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "max_retries": DEFAULT_MAX_RETRIES,
        "workers": DEFAULT_WORKERS,
        "weights": DEFAULT_WEIGHTS,
        "vlm_max_adjustment": DEFAULT_VLM_MAX_ADJUSTMENT,
    }


# Config dataclass 合法字段名集合（构造时过滤非法 key，避免 TypeError）
_CONFIG_FIELD_NAMES: set[str] = {f.name for f in fields(Config)}


def build_config(
    directory: str,
    file_cfg: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> Config:
    """装配 Config。优先级：overrides > env > file > default。

    CLI 与 MCP 共用此函数，消除两处重复的 env 读取 + 默认值填充逻辑。
    overrides 中值为 None 的键不参与覆盖（保留下层值）。
    """
    defaults = default_config_dict()
    env = merge_env()
    file_cfg = file_cfg or {}

    # 三层基础合并：default < file < env
    base: dict[str, Any] = {**defaults, **file_cfg, **env}
    # overrides 覆盖（仅非 None 值）
    for k, v in overrides.items():
        if v is not None:
            base[k] = v

    # 过滤掉非 Config 字段，避免构造报错
    valid = _CONFIG_FIELD_NAMES
    kwargs = {k: v for k, v in base.items() if k in valid and k != "directory"}
    return Config(directory=directory, **kwargs)

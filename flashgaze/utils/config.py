"""配置加载工具。

优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值（defaults.py）。
"""

from __future__ import annotations

import json
import os
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional

from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_VLM_MAX_ADJUSTMENT,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_WEIGHTS,
    DEFAULT_WORKERS,
    ENV_API_BASE,
    ENV_API_KEY,
    ENV_DEDUP_THRESHOLD,
    ENV_MAX_RETRIES,
    ENV_MODEL,
    ENV_SCENE,
    ENV_TIMEOUT,
    ENV_VLM_MAX_ADJUSTMENT,
    ENV_VLM_PROVIDER,
    ENV_WEIGHTS,
    ENV_WORKERS,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.schemas import Config
from flashgaze.utils.logging import get_logger

# 合法权重 key 集合（sharpness/exposure 必填，composition/noise/color 可选）
_WEIGHT_KEYS_REQUIRED = ("sharpness", "exposure")
_WEIGHT_KEYS_OPTIONAL = ("composition", "noise", "color")
_WEIGHT_KEYS_ALL = _WEIGHT_KEYS_REQUIRED + _WEIGHT_KEYS_OPTIONAL


def _parse_weights(raw: Any) -> Optional[dict[str, float]]:
    """解析权重 dict，支持 sharpness/exposure/composition/noise/color 五个 key。

    - sharpness/exposure 必填，composition/noise/color 可选
    - 自动归一化到总和 1.0
    - 非法输入（非 dict、缺必填 key、值非数值、总和<=0）返回 None
    """
    if not isinstance(raw, dict):
        return None
    for k in _WEIGHT_KEYS_REQUIRED:
        if k not in raw:
            return None
    try:
        weights: dict[str, float] = {}
        for k in _WEIGHT_KEYS_REQUIRED:
            weights[k] = float(raw[k])
        for k in _WEIGHT_KEYS_OPTIONAL:
            if k in raw:
                weights[k] = float(raw[k])
    except (ValueError, TypeError):
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in weights.items()}


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
            parsed = _parse_weights(raw)
            if parsed is not None:
                cfg["weights"] = parsed
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    if os.environ.get(ENV_DEDUP_THRESHOLD):
        try:
            cfg["dedup_threshold"] = int(os.environ[ENV_DEDUP_THRESHOLD])
        except ValueError:
            pass
    # ── VLM 扩展新增环境变量（M3）──────────────────────
    if os.environ.get(ENV_VLM_PROVIDER):
        cfg["vlm_provider"] = os.environ[ENV_VLM_PROVIDER]
    if os.environ.get(ENV_SCENE):
        cfg["scene"] = os.environ[ENV_SCENE]
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
        "vlm_provider": DEFAULT_VLM_PROVIDER,
        "scene": DEFAULT_SCENE,
    }


# Config dataclass 合法字段名集合（构造时过滤非法 key，避免 TypeError）
_CONFIG_FIELD_NAMES: set[str] = {f.name for f in fields(Config)}


def _adjust_weights_for_enabled_features(config: Config) -> Config:
    """启用新维度但未自定义权重时，自动注入默认权重。

    仅当 config.weights 仍为 DEFAULT_WEIGHTS（用户未自定义）时触发。
    若用户通过 --weights 或配置文件设置了自定义权重，直接返回原 config。

    权重策略：
    - 全维度启用（composition+noise+color）：sharpness 0.35 / exposure 0.25 / composition 0.20 / noise 0.10 / color 0.10
    - 部分启用：基础 sharpness 0.5 / exposure 0.5，每启用一个新维度从基础各借权重
    """
    # 用户已自定义权重（非 DEFAULT_WEIGHTS），保持原样
    if config.weights is not DEFAULT_WEIGHTS:
        return config

    has_composition = config.enable_composition
    has_noise = config.enable_noise
    has_color = config.enable_color

    # 未启用任何新维度，保持默认 sharpness 0.5 / exposure 0.5
    if not (has_composition or has_noise or has_color):
        return config

    # 全维度启用：使用预设的非对称权重
    if has_composition and has_noise and has_color:
        weights = {
            "sharpness": 0.35,
            "exposure": 0.25,
            "composition": 0.20,
            "noise": 0.10,
            "color": 0.10,
        }
        return replace(config, weights=MappingProxyType(weights))

    # 部分启用：从基础 0.5/0.5 逐步借权重
    weights: dict[str, float] = {"sharpness": 0.5, "exposure": 0.5}
    if has_composition:
        weights["composition"] = 0.2
        weights["sharpness"] = 0.4
        weights["exposure"] = 0.4
    if has_noise:
        weights["noise"] = 0.1
        weights["sharpness"] = round(weights["sharpness"] - 0.05, 2)
        weights["exposure"] = round(weights["exposure"] - 0.05, 2)
    if has_color:
        weights["color"] = 0.1
        weights["sharpness"] = round(weights["sharpness"] - 0.05, 2)
        weights["exposure"] = round(weights["exposure"] - 0.05, 2)
    return replace(config, weights=MappingProxyType(weights))


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
    logger = get_logger()

    # 配置文件传入的 weights 走校验：必填 sharpness/exposure，缺失或非法则
    # 回退默认权重（删除该 key 让 defaults 兜底），与 env/CLI 路径保持一致
    if "weights" in file_cfg:
        parsed = _parse_weights(file_cfg["weights"])
        if parsed is None:
            logger.warning(
                "配置文件 weights=%r 缺失必填 key（sharpness/exposure）或非法，"
                "回退到默认权重",
                file_cfg["weights"],
            )
            file_cfg = {k: v for k, v in file_cfg.items() if k != "weights"}
        else:
            file_cfg = {**file_cfg, "weights": parsed}

    # 三层基础合并：default < file < env
    base: dict[str, Any] = {**defaults, **file_cfg, **env}
    # overrides 覆盖（仅非 None 值）
    for k, v in overrides.items():
        if v is not None:
            base[k] = v

    # ── VLM 扩展字段校验（M3）──────────────────────────
    # 非法 provider/scene 回退到默认值并记 warning，不抛异常
    if base.get("vlm_provider") not in SUPPORTED_VLM_PROVIDERS:
        if base.get("vlm_provider") is not None:
            logger.warning(
                "不支持的 vlm_provider=%s，回退到 %s",
                base.get("vlm_provider"), DEFAULT_VLM_PROVIDER,
            )
        base["vlm_provider"] = DEFAULT_VLM_PROVIDER
    if base.get("scene") not in SUPPORTED_SCENES:
        if base.get("scene") is not None:
            logger.warning(
                "不支持的 scene=%s，回退到 %s",
                base.get("scene"), DEFAULT_SCENE,
            )
        base["scene"] = DEFAULT_SCENE

    raw_workers = base.get("workers", DEFAULT_WORKERS)
    # 下限保护：至少 1 个 worker，防止 0 或负数导致线程池崩溃
    if raw_workers < 1:
        logger.warning(
            "workers=%d 小于 1，已自动钳制为 1",
            raw_workers,
        )
        raw_workers = 1
    cpu_count = os.cpu_count() or 4
    # 上限钳制：硬上限 16，且不超过 cpu_count（与 FIX_WP4_PLAN 设计一致）
    max_workers = min(cpu_count, 16)
    if raw_workers > max_workers:
        logger.warning(
            "workers=%d 超过上限 %d（cpu_count=%d），已自动钳制为 %d",
            raw_workers, max_workers, cpu_count, max_workers,
        )
        raw_workers = max_workers
    base["workers"] = raw_workers

    # 过滤掉非 Config 字段，避免构造报错
    valid = _CONFIG_FIELD_NAMES
    kwargs = {k: v for k, v in base.items() if k in valid and k != "directory"}
    config = Config(directory=directory, **kwargs)

    # 启用新维度但未自定义权重时，自动注入默认权重
    config = _adjust_weights_for_enabled_features(config)

    # 统一保证 config.weights 不可变：无论来源（默认/env/CLI/配置文件/自动注入），
    # 都用 MappingProxyType 包裹，封堵 config.weights["x"] = y 原地修改路径
    weights = config.weights
    if not isinstance(weights, MappingProxyType):
        weights = MappingProxyType(dict(weights))
    config = replace(config, weights=weights)
    return config

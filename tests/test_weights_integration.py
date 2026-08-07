"""权重体系集成测试（M6）。

覆盖 _parse_weights / _adjust_weights_for_enabled_features / build_config 的权重自动注入逻辑：
- 默认不启用任何新维度时权重为 {sharpness: 0.5, exposure: 0.5}
- 全维度启用时使用非对称权重
- 部分启用时正确借权重
- 用户自定义 --weights 时自动注入不生效
- CLI --weights 含 noise/color 时正确解析
- config.weights 不可变（MappingProxyType），原地修改抛 TypeError
- 配置文件 weights 缺必填 key 时回退默认并 warning
"""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from flashgaze.cli.parser import CLIParser
from flashgaze.defaults import DEFAULT_WEIGHTS
from flashgaze.utils.config import _parse_weights, build_config


# ---------- _parse_weights ----------

def test_parse_weights_required_keys():
    """缺 sharpness 或 exposure 返回 None。"""
    assert _parse_weights({"sharpness": 0.5}) is None
    assert _parse_weights({"exposure": 0.5}) is None


def test_parse_weights_optional_keys():
    """可选 key（composition/noise/color）按需包含。"""
    w = _parse_weights({"sharpness": 0.5, "exposure": 0.5})
    assert w == {"sharpness": 0.5, "exposure": 0.5}

    w = _parse_weights({"sharpness": 0.4, "exposure": 0.4, "noise": 0.2})
    assert w == {"sharpness": 0.4, "exposure": 0.4, "noise": 0.2}

    w = _parse_weights({
        "sharpness": 0.35, "exposure": 0.25,
        "composition": 0.20, "noise": 0.10, "color": 0.10,
    })
    assert w["sharpness"] == 0.35
    assert w["color"] == 0.10


def test_parse_weights_normalizes():
    """非归一化输入自动归一化到 1.0。"""
    w = _parse_weights({"sharpness": 2, "exposure": 2, "noise": 1})
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["sharpness"] == 0.4
    assert w["exposure"] == 0.4
    assert w["noise"] == 0.2


def test_parse_weights_invalid_returns_none():
    """非法输入返回 None。"""
    assert _parse_weights("not a dict") is None
    assert _parse_weights(None) is None
    assert _parse_weights({"sharpness": "x", "exposure": 0.5}) is None
    assert _parse_weights({"sharpness": 0, "exposure": 0}) is None  # 总和 <= 0


# ---------- 默认行为（不启用新维度） ----------

def test_default_weights_unchanged_when_no_features():
    """不启用任何新维度时，权重应为 DEFAULT_WEIGHTS。"""
    cfg = build_config(directory="/tmp")
    assert cfg.weights is DEFAULT_WEIGHTS
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.5


# ---------- 全维度启用 ----------

def test_all_features_enabled_uses_asymmetric_weights():
    """全维度启用（composition+noise+color）时使用非对称权重。"""
    cfg = build_config(
        directory="/tmp",
        enable_composition=True,
        enable_noise=True,
        enable_color=True,
    )
    assert cfg.weights["sharpness"] == 0.35
    assert cfg.weights["exposure"] == 0.25
    assert cfg.weights["composition"] == 0.20
    assert cfg.weights["noise"] == 0.10
    assert cfg.weights["color"] == 0.10
    # 总和为 1.0
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9


# ---------- 部分启用 ----------

def test_only_composition_enabled():
    """仅启用 composition：sharpness/exposure 各 0.4，composition 0.2。"""
    cfg = build_config(directory="/tmp", enable_composition=True)
    assert cfg.weights["sharpness"] == 0.4
    assert cfg.weights["exposure"] == 0.4
    assert cfg.weights["composition"] == 0.2
    assert "noise" not in cfg.weights
    assert "color" not in cfg.weights


def test_only_noise_enabled():
    """仅启用 noise：sharpness/exposure 各 0.45，noise 0.1。"""
    cfg = build_config(directory="/tmp", enable_noise=True)
    assert cfg.weights["sharpness"] == 0.45
    assert cfg.weights["exposure"] == 0.45
    assert cfg.weights["noise"] == 0.1
    assert "composition" not in cfg.weights
    assert "color" not in cfg.weights


def test_only_color_enabled():
    """仅启用 color：sharpness/exposure 各 0.45，color 0.1。"""
    cfg = build_config(directory="/tmp", enable_color=True)
    assert cfg.weights["sharpness"] == 0.45
    assert cfg.weights["exposure"] == 0.45
    assert cfg.weights["color"] == 0.1


def test_composition_and_noise_enabled():
    """启用 composition + noise（非全维度）。"""
    cfg = build_config(
        directory="/tmp",
        enable_composition=True,
        enable_noise=True,
    )
    # 部分启用路径：从 0.5/0.5 借权重
    assert cfg.weights["composition"] == 0.2
    assert cfg.weights["noise"] == 0.1
    # sharpness 从 0.4 再借 0.05 = 0.35
    assert cfg.weights["sharpness"] == 0.35
    assert cfg.weights["exposure"] == 0.35
    assert "color" not in cfg.weights


# ---------- 用户自定义权重 ----------

def test_custom_weights_not_overridden():
    """用户提供 --weights 时自动注入不生效。"""
    custom = {"sharpness": 0.7, "exposure": 0.3}
    cfg = build_config(
        directory="/tmp",
        enable_composition=True,  # 启用 composition 但已有自定义权重
        enable_noise=True,
        enable_color=True,
        weights=custom,
    )
    # 用户自定义权重应保留，不被自动注入覆盖
    assert cfg.weights["sharpness"] == 0.7
    assert cfg.weights["exposure"] == 0.3
    assert "composition" not in cfg.weights  # 用户未提供就不注入


def test_custom_weights_with_optional_keys():
    """用户在 --weights 中提供可选 key 时保留。"""
    custom = {
        "sharpness": 0.4, "exposure": 0.3,
        "composition": 0.2, "noise": 0.1,
    }
    cfg = build_config(directory="/tmp", weights=custom)
    assert cfg.weights["sharpness"] == 0.4
    assert cfg.weights["composition"] == 0.2
    assert cfg.weights["noise"] == 0.1


# ---------- CLI 集成 ----------

def test_cli_weights_with_noise_and_color():
    """CLI --weights 含 noise/color 时正确解析。"""
    cfg = CLIParser().parse([
        "./photos",
        "--weights", '{"sharpness": 0.5, "exposure": 0.3, "noise": 0.1, "color": 0.1}',
    ])
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.3
    assert cfg.weights["noise"] == 0.1
    assert cfg.weights["color"] == 0.1


def test_cli_enable_noise_without_weights_uses_default():
    """CLI --enable-noise 不带 --weights 时使用自动注入的权重。"""
    cfg = CLIParser().parse(["./photos", "--enable-noise"])
    assert cfg.weights["sharpness"] == 0.45
    assert cfg.weights["exposure"] == 0.45
    assert cfg.weights["noise"] == 0.1


def test_cli_enable_color_without_weights_uses_default():
    """CLI --enable-color 不带 --weights 时使用自动注入的权重。"""
    cfg = CLIParser().parse(["./photos", "--enable-color"])
    assert cfg.weights["color"] == 0.1
    assert cfg.weights["sharpness"] == 0.45


def test_cli_enable_all_features_uses_full_weights():
    """CLI 同时启用全部维度时使用预设非对称权重。"""
    cfg = CLIParser().parse([
        "./photos",
        "--enable-composition", "--enable-noise",
        "--enable-color", "--enable-portrait", "--enable-dedup",
    ])
    assert cfg.weights["sharpness"] == 0.35
    assert cfg.weights["exposure"] == 0.25
    assert cfg.weights["composition"] == 0.20
    assert cfg.weights["noise"] == 0.10
    assert cfg.weights["color"] == 0.10
    # portrait 和 dedup 不影响权重（portrait 是加分，dedup 是去重标记）
    assert cfg.enable_portrait is True
    assert cfg.dedup is True


def test_cli_dedup_threshold():
    """CLI --dedup-threshold 正确解析。"""
    cfg = CLIParser().parse([
        "./photos", "--enable-dedup", "--dedup-threshold", "5",
    ])
    assert cfg.dedup is True
    assert cfg.dedup_threshold == 5


def test_cli_dedup_threshold_default_none():
    """不传 --dedup-threshold 时为 None（由 Deduplicator 用默认 8）。"""
    cfg = CLIParser().parse(["./photos"])
    assert cfg.dedup_threshold is None


# ---------- config.weights 不可变性 ----------

def test_config_weights_immutable_default():
    """默认权重路径：config.weights 是 MappingProxyType，原地修改抛 TypeError。"""
    cfg = build_config(directory="/tmp")
    assert isinstance(cfg.weights, MappingProxyType)
    with pytest.raises(TypeError):
        cfg.weights["sharpness"] = 0.9  # type: ignore[index]


def test_config_weights_immutable_custom_override():
    """用户自定义 weights（overrides 路径）：包裹为不可变，原地修改抛 TypeError。"""
    cfg = build_config(
        directory="/tmp",
        weights={"sharpness": 0.7, "exposure": 0.3},
    )
    assert isinstance(cfg.weights, MappingProxyType)
    assert cfg.weights["sharpness"] == 0.7
    with pytest.raises(TypeError):
        cfg.weights["sharpness"] = 0.9  # type: ignore[index]


def test_config_weights_immutable_auto_injected():
    """自动注入权重路径：仍是 MappingProxyType，原地修改抛 TypeError。"""
    cfg = build_config(
        directory="/tmp",
        enable_composition=True,
        enable_noise=True,
        enable_color=True,
    )
    assert isinstance(cfg.weights, MappingProxyType)
    assert cfg.weights["composition"] == 0.20
    with pytest.raises(TypeError):
        cfg.weights["sharpness"] = 0.9  # type: ignore[index]


def test_config_weights_immutable_from_cli():
    """CLI --weights 路径：config.weights 不可变。"""
    cfg = CLIParser().parse([
        "./photos",
        "--weights", '{"sharpness": 0.6, "exposure": 0.4}',
    ])
    assert isinstance(cfg.weights, MappingProxyType)
    with pytest.raises(TypeError):
        cfg.weights["sharpness"] = 0.9  # type: ignore[index]


def test_config_weights_immutable_from_file():
    """配置文件 weights 路径：config.weights 不可变。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": {"sharpness": 0.6, "exposure": 0.4}},
    )
    assert isinstance(cfg.weights, MappingProxyType)
    assert cfg.weights["sharpness"] == 0.6
    with pytest.raises(TypeError):
        cfg.weights["sharpness"] = 0.9  # type: ignore[index]


def test_config_weights_custom_does_not_mutate_input():
    """传入的 dict 被 copy 包裹，原 dict 不受影响。"""
    custom = {"sharpness": 0.7, "exposure": 0.3}
    cfg = build_config(directory="/tmp", weights=custom)
    # config.weights 不可变
    assert isinstance(cfg.weights, MappingProxyType)
    # 原 dict 仍可写（未被冻结）
    custom["sharpness"] = 0.1
    # config.weights 不受影响（独立副本）
    assert cfg.weights["sharpness"] == 0.7


# ---------- 配置文件 weights 校验 ----------

def test_file_weights_missing_required_key_falls_back(caplog):
    """配置文件 weights 缺 exposure：回退默认权重并记 warning。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": {"sharpness": 0.7}},  # 缺 exposure
    )
    # 回退到默认权重
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.5
    # 有 warning 日志
    assert any(
        "回退到默认权重" in rec.message and rec.levelname == "WARNING"
        for rec in caplog.records
    )


def test_file_weights_non_dict_falls_back(caplog):
    """配置文件 weights 非 dict：回退默认权重并记 warning。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": [0.7, 0.3]},  # 非 dict
    )
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.5
    assert any(
        "回退到默认权重" in rec.message and rec.levelname == "WARNING"
        for rec in caplog.records
    )


def test_file_weights_valid_is_accepted():
    """配置文件 weights 合法时被接受且不可变。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": {"sharpness": 0.6, "exposure": 0.4}},
    )
    assert cfg.weights["sharpness"] == 0.6
    assert cfg.weights["exposure"] == 0.4
    assert isinstance(cfg.weights, MappingProxyType)


def test_file_weights_normalized_when_accepted():
    """配置文件 weights 非归一化时被 _parse_weights 归一化。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": {"sharpness": 2, "exposure": 2}},
    )
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.5


def test_file_weights_with_optional_keys_accepted():
    """配置文件 weights 含可选 key 时保留。"""
    cfg = build_config(
        directory="/tmp",
        file_cfg={"weights": {
            "sharpness": 0.5, "exposure": 0.3, "composition": 0.2,
        }},
    )
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["composition"] == 0.2

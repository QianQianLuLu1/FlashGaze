"""utils/config.py 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashgaze.defaults import DEFAULT_API_BASE, DEFAULT_MODEL, DEFAULT_WEIGHTS, DEFAULT_WORKERS
from flashgaze.utils.config import build_config, default_config_dict, load_config_file, merge_env

# ---------- load_config_file ----------


def test_load_config_file_valid(tmp_path: Path) -> None:
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"api_key": "k", "model": "m", "workers": 8}),
        encoding="utf-8",
    )
    cfg = load_config_file(cfg_file)
    assert cfg["api_key"] == "k"
    assert cfg["model"] == "m"
    assert cfg["workers"] == 8


def test_load_config_file_not_exist(tmp_path: Path) -> None:
    """文件不存在返回空 dict。"""
    assert load_config_file(tmp_path / "nope.json") == {}


def test_load_config_file_corrupted(tmp_path: Path) -> None:
    """格式错误返回空 dict。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    assert load_config_file(bad) == {}


def test_load_config_file_corrupted_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """#3-4 回归：配置文件损坏须告警，便于发现配置未生效。"""
    import logging

    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        load_config_file(bad)
    assert any("读取或解析失败" in r.message for r in caplog.records)


def test_merge_env_invalid_numeric_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#3-5 回归：非法 env 数值须告警而非静默丢弃。"""
    import logging

    monkeypatch.setenv("FLASHGAZE_TIMEOUT", "abc")
    with caplog.at_level(logging.WARNING):
        cfg = merge_env()
    assert "FLASHGAZE_TIMEOUT" in caplog.text
    # 非法值不应进入配置，回退默认
    assert "timeout_sec" not in cfg


def test_load_config_file_empty(tmp_path: Path) -> None:
    """空文件返回空 dict。"""
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert load_config_file(empty) == {}


# ---------- merge_env ----------


def test_merge_env_reads_all_vars(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_merge_env_empty_when_no_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """无环境变量时返回空 dict。"""
    for var in (
        "FLASHGAZE_API_KEY",
        "FLASHGAZE_API_BASE",
        "FLASHGAZE_MODEL",
        "FLASHGAZE_TIMEOUT",
        "FLASHGAZE_WORKERS",
    ):
        monkeypatch.delenv(var, raising=False)
    assert merge_env() == {}


def test_merge_env_invalid_timeout_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """非数字的 TIMEOUT 被忽略。"""
    monkeypatch.setenv("FLASHGAZE_TIMEOUT", "not-a-number")
    cfg = merge_env()
    assert "timeout_sec" not in cfg


def test_merge_env_invalid_workers_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """非数字的 WORKERS 被忽略。"""
    monkeypatch.setenv("FLASHGAZE_WORKERS", "abc")
    cfg = merge_env()
    assert "workers" not in cfg


def test_merge_env_breaker_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_VLM_BREAKER_THRESHOLD 合法值被读取。"""
    monkeypatch.setenv("FLASHGAZE_VLM_BREAKER_THRESHOLD", "3")
    cfg = merge_env()
    assert cfg["vlm_breaker_threshold"] == 3


def test_merge_env_invalid_breaker_threshold_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """非数字的 VLM_BREAKER_THRESHOLD 被忽略。"""
    monkeypatch.setenv("FLASHGAZE_VLM_BREAKER_THRESHOLD", "abc")
    cfg = merge_env()
    assert "vlm_breaker_threshold" not in cfg


def test_build_config_breaker_threshold_default() -> None:
    """熔断阈值默认 5（DEFAULT_VLM_BREAKER_THRESHOLD）。"""
    assert build_config("/tmp").vlm_breaker_threshold == 5


def test_build_config_breaker_threshold_negative_clamped_to_zero() -> None:
    """负值熔断阈值钳制到 0（关闭熔断），0 是合法语义。"""
    assert build_config("/tmp", vlm_breaker_threshold=-2).vlm_breaker_threshold == 0
    assert build_config("/tmp", vlm_breaker_threshold=0).vlm_breaker_threshold == 0


def test_build_config_breaker_threshold_string_coerced() -> None:
    """配置文件/override 传入字符串数字时强转为 int。"""
    assert build_config("/tmp", vlm_breaker_threshold="7").vlm_breaker_threshold == 7


def test_build_config_breaker_threshold_invalid_falls_back_default() -> None:
    """完全非法（无法 int 化）的熔断阈值回退默认值，不抛异常。"""
    assert build_config("/tmp", vlm_breaker_threshold=None) is not None
    cfg = build_config("/tmp", vlm_breaker_threshold=[1])
    assert cfg.vlm_breaker_threshold == 5


# ---------- cleanup_guard_min_sample（删除护栏最小样本量）----------


def test_build_config_guard_min_sample_default() -> None:
    """护栏最小样本量默认 6（CLEANUP_GUARD_MIN_SAMPLE，由 20 下调）。"""
    assert build_config("/tmp").cleanup_guard_min_sample == 6


def test_build_config_guard_min_sample_below_one_clamped() -> None:
    """<1 钳到 1：护栏不可经配置关闭，放行须走 --force + 清单指纹。"""
    assert build_config("/tmp", cleanup_guard_min_sample=0).cleanup_guard_min_sample == 1
    assert build_config("/tmp", cleanup_guard_min_sample=-5).cleanup_guard_min_sample == 1


def test_build_config_guard_min_sample_string_coerced() -> None:
    """配置文件/override 传入字符串数字时强转为 int。"""
    assert build_config("/tmp", cleanup_guard_min_sample="3").cleanup_guard_min_sample == 3


def test_build_config_guard_min_sample_invalid_falls_back_default() -> None:
    """完全非法（无法 int 化）回退默认值，不抛异常（与其它数值字段同契约）。"""
    assert build_config("/tmp", cleanup_guard_min_sample=[3]).cleanup_guard_min_sample == 6


def test_build_config_guard_min_sample_via_file() -> None:
    """配置文件键 cleanup_guard_min_sample 生效（CLI > env > file > default 的 file 层）。"""
    cfg = build_config("/tmp", file_cfg={"cleanup_guard_min_sample": 3})
    assert cfg.cleanup_guard_min_sample == 3


# ---------- default_config_dict ----------


def test_default_config_dict_values() -> None:
    """默认配置与 defaults.py 一致。"""
    cfg = default_config_dict()
    assert cfg["api_base"] == DEFAULT_API_BASE
    assert cfg["model"] == DEFAULT_MODEL
    assert cfg["workers"] == DEFAULT_WORKERS
    assert "weights" in cfg
    assert "vlm_max_adjustment" in cfg
    assert "vlm_breaker_threshold" in cfg


# ---------- C-07: DEFAULT_WEIGHTS 不可变性 ----------


def test_default_weights_is_immutable() -> None:
    """DEFAULT_WEIGHTS 是 MappingProxyType，原地修改应抛 TypeError。"""
    with pytest.raises(TypeError):
        DEFAULT_WEIGHTS["sharpness"] = 0.9  # type: ignore[index]


def test_default_weights_read_compatible() -> None:
    """MappingProxyType 读取接口与 dict 兼容。"""
    assert DEFAULT_WEIGHTS["sharpness"] == 0.5
    assert DEFAULT_WEIGHTS.get("exposure") == 0.5
    assert dict(DEFAULT_WEIGHTS) == {"sharpness": 0.5, "exposure": 0.5}


# ---------- F-05: weights composition key ----------


def test_merge_env_weights_with_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_WEIGHTS 含 composition 时三键归一化。"""
    monkeypatch.setenv(
        "FLASHGAZE_WEIGHTS",
        json.dumps({"sharpness": 0.5, "exposure": 0.3, "composition": 0.2}),
    )
    cfg = merge_env()
    w = cfg["weights"]
    assert w["sharpness"] == 0.5  # 0.5/1.0
    assert w["exposure"] == 0.3  # 0.3/1.0
    assert w["composition"] == 0.2  # 0.2/1.0


def test_merge_env_weights_without_composition(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_merge_env_weights_composition_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """composition 权重非归一化输入时正确归一化。"""
    monkeypatch.setenv(
        "FLASHGAZE_WEIGHTS",
        json.dumps({"sharpness": 2, "exposure": 2, "composition": 1}),
    )
    cfg = merge_env()
    w = cfg["weights"]
    assert w["sharpness"] == 0.4  # 2/5
    assert w["exposure"] == 0.4  # 2/5
    assert w["composition"] == 0.2  # 1/5


# ---------- VLM 扩展：provider / scene 环境变量（M3）----------


def test_merge_env_reads_vlm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_VLM_PROVIDER 被正确读取。"""
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "openai")
    cfg = merge_env()
    assert cfg["vlm_provider"] == "openai"


def test_merge_env_reads_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_SCENE 被正确读取。"""
    monkeypatch.setenv("FLASHGAZE_SCENE", "portrait")
    cfg = merge_env()
    assert cfg["scene"] == "portrait"


def test_merge_env_reads_allow_private_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_ALLOW_PRIVATE_TARGETS 真值被解析为 bool（SSRF 逃生通道）。"""
    from flashgaze.defaults import ENV_ALLOW_PRIVATE_TARGETS

    monkeypatch.setenv(ENV_ALLOW_PRIVATE_TARGETS, "true")
    assert merge_env()["allow_private_targets"] is True
    monkeypatch.setenv(ENV_ALLOW_PRIVATE_TARGETS, "1")
    assert merge_env()["allow_private_targets"] is True
    # 未设置 / 非真值 → 不进入配置（保持默认 False，避免误放开云 API）
    monkeypatch.delenv(ENV_ALLOW_PRIVATE_TARGETS, raising=False)
    assert "allow_private_targets" not in merge_env()
    monkeypatch.setenv(ENV_ALLOW_PRIVATE_TARGETS, "false")
    assert "allow_private_targets" not in merge_env()


def test_merge_env_no_vlm_vars_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """未设置 VLM 扩展变量时不出现在返回 dict 中。"""
    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = merge_env()
    assert "vlm_provider" not in cfg
    assert "scene" not in cfg


def test_default_config_dict_includes_vlm_provider_and_scene() -> None:
    """默认配置 dict 包含 vlm_provider / scene 默认值。"""
    cfg = default_config_dict()
    assert cfg["vlm_provider"] == "qwen"
    assert cfg["scene"] == "auto"


# ---------- build_config 校验（M3）----------


def test_build_config_invalid_provider_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法 provider 回退到 qwen 默认值。"""
    from flashgaze.utils.config import build_config

    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    cfg = build_config(".", vlm_provider="invalid_provider")
    assert cfg.vlm_provider == "qwen"


def test_build_config_invalid_scene_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """非法 scene 回退到 auto 默认值。"""
    from flashgaze.utils.config import build_config

    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = build_config(".", scene="invalid_scene")
    assert cfg.scene == "auto"


def test_build_config_valid_provider_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法 provider 被接受。"""
    from flashgaze.utils.config import build_config

    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    cfg = build_config(".", vlm_provider="anthropic")
    assert cfg.vlm_provider == "anthropic"


def test_build_config_valid_scene_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法 scene 被接受。"""
    from flashgaze.utils.config import build_config

    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = build_config(".", scene="landscape")
    assert cfg.scene == "landscape"


def test_build_config_defaults_provider_and_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    """无任何覆盖时使用默认值 qwen / auto。"""
    from flashgaze.utils.config import build_config

    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = build_config(".")
    assert cfg.vlm_provider == "qwen"
    assert cfg.scene == "auto"


def test_build_config_legacy_file_without_new_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """旧配置文件（无 vlm_provider/scene 字段）可正常加载，使用默认值。"""
    from flashgaze.utils.config import build_config, load_config_file

    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"api_key": "k", "model": "m"}),
        encoding="utf-8",
    )
    cfg = build_config(".", file_cfg=load_config_file(legacy))
    assert cfg.vlm_provider == "qwen"
    assert cfg.scene == "auto"
    assert cfg.api_key == "k"


def test_build_config_env_overrides_file_for_vlm_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """环境变量 vlm_provider 优先于配置文件。"""
    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"vlm_provider": "openai"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "anthropic")
    cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.vlm_provider == "anthropic"


# ---------- C-05：配置文件/override 数值强转（字符串/浮点不崩）----------


def test_build_config_coerces_string_workers_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配置文件 workers 写成字符串 \"4\" 时强转为 int，不抛 TypeError（C-05）。"""
    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"workers": "4"}), encoding="utf-8")
    cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.workers == 4
    assert isinstance(cfg.workers, int)


def test_build_config_coerces_numeric_fields_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """timeout_sec / max_retries / dedup_threshold 字符串值被强转（C-05）。"""
    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"timeout_sec": "30", "max_retries": "2", "dedup_threshold": "5"}),
        encoding="utf-8",
    )
    cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.timeout_sec == 30
    assert cfg.max_retries == 2
    assert cfg.dedup_threshold == 5


def test_build_config_invalid_workers_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配置文件 workers 非法（非数字）时回退默认 int，不崩溃（C-05）。"""
    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "bad.json"
    cfg_file.write_text(json.dumps({"workers": "abc"}), encoding="utf-8")
    cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.workers == DEFAULT_WORKERS
    assert isinstance(cfg.workers, int)


def test_build_config_override_float_workers_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    """override 传浮点 4.0 也强转为 int（C-05）。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", workers=4.0)
    assert cfg.workers == 4
    assert isinstance(cfg.workers, int)


# ---------- C-06：override 的 weights 必须经 _parse_weights 校验 ----------


def test_build_config_override_weights_missing_required_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """override 缺 sharpness 的 weights 被忽略，回退默认权重（C-06）。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", weights={"exposure": 0.5})  # 缺必填 sharpness
    assert dict(cfg.weights) == dict(DEFAULT_WEIGHTS)


def test_build_config_override_weights_valid_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """override 含合法 weights 时被采用并归一化（C-06）。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", weights={"sharpness": 0.7, "exposure": 0.3})
    assert cfg.weights["sharpness"] == 0.7
    assert cfg.weights["exposure"] == 0.3


# ---------- 零权重护栏（FIX #C-15）----------


def test_validate_weights_rejects_zero_sum() -> None:
    """_validate_weights 对零和权重抛 ValueError。"""
    from dataclasses import replace
    from types import MappingProxyType

    from flashgaze.models.schemas import Config
    from flashgaze.utils.config import _validate_weights

    cfg = replace(
        Config(directory="."),
        weights=MappingProxyType({"sharpness": 0.0, "exposure": 0.0}),
    )
    with pytest.raises(ValueError, match="权重总和必须为正数"):
        _validate_weights(cfg)


def test_validate_weights_accepts_normal() -> None:
    """正常权重（总和 > 0）不抛错。"""
    from flashgaze.models.schemas import Config
    from flashgaze.utils.config import _validate_weights

    cfg = Config(directory=".", weights={"sharpness": 0.5, "exposure": 0.5})
    _validate_weights(cfg)  # 不应抛错


def test_build_config_zero_weights_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_config 在最终权重被强制为零和时，收尾 _validate_weights 响亮抛错。"""
    from dataclasses import replace
    from types import MappingProxyType

    from flashgaze.models.schemas import Config
    from flashgaze.utils.config import build_config

    def _force_zero(cfg: Config) -> Config:
        return replace(
            cfg,
            weights=MappingProxyType({"sharpness": 0.0, "exposure": 0.0}),
        )

    monkeypatch.setattr(
        "flashgaze.utils.config._adjust_weights_for_enabled_features", _force_zero
    )
    with pytest.raises(ValueError, match="权重总和必须为正数"):
        build_config(".", weights={"sharpness": 0.5, "exposure": 0.5})


# ---------- exif_backup 单一真源归一化（C-配置）----------


def test_build_config_exif_backup_default_true() -> None:
    """默认 exif_backup=True，且 Config 不再含 no_exif_backup 字段。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".")
    assert cfg.exif_backup is True
    assert not hasattr(cfg, "no_exif_backup")


def test_build_config_exif_backup_false_explicit() -> None:
    """显式 exif_backup=False 生效，不备份。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", exif_backup=False)
    assert cfg.exif_backup is False


def test_build_config_no_exif_backup_override_disables_backup() -> None:
    """兼容反向开关 no_exif_backup=True 归一到 exif_backup=False 且不进入 Config。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", no_exif_backup=True)
    assert cfg.exif_backup is False
    assert not hasattr(cfg, "no_exif_backup")


def test_build_config_no_exif_backup_conflict_warns_and_disables(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """exif_backup=True 与 no_exif_backup=True 同时出现：归一化为不备份并记 WARNING。"""
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", exif_backup=True, no_exif_backup=True)
    assert cfg.exif_backup is False
    assert any("no_exif_backup=True" in r.message for r in caplog.records)


def test_build_config_no_exif_backup_false_keeps_exif_backup() -> None:
    """no_exif_backup=False 不覆盖已显式的 exif_backup=False（保持不备份）。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", exif_backup=False, no_exif_backup=False)
    assert cfg.exif_backup is False


def test_build_config_no_exif_backup_false_default_stays_backup() -> None:
    """no_exif_backup=False 配合默认 exif_backup=True：保持备份。"""
    from flashgaze.utils.config import build_config

    cfg = build_config(".", no_exif_backup=False)
    assert cfg.exif_backup is True


def test_build_config_unknown_override_key_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """未知 override 键（拼写错误/已废弃）须记 WARNING，且合法键仍生效。"""
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", top=5, workeres=8)  # workeres 为拼写错误
    # 未知键被告警但不过滤报错，Config 正常构造
    assert any("忽略未知配置键" in r.message for r in caplog.records)
    assert any("workeres" in r.message for r in caplog.records)
    # 合法键 top 仍生效
    assert cfg.top == 5


def test_build_config_directory_key_not_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """directory 属有意排除（已单独传入构造），不触发未知键告警。"""
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        build_config(".")
    assert not any("忽略未知配置键" in r.message for r in caplog.records)


# ---------- top / threshold 边界钳制（FIX #sec-threshold）----------


def test_build_config_top_below_one_falls_back_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """top=0 / -3 回退 DEFAULT_TOP(30)：禁止"只留 0 张"的清空语义。

    刻意不钳到 1——那会让 top=0 变成"只留 1 张、删掉其余"，比回退默认值更危险。
    """
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", top=0)
    assert cfg.top == 30
    assert any("top" in r.message for r in caplog.records)

    cfg2 = build_config(".", top=-3)
    assert cfg2.top == 30


def test_build_config_top_invalid_type_falls_back_to_default() -> None:
    """配置文件传入字符串/None 等非数值 top 时回退默认值，不抛异常。"""
    from flashgaze.utils.config import build_config

    assert build_config(".", top="abc").top == 30
    assert build_config(".", top="12").top == 12  # 可解析字符串按原值强转


def test_build_config_threshold_clamped_to_bounds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """threshold 越界钳到 [0,100]：150 → 100、-5 → 0，并记 WARNING。

    threshold=150 会让全部分数比较为 False → 全部进入待删 → 一次调用删空工作空间。
    """
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", threshold=150)
    assert cfg.threshold == 100.0
    assert any("threshold" in r.message for r in caplog.records)

    assert build_config(".", threshold=-5).threshold == 0.0
    assert build_config(".", threshold=42).threshold == 42.0


def test_build_config_threshold_nan_or_invalid_treated_as_unset() -> None:
    """NaN / inf / 不可解析视为"未设置"（None），回落 top 语义。

    NaN 无法被 `<0 / >100` 捕获，而 `score >= nan` 恒为 False 会删空，必须单独处置。
    """
    from flashgaze.utils.config import build_config

    for bad in (float("nan"), float("inf"), float("-inf"), "abc", object()):
        assert build_config(".", threshold=bad).threshold is None


def test_build_config_selection_bounds_cover_file_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """钳制须覆盖"配置文件"与"环境变量"两条非 CLI 来源（此前完全无校验）。"""
    import json

    import flashgaze.utils.config as config_mod

    # ① 配置文件来源
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"top": 0, "threshold": 999}), encoding="utf-8")
    cfg = config_mod.build_config(".", config_mod.load_config_file(cfg_file))
    assert cfg.top == 30
    assert cfg.threshold == 100.0

    # ② env 来源：打桩 merge_env 模拟环境变量注入的越界值
    monkeypatch.setattr(config_mod, "merge_env", lambda: {"top": -1, "threshold": 500})
    cfg2 = config_mod.build_config(".")
    assert cfg2.top == 30
    assert cfg2.threshold == 100.0


# ---------- int(inf) / 巨型整数不崩：OverflowError 收敛（FIX #3-6）----------


def test_build_config_file_with_1e999_falls_back_to_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#3-6 回归：JSON 允许 1e999（解析为 inf），int(inf) 抛 OverflowError，
    不在 (TypeError, ValueError) 捕获范围内，曾击穿「不抛异常」的装配契约。"""
    import logging

    from flashgaze.defaults import (
        DEFAULT_MAX_RETRIES,
        DEFAULT_TIMEOUT_SEC,
        DEFAULT_TOP,
        DEFAULT_WORKERS,
    )
    from flashgaze.utils.config import build_config

    # 刻意写原始 JSON 文本而非 json.dumps：后者会把 inf 序列化成非法的 Infinity 字面量
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        '{"top": 1e999, "workers": 1e999, "timeout_sec": 1e999,'
        ' "max_retries": 1e999, "dedup_threshold": 1e999}',
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", load_config_file(cfg_file))
    assert cfg.top == DEFAULT_TOP
    assert cfg.workers == DEFAULT_WORKERS
    assert cfg.timeout_sec == DEFAULT_TIMEOUT_SEC
    assert cfg.max_retries == DEFAULT_MAX_RETRIES
    assert cfg.dedup_threshold is None  # 非法即移除，回落 Config 默认（下游再用 8 兜底）
    assert any("非法" in r.message for r in caplog.records)


def test_build_config_numeric_overrides_survive_infinity() -> None:
    """#3-6 回归：override 直接传 float('inf') 逐字段回退默认，不抛 OverflowError。"""
    from flashgaze.defaults import (
        DEFAULT_MAX_RETRIES,
        DEFAULT_TIMEOUT_SEC,
        DEFAULT_TOP,
        DEFAULT_WORKERS,
    )
    from flashgaze.utils.config import build_config

    cfg = build_config(
        ".",
        top=float("inf"),
        workers=float("inf"),
        timeout_sec=float("inf"),
        max_retries=float("inf"),
        dedup_threshold=float("inf"),
    )
    assert cfg.top == DEFAULT_TOP
    assert cfg.workers == DEFAULT_WORKERS
    assert cfg.timeout_sec == DEFAULT_TIMEOUT_SEC
    assert cfg.max_retries == DEFAULT_MAX_RETRIES
    assert cfg.dedup_threshold is None


def test_build_config_threshold_huge_int_treated_as_unset() -> None:
    """#3-6 回归：threshold 传 10**400 时 float() 抛 OverflowError，按未设置处理。"""
    from flashgaze.utils.config import build_config

    assert build_config(".", threshold=10**400).threshold is None


def test_build_config_weights_huge_int_falls_back_to_default() -> None:
    """#3-6 回归：weights 值传 10**400 时 float() 溢出，回退默认权重不崩。"""
    from flashgaze.defaults import DEFAULT_WEIGHTS
    from flashgaze.utils.config import build_config

    cfg = build_config(".", weights={"sharpness": 10**400, "exposure": 1})
    assert cfg.weights == DEFAULT_WEIGHTS


# ---------- 小修：默认值单一真源（Config.top 引用 DEFAULT_TOP）----------


def test_config_top_default_references_default_top() -> None:
    """小修护栏：Config.top 的默认值来自 defaults.DEFAULT_TOP，不再重复字面量。"""
    from flashgaze.defaults import DEFAULT_TOP
    from flashgaze.models.schemas import Config

    assert Config(directory=".").top == DEFAULT_TOP


# ---------- M-7：布尔字段统一强转（字符串来源不得被静默当成真值）----------

_EXPECTED_BOOL_FIELDS = {
    "no_vlm",
    "enable_composition",
    "enable_noise",
    "enable_color",
    "enable_portrait",
    "dedup",
    "no_downscale",
    "allow_private_targets",
    "enable_plugins",
    "export",
    "move",
    "exif",
    "exif_backup",
    "output_json",
    "output_csv",
    "output_xlsx",
    "verbose",
    # H-6：端点确认逃生舱（非白名单端点不再告警）
    "allow_untrusted_api_base",
}


def test_coerce_bool_covers_all_config_bool_fields() -> None:
    """M-7 结构护栏：_BOOL_FIELDS 逐字覆盖 Config 全部布尔字段（新增字段漏配即失败）。"""
    from flashgaze.utils.config import _BOOL_FIELDS

    assert set(_BOOL_FIELDS) == _EXPECTED_BOOL_FIELDS
    # exif_backup 是唯一默认为 True 的布尔字段，回退方向与其它字段相反
    assert _BOOL_FIELDS["exif_backup"] is True
    assert all(_BOOL_FIELDS[k] is False for k in _EXPECTED_BOOL_FIELDS - {"exif_backup"})


def test_build_config_coerces_false_literals() -> None:
    """M-7：override 写 "false"/"0"/"no"/"off"（含大小写与空白）一律转为 False。"""
    from flashgaze.utils.config import build_config

    for raw in ("false", "0", "no", "off", "FALSE", " Off "):
        cfg = build_config(".", no_vlm=raw)
        assert cfg.no_vlm is False, raw


def test_build_config_coerces_true_literals() -> None:
    """M-7："true"/"1"/"yes"/"on"（含大小写与空白）一律转为 True。"""
    from flashgaze.utils.config import build_config

    for raw in ("true", "1", "yes", "on", "YES", " On "):
        cfg = build_config(".", dedup=raw)
        assert cfg.dedup is True, raw


def test_build_config_invalid_bool_falls_back_to_default_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M-7：非法布尔值 WARNING + 回退该字段默认值（exif_backup 默认 True，方向相反）。"""
    import logging

    from flashgaze.utils.config import build_config

    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", exif_backup="maybe", no_vlm=2)
    assert cfg.exif_backup is True  # 默认值 True
    assert cfg.no_vlm is False  # 默认值 False
    assert "非法布尔值" in caplog.text


def test_build_config_bool_null_treated_as_unset(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """M-7：配置文件写 null 等同未设置——回落默认值且**不**刷告警。"""
    import logging

    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"exif_backup": None, "no_vlm": None}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.exif_backup is True  # 默认值
    assert cfg.no_vlm is False  # 默认值
    assert "非法布尔值" not in caplog.text


def test_build_config_coerces_bool_from_file(tmp_path: Path) -> None:
    """M-7：配置文件来源（非仅 override）的布尔字符串同样被强转。"""
    from flashgaze.utils.config import build_config, load_config_file

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"no_vlm": "off", "dedup": "yes", "export": 1}), encoding="utf-8"
    )
    cfg = build_config(".", file_cfg=load_config_file(cfg_file))
    assert cfg.no_vlm is False
    assert cfg.dedup is True
    assert cfg.export is True


def test_build_config_bool_int_and_bool_passthrough() -> None:
    """M-7：int 0/1 按布尔解释；真正的 bool 原样放行（不告警、不改写）。"""
    from flashgaze.utils.config import build_config

    assert build_config(".", no_vlm=0).no_vlm is False
    assert build_config(".", no_vlm=1).no_vlm is True
    assert build_config(".", no_vlm=True).no_vlm is True
    assert build_config(".", no_vlm=False).no_vlm is False


def test_merge_env_allow_private_targets_false_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M-7 不改既有 env 行为：非真值字符串不进入配置（仍由默认 False 兜底）。"""
    from flashgaze.defaults import ENV_ALLOW_PRIVATE_TARGETS
    from flashgaze.utils.config import merge_env

    monkeypatch.setenv(ENV_ALLOW_PRIVATE_TARGETS, "false")
    assert "allow_private_targets" not in merge_env()
    monkeypatch.setenv(ENV_ALLOW_PRIVATE_TARGETS, "on")
    assert merge_env()["allow_private_targets"] is True


# ---------- vlm_temperature / vlm_seed（VLM 采样参数，可复现性）----------


def test_merge_env_vlm_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASHGAZE_VLM_TEMPERATURE / FLASHGAZE_VLM_SEED 合法值被读取。"""
    monkeypatch.setenv("FLASHGAZE_VLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("FLASHGAZE_VLM_SEED", "7")
    cfg = merge_env()
    assert cfg["vlm_temperature"] == 0.3
    assert cfg["vlm_seed"] == 7


def test_merge_env_invalid_vlm_sampling_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """非数字的采样参数 env 被忽略（不进 merge_env 结果，由默认值兜底）。"""
    monkeypatch.setenv("FLASHGAZE_VLM_TEMPERATURE", "abc")
    monkeypatch.setenv("FLASHGAZE_VLM_SEED", "abc")
    cfg = merge_env()
    assert "vlm_temperature" not in cfg
    assert "vlm_seed" not in cfg


def test_build_config_vlm_sampling_defaults() -> None:
    """默认 temperature=0.0 / seed=42（DEFAULT_VLM_TEMPERATURE / DEFAULT_VLM_SEED）。"""
    cfg = build_config("/tmp")
    assert cfg.vlm_temperature == 0.0
    assert cfg.vlm_seed == 42


def test_build_config_vlm_sampling_env_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 与 override 两条来源均可达。"""
    monkeypatch.setenv("FLASHGAZE_VLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("FLASHGAZE_VLM_SEED", "7")
    cfg = build_config("/tmp")
    assert cfg.vlm_temperature == 0.3
    assert cfg.vlm_seed == 7
    cfg2 = build_config("/tmp", vlm_temperature=0.9, vlm_seed=123)
    assert cfg2.vlm_temperature == 0.9
    assert cfg2.vlm_seed == 123


def test_build_config_vlm_sampling_string_coerced() -> None:
    """配置文件/override 传入字符串数字时强转（与 vlm_breaker_threshold 同契约）。"""
    assert build_config("/tmp", vlm_temperature="0.5").vlm_temperature == 0.5
    assert build_config("/tmp", vlm_seed="7").vlm_seed == 7


def test_build_config_vlm_temperature_clamped() -> None:
    """temperature 钳制到 [0.0, 2.0]。"""
    assert build_config("/tmp", vlm_temperature=99).vlm_temperature == 2.0
    assert build_config("/tmp", vlm_temperature=-1).vlm_temperature == 0.0


def test_build_config_vlm_temperature_nonfinite_falls_back_default() -> None:
    """temperature NaN/inf 非有限，回退默认 0.0，不抛异常。"""
    assert build_config("/tmp", vlm_temperature=float("nan")).vlm_temperature == 0.0
    assert build_config("/tmp", vlm_temperature=float("inf")).vlm_temperature == 0.0


def test_build_config_vlm_seed_invalid_falls_back_default() -> None:
    """seed 负数/非整数 float/bool 回退默认 42，不抛异常。"""
    assert build_config("/tmp", vlm_seed=-1).vlm_seed == 42
    assert build_config("/tmp", vlm_seed=7.5).vlm_seed == 42
    assert build_config("/tmp", vlm_seed=True).vlm_seed == 42


def test_build_config_file_null_vlm_sampling_disables_injection(tmp_path: Path) -> None:
    """配置文件 null = 不注入（Config 字段保留 None）——旧行为逃生舱。

    注意 overrides/env 语义中 None 是「不覆盖」，故 None 只能经配置文件 null 达成。
    """
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({"vlm_temperature": None, "vlm_seed": None}),
        encoding="utf-8",
    )
    cfg = build_config("/tmp", file_cfg=load_config_file(str(cfg_file)))
    assert cfg.vlm_temperature is None
    assert cfg.vlm_seed is None


def test_scoring_options_mirror_vlm_sampling_fields() -> None:
    """ScoringOptions 镜像 Config 新字段（逐字同名；默认 None=不覆盖下层配置）。"""
    from dataclasses import fields as dc_fields

    from flashgaze.models.options import ScoringOptions

    names = {f.name for f in dc_fields(ScoringOptions)}
    assert {"vlm_temperature", "vlm_seed"} <= names
    opts = ScoringOptions()
    assert opts.vlm_temperature is None
    assert opts.vlm_seed is None
    # None = 不覆盖：不进入 overrides，env/文件值不被顶掉
    assert "vlm_temperature" not in opts.to_config_kwargs()
    assert "vlm_seed" not in opts.to_config_kwargs()


# ---------- M-11：FLASHGAZE_CONFIG_FILE（配置文件层下沉 build_config，三入口一致）----------


def _write_m11_cfg_file(tmp_path: Path, data: dict[str, object]) -> str:
    """写一个最小 JSON 配置文件，返回路径字符串。"""
    cfg_file = tmp_path / "m11_cfg.json"
    cfg_file.write_text(json.dumps(data), encoding="utf-8")
    return str(cfg_file)


def test_build_config_env_config_file_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """正常：FLASHGAZE_CONFIG_FILE 指向的文件作为 file 层生效（MCP/WebUI 调用形态，无 file_cfg）。"""
    path = _write_m11_cfg_file(tmp_path, {"enable_noise": True, "timeout_sec": 77})
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", path)
    cfg = build_config("/tmp")
    assert cfg.enable_noise is True
    assert cfg.timeout_sec == 77


def test_file_cfg_applies_to_all_entries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """审查 M-11 建议用例：同一 env 配置文件在三种调用形态下均生效。

    - build_config(directory)：MCP _config_from / WebUI build_run_config 的调用形态
    - build_config(directory, file_cfg={})：CLI 无 --config-file 的调用形态
    - build_config(directory, file_cfg=显式加载)：CLI --config-file 的调用形态
    """
    path = _write_m11_cfg_file(tmp_path, {"enable_noise": True, "timeout_sec": 77})
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", path)
    assert build_config("/tmp").enable_noise is True
    assert build_config("/tmp", file_cfg={}).enable_noise is True
    explicit = build_config("/tmp", file_cfg=load_config_file(path))
    assert explicit.enable_noise is True
    assert explicit.timeout_sec == 77


def test_build_config_env_file_env_beats_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """反例：env 配置文件不得越过环境变量层——FLASHGAZE_MODEL 仍压过文件值。"""
    path = _write_m11_cfg_file(tmp_path, {"model": "file-model"})
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", path)
    monkeypatch.setenv("FLASHGAZE_MODEL", "env-model")
    assert build_config("/tmp").model == "env-model"


def test_build_config_explicit_file_cfg_wins_per_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """边界：显式 file_cfg（CLI --config-file）与 env 文件同层逐键合并，显式键优先。"""
    path = _write_m11_cfg_file(tmp_path, {"timeout_sec": 99, "enable_noise": True})
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", path)
    cfg = build_config("/tmp", file_cfg={"timeout_sec": 5})
    assert cfg.timeout_sec == 5
    assert cfg.enable_noise is True


def test_build_config_env_config_file_missing_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """异常：env 指向不存在的文件须告警（不得静默忽略），配置回落默认。"""
    import logging

    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", str(tmp_path / "nope.json"))
    with caplog.at_level(logging.WARNING):
        cfg = build_config("/tmp")
    assert "不存在" in caplog.text
    assert cfg.timeout_sec == default_config_dict()["timeout_sec"]


def test_build_config_env_config_file_corrupted_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """异常：env 指向损坏 JSON 须告警并回退默认。"""
    import logging

    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", str(bad))
    with caplog.at_level(logging.WARNING):
        cfg = build_config("/tmp")
    assert "读取或解析失败" in caplog.text
    assert cfg.timeout_sec == default_config_dict()["timeout_sec"]


def test_build_config_env_config_file_empty_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """边界：空串/纯空白视为未设置，不加载不告警。"""
    import logging

    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", "   ")
    with caplog.at_level(logging.WARNING):
        cfg = build_config("/tmp")
    assert "配置文件" not in caplog.text
    assert cfg.timeout_sec == default_config_dict()["timeout_sec"]


def test_build_config_no_default_path_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """反例：无默认路径自动发现——cwd 存在 config.json 而未显式指定时不得加载。"""
    import logging

    monkeypatch.delenv("FLASHGAZE_CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"enable_noise": True}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = build_config(str(tmp_path))
    assert cfg.enable_noise is False
    assert "配置文件" not in caplog.text


def test_load_config_file_not_exist_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """M-11 配套：配置文件不存在须告警（CLI --config-file 与 FLASHGAZE_CONFIG_FILE 同路径）。"""
    import logging

    with caplog.at_level(logging.WARNING):
        assert load_config_file(tmp_path / "nope.json") == {}
    assert "不存在" in caplog.text

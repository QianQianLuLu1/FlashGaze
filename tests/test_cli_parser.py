"""CLIParser 单元测试。

验证参数解析与配置优先级：CLI > env > file > default。
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
from dataclasses import fields as dc_fields
from pathlib import Path

import pytest

from flashgaze.cli.entry import (
    UnsafeOutputPathError,
    _cmd_score,
    _safe_output_path,
)
from flashgaze.cli.parser import CLIParser
from flashgaze.models.schemas import Config, ExitCode
from flashgaze.utils.logging import get_logger


def _parse(argv: list[str]) -> Config:
    return CLIParser().parse(argv)


# ---------- 基础参数 ----------


def test_parse_basic_directory() -> None:
    cfg = _parse(["./photos"])
    assert cfg.directory == "./photos"
    assert cfg.top == 30  # 默认
    assert cfg.no_vlm is False
    assert cfg.export is False


def test_parse_top_override() -> None:
    cfg = _parse(["./photos", "--top", "50"])
    assert cfg.top == 50


def test_parse_threshold() -> None:
    cfg = _parse(["./photos", "--threshold", "75.5"])
    assert cfg.threshold == 75.5


def test_parse_export_and_move() -> None:
    cfg = _parse(["./photos", "--export", "--move"])
    assert cfg.export is True
    assert cfg.move is True


def test_parse_json_csv_flags() -> None:
    cfg = _parse(["./photos", "--json", "--csv"])
    assert cfg.output_json is True
    assert cfg.output_csv is True


def test_parse_no_vlm() -> None:
    cfg = _parse(["./photos", "--no-vlm"])
    assert cfg.no_vlm is True


def test_parse_no_downscale_default_false() -> None:
    """默认 no_downscale=False，即启用降采样。"""
    cfg = _parse(["./photos"])
    assert cfg.no_downscale is False


def test_parse_no_downscale_flag() -> None:
    """--no-downscale 被正确解析为 True。"""
    cfg = _parse(["./photos", "--no-downscale"])
    assert cfg.no_downscale is True


def test_parse_enable_composition() -> None:
    cfg = _parse(["./photos", "--enable-composition"])
    assert cfg.enable_composition is True


def test_parse_output_path() -> None:
    cfg = _parse(["./photos", "--output", "report.json"])
    assert cfg.output_path == "report.json"


def test_parse_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    # workers 会被钳制到 min(cpu_count, 16)；钉住核数，本用例才只检验解析本身而非运行机器
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    cfg = _parse(["./photos", "--workers", "8"])
    assert cfg.workers == 8


# ---------- VLM 扩展：--vlm-provider / --scene 参数（M3/M7）----------


def test_parse_vlm_provider_default_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 --vlm-provider 时默认 qwen。"""
    monkeypatch.delenv("FLASHGAZE_VLM_PROVIDER", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.vlm_provider == "qwen"


def test_parse_vlm_provider_openai() -> None:
    """--vlm-provider openai 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "openai"])
    assert cfg.vlm_provider == "openai"


def test_parse_vlm_provider_anthropic() -> None:
    """--vlm-provider anthropic 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "anthropic"])
    assert cfg.vlm_provider == "anthropic"


def test_parse_vlm_provider_ollama() -> None:
    """--vlm-provider ollama 被正确解析。"""
    cfg = _parse(["./photos", "--vlm-provider", "ollama"])
    assert cfg.vlm_provider == "ollama"


def test_parse_vlm_provider_invalid_choice_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """--vlm-provider 不在 choices 中时 argparse 报错（exit code=2）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["./photos", "--vlm-provider", "claude"])
    assert exc_info.value.code == 2


def test_parse_scene_default_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 --scene 时默认 auto。"""
    monkeypatch.delenv("FLASHGAZE_SCENE", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.scene == "auto"


def test_parse_scene_portrait() -> None:
    """--scene portrait 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "portrait"])
    assert cfg.scene == "portrait"


def test_parse_scene_landscape() -> None:
    """--scene landscape 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "landscape"])
    assert cfg.scene == "landscape"


def test_parse_scene_still_life() -> None:
    """--scene still_life 被正确解析。"""
    cfg = _parse(["./photos", "--scene", "still_life"])
    assert cfg.scene == "still_life"


def test_parse_scene_invalid_choice_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """--scene 不在 choices 中时 argparse 报错（exit code=2）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["./photos", "--scene", "macro"])
    assert exc_info.value.code == 2


def test_parse_vlm_provider_and_scene_combined() -> None:
    """同时传 --vlm-provider 与 --scene。"""
    cfg = _parse(
        [
            "./photos",
            "--vlm-provider",
            "openai",
            "--scene",
            "portrait",
        ]
    )
    assert cfg.vlm_provider == "openai"
    assert cfg.scene == "portrait"


def test_priority_cli_vlm_provider_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI --vlm-provider 优先于环境变量。"""
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "anthropic")
    cfg = _parse(["./photos", "--vlm-provider", "openai"])
    assert cfg.vlm_provider == "openai"


def test_priority_env_vlm_provider_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 FLASHGAZE_VLM_PROVIDER 优先于默认值。"""
    monkeypatch.setenv("FLASHGAZE_VLM_PROVIDER", "ollama")
    cfg = _parse(["./photos"])
    assert cfg.vlm_provider == "ollama"


def test_priority_env_scene_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 FLASHGAZE_SCENE 优先于默认值。"""
    monkeypatch.setenv("FLASHGAZE_SCENE", "landscape")
    cfg = _parse(["./photos"])
    assert cfg.scene == "landscape"


# ---------- 配置优先级 ----------


def test_priority_cli_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI 参数优先于环境变量。"""
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-key")
    monkeypatch.setenv("FLASHGAZE_MODEL", "env-model")
    cfg = _parse(["./photos", "--api-key", "cli-key", "--model", "cli-model"])
    assert cfg.api_key == "cli-key"
    assert cfg.model == "cli-model"


def test_priority_env_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """环境变量优先于配置文件。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps({"api_key": "file-key", "model": "file-model"}), encoding="utf-8"
    )
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-key")
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.api_key == "env-key"
    assert cfg.model == "file-model"  # env 未设置 model，回退到 file


def test_priority_file_over_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """配置文件优先于默认值。"""
    # 同上：钉住核数，否则 workers=12 在少核机器上会被钳制，掩盖真正要验的优先级语义
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps(
            {
                "api_base": "https://custom.api/v1",
                "model": "custom-model",
                "workers": 12,
            }
        ),
        encoding="utf-8",
    )
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.api_base == "https://custom.api/v1"
    assert cfg.model == "custom-model"
    assert cfg.workers == 12


# ---------- 配置优先级：bool 旗未传 = 不覆盖（四旗 default=None 回归）----------


@pytest.mark.parametrize(
    ("file_key", "file_value", "attr", "expected"),
    [
        ("exif", True, "exif", True),
        ("output_xlsx", True, "output_xlsx", True),
        ("enable_plugins", True, "enable_plugins", True),
        ("exif_backup", False, "exif_backup", False),
    ],
)
def test_priority_file_bool_over_default_when_flag_absent(
    tmp_path: Path,
    file_key: str,
    file_value: bool,
    attr: str,
    expected: bool,
) -> None:
    """配置文件设置 exif/output_xlsx/enable_plugins/exif_backup 且 CLI 未传旗 → 文件值生效。

    回归：四旗曾缺 default=None，未传旗恒以 False 进入 overrides 覆盖文件值
    （--no-exif-backup 侧则恒以 exif_backup=True 覆盖），配置文件布尔键静默失效。
    """
    config_file = tmp_path / "cfg.json"
    config_file.write_text(json.dumps({file_key: file_value}), encoding="utf-8")
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert getattr(cfg, attr) is expected


@pytest.mark.parametrize(
    ("cli_flag", "attr"),
    [
        ("--exif", "exif"),
        ("--xlsx", "output_xlsx"),
        ("--enable-plugins", "enable_plugins"),
        ("--no-exif-backup", "exif_backup"),
    ],
)
def test_priority_cli_bool_flag_over_file(tmp_path: Path, cli_flag: str, attr: str) -> None:
    """显式传旗仍覆盖配置文件（exif_backup 经 --no-exif-backup 反向归一为 False）。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps(
            {"exif": False, "output_xlsx": False, "enable_plugins": False, "exif_backup": True}
        ),
        encoding="utf-8",
    )
    cfg = _parse(["./photos", "--config-file", str(config_file), cli_flag])
    if attr == "exif_backup":
        assert cfg.exif_backup is False
    else:
        assert getattr(cfg, attr) is True


def test_bool_flags_fall_back_to_defaults_when_nothing_provided() -> None:
    """无任何配置时四旗回落 Config 默认值（exif_backup 默认 True，其余 False）。"""
    cfg = _parse(["./photos"])
    assert cfg.exif is False
    assert cfg.exif_backup is True
    assert cfg.output_xlsx is False
    assert cfg.enable_plugins is False


def test_score_parser_config_bool_flags_default_none() -> None:
    """结构护栏：子解析器中 dest 为 Config 字段的 store_true 旗必须 default=None。

    「未传旗 = None = 不覆盖下层配置」是 CLI > env > file > default 链路成立的
    前提；新增旗漏写 default=None 会再次让配置文件/env 的布尔值静默失效。
    --apply/--force 非 Config 字段（cleanup 专用开关，False 即"未确认"），不在约束内。
    """
    config_fields = {f.name for f in dc_fields(Config)}
    for subcommand in ("score", "cleanup"):
        subparsers = CLIParser().parser._subparsers
        assert subparsers is not None  # add_subparsers 在构建时必然已调用
        choices = subparsers._group_actions[0].choices
        assert isinstance(choices, dict)  # 子命令名 -> 子解析器
        sub = choices[subcommand]
        violations = [
            a.dest
            for a in sub._actions
            if isinstance(a, argparse._StoreTrueAction)
            and (a.dest in config_fields or a.dest == "no_exif_backup")
            and a.default is not None
        ]
        assert violations == [], f"{subcommand} 子解析器以下旗缺 default=None: {violations}"


def test_env_api_key_used_when_no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-only-key")
    cfg = _parse(["./photos"])
    assert cfg.api_key == "env-only-key"


def test_defaults_when_nothing_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    """无任何配置时使用 defaults.py 的默认值。"""
    # 同上：钉住核数，否则 DEFAULT_WORKERS=4 在 2 核 CI 上被钳制成 2，掩盖真正要验的「默认值」语义
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    monkeypatch.delenv("FLASHGAZE_API_BASE", raising=False)
    monkeypatch.delenv("FLASHGAZE_MODEL", raising=False)
    cfg = _parse(["./photos"])
    assert cfg.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen-vl-max"
    assert cfg.workers == 4
    assert cfg.timeout_sec == 30
    assert cfg.api_key is None


def test_config_file_not_exist_uses_defaults(tmp_path: Path) -> None:
    """配置文件不存在时不报错，用默认值。"""
    cfg = _parse(["./photos", "--config-file", str(tmp_path / "nope.json")])
    assert cfg.model == "qwen-vl-max"


def test_config_file_corrupted_uses_defaults(tmp_path: Path) -> None:
    """配置文件格式错误时用默认值，不抛异常。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    cfg = _parse(["./photos", "--config-file", str(bad)])
    assert cfg.model == "qwen-vl-max"


def test_weights_from_config_file(tmp_path: Path) -> None:
    """权重从配置文件加载。"""
    config_file = tmp_path / "cfg.json"
    config_file.write_text(
        json.dumps({"weights": {"sharpness": 0.7, "exposure": 0.3}}),
        encoding="utf-8",
    )
    cfg = _parse(["./photos", "--config-file", str(config_file)])
    assert cfg.weights == {"sharpness": 0.7, "exposure": 0.3}


def test_weights_cli_with_composition() -> None:
    """--weights 含 composition（且 --enable-composition）时三键归一化（F-05）。"""
    cfg = _parse(
        [
            "./photos",
            "--enable-composition",
            "--weights",
            '{"sharpness": 0.5, "exposure": 0.3, "composition": 0.2}',
        ]
    )
    assert cfg.weights["sharpness"] == 0.5
    assert cfg.weights["exposure"] == 0.3
    assert cfg.weights["composition"] == 0.2


def test_weights_cli_composition_normalized() -> None:
    """--weights 非归一化输入时正确归一化（F-05）。"""
    cfg = _parse(
        [
            "./photos",
            "--enable-composition",
            "--weights",
            '{"sharpness": 3, "exposure": 1, "composition": 1}',
        ]
    )
    assert cfg.weights["sharpness"] == 0.6  # 3/5
    assert cfg.weights["exposure"] == 0.2  # 1/5
    assert cfg.weights["composition"] == 0.2  # 1/5


# ---------- 参数错误 ----------


def test_missing_directory_returns_param_error(capsys: pytest.CaptureFixture[str]) -> None:
    """缺必选参数 directory 时返回 PARAM_ERROR。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse([])
    # argparse 缺必选参数时 exit code=2
    assert exc_info.value.code == 2


def test_version_flag_exits_zero() -> None:
    """--version 正常退出（code=0）。"""
    with pytest.raises(SystemExit) as exc_info:
        _parse(["--version"])
    assert exc_info.value.code == 0


# ---------- 入口装配健壮性（#12-2 / #12-4）----------


def test_cmd_score_assembly_error_maps_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """#12-2 回归：配置装配抛非 SystemExit 异常时收敛为 CONFIG_ERROR，而非裸 traceback。"""
    clp = CLIParser()
    ns = clp.parse_namespace(["./photos"])

    def _boom(self: CLIParser, ns: argparse.Namespace) -> Config:
        raise ValueError("unexpected assembly error")

    monkeypatch.setattr(CLIParser, "_config_from_ns", _boom)
    code = _cmd_score(clp, ns, get_logger())
    assert code == ExitCode.CONFIG_ERROR


def test_safe_output_path_resolves_inside_workspace(tmp_path: Path) -> None:
    """#12-4 回归：工作区内的输出路径被 resolve 规范化。"""
    target = tmp_path / "sub" / "out.json"
    target.parent.mkdir()
    assert _safe_output_path(str(target), tmp_path) == target.resolve()


def test_safe_output_path_escape_rejected(
    tmp_path: Path,
) -> None:
    """#12-4 回归：越出工作区的路径一律抛 UnsafeOutputPathError（硬拒绝，不再仅告警）。"""
    outside = tmp_path.parent / "escape.json"
    with pytest.raises(UnsafeOutputPathError):
        _safe_output_path(str(outside), tmp_path)


def test_safe_output_path_absolute_outside_rejected(
    tmp_path: Path,
) -> None:
    """#12-4 回归：workspace 之外的绝对路径同样被拒绝（杜绝越界覆盖）。"""
    outside = tmp_path.parent / "escape.json"
    with pytest.raises(UnsafeOutputPathError):
        _safe_output_path(str(outside.resolve()), tmp_path)


def test_safe_output_path_none_when_empty() -> None:
    """未提供输出路径时返回 None（仅打印 stdout）。"""
    assert _safe_output_path(None, ".") is None
    assert _safe_output_path("", ".") is None


# ---------- cleanup 子命令：--force 开关（FIX #sec-threshold）----------


def test_cleanup_force_flag_default_false(tmp_path: Path) -> None:
    """cleanup 子命令默认不带 force（护栏保持启用）。"""
    ns = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm"])
    assert getattr(ns, "force", False) is False


def test_cleanup_force_flag_parsed(tmp_path: Path) -> None:
    """显式 --force 被解析为 ns.force=True（透传给 run_cleanup）。"""
    ns = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm", "--apply", "--force"])
    assert ns.force is True
    assert ns.apply is True


def test_cleanup_confirm_fingerprint_flag(tmp_path: Path) -> None:
    """--confirm-fingerprint 解析为 ns.confirm_fingerprint（force 的放行凭证）。"""
    ns = CLIParser().parse_namespace(
        ["cleanup", str(tmp_path), "--no-vlm", "--apply", "--force", "--confirm-fingerprint", "abc123def456"]
    )
    assert ns.confirm_fingerprint == "abc123def456"
    # 默认 None（未提供指纹 = 未核对，核心层据此拦截）
    ns2 = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm", "--apply", "--force"])
    assert ns2.confirm_fingerprint is None


def test_cleanup_no_recycle_flag_default_false(tmp_path: Path) -> None:
    """--no-recycle 默认 False（回收站默认开启），显式传入才置 True。"""
    ns = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm"])
    assert ns.no_recycle is False
    ns2 = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm", "--no-recycle"])
    assert ns2.no_recycle is True


def test_cleanup_guard_min_sample_flag(tmp_path: Path) -> None:
    """--guard-min-sample 解析为 ns.cleanup_guard_min_sample；未传默认 None（不覆盖）。"""
    ns = CLIParser().parse_namespace(["cleanup", str(tmp_path), "--no-vlm"])
    assert ns.cleanup_guard_min_sample is None
    ns2 = CLIParser().parse_namespace(
        ["cleanup", str(tmp_path), "--no-vlm", "--guard-min-sample", "3"]
    )
    assert ns2.cleanup_guard_min_sample == 3


def test_restore_subcommand_registered(tmp_path: Path) -> None:
    """restore 已登记为子命令；否则兼容垫片会把它误路由到 score。"""
    from flashgaze.cli.parser import _SUBCOMMANDS

    assert "restore" in _SUBCOMMANDS
    ns = CLIParser().parse_namespace(["restore", "some.jsonl", "--dry-run"])
    assert ns.command == "restore"
    assert ns.manifest == "some.jsonl"
    assert ns.dry_run is True


# ---------- M-26：--api-key-file（密钥不进进程命令行）----------


def test_api_key_file_reads_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正常：从文件读取密钥，首尾空白（含尾部换行）被 strip。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    key_file = tmp_path / "secret.key"
    key_file.write_text("sk-from-file\n", encoding="utf-8")
    cfg = _parse(["./photos", "--api-key-file", str(key_file)])
    assert cfg.api_key == "sk-from-file"


def test_api_key_file_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常：`--api-key-file -` 从 stdin 读取（可用于管道/密钥管理器注入）。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-from-stdin\n"))
    cfg = _parse(["./photos", "--api-key-file", "-"])
    assert cfg.api_key == "sk-from-stdin"


def test_api_key_file_missing_exits(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """异常：文件不存在 → 参数错误中止（不静默回退为无密钥）。"""
    missing = tmp_path / "nope.key"
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        _parse(["./photos", "--api-key-file", str(missing)])
    assert exc.value.code == 2
    # 中止原因必须是「读取失败」，而非 argparse 未识别参数
    assert "api-key-file" in caplog.text


def test_api_key_file_empty_exits(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """异常：空文件（或纯空白）→ 中止，避免装配出空密钥误导后续鉴权报错。"""
    key_file = tmp_path / "empty.key"
    key_file.write_text("   \n", encoding="utf-8")
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        _parse(["./photos", "--api-key-file", str(key_file)])
    assert exc.value.code == 2
    assert "为空" in caplog.text


def test_api_key_and_api_key_file_are_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """异常：--api-key 与 --api-key-file 同传 → 中止（拒绝二义，不静默择一）。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)
    key_file = tmp_path / "secret.key"
    key_file.write_text("sk-from-file", encoding="utf-8")
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        _parse(["./photos", "--api-key", "cli-key", "--api-key-file", str(key_file)])
    assert exc.value.code == 2
    assert "二选一" in caplog.text


def test_api_key_file_absent_does_not_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """反例：未传 --api-key-file 时，既有 env 密钥原样生效（新参数零副作用）。"""
    monkeypatch.setenv("FLASHGAZE_API_KEY", "env-only-key")
    cfg = _parse(["./photos"])
    assert cfg.api_key == "env-only-key"

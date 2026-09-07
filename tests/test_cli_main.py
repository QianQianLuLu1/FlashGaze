"""CLI main() 进程内分支测试。

test_cli_e2e.py 用 subprocess 真实调用（验证进程边界与退出码保真），但
pytest-cov >= 7.0 不再测量子进程，subprocess 用例对覆盖率零贡献；本模块
进程内直调 flashgaze.cli.entry.main()，覆盖 _cmd_score/_cmd_cleanup 的
成功与全部错误收敛路径（返回码映射 FIX #12-2/#12-3 的回归面）。

失败注入统一走 monkeypatch（stub Exporter / make_scorer / run_cleanup /
sys.modules 模块桩），不依赖真实网络或可选 extras 是否安装，任何环境结果一致。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import runpy
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from flashgaze.cli.entry import (
    UnsafeOutputPathError,
    _cleanup_output_tmp,
    _render_cleanup_report,
    _safe_output_path,
    main,
)
from flashgaze.cli.parser import CLIParser
from flashgaze.core.cleanup import CleanupError, pending_fingerprint
from flashgaze.core.cv_engine import BrisqueIntegrityError
from flashgaze.models.schemas import Config, ExitCode, ImageScore


@pytest.fixture
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉环境里的 API Key，让「缺 key」校验可控。"""
    monkeypatch.delenv("FLASHGAZE_API_KEY", raising=False)


# ---------- stub 工具 ----------


class _StubExporter:
    """Exporter 桩：默认全成功，可在子类里按需抛异常。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        # H-9：_cmd_score 收尾会读导出失败明细，桩须具备同名字段（默认「零失败」）
        self.last_failures: list[dict[str, str]] = []
        self.last_expected = 0

    def export_images(self, scored: list[ImageScore], export_dir: str) -> int:
        self.last_expected = sum(1 for s in scored if s.selected and s.error is None)
        return len(scored)

    def build_report(
        self,
        scored: list[ImageScore],
        elapsed_ms: int,
        exif_results: list[Any] | None = None,
        export: Any | None = None,
        # 镜像 Exporter.build_report 真实契约（phase1_stats / vlm_sampling 为新增
        # 可选参数），否则 _emit_json 传参时桩抛 TypeError 走 INTERNAL_ERROR 分支
        phase1_stats: dict[str, int] | None = None,
        vlm_sampling: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"status": "success", "images": []}

    def write_manifest(self, scored: list[ImageScore], fmt: str, path: str) -> None:
        Path(path).write_text("stub", encoding="utf-8")


class _ExporterExportFails(_StubExporter):
    def export_images(self, scored: list[ImageScore], export_dir: str) -> int:
        raise OSError("disk full")


class _ExporterPartialExport(_StubExporter):
    """H-9：一部分图导出失败（last_failures 非空），导出数少于预期入选数。"""

    def export_images(self, scored: list[ImageScore], export_dir: str) -> int:
        self.last_expected = sum(1 for s in scored if s.selected and s.error is None)
        self.last_failures = [{"file": "sharp.jpg", "path": "sharp.jpg", "error": "disk full"}]
        return 0


class _ExporterOverReports(_StubExporter):
    """反例（R2）：导出数多于预期入选数，但无任何失败记录。

    复现 `_StubExporter.export_images` 返回 len(scored)（含未入选图）的形态——
    若改用「exported + len(failures) != 预期数」等式判定，此形态会被误判为失败。
    """

    def export_images(self, scored: list[ImageScore], export_dir: str) -> int:
        self.last_expected = 1
        return len(scored)


class _ExporterStaleFailures(_StubExporter):
    """反例（R3）：last_failures 带残留值但本次并未导出（--export 未启用）。"""

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.last_failures = [{"file": "stale.jpg", "path": "stale.jpg", "error": "stale"}]


class _ExporterReportFails(_StubExporter):
    def build_report(
        self,
        scored: list[ImageScore],
        elapsed_ms: int,
        exif_results: list[Any] | None = None,
        export: Any | None = None,
        phase1_stats: dict[str, int] | None = None,
        vlm_sampling: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise OSError("stdout broken")


class _ExporterCsvFails(_StubExporter):
    def write_manifest(self, scored: list[ImageScore], fmt: str, path: str) -> None:
        raise OSError("csv unwritable")


class _ScorerStub:
    """HybridScorer 桩：score_paths 返回可控结果或抛异常。"""

    def __init__(
        self,
        result: list[ImageScore] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.result = result if result is not None else []
        self.exc = exc

    def score_paths(
        self,
        images: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ImageScore]:
        if self.exc is not None:
            raise self.exc
        return self.result


def _cleanup_result(
    *,
    blocked: list[dict[str, Any]] | None = None,
    deleted: list[dict[str, Any]] | None = None,
    pending: list[dict[str, Any]] | None = None,
    unevaluated: list[dict[str, Any]] | None = None,
    summary_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 run_cleanup 返回结构（字段契约见 cleanup.classify_and_delete）。

    summary_extra 用于补充新增 summary 键（如 vlm_applied / vlm_degraded），
    未提供时保持旧形状——渲染层对新键必须用 .get() 容错。
    """
    blocked = blocked or []
    deleted = deleted or []
    pending = pending or []
    unevaluated = unevaluated or []
    summary: dict[str, Any] = {
        "workspace": "/ws",
        "total": 4,
        "selected": 1,
        "to_delete": len(pending) or len(deleted),
        "deleted": len(deleted),
        "blocked": len(blocked),
        "unevaluated": len(unevaluated),
        "mode": "dry_run" if pending else "actual_delete",
    }
    if summary_extra:
        summary.update(summary_extra)
    return {
        "summary": summary,
        "pending_delete": pending,
        "deleted": deleted,
        "blocked": blocked,
        "unevaluated": unevaluated,
        "kept": [],
    }


def _module_stub(cls_dict: dict[str, Any]) -> types.ModuleType:
    """伪造一个可被 `from x import Y` 的模块（配合 monkeypatch.setitem sys.modules）。"""
    mod = types.ModuleType("stub")
    for name, cls in cls_dict.items():
        setattr(mod, name, cls)
    return mod


# ---------- main()：参数解析与 SystemExit 映射 ----------


def test_main_version_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    """--version：argparse 抛 SystemExit(0)，映射为 SUCCESS。"""
    assert main(["--version"]) == ExitCode.SUCCESS
    assert "flashgaze" in capsys.readouterr().out


def test_main_score_and_cleanup_help_render_dependency_hints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """score/cleanup --help 可完整渲染且声明输出开关依赖。

    回归：help 文本含裸 ``%``（如「95% 比例护栏」）时 argparse 的
    ``_expand_help`` 做 ``% params`` 格式化直接抛 ValueError，--help 崩溃；
    同时锁定输出路径旗标的「需搭配」依赖声明与实现一致（文档契约）。
    """
    assert main(["score", "--help"]) == ExitCode.SUCCESS
    score_help = capsys.readouterr().out
    assert "需搭配 --json" in score_help
    assert "需搭配 --csv" in score_help
    assert "需搭配 --xlsx" in score_help
    assert score_help.count("需搭配 --export") == 2  # --export-dir 与 --move 两处依赖声明（M-07）
    assert "95%" in score_help  # ``%%`` 转义后渲染为字面 %
    assert main(["cleanup", "--help"]) == ExitCode.SUCCESS
    cleanup_help = capsys.readouterr().out
    assert "报告写入文件（需搭配 --json）" in cleanup_help
    assert "95%" in cleanup_help


def test_main_argparse_error_returns_param_error(photo_dir: str) -> None:
    """非法参数（--top 非数字）：argparse 抛 SystemExit(2) → PARAM_ERROR。"""
    assert main([photo_dir, "--top", "abc"]) == ExitCode.PARAM_ERROR


def test_main_score_top_zero_sysexit_returns_param_error(photo_dir: str) -> None:
    """--top 0 在 _config_from_ns 内 sys.exit(2)，穿透 _cmd_score 由 main 映射。"""
    assert main([photo_dir, "--no-vlm", "--top", "0"]) == ExitCode.PARAM_ERROR


def test_main_threshold_out_of_range_returns_param_error(photo_dir: str) -> None:
    """--threshold 越界（>100）同样走 sys.exit(2) → PARAM_ERROR。"""
    assert main([photo_dir, "--no-vlm", "--threshold", "101"]) == ExitCode.PARAM_ERROR


# ---------- _cmd_score：成功路径 ----------


def test_main_score_success_json_csv_export(
    photo_dir: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """全开关成功路径：--json/--output/--csv/--export/--verbose → SUCCESS 且产物齐全。"""
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"
    export_dir = tmp_path / "export"
    code = main(
        [
            photo_dir,
            "--no-vlm",
            "--top",
            "2",
            "--json",
            "--output",
            str(out_json),
            "--csv",
            "--csv-output",
            str(out_csv),
            "--export",
            "--export-dir",
            str(export_dir),
            "--verbose",
        ]
    )
    assert code == ExitCode.SUCCESS
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert out_csv.exists()
    assert len(list(export_dir.iterdir())) == 2
    # stdout 只有 JSON（Agent 消费契约）
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["status"] == "success"


def test_main_score_csv_default_in_workspace(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--csv 不传 --csv-output 时落到 DEFAULT_CSV_OUTPUT（被扫描目录内，按 workspace 解析）。"""
    # 把 CWD 设到 workspace 的子目录，以区分"相对 workspace"与"相对 CWD"。
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    code = main([photo_dir, "--no-vlm", "--top", "1", "--csv"])
    assert code == ExitCode.SUCCESS
    # 默认文件名解析基准为 workspace（被扫描目录），故落在 photo_dir 而非 CWD。
    assert (Path(photo_dir) / "flashgaze_result.csv").exists()
    assert not (cwd / "flashgaze_result.csv").exists()


def test_main_score_json_stdout_only(photo_dir: str, capsys: pytest.CaptureFixture[str]) -> None:
    """--json 不带 --output：仅打印 stdout，不落盘。"""
    code = main([photo_dir, "--no-vlm", "--top", "1", "--json"])
    assert code == ExitCode.SUCCESS
    assert json.loads(capsys.readouterr().out)["status"] == "success"


# ---------- _cmd_score：错误收敛路径 ----------


def test_main_score_empty_dir_returns_no_images(tmp_path: Path) -> None:
    """空目录 → NO_IMAGES。"""
    assert main([str(tmp_path), "--no-vlm"]) == ExitCode.NO_IMAGES


def test_main_score_missing_api_key_returns_config_error(photo_dir: str, no_api_key: None) -> None:
    """未禁用 VLM 且缺 key → CONFIG_ERROR（scorer 构建前拦截，无网络风险）。"""
    assert main([photo_dir, "--top", "1"]) == ExitCode.CONFIG_ERROR


def test_main_score_config_assembly_error(photo_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """配置装配抛非 SystemExit 异常 → 统一收敛 CONFIG_ERROR（FIX #12-2）。"""

    def _raise(self: CLIParser, ns: argparse.Namespace) -> Config:
        raise ValueError("boom")

    monkeypatch.setattr(CLIParser, "_config_from_ns", _raise)
    assert main([photo_dir, "--no-vlm"]) == ExitCode.CONFIG_ERROR


def test_main_score_scoring_raises_returns_image_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """score_paths 抛异常 → IMAGE_ERROR，不向调用方裸抛。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer",
        lambda config: _ScorerStub(exc=RuntimeError("cv crash")),
    )
    assert main([photo_dir, "--no-vlm"]) == ExitCode.IMAGE_ERROR


def test_main_score_empty_result_returns_no_images(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """评分返回空列表 → NO_IMAGES。"""
    monkeypatch.setattr("flashgaze.cli.entry.make_scorer", lambda config: _ScorerStub(result=[]))
    assert main([photo_dir, "--no-vlm"]) == ExitCode.NO_IMAGES


def test_main_score_export_oserror_returns_export_error(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """导出阶段 OSError → EXPORT_ERROR。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterExportFails)
    code = main([photo_dir, "--no-vlm", "--export", "--export-dir", str(tmp_path / "e")])
    assert code == ExitCode.EXPORT_ERROR


def test_main_score_export_dir_outside_workspace_rejected(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """越界 export_dir 与 --output 类统一硬拒绝（原 M2 仅 warning 放行已废弃）。

    断言：① 退出码 PARAM_ERROR（sys.exit(2) 经 main() 的 except SystemExit 收敛）；
    ② 错误日志含「拒绝越界」；③ export_images 不再被调用。
    """
    calls: dict[str, Any] = {}

    class _CaptureExporter(_StubExporter):
        def export_images(self, scored: list[ImageScore], export_dir: str) -> int:
            calls["export_dir"] = export_dir
            return len(scored)

    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _CaptureExporter)
    # 指向 photo_dir（=tmp_path）的兄弟目录，明确越出 workspace，绝对路径
    outside = tmp_path.parent / "escape_dir"
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--export", "--export-dir", str(outside)])
    assert code == ExitCode.PARAM_ERROR
    assert any("拒绝越界" in r.message for r in caplog.records)
    assert calls == {}  # 导出不执行


def test_main_score_export_dir_relative_resolves_to_workspace(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-1 回归：相对 --export-dir 以被扫描目录（workspace）为基准解析，
    而非落盘时的 CWD——校验与落盘同源，CWD≠workspace 时导出仍落在 workspace 内。"""
    # CWD 切到 workspace 之外：N-1 前相对 export_dir 按当时 CWD 解析，会落盘到这里
    other_cwd = tmp_path.parent / "fg_n1_cwd"
    other_cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(other_cwd)

    code = main([photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", "精选"])

    assert code == ExitCode.SUCCESS
    exported = Path(photo_dir) / "精选"
    assert exported.is_dir()
    assert any(exported.iterdir())  # 导出图落在 workspace/精选
    assert not (other_cwd / "精选").exists()  # 不再按 CWD 落盘


# ---------- _cmd_score：H-9 导出部分失败不再静默成功 ----------


def test_main_score_partial_export_returns_export_error(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """H-9（P0 序 8）：部分导出失败不得返回 0 —— 映射为 EXPORT_ERROR 并留响亮日志。

    此前 _cmd_score 调用 export_images 后既不读 last_failures 也不比对入选数，
    「声称导出 30 张、实际 12 张」以退出码 0 收场，Agent 无法区分「全部成功」
    与「大面积失败」，直接违背失败路径不得返回 0 的基线。
    """
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterPartialExport)
    with caplog.at_level(logging.ERROR):
        code = main(
            [photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(tmp_path / "e")]
        )
    assert code == ExitCode.EXPORT_ERROR
    assert any("导出部分失败" in r.message for r in caplog.records)


def test_main_score_full_export_returns_success(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对照：零失败导出 → 仍为 SUCCESS，导出路径的退出码语义不变。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _StubExporter)
    code = main(
        [photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(tmp_path / "e")]
    )
    assert code == ExitCode.SUCCESS


def test_main_score_export_count_mismatch_without_failures_stays_success(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """反例（R2）：导出数 ≠ 预期入选数但无失败记录 → 仅告警，退出码仍 SUCCESS。

    护栏：若改用「exported + len(failures) != 预期入选数」等式作判据，本形态
    （多报导出数、零失败）会被误判为失败——退出码因此凭空非 0。
    """
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterOverReports)
    with caplog.at_level(logging.WARNING):
        code = main(
            [photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(tmp_path / "e")]
        )
    assert code == ExitCode.SUCCESS
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_main_score_without_export_ignores_exporter_state(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例（R3）：未启用 --export 时导出根本未发生，退出码不受失败状态影响。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterStaleFailures)
    assert main([photo_dir, "--no-vlm", "--top", "1"]) == ExitCode.SUCCESS


def test_export_failure_takes_precedence_over_exif_error(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """H-9：导出与 EXIF 同时部分失败 → 退出码取 EXPORT_ERROR(5)。

    导出是用户显式要求的主产物，优先级高于 EXIF 元数据写入（7）；两条 ERROR
    日志都必须出现，保证两类失败都可见。
    """

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            pass

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            return [SimpleNamespace(ok=False, path=s.path, error="boom") for s in scored]

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterPartialExport)
    with caplog.at_level(logging.ERROR):
        code = main(
            [
                photo_dir,
                "--no-vlm",
                "--top",
                "1",
                "--exif",
                "--export",
                "--export-dir",
                str(tmp_path / "e"),
            ]
        )
    assert code == ExitCode.EXPORT_ERROR
    assert any("导出部分失败" in r.message for r in caplog.records)
    assert any("EXIF" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("flags", "filename"),
    [
        (("--json", "--output"), "out.json"),
        (("--csv", "--csv-output"), "out.csv"),
        (("--xlsx", "--xlsx-output"), "out.xlsx"),
    ],
)
def test_main_score_output_path_outside_workspace_rejected(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    flags: tuple[str, str],
    filename: str,
) -> None:
    """#12-4 回归（main 级）：越界 --output/--csv-output/--xlsx-output 硬拒绝。

    此前只有异常层用例（pytest.raises），未锁定进程内 main() 的最终返回码；
    sys.exit(2) 应经 main() 收敛为 PARAM_ERROR（=1），且目标文件不落盘。
    xlsx 校验先于 openpyxl lazy import，无需该可选依赖。
    """
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _StubExporter)
    # 指向 photo_dir（=tmp_path）的兄弟目录，明确越出 workspace，绝对路径
    outside = tmp_path.parent / filename
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", *flags, str(outside)])
    assert code == ExitCode.PARAM_ERROR
    assert any("拒绝越界" in r.message for r in caplog.records)
    assert not outside.exists()  # 越界文件不落盘


def test_main_score_json_oserror_returns_export_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JSON 输出（build_report/落盘）OSError → EXPORT_ERROR。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterReportFails)
    assert main([photo_dir, "--no-vlm", "--json"]) == ExitCode.EXPORT_ERROR


def test_main_score_json_write_oserror_returns_export_error(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--output 落盘 atomic_write_text 抛 OSError → EXPORT_ERROR。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _StubExporter)

    def _raise(path: Path, text: str) -> None:
        raise OSError("readonly")

    monkeypatch.setattr("flashgaze.cli.entry.atomic_write_text", _raise)
    code = main([photo_dir, "--no-vlm", "--json", "--output", str(tmp_path / "o.json")])
    assert code == ExitCode.EXPORT_ERROR


def test_main_score_csv_oserror_returns_export_error(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSV 清单写入 OSError → EXPORT_ERROR。"""
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _ExporterCsvFails)
    code = main([photo_dir, "--no-vlm", "--csv", "--csv-output", str(tmp_path / "o.csv")])
    assert code == ExitCode.EXPORT_ERROR


# ---------- 输出路径未搭配对应开关：PARAM_ERROR（此前静默丢弃 + exit 0） ----------


def test_main_score_output_without_json_returns_param_error(
    photo_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--output 未搭配 --json：PARAM_ERROR 且不落盘。

    此前该组合静默丢弃路径、照常评分并以退出码 0 结束——Agent 按退出码去读
    结果文件只会得到次生的「文件不存在」。现改为评分开始前拒绝。
    """
    out = tmp_path / "r.json"
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--output", str(out)])
    assert code == ExitCode.PARAM_ERROR
    assert any("--output" in r.message and "--json" in r.message for r in caplog.records)
    assert not out.exists()


def test_main_score_csv_output_without_csv_returns_param_error(
    photo_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--csv-output 未搭配 --csv：同构拒绝（与 --output/--json 同一缺陷族）。"""
    out = tmp_path / "custom.csv"
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--csv-output", str(out)])
    assert code == ExitCode.PARAM_ERROR
    assert any("--csv-output" in r.message and "--csv" in r.message for r in caplog.records)
    assert not out.exists()


def test_main_score_xlsx_output_without_xlsx_returns_param_error(
    photo_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--xlsx-output 未搭配 --xlsx：同构拒绝（校验先于 openpyxl lazy import）。"""
    out = tmp_path / "custom.xlsx"
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--xlsx-output", str(out)])
    assert code == ExitCode.PARAM_ERROR
    assert any("--xlsx-output" in r.message and "--xlsx" in r.message for r in caplog.records)
    assert not out.exists()


def test_main_score_config_file_output_path_without_json_returns_param_error(
    photo_dir: str, tmp_path: Path
) -> None:
    """边界：配置文件只给 output_path 不给 output_json → 同样 PARAM_ERROR。

    判定源是装配后的 effective Config（与落盘分支的启用条件同源），
    因此配置文件来源的「路径无开关」同样拦截，而非只盯 CLI 旗标。
    """
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"output_path": str(tmp_path / "r.json")}), encoding="utf-8")
    code = main([photo_dir, "--no-vlm", "--config-file", str(cfg)])
    assert code == ExitCode.PARAM_ERROR


def test_main_score_config_file_json_with_output_path_succeeds(
    photo_dir: str, tmp_path: Path
) -> None:
    """反例（不得误拒）：配置文件启用 output_json + CLI --output → 正常落盘 exit 0。

    开关可来自配置文件（store_true 旗 default=None 让下层兜底），
    校验必须看 effective Config 而非原始命名空间，否则此合法组合会被误伤。
    """
    cfg = tmp_path / "cfg.json"
    out = tmp_path / "r.json"
    cfg.write_text(json.dumps({"output_json": True}), encoding="utf-8")
    code = main([photo_dir, "--no-vlm", "--config-file", str(cfg), "--output", str(out)])
    assert code == ExitCode.SUCCESS
    assert out.exists()


# ---------- 导出旗标未搭配 --export：PARAM_ERROR（此前静默无效 + exit 0，M-07） ----------


def test_main_score_move_without_export_returns_param_error(
    photo_dir: str, caplog: pytest.LogCaptureFixture
) -> None:
    """--move 未搭配 --export：PARAM_ERROR 且源文件不被触碰。

    此前该组合静默忽略 --move、照常评分并以退出码 0 结束——用户按「已移动」
    做的后续清理会误删源文件。现改为评分开始前拒绝。
    """
    images_before = sorted(p.name for p in Path(photo_dir).iterdir())
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--move"])
    assert code == ExitCode.PARAM_ERROR
    assert any("--move" in r.message and "--export" in r.message for r in caplog.records)
    assert sorted(p.name for p in Path(photo_dir).iterdir()) == images_before


def test_main_score_export_dir_without_export_returns_param_error(
    photo_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--export-dir 未搭配 --export：同构拒绝（与 --move 同一缺陷族 M-07）。"""
    dest = tmp_path / "e"
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--export-dir", str(dest)])
    assert code == ExitCode.PARAM_ERROR
    assert any("--export-dir 需搭配 --export" in r.message for r in caplog.records)
    assert not dest.exists()


def test_main_score_config_file_export_with_cli_move_succeeds(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例（不得误拒）：配置文件启用 export + CLI --move → 正常导出 exit 0。

    开关可来自配置文件（store_true 旗 default=None 让下层兜底），
    move 校验必须看 effective Config 而非原始命名空间，否则此合法组合会被误伤。
    """
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"export": True}), encoding="utf-8")
    monkeypatch.setattr("flashgaze.cli.entry.Exporter", _StubExporter)
    code = main([photo_dir, "--no-vlm", "--top", "1", "--config-file", str(cfg), "--move"])
    assert code == ExitCode.SUCCESS


def test_main_score_exif_import_error_returns_config_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, no_api_key: None
) -> None:
    """--exif 但 piexif 未安装（ImportError）→ CONFIG_ERROR（与环境无关的确定性桩）。"""
    monkeypatch.setitem(sys.modules, "flashgaze.core.exif_writer", None)
    assert main([photo_dir, "--no-vlm", "--exif"]) == ExitCode.CONFIG_ERROR


def test_main_score_exif_success(photo_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """--exif 且写入成功 → SUCCESS，exif 结果仅记日志不改变退出码。"""
    calls: dict[str, Any] = {}

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            calls["preserve_original"] = preserve_original
            # H-2：备份开启时 entry 显式传 undo_log=None（不产生撤销日志）
            calls["undo_log"] = undo_log

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            calls["count"] = len(scored)
            return [SimpleNamespace(ok=True)] * len(scored)

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    assert main([photo_dir, "--no-vlm", "--exif"]) == ExitCode.SUCCESS
    assert calls["count"] == 4  # 4 张图（含 corrupted 的 error 条目）
    assert calls["undo_log"] is None  # 备份开启 → 不产生撤销日志


def test_main_score_exif_no_backup_flag_disables_preserve(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--exif --no-exif-backup --force → ExifWriter 收到 preserve_original=False（CLI 反向映射）。

    H-2 契约变更：无回滚点的原地改写须先经 --force 显式确认，故「未加 --force」时
    不再放行（见 test_no_exif_backup_without_force_returns_param_error）。
    """
    calls: dict[str, Any] = {}

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            calls["preserve_original"] = preserve_original

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            calls["count"] = len(scored)
            return [SimpleNamespace(ok=True)] * len(scored)

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    code = main([photo_dir, "--no-vlm", "--exif", "--no-exif-backup", "--force"])
    assert code == ExitCode.SUCCESS
    assert calls["preserve_original"] is False


def test_no_exif_backup_without_force_returns_param_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """H-2：--exif --no-exif-backup 未加 --force → PARAM_ERROR，且绝不构造 ExifWriter。

    无回滚点 = 危险操作，必须在消耗任何算力（扫描/评分）之前拒绝，且一张图都不许落笔。
    """
    calls: dict[str, Any] = {}

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            calls["constructed"] = True

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            calls["wrote"] = len(scored)
            return [SimpleNamespace(ok=True)] * len(scored)

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--exif", "--no-exif-backup"])

    assert code == ExitCode.PARAM_ERROR
    assert "constructed" not in calls  # 未确认即拒绝，绝不落笔
    assert any("--force" in r.message for r in caplog.records)


def test_no_exif_backup_with_force_proceeds_and_passes_undo_log(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-2：--force 放行后，无备份模式仍拿到差异撤销日志落点 .flashgaze_undo/。"""
    calls: dict[str, Any] = {}

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            calls["preserve_original"] = preserve_original
            calls["undo_log"] = undo_log

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            return [SimpleNamespace(ok=True)] * len(scored)

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    assert (
        main([photo_dir, "--no-vlm", "--exif", "--no-exif-backup", "--force"]) == ExitCode.SUCCESS
    )
    assert calls["preserve_original"] is False

    undo_log = calls["undo_log"]
    assert isinstance(undo_log, Path)
    assert undo_log.parent.name == ".flashgaze_undo"
    assert undo_log.parent.parent == Path(photo_dir).resolve()
    assert undo_log.name.startswith("exif_undo_") and undo_log.suffix == ".jsonl"


def test_exif_failure_returns_exif_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """H-2/M-15：EXIF 写入存在失败项 → 退出码 EXIF_ERROR(7)，不再以 0 谎报成功。"""

    class _ExifWriter:
        def __init__(self, preserve_original: bool = True, undo_log: Any = None) -> None:
            pass

        def write_batch(self, scored: list[ImageScore]) -> list[Any]:
            # 前两张成功、其余失败：部分失败也必须可见
            return [
                SimpleNamespace(ok=i < 2, path=s.path, error=None if i < 2 else "boom")
                for i, s in enumerate(scored)
            ]

    monkeypatch.setitem(
        sys.modules, "flashgaze.core.exif_writer", _module_stub({"ExifWriter": _ExifWriter})
    )
    with caplog.at_level(logging.ERROR):
        code = main([photo_dir, "--no-vlm", "--exif"])
    assert code == ExitCode.EXIF_ERROR
    assert any("EXIF" in r.message for r in caplog.records)


def test_no_exif_backup_force_writes_real_undo_log(photo_dir: str) -> None:
    """H-2 真机：--force 放行后每张入选图在 .flashgaze_undo/*.jsonl 留一条差异撤销记录。

    不打桩，走真实 ExifWriter + piexif，验证「关闭备份也留有可回退的差异信息」。
    """
    pytest.importorskip("piexif")

    assert (
        main([photo_dir, "--no-vlm", "--exif", "--no-exif-backup", "--force"]) == ExitCode.SUCCESS
    )

    undo_dir = Path(photo_dir) / ".flashgaze_undo"
    logs = sorted(undo_dir.glob("exif_undo_*.jsonl"))
    assert len(logs) == 1
    records = [
        json.loads(line)
        for line in logs[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # sharp/blurry/dark 三张入选；corrupted 带 error 被 write_batch 跳过
    assert len(records) == 3
    for rec in records:
        assert len(rec["sha256_before"]) == 64
        assert rec["user_comment_before"] is None


def test_main_score_xlsx_import_error_returns_config_error(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--xlsx 但 openpyxl 未安装 → CONFIG_ERROR。"""
    monkeypatch.setitem(sys.modules, "flashgaze.core.xlsx_exporter", None)
    code = main([photo_dir, "--no-vlm", "--xlsx", "--xlsx-output", str(tmp_path / "o.xlsx")])
    assert code == ExitCode.CONFIG_ERROR


def test_main_score_xlsx_success(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--xlsx 且 XlsxExporter 可用 → SUCCESS 且文件写出。"""

    class _XlsxExporter:
        def write(self, scored: list[ImageScore], path: str) -> None:
            Path(path).write_text("xlsx", encoding="utf-8")

    monkeypatch.setitem(
        sys.modules,
        "flashgaze.core.xlsx_exporter",
        _module_stub({"XlsxExporter": _XlsxExporter}),
    )
    out = tmp_path / "o.xlsx"
    assert main([photo_dir, "--no-vlm", "--xlsx", "--xlsx-output", str(out)]) == ExitCode.SUCCESS
    assert out.exists()


def test_main_score_xlsx_oserror_returns_export_error(
    photo_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XLSX 写入 OSError → EXPORT_ERROR。"""

    class _XlsxExporter:
        def write(self, scored: list[ImageScore], path: str) -> None:
            raise OSError("xlsx unwritable")

    monkeypatch.setitem(
        sys.modules,
        "flashgaze.core.xlsx_exporter",
        _module_stub({"XlsxExporter": _XlsxExporter}),
    )
    code = main([photo_dir, "--no-vlm", "--xlsx", "--xlsx-output", str(tmp_path / "o.xlsx")])
    assert code == ExitCode.EXPORT_ERROR


# ---------- _cmd_cleanup：真实运行（无桩） ----------


def test_main_cleanup_dry_run_reports_and_keeps_files(
    photo_dir: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """默认 dry-run：只报告不删除，人类可读报告含试运行与待删除清单。"""
    code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1"])
    assert code == ExitCode.SUCCESS
    out = capsys.readouterr().out
    assert "试运行" in out
    assert "待删除" in out
    # corrupted 无法评分 → 损坏图清单
    assert "损坏图" in out
    # 三张可评分图全部保留
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg"):
        assert (Path(photo_dir) / name).exists()


def test_main_cleanup_apply_deletes_low_score(
    photo_dir: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--apply 实际删除低分图：保留 top 1，删除其余可评分图。"""
    code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1", "--apply"])
    assert code == ExitCode.SUCCESS
    out = capsys.readouterr().out
    assert "实际删除" in out
    assert "已删除" in out
    assert (Path(photo_dir) / "sharp.jpg").exists()
    assert not (Path(photo_dir) / "blurry.jpg").exists()
    assert not (Path(photo_dir) / "dark.jpg").exists()
    # corrupted 不参与删除（损坏图需手动处理）
    assert (Path(photo_dir) / "corrupted.jpg").exists()


def test_main_cleanup_apply_warns_count_before_delete(
    photo_dir: str, caplog: pytest.LogCaptureFixture
) -> None:
    """--apply 删除前在 stderr 打印待删数量，默认（无 --verbose）级别即可见。

    回归锁定：该提示曾用 INFO 级别，被默认 WARNING 压制，CHANGELOG 承诺落空。
    at_level 锁在 WARNING：若改回 INFO，记录低于级别不会发出，测试随之失败。
    """
    with caplog.at_level(logging.WARNING, logger="flashgaze"):
        code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1", "--apply"])
    assert code == ExitCode.SUCCESS
    assert any("即将删除 2 张低分图" in r.message for r in caplog.records)
    # 提示在删除之前兑现过：文件确实被实际删除
    assert not (Path(photo_dir) / "blurry.jpg").exists()
    assert not (Path(photo_dir) / "dark.jpg").exists()


def test_main_cleanup_json_to_file(photo_dir: str, tmp_path: Path) -> None:
    """cleanup --json --output：结构化报告原子写入文件。"""
    report = tmp_path / "report.json"
    code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1", "--json", "--output", str(report)])
    assert code == ExitCode.SUCCESS
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["summary"]["mode"] == "dry_run"


def test_main_cleanup_json_to_stdout(photo_dir: str, capsys: pytest.CaptureFixture[str]) -> None:
    """cleanup --json 不带 --output：报告打印到 stdout。"""
    code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1", "--json"])
    assert code == ExitCode.SUCCESS
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["total"] == 4


def test_main_cleanup_output_without_json_returns_param_error(
    photo_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """cleanup --output 未搭配 --json：PARAM_ERROR 且报告不落盘。

    cleanup 报告的落盘启用条件以命名空间为源（与 _render_cleanup_report 一致），
    此前该组合在评分/删除全部完成后静默丢弃路径，退出码由删除结果决定。
    """
    report = tmp_path / "r.json"
    with caplog.at_level(logging.ERROR):
        code = main(["cleanup", photo_dir, "--no-vlm", "--top", "1", "--output", str(report)])
    assert code == ExitCode.PARAM_ERROR
    assert any("--output" in r.message and "--json" in r.message for r in caplog.records)
    assert not report.exists()


@pytest.mark.parametrize("apply_flags", [(), ("--apply",)])
def test_main_cleanup_output_path_outside_rejected_before_run_cleanup(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    apply_flags: tuple[str, ...],
) -> None:
    """LOW-1(cleanup) 回归：越界 --output 在 run_cleanup 之前硬拒绝。

    原校验在 _render_cleanup_report 内部，评分乃至 --apply 实删全部完成后才
    sys.exit(2)——删除已发生而报告（唯一机器可读记录）既不落盘也不打印。
    断言：① PARAM_ERROR（sys.exit(2) 经 main() 收敛）；② 日志含「拒绝越界」；
    ③ 越界文件不落盘；④ run_cleanup（评分/删除）一次都不应执行。
    """
    calls: list[bool] = []

    def _spy_run_cleanup(*a: Any, **kw: Any) -> dict[str, Any]:
        calls.append(True)
        return _cleanup_result()

    monkeypatch.setattr("flashgaze.cli.entry.run_cleanup", _spy_run_cleanup)
    # 指向 photo_dir（=tmp_path）的兄弟目录，明确越出 workspace，绝对路径
    outside = tmp_path.parent / "cleanup_escape.json"
    with caplog.at_level(logging.ERROR):
        code = main(
            ["cleanup", photo_dir, "--no-vlm", *apply_flags, "--json", "--output", str(outside)]
        )
    assert code == ExitCode.PARAM_ERROR
    assert any("拒绝越界" in r.message for r in caplog.records)
    assert not outside.exists()
    assert calls == []  # 校验前置：评分与删除尚未开始


def test_main_cleanup_apply_output_outside_files_survive(
    photo_dir: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """真实流程回归：--apply + 越界 --output 时删除不得发生。

    run_cleanup 不打桩走真实路径：修复前实删已完成才在渲染层拒绝，
    该用例以「图片是否仍在」锁定前置顺序。
    """
    outside = tmp_path.parent / "cleanup_escape_real.json"
    flags = ["cleanup", photo_dir, "--no-vlm", "--top", "1", "--apply", "--json", "--output"]
    with caplog.at_level(logging.ERROR):
        code = main([*flags, str(outside)])
    assert code == ExitCode.PARAM_ERROR
    assert not outside.exists()
    # 修复前此处 blurry/dark 已被删除
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg"):
        assert (Path(photo_dir) / name).exists()


def test_main_cleanup_report_write_failure_degrades_to_stdout(
    photo_dir: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """main 级兜底：报告写盘失败降级 stdout，退出码仍由删除结果决定。

    删除已发生的前提下，写盘失败（权限/磁盘满）不得让唯一的结果记录消失，
    也不得谎报失败（SUCCESS 而非 EXPORT_ERROR），降级事实由 warning 日志承载。
    """
    result = _cleanup_result(pending=[{"file": "a.jpg", "path": "/ws/a.jpg"}])
    monkeypatch.setattr("flashgaze.cli.entry.run_cleanup", lambda *a, **kw: result)

    def _boom(path: object, text: str, **kw: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("flashgaze.cli.entry.atomic_write_text", _boom)
    report = tmp_path / "report.json"  # photo_dir = tmp_path，路径在 workspace 内
    with caplog.at_level(logging.WARNING):
        code = main(["cleanup", photo_dir, "--no-vlm", "--json", "--output", str(report)])
    assert code == ExitCode.SUCCESS
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["to_delete"] == 1
    assert any("降级输出到 stdout" in r.message for r in caplog.records)
    assert not report.exists()  # 写盘确实失败，未产生半截文件


def test_main_cleanup_missing_api_key_returns_config_error(
    photo_dir: str, no_api_key: None
) -> None:
    """cleanup 缺 VLM key → CONFIG_ERROR。"""
    assert main(["cleanup", photo_dir]) == ExitCode.CONFIG_ERROR


def test_main_cleanup_top_zero_guard(photo_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """top<1 护栏：配置层绕过校验（如配置文件 top=0）时在 cleanup 侧拦截。

    CLI --top 0 会在 _config_from_ns 内 sys.exit(2)，走不到该护栏；护栏防的是
    文件/env 层注入的非法值，故此处直接桩掉配置装配来触发。
    """
    monkeypatch.setattr(CLIParser, "_config_from_ns", lambda self, ns: SimpleNamespace(top=0))
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.PARAM_ERROR


# ---------- _cmd_cleanup：异常映射（run_cleanup 桩） ----------


def test_main_cleanup_config_assembly_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cleanup 配置装配异常 → CONFIG_ERROR（FIX #12-2）。"""

    def _raise(self: CLIParser, ns: argparse.Namespace) -> Config:
        raise ValueError("boom")

    monkeypatch.setattr(CLIParser, "_config_from_ns", _raise)
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.CONFIG_ERROR


def test_main_cleanup_cleanup_error_returns_no_images(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CleanupError（目录无效等）→ NO_IMAGES。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.run_cleanup",
        lambda *a, **kw: (_ for _ in ()).throw(CleanupError("目录无效")),
    )
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.NO_IMAGES


def test_main_cleanup_runtime_error_returns_image_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """评分阶段被包装的 RuntimeError → IMAGE_ERROR（FIX #12-3 标签区分）。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.run_cleanup",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("评分过程异常: x")),
    )
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.IMAGE_ERROR


def test_main_cleanup_brisque_integrity_error_returns_image_error(
    photo_dir: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """供应链信号 BrisqueIntegrityError → IMAGE_ERROR，且日志用专属标签。

    回归：BrisqueIntegrityError 是 RuntimeError 子类，except 顺序错时会落入
    「评分失败」分支（退出码相同但日志语义错位），见 entry._cmd_cleanup 注释。
    """
    monkeypatch.setattr(
        "flashgaze.cli.entry.run_cleanup",
        lambda *a, **kw: (_ for _ in ()).throw(BrisqueIntegrityError("sha mismatch")),
    )
    with caplog.at_level(logging.ERROR, logger="flashgaze"):
        assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.IMAGE_ERROR
    assert any("模型完整性校验失败" in r.message for r in caplog.records)


def test_main_cleanup_unexpected_error_returns_export_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分类/删除阶段的意外异常 → EXPORT_ERROR（FIX #12-3 单独收敛）。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.run_cleanup",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk io")),
    )
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.EXPORT_ERROR


def test_main_cleanup_delete_failure_returns_export_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """实际删除模式下存在「删除失败」拦截 → EXPORT_ERROR；dry-run 同数据仍 SUCCESS。

    LOW-2 后退出码判定消费 blocked 项的结构化 kind 字段（classify_and_delete
    恒输出），mock 夹具同步携带 kind="delete_failure"。"""
    result = _cleanup_result(
        blocked=[
            {"path": "/ws/a.jpg", "reason": "删除失败: PermissionError", "kind": "delete_failure"}
        ],
    )
    monkeypatch.setattr("flashgaze.cli.entry.run_cleanup", lambda *a, **kw: result)
    code = main(["cleanup", photo_dir, "--no-vlm", "--apply"])
    assert code == ExitCode.EXPORT_ERROR

    # dry-run：安全拦截视为已处理，不降级退出码
    pending_result = _cleanup_result(
        blocked=[
            {"path": "/ws/a.jpg", "reason": "删除失败: PermissionError", "kind": "delete_failure"}
        ],
        pending=[{"file": "a.jpg", "path": "/ws/a.jpg"}],
    )
    monkeypatch.setattr("flashgaze.cli.entry.run_cleanup", lambda *a, **kw: pending_result)
    assert main(["cleanup", photo_dir, "--no-vlm"]) == ExitCode.SUCCESS


# ---------- 渲染与工具函数 ----------


def test_render_cleanup_report_human_full_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """人类可读报告：实际删除模式含已删除/拦截/损坏图全部分区。"""
    result = _cleanup_result(
        deleted=[{"file": "a.jpg", "path": "/ws/a.jpg"}],
        blocked=[{"path": "/ws/b.jpg", "reason": "路径在工作空间外，已拦截"}],
        unevaluated=[{"file": "c.jpg", "path": "/ws/c.jpg", "error": "decode failed"}],
    )
    ns = argparse.Namespace(output_json=False, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=False)
    out = capsys.readouterr().out
    assert "已删除: 1 张" in out
    assert "已拦截（未删除）" in out
    assert "损坏图（需手动处理）" in out
    assert "decode failed" in out


def test_render_cleanup_report_json_without_output_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json 且未提供 --output：结构化结果打印 stdout。"""
    result = _cleanup_result(pending=[{"file": "a.jpg", "path": "/ws/a.jpg"}])
    ns = argparse.Namespace(output_json=True, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=True)
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["to_delete"] == 1


# ---------- 评分口径渲染（VLM 部分失败/熔断可观测）----------


def test_render_cleanup_report_shows_vlm_caliber_mixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """混合口径：含补偿与降级纯 CV 并存 → 输出口径行 + 降级图 [纯CV] 标记。"""
    result = _cleanup_result(
        pending=[
            {"file": "a.jpg", "path": "/ws/a.jpg", "vlm_applied": True, "vlm_error": ""},
            {
                "file": "b.jpg",
                "path": "/ws/b.jpg",
                "vlm_applied": False,
                "vlm_error": "circuit_open",
            },
        ],
        summary_extra={"vlm_applied": 1, "vlm_degraded": 1},
    )
    ns = argparse.Namespace(output_json=False, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=True)
    out = capsys.readouterr().out
    assert "评分口径: 1 张含 VLM 补偿 | 1 张降级为纯 CV" in out
    assert "删除决策置信度较低" in out
    # 仅降级图带 [纯CV] 标记
    b_line = next(line for line in out.splitlines() if "b.jpg" in line)
    a_line = next(line for line in out.splitlines() if "a.jpg" in line)
    assert "[纯CV]" in b_line
    assert "[纯CV]" not in a_line


def test_render_cleanup_report_shows_all_degraded_caliber(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """全部降级：vlm_applied=0 时提示整批纯 CV 口径。"""
    result = _cleanup_result(
        pending=[{"file": "a.jpg", "path": "/ws/a.jpg", "vlm_error": "retry_exhausted"}],
        summary_extra={"vlm_applied": 0, "vlm_degraded": 3},
    )
    ns = argparse.Namespace(output_json=False, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=True)
    out = capsys.readouterr().out
    assert "本批 VLM 全部失败/已熔断" in out
    assert "删除决策全部基于纯 CV 分" in out


def test_render_cleanup_report_no_vlm_skips_caliber_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """未启用 VLM（旧形状 summary / 两计数为 0）：不输出评分口径行。"""
    result = _cleanup_result(pending=[{"file": "a.jpg", "path": "/ws/a.jpg"}])
    ns = argparse.Namespace(output_json=False, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=True)
    out = capsys.readouterr().out
    assert "评分口径" not in out
    assert "[纯CV]" not in out


def test_render_cleanup_report_json_passthrough_caliber_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json 模式：summary 口径计数与图级字段原样透传。"""
    result = _cleanup_result(
        pending=[
            {
                "file": "a.jpg",
                "path": "/ws/a.jpg",
                "vlm_applied": False,
                "vlm_error": "circuit_open",
            }
        ],
        summary_extra={"vlm_applied": 0, "vlm_degraded": 1},
    )
    ns = argparse.Namespace(output_json=True, output_path=None, directory=str(tmp_path))
    _render_cleanup_report(result, ns, dry_run=True)
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["vlm_applied"] == 0
    assert data["summary"]["vlm_degraded"] == 1
    assert data["pending_delete"][0]["vlm_error"] == "circuit_open"


def test_render_cleanup_report_write_failure_degrades_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """渲染层兜底：报告落盘失败（OSError）→ 降级打印 stdout，不抛 SystemExit。"""
    result = _cleanup_result(deleted=[{"file": "a.jpg", "path": "/ws/a.jpg"}])
    ns = argparse.Namespace(
        output_json=True, output_path=str(tmp_path / "r.json"), directory=str(tmp_path)
    )

    def _boom(path: object, text: str, **kw: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("flashgaze.cli.entry.atomic_write_text", _boom)
    with caplog.at_level(logging.WARNING):
        _render_cleanup_report(result, ns, dry_run=False)
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["deleted"] == 1
    assert any("降级输出到 stdout" in r.message for r in caplog.records)
    assert not (tmp_path / "r.json").exists()


def test_safe_output_path_none() -> None:
    """未提供输出路径 → None（仅 stdout）。"""
    assert _safe_output_path(None, "/ws") is None


def test_safe_output_path_inside_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """工作区内路径：返回 resolved 路径，不告警。"""
    with caplog.at_level(logging.WARNING):
        p = _safe_output_path(str(tmp_path / "o.json"), str(tmp_path))
    assert p == (tmp_path / "o.json").resolve()
    assert not caplog.records


def test_safe_output_path_outside_rejected(tmp_path: Path) -> None:
    """越出工作区的路径：硬拒绝（抛 UnsafeOutputPathError），不再仅告警。"""
    outside = tmp_path.parent / "escaped.json"
    with pytest.raises(UnsafeOutputPathError):
        _safe_output_path(str(outside), str(tmp_path))


def test_cleanup_output_tmp_removes_stale(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """启动时清理上次异常退出遗留的 .tmp 原子写残留，并记 info 日志。"""
    stale = tmp_path / ".out.json.tmp.12345"
    stale.write_text("leftover", encoding="utf-8")
    # M-10：cleanup_stale_tmp 跳过 mtime 距今 1 小时内的新鲜 tmp，须拨老模拟异常退出残留
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    cfg = Config(
        directory=str(tmp_path),
        output_json=True,
        output_path=str(tmp_path / "out.json"),
        output_csv=True,
        csv_output_path=str(tmp_path / "out.csv"),
        output_xlsx=False,
        xlsx_output_path=None,
    )
    with caplog.at_level(logging.INFO, logger="flashgaze"):
        _cleanup_output_tmp(cfg, logging.getLogger("flashgaze"))
    assert not stale.exists()
    assert any("清理残留" in r.message for r in caplog.records)


# ---------- __main__ 入口 ----------


def test_dunder_main_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m flashgaze` 入口：runpy 进程内执行 __main__.py，--version 退出码 0。"""
    monkeypatch.setattr(sys, "argv", ["flashgaze", "--version"])
    with pytest.raises(SystemExit) as ei:
        runpy.run_module("flashgaze", run_name="__main__")
    assert ei.value.code == 0


# ---------- cleanup：95% 删除护栏（FIX #sec-threshold）----------


def _mk_ws_images(ws: Path, sharp_img: str, n: int) -> list[Path]:
    """造含 n 张真实图片的工作空间。"""
    import shutil

    ws.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        f = ws / f"img{i:02d}.jpg"
        shutil.copy(sharp_img, f)
        out.append(f)
    return out


def _all_low_score_factory(paths: list[Path]) -> Any:
    """make_scorer 替身：所有图均低分落选（触发待删 100%）。"""

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            return [
                ImageScore(
                    file=p.name,
                    path=str(p),
                    sharpness=1.0,
                    exposure=1.0,
                    composition=None,
                    vlm_adjustment=0.0,
                    score=1.0,
                )
                for p in paths
            ]

    return lambda cfg: _Scorer()


def test_cleanup_apply_blocked_by_bulk_guard(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--apply 且待删 100%：护栏拦截，返回 PARAM_ERROR 且文件一张不少。"""
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))

    rc = main(["cleanup", str(ws), "--no-vlm", "--apply"])
    assert rc == ExitCode.PARAM_ERROR
    assert all(p.exists() for p in paths)


def test_cleanup_apply_force_deletes(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--apply --force --confirm-fingerprint 放行：真实 rename 进回收站。

    force 必须与已核对的清单指纹同行；同卷 rename 语义（非删除）经验证不受
    环境删除拦截影响，整批走真实文件系统断言。
    """
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))
    fingerprint = pending_fingerprint(paths)

    rc = main(
        [
            "cleanup",
            str(ws),
            "--no-vlm",
            "--apply",
            "--force",
            "--confirm-fingerprint",
            fingerprint,
        ]
    )
    assert rc == ExitCode.SUCCESS
    # 真实文件系统验证：25 张全部移入回收站，原路径无残留
    assert all(not p.exists() for p in paths)
    moved = [p for p in (ws / ".flashgaze_deleted").rglob("*") if p.is_file()]
    assert len(moved) == 25


def test_cleanup_force_without_fingerprint_rejected_before_scoring(
    tmp_path: Path,
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """--apply --force 缺 --confirm-fingerprint → PARAM_ERROR，且评分根本没发生。

    与 H-2「危险操作在消耗算力之前先拒错」同款纪律：指纹校验前置到 run_cleanup
    之前，避免在用户必然被拦截的输入上白烧评分算力（VLM 费用 + 数分钟）。
    """
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    calls: list[Any] = []

    def _must_not_run(config: Any) -> Any:
        calls.append(config)
        raise AssertionError("缺指纹时不得进入评分阶段")

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _must_not_run)

    with caplog.at_level(logging.ERROR):
        rc = main(["cleanup", str(ws), "--no-vlm", "--apply", "--force"])
    assert rc == ExitCode.PARAM_ERROR
    assert calls == []  # 未消耗任何评分算力
    assert any("--confirm-fingerprint" in r.message for r in caplog.records)
    assert all(p.exists() for p in paths)


def test_cleanup_apply_force_wrong_fingerprint_blocked(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """指纹与当前待删清单不符 → 一张不删、退出码 1（清单已变，核对失效）。"""
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))

    rc = main(
        [
            "cleanup",
            str(ws),
            "--no-vlm",
            "--apply",
            "--force",
            "--confirm-fingerprint",
            "0" * 12,
        ]
    )
    assert rc == ExitCode.PARAM_ERROR
    assert all(p.exists() for p in paths)  # 一张未删
    assert not (ws / ".flashgaze_deleted").exists()


def test_cleanup_apply_force_fingerprint_end_to_end(
    tmp_path: Path,
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """两步确认闭环：dry_run 的 JSON 报告给出指纹 → apply 回填后真删进回收站。"""
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))

    rc_dry = main(["cleanup", str(ws), "--no-vlm", "--json"])
    assert rc_dry == ExitCode.SUCCESS
    fingerprint = json.loads(capsys.readouterr().out)["summary"]["fingerprint"]
    assert len(fingerprint) == 12

    rc = main(
        [
            "cleanup",
            str(ws),
            "--no-vlm",
            "--apply",
            "--force",
            "--confirm-fingerprint",
            fingerprint,
        ]
    )
    assert rc == ExitCode.SUCCESS
    assert len(list((ws / ".flashgaze_deleted").rglob("*.jpg"))) == 25
    assert not any(p.exists() for p in paths)
    assert len(list(ws.glob(".flashgaze_deleted_*.jsonl"))) == 1


def test_cleanup_no_recycle_without_force_rejected(
    tmp_path: Path,
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """--no-recycle 属无回滚点危险操作，未与 --force 同行直接拒绝（与 H-2 同语义）。"""
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 3)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))

    with caplog.at_level(logging.ERROR):
        rc = main(["cleanup", str(ws), "--no-vlm", "--top", "1", "--apply", "--no-recycle"])
    assert rc == ExitCode.PARAM_ERROR
    assert any("--no-recycle" in r.message for r in caplog.records)
    assert all(p.exists() for p in paths)


def test_restore_command_roundtrip(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flashgaze restore <清单>：删除后按审计清单恢复，退出码 0、文件回原位。"""
    ws = tmp_path / "ws"
    paths = _mk_ws_images(ws, sharp_img, 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _all_low_score_factory(paths))
    fingerprint = pending_fingerprint(paths)
    rc = main(
        ["cleanup", str(ws), "--no-vlm", "--apply", "--force", "--confirm-fingerprint", fingerprint]
    )
    assert rc == ExitCode.SUCCESS
    manifest = next(iter(ws.glob(".flashgaze_deleted_*.jsonl")))

    rc_dry = main(["restore", str(manifest), "--dry-run"])
    assert rc_dry == ExitCode.SUCCESS
    assert not any(p.exists() for p in paths)  # dry_run 未动文件

    rc_restore = main(["restore", str(manifest)])
    assert rc_restore == ExitCode.SUCCESS
    assert all(p.exists() for p in paths)


def test_restore_missing_manifest_returns_param_error(tmp_path: Path) -> None:
    """restore 清单不存在 → PARAM_ERROR，不崩溃。"""
    rc = main(["restore", str(tmp_path / "nope.jsonl")])
    assert rc == ExitCode.PARAM_ERROR


# ---------- H-8：评分器构造异常收敛 + main() 兜底 ----------


def _raise_on_construct(exc: Exception) -> Callable[[Config], Any]:
    """make_scorer 替身：构造期即抛给定异常（模拟 CVEngine/VLMClient 装配失败）。"""

    def _raise(config: Config) -> Any:
        raise exc

    return _raise


def test_score_brisque_integrity_exit_code(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """H-8/P0 序 7：make_scorer 抛 BrisqueIntegrityError → IMAGE_ERROR + 供应链语义日志。

    修复前该异常穿透 main() 直达解释器（裸 traceback + 退出码 1），此用例直接 error。
    """
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer",
        _raise_on_construct(BrisqueIntegrityError("BRISQUE 模型完整性校验失败，已拒绝落盘")),
    )
    with caplog.at_level(logging.ERROR):
        rc = main([photo_dir, "--no-vlm"])
    assert rc == ExitCode.IMAGE_ERROR
    assert any("模型完整性校验失败" in r.message for r in caplog.records)
    assert not any("评分失败" in r.message for r in caplog.records)


def test_score_scorer_construction_error_exit_code(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """H-8：构造期非供应链异常（如 SSRF 拒绝的 ValueError）→ CONFIG_ERROR + 独立文案。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer",
        _raise_on_construct(ValueError("private target rejected")),
    )
    with caplog.at_level(logging.ERROR):
        rc = main([photo_dir, "--no-vlm"])
    assert rc == ExitCode.CONFIG_ERROR
    assert any("评分器构造失败" in r.message for r in caplog.records)


def test_construction_error_not_mapped_to_image_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：构造失败不得被标成 IMAGE_ERROR(4) 或 PARAM_ERROR(1)（数值重叠是本 Issue 病根）。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer", _raise_on_construct(ValueError("bad provider"))
    )
    rc = main([photo_dir, "--no-vlm"])
    assert rc not in (ExitCode.IMAGE_ERROR, ExitCode.PARAM_ERROR)


def test_score_paths_brisque_error_not_labeled_scoring_failure(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """M-05：score_paths 抛 BrisqueIntegrityError 不得被通用分支错标为「评分失败」。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer",
        lambda config: _ScorerStub(exc=BrisqueIntegrityError("hash mismatch")),
    )
    with caplog.at_level(logging.ERROR):
        rc = main([photo_dir, "--no-vlm"])
    assert rc == ExitCode.IMAGE_ERROR
    assert any("模型完整性校验失败" in r.message for r in caplog.records)
    assert not any("评分失败" in r.message for r in caplog.records)


def test_main_unexpected_exception_returns_internal_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """H-8：子命令未收敛的异常由 main() 兜底为 INTERNAL_ERROR(8)，无 traceback。"""

    def _boom(*_args: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr("flashgaze.cli.entry._cmd_score", _boom)
    with caplog.at_level(logging.DEBUG, logger="flashgaze"):
        rc = main([photo_dir, "--no-vlm"])
    assert rc == ExitCode.INTERNAL_ERROR
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("未预期的内部错误（RuntimeError）: boom" in r.message for r in errors)
    assert not any(r.exc_info for r in errors)  # ERROR 行不带堆栈


def test_scoring_runtime_error_stays_image_error(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """反例：构造成功后 score_paths 抛普通 RuntimeError 仍为 IMAGE_ERROR + 「评分失败」。"""
    monkeypatch.setattr(
        "flashgaze.cli.entry.make_scorer",
        lambda config: _ScorerStub(exc=RuntimeError("cv crash")),
    )
    with caplog.at_level(logging.ERROR):
        rc = main([photo_dir, "--no-vlm"])
    assert rc == ExitCode.IMAGE_ERROR
    assert any("评分失败" in r.message for r in caplog.records)
    assert not any("评分器构造失败" in r.message for r in caplog.records)


def test_systemexit_from_command_not_swallowed_by_fallback(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：兜底层只捕 Exception，不得吞掉子命令抛出的 SystemExit（参数校验通道）。"""

    def _exit_nonzero(*_args: Any) -> int:
        sys.exit(2)

    monkeypatch.setattr("flashgaze.cli.entry._cmd_score", _exit_nonzero)
    assert main([photo_dir, "--no-vlm"]) == ExitCode.PARAM_ERROR

    def _exit_zero(*_args: Any) -> int:
        sys.exit(0)

    monkeypatch.setattr("flashgaze.cli.entry._cmd_score", _exit_zero)
    assert main([photo_dir, "--no-vlm"]) == ExitCode.SUCCESS

"""core/cleanup 单元测试。

验证 run_cleanup / classify_and_delete 的：
- dry_run 默认不删除（硬要求）
- 评分 → 分类 → 三重安全校验（relative_to 边界、stat.S_ISREG、删除前再校验）
- 损坏图（error）只归类不删除
- 目录无效 / 无图 / 评分为空 抛 CleanupError

评分用 monkeypatch 替换 make_scorer，保证用例确定、不依赖真实 CV 引擎；
删除目标用 tests/fixtures 下的真实图片，使 stat 校验路径处理的是真实文件。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from flashgaze.core.cleanup import (
    CleanupError,
    classify_and_delete,
    exclusion_dirs,
    pending_fingerprint,
    restore_from_manifest,
    run_cleanup,
)
from flashgaze.models.schemas import Config, ImageScore
from flashgaze.utils.image_io import iter_images


def _fake_factory(scored: list[ImageScore]) -> Callable[[Config], Any]:
    """返回一个 make_scorer 替身，score_paths 直接返回给定列表。"""

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            return scored

    return lambda cfg: _Scorer()


def _copy_images(ws: Path, names: list[str], fixtures_dir: Path) -> list[Path]:
    out = []
    for n in names:
        f = ws / n
        shutil.copy(fixtures_dir / "sharp.jpg", f)
        out.append(f)
    return out


def _mk_scores(
    paths: list[Path], selected_flags: list[bool], scores: list[float]
) -> list[ImageScore]:
    """按路径列表构造 ImageScore（selected/score 由对应列表给出）。"""
    return [
        ImageScore(
            file=p.name,
            path=str(p),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=sc,
            selected=sel,
        )
        for p, sel, sc in zip(paths, selected_flags, scores)
    ]


# ── dry_run 不删除（硬要求）────────────────────────


def test_run_cleanup_dry_run_no_deletion(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dry_run 默认只登记待删文件，不实际 unlink，返回结构含五段。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b, c = _copy_images(ws, ["a.jpg", "b.jpg", "c.jpg"], fixtures_dir)
    # a 高分入选；b/c 低分待删
    scored = _mk_scores([a, b, c], [True, False, False], [90.0, 10.0, 5.0])
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))

    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=True)

    assert result["summary"]["mode"] == "dry_run"
    assert result["summary"]["to_delete"] == 2
    assert result["summary"]["deleted"] == 0
    assert result["summary"]["selected"] == 1
    assert len(result["pending_delete"]) == 2
    # 五段结构齐全
    assert set(result) >= {"summary", "pending_delete", "deleted", "blocked", "unevaluated"}
    # 文件一个都没少
    assert a.exists() and b.exists() and c.exists()


def test_run_cleanup_default_is_dry_run(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cleanup 默认 dry_run=True，不删除任何文件。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config)  # 不传 dry_run
    assert result["summary"]["mode"] == "dry_run"
    assert a.exists() and b.exists()


# ── 评分口径计数（VLM 部分失败/熔断可观测）──────────


def test_run_cleanup_summary_reports_vlm_caliber(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """summary 区分「含 VLM 补偿」与「VLM 失败降级纯 CV」两类图，降级图进待删名单。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b, c, d = _copy_images(ws, ["a.jpg", "b.jpg", "c.jpg", "d.jpg"], fixtures_dir)
    scored = _mk_scores([a, b, c, d], [True, False, False, False], [90.0, 20.0, 15.0, 10.0])
    # a: VLM 成功（含补偿）；b/c: VLM 失败（重试耗尽 / 熔断跳过）；d: 未启用 VLM
    scored[0].vlm_applied = True
    scored[1].vlm_error = "retry_exhausted"
    scored[2].vlm_error = "circuit_open"
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))

    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=True)

    assert result["summary"]["vlm_applied"] == 1
    assert result["summary"]["vlm_degraded"] == 2
    # 降级图进入待删名单且携带 vlm_error（asdict 透传），入选图携带 vlm_applied
    pending = {p["file"]: p for p in result["pending_delete"]}
    assert pending["b.jpg"]["vlm_error"] == "retry_exhausted"
    assert pending["c.jpg"]["vlm_error"] == "circuit_open"
    assert pending["c.jpg"]["vlm_applied"] is False
    assert pending["d.jpg"]["vlm_error"] == ""  # 未启用 ≠ 失败
    assert result["kept"][0]["vlm_applied"] is True


def test_run_cleanup_summary_no_vlm_zero_caliber_counts(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未启用 VLM 时口径计数均为 0（与「全部失败」可区分）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))

    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=True)

    assert result["summary"]["vlm_applied"] == 0
    assert result["summary"]["vlm_degraded"] == 0


# ── 安全护栏：relative_to 边界（检查点 B）──────────


def test_classify_and_delete_blocks_outside_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """指向工作空间外的待删文件被 relative_to 拦截，不删除。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "keep.jpg"
    inside.write_text("x")

    outside = tmp_path / "outside.jpg"
    outside.write_text("x")
    scored = [
        ImageScore(
            file="outside.jpg",
            path=str(outside),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
        )
    ]
    result = classify_and_delete(ws, scored, dry_run=False)
    assert len(result["blocked"]) >= 1
    assert "工作空间外" in result["blocked"][0]["reason"]
    assert result["blocked"][0]["kind"] == "outside_workspace"  # LOW-2 结构化类别
    # 外部文件完好
    assert outside.exists()


# ── 安全护栏：符号链接路径拦截（检查点 A0，纵深防御）──


def test_symlink_not_deleted_target(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """待删路径为符号链接时拦截（kind=symlink_path），绝不解析后作用于目标本体（H-4）。

    模拟 scored 来自内部 iter_images 之外的来源（预评分/测试注入）的场景：
    扫描层过滤链接后（H-4/M-16 主修复），该检查点闭环「删除对象与审计轨迹一致」。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    real = _copy_images(ws, ["real.jpg"], fixtures_dir)[0]
    link = ws / "link.jpg"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无符号链接创建权限（Windows 需开发者模式/管理员），未验证")

    scored = _mk_scores([link], [False], [10.0])
    result = classify_and_delete(ws, scored, dry_run=False)

    # 目标本体绝不被删除，审计清单/报告不记任何删除
    assert real.exists()
    assert result["summary"]["deleted"] == 0
    assert result["deleted"] == []
    blocked = [b for b in result["blocked"] if Path(b["path"]).name == "link.jpg"]
    assert blocked and blocked[0]["kind"] == "symlink_path"  # LOW-2 结构化类别


# ── 安全护栏：stat.S_ISREG（检查点 C，TOCTOU）──────


def test_classify_and_delete_rejects_non_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """待删路径指向目录（非普通文件）时，stat 校验拦截，不删除。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    subdir = ws / "notanimage"
    subdir.mkdir()

    scored = [
        ImageScore(
            file="notanimage",
            path=str(subdir),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
        )
    ]
    result = classify_and_delete(ws, scored, dry_run=False)
    assert len(result["blocked"]) >= 1
    assert "非常规文件" in result["blocked"][0]["reason"]
    assert result["blocked"][0]["kind"] == "not_regular_file"  # LOW-2 结构化类别
    assert subdir.exists()


# ── 损坏图（error）只归类不删除（F-03）──────────────


def test_classify_and_delete_unevaluated_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """error 非 None 的图进 unevaluated，既不删也不入选。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    good = ws / "good.jpg"
    good.write_text("x")
    bad = ws / "bad.jpg"
    bad.write_text("x")

    scored = [
        ImageScore(
            file="good.jpg",
            path=str(good),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=90.0,
            selected=True,
        ),
        ImageScore(
            file="bad.jpg",
            path=str(bad),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
            error="解码失败",
        ),
    ]
    result = classify_and_delete(ws, scored, dry_run=True)
    assert result["summary"]["unevaluated"] == 1
    assert "bad.jpg" in [u["file"] for u in result["unevaluated"]]
    assert "bad.jpg" not in [d["file"] for d in result["pending_delete"]]
    assert bad.exists()


# ── 前置校验：目录无效 / 无图 / 评分为空 ───────────────


def test_run_cleanup_workspace_not_exist_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flashgaze.utils.config import build_config

    config = build_config(str(tmp_path / "nope"), no_vlm=True)
    with pytest.raises(CleanupError):
        run_cleanup(str(tmp_path / "nope"), config, dry_run=True)


def test_run_cleanup_empty_directory_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    with pytest.raises(CleanupError):
        run_cleanup(str(ws), config, dry_run=True)


def test_run_cleanup_empty_scored_raises(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    # 放一张真实图片让 iter_images 非空，但评分返回空列表 → 评分为空
    _copy_images(ws, ["a.jpg"], fixtures_dir)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory([]))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    with pytest.raises(CleanupError):
        run_cleanup(str(ws), config, dry_run=True)


# ── 实际删除分支：移入回收站并登记已删 + 审计记录 ─────────


def test_run_cleanup_actual_delete_records_deleted(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dry_run=False 时低分图移入回收站（不 unlink），并登记已删与审计记录。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))

    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=False)

    assert result["summary"]["mode"] == "actual_delete"
    assert result["summary"]["deleted"] == 1
    assert len(result["deleted"]) == 1
    assert result["deleted"][0]["file"] == "b.jpg"
    assert a.exists()  # 高分图保留
    assert not b.exists()  # 低分图已移出原位
    assert len(_recycle_files(ws)) == 1  # 字节仍在回收站，未真删
    assert len(result["delete_audit"]) == 1


# ── CLI 入口：cleanup 子命令 + 兼容垫片 ───────────────


def test_cli_cleanup_dry_run_default_via_main(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flashgaze cleanup <目录> 默认 dry_run 且不删除（兼容旧用法垫片不影响 score）。"""
    from flashgaze.cli.entry import main

    ws = tmp_path / "ws"
    ws.mkdir()
    _copy_images(ws, ["a.jpg", "b.jpg", "c.jpg"], fixtures_dir)
    # 真实评分（--no-vlm）即可，不必 mock
    rc = main(["cleanup", str(ws), "--no-vlm", "--top", "1"])
    assert rc == 0
    # 文件全部保留（dry_run 默认）
    assert (ws / "a.jpg").exists() and (ws / "b.jpg").exists() and (ws / "c.jpg").exists()


def test_cli_cleanup_top_zero_rejected(tmp_path: Path, fixtures_dir: Path) -> None:
    """cleanup 子命令 top=0 被拒（PARAM_ERROR）。"""
    from flashgaze.cli.parser import CLIParser

    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(SystemExit) as exc:
        CLIParser().parse(["cleanup", str(ws), "--no-vlm", "--top", "0"])
    assert exc.value.code == 2  # argparse 范围校验 → 上层映射 PARAM_ERROR


def test_cli_legacy_score_shim(tmp_path: Path, fixtures_dir: Path) -> None:
    """无子命令的旧用法 `flashgaze <目录>` 仍路由到 score（解析出 directory）。"""
    from flashgaze.cli.parser import CLIParser

    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = CLIParser().parse([str(ws), "--no-vlm", "--top", "5"])
    assert cfg.directory == str(ws)
    assert cfg.no_vlm is True
    assert cfg.top == 5


# ── C-01：cleanup 排除导出目录，避免误删精选副本 ──────────


def _recording_factory(seen: list[str]) -> Callable[[Config], Any]:
    """make_scorer 替身：记录收到的图片路径，并把所有图标为低分待删。"""

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            seen.extend(images)
            return [
                ImageScore(
                    file=Path(p).name,
                    path=p,
                    sharpness=0.0,
                    exposure=0.0,
                    composition=None,
                    vlm_adjustment=0.0,
                    score=10.0,
                    selected=False,
                )
                for p in images
            ]

    return lambda cfg: _Scorer()


def _raising_factory(exc: Exception) -> Callable[[Config], Any]:
    """make_scorer 替身：score_paths 直接抛指定异常。"""

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            raise exc

    return lambda cfg: _Scorer()


def test_run_cleanup_excludes_export_dir(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cleanup 不把导出目录 ./精选 内的图片交给评分/删除（C-01）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _copy_images(ws, ["a.jpg"], fixtures_dir)
    export = ws / "精选"
    export.mkdir()
    shutil.copy(fixtures_dir / "sharp.jpg", export / "sel.jpg")

    seen: list[str] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _recording_factory(seen))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    run_cleanup(str(ws), config, dry_run=True)

    seen_names = {Path(p).name for p in seen}
    assert "a.jpg" in seen_names  # 源目录图片照常扫描、评分
    assert "sel.jpg" not in seen_names  # 导出目录副本被排除，绝不进入待删
    assert (export / "sel.jpg").exists()  # 导出副本完好


def test_run_cleanup_reraises_brisque_integrity(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cleanup 评分阶段抛出的 BrisqueIntegrityError（供应链信号）必须响亮失败，
    不得被包装成通用 RuntimeError（C-04 在 cleanup 入口的闭环）。"""
    from flashgaze.core.cv_engine import BrisqueIntegrityError

    ws = tmp_path / "ws"
    ws.mkdir()
    _copy_images(ws, ["a.jpg"], fixtures_dir)
    monkeypatch.setattr(
        "flashgaze.core.cleanup.make_scorer",
        _raising_factory(BrisqueIntegrityError("hash mismatch")),
    )
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    with pytest.raises(BrisqueIntegrityError):
        run_cleanup(str(ws), config, dry_run=True)


# ──────────────────────────────────────────────────────────────────────────
# C-01：score / export / cleanup 三入口扫描排除目录一致性（导出副本 + EXIF 备份）
# ──────────────────────────────────────────────────────────────────────────


def test_exclusion_dirs_relative_export_and_backup(tmp_path: Path) -> None:
    """相对 export_dir 解析到 ws 自身；backup 为 ws/.flashgaze_backup（C-01）。"""
    from flashgaze.utils.config import build_config

    ws = tmp_path / "ws"
    ws.mkdir()
    config = build_config(str(ws), no_vlm=True)  # 默认 export_dir = "./精选"

    excl = exclusion_dirs(config, ws.resolve())
    assert isinstance(excl, set)
    assert (ws / "精选").resolve() in excl
    assert (ws / ".flashgaze_backup").resolve() in excl
    # 仅两项，不污染其它目录
    assert excl == {(ws / "精选").resolve(), (ws / ".flashgaze_backup").resolve()}


def test_exclusion_dirs_absolute_export_resolved_as_is(tmp_path: Path) -> None:
    """绝对 export_dir 按原值 resolve，不拼到 ws（C-01）。"""
    from flashgaze.utils.config import build_config

    ws = tmp_path / "ws"
    ws.mkdir()
    abs_export = (tmp_path / "somewhere_else" / "out").resolve()
    config = build_config(str(ws), no_vlm=True, export_dir=str(abs_export))

    excl = exclusion_dirs(config, ws.resolve())
    assert abs_export in excl
    assert (ws / "精选").resolve() not in excl


def test_score_scan_excludes_export_dir(tmp_path: Path, fixtures_dir: Path) -> None:
    """score/export 入口共用的扫描契约：ws 内置 ./精选 副本不被枚举（C-01）。

    两入口均走 iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws))，
    故该集成测试等价于验证 score_images / export_selected_images / _cmd_score
    扫描阶段不会把已导出副本重新扫描、评分并污染统计。
    """
    from flashgaze.utils.config import build_config

    ws = tmp_path / "ws"
    ws.mkdir()
    _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    export = ws / "精选"
    export.mkdir()
    shutil.copy(fixtures_dir / "sharp.jpg", export / "sel.jpg")
    backup = ws / ".flashgaze_backup"
    backup.mkdir()
    shutil.copy(fixtures_dir / "blurry.jpg", backup / "bk.jpg")

    config = build_config(str(ws), no_vlm=True)
    seen = {Path(p).name for p in iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws))}

    assert seen == {"a.jpg", "b.jpg"}  # 仅源目录图片
    assert "sel.jpg" not in seen  # 导出副本被排除
    assert "bk.jpg" not in seen  # 备份图被排除


def test_score_images_passes_exclude_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """score_images 入口把 exclusion_dirs 传入 iter_images（与 cleanup 对齐，C-01）。"""
    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        "flashgaze.mcp_server.iter_images",
        lambda directory, recursive=True, exclude_dirs=(): calls.setdefault("args", (directory, exclude_dirs)) or [],
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    mcp.score_images(str(ws), no_vlm=True, workers=1)

    assert "args" in calls, "iter_images 应被 score_images 调用"
    _, exclude_dirs_arg = calls["args"]
    assert exclude_dirs_arg, "score_images 必须传入非空 exclude_dirs"
    assert (ws / "精选").resolve() in exclude_dirs_arg
    assert (ws / ".flashgaze_backup").resolve() in exclude_dirs_arg


def test_export_selected_images_passes_exclude_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """export_selected_images 入口把 exclusion_dirs 传入 iter_images（C-01）。"""
    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        "flashgaze.mcp_server.iter_images",
        lambda directory, recursive=True, exclude_dirs=(): calls.setdefault("args", (directory, exclude_dirs)) or [],
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    # dest_dir 必须位于 workspace 内（M2 路径穿越防护）；不可为 ws 的兄弟目录，否则
    # export_selected_images 在调用 iter_images 前即返回参数错误。
    dest = ws / "exported"
    dest.mkdir()
    mcp.export_selected_images(str(ws), no_vlm=True, workers=1, dest_dir=str(dest))

    assert "args" in calls, "iter_images 应被 export_selected_images 调用"
    _, exclude_dirs_arg = calls["args"]
    assert exclude_dirs_arg, "export_selected_images 必须传入非空 exclude_dirs"
    assert (ws / "精选").resolve() in exclude_dirs_arg
    assert (ws / ".flashgaze_backup").resolve() in exclude_dirs_arg


def test_cleanup_workspace_images_passes_exclude_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cleanup_workspace_images（MCP 清理入口）也复用 exclusion_dirs 单一真源（C-01）。

    同时验证 backup 目录经 resolve 后生效——此前该入口内联逻辑未对 backup 做
    resolve，与 iter_images 内部按绝对路径比对不一致，会导致备份目录实际未被排除。
    """
    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        "flashgaze.mcp_server.iter_images",
        lambda directory, recursive=True, exclude_dirs=(): calls.setdefault("args", (directory, exclude_dirs)) or [],
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    mcp.cleanup_workspace_images(str(ws), no_vlm=True, workers=1)

    assert "args" in calls, "iter_images 应被 cleanup_workspace_images 调用"
    _, exclude_dirs_arg = calls["args"]
    assert exclude_dirs_arg, "cleanup_workspace_images 必须传入非空 exclude_dirs"
    assert (ws / "精选").resolve() in exclude_dirs_arg
    assert (ws / ".flashgaze_backup").resolve() in exclude_dirs_arg


# ── C-05：cleanup 复用预评分，避免对已损坏/已评图重复解码与重算 ──


def _call_tracking_factory(calls: list[list[str]]) -> Callable[[Config], Any]:
    """make_scorer 替身：记录每次 score_paths 收到的路径列表；把图标为低分待删。"""

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return [
                ImageScore(
                    file=Path(p).name,
                    path=p,
                    sharpness=0.0,
                    exposure=0.0,
                    composition=None,
                    vlm_adjustment=0.0,
                    score=10.0,
                    selected=False,
                )
                for p in images
            ]

    return lambda cfg: _Scorer()


def test_resolve_scored_reuses_and_rescores(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_resolve_scored：scored 覆盖的复用、缺失的重算，最终顺序以 images 为准
    （trust_scored=True 显式信任路径，C-09）。"""
    from flashgaze.core.cleanup import _resolve_scored

    ws = tmp_path / "ws"
    ws.mkdir()
    a, b, c = _copy_images(ws, ["a.jpg", "b.jpg", "c.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])  # a,b 已评分
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    # 仅 a,c 在磁盘（b 不在 images 中 → 被丢弃；c 缺失 → 重算）
    final, source = _resolve_scored([str(a), str(c)], scored, config, trust_scored=True)

    paths = [Path(s.path).resolve() for s in final]
    assert source == "caller"  # C-09：信任路径返回 caller 口径
    assert paths == [a.resolve(), c.resolve()]
    assert final[0].selected is True  # 默认 top=30 复算后复用项仍入选
    assert len(calls) == 1  # 仅 c 触发重算
    assert {Path(p).name for p in calls[0]} == {"c.jpg"}


def test_run_cleanup_reuses_scored_skips_rescore(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """提供 scored 且显式 trust_scored=True 时全部复用、不调用评分引擎重算；

    top/threshold 对复用项统一生效。默认（trust_scored=False）仅复用损坏标记、
    分数重算，由 test_resolve_scored_untrusted_* 与核心反例覆盖（C-09）。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=True, scored=scored, trust_scored=True)

    assert calls == []  # 评分引擎一次都未调用
    assert result["summary"]["total"] == 2
    # 默认 top=30 对复用项统一重算：两张均入选，无删除
    assert result["summary"]["selected"] == 2
    assert result["summary"]["to_delete"] == 0


def test_reuse_scored_top_honored_on_reused(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归：复用 scored 时 top 对复用项生效（消除"调参无效"陷阱）。

    原评分报告 a 入选、b 落选；传入 top=1 后仅最高分 a 入选、b 删除，且不计分引擎。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True, top=1)
    result = run_cleanup(str(ws), config, dry_run=True, scored=scored, trust_scored=True)

    assert calls == []  # 未重算
    assert result["summary"]["selected"] == 1  # 仅 a 入选
    assert result["summary"]["to_delete"] == 1  # b 被删
    assert result["summary"]["total"] == 2


def test_reuse_scored_threshold_honored_on_reused(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归：复用 scored 时 threshold 对复用项生效。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True, threshold=50.0)
    result = run_cleanup(str(ws), config, dry_run=True, scored=scored, trust_scored=True)

    assert calls == []  # 未重算
    assert result["summary"]["selected"] == 1  # a(90)>=50 入选，b(10) 落选
    assert result["summary"]["to_delete"] == 1
    assert result["summary"]["total"] == 2


def test_run_cleanup_rescores_only_missing(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scored 仅覆盖部分图时，仅对缺失图重算（trust_scored=True：已评分图复用）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    a, _, _ = _copy_images(ws, ["a.jpg", "b.jpg", "c.jpg"], fixtures_dir)
    scored = _mk_scores([a], [True], [90.0])  # 仅 a 已评分
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    run_cleanup(str(ws), config, dry_run=True, scored=scored, trust_scored=True)

    assert len(calls) == 1
    seen = {Path(p).name for p in calls[0]}
    assert seen == {"b.jpg", "c.jpg"}  # 仅缺失的 b/c 重算，a 复用


def test_run_cleanup_corrupt_scored_reused_not_redecoded(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已损坏图（error）在 scored 中提供时复用并归入 unevaluated，不再触发重解码
    （trust_scored=True 信任路径；默认路径的损坏占位由
    test_resolve_scored_untrusted_reuses_error_only_not_redecoded 覆盖）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    good, bad = _copy_images(ws, ["good.jpg", "bad.jpg"], fixtures_dir)
    scored = [
        ImageScore(
            file="good.jpg",
            path=str(good),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=90.0,
            selected=True,
        ),
        ImageScore(
            file="bad.jpg",
            path=str(bad),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
            error="解码失败",
        ),
    ]
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    result = run_cleanup(str(ws), config, dry_run=True, scored=scored, trust_scored=True)

    assert calls == []  # 已损坏图未触发重解码
    assert result["summary"]["total"] == 2
    assert result["summary"]["unevaluated"] == 1
    assert "bad.jpg" in [u["file"] for u in result["unevaluated"]]


def test_run_cleanup_scored_none_full_rescore(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scored=None 时保持旧行为：全量重算（回退路径逐字等价）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _, _ = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    run_cleanup(str(ws), config, dry_run=True)  # scored=None

    assert len(calls) == 1
    seen = {Path(p).name for p in calls[0]}
    assert seen == {"a.jpg", "b.jpg"}


def test_cleanup_workspace_images_reuses_scored(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP 清理入口显式 trust_scored=True 时复用、不重算；top/threshold 对复用项统一生效
    （C-09：默认仅复用损坏标记、分数重算，由核心反例用例覆盖）。"""
    import json as _json

    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))

    result = mcp.cleanup_workspace_images(
        str(ws), no_vlm=True, workers=1, scored=scored, trust_scored=True
    )
    payload = _json.loads(result)
    assert payload.get("code", -1) == 0  # 成功响应，非 _error
    assert payload["summary"]["total"] == 2
    # 默认 top=30 对复用项统一重算：两张均入选，无删除
    assert payload["summary"]["selected"] == 2
    assert payload["summary"]["to_delete"] == 0
    assert calls == []  # 全量复用，评分引擎未调用


def test_cleanup_workspace_images_reuse_scored_top_honored(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP 层回归：复用 scored 时 top 对复用项生效（仅最高分入选，其余删除）。"""
    import json as _json

    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scored = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))

    result = mcp.cleanup_workspace_images(
        str(ws), no_vlm=True, workers=1, top=1, scored=scored, trust_scored=True
    )
    payload = _json.loads(result)
    assert payload.get("code", -1) == 0
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["selected"] == 1  # 仅 a 入选
    assert payload["summary"]["to_delete"] == 1  # b 删除
    assert calls == []  # 未重算


# ── C-09：scored 来源可信度分级（伪造预评分不得指定删除集合）──


def test_resolve_scored_untrusted_ignores_forged_scores(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认（trust_scored=False）不信任入参分数：伪造高分无效，分数一律重算。

    伪造 scored 声称 a 高分（保留）、b 低分（删除），桩引擎给出相反的真实口径；
    修复后最终分数必须来自引擎，伪造值被整体丢弃。
    """
    from flashgaze.core.cleanup import _resolve_scored

    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    forged = _mk_scores([a, b], [True, False], [95.0, 5.0])  # 伪造：a 留 b 删
    real = _mk_scores([a, b], [False, True], [5.0, 95.0])  # 引擎口径相反
    calls: list[list[str]] = []

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return real

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    final, source = _resolve_scored([str(a), str(b)], forged, config)

    by_path = {Path(s.path).resolve(): s for s in final}
    assert by_path[a.resolve()].score == 5.0  # 引擎值；伪造的 95 分被丢弃
    assert by_path[b.resolve()].score == 95.0
    assert source == "engine_with_caller_errors"
    assert len(calls) == 1
    assert {Path(p).name for p in calls[0]} == {"a.jpg", "b.jpg"}  # 全量重算


def test_resolve_scored_untrusted_reuses_error_only_not_redecoded(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认路径仍复用损坏标记（error 占位不重解码），分数与其余图一律重算。"""
    from flashgaze.core.cleanup import _resolve_scored

    ws = tmp_path / "ws"
    ws.mkdir()
    good, bad = _copy_images(ws, ["good.jpg", "bad.jpg"], fixtures_dir)
    scored = [
        ImageScore(
            file="good.jpg",
            path=str(good),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=99.0,  # 伪造高分
            selected=True,
        ),
        ImageScore(
            file="bad.jpg",
            path=str(bad),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
            error="解码失败",
        ),
    ]
    calls: list[list[str]] = []

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return _mk_scores([Path(p) for p in images], [True] * len(images), [42.0] * len(images))

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)
    final, source = _resolve_scored([str(good), str(bad)], scored, config)

    by_name = {s.file: s for s in final}
    assert by_name["bad.jpg"].error == "解码失败"  # 损坏标记复用，不重解码
    assert by_name["bad.jpg"].score == 0.0
    assert by_name["good.jpg"].score == 42.0  # 引擎值；伪造的 99 分被丢弃
    assert source == "engine_with_caller_errors"
    assert len(calls) == 1
    assert {Path(p).name for p in calls[0]} == {"good.jpg"}  # 仅正常图重算


def test_cleanup_forged_scores_rejected_by_default(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """核心反例（MCP 层）：伪造预评分默认不得影响删除集合。

    攻击链：Agent 传想保留的图 100 分、想删的图 0 分的 scored + top=3 → 旧实现
    按伪造分数排序，删除集合由调用方逐图指定且在 summary 中不可见。修复后默认
    仅复用损坏标记、分数全量重算，删除决策回到评分引擎口径。
    """
    import json as _json

    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    ws, paths = _mk_ws(tmp_path, fixtures_dir, 6)
    keep, delete = paths[:3], paths[3:]
    # 伪造预评分：keep 三张 100 分、delete 三张 0 分
    forged = _mk_scores(keep, [True] * 3, [100.0] * 3) + _mk_scores(delete, [False] * 3, [0.0] * 3)
    # 桩引擎真实口径与伪造相反：keep 三张低分、delete 三张高分
    real = _mk_scores(keep, [False] * 3, [10.0] * 3) + _mk_scores(delete, [True] * 3, [80.0] * 3)
    calls: list[list[str]] = []

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return real

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())

    result = mcp.cleanup_workspace_images(str(ws), no_vlm=True, workers=1, top=3, scored=forged)
    payload = _json.loads(result)
    assert payload.get("code", -1) == 0
    # 既有契约：dry_run 下 details.deleted_files 承载待删清单（mcp_server L730-732）
    pending = set(payload["details"]["deleted_files"])
    # 引擎口径：keep 低分 → 待删；delete 高分 → 入选。伪造口径必须被完全丢弃。
    assert pending == {p.name for p in keep}
    assert payload["summary"]["scored_source"] == "engine_with_caller_errors"
    assert len(calls) == 1
    assert len(calls[0]) == 6  # 全量重算


def test_resolve_scored_trusted_validates_range(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """trust_scored=True 校验：非法分数（-1/100.01/NaN/±Inf）ValueError；端点 0/100 放行。

    增强类（C-09）：改动前因 trust_scored 参数不存在而 TypeError，校验不存在。
    """
    from flashgaze.core.cleanup import _resolve_scored

    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    paths = [str(a), str(b)]

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            raise AssertionError("校验失败不应触发重算")

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)

    for bad in (-1.0, 100.01, float("nan"), float("inf"), float("-inf")):
        forged = _mk_scores([a, b], [True, False], [50.0, bad])
        with pytest.raises(ValueError, match="非法分数"):
            _resolve_scored(paths, forged, config, trust_scored=True)

    # 端点 0.0 / 100.0 合法（trust 路径放行，复用不重算）
    for edge in (0.0, 100.0):
        scored = _mk_scores([a, b], [True, False], [edge, edge])
        final, source = _resolve_scored(paths, scored, config, trust_scored=True)
        assert source == "caller"
        assert {s.score for s in final} == {edge}


def test_run_cleanup_scored_source_annotated(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cleanup 的 summary.scored_source 三态回填（engine / engine_with_caller_errors / caller）。

    增强类（C-09）：改动前 summary 无 scored_source 键。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    a, b = _copy_images(ws, ["a.jpg", "b.jpg"], fixtures_dir)
    scores = _mk_scores([a, b], [True, False], [90.0, 10.0])
    calls: list[list[str]] = []
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _call_tracking_factory(calls))
    from flashgaze.utils.config import build_config

    config = build_config(str(ws), no_vlm=True)

    r1 = run_cleanup(str(ws), config, dry_run=True)
    assert r1["summary"]["scored_source"] == "engine"
    r2 = run_cleanup(str(ws), config, dry_run=True, scored=scores)
    assert r2["summary"]["scored_source"] == "engine_with_caller_errors"
    r3 = run_cleanup(str(ws), config, dry_run=True, scored=scores, trust_scored=True)
    assert r3["summary"]["scored_source"] == "caller"


def test_cleanup_scored_source_annotated(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP 层 summary.scored_source 三态标注（增强类 C-09：改动前无此键）。"""
    import json as _json

    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    ws, paths = _mk_ws(tmp_path, fixtures_dir, 2)
    scores = _mk_scores(paths, [True, False], [90.0, 10.0])
    calls: list[list[str]] = []

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return scores

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())

    # ① scored=None → engine（全量重算）
    r1 = _json.loads(mcp.cleanup_workspace_images(str(ws), no_vlm=True, workers=1))
    assert r1["summary"]["scored_source"] == "engine"
    assert len(calls) == 1
    # ② scored 默认 → engine_with_caller_errors（分数丢弃重算）
    r2 = _json.loads(mcp.cleanup_workspace_images(str(ws), no_vlm=True, workers=1, scored=scores))
    assert r2["summary"]["scored_source"] == "engine_with_caller_errors"
    assert len(calls) == 2
    # ③ trust_scored=True → caller（复用不重算）
    r3 = _json.loads(
        mcp.cleanup_workspace_images(
            str(ws), no_vlm=True, workers=1, scored=scores, trust_scored=True
        )
    )
    assert r3["summary"]["scored_source"] == "caller"
    assert len(calls) == 2  # 未再触发重算


def test_cleanup_trust_scored_invalid_score_rejected(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """trust_scored=True 且分数非法 → 整体拒绝执行（code=4、status=error、一张未删）。

    增强类（C-09）：拒绝发生在评分之前（make_scorer 零调用）；改动前无该校验。
    """
    import json as _json

    # mcp 为可选 extras 依赖：缺失时跳过而非报错（与 tests/test_mcp_server.py:20 守卫对齐）
    pytest.importorskip("mcp")
    import flashgaze.mcp_server as mcp

    ws, paths = _mk_ws(tmp_path, fixtures_dir, 2)
    calls: list[list[str]] = []

    class _Scorer:
        def score_paths(
            self, images: list[str], progress_callback: Callable[[int, int], None] | None = None
        ) -> list[ImageScore]:
            calls.append(list(images))
            return _mk_scores(paths, [True] * len(paths), [50.0] * len(paths))

    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", lambda cfg: _Scorer())

    for bad_score in (-1.0, 100.01, float("nan"), float("inf")):
        forged = _mk_scores(paths, [True] * 2, [50.0, bad_score])
        payload = _json.loads(
            mcp.cleanup_workspace_images(
                str(ws), no_vlm=True, workers=1, scored=forged, trust_scored=True
            )
        )
        assert payload.get("code") == 4, bad_score
        assert payload["status"] == "error"
        assert "非法分数" in payload["message"], bad_score
        assert calls == []  # 拒绝发生在评分之前，未触发任何重算


# ── 95% 批量删除护栏（FIX #sec-threshold）──────────────
# 防御：threshold 越界/配置错误让全部图落选 → 一次调用删空整个工作空间。


def _mk_ws(tmp_path: Path, fixtures_dir: Path, n: int) -> tuple[Path, list[Path]]:
    """造含 n 张真实图片的工作空间，返回 (ws, 图片路径列表)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    paths = _copy_images(ws, [f"img{i:02d}.jpg" for i in range(n)], fixtures_dir)
    return ws, paths


def test_bulk_delete_guard_blocks_without_force(tmp_path: Path, fixtures_dir: Path) -> None:
    """待删 100% 且非 dry_run 且未 force → 整批拦截，一张不删。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["mode"] == "actual_delete"
    assert result["summary"]["to_delete"] == 25
    assert result["summary"]["deleted"] == 0  # 一张未删
    assert result["summary"]["blocked"] == 25
    assert result["summary"]["force_required"] is True
    assert len(result["deleted"]) == 0
    assert all("95%" in b["reason"] for b in result["blocked"])
    # LOW-2: 结构化 kind 统一为 guard（调用方按 kind 判定，不耦合 reason 文案）
    assert all(b["kind"] == "guard" for b in result["blocked"])
    # 护栏 reason 不得以"删除失败"开头（entry.py 据此映射 EXPORT_ERROR）
    assert not any(b["reason"].startswith("删除失败") for b in result["blocked"])
    assert all(p.exists() for p in paths)  # 磁盘文件完好


def test_bulk_delete_guard_force_deletes(tmp_path: Path, fixtures_dir: Path) -> None:
    """force=True + 已核对的清单指纹：整批真实移入回收站，blocked 为空。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)
    # 先 dry_run 取清单指纹：force 必须与「已人工核对过的那份清单」绑定
    fingerprint = classify_and_delete(ws, scored, dry_run=True)["summary"]["fingerprint"]

    result = classify_and_delete(
        ws, scored, dry_run=False, force=True, confirm_fingerprint=fingerprint
    )

    assert result["summary"]["deleted"] == 25
    assert result["summary"]["blocked"] == 0
    assert result["summary"]["force_required"] is False
    assert len(result["delete_audit"]) == 25
    # 真实文件系统验证：25 张全部移入回收站，原路径无残留，字节完整
    assert all(not p.exists() for p in paths)
    moved = _recycle_files(ws)
    assert len(moved) == 25  # 全部走回收站移动，无一张直接 unlink
    fixture_bytes = (fixtures_dir / "sharp.jpg").read_bytes()
    assert all(p.read_bytes() == fixture_bytes for p in moved)


def test_bulk_delete_guard_not_applied_on_dry_run(tmp_path: Path, fixtures_dir: Path) -> None:
    """dry_run 不受护栏影响（只报告不删除，无需 force）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)

    result = classify_and_delete(ws, scored, dry_run=True)

    assert result["summary"]["pending"] == 25
    assert result["summary"]["blocked"] == 0
    assert result["summary"]["force_required"] is False


def test_bulk_delete_guard_skips_small_sample(tmp_path: Path, fixtures_dir: Path) -> None:
    """小样本豁免：不足 6 张不启用护栏（1~3 张的小目录删 1 张即 33%~100%）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 5)
    scored = _mk_scores(paths, [False] * 5, [1.0] * 5)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 5
    assert result["summary"]["force_required"] is False
    # 真实文件系统验证：5 张全部移入回收站，原路径无残留
    assert all(not p.exists() for p in paths)
    assert len(_recycle_files(ws)) == 5


def test_guard_min_sample_boundary(tmp_path: Path, fixtures_dir: Path) -> None:
    """默认 guard_min_sample=6 的边界：6 张 100% 待删 → 拦截；5 张 → 豁免。

    小目录同样暴露在 threshold 配置错误之下（如 --threshold 100 全不达标），
    下调最小样本量让 6 张以上的目录获得 95% 比例护栏保护。
    """
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 6)
    scored = _mk_scores(paths, [False] * 6, [1.0] * 6)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["force_required"] is True
    assert result["summary"]["deleted"] == 0
    assert all(p.exists() for p in paths)

    (tmp_path / "small").mkdir()
    ws5, paths5 = _mk_ws(tmp_path / "small", fixtures_dir, 5)
    scored5 = _mk_scores(paths5, [False] * 5, [1.0] * 5)
    result5 = classify_and_delete(ws5, scored5, dry_run=False)
    assert result5["summary"]["force_required"] is False
    assert result5["summary"]["deleted"] == 5


def test_guard_min_sample_param_override(tmp_path: Path, fixtures_dir: Path) -> None:
    """guard_min_sample 参数化生效：更小阈值保护更小目录（调用方按场景收紧）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 5)
    scored = _mk_scores(paths, [False] * 5, [1.0] * 5)

    result = classify_and_delete(ws, scored, dry_run=False, guard_min_sample=3)

    assert result["summary"]["force_required"] is True  # 5 >= 3 且 100% 待删
    assert result["summary"]["deleted"] == 0


def test_guard_min_sample_invalid_clamped_not_disabled(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """guard_min_sample 非法（0/负数）→ 钳到 1，绝不关闭护栏（放行走 force+指纹）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 2)
    scored = _mk_scores(paths, [False] * 2, [1.0] * 2)

    result = classify_and_delete(ws, scored, dry_run=False, guard_min_sample=0)

    assert result["summary"]["force_required"] is True  # 2 >= 1 且 100% → 拦截
    assert result["summary"]["deleted"] == 0


def test_bulk_delete_guard_not_diluted_by_unevaluated(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """护栏分母用可评分图口径：损坏图不计入分母，比例不被稀释。

    25 图 = 20 低分（error=None）+ 5 损坏（error 非 None）：损坏图本就不进
    to_delete，若计入分母则 20/25=80%<95% 护栏失效，一次删空全部 20 张可评分
    图、用户只剩 5 张损坏图——正是护栏要防的「配置错误删空工作空间」在
    「目录混有损坏图」条件下的绕过。可评分口径下 20/20=100%>95% → 拦截。
    """
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)
    # 前 5 张标记为损坏图（error 非 None）→ unevaluated，不参与比例
    scored = [replace(s, error="解码失败") if i < 5 else s for i, s in enumerate(scored)]

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["unevaluated"] == 5
    assert result["summary"]["to_delete"] == 20
    assert result["summary"]["force_required"] is True
    assert result["summary"]["deleted"] == 0  # 一张未删
    assert result["summary"]["blocked"] == 20
    assert all(b["kind"] == "guard" for b in result["blocked"])
    assert all("95%" in b["reason"] for b in result["blocked"])
    assert all(p.exists() for p in paths)  # 磁盘文件完好（含 5 张损坏图）


def test_guard_boundary_95pct_of_scoreable_not_triggered(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """反例（不应命中）：待删恰为可评分图的 95% → 不拦截（`>` 而非 `>=`）。

    25 图 = 19 低分 + 1 入选 + 5 损坏：19/20=95% 不大于 95%，护栏不触发，
    正常删除 19 张。锁「修复不过度收紧、不改变既定 95% 阈值策略」。
    """
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 19 + [True] + [False] * 5, [1.0] * 19 + [90.0] + [1.0] * 5)
    scored = [replace(s, error="解码失败") if i >= 20 else s for i, s in enumerate(scored)]

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["force_required"] is False
    assert result["summary"]["deleted"] == 19
    assert result["summary"]["unevaluated"] == 5
    # 真实文件系统验证：19 张低分图移入回收站，入选图与损坏图原位保留
    assert all(not paths[i].exists() for i in range(19))
    assert paths[19].exists()
    assert all(p.exists() for p in paths[20:])
    assert len(_recycle_files(ws)) == 19


def test_guard_ignores_unevaluated_when_ratio_moderate(tmp_path: Path, fixtures_dir: Path) -> None:
    """反例（不应命中）：含损坏图但比例中等 → 正常删除，不受分母口径影响。

    25 图 = 10 损坏 + 10 低分 + 5 入选：10/15≈66.7%<95%，护栏不触发。
    """
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(
        paths, [False] * 10 + [True] * 5 + [False] * 10, [1.0] * 10 + [90.0] * 5 + [1.0] * 10
    )
    scored = [replace(s, error="解码失败") if i < 10 else s for i, s in enumerate(scored)]

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["force_required"] is False
    assert result["summary"]["deleted"] == 10
    assert result["summary"]["unevaluated"] == 10
    # 真实文件系统验证：10 张低分图移入回收站，损坏图与入选图原位保留
    assert all(p.exists() for p in paths[:15])
    assert all(not p.exists() for p in paths[15:])
    assert len(_recycle_files(ws)) == 10


def test_all_unevaluated_no_guard_no_crash(tmp_path: Path, fixtures_dir: Path) -> None:
    """边界：全部为损坏图（可评分图=0）→ 除零保护，不崩溃、无待删项。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 7)
    scored = _mk_scores(paths, [False] * 7, [1.0] * 7)
    scored = [replace(s, error="解码失败") for s in scored]

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["to_delete"] == 0
    assert result["summary"]["force_required"] is False
    assert result["summary"]["deleted"] == 0
    assert result["summary"]["unevaluated"] == 7
    assert all(p.exists() for p in paths)


def test_run_cleanup_forwards_force(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cleanup 透传 force：未传则护栏拦截，传入则删除。"""
    from flashgaze.utils.config import build_config

    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))
    config = build_config(str(ws), no_vlm=True)

    blocked = run_cleanup(str(ws), config, dry_run=False)
    assert blocked["summary"]["deleted"] == 0
    assert blocked["summary"]["force_required"] is True
    assert all(p.exists() for p in paths)  # 拦截时文件原位保留
    assert not (ws / ".flashgaze_deleted").exists()  # 拦截时零副作用
    assert not list(ws.glob(".flashgaze_deleted_*.jsonl"))  # 不落审计清单

    fingerprint = run_cleanup(str(ws), config, dry_run=True)["summary"]["fingerprint"]
    forced = run_cleanup(
        str(ws), config, dry_run=False, force=True, confirm_fingerprint=fingerprint
    )
    assert forced["summary"]["deleted"] == 25
    # 真实文件系统验证：25 张全部移入回收站，原路径无残留
    assert all(not p.exists() for p in paths)
    assert len(_recycle_files(ws)) == 25


# ── LOW-2: blocked 项结构化 kind 字段 ───────────────────


def test_classify_and_delete_failure_kind_structured(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回收站移动抛 OSError 时，blocked 项携带 kind="delete_failure"，reason 保留原文。

    entry.py 退出码判定已改为消费 kind 字段（LOW-2），不再与 reason 文案前缀
    强耦合；本用例锁死 kind 契约，文案改动不再静默破坏退出码语义。

    保留类级 patch 的理由：pytest monkeypatch fixture 在 teardown 自动还原
    （断言抛异常亦还原）；真实文件系统无法跨平台构造 rename 失败（Windows 占用
    句柄法在 Linux 上 rename 照常成功，目录占位被 _recycle_target 冲突后缀逻辑
    化解），依 M-18 纪律保留此真实故障注入。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [False] * 3, [1.0] * 3)

    def _deny(self: Path, target: Path) -> None:
        raise PermissionError(13, "模拟文件被占用")

    monkeypatch.setattr(Path, "replace", _deny)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 0
    assert len(result["blocked"]) == 3
    assert all(b["kind"] == "delete_failure" for b in result["blocked"])
    assert all(b["reason"].startswith("删除失败") for b in result["blocked"])
    assert all(p.exists() for p in paths)  # 文件完好


# ──────────────────────────────────────────────────────────────────────────
# 回收站删除 + 删除审计清单（不可逆删除防护）
#
# 硬要求：实际删除绝不直接 unlink——先同卷 rename 到 ws/.flashgaze_deleted/<批>/
# 保留原相对路径，再落盘审计清单（原路径 / 回收站路径 / SHA256 / 大小 / 评分），
# 使删除可追溯、可回滚。审计与哈希均为 best-effort：失败仅告警，不阻断删除。
# ──────────────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    """计算文件 SHA256（测试侧独立实现，不复用被测代码，避免自证）。"""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recycle_files(ws: Path) -> list[Path]:
    """回收站内全部文件（.flashgaze_deleted 为隐藏目录，iter_images 不会扫到）。"""
    root = ws / ".flashgaze_deleted"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    """读取审计清单（JSONL），跳过空行。"""
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def test_actual_delete_moves_files_to_recycle_dir(tmp_path: Path, fixtures_dir: Path) -> None:
    """实际删除不再 unlink：原文件移入 ws/.flashgaze_deleted/<批>/<名>，字节完整。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    a, b, c = paths
    scored = _mk_scores([a, b, c], [True, False, False], [90.0, 10.0, 5.0])

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 2
    assert result["summary"]["recycle"] is True
    assert a.exists()  # 高分图保留
    assert not b.exists() and not c.exists()
    moved = _recycle_files(ws)
    assert [p.name for p in moved] == ["img01.jpg", "img02.jpg"]
    fixture_bytes = (fixtures_dir / "sharp.jpg").read_bytes()
    assert all(p.read_bytes() == fixture_bytes for p in moved)  # 字节完整


def test_actual_delete_writes_audit_manifest(tmp_path: Path, fixtures_dir: Path) -> None:
    """每次实际删除在 workspace 内落盘审计清单，逐张含原路径/回收站路径/SHA256。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])

    result = classify_and_delete(ws, scored, dry_run=False)

    raw_manifest = result["summary"]["delete_manifest"]
    assert raw_manifest is not None
    manifest = Path(raw_manifest)
    assert manifest.is_file()
    assert manifest.parent == ws.resolve()
    assert manifest.name.startswith(".flashgaze_deleted_") and manifest.suffix == ".jsonl"

    records = _read_manifest(manifest)
    assert len(records) == 2
    assert len(result["delete_audit"]) == 2
    fixture = fixtures_dir / "sharp.jpg"
    for rec in records:
        assert rec["workspace"] == str(ws.resolve())
        assert rec["mode"] == "recycle"
        assert rec["sha256"] == _sha256(fixture)
        assert rec["size"] == fixture.stat().st_size
        assert Path(rec["trash_path"]).is_file()  # 回滚路径可定位
        assert not Path(rec["original_path"]).exists()
    assert sorted(Path(r["original_path"]).name for r in records) == ["img01.jpg", "img02.jpg"]


def test_audit_manifest_not_written_in_dry_run(tmp_path: Path, fixtures_dir: Path) -> None:
    """dry_run 零副作用：不创建回收站目录、不落盘审计清单。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])

    result = classify_and_delete(ws, scored, dry_run=True)

    assert result["summary"]["delete_manifest"] is None
    assert result["delete_audit"] == []
    assert not (ws / ".flashgaze_deleted").exists()
    assert not list(ws.glob(".flashgaze_deleted_*.jsonl"))
    assert all(p.exists() for p in paths)


def test_recycle_failure_records_delete_failure_kind(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回收站移动失败（跨卷/占用）→ delete_failure，绝不降级为 unlink。

    类级 patch 经 pytest monkeypatch fixture teardown 自动还原；真实文件系统
    无法跨平台构造 rename 失败，依 M-18 纪律保留此真实故障注入。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])

    def _deny(self: Path, target: Path) -> None:
        raise OSError(18, "模拟跨卷移动失败")

    monkeypatch.setattr(Path, "replace", _deny)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 0
    assert len(result["blocked"]) == 2
    assert all(b["kind"] == "delete_failure" for b in result["blocked"])
    assert all(b["reason"].startswith("删除失败") for b in result["blocked"])
    assert all(p.exists() for p in paths)  # 降级 unlink 会造成"假回收站"


def test_sha256_failure_does_not_block_deletion(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SHA256 计算失败属 best-effort：审计记 null，删除照常进行。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    monkeypatch.setattr("flashgaze.core.cleanup._sha256_file", lambda p: None)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 2
    assert result["summary"]["audit_failed"] is False
    assert all(rec["sha256"] is None for rec in result["delete_audit"])


def test_audit_write_failure_does_not_block_deletion(tmp_path: Path, fixtures_dir: Path) -> None:
    """审计清单落盘失败（只读/磁盘满/路径被目录占用）不阻断删除，只标记 audit_failed。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    # 与回收站根目录同名的路径：移动创建该目录后，清单追加写必然 OSError
    blocked_manifest = ws / ".flashgaze_deleted"

    result = classify_and_delete(ws, scored, dry_run=False, audit_manifest=blocked_manifest)

    assert result["summary"]["deleted"] == 2
    assert result["summary"]["audit_failed"] is True
    assert not paths[1].exists() and not paths[2].exists()


def test_recycle_preserves_nested_relative_layout(tmp_path: Path, fixtures_dir: Path) -> None:
    """子目录图回收后保留相对目录结构，便于按原路径整树恢复。"""
    ws = tmp_path / "ws"
    (ws / "sub" / "deep").mkdir(parents=True)
    img = ws / "sub" / "deep" / "nested.jpg"
    shutil.copy(fixtures_dir / "sharp.jpg", img)
    scored = _mk_scores([img], [False], [1.0])

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 1
    rec = result["delete_audit"][0]
    trash = Path(rec["trash_path"])
    assert trash.is_file()
    assert trash.relative_to(ws / ".flashgaze_deleted").parts[1:] == ("sub", "deep", "nested.jpg")


def test_recycle_name_collision_appends_suffix(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回收站目标名冲突时追加 .1 后缀，绝不覆盖既有回收副本。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    monkeypatch.setattr("flashgaze.core.cleanup._utc_stamp", lambda: "20260101T000000Z")
    batch = ws / ".flashgaze_deleted" / f"deleted_20260101T000000Z_{os.getpid()}"
    batch.mkdir(parents=True)
    (batch / "img01.jpg").write_bytes(b"SENTINEL")

    result = classify_and_delete(ws, scored, dry_run=False)

    assert (batch / "img01.jpg").read_bytes() == b"SENTINEL"  # 既有副本完好
    rec_b = next(r for r in result["delete_audit"] if r["original_path"].endswith("img01.jpg"))
    assert rec_b["trash_path"].endswith("img01.jpg.1")
    assert Path(rec_b["trash_path"]).is_file()


def test_no_recycle_still_writes_audit(tmp_path: Path, fixtures_dir: Path) -> None:
    """--no-recycle（recycle=False）真删，但仍强制写审计清单保证可追溯。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])

    result = classify_and_delete(ws, scored, dry_run=False, recycle=False)

    assert result["summary"]["deleted"] == 2
    assert result["summary"]["recycle"] is False
    assert not (ws / ".flashgaze_deleted").exists()  # 无回收副本
    assert all(r["mode"] == "unlink" and r["trash_path"] is None for r in result["delete_audit"])
    assert not paths[1].exists() and not paths[2].exists()


def test_empty_to_delete_creates_no_recycle_dir(tmp_path: Path, fixtures_dir: Path) -> None:
    """无待删项时不产生空的回收站批目录与审计清单。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, True, True], [90.0, 80.0, 70.0])

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["deleted"] == 0
    assert result["summary"]["delete_manifest"] is None
    assert not (ws / ".flashgaze_deleted").exists()
    assert not list(ws.glob(".flashgaze_deleted_*.jsonl"))
    assert all(p.exists() for p in paths)


# ──────────────────────────────────────────────────────────────────────────
# force 与 dry_run 清单指纹强绑定
#
# 硬要求：--force 不再是无条件放行。它必须与「已人工核对过的 dry_run 清单指纹」
# 绑定——先 dry_run 拿到 summary.fingerprint，再回填 --confirm-fingerprint。
# 缺失或不符 → 整批拦截、一张不删（force_required 同级语义 confirm_required）。
# ──────────────────────────────────────────────────────────────────────────


def test_pending_fingerprint_is_stable_and_path_sensitive(tmp_path: Path) -> None:
    """指纹只取决于已解析绝对路径集合：顺序无关，路径增减即变。"""
    a, b, c = tmp_path / "a.jpg", tmp_path / "b.jpg", tmp_path / "c.jpg"

    fp = pending_fingerprint([a, b])

    assert len(fp) == 12
    assert fp == pending_fingerprint([b, a])  # 顺序无关
    assert fp != pending_fingerprint([a, b, c])  # 清单变化即变
    assert fp != pending_fingerprint([a])


def test_force_without_fingerprint_blocks_everything(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """force=True 但未提供指纹 → 整批拦截、一张不删（force 不得绕过人工核对）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 8)
    scored = _mk_scores(paths, [False] * 8, [1.0] * 8)

    result = classify_and_delete(ws, scored, dry_run=False, force=True)

    assert result["summary"]["deleted"] == 0
    assert result["summary"]["confirm_required"] is True
    assert len(result["blocked"]) == 8
    assert all(b["kind"] == "confirm_required" for b in result["blocked"])
    assert all(p.exists() for p in paths)  # 磁盘完好
    assert not (ws / ".flashgaze_deleted").exists()  # 零副作用


def test_force_with_wrong_fingerprint_blocks(tmp_path: Path, fixtures_dir: Path) -> None:
    """指纹与当前待删清单不符 → 拦截（清单已变，先前的核对不再有效）。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 8)
    scored = _mk_scores(paths, [False] * 8, [1.0] * 8)
    fingerprint = classify_and_delete(ws, scored, dry_run=True)["summary"]["fingerprint"]

    result = classify_and_delete(
        ws, scored, dry_run=False, force=True, confirm_fingerprint="deadbeef1234"
    )

    assert result["summary"]["fingerprint"] == fingerprint  # 报告始终带当前指纹
    assert result["summary"]["confirm_required"] is True
    assert result["summary"]["deleted"] == 0
    assert all(b["kind"] == "confirm_required" for b in result["blocked"])
    assert all(p.exists() for p in paths)


def test_force_with_matching_fingerprint_deletes(tmp_path: Path, fixtures_dir: Path) -> None:
    """dry_run 取指纹 → force + 正确指纹 → 整批移入回收站。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 8)
    scored = _mk_scores(paths, [False] * 8, [1.0] * 8)
    fingerprint = classify_and_delete(ws, scored, dry_run=True)["summary"]["fingerprint"]

    result = classify_and_delete(
        ws, scored, dry_run=False, force=True, confirm_fingerprint=fingerprint
    )

    assert result["summary"]["deleted"] == 8
    assert result["summary"]["confirm_required"] is False
    assert result["summary"]["blocked"] == 0
    assert len(_recycle_files(ws)) == 8
    assert not any(p.exists() for p in paths)


def test_run_cleanup_forwards_confirm_fingerprint(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cleanup 透传 confirm_fingerprint：无指纹拦截，正确指纹放行。"""
    from flashgaze.utils.config import build_config

    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)
    monkeypatch.setattr("flashgaze.core.cleanup.make_scorer", _fake_factory(scored))
    config = build_config(str(ws), no_vlm=True)

    blocked = run_cleanup(str(ws), config, dry_run=False, force=True)
    assert blocked["summary"]["confirm_required"] is True
    assert blocked["summary"]["deleted"] == 0

    fingerprint = run_cleanup(str(ws), config, dry_run=True)["summary"]["fingerprint"]
    forced = run_cleanup(str(ws), config, dry_run=False, force=True, confirm_fingerprint=fingerprint)
    assert forced["summary"]["deleted"] == 25
    assert len(_recycle_files(ws)) == 25


# ──────────────────────────────────────────────────────────────────────────
# restore：按删除审计清单回滚回收站（删除—审计—恢复闭环）
#
# 安全校验（缺一不可）：清单必须存在；original_path 必须落在记录声明的 workspace
# 内（清单被复制/篡改后不得把文件还原到 workspace 外）；回收站副本必须存在；
# 原路径已被占用时绝不覆盖。
# ──────────────────────────────────────────────────────────────────────────


def test_restore_from_manifest_moves_files_back(tmp_path: Path, fixtures_dir: Path) -> None:
    """删除 → restore：文件按审计清单搬回原路径，字节完整，回收站清空。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    result = classify_and_delete(ws, scored, dry_run=False)
    manifest = result["summary"]["delete_manifest"]
    assert manifest is not None

    restore = restore_from_manifest(manifest)

    assert restore["summary"]["restored"] == 2
    assert restore["summary"]["failed"] == 0
    assert not restore["failed"]
    assert paths[1].exists() and paths[2].exists()
    fixture_bytes = (fixtures_dir / "sharp.jpg").read_bytes()
    assert paths[1].read_bytes() == fixture_bytes
    assert paths[2].read_bytes() == fixture_bytes
    assert not _recycle_files(ws)  # 回收站副本已搬走


def test_restore_dry_run_reports_only(tmp_path: Path, fixtures_dir: Path) -> None:
    """restore dry_run 只报告可恢复项，不实际移动。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    result = classify_and_delete(ws, scored, dry_run=False)
    manifest = result["summary"]["delete_manifest"]
    assert manifest is not None

    restore = restore_from_manifest(manifest, dry_run=True)

    assert restore["summary"]["mode"] == "dry_run"
    assert restore["summary"]["pending"] == 2
    assert restore["summary"]["restored"] == 0
    assert not paths[1].exists() and not paths[2].exists()  # 仍在回收站


def test_restore_missing_manifest_raises(tmp_path: Path) -> None:
    """清单不存在 → CleanupError（调用方映射参数错误），不静默返回空结果。"""
    with pytest.raises(CleanupError):
        restore_from_manifest(tmp_path / "nope.jsonl")


def test_restore_blocks_target_outside_workspace(tmp_path: Path, fixtures_dir: Path) -> None:
    """清单被篡改（original_path 逃逸 workspace）→ 该条拒绝，不还原到外面。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 2)
    scored = _mk_scores(paths, [False] * 2, [1.0] * 2)
    result = classify_and_delete(ws, scored, dry_run=False)
    manifest_path = Path(result["summary"]["delete_manifest"])
    assert manifest_path is not None

    records = _read_manifest(manifest_path)
    records[0]["original_path"] = str(tmp_path / "evil.jpg")  # 篡改到 workspace 外
    manifest_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )

    restore = restore_from_manifest(manifest_path)

    assert restore["summary"]["restored"] == 1  # 未被篡改的另一条正常恢复
    assert restore["summary"]["failed"] == 1
    assert restore["failed"][0]["kind"] == "outside_workspace"
    assert not (tmp_path / "evil.jpg").exists()
    assert len(_recycle_files(ws)) == 1  # 被篡改那条的回收站副本原封不动


def test_restore_refuses_when_target_already_exists(tmp_path: Path, fixtures_dir: Path) -> None:
    """原路径已被同名新文件占用 → 拒绝恢复该条，绝不覆盖既有文件。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    result = classify_and_delete(ws, scored, dry_run=False)
    manifest = result["summary"]["delete_manifest"]
    assert manifest is not None
    paths[1].write_bytes(b"NEW FILE")  # 用户在原位放了新文件

    restore = restore_from_manifest(manifest)

    assert restore["summary"]["restored"] == 1
    assert restore["summary"]["failed"] == 1
    assert restore["failed"][0]["kind"] == "target_exists"
    assert paths[1].read_bytes() == b"NEW FILE"  # 新文件完好
    assert paths[2].exists()  # 另一条正常恢复


def test_restore_skips_unlink_mode_records(tmp_path: Path, fixtures_dir: Path) -> None:
    """mode=unlink（--no-recycle）的记录无回收站副本 → 计失败，不误报恢复。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 3)
    scored = _mk_scores(paths, [True, False, False], [90.0, 10.0, 5.0])
    result = classify_and_delete(ws, scored, dry_run=False, recycle=False)
    manifest = result["summary"]["delete_manifest"]
    assert manifest is not None

    restore = restore_from_manifest(manifest)

    assert restore["summary"]["restored"] == 0
    assert restore["summary"]["failed"] == 2
    assert all(f["kind"] == "missing_trash" for f in restore["failed"])


def test_restore_recreates_missing_parent_dirs(tmp_path: Path, fixtures_dir: Path) -> None:
    """子目录图恢复时父目录已不存在 → 自动重建目录再落回原位。"""
    ws = tmp_path / "ws"
    (ws / "sub" / "deep").mkdir(parents=True)
    img = ws / "sub" / "deep" / "nested.jpg"
    shutil.copy(fixtures_dir / "sharp.jpg", img)
    scored = _mk_scores([img], [False], [1.0])
    result = classify_and_delete(ws, scored, dry_run=False)
    manifest = result["summary"]["delete_manifest"]
    assert manifest is not None
    shutil.rmtree(ws / "sub")  # 模拟父目录已被清理

    restore = restore_from_manifest(manifest)

    assert restore["summary"]["restored"] == 1
    assert img.exists()
    assert img.read_bytes() == (fixtures_dir / "sharp.jpg").read_bytes()


# ── _reselect 平分规则（M-04）────────────────────────


def test_reselect_tie_break_by_full_path(tmp_path: Path) -> None:
    """复用预评分时跨目录同名同分图按全路径升序重算 selected（M-04）。

    此前二级键是纯文件名，不同子目录同名文件键值相等，
    top-N 边界花落谁家取决于调用方传入顺序，跨机器不可复现。
    """
    from flashgaze.core.cleanup import _reselect
    from flashgaze.utils.config import build_config

    a_img = tmp_path / "a" / "IMG_0001.jpg"
    b_img = tmp_path / "b" / "IMG_0001.jpg"
    # _reselect 只改 selected 标志不读盘，路径无需真实文件；同名 file、同分、异路径
    scored = _mk_scores([b_img, a_img], [False, False], [80.0, 80.0])
    config = build_config(str(tmp_path), no_vlm=True, top=1)

    _reselect(scored, config)

    # 全路径升序下 a 在前，top=1 应选中 a，与传入顺序（b 在前）无关
    assert [s.path for s in scored if s.selected] == [str(a_img)]


# ── 审计路径一致性：报告同时含原始路径与解析后真实路径（M-09）──


def test_deleted_records_include_resolved_path(tmp_path: Path) -> None:
    """deleted 记录同时含 path（原始串）与 resolved_path（解析后真实路径）。

    unlink 作用于检查点 A 解析后的真实路径（M-09）：报告若只记原始 `..` 串，
    事故复盘无法定位被删文件；常规路径下二者应相等（口径对照）。"""
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    low = ws / "low.jpg"
    ok = ws / "ok.jpg"
    low.write_text("x")
    ok.write_text("x")

    raw_low = str(ws / "sub" / ".." / "low.jpg")
    scored = [
        replace(_mk_scores([low], [False], [0.0])[0], path=raw_low),
        *_mk_scores([ok], [False], [0.0]),
    ]
    result = classify_and_delete(ws, scored, dry_run=False, recycle=False)

    assert result["summary"]["deleted"] == 2
    by_path = {r["path"]: r for r in result["deleted"]}
    assert by_path[raw_low]["resolved_path"] == str(low)  # 解析后真实路径
    assert by_path[str(ok)]["resolved_path"] == str(ok)  # 常规路径二者相等
    assert not low.exists() and not ok.exists()  # 删除仍作用于解析后路径


def test_pending_records_include_resolved_path(tmp_path: Path) -> None:
    """dry_run 报告同样给出 resolved_path（与指纹按解析后路径计算的口径对齐）。"""
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    low = ws / "low.jpg"
    low.write_text("x")

    scored = [
        replace(_mk_scores([low], [False], [0.0])[0], path=str(ws / "sub" / ".." / "low.jpg"))
    ]
    result = classify_and_delete(ws, scored, dry_run=True)

    pending = result["pending_delete"][0]
    assert pending["path"] == str(ws / "sub" / ".." / "low.jpg")
    assert pending["resolved_path"] == str(low)
    assert low.exists()  # dry_run 不动文件


def test_blocked_outside_workspace_records_resolved_path(tmp_path: Path) -> None:
    """outside_workspace 拦截记录 resolved_path，可区分 .. 穿越与链接解析后逃逸。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_text("x")

    scored = [
        replace(_mk_scores([outside], [False], [0.0])[0], path=str(ws / ".." / "outside.jpg"))
    ]
    result = classify_and_delete(ws, scored, dry_run=False)

    blocked = result["blocked"][0]
    assert blocked["kind"] == "outside_workspace"
    assert blocked["path"] == str(ws / ".." / "outside.jpg")  # 原始 .. 穿越串
    assert blocked["resolved_path"] == str(outside)  # 解析后真实落点
    assert outside.exists()


def test_guard_blocked_resolved_path_is_none(tmp_path: Path, fixtures_dir: Path) -> None:
    """guard 为批级拦截（未做路径解析）：resolved_path 显式为 None。"""
    ws, paths = _mk_ws(tmp_path, fixtures_dir, 25)
    scored = _mk_scores(paths, [False] * 25, [1.0] * 25)

    result = classify_and_delete(ws, scored, dry_run=False)

    assert result["summary"]["force_required"] is True
    assert len(result["blocked"]) == 25
    assert all(b["resolved_path"] is None for b in result["blocked"])


def test_symlink_blocked_resolved_path_is_none(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """symlink_path 拦截（检查点 A0）不解析：resolved_path 显式为 None（M-09）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _copy_images(ws, ["real.jpg"], fixtures_dir)
    link = ws / "link.jpg"
    try:
        os.symlink(ws / "real.jpg", link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无符号链接创建权限（Windows 需开发者模式/管理员），未验证")

    scored = _mk_scores([link], [False], [10.0])
    result = classify_and_delete(ws, scored, dry_run=False)

    blocked = [b for b in result["blocked"] if Path(b["path"]).name == "link.jpg"]
    assert blocked and blocked[0]["kind"] == "symlink_path"
    assert blocked[0]["resolved_path"] is None  # A0「不解析」，不报告链接目标


def test_kept_unevaluated_schema_unchanged(tmp_path: Path) -> None:
    """反例：kept / unevaluated 未删除未拦截，schema 不变（不得混入 resolved_path）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_text("x")
    keep = ws / "keep.jpg"
    keep.write_text("x")

    scored = [
        ImageScore(
            file="keep.jpg",
            path=str(keep),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=90.0,
            selected=True,
        ),
        ImageScore(
            file="broken.jpg",
            path=str(ws / "broken.jpg"),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
            error="decode failed",
        ),
        ImageScore(
            file="outside.jpg",
            path=str(ws / ".." / "outside.jpg"),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
            selected=False,
        ),
    ]
    result = classify_and_delete(ws, scored, dry_run=False)

    assert "resolved_path" not in result["kept"][0]
    assert "resolved_path" not in result["unevaluated"][0]
    # blocked 条目原有三键语义不变
    blocked = result["blocked"][0]
    assert blocked["kind"] == "outside_workspace"
    assert "工作空间外" in blocked["reason"]
    assert blocked["path"] == str(ws / ".." / "outside.jpg")
    assert outside.exists()

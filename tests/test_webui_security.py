"""FlashGaze WebUI 安全加固回归测试。

覆盖五类修复（详见 webui/app.py / webui/runner.py 安全改动）：
1. 公网暴露强制鉴权（_is_public_binding / _compute_launch_auth）；
2. 导出目录越界硬拒绝（runner.export_to_dir 复用 is_within_directory）；
3. 图片目录白名单 --allow-root（runner.run_scoring 包含校验，可选）；
4. api_key 控件不再序列化服务端真实密钥（build_app 控件初值）；
5. 清单导出路径收敛：export_manifest 允许根 = 评分目录 ∪ 系统临时目录（M-10）。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import ExitCode
from flashgaze.webui.app import (
    _compute_launch_auth,
    _is_public_binding,
    build_app,
)
from flashgaze.webui.runner import (
    ScoringResult,
    build_run_config,
    export_manifest,
    export_to_dir,
    run_scoring,
)
from tests.webui_helpers import make_result, make_score

# ── 1. _is_public_binding ──────────────────────────────────────────────


def test_is_public_binding_loopback() -> None:
    """回环地址（含空）视为本机，不触发强制鉴权。"""
    assert _is_public_binding("127.0.0.1", False) is False
    assert _is_public_binding("localhost", False) is False
    assert _is_public_binding("::1", False) is False
    assert _is_public_binding("", False) is False
    assert _is_public_binding(None, False) is False


def test_is_public_binding_exposed() -> None:
    """0.0.0.0 / 局域网或公网 IP，以及 --share，均视为对外暴露。"""
    assert _is_public_binding("0.0.0.0", False) is True
    assert _is_public_binding("192.168.1.10", False) is True
    assert _is_public_binding("10.0.0.5", False) is True
    # share 即使回环也强制暴露
    assert _is_public_binding("127.0.0.1", True) is True


# ── 2. _compute_launch_auth ─────────────────────────────────────────────


def test_compute_auth_loopback_no_auth() -> None:
    """仅回环且非 share：返回 None（本地无鉴权，向后兼容）。"""
    assert _compute_launch_auth("127.0.0.1", False, None) is None


def test_compute_auth_share_auto_token(capsys: pytest.CaptureFixture[str]) -> None:
    """对外暴露且无 --auth：自动生成 (admin, token) 并打印到 stderr。"""
    auth = _compute_launch_auth("127.0.0.1", True, None)
    assert auth is not None
    user, token = auth
    assert user == "admin"
    assert token  # 非空随机令牌
    err = capsys.readouterr().err
    assert "强制开启登录鉴权" in err
    assert token in err


def test_compute_auth_explicit_override() -> None:
    """显式 --auth user:pass 优先于自动令牌（含 share 场景）。"""
    assert _compute_launch_auth("0.0.0.0", False, "alice:s3cret") == ("alice", "s3cret")
    assert _compute_launch_auth("127.0.0.1", True, "bob:pw") == ("bob", "pw")


def test_compute_auth_bad_format_falls_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """--auth 格式非法（无冒号）仍退回自动令牌，避免暴露无鉴权，并记告警。"""
    with caplog.at_level(logging.WARNING):
        auth = _compute_launch_auth("0.0.0.0", False, "nopass")
    assert auth is not None
    assert auth[0] == "admin"
    assert any("格式应为 user:password" in r.message for r in caplog.records)


# ── 3. 导出越界硬拒绝 ──────────────────────────────────────────────────


def _result_in(ws: Path) -> ScoringResult:
    """构造位于 ws 的评分结果，并写入真实（假）图片文件供导出复制。"""
    config = build_run_config(str(ws), ScoringOptions(no_vlm=True))
    scored = [
        make_score("a.jpg", str(ws / "a.jpg"), score=90.0, selected=True),
        make_score("b.jpg", str(ws / "b.jpg"), score=50.0, selected=False),
    ]
    (ws / "a.jpg").write_bytes(b"fake-a")
    (ws / "b.jpg").write_bytes(b"fake-b")
    return make_result(scored, config=config)


def test_export_outside_workspace_rejected(tmp_path: Path) -> None:
    """导出到 workspace 外的绝对路径：硬拒绝（move=True 也受同一闸门约束）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    result = _result_in(ws)
    count, msg = export_to_dir(result, str(outside), move=True)
    assert count == 0
    assert "已拒绝" in msg


def test_export_inside_workspace_allowed(tmp_path: Path) -> None:
    """导出到 workspace 内的子目录：放行并真实复制入选图。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "精选"
    result = _result_in(ws)
    count, msg = export_to_dir(result, str(out))
    assert "已拒绝" not in msg
    # 仅入选的 a.jpg 被复制（b.jpg 未入选）
    assert count == 1
    assert (out / "a.jpg").exists()
    assert not (out / "b.jpg").exists()


def test_export_relative_dir_resolves_against_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-1 契约对齐：相对导出目录以评分目录为基准解析，与进程 CWD 无关。

    Gradio 进程 CWD ≠ 评分目录时（常态），默认 ./精选 此前按 CWD 解析后被
    越界防护误拒；现应与 CLI 一致落到评分目录内的 精选/。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(tmp_path)  # CWD = ws 父目录，≠ 评分目录
    result = _result_in(ws)
    count, msg = export_to_dir(result, "./精选")
    assert "已拒绝" not in msg
    assert count == 1
    assert (ws / "精选" / "a.jpg").exists()
    # 不得按 CWD 落盘（证明解析基准确为评分目录）
    assert not (tmp_path / "精选").exists()


def test_export_relative_escape_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """相对路径的 .. 逃逸同样被硬拒绝（与绝对路径越界同强度）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)  # CWD = ws，使 ../escape 与旧行为可比
    result = _result_in(ws)
    count, msg = export_to_dir(result, "../outside")
    assert count == 0
    assert "已拒绝" in msg
    assert not (tmp_path / "outside").exists()


def test_export_partial_failure_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """H-9(WebUI)：部分图导出失败时，状态文案与日志必须暴露失败数。

    源文件在评分后被外部删除是真实场景（磁盘满/权限不足同族）：此前 `export_to_dir`
    只回成功数，状态栏显示「复制 1 张到 …」，用户拿到不完整的精选集却毫不知情——
    与 CLI 退出码 5 / MCP `status="partial"` 的既有语义不一致。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.jpg").write_bytes(b"fake-a")
    config = build_run_config(str(ws), ScoringOptions(no_vlm=True))
    scored = [
        make_score("a.jpg", str(ws / "a.jpg"), score=90.0, selected=True),
        # 入选但源文件已消失（评分后被外部删除），导出时进入 last_failures
        make_score("c.jpg", str(ws / "c.jpg"), score=85.0, selected=True),
    ]
    result = make_result(scored, config=config)

    with caplog.at_level(logging.ERROR):
        count, msg = export_to_dir(result, str(ws / "out"))

    assert count == 1
    # 前缀逐字保留（e2e 断言状态以「复制」开头），失败信息追加在句尾
    assert msg.startswith("复制 1 张到")
    assert "1 张导出失败" in msg
    assert "c.jpg" in msg
    assert any("导出部分失败" in r.message for r in caplog.records)


def test_export_all_failed_reports_every_item(tmp_path: Path) -> None:
    """边界：全部入选图都导出失败（成功数 0）时，失败数与逐项原因仍完整可见。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    config = build_run_config(str(ws), ScoringOptions(no_vlm=True))
    scored = [
        make_score("c.jpg", str(ws / "c.jpg"), score=90.0, selected=True),
        make_score("d.jpg", str(ws / "d.jpg"), score=85.0, selected=True),
    ]  # 两个源文件都不存在
    result = make_result(scored, config=config)

    count, msg = export_to_dir(result, str(ws / "out"))

    assert count == 0
    assert "2 张导出失败" in msg
    # 摘要取前 3 项，本例 2 项须全部出现
    assert "c.jpg" in msg
    assert "d.jpg" in msg


def test_export_full_success_message_unchanged(tmp_path: Path) -> None:
    """对照：零失败时状态文案逐字不变（e2e 断言「复制」前缀，追加内容不得出现）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    result = _result_in(ws)

    count, msg = export_to_dir(result, str(ws / "out"))

    assert count == 1
    assert msg == f"复制 1 张到 {ws / 'out'}"
    assert "失败" not in msg


def test_export_rejection_is_not_reported_as_export_failure(tmp_path: Path) -> None:
    """反例：越界硬拒绝属安全拦截，不得混入「导出失败」字样（与导出失败处置不同）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    result = _result_in(ws)

    count, msg = export_to_dir(result, str(outside), move=True)

    assert count == 0
    assert "已拒绝" in msg
    assert "导出失败" not in msg
    assert "导出部分失败" not in msg


def test_export_dest_is_file_without_candidate_is_not_failure(tmp_path: Path) -> None:
    """反例（与 CLI/MCP 同口径）：无待导出图时 dest 是普通文件不构成导出失败。

    没有任何图片需要导出，用户未损失产物；记为失败会让「导出目录误填成文件」
    但本就零入选的正常场景被误报成故障。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    dest = ws / "精选"
    dest.write_text("i am a file", encoding="utf-8")
    config = build_run_config(str(ws), ScoringOptions(no_vlm=True))
    # 仅一张未入选图 → last_expected == 0
    scored = [make_score("b.jpg", str(ws / "b.jpg"), score=50.0, selected=False)]
    (ws / "b.jpg").write_bytes(b"fake-b")
    result = make_result(scored, config=config)

    count, msg = export_to_dir(result, str(dest))

    assert count == 0
    assert "失败" not in msg


# ── 3b. 清单导出路径收敛（M-10） ──────────────────────────────────────


def test_export_manifest_rejects_outside_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-10：清单路径落在评分目录与系统临时目录之外 → 硬拒绝且零磁盘副作用。

    pytest 的 tmp_path 默认在系统临时目录内，不打桩的话负例会经临时目录分支
    放行——这里把 tempfile.tempdir 钉到受控根，构造真正的「双根之外」路径。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    fake_tmp = tmp_path / "fakeroot"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
    result = _result_in(ws)
    evil = tmp_path / "evil" / "manifest.json"

    ok, msg = export_manifest(result, "json", str(evil))

    assert ok is False
    assert "已拒绝" in msg
    # 安全拦截不与导出失败混同（H-9 文案契约）
    assert "导出失败" not in msg
    # 先于落盘拦截：write_manifest 的原子写会 mkdir(parents=True)，不得留下痕迹
    assert not evil.exists()
    assert not evil.parent.exists()


def test_export_manifest_allows_temp_path(tmp_path: Path) -> None:
    """对照（生产调用点形态）：真实 mkstemp 临时路径照常写入，下载链路不回归。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    result = _result_in(ws)
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    ok, msg = export_manifest(result, "json", tmp)

    assert ok is True
    assert "已拒绝" not in msg
    assert Path(tmp).exists()
    assert Path(tmp).stat().st_size > 0


def test_export_manifest_allows_workspace_path(tmp_path: Path) -> None:
    """对照：workspace 内的路径放行（与 export_to_dir 同信任域）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    result = _result_in(ws)
    out = ws / "清单.csv"

    ok, msg = export_manifest(result, "csv", str(out))

    assert ok is True
    assert "已拒绝" not in msg
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_manifest_relative_resolves_against_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """增强（N-1 对齐）：相对清单路径以评分目录为基准解析，与进程 CWD 无关。

    改动前 export_manifest 不做解析，相对路径经原子写按 CWD 落盘——Gradio 进程
    CWD ≠ 评分目录时清单落点随进程启动目录漂移。与 export_to_dir 同款解析。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(tmp_path)  # CWD = ws 父目录，≠ 评分目录
    result = _result_in(ws)

    ok, _ = export_manifest(result, "json", "./清单.json")

    assert ok is True
    assert (ws / "清单.json").exists()
    # 不得按 CWD 落盘（证明解析基准确为评分目录）
    assert not (tmp_path / "清单.json").exists()


def test_export_manifest_relative_escape_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """相对路径的 .. 逃逸同样被硬拒绝（与绝对路径越界同强度）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    fake_tmp = ws / "fakeroot"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
    monkeypatch.chdir(ws)  # CWD = ws，使 ../escape 与旧 CWD 行为可比
    result = _result_in(ws)

    ok, msg = export_manifest(result, "json", "../escape.json")

    assert ok is False
    assert "已拒绝" in msg
    assert not (tmp_path / "escape.json").exists()


# ── 4. --allow-root 白名单 ─────────────────────────────────────────────


def test_allowed_root_rejects_outside(tmp_path: Path) -> None:
    """提供白名单后，目录不在其内 → PARAM_ERROR 且 result=None。"""
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    code, msg, result = run_scoring(
        str(outside), options=ScoringOptions(no_vlm=True), allowed_roots=[str(root)]
    )
    assert code == ExitCode.PARAM_ERROR
    assert result is None
    assert "不在允许的访问范围内" in msg


def test_allowed_root_allows_inside(tmp_path: Path) -> None:
    """目录落在白名单内：通过校验（空目录返回 NO_IMAGES，而非 PARAM_ERROR）。"""
    root = tmp_path / "allowed"
    root.mkdir()
    code, _, _ = run_scoring(
        str(root), options=ScoringOptions(no_vlm=True), allowed_roots=[str(root)]
    )
    assert code != ExitCode.PARAM_ERROR
    assert code == ExitCode.NO_IMAGES


def test_allowed_root_unset_is_permissive(tmp_path: Path) -> None:
    """未提供白名单（None 与 [] 两种）时本地无限制，外部目录不被拒绝。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    code_none, _, _ = run_scoring(
        str(outside), options=ScoringOptions(no_vlm=True), allowed_roots=None
    )
    code_empty, _, _ = run_scoring(
        str(outside), options=ScoringOptions(no_vlm=True), allowed_roots=[]
    )
    assert code_none != ExitCode.PARAM_ERROR
    assert code_empty != ExitCode.PARAM_ERROR


# ── 5. api_key 控件初值不泄露服务端密钥 ─────────────────────────────────


def test_api_key_field_not_prefilled_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api_key 文本框初值不应是服务端真实密钥（应为空串）；想用服务端密钥留空即可。"""
    monkeypatch.setenv("FLASHGAZE_API_KEY", "SUPER_SECRET_SERVER_KEY")
    pytest.importorskip("gradio")  # build_app 需 gradio；缺失则跳过
    demo = build_app()
    found: Any = None  # gradio 组件按鸭子类型访问，Block 基类未声明 value 属性
    for comp in demo.blocks.values():
        if getattr(comp, "elem_id", None) == "fg-api-key":
            found = comp
            break
    assert found is not None
    # 安全修复核心断言：真实密钥未序列化进前端控件初值
    assert found.value == ""

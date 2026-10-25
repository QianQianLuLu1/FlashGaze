"""tools/extras_health.py 的判定契约（该脚本此前零单测，R1-R5 全靠读代码）。

用例统一**子进程真实调用** `python tools/extras_health.py …`，与
`.github/workflows/extras-health.yml` 的 Evaluate health 步骤逐字同构：断言既看
`health_out/decision.json`，也看**退出码**——critical=2 是这个脚本对外的第二份契约，
而 CI run 40134963461 正是被「步骤把非零一律当崩溃」打红的（critical 分支的写锁 /
建 Issue 四处步骤因此一次也没执行过）。

输入数字取自 CI run 40107357212 的真实产物 coverage.xml（ubuntu extras 腿，逐模块
line 覆盖/总数）：mcp_server 207/236、webui/app 217/253、xlsx_exporter 46/46、
deduplicator 72/86、portrait_engine 20/42。用真实数据是为了让「portrait 47.62% 落在
判定集外 → 不再判死」这条口径变更有据可查，而不是拿编造的数字自证。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "extras_health.py"

# CI 实测的（覆盖行数, 总行数），键为 coverage.xml 里相对包根的 filename。
CI_REAL: dict[str, tuple[int, int]] = {
    "mcp_server.py": (207, 236),
    "webui/app.py": (217, 253),
    "core/xlsx_exporter.py": (46, 46),
    "core/deduplicator.py": (72, 86),
    "core/portrait_engine.py": (20, 42),
}


# 快照/历史里的键是模块点号名（extras_health 的 MODULES），与 coverage.xml 的 filename 是
# 两套标识；混用会让用例对着永远不存在的键自证（本文件第一版就踩过一次）。
MODULE_NAMES = (
    "flashgaze.mcp_server",
    "flashgaze.webui.app",
    "flashgaze.core.xlsx_exporter",
    "flashgaze.core.deduplicator",
    "flashgaze.core.portrait_engine",
)


def _snaps(**overrides: float) -> dict[str, float]:
    """构造「全模块 90%、个别模块按参数覆盖」的快照字典。"""
    base = {m: 90.0 for m in MODULE_NAMES}
    base.update(overrides)
    return base


def _write_coverage(
    tmp_path: Path, stats: dict[str, tuple[int, int]], name: str = "coverage.xml"
) -> Path:
    """按（覆盖行数, 总行数）造最小 cobertura 文档；extras_health 只读 class/filename/line。"""
    coverage = ET.Element("coverage", {"version": "7.16.2"})
    packages = ET.SubElement(coverage, "packages")
    package = ET.SubElement(packages, "package", {"name": "."})
    classes = ET.SubElement(package, "classes")
    for filename, (covered, total) in stats.items():
        cls = ET.SubElement(
            classes,
            "class",
            {"filename": filename, "line-rate": f"{covered / total:.4f}"},
        )
        lines = ET.SubElement(cls, "lines")
        for i in range(total):
            ET.SubElement(
                lines, "line", {"number": str(i + 1), "hits": "1" if i < covered else "0"}
            )
    path = tmp_path / name
    ET.ElementTree(coverage).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _write_history(
    tmp_path: Path, snapshots: list[dict[str, Any]], name: str = "history.json"
) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")
    return path


def _run(
    tmp_path: Path,
    coverage: Path,
    history: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any], dict[str, Any]]:
    """子进程调用脚本，返回（进程, decision.json, snapshot.json）。

    decision.json 里没有 snapshot 键（write_outputs 把快照单独落 snapshot.json），涉及具体
    百分比的断言一律读 snapshot.json，避免用例对着不存在的键自证。

    PYTHONIOENCODING=utf-8 钉住子进程输出编码（Windows 默认 cp936 会让中文断言随机失效），
    与 tests/test_cli_terminal_e2e.py 的 _env() 同一手法。
    """
    out_dir = tmp_path / "health_out"
    cmd = [sys.executable, str(SCRIPT), "--coverage", str(coverage), "--out-dir", str(out_dir)]
    if history is not None:
        cmd += ["--history", str(history)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    decision: dict[str, Any] = json.loads((out_dir / "decision.json").read_text(encoding="utf-8"))
    snapshot: dict[str, Any] = json.loads((out_dir / "snapshot.json").read_text(encoding="utf-8"))
    return proc, decision, snapshot


def _stats_with(filename: str, covered: int, total: int) -> dict[str, tuple[int, int]]:
    stats = dict(CI_REAL)
    stats[filename] = (covered, total)
    return stats


def test_ci_real_numbers_no_longer_bail_out_critical(tmp_path: Path) -> None:
    """主用例（口径变更的正例）：CI 真实数字下判定为 ok 且不加锁。

    修复前失效证据：CI run 40134963461 用同一份 coverage.xml 判出 decision=critical、
    actions.write_lock=true、退出码 2（criticals 里唯一一条 R4 是 portrait_engine 47.62%）。
    """
    proc, decision, snapshot = _run(tmp_path, _write_coverage(tmp_path, CI_REAL))

    assert decision["decision"] == "ok", decision
    assert decision["criticals"] == [] and decision["warnings"] == [], decision
    assert decision["actions"]["write_lock"] is False, "判定 ok 却仍要写锁：会把锁真的推进 main"
    assert decision["actions"]["create_issue"] is False, decision
    assert proc.returncode == 0, f"ok 必须是 0 退出：rc={proc.returncode} stderr={proc.stderr!r}"
    # 观测性不得丢失：dedup / portrait 仍进快照与 Issue 表格，只是不参与判定。
    assert snapshot["modules"]["flashgaze.core.portrait_engine"] == 47.62
    assert "观测项" in decision["issue_text"], "Issue 表格须标明只观测的模块，免被读成没数据"


def test_judged_module_below_crit_line_is_critical(tmp_path: Path) -> None:
    """反例护栏（守卫非恒真）：同一条 45% 落在判定集内必须判死。

    把 mcp_server 压到 18/40 = 45%（低于 R4 的 50）→ decision=critical、退出码 **2**、
    write_lock=true。与主用例互为反向：限定判定集不等于「一律放行」。
    """
    coverage = _write_coverage(tmp_path, _stats_with("mcp_server.py", 18, 40))
    proc, decision, _ = _run(tmp_path, coverage)

    assert decision["decision"] == "critical", decision
    assert [c["module"] for c in decision["criticals"]] == ["flashgaze.mcp_server"], decision
    assert decision["actions"]["write_lock"] is True, decision
    assert proc.returncode == 2, f"critical 的对外契约是退出码 2：实际 {proc.returncode}"


def test_same_low_value_outside_judged_set_stays_ok(tmp_path: Path) -> None:
    """判定集外的模块即便低于 50% 也只观测（把上面那条的数值原样搬到 portrait_engine 上）。"""
    stats = dict(CI_REAL)
    stats["core/portrait_engine.py"] = (18, 40)  # 45%，与上面的 critical 用例同数值
    proc, decision, snapshot = _run(tmp_path, _write_coverage(tmp_path, stats))

    assert decision["decision"] == "ok", decision
    assert proc.returncode == 0, decision
    assert snapshot["modules"]["flashgaze.core.portrait_engine"] == 45.0


def test_judged_module_between_50_and_60_warns_without_lock(tmp_path: Path) -> None:
    """边界：判定集内 55% → R1 warning（建 Issue）但不写锁、退出码 0。

    钉住「限定判定集」没有顺带改掉 R1/R4 的两级语义：warning 与 critical 仍分得开。
    """
    coverage = _write_coverage(tmp_path, _stats_with("webui/app.py", 22, 40))
    proc, decision, _ = _run(tmp_path, coverage)

    assert decision["decision"] == "warning", decision
    assert {w["rule"] for w in decision["warnings"]} == {"R1"}, decision
    assert decision["actions"]["create_issue"] is True, decision
    assert decision["actions"]["write_lock"] is False, "warning 不得加锁（R4 才加）"
    assert proc.returncode == 0, decision


def _drop_history(tmp_path: Path, module: str, name: str) -> Path:
    """三连降历史（90 → 80 → 70，每步降 10pp ≥ drop_pp=5，条数正好等于 n_drop=3）。

    R2 读的是**已落盘的历史**（本轮快照尚未计入），少于 3 条时永远不会触发——第一版用例
    只写了 2 条，于是「R2 触发」那一侧其实是假绿，被自己的断言打回后才补全。
    """
    return _write_history(
        tmp_path,
        [
            {"modules": _snaps(**{module: 90.0}), "failures": []},
            {"modules": _snaps(**{module: 80.0}), "failures": []},
            {"modules": _snaps(**{module: 70.0}), "failures": []},
        ],
        name=name,
    )


def test_history_drop_triggers_r2_inside_judged_set_only(tmp_path: Path) -> None:
    """R2 随判定集收敛：同一段三连降，落在 mcp_server 触发、落在 portrait_engine 不触发。

    本轮覆盖率一律摆到 90%（排除 R1/R4 干扰），使断言只可能由 R2 决定。
    """
    full_ok = {f: (90, 100) for f in CI_REAL}

    judged = _write_coverage(tmp_path, full_ok, name="c1.xml")
    _, decision, _ = _run(
        tmp_path, judged, _drop_history(tmp_path, "flashgaze.mcp_server", "h1.json")
    )
    assert "R2" in {w["rule"] for w in decision["warnings"]}, decision
    assert decision["decision"] == "warning", decision

    observed = _write_coverage(tmp_path, full_ok, name="c2.xml")
    _, decision2, _ = _run(
        tmp_path, observed, _drop_history(tmp_path, "flashgaze.core.portrait_engine", "h2.json")
    )
    # 只断言 R2 不触发：判定集全在 90% 时 R5（recovered）会合法接管 decision，
    # 把它一起写死会让本用例看起来在测 R2、实际在测 R5 的顺序。
    assert "R2" not in {w["rule"] for w in decision2["warnings"]}, decision2
    assert decision2["criticals"] == [], decision2
    assert decision2["actions"]["write_lock"] is False, decision2


def test_recovery_only_needs_judged_modules(tmp_path: Path) -> None:
    """R5 与 R1/R4 同集合，否则「能加锁、永远解不掉」——自愈会因降级口径而失效。

    两个历史快照里判定集三模块均 ≥70、无失败，portrait 一直是 47.62% → 本轮应 recovered
    且 clear_lock=true（改动前不可能：按全集口径会被 portrait 一直拦住）。
    """
    clean_modules = _snaps(**{"flashgaze.core.portrait_engine": 47.62})
    history = _write_history(
        tmp_path,
        [{"modules": clean_modules, "failures": []}, {"modules": clean_modules, "failures": []}],
    )
    proc, decision, _ = _run(tmp_path, _write_coverage(tmp_path, CI_REAL), history)

    assert decision["decision"] == "recovered", decision
    assert decision["actions"]["clear_lock"] is True, decision
    assert proc.returncode == 0, decision


def test_missing_or_damaged_coverage_degrades_without_red(tmp_path: Path) -> None:
    """边界（不加第二条红源）：coverage.xml 缺失或损坏 → 无数据 → ok + 退出码 0。

    这是既有 LOW-6 优雅降级的回归位：extras 腿挂掉时，夜间治理线不能反过来再判红一次。
    """
    proc, decision, _ = _run(tmp_path, tmp_path / "not_written.xml")
    assert decision["decision"] == "ok", decision
    assert proc.returncode == 0, decision

    broken = tmp_path / "broken.xml"
    broken.write_text("<coverage><truncated", encoding="utf-8")
    proc2, decision2, _ = _run(tmp_path, broken)
    assert decision2["decision"] == "ok", decision2
    assert proc2.returncode == 0, proc2.stderr
    assert "[extras_health]" in proc2.stderr and "coverage.xml" in proc2.stderr, proc2.stderr

"""FlashGaze 可选模块健康度判定脚本（纯标准库，无第三方依赖）。

输入：
  - coverage.xml  (pytest-cov 输出，cobertura 格式)
  - junit.xml     (pytest --junitxml 输出，可选；缺失时视为无失败)
  - history.json  (gh-pages 上的历史快照，可选；缺失时从头累积)
  - --config      (阈值参数 JSON，可选，覆盖内置默认值)

输出（写入 --out-dir 目录，供 workflow 消费）：
  - snapshot.json   本次快照（时间戳 + 各模块覆盖率）
  - benchmark.json  github-action-benchmark 兼容格式（每模块 coverage 为 metric）
  - decision.json   判定结果与动作（decision / actions / issue_text / snapshot）
  - history.json    追加本快照后的历史（落地 gh-pages）

判定规则（默认阈值，见 DEFAULT_CONFIG）：
  R1 绝对下限 warning：判定集内任一模块 line 覆盖率 < ABS_WARN(60%)
  R2 连续劣化 warning：判定集内任一模块周环比降 >= DROP_PP(5) 且连续 N_DROP(3) 个快照
  R3 持续失败 warning：同一测试 nodeid 在 K_FAIL(3) 个连续运行中失败
  R4 临界 critical：判定集内任一模块 < CRIT_LINE(50%)，或 R2/R3 触发后未修复再持续 M_UNFIXED(2) 快照
  R5 恢复 recovered：判定集内所有模块 >= RECOVER_LINE(70%) 且连续 2 快照无失败测试

  R1/R2/R4/R5 的「模块」指 JUDGED_MODULES（= ci.yml 里带逐模块 --fail-under 的那 3 个）；
  其余 2 个可选模块仍进 snapshot / benchmark.json / Issue 表格，但只观测不判死。R3 不设模块范围。

退出码：critical 返回 **2**（供调用方区分级别）。调用方若把「非零」一律当崩溃，
就会让 critical 分支的后续动作（写锁 / 建 Issue）整条被跳过 —— 见
.github/workflows/extras-health.yml 的 Evaluate health 步骤。

纯逻辑（parse_* / evaluate / load_history / render_*）与 I/O 分离，便于本地单测。

勿加 shebang：本文件在版本库里是 mode 644（不可执行），加上 `#!/usr/bin/env python3` 会让
Linux 腿的 `ruff check` 报 EXE001，而 Windows 无 exec 位语义、本地怎么跑都测不出来。调用方
一律是 `python tools/extras_health.py …`（见 .github/workflows/extras-health.yml）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ── 治理对象：5 个可选模块（与 .coveragerc-extras 的 source 一致）──────────
MODULES = [
    "flashgaze.mcp_server",
    "flashgaze.webui.app",
    "flashgaze.core.xlsx_exporter",
    "flashgaze.core.deduplicator",
    "flashgaze.core.portrait_engine",
]

# ── 判定集：R1/R2/R4/R5 只对这些模块生效 ─────────────────────────────────
# 逐字等于 ci.yml 里带 `--fail-under=` 的模块集合（由
# tests/test_coverage_gate_contract.py 钉住，补/删逐模块 floor 时不同步就判红）。
# deduplicator / portrait_engine 刻意留在 MODULES 里进快照与趋势图，但**只观测不判死**：
# 它们的实测值来自「本地/CI 装不上 imagededup、face_recognition」的降级口径（见
# docs/extras-governance.md §2.1），而 R1/R4 按「任一模块」的绝对线判定 —— 二者叠加会让
# 一个测量口径问题伪装成质量临界（CI run 40134963461 的 R4 即 portrait 47.62% 触发）。
# 代价须知情：这两个模块真实跌破 60% 甚至 50% 都不再自动告警/加锁，靠人看趋势图。
JUDGED_MODULES = (
    "flashgaze.mcp_server",
    "flashgaze.webui.app",
    "flashgaze.core.xlsx_exporter",
)

# 模块 owner（用于自动指派清理 Issue）。占位为 GitHub 用户名或团队 slug；
# 落地时替换为实际负责人，留空字符串表示暂不指派。
MODULE_OWNERS = {
    "flashgaze.mcp_server": "",
    "flashgaze.webui.app": "",
    "flashgaze.core.xlsx_exporter": "",
    "flashgaze.core.deduplicator": "",
    "flashgaze.core.portrait_engine": "",
}

DEFAULT_CONFIG = {
    "abs_warn": 60.0,  # R1 绝对下限（%）
    "drop_pp": 5.0,  # R2 周环比劣化幅度（百分点）
    "n_drop": 3,  # R2 连续劣化快照数
    "k_fail": 3,  # R3 同一用例持续失败运行数
    "crit_line": 50.0,  # R4 临界绝对下限（%）
    "m_unfixed": 2,  # R4 触发后未修复的持续快照数
    "recover_line": 70.0,  # R5 恢复绝对下限（%）
    "recover_clean": 2,  # R5 连续无失败快照数
}


# 每个可选模块在 coverage.xml 中的「源码根下相对路径前缀」（与 .coveragerc-extras
# 的 source=flashgaze 一致；filename 相对该根，如 mcp_server/__init__.py）。
# 用路径前缀匹配而非完整文件名，兼容包内多文件（如 mcp_server/*.py）。
MODULE_PATH_PREFIX = {
    "flashgaze.mcp_server": "mcp_server",
    "flashgaze.webui.app": "webui/app",
    "flashgaze.core.xlsx_exporter": "core/xlsx_exporter",
    "flashgaze.core.deduplicator": "core/deduplicator",
    "flashgaze.core.portrait_engine": "core/portrait_engine",
}

import re as _re

_BRANCH_RE = _re.compile(r"\((\d+)/(\d+)\)")  # 解析 condition-coverage="50% (1/2)"


# ── 解析层 ────────────────────────────────────────────────────────────────
def parse_coverage(xml_path: Path) -> dict[str, dict]:
    """从 cobertura coverage.xml 解析每个可选模块的 line/branch 覆盖率。

    coverage.py 生成的 cobertura 格式要点：
      - <source> 为包根（flashgaze）；<class filename> 相对该根，如 "mcp_server/__init__.py"；
      - package 的 name 通常为 "."；故按 filename 路径前缀匹配 MODULE_PATH_PREFIX；
      - 分支覆盖率写在 <line condition-coverage="50% (1/2)">，需解析括号里的 (覆盖/总数)。

    返回 {module: {...}}；未出现在报告中（被 omit 或源码缺失）的模块 line_pct=None。
    """
    result: dict[str, dict] = {}
    for mod in MODULES:
        result[mod] = {
            "line_pct": None,
            "branch_pct": None,
            "line_total": 0,
            "line_covered": 0,
            "branch_total": 0,
            "branch_covered": 0,
            "present": False,
        }

    if not xml_path.exists():
        return result

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        # LOW-6: coverage.xml 存在但格式损坏时不得裸崩——按"无数据"处理
        # （各模块 present=False，判定规则自然降级），stderr 告警提示上游修复。
        print(f"[extras_health] coverage.xml 解析失败，按无数据处理: {e}", file=sys.stderr)
        return result
    root = tree.getroot()

    for cls in root.iter("class"):
        filename = (cls.get("filename") or "").replace("\\", "/")
        if not filename:
            continue
        match = next(
            (
                m
                for m, prefix in MODULE_PATH_PREFIX.items()
                if filename == f"{prefix}.py" or filename.startswith(f"{prefix}/")
            ),
            None,
        )
        if match is None:
            continue
        lines = cls.find("lines")
        # 不写 `lines or []`：ElementTree 元素的真值判定已弃用（未来版本恒为 True，会让
        # 空 <lines> 与缺失 <lines> 分不开），且每次解析都会在 stderr 抛一条
        # DeprecationWarning —— 夜间治理线的日志噪声本身就难归因（见 AGENTS.md §4.6）。
        line_nodes = [] if lines is None else list(lines)
        total = len(line_nodes)
        covered = sum(1 for ln in line_nodes if int(ln.get("hits", "0")) > 0)
        br_total = br_cov = 0
        for ln in cls.iter("line"):
            cond = ln.get("condition-coverage")
            if cond:
                m = _BRANCH_RE.search(cond)
                if m:
                    br_cov += int(m.group(1))
                    br_total += int(m.group(2))
        entry = result[match]
        entry["present"] = True
        entry["line_total"] += total
        entry["line_covered"] += covered
        entry["branch_total"] += br_total
        entry["branch_covered"] += br_cov

    for mod, entry in result.items():
        if entry["line_total"] > 0:
            entry["line_pct"] = round(entry["line_covered"] / entry["line_total"] * 100, 2)
        if entry.get("branch_total", 0) > 0:
            entry["branch_pct"] = round(entry["branch_covered"] / entry["branch_total"] * 100, 2)
    return result


def parse_junit(xml_path: Path) -> list[str]:
    """从 junit xml 解析失败测试用例的 nodeid。

    pytest --junitxml 输出 <testcase classname="tests.xxx" name="test_yyy">，
    失败体现在子元素 <failure>/<error>。nodeid 规范为 "classname::name"。
    返回失败用例列表（去重，保持出现顺序）。
    """
    if not xml_path.exists():
        return []

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        # LOW-6: junit.xml 格式损坏时按"无失败用例"处理，不让 CI 脚本裸崩。
        print(f"[extras_health] junit.xml 解析失败，视为无失败用例: {e}", file=sys.stderr)
        return []
    root = tree.getroot()
    failures: list[str] = []
    seen: set[str] = set()

    # junit 顶层可能是 <testsuite> 或两个 <testsuite> 包在 <testsuites>
    suites = root.iter("testcase")
    for tc in suites:
        failed = tc.find("failure") is not None or tc.find("error") is not None
        if not failed:
            continue
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        nodeid = f"{classname}::{name}"
        if nodeid not in seen:
            seen.add(nodeid)
            failures.append(nodeid)
    return failures


def load_history(history_path: Path) -> list[dict]:
    """加载历史快照列表（按时间升序）。缺失或损坏时返回空列表。"""
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


# ── 判定层 ────────────────────────────────────────────────────────────────
@dataclass
class Decision:
    decision: str  # "ok" | "warning" | "critical" | "recovered"
    level: str  # 与 decision 同义的人类可读级别
    actions: dict = field(
        default_factory=dict
    )  # {create_issue, write_lock, clear_lock, close_issue}
    warnings: list[dict] = field(default_factory=list)  # 触发的规则明细
    criticals: list[dict] = field(default_factory=list)
    issue_text: str = ""
    snapshot: dict = field(default_factory=dict)


def evaluate(
    modules: dict[str, dict], failures: list[str], history: list[dict], cfg: dict
) -> Decision:
    """核心判定：输入本次模块覆盖率、失败用例、历史快照，输出 Decision。"""
    ts = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "timestamp": ts,
        "modules": {m: modules[m]["line_pct"] for m in MODULES},
        "branch": {m: modules[m]["branch_pct"] for m in MODULES},
        "failures": failures,
    }

    warnings: list[dict] = []
    criticals: list[dict] = []

    present = {
        m: modules[m]["line_pct"] for m in JUDGED_MODULES if modules[m]["line_pct"] is not None
    }

    # R1：绝对下限（仅对判定集中有覆盖率数据的模块判定）
    for m, pct in present.items():
        if pct < cfg["abs_warn"]:
            warnings.append(
                {
                    "rule": "R1",
                    "module": m,
                    "value": pct,
                    "threshold": cfg["abs_warn"],
                    "msg": f"{m} 覆盖率 {pct}% 低于下限 {cfg['abs_warn']}%",
                }
            )

    # R4（临界绝对下限）
    for m, pct in present.items():
        if pct < cfg["crit_line"]:
            criticals.append(
                {
                    "rule": "R4",
                    "module": m,
                    "value": pct,
                    "threshold": cfg["crit_line"],
                    "msg": f"{m} 覆盖率 {pct}% 低于临界值 {cfg['crit_line']}%",
                }
            )

    # R2：连续 N 个快照周环比降幅 >= drop_pp（判定集内）
    recent = [h for h in history if h.get("modules")][-(cfg["n_drop"]) :]
    for m in JUDGED_MODULES:
        seq = [h["modules"].get(m) for h in recent]
        if None in seq:
            continue
        consecutive = 0
        ok = True
        for i in range(1, len(seq)):
            if (
                seq[i] is not None
                and seq[i - 1] is not None
                and (seq[i - 1] - seq[i]) >= cfg["drop_pp"]
            ):
                consecutive += 1
            else:
                ok = False
                break
        if ok and len(seq) >= cfg["n_drop"] and consecutive >= cfg["n_drop"] - 1:
            warnings.append(
                {
                    "rule": "R2",
                    "module": m,
                    "seq": seq,
                    "msg": f"{m} 连续 {len(seq)} 个快照下降（{seq}），累计降 {round(seq[0] - seq[-1], 2)}pp",
                }
            )

    # R3：同一用例在最近 K 个快照中持续失败
    fail_hist = [set(h.get("failures", [])) for h in history[-cfg["k_fail"] :]]
    if len(fail_hist) >= cfg["k_fail"]:
        for nodeid in set().union(*fail_hist):
            if all(nodeid in s for s in fail_hist):
                warnings.append(
                    {
                        "rule": "R3",
                        "module": nodeid.split("::")[0],
                        "nodeid": nodeid,
                        "msg": f"用例 {nodeid} 连续 {cfg['k_fail']} 次运行失败",
                    }
                )

    # R4（未修复持续）：历史中最近一次 warning 触发的模块，再持续 M 快照仍劣化
    if history:
        last_warn = next(
            (h for h in reversed(history) if h.get("decision") in ("warning", "critical")), None
        )
        if last_warn is not None:
            lag = len(history) - history.index(last_warn) - 1
            if lag >= cfg["m_unfixed"]:
                criticals.append(
                    {
                        "rule": "R4",
                        "module": "aggregate",
                        "lag": lag,
                        "msg": f"劣化自上次告警已持续 {lag} 个快照未修复（阈值 {cfg['m_unfixed']}）",
                    }
                )

    # 决策与动作
    no_fail = len(failures) == 0
    # 判定集内的达标口径（与 R1/R4 同一集合，保证「能加锁」与「能解锁」对称：
    # 若 R5 仍按全集判，portrait 的降级口径会让锁一旦写上就永远解不掉，自愈失效）。
    all_above_recover = (
        all(p is not None and p >= cfg["recover_line"] for p in present.values())
        if present
        else False
    )

    decision = "ok"
    actions: dict = {
        "create_issue": False,
        "write_lock": False,
        "clear_lock": False,
        "close_issue": False,
    }

    if criticals:
        decision = "critical"
        actions["write_lock"] = True
        actions["create_issue"] = True
    elif warnings:
        decision = "warning"
        actions["create_issue"] = True
    elif all_above_recover and no_fail and len(history) >= cfg["recover_clean"]:
        # R5 恢复：最近 recover_clean 个快照的判定集模块均达标且无失败
        tail = history[-cfg["recover_clean"] :]
        tail_ok = (
            all(
                all(
                    p is not None and p >= cfg["recover_line"]
                    for m, p in h.get("modules", {}).items()
                    if m in JUDGED_MODULES
                )
                and len(h.get("failures", [])) == 0
                for h in tail
            )
            if tail
            else False
        )
        if tail_ok:
            decision = "recovered"
            actions["clear_lock"] = True
            actions["close_issue"] = True

    issue_text = _render_issue(decision, warnings, criticals, snapshot)
    return Decision(
        decision=decision,
        level=decision,
        actions=actions,
        warnings=warnings,
        criticals=criticals,
        issue_text=issue_text,
        snapshot=snapshot,
    )


def _render_issue(
    decision: str, warnings: list[dict], criticals: list[dict], snapshot: dict
) -> str:
    """生成 Issue / 评论 Markdown 文本。"""
    emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨", "recovered": "🟢"}.get(decision, "•")
    lines = [f"## {emoji} 可选模块健康度 — {decision.upper()}", ""]
    lines.append(f"快照时间（UTC）：{snapshot['timestamp']}")
    lines.append("")
    lines.append("### 各模块 line 覆盖率")
    for m in MODULES:
        pct = snapshot["modules"].get(m)
        # 判定集外的模块显式标注，避免读 Issue 的人把「没告警」当成「没数据/没问题」。
        note = "" if m in JUDGED_MODULES else "（观测项，不参与 R1/R2/R4/R5 判定）"
        lines.append(f"- `{m}`: {pct if pct is not None else 'n/a'}%{note}")
    if snapshot["failures"]:
        lines.append("")
        lines.append(f"### 失败用例（{len(snapshot['failures'])}）")
        for f in snapshot["failures"][:20]:
            lines.append(f"- `{f}`")
    if criticals:
        lines.append("")
        lines.append("### 🚨 临界触发")
        for c in criticals:
            lines.append(f"- [{c['rule']}] {c['msg']}")
    if warnings:
        lines.append("")
        lines.append("### ⚠️ 告警触发")
        for w in warnings:
            lines.append(f"- [{w['rule']}] {w['msg']}")
    lines.append("")
    lines.append(
        "> 由 `.github/workflows/extras-health.yml` 自动生成。详见 `docs/extras-governance.md`。"
    )
    return "\n".join(lines)


# ── 渲染层（gh-pages 趋势图）──────────────────────────────────────────────
def render_benchmark(snapshot: dict, out_path: Path) -> None:
    """生成 github-action-benchmark 兼容的 benchmark.json。

    每个模块一条记录；metric 为覆盖率百分比（默认 higher_is_better，故用覆盖率本身）。
    """
    entries = []
    ts = snapshot["timestamp"]
    for m in MODULES:
        pct = snapshot["modules"].get(m)
        if pct is None:
            continue
        entries.append(
            {
                "name": m,
                "unit": "%",
                "value": pct,
                "range": "RANGE",
                "extra": ts,
            }
        )
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(out_dir: Path, decision: Decision, history: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "snapshot.json").write_text(
        json.dumps(decision.snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "decision.json").write_text(
        json.dumps(
            {
                "decision": decision.decision,
                "level": decision.level,
                "actions": decision.actions,
                "warnings": decision.warnings,
                "criticals": decision.criticals,
                "issue_text": decision.issue_text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    render_benchmark(decision.snapshot, out_dir / "benchmark.json")
    # 历史追加本快照
    history.append(decision.snapshot)
    (out_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 入口 ──────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FlashGaze extras health evaluator")
    parser.add_argument("--coverage", required=True, type=Path, help="coverage.xml 路径")
    parser.add_argument("--junit", required=False, type=Path, help="junit.xml 路径（可选）")
    parser.add_argument(
        "--history", required=False, type=Path, help="历史 history.json 路径（可选）"
    )
    parser.add_argument("--out-dir", required=True, type=Path, help="输出目录")
    parser.add_argument(
        "--config", required=False, type=Path, help="阈值配置 JSON（可选，覆盖默认）"
    )
    args = parser.parse_args(argv)

    cfg = dict(DEFAULT_CONFIG)
    if args.config and args.config.exists():
        try:
            cfg.update(json.loads(args.config.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            # LOW-6: 阈值配置损坏/不可读时按内置默认值继续判定（stderr 告警），
            # 不让脚本在产出判定前裸崩；上游需留意告警修正配置。
            print(f"[extras_health] --config 解析失败，使用内置默认阈值: {e}", file=sys.stderr)

    modules = parse_coverage(args.coverage)
    failures = parse_junit(args.junit) if args.junit else []
    history = load_history(args.history) if args.history else []
    decision = evaluate(modules, failures, history, cfg)
    write_outputs(args.out_dir, decision, history)

    print(
        f"[extras_health] decision={decision.decision} "
        f"warn={len(decision.warnings)} crit={len(decision.criticals)} "
        f"actions={decision.actions}"
    )
    # 退出码：critical=2（供 workflow 区分告警级别，不影响非阻塞语义）
    return 2 if decision.decision == "critical" else 0


if __name__ == "__main__":
    sys.exit(main())

"""覆盖率门禁契约测试（审查项 M-12 的防退化守卫）。

锁定四个配置文件的关键契约，防止覆盖率门禁被静默掏空或回退：

- ``.coveragerc``：主门禁 ``fail_under = 80`` 不得变更；omit 精确等于 3 个
  依赖缺失的可选模块——``mcp_server`` / ``webui.app`` 必须留在主门禁考核
  范围内（M-12 修复成果），核心模块不得被塞进 omit。
- ``.coveragerc-extras``：extras job 必须有硬门槛 ``fail_under >= 50``，
  且 source 覆盖全部 5 个可选模块（tools/extras_health.py 的 MODULES 与
  夜间 extras-health 任务依赖该 source 清单）。
- ``.github/workflows/ci.yml``：test job 安装 mcp/gui/exif/heic 轻量 extras
  （纳入主门禁的模块才能在主矩阵被真实度量）；extras job 不得有 job 级
  ``continue-on-error``（否则门禁失败被吞掉，回到「只报告不设门」）；
  覆盖率硬门禁步骤必须存在且无条件执行（不受 sentinel 锁条件化）。
- ``codecov.yml``：patch/core 强制状态不得再排除 mcp_server / webui.app。

改门槛、改 omit、改 CI 门禁结构时，必须同步更新本测试与 README
「覆盖率门禁」小节、docs/extras-governance.md 的口径。
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MAIN_RC = REPO_ROOT / ".coveragerc"
EXTRAS_RC = REPO_ROOT / ".coveragerc-extras"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CODECOV_YML = REPO_ROOT / "codecov.yml"

# 主门禁数值（单一来源 .coveragerc [report] fail_under；本次修复不改变它）。
MAIN_FAIL_UNDER = 80

# extras job 硬门槛：5 个可选模块的总覆盖率下限（与治理文档 R4 临界线一致）。
EXTRAS_OVERALL_FLOOR = 50

# extras job 逐模块硬下限（按 2026-09-06 本地实测行覆盖率 int(rate)-5 冻结：
# mcp_server 87.71% / webui.app 85.77% / xlsx_exporter 100%，取值溯源见
# docs/extras-governance.md §2.1；
# 上调/下调必须同步更新该小节与 README / extras-governance.md 口径。
# deduplicator/portrait_engine 本地缺 imagededup/face_recognition 无法实测，
# 不设逐模块下限，由总下限与夜间 R1/R4 治理兜底）。
PER_MODULE_FLOORS: dict[str, int] = {
    "flashgaze/mcp_server.py": 82,
    "flashgaze/webui/app.py": 80,
    "flashgaze/core/xlsx_exporter.py": 95,
}

# extras 总下限覆盖的模块清单（--include 逗号列表，防止 --cov=flashgaze 全包
# 数据稀释总下限信号）。
EXTRAS_INCLUDE_LIST = (
    "flashgaze/mcp_server.py,"
    "flashgaze/webui/app.py,"
    "flashgaze/core/xlsx_exporter.py,"
    "flashgaze/core/deduplicator.py,"
    "flashgaze/core/portrait_engine.py"
)

# 主门禁 omit 的精确合法集合（mcp_server / webui.app 已纳入主门禁，不得回退）。
MAIN_OMIT_ALLOWED = {
    "flashgaze/core/xlsx_exporter.py",
    "flashgaze/core/deduplicator.py",
    "flashgaze/core/portrait_engine.py",
}

# extras 配置 source 必须覆盖的 5 个可选模块（extras-health 夜间任务依赖）。
EXTRAS_SOURCE_MODULES = {
    "flashgaze.mcp_server",
    "flashgaze.webui.app",
    "flashgaze.core.xlsx_exporter",
    "flashgaze.core.deduplicator",
    "flashgaze.core.portrait_engine",
}

# 主 test 矩阵必须安装的轻量 extras（2026-09 扩围：webui/app、exif_writer
# 纳入主门禁后，其运行依赖也须进主矩阵，否则对应测试跳过、门禁失真；
# heic 使 HEIC 格式矩阵用例真实执行而非跳过）。
REQUIRED_TEST_EXTRAS = {"mcp", "gui", "exif", "heic"}


def _read_rc(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _job_section(ci_text: str, job_key: str, next_job_key: str) -> str:
    """截取 ci.yml 中单个 job 的文本片段（左闭右开，锚点为整行匹配）。"""
    lines = ci_text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == job_key)
    end = next(i for i, ln in enumerate(lines) if ln.rstrip() == next_job_key)
    assert start < end, f"ci.yml 片段定位失败：{job_key} .. {next_job_key}"
    return "\n".join(lines[start:end])


# ── .coveragerc（主门禁）──────────────────────────────────────────────


def test_main_gate_fail_under_unchanged() -> None:
    """主门禁 80% 数值是既有契约，本次修复不得降低（也不允许悄悄调高掩盖问题）。"""
    fail_under = _read_rc(MAIN_RC).getint("report", "fail_under")
    assert fail_under == MAIN_FAIL_UNDER, (
        f".coveragerc [report] fail_under 应为 {MAIN_FAIL_UNDER}，实际 {fail_under}；"
        "调整主门槛必须同步更新本测试与 README 覆盖率门禁口径"
    )


def test_main_gate_omit_is_exactly_three_modules() -> None:
    """omit 精确等于 3 个依赖缺失模块（正常集合 + 双向反例共用本断言）。

    反例语义：mcp_server/webui.app 回到 omit = M-12 修复被回退；cleanup 等
    核心模块进入 omit = 主门禁被掏空。精确集合断言同时拦住两类回归。
    """
    omit_raw = _read_rc(MAIN_RC).get("run", "omit", fallback="")
    omit = {ln.strip() for ln in omit_raw.splitlines() if ln.strip()}
    assert omit == MAIN_OMIT_ALLOWED, (
        f".coveragerc omit 应精确为 {sorted(MAIN_OMIT_ALLOWED)}，实际 {sorted(omit)}；"
        "mcp_server/webui.app 不得回退进 omit，核心模块不得被排除出主门禁"
    )


# ── .coveragerc-extras（extras 硬门槛）───────────────────────────────


def test_extras_rc_has_hard_floor() -> None:
    """extras 配置必须有 fail_under>=50（M-12：杜绝「只报告不设门」）。"""
    parser = _read_rc(EXTRAS_RC)
    assert parser.has_option("report", "fail_under"), (
        ".coveragerc-extras 缺少 [report] fail_under —— extras job 回到了只报告不设门"
    )
    fail_under = parser.getint("report", "fail_under")
    assert fail_under >= EXTRAS_OVERALL_FLOOR, (
        f".coveragerc-extras fail_under={fail_under} 低于硬下限 {EXTRAS_OVERALL_FLOOR}"
    )


def test_extras_rc_source_covers_five_modules() -> None:
    """extras source 必须覆盖 5 个可选模块（tools/extras_health.py MODULES 依赖）。"""
    source_raw = _read_rc(EXTRAS_RC).get("run", "source", fallback="")
    source = {ln.strip() for ln in source_raw.splitlines() if ln.strip()}
    missing = EXTRAS_SOURCE_MODULES - source
    assert not missing, (
        f".coveragerc-extras source 缺少模块 {sorted(missing)}；"
        "夜间 extras-health（R1-R5）依赖 5 模块清单，收紧 source 前先改 tools/extras_health.py"
    )


# ── .github/workflows/ci.yml ─────────────────────────────────────────


def test_ci_test_job_installs_required_extras() -> None:
    """主 test 矩阵必须安装 mcp/gui/exif/heic extras，纳入 80% 门禁的模块才能真实执行。

    缺 mcp → mcp_server 覆盖率 0；缺 gui → webui/app 组件测试全跳过（~22%）；
    缺 exif → exif_writer 0%。任缺其一，主门禁必然失真甚至直接失守
    （2026-09 实测：仅装 mcp 时总覆盖率 79.31% < 80）。
    """
    test_job = _job_section(_read_text(CI_YML), "  test:", "  typecheck:")
    match = re.search(r'pip install -e "\.\[([^"]+)\]"', test_job)
    assert match is not None, 'ci.yml test job 缺少 pip install -e ".[...]" 安装命令'
    installed = {x.strip() for x in match.group(1).split(",")}
    missing = REQUIRED_TEST_EXTRAS - installed
    assert not missing, (
        f"ci.yml test job 安装命令缺少 extras {sorted(missing)}："
        "对应模块测试跳过（mcp_server/webui/app/exif_writer 覆盖率塌方），"
        "主 80% 门禁必然失真；新增 extras 需同步更新本测试与"
        "README 覆盖率门禁小节、docs/extras-governance.md 口径"
    )
    assert "--cov-config=.coveragerc-extras" not in test_job, (
        "test job 必须使用主 .coveragerc（extras 配置仅限 extras job）"
    )


def test_ci_extras_job_has_no_job_level_continue_on_error() -> None:
    """extras job 不得有 job 级 continue-on-error（会吞掉门禁失败 = 零门禁）。

    步级 continue-on-error（pytest 步骤）允许保留：可选模块测试自身不稳定
    不阻塞，但覆盖率门禁步骤必须真实失败。
    """
    extras_job = _job_section(_read_text(CI_YML), "  extras:", "  e2e:")
    job_level = re.search(r"^    continue-on-error:", extras_job, re.MULTILINE)
    assert job_level is None, (
        "ci.yml extras job 仍存在 job 级 continue-on-error —— 门禁失败会被吞掉，"
        "回到「只报告不设门」（M-12 复发）"
    )
    step_level = re.search(r"^ {8}continue-on-error:", extras_job, re.MULTILINE)
    assert step_level is not None, (
        "pytest 步骤的步级 continue-on-error: true 丢失——可选模块测试自身不稳定"
        "应仅由该步级开关兜底，而非 job 级开关"
    )


def test_ci_extras_job_has_unconditional_hard_floor_gate() -> None:
    """extras job 必须有无条件的覆盖率硬门禁步骤（总下限 + 逐模块下限）。"""
    ci_text = _read_text(CI_YML)
    extras_job = _job_section(ci_text, "  extras:", "  e2e:")
    marker = "- name: Coverage gate (hard floors)"
    assert marker in extras_job, (
        "ci.yml extras job 缺少 Coverage gate (hard floors) 步骤——extras 硬门禁被移除"
    )
    lines = extras_job.splitlines()
    gate_start = next(i for i, ln in enumerate(lines) if marker in ln)
    next_step = next(
        (i for i, ln in enumerate(lines[gate_start + 1 :], gate_start + 1) if "- name:" in ln),
        len(lines),
    )
    gate_block = "\n".join(lines[gate_start:next_step])
    # if: always() 是无条件执行的保障（即使 pytest 步骤失败/被取消也评估门禁），
    # 允许；其余条件（如 strict sentinel 条件化）意味着门禁可能被跳过，禁止。
    gate_conditions = re.findall(r"^\s*if:\s*(.+)$", gate_block, re.MULTILINE)
    conditional = [c for c in gate_conditions if c.strip() != "always()"]
    assert not conditional, (
        f"覆盖率硬门禁步骤被条件化执行（{conditional}，如仅 sentinel 锁存在时）——"
        "M-12 要求它无条件生效，锁机制只能做加严升级"
    )
    five_module_line = f'--include="{EXTRAS_INCLUDE_LIST}"'
    assert five_module_line in gate_block, (
        "硬门禁步骤缺少 5 模块 include 的总下限行（fail_under=50 来自 .coveragerc-extras）；"
        "缺它则全包数据会稀释可选模块的总下限信号"
    )
    for module, floor in PER_MODULE_FLOORS.items():
        expected = f'--include="{module}" --fail-under={floor}'
        assert expected in gate_block, (
            f"硬门禁步骤缺少逐模块下限：{expected}；"
            "调整阈值需同步更新本测试与 docs/extras-governance.md §2.1 基线表"
        )


# ── codecov.yml ──────────────────────────────────────────────────────


def test_codecov_core_patch_no_longer_excludes_mcp_and_app() -> None:
    """codecov patch/core 强制状态不得排除 mcp_server/webui.app（其余 3 模块保留排除）。"""
    codecov = _read_text(CODECOV_YML)
    for excluded in ("!flashgaze/mcp_server/**", "!flashgaze/webui/app/**"):
        assert excluded not in codecov, (
            f"codecov.yml 仍排除 {excluded} —— patch/core 强制状态未覆盖该模块"
        )
    for still_excluded in (
        "!flashgaze/core/xlsx_exporter/**",
        "!flashgaze/core/deduplicator/**",
        "!flashgaze/core/portrait_engine/**",
    ):
        assert still_excluded in codecov, (
            f"codecov.yml 丢失既有排除项 {still_excluded}（依赖缺失模块保留在 core 之外）"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

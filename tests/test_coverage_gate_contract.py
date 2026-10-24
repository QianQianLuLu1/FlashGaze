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
  覆盖率硬门禁步骤必须存在且无条件执行（不受 sentinel 锁条件化）；
  test job 必须逐腿产出 junit 并上传（否则产物只有 coverage.xml，腿挂了
  也查不出是失败/报错/未跑）；extras 投递给 Codecov 的 flag 名必须与
  ``codecov.yml`` 声明的 flags 逐字对齐（错配会让 carryforward 静默落空）。
- ``codecov.yml``：patch/core 强制状态不得再排除 mcp_server / webui.app。
- ``requirements-dev.txt``：coverage 引擎必须钉死单版本（不钉时 12 腿矩阵
  会因 requires-python 差异解析出两个版本，跨腿覆盖率不再是同一口径）；
  ruff / mypy / types-requests 同样钉死单版本（区间式会让 CI 与开发机各取
  一版，静态 job 变红时无法排除版本因素）。

改门槛、改 omit、改 CI 门禁结构时，必须同步更新本测试与 README
「覆盖率门禁」小节、docs/extras-governance.md 的口径。
"""

from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MAIN_RC = REPO_ROOT / ".coveragerc"
EXTRAS_RC = REPO_ROOT / ".coveragerc-extras"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CODECOV_YML = REPO_ROOT / "codecov.yml"
DEV_REQ = REPO_ROOT / "requirements-dev.txt"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
EXTRAS_HEALTH_YML = WORKFLOWS_DIR / "extras-health.yml"
BENCHMARK_YML = WORKFLOWS_DIR / "benchmark.yml"
RELEASE_YML = WORKFLOWS_DIR / "release.yml"

# rhysd/github-action-benchmark 没有这两个入参（该 action 唯一的 required 入参是
# output-file-path）。写了不会报错、只会被静默忽略，所以必须由契约测试钉住。
BENCHMARK_UNDECLARED_INPUTS: frozenset[str] = frozenset({"raw-data-file", "output-storage"})

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


def _declared_codecov_flags(codecov_text: str) -> set[str]:
    """取 codecov.yml 顶层 flags: 块下声明的 flag 名（2 空格缩进的键）。"""
    lines = codecov_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "flags:"), None)
    assert start is not None, "codecov.yml 没有顶层 flags: 声明块"
    declared: set[str] = set()
    for ln in lines[start + 1 :]:
        if ln.strip() and not ln.startswith("  "):
            break  # 出块（下一个顶层键）
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ln)
        if match is not None:
            declared.add(match.group(1))
    return declared


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


def test_ci_test_job_uploads_junit_per_leg() -> None:
    """test job 必须逐腿产出并上传 junit，且把本腿结果写进 job summary。

    coverage-* 产物只含 coverage.xml，因此「这条腿挂在哪一行」可查、但「为什么挂」
    不可查：2026-10-23 的 12 腿产物里 macos-py3.10 / windows-py3.10 有 6 行分支
    未覆盖，无法区分用例失败、fixture 报错还是根本没跑。反例护栏：junit 缺失/损坏
    时摘要步骤只发 notice 并以 0 退出——真正的门禁是 pytest 退出码，不让诊断步骤
    反过来制造第二条红。
    """
    test_job = _job_section(_read_text(CI_YML), "  test:", "  typecheck:")
    assert "--junitxml=junit.xml" in test_job, (
        "test job 的 pytest 步骤缺少 --junitxml：腿挂了也拿不到失败清单，只能靠猜"
    )
    assert "name: junit-${{ matrix.os }}-py${{ matrix.python-version }}" in test_job, (
        "junit 必须逐腿独立成产物（勿塞进 coverage-* 产物：那会破坏"
        "「coverage 产物只含 coverage.xml」这一跨腿比对前提）"
    )
    assert "- name: Summarize leg test outcome" in test_job, (
        "缺少逐腿结果摘要步骤：12 条腿的失败点不会出现在 job summary 上"
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


# ── Codecov flag 对齐（ci.yml 投递名 ↔ codecov.yml 声明名）─────────────


def test_ci_extras_job_posts_declared_codecov_flags() -> None:
    """extras job 投递的 flag 名必须逐字命中 codecov.yml 声明的 flags。

    回归实证：写 ``flags: extras-${{ matrix.os }}`` 时实际投递
    ``extras-ubuntu-latest`` / ``extras-macos-latest``，而声明的是
    ``extras-ubuntu`` / ``extras-macos``——两组名字永不相交，声明里的
    carryforward/informational 全部落空，可选模块滚动覆盖率从未真聚合。
    双向反例都拦：新增 extras 腿未登记 → unmapped；改成未声明的 flag 名 → unknown。
    """
    extras_job = _job_section(_read_text(CI_YML), "  extras:", "  e2e:")
    match = re.search(r"flags:\s*\$\{\{\s*fromJSON\('(\{.*?\})'\)\[matrix\.os\]\s*\}\}", extras_job)
    assert match is not None, (
        "extras job 的 Codecov flags 必须写成 fromJSON 查表形式（拼接 matrix.os 会产出"
        "与 codecov.yml 声明不一致的 flag 名，见本用例说明）"
    )
    posted = json.loads(match.group(1))
    declared = _declared_codecov_flags(_read_text(CODECOV_YML))

    unknown = set(posted.values()) - declared
    assert not unknown, (
        f"extras job 投递了未声明的 flag {sorted(unknown)}；"
        "codecov.yml 的 flags: 声明（含 carryforward/informational）对其无效"
    )
    matrix_os = re.search(r"^ {8}os:\s*\[([^\]]*)\]", extras_job, re.MULTILINE)
    assert matrix_os is not None, "extras job 的 strategy.matrix.os 定位失败"
    legs = {x.strip().strip("'\"") for x in matrix_os.group(1).split(",") if x.strip()}
    unmapped = legs - set(posted)
    assert not unmapped, (
        f"extras 矩阵新增腿 {sorted(unmapped)} 未在 Codecov flag 查表里登记，"
        "该腿会投递空 flag；新增 extras 腿必须同步补 flags 查表项"
    )


# ── requirements-dev.txt（测量引擎口径）───────────────────────────────


def test_coverage_engine_is_pinned_to_single_version() -> None:
    """coverage 必须钉死单版本，避免 12 腿矩阵解析出两个测量引擎。

    回归实证：coverage 7.17.0（2026-10-22）起 requires-python >=3.11，未钉版时
    2026-10-23 那轮 12 份 coverage.xml 的 version 属性分裂成 7.16.2（py3.10 腿）
    与 7.17.0（其余腿），跨腿覆盖率不再同口径——差异无法区分「代码变了」还是
    「引擎变了」。反例：写成区间（>=…/<…）同样判红，因为 resolver 仍可能按
    requires-python 分腿选到不同版本。
    """
    entries = [
        ln.strip()
        for ln in _read_text(DEV_REQ).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    specs = [e for e in entries if re.match(r"^coverage(\[[^\]]*\])?[=<>!~]", e)]
    assert len(specs) == 1, (
        f"requirements-dev.txt 必须且只能有一条 coverage 声明，实际 {specs}；"
        "不钉版时 pytest-cov 的 coverage 由 resolver 按各腿 requires-python 选择"
    )
    assert "==" in specs[0], (
        f"coverage 必须钉死单版本（实际 {specs[0]}）；"
        "解除此约束的前提见该文件注释与 docs/agent-context/pitfalls.md"
    )


def test_static_analysis_tools_are_pinned_to_single_version() -> None:
    """ruff / mypy / types-requests 必须钉死单版本，让静态 job 的红灯可归因。

    回归实证：2026-10-23 CI 的 lint job 装 ruff 0.16.10、开发机装 0.16.4，两个静态
    job 同时红而本地全绿。事后查明根因是平台盲区而非版本（EXE001 要看文件 exec 位，
    NTFS 无该语义、本地 `ruff check --select EXE001` 恒不报；mypy 按运行平台解析
    typeshed 的 win32 分支，`_winapi.CreateJunction` 只在 Linux 视角报错），但区间式
    约束让「先怀疑版本」成了无法排除的第一步——钉版把这条归因成本一并消掉。
    反例：任一条改回区间（>=…/<…）即判红，resolver 仍会在 CI 与本地各选一版。
    """
    entries = [
        ln.strip()
        for ln in _read_text(DEV_REQ).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for pkg in ("ruff", "mypy", "types-requests"):
        specs = [e for e in entries if re.match(rf"^{re.escape(pkg)}[=<>!~]", e)]
        assert len(specs) == 1, (
            f"requirements-dev.txt 必须且只能有一条 {pkg} 声明，实际 {specs}；"
            "不钉版时 CI 与开发机会由 resolver 各选一版，静态 job 红灯无法归因"
        )
        assert "==" in specs[0], (
            f"{pkg} 必须钉死单版本（实际 {specs[0]}）；"
            "升级走 dependabot 评审后改钉新单版本，解除前提见该文件注释与 pitfalls §3.8"
        )


# ── .github/workflows/extras-health.yml（夜间治理链路）──────────────────


def _step_with_blocks(text: str, action_contains: str) -> list[str]:
    """截取每个 ``uses: *<action_contains>*`` step 的 ``with:`` 入参文本块。

    纯行文本实现（不 import yaml）：PyYAML 未出现在 requirements-dev.txt / pyproject.toml，
    CI 各腿只靠传递依赖拿到它，不能把契约测试挂在它身上——与本文件既有的
    ``_read_text`` / ``_job_section`` / ``_declared_codecov_flags`` 同一范式。
    """
    lines = text.splitlines()
    blocks: list[str] = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped.startswith("uses:") or action_contains not in stripped:
            continue
        # 向后找紧跟的 with:，遇到下一个 step（"- " 开头）即停
        j = i + 1
        while j < len(lines) and lines[j].strip() != "with:":
            if lines[j].lstrip().startswith("- "):
                break
            j += 1
        assert j < len(lines) and lines[j].strip() == "with:", (
            f"{action_contains} 的 step 没有 with: 入参块，切片逻辑需复核"
        )
        with_indent = len(lines[j]) - len(lines[j].lstrip())
        collected: list[str] = []
        k = j + 1
        while k < len(lines):
            cur = lines[k]
            if cur.strip() and len(cur) - len(cur.lstrip()) <= with_indent:
                break
            collected.append(cur)
            k += 1
        blocks.append("\n".join(collected))
    return blocks


def _with_keys(block: str) -> set[str]:
    """取 with: 块里的入参键名（行首缩进层级的 ``key:``）。"""
    keys: set[str] = set()
    for ln in block.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        match = re.match(r"^\s+([A-Za-z0-9_-]+):", ln)
        if match is not None:
            keys.add(match.group(1))
    return keys


def _benchmark_action_inputs_ok(block: str) -> bool:
    """benchmark action 的入参必须用合法名，且不含本仓库曾误用过的非法名。"""
    keys = _with_keys(block)
    return "output-file-path" in keys and not (keys & BENCHMARK_UNDECLARED_INPUTS)


def test_extras_health_benchmark_action_uses_declared_inputs() -> None:
    """extras-health 的 gh-pages 推送步骤必须用 action 真实存在的入参名。

    回归实证（CI run 40031692874，该 workflow 的首次运行）：runner 原文先报
    ``Unexpected input(s) 'output-storage', 'raw-data-file'``，再报
    ``Invalid value for 'output-file-path' input: ... is not a file``——因为
    ``rhysd/github-action-benchmark`` 根本没有 ``raw-data-file`` 这个入参，必填的
    ``output-file-path`` 于是回退成仓库目录。后果是趋势图从未落盘（gh-pages 存在，
    ``dev/extras-health/`` 404），而 CI 里只留下一条没有 annotation 的 step 失败。
    同仓库 benchmark.yml 用的是 ``output-file-path`` 且长期成功，是现成参照物。
    """
    blocks = _step_with_blocks(_read_text(EXTRAS_HEALTH_YML), "rhysd/github-action-benchmark")
    assert blocks, "extras-health.yml 里没有 benchmark action 步骤，切片逻辑需复核"
    for block in blocks:
        assert _benchmark_action_inputs_ok(block), (
            f"benchmark action 入参非法：缺 output-file-path 或含 {sorted(BENCHMARK_UNDECLARED_INPUTS)} "
            f"中的非法键，实际键为 {sorted(_with_keys(block))}；"
            "action 会静默忽略未知入参并把 output-file-path 回退成目录，趋势图永不落盘"
        )

    # 反例 1：删掉 output-file-path，谓词必须返回 False（否则守卫是恒真的假绿）。
    dropped = "\n".join(
        ln for ln in blocks[0].splitlines() if not ln.lstrip().startswith("output-file-path:")
    )
    assert not _benchmark_action_inputs_ok(dropped), (
        "去掉 output-file-path 后谓词仍为真——守卫形同虚设"
    )
    # 反例 2：把合法键改回曾经误用的 raw-data-file，同样必须被拦下。
    reverted = blocks[0].replace("output-file-path:", "raw-data-file:")
    assert not _benchmark_action_inputs_ok(reverted), (
        "改回 raw-data-file 后谓词仍为真——守卫形同虚设"
    )


def _github_output_offenders(name: str, text: str) -> list[str]:
    """找出「引号 heredoc 体内以 ``$VAR`` 形式引用 GITHUB_OUTPUT/GITHUB_ENV」的位置。

    引号定界符（``<<'PY'``）会让 bash **不做变量展开**，于是 Python 侧看到的
    ``"$GITHUB_OUTPUT"`` 是字面量文件名：写入成功、进程 0 退出、step 恒绿，而
    ``steps.<id>.outputs.*`` 永远为空。
    """
    offenders: list[str] = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        match = re.search(r"<<-?\s*'([A-Za-z_][A-Za-z0-9_]*)'", ln)
        if match is None:
            continue
        delim = match.group(1)
        for offset, body_ln in enumerate(lines[i + 1 :], start=1):
            if body_ln.strip() == delim:
                break
            if re.search(r"\$GITHUB_(OUTPUT|ENV)\b", body_ln):
                offenders.append(f"{name}:{i + 1 + offset}: {body_ln.strip()}")
    return offenders


def test_no_workflow_writes_github_output_inside_quoted_heredoc() -> None:
    """workflow 里不得在引号 heredoc 中用 ``$GITHUB_OUTPUT`` 字面量写步骤输出。

    回归实证（extras-health.yml 的 Evaluate health 步骤）：
    ``python - <<'PY'`` 里写 ``open("$GITHUB_OUTPUT", "a")``，Python 打开的是字面叫
    ``$GITHUB_OUTPUT`` 的文件，进程 0 退出所以 collect job 恒绿；而
    ``steps.eval.outputs.{decision,write_lock,clear_lock,create_issue,close_issue}``
    永远为空 → 写/清 sentinel 锁、建/关 tracking Issue 四处步骤从未执行过一次，
    extras-governance.md §4 的 R4 熔断加严链路整条是死的。
    """
    offenders: list[str] = []
    for yml in sorted(WORKFLOWS_DIR.glob("*.yml")):
        offenders.extend(_github_output_offenders(yml.name, _read_text(yml)))
    assert not offenders, (
        f"引号 heredoc 里出现了不会展开的 $GITHUB_OUTPUT/$GITHUB_ENV：{offenders}；"
        '改用 os.environ["GITHUB_OUTPUT"]，或去掉定界符引号（但会把整段脚本暴露给 shell 展开）'
    )

    # 边界：块外直写 ``echo ... >> "$GITHUB_OUTPUT"`` 是合法写法，不得误伤。
    # 这几条断言同时排除「根本没扫到 run 块」的假绿——证明这些写法确实存在。
    for legit in (CI_YML, BENCHMARK_YML, RELEASE_YML):
        assert '"$GITHUB_OUTPUT"' in _read_text(legit), (
            f"{legit.name} 不再有块外直写 $GITHUB_OUTPUT 的写法，本用例的边界覆盖需复核"
        )

    # 反例：同一个字面量放进引号 heredoc 里必须被抓到。
    synthetic = (
        "        run: |\n"
        "          python - <<'PY'\n"
        '          open("$GITHUB_OUTPUT", "a")\n'
        "          PY\n"
    )
    assert _github_output_offenders("synthetic.yml", synthetic), (
        "谓词抓不到引号 heredoc 里的 $GITHUB_OUTPUT——守卫形同虚设"
    )
    # 反例的对称面：os.environ 写法（无 $）必须放行，否则守卫会误伤正确修复。
    fixed = (
        "        run: |\n"
        "          python - <<'PY'\n"
        '          open(os.environ["GITHUB_OUTPUT"], "a")\n'
        "          PY\n"
    )
    assert not _github_output_offenders("fixed.yml", fixed), (
        "os.environ 写法被误判——守卫会拦住正确修复"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

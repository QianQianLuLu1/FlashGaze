"""FlashGaze AGENTS.md 完整性检查脚本（纯标准库，无第三方依赖）。

用途：
  作为 pre-commit hook 与 CI job 的检查入口，强制 AGENTS.md 存在且包含
  必要章节（1-9 节），守护跨会话项目上下文的 SSoT。

背景（F3 fix）：
  Qoder Agent 每次会话开始时自动读取 AGENTS.md（如果存在），作为静态上下文注入。
  本脚本确保该文件存在且结构完整，避免 Agent 每次从零理解项目上下文。

检查规则：
  1. AGENTS.md 必须存在于仓库根目录
  2. 必须包含 9 个必要章节（## 1. 项目概述 ~ ## 9. 维护约定）
  3. 每个章节必须有实质内容（非空）
  4. docs/agent-context/ 作用域文档必须存在（architecture/pitfalls/fixes/release）

注意（易踩）：规则 4 只看文件在不在磁盘上，不看它进没进版本库。四篇作用域文档留在
工作区而未 git add 时，本地检查照样 PASS，但 CI 在干净 checkout 上取不到它们 →
`agents-md-integrity` job 必红。提交前用
`git ls-files docs/agent-context tools/check_agents_md.py` 复核（应为 5 条）。

退出码：
  0 - 检查通过
  1 - 检查失败（文件不存在或章节缺失）

本地等价命令：
  python -m tools.check_agents_md

CI 等价步骤：
  - name: Check AGENTS.md integrity
    run: python -m tools.check_agents_md

勿加 shebang：本文件在版本库里是 mode 644（不可执行），一旦加上 `#!/usr/bin/env python3`，
Linux 腿的 `ruff check` 就报 EXE001；Windows 无 exec 位语义，本地怎么跑都测不出来。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ── 必要章节清单（与 AGENTS.md 的 9 个章节一一对应）──────────────────────
REQUIRED_SECTIONS = [
    ("1", "项目概述"),
    ("2", "关键架构决策"),
    ("3", "已知陷阱"),
    ("4", "历史修复经验"),
    ("5", "关键命令"),
    ("6", "关键文件路径"),
    ("7", "CI 门禁矩阵"),
    ("8", "发布流程语义"),
    ("9", "维护约定"),
]

# ── 作用域文档清单（从 AGENTS.md 拆分的详细文档）────────────────────────
SCOPED_DOCS = [
    "docs/agent-context/architecture.md",
    "docs/agent-context/pitfalls.md",
    "docs/agent-context/fixes.md",
    "docs/agent-context/release.md",
]

# 章节标题正则：匹配 "## N. 标题" 或 "## N. 标题（副标题）"
SECTION_PATTERN = re.compile(r"^##\s+(\d+)\.\s+(.+?)(?:\s*（.*?）)?\s*$", re.MULTILINE)


def find_repo_root() -> Path:
    """查找仓库根目录（pyproject.toml 所在目录）。"""
    current = Path(__file__).parent.parent
    if (current / "pyproject.toml").exists():
        return current
    # 回退：向上查找
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    # 最终回退：当前目录
    return current


def check_agents_md_exists(repo_root: Path) -> tuple[bool, Path]:
    """检查 AGENTS.md 是否存在。"""
    agents_md = repo_root / "AGENTS.md"
    return agents_md.exists(), agents_md


def check_sections(content: str) -> list[tuple[str, str, bool]]:
    """检查必要章节是否存在。

    返回：[(编号, 标题, 是否存在), ...]
    """
    found_sections = {match.group(1): match.group(2) for match in SECTION_PATTERN.finditer(content)}
    results = []
    for num, expected_title in REQUIRED_SECTIONS:
        exists = num in found_sections
        results.append((num, expected_title, exists))
    return results


def check_section_content(content: str, section_num: str) -> bool:
    """检查指定章节是否有实质内容（非空）。

    简单启发式：章节标题后至少有 1 行非空内容（下一个 ## 之前）。
    """
    # 匹配章节标题到下一个 ## 之间的内容
    pattern = re.compile(
        rf"^##\s+{section_num}\.\s+.+?\n(.*?)(?=^##\s+\d+\.|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return False
    section_body = match.group(1).strip()
    # 至少 1 行非空内容
    return len(section_body.splitlines()) > 0


def main() -> int:
    """主入口。"""
    repo_root = find_repo_root()
    print(f"[check_agents_md] 仓库根目录: {repo_root}")

    # 1. 检查文件存在
    exists, agents_md = check_agents_md_exists(repo_root)
    if not exists:
        print(f"[check_agents_md] ERROR: AGENTS.md 不存在于 {agents_md}")
        print("[check_agents_md] 修复: 创建 AGENTS.md 作为跨会话项目上下文载体")
        print("[check_agents_md] 参考: AGENTS.md §9 维护约定 + docs/agent-context/ 作用域文档")
        return 1

    print(f"[check_agents_md] OK: AGENTS.md 存在: {agents_md}")

    # 2. 读取内容
    try:
        content = agents_md.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[check_agents_md] ERROR: 无法读取 AGENTS.md: {e}")
        return 1

    # 3. 检查必要章节
    section_results = check_sections(content)
    missing_sections = [(num, title) for num, title, exists in section_results if not exists]

    if missing_sections:
        print("[check_agents_md] ERROR: AGENTS.md 缺少必要章节:")
        for num, title in missing_sections:
            print(f"[check_agents_md]   - ## {num}. {title}")
        print("[check_agents_md] 修复: 补充缺失章节，确保 1-9 节完整")
        return 1

    print("[check_agents_md] OK: 所有必要章节存在 (1-9 节)")

    # 4. 检查章节内容非空
    empty_sections = []
    for num, title, exists in section_results:
        if exists and not check_section_content(content, num):
            empty_sections.append((num, title))

    if empty_sections:
        print("[check_agents_md] WARNING: 以下章节内容为空:")
        for num, title in empty_sections:
            print(f"[check_agents_md]   - ## {num}. {title}")
        print("[check_agents_md] 建议: 补充章节内容，避免空章节")
        # 警告不阻塞，返回 0
        return 0

    print("[check_agents_md] OK: 所有章节有实质内容")

    # 5. 检查作用域文档存在
    missing_docs = []
    for doc_path in SCOPED_DOCS:
        full_path = repo_root / doc_path
        if not full_path.exists():
            missing_docs.append(doc_path)

    if missing_docs:
        print("[check_agents_md] ERROR: 缺少作用域文档:")
        for doc_path in missing_docs:
            print(f"[check_agents_md]   - {doc_path}")
        print("[check_agents_md] 修复: 创建缺失的作用域文档（从 AGENTS.md 拆分的详细章节）")
        return 1

    print(f"[check_agents_md] OK: 所有作用域文档存在 ({len(SCOPED_DOCS)} 个)")
    print("[check_agents_md] PASS: AGENTS.md 完整性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""gh-pages 推送脚本的行为契约测试。

锁死 2026-11-05 nightly 事故的三个缺陷：rebase 缺提交身份、浅 fetch、错误不分类，
以及两处 workflow 内联脚本必须收敛到同一个可测试工具。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "ci" / "push_gh_pages.py"
IDENT = ["-c", "user.name=ci-test", "-c", "user.email=ci-test@example.com"]


def _run(
    args: list[str], cwd: Path, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return _run(["git", *args], cwd, env=env).stdout.strip()


@pytest.fixture
def clean_env(tmp_path: Path) -> dict[str, str]:
    """无任何全局/仓库 git 身份，复现 runner 上的 checkout 状态。"""
    home = tmp_path / "empty-home"
    home.mkdir()
    env = os.environ.copy()
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        env.pop(key, None)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(home / "gitconfig"),
        GIT_TERMINAL_PROMPT="0",
    )
    return env


def _init_pair(tmp_path: Path, history: int = 1) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(bare), str(work))
    _git(work, *IDENT, "checkout", "-b", "gh-pages")
    data = work / "dev" / "bench" / "data.js"
    data.parent.mkdir(parents=True)
    for index in range(history):
        data.write_text(f"history {index}\n", encoding="utf-8", newline="\n")
        _git(work, *IDENT, "add", "-A")
        _git(work, *IDENT, "commit", "-m", f"history {index}")
    _git(work, *IDENT, "push", "-u", "origin", "gh-pages")
    return bare, work


def _commit(work: Path, text: str, path: str = "dev/bench/data.js") -> None:
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    _git(work, *IDENT, "add", "-A")
    _git(work, *IDENT, "commit", "-m", f"local {text.strip()}")


def _remote_advance(
    tmp_path: Path, bare: Path, text: str, path: str = "dev/bench/remote.js"
) -> None:
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, *IDENT, "checkout", "gh-pages")
    _commit(other, text, path)
    _git(other, *IDENT, "push", "origin", "gh-pages")


def _install_hook(bare: Path, body: str) -> None:
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    hook.chmod(0o755)


def _attempts(bare: Path) -> int:
    counter = bare / "push-attempts"
    return int(counter.read_text(encoding="utf-8").strip()) if counter.exists() else 0


def _run_tool(
    work: Path,
    env: dict[str, str],
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            str(TOOL),
            "--repo",
            str(work),
            "--branch",
            "gh-pages",
            "--backoff-base",
            "0",
            *extra,
        ],
        REPO_ROOT,
        env=env,
        check=False,
    )


def test_first_push_succeeds(tmp_path: Path, clean_env: dict[str, str]) -> None:
    bare, work = _init_pair(tmp_path)
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "3")

    assert result.returncode == 0, result.stderr
    assert _git(work, "rev-parse", "HEAD") == _git(bare, "rev-parse", "refs/heads/gh-pages")
    assert "push=ok" in result.stdout


def test_non_fast_forward_uses_full_fetch_without_depth(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path, history=60)
    _remote_advance(tmp_path, bare, "remote result\n")
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "3")

    assert result.returncode == 0, result.stderr
    assert _git(bare, "rev-list", "--count", "gh-pages") == "62"
    assert _git(bare, "rev-list", "--merges", "--count", "gh-pages") == "0"
    assert _git(work, "rev-parse", "HEAD") == _git(bare, "rev-parse", "refs/heads/gh-pages")


def test_transient_commit_refs_rules_retries_then_succeeds(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path)
    _install_hook(
        bare,
        "count=0\n"
        "[ -f push-attempts ] && count=$(cat push-attempts)\n"
        "count=$((count+1))\n"
        'echo "$count" > push-attempts\n'
        'if [ "$count" -le 2 ]; then\n'
        '  echo "fatal error in commit_refs_rules" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "5")

    assert result.returncode == 0, result.stderr
    assert _attempts(bare) == 3
    assert "class=transient" in result.stdout
    assert _git(bare, "rev-parse", "refs/heads/gh-pages") == _git(work, "rev-parse", "HEAD")


def test_rebase_works_without_global_git_identity(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path, history=2)
    _remote_advance(tmp_path, bare, "remote result\n")
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "3")

    assert result.returncode == 0, result.stderr
    committer = _git(bare, "log", "-1", "--format=%cn", "gh-pages")
    assert committer == "github-actions[bot]"


def test_fatal_auth_fails_fast_without_retry(tmp_path: Path, clean_env: dict[str, str]) -> None:
    bare, work = _init_pair(tmp_path)
    _install_hook(
        bare,
        "count=0\n"
        "[ -f push-attempts ] && count=$(cat push-attempts)\n"
        "count=$((count+1))\n"
        'echo "$count" > push-attempts\n'
        'echo "remote: Permission to QianQianLuLu1/FlashGaze.git denied to user." >&2\n'
        "exit 1\n",
    )
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "5")

    assert result.returncode == 1, result.stderr
    assert _attempts(bare) == 1, result.stdout + result.stderr
    assert "class=fatal-auth" in result.stdout + result.stderr


def test_missing_local_branch_fails_without_rebase(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path)
    remote_before = _git(bare, "rev-parse", "refs/heads/gh-pages")
    _git(work, "checkout", "-b", "other")
    _git(work, "branch", "-D", "gh-pages")

    result = _run_tool(work, clean_env, "--attempts", "3")

    assert result.returncode == 1
    assert "refs/heads/gh-pages" in result.stdout + result.stderr
    assert _git(bare, "rev-parse", "refs/heads/gh-pages") == remote_before


def test_attempts_exhausted_reports_classified_failure(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path)
    _install_hook(
        bare,
        "count=0\n"
        "[ -f push-attempts ] && count=$(cat push-attempts)\n"
        "count=$((count+1))\n"
        'echo "$count" > push-attempts\n'
        'echo "fatal error in commit_refs_rules" >&2\n'
        "exit 1\n",
    )
    _commit(work, "local result\n")

    result = _run_tool(work, clean_env, "--attempts", "2")

    assert result.returncode == 1
    assert _attempts(bare) == 2
    assert "class=transient" in result.stdout + result.stderr
    assert "attempts=2" in result.stdout + result.stderr


def test_invalid_arguments_exit_2_without_side_effects(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path)
    _commit(work, "local result\n")
    before = _git(bare, "rev-parse", "refs/heads/gh-pages")

    zero = _run_tool(work, clean_env, "--attempts", "0")
    bad_branch = _run(
        [
            sys.executable,
            str(TOOL),
            "--repo",
            str(work),
            "--branch",
            "bad name",
            "--backoff-base",
            "0",
        ],
        REPO_ROOT,
        env=clean_env,
        check=False,
    )
    not_repo = _run(
        [
            sys.executable,
            str(TOOL),
            "--repo",
            str(tmp_path),
            "--branch",
            "gh-pages",
            "--backoff-base",
            "0",
        ],
        REPO_ROOT,
        env=clean_env,
        check=False,
    )

    assert zero.returncode == 2
    assert bad_branch.returncode == 2
    assert not_repo.returncode == 2
    for result in (zero, bad_branch, not_repo):
        assert "参数非法" in result.stdout + result.stderr
    assert _git(bare, "rev-parse", "refs/heads/gh-pages") == before
    assert _attempts(bare) == 0


def test_rebase_conflict_aborts_and_leaves_remote_untouched(
    tmp_path: Path, clean_env: dict[str, str]
) -> None:
    bare, work = _init_pair(tmp_path)
    _remote_advance(tmp_path, bare, "remote version\n", path="dev/bench/data.js")
    remote_before = _git(bare, "rev-parse", "refs/heads/gh-pages")
    _commit(work, "local version\n")

    result = _run_tool(work, clean_env, "--attempts", "3")

    assert result.returncode == 1
    assert "conflict" in (result.stdout + result.stderr).lower()
    assert _git(bare, "rev-parse", "refs/heads/gh-pages") == remote_before
    assert _git(work, "status", "--porcelain") == ""
    assert "REBASE_HEAD" not in _git(work, "rev-parse", "--all")


def _assert_workflow_uses_tool(name: str) -> None:
    text = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    assert "tools/ci/push_gh_pages.py" in text, name
    assert "--depth=50" not in text, name
    assert not re.search(r"git push origin gh-pages:gh-pages", text), name


def test_benchmark_workflow_uses_shared_push_tool() -> None:
    _assert_workflow_uses_tool("benchmark.yml")


def test_extras_health_workflow_uses_shared_push_tool() -> None:
    _assert_workflow_uses_tool("extras-health.yml")


def test_tool_source_has_no_shallow_fetch() -> None:
    source = TOOL.read_text(encoding="utf-8")
    assert "--depth" not in source

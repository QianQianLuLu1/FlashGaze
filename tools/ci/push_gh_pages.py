#!/usr/bin/env python
"""把本地 gh-pages 提交推送到远端，替代 workflow 里的两处内联重试脚本。

设计目标（对应 docs/ci-fix-plan.md）：
- rebase 前显式注入提交身份，不依赖 runner 的全局 gitconfig；
- 同步远端时做完整 fetch（禁止会制造浅历史的参数）；
- 对 push 失败分类：权限类立即失败，非快进/平台瞬时类有限次退避重试；
- 退避用尽仍失败时明确判红并输出分类原因，不静默吞掉。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

FATAL_AUTH_PATTERNS = (
    "permission to ",
    "permission denied",
    "authentication failed",
    "could not read username",
    "invalid username or password",
    "protected branch",
    "gh006",
    "returned error: 403",
)

NON_FAST_FORWARD_PATTERNS = ("non-fast-forward", "fetch first", "stale info")

TRANSIENT_PATTERNS = (
    "commit_refs_rules",
    "internal server error",
    "remote failure",
    "rpc failed",
    "connection reset",
    "connection timed out",
    "timed out",
    "returned error: 500",
    "returned error: 502",
    "returned error: 503",
    "returned error: 504",
)


def _emit(level: str, message: str) -> None:
    print(f"::{level}::{message}", file=sys.stderr)


def _fail_args(message: str) -> int:
    print(f"push-gh-pages: 参数非法: {message}", file=sys.stderr)
    return 2


def _classify(output: str) -> str:
    lowered = output.lower()
    if any(pattern in lowered for pattern in FATAL_AUTH_PATTERNS):
        return "fatal-auth"
    if any(pattern in lowered for pattern in NON_FAST_FORWARD_PATTERNS):
        return "non-fast-forward"
    if any(pattern in lowered for pattern in TRANSIENT_PATTERNS):
        return "transient"
    return "unknown"


def _git(
    git: str,
    repo: str,
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_SEQUENCE_EDITOR="true")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [git, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def _identity_env(args: argparse.Namespace) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": args.author_name,
        "GIT_AUTHOR_EMAIL": args.author_email,
        "GIT_COMMITTER_NAME": args.author_name,
        "GIT_COMMITTER_EMAIL": args.author_email,
    }


def _identity_flags(args: argparse.Namespace) -> list[str]:
    return [
        "-c",
        f"user.name={args.author_name}",
        "-c",
        f"user.email={args.author_email}",
    ]


def _ahead_count(git: str, repo: str, remote: str, branch: str) -> int:
    result = _git(git, repo, ["rev-list", "--count", f"refs/remotes/{remote}/{branch}..HEAD"])
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else -1


def _sync_and_rebase(
    git: str, repo: str, remote: str, branch: str, args: argparse.Namespace
) -> str | None:
    """完整同步远端后按需 rebase；返回错误信息，成功返回 None。"""
    remote_ref = f"refs/remotes/{remote}/{branch}"
    fetch = _git(git, repo, ["fetch", remote, f"+refs/heads/{branch}:{remote_ref}"])
    if fetch.returncode != 0:
        return f"fetch 失败: {(fetch.stdout + fetch.stderr).strip()}"

    ancestor = _git(git, repo, ["merge-base", "--is-ancestor", remote_ref, "HEAD"])
    if ancestor.returncode == 0:
        return None

    rebase = _git(
        git,
        repo,
        [*_identity_flags(args), "rebase", remote_ref],
        extra_env=_identity_env(args),
    )
    if rebase.returncode != 0:
        _git(git, repo, ["rebase", "--abort"])
        conflicts = _git(git, repo, ["diff", "--name-only", "--diff-filter=U"])
        files = conflicts.stdout.strip().replace("\n", ", ") or "未知文件"
        detail = "\n".join((rebase.stdout + rebase.stderr).strip().splitlines()[:20])
        status = _git(git, repo, ["status", "--porcelain=v1"])
        changed = status.stdout.strip().replace("\n", ", ") or "none"
        return f"rebase conflict: {files}\n{detail}\nstatus: {changed}"
    return None


def _remote_sha(git: str, repo: str, remote: str, branch: str) -> str | None:
    result = _git(git, repo, ["ls-remote", remote, f"refs/heads/{branch}"])
    if result.returncode != 0:
        return None
    line = result.stdout.strip().splitlines()
    return line[0].split("\t")[0] if line else None


def _validate(args: argparse.Namespace) -> str | None:
    if not 1 <= args.attempts <= 10:
        return "--attempts 必须在 1..10"
    if not 0 <= args.backoff_base <= 300:
        return "--backoff-base 必须在 0..300"
    if not BRANCH_RE.match(args.branch) or args.branch.startswith("-") or ".." in args.branch:
        return f"--branch 非法: {args.branch!r}"
    if not args.author_name.strip():
        return "--author-name 不得为空"
    if "@" not in args.author_email or any(c.isspace() for c in args.author_email):
        return f"--author-email 非法: {args.author_email!r}"
    if not os.path.isdir(args.repo):
        return f"--repo 不存在: {args.repo}"
    if shutil.which(args.git) is None and not os.path.isfile(args.git):
        return f"--git 不可执行: {args.git}"
    return None


def _run(args: argparse.Namespace) -> int:
    git, repo = args.git, args.repo

    if _git(git, repo, ["rev-parse", "--git-dir"]).returncode != 0:
        return _fail_args(f"--repo 不是 git 仓库: {repo}")
    if _git(git, repo, ["remote", "get-url", args.remote]).returncode != 0:
        return _fail_args(f"远端不存在: {args.remote}")

    branch_ref = f"refs/heads/{args.branch}"
    if _git(git, repo, ["rev-parse", "--verify", "--quiet", branch_ref]).returncode != 0:
        print(f"push-gh-pages: 本地分支不存在: {branch_ref}", file=sys.stderr)
        return 1
    head = _git(git, repo, ["symbolic-ref", "--short", "HEAD"]).stdout.strip()
    if head != args.branch:
        print(f"push-gh-pages: 当前分支 {head!r} 不是目标分支 {args.branch!r}", file=sys.stderr)
        return 1

    # 首次 push 前也先做一次完整同步，避免基于陈旧远端历史起推。
    initial = _sync_and_rebase(git, repo, args.remote, args.branch, args)
    if initial:
        print(f"push-gh-pages: {initial}", file=sys.stderr)
        return 1

    last_class = "unknown"
    for attempt in range(1, args.attempts + 1):
        push = _git(git, repo, ["push", args.remote, f"{args.branch}:{args.branch}"])
        if push.returncode == 0:
            local_sha = _git(git, repo, ["rev-parse", "HEAD"]).stdout.strip()
            remote_sha = _remote_sha(git, repo, args.remote, args.branch)
            if remote_sha is not None and remote_sha != local_sha:
                last_class = "non-fast-forward"
                print(
                    f"attempt={attempt}/{args.attempts} push=ok-but-mismatch "
                    f"local={local_sha[:7]} remote={remote_sha[:7]}",
                    file=sys.stderr,
                )
            else:
                print(f"attempt={attempt}/{args.attempts} push=ok sha={local_sha[:7]}")
                return 0

        output = push.stdout + push.stderr
        last_class = _classify(output)
        ahead = _ahead_count(git, repo, args.remote, args.branch)
        backoff = attempt * args.backoff_base
        print(
            f"attempt={attempt}/{args.attempts} push=rejected class={last_class} "
            f"ahead={ahead} backoff={backoff}"
        )
        print("\n".join(output.strip().splitlines()[:20]), file=sys.stderr)
        _emit("warning", f"gh-pages 推送第 {attempt} 次失败（{last_class}）")

        if last_class == "fatal-auth":
            _emit("error", f"gh-pages 推送被拒绝（{last_class}），不重试")
            return 1

        error = _sync_and_rebase(git, repo, args.remote, args.branch, args)
        if error:
            _emit("error", f"gh-pages 推送中止：{error}")
            return 1

        if attempt < args.attempts:
            time.sleep(backoff)

    _emit(
        "error",
        f"gh-pages 推送在 {args.attempts} 次尝试后仍失败，最后分类={last_class}",
    )
    print(
        f"push-gh-pages: push failed: class={last_class} attempts={args.attempts}", file=sys.stderr
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推送 gh-pages 提交到远端")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="gh-pages")
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--backoff-base", type=float, default=10.0)
    parser.add_argument("--author-name", default="github-actions[bot]")
    parser.add_argument(
        "--author-email", default="41898282+github-actions[bot]@users.noreply.github.com"
    )
    parser.add_argument("--git", default="git")
    args = parser.parse_args(argv)

    invalid = _validate(args)
    if invalid:
        return _fail_args(invalid)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())

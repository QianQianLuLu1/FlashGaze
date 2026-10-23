"""atomic_write 权限保留回归测试。

聚焦数据完整性修复：覆盖已存在目标文件时，原子替换应继承其权限/属主，
而非被默认 umask 放宽（如 0600 → 0644 的信息泄露隐患）。

Windows 权限模型不同（chmod 仅控制只读位，stat 不返回完整 octal 权限），
故严格等值断言仅 POSIX 执行；Windows 上仍验证内容正确性与不抛异常。
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from flashgaze.utils.atomic_write import (
    atomic_write_bytes,
    atomic_write_text,
    cleanup_stale_tmp,
)

_IS_POSIX = os.name != "nt"


def _mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_bytes_preserves_existing_mode(tmp_path: Path) -> None:
    """覆盖已存在文件时，新文件应继承原文件的权限位（如 0600）。"""
    target = tmp_path / "img.jpg"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)  # 模拟受限权限：只有属主可读写

    atomic_write_bytes(target, b"new content")

    assert target.read_bytes() == b"new content"
    if _IS_POSIX:
        # 权限位必须被保留，而非被放宽成默认 umask（数据完整性）
        assert _mode_of(target) == 0o600


def test_text_preserves_existing_mode(tmp_path: Path) -> None:
    """atomic_write_text 同样应继承原文件权限。"""
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")
    os.chmod(target, 0o640)

    atomic_write_text(target, "new", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "new"
    if _IS_POSIX:
        assert _mode_of(target) == 0o640


def test_new_file_uses_default_umask(tmp_path: Path) -> None:
    """目标不存在时不应抛错，且无需继承任何权限。"""
    target = tmp_path / "fresh.json"
    atomic_write_bytes(target, b"data")
    assert target.exists()
    assert target.read_bytes() == b"data"


def test_preserve_mode_false_skips_inheritance(tmp_path: Path) -> None:
    """preserve_mode=False 时显式关闭继承，覆盖后权限按默认 umask。"""
    target = tmp_path / "noinherit.jpg"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)

    atomic_write_bytes(target, b"new", preserve_mode=False)

    # 关闭继承后不再强制 0600，至少能正常落盘且内容更新
    assert target.read_bytes() == b"new"


def test_explicit_mode_on_new_file(tmp_path: Path) -> None:
    """显式 mode= 用于新建文件场景（无已存在目标可继承）：落盘即为目标
    权限而非默认 umask（#2-3 补漏：exif_writer._backup 的 .bak 备份场景）。"""
    target = tmp_path / "fresh_bak.jpg"
    atomic_write_bytes(target, b"data", mode=0o600)

    assert target.read_bytes() == b"data"
    if _IS_POSIX:
        assert _mode_of(target) == 0o600


def test_explicit_mode_overrides_preserve_mode(tmp_path: Path) -> None:
    """显式 mode= 优先于 preserve_mode 继承：目标已存在时也按 mode 落盘。"""
    target = tmp_path / "override.jpg"
    target.write_bytes(b"old")
    os.chmod(target, 0o640)

    atomic_write_bytes(target, b"new", mode=0o600)

    assert target.read_bytes() == b"new"
    if _IS_POSIX:
        assert _mode_of(target) == 0o600


@pytest.mark.skipif(not _IS_POSIX, reason="owner 继承仅 POSIX 有意义")
def test_preserves_owner(tmp_path: Path) -> None:
    """POSIX 上覆盖应继承原文件的属主/属组。"""
    target = tmp_path / "owned.bin"
    target.write_bytes(b"x")
    st = os.stat(target)
    atomic_write_bytes(target, b"y")
    new_st = os.stat(target)
    assert new_st.st_uid == st.st_uid
    assert new_st.st_gid == st.st_gid


# ---------- M-1：只读目标 + chmod best-effort ----------


def test_readonly_target_rejected_leaves_no_tmp(tmp_path: Path) -> None:
    """Windows：目标只读（0o444）时 os.replace 抛 PermissionError；finally 清理
    不得因 tmp 只读而二次抛错掩盖原始异常，且目录无 .tmp 残留（M-1）。"""
    target = tmp_path / "locked.jpg"
    target.write_bytes(b"original")
    os.chmod(target, 0o444)

    with pytest.raises(PermissionError):
        atomic_write_bytes(target, b"new content")

    # M-1 前只读 tmp 会让 unlink 再抛 PermissionError，残留 .tmp 且掩盖原始异常
    assert not list(tmp_path.glob(".*.tmp.*"))
    # 原文件未被破坏
    assert target.read_bytes() == b"original"
    os.chmod(target, 0o600)  # 还原可写，便于 tmp_path 清理


@pytest.mark.skipif(os.name == "nt", reason="POSIX 上 os.replace 可覆盖只读目标")
def test_readonly_target_posix_replaced_in_place(tmp_path: Path) -> None:
    """POSIX：replace 覆盖只读目标成功（由父目录写位决定），权限继承 0o444。"""
    target = tmp_path / "locked.jpg"
    target.write_bytes(b"original")
    os.chmod(target, 0o444)

    atomic_write_bytes(target, b"new content")

    assert target.read_bytes() == b"new content"
    assert _mode_of(target) == 0o444


def test_chmod_failure_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M-1：chmod 失败为 best-effort（与 chown 对称）——不阻断落盘、无 .tmp 残留。"""

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("chmod not permitted")

    monkeypatch.setattr(os, "chmod", _boom)

    target = tmp_path / "img.jpg"
    atomic_write_bytes(target, b"data", mode=0o600)

    assert target.read_bytes() == b"data"
    assert not list(tmp_path.glob(".*.tmp.*"))


def test_preserve_mode_chmod_failure_still_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-1 的 preserve_mode 分支：继承权限的 chmod 失败同样只降级、不阻断落盘。

    上方用例传了显式 mode=，结构上只能走 `if mode is not None` 分支；覆盖已存在
    目标却继承失败（`elif preserve_mode and p.exists()`）是另一条 best-effort
    路径——受限文件系统/奇异 st_mode 下会真实抛 OSError，此前无测试覆盖。
    """

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("chmod not permitted")

    target = tmp_path / "img.jpg"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)  # chmod 必须在打桩前完成

    monkeypatch.setattr(os, "chmod", _boom)
    atomic_write_bytes(target, b"new content")  # 不传 mode：走 preserve_mode 继承分支

    assert target.read_bytes() == b"new content"
    assert not list(tmp_path.glob(".*.tmp.*"))


@pytest.mark.skipif(not _IS_POSIX, reason="os.chown 仅 POSIX 存在")
def test_chown_failure_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """属主继承（os.chown）失败为 best-effort：权限位已继承即达成目的，不得阻断落盘。

    平台记账（勿误读为「测试没跑=没修好」）：本用例在 Windows 4 条 CI 腿上
    必定 SKIPPED，因为生产代码的 `hasattr(os, "chown")` 守卫在 nt 上恒为 False——
    atomic_write.py 的 chown 体属「POSIX 可达 / Windows 永久不可达」，按 pitfalls
    口径记账而不加 pragma 掩盖（pragma 会连带屏蔽 8 条 POSIX 腿上的真实执行）。

    skipif 还有第二个理由，别顺手摘掉它：Windows 的 chmod 只控制只读位，
    `stat` 取不回完整 octal（实测 chown 失败后 0o600 目标回读为 0o666），
    下面的权限等值断言在本模块仅 POSIX 执行——与 test_bytes_preserves_existing_mode
    同一条约定。
    """

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("chown not permitted")

    target = tmp_path / "img.jpg"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)

    monkeypatch.setattr(os, "chown", _boom)
    atomic_write_bytes(target, b"new content")

    assert target.read_bytes() == b"new content"
    assert _mode_of(target) == 0o600, "chown 失败不应牵连已成功的权限继承"
    assert not list(tmp_path.glob(".*.tmp.*"))


# ---------- M-10：cleanup_stale_tmp 新鲜 tmp 宽限 ----------


def test_cleanup_skips_fresh_tmp(tmp_path: Path) -> None:
    """M-10：mtime 距今不足 1 小时的 tmp 视为并发进程正在写，跳过不清理。"""
    fresh = tmp_path / ".a.tmp.12345"
    fresh.write_bytes(b"x")

    assert cleanup_stale_tmp(tmp_path) == 0
    assert fresh.exists()


def test_cleanup_removes_old_tmp(tmp_path: Path) -> None:
    """M-10：mtime 超过 1 小时的匹配 tmp 正常清理（异常退出残留语义不变）。"""
    stale = tmp_path / ".a.tmp.12345"
    stale.write_bytes(b"x")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))

    assert cleanup_stale_tmp(tmp_path) == 1
    assert not stale.exists()

"""原子写工具。

解决"非原子写留下截断脏文件"问题（P2/P3）：直接在目标路径上
`write_text` / `open("w")` 是"先截断、再流式写入"，进程中途死亡会留下
半截 JSON/CSV，下游读取即失败且极难察觉。

统一入口 `atomic_write_text` / `atomic_write_bytes`：
1. 写临时文件 `<name>.tmp.<pid>`（与最终文件同目录，保证同文件系统）
2. flush + 原子 `os.replace(tmp, path)`（Windows/Linux 均原子覆盖）
3. `finally` 清理临时文件，避免进程崩溃遗留垃圾

落盘结果要么完整旧版、要么完整新版，绝不会是半截。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    preserve_mode: bool = True,
    mode: int | None = None,
) -> None:
    """原子写入文本：先写临时文件再 os.replace 覆盖，避免截断脏文件。

    preserve_mode=True 时，覆盖已存在的目标文件会继承其权限/属主，
    避免原子替换把受限权限（如 0600）放宽成默认 umask（如 0644）造成泄露。
    显式 mode=（st_mode 值）用于新建文件场景（目标不存在、无权限可继承），
    在 os.replace 前对临时文件 chmod，落盘瞬间即为目标权限；传了 mode 时
    优先于 preserve_mode 继承。
    """
    _atomic_write(
        path,
        lambda f: f.write(text),
        encoding=encoding,
        preserve_mode=preserve_mode,
        mode=mode,
    )


def atomic_write_bytes(
    path: str | Path,
    data: bytes,
    *,
    preserve_mode: bool = True,
    mode: int | None = None,
) -> None:
    """原子写入字节：与 atomic_write_text 同语义，用于二进制内容。

    encoding 形参对二进制分支无效，已移除，避免误导调用方传 encoding 却无效果（C-17）。
    preserve_mode=True 时继承被覆盖文件的权限/属主（FIX 数据完整性，见 _atomic_write）；
    新建文件场景用显式 mode= 指定权限（如 exif_writer._backup 备份原图，见 _atomic_write）。
    """
    _atomic_write(
        path,
        lambda f: f.write(data),
        binary=True,
        preserve_mode=preserve_mode,
        mode=mode,
    )


def _atomic_write(
    path: str | Path,
    write_fn: Any,
    *,
    encoding: str = "utf-8",
    binary: bool = False,
    preserve_mode: bool = True,
    mode: int | None = None,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件与最终文件同目录，保证 os.replace 是同一文件系统内的原子操作
    tmp = p.parent / f".{p.name}.tmp.{os.getpid()}"
    try:
        open_mode = "wb" if binary else "w"
        with open(tmp, open_mode, encoding=None if binary else encoding) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        # FIX(#2-3): 原子替换不会继承被覆盖文件的权限/属主——临时文件按默认 umask
        # 创建，os.replace 只是改名，原图 0600 会被放宽成 0644，受限场景下信息泄露。
        # 故在 replace 前把临时文件 chmod 成原文件 st_mode，并在 POSIX 上 chown 继承属主；
        # 仅当目标已存在才继承（新文件本就无权限可继承，避免 stat 抛 FileNotFoundError）。
        # FIX(#2-3 补漏): 显式 mode= 覆盖"新建文件"场景——目标是新文件时 preserve_mode
        # 分支不生效，内容会按默认 umask 落盘（如 exif_writer._backup 的原图 .bak：
        # 0600 原图备份成 0644，写入失败路径保留的回滚点恰以放宽权限留存原图）。
        # chmod 作用在 replace 前的临时文件上：落盘瞬间即为目标权限（无放宽窗口）。
        # M-1: chmod 与下方 chown 同为 best-effort——个别文件系统/受限环境下会失败，
        # 此时退回默认 umask 权限但不阻断落盘（写入中断比权限继承缺失更难恢复）。
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        elif preserve_mode and p.exists():
            st = os.stat(p)
            try:
                os.chmod(tmp, st.st_mode)
            except OSError:
                pass
            # os.chown 仅 POSIX 有意义：Windows 上可能 AttributeError/NotImplemented，
            # 用 hasattr + try 双重防护优雅跳过，跨平台不掉链子。
            if hasattr(os, "chown"):
                try:
                    os.chown(tmp, st.st_uid, st.st_gid)
                except OSError:
                    # 属主继承失败（如权限不足）不应阻断落盘，权限位已继承即可
                    pass
        # 原子替换：要么旧文件，要么完整新文件，不会半截
        os.replace(tmp, p)
    finally:
        # 任何情况下都清理临时文件，避免崩溃遗留 .tmp.<pid> 垃圾。
        # M-1: tmp 可能已被 chmod 成只读（如 0o400/0o444 目标），Windows 上直接
        # unlink 只读文件会抛 PermissionError 并掩盖 try 块的原始异常——先放宽为
        # 可写再删（最小权限取 0o600 而非 0o666：Windows 上有写位即清除只读属性，
        # POSIX 上 unlink 本就不需要文件写位）。成功路径 tmp 已随 replace 消失，
        # chmod 抛 FileNotFoundError 被下方 except 吞掉，无额外成本。
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.unlink(missing_ok=True)


# 原子写临时文件名形如 `.{orig}.tmp.{pid}`，精确匹配避免误删其它工具的点文件（C-18）
_STALE_TMP_RE = re.compile(r"^\..*\.tmp\.\d+$")
# M-10: mtime 距今不足该值的 tmp 视为并发进程正在写的存活文件，跳过不清理。
# 1 小时远大于单次原子写耗时，又不会让真正的异常退出残留滞留太久；取 mtime
# 判断为跨平台最简单可靠的方案。
_STALE_TMP_MIN_AGE_SECONDS = 3600


def cleanup_stale_tmp(directory: str | Path) -> int:
    """清理上次异常退出遗留的原子写临时文件（`.{orig}.tmp.{pid}` 模式）。

    仅清理 mtime 距今超过 1 小时的匹配文件（M-10）：过新的 tmp 可能属于并发
    运行中的进程，误删会令其随后的 os.replace 失败；异常退出残留的 tmp 通常
    早已超龄，不受影响。返回清理的文件数量。仅在导出/写清单前调用一次，成本极低。
    """
    d = Path(directory)
    if not d.is_dir():
        return 0
    removed = 0
    now = time.time()
    # FIX(#2-2): 原子写临时文件始终创建在目标文件同目录；当导出/清单落于子目录
    # （如 ./精选/子目录/）时，顶层 iterdir 扫不到，故改为递归 rglob 一并清理。
    for item in d.rglob("*"):
        if item.is_file() and _STALE_TMP_RE.match(item.name):
            try:
                if now - item.stat().st_mtime < _STALE_TMP_MIN_AGE_SECONDS:
                    continue  # 太新：可能是并发进程正在写，保守跳过
            except OSError:
                # stat 失败（竞态中文件刚被其属主删除等）：保守跳过
                continue
            try:
                item.unlink(missing_ok=True)
                removed += 1
            except OSError:
                # 清理失败不应阻断主流程
                continue
    return removed

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
from pathlib import Path
from typing import Any


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """原子写入文本：先写临时文件再 os.replace 覆盖，避免截断脏文件。"""
    _atomic_write(path, lambda f: f.write(text), encoding=encoding)


def atomic_write_bytes(
    path: str | Path,
    data: bytes,
    *,
    encoding: str = "utf-8",
) -> None:
    """原子写入字节：与 atomic_write_text 同语义，用于二进制内容。"""
    _atomic_write(path, lambda f: f.write(data), encoding=encoding, binary=True)


def _atomic_write(
    path: str | Path,
    write_fn: Any,
    *,
    encoding: str,
    binary: bool = False,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件与最终文件同目录，保证 os.replace 是同一文件系统内的原子操作
    tmp = p.parent / f".{p.name}.tmp.{os.getpid()}"
    try:
        mode = "wb" if binary else "w"
        with open(tmp, mode, encoding=None if binary else encoding) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        # 原子替换：要么旧文件，要么完整新文件，不会半截
        os.replace(tmp, p)
    finally:
        # 任何情况下都清理临时文件，避免崩溃遗留 .tmp.<pid> 垃圾
        tmp.unlink(missing_ok=True)


def cleanup_stale_tmp(directory: str | Path) -> int:
    """清理上次异常退出遗留的原子写临时文件（`.*.tmp.<pid>` 模式）。

    返回清理的文件数量。仅在导出/写清单前调用一次，成本极低。
    """
    d = Path(directory)
    if not d.is_dir():
        return 0
    removed = 0
    for item in d.iterdir():
        if item.is_file() and item.name.startswith(".") and ".tmp." in item.name:
            try:
                item.unlink(missing_ok=True)
                removed += 1
            except OSError:
                # 清理失败不应阻断主流程
                continue
    return removed

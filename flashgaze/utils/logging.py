"""统一日志。stdout 留给 JSON 数据，日志一律走 stderr。"""

from __future__ import annotations

import logging
import sys
import threading

_LOGGER_NAME = "flashgaze"
_configured = False
_config_lock = threading.Lock()


def get_logger() -> logging.Logger:
    """获取统一 logger。用模块级标志做一次性配置，避免被第三方库/并发重复添加 handler。

    基于 `logger.handlers` 的判断在并发或第三方库注入 handler 时不可靠，
    改用模块级 `_configured` 标志保证 handler 只挂一次。
    """
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        # FIX(#2-1): 并发首调时多个线程可能同时通过 `not _configured` 判断并各自
        # addHandler，导致 handler 重复挂载、日志行翻倍。用锁 + 二次检查保证仅挂一次。
        with _config_lock:
            if not _configured:
                handler = logging.StreamHandler(stream=sys.stderr)
                handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
                logger.addHandler(handler)
                logger.setLevel(logging.WARNING)
                logger.propagate = False
                _configured = True
    return logger


def set_verbose(verbose: bool) -> None:
    """开启详细日志（--verbose）。"""
    get_logger().setLevel(logging.DEBUG if verbose else logging.WARNING)

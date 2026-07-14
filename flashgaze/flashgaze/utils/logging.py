"""统一日志。stdout 留给 JSON 数据，日志一律走 stderr。"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "flashgaze"


def get_logger() -> logging.Logger:
    """获取统一 logger。通过 handlers 判断是否已初始化，避免全局状态残留。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
    return logger


def set_verbose(verbose: bool) -> None:
    """开启详细日志（--verbose）。"""
    get_logger().setLevel(logging.DEBUG if verbose else logging.WARNING)

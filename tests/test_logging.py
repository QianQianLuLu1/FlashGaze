"""统一日志模块单元测试。"""

from __future__ import annotations

import logging

from flashgaze.utils.logging import get_logger, set_verbose


def test_get_logger_returns_named_logger():
    """get_logger 返回名为 flashgaze 的 logger。"""
    logger = get_logger()
    assert logger.name == "flashgaze"


def test_get_logger_has_stream_handler():
    """logger 注册了 StreamHandler 且绑定到 stderr（首次调用时捕获的引用）。"""
    logger = get_logger()
    assert len(logger.handlers) >= 1
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    # 注意：handler.stream 在 get_logger 首次调用时绑定到当时的 sys.stderr。
    # pytest 捕获后会替换 sys.stderr，故此处只断言 stream 存在且可写。
    assert handler.stream is not None
    assert hasattr(handler.stream, "write")


def test_get_logger_is_idempotent():
    """多次调用不会重复添加 handler。"""
    logger1 = get_logger()
    before = len(logger1.handlers)
    logger2 = get_logger()
    assert logger1 is logger2
    assert len(logger2.handlers) == before


def test_set_verbose_true_sets_debug_level():
    """set_verbose(True) 切到 DEBUG。"""
    set_verbose(True)
    assert get_logger().level == logging.DEBUG


def test_set_verbose_false_sets_warning_level():
    """set_verbose(False) 切回 WARNING。"""
    set_verbose(True)
    set_verbose(False)
    assert get_logger().level == logging.WARNING


def test_logger_emit_to_stderr(capsys):
    """logger.error 输出到 stderr，stdout 无内容。"""
    logger = get_logger()
    logger.error("测试错误消息")
    captured = capsys.readouterr()
    assert "测试错误消息" in captured.err
    assert captured.out == ""

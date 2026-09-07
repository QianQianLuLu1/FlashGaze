"""ProgressReporter 单元测试：三档互斥策略（进度条 / 日志行 / 静默）。

stream 注入假终端流（isatty 恒真）与普通内存流，验证各档行为与生命周期。
终端级（PTY/流式子进程）覆盖见 test_cli_terminal_e2e.py。
"""

from __future__ import annotations

import io
import logging

import pytest

from flashgaze.cli.progress import ProgressReporter, make_progress_reporter


class _FakeTTYStream(io.StringIO):
    """isatty 恒真的内存流，模拟终端 stderr。"""

    def isatty(self) -> bool:
        return True


def test_non_tty_and_not_verbose_is_silent() -> None:
    """非 TTY + 默认（管道/CI/Agent）：不产生任何进度输出。"""
    stream = io.StringIO()
    reporter = ProgressReporter(verbose=False, stream=stream)
    reporter.update(1, 3)
    reporter.update(3, 3)
    reporter.close()
    assert stream.getvalue() == ""


def test_verbose_logs_progress_lines(caplog: pytest.LogCaptureFixture) -> None:
    """--verbose：进度走 [INFO] 日志行（与历史行为一致），不渲染进度条。"""
    stream = io.StringIO()
    reporter = ProgressReporter(verbose=True, stream=stream)
    with caplog.at_level(logging.INFO, logger="flashgaze"):
        reporter.update(1, 3)
        reporter.update(2, 3)
    reporter.close()
    assert [r.getMessage() for r in caplog.records] == ["进度 1/3", "进度 2/3"]
    assert stream.getvalue() == ""


def test_tty_renders_bar_with_fraction_and_newline_on_close() -> None:
    """终端 + 默认：渲染进度条（含 k/N 与 \\r 单行重绘），close 后换行收尾。"""
    stream = _FakeTTYStream()
    reporter = ProgressReporter(verbose=False, stream=stream)
    reporter.update(2, 4)
    reporter.update(4, 4)
    reporter.close()
    text = stream.getvalue()
    assert "2/4" in text
    assert "4/4" in text
    assert "\r" in text
    assert text.endswith("\n")


def test_tty_total_change_resets_bar_position() -> None:
    """total 变化（多阶段重计数）：进度条按新 total 重置并跳到绝对位置。"""
    stream = _FakeTTYStream()
    reporter = ProgressReporter(verbose=False, stream=stream)
    reporter.update(3, 4)
    reporter.update(1, 6)
    reporter.update(6, 6)
    reporter.close()
    text = stream.getvalue()
    assert "3/4" in text
    assert "6/6" in text


def test_close_is_idempotent_and_blocks_further_updates() -> None:
    """close 幂等；关闭后再收到回调不再输出。"""
    stream = _FakeTTYStream()
    reporter = ProgressReporter(verbose=False, stream=stream)
    reporter.update(1, 2)
    reporter.close()
    reporter.close()
    reporter.update(2, 2)
    assert "2/2" not in stream.getvalue()


def test_closed_stream_treated_as_non_tty() -> None:
    """已关闭的流 isatty 抛 ValueError：按非终端处理，不创建进度条也不崩溃。"""
    stream = io.StringIO()
    stream.close()
    reporter = ProgressReporter(verbose=False, stream=stream)
    reporter.update(1, 2)  # 若误建进度条，写入已关闭流会抛 ValueError
    reporter.close()


def test_factory_defaults_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """make_progress_reporter 缺省 stream=sys.stderr，并继承其 TTY 判定。"""
    fake = _FakeTTYStream()
    monkeypatch.setattr("flashgaze.cli.progress.sys.stderr", fake)
    reporter = make_progress_reporter(verbose=False)
    reporter.update(1, 2)
    reporter.close()
    assert "1/2" in fake.getvalue()

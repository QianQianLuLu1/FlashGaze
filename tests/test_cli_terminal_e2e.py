"""终端级 CLI E2E 测试。

与 test_cli_e2e.py（subprocess.run 一次性捕获、只做结束后断言）互补，本文件
验证"运行中"的终端行为：
- TestStreamingPopen（跨平台）：Popen 管道逐行流式读取 —— --verbose 进度日志在
  进程仍在运行时增量到达、stdin 关闭不挂起、SIGINT 中断后 stdout 无半截 JSON；
- TestPtyTerminal（仅 POSIX，pexpect 真 PTY）：默认参数在真实终端渲染进度条、
  --verbose 仍为逐行日志而非进度条、Ctrl+C 及时退出、cleanup 人类可读报告渲染。

多图用例统一 --workers 1：走 hybrid_scorer 的串行评分短路（无进程池），运行
时长可预期、单进程信号语义简单，流式与中断断言不依赖毫秒级时机。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

_IS_WINDOWS = os.name == "nt"
_CMD = [sys.executable, "-u", "-m", "flashgaze"]
_SOURCE_IMAGES = ("sharp.jpg", "blurry.jpg", "dark.jpg", "colorful.jpg", "gray.jpg")


def _env() -> dict[str, str]:
    """子进程环境：清 API Key 避免污染；强制 UTF-8 规避 Windows cp936 下
    中文进度日志按本地编码写出导致的解码错乱。"""
    env = os.environ.copy()
    env.pop("FLASHGAZE_API_KEY", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/corrupted 到临时目录（与 test_cli_e2e 同构）。"""
    for name in ("sharp.jpg", "blurry.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


@pytest.fixture
def many_photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """60 张图的目录：串行评分有足够时长，流式/中断断言不依赖毫秒级时机。"""
    for rep in range(12):
        for name in _SOURCE_IMAGES:
            src = fixtures_dir / name
            if src.exists():
                shutil.copy2(src, tmp_path / f"{rep:02d}_{name}")
    return str(tmp_path)


class TestStreamingPopen:
    """Popen 管道逐行流式断言（Windows 本地/CI 也运行）。"""

    def test_verbose_progress_streams_before_exit(self, many_photo_dir: str) -> None:
        """--verbose 进度日志在进程仍在评分时（poll 为 None）增量到达 stderr。

        capture_output=True 只能在进程结束后拿到全部输出，无法做此断言。
        """
        proc = subprocess.Popen(
            _CMD + [many_photo_dir, "--no-vlm", "--json", "--verbose", "--workers", "1"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=_env(),
        )
        # 看门狗：子进程若始终不产出进度行，迭代会阻塞在 read 上，超时强杀避免挂死
        watchdog = threading.Timer(90.0, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            first_line = None
            assert proc.stderr is not None
            for line in proc.stderr:
                if "进度 " in line:
                    first_line = line
                    break
            assert first_line is not None, "未收到进度日志行"
            assert proc.poll() is None, "首条进度行到达时进程应仍在运行"
        finally:
            watchdog.cancel()
            stdout_text, _ = proc.communicate(timeout=120)
        assert proc.returncode == 0
        data = json.loads(stdout_text or "")
        assert data["summary"]["total"] == 60

    def test_completes_with_stdin_closed_and_silent_progress_when_piped(
        self, many_photo_dir: str
    ) -> None:
        """stdin 关闭：CLI 不读键盘输入；管道（非 TTY）+ 默认无任何进度输出。"""
        result = subprocess.run(
            _CMD + [many_photo_dir, "--no-vlm", "--top", "3", "--json", "--workers", "1"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_env(),
            timeout=120,
            check=False,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["total"] == 60
        assert "进度" not in result.stderr  # 非 TTY + 非 verbose：完全静默

    @pytest.mark.skipif(_IS_WINDOWS, reason="SIGINT 信号语义仅 POSIX")
    def test_sigint_midrun_no_partial_json(self, many_photo_dir: str, tmp_path: Path) -> None:
        """SIGINT 中断长评分：限时非零退出、stdout 无半截 JSON、无结果残留；重跑恢复。"""
        out_path = tmp_path / "result.json"
        args = [
            many_photo_dir,
            "--no-vlm",
            "--json",
            "--verbose",
            "--workers",
            "1",
            "--output",
            str(out_path),
        ]
        proc: subprocess.Popen[str] = subprocess.Popen(
            _CMD + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=_env(),
        )
        watchdog = threading.Timer(60.0, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                if "进度 " in line:
                    break
            proc.send_signal(signal.SIGINT)
            stdout_text, _ = proc.communicate(timeout=30)
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        assert proc.returncode != 0
        if stdout_text.strip():  # 原子性：要么为空，要么必须是完整合法 JSON
            json.loads(stdout_text)
        assert not out_path.exists()  # 原子写：中断不落半截结果
        # 重跑恢复正常写出，且目录无原子写残留的 .tmp 文件
        rerun = subprocess.run(
            _CMD + args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_env(),
            timeout=120,
            check=False,
        )
        assert rerun.returncode == 0
        assert out_path.exists()
        assert not list(tmp_path.glob("*.tmp"))


def _spawn_pty(pexpect: Any, args: list[str], timeout: int = 60) -> tuple[Any, io.StringIO]:
    """在真 PTY 中启动 flashgaze，返回 (child, 已读输出缓冲)。

    pexpect 由调用方经 pytest.importorskip 按需加载（仅 POSIX 可用）。
    """
    buf = io.StringIO()
    child = pexpect.spawn(
        sys.executable,
        ["-u", "-m", "flashgaze", *args],
        encoding="utf-8",
        timeout=timeout,
        env=_env(),
        dimensions=(24, 120),
    )
    child.logfile_read = buf
    return child, buf


def _extract_json(full: str) -> Any:
    """从 PTY 合流输出中提取末尾的 JSON 报告（进度条/日志行不含行首 '{'）。"""
    idx = full.find("\n{")
    assert idx != -1, f"PTY 输出中未找到 JSON 数据块，末尾输出:\n{full[-500:]}"
    return json.loads(full[idx + 1 :])


@pytest.mark.skipif(_IS_WINDOWS, reason="pexpect 需要 POSIX pty 模块")
class TestPtyTerminal:
    """pexpect 真 PTY（POSIX）：终端交互级行为。"""

    def test_tty_default_renders_progress_bar(self, many_photo_dir: str) -> None:
        """默认参数 + 真终端：渲染进度条（k/N 与 \\r 单行重绘），stdout JSON 完整。"""
        pexpect = pytest.importorskip("pexpect")
        child, buf = _spawn_pty(
            pexpect, [many_photo_dir, "--no-vlm", "--top", "3", "--json", "--workers", "1"]
        )
        try:
            child.expect(r"进度 \d+/\d+", timeout=60)
            child.expect(pexpect.EOF, timeout=120)
        finally:
            child.close()
        full = buf.getvalue()
        assert "\r" in full  # 进度条单行重绘
        data = _extract_json(full)
        assert data["summary"]["total"] == 60
        assert child.exitstatus == 0

    def test_tty_verbose_uses_log_lines_not_bar(self, many_photo_dir: str) -> None:
        """--verbose 与进度条互斥：真终端下仍是 [INFO] 日志行，无 '#' 进度条。"""
        pexpect = pytest.importorskip("pexpect")
        child, buf = _spawn_pty(
            pexpect, [many_photo_dir, "--no-vlm", "--json", "--verbose", "--workers", "1"]
        )
        try:
            child.expect(r"\[INFO\] 进度 \d+/\d+", timeout=60)
            child.expect(pexpect.EOF, timeout=120)
        finally:
            child.close()
        full = buf.getvalue()
        assert "##" not in full  # ASCII 进度条填充不出现
        data = _extract_json(full)
        assert data["summary"]["total"] == 60
        assert child.exitstatus == 0

    def test_tty_ctrl_c_exits_promptly_without_partial_json(self, many_photo_dir: str) -> None:
        """评分中 Ctrl+C：限时退出且不输出半截 JSON 报告。"""
        pexpect = pytest.importorskip("pexpect")
        child, buf = _spawn_pty(pexpect, [many_photo_dir, "--no-vlm", "--json", "--workers", "1"])
        try:
            child.expect(r"进度 \d+/\d+", timeout=60)
            child.sendcontrol("c")
            child.expect(pexpect.EOF, timeout=30)
        finally:
            child.close()
        full = buf.getvalue()
        assert '"status"' not in full  # JSON 报告未输出
        assert child.exitstatus != 0  # 被信号杀死时 exitstatus 为 None，同样满足

    def test_tty_cleanup_renders_human_report(self, photo_dir: str) -> None:
        """cleanup 默认 dry-run：真终端渲染多行人类可读报告而非 JSON。"""
        pexpect = pytest.importorskip("pexpect")
        child, buf = _spawn_pty(pexpect, ["cleanup", photo_dir, "--no-vlm", "--top", "1"])
        try:
            child.expect_exact("=== FlashGaze 工作空间清理 ===", timeout=60)
            child.expect_exact("模式: 试运行（不删除）", timeout=30)
            child.expect(pexpect.EOF, timeout=120)
        finally:
            child.close()
        full = buf.getvalue()
        assert "待删除" in full
        assert "\n{" not in full  # 非 --json：不输出 JSON 块
        assert child.exitstatus == 0

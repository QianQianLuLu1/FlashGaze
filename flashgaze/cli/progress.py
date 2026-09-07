"""CLI 进度展示：终端下渲染进度条，其余场景维持既有静默/日志行为。

三档互斥策略（进度只走 stderr，stdout 始终只输出 JSON 数据）：
- --verbose              ：[INFO] 进度 k/N 日志行（历史行为，字节级不变）；
- 终端（stderr 为 TTY）   ：tqdm 进度条（默认体验）；
- 非 TTY 且非 --verbose   ：不输出任何进度（管道/CI/Agent 场景零干扰）。

与 --verbose 互斥而非叠加：日志行会打断进度条的单行重绘，同开必然花屏。
"""

from __future__ import annotations

import sys
import threading
from typing import TextIO

from tqdm import tqdm

from flashgaze.utils.logging import get_logger

# 纯 ASCII 确定性格式：无颜色码与 Unicode 方块，GBK 控制台与终端级 E2E 断言均稳定。
_BAR_FORMAT = "进度 {n_fmt}/{total_fmt} {bar}"


def make_progress_reporter(verbose: bool, stream: TextIO | None = None) -> ProgressReporter:
    """构造进度展示器；stream 缺省 sys.stderr，测试可注入假终端流。"""
    return ProgressReporter(verbose=verbose, stream=stream if stream is not None else sys.stderr)


class ProgressReporter:
    """把 HybridScorer 的 progress_callback(done, total) 映射为用户可见的进度输出。

    回调当前均来自主线程（as_completed 循环），加锁仅作防御；
    update/close 均幂等。
    """

    def __init__(self, verbose: bool, stream: TextIO) -> None:
        self._verbose = verbose
        self._stream = stream
        self._tty = _is_tty(stream)
        self._logger = get_logger()
        self._lock = threading.Lock()
        self._bar: tqdm[None] | None = None
        self._last_done = 0
        self._last_total: int | None = None
        self._closed = False

    def update(self, done: int, total: int) -> None:
        """进度回调；done/total 为绝对计数（已处理张数/总张数）。"""
        with self._lock:
            if self._closed:
                return
            if self._verbose:
                self._logger.info("进度 %d/%d", done, total)
                return
            if self._bar is None:
                if not self._tty:
                    return
                self._bar = tqdm(
                    total=total,
                    file=self._stream,
                    bar_format=_BAR_FORMAT,
                    ascii=True,
                    dynamic_ncols=True,
                    # 每次回调都渲染：图片评分本身是慢操作，节流无收益，
                    # 且确定性渲染让终端级 E2E 断言（k/N 逐帧可见）不依赖时机。
                    mininterval=0,
                )
                self._last_total = total
                self._last_done = 0
            if total != self._last_total:
                # 多阶段各自从 0 计数时，按新 total 重置后跳到绝对位置
                self._bar.reset(total)
                self._last_total = total
                self._last_done = 0
            if done >= self._last_done:
                self._bar.update(done - self._last_done)
            self._last_done = done

    def close(self) -> None:
        """收尾：进度条定格最终状态并换行；幂等，关闭后不再输出。"""
        with self._lock:
            self._closed = True
            if self._bar is not None:
                self._bar.close()
                self._bar = None


def _is_tty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except ValueError:  # 已关闭的流：isatty 抛 ValueError，按非终端处理
        return False

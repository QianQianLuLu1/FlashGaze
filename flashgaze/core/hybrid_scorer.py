"""HybridScorer：合并 CV 客观分与 VLM 场景补偿。

CV 主导，VLM 仅作 ±max_adjustment 微调。

并发模型（充分利用多核 CPU）：
- 纯 CV 模式（--no-vlm）：ProcessPoolExecutor 单阶段多进程并发
- 混合 VLM 模式：分阶段处理
    阶段 1：ProcessPoolExecutor 多进程执行 CV + 人像评分（CPU 密集）
    阶段 2：ThreadPoolExecutor 多线程调用 VLM API（IO 密集）
- workers 参数同时控制进程数与线程数，默认 4

可选扩展：人像专项加分（PortraitEngine）、PHash 去重（Deduplicator）。
"""

from __future__ import annotations

import contextlib
import math
import multiprocessing
import multiprocessing.synchronize
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path
from queue import Empty
from typing import Any

from flashgaze.core.cv_engine import BrisqueIntegrityError, CVEngine
from flashgaze.core.deduplicator import Deduplicator
from flashgaze.core.portrait_engine import PortraitEngine
from flashgaze.core.vlm_client import VLMClient
from flashgaze.defaults import DEFAULT_TOP
from flashgaze.models.schemas import (
    Config,
    CVResult,
    ImageScore,
    PortraitResult,
    VLMResult,
)
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger

# ── 插件评分边界（H-1）──────────────────────────────────────────────
# 插件返回值是不可信输入：PluginScore.score / weight 是无约束的裸 float，
# 而 `min(100.0, nan)` 因 `nan < 100.0` 恒为 False 会返回 100.0，一个返回 NaN
# 的第三方插件即可把全批图片刷成并列满分、top-N 退化为按文件名排序（且无任何
# 异常标记可供 Agent 判定）。故违反下述契约的返回值一律「不采信 + 告警」，
# 与 _assemble 的 math.isfinite 兜底保持同一口径。
# 契约（同时写在 plugins/base.py 的 PluginScore 注释里）：
#   score  必须是有限值且落在 [PLUGIN_SCORE_MIN, PLUGIN_SCORE_MAX]
#   weight 必须是有限值且 |weight| <= PLUGIN_WEIGHT_MAX
# 权重上限取 1.0：内置示例插件为 0.1（单图最多 +10），1.0 已是「插件主导分数」
# 的极端配置，再大即视为配置错误。
PLUGIN_SCORE_MIN = 0.0
PLUGIN_SCORE_MAX = 100.0
PLUGIN_WEIGHT_MAX = 1.0
# 单图累计插件增量上限（正负对称）：多个各自合规的插件叠加仍可能把整批图推到
# 0/100 边界而丢失排序信息，故对累计值设天花板。取 30.0 与 VLM 补偿
# （DEFAULT_VLM_MAX_ADJUSTMENT=10）同量级的 3 倍，留足多插件叠加空间。
PLUGIN_MAX_TOTAL_ADDED = 30.0

# 阶段 1 单张图 CV/人像评分超时上限(秒)。
# 正常图耗时为毫秒到秒级,120s 足够宽松避免误杀好图;语义不同于 VLM 的
# DEFAULT_TIMEOUT_SEC(=30,VLM API 调用超时),不复用以免混淆。
# 畸形 TIFF/WebP 触发 OpenCV C 层死锁时不抛异常只永不返回,此值用于主动隔离。
PER_IMAGE_TIMEOUT_SEC = 120

# 进程池看门狗轮询间隔(秒)：wait(FIRST_COMPLETED) 的等待上限。
# 有 future 完成时 wait 立即返回，此值只影响挂起检测粒度（最多延迟 1s
# 标记超时），不给正常完成路径增加任何延迟。
_HUNG_POLL_SEC = 1.0

# 进程池「整体无进展」判定阈值倍数：阈值 = 倍数 × PER_IMAGE_TIMEOUT_SEC，
# 在看门狗循环前运行时相乘（MED-4），保持与测试对 PER_IMAGE_TIMEOUT_SEC 的
# monkeypatch 联动。「无任何派发/完成」更可能是慢冷启动（spawn 解释器重启 +
# 杀毒扫描 + BRISQUE 预热）而非真死锁，给 3 倍宽限期避免把极慢环境整批误判。
_POOL_STALLED_MULTIPLIER = 3

# 挂起 worker 耗尽全部池槽后允许「强杀 worker + 重建新池 + 重提交未决图」的
# 最大次数。stdlib ProcessPoolExecutor 无法终止单个 worker 原地补位（worker
# 进程意外死亡会把整个池标记为 BrokenProcessPool），只能整池换代。每代 leaked
# 图已标 error 移出 pending，pending 严格缩减，总代数 <= LIMIT+1，必然有界；
# 额度耗尽后回退为「剩余 pending 统一标 阶段1超时-进程池被死锁占满」的旧语义。
# 取 2：覆盖「少量畸形图混在大批中」的常见场景（可容忍 3×workers 张挂起图），
# 同时把病态全挂起批的额外耗时压在 (LIMIT+1)×PER_IMAGE_TIMEOUT_SEC（默认约 6 分钟）。
_POOL_REBUILD_LIMIT = 2

# 串行回退路径的防泄漏硬上限（M-02）：_score_serial 的线程看门狗无法回收挂起
# 线程（daemon 线程只能放弃，栈帧里的全分辨率 BGR 与 CVEngine 随之泄漏）。首次
# 挂起后剩余图已升级一次性子进程托管（挂起可 terminate 真回收），两个上限分别
# 兜底线程回退模式（受限环境子进程创建失败）的内存累积与两种模式的耗时累积：
# - _SERIAL_MAX_LEAKED_THREADS：线程模式被放弃的挂起线程数上限。每线程至少泄漏
#   一份全分辨率 BGR + 一份 CVEngine（BRISQUE 模型），达限即提前整批失败（剩余
#   图统一标「阶段1超时-串行看门狗预算耗尽」）。取 3：与 _POOL_REBUILD_LIMIT=2
#   的「少量畸形图混批可容忍」尺度一致，泄漏内存封顶在数百 MB 量级。
# - _SERIAL_HUNG_BUDGET_MULTIPLIER：累计挂起等待预算 = 倍数 × PER_IMAGE_TIMEOUT_SEC，
#   在 _score_serial 内运行时相乘（与测试对 PER_IMAGE_TIMEOUT_SEC 的 monkeypatch
#   联动，禁止 import 时派生）。子进程模式回收内存但不回收时间——每张挂起图固定
#   消耗单图超时时长，达限后剩余图统一标 error，总耗时必有界（默认 480s）。
_SERIAL_MAX_LEAKED_THREADS = 3
_SERIAL_HUNG_BUDGET_MULTIPLIER = 4

# 拆池前强杀挂起 worker：terminate() 后单进程回收等待上限(秒)，超时仍存活
# （SIGTERM 被屏蔽等极端情况）则升级 kill()。只影响异常路径，正常批零开销。
_TERMINATE_JOIN_SEC = 5.0

# 阶段 1 worker 的返回类型（img_path, CVResult, PortraitResult, phash），
# 仅用于看门狗集合的类型注解。传统赋值别名——本项目 mypy 目标 3.10，禁用 PEP 695。
_Phase1Future = Future[tuple[str, CVResult, PortraitResult, object]]

# 进程内 CVEngine 单例缓存。
# 每个进程（主进程或 ProcessPoolExecutor 子进程）各持有一份，互不干扰。
# 单槽而非 dict：一次批量评分内配置恒定，无需多槽，也避免无界增长。
_CV_ENGINE_SINGLETON: CVEngine | None = None
_CV_ENGINE_KEY: tuple[bool, bool, bool, bool] | None = None


def _get_cv_engine(
    enable_composition: bool,
    enable_noise: bool,
    enable_color: bool,
    downscale: bool,
) -> CVEngine:
    """返回进程内复用的 CVEngine，避免每图重复加载 BRISQUE 模型。

    缓存键覆盖全部影响 CVEngine 行为的构造参数；键不匹配时重建，
    保证绝不会拿到配置不符的旧引擎（静默错配比慢更可怕）。
    若 CVEngine.__init__ 新增参数，必须同步扩充这里的键。

    线程安全：当前调用方均为"每进程一次只跑一个任务"（进程池 worker 或
    主进程串行循环），不存在并发访问。若将来把阶段 1 换成 ThreadPoolExecutor
    或在线程中复用本单例，必须先确认 QualityBRISQUE.compute() 的线程安全性。
    """
    global _CV_ENGINE_SINGLETON, _CV_ENGINE_KEY
    key = (enable_composition, enable_noise, enable_color, downscale)
    if _CV_ENGINE_SINGLETON is None or _CV_ENGINE_KEY != key:
        _CV_ENGINE_SINGLETON = CVEngine(
            enable_composition=enable_composition,
            enable_noise=enable_noise,
            enable_color=enable_color,
            downscale=downscale,
        )
        _CV_ENGINE_KEY = key
    return _CV_ENGINE_SINGLETON


def _reset_cv_engine_cache() -> None:
    """清空进程内引擎缓存。供测试 fixture 调用，避免模块级状态跨用例泄漏。"""
    global _CV_ENGINE_SINGLETON, _CV_ENGINE_KEY
    _CV_ENGINE_SINGLETON = None
    _CV_ENGINE_KEY = None


def _plugin_added(score: Any, weight: Any) -> float | None:
    """把插件返回的 (score, weight) 归一为可采信的加分增量；不可采信返回 None。

    插件是第三方代码，其返回值属不可信输入：非数值、`NaN` / `±inf`、或越出
    `[PLUGIN_SCORE_MIN, PLUGIN_SCORE_MAX]` / `|weight| <= PLUGIN_WEIGHT_MAX`
    契约的值一律返回 None，由调用方跳过并告警（H-1）。

    永不抛异常：`float()` 转换失败（TypeError / ValueError）亦归为不可采信。
    区间已保证乘积有限（|score| <= 100、|weight| <= 1），故无需再对返回值做
    isfinite 检查。
    """
    try:
        s = float(score)
        w = float(weight)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(s) and math.isfinite(w)):
        return None
    if not PLUGIN_SCORE_MIN <= s <= PLUGIN_SCORE_MAX or abs(w) > PLUGIN_WEIGHT_MAX:
        return None
    return s * w


def _init_cv_engine(
    enable_composition: bool,
    enable_noise: bool,
    enable_color: bool,
    downscale: bool,
    brisque_flag: multiprocessing.synchronize.Event | None = None,
) -> None:
    """ProcessPoolExecutor initializer：子进程启动时预热 CVEngine。

    Windows spawn 下子进程会重新 import 本模块并执行本函数，BRISQUE 模型
    因此在子进程内加载一次，而非每图一次；模型对象本身不可 pickle，
    也绝不能作为任务参数跨进程传递。

    普通异常必须静默降级：initializer 抛异常会让整个进程池变为
    BrokenProcessPool，代价远大于"预热失败"。失败时留空缓存，worker
    首次调用会惰性重建。

    唯一例外是 BrisqueIntegrityError（供应链信号）：置位共享 Event 供主
    进程在 BrokenProcessPool 分类处识别（子进程的模块级状态父进程读不到，
    只能经 multiprocessing.Event 跨进程传播），然后响亮 re-raise。模型被
    投毒时宁可整池失败，也绝不静默降级——否则信号会延迟到首个任务、甚至
    在"首批全为损坏图"的批次中完全不浮现。
    """
    try:
        _get_cv_engine(enable_composition, enable_noise, enable_color, downscale)
    except BrisqueIntegrityError:
        # 必须排在 except Exception 之前（RuntimeError 子类，后置会被吞）
        get_logger().error(
            "BRISQUE 模型完整性校验失败（供应链信号），拒绝静默降级，进程池将失败退出"
        )
        if brisque_flag is not None:
            brisque_flag.set()
        raise
    except Exception:  # noqa: BLE001, S110 — 预热失败必须静默降级（见上方 docstring）
        pass


def _evaluate_cv_and_portrait(
    img_path: str,
    enable_composition: bool,
    enable_noise: bool,
    enable_color: bool,
    enable_portrait: bool,
    downscale: bool = True,
    enable_dedup: bool = False,
) -> tuple[str, CVResult, PortraitResult, object]:
    """进程池 worker：在子进程中执行 CV + 人像评分（可选 PHash 编码）。

    仅接收基本类型参数，确保跨进程 pickle 可靠（Windows spawn 模式下
    子进程会重新 import 本模块，函数定义为模块级即可被 pickle 找到）。
    返回 (img_path, cv_result, portrait_result, phash_encoding) 四元组，
    img_path 用于主进程关联结果；phash_encoding 为 PHash 编码（None 表示
    未启用 / 依赖缺失 / 编码失败），主进程可直接复用避免重复读盘。
    phash_encoding 位于第 4 位（索引 3），仅用 [3] 索引的调用方无需改动。

    CV 失败时跳过人像评分与 PHash 编码，与原 score_one 的早返回语义一致，
    避免对损坏图做无用的二次解码。

    引擎走 _get_cv_engine 进程内复用：进程池路径由 initializer 预热，
    串行回退路径在主进程内惰性建一次。仍逐任务传布尔参数而不只靠 initargs，
    是为了让 worker 不依赖 initializer 已成功执行——预热失败也能自己重建。
    """
    cv_engine = _get_cv_engine(
        enable_composition,
        enable_noise,
        enable_color,
        downscale,
    )
    portrait_engine = PortraitEngine(enable=enable_portrait)
    cv, color = cv_engine.evaluate_with_color(img_path)
    if cv.error:
        return img_path, cv, PortraitResult(face_count=0), None
    # 复用 CV 阶段已解码的全分辨率 BGR，避免人像评分二次解码磁盘
    portrait = portrait_engine.evaluate(img_path, preloaded_color=color)
    # 复用子进程已读图：在此时计算 PHash 编码，避免主进程 Deduplicator 重复读盘。
    # imagededup 不可用 / 编码失败时不阻塞主流程，phash_encoding 留 None。
    phash_encoding: object = None
    if enable_dedup:
        try:
            from imagededup.methods import PHash

            # encode_image 返回 16 字符 hex 字符串（失败时 None），
            # 正是 Deduplicator.find_duplicates 的 encoding_map 期望的值类型，直接透传。
            phash_encoding = PHash().encode_image(img_path)
        except Exception:  # noqa: BLE001 — 单图 PHash 失败降级为 None
            phash_encoding = None
    return img_path, cv, portrait, phash_encoding


def _serial_subprocess_worker(
    img_path: str,
    enable_comp: bool,
    enable_noise: bool,
    enable_color: bool,
    enable_portrait: bool,
    downscale: bool,
    enable_dedup: bool,
    queue: Any,
) -> None:
    """一次性子进程的入口（M-02 串行托管）：单图评分并把结果放回队列。

    必须保持模块级定义（spawn 子进程按 module+qualname 重导入后 pickle 才能找
    到），参数全为基本类型（同 _evaluate_cv_and_portrait 的跨进程约束）。
    BrisqueIntegrityError 单独标记而不并入 error：供应链信号（模型哈希不符）
    必须由父进程 raise 穿透，绝不能降级为逐图 error 占位——与线程路径
    （err_holder["brisque"]）和进程池路径（except BrisqueIntegrityError: raise）
    同一契约。
    """
    try:
        result = _evaluate_cv_and_portrait(
            img_path,
            enable_comp,
            enable_noise,
            enable_color,
            enable_portrait,
            downscale,
            enable_dedup,
        )
        queue.put(("ok", result))
    except BrisqueIntegrityError as be:
        queue.put(("brisque", str(be)))
    except Exception as ex:  # noqa: BLE001 — 单图异常跨进程回传，由父进程统一兜底占位
        queue.put(("error", repr(ex)))


def _run_one_in_subprocess(
    img_path: str,
    engine_args: tuple[bool, bool, bool, bool],
    enable_portrait: bool,
    enable_dedup: bool,
    timeout_sec: float,
) -> tuple[str, Any]:
    """在一次性 spawn 子进程中托管单图评分（M-02）：挂起可 terminate 真回收。

    与线程看门狗（daemon 线程无法被 Python 杀掉、只能放弃，其栈帧里的全分辨率
    BGR 与 CVEngine 随之永久泄漏）不同：子进程超时后 terminate/kill 即被操作
    系统整体回收，不再累积内存。必须用 spawn 上下文——主进程可能已存在挂起
    线程，fork 会把线程与锁状态一并复制进子进程。daemon=True：父进程退出时
    孤儿子进程自动被回收。

    返回 (kind, payload)：
    - ("ok", 四元组)         子进程正常完成（同 _evaluate_cv_and_portrait 返回值）
    - ("brisque", 文案)      子进程捕获到 BrisqueIntegrityError（调用方必须 raise 穿透）
    - ("error", repr)        子进程内评分异常
    - ("timeout", None)      超时，子进程已被 terminate/kill 回收
    - ("crashed", exitcode)  子进程退出但未产出结果（如 cv2 C 层崩溃）

    进程创建失败（受限环境缺信号量等）向上抛 OSError/ValueError，由调用方
    回退线程模式。worker 取模块级 _serial_subprocess_worker（函数体内按全局名
    解析，测试可 monkeypatch 注入——子进程按 module+qualname 重导入后执行）。
    """
    enable_comp, enable_noise, enable_color, downscale = engine_args
    ctx = multiprocessing.get_context("spawn")
    queue: Any = ctx.Queue()
    proc = ctx.Process(
        target=_serial_subprocess_worker,
        args=(
            img_path,
            enable_comp,
            enable_noise,
            enable_color,
            enable_portrait,
            downscale,
            enable_dedup,
            queue,
        ),
        daemon=True,
    )
    proc.start()
    proc.join(timeout_sec)
    if proc.is_alive():
        # 挂起子进程：terminate 后限时回收，仍存活升级 kill（对齐拆池路径语义）
        proc.terminate()
        proc.join(_TERMINATE_JOIN_SEC)
        if proc.is_alive():
            proc.kill()
        return ("timeout", None)
    try:
        # 子进程正常退出后结果必然已在管道中（multiprocessing 退出前 flush 队列），
        # 2s 仅兜底极端调度延迟；空队列即崩溃（exitcode 供诊断）。
        kind, payload = queue.get(timeout=2.0)
    except Empty:
        return ("crashed", proc.exitcode)
    return (kind, payload)


class HybridScorer:
    """合并 CV 客观分与 VLM 场景补偿。"""

    def __init__(
        self,
        cv_engine: CVEngine,
        vlm_client: VLMClient | None,
        config: Config,
    ) -> None:
        self.cv_engine = cv_engine
        self.vlm_client = vlm_client
        self.config = config
        # 装配可选引擎（依赖缺失或 enable=False 时降级为空结果，不影响主流程）
        self.portrait_engine = PortraitEngine(enable=config.enable_portrait)
        self.deduplicator = Deduplicator(threshold=config.dedup_threshold)
        # 阶段1看门狗统计（summary 可观测，score_paths 每次调用重置）：
        # timed_out=单图超时隔离数（含串行路径），pool_exhausted=重建额度耗尽后
        # 被判死数，rebuilds=池代际重建次数。
        self.phase1_stats: dict[str, int] = {
            "timed_out": 0,
            "pool_exhausted": 0,
            "rebuilds": 0,
        }

    def score_batch(self, directory: str) -> list[ImageScore]:
        """并发评分目录下所有图片，按综合分降序返回。"""
        return self.score_paths(list(iter_images(directory)))

    def _score_serial(
        self,
        image_paths: list[str],
        engine_args: tuple[bool, bool, bool, bool],
        cv_results: dict[str, tuple[CVResult, PortraitResult]],
        phash_encodings: dict[str, object],
        total: int,
        report_progress: bool,
        progress_callback: Callable[[int, int], None] | None,
    ) -> int:
        """进程池不可用时的串行回退：在主进程内逐图评分。

        抽成方法，让 workers<=1 短路分支与 BrokenProcessPool / 创建失败两条
        回退分支共用同一段循环，避免逻辑重复。返回已评分数量供阶段 2 续接进度。

        M-02 挂起回收：线程看门狗超时后只能放弃 daemon 线程（其栈帧持有的
        全分辨率 BGR 与 CVEngine 无法释放），故首次挂起即升级——剩余图改由
        一次性 spawn 子进程托管（_run_one_in_subprocess），挂起可 terminate
        真正回收；健康图（本方法开头直至首次挂起）仍走主进程线程路径，不为
        workers<=1/MCP 短路场景引入 spawn 开销（见 score_paths 短路注释）。
        子进程创建失败（受限环境）则永久回退线程模式。
        """
        # 清理可能的部分结果，串行重跑保证一致性；不碰引擎缓存
        # （清掉只会让串行路径重新加载 BRISQUE 模型，纯亏）。
        # 串行重跑全量：同步清零池路径的看门狗统计，stats 描述最后一次实际
        # 执行的阶段 1（本方法），避免已废池的计数混入 summary 误导。
        cv_results.clear()
        phash_encodings.clear()
        self.phase1_stats = {"timed_out": 0, "pool_exhausted": 0, "rebuilds": 0}
        done = 0
        logger = get_logger()
        enable_comp, enable_noise, enable_color, downscale = engine_args
        # 是否已升级子进程托管 / 子进程创建是否可用（失败后永久回退线程模式，
        # 避免逐图重试白耗 spawn 开销）。
        escalated = False
        subprocess_ok = True
        # M-02 硬上限（预算运行时相乘，与测试 monkeypatch PER_IMAGE_TIMEOUT_SEC 联动）：
        # leaked=线程模式被放弃的挂起线程数（子进程模式挂起已被回收，不计入）；
        # hung_sec=累计挂起等待时长（两种模式都计——子进程回收内存但不回收时间）。
        # 任一达限即提前整批失败：剩余图统一标「预算耗尽」占位并触发进度回调
        # （对齐池路径 exhausted 语义），不再新建看门线程/子进程。
        leaked = 0
        hung_sec = 0.0
        hung_budget_sec = _SERIAL_HUNG_BUDGET_MULTIPLIER * PER_IMAGE_TIMEOUT_SEC
        for idx, p in enumerate(image_paths):
            if leaked >= _SERIAL_MAX_LEAKED_THREADS or hung_sec >= hung_budget_sec:
                logger.warning(
                    "阶段1串行看门狗预算耗尽(泄漏线程%d>=%d或累计挂起%.0fs>=%.0fs),"
                    "剩余%d张图统一标error占位",
                    leaked,
                    _SERIAL_MAX_LEAKED_THREADS,
                    hung_sec,
                    hung_budget_sec,
                    len(image_paths) - idx,
                )
                for rest in image_paths[idx:]:
                    cv_results[rest] = (
                        CVResult(
                            sharpness=0.0,
                            exposure=0.0,
                            error="阶段1超时-串行看门狗预算耗尽",
                        ),
                        PortraitResult(face_count=0),
                    )
                    self.phase1_stats["timed_out"] += 1
                    if report_progress:
                        done += 1
                        if progress_callback is not None:
                            progress_callback(done, total)
                break
            result: tuple[CVResult, PortraitResult, object, bool] | None = None
            went_thread = False
            if escalated and subprocess_ok:
                try:
                    result = self._score_one_subprocess(p, engine_args)
                except (OSError, ValueError) as pe:
                    logger.warning("一次性子进程创建失败(%s)，串行回退保持线程看门狗模式", pe)
                    subprocess_ok = False
            if result is None:
                went_thread = True
                result = self._score_one_thread(
                    p, enable_comp, enable_noise, enable_color, downscale
                )
            cv, portrait, phash_enc, timed_out = result
            if timed_out:
                hung_sec += PER_IMAGE_TIMEOUT_SEC
                if went_thread:
                    leaked += 1
            if timed_out and not escalated:
                escalated = True
                logger.warning(
                    "串行路径首次单图挂起:剩余 %d 张图改由一次性子进程托管"
                    "(挂起可terminate回收,不再累积泄漏线程)",
                    len(image_paths) - idx - 1,
                )
            cv_results[p] = (cv, portrait)
            if phash_enc is not None:
                phash_encodings[p] = phash_enc
            if report_progress:
                done += 1
                if progress_callback is not None:
                    progress_callback(done, total)
        return done

    def _score_one_thread(
        self,
        img_path: str,
        enable_comp: bool,
        enable_noise: bool,
        enable_color: bool,
        downscale: bool,
    ) -> tuple[CVResult, PortraitResult, object, bool]:
        """线程看门狗托管单图评分（原 _score_serial 循环体，原样抽出）。

        返回 (cv, portrait, phash, timed_out)；timed_out 供调用方触发子进程
        托管升级。注：超时后被放弃的 daemon 线程无法回收，其栈帧持有的
        全分辨率 BGR 与旧 CVEngine 随进程生命周期泄漏——调用方必须据此升级
        子进程托管（M-02），不得让本路径无限连续处理挂起图。
        """
        logger = get_logger()
        # 看门线程:畸形图触发 OpenCV C 层死锁时 _evaluate_cv_and_portrait 永不返回,
        # 串行路径会无限阻塞整批。置于子线程并 join(timeout),超时则放弃该图标 error,
        # 主线程继续下一张。注:C 层死锁线程无法被 Python 杀掉,只能放弃(daemon 线程)。
        err_holder: dict[str, Any] = {}
        state: dict[str, Any] = {}

        def _run() -> None:
            try:
                # 闭包只引用本次调用的局部变量（img_path 等均为方法参数），
                # 无跨图共享状态，不存在 B023 晚绑定问题。
                state["v"] = _evaluate_cv_and_portrait(
                    img_path,
                    enable_comp,
                    enable_noise,
                    enable_color,
                    self.config.enable_portrait,
                    downscale,
                    self.config.dedup,
                )
            except BrisqueIntegrityError as be:
                err_holder["brisque"] = be
            except Exception as ex:  # noqa: BLE001
                err_holder["ex"] = ex

        watcher = threading.Thread(target=_run, daemon=True)
        watcher.start()
        watcher.join(timeout=PER_IMAGE_TIMEOUT_SEC)
        if watcher.is_alive():
            # 单图超时(挂起型 worker):标 error 占位并继续,不中断批量
            logger.warning(
                "阶段1串行单图超时(>%ds),标error占位: %s",
                PER_IMAGE_TIMEOUT_SEC,
                img_path,
            )
            self.phase1_stats["timed_out"] += 1
            # MED-1: 挂起线程仍持有模块级 CVEngine 单例；重置缓存让下一张图
            # 重建全新实例，挂起线程独占旧实例，消除对同一引擎（OpenCV C 层/
            # BRISQUE 模型对象，线程安全性未经验证）的并发调用。
            # 仅超时路径触发，正常批零开销；重建失败由下一轮 _run 兜底为 error 占位。
            _reset_cv_engine_cache()
            return (
                CVResult(
                    sharpness=0.0, exposure=0.0, error=f"阶段1超时(>{PER_IMAGE_TIMEOUT_SEC}s)"
                ),
                PortraitResult(face_count=0),
                None,
                True,
            )
        if "brisque" in err_holder:
            # 供应链信号（模型哈希不符）必须响亮失败，绝不降级为逐图 error 占位
            raise err_holder["brisque"]
        if "ex" in err_holder:
            # 串行模式异常兜底：语义与多进程分支一致
            return (
                CVResult(sharpness=0.0, exposure=0.0, error=f"评分异常: {err_holder['ex']}"),
                PortraitResult(face_count=0),
                None,
                False,
            )
        _, cv, portrait, phash_enc = state["v"]
        return cv, portrait, phash_enc, False

    def _score_one_subprocess(
        self,
        img_path: str,
        engine_args: tuple[bool, bool, bool, bool],
    ) -> tuple[CVResult, PortraitResult, object, bool]:
        """子进程托管单图评分（M-02 升级路径）：挂起可 terminate 真回收。

        返回元组形态与 _score_one_thread 一致（timed_out 仅 kind=="timeout" 为
        True——子进程已被回收，无泄漏线程，但仍计入挂起等待）。BrisqueIntegrityError
        经 _run_one_in_subprocess 的 ("brisque", ...) 标记在此处 raise 穿透，
        绝不降级为逐图 error 占位（供应链信号契约，同线程/进程池路径）。
        进程创建失败（OSError/ValueError）向上抛，由调用方回退线程模式。
        """
        kind, payload = _run_one_in_subprocess(
            img_path,
            engine_args,
            self.config.enable_portrait,
            self.config.dedup,
            timeout_sec=PER_IMAGE_TIMEOUT_SEC,
        )
        if kind == "ok":
            _, cv, portrait, phash_enc = payload
            return cv, portrait, phash_enc, False
        if kind == "timeout":
            get_logger().warning(
                "阶段1串行单图超时(>%ds,子进程已terminate回收),标error占位: %s",
                PER_IMAGE_TIMEOUT_SEC,
                img_path,
            )
            self.phase1_stats["timed_out"] += 1
            return (
                CVResult(
                    sharpness=0.0, exposure=0.0, error=f"阶段1超时(>{PER_IMAGE_TIMEOUT_SEC}s)"
                ),
                PortraitResult(face_count=0),
                None,
                True,
            )
        if kind == "brisque":
            # 供应链信号（模型哈希不符）必须响亮失败，绝不降级为逐图 error 占位
            raise BrisqueIntegrityError(payload)
        if kind == "crashed":
            return (
                CVResult(
                    sharpness=0.0,
                    exposure=0.0,
                    error=f"串行子进程异常退出(exitcode={payload})",
                ),
                PortraitResult(face_count=0),
                None,
                False,
            )
        # kind == "error"：子进程内评分异常，语义与线程模式兜底一致
        return (
            CVResult(sharpness=0.0, exposure=0.0, error=f"评分异常: {payload}"),
            PortraitResult(face_count=0),
            None,
            False,
        )

    def score_paths(
        self,
        image_paths: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ImageScore]:
        """对给定路径列表评分，按综合分降序返回。

        并发模型：
        - 纯 CV 模式（vlm_client is None）：阶段 1 多进程，progress 实时反馈
        - 混合 VLM 模式：阶段 1 多进程静默，阶段 2 多线程 progress 反馈

        progress_callback(done, total) 在每张图评分完成后被调用。
        若 config.dedup=True，评分排序后调用 Deduplicator.mark_duplicates 原地标记。
        """
        if not image_paths:
            return []

        # 重置阶段1看门狗统计：stats 永远描述最近一次 score_paths 调用
        self.phase1_stats = {"timed_out": 0, "pool_exhausted": 0, "rebuilds": 0}

        total = len(image_paths)
        done = 0
        cv_results: dict[str, tuple[CVResult, PortraitResult]] = {}
        vlm_results: dict[str, VLMResult] = {}
        # 子进程预计算的 PHash 编码（仅 config.dedup=True 时填充），
        # 透传给 Deduplicator 避免主进程重复读盘。
        phash_encodings: dict[str, object] = {}

        # 预置 error 占位：覆盖全部 image_paths，确保 cv_results 对任意路径必有条目。
        # 否则若未来新增"跳过提交"的路径，阶段2的 vlm_targets 过滤
        # (cv_results[p][0].error) 与末尾组装循环 (cv_results[img_path]) 会抛 KeyError，
        # 且不在单图错误隔离内，会冲垮 score_paths 整批——违背"错误不中断批处理"原则。
        # 阶段1真实结果会覆盖占位；串行回退路径(_score_serial 先 clear 再全量重写)亦兼容。
        _stub_portrait = PortraitResult(face_count=0)
        for _p in image_paths:
            cv_results[_p] = (
                CVResult(
                    sharpness=0.0,
                    exposure=0.0,
                    error="未提交CV评分（缺失占位，应被阶段1结果覆盖）",
                ),
                _stub_portrait,
            )

        # 阶段 1：CV + 人像评分（多进程，CPU 密集型）
        # 纯 CV 模式下 progress 在此阶段实时反馈；混合模式下此阶段静默
        report_progress_in_phase1 = self.vlm_client is None
        logger = get_logger()
        # initargs 与 submit 传给 worker 的四个引擎参数必须完全一致，否则预热的
        # 引擎缓存键不匹配、worker 会立刻重建，优化归零却毫无报错。抽出共用变量避免写歪。
        engine_args = (
            self.config.enable_composition,
            self.config.enable_noise,
            self.config.enable_color,
            not self.config.no_downscale,
        )
        enable_comp, enable_noise, enable_color, downscale = engine_args

        # 短路：workers 显式 <=1 时进程池无并发收益，且 MCP 场景下反复创建进程池
        # （spawn 子进程 + 重新 import + BRISQUE 预热）开销显著。直接复用串行路径，
        # 进入进程池之前完成阶段 1，绝不重复创建池。
        if self.config.workers is not None and self.config.workers <= 1:
            done = self._score_serial(
                image_paths,
                engine_args,
                cv_results,
                phash_encodings,
                total,
                report_progress_in_phase1,
                progress_callback,
            )
        else:
            try:
                # suppress 罩住 submit 与看门狗循环体：submit 期抛出的
                # BrokenProcessPool 被吞掉且不传播到外层 except，体路径靠
                # pool_body_clean 哨兵在池拆除后补判（见下方守卫）；finally
                # 中 shutdown 的 BrokenProcessPool 同样单独抑制，避免其干扰
                # 外层对"池损坏"的判定与回退流程。
                pool_broken = False
                # 挂起 worker 耗尽全部池槽 / 池整体卡死（initializer 挂起等）：
                # 置位后跳出循环，剩余 pending 图统一标 error 占位。
                exhausted = False
                # suppress 体未被吞掉任何 BrokenProcessPool、循环自然收尾
                # 时置位（while-else），供拆除后的守卫判定。
                pool_body_clean = False
                # 纯计算绑定必须留在池创建之前：submit 期异常被吞时体内赋值全部
                # 跳过，若留在体内这两个名字将未绑定，任何后续引用即
                # UnboundLocalError，且不被下方两个 except 接住，整批崩。
                max_workers = (
                    self.config.workers
                    if self.config.workers is not None
                    else (os.cpu_count() or 1)
                )
                # 池代际循环：挂起 worker 无法被单独终止（fut.cancel() 对运行中
                # future 是 no-op，且 CPython 下 worker 进程意外死亡会把整个池
                # 标记为 BrokenProcessPool，不存在"杀单个 worker 原地补位"），
                # 故 leaked 达到 max_workers 时不立即批死剩余 pending 图，而是
                # 强杀全部 worker、丢弃已废池、重建全新池并只重提交未决图（含
                # 被误杀的好图）。每代 leaked 图已标 error 并移出 pending，
                # pending 严格缩减；重建额度耗尽后维持 exhausted 批死旧语义，
                # 故总代数 <= _POOL_REBUILD_LIMIT + 1，必然有界。不加「有进展
                # 才允许重建」门槛：2 worker 全挂 + 1 排队图的场景全代零完成
                # 也必须重建才能救回排队图，有界性由额度保证。
                rebuilds_left = _POOL_REBUILD_LIMIT
                unresolved = list(image_paths)
                # 已完成的 future 总数（含异常兜底完成），独立于 progress 上报：
                # 混合模式下阶段 1 静默（report_progress_in_phase1=False、done 恒 0），
                # 「整体无进展且零完成」的串行回退判定必须用它（MED-4）。
                completed_any = 0
                # 整体无进展阈值：运行时与 PER_IMAGE_TIMEOUT_SEC 相乘（见常量注释）
                stalled_sec = _POOL_STALLED_MULTIPLIER * PER_IMAGE_TIMEOUT_SEC
                # 供应链标志：initializer 检出 BrisqueIntegrityError 时在 worker
                # 内置位。initializer 运行在子进程，其模块级状态父进程读不到，
                # 只能经 multiprocessing.Event 跨进程传播（initargs 末位传入，
                # _init_cv_engine 不把它计入引擎缓存键）。主循环在 BrokenProcessPool
                # 分类处优先检查本标志：置位 → 响亮抛出，绝不降级串行重跑。
                # while 循环外声明仅供下方 except 引用；每代建池前新建独立
                # Event，旧池不复用，避免跨代污染。
                brisque_flag: multiprocessing.synchronize.Event | None = None
                while True:
                    leaked = 0  # 本代被死锁/挂起 worker 占用的池槽计数
                    rebuild = False  # 本代是否走「强杀 + 重建 + 重提交未决图」
                    # suppress 体未被吞掉任何 BrokenProcessPool、循环自然收尾
                    # 时置位（while-else），供拆除后的守卫判定；每代重置。
                    pool_body_clean = False
                    # 显式拆池替代 with 管理：看门狗放弃挂起 worker 后池内仍有永不
                    # 完成的工作项，with/__exit__ 的 shutdown(wait=True) 会在拆除
                    # 阶段永久阻塞（见 finally 注释），改为 finally 先 terminate
                    # 挂起 worker 再 shutdown。
                    brisque_flag = multiprocessing.Event()
                    pool = ProcessPoolExecutor(
                        max_workers=self.config.workers,
                        initializer=_init_cv_engine,
                        initargs=(*engine_args, brisque_flag),
                    )
                    try:
                        with contextlib.suppress(BrokenProcessPool):
                            futures = {
                                pool.submit(
                                    _evaluate_cv_and_portrait,
                                    p,
                                    enable_comp,
                                    enable_noise,
                                    enable_color,
                                    self.config.enable_portrait,
                                    downscale,
                                    self.config.dedup,
                                ): p
                                for p in unresolved
                            }
                            # 看门狗状态：pending=尚未出结果的 future；deadlines 记录
                            # 首次观测到 running 的时刻+超时。as_completed 只产出已完成
                            # 的 future，其 result(timeout) 恒立即返回、超时分支永远
                            # 不可达（挂起 future 更是永远轮不到产出），故改用
                            # wait(FIRST_COMPLETED) 主动轮询实现单图超时。
                            pending: set[_Phase1Future] = set(futures)
                            deadlines: dict[_Phase1Future, float] = {}
                            last_progress = time.monotonic()
                            while pending:
                                # 等待上限取"最近一次 deadline 到期时刻"与轮询间隔的较小者：
                                # 有完成立即唤醒，deadline 到期也即醒，检测延迟不叠加轮询周期。
                                now = time.monotonic()
                                tick = min([_HUNG_POLL_SEC, *(d - now for d in deadlines.values())])
                                done_batch, pending = wait(
                                    pending,
                                    timeout=max(0.0, tick),
                                    return_when=FIRST_COMPLETED,
                                )
                                now = time.monotonic()
                                for fut in done_batch:
                                    img_path = futures[fut]
                                    deadlines.pop(fut, None)
                                    completed_any += 1
                                    try:
                                        _, cv, portrait, phash_enc = fut.result()
                                    except BrokenProcessPool:
                                        # 池已废（initializer 失败 / 子进程被杀），单图兜底毫无意义：
                                        # 置位并跳出循环，交给下方 except 统一降级为串行重跑，
                                        # 否则整批图都会被标成 error。
                                        pool_broken = True
                                        break
                                    except BrisqueIntegrityError:
                                        # 供应链信号（模型哈希不符）必须响亮失败，绝不降级为逐图 error 占位
                                        raise
                                    except Exception as e:  # noqa: BLE001 — 子进程单图异常兜底为 error 占位，不中断批量评分
                                        # 子进程异常兜底：构造 error 占位，避免中断批量评分
                                        # 与 _evaluate_cv_and_portrait 内 CV 失败早返回语义一致，
                                        # 下游 vlm_targets 过滤与 _assemble 的 cv.error 分支均天然兼容
                                        cv = CVResult(
                                            sharpness=0.0, exposure=0.0, error=f"子进程异常: {e}"
                                        )
                                        portrait = PortraitResult(face_count=0)
                                        phash_enc = None
                                    cv_results[img_path] = (cv, portrait)
                                    if phash_enc is not None:
                                        phash_encodings[img_path] = phash_enc
                                    if report_progress_in_phase1:
                                        done += 1
                                        if progress_callback is not None:
                                            progress_callback(done, total)
                                if pool_broken:
                                    break
                                if done_batch:
                                    last_progress = now
                                # 首次观测到"已在 worker 上执行"才开始计时：排队等待不计入，
                                # 大批量下健康图排队远超单图耗时，按提交时刻计时会误杀好图。
                                # 语义与串行路径看门狗一致（每图从自身开始执行起算）。
                                for f in pending:
                                    if f not in deadlines and f.running():
                                        deadlines[f] = now + PER_IMAGE_TIMEOUT_SEC
                                        last_progress = now
                                # 挂起型 worker：畸形 TIFF/WebP 触发 OpenCV C 层死锁，
                                # 不抛异常只永不返回。隔离为 error 占位，不中断批量。
                                hung = [
                                    f
                                    for f in pending
                                    if deadlines.get(f) is not None and deadlines[f] <= now
                                ]
                                for f in hung:
                                    img_path = futures[f]
                                    leaked += 1
                                    deadlines.pop(f, None)
                                    pending.discard(f)
                                    logger.warning(
                                        "阶段1单图超时(>%ds),标error占位: %s",
                                        PER_IMAGE_TIMEOUT_SEC,
                                        img_path,
                                    )
                                    self.phase1_stats["timed_out"] += 1
                                    cv_results[img_path] = (
                                        CVResult(
                                            sharpness=0.0,
                                            exposure=0.0,
                                            error=f"阶段1超时(>{PER_IMAGE_TIMEOUT_SEC}s)",
                                        ),
                                        PortraitResult(face_count=0),
                                    )
                                    if report_progress_in_phase1:
                                        done += 1
                                        if progress_callback is not None:
                                            progress_callback(done, total)
                                # 注:fut.cancel() 对运行中的 ProcessPoolExecutor future
                                # 是 no-op,无法终止子进程,挂起 worker 只能放弃其结果,
                                # 进程由 finally 拆池阶段强制 terminate(见下)。leaked 达到
                                # max_workers 时不直接批死:先强杀全部 worker 重建新池、
                                # 只重提交未决图(见下方 rebuild),额度耗尽才回退旧语义。
                                if leaked >= max_workers and pending:
                                    if rebuilds_left > 0:
                                        rebuilds_left -= 1
                                        rebuild = True
                                        self.phase1_stats["rebuilds"] += 1
                                        logger.warning(
                                            "进程池被挂起耗尽(leaked=%d>=%d),强杀 worker 重建"
                                            "第 %d 代池,重提交 %d 张未决图",
                                            leaked,
                                            max_workers,
                                            _POOL_REBUILD_LIMIT - rebuilds_left + 1,
                                            len(pending),
                                        )
                                        break
                                    logger.warning(
                                        "进程池被死锁占满(leaked=%d>=%d)且重建额度(%d)已耗尽,"
                                        "标记剩余pending图为error",
                                        leaked,
                                        max_workers,
                                        _POOL_REBUILD_LIMIT,
                                    )
                                    exhausted = True
                                    break
                                if (
                                    not done_batch
                                    and not hung
                                    and not any(f.running() for f in pending)
                                    and now - last_progress >= stalled_sec
                                ):
                                    if completed_any == 0:
                                        # 一张都未完成即整体无进展（initializer 挂起或极慢
                                        # 冷启动，MED-4）：不整批标 error，改走串行回退——
                                        # 串行路径有逐图看门狗，挂起图可被隔离、健康图正常
                                        # 出分。置 pool_broken 经既有补抛路径进 except 回退；
                                        # finally 按 pool_broken 分支强杀 worker，避免
                                        # shutdown(wait=True) 等待永不完成的排队工作项。
                                        # 不走 rebuild：重建新池解决不了环境性卡死。
                                        logger.warning(
                                            "进程池 >%ds 无任何派发/完成且零完成，回退串行重跑",
                                            stalled_sec,
                                        )
                                        pool_broken = True
                                        break
                                    # 无任何 future 被派发/完成且长期无进展（如 initializer
                                    # 挂起导致所有图永不出队）：池整体卡死，等待永不结束。
                                    logger.warning(
                                        "进程池整体无进展(>%ds 无派发/完成),标记剩余pending图为error",
                                        stalled_sec,
                                    )
                                    exhausted = True
                                    break
                            else:
                                # while 正常收尾（pending 清空、无 break）才置位：
                                # pool_broken / exhausted / rebuild 三条 break 路径
                                # 跳过 else 不置位，下方守卫据此区分"循环自然结束"
                                # 与"submit 期 BrokenProcessPool 被 suppress 吞掉
                                # 后静默退出"。
                                pool_body_clean = True
                    finally:
                        # 拆池前必须强杀已被看门狗放弃的挂起 worker（畸形图触发
                        # OpenCV C 层死锁：永不返回、不抛异常）。不终止则其工作项
                        # 永不产生结果，pending_work_items 永不排空，shutdown(wait=True)
                        # join 管理线程无限阻塞；即便走到 _join_executor_internals，
                        # 其 p.join() 也只对 broken 进程 terminate——挂死发生在拆除
                        # 阶段，下方 exhausted 收尾标记代码根本执行不到。已取回的
                        # 结果不受 terminate 影响；挂起进程被杀后其 future 会被 set
                        # BrokenProcessPool，但已无人再读这些 future。
                        # rebuild 路径同理：重建前必须先强杀本代全部 worker（含挂起者
                        # 与正在跑好图者——后者的结果作废、下代重提交）。
                        # pool_broken 一并覆盖：「整体无进展零完成」回退路径（MED-4）
                        # 与 submit 期损坏路径下池内仍有排队/挂起工作项，不强杀同样
                        # 会令 shutdown(wait=True) 永久阻塞、串行回退永不可达。
                        if leaked or rebuild or exhausted or pool_broken:
                            # _processes 为私有 API（3.10-3.13 均存在，CPython 自家
                            # _join_executor_internals 同样以它枚举 worker），getattr
                            # 防御未来版本变动；fake 池默认空表（或无此属性）时安全跳过。
                            proc_map = getattr(pool, "_processes", None) or {}
                            procs = list(proc_map.values())
                            try:
                                for proc in procs:
                                    proc.terminate()
                                for proc in procs:
                                    proc.join(_TERMINATE_JOIN_SEC)
                                    if proc.is_alive():
                                        logger.warning(
                                            "terminate 未生效，升级 kill 挂起 worker: pid=%s",
                                            proc.pid,
                                        )
                                        proc.kill()
                            except OSError:
                                # 进程已退出等竞态：跳过即可，不得掩盖在途异常
                                # （如 BrisqueIntegrityError 经 finally 向外传播）。
                                logger.debug("终止挂起 worker 时进程已退出", exc_info=True)
                        with contextlib.suppress(BrokenProcessPool):
                            pool.shutdown(wait=True)
                    if rebuild:
                        # 本代从未出结果的图（含被强杀误伤的运行中好图）重提交到
                        # 下一代池；已完成结果保留在 cv_results，不重跑。
                        unresolved = [futures[f] for f in pending]
                        continue
                    # 池耗尽/卡死后中断循环:把仍未完成的 pending 图统一标 error 占位,
                    # 它们的 future 永远等不到空闲 worker,继续等待会二次挂起。
                    # (不能用 `p not in cv_results` 判定——所有路径已在循环前预置占位)
                    if exhausted:
                        for f in pending:
                            img_path = futures[f]
                            self.phase1_stats["pool_exhausted"] += 1
                            cv_results[img_path] = (
                                CVResult(
                                    sharpness=0.0,
                                    exposure=0.0,
                                    error="阶段1超时-进程池被死锁占满",
                                ),
                                PortraitResult(face_count=0),
                            )
                            if report_progress_in_phase1:
                                done += 1
                                if progress_callback is not None:
                                    progress_callback(done, total)
                    if not pool_body_clean and not exhausted and not pool_broken:
                        # submit 期抛出的 BrokenProcessPool 被 suppress 吞掉：异常未传播
                        # 出 try 体，两个外层 except 均接不住，串行回退会被静默绕过、
                        # 整批退化为"未提交CV评分"占位。置位后走下方显式补抛进串行回退。
                        # exhausted（有意标 error 不回退）、rebuild（已 continue 进下一
                        # 代）与 pool_broken（已有补抛）三路不得被本守卫改写。
                        pool_broken = True
                    if pool_broken:
                        # 在 suppress 之外抛出，让下方 except 显式捕获并进入串行回退
                        raise BrokenProcessPool("进程池已损坏")
                    # 本代自然收尾（pending 清空、无 rebuild/耗尽/损坏）：整批完成
                    break
            except BrokenProcessPool:
                # 池损坏兜底：不再靠 (OSError, RuntimeError, ValueError) 顺带捕获
                # （BrokenProcessPool 虽是 RuntimeError 子类，但语义与代价不同，单独处理）
                if brisque_flag is not None and brisque_flag.is_set():
                    # 供应链信号经 initializer 在 worker 内置位、跨进程传播到主进程：
                    # 响亮失败穿透到 CLI 退出码 4，绝不降级为串行重跑（与循环内
                    # fut.result() 的 BrisqueIntegrityError 分支同源契约）。
                    raise BrisqueIntegrityError(
                        "进程池预热阶段检出 BRISQUE 模型完整性校验失败（供应链信号）"
                    ) from None
                logger.warning("进程池不可用，已回退串行")
                done = self._score_serial(
                    image_paths,
                    engine_args,
                    cv_results,
                    phash_encodings,
                    total,
                    report_progress_in_phase1,
                    progress_callback,
                )
            except BrisqueIntegrityError:
                # 循环内响亮 re-raise 的供应链信号是 RuntimeError 子类，若不加此
                # 分支会命中下方 (OSError, RuntimeError, ValueError)，打出误导性
                # "创建失败"日志并全量串行重跑后才真正抛出。直接穿透。
                raise
            except (OSError, RuntimeError, ValueError) as e:
                # 受限环境（Docker/CI 等）多进程创建失败，回退到当前进程串行执行
                logger.warning(
                    "ProcessPoolExecutor 创建失败（%s），回退到串行模式",
                    e,
                )
                done = self._score_serial(
                    image_paths,
                    engine_args,
                    cv_results,
                    phash_encodings,
                    total,
                    report_progress_in_phase1,
                    progress_callback,
                )

        # 阶段 2：VLM 评分（多线程，IO 密集型）
        # 仅 vlm_client is not None 时执行；CV 失败的图跳过 VLM
        if self.vlm_client is not None:
            vlm_targets = [p for p in image_paths if not cv_results[p][0].error]
            errored_count = total - len(vlm_targets)

            if vlm_targets:
                with ThreadPoolExecutor(max_workers=self.config.workers) as vlm_pool:
                    # 命名 vlm_pool/vlm_futures/vfut：与阶段 1 的 pool/futures/fut 区分，
                    # 同名会让 mypy 把两处变量类型/Future 泛型参数 join 到一起
                    vlm_futures = {
                        vlm_pool.submit(
                            self.vlm_client.judge,
                            p,
                            cv_results[p][0],
                        ): p
                        for p in vlm_targets
                    }
                    for vfut in as_completed(vlm_futures):
                        img_path = vlm_futures[vfut]
                        try:
                            vlm_results[img_path] = vfut.result()
                        except Exception as e:  # noqa: BLE001 — VLM 单图异常兜底，与 judge 内部失败语义一致
                            # VLM 异常兜底：与 judge 内部失败语义一致
                            vlm_results[img_path] = VLMResult(
                                0.0,
                                "VLM 异常",
                                ok=False,
                                error=str(e),
                                provider=self.vlm_client.provider,
                                scene=self.vlm_client.scene,
                            )
                        done += 1
                        if progress_callback is not None:
                            progress_callback(done + errored_count, total)
            else:
                # 所有图 CV 失败，直接报告完成
                if progress_callback is not None:
                    progress_callback(total, total)

        # 组装最终 ImageScore（按 image_paths 原始顺序，后续排序统一处理）
        results: list[ImageScore] = []
        for img_path in image_paths:
            cv, portrait = cv_results[img_path]
            vlm = vlm_results.get(img_path)
            results.append(self._assemble(img_path, cv, portrait, vlm))

        # 插件评分阶段（M4）：必须先于排序执行，让插件叠加后的最终分
        # 参与后续排序，进而让 _mark_selected 的 top-N 基于最终分选取，
        # 否则插件在排序后改分会选错图（见 test_plugin_low_score_excluded_from_selection）。
        if self.config.enable_plugins:
            self._run_plugins(results)

        # 按 score 降序，同分按全路径升序，保证排序稳定可复现（二级键用全路径：
        # 递归扫描/调用方直传列表下不同子目录可能同名，纯文件名键会退化为输入序）
        # 必须放在插件之后：此时 score 已是最终分（含插件叠加）
        results.sort(key=lambda s: (-s.score, s.path))

        self._mark_selected(results)
        # 去重后处理：标记非最高分图为 selected=False, deduped=True
        # 透传子进程预计算的 phash_encodings，避免主进程重复读盘
        if self.config.dedup:
            self.deduplicator.mark_duplicates(results, encodings=phash_encodings)

        return results

    def _run_plugins(self, results: list[ImageScore]) -> None:
        """执行插件评分并叠加到最终分；结束后统一 cleanup，异常全部兜底。

        插件阶段在主进程单线程顺序执行（CV/VLM 的并行只发生在前面阶段），
        故插件实例不存在跨进程 pickle 问题。每个插件对所有图评分后 cleanup，
        任一插件的 evaluate / cleanup 异常都被捕获并记 warning，绝不向上抛。

        H-1：插件返回值是不可信输入，`_plugin_added` 返回 None（非有限 / 越界 /
        不可转换）时该次返回值不参与计分并告警，每个插件每批只告警一次。
        单图累计增量另受 `±PLUGIN_MAX_TOTAL_ADDED` 封顶，避免多个各自合规的
        插件叠加后把整批图推到 0/100 边界而丢失排序信息。
        """
        from flashgaze.plugins import discover_plugins

        plugin_dir = Path(self.config.plugin_dir) if self.config.plugin_dir else None
        plugins = discover_plugins(str(plugin_dir) if plugin_dir else None)
        if not plugins:
            return

        # 每张图上已累计的插件增量（跨插件累加），与 results 下标一一对应
        totals: list[float] = [0.0] * len(results)

        for plugin in plugins:
            warned = False  # 每插件每批只告警一次，避免 N 张图刷 N 条
            try:
                for i, s in enumerate(results):
                    try:
                        r = plugin.evaluate(s.path)
                    except Exception as e:  # noqa: BLE001 — 插件失控抛异常须兜底，避免单个坏插件中断整批评分
                        # 子类失控抛异常也兜底，避免单个坏插件中断整批评分
                        get_logger().warning(
                            "插件 %s.evaluate 抛异常，已跳过: %s",
                            getattr(plugin, "name", "?"),
                            e,
                        )
                        continue
                    if r is None:
                        continue
                    added = _plugin_added(r.score, r.weight)
                    if added is None:
                        # 违反契约的返回值一律不采信：钳制会把 1e9 变成 100，
                        # 配合大权重仍让全批图并列满分，比跳过更危险。
                        if not warned:
                            warned = True
                            get_logger().warning(
                                "插件 %s 返回值违反评分契约（score=%r, weight=%r；"
                                "要求有限值且 score∈[%s,%s]、|weight|≤%s），"
                                "已跳过该次加分，首个违规图片: %s",
                                getattr(plugin, "name", "?"),
                                r.score,
                                r.weight,
                                PLUGIN_SCORE_MIN,
                                PLUGIN_SCORE_MAX,
                                PLUGIN_WEIGHT_MAX,
                                s.file,
                            )
                        continue
                    # 先按累计上限截断本次增量，再叠加；最终分仍钳制到 0-100。
                    # 用 dataclasses.replace 生成新对象，不原地改
                    capped = max(
                        -PLUGIN_MAX_TOTAL_ADDED,
                        min(PLUGIN_MAX_TOTAL_ADDED, totals[i] + added),
                    )
                    delta = capped - totals[i]
                    totals[i] = capped
                    new_score = max(0.0, min(100.0, s.score + delta))
                    results[i] = replace(s, score=round(new_score, 2))
            finally:
                try:
                    plugin.cleanup()
                except Exception as e:  # noqa: BLE001 — 插件 cleanup 失败仅告警，绝不中断清理循环
                    get_logger().warning(
                        "插件 %s.cleanup 抛异常，已忽略: %s",
                        getattr(plugin, "name", "?"),
                        e,
                    )

    def _assemble(
        self,
        img_path: str,
        cv: CVResult,
        portrait: PortraitResult,
        vlm: VLMResult | None,
    ) -> ImageScore:
        """将 CV / 人像 / VLM 三方结果合并为 ImageScore。

        与原 score_one 后半段逻辑等价，仅拆分为独立方法以便在
        多进程结果组装阶段复用。CV 失败时返回与原版一致的错误占位。
        """
        if cv.error:
            return ImageScore(
                file=Path(img_path).name,
                path=img_path,
                sharpness=0.0,
                exposure=0.0,
                composition=None,
                vlm_adjustment=0.0,
                score=0.0,
                error=cv.error,
            )
        try:
            base = self._weighted_cv_score(cv)
        except ValueError as e:
            # 零权重等非法配置：转为带 error 的占位结果（与 cv.error 分支同构），
            # 综合分 0.0 且被 cleanup 的 `if not r.error` 过滤、不参与入选，不冒泡崩溃。
            return ImageScore(
                file=Path(img_path).name,
                path=img_path,
                sharpness=cv.sharpness,
                exposure=cv.exposure,
                composition=cv.composition,
                vlm_adjustment=0.0,
                score=0.0,
                noise=cv.noise,
                color=cv.color,
                face_count=portrait.face_count,
                face_sharpness=portrait.face_sharpness,
                portrait_bonus=portrait.portrait_bonus,
                error=str(e),
            )
        vlm_adj = 0.0
        vlm_reason = ""
        vlm_provider = ""
        vlm_applied = False
        vlm_error = ""
        if vlm is not None and vlm.ok:
            vlm_adj = vlm.adjustment
            vlm_reason = vlm.reason
            vlm_provider = vlm.provider
            vlm_applied = True
        elif vlm is not None:
            # VLM 调用失败：补偿归零，但失败原因必须落到 ImageScore 上，
            # 与「未启用 VLM」（vlm_error 保持空串）显式区分（评分口径可观测）。
            vlm_error = vlm.error or "vlm_failed"
        # NaN/Inf 兜底：任一分量异常时不得污染排序，回退 0.0 再 clamp（C-13）
        raw = base + vlm_adj + portrait.portrait_bonus
        final = 0.0 if not math.isfinite(raw) else max(0.0, min(100.0, raw))
        return ImageScore(
            file=Path(img_path).name,
            path=img_path,
            sharpness=cv.sharpness,
            exposure=cv.exposure,
            composition=cv.composition,
            vlm_adjustment=vlm_adj,
            score=round(final, 2),
            noise=cv.noise,
            color=cv.color,
            face_count=portrait.face_count,
            face_sharpness=portrait.face_sharpness,
            portrait_bonus=portrait.portrait_bonus,
            vlm_reason=vlm_reason,
            vlm_provider=vlm_provider,
            vlm_applied=vlm_applied,
            vlm_error=vlm_error,
        )

    def score_one(self, img_path: str) -> ImageScore:
        """单图评分：CV 主导 + VLM 微调 + 人像加分（带 CV 挂起看门狗）。

        单图同步执行（不开进程池），供 MCP score_single_image 与 WebUI 单图调用。
        批量评分请用 score_paths 以获得多进程加速。

        CV 评估置于独立守护线程并以 PER_IMAGE_TIMEOUT_SEC 施加看门狗：畸形
        TIFF/WebP 触发 OpenCV C 层死锁时不抛异常只永不返回，超时即放弃该图、
        标 error 返回，与批量路径（_score_serial / score_paths 的超时隔离）语义对齐，
        避免单图请求线程被永久阻塞、功能不可用。C 层死锁线程无法被 Python 杀掉，
        超时后随进程退出回收（daemon 线程）。
        """
        # 看门狗必须用裸 daemon 线程 + join(timeout)（同 _score_serial），禁用
        # ThreadPoolExecutor + fut.result(timeout)：超时抛 TimeoutError 后 with 块
        # 退出触发 shutdown(wait=True)，对卡死在 OpenCV C 层的线程无限 join，
        # except TimeoutError 永不可达，看门狗失效。
        err_holder: dict[str, Any] = {}
        state: dict[str, Any] = {}

        def _run() -> None:
            try:
                state["v"] = self.cv_engine.evaluate_with_color(img_path)
            except Exception as ex:  # noqa: BLE001
                err_holder["ex"] = ex

        watcher = threading.Thread(target=_run, daemon=True)
        watcher.start()
        watcher.join(timeout=PER_IMAGE_TIMEOUT_SEC)
        if watcher.is_alive():
            # 挂起型 worker（C 层死锁线程无法被 Python 杀掉）：放弃该图标 error
            get_logger().warning("单图CV超时(>%ds),标error: %s", PER_IMAGE_TIMEOUT_SEC, img_path)
            # MED-1: 挂起线程仍持有 self.cv_engine；重建实例让后续调用拿全新引擎，
            # 挂起线程独占旧实例，消除对同一引擎的并发调用（见 _rebuild_cv_engine）。
            self._rebuild_cv_engine()
            cv = CVResult(
                sharpness=0.0,
                exposure=0.0,
                error=f"单图CV超时(>{PER_IMAGE_TIMEOUT_SEC}s)",
            )
            color = None
        elif "ex" in err_holder:
            raise err_holder["ex"]
        else:
            cv, color = state["v"]
        portrait = (
            self.portrait_engine.evaluate(img_path, preloaded_color=color)
            if not cv.error
            else PortraitResult(face_count=0)
        )
        vlm: VLMResult | None = None
        if self.vlm_client is not None and not cv.error:
            vlm = self.vlm_client.judge(img_path, cv)
        return self._assemble(img_path, cv, portrait, vlm)

    def _rebuild_cv_engine(self) -> None:
        """看门狗超时后重建实例级 CVEngine（MED-1）。

        超时被放弃的挂起线程仍持有并可能永远占用旧实例；继续复用会让下一张图
        与挂起线程并发调用同一引擎的 OpenCV C 层（QualityBRISQUE.compute 的线程
        安全性未经验证，hybrid_scorer 模块单例注释同此约束）。重建后挂起线程独占
        旧实例，主流程使用全新实例，消除并发。仅单图超时路径触发，正常调用零开销。

        BrisqueIntegrityError（模型哈希不符的供应链信号）穿透响亮失败，绝不降级；
        其余重建失败记 warning 并保留旧实例——退化为修复前的复用行为，不中断调用。
        """
        try:
            self.cv_engine = CVEngine(
                enable_composition=self.config.enable_composition,
                enable_noise=self.config.enable_noise,
                enable_color=self.config.enable_color,
                downscale=not self.config.no_downscale,
            )
        except BrisqueIntegrityError:
            raise
        except Exception as e:  # noqa: BLE001 — 重建失败保留旧实例，不中断评分
            get_logger().warning("CVEngine 重建失败，保留旧实例（并发风险退回原行为）: %s", e)

    def _weighted_cv_score(self, cv: CVResult) -> float:
        """按权重合并 CV 各维度分数（权重归一化，避免启用新维度后分数偏低）。

        支持 sharpness/exposure/composition/noise/color 五个维度，
        仅当对应 CVResult 字段非 None 时参与计算。
        """
        w = self.config.weights
        # 收集 (分数, 权重) 对，仅计入有值的维度
        pairs: list[tuple[float, float]] = [
            (cv.sharpness, float(w.get("sharpness", 0.5))),
            (cv.exposure, float(w.get("exposure", 0.5))),
        ]
        if cv.composition is not None:
            pairs.append((cv.composition, float(w.get("composition", 0.0))))
        if cv.noise is not None:
            pairs.append((cv.noise, float(w.get("noise", 0.0))))
        if cv.color is not None:
            pairs.append((cv.color, float(w.get("color", 0.0))))
        total_w = sum(pw for _, pw in pairs)
        if total_w <= 0:
            # FIX(#C-15): 零权重会让全部评分被静默归零、失去意义，改为响亮失败。
            # 正常权重（sharpness/exposure 必填且默认 0.5）下不会触发；
            # 仅当直接构造的 Config 将全部参与维度权重置 0 时命中。
            raise ValueError("权重总和为 0（sharpness/exposure 不可同时为 0），无法计算综合分")
        return sum(val * pw for val, pw in pairs) / total_w

    def _mark_selected(self, results: list[ImageScore]) -> None:
        """标记入选图。threshold 优先于 top。"""
        valid = [r for r in results if not r.error]
        if self.config.threshold is not None:
            for r in valid:
                r.selected = r.score >= self.config.threshold
        else:
            # top 必须 >=1，禁止 0/负数把整批标为未入选（清理模式会据此删光）
            if self.config.top is None or self.config.top < 1:
                top_n = max(DEFAULT_TOP, 1)  # 退回默认 30，绝不清空
            else:
                top_n = min(self.config.top, len(valid))
            if top_n <= 0:
                return
            for r in valid[:top_n]:
                r.selected = True

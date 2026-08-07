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

from dataclasses import replace
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path
from typing import Callable, Optional

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.deduplicator import Deduplicator
from flashgaze.core.portrait_engine import PortraitEngine
from flashgaze.core.vlm_client import VLMClient
from flashgaze.models.schemas import (
    Config,
    CVResult,
    ImageScore,
    PortraitResult,
    VLMResult,
)
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger


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

    CV 失败时跳过人像评分与 PHash 编码，与原 score_one 的早返回语义一致，
    避免对损坏图做无用的二次解码。
    """
    cv_engine = CVEngine(
        enable_composition=enable_composition,
        enable_noise=enable_noise,
        enable_color=enable_color,
        downscale=downscale,
    )
    portrait_engine = PortraitEngine(enable=enable_portrait)
    cv = cv_engine.evaluate(img_path)
    if cv.error:
        return img_path, cv, PortraitResult(face_count=0), None
    portrait = portrait_engine.evaluate(img_path)
    # 复用子进程已读图：在此时计算 PHash 编码，避免主进程 Deduplicator 重复读盘。
    # imagededup 不可用 / 编码失败时不阻塞主流程，phash_encoding 留 None。
    phash_encoding: object = None
    if enable_dedup:
        try:
            from imagededup.methods import PHash

            phash_encoding = PHash().encode_image(img_path)
        except Exception:
            phash_encoding = None
    return img_path, cv, portrait, phash_encoding


class HybridScorer:
    """合并 CV 客观分与 VLM 场景补偿。"""

    def __init__(
        self,
        cv_engine: CVEngine,
        vlm_client: Optional[VLMClient],
        config: Config,
    ):
        self.cv_engine = cv_engine
        self.vlm_client = vlm_client
        self.config = config
        # 装配可选引擎（依赖缺失或 enable=False 时降级为空结果，不影响主流程）
        self.portrait_engine = PortraitEngine(enable=config.enable_portrait)
        self.deduplicator = Deduplicator(threshold=config.dedup_threshold)

    def score_batch(self, directory: str) -> list[ImageScore]:
        """并发评分目录下所有图片，按综合分降序返回。"""
        return self.score_paths(list(iter_images(directory)))

    def score_paths(
        self,
        image_paths: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
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

        total = len(image_paths)
        done = 0
        cv_results: dict[str, tuple[CVResult, PortraitResult]] = {}
        vlm_results: dict[str, VLMResult] = {}
        # 子进程预计算的 PHash 编码（仅 config.dedup=True 时填充），
        # 透传给 Deduplicator 避免主进程重复读盘。
        phash_encodings: dict[str, object] = {}

        # 阶段 1：CV + 人像评分（多进程，CPU 密集型）
        # 纯 CV 模式下 progress 在此阶段实时反馈；混合模式下此阶段静默
        report_progress_in_phase1 = self.vlm_client is None
        logger = get_logger()
        try:
            with ProcessPoolExecutor(max_workers=self.config.workers) as pool:
                futures = {
                    pool.submit(
                        _evaluate_cv_and_portrait,
                        p,
                        self.config.enable_composition,
                        self.config.enable_noise,
                        self.config.enable_color,
                        self.config.enable_portrait,
                        not self.config.no_downscale,
                        self.config.dedup,
                    ): p
                    for p in image_paths
                }
                for fut in as_completed(futures):
                    img_path = futures[fut]
                    try:
                        _, cv, portrait, phash_enc = fut.result()
                    except Exception as e:
                        # 子进程异常兜底：构造 error 占位，避免中断批量评分
                        # 与 _evaluate_cv_and_portrait 内 CV 失败早返回语义一致，
                        # 下游 vlm_targets 过滤与 _assemble 的 cv.error 分支均天然兼容
                        cv = CVResult(sharpness=0.0, exposure=0.0, error=f"子进程异常: {e}")
                        portrait = PortraitResult(face_count=0)
                        phash_enc = None
                    cv_results[img_path] = (cv, portrait)
                    if phash_enc is not None:
                        phash_encodings[img_path] = phash_enc
                    if report_progress_in_phase1:
                        done += 1
                        if progress_callback is not None:
                            progress_callback(done, total)
        except (OSError, RuntimeError, ValueError) as e:
            # 受限环境（Docker/CI 等）多进程不可用，回退到当前进程串行执行
            logger.warning(
                "ProcessPoolExecutor 创建失败（%s），回退到串行模式", e,
            )
            # 清理可能的部分结果，串行重跑保证一致性
            cv_results.clear()
            phash_encodings.clear()
            done = 0
            for p in image_paths:
                try:
                    _, cv, portrait, phash_enc = _evaluate_cv_and_portrait(
                        p,
                        self.config.enable_composition,
                        self.config.enable_noise,
                        self.config.enable_color,
                        self.config.enable_portrait,
                        not self.config.no_downscale,
                        self.config.dedup,
                    )
                except Exception as ex:
                    # 串行模式异常兜底：语义与多进程分支一致
                    cv = CVResult(sharpness=0.0, exposure=0.0, error=f"评分异常: {ex}")
                    portrait = PortraitResult(face_count=0)
                    phash_enc = None
                cv_results[p] = (cv, portrait)
                if phash_enc is not None:
                    phash_encodings[p] = phash_enc
                if report_progress_in_phase1:
                    done += 1
                    if progress_callback is not None:
                        progress_callback(done, total)

        # 阶段 2：VLM 评分（多线程，IO 密集型）
        # 仅 vlm_client is not None 时执行；CV 失败的图跳过 VLM
        if self.vlm_client is not None:
            vlm_targets = [p for p in image_paths if not cv_results[p][0].error]
            errored_count = total - len(vlm_targets)

            if vlm_targets:
                with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
                    futures = {
                        pool.submit(
                            self.vlm_client.judge, p, cv_results[p][0]
                        ): p
                        for p in vlm_targets
                    }
                    for fut in as_completed(futures):
                        img_path = futures[fut]
                        try:
                            vlm_results[img_path] = fut.result()
                        except Exception as e:
                            # VLM 异常兜底：与 judge 内部失败语义一致
                            vlm_results[img_path] = VLMResult(
                                0.0, "VLM 异常", ok=False, error=str(e),
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

        # 按 score 降序，同分按文件名升序，保证排序稳定可复现
        results.sort(key=lambda s: (-s.score, s.file))
        self._mark_selected(results)
        # 去重后处理：标记非最高分图为 selected=False, deduped=True
        # 透传子进程预计算的 phash_encodings，避免主进程重复读盘
        if self.config.dedup:
            self.deduplicator.mark_duplicates(results, encodings=phash_encodings)

        # 插件评分阶段（M4）：去重之后、return 之前，仅当 enable_plugins
        if self.config.enable_plugins:
            self._run_plugins(results)

        return results

    def _run_plugins(self, results: list[ImageScore]) -> None:
        """执行插件评分并叠加到最终分；结束后统一 cleanup，异常全部兜底。

        插件阶段在主进程单线程顺序执行（CV/VLM 的并行只发生在前面阶段），
        故插件实例不存在跨进程 pickle 问题。每个插件对所有图评分后 cleanup，
        任一插件的 evaluate / cleanup 异常都被捕获并记 warning，绝不向上抛。
        """
        from flashgaze.plugins import discover_plugins

        plugin_dir = Path(self.config.plugin_dir) if self.config.plugin_dir else None
        plugins = discover_plugins(plugin_dir)
        if not plugins:
            return

        for plugin in plugins:
            try:
                for i, s in enumerate(results):
                    try:
                        r = plugin.evaluate(s.path)
                    except Exception as e:
                        # 子类失控抛异常也兜底，避免单个坏插件中断整批评分
                        get_logger().warning(
                            "插件 %s.evaluate 抛异常，已跳过: %s",
                            getattr(plugin, "name", "?"), e,
                        )
                        continue
                    if r is None:
                        continue
                    try:
                        added = float(r.score) * float(r.weight)
                    except (TypeError, ValueError):
                        continue
                    # 按权重叠加到最终分，钳制到 0-100；
                    # 用 dataclasses.replace 生成新对象，不原地改
                    new_score = max(0.0, min(100.0, s.score + added))
                    results[i] = replace(s, score=round(new_score, 2))
            finally:
                try:
                    plugin.cleanup()
                except Exception as e:
                    get_logger().warning(
                        "插件 %s.cleanup 抛异常，已忽略: %s",
                        getattr(plugin, "name", "?"), e,
                    )

    def _assemble(
        self,
        img_path: str,
        cv: CVResult,
        portrait: PortraitResult,
        vlm: Optional[VLMResult],
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
        base = self._weighted_cv_score(cv)
        vlm_adj = 0.0
        vlm_reason = ""
        vlm_provider = ""
        if vlm is not None and vlm.ok:
            vlm_adj = vlm.adjustment
            vlm_reason = vlm.reason
            vlm_provider = vlm.provider
        final = max(0.0, min(100.0, base + vlm_adj + portrait.portrait_bonus))
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
        )

    def score_one(self, img_path: str) -> ImageScore:
        """单图评分：CV 主导 + VLM 微调 + 人像加分。

        单图同步执行（不开进程池），供 MCP score_single_image 调用。
        批量评分请用 score_paths 以获得多进程加速。
        """
        cv = self.cv_engine.evaluate(img_path)
        portrait = (
            self.portrait_engine.evaluate(img_path)
            if not cv.error
            else PortraitResult(face_count=0)
        )
        vlm: Optional[VLMResult] = None
        if self.vlm_client is not None and not cv.error:
            vlm = self.vlm_client.judge(img_path, cv)
        return self._assemble(img_path, cv, portrait, vlm)

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
            return 0.0
        return sum(val * pw for val, pw in pairs) / total_w

    def _mark_selected(self, results: list[ImageScore]) -> None:
        """标记入选图。threshold 优先于 top。"""
        valid = [r for r in results if not r.error]
        if self.config.threshold is not None:
            for r in valid:
                r.selected = r.score >= self.config.threshold
        else:
            top_n = max(self.config.top, 0)  # 防御负数
            top_n = min(top_n, len(valid))
            if top_n <= 0:
                return
            for r in valid[:top_n]:
                r.selected = True

"""HybridScorer：合并 CV 客观分与 VLM 场景补偿。

CV 主导，VLM 仅作 ±max_adjustment 微调。ThreadPoolExecutor 并发处理批量图片。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.vlm_client import VLMClient
from flashgaze.models.schemas import Config, CVResult, ImageScore
from flashgaze.utils.image_io import iter_images


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

    def score_batch(self, directory: str) -> list[ImageScore]:
        """并发评分目录下所有图片，按综合分降序返回。"""
        return self.score_paths(list(iter_images(directory)))

    def score_paths(
        self,
        image_paths: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> list[ImageScore]:
        """对给定路径列表评分，按综合分降序返回。

        供 MCP 上传模式与 CLI 缓存复用，避免目录双重遍历。
        progress_callback(done, total) 在每张图评分完成后被调用，用于进度反馈。
        """
        if not image_paths:
            return []
        results: list[ImageScore] = []
        total = len(image_paths)
        done = 0
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = {pool.submit(self.score_one, p): p for p in image_paths}
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if progress_callback is not None:
                    progress_callback(done, total)
        # 按 score 降序，同分按文件名升序，保证排序稳定可复现
        results.sort(key=lambda s: (-s.score, s.file))
        self._mark_selected(results)
        return results

    def score_one(self, img_path: str) -> ImageScore:
        """单图评分：CV 主导 + VLM 微调。"""
        cv = self.cv_engine.evaluate(img_path)
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
        # vlm_client 仅在 not no_vlm 时被构造（见 entry.py 与 mcp_server._make_vlm_client），
        # 故 self.vlm_client is not None 已隐含 not no_vlm
        if self.vlm_client is not None:
            vlm = self.vlm_client.judge(img_path, cv)
            vlm_adj = vlm.adjustment if vlm.ok else 0.0
        final = max(0.0, min(100.0, base + vlm_adj))
        return ImageScore(
            file=Path(img_path).name,
            path=img_path,
            sharpness=cv.sharpness,
            exposure=cv.exposure,
            composition=cv.composition,
            vlm_adjustment=vlm_adj,
            score=round(final, 2),
        )

    def _weighted_cv_score(self, cv: CVResult) -> float:
        """按权重合并 CV 各维度分数（权重归一化，避免启用 composition 后分数偏低）。"""
        w = self.config.weights
        s_w = w.get("sharpness", 0.5)
        e_w = w.get("exposure", 0.5)
        c_w = w.get("composition", 0.0) if cv.composition is not None else 0.0
        total = s_w + e_w + c_w
        if total <= 0:
            return 0.0
        c_val = cv.composition if cv.composition is not None else 0.0
        return (cv.sharpness * s_w + cv.exposure * e_w + c_val * c_w) / total

    def _mark_selected(self, results: list[ImageScore]) -> None:
        """标记入选图。threshold 优先于 top。"""
        valid = [r for r in results if not r.error]
        if self.config.threshold is not None:
            for r in valid:
                r.selected = r.score >= self.config.threshold
        else:
            top_n = min(self.config.top, len(valid))
            for r in valid[:top_n]:
                r.selected = True

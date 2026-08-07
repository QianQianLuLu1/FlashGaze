"""Deduplicator：基于 PHash 的图片去重。

使用 imagededup 库的 PHash 算法识别感知相似图片，保留每组最高分图。
依赖缺失时所有方法返回空结果，不阻塞主流程。
"""

from __future__ import annotations

import logging
from typing import Optional

from flashgaze.models.schemas import ImageScore

logger = logging.getLogger(__name__)

# 模块级探测 imagededup 依赖
try:
    from imagededup.methods import PHash  # type: ignore
    _IMAGEDEDUP_AVAILABLE = True
except ImportError:
    PHash = None  # type: ignore
    _IMAGEDEDUP_AVAILABLE = False


class Deduplicator:
    """基于 PHash 汉明距离的图片去重器。

    依赖 imagededup 库。依赖缺失时 available=False，所有方法返回空结果。
    """

    def __init__(self, threshold: Optional[int] = None) -> None:
        # threshold=None 时使用默认值 8（由调用方传入解析后的值）
        self.threshold = threshold if threshold is not None else 8
        self.available = _IMAGEDEDUP_AVAILABLE
        self._phash = PHash() if _IMAGEDEDUP_AVAILABLE else None

    def find_duplicates(
        self,
        scored: list[ImageScore],
        encodings: dict[str, object] | None = None,
    ) -> dict[str, list[str]]:
        """识别相似图分组。

        返回 keep_map：{保留图路径: [被去重图路径列表]}
        每组保留最高分图（同分按文件名升序），其余为被去重图。

        encodings 由调用方预计算（如 HybridScorer 在子进程中已计算），
        传入时直接复用，跳过自行 encode_image 的循环以避免重复读盘；
        未传入（None）时回退到原有自行编码逻辑，保持向后兼容。

        依赖缺失、有效图不足 2 张、或编码失败时返回空 dict。
        """
        if not self.available or len(scored) < 2:
            return {}
        # 仅对有效评分图（无 error）去重，损坏图不参与
        valid = [s for s in scored if s.error is None]
        if len(valid) < 2:
            return {}
        path_to_score = {s.path: s for s in valid}
        # 计算 PHash 编码：优先复用调用方预计算的编码，避免重复读盘
        if encodings is None:
            # 向后兼容：调用方未预计算，此处自行读盘
            encoding_map: dict[str, object] = {}
            for s in valid:
                try:
                    encoding_map[s.path] = self._phash.encode_image(s.path)
                except Exception as e:
                    logger.debug("PHash 编码失败 %s: %s", s.path, e)
        else:
            # 仅保留有效图且非 None 的编码，过滤损坏图与未命中项
            encoding_map = {
                p: enc for p, enc in encodings.items()
                if p in path_to_score and enc is not None
            }
        if len(encoding_map) < 2:
            return {}
        # imagededup 返回 {path: [相似图路径列表]}
        try:
            dup_map: dict[str, list[str]] = self._phash.find_duplicates(
                encoding_map=encoding_map,
                max_distance_threshold=self.threshold,
            )
        except Exception as e:
            logger.debug("PHash find_duplicates 失败: %s", e)
            return {}
        return self._build_keep_map(dup_map, path_to_score)

    def mark_duplicates(
        self,
        scored: list[ImageScore],
        encodings: dict[str, object] | None = None,
    ) -> int:
        """原地标记被去重图，返回被标记的数量。

        被去重图设置 selected=False, deduped=True。
        保留图（每组最高分）保持原状。

        encodings 由调用方预计算，透传给 find_duplicates 避免重复读盘。
        """
        keep_map = self.find_duplicates(scored, encodings=encodings)
        if not keep_map:
            return 0
        # 收集所有被去重图路径
        deduped_paths: set[str] = set()
        for dup_list in keep_map.values():
            deduped_paths.update(dup_list)
        # 原地标记（ImageScore 非 frozen，可修改）
        count = 0
        for s in scored:
            if s.path in deduped_paths:
                s.selected = False
                s.deduped = True
                count += 1
        return count

    def _build_keep_map(
        self,
        dup_map: dict[str, list[str]],
        path_to_score: dict[str, ImageScore],
    ) -> dict[str, list[str]]:
        """将 imagededup 的双向相似关系转换为 keep_map。

        imagededup 返回 {A: [B, C]} 表示 A 与 B、C 相似，但 B 的 entry 可能不含 A。
        需要先用并查集合并相似组，再每组选最高分图作为保留图。

        返回 {保留图路径: [被去重图路径列表]}。
        """
        # 并查集合并相似组
        parent: dict[str, str] = {p: p for p in path_to_score}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for src, dups in dup_map.items():
            if src not in parent:
                continue
            for d in dups:
                if d in parent:
                    union(src, d)

        # 按根分组
        groups: dict[str, list[str]] = {}
        for p in path_to_score:
            root = find(p)
            groups.setdefault(root, []).append(p)

        # 每组选最高分图（同分按文件名升序，与 score_paths 排序一致）
        keep_map: dict[str, list[str]] = {}
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda p: (-path_to_score[p].score, path_to_score[p].file))
            keeper = members[0]
            deduped = members[1:]
            keep_map[keeper] = deduped
        return keep_map

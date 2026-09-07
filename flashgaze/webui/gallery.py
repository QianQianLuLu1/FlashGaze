"""高分图预览组件辅助：把 ScoringResult 转成 Gradio Gallery 所需格式。"""

from __future__ import annotations

from flashgaze.models.schemas import ImageScore
from flashgaze.webui.runner import ScoringResult


def build_gallery_items(
    result: ScoringResult | None,
    *,
    only_selected: bool = False,
    min_score: float | None = None,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """把评分结果转成 (path, caption) 列表，供 gr.Gallery 直接消费。

    - only_selected: 仅展示入选图
    - min_score: 仅展示分数 >= 该值的图
    - limit: 最多展示多少张（已按分数降序，截取前 N 张）
    """
    if not result or not result.scored:
        return []

    items: list[tuple[str, str]] = []
    for s in result.scored:
        if s.error:
            continue
        if only_selected and not s.selected:
            continue
        if min_score is not None and s.score < min_score:
            continue
        items.append((s.path, _caption(s)))
        if limit and len(items) >= limit:
            break
    return items


def _caption(s: ImageScore) -> str:
    """单图说明文字：分数 + 入选标记 + VLM 理由。"""
    parts = [f"{s.file}", f"分数 {s.score:.2f}"]
    if s.selected:
        parts.append("★入选")
    if s.vlm_reason:
        parts.append(s.vlm_reason)
    if s.deduped:
        parts.append("去重")
    return " | ".join(parts)


def filter_rows(
    result: ScoringResult | None,
    *,
    only_selected: bool = False,
    min_score: float | None = None,
    keyword: str = "",
) -> list[list[object]]:
    """按条件筛选表格行。返回与 ScoringResult.to_rows 同结构的子集。"""
    if not result:
        return []
    rows: list[list[object]] = []
    kw = keyword.strip().lower() if keyword else ""
    for s in result.scored:
        if only_selected and not s.selected:
            continue
        if min_score is not None and s.score < min_score:
            continue
        if kw and kw not in s.file.lower() and kw not in (s.vlm_reason or "").lower():
            continue
        rows.append(_row_for(s))
    return rows


def _row_for(s: ImageScore) -> list[object]:
    """展示行，复用 ImageScore.to_display_row()（C-09 单一来源，
    与 ScoringResult.to_rows 同结构，不再各自硬编码取值）。"""
    return s.to_display_row()

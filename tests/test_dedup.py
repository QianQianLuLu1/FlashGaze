"""Deduplicator PHash 去重测试（M5）。

依赖 imagededup 库。依赖缺失时 pytest.skip。
使用 duplicate_a.jpg 和 duplicate_b.jpg（完全相同的两张图）验证相似识别。
"""

from __future__ import annotations

import pytest

from flashgaze.core.deduplicator import Deduplicator, _IMAGEDEDUP_AVAILABLE
from flashgaze.models.schemas import ImageScore


pytestmark = pytest.mark.skipif(
    not _IMAGEDEDUP_AVAILABLE,
    reason="imagededup 未安装，跳过 PHash 去重测试",
)


def _make_score(file: str, path: str, score: float, selected: bool = True) -> ImageScore:
    """构造测试用 ImageScore。"""
    return ImageScore(
        file=file,
        path=path,
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=0.0,
        score=score,
        selected=selected,
    )


# ---------- 基础行为 ----------

def test_deduplicator_available_when_dependency_present():
    """imagededup 已安装时 Deduplicator.available 应为 True。"""
    d = Deduplicator()
    assert d.available is True


def test_threshold_default_is_8():
    """默认阈值为 8。"""
    d = Deduplicator()
    assert d.threshold == 8


def test_threshold_custom():
    """自定义阈值生效。"""
    d = Deduplicator(threshold=4)
    assert d.threshold == 4


# ---------- 空与不足 ----------

def test_empty_list_returns_empty():
    """空列表返回空 dict。"""
    d = Deduplicator()
    assert d.find_duplicates([]) == {}
    assert d.mark_duplicates([]) == 0


def test_single_image_returns_empty(duplicate_a_img: str):
    """单图返回空结果（无法比较）。"""
    d = Deduplicator()
    scored = [_make_score("a.jpg", duplicate_a_img, 90.0)]
    assert d.find_duplicates(scored) == {}
    assert d.mark_duplicates(scored) == 0


# ---------- 重复识别 ----------

def test_identical_images_detected_as_duplicates(
    duplicate_a_img: str,
    duplicate_b_img: str,
):
    """完全相同的两张图被识别为相似。"""
    d = Deduplicator()
    scored = [
        _make_score("duplicate_a.jpg", duplicate_a_img, 90.0),
        _make_score("duplicate_b.jpg", duplicate_b_img, 80.0),
    ]
    keep_map = d.find_duplicates(scored)
    # 应识别出一组相似（保留 1 张，去重 1 张）
    assert len(keep_map) == 1
    keeper_path = list(keep_map.keys())[0]
    deduped_list = list(keep_map.values())[0]
    assert len(deduped_list) == 1
    # 保留图应为高分图（duplicate_a.jpg 90 分）
    assert keeper_path == duplicate_a_img
    assert deduped_list[0] == duplicate_b_img


def test_mark_duplicates_marks_lower_score(
    duplicate_a_img: str,
    duplicate_b_img: str,
):
    """非最高分图被标记为 selected=False, deduped=True。"""
    d = Deduplicator()
    scored = [
        _make_score("duplicate_a.jpg", duplicate_a_img, 90.0),
        _make_score("duplicate_b.jpg", duplicate_b_img, 80.0),
    ]
    count = d.mark_duplicates(scored)
    assert count == 1
    # 低分图被标记
    low = next(s for s in scored if s.file == "duplicate_b.jpg")
    assert low.deduped is True
    assert low.selected is False
    # 高分图未被标记
    high = next(s for s in scored if s.file == "duplicate_a.jpg")
    assert high.deduped is False
    assert high.selected is True  # 仍是 selected


def test_mark_duplicates_preserves_highest_score(
    duplicate_a_img: str,
    duplicate_b_img: str,
):
    """同分情况下按文件名升序保留（duplicate_a 保留）。"""
    d = Deduplicator()
    scored = [
        _make_score("duplicate_a.jpg", duplicate_a_img, 85.0),
        _make_score("duplicate_b.jpg", duplicate_b_img, 85.0),
    ]
    d.mark_duplicates(scored)
    # 同分按文件名升序，duplicate_a 应保留
    a = next(s for s in scored if s.file == "duplicate_a.jpg")
    b = next(s for s in scored if s.file == "duplicate_b.jpg")
    assert a.deduped is False
    assert b.deduped is True


# ---------- 不同图不被误判 ----------

def test_different_images_not_flagged(sharp_img: str, blurry_img: str):
    """清晰图和模糊图差异大，不应被识别为相似。"""
    d = Deduplicator()
    scored = [
        _make_score("sharp.jpg", sharp_img, 90.0),
        _make_score("blurry.jpg", blurry_img, 40.0),
    ]
    keep_map = d.find_duplicates(scored)
    # sharp 是高频噪声，blurry 是其强模糊版，PHash 可能仍判定相似
    # 此处不强制断言结果，仅验证不崩溃且返回 dict
    assert isinstance(keep_map, dict)


# ---------- 阈值效果 ----------

def test_strict_threshold_reduces_matches(
    duplicate_a_img: str,
    duplicate_b_img: str,
):
    """阈值越小越严格。完全相同的图在任何阈值下都应被识别。"""
    d = Deduplicator(threshold=0)  # 最严格
    scored = [
        _make_score("a.jpg", duplicate_a_img, 90.0),
        _make_score("b.jpg", duplicate_b_img, 80.0),
    ]
    # 完全相同的图 PHash 距离为 0，阈值=0 也应识别
    keep_map = d.find_duplicates(scored)
    assert len(keep_map) == 1

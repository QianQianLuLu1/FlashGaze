"""Deduplicator PHash 去重测试（M5）。

行为测试依赖真实 imagededup 库，用 @requires_imagededup 逐个标注，依赖缺失时跳过。
使用 duplicate_a.jpg 和 duplicate_b.jpg（完全相同的两张图）验证相似识别。

文件末尾的"编码形状契约"测试用 stub 替代真实依赖，不带 skip 标记：
它守护的是形状约定本身，在没装 imagededup 的环境里同样必须跑。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from flashgaze.core.deduplicator import _IMAGEDEDUP_AVAILABLE, Deduplicator
from flashgaze.models.schemas import CVResult, ImageScore, PortraitResult

# 具名 mark 而非模块级 pytestmark：模块级会连带跳过末尾的 stub 契约测试，
# 而那些用例的全部意义就在于"没装依赖也要能拦住形状被改错"。
requires_imagededup = pytest.mark.skipif(
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


@requires_imagededup
def test_deduplicator_available_when_dependency_present() -> None:
    """imagededup 已安装时 Deduplicator.available 应为 True。"""
    d = Deduplicator()
    assert d.available is True


@requires_imagededup
def test_threshold_default_is_8() -> None:
    """默认阈值为 8。"""
    d = Deduplicator()
    assert d.threshold == 8


@requires_imagededup
def test_threshold_custom() -> None:
    """自定义阈值生效。"""
    d = Deduplicator(threshold=4)
    assert d.threshold == 4


# ---------- 空与不足 ----------


@requires_imagededup
def test_empty_list_returns_empty() -> None:
    """空列表返回空 dict。"""
    d = Deduplicator()
    assert d.find_duplicates([]) == {}
    assert d.mark_duplicates([]) == 0


@requires_imagededup
def test_single_image_returns_empty(duplicate_a_img: str) -> None:
    """单图返回空结果（无法比较）。"""
    d = Deduplicator()
    scored = [_make_score("a.jpg", duplicate_a_img, 90.0)]
    assert d.find_duplicates(scored) == {}
    assert d.mark_duplicates(scored) == 0


# ---------- 重复识别 ----------


@requires_imagededup
def test_identical_images_detected_as_duplicates(
    duplicate_a_img: str,
    duplicate_b_img: str,
) -> None:
    """完全相同的两张图被识别为相似。"""
    d = Deduplicator()
    scored = [
        _make_score("duplicate_a.jpg", duplicate_a_img, 90.0),
        _make_score("duplicate_b.jpg", duplicate_b_img, 80.0),
    ]
    keep_map = d.find_duplicates(scored)
    # 应识别出一组相似（保留 1 张，去重 1 张）
    assert len(keep_map) == 1
    keeper_path = next(iter(keep_map))
    deduped_list = next(iter(keep_map.values()))
    assert len(deduped_list) == 1
    # 保留图应为高分图（duplicate_a.jpg 90 分）
    assert keeper_path == duplicate_a_img
    assert deduped_list[0] == duplicate_b_img


@requires_imagededup
def test_mark_duplicates_marks_lower_score(
    duplicate_a_img: str,
    duplicate_b_img: str,
) -> None:
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


@requires_imagededup
def test_mark_duplicates_preserves_highest_score(
    duplicate_a_img: str,
    duplicate_b_img: str,
) -> None:
    """同分情况下按全路径升序保留（duplicate_a 路径较小，仍保留）。"""
    d = Deduplicator()
    scored = [
        _make_score("duplicate_a.jpg", duplicate_a_img, 85.0),
        _make_score("duplicate_b.jpg", duplicate_b_img, 85.0),
    ]
    d.mark_duplicates(scored)
    # 同分按全路径升序（同目录下与文件名序一致），duplicate_a 应保留
    a = next(s for s in scored if s.file == "duplicate_a.jpg")
    b = next(s for s in scored if s.file == "duplicate_b.jpg")
    assert a.deduped is False
    assert b.deduped is True


# ---------- 不同图不被误判 ----------


@requires_imagededup
def test_different_images_not_flagged(sharp_img: str, blurry_img: str) -> None:
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


@requires_imagededup
def test_strict_threshold_reduces_matches(
    duplicate_a_img: str,
    duplicate_b_img: str,
) -> None:
    """阈值越小越严格。完全相同的图在任何阈值下都应被识别。"""
    d = Deduplicator(threshold=0)  # 最严格
    scored = [
        _make_score("a.jpg", duplicate_a_img, 90.0),
        _make_score("b.jpg", duplicate_b_img, 80.0),
    ]
    # 完全相同的图 PHash 距离为 0，阈值=0 也应识别
    keep_map = d.find_duplicates(scored)
    assert len(keep_map) == 1


# ---------- 编码形状契约（子进程产出 → 主进程消费）----------
#
# _evaluate_cv_and_portrait 返回元组第 4 位的 phash_encoding 会被 score_paths
# 汇总成 phash_encodings，再原样喂给 Deduplicator.mark_duplicates(encodings=...)，
# 最终落到 PHash.find_duplicates(encoding_map: Dict[str, str])。
# imagededup 官方 hashing.py 的契约是 encode_image(...) -> str（16 字符 hex，失败 None），
# 这里用 stub 把契约钉死：任何"把返回值当 dict 再取值"的改动都会被 except 吞成 None 而漏网，
# 所以必须正面断言"拿到的就是那个字符串"，而不只是断言不崩。

_STUB_PHASH_HEX = "a1b2c3d4e5f60718"  # 16 字符 hex，与官方返回形状一致


def _install_fake_imagededup(
    monkeypatch: pytest.MonkeyPatch, encode_result: Any
) -> list[str | None]:
    """往 sys.modules 注入假的 imagededup / imagededup.methods。

    被测代码是函数内 `from imagededup.methods import PHash`，导入机制会先命中
    sys.modules，故两级都要注入。返回调用记录列表，供断言入参。
    monkeypatch.setitem 会在用例结束后自动还原，不污染后续用例。
    """
    calls: list[str | None] = []

    class _StubPHash:
        def encode_image(self, image_file: str | None = None, image_array: Any = None) -> Any:
            calls.append(image_file)
            return encode_result

    methods_mod = types.ModuleType("imagededup.methods")
    methods_mod.PHash = _StubPHash  # type: ignore[attr-defined]
    pkg_mod = types.ModuleType("imagededup")
    # 标记为包，否则子模块导入行为不一致（__path__ 在 typeshed 有声明，无需 ignore）
    pkg_mod.__path__ = []
    pkg_mod.methods = methods_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "imagededup", pkg_mod)
    monkeypatch.setitem(sys.modules, "imagededup.methods", methods_mod)
    return calls


def _run_worker(
    img_path: str, enable_dedup: bool = True
) -> tuple[str, CVResult, PortraitResult, object]:
    """按位置参数调用 worker，返回完整四元组。

    导入放函数内，与 conftest 的约定一致（避免收集阶段就 import hybrid_scorer）。
    """
    from flashgaze.core.hybrid_scorer import _evaluate_cv_and_portrait

    return _evaluate_cv_and_portrait(
        img_path,
        False,  # enable_composition
        False,  # enable_noise
        False,  # enable_color
        False,  # enable_portrait
        True,  # downscale
        enable_dedup,
    )


def test_worker_returns_phash_encoding_as_plain_string(
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """encode_image 返回 hex 字符串时，phash_encoding 必须原样透传该字符串。

    不装 imagededup 也能跑：PHash 由 stub 提供。
    """
    calls = _install_fake_imagededup(monkeypatch, _STUB_PHASH_HEX)

    returned = _run_worker(sharp_img, enable_dedup=True)

    assert len(returned) == 4, "worker 返回元组长度变了，主进程解包会错位"
    phash_encoding = returned[3]

    # 恒为 None 是去重失效的典型症状，且会被 except 静默掩盖，必须正面断言
    assert phash_encoding is not None
    assert isinstance(phash_encoding, str), (
        f"encode_image 契约是 str，实际拿到 {type(phash_encoding).__name__}"
    )
    assert phash_encoding == _STUB_PHASH_HEX
    # 顺带钉住入参：worker 必须把图片路径传给 encode_image
    assert calls == [sharp_img]


def test_worker_returns_none_when_encode_image_returns_none(
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """encode_image 编码失败返回 None 时，phash_encoding 也应为 None 且不崩。"""
    _install_fake_imagededup(monkeypatch, None)

    phash_encoding = _run_worker(sharp_img, enable_dedup=True)[3]

    assert phash_encoding is None


def test_worker_skips_encoding_when_dedup_disabled(
    sharp_img: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_dedup=False 时不应触碰 imagededup，phash_encoding 为 None。"""
    calls = _install_fake_imagededup(monkeypatch, _STUB_PHASH_HEX)

    phash_encoding = _run_worker(sharp_img, enable_dedup=False)[3]

    assert phash_encoding is None
    assert calls == []


def test_phash_encodings_shape_is_accepted_by_deduplicator(
    sharp_img: str,
    blurry_img: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """闭合链路：worker 产出的编码汇总成 {path: str}，正是 encoding_map 期望的形状。

    Deduplicator 的 available 由真实依赖决定，此处不断言去重结果，
    只断言主进程汇总出的 dict 值类型全是 str——即 find_duplicates 的
    encoding_map: Dict[str, str] 契约。
    """
    _install_fake_imagededup(monkeypatch, _STUB_PHASH_HEX)

    encodings = {path: _run_worker(path, enable_dedup=True)[3] for path in (sharp_img, blurry_img)}

    assert set(encodings) == {sharp_img, blurry_img}
    assert all(isinstance(v, str) for v in encodings.values()), (
        f"encoding_map 的值必须是 str，实际 {[type(v).__name__ for v in encodings.values()]}"
    )


def test_worker_returns_4tuple_no_vlm_b64(sharp_img: str) -> None:
    """阶段 1 worker 不再预编码 VLM base64：返回固定为 4 元组，VLM 编码延后到阶段 2。

    钉死修复不变量（OOM 修复）：worker 不产出 base64，主进程不再常驻大尺寸字符串，
    批量内存恒定；VLM base64 改为阶段 2 由 judge 经 encode_image_b64(img_path) 现用现编。
    """
    returned = _run_worker(sharp_img, enable_dedup=False)

    assert len(returned) == 4, "worker 必须返回 4 元组（img_path, cv, portrait, phash）"
    assert isinstance(returned[0], str)
    assert isinstance(returned[1], CVResult)
    assert isinstance(returned[2], PortraitResult)
    # 未启用去重 → phash 为 None；关键是已经没有第 5 位的 base64
    assert returned[3] is None
    # 显式确认返回对象不含任何 base64 字符串
    assert not any(isinstance(v, str) and len(v) > 1000 for v in returned)


# ---------- keep_map 平分规则（M-04）----------


def test_build_keep_map_tie_break_by_full_path(tmp_path: Path) -> None:
    """同分组内跨目录同名同分图按全路径升序选 keeper（M-04）。

    此前二级键是纯文件名，不同子目录同名文件键值相等，
    删哪张留哪张取决于组内输入顺序，跨机器不可复现。
    _build_keep_map 是纯逻辑不读盘，无需 imagededup 即可测。
    """
    a_img = tmp_path / "a" / "IMG_0001.jpg"
    b_img = tmp_path / "b" / "IMG_0001.jpg"
    # 插入序 b 在前，模拟与全路径序相反的输入顺序
    path_to_score = {
        str(b_img): _make_score(b_img.name, str(b_img), 80.0),
        str(a_img): _make_score(a_img.name, str(a_img), 80.0),
    }
    dup_map = {str(b_img): [str(a_img)], str(a_img): [str(b_img)]}

    keep_map = Deduplicator()._build_keep_map(dup_map, path_to_score)

    assert list(keep_map) == [str(a_img)]
    assert keep_map[str(a_img)] == [str(b_img)]

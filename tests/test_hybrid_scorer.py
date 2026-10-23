"""HybridScorer 测试。

用真实 CVEngine（确定性）+ mock VLMClient，验证合并逻辑、权重、并发、选取。
测试目录用 tmp_path + 复制 fixture 图，避免污染 fixtures 目录。
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.synchronize
import shutil
import threading
import time
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import requests

from flashgaze.core import hybrid_scorer as hs
from flashgaze.core.cv_engine import (
    _BRISQUE_API,
    _BRISQUE_MODEL_DIR,
    BrisqueIntegrityError,
    CVEngine,
)
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.core.vlm_client import VLMClient
from flashgaze.models.schemas import Config, CVResult, ImageScore, PortraitResult, VLMResult
from flashgaze.utils.config import build_config
from flashgaze.utils.image_io import encode_image_b64

# BRISQUE 依赖或模型缺失时，噪点相关用例无意义（noise 恒为 None、构造成本恒为 0），
# 与 test_noise.py 采用同一判定条件。
_HAS_BRISQUE = (
    _BRISQUE_API is not None
    and _BRISQUE_MODEL_DIR is not None
    and (_BRISQUE_MODEL_DIR / "brisque_model_live.yml").is_file()
    and (_BRISQUE_MODEL_DIR / "brisque_range_live.yml").is_file()
)


def _config(**overrides: Any) -> Config:
    """构造测试用 Config，默认 no_vlm=True（纯 CV，可复现）。"""
    base: dict[str, Any] = {
        "directory": ".",
        "top": 30,
        "no_vlm": True,
        "weights": {"sharpness": 0.5, "exposure": 0.5},
    }
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/dark/corrupted 到临时目录，作为评分目标。"""
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


# ---------- score_batch 基础 ----------


def test_score_batch_returns_sorted_descending(photo_dir: str) -> None:
    """结果按综合分降序排列。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    assert len(results) == 4
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_score_batch_empty_directory_returns_empty(tmp_path: Path) -> None:
    """空目录返回空列表。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path)))
    assert scorer.score_batch(str(tmp_path)) == []


def test_score_batch_nonexistent_directory_returns_empty() -> None:
    """不存在的目录返回空列表。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory="nonexistent"))
    assert scorer.score_batch("nonexistent") == []


# ---------- 异常处理 ----------


def test_score_batch_handles_corrupted_image(photo_dir: str) -> None:
    """corrupted.jpg 不中断流程，标记 error 且 score=0。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    corrupted = [r for r in results if r.file == "corrupted.jpg"]
    assert len(corrupted) == 1
    assert corrupted[0].error is not None
    assert corrupted[0].score == 0.0


def test_score_paths_skipped_submission_does_not_crash(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归(FIX 健壮性): image_paths 中某路径始终拿不到阶段1有效结果时
    (victim future 永不完成、被看门狗隔离为超时占位), 不得因 KeyError
    冲垮整批, 而应作为 error 占位正常产出结果 (与"错误不中断批处理"原则一致)。

    旧实现经 monkeypatch as_completed 把 victim 从迭代中剔除来模拟"提交后未
    回收"; 现实现改为 wait 看门狗循环 + 全路径预置占位, 同一条下游契约改由
    "victim future 永不完成"驱动验证。
    """
    victim = str(Path(photo_dir) / "sharp.jpg")
    assert Path(victim).exists()
    other = [
        str(Path(photo_dir) / "blurry.jpg"),
        str(Path(photo_dir) / "dark.jpg"),
    ]

    _install_fake_pool(monkeypatch, {victim: {"hang": True}})
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)

    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, workers=2))
    results = scorer.score_paths([victim, *other])

    # 不抛 KeyError; 全部路径(含未完成者)都有结果
    assert len(results) == len([victim, *other])
    v = [r for r in results if r.file == "sharp.jpg"]
    assert len(v) == 1
    # 预置 error 占位生效, 该图被标记为 error 而非冲垮整批
    assert v[0].error is not None
    assert v[0].score == 0.0
    # 其余图正常评分, 不受影响
    assert all(r.error is None for r in results if r.file != "sharp.jpg")


# ---------- 零权重（FIX #C-15）----------


def test_weighted_cv_score_zero_weights_raises() -> None:
    """权重总和为 0 时 _weighted_cv_score 抛 ValueError，不再静默返回 0.0。"""
    config = _config(weights={"sharpness": 0.0, "exposure": 0.0})
    scorer = HybridScorer(CVEngine(), None, config)
    cv = CVResult(sharpness=80.0, exposure=70.0)
    with pytest.raises(ValueError, match="权重总和为 0"):
        scorer._weighted_cv_score(cv)


def test_zero_weights_score_batch_returns_error_results(photo_dir: str) -> None:
    """零权重配置经 score_batch 产生带 error 的结果，而非静默全 0 有效分。"""
    config = _config(directory=photo_dir, weights={"sharpness": 0.0, "exposure": 0.0})
    scorer = HybridScorer(CVEngine(), None, config)
    results = scorer.score_batch(photo_dir)
    # 每张图都应带 error（综合分无意义），且 score=0.0
    assert results, "应有评分结果"
    assert all(r.error is not None for r in results)
    assert all(r.score == 0.0 for r in results)
    # 全部为 error，故无任何图被选中（不会被 cleanup 误删/误判）
    assert all(not r.selected for r in results)


def test_zero_weights_score_one_returns_error(photo_dir: str) -> None:
    """单图评分（MCP 路径）对零权重同样返回带 error 的 ImageScore，不崩溃。"""
    config = _config(directory=photo_dir, weights={"sharpness": 0.0, "exposure": 0.0})
    scorer = HybridScorer(CVEngine(), None, config)
    sharp = next(Path(photo_dir).glob("*.jpg"))
    result = scorer.score_one(str(sharp))
    assert result.error is not None
    assert result.score == 0.0


def test_score_one_cv_hang_returns_error(photo_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """单图 CV 评估挂起（畸形图触发 OpenCV C 层死锁）时，看门狗超时返回 error 不阻塞。

    模拟：将 PER_IMAGE_TIMEOUT_SEC 压到 1s，并把 CV 评估替换为永久阻塞函数；
    断言 score_one 在数秒内返回带 error 的 ImageScore（综合分 0.0），不被挂起。
    """
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 1)
    config = _config(directory=photo_dir)
    scorer = HybridScorer(CVEngine(), None, config)
    # 有界阻塞：模拟 C 层死循环（libwebp/libtiff 畸形图）。勿用 time.sleep(1e9)——py3.10 的
    # Windows（Sleep 的 32 位毫秒计数）与 macOS（select EINVAL）会立即抛错而非挂起，异常经
    # err_holder 被看门狗原样重抛，超时分支根本不触发。口径同 _hang_thread_stub 的 30s。
    scorer.cv_engine.evaluate_with_color = lambda p: threading.Event().wait(30)  # type: ignore[method-assign, assignment, return-value]  # 测试桩：制造挂起
    sharp = next(Path(photo_dir).glob("*.jpg"))
    hung_engine = scorer.cv_engine
    start = time.monotonic()
    result = scorer.score_one(str(sharp))
    elapsed = time.monotonic() - start
    # 看门狗必须在超时附近返回，远小于无限挂起
    assert elapsed < 10.0
    assert result.error is not None
    assert result.score == 0.0
    # MED-1: 超时后实例级引擎必须重建——挂起线程独占旧实例，后续调用拿全新引擎，
    # 不再与挂起线程并发复用同一 OpenCV C 层对象
    assert scorer.cv_engine is not hung_engine, "看门狗超时后必须重建 CVEngine（MED-1）"


def test_score_one_worker_exception_propagates(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CV 评估线程内抛异常（非挂起类失败）时，score_one 原样向上传播。

    看门狗只隔离挂起型 worker（C 层死锁）；普通异常由 _run 捕获后重抛，
    与原 fut.result() 的传播语义一致，调用方（MCP）能看到真实错误。
    """
    config = _config(directory=photo_dir)
    scorer = HybridScorer(CVEngine(), None, config)

    def _boom(_p: str) -> Any:
        raise RuntimeError("CV评估崩溃")

    monkeypatch.setattr(scorer.cv_engine, "evaluate_with_color", _boom)
    sharp = next(Path(photo_dir).glob("*.jpg"))
    with pytest.raises(RuntimeError, match="CV评估崩溃"):
        scorer.score_one(str(sharp))


# ---------- 选取逻辑 ----------


def test_top_selection(photo_dir: str) -> None:
    """top=2 时，前 2 名有效图被选中，corrupted 不选中。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, top=2))
    results = scorer.score_batch(photo_dir)
    selected = [r for r in results if r.selected]
    assert len(selected) == 2
    # corrupted 不应被选中
    assert all(r.error is None for r in selected)


def test_threshold_selection(photo_dir: str) -> None:
    """threshold 模式：高于阈值的全部选中。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, threshold=50.0))
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None:
            assert r.selected == (r.score >= 50.0)
        else:
            assert r.selected is False


def test_top_larger_than_valid_count(photo_dir: str) -> None:
    """top > 有效图数时，全部有效图选中。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, top=100))
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    selected = [r for r in results if r.selected]
    assert len(selected) == len(valid)


# ---------- VLM 微调 ----------


def test_vlm_adjustment_applied(photo_dir: str) -> None:
    """VLM 补偿被加到最终分数上。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(adjustment=5.0, reason="艺术虚化", ok=True)
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    # 有效图的 vlm_adjustment 应为 5.0
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_adjustment == 5.0 for r in valid)


def test_vlm_failure_falls_back_to_cv_only(photo_dir: str) -> None:
    """VLM 调用失败时，vlm_adjustment=0，不中断。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=0.0, reason="失败", ok=False, error="timeout"
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_adjustment == 0.0 for r in valid)


# ---------- VLM 可解释性字段透传（M4）----------


def test_vlm_success_propagates_reason_and_provider(photo_dir: str) -> None:
    """VLM 成功时 ImageScore.vlm_reason / vlm_provider 被填充。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=5.0,
        reason="背景虚化",
        ok=True,
        provider="qwen",
        scene="portrait",
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_reason == "背景虚化" for r in valid)
    assert all(r.vlm_provider == "qwen" for r in valid)
    assert all(r.vlm_adjustment == 5.0 for r in valid)


def test_vlm_failure_empty_reason_and_provider(photo_dir: str) -> None:
    """VLM 失败时 ImageScore.vlm_reason / vlm_provider 为空串。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=0.0,
        reason="失败",
        ok=False,
        error="timeout",
        provider="qwen",
        scene="auto",
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    # 失败时 vlm_adj 归零，reason/provider 为空串（向后兼容）
    assert all(r.vlm_adjustment == 0.0 for r in valid)
    assert all(r.vlm_reason == "" for r in valid)
    assert all(r.vlm_provider == "" for r in valid)


def test_no_vlm_mode_empty_reason_and_provider(photo_dir: str) -> None:
    """--no-vlm 模式下 vlm_reason / vlm_provider 为空串。"""
    config = _config(directory=photo_dir, no_vlm=True)
    scorer = HybridScorer(CVEngine(), None, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_reason == "" for r in valid)
    assert all(r.vlm_provider == "" for r in valid)
    assert all(r.vlm_adjustment == 0.0 for r in valid)


def test_vlm_success_zero_adjustment_marks_applied(photo_dir: str) -> None:
    """VLM 成功但补偿恰为 0 时 vlm_applied=True，与「失败/未启用」显式区分。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(adjustment=0.0, reason="无需调整", ok=True)
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_applied is True for r in valid)
    assert all(r.vlm_error == "" for r in valid)
    assert all(r.vlm_adjustment == 0.0 for r in valid)


def test_vlm_failure_records_error(photo_dir: str) -> None:
    """VLM 失败时 vlm_applied=False 且失败原因透传到 ImageScore.vlm_error。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(
        adjustment=0.0, reason="失败", ok=False, error="circuit_open"
    )
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_applied is False for r in valid)
    assert all(r.vlm_error == "circuit_open" for r in valid)
    assert all(r.vlm_adjustment == 0.0 for r in valid)


def test_no_vlm_mode_marks_not_applied(photo_dir: str) -> None:
    """未启用 VLM 时 vlm_applied=False 且 vlm_error 为空串（与「调用失败」可区分）。"""
    config = _config(directory=photo_dir, no_vlm=True)
    scorer = HybridScorer(CVEngine(), None, config)
    results = scorer.score_batch(photo_dir)
    valid = [r for r in results if r.error is None]
    assert all(r.vlm_applied is False for r in valid)
    assert all(r.vlm_error == "" for r in valid)


# ---------- 批量熔断集成（端点宕机 → 批级止损 + 口径标记）----------


def test_score_paths_dead_endpoint_circuit_breaks(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点宕机时批级熔断：post 调用数有上界（对比朴素 O(全图×重试)），口径可观测。

    workers=1（确定性串行）：前 5 张图各烧满 max_retries=3 次尝试 → 连续失败
    达阈值熔断 → 其余图零网络早退。总调用数 = 阈值 × 重试，与图片数量无关。
    """
    for i in range(12):
        shutil.copy2(fixtures_dir / "sharp.jpg", tmp_path / f"img_{i:02d}.jpg")
    calls = {"n": 0}

    def fake_post(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        raise requests.ConnectionError("dead endpoint")

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    monkeypatch.setattr("flashgaze.core.vlm_client.time.sleep", lambda s: None)
    monkeypatch.setattr("flashgaze.core.vlm_client._resolve_pinned_target", lambda *a, **kw: [])

    vlm = VLMClient(
        api_key="k",
        api_base="http://x",
        model="m",
        timeout_sec=1,
        max_retries=3,
        breaker_threshold=5,
    )
    config = _config(directory=str(tmp_path), no_vlm=False, workers=1)
    scorer = HybridScorer(CVEngine(), vlm, config)
    results = scorer.score_batch(str(tmp_path))

    valid = [r for r in results if r.error is None]
    assert len(valid) == 12
    # 调用数上界：熔断后剩余图零请求。朴素行为 = 12 张 × 3 次 = 36 次
    assert calls["n"] == 5 * 3
    # 全部图降级为纯 CV 口径且显式标记
    assert all(r.vlm_applied is False for r in valid)
    assert all(r.vlm_adjustment == 0.0 for r in valid)
    assert all(r.vlm_error != "" for r in valid)
    errors = {r.vlm_error for r in valid}
    assert errors == {"retry_exhausted", "circuit_open"}
    assert sum(1 for r in valid if r.vlm_error == "circuit_open") == 7
    # 纯 CV 口径：分数与无 VLM 基线一致（同 CV 引擎、确定性）
    baseline = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path)))
    baseline_scores = {r.file: r.score for r in baseline.score_batch(str(tmp_path))}
    assert all(r.score == baseline_scores[r.file] for r in valid)


def test_score_clamped_to_0_100(photo_dir: str) -> None:
    """VLM 补偿导致超范围时 clamp 到 0-100。"""
    mock_vlm = MagicMock()
    mock_vlm.judge.return_value = VLMResult(adjustment=100.0, reason="过补", ok=True)
    config = _config(directory=photo_dir, no_vlm=False)
    scorer = HybridScorer(CVEngine(), mock_vlm, config)
    results = scorer.score_batch(photo_dir)
    assert all(0.0 <= r.score <= 100.0 for r in results)


# ---------- 权重 ----------


def test_weighted_score_with_default_weights(photo_dir: str) -> None:
    """默认权重 0.5/0.5 时，综合分 = 0.5*sharpness + 0.5*exposure（无 VLM）。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None:
            expected = round(0.5 * r.sharpness + 0.5 * r.exposure, 2)
            assert r.score == expected


def test_weighted_score_with_composition_normalized(photo_dir: str) -> None:
    """启用 composition 且三维权重时，综合分 = 加权和 / 权重和（归一化）。"""
    weights = {"sharpness": 0.4, "exposure": 0.4, "composition": 0.2}
    config = _config(directory=photo_dir, enable_composition=True, weights=weights)
    scorer = HybridScorer(CVEngine(enable_composition=True), None, config)
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None and r.composition is not None:
            expected = round((r.sharpness * 0.4 + r.exposure * 0.4 + r.composition * 0.2) / 1.0, 2)
            assert r.score == expected, f"权重归一化失败: {r.file}"


def test_weighted_score_injects_missing_enabled_dim(photo_dir: str) -> None:
    """自定义权重缺 composition key 但启用 composition 时，composition 进入最终分。

    评分口径变更（PLAN-weight-injection）：此前 composition 零贡献，修复后按
    build_config 注入的 0.56/0.24/0.20 加权计入（sharpness=0.7*0.8 等）。
    """
    cfg = build_config(
        directory=photo_dir,
        enable_composition=True,
        weights={"sharpness": 0.7, "exposure": 0.3},
    )
    assert "composition" in cfg.weights
    assert abs(cfg.weights["composition"] - 0.2) < 1e-9
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9

    scorer = HybridScorer(CVEngine(enable_composition=True), None, cfg)
    results = scorer.score_batch(photo_dir)
    for r in results:
        if r.error is None and r.composition is not None:
            expected = round(0.56 * r.sharpness + 0.24 * r.exposure + 0.20 * r.composition, 2)
            assert r.score == expected, "最终分未按注入权重加权（composition 未贡献）"


# ---------- 可复现性 ----------


def test_score_batch_is_deterministic_without_vlm(photo_dir: str) -> None:
    """no_vlm 模式下，连续 10 次评分结果完全一致。"""
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    runs = [scorer.score_batch(photo_dir) for _ in range(10)]
    base_scores = [(r.file, r.score) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score) for r in run] == base_scores


def test_tie_break_by_full_path(tmp_path: Path, fixtures_dir: Path) -> None:
    """跨目录同名同分图按全路径升序，顺序与输入顺序无关（M-04）。

    此前二级键是纯文件名（s.file），不同子目录同名文件键值相等，
    顺序退化为 Python 稳定排序保留的输入顺序，跨机器/文件系统不可复现。
    """
    a_img = tmp_path / "a_dir" / "IMG_0001.jpg"
    b_img = tmp_path / "b_dir" / "IMG_0001.jpg"
    low_img = tmp_path / "0_low" / "IMG_0001.jpg"
    for img in (a_img, b_img, low_img):
        img.parent.mkdir()
        shutil.copy(fixtures_dir / ("sharp.jpg" if img is not low_img else "blurry.jpg"), img)

    scorer = HybridScorer(CVEngine(), None, _config())
    for paths in ([str(b_img), str(a_img)], [str(a_img), str(b_img)]):
        results = scorer.score_paths([str(low_img), *paths])
        # 同分前提：同内容文件分数逐位一致，否则断言的不是 tie-break
        assert results[0].score == results[1].score
        # 全路径升序：a_dir < b_dir，且与传入顺序无关
        assert results[0].path == str(a_img)
        assert results[1].path == str(b_img)
        # 反例：低分图即使全路径最小，也必须排在同分高分图之后（主键不被二级键破坏）
        assert results[2].path == str(low_img)


# ---------- 进程内 CVEngine 单例缓存 ----------


def test_get_cv_engine_reuses_instance() -> None:
    """同参数必须命中缓存，返回同一实例。"""
    a = hs._get_cv_engine(False, False, False, True)
    b = hs._get_cv_engine(False, False, False, True)
    assert a is b


@pytest.mark.parametrize(
    "changed",
    [
        (True, False, False, True),  # enable_composition
        (False, True, False, True),  # enable_noise
        (False, False, True, True),  # enable_color
        (False, False, False, False),  # downscale
    ],
)
def test_get_cv_engine_rebuilds_on_key_change(changed: tuple[bool, bool, bool, bool]) -> None:
    """任一构造参数变化都必须重建引擎，杜绝"配置变了却拿到旧引擎"的静默错配。"""
    base = hs._get_cv_engine(False, False, False, True)
    other = hs._get_cv_engine(*changed)
    assert other is not base
    # 断言新引擎的配置确实生效，而非只是换了个对象
    assert other.enable_composition == changed[0]
    assert other.enable_noise == changed[1]
    assert other.enable_color == changed[2]


def test_reset_cv_engine_cache_clears_singleton() -> None:
    """重置后必须真正建新对象，保证 autouse fixture 能隔离用例间状态。"""
    first = hs._get_cv_engine(False, False, False, True)
    hs._reset_cv_engine_cache()
    assert hs._CV_ENGINE_SINGLETON is None
    assert hs._get_cv_engine(False, False, False, True) is not first


def test_init_cv_engine_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """initializer 必须吞掉构造异常：抛出会让整个进程池变砖。"""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("模拟 CVEngine 构造失败")

    monkeypatch.setattr(hs, "CVEngine", boom)
    hs._init_cv_engine(False, True, False, True)  # 不应抛异常
    assert hs._CV_ENGINE_SINGLETON is None


def test_init_cv_engine_raises_on_brisque_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """供应链信号（模型哈希不符）绝不能被 initializer 静默吞掉：必须置位共享
    标志后响亮 re-raise。旧行为裸吞导致投毒信号延迟到首个任务、甚至整批不浮现。"""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise BrisqueIntegrityError("模拟模型 SHA256 校验失败")

    flag = multiprocessing.Event()
    monkeypatch.setattr(hs, "_get_cv_engine", boom)
    with pytest.raises(BrisqueIntegrityError):
        hs._init_cv_engine(False, True, False, True, flag)
    assert flag.is_set(), "共享标志未置位：主循环将无法区分供应链失败与普通池损坏"


def test_init_cv_engine_swallows_ordinary_exception_and_keeps_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反例：普通构造异常（非供应链信号）必须维持静默降级，共享标志不得置位，
    否则普通预热失败会被主循环误报为供应链事件。"""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("模拟模型文件缺失")

    flag = multiprocessing.Event()
    monkeypatch.setattr(hs, "_get_cv_engine", boom)
    hs._init_cv_engine(False, True, False, True, flag)  # 不应抛异常
    assert not flag.is_set()


def _boom_initializer(*_args: object) -> None:
    """会失败的 initializer。必须是模块级函数，否则无法 pickle 进子进程。"""
    raise RuntimeError("模拟 initializer 失败")


def test_broken_pool_falls_back_to_serial(monkeypatch: pytest.MonkeyPatch, photo_dir: str) -> None:
    """initializer 抛异常时必须降级为串行并产出正常评分，而非整批标 error。"""
    monkeypatch.setattr(hs, "_init_cv_engine", _boom_initializer)
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    results = scorer.score_batch(photo_dir)

    ok = [r for r in results if not r.error]
    assert ok, "串行回退未生效：所有图都变成了 error"
    assert all("子进程异常" not in (r.error or "") for r in results)


def test_submit_phase_broken_pool_falls_back_to_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """submit 阶段抛 BrokenProcessPool（如 worker 启动即崩）不得被外层 suppress
    静默吞掉：该异常不传播出 with，两个外层 except 均接不住，旧实现下整批退化
    为"未提交CV评分"占位且串行回退被绕过。修复后必须落入串行回退并产出正常评分。"""
    good1 = _write_jpg(tmp_path, "sub1.jpg", 0)
    good2 = _write_jpg(tmp_path, "sub2.jpg", 1)
    _install_fake_pool(monkeypatch, {good1: {"submit_broken": True}})

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    results = scorer.score_paths([good1, good2])

    assert all(not r.error for r in results), (
        f"submit 期池损坏必须触发串行回退，而非整批 error: {[r.error for r in results]}"
    )


def test_brisque_integrity_surfaces_via_broken_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """initializer 检出供应链信号（共享 Event 置位）后池损坏时，主循环必须在
    BrokenProcessPool 分类处响亮抛出 BrisqueIntegrityError，绝不降级为串行重跑
    或 error 占位——否则投毒信号延迟到首个任务、甚至整批不浮现（缺陷修复）。"""
    good1 = _write_jpg(tmp_path, "brisque1.jpg", 0)
    good2 = _write_jpg(tmp_path, "brisque2.jpg", 1)
    _install_fake_pool(monkeypatch, {good1: {"brisque_broken_pool": True}})

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    with pytest.raises(BrisqueIntegrityError):
        scorer.score_paths([good1, good2])


def test_broken_pool_without_flag_keeps_serial_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：普通 BrokenProcessPool（供应链标志未置位）必须维持既有串行回退，
    不得因本次新增的标志检查被误报为供应链事件。"""
    good1 = _write_jpg(tmp_path, "plainbroken1.jpg", 0)
    good2 = _write_jpg(tmp_path, "plainbroken2.jpg", 1)
    _install_fake_pool(monkeypatch, {good1: {"submit_broken": True}})

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    results = scorer.score_paths([good1, good2])

    assert all(not r.error for r in results), (
        f"普通池损坏必须串行回退出正常分，而非整批 error: {[r.error for r in results]}"
    )


# ---------- 100 图小批量：噪点一致性与引擎复用 ----------


@pytest.fixture(scope="module")
def batch100_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """100 张 256x256 随机图（固定种子，可复现），用于批量噪点验证。"""
    d = tmp_path_factory.mktemp("batch100")
    rng = np.random.default_rng(1234)
    for i in range(100):
        img = rng.integers(0, 256, size=(256, 256, 3), dtype=np.uint8)
        cv2.imwrite(str(d / f"img_{i:03d}.jpg"), img)
    return str(d)


@pytest.mark.skipif(not _HAS_BRISQUE, reason="BRISQUE 依赖或模型文件缺失")
def test_batch100_noise_identical_across_workers(batch100_dir: str) -> None:
    """100 图开 noise：多进程与串行单进程的噪点分必须逐张相同且非 null。"""

    def run(workers: int) -> dict[str, float]:
        config = _config(directory=batch100_dir, top=100, enable_noise=True, workers=workers)
        scorer = HybridScorer(CVEngine(enable_noise=True), None, config)
        # noise 运行时可能为 None（由下方"非 null"断言兜底），cast 只收敛类型不改值
        return {r.file: cast(float, r.noise) for r in scorer.score_batch(batch100_dir)}

    n4 = run(4)
    n1 = run(1)
    assert len(n4) == 100
    assert all(v is not None for v in n4.values()), "存在 noise 为 null 的图"
    assert all(0.0 <= v <= 100.0 for v in n4.values())
    assert n4 == n1, "多进程与串行的噪点分不一致"


@pytest.mark.skipif(not _HAS_BRISQUE, reason="BRISQUE 依赖或模型文件缺失")
def test_batch100_builds_engine_once_and_is_faster(
    batch100_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """100 图只构造 1 次 CVEngine，且总耗时低于"每图新建"的旧行为。"""
    paths = sorted(str(p) for p in Path(batch100_dir).glob("*.jpg"))
    assert len(paths) == 100

    built: list[int] = []
    real_init = CVEngine.__init__

    def counting_init(self: CVEngine, *args: Any, **kwargs: Any) -> None:
        built.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(CVEngine, "__init__", counting_init)

    hs._reset_cv_engine_cache()
    start = time.perf_counter()
    for p in paths:
        hs._evaluate_cv_and_portrait(p, False, True, False, False, True, False)
    reused_elapsed = time.perf_counter() - start
    assert len(built) == 1, f"100 图应只构造 1 次 CVEngine，实际 {len(built)} 次"

    # 参照组：复刻改动前"每图 new CVEngine"的行为
    built.clear()
    start = time.perf_counter()
    for p in paths:
        CVEngine(enable_noise=True).evaluate(p)
    per_new_elapsed = time.perf_counter() - start
    assert len(built) == 100

    assert reused_elapsed < per_new_elapsed, (
        f"复用未带来提速: 复用 {reused_elapsed:.3f}s vs 每图新建 {per_new_elapsed:.3f}s"
    )


def test_no_vlm_skips_vlm_encode(photo_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """--no-vlm（vlm_client=None）路径不得编码 VLM base64，零额外开销。"""
    calls: dict[str, int] = {"n": 0}
    real_encode = encode_image_b64

    def counting(*a: Any, **kw: Any) -> str:
        calls["n"] += 1
        return real_encode(*a, **kw)

    monkeypatch.setattr("flashgaze.utils.image_io.encode_image_b64", counting)
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir))
    scorer.score_batch(photo_dir)
    assert calls["n"] == 0, "纯 CV 模式不应编码 VLM base64"


def test_phase2_reencodes_each_image_from_path(
    photo_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阶段 2 按 img_path 重新编码（不缓存阶段 1 的 base64），每有效图恰好编码一次。

    钉死修复不变量：主进程不常驻 VLM base64（OOM 修复），编码延后到阶段 2
    由 judge 经 encode_image_b64(img_path) 现用现编，批量内存恒定。
    """
    import flashgaze.utils.image_io as _imgio

    calls: dict[str, int] = {"n": 0}
    real_encode = encode_image_b64

    def counting(*a: Any, **kw: Any) -> str:
        calls["n"] += 1
        return real_encode(*a, **kw)

    monkeypatch.setattr("flashgaze.utils.image_io.encode_image_b64", counting)

    class _FakeVLM:
        def __init__(self) -> None:
            self.calls = 0
            self.paths: list[str] = []

        def judge(
            self,
            img_path: str,
            cv: CVResult | None = None,
            provider: str | None = None,
            pre_encoded_b64: str | None = None,
            **kwargs: Any,
        ) -> VLMResult:
            assert pre_encoded_b64 is None, "阶段 2 不应携带预编码 base64（修复不变量）"
            # 真实 judge 走同一回退路径：按路径重新编码（动态查属性以命中打桩计数）
            _imgio.encode_image_b64(img_path)
            self.calls += 1
            self.paths.append(img_path)
            return VLMResult(50.0, "ok", ok=True)

    # 先以纯 CV 模式确定哪些图能正常评分（无 error），即为阶段 2 的 VLM 目标数
    base = HybridScorer(CVEngine(), None, _config(directory=photo_dir)).score_batch(photo_dir)
    expected = len([s for s in base if s.error is None])

    fake = _FakeVLM()
    scorer = HybridScorer(CVEngine(), cast(VLMClient, fake), _config(directory=photo_dir))
    scorer.score_batch(photo_dir)
    assert fake.calls == expected, "阶段 2 应对每张有效图调用一次 judge"
    assert calls["n"] == expected, "阶段 2 应经 encode_image_b64 按路径重新编码一次"
    assert len(fake.paths) == expected
    assert calls["n"] == fake.calls, "每次 judge 调用都按路径现编一次（无缓存）"


# ── C-04：BRISQUE 供应链信号（哈希不符）必须穿透 score_paths 响亮失败 ──


def test_score_paths_reraises_brisque_integrity(
    monkeypatch: pytest.MonkeyPatch, photo_dir: str
) -> None:
    """BrisqueIntegrityError（模型哈希不符的供应链信号）必须穿透 score_paths，
    不得被逐图 except Exception 降级为 error 占位（C-04）。"""
    from flashgaze.core.cv_engine import BrisqueIntegrityError

    def _boom(*a: Any, **k: Any) -> None:
        raise BrisqueIntegrityError("mocked hash mismatch")

    # 串行路径（workers<=1）下 worker 在主进程内运行，异常直接冒泡
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _boom)
    scorer = HybridScorer(CVEngine(), None, _config(directory=photo_dir, workers=1))
    target = str(Path(photo_dir) / "sharp.jpg")
    with pytest.raises(BrisqueIntegrityError):
        scorer.score_paths([target])


# ── 阶段1 单图超时保护（防死锁拖垮整批）──


def test_phase1_serial_timeout_marks_error_and_keeps_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """workers<=1 串行路径：单图死锁(永不返回)必须在超时后被隔离为 error 占位，
    且其余好图仍正常评分、批次不挂起（看门线程保护）。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    rng = np.random.default_rng(0)
    hang_path = str(tmp_path / "hang.jpg")
    good_path = str(tmp_path / "good.jpg")
    cv2.imwrite(hang_path, rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8))
    cv2.imwrite(good_path, rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8))

    real = hs._evaluate_cv_and_portrait

    def _maybe_hang(path: str, *a: Any, **k: Any) -> tuple[Any, ...]:
        if path == hang_path:
            time.sleep(1.0)  # 模拟死锁
            return (
                "x",
                CVResult(sharpness=0.0, exposure=0.0),
                PortraitResult(face_count=0),
                None,
                None,
            )
        return real(path, *a, **k)

    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _maybe_hang)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_batch(str(tmp_path))

    good = [r for r in results if r.file == "good.jpg"]
    assert good and good[0].error is None, "好图不应被超时误伤"
    hang = [r for r in results if r.file == "hang.jpg"]
    assert hang and hang[0].error is not None and "阶段1超时" in hang[0].error


def test_phase1_serial_timeout_resets_cv_engine_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """串行看门狗超时后必须重置模块级 CVEngine 缓存（MED-1）。

    挂起线程仍持有超时前预置的单例引擎；重置后下一张图经 _get_cv_engine 重建
    全新实例，挂起线程独占旧实例，消除对同一引擎的并发调用。autouse fixture
    会在用例前后清缓存，此处预置的单例不泄漏到其它用例。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang_path = str(tmp_path / "hang.jpg")
    cv2.imwrite(
        hang_path, np.random.default_rng(0).integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
    )

    # 预置单例（模拟前一张图已建好引擎），随后整体替换为挂起桩
    hs._get_cv_engine(False, False, False, True)
    assert hs._CV_ENGINE_SINGLETON is not None, "前置条件：单例应已建好"

    def _hang(path: str, *_a: Any, **_k: Any) -> tuple[Any, ...]:
        time.sleep(1.0)  # 模拟死锁：永不返回
        return ("x", CVResult(sharpness=0.0, exposure=0.0), PortraitResult(face_count=0), None)

    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_batch(str(tmp_path))

    assert results and results[0].error is not None and "阶段1超时" in results[0].error
    assert hs._CV_ENGINE_SINGLETON is None, "超时分支必须重置引擎缓存（MED-1）"


# ---------- M-02 串行看门狗：首次挂起升级一次性子进程托管 ----------
#
# 串行路径的挂起线程无法被 Python 回收（daemon 线程只能放弃），修复后首次
# 挂起即把剩余图改由一次性 spawn 子进程托管：挂起可 terminate 真正回收。
# 注入方式与真实进程池集成用例相同：spawn 子进程按 module+qualname 重导入
# 本模块，monkeypatch 把 hs 模块属性指向下方模块级函数即可被子进程执行
# （monkeypatch 只改父进程属性，子进程重导入拿到的是本模块的真实 def）。


_SUBPROCESS_CALLS: list[str] = []


def _subprocess_ok_stub(img_path: str, *_a: Any, **_k: Any) -> tuple[str, Any]:
    """_run_one_in_subprocess 的同步桩：记录调用并即时回罐头 ok 结果。
    免真实 spawn——0.3s 级超时远小于 spawn 子进程导入耗时，真实进程在快速
    用例中不可确定性完成；真实 spawn + terminate 由 slow 集成用例覆盖。"""
    _SUBPROCESS_CALLS.append(img_path)
    return (
        "ok",
        (img_path, CVResult(sharpness=42.0, exposure=24.0), PortraitResult(face_count=0), None),
    )


def _canned_or_hang_subprocess_worker(
    path: str,
    _enable_comp: bool,
    _enable_noise: bool,
    _enable_color: bool,
    _enable_portrait: bool,
    _downscale: bool,
    _enable_dedup: bool,
    queue: Any,
) -> None:
    """真实子进程内执行的评分 worker：文件名含 __hang__ 的图阻塞（模拟
    OpenCV C 层死锁，永不返回、不抛异常），其余图即时回罐头结果（供父进程
    断言「该图经子进程托管」）。Event.wait 带 120s 上限：回归时孤儿进程至多
    存活 2 分钟（正常路径父进程会先 terminate，触不到该上界）。"""
    if "__hang__" in Path(path).name:
        threading.Event().wait(120)
        return
    queue.put(
        (
            "ok",
            (path, CVResult(sharpness=42.0, exposure=24.0), PortraitResult(face_count=0), None),
        )
    )


def _hang_thread_stub(path: str, *_a: Any, **_k: Any) -> tuple[Any, ...]:
    """线程模式桩：__hang__ 图在父进程内阻塞 30s（模拟首次挂起、触发升级；
    有界阻塞——被放弃的看门线程至多存活 30s），其余图抛 AssertionError：
    升级生效后不应有任何图再走主进程线程评分，若回归（未升级）该异常被
    err_holder 兜底为「评分异常」占位，good 图的 error is None 断言即失败。"""
    if "__hang__" in Path(path).name:
        threading.Event().wait(30)
        return (path, CVResult(sharpness=0.0, exposure=0.0), PortraitResult(face_count=0), None)
    raise AssertionError("升级后不应在主进程线程内评分（应由一次性子进程托管）")


def _write_jpgs(tmp_path: Path, names: list[str]) -> list[str]:
    """按给定顺序生成测试 jpg 并返回同序路径列表。"""
    return [_write_jpg(tmp_path, n, i) for i, n in enumerate(names)]


def test_serial_first_hang_escalates_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """串行路径首次挂起后，剩余图必须全部改由子进程托管评分（M-02 升级语义）。

    子进程边界以 _run_one_in_subprocess 为接缝做同步桩；真实 spawn + terminate
    由下方 test_serial_watchdog_reclaims_hung_worker 慢速集成覆盖。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    paths = _write_jpgs(tmp_path, ["__hang__0.jpg", "good1.jpg", "good2.jpg"])
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_thread_stub)
    _SUBPROCESS_CALLS.clear()
    monkeypatch.setattr(hs, "_run_one_in_subprocess", _subprocess_ok_stub)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_paths(paths)

    hang = [r for r in results if "__hang__" in r.file]
    good = [r for r in results if r.file in ("good1.jpg", "good2.jpg")]
    assert len(hang) == 1 and hang[0].error is not None and "阶段1超时" in hang[0].error
    assert _SUBPROCESS_CALLS == paths[1:], (
        f"挂起后剩余图必须全部经子进程托管: calls={_SUBPROCESS_CALLS}"
    )
    assert all(r.error is None for r in good), (
        f"好图不应被误伤: {[(r.file, r.error) for r in good]}"
    )


def test_serial_single_hang_no_budget_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：单张挂起图不得触发任何「预算耗尽」批死——少量畸形图混批时
    剩余好图必须照常经子进程托管出分（与进程池路径容忍少量挂起的尺度一致）。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    paths = _write_jpgs(tmp_path, ["__hang__0.jpg", "good1.jpg", "good2.jpg"])
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_thread_stub)
    _SUBPROCESS_CALLS.clear()
    monkeypatch.setattr(hs, "_run_one_in_subprocess", _subprocess_ok_stub)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_paths(paths)

    assert all("预算耗尽" not in (r.error or "") for r in results), (
        f"单张挂起不应触发预算耗尽批死: {[(r.file, r.error) for r in results]}"
    )
    hang = [r for r in results if "__hang__" in r.file]
    good = [r for r in results if r.file in ("good1.jpg", "good2.jpg")]
    assert len(hang) == 1 and hang[0].error is not None and "阶段1超时" in hang[0].error
    assert _SUBPROCESS_CALLS == paths[1:]
    assert all(r.error is None for r in good), (
        f"好图不应被误伤: {[(r.file, r.error) for r in good]}"
    )


@pytest.mark.slow
def test_serial_watchdog_reclaims_hung_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实 spawn 子进程集成（M-02 验收：串行回退路径的挂起可被真正终止）。

    __hang__1 先在线程模式挂起触发升级；此后各图均由真实一次性子进程执行：
    good 即时回罐头分，__hang__2 在子进程内阻塞、被父进程 terminate 回收，
    score_paths 必须有界返回。修复前（无托管）good 图会落入线程桩的
    AssertionError → 「评分异常」占位，下方好图断言随即失败。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 15.0)
    paths = _write_jpgs(tmp_path, ["__hang__1.jpg", "good1.jpg", "__hang__2.jpg", "good2.jpg"])
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_thread_stub)
    monkeypatch.setattr(hs, "_serial_subprocess_worker", _canned_or_hang_subprocess_worker)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    box: list[list[ImageScore]] = []
    errors: list[Exception] = []

    def _run() -> None:
        try:
            box.append(scorer.score_paths(paths))
        except Exception as e:  # noqa: BLE001 — 线程内异常带回主线程断言，避免吞掉
            errors.append(e)

    start = time.monotonic()
    runner = threading.Thread(target=_run, daemon=True)
    runner.start()
    runner.join(timeout=120.0)
    elapsed = time.monotonic() - start
    assert not runner.is_alive(), "score_paths 未在有界时间返回：挂起子进程未被 terminate 回收"
    assert not errors, f"score_paths 抛出异常: {errors!r}"
    results = box[0]
    assert len(results) == len(paths)
    hangs = [r for r in results if "__hang__" in r.file]
    goods = [r for r in results if r.file in ("good1.jpg", "good2.jpg")]
    assert len(hangs) == 2 and all("阶段1超时" in (r.error or "") for r in hangs), (
        f"挂起图应被逐图隔离: {[(r.file, r.error) for r in hangs]}"
    )
    assert all(r.error is None for r in goods), (
        f"好图应经子进程托管正常出分: {[(r.file, r.error) for r in goods]}"
    )
    assert elapsed < 110.0, f"必须远小于修复前的无限阻塞: {elapsed:.1f}s"


# ---------- M-02 串行看门狗：泄漏线程数 / 累计挂起时长双硬上限 ----------
#
# 子进程托管回收内存但不回收时间（每张挂起图固定消耗单图超时时长）；受限环境
# （子进程创建失败）下永久回退线程模式，被放弃的挂起线程继续累积内存。两个
# 硬上限分别兜底：达限后剩余图统一标「阶段1超时-串行看门狗预算耗尽」提前
# 整批失败，杜绝「100 张畸形图 = 100×120s 假死 + 内存线性增长直至 OOM」。


def _subprocess_oserror_stub(img_path: str, *_a: Any, **_k: Any) -> tuple[str, Any]:
    """模拟受限环境：一次性子进程创建即失败（调用方应永久回退线程模式）。"""
    raise OSError(f"sem_open 失败(模拟受限环境): {img_path}")


def _subprocess_timeout_stub(img_path: str, *_a: Any, **_k: Any) -> tuple[str, Any]:
    """模拟子进程托管下的挂起图：免去真实 spawn，直接返回超时结果。"""
    return ("timeout", None)


def _subprocess_canary_stub(img_path: str, *_a: Any, **_k: Any) -> tuple[str, Any]:
    """反例哨兵：健康批不应有任何子进程托管调用，被调用即失败。"""
    raise AssertionError(f"健康批不应触发子进程托管: {img_path}")


def test_serial_leak_cap_aborts_remaining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """泄漏线程数达上限（默认 3）后必须提前整批失败：剩余图统一标
    「阶段1超时-串行看门狗预算耗尽」，不再为后续畸形图新建看门线程。

    受限环境模拟：_run_one_in_subprocess 一调即抛 OSError，全批困在线程模式，
    泄漏计数逐挂起图递增——修复前 4 张挂起图会逐图 4×timeout 隔离且 good 落入
    线程桩 AssertionError（评分异常占位），无限累积。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.2)
    paths = _write_jpgs(
        tmp_path, ["__hang__0.jpg", "__hang__1.jpg", "__hang__2.jpg", "__hang__3.jpg", "good.jpg"]
    )
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_thread_stub)
    monkeypatch.setattr(hs, "_run_one_in_subprocess", _subprocess_oserror_stub)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_paths(paths)

    timeout_errs = [r for r in results if "阶段1超时(>" in (r.error or "")]
    exhausted_errs = [r for r in results if "预算耗尽" in (r.error or "")]
    assert len(timeout_errs) == 3, (
        f"恰 3 张挂起图被逐图隔离(泄漏上限), 实际 {len(timeout_errs)}: "
        f"{[(r.file, r.error) for r in results]}"
    )
    assert [r.file for r in exhausted_errs] == ["__hang__3.jpg", "good.jpg"], (
        f"达限后剩余图必须统一标预算耗尽: {[(r.file, r.error) for r in exhausted_errs]}"
    )
    assert scorer.phase1_stats["timed_out"] == 5, (
        f"隔离数(3)+预算耗尽数(2)应全部计入 timed_out: {scorer.phase1_stats}"
    )


def test_serial_budget_cap_in_subprocess_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """子进程托管模式下累计挂起时长达预算（4×单图超时）后必须提前整批失败：
    子进程回收内存但不回收时间，无预算则 100 张畸形图 = 100×120s 假死。

    _run_one_in_subprocess 桩直接返回 timeout（免真实 spawn），首图仍走线程模式
    挂起以触发升级——耗时累计覆盖两种模式，预算运行时相乘与 monkeypatch 联动。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.2)
    paths = _write_jpgs(
        tmp_path,
        [
            "__hang__0.jpg",
            "__hang__1.jpg",
            "__hang__2.jpg",
            "__hang__3.jpg",
            "__hang__4.jpg",
            "good.jpg",
        ],
    )
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_thread_stub)
    monkeypatch.setattr(hs, "_run_one_in_subprocess", _subprocess_timeout_stub)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_paths(paths)

    timeout_errs = [r for r in results if "阶段1超时(>" in (r.error or "")]
    exhausted_errs = [r for r in results if "预算耗尽" in (r.error or "")]
    assert len(timeout_errs) == 4, (
        f"预算=4×0.2s, 恰 4 张挂起图被逐图隔离, 实际 {len(timeout_errs)}: "
        f"{[(r.file, r.error) for r in results]}"
    )
    assert [r.file for r in exhausted_errs] == ["__hang__4.jpg", "good.jpg"], (
        f"达限后剩余图必须统一标预算耗尽: {[(r.file, r.error) for r in exhausted_errs]}"
    )


def test_serial_no_escalation_on_healthy_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：健康批（无挂起）不得触发子进程托管与任何预算逻辑——
    workers<=1/MCP 短路的存在理由就是避免健康图付出 spawn 开销。"""
    paths = [_write_jpg(tmp_path, f"img_{i}.jpg", i) for i in range(3)]
    monkeypatch.setattr(hs, "_run_one_in_subprocess", _subprocess_canary_stub)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=1, top=10))
    results = scorer.score_paths(paths)

    assert len(results) == 3
    assert all(r.error is None for r in results), (
        f"健康图不应被误伤: {[(r.file, r.error) for r in results]}"
    )
    assert all(v == 0 for v in scorer.phase1_stats.values()), (
        f"健康批看门狗统计必须全零: {scorer.phase1_stats}"
    )


def test_phase1_pool_fast_workers_not_falsely_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """小超时时，正常(快速)图不应被误标 error：验证超时分支只在真挂起时触发，
    不影响进程池正常路径（跨平台，无需子进程死锁注入）。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    paths = []
    for i in range(4):
        p = str(tmp_path / f"img_{i}.jpg")
        cv2.imwrite(p, np.random.default_rng(i).integers(0, 256, size=(32, 32, 3), dtype=np.uint8))
        paths.append(p)
    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    results = scorer.score_paths(paths)
    assert len(results) == 4
    assert all(r.error is None for r in results), "快速好图不应被超时误伤"


# ── 阶段1 进程池看门狗（跨平台：fake executor 驱动真 Future）──
#
# 挂起注入无法经 monkeypatch 进入 spawn 子进程（Windows/macOS 默认启动方式，
# 子进程重导入模块），故不改真实进程池，而是把 hs.ProcessPoolExecutor 替换为
# 假池：submit 返回真实的 concurrent.futures.Future，由假池控制 running() 与
# 完成时机，生产代码里的 wait(FIRST_COMPLETED) 看门狗循环走真实实现。
# 无子进程、无 pickle 限制，三平台行为一致。
# （旧 fork 门控用例 test_phase1_pool_timeout_and_exhaustion_marks_pending_error
#   已被下方三个跨平台用例取代——它验证的"死锁占满"文案在旧实现中本就不可达。）
#
# fake 池无法覆盖"真实池拆除"路径：挂起 worker 进程若不被终止，拆池的
# shutdown(wait=True) 会永久阻塞（管理线程 join + p.join() 均无超时）。
# 该路径由下方 test_phase1_real_pool_hung_worker_teardown_bounded 集成用例
# 跨平台覆盖：真实进程池 + 模块级可 pickle 的挂起 worker（spawn 子进程按
# module+qualname 重导入后执行，天然绕开 monkeypatch 进不了子进程的限制）。


class _FakeProc:
    """进程桩：只实现 hybrid_scorer 拆池块（:966-982）用到的 5 个成员。

    「terminate 未生效 → 升级 kill」此前只被 @slow 真进程池用例偶然踩到——
    2026-10-23 的 12 腿 CI 产物中仅 ubuntu-py3.10 一条覆盖 974/978，且该用例
    断言的是墙钟有界而非强杀行为，回归不会变红。桩把计时偶然换成确定判定：
    survive_terminate=True 时 is_alive() 恒真；raise_on 指定哪个方法抛 OSError
    以驱动「进程已抢先退出」竞态兜底。join() 记录超时值但不等待，所以
    _TERMINATE_JOIN_SEC=5.0 在本用例里零开销。
    """

    def __init__(self, pid: int, *, survive_terminate: bool = False, raise_on: str = "") -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.join_timeout: float | None = None
        self._survive = survive_terminate
        self._raise_on = raise_on
        self._alive = True

    def _boom(self, where: str) -> None:
        if self._raise_on == where:
            raise OSError(f"模拟进程已退出的竞态: {where}")

    def terminate(self) -> None:
        self._boom("terminate")
        self.terminated = True
        self._alive = self._survive

    def join(self, timeout: float | None = None) -> None:
        self._boom("join")
        self.join_timeout = timeout

    def is_alive(self) -> bool:
        self._boom("is_alive")
        return self._alive

    def kill(self) -> None:
        self._boom("kill")
        self.killed = True


# 3.10 目标下无 typing.Self，且 typing_extensions 未在本项目依赖中声明，
# __enter__ 返回自身类名并标注 PYI034 豁免。
def _install_fake_pool(monkeypatch: pytest.MonkeyPatch, plans: dict[str, Any]) -> list[Any]:
    """按 plans 替换 hybrid_scorer.ProcessPoolExecutor，返回各代假池实例列表。

    plans[path] 支持：
    - {"delay": 秒}        正常完成，延迟后 set_result（缺省立即完成）
    - {"hang": True}       置 running 后永不 set_result（模拟 OpenCV C 层死锁）
    - {"running": False}   永不置 running 也永不完成（模拟排队卡死 / initializer 挂起）
    - {"submit_broken": True}  submit 时直接抛 BrokenProcessPool（模拟 worker
      启动即崩、池在提交阶段就已损坏）
    - {"brisque_broken_pool": True}  池级计划：initargs 末位是共享 Event（生产
      代码传入的供应链标志）时置位，且全部 submit 抛 BrokenProcessPool——模拟
      "initializer 检出 BrisqueIntegrityError → 池损坏 + 标志跨进程传播"。
      修复前的生产代码 initargs 只有 4 个引擎布尔参数，无 Event 可置位。
    - callable(gen) -> dict   代际感知计划：gen 为本次评分中的池代数（0 起），
      用于验证「池代际重建」——重建后同一张图的派发行为可以不同。
    特殊键 "__procs__"（非路径）：list[dict] | callable(gen) -> list[dict]，每项是
      _FakeProc 的构造参数（survive_terminate / raise_on），用于驱动拆池阶段的
      terminate→kill 升级与 OSError 竞态。缺省为空表——生产代码对「无 _processes
      属性」与「空表」同样安全跳过，故既有假池用例行为逐字节不变。
    未列出的 path 默认立即正常完成。
    返回值供用例断言实际创建了几代假池（重建次数 + 1）。
    """
    created: list[Any] = []
    brisque_broken = any(
        isinstance(p, dict) and p.get("brisque_broken_pool") for p in plans.values()
    )

    class _FakePool:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self._threads: list[threading.Thread] = []
            self._gen = len(created)  # 本池的代数索引（0 起）
            created.append(self)
            procs_spec = plans.get("__procs__", [])
            if callable(procs_spec):
                procs_spec = procs_spec(self._gen)
            self._processes: dict[int, Any] = {
                pid: _FakeProc(pid, **kw) for pid, kw in enumerate(procs_spec, 1)
            }
            if brisque_broken:
                initargs = _k.get("initargs", ())
                if initargs and hasattr(initargs[-1], "set"):
                    initargs[-1].set()

        def __enter__(self) -> _FakePool:  # noqa: PYI034 — 见上方说明
            return self

        def __exit__(self, *_exc: object) -> None:
            self.shutdown(wait=True)

        def shutdown(self, wait: bool = True) -> None:
            # 生产代码已改为显式拆池（不再经 __exit__），fake 池必须提供同名
            # 方法；语义对齐真实 shutdown(wait=True)：等待全部驱动线程收尾。
            for t in self._threads:
                t.join(timeout=5)

        def submit(self, _fn: Any, path: str, *_a: Any, **_k: Any) -> hs._Phase1Future:
            if brisque_broken:
                raise BrokenProcessPool(f"initializer 检出供应链失败，池损坏: {path}")
            plan = plans.get(path, {})
            if callable(plan):
                plan = plan(self._gen)
            if plan.get("submit_broken"):
                raise BrokenProcessPool(f"submit 阶段池损坏: {path}")
            fut: hs._Phase1Future = Future()
            if plan.get("running", True):
                fut.set_running_or_notify_cancel()
            if not plan.get("running", True) or plan.get("hang"):
                return fut  # 永不完成：无需驱动线程

            def _drive() -> None:
                time.sleep(plan.get("delay", 0.0))
                fut.set_result(
                    (
                        path,
                        CVResult(sharpness=80.0, exposure=70.0),
                        PortraitResult(face_count=0),
                        None,
                    )
                )

            t = threading.Thread(target=_drive, daemon=True)
            t.start()
            self._threads.append(t)
            return fut

    monkeypatch.setattr(hs, "ProcessPoolExecutor", _FakePool)
    return created


def _write_jpg(tmp_path: Path, name: str, seed: int) -> str:
    p = str(tmp_path / name)
    cv2.imwrite(p, np.random.default_rng(seed).integers(0, 256, size=(32, 32, 3), dtype=np.uint8))
    return p


# ── 真实进程池集成测试的模块级辅助 ──
# spawn 子进程按 module+qualname 重导入并 unpickle 函数引用：monkeypatch 在父
# 进程内替换 hs._evaluate_cv_and_portrait / hs._init_cv_engine 后，submit 与
# initializer 拿到的就是下列函数的引用，子进程重导入本模块即可执行——绕开
# "monkeypatch 进不了 spawn 子进程"（fake 池注释所述）限制的方式。


def _noop_pool_init(*_a: Any, **_k: Any) -> None:
    """测试用池 initializer：跳过 BRISQUE 预热，让 spawn 子进程秒级启动，
    压低看门狗"整体无进展"分支的误触发面。"""


def _brisque_flag_init_broken(*_a: Any, **_k: Any) -> None:
    """测试用池 initializer：置位 initargs 末位的供应链共享 Event 后抛
    BrisqueIntegrityError，模拟 worker 内检出模型哈希不符。必须是模块级函数，
    否则无法 pickle 进 spawn 子进程（见上方注释）。"""
    flag = _a[-1] if _a else None
    if flag is not None and hasattr(flag, "set"):
        flag.set()
    raise BrisqueIntegrityError("worker 内检出 BRISQUE 模型完整性校验失败（集成用例）")


def _hang_or_score_worker(
    path: str, *_a: Any, **_k: Any
) -> tuple[str, CVResult, PortraitResult, object]:
    """文件名含 __hang__ 的图在子进程内阻塞，模拟 OpenCV C 层死锁（永不返回、
    不抛异常）；其余图即时返回罐头结果。
    Event.wait 带 120s 上限：修复若回归，孤儿进程至多存活 2 分钟。"""
    if "__hang__" in Path(path).name:
        threading.Event().wait(120)
    return (path, CVResult(sharpness=80.0, exposure=70.0), PortraitResult(face_count=0), None)


def test_phase1_pool_hang_isolated_by_watchdog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进程池路径：单图死锁（永不返回）必须在超时后被隔离为 error 占位，
    其余好图正常评分、整批快速返回。旧实现 as_completed+result(timeout)
    组合下该分支不可达，一张挂起图会让整批无限阻塞。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang = _write_jpg(tmp_path, "hang.jpg", 0)
    good1 = _write_jpg(tmp_path, "good1.jpg", 1)
    good2 = _write_jpg(tmp_path, "good2.jpg", 2)
    _install_fake_pool(monkeypatch, {hang: {"hang": True}, good1: {}, good2: {}})

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths([hang, good1, good2])
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, "单图挂起不得阻塞整批"
    hang_r = [r for r in results if r.file == "hang.jpg"]
    assert hang_r and hang_r[0].error is not None and "阶段1超时" in hang_r[0].error
    assert "死锁占满" not in (hang_r[0].error or ""), "单图挂起未耗尽池，不该标耗尽文案"
    for name in ("good1.jpg", "good2.jpg"):
        g = [r for r in results if r.file == name]
        assert g and g[0].error is None, "好图不应被超时误伤"


def test_phase1_pool_exhaustion_rebuild_then_serial_for_never_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """workers=2 全部被死锁图占满（leaked>=max_workers）时先重建一代池重提交
    未决图（替代旧实现"直接统一标 死锁占满"的批死语义）；若重建后仍未决图
    （本例 queued 在两代中都永不派发，重建救不回）则继续走 MED-4 零完成串行
    回退，串行重跑全量后健康图正常出分。
    （旧断言 queued 标"死锁占满"对应已被替换的批死语义，重建行为见下方两个
    rebuild 用例；本用例改写自旧 test_phase1_pool_exhaustion_marks_pending_error。）"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang1 = _write_jpg(tmp_path, "hang1.jpg", 0)
    hang2 = _write_jpg(tmp_path, "hang2.jpg", 1)
    queued = _write_jpg(tmp_path, "queued.jpg", 2)
    pools = _install_fake_pool(
        monkeypatch,
        {
            hang1: {"hang": True},
            hang2: {"hang": True},
            # 两代池容量语义下都永不派发：重建救不回，最终走串行回退
            queued: {"running": False},
        },
    )

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths([hang1, hang2, queued])
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, "重建 + 串行回退必须有界返回而非二次挂起"
    assert len(results) == 3
    assert len(pools) == 2, f"应先重建一代池再串行回退（非串行直退）: 实际 {len(pools)} 代"
    # 串行回退重跑全量，真实引擎对有效 jpg 正常评分：三张图全部出分
    assert all(r.error is None for r in results), (
        f"串行回退后全部图应正常出分: {[(r.file, r.error) for r in results]}"
    )


def test_phase1_pool_rebuild_rescues_queued_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[增强类] workers=2 全部被死锁图占满（leaked>=max_workers）时，看门狗应强杀
    worker、重建新一代进程池并只重提交未决图，排队图在重建后正常出分，而非被
    统一标"进程池被死锁占满"（旧实现直接批死）。修复前该用例失败（增强类红灯）。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang1 = _write_jpg(tmp_path, "hang1.jpg", 0)
    hang2 = _write_jpg(tmp_path, "hang2.jpg", 1)
    queued = _write_jpg(tmp_path, "queued.jpg", 2)
    pools = _install_fake_pool(
        monkeypatch,
        {
            hang1: {"hang": True},
            hang2: {"hang": True},
            # 第 1 代池容量语义下永不派发；重建后的第 2 代立即完成
            queued: lambda gen: {} if gen >= 1 else {"running": False},
        },
    )

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths([hang1, hang2, queued])
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, "重建路径必须快速返回而非二次挂起"
    assert len(results) == 3
    for name in ("hang1.jpg", "hang2.jpg"):
        h = [r for r in results if r.file == name]
        assert h and "阶段1超时" in (h[0].error or "") and "死锁占满" not in (h[0].error or "")
    queued_r = [r for r in results if r.file == "queued.jpg"]
    assert queued_r and queued_r[0].error is None, (
        f"重建后排队图应正常出分而非被判死: {queued_r[0].error!r}"
    )
    assert len(pools) == 2, f"应恰好重建 1 次池（2 代）而非串行回退: 实际 {len(pools)} 代"


def test_phase1_pool_rebuild_limit_bounds_all_hang_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[增强类] 8 张全挂起图、workers=2：每代 leaked=2 触发重建，重建额度
    （_POOL_REBUILD_LIMIT=2）耗尽后剩余 pending 图仍统一标"死锁占满"且整批
    有界返回；已超时的图各自标单图超时，不与被判死文案混淆。"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    paths = [_write_jpg(tmp_path, f"hang{i}.jpg", i) for i in range(8)]
    # 每代（gen，0 起）仅前 2*(gen+1) 张图置 running 并挂起，模拟 2 worker 容量：
    # 第 1 代 hang0/hang1 挂起、hang2-hang7 排队；重建后滚动前推
    plans = {
        p: (lambda gen, idx=i: {"hang": True} if idx < 2 * (gen + 1) else {"running": False})
        for i, p in enumerate(paths)
    }
    _install_fake_pool(monkeypatch, plans)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths(paths)
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, "重建额度耗尽后必须有界返回而非二次挂起"
    assert len(results) == 8
    assert all(r.error is not None for r in results), "全挂起批所有图都应被标 error"
    timed_out = [
        r for r in results if "阶段1超时" in (r.error or "") and "死锁占满" not in (r.error or "")
    ]
    exhausted = [r for r in results if "死锁占满" in (r.error or "")]
    # 3 代各隔离 2 张单图超时；额度耗尽后剩余 2 张被判死
    assert len(timed_out) == 6, f"前 6 张应单图超时隔离: {[(r.file, r.error) for r in timed_out]}"
    assert len(exhausted) == 2, (
        f"重建额度耗尽后剩余 2 张应标死锁占满: {[(r.file, r.error) for r in exhausted]}"
    )


def test_phase1_pool_total_wedge_falls_back_to_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """池整体卡死（如 initializer 挂起：所有 future 永不 running 永不完成）且
    零完成（MED-4）时，看门狗必须在宽限期后改走串行回退而非整批标 error——
    串行路径有逐图看门狗，健康图正常出分；整批仍须有界返回。
    （旧断言"全部标 死锁占满 error"对应 exhausted 收尾；零完成回退语义见
    hybrid_scorer 看门狗 stalled 分支。）"""
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    paths = [_write_jpg(tmp_path, f"img_{i}.jpg", i) for i in range(3)]
    _install_fake_pool(monkeypatch, {p: {"running": False} for p in paths})

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths(paths)
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, "池整体卡死必须有界返回（宽限期 + 串行回退）"
    assert len(results) == 3
    # 零完成卡死 → 串行回退：真实引擎对有效图正常评分，不再整批 error 占位
    assert all(r.error is None for r in results), (
        f"零完成卡死应回退串行重跑而非整批标 error: {[(r.file, r.error) for r in results]}"
    )


def test_phase1_fake_pool_terminate_escalates_to_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拆池阶段 terminate 未生效的 worker 必须升级为 kill，且 join 带上界超时。

    覆盖 hybrid_scorer 的 973-978（升级强杀）判定本身。此前该分支的唯一覆盖来自
    @slow 真进程池用例的计时偶然（2026-10-23 的 12 腿 CI 产物里只有 ubuntu-py3.10
    命中，其余 11 腿 974/978 常年 Missing），且那条用例断言墙钟有界、从不检查
    强杀是否发生——删掉 proc.kill() 也不会变红。桩驱动后三平台一致、不依赖计时，
    因此不打 slow：12 条腿与 make test 都必须跑到。
    """
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang = _write_jpg(tmp_path, "hang.jpg", 0)
    good = _write_jpg(tmp_path, "good.jpg", 1)
    pools = _install_fake_pool(
        monkeypatch,
        {
            hang: {"hang": True},
            good: {},
            "__procs__": [{"survive_terminate": True}],
        },
    )

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    start = time.monotonic()
    results = scorer.score_paths([hang, good])
    assert time.monotonic() - start < 10.0, "升级 kill 后整批仍须有界返回"

    hang_r = next(r for r in results if r.file == "hang.jpg")
    assert hang_r.error is not None and "阶段1超时" in hang_r.error

    stub = pools[0]._processes[1]
    assert stub.terminated is True, "拆池必须先走 terminate"
    assert stub.join_timeout == hs._TERMINATE_JOIN_SEC, (
        "terminate 后的 join 必须带 _TERMINATE_JOIN_SEC 上界，不得无限等待"
    )
    assert stub.killed is True, "is_alive() 仍为真时必须升级为 kill 强杀挂起 worker"


def test_phase1_fake_pool_teardown_oserror_race_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拆池时 worker 已抢先退出（terminate 抛 OSError）必须就地吞掉、不得外泄。

    覆盖 hybrid_scorer 的 979-982 兜底：该 except 分支存在的意义是「不得掩盖在途
    异常」（如 BrisqueIntegrityError 经 finally 向外传播），此前 12 条腿均未覆盖。
    反例面：竞态后不应继续升级 kill，也不应把 OSError 冒泡成整批失败。
    """
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 0.3)
    hang = _write_jpg(tmp_path, "hang.jpg", 0)
    good = _write_jpg(tmp_path, "good.jpg", 1)
    pools = _install_fake_pool(
        monkeypatch,
        {
            hang: {"hang": True},
            good: {},
            "__procs__": [{"raise_on": "terminate"}],
        },
    )

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    results = scorer.score_paths([hang, good])

    assert len(results) == 2, "竞态兜底不得让批次丢图或抛出"
    stub = pools[0]._processes[1]
    assert stub.killed is False, "terminate 已抛 OSError，不应继续走到 kill"


# ---------- 阶段1 真实进程池拆除（挂起 worker 强杀）集成 ----------


@pytest.mark.slow
@pytest.mark.parametrize("hang_count", [1, 5])
def test_phase1_real_pool_hung_worker_teardown_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hang_count: int
) -> None:
    """真实进程池 + 真实挂起子进程：看门狗标 error 占位后，挂起的 worker 必须
    在拆池阶段被强制终止，score_paths 有界返回。旧实现只标记不终止，
    with/__exit__ 的 shutdown(wait=True) 会因挂起工作项永不完成而无限阻塞
    （管理线程 join 与 _join_executor_internals 的 p.join() 均无超时），整批
    永久挂死。hang_count=1 覆盖 leaked 未达阈值、不触发重建的正常收尾路径；
    hang_count=5（2 worker，in-flight 容量 = 2 worker + call_queue(max_workers+1)=3
    共 5 槽）让 5 张挂起图占满全部槽位：leaked>=max_workers 触发池代际重建
    （强杀 worker 后重提交未决图），good1 在重建后正常出分（替代旧实现的
    "死锁占满"批死），剩余挂起图在后续代中被逐图隔离——覆盖重建路径在真实
    spawn 池下确定性可达。"""
    # 15s：兼顾「挂起图尽早隔离」与「重载下好图不被误标」——连续全量回归时
    # Windows 真实进程 spawn/调度延迟可叠加数秒，5s 余量不足会把先提交的好图
    # 误标「阶段1超时」（负载下实测偶发，leaked=4+1）；15s 仍远小于 60s 有界上界。
    monkeypatch.setattr(hs, "PER_IMAGE_TIMEOUT_SEC", 15.0)
    monkeypatch.setattr(hs, "_init_cv_engine", _noop_pool_init)
    monkeypatch.setattr(hs, "_evaluate_cv_and_portrait", _hang_or_score_worker)
    # 好图排第一：尽快产生完成事件，压低 spawn 期间"整体无进展"分支误触发面
    names = ["good0.jpg"] + [f"__hang__{i}.jpg" for i in range(hang_count)] + ["good1.jpg"]
    paths = [_write_jpg(tmp_path, n, i) for i, n in enumerate(names)]

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    box: list[list[ImageScore]] = []
    errors: list[Exception] = []

    def _run() -> None:
        try:
            box.append(scorer.score_paths(paths))
        except Exception as e:  # noqa: BLE001 — 线程内异常带回主线程断言，避免吞掉
            errors.append(e)

    # 修复后最坏 3 代 × 15s 超时 + 多次 spawn 开销，60s 余量不足；120s 仍远
    # 小于修复前旧实现的无限阻塞，且只是等待上界而非断言弱化（good1 断言实际加强）。
    runner = threading.Thread(target=_run, daemon=True)
    runner.start()
    runner.join(timeout=120.0)
    assert not runner.is_alive(), "score_paths 未在有界时间返回：挂起 worker 未被终止，池拆除仍挂死"
    assert not errors, f"score_paths 抛出异常: {errors!r}"
    results = box[0]

    assert len(results) == len(paths)
    hang_r = [r for r in results if "__hang__" in r.file]
    assert len(hang_r) == hang_count
    if hang_count == 1:
        # 未达重建阈值：与旧行为一致，单图超时隔离
        assert all(
            "阶段1超时" in (r.error or "") and "死锁占满" not in (r.error or "") for r in hang_r
        ), f"挂起图应单图超时隔离: {[(r.file, r.error) for r in hang_r]}"
    else:
        # 重建语义下每张挂起图都在某一代中被逐图隔离，不再有"死锁占满"批死
        assert all(
            "阶段1超时" in (r.error or "") and "死锁占满" not in (r.error or "") for r in hang_r
        ), f"挂起图应全部被逐图隔离: {[(r.file, r.error) for r in hang_r]}"
    good0 = [r for r in results if r.file == "good0.jpg"]
    assert good0 and good0[0].error is None, "先提交的好图必须正常评分"
    good1 = [r for r in results if r.file == "good1.jpg"]
    if hang_count == 1:
        assert good1 and good1[0].error is None, "未占满池时好图不应被超时误伤"
        assert scorer.phase1_stats["rebuilds"] == 0, "leaked 未达阈值不应触发池代际重建"
    else:
        # 【不在此钉 good1 必须出分】ProcessPoolExecutor 的 future.running() 在进入
        # call_queue 时即为真，看门狗 deadline 从那一刻起算，因此重建后的新一代里
        # good1 可能与 ≥2 张挂起图同代派发并共享同一 deadline 而被连带标「阶段1超时」；
        # 是否落入该分支取决于 _HUNG_POLL_SEC=1s 的轮询粒度与 pending 集合
        # （hybrid_scorer.py 重建处）的迭代顺序，真实 spawn 池下非确定性——2026-10-23
        # macos-latest py3.13 腿即如此。「重建后排队图正常出分」由确定性假池用例
        # test_phase1_pool_rebuild_rescues_queued_images 钉死（12 腿与 make test 都跑），
        # 本用例的独有贡献是「真实 spawn + terminate 下拆除有界」，改由 rebuilds 指纹
        # 证明重建代确实跑过（修复前从未断言）。
        assert good1 and "死锁占满" not in (good1[0].error or ""), (
            f"重建语义下好图不得被整批判死: {good1[0].error!r}"
        )
        assert scorer.phase1_stats["rebuilds"] >= 1, "5 张挂起占满 2 worker 必须触发池代际重建"


# ---------- 阶段1 真实进程池：供应链信号跨进程传播 集成 ----------


@pytest.mark.slow
def test_brisque_integrity_real_pool_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实 spawn 进程池端到端：worker initializer 置位共享 multiprocessing.Event
    并抛 BrisqueIntegrityError（池转 BrokenProcessPool）→ 父进程在 BrokenProcessPool
    分类处读到置位标志 → score_paths 响亮抛出。fake 池无法覆盖的两点由本用例钉死：
    ① multiprocessing.Event 可经 spawn initargs pickle 传入子进程；② worker 内
    置位对父进程可见。信号不依赖任何任务触发模型加载，与投毒场景的实际时序一致。"""
    paths = [_write_jpg(tmp_path, f"r{i}.jpg", i) for i in range(2)]
    monkeypatch.setattr(hs, "_init_cv_engine", _brisque_flag_init_broken)

    scorer = HybridScorer(CVEngine(), None, _config(directory=str(tmp_path), workers=2, top=10))
    with pytest.raises(BrisqueIntegrityError):
        scorer.score_paths(paths)

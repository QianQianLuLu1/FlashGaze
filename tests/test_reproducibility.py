"""可复现性测试。

核心指标：同一张图连续运行 10 次，分数完全一致（VLM 关闭时）。
这是 FlashGaze 的核心承诺——Agent 可重复调用得到稳定结果。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config
from flashgaze.utils.config import build_config

FLASHGAZE_CMD = [sys.executable, "-m", "flashgaze"]


# ---------- CV 层可复现 ----------


def test_cv_sharpness_10_runs_identical(sharp_img: str) -> None:
    """清晰度 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_sharpness(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"清晰度不稳定: {scores}"


def test_cv_exposure_10_runs_identical(sharp_img: str) -> None:
    """曝光度 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_exposure(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"曝光度不稳定: {scores}"


def test_cv_composition_10_runs_identical(sharp_img: str) -> None:
    """构图分 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"构图分不稳定: {scores}"


def test_cv_evaluate_10_runs_identical(sharp_img: str) -> None:
    """evaluate 完整结果 10 次调用完全一致。"""
    engine = CVEngine(enable_composition=True)
    results = [engine.evaluate(sharp_img) for _ in range(10)]
    base = results[0]
    for r in results[1:]:
        assert r.sharpness == base.sharpness
        assert r.exposure == base.exposure
        assert r.composition == base.composition
        assert r.error == base.error


# ---------- CV 增强维度可复现（M10）----------


def test_cv_color_10_runs_identical(colorful_img: str) -> None:
    """色彩丰富度 10 次调用结果完全一致（OpenCV 内置，必可用）。"""
    engine = CVEngine(enable_color=True)
    results = [engine.evaluate(colorful_img) for _ in range(10)]
    base = results[0]
    for r in results[1:]:
        assert r.color == base.color, f"色彩丰富度不稳定: {[r.color for r in results]}"
    # 顺便验证其他维度也保持一致
    for r in results[1:]:
        assert r.sharpness == base.sharpness
        assert r.exposure == base.exposure


def test_hybrid_scorer_with_color_10_runs_identical(sharp_img: str, blurry_img: str) -> None:
    """启用 color 维度后，HybridScorer no_vlm 模式下 10 次评分完全一致。"""
    config = Config(
        directory=".",
        no_vlm=True,
        top=2,
        enable_color=True,
    )
    scorer = HybridScorer(CVEngine(enable_color=True), None, config)
    runs = [scorer.score_batch(str(Path(sharp_img).parent)) for _ in range(10)]
    base = [(r.file, r.score, r.color) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score, r.color) for r in run] == base


# ---------- HybridScorer 可复现 ----------


def test_hybrid_scorer_10_runs_identical_no_vlm(sharp_img: str, blurry_img: str) -> None:
    """no_vlm 模式下，HybridScorer 10 次评分完全一致。"""
    config = Config(directory=".", no_vlm=True, top=2)
    scorer = HybridScorer(CVEngine(), None, config)
    runs = [scorer.score_batch(str(Path(sharp_img).parent)) for _ in range(10)]
    base = [(r.file, r.score) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score) for r in run] == base


def test_repro_custom_weights_missing_enabled_dim_no_vlm(
    sharp_img: str, blurry_img: str, tmp_path: Path
) -> None:
    """自定义权重缺 composition key + 启用 composition：10 次 --no-vlm 一致且含 composition 加权。

    评分口径变更（PLAN-weight-injection）：注入后权重 0.56/0.24/0.20，
    最终分按此加权，且可复现性承诺不受影响。
    """
    for f in (Path(sharp_img), Path(blurry_img)):
        shutil.copy2(f, tmp_path / f.name)
    cfg = build_config(
        directory=str(tmp_path),
        enable_composition=True,
        weights={"sharpness": 0.7, "exposure": 0.3},
        no_vlm=True,
        workers=1,
    )
    scorer = HybridScorer(CVEngine(enable_composition=True), None, cfg)
    runs = [scorer.score_batch(str(tmp_path)) for _ in range(10)]
    base = [(r.file, r.score) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score) for r in run] == base
    # 含 composition 加权（而非 0.7*s + 0.3*e）
    for r in runs[0]:
        if r.error is None and r.composition is not None:
            expected = round(0.56 * r.sharpness + 0.24 * r.exposure + 0.20 * r.composition, 2)
            assert r.score == expected


# ---------- CLI 端到端可复现 ----------


def test_cli_e2e_10_runs_identical_json(fixtures_dir: Path, tmp_path: Path) -> None:
    """subprocess 调用 CLI 10 次，JSON 输出（除 elapsed_ms 外）完全一致。"""
    # 准备测试目录
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)

    import os

    env = os.environ.copy()
    env.pop("FLASHGAZE_API_KEY", None)

    outputs: list[str] = []
    for _ in range(10):
        result = subprocess.run(
            FLASHGAZE_CMD + [str(tmp_path), "--no-vlm", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            encoding="utf-8",
            check=False,  # 返回码由下方 assert 统一断言
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # 移除 elapsed_ms（时间相关，必然波动）
        data["summary"].pop("elapsed_ms", None)
        outputs.append(json.dumps(data, sort_keys=True))

    assert len(set(outputs)) == 1, "CLI 10 次输出不一致（除 elapsed_ms 外）"


# ---------- VLM 层可复现（采样参数固定，PLAN-vlm-sampling-reproducibility）----------


def test_vlm_payload_sampling_stable_across_runs(
    sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一 client 连续两次 judge 的请求体采样参数完全一致（temperature/seed 固定）。

    [增强类] 修复前 payload 不含采样参数，断言键缺失即失败（红灯）。
    """
    from unittest.mock import MagicMock

    import requests

    from flashgaze.core.vlm_client import VLMClient
    from flashgaze.models.schemas import CVResult

    payloads: list[dict[str, Any]] = []

    def fake_post(*a: object, **kw: object) -> MagicMock:
        payloads.append(kw.get("json") or {})  # type: ignore[arg-type]
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {}
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": '{"adjustment": 1.0, "reason": "ok"}'}}]
        }
        return resp

    monkeypatch.setattr("flashgaze.core.vlm_client.requests.Session.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    cv = CVResult(sharpness=80.0, exposure=70.0)
    client.judge(sharp_img, cv)
    client.judge(sharp_img, cv)
    assert len(payloads) == 2
    assert payloads[0]["temperature"] == payloads[1]["temperature"] == 0.0
    assert payloads[0]["seed"] == payloads[1]["seed"] == 42

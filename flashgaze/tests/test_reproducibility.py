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

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config

FLASHGAZE_CMD = [sys.executable, "-m", "flashgaze"]


# ---------- CV 层可复现 ----------

def test_cv_sharpness_10_runs_identical(sharp_img: str):
    """清晰度 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_sharpness(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"清晰度不稳定: {scores}"


def test_cv_exposure_10_runs_identical(sharp_img: str):
    """曝光度 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_exposure(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"曝光度不稳定: {scores}"


def test_cv_composition_10_runs_identical(sharp_img: str):
    """构图分 10 次调用结果完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"构图分不稳定: {scores}"


def test_cv_evaluate_10_runs_identical(sharp_img: str):
    """evaluate 完整结果 10 次调用完全一致。"""
    engine = CVEngine(enable_composition=True)
    results = [engine.evaluate(sharp_img) for _ in range(10)]
    base = results[0]
    for r in results[1:]:
        assert r.sharpness == base.sharpness
        assert r.exposure == base.exposure
        assert r.composition == base.composition
        assert r.error == base.error


# ---------- HybridScorer 可复现 ----------

def test_hybrid_scorer_10_runs_identical_no_vlm(sharp_img: str, blurry_img: str):
    """no_vlm 模式下，HybridScorer 10 次评分完全一致。"""
    config = Config(directory=".", no_vlm=True, top=2)
    scorer = HybridScorer(CVEngine(), None, config)
    runs = [
        scorer.score_batch(str(Path(sharp_img).parent)) for _ in range(10)
    ]
    base = [(r.file, r.score) for r in runs[0]]
    for run in runs[1:]:
        assert [(r.file, r.score) for r in run] == base


# ---------- CLI 端到端可复现 ----------

def test_cli_e2e_10_runs_identical_json(fixtures_dir: Path, tmp_path: Path):
    """subprocess 调用 CLI 10 次，JSON 输出（除 elapsed_ms 外）完全一致。"""
    # 准备测试目录
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)

    import os
    env = os.environ.copy()
    env.pop("FLASHGAZE_API_KEY", None)

    outputs = []
    for _ in range(10):
        result = subprocess.run(
            FLASHGAZE_CMD + [str(tmp_path), "--no-vlm", "--json"],
            capture_output=True, text=True, env=env, timeout=120, encoding="utf-8",
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # 移除 elapsed_ms（时间相关，必然波动）
        data["summary"].pop("elapsed_ms", None)
        outputs.append(json.dumps(data, sort_keys=True))

    assert len(set(outputs)) == 1, "CLI 10 次输出不一致（除 elapsed_ms 外）"

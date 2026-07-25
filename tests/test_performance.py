"""性能基准测试。

用 @pytest.mark.slow 标记，可通过 --skip-slow 跳过。
基准阈值基于开发机典型表现设定，回归时供参考。

- 批量评分 100 张图（--no-vlm）≤ 30s
- 单张图 base64 编码 ≤ 1s
- 单张图 CV 评估 ≤ 500ms
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config
from flashgaze.utils.image_io import encode_image_b64

# 4 张 fixture 图复制 25 份凑够 100 张
_BATCH_SOURCE_FILES = ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg")
_COPIES_PER_FILE = 25  # 4 * 25 = 100


@pytest.fixture
def batch_100_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """在临时目录下生成 100 张图片（4 张 fixture 各复制 25 份）。"""
    for name in _BATCH_SOURCE_FILES:
        src = fixtures_dir / name
        if not src.exists():
            continue
        stem, ext = src.stem, src.suffix
        for i in range(_COPIES_PER_FILE):
            dst = tmp_path / f"{stem}_{i:03d}{ext}"
            shutil.copy2(src, dst)
    return str(tmp_path)


# ── 性能基准 ─────────────────────────────────────────


@pytest.mark.slow
def test_batch_scoring_100_images_under_30s(batch_100_dir: str):
    """100 张图 --no-vlm 批量评分耗时不超过 30 秒。"""
    config = Config(directory=batch_100_dir, no_vlm=True, top=30)
    scorer = HybridScorer(CVEngine(), None, config)

    start = time.perf_counter()
    results = scorer.score_batch(batch_100_dir)
    elapsed = time.perf_counter() - start

    assert len(results) == 100, f"期望 100 张结果，实际 {len(results)}"
    assert elapsed < 30.0, f"批量评分 100 张耗时 {elapsed:.2f}s 超过 30s 阈值"


@pytest.mark.slow
def test_encode_image_b64_under_1s(sharp_img: str):
    """单张图 base64 编码不超过 1 秒。"""
    # 预热：首次调用可能触发 HEIC 解码器注册等惰性初始化
    encode_image_b64(sharp_img)

    start = time.perf_counter()
    encoded = encode_image_b64(sharp_img)
    elapsed = time.perf_counter() - start

    assert isinstance(encoded, str) and len(encoded) > 0
    assert elapsed < 1.0, f"base64 编码耗时 {elapsed:.3f}s 超过 1s 阈值"


@pytest.mark.slow
def test_cv_engine_evaluate_under_500ms(sharp_img: str):
    """单张图 CV 评估（含清晰度+曝光度）不超过 500ms。"""
    engine = CVEngine()
    # 预热文件读取缓存
    engine.evaluate(sharp_img)

    start = time.perf_counter()
    result = engine.evaluate(sharp_img)
    elapsed = time.perf_counter() - start

    assert result.error is None, f"评估失败: {result.error}"
    assert elapsed < 0.5, f"CV 评估耗时 {elapsed:.3f}s 超过 500ms 阈值"

"""CVEngine 核心评分热路径基准。

覆盖 flashgaze/core/cv_engine.py 的两条主路径：
- evaluate：完整单图评分（含 Pillow 磁盘解码、灰度转换、降采样、各维度计算），
  CI PR 门禁的核心指标——历史上多次性能回归（重复解码、缩放顺序错误）都发生在这条路径；
- compute_sharpness 注入预解码数组：剥离磁盘 IO，纯度量 CV 计算，用于定位
  回归来自解码还是计算。

enable_noise（BRISQUE）不进基准：依赖 opencv-contrib extras 与模型文件，
不属于跨环境稳定基线（见 conftest.cv_engine_full 注释）。
"""

from __future__ import annotations

import cv2
from pytest_benchmark.fixture import BenchmarkFixture

from flashgaze.core.cv_engine import CVEngine
from flashgaze.utils.image_io import decode_bgr


def test_evaluate_2000x1500(
    benchmark: BenchmarkFixture, cv_engine_full: CVEngine, large_jpeg: str
) -> None:
    """大图完整单图评分（构图 + 色彩全开，含解码与降采样）。"""
    result = benchmark.pedantic(
        cv_engine_full.evaluate, args=(large_jpeg,), rounds=8, warmup_rounds=1
    )
    # evaluate 失败时返回带 error 的 CVResult 且耗时近零，必须断言成功才算有效基准
    assert result.error is None


def test_evaluate_512x384(
    benchmark: BenchmarkFixture, cv_engine_full: CVEngine, small_jpeg: str
) -> None:
    """小图完整单图评分（低于归一化尺寸 1024，走无降采样分支）。"""
    result = benchmark.pedantic(
        cv_engine_full.evaluate, args=(small_jpeg,), rounds=8, warmup_rounds=1
    )
    assert result.error is None


def test_compute_sharpness_inmemory(
    benchmark: BenchmarkFixture, cv_engine_full: CVEngine, small_jpeg: str
) -> None:
    """纯计算路径：注入预解码灰度图，剥离磁盘 IO 只度量 CV 算子。"""
    gray = cv2.cvtColor(decode_bgr(small_jpeg), cv2.COLOR_BGR2GRAY)
    score = benchmark(cv_engine_full.compute_sharpness, small_jpeg, gray)
    # 噪声图拉普拉斯方差高，得分为正即可证明计算真实发生
    assert score > 0

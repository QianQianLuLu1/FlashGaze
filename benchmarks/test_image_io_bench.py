"""图片 IO 热路径基准（flashgaze/utils/image_io.py）。

- decode_bgr：全项目统一解码入口（Pillow），每张图评分的第一步；
- downscale_if_needed：INTER_AREA 降采样，4K → 2048 触发阈值分支；
- encode_bgr_b64：VLM 请求体编码路径（resize + JPEG + base64）；
- iter_images：目录扫描（os.walk + 过滤 + 排序）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pytest_benchmark.fixture import BenchmarkFixture

from flashgaze.utils.image_io import decode_bgr, downscale_if_needed, encode_bgr_b64, iter_images

# 4K 横幅：长边 3840 超过 DOWNSCALE_THRESHOLD(2048)，触发等比降采样
DOWNSCALE_W, DOWNSCALE_H = 3840, 2160


def test_decode_bgr_jpeg_2000x1500(benchmark: BenchmarkFixture, large_jpeg: str) -> None:
    """Pillow 解码 2000x1500 JPEG q90（含 EXIF 转正与 RGB 转换）。"""
    img = benchmark.pedantic(decode_bgr, args=(large_jpeg,), rounds=10, warmup_rounds=1)
    assert img.shape == (1500, 2000, 3)


def test_downscale_inter_area_3840(benchmark: BenchmarkFixture) -> None:
    """4K 图 INTER_AREA 等比降采样到长边 2048（纯计算，无磁盘 IO）。"""
    rng = np.random.default_rng(42)
    img = rng.integers(0, 256, (DOWNSCALE_H, DOWNSCALE_W, 3), dtype=np.uint8)
    out = benchmark(downscale_if_needed, img, 2048)
    assert max(out.shape[:2]) == 2048


def test_encode_bgr_b64_2000x1500(benchmark: BenchmarkFixture, large_jpeg: str) -> None:
    """VLM base64 编码：2000x1500 → 1024 长边 JPEG(q85) → base64（纯计算）。"""
    bgr = decode_bgr(large_jpeg)
    encoded = benchmark(encode_bgr_b64, bgr)
    assert len(encoded) > 0


def test_iter_images_scan(benchmark: BenchmarkFixture, mixed_dir: str) -> None:
    """扫描 12 张混合图的目录（os.walk + 扩展名过滤 + 排序）。"""
    found = benchmark.pedantic(lambda: list(iter_images(mixed_dir)), rounds=10, warmup_rounds=1)
    assert len(found) == 12
    assert all(Path(p).suffix == ".jpg" for p in found)

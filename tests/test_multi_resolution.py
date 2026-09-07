"""多分辨率 / 多格式固件覆盖测试。

验证 conftest 扩展固件矩阵覆盖的关键路径（全部离线，无网络）：
- 各分辨率档位（4K / 手机横竖幅 / 极端长宽比 / 阈值边界 / 小图）可解码且
  尺寸正确；长边 > DOWNSCALE_THRESHOLD(2048) 的档位触发等比降采样，
  边界(恰好 2048)与小图不触发
- 全部支持格式的 512 基准图可解码为 3 通道（灰度/调色板模式走 convert("RGB")）
- 扫描器在混合目录中找齐全部固件，含大写 .JPEG 与 .tif 别名
- 手机竖幅 + EXIF Orientation=6 大图按正向像素解码，分数与正向参考逐分一致
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flashgaze.core.cv_engine import CVEngine
from flashgaze.defaults import DOWNSCALE_THRESHOLD
from flashgaze.utils.image_io import decode_bgr, downscale_if_needed, iter_images
from tests.conftest import ResolutionImage

# 长边超过 DOWNSCALE_THRESHOLD 的大图档位（含 19.5:9 截图：长边 2532 同样超阈值）
_LARGE_RES_IDS = ["4k_landscape", "phone_landscape", "phone_portrait", "phone_screenshot"]
# 长边未超阈值的档位：恰好等于 2048 的边界 + 低于归一化尺寸的小图
_SMALL_RES_IDS = ["boundary_2048", "thumbnail"]


def test_resolution_decodes_expected_size(resolution_img: ResolutionImage) -> None:
    """各分辨率档位经 decode_bgr（Pillow 统一路径）解码后尺寸正确。"""
    img = decode_bgr(resolution_img.path)
    assert img.shape == (resolution_img.height, resolution_img.width, 3)


@pytest.mark.parametrize("resolution_img", _LARGE_RES_IDS, indirect=True)
def test_large_resolution_triggers_downscale(resolution_img: ResolutionImage) -> None:
    """长边超阈值的大图：降采样后长边等于阈值，且宽高比保持。"""
    img = decode_bgr(resolution_img.path)
    out = downscale_if_needed(img, DOWNSCALE_THRESHOLD)
    assert max(out.shape[:2]) == DOWNSCALE_THRESHOLD
    src_ratio = img.shape[1] / img.shape[0]
    out_ratio = out.shape[1] / out.shape[0]
    assert abs(out_ratio - src_ratio) / src_ratio < 0.02  # resize 取整容忍 ±2%


@pytest.mark.parametrize("resolution_img", _SMALL_RES_IDS, indirect=True)
def test_non_large_resolution_not_downscaled(resolution_img: ResolutionImage) -> None:
    """恰好等于阈值(2048)的边界图与小图：长边未超阈值，不降采样。"""
    img = decode_bgr(resolution_img.path)
    out = downscale_if_needed(img, DOWNSCALE_THRESHOLD)
    assert out.shape == img.shape


def test_cv_engine_scores_all_resolutions(resolution_img: ResolutionImage) -> None:
    """各分辨率档位都能走完 CVEngine 全维度评估，分数落在值域内且非零。"""
    result = CVEngine().evaluate(resolution_img.path)
    assert result.error is None
    assert 0.0 <= result.sharpness <= 100.0
    assert 0.0 <= result.exposure <= 100.0
    # 结构化内容含噪声与色块边缘，清晰度应非零（防"全零分数掩盖维度错误"）
    assert result.sharpness > 0.0


def test_formats_decode_to_rgb_512(format_img: str) -> None:
    """全部支持格式的基准图可解码为 3 通道 512x512。"""
    img = decode_bgr(format_img)
    assert img.shape == (512, 512, 3)


def test_mixed_dir_scanner_finds_all(mixed_photo_dir: str) -> None:
    """扫描器在混合目录中找齐全部固件（目录内文件全部命中，无一漏扫）。"""
    found = {Path(p).name for p in iter_images(mixed_photo_dir)}
    expected = {p.name for p in Path(mixed_photo_dir).iterdir() if p.is_file()}
    assert found == expected
    assert "alias_upper.JPEG" in found  # 扩展名大小写归一化
    assert "alias_tif.tif" in found  # .tif 别名
    # 6 分辨率 + 6 格式（缺 pillow-heif 时 5）+ 2 别名 + 1 EXIF 竖幅
    assert len(found) >= 15


def test_oriented_phone_decodes_upright(
    oriented_phone_img: str, oriented_phone_upright_ref_img: str
) -> None:
    """Orientation=6 手机大图解码后转正为竖幅，像素与正向参考完全一致（PNG 无损）。"""
    fixed = decode_bgr(oriented_phone_img)
    assert fixed.shape == (4032, 3024, 3)  # 高 4032、宽 3024 的竖幅
    ref = decode_bgr(oriented_phone_upright_ref_img)
    assert np.array_equal(fixed, ref), "EXIF 方向未校正：解码结果未转正"


def test_oriented_phone_scores_match_ref(
    oriented_phone_img: str, oriented_phone_upright_ref_img: str
) -> None:
    """EXIF 转正后清晰度/曝光度与正向参考逐分一致（旋转是纯像素置换）。"""
    engine = CVEngine()
    fixed = engine.evaluate(oriented_phone_img)
    ref = engine.evaluate(oriented_phone_upright_ref_img)
    assert fixed.error is None
    assert ref.error is None
    assert fixed.sharpness == ref.sharpness
    assert fixed.exposure == ref.exposure

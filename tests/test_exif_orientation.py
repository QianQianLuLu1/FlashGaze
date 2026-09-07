"""EXIF 方向校正回归测试（覆盖 decode_bgr 的 Orientation 处理）。

设计要点：
- EXIF Orientation（6/8 等）本质是对像素做 90° 旋转或镜像，二者都是纯像素置换，
  数学上严格保持「直方图」（曝光度）与「局部拉普拉斯方差场」（清晰度）不变。
  因此清晰度/曝光度在修正前、后必然相等；这两者的正确性由"修正后 == 正向参考"
  来证明。能体现 bug（方向错误）被修掉的、对方向敏感的维度是"构图"（质心/三分线），
  故"修正后 != 修正前"断言落在构图维度 + 像素层面。
- 固件用 Pillow 现造（PNG 无损），使"修正后数组 == 正向参考数组"可用 np.array_equal
  严格断言；不引入二进制、不修改 conftest.py。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import ExifTags, Image

from flashgaze.core.cv_engine import CVEngine
from flashgaze.utils.image_io import decode_bgr

ORIENTED_NAME = "oriented_orientation6.png"
UPRIGHT_REF_NAME = "oriented_upright_ref.png"

_RNG_SEED = 7
_H, _W = 480, 640


def _ensure_oriented_fixtures(fixtures_dir: Path) -> None:
    """生成 Orientation=6 固件与正向参考固件（已存在则跳过）。"""
    oriented = fixtures_dir / ORIENTED_NAME
    upright_ref = fixtures_dir / UPRIGHT_REF_NAME
    if oriented.exists() and upright_ref.exists():
        return

    rng = np.random.default_rng(_RNG_SEED)
    # 非对称正向图 U：竖直渐变 + 随机高频，旋转后构图（质心）明显不同
    grad = np.linspace(0, 255, _H, dtype=np.float64)[:, None]  # 竖直渐变
    noise = rng.integers(0, 40, size=(_H, _W), dtype=np.uint8).astype(np.float64)
    U = np.clip(grad + noise, 0, 255).astype(np.uint8)
    U = np.stack([U] * 3, axis=-1)  # (H, W, 3) 正向

    # 参考正向图：无损保存，作为"正确答案"对照
    Image.fromarray(U).save(str(upright_ref))

    # 存储图 S：把 U 逆时针旋转 90°，并打上 Orientation=6（显示时需顺时针转正）
    S = np.ascontiguousarray(np.rot90(U, k=1))  # 逆时针 90°
    s_img = Image.fromarray(S)
    exif = s_img.getexif()
    exif[ExifTags.Base.Orientation] = 6
    s_img.save(str(oriented), exif=exif)


@pytest.fixture(scope="session")
def oriented_fixtures(fixtures_dir: Path) -> Path:
    """session 级：确保 Orientation=6 固件已生成，返回 fixtures 目录。"""
    _ensure_oriented_fixtures(fixtures_dir)
    return fixtures_dir


def test_decode_bgr_applies_exif_orientation(oriented_fixtures: Path) -> None:
    """Orientation=6 图片经 decode_bgr 后，像素应等于正向参考图（无损 PNG）。"""
    fixed = decode_bgr(str(oriented_fixtures / ORIENTED_NAME))
    ref = decode_bgr(str(oriented_fixtures / UPRIGHT_REF_NAME))
    assert fixed.shape == ref.shape
    assert np.array_equal(fixed, ref), "EXIF 方向未校正：解码结果未转正"


def test_orientation_changes_score_vs_pre_fix(oriented_fixtures: Path, tmp_path: Path) -> None:
    """修正后分数应 == 正向参考（全维度）；且相对"修正前"确有方向修正。"""
    engine = CVEngine(enable_composition=True)
    oriented_path = str(oriented_fixtures / ORIENTED_NAME)
    upright_path = str(oriented_fixtures / UPRIGHT_REF_NAME)

    # 修正后（走 decode_bgr + exif_transpose）
    fixed = engine.evaluate(oriented_path)
    # 正向参考（正确答案）
    ref = engine.evaluate(upright_path)

    # 1) 修正后分数 == 正向参考（所有维度）。
    #    清晰度/曝光度对旋转不敏感（纯置换不变），构图依赖方向（质心/三分线）。
    #    三者同时相等，证明修复给出了"正确像素上"的正确分数。
    assert fixed.sharpness == ref.sharpness, "修正后清晰度应等于正向参考"
    assert fixed.exposure == ref.exposure, "修正后曝光度应等于正向参考"
    assert fixed.composition == ref.composition, "修正后构图应等于正向参考"

    # 2) 模拟旧逻辑：只读不旋转（绕过 exif_transpose）
    with Image.open(oriented_path) as im:
        raw_bgr = np.array(im.convert("RGB"))[:, :, ::-1].copy()
    raw_path = str(tmp_path / "raw.png")
    Image.fromarray(raw_bgr[:, :, ::-1]).save(raw_path)  # 存回以便 evaluate
    buggy = engine.evaluate(raw_path)

    # 3) 证明确有方向修正：构图依赖方向（旋转后质心相对三分线移动）必然改变；
    #    且解码像素层面修正后 != 修正前。
    assert fixed.composition != buggy.composition, "修正后与修正前构图应不同"
    assert not np.array_equal(decode_bgr(oriented_path), raw_bgr), (
        "修正前后像素应不同（修复已生效）"
    )


def test_no_orientation_tag_is_noop(fixtures_dir: Path) -> None:
    """无 Orientation 标签的图，decode_bgr 像素不变（幂等保护）。"""
    p = str(fixtures_dir / "sharp.jpg")  # cv2 生成的既有固件，无 EXIF
    with Image.open(p) as im:
        expected = np.array(im.convert("RGB"))[:, :, ::-1].copy()
    assert np.array_equal(decode_bgr(p), expected), "无标签图不应被改动"

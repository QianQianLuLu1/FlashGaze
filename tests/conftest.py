"""pytest 公共 fixtures。

测试图在 session 开始时用 numpy + cv2 生成，保证可复现且无需提交二进制文件。
- sharp.jpg：高频随机噪声（高拉普拉斯方差）
- blurry.jpg：强高斯模糊（低方差）
- dark.jpg：全黑图（D3 用，曝光度低分）
- corrupted.jpg：纯文本伪装成 jpg（D8 异常用例）
- colorful.jpg：多色块图（高饱和度多色相，M3 色彩丰富度用）
- gray.jpg：纯灰图（饱和度=0，M3 色彩丰富度对照用）
- duplicate_a.jpg / duplicate_b.jpg：完全相同的两张图（M5 去重用）
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RNG_SEED = 42  # 固定种子，保证生成图可复现


def _ensure_fixtures() -> None:
    """按需生成测试 fixture 图。已存在则跳过。"""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    sharp = FIXTURES_DIR / "sharp.jpg"
    if not sharp.exists():
        rng = np.random.default_rng(RNG_SEED)
        # 高频噪声：每个像素独立随机，拉普拉斯方差极大
        noise = rng.integers(0, 256, size=(512, 512), dtype=np.uint8)
        cv2.imwrite(str(sharp), noise)

    blurry = FIXTURES_DIR / "blurry.jpg"
    if not blurry.exists():
        rng = np.random.default_rng(RNG_SEED)
        noise = rng.integers(0, 256, size=(512, 512), dtype=np.uint8)
        # 强高斯模糊：方差会大幅下降
        blurred = cv2.GaussianBlur(noise, (51, 51), 0)
        cv2.imwrite(str(blurry), blurred)

    dark = FIXTURES_DIR / "dark.jpg"
    if not dark.exists():
        # 全黑图，D3 曝光度测试用
        black = np.zeros((512, 512), dtype=np.uint8)
        cv2.imwrite(str(dark), black)

    corrupted = FIXTURES_DIR / "corrupted.jpg"
    if not corrupted.exists():
        # 伪装成 jpg 的纯文本，解码必失败
        corrupted.write_text("this is not a real image", encoding="utf-8")

    colorful = FIXTURES_DIR / "colorful.jpg"
    if not colorful.exists():
        # 多色块图：6 个色块，高饱和度多色相，色彩丰富度高
        # BGR 格式（OpenCV 默认）
        blocks = [
            ((0, 0, 255), (0, 0)),       # 红
            ((0, 255, 0), (256, 0)),     # 绿
            ((255, 0, 0), (0, 256)),     # 蓝
            ((0, 255, 255), (256, 256)), # 黄
            ((255, 0, 255), (128, 128)), # 品红
            ((255, 255, 0), (200, 50)),  # 青
        ]
        img = np.zeros((512, 512, 3), dtype=np.uint8)
        for color, (x, y) in blocks:
            img[y:y+256, x:x+256] = color
        cv2.imwrite(str(colorful), img)

    gray = FIXTURES_DIR / "gray.jpg"
    if not gray.exists():
        # 纯灰图：饱和度=0，色彩丰富度应为 0
        img = np.full((512, 512, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(gray), img)

    # 完全相同的两张图，用于 PHash 去重测试
    dup_a = FIXTURES_DIR / "duplicate_a.jpg"
    dup_b = FIXTURES_DIR / "duplicate_b.jpg"
    if not dup_a.exists() or not dup_b.exists():
        rng = np.random.default_rng(RNG_SEED + 1)
        noise = rng.integers(0, 256, size=(256, 256), dtype=np.uint8)
        cv2.imwrite(str(dup_a), noise)
        cv2.imwrite(str(dup_b), noise.copy())  # 完全一致的另一份


@pytest.fixture(scope="session", autouse=True)
def fixtures_dir() -> Path:
    """session 级自动 fixture：确保测试图已生成，返回目录。"""
    _ensure_fixtures()
    return FIXTURES_DIR


@pytest.fixture
def sharp_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "sharp.jpg")


@pytest.fixture
def blurry_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "blurry.jpg")


@pytest.fixture
def dark_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "dark.jpg")


@pytest.fixture
def corrupted_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "corrupted.jpg")


@pytest.fixture
def colorful_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "colorful.jpg")


@pytest.fixture
def gray_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "gray.jpg")


@pytest.fixture
def duplicate_a_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "duplicate_a.jpg")


@pytest.fixture
def duplicate_b_img(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "duplicate_b.jpg")

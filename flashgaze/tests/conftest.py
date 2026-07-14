"""pytest 公共 fixtures。

测试图在 session 开始时用 numpy + cv2 生成，保证可复现且无需提交二进制文件。
- sharp.jpg：高频随机噪声（高拉普拉斯方差）
- blurry.jpg：强高斯模糊（低方差）
- dark.jpg：全黑图（D3 用，曝光度低分）
- corrupted.jpg：纯文本伪装成 jpg（D8 异常用例）
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

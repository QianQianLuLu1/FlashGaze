"""基准套件公共 fixtures。

基准语料在 session 开始时按固定种子生成（算法与 tools/bench/make_images.py
一致：linspace 底图 + 种子噪声，JPEG q90），保证跨机器、跨次运行可复现。
quick 语料（large/small/batch_small）写入 pytest 临时目录；bench_full 的 100
张大图复用 tools/bench/images/（由 make_images.py 生成、CI 经 actions/cache
缓存），缺失时兜底现场生成。所有图片不入库。

与 tests/ 的关系：基准放在独立顶层目录 benchmarks/，`pytest tests/`（CI test
job 与本地默认命令）完全不会收集到本目录；运行方式见 docs/bench/README.md。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# 种子与 tools/bench/make_images.py 一致；不同语料间偏移避免相互重复
RNG_SEED = 42
# 拟真大图：贴近 tools/bench/make_images.py 的 2000x1500，长边 < DOWNSCALE_THRESHOLD(2048)
LARGE_WIDTH, LARGE_HEIGHT = 2000, 1500
LARGE_COUNT = 4
# 小图：低于 SHARPNESS_NORMALIZE_SIZE(1024)，覆盖小图评分路径
SMALL_WIDTH, SMALL_HEIGHT = 512, 384
SMALL_COUNT = 8
# quick 批量：20 张小图，单轮秒级；full 批量：100 张大图，对齐 docs/bench 历史口径
BATCH_SMALL_COUNT = 20
BATCH_FULL_COUNT = 100


def _make_image(path: Path, width: int, height: int, rng: np.random.Generator, tint: int) -> None:
    """生成一张拟真基准图（linspace 底图 + 噪声，JPEG q90）。

    与 tools/bench/make_images.py 同款算法：B/G 通道做横向/纵向渐变，R 通道用
    tint 区分不同图，再叠加 [0,40) 均匀噪声。高频噪声保证拉普拉斯方差非退化。
    """
    base = np.zeros((height, width, 3), dtype=np.uint8)
    base[:, :, 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    base[:, :, 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    base[:, :, 2] = tint
    img = cv2.add(base, rng.integers(0, 40, (height, width, 3), dtype=np.uint8))
    if not cv2.imwrite(str(path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 90]):
        raise OSError(f"基准图生成失败: {path}")


def _make_corpus(directory: Path, count: int, width: int, height: int, seed: int) -> list[Path]:
    """在 directory 下生成 count 张基准图，返回按文件名排序的路径列表。"""
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    paths = []
    for i in range(count):
        p = directory / f"img_{i:03d}.jpg"
        _make_image(p, width, height, rng, tint=(i * 2) % 256)
        paths.append(p)
    return paths


@pytest.fixture(scope="session")
def bench_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """基准语料根目录（session 级，所有基准共享）。"""
    return tmp_path_factory.mktemp("benchmarks")


@pytest.fixture(scope="session")
def large_images(bench_root: Path) -> list[Path]:
    """4 张 2000x1500 拟真大图。"""
    return _make_corpus(bench_root / "large", LARGE_COUNT, LARGE_WIDTH, LARGE_HEIGHT, RNG_SEED)


@pytest.fixture(scope="session")
def small_images(bench_root: Path) -> list[Path]:
    """8 张 512x384 小图（种子偏移，避免与大图语料重复）。"""
    return _make_corpus(
        bench_root / "small", SMALL_COUNT, SMALL_WIDTH, SMALL_HEIGHT, RNG_SEED + 1000
    )


@pytest.fixture(scope="session")
def large_jpeg(large_images: list[Path]) -> str:
    """单图基准用的大图路径（取第一张）。"""
    return str(large_images[0])


@pytest.fixture(scope="session")
def small_jpeg(small_images: list[Path]) -> str:
    """单图基准用的小图路径（取第一张）。"""
    return str(small_images[0])


@pytest.fixture(scope="session")
def mixed_dir(bench_root: Path, large_images: list[Path], small_images: list[Path]) -> str:
    """12 张大小混合图的目录，供目录扫描（iter_images）基准使用。

    复制而非重新生成：内容与大/小语料逐字节一致，省去重复编码开销。
    大小语料文件名同为 img_NNN.jpg，复制时加前缀避免互相覆盖。
    """
    mixed = bench_root / "mixed"
    mixed.mkdir(parents=True, exist_ok=True)
    for src in large_images:
        shutil.copy2(src, mixed / f"large_{src.name}")
    for src in small_images:
        shutil.copy2(src, mixed / f"small_{src.name}")
    return str(mixed)


@pytest.fixture(scope="session")
def batch_small_dir(bench_root: Path) -> str:
    """20 张小图的批量评分目录（quick 基准）。"""
    corpus = _make_corpus(
        bench_root / "batch_small", BATCH_SMALL_COUNT, SMALL_WIDTH, SMALL_HEIGHT, RNG_SEED + 2000
    )
    return str(corpus[0].parent)


@pytest.fixture(scope="session")
def batch_full_dir(bench_root: Path) -> str:
    """100 张 2000x1500 大图的批量评分目录（bench_full，仅 nightly 生成）。

    优先复用 tools/bench/images/（由 tools/bench/make_images.py 产出，CI 中经
    actions/cache 缓存）；该目录不存在（本地首次运行或缓存未命中）时，调用
    make_images.generate() 兜底生成到同级 images/，保证本地与 CI 行为统一。
    """
    # tools/bench/images/，相对仓库根（benchmarks/ 的父目录）
    images_dir = Path(__file__).resolve().parents[1] / "tools" / "bench" / "images"
    if not images_dir.is_dir() or not any(images_dir.glob("img_*.jpg")):
        try:
            from tools.bench.make_images import generate
        except ImportError:
            # 不在仓库根运行时回退到源码相对路径导入
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from tools.bench.make_images import generate
        print(f"[batch_full] tools/bench/images 缺失，兜底生成 {BATCH_FULL_COUNT} "
              f"张 {LARGE_WIDTH}x{LARGE_HEIGHT} 基准图（约 10-20 秒）...")
        generate(images_dir)
    else:
        print(f"[batch_full] 复用缓存的 tools/bench/images（{len(list(images_dir.glob('img_*.jpg')))} 张）")
    return str(images_dir)


@pytest.fixture(scope="session")
def cv_engine_full():
    """开启全部非外部依赖维度的 CVEngine（构图 + 色彩，不启用 BRISQUE 噪点）。

    不启用 enable_noise：BRISQUE 依赖 opencv-contrib 与模型文件，会让基准
    job 依赖 cv-enhanced extras 且引入模型加载开销；噪点维度不属于稳定基线。
    """
    from flashgaze.core.cv_engine import CVEngine

    return CVEngine(enable_composition=True, enable_color=True)

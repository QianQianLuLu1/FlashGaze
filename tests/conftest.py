"""pytest 公共 fixtures。

测试图在 session 开始时用 numpy + cv2 生成，保证可复现且无需提交二进制文件。
- sharp.jpg：高频随机噪声（高拉普拉斯方差）
- blurry.jpg：强高斯模糊（低方差）
- dark.jpg：全黑图（D3 用，曝光度低分）
- corrupted.jpg：纯文本伪装成 jpg（D8 异常用例）
- colorful.jpg：多色块图（高饱和度多色相，M3 色彩丰富度用）
- gray.jpg：纯灰图（饱和度=0，M3 色彩丰富度对照用）
- duplicate_a.jpg / duplicate_b.jpg：完全相同的两张图（M5 去重用）

多分辨率矩阵（RESOLUTION_SPECS，参数化 fixture resolution_img）：
- res_4k_landscape.jpg：3840x2160，4K 横幅，长边超 DOWNSCALE_THRESHOLD 触发降采样
- res_phone_landscape.jpg：4032x3024，12MP 手机主摄 4:3 横幅，触发降采样
- res_phone_portrait.jpg：3024x4032，手机竖幅（高>宽），验证竖幅降采样
- res_phone_screenshot.jpg：1170x2532，19.5:9 极端长宽比，同样触发降采样
- res_boundary_2048.jpg：2048x2048，恰好等于阈值边界，不应降采样
- res_thumbnail.jpg：320x240，小图（低于 SHARPNESS_NORMALIZE_SIZE）

多格式矩阵（FORMAT_SPECS，参数化 fixture format_img，512x512 同内容）：
- fmt_sharp.png/.webp/.bmp/.tiff：cv2 编码；fmt_sharp.heic：装 pillow-heif 才生成
- fmt_gray.png / fmt_palette.png：灰度与调色板模式，覆盖 decode_bgr 的 convert("RGB")
- alias_upper.JPEG / alias_tif.tif：扩展名大小写与别名，验证扫描器归一化
- oriented_phone_orientation6.png / oriented_phone_upright_ref.png：
  3024x4032 手机竖幅 + EXIF Orientation=6（旋转 90° 存储），PNG 无损保像素级断言
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
import numpy.typing as npt
import pytest
from PIL import ExifTags, Image

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RNG_SEED = 42  # 固定种子，保证生成图可复现

# 分辨率矩阵：(文件名, 宽, 高)。覆盖 4K / 手机主摄横竖幅 / 极端长宽比 /
# 降采样阈值边界 / 小图。种子偏移 +10 起避免与既有固件撞种子。
RESOLUTION_SPECS: dict[str, tuple[str, int, int]] = {
    "4k_landscape": ("res_4k_landscape.jpg", 3840, 2160),
    "phone_landscape": ("res_phone_landscape.jpg", 4032, 3024),
    "phone_portrait": ("res_phone_portrait.jpg", 3024, 4032),
    "phone_screenshot": ("res_phone_screenshot.jpg", 1170, 2532),
    "boundary_2048": ("res_boundary_2048.jpg", 2048, 2048),
    "thumbnail": ("res_thumbnail.jpg", 320, 240),
}

# 格式矩阵：文件名 → 固件路径。heic 依赖可选包 pillow-heif，缺依赖不生成，
# format_img 的 heic 参数据此 pytest.skip（与 e2e conftest 的 importorskip 思路一致）。
FORMAT_SPECS: dict[str, str] = {
    "png": "fmt_sharp.png",
    "webp": "fmt_sharp.webp",
    "bmp": "fmt_sharp.bmp",
    "tiff": "fmt_sharp.tiff",
    "heic": "fmt_sharp.heic",
    "gray_png": "fmt_gray.png",
    "palette_png": "fmt_palette.png",
}


class ResolutionImage(NamedTuple):
    """一档分辨率固件：文件路径 + 期望宽高。"""

    path: str
    width: int
    height: int


def _sharp_noise_512() -> npt.NDArray[np.uint8]:
    """与 sharp.jpg 同源的 512x512 高频噪声（灰度），供格式矩阵复用。"""
    rng = np.random.default_rng(RNG_SEED)
    return rng.integers(0, 256, size=(512, 512), dtype=np.uint8)


def _make_structured_scene(width: int, height: int, seed: int) -> npt.NDArray[np.uint8]:
    """结构化场景图（BGR）：竖直渐变 + 彩色块 + 低幅噪声。

    大分辨率固件不用纯噪声（12MP 纯噪声 JPEG 约 12MB+），结构化内容把单文件
    控制在 1-3MB；渐变/色块/噪声让曝光、色彩、清晰度维度都有非平凡分数，
    避免"全零分数掩盖维度错误"。
    """
    rng = np.random.default_rng(seed)
    grad = np.linspace(40, 215, height, dtype=np.float64)[:, None]  # 竖直渐变，避开极端曝光
    base = np.repeat(grad, width, axis=1)
    noise = rng.integers(0, 30, size=(height, width), dtype=np.uint8)
    lum = np.clip(base + noise, 0, 255).astype(np.uint8)
    img = np.stack([lum] * 3, axis=-1)  # 灰度基底，通道序无关
    # BGR 色块：四角 + 中心，提供色彩与边缘高频
    bs = max(width, height) // 8
    blocks = [
        ((0, 0, 255), (0, 0)),  # 红
        ((0, 255, 0), (width - bs, 0)),  # 绿
        ((255, 0, 0), (0, height - bs)),  # 蓝
        ((0, 255, 255), (width - bs, height - bs)),  # 黄
        ((255, 0, 255), ((width - bs) // 2, (height - bs) // 2)),  # 品红
    ]
    for color, (x, y) in blocks:
        img[y : y + bs, x : x + bs] = color
    return np.ascontiguousarray(img)


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
            ((0, 0, 255), (0, 0)),  # 红
            ((0, 255, 0), (256, 0)),  # 绿
            ((255, 0, 0), (0, 256)),  # 蓝
            ((0, 255, 255), (256, 256)),  # 黄
            ((255, 0, 255), (128, 128)),  # 品红
            ((255, 255, 0), (200, 50)),  # 青
        ]
        img = np.zeros((512, 512, 3), dtype=np.uint8)
        for color, (x, y) in blocks:
            img[y : y + 256, x : x + 256] = color
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

    # ── 分辨率矩阵：结构化场景 JPEG（SUPPORTED_EXTENSIONS 的主格式）──────
    for offset, (name, width, height) in enumerate(RESOLUTION_SPECS.values()):
        path = FIXTURES_DIR / name
        if not path.exists():
            scene = _make_structured_scene(width, height, RNG_SEED + 10 + offset)
            cv2.imwrite(str(path), scene, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # ── 格式矩阵：同一份 512 噪声内容存成不同编码格式 ──────────────────
    noise = _sharp_noise_512()
    rgb = np.stack([noise] * 3, axis=-1)  # PIL 按 RGB 通道序读取
    for ext in ("png", "webp", "bmp", "tiff"):
        path = FIXTURES_DIR / f"fmt_sharp.{ext}"
        if not path.exists():
            cv2.imwrite(str(path), noise)

    # HEIC：cv2 无法编码，须 pillow-heif（可选依赖）。缺依赖时不生成，
    # format_img 的 heic 参数据此 pytest.skip。
    heic = FIXTURES_DIR / "fmt_sharp.heic"
    if not heic.exists():
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            pass
        else:
            register_heif_opener()
            Image.fromarray(rgb).save(str(heic), format="HEIF")

    gray_png = FIXTURES_DIR / "fmt_gray.png"
    if not gray_png.exists():
        # 灰度模式（PIL mode "L"），覆盖 decode_bgr 的 convert("RGB") 路径
        Image.fromarray(noise, mode="L").save(str(gray_png))

    palette_png = FIXTURES_DIR / "fmt_palette.png"
    if not palette_png.exists():
        # 调色板模式（mode "P"），同样覆盖 convert("RGB") 路径。
        # Pillow stubs 只声明枚举形式 Image.Palette.ADAPTIVE（旧模块级别名
        # Image.ADAPTIVE 运行时仍在但无 stub），统一用规范枚举写法
        Image.fromarray(rgb).convert("P", palette=Image.Palette.ADAPTIVE).save(str(palette_png))

    # ── 扩展名别名：复制字节即可，验证扫描器的大小写与 .tif 别名归一化 ──
    alias_upper = FIXTURES_DIR / "alias_upper.JPEG"
    if not alias_upper.exists():
        shutil.copyfile(FIXTURES_DIR / "sharp.jpg", alias_upper)
    alias_tif = FIXTURES_DIR / "alias_tif.tif"
    if not alias_tif.exists():
        shutil.copyfile(FIXTURES_DIR / "fmt_sharp.tiff", alias_tif)

    # ── EXIF 方向竖幅手机图：正向内容逆时针旋转 90° 存储 + Orientation=6 ──
    # 手法与 test_exif_orientation.py 相同（PNG 无损，保住像素级断言），分辨率
    # 提升到手机级 3024x4032。内容刻意接近确定性（渐变+色块+细线，无逐像素
    # 噪声）：12MP 无损 PNG 一旦带随机噪声会膨胀到 10MB 以上。
    oriented = FIXTURES_DIR / "oriented_phone_orientation6.png"
    upright_ref = FIXTURES_DIR / "oriented_phone_upright_ref.png"
    if not oriented.exists() or not upright_ref.exists():
        w, h = 3024, 4032  # 正向竖幅：宽 3024、高 4032
        grad = np.linspace(0, 255, h, dtype=np.float64)[:, None]
        lum = np.repeat(grad, w, axis=1).astype(np.uint8)
        upright = np.stack([lum] * 3, axis=-1)
        bs = 512
        upright[512 : 512 + bs, 512 : 512 + bs] = (0, 0, 255)  # BGR 红
        upright[2560 : 2560 + bs, 1800 : 1800 + bs] = (0, 255, 0)  # 绿
        upright[3200 : 3200 + bs, 400 : 400 + bs] = (255, 255, 0)  # 青
        upright[::256, :, :] = 255  # 细线：稀疏边缘高频，清晰度非零且压缩友好
        upright[:, ::256, :] = 255
        Image.fromarray(upright).save(str(upright_ref))
        stored = np.ascontiguousarray(np.rot90(upright, k=1))  # 逆时针 90° 横幅存储
        stored_img = Image.fromarray(stored)
        exif = stored_img.getexif()
        exif[ExifTags.Base.Orientation] = 6  # 显示时顺时针转正
        stored_img.save(str(oriented), exif=exif)


@pytest.fixture(scope="session", autouse=True)
def fixtures_dir() -> Path:
    """session 级自动 fixture：确保测试图已生成，返回目录。"""
    _ensure_fixtures()
    return FIXTURES_DIR


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/dark/corrupted 到临时目录，作为评分目标。

    提到 conftest 作为共享 fixture，使 test_plugins.py 等模块单独运行时
    也能拿到 photo_dir（原先只在部分测试模块内局部定义）。
    """
    for name in ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _reset_engine_cache() -> Iterator[None]:
    """每个用例前后清空 CVEngine 进程内缓存。

    hybrid_scorer 的模块级单例会跨用例存活，不清理会造成顺序依赖的偶发失败
    （例如先跑 enable_noise=True 再跑 False 时拿到旧引擎）。
    导入放在函数体内，避免收集阶段就 import hybrid_scorer 拖慢启动。
    """
    from flashgaze.core.hybrid_scorer import _reset_cv_engine_cache

    _reset_cv_engine_cache()
    yield
    _reset_cv_engine_cache()


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


# ── 多分辨率 / 多格式 fixtures ───────────────────────────────────────────


@pytest.fixture(params=tuple(RESOLUTION_SPECS))
def resolution_img(request: pytest.FixtureRequest, fixtures_dir: Path) -> ResolutionImage:
    """参数化分辨率固件（6 档 JPEG）：4K / 手机横竖幅 / 极端长宽比 / 阈值边界 / 小图。"""
    name, width, height = RESOLUTION_SPECS[request.param]
    return ResolutionImage(path=str(fixtures_dir / name), width=width, height=height)


@pytest.fixture(params=tuple(FORMAT_SPECS))
def format_img(request: pytest.FixtureRequest, fixtures_dir: Path) -> str:
    """参数化格式固件（512x512 同内容不同编码）：PNG/WebP/BMP/TIFF/HEIC/灰度/调色板。"""
    path = fixtures_dir / FORMAT_SPECS[request.param]
    # HEIC 固件随仓库分发，但解码必须 pillow-heif（image_io 惰性注册）：
    # 「文件存在」不代表「环境能解码」，以能力守卫，否则缺依赖时
    # test_formats_decode_to_rgb_512[heic] 报 ImageReadError 而非跳过。
    if request.param == "heic":
        pytest.importorskip("pillow_heif")
    if not path.exists():
        pytest.skip(f"固件 {path.name} 未生成")
    return str(path)


@pytest.fixture
def img_4k(fixtures_dir: Path) -> str:
    """4K 横幅（3840x2160），最常用的大图档位。"""
    return str(fixtures_dir / RESOLUTION_SPECS["4k_landscape"][0])


@pytest.fixture
def phone_portrait_img(fixtures_dir: Path) -> str:
    """手机竖幅（3024x4032），竖幅降采样路径。"""
    return str(fixtures_dir / RESOLUTION_SPECS["phone_portrait"][0])


@pytest.fixture
def oriented_phone_img(fixtures_dir: Path) -> str:
    """手机竖幅 EXIF Orientation=6 图（旋转 90° 横幅存储，解码应转正）。"""
    return str(fixtures_dir / "oriented_phone_orientation6.png")


@pytest.fixture
def oriented_phone_upright_ref_img(fixtures_dir: Path) -> str:
    """EXIF 竖幅手机图的正向参考（像素级对照答案）。"""
    return str(fixtures_dir / "oriented_phone_upright_ref.png")


# 混合目录内容：全部分辨率档 + 全部格式 + 扩展名别名 + EXIF 竖幅。
# 不含正向参考图（它是对照答案，不是被扫描对象）。
_MIXED_DIR_FILES: tuple[str, ...] = (
    *[spec[0] for spec in RESOLUTION_SPECS.values()],
    *FORMAT_SPECS.values(),
    "alias_upper.JPEG",
    "alias_tif.tif",
    "oriented_phone_orientation6.png",
)


@pytest.fixture
def mixed_photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制全部多分辨率/多格式固件到临时目录，供批量扫描/评分测试。

    只复制实际存在的文件（heic 可能因缺 pillow-heif 未生成）。
    与 photo_dir 互不影响：photo_dir 保持 4 张图不变，既有批量测试的
    数量断言不受新增固件影响。
    """
    for name in _MIXED_DIR_FILES:
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)

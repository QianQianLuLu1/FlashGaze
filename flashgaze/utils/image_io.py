"""图片 IO 工具。

统一处理图片读取、格式校验、损坏检测。CVEngine 与 VLMClient 都依赖此模块，
避免业务层重复处理异常。

解码像素预算（H-7）：导入本模块会把 Pillow 的全局 `Image.MAX_IMAGE_PIXELS`
收紧为项目上限（`defaults.MAX_IMAGE_PIXELS`，可用 `FLASHGAZE_MAX_IMAGE_PIXELS`
覆盖、置 0 关闭）。这是**刻意的进程级副作用**——解压炸弹只需一个几十字节的
文件即可声明上亿像素、让解码分配数百 MB，收紧全局阈值是唯一能同时覆盖本进程
全部 `Image.open` 调用点的手段。作为库被嵌入且需自有阈值时，可在 import 后
自行重设 `Image.MAX_IMAGE_PIXELS`，或把环境变量置 0 关闭本上限。
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image, ImageOps, UnidentifiedImageError

from flashgaze.defaults import ENV_MAX_IMAGE_PIXELS, MAX_IMAGE_PIXELS, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class ImageReadError(Exception):
    """图片读取失败（损坏、不支持、无法解码）。"""


def max_image_pixels() -> int:
    """当前解码像素上限（H-7）。

    每次调用读取 `ENV_MAX_IMAGE_PIXELS`，便于运行期与测试期覆盖：
    - 未设置 → 回退 `MAX_IMAGE_PIXELS`；
    - 非法（非整数）→ 记一次 WARNING 后回退 `MAX_IMAGE_PIXELS`；
    - `0` 或负数 → 关闭项目上限，交由 Pillow 自带阈值兜底（100MP+ 中画幅逃生舱）。

    注意：`Image.MAX_IMAGE_PIXELS` 在导入期一次性设定，运行期改环境变量只影响
    本函数返回的预检阈值，不改变 Pillow 的全局值。
    """
    raw = os.environ.get(ENV_MAX_IMAGE_PIXELS)
    if raw is None or not raw.strip():
        return MAX_IMAGE_PIXELS
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r 非法，回退默认 %d", ENV_MAX_IMAGE_PIXELS, raw, MAX_IMAGE_PIXELS)
        return MAX_IMAGE_PIXELS


def _check_pixel_budget(size: tuple[int, int], path: str) -> None:
    """解码前预检像素预算（H-7）：只比较文件头尺寸，零像素分配。

    超限即抛 ImageReadError——失败必须发生在内存分配**之前**，否则「优雅降级」
    无从谈起：解压炸弹的失败发生在数百 MB 已分配之后，进程早已被打挂。

    `max_image_pixels() <= 0`（显式关闭）时直接返回，不校验。
    """
    budget = max_image_pixels()
    if budget <= 0:
        return
    width, height = size
    pixels = width * height
    if pixels <= budget:
        return
    raise ImageReadError(
        f"图片尺寸超限：{width}×{height}（{pixels} 像素）超过上限 {budget} 像素，"
        f"已跳过以避免解压炸弹导致 OOM；如需处理请设置 {ENV_MAX_IMAGE_PIXELS}"
        f"=<更大值>（置 0 关闭本上限、沿用 Pillow 自带阈值）: {path}"
    )


# 收紧 Pillow 的全局解压炸弹阈值（H-7，进程级副作用，依据见模块 docstring）。
# 仅当解析到正上限时设置：置 0 表示显式关闭，保留 Pillow 自带阈值。
if max_image_pixels() > 0:
    Image.MAX_IMAGE_PIXELS = max_image_pixels()


# HEIC 解码器惰性注册状态（进程级幂等，仅在实际解码 HEIC 时触发）
_heif_registered = False
# 缺依赖时的一次性提示标记，避免批量评分时逐图刷屏
_heif_warned = False


def _ensure_heif_support() -> None:
    """惰性注册 HEIC/HEIF 解码器，幂等。

    register_heif_opener() 是进程级全局注册，会影响整个 Python 进程的 Pillow
    行为。作为库被其他代码导入时，应在实际需要时才注册，避免副作用。
    pillow-heif 未安装时记录一次提示，由 decode_bgr 抛出 ImageReadError。
    """
    global _heif_registered, _heif_warned
    if _heif_registered:
        return
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _heif_registered = True
    except ImportError:
        # pillow-heif 未安装，HEIC 解码会失败并由 decode_bgr 报错；
        # 仅提示一次，避免批量评分时每张 HEIC 都刷屏。
        if not _heif_warned:
            _heif_warned = True
            logger.warning(
                "检测到 HEIC/HEIF 文件但缺少 pillow-heif，已降级跳过该格式。"
                '如需支持 HEIC/HEIF，请运行：pip install -e ".[heic]"'
            )


def _maybe_register_heif(path: str) -> None:
    """路径为 HEIC/HEIF 时触发解码器注册。"""
    if path.lower().endswith((".heic", ".heif")):
        _ensure_heif_support()


def is_supported_image(path: str | Path) -> bool:
    """判断文件是否为支持的图片格式（按扩展名）。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


# Windows 目录联接（junction/mount point）的 reparse tag。junction 不是符号链接
# ——`is_symlink()`/`os.path.islink()` 对其恒为 False，`os.walk(followlinks=False)`
# 在 Windows 上仍会进入，故扫描层需按 lstat 的 reparse tag 显式识别。用字面量而非
# `stat.IO_REPARSE_TAG_MOUNT_POINT` 以兼容 py3.10（该常量 3.13 才引入）；
# `st_reparse_tag` 自 3.8 起在 Windows 的 os.lstat 结果上可用，非 Windows 无此属性。
_IO_REPARSE_TAG_MOUNT_POINT = 0xA000_0003


def _is_junction(path: str | Path) -> bool:
    """判断路径是否为 Windows 目录联接（junction）：lstat 读 reparse tag，不跟随目标。

    非 Windows 平台恒为 False（os.name 短路，零开销）；lstat 失败（竞态删除等）
    返回 False，交由后续 resolve/stat/解码 error 路径兜底，不新增异常分支。断链
    junction 的 tag 仍可由 lstat 读出，判定不受目标存在性影响。
    """
    if os.name != "nt":
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def iter_images(
    directory: str | Path,
    recursive: bool = True,
    exclude_dirs: Collection[Path] = (),
) -> Iterator[str]:
    """遍历目录下所有支持格式的图片，返回绝对路径字符串。

    默认递归扫描子目录。设 recursive=False 则只扫第一层。
    目录不存在时返回空迭代器，不抛异常——由调用方根据空结果决定返回码。

    健壮性约定（C-19/C-20 + C-01）：
    - 递归用 `os.walk(followlinks=False)`，软链接目录**不跟随**，避免软链环/越界
      导致栈溢出或扫描到 workspace 之外；如需扫描软链接目录，调用方应显式传入其真实路径。
    - 每层目录名以 "." 开头的隐藏目录（如 `.flashgaze_backup/`）整体跳过，
      避免 cleanup/export 把备份图重新评分甚至误删备份。
    - 文件名以 "." 开头的隐藏文件（`.cover.jpg`、macOS `._foo.jpg` 等）跳过，
      不污染扫描结果；文件名中间含点的普通图（photo.v2.jpg）不受影响。
    - `exclude_dirs`：额外的排除目录（如导出目录 `./精选`、EXIF 备份目录
      `.flashgaze_backup`）。凡落在其内的图片一律不产出，避免 `cleanup` 把
      精选副本或备份图重新扫描、评分并误删（C-01）。排除基于解析后的绝对路径比较，
      不区分大小写由文件系统语义决定。
    - 符号链接文件（含断链）一律不产出（H-4/M-16）：与 `followlinks=False` 的
      链接目录语义对齐——否则链接经 `resolve()` 折叠到目标本体，workspace 内链接
      导致真实图重复产出（重复评分、扭曲统计），workspace 外链接导致外部真实文件
      进入评分/EXIF/导出/删除候选，断链产出不存在路径；如需扫描链接目标，调用方应
      显式传入其真实路径。硬链接不是符号链接，不受影响。
    - junction（Windows 目录联接）与符号链接同语义（M-16 同类残留）：junction
      目录不进入、junction 条目一律不产出（含断链）——junction 不是符号链接，
      `is_symlink()` 恒为 False 且 `followlinks=False` 挡不住，扫描层按 reparse
      tag 显式排除。如需扫描联接目标，调用方应显式传入其真实路径。非递归分支
      中 junction 是目录条目，`is_file()` 恒 False，天然不产出。
    """
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return

    exts = SUPPORTED_EXTENSIONS
    # 解析为绝对路径，凡落入其内的图片一律不产出（C-01）
    exclude = [Path(d).resolve() for d in exclude_dirs]

    def _is_excluded(p: Path) -> bool:
        if not exclude:
            return False
        try:
            rp = p.resolve()
        except OSError:
            return False
        for d in exclude:
            try:
                rp.relative_to(d)
                return True
            except ValueError:
                continue
        return False

    def _gen() -> Iterator[Path]:
        if recursive:
            # followlinks=False：软链接目录不跟随，杜绝环递归/越界扫描
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # 原地裁剪 dirnames：以 "." 开头的隐藏目录整体不递归；junction
                # （Windows 目录联接）不被 is_symlink 识别、followlinks=False 挡
                # 不住，一并裁剪——「链接目录不跟随」语义对 junction 同样成立，
                # 杜绝重复产出、越界扫描与联接环导致的扫描不终止
                dirnames[:] = [
                    d
                    for d in dirnames
                    if not d.startswith(".") and not _is_junction(Path(dirpath) / d)
                ]
                for fname in filenames:
                    if fname.startswith("."):
                        continue  # 跳过隐藏文件（.cover.jpg / ._foo.jpg 等）
                    p = Path(dirpath) / fname
                    if _is_excluded(p):
                        continue
                    if p.suffix.lower() not in exts:
                        continue
                    if p.is_symlink() or _is_junction(p):
                        # 符号链接/junction 条目不产出（H-4/M-16 及其 junction
                        # 同类，含断链）：lstat 判定，防止 resolve 折叠到目标
                        # 本体/越界产出，见 docstring 约定。实测完好与断链
                        # junction 均被 os.walk 归入 dirnames（上方已裁剪），
                        # 此处为不可访问目标等边缘形态的纵深防御
                        continue
                    yield p
        else:
            for entry in root.iterdir():
                if (
                    not entry.is_symlink()  # 链接文件不产出（H-4/M-16，含断链）
                    and entry.is_file()
                    and not entry.name.startswith(".")
                    and entry.suffix.lower() in exts
                ):
                    if _is_excluded(entry):
                        continue
                    yield entry

    # 先按扩展名过滤、再统一排序：避免把目录/非图片条目一并收集进内存排序，
    # 超大目录（数十万文件）下降低内存峰值，同时保留全量排序以保证可复现。
    for p in sorted(_gen()):
        yield str(p.resolve())


def decode_bgr(path: str) -> npt.NDArray[np.uint8]:
    """统一用 Pillow 解码为 BGR（原生支持 Unicode 路径），消除双解码器漂移。

    cv2.imread 在 Windows 下遇到中文/全角括号等 Unicode 路径会返回 None，
    回退到 Pillow 会让两条解码路径的像素值差 ±1(uint8)，破坏 --no-vlm 的
    逐位可复现性。因此所有解码一律走 Pillow，cv2 仅用于确定的色彩转换/缩放。

    H-7：解码前先按文件头尺寸做像素预算预检（见 `_check_pixel_budget`），超限
    抛 ImageReadError；Pillow 对「超过 2 倍上限」的图抛的 DecompressionBombError
    只继承 Exception（既非 OSError 也非 RuntimeError，下方原有 except 抓不到），
    在此一并转换，避免退化成误导性的「CV 评估失败」。
    """
    _maybe_register_heif(path)
    try:
        # with 目标命名 src：exif_transpose/convert 返回 Image 而非 ImageFile，
        # 复用同名变量会让 mypy 按首个绑定推断成 ImageFile
        with Image.open(path) as src:
            _check_pixel_budget(src.size, path)  # 预检：零像素分配
            img = ImageOps.exif_transpose(src)  # 校正 EXIF 方向，手机旋转图按正向像素评分
            img = img.convert("RGB")
            # 注：审查报告 H-7 建议把这里的 np.array 换成 np.asarray 以消除二次
            # 拷贝。Pillow 12.2 实测不成立——其 __array_interface__ 返回的是
            # tobytes() 产出的 bytes 副本（np.asarray 结果的 base 是 bytes，
            # 而非指向 Pillow 内部缓冲的视图），两条写法的解码峰值完全等同
            # （5000×5000 实测 143.28 vs 143.20 MiB）。故维持原写法，避免
            # 引入无收益的改动。真正的峰值约束由上方 _check_pixel_budget 提供。
            return np.array(img)[:, :, ::-1].copy()  # RGB -> BGR
    except Image.DecompressionBombError as e:
        raise ImageReadError(f"图片尺寸超限（Pillow 解压炸弹保护），已跳过: {e}") from e
    except (UnidentifiedImageError, OSError) as e:
        raise ImageReadError(f"图片解码失败: {e}") from e


def downscale_if_needed(
    img: npt.NDArray[np.uint8], max_long_side: int | None
) -> npt.NDArray[np.uint8]:
    """长边超过 max_long_side 时按比例等比缩小，返回新数组（原数组不动）。

    仅用于内部评分降采样，绝不修改原图片文件。max_long_side 为 None 或
    长边未超阈值时原样返回。INTER_AREA 是 OpenCV 推荐的下采样插值，
    能有效抑制锯齿，保留原图高频信息的相对强弱关系。
    """
    if max_long_side is None:
        return img
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side <= max_long_side:
        return img
    scale = max_long_side / long_side
    new_size = (int(w * scale), int(h * scale))
    # cv2 stubs 把 resize 返回宽化为 integer|floating 泛型；实际保持输入
    # dtype uint8 不变（下采样不引入浮点），用 cast 恢复语义准确的类型。
    return cast(npt.NDArray[np.uint8], cv2.resize(img, new_size, interpolation=cv2.INTER_AREA))


def load_image_color(path: str, max_long_side: int | None = None) -> npt.NDArray[np.uint8]:
    """读取彩色图（BGR，OpenCV 约定）。失败抛 ImageReadError。

    max_long_side 设定时，长边超过该值的图在内存中按比例缩小（不修改原文件），
    用于降低大图评分时的内存峰值。默认 None 表示按原分辨率加载。
    """
    img = decode_bgr(path)
    return downscale_if_needed(img, max_long_side)


def load_image_grayscale(path: str, max_long_side: int | None = None) -> npt.NDArray[np.uint8]:
    """读取灰度图。失败抛 ImageReadError。

    max_long_side 设定时，长边超过该值的图在内存中按比例缩小（不修改原文件）。
    """
    color = decode_bgr(path)
    img = cast(npt.NDArray[np.uint8], cv2.cvtColor(color, cv2.COLOR_BGR2GRAY))
    return downscale_if_needed(img, max_long_side)


def encode_image_b64(path: str, max_size: int = 1024) -> str:
    """将图片编码为 base64（供 VLM API 调用）。

    超过 max_size 的图按比例缩小，避免请求体过大。
    编码后立即释放原图数组引用，降低并发评分内存峰值。
    """
    color = load_image_color(path)
    h, w = color.shape[:2]
    scale = min(1.0, max_size / max(h, w))
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        # 缩放后立即释放原数组，避免同时持有原图与缩放图；
        # cast 同 downscale_if_needed：cv2 stubs 宽化返回类型，实际仍为 uint8。
        color = cast(
            npt.NDArray[np.uint8], cv2.resize(color, new_size, interpolation=cv2.INTER_AREA)
        )
    ok, buf = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 85])
    del color  # 释放 BGR 数组，降低并发内存峰值
    if not ok:
        raise ImageReadError("JPEG 编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def encode_bgr_b64(bgr: npt.NDArray[np.uint8], max_size: int = 1024) -> str:
    """对已在内存的 BGR 数组编码为 base64（供 VLM），与 encode_image_b64 同款参数。

    与 encode_image_b64(path) 的唯一区别是跳过磁盘解码：调用方已持有 BGR 数组
    （如 worker 内只解码一次后复用），直接复用避免主进程阶段 2 重复读盘。
    resize / 质量参数保持一致，保证 VLM 请求体逐字节等价。
    """
    h, w = bgr.shape[:2]
    scale = min(1.0, max_size / max(h, w))
    color = bgr
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        # cast 同 downscale_if_needed：cv2 stubs 宽化返回类型，实际仍为 uint8。
        color = cast(npt.NDArray[np.uint8], cv2.resize(bgr, new_size, interpolation=cv2.INTER_AREA))
    ok, buf = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 85])
    del color
    if not ok:
        raise ImageReadError("JPEG 编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")

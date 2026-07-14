"""图片 IO 工具。

统一处理图片读取、格式校验、损坏检测。CVEngine 与 VLMClient 都依赖此模块，
避免业务层重复处理异常。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from flashgaze.defaults import SUPPORTED_EXTENSIONS


class ImageReadError(Exception):
    """图片读取失败（损坏、不支持、无法解码）。"""


def is_supported_image(path: str | Path) -> bool:
    """判断文件是否为支持的图片格式（按扩展名）。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def iter_images(directory: str | Path) -> Iterator[str]:
    """遍历目录下所有支持格式的图片，返回绝对路径字符串。

    非递归（仅当前目录）。目录不存在时返回空迭代器，不抛异常——
    由调用方根据空结果决定返回码。
    """
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_file() and is_supported_image(p):
            yield str(p.resolve())


def _decode_with_pillow(path: str) -> np.ndarray:
    """Pillow 兜底解码（OpenCV 对 WebP / 损坏 JPEG 可能失败）。"""
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            return np.array(img)[:, :, ::-1].copy()  # RGB -> BGR
    except (UnidentifiedImageError, OSError) as e:
        raise ImageReadError(f"Pillow 解码失败: {e}") from e


def load_image_color(path: str) -> np.ndarray:
    """读取彩色图（BGR，OpenCV 约定）。失败抛 ImageReadError。"""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        # OpenCV 失败，用 Pillow 兜底
        img = _decode_with_pillow(path)
    return img


def load_image_grayscale(path: str) -> np.ndarray:
    """读取灰度图。失败抛 ImageReadError。"""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        color = _decode_with_pillow(path)
        img = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    return img


def encode_image_b64(path: str, max_size: int = 1024) -> str:
    """将图片编码为 base64（供 VLM API 调用）。

    超过 max_size 的图按比例缩小，避免请求体过大。
    """
    color = load_image_color(path)
    h, w = color.shape[:2]
    scale = min(1.0, max_size / max(h, w))
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        color = cv2.resize(color, new_size, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ImageReadError("JPEG 编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")

"""CVEngine：客观评分引擎。

清晰度（拉普拉斯方差 + 尺寸归一化）、曝光度（直方图分布 + 均值偏差）、构图（三分法，实验性）。
可选维度：噪点（BRISQUE 无参考 IQA）、色彩丰富度（HSV 直方图分布）。
所有方法对同一图片多次调用结果恒定（无随机性），保证可复现。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    # 仅类型检查期导入（运行时不执行）。importlib.resources.abc 为 3.11 新增模块，
    # mypy python_version=3.10 目标下不可用，故改用等价协议类 importlib.abc.Traversable
    # （3.9 起可用，与前者是同一协议）；mypy 目标升到 3.11+ 后可换回 importlib.resources.abc。
    from importlib.abc import Traversable

import cv2
import numpy as np
import numpy.typing as npt

from flashgaze.defaults import (
    DOWNSCALE_THRESHOLD,
    ENV_BRISQUE_ALLOW_DOWNLOAD,
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    SHARPNESS_NORMALIZE_SIZE,
    SHARPNESS_VARIANCE_CEIL,
)
from flashgaze.models.schemas import CVResult
from flashgaze.utils.image_io import (
    ImageReadError,
    decode_bgr,
    downscale_if_needed,
    load_image_color,
    load_image_grayscale,
)

logger = logging.getLogger(__name__)

# 模块级探测 BRISQUE 依赖（opencv-contrib-python 的 cv2.quality.QualityBRISQUE）
# 基础 opencv-python 不含此模块，缺失时 compute_noise 返回 None，不阻塞主流程。
_BRISQUE_API: Any | None = None
_BRISQUE_MODEL_DIR: Traversable | None = None
try:
    from cv2.quality import QualityBRISQUE  # 基础 opencv 无此模块时经 overrides 忽略导入

    _BRISQUE_API = QualityBRISQUE
    # 包内资源目录：用 importlib.resources.files() 按包的导入位置解析，
    # 与进程当前工作目录无关。可编辑安装（源码目录）与 wheel 安装（site-packages）都正确。
    from importlib.resources import files as _package_files

    _BRISQUE_MODEL_DIR = _package_files("flashgaze.models") / "brisque"
except Exception:  # noqa: BLE001 — 依赖缺失/资源定位异常一律降级，绝不阻塞 import
    # 依赖缺失或资源定位异常，一律降级，绝不阻塞 import flashgaze
    _BRISQUE_API = None
    _BRISQUE_MODEL_DIR = None

_BRISQUE_FILENAMES = ("brisque_model_live.yml", "brisque_range_live.yml")

# 官方来源写死为常量，绝不与任何用户输入拼接，杜绝 SSRF 与路径穿越。
# 注意路径是 opencv_contrib/modules/quality/samples/ —— 这两个文件从不在
# opencv_extra 仓库里（已核对其 master 全量文件树，无任何 brisque 条目）。
_BRISQUE_BASE_URL = (
    "https://raw.githubusercontent.com/opencv/opencv_contrib/master/modules/quality/samples"
)
_BRISQUE_DOWNLOAD_TIMEOUT = 10.0
# 正常模型 ~570KB；超过 10MB 一律视为异常响应，避免挂起或被投毒的大文件写盘
_BRISQUE_MAX_BYTES = 10 * 1024 * 1024

# 官方模型文件的 SHA256，钉死在代码里，运行时只做本地比对。
# 【维护须知】这两个值由开发者用 sha256sum 计算官方模型后填入，命令见
# flashgaze/models/brisque/README.md：
#     sha256sum brisque_model_live.yml brisque_range_live.yml   # Linux
#     shasum -a 256 ...                                          # macOS
#     certutil -hashfile brisque_model_live.yml SHA256           # Windows
# 纪律：必须对「从官方 URL 新鲜下载」的文件计算，下载与算哈希在同一台可信机器上
# 完成，算完人工粘进来。绝不允许运行时联网获取校验值——校验值一旦与被校验物走
# 同一条信道，校验本身就失去了意义。
# 当前值：2026-08-11 对随包 flashgaze/models/brisque/ 内文件实测
# （brisque_model_live.yml 567815 字节、brisque_range_live.yml 1356 字节）。
# 上游更新导致校验失败时的处理流程见 flashgaze/models/brisque/README.md
# 「完整性校验失败（供应链信号，不降级）」一节；退出码与 except 顺序的教训见
# docs/agent-context/fixes.md §4.3（M-05）。
_BRISQUE_SHA256 = {
    "brisque_model_live.yml": "4c44c7eec9e5139830c0bb0e4a044c9cd351ba5bbc9e3798beca3243e2782ff4",
    "brisque_range_live.yml": "a18427f4f7ad087524bd0d63389649a3899b51ca6d44a4d5f8d8171f1f914a9c",
}

# 包目录不可写时（系统级 site-packages 只读）的兜底落盘位置
_BRISQUE_CACHE_DIR = Path.home() / ".cache" / "flashgaze" / "brisque"

_BRISQUE_MISSING_HINT = (
    "BRISQUE 噪点评分不可用：缺少 opencv-contrib-python 或模型文件"
    "（brisque_model_live.yml / brisque_range_live.yml）。\n"
    "  模型随包分发，正常安装无需联网；出于供应链安全考虑，本程序默认不会"
    "联网下载模型，缺失即降级。\n"
    '  解决：1) pip install -e ".[cv-enhanced]"（补依赖）；'
    "2) 按 flashgaze/models/brisque/README.md 手动下载模型并核对 SHA256（推荐）；"
    f"3) 或设 {ENV_BRISQUE_ALLOW_DOWNLOAD}=1 显式允许本次运行联网下载"
    "（下载内容仍会做 SHA256 校验，不符将直接报错而非加载）。\n"
    "  本次 noise 字段将返回 null，不阻塞其他评分维度。"
)


class BrisqueIntegrityError(RuntimeError):
    """下载内容与钉死的 SHA256 不符。这是供应链信号，绝不降级、必须向上抛。"""


# 进程内"已确认 BRISQUE 不可用"的短路缓存，同时承载失败原因（用于 WARNING 文案）。
# None = 尚未确认失败；非空字符串 = 已确认失败，值即原因。
# 仅进程内有效：Windows spawn 下每个子进程独立，这是可接受的——默认不下载后，
# 单进程的重复代价只是两次 Path.is_file()。
_BRISQUE_FAILURE: str | None = None

_REASON_NO_API = "缺少 opencv-contrib-python（cv2.quality 模块不可用）"
_REASON_NO_MODEL = (
    f"模型文件缺失，且运行时自动下载默认关闭（如需允许，设 {ENV_BRISQUE_ALLOW_DOWNLOAD}=1）"
)
_REASON_DOWNLOAD_FAILED = (
    f"模型文件缺失，{ENV_BRISQUE_ALLOW_DOWNLOAD} 已开启但下载失败（网络不可达或响应异常）"
)
_REASON_BAD_MODEL = "模型文件存在但 QualityBRISQUE 构造失败（文件可能损坏或版本不兼容）"


def _reset_brisque_state() -> None:
    """清空进程内失败缓存。供测试 fixture 调用，避免模块级状态跨用例泄漏。"""
    global _BRISQUE_FAILURE
    _BRISQUE_FAILURE = None


def _as_path(directory: Traversable | None) -> Path | None:
    """把 importlib.resources 的 Traversable 转成真实 Path；非文件系统资源返回 None。"""
    if directory is None:
        return None
    try:
        return Path(str(directory))
    except Exception:  # noqa: BLE001 — 模型文件定位失败降级为 None
        return None


def _existing_model_pair(directory: Traversable | None) -> tuple[Path, Path] | None:
    """目录下两个模型文件齐全时返回其路径，否则返回 None。"""
    base = _as_path(directory)
    if base is None:
        return None
    paths = tuple(base / name for name in _BRISQUE_FILENAMES)
    if all(p.is_file() for p in paths):
        return paths  # type: ignore[return-value]
    return None


def _fetch_model_file(url: str, dest: Path, expected_sha256: str) -> None:
    """下载单个模型文件到 dest，SHA256 通过后才落盘。

    校验顺序由廉价到昂贵：HTTP 状态码 → 大小上限 → FileStorage 头 → SHA256。
    异常契约：内容与 expected_sha256 不符抛 BrisqueIntegrityError（供应链信号，
    调用方不得降级）；其余失败抛 OSError 等，由调用方统一降级。

    关键不变式：哈希在内存中的 payload 上计算，落盘发生在校验之后，
    因此校验失败时既不会写出脏文件，也不会残留 .part。
    """
    request = urllib.request.Request(url, headers={"User-Agent": "flashgaze-brisque-fetch"})
    with urllib.request.urlopen(request, timeout=_BRISQUE_DOWNLOAD_TIMEOUT) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError(f"HTTP {response.status}")
        payload = response.read(_BRISQUE_MAX_BYTES + 1)
    if len(payload) > _BRISQUE_MAX_BYTES:
        raise OSError(f"响应体超过 {_BRISQUE_MAX_BYTES} 字节上限")
    # GitHub 对错误路径返回 200 + HTML 页面，直接落盘会写出一个"看起来存在"
    # 但永远加载失败的假模型。校验 FileStorage 头，宁可不写也不写脏文件。
    # 哈希校验严格强于头校验，此处保留纯粹为了诊断质量：拿到 404 页面时，
    # "不是 YAML" 比 "哈希不符" 更能让人立刻想到"URL 挂了"而不是"我被攻击了"。
    if not payload.startswith(b"%YAML"):
        raise OSError("响应体不是 OpenCV FileStorage YAML，疑似错误页面")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise BrisqueIntegrityError(
            f"BRISQUE 模型完整性校验失败，已拒绝落盘：{url}\n"
            f"  期望 SHA256: {expected_sha256}\n"
            f"  实际 SHA256: {actual}（{len(payload)} 字节）\n"
            "  可能是上游文件已更新，也可能是响应被篡改。请人工核实来源后再更新 "
            "_BRISQUE_SHA256，切勿直接放行。"
        )
    # FIX(#4a-1): 临时文件改用 atomic_write 同款的 `.{name}.tmp.{pid}` 命名，
    # 使其能被 cleanup_stale_tmp 的 `^\..*\.tmp\.\d+$` 正则识别并回收；
    # 下载在 write_bytes 与 replace 之间中断/崩溃时残留可被后续运行清理。
    tmp = dest.with_name(f".{dest.name}.tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    tmp.replace(dest)  # 原子替换，避免半截文件被后续运行当成有效模型


def _download_model_pair(directory: Path | None) -> tuple[Path, Path] | None:
    """把缺失的模型文件下载到 directory。

    异常分级（与"任一失败即 None"的直觉不同，务必注意）：
    BrisqueIntegrityError 会穿透本函数向上抛——对着可能被投毒的源换目录重试
    毫无意义；其余失败返回 None，交由上层换目录或降级。
    """
    if directory is None:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for name in _BRISQUE_FILENAMES:
        dest = directory / name
        if dest.is_file():
            continue
        try:
            # 用下标而非 .get()：将来往 _BRISQUE_FILENAMES 加文件却忘了加哈希，
            # 就该在开发期 KeyError 炸掉，而不是拿 None 静默跳过校验。
            _fetch_model_file(f"{_BRISQUE_BASE_URL}/{name}", dest, _BRISQUE_SHA256[name])
        except BrisqueIntegrityError:
            raise
        except Exception:  # noqa: BLE001 — 模型加载失败降级为 None
            return None
    return _existing_model_pair(directory)


def _download_allowed() -> bool:
    """是否允许运行时联网下载模型。默认否；只有明确的肯定值才放行。

    每次调用实时读 os.environ，不在 import 时快照：测试可直接 monkeypatch.setenv
    控制，进程池 spawn 的子进程继承环境变量后行为也一致。每进程只调一次，无性能顾虑。
    """
    raw = os.environ.get(ENV_BRISQUE_ALLOW_DOWNLOAD, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_model_pair() -> tuple[Path, Path] | None:
    """定位可用的模型文件：进程内短路 → 包目录 → 用户缓存 → 下载（仅在开关开启时）。

    正常安装（模型随包分发）在第二步即命中，全程零网络。
    BrisqueIntegrityError 向上穿透，且不写入 _BRISQUE_FAILURE——它是安全信号而非
    "降级结论"，必须每次调用都重新抛出，不能第一次报警、第二次装没事。
    """
    global _BRISQUE_FAILURE
    if _BRISQUE_FAILURE is not None:
        return None  # 本进程已确认不可用，不再重复探测（多进程各自短路）
    pair = _existing_model_pair(_BRISQUE_MODEL_DIR) or _existing_model_pair(_BRISQUE_CACHE_DIR)
    if pair is not None:
        return pair  # 已有文件就绝不联网，也不覆盖用户手动放置的模型
    if not _download_allowed():
        _BRISQUE_FAILURE = _REASON_NO_MODEL
        return None
    pair = _download_model_pair(_as_path(_BRISQUE_MODEL_DIR)) or _download_model_pair(
        _BRISQUE_CACHE_DIR
    )
    if pair is None:
        _BRISQUE_FAILURE = _REASON_DOWNLOAD_FAILED
    return pair


def _load_brisque() -> Any | None:
    """构造 BRISQUE 评分对象；依赖或模型不可用时返回 None，并记下原因。

    BrisqueIntegrityError 不捕获，让它穿过本函数继续上抛。
    """
    global _BRISQUE_FAILURE
    if _BRISQUE_API is None:
        _BRISQUE_FAILURE = _REASON_NO_API
        return None
    pair = _resolve_model_pair()
    if pair is None:
        return None
    # 必须走 create() 工厂：直接调类构造器 QualityBRISQUE(model, range) 在 OpenCV 5.0
    # 下能"构造成功"，但拿到的对象 compute() 会抛 "Unknown C++ exception"——
    # 表现成噪点分永远算不出来，且异常被 compute_noise 吞掉，极难定位。
    factory = getattr(_BRISQUE_API, "create", None) or _BRISQUE_API
    try:
        return factory(str(pair[0]), str(pair[1]))
    except Exception:  # noqa: BLE001 — BRISQUE 初始化失败标记坏模型并降级
        _BRISQUE_FAILURE = _REASON_BAD_MODEL
        return None


class CVEngine:
    """CV 客观评分引擎。"""

    # 若此处新增构造参数，必须同步扩充 hybrid_scorer._get_cv_engine 的缓存键，
    # 否则批量评分会拿到配置不符的旧引擎（静默错误评分）。
    def __init__(
        self,
        enable_composition: bool = False,
        enable_noise: bool = False,
        enable_color: bool = False,
        downscale: bool = True,
    ) -> None:
        self.enable_composition = enable_composition
        self.enable_noise = enable_noise
        self.enable_color = enable_color
        # 评分时加载图片的降采样阈值：downscale=True 时长边超 DOWNSCALE_THRESHOLD
        # 的图按比例缩小（仅内存中，不改原文件）；False 时按原分辨率加载
        self._eval_max_long_side: int | None = DOWNSCALE_THRESHOLD if downscale else None
        # BRISQUE 模型在 __init__ 中加载一次并缓存，避免 compute_noise 每次调用
        # 都重新从磁盘读取模型文件（批量评分时严重浪费 IO）。
        # 仅在 enable_noise=True 时加载；依赖或模型缺失时置 None，
        # compute_noise 将返回 None（保持原有降级行为）。
        self._brisque_obj = None
        # 计算噪声时若遇到非 cv2.error 的异常（如 NaN/栈溢出），只告警一次，
        # 避免批量评分时逐图刷屏（C-10：过宽 except 会掩盖真实错误）。
        self._noise_warn_logged = False
        if enable_noise:
            self._brisque_obj = _load_brisque()
            # 告警只在构造时打一次：批量评分逐图调用 compute_noise 会把日志刷爆
            if self._brisque_obj is None:
                logger.warning("%s\n%s", _BRISQUE_FAILURE or "原因未知", _BRISQUE_MISSING_HINT)

    def _load_eval_images(
        self, img_path: str
    ) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
        """解码一次，返回 (color_full, color, gray)。

        color_full 为全分辨率 BGR（与 load_image_color(img_path) 等价），
        供人像评分等下游复用，避免二次磁盘解码；color 与 gray 均已按
        _eval_max_long_side 降采样，供 CV 各维度评分（保持原分数不变）。

        算子顺序必须与 load_image_color / load_image_grayscale 保持一致
        （gray 先转换后降采样，color 直接降采样），否则大图评分数值会漂移：
        cvtColor 与 INTER_AREA 都会取整回 uint8，交换顺序会引入逐像素 ±1 的
        舍入差异，被拉普拉斯方差这类高频统计量直接放大。

        返回的数组由多个 compute_* 共享，任何调用方都不得原地修改。
        """
        raw = decode_bgr(img_path)
        # cv2 stubs 把 cvtColor/resize 返回宽化为 integer|floating 泛型；
        # COLOR_BGR2GRAY 与 INTER_AREA 实际保持 uint8，用 cast 恢复语义准确的类型。
        gray_in = cast(npt.NDArray[np.uint8], cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY))
        gray = downscale_if_needed(gray_in, self._eval_max_long_side)
        color = downscale_if_needed(raw, self._eval_max_long_side)
        # 保留全分辨率 raw 供下游复用（人像评分），不再 del：原 del 仅为释放峰值，
        # 如今 raw 透传给 portrait 避免其再次解码，整体内存峰值与原"cv + portrait
        # 各自解码"持平甚至更低。
        return raw, color, gray

    def _evaluate_full(self, img_path: str) -> tuple[CVResult, npt.NDArray[np.uint8] | None]:
        """对单图执行完整 CV 评估，额外返回全分辨率 BGR 数组。

        全程只解码一次，解码结果注入各 compute_*，避免逐维度重复读盘。
        CV 维度评分仍使用降采样数组（保持分数与原实现一致），返回元组的第二
        项为全分辨率 BGR（与 load_image_color(img_path) 等价），供人像评分等
        下游复用、避免二次磁盘解码；解码失败时第二项为 None。
        """
        try:
            color_full, color_img, gray = self._load_eval_images(img_path)
            gray_norm = self._normalize_size(gray)
            sharpness = self.compute_sharpness(img_path, gray=gray_norm)
            # 曝光用未归一化的 gray：现状它就没调 _normalize_size，传 gray_norm 会改变分数
            exposure = self.compute_exposure(img_path, gray=gray)
            composition = (
                self.compute_composition(img_path, img=color_img)
                if self.enable_composition
                else None
            )
            noise = self.compute_noise(img_path, gray=gray_norm) if self.enable_noise else None
            color = (
                self.compute_color_richness(img_path, img=color_img) if self.enable_color else None
            )
            return (
                CVResult(
                    sharpness=sharpness,
                    exposure=exposure,
                    composition=composition,
                    noise=noise,
                    color=color,
                ),
                color_full,
            )
        except ImageReadError as e:
            return CVResult(0.0, 0.0, None, error=str(e)), None
        except Exception as e:
            logger.exception("CV 评估失败: %s", img_path)
            return CVResult(0.0, 0.0, None, error=f"CV 评估失败: {e}"), None

    def evaluate(self, img_path: str) -> CVResult:
        """对单图执行完整 CV 评估。失败时返回带 error 的 CVResult，不抛异常。

        仅解码一次。如需复用已解码的全分辨率 BGR 数组（如人像评分），用
        evaluate_with_color 以避免下游二次解码。
        """
        cv, _ = self._evaluate_full(img_path)
        return cv

    def evaluate_with_color(self, img_path: str) -> tuple[CVResult, npt.NDArray[np.uint8] | None]:
        """同 evaluate，但额外返回全分辨率 BGR 数组（color_full）。

        color_full 与 load_image_color(img_path) 等价；解码失败时为 None。
        供人像评分等下游接收并直传 preloaded_color，消除重复解码。
        """
        return self._evaluate_full(img_path)

    def _normalize_size(self, gray: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """将图片长边缩放到 SHARPNESS_NORMALIZE_SIZE，消除分辨率对评分的影响。

        本函数必须保持幂等：evaluate 已归一化一次再注入 compute_sharpness /
        compute_noise，依赖二次调用为 no-op（长边 ≤ 上限时提前返回原对象）。
        若去掉提前返回守卫，evaluate 路径会变成双重缩放且不报错。
        """
        h, w = gray.shape[:2]
        long_side = max(h, w)
        if long_side <= SHARPNESS_NORMALIZE_SIZE:
            return gray
        scale = SHARPNESS_NORMALIZE_SIZE / long_side
        new_size = (int(w * scale), int(h * scale))
        # cast 同 _load_eval_images：cv2 stubs 宽化返回类型，实际仍为 uint8。
        return cast(npt.NDArray[np.uint8], cv2.resize(gray, new_size, interpolation=cv2.INTER_AREA))

    def compute_sharpness(self, img_path: str, gray: npt.NDArray[np.uint8] | None = None) -> float:
        """拉普拉斯方差 → 0-100。方差越大越清晰。

        先将图片长边归一化到 SHARPNESS_NORMALIZE_SIZE（默认 1024），
        再计算拉普拉斯方差，消除分辨率差异对评分的影响。
        映射：variance 0 ~ SHARPNESS_VARIANCE_CEIL 线性映射到 0 ~ 100，
        超过 CEIL 封顶 100。

        gray 传入已降采样的灰度图时复用之，不再读盘（归一化与否都可以，
        _normalize_size 幂等）；为 None 时按 img_path 自行加载。
        """
        if gray is None:
            gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
        gray = self._normalize_size(gray)
        # float() 收敛 numpy 标量类型，否则 min()/round() 推断为 numpy.floating|object
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        score = min(variance / SHARPNESS_VARIANCE_CEIL * 100.0, 100.0)
        return float(round(score, 2))

    def compute_exposure(self, img_path: str, gray: npt.NDArray[np.uint8] | None = None) -> float:
        """直方图分布 + 均值偏差 → 0-100。

        两部分综合：
        1. 中间灰度像素占比（极端暗/亮越少分越高），权重 0.6
        2. 均值偏离 127.5 的程度（越接近中间灰度分越高），权重 0.4

        比单纯中间灰度占比更能区分欠曝/过曝。

        gray 必须是已降采样但**未归一化**的灰度图——本函数不调
        _normalize_size，传归一化后的数组会改变分数。为 None 时自行加载。
        """
        if gray is None:
            gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total = hist.sum()
        if total == 0:
            return 0.0
        hist = hist / total
        # 边界语义统一为"不含阈值本身"：dark 区间 [0, DARK)，bright 区间 (BRIGHT, 255]
        # 即 DARK=30 表示 0-29 为暗，BRIGHT=225 表示 226-255 为亮
        over_dark = hist[:EXPOSURE_DARK_THRESHOLD].sum()
        over_bright = hist[EXPOSURE_BRIGHT_THRESHOLD + 1 :].sum()
        mid_ratio = 1.0 - over_dark - over_bright

        mean_val = float(gray.mean())
        mean_deviation = abs(mean_val - 127.5) / 127.5
        mean_score = max(0.0, 1.0 - mean_deviation)

        score = (mid_ratio * 0.6 + mean_score * 0.4) * 100.0
        return float(round(score, 2))

    def compute_composition(self, img_path: str, img: npt.NDArray[np.uint8] | None = None) -> float:
        """三分法（实验性）→ 0-100。

        用 Otsu 阈值分割前景并计算质心，质心越靠近三分线交点分越高。
        无法分割时返回中位分 50。

        img 传入已降采样的 BGR 彩色图时复用之，不再读盘；为 None 时自行加载。
        """
        if img is None:
            img = load_image_color(img_path, max_long_side=self._eval_max_long_side)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        moments = cv2.moments(thresh)
        if moments["m00"] == 0:
            return 50.0
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
        thirds_x = [w / 3, 2 * w / 3]
        thirds_y = [h / 3, 2 * h / 3]
        min_dist = min(abs(cx - tx) + abs(cy - ty) for tx in thirds_x for ty in thirds_y)
        diag = (w**2 + h**2) ** 0.5
        score = max(0.0, 100.0 - (min_dist / diag) * 300.0)
        return float(round(score, 2))

    def compute_noise(
        self, img_path: str, gray: npt.NDArray[np.uint8] | None = None
    ) -> float | None:
        """BRISQUE 无参考 IQA → 0-100。

        原始 BRISQUE 分数越低质量越好（典型范围 0-100），故归一化为：
            normalized = 100 - raw_score（clamp 到 [0, 100]）

        依赖缺失（opencv-contrib-python 未安装）或模型文件缺失时返回 None，
        上层逻辑应将 None 视为未评分，不参与权重计算。
        模型对象在 __init__ 中加载并缓存为 self._brisque_obj，此处直接复用，
        避免每次调用都从磁盘重新读取模型文件。

        gray 传入已降采样的灰度图时复用之，不再读盘；为 None 时自行加载。
        """
        if self._brisque_obj is None:
            return None
        try:
            if gray is None:
                gray = load_image_grayscale(img_path, max_long_side=self._eval_max_long_side)
            gray = self._normalize_size(gray)
            score = self._brisque_obj.compute(gray)[0]
            # FIX(#4b-2): BRISQUE 原始分可能为 NaN/inf（退化图等），先校验有限性，
            # 否则 100 - score 仍为 NaN 并污染下游加权评分。
            if not math.isfinite(score):
                return None
            # BRISQUE 越低质量越好，反转并 clamp
            normalized = max(0.0, min(100.0, 100.0 - float(score)))
            return round(normalized, 2)
        except cv2.error:
            # 已知可降级的异常（解码/前处理），静默返回 None 不阻塞主流程
            return None
        except Exception as e:  # noqa: BLE001 — 其余异常（NaN 等）仅告警一次后降级
            if not self._noise_warn_logged:
                self._noise_warn_logged = True
                logger.warning("BRISQUE 计算异常（已降级为 None）：%s", e)
            return None

    def compute_color_richness(
        self, img_path: str, img: npt.NDArray[np.uint8] | None = None
    ) -> float:
        """HSV 直方图分布 → 0-100。

        综合两部分：
        1. H 通道直方图熵（信息熵，反映色相分布广度），权重 0.6
        2. S 通道均值（饱和度水平），权重 0.4

        纯灰图（饱和度=0）返回 0.0。

        img 传入已降采样的 BGR 彩色图时复用之，不再读盘；为 None 时自行加载。
        """
        if img is None:
            img = load_image_color(img_path, max_long_side=self._eval_max_long_side)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, _ = cv2.split(hsv)
        # H 通道直方图熵（180 bin，OpenCV HSV 中 H 范围 0-179）
        hist_h = cv2.calcHist([h], [0], None, [180], [0, 180]).flatten()
        total = hist_h.sum()
        if total == 0:
            return 0.0
        p = hist_h / total
        p_nonzero = p[p > 0]
        entropy = -float(np.sum(p_nonzero * np.log2(p_nonzero)))
        max_entropy = float(np.log2(180))
        entropy_score = min(entropy / max_entropy * 100.0, 100.0)
        # S 通道均值归一化
        s_mean = float(s.mean())
        s_score = min(s_mean / 255.0 * 100.0, 100.0)
        score = entropy_score * 0.6 + s_score * 0.4
        return round(min(max(score, 0.0), 100.0), 2)

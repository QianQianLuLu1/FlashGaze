"""CVEngine 测试。

覆盖 sharpness / exposure / composition / evaluate / 降采样，以及 BRISQUE
模型管理机制（定位/下载/校验/加载）——全程桩掉网络与依赖，基础环境（无
opencv-contrib）也能确定性地覆盖降级与供应链校验路径。
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import cv2
import numpy as np
import numpy.typing as npt
import pytest

if TYPE_CHECKING:
    # 仅类型检查期导入（运行时不执行）。importlib.resources.abc 为 3.11 新增模块，
    # mypy python_version=3.10 目标下不可用，故改用等价协议类 importlib.abc.Traversable
    # （3.9 起可用，与前者是同一协议）；与主代码 flashgaze/core/cv_engine.py 保持一致。
    from importlib.abc import Traversable

    # typing.Self 为 3.11 新增，3.10 目标下 mypy 自身可从 typing_extensions 解析，
    # 运行时注解经 future 惰性求值，无需在依赖清单中声明该包。
    from typing_extensions import Self

from flashgaze.core import cv_engine as cvm
from flashgaze.core.cv_engine import (
    BrisqueIntegrityError,
    CVEngine,
)
from flashgaze.defaults import (
    DOWNSCALE_THRESHOLD,
    ENV_BRISQUE_ALLOW_DOWNLOAD,
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
)
from flashgaze.utils.image_io import downscale_if_needed

# ---------- 清晰度 ----------


def test_sharpness_returns_float_in_range(sharp_img: str) -> None:
    """清晰度返回 0-100 的 float。"""
    score = CVEngine().compute_sharpness(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_sharp_image_scores_higher_than_blurry(sharp_img: str, blurry_img: str) -> None:
    """高频噪声图的清晰度必须显著高于强模糊图。"""
    engine = CVEngine()
    sharp_score = engine.compute_sharpness(sharp_img)
    blurry_score = engine.compute_sharpness(blurry_img)
    assert sharp_score > blurry_score
    assert sharp_score > 80.0
    assert blurry_score < 20.0


def test_sharpness_is_deterministic(sharp_img: str) -> None:
    """同一张图多次调用清晰度必须完全一致。"""
    engine = CVEngine()
    scores = [engine.compute_sharpness(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"清晰度不稳定: {scores}"


# ---------- 曝光度 ----------


def test_exposure_returns_float_in_range(sharp_img: str) -> None:
    """曝光度返回 0-100 的 float。"""
    score = CVEngine().compute_exposure(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_dark_image_gets_low_exposure(dark_img: str) -> None:
    """全黑图像素全在极端暗区，曝光分应接近 0。"""
    score = CVEngine().compute_exposure(dark_img)
    assert score < 5.0, f"全黑图曝光分应极低，实际: {score}"


def test_exposure_is_deterministic(sharp_img: str) -> None:
    """曝光度可复现。"""
    engine = CVEngine()
    scores = [engine.compute_exposure(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"曝光度不稳定: {scores}"


def test_exposure_boundary_excludes_threshold(tmp_path: Path) -> None:
    """C-06：边界语义为"不含阈值本身"。

    构造一张全 EXPOSURE_BRIGHT_THRESHOLD(225) 值的图：
    - 旧逻辑 hist[BRIGHT:] 会把 225 算入 over_bright → 曝光分低
    - 新逻辑 hist[BRIGHT+1:] 不含 225 → 225 属于 mid 区 → 曝光分高
    """
    boundary = EXPOSURE_BRIGHT_THRESHOLD  # 225
    img = np.full((64, 64), boundary, dtype=np.uint8)
    p = str(tmp_path / "boundary.png")
    cv2.imwrite(p, img)
    score = CVEngine().compute_exposure(p)
    # 225 属于中间灰度，曝光分应较高（不被判为过曝）
    assert score > 60.0, f"边界值 {boundary} 应属中间灰度，曝光分应高，实际: {score}"


def test_exposure_boundary_dark_threshold(tmp_path: Path) -> None:
    """C-06：DARK_THRESHOLD(30) 边界——值为 30 不算过暗。"""
    boundary = EXPOSURE_DARK_THRESHOLD  # 30
    img = np.full((64, 64), boundary, dtype=np.uint8)
    p = str(tmp_path / "dark_boundary.png")
    cv2.imwrite(p, img)
    score = CVEngine().compute_exposure(p)
    # 30 属于中间灰度（[:DARK] 不含 30），曝光分应高于全黑图
    black = np.zeros((64, 64), dtype=np.uint8)
    p_black = str(tmp_path / "black.png")
    cv2.imwrite(p_black, black)
    black_score = CVEngine().compute_exposure(p_black)
    assert score > black_score, f"值 {boundary} 不应被算作过暗"


# ---------- 构图 ----------


def test_composition_returns_float_in_range(sharp_img: str) -> None:
    """构图分返回 0-100 的 float。"""
    score = CVEngine().compute_composition(sharp_img)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_composition_is_deterministic(sharp_img: str) -> None:
    """构图分可复现。"""
    engine = CVEngine()
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1, f"构图分不稳定: {scores}"


# ---------- evaluate 汇总 ----------


def test_evaluate_without_composition(sharp_img: str) -> None:
    """evaluate 默认不启用构图，composition 应为 None。"""
    result = CVEngine(enable_composition=False).evaluate(sharp_img)
    assert result.error is None
    assert result.composition is None
    assert result.sharpness > 0
    assert result.exposure >= 0


def test_evaluate_with_composition(sharp_img: str) -> None:
    """启用构图时 composition 非 None。"""
    result = CVEngine(enable_composition=True).evaluate(sharp_img)
    assert result.error is None
    assert result.composition is not None


def test_evaluate_handles_corrupted_image(corrupted_img: str) -> None:
    """损坏图 evaluate 返回带 error 的 CVResult，不抛异常。"""
    result = CVEngine().evaluate(corrupted_img)
    assert result.error is not None
    assert result.sharpness == 0.0


# ---------- 降采样 ----------
# 大图（长边 > DOWNSCALE_THRESHOLD）评分时启用降采样以降低内存占用。
# 以下测试验证：1) 辅助函数行为正确；2) 降采样前后评分相对排序不变；
# 3) 降采样不修改原文件。

_LARGE_LONG_SIDE = 3000  # 大于 DOWNSCALE_THRESHOLD(2048)，触发降采样


def _make_large_noise_img(path: str, size: tuple[int, int], seed: int) -> None:
    """生成大尺寸高频噪声图（高拉普拉斯方差，清晰度高）。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=size, dtype=np.uint8)
    cv2.imwrite(path, noise)


def _make_large_blurry_img(path: str, size: tuple[int, int], seed: int) -> None:
    """生成大尺寸强模糊图（低拉普拉斯方差，清晰度低）。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=size, dtype=np.uint8)
    blurred = cv2.GaussianBlur(noise, (51, 51), 0)
    cv2.imwrite(path, blurred)


def _make_large_dark_img(path: str, size: tuple[int, int]) -> None:
    """生成大尺寸全黑图（曝光度极低）。"""
    cv2.imwrite(path, np.zeros(size, dtype=np.uint8))


def _make_large_midgray_img(path: str, size: tuple[int, int]) -> None:
    """生成大尺寸中间灰度图（曝光度良好）。"""
    cv2.imwrite(path, np.full(size, 128, dtype=np.uint8))


def _file_hash(path: str) -> str:
    """计算文件 SHA256，用于验证降采样不修改原文件。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ----- downscale_if_needed 辅助函数 -----


def test_downscale_if_needed_none_disables() -> None:
    """max_long_side=None 时返回原数组（不降采样）。"""
    img = np.zeros((100, 100), dtype=np.uint8)
    result = downscale_if_needed(img, None)
    assert result is img  # 同一对象


def test_downscale_if_needed_small_image_unchanged() -> None:
    """长边未超阈值时返回原数组。"""
    img = np.zeros((100, 200), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    assert result is img  # 长边 200 < 2048，原样返回


def test_downscale_if_needed_scales_large_image() -> None:
    """长边超阈值时按比例缩小到阈值。"""
    img = np.zeros((1000, 3000), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    assert result.shape[0] < 1000 or result.shape[1] < 3000  # 至少一边缩小
    assert max(result.shape) <= 2048  # 长边不超阈值


def test_downscale_if_needed_preserves_aspect_ratio() -> None:
    """降采样保持宽高比。"""
    h, w = 2000, 3000
    img = np.zeros((h, w), dtype=np.uint8)
    result = downscale_if_needed(img, 2048)
    orig_ratio = w / h
    new_h, new_w = result.shape[:2]
    new_ratio = new_w / new_h
    assert abs(orig_ratio - new_ratio) < 0.01  # 宽高比基本不变


def test_downscale_if_needed_does_not_mutate_input() -> None:
    """降采样不修改输入数组（返回新数组）。"""
    img = np.full((3000, 3000), 128, dtype=np.uint8)
    _ = downscale_if_needed(img, 2048)
    assert img.shape == (3000, 3000)  # 原数组尺寸不变
    assert (img == 128).all()  # 原数组内容不变


# ----- CVEngine 降采样开关 -----


def test_cv_engine_default_enables_downscale() -> None:
    """CVEngine() 默认启用降采样（_eval_max_long_side 为阈值）。"""
    engine = CVEngine()
    assert engine._eval_max_long_side == DOWNSCALE_THRESHOLD


def test_cv_engine_downscale_false_disables() -> None:
    """downscale=False 时禁用降采样（_eval_max_long_side 为 None）。"""
    engine = CVEngine(downscale=False)
    assert engine._eval_max_long_side is None


# ----- 清晰度评分：降采样前后排序一致性 -----


def test_sharpness_ranking_preserved_with_downscale(tmp_path: Path) -> None:
    """降采样前后清晰度相对排序不变：清晰图 > 模糊图 在两种模式下均成立。"""
    sharp_p = str(tmp_path / "large_sharp.jpg")
    blurry_p = str(tmp_path / "large_blurry.jpg")
    size = (_LARGE_LONG_SIDE, 2000)
    _make_large_noise_img(sharp_p, size, seed=42)
    _make_large_blurry_img(blurry_p, size, seed=42)

    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    sharp_on = engine_on.compute_sharpness(sharp_p)
    blurry_on = engine_on.compute_sharpness(blurry_p)
    sharp_off = engine_off.compute_sharpness(sharp_p)
    blurry_off = engine_off.compute_sharpness(blurry_p)

    # 两种模式下清晰图分数都必须高于模糊图
    assert sharp_on > blurry_on, f"降采样模式排序异常: sharp={sharp_on} blurry={blurry_on}"
    assert sharp_off > blurry_off, f"原分辨率模式排序异常: sharp={sharp_off} blurry={blurry_off}"


def test_sharpness_score_consistency_downscale_vs_original(tmp_path: Path) -> None:
    """降采样与原分辨率的清晰度分数接近（双重缩放偏差可控）。"""
    img_p = str(tmp_path / "large_sharp.jpg")
    _make_large_noise_img(img_p, (_LARGE_LONG_SIDE, 2000), seed=42)

    score_on = CVEngine(downscale=True).compute_sharpness(img_p)
    score_off = CVEngine(downscale=False).compute_sharpness(img_p)

    # 两种模式最终都归一化到 SHARPNESS_NORMALIZE_SIZE(1024)，
    # 两步缩放 vs 一步缩放的拉普拉斯方差差异应在 10 分以内
    assert abs(score_on - score_off) < 10.0, (
        f"降采样前后清晰度分数差异过大: downscale={score_on} original={score_off}"
    )


# ----- 曝光度评分：降采样前后排序一致性 -----


def test_exposure_ranking_preserved_with_downscale(tmp_path: Path) -> None:
    """降采样前后曝光度相对排序不变：中间灰度图 > 全黑图 在两种模式下均成立。"""
    midgray_p = str(tmp_path / "large_midgray.jpg")
    dark_p = str(tmp_path / "large_dark.jpg")
    size = (_LARGE_LONG_SIDE, 2000)
    _make_large_midgray_img(midgray_p, size)
    _make_large_dark_img(dark_p, size)

    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    mid_on = engine_on.compute_exposure(midgray_p)
    dark_on = engine_on.compute_exposure(dark_p)
    mid_off = engine_off.compute_exposure(midgray_p)
    dark_off = engine_off.compute_exposure(dark_p)

    assert mid_on > dark_on, f"降采样模式曝光排序异常: mid={mid_on} dark={dark_on}"
    assert mid_off > dark_off, f"原分辨率模式曝光排序异常: mid={mid_off} dark={dark_off}"


def test_exposure_score_consistency_downscale_vs_original(tmp_path: Path) -> None:
    """降采样与原分辨率的曝光度分数高度一致（直方图分布近似不变）。"""
    img_p = str(tmp_path / "large_midgray.jpg")
    _make_large_midgray_img(img_p, (_LARGE_LONG_SIDE, 2000))

    score_on = CVEngine(downscale=True).compute_exposure(img_p)
    score_off = CVEngine(downscale=False).compute_exposure(img_p)

    # 曝光度基于直方图分布，降采样仅是子采样，分布近似不变
    assert abs(score_on - score_off) < 1.0, (
        f"降采样前后曝光度分数差异过大: downscale={score_on} original={score_off}"
    )


# ----- 降采样不修改原文件 -----


def test_downscale_does_not_modify_original_file(tmp_path: Path) -> None:
    """评分（含降采样）后原图片文件字节不变。"""
    img_p = str(tmp_path / "large_sharp.jpg")
    _make_large_noise_img(img_p, (_LARGE_LONG_SIDE, 2000), seed=42)

    before = _file_hash(img_p)
    _ = CVEngine(downscale=True).evaluate(img_p)
    after = _file_hash(img_p)

    assert before == after, "降采样评分修改了原图片文件"


# ----- 小图（长边 <= 2048）降采样不生效 -----


def test_small_image_scores_identical_with_or_without_downscale(sharp_img: str) -> None:
    """小图（512x512）降采样开关不影响评分（两种模式分数完全一致）。"""
    engine_on = CVEngine(downscale=True)
    engine_off = CVEngine(downscale=False)

    assert engine_on.compute_sharpness(sharp_img) == engine_off.compute_sharpness(sharp_img)
    assert engine_on.compute_exposure(sharp_img) == engine_off.compute_exposure(sharp_img)


# ---------- BRISQUE 模型管理机制（定位 / 下载 / 校验 / 加载） ----------


@pytest.fixture
def brisque_state() -> Iterator[None]:
    """每个用例前后清空进程内失败缓存，避免模块级状态跨用例泄漏。"""
    cvm._reset_brisque_state()
    yield
    cvm._reset_brisque_state()


class _FakeResponse:
    """urlopen 返回桩：上下文管理器 + 按长度读取。"""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self.payload[:n] if n >= 0 else self.payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        return False


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, payload: bytes, status: int = 200) -> list[str]:
    """桩掉 urllib.request.urlopen，返回请求 URL 记录。"""
    calls: list[str] = []

    def _fake(req: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        calls.append(req.full_url)
        return _FakeResponse(payload, status)

    # cvm 内的 urllib.request 与全局 urllib.request 是同一模块对象，直接patch等价
    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    return calls


def test_as_path_none_returns_none() -> None:
    """None 目录 → None。"""
    assert cvm._as_path(None) is None


def test_as_path_traversable_to_path(tmp_path: Path) -> None:
    """文件系统资源 → 真实 Path。"""
    assert cvm._as_path(tmp_path) == tmp_path


def test_as_path_broken_str_returns_none() -> None:
    """str() 抛异常的资源（如某些 zip importer）→ 降级 None。"""

    class _Broken:
        def __str__(self) -> str:
            raise RuntimeError("not a filesystem path")

    # 故意传入非 Traversable 的坏对象验证降级路径，cast 仅收敛类型不改运行时值
    assert cvm._as_path(cast("Traversable", _Broken())) is None


def test_existing_model_pair_none_directory() -> None:
    """目录为 None → None。"""
    assert cvm._existing_model_pair(None) is None


def test_existing_model_pair_all_present(tmp_path: Path) -> None:
    """两个模型文件齐全 → 返回路径对。"""
    for name in cvm._BRISQUE_FILENAMES:
        (tmp_path / name).write_bytes(b"%YAML stub")
    pair = cvm._existing_model_pair(tmp_path)
    assert pair == tuple(tmp_path / name for name in cvm._BRISQUE_FILENAMES)


def test_existing_model_pair_missing_one(tmp_path: Path) -> None:
    """缺任一文件 → None。"""
    (tmp_path / cvm._BRISQUE_FILENAMES[0]).write_bytes(b"%YAML stub")
    assert cvm._existing_model_pair(tmp_path) is None


def test_fetch_model_file_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """哈希命中：校验后原子落盘，无 .tmp 残留。"""
    payload = b"%YAML:1.0\nfake-model-body\n"
    expected = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "model.yml"
    calls = _patch_urlopen(monkeypatch, payload)

    cvm._fetch_model_file("https://example.invalid/model.yml", dest, expected)

    assert dest.read_bytes() == payload
    assert calls == ["https://example.invalid/model.yml"]
    assert list(tmp_path.glob(".*tmp*")) == []  # 无 .part/.tmp 残留


def test_fetch_model_file_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 200 状态 → OSError（廉价校验先于哈希）。"""
    _patch_urlopen(monkeypatch, b"whatever", status=404)
    with pytest.raises(OSError, match="HTTP 404"):
        cvm._fetch_model_file("https://example.invalid/m", tmp_path / "m.yml", "0" * 64)


def test_fetch_model_file_oversized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过大小上限的响应 → OSError，防投毒大文件写盘。"""
    payload = b"%YAML" + b"x" * (cvm._BRISQUE_MAX_BYTES + 1)
    _patch_urlopen(monkeypatch, payload)
    with pytest.raises(OSError, match="上限"):
        cvm._fetch_model_file("https://example.invalid/m", tmp_path / "m.yml", "0" * 64)


def test_fetch_model_file_not_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """200 但响应体是 HTML 错误页（GitHub 行为）→ OSError 拒绝落盘。"""
    _patch_urlopen(monkeypatch, b"<html>404 page</html>")
    with pytest.raises(OSError, match="FileStorage"):
        cvm._fetch_model_file("https://example.invalid/m", tmp_path / "m.yml", "0" * 64)
    assert not (tmp_path / "m.yml").exists()


def test_fetch_model_file_sha_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SHA256 不符 → BrisqueIntegrityError（供应链信号，绝不降级），且不落盘。"""
    _patch_urlopen(monkeypatch, b"%YAML tampered")
    with pytest.raises(BrisqueIntegrityError, match="完整性校验失败"):
        cvm._fetch_model_file("https://example.invalid/m", tmp_path / "m.yml", "0" * 64)
    assert not (tmp_path / "m.yml").exists()
    assert list(tmp_path.glob(".*tmp*")) == []


def test_download_model_pair_none_directory() -> None:
    """目录 None → 直接 None。"""
    assert cvm._download_model_pair(None) is None


def test_download_model_pair_mkdir_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目录不可创建（只读 site-packages）→ None 交由上层换目录。"""
    monkeypatch.setattr(
        Path, "mkdir", lambda self, *a, **kw: (_ for _ in ()).throw(OSError("read-only fs"))
    )
    assert cvm._download_model_pair(tmp_path) is None


def test_download_model_pair_skips_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已有文件不重复下载，只补缺失的那个。"""
    existing = cvm._BRISQUE_FILENAMES[1]
    (tmp_path / existing).write_bytes(b"%YAML kept")
    payload = b"%YAML:1.0\ndownloaded\n"
    # 钉死哈希替换为与桩 payload 匹配的值：_fetch_model_file 保持真实校验逻辑
    monkeypatch.setattr(
        cvm,
        "_BRISQUE_SHA256",
        {name: hashlib.sha256(payload).hexdigest() for name in cvm._BRISQUE_FILENAMES},
    )
    calls = _patch_urlopen(monkeypatch, payload)

    pair = cvm._download_model_pair(tmp_path)

    assert pair is not None
    assert len(calls) == 1  # 只下载了缺失的 model 文件
    assert calls[0].endswith(cvm._BRISQUE_FILENAMES[0])
    assert (tmp_path / existing).read_bytes() == b"%YAML kept"  # 未被覆盖


def test_download_model_pair_network_failure_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载抛普通异常（网络不可达）→ None（降级，不向上抛）。"""
    _patch_urlopen(monkeypatch, b"%YAML partial", status=500)
    assert cvm._download_model_pair(tmp_path) is None


def test_download_model_pair_integrity_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BrisqueIntegrityError 穿透不降级：对可能被投毒的源换目录重试毫无意义。"""
    payload = b"%YAML tampered"
    _patch_urlopen(monkeypatch, payload)
    with pytest.raises(BrisqueIntegrityError):
        cvm._download_model_pair(tmp_path)


def test_download_allowed_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """只有明确的肯定值才放行（大小写/空白宽容）。"""
    for raw in ("1", "true", "YES", " on "):
        monkeypatch.setenv(ENV_BRISQUE_ALLOW_DOWNLOAD, raw)
        assert cvm._download_allowed() is True, raw


def test_download_allowed_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """未设置、空串与其他值一律不放行。"""
    monkeypatch.delenv(ENV_BRISQUE_ALLOW_DOWNLOAD, raising=False)
    assert cvm._download_allowed() is False
    for raw in ("", "0", "false", "y"):
        monkeypatch.setenv(ENV_BRISQUE_ALLOW_DOWNLOAD, raw)
        assert cvm._download_allowed() is False, raw


def test_resolve_model_pair_short_circuits_after_failure(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进程内已确认失败 → 后续调用直接短路，不再探测。"""
    monkeypatch.setattr(cvm, "_BRISQUE_FAILURE", "已确认不可用")
    monkeypatch.setattr(
        cvm, "_existing_model_pair", lambda d: (_ for _ in ()).throw(AssertionError("不应再探测"))
    )
    assert cvm._resolve_model_pair() is None


def test_resolve_model_pair_bundled_files_no_network(
    brisque_state: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """随包模型齐全 → 直接命中，绝不联网。"""
    for name in cvm._BRISQUE_FILENAMES:
        (tmp_path / name).write_bytes(b"%YAML bundled")
    monkeypatch.setattr(cvm, "_BRISQUE_MODEL_DIR", tmp_path)
    monkeypatch.setattr(
        cvm, "_download_model_pair", lambda d: (_ for _ in ()).throw(AssertionError("不应联网"))
    )

    pair = cvm._resolve_model_pair()

    assert pair == tuple(tmp_path / name for name in cvm._BRISQUE_FILENAMES)
    assert cvm._BRISQUE_FAILURE is None  # 成功不写失败缓存


def test_resolve_model_pair_cache_dir_fallback(
    brisque_state: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """包目录缺失 → 用户缓存目录兜底命中。"""
    empty_pkg = tmp_path / "pkg"
    empty_pkg.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in cvm._BRISQUE_FILENAMES:
        (cache / name).write_bytes(b"%YAML cached")
    monkeypatch.setattr(cvm, "_BRISQUE_MODEL_DIR", empty_pkg)
    monkeypatch.setattr(cvm, "_BRISQUE_CACHE_DIR", cache)

    assert cvm._resolve_model_pair() == tuple(cache / name for name in cvm._BRISQUE_FILENAMES)


def test_resolve_model_pair_download_disabled_sets_failure(
    brisque_state: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型缺失且默认不联网 → None 并记录 NO_MODEL 原因（下次短路）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(cvm, "_BRISQUE_MODEL_DIR", empty)
    monkeypatch.setattr(cvm, "_BRISQUE_CACHE_DIR", tmp_path / "no-cache")
    monkeypatch.delenv(ENV_BRISQUE_ALLOW_DOWNLOAD, raising=False)

    assert cvm._resolve_model_pair() is None
    assert cvm._BRISQUE_FAILURE == cvm._REASON_NO_MODEL


def test_resolve_model_pair_download_success_and_failure(
    brisque_state: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关开启：下载成功 → 命中；两处目录全失败 → 记录 DOWNLOAD_FAILED。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(cvm, "_BRISQUE_MODEL_DIR", empty)
    monkeypatch.setattr(cvm, "_BRISQUE_CACHE_DIR", tmp_path / "no-cache")
    monkeypatch.setenv(ENV_BRISQUE_ALLOW_DOWNLOAD, "1")

    pair = tuple(empty / name for name in cvm._BRISQUE_FILENAMES)
    monkeypatch.setattr(cvm, "_download_model_pair", lambda d: pair)
    assert cvm._resolve_model_pair() == pair
    assert cvm._BRISQUE_FAILURE is None

    # 下载全部失败 → 失败原因可观测
    cvm._reset_brisque_state()
    monkeypatch.setattr(cvm, "_download_model_pair", lambda d: None)
    assert cvm._resolve_model_pair() is None
    assert cvm._BRISQUE_FAILURE == cvm._REASON_DOWNLOAD_FAILED


def test_load_brisque_no_api_sets_failure(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺 opencv-contrib（_BRISQUE_API 为 None）→ None + NO_API 原因。"""
    monkeypatch.setattr(cvm, "_BRISQUE_API", None)
    assert cvm._load_brisque() is None
    assert cvm._BRISQUE_FAILURE == cvm._REASON_NO_API


def test_load_brisque_no_model_returns_none(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API 在但模型定位失败 → None（失败原因由 _resolve_model_pair 记录）。"""
    monkeypatch.setattr(cvm, "_BRISQUE_API", object)
    monkeypatch.setattr(cvm, "_resolve_model_pair", lambda: None)
    assert cvm._load_brisque() is None


def test_load_brisque_create_factory(
    brisque_state: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """优先走 create() 工厂（OpenCV 5.0 直接构造 compute 会炸，见源码注释）。"""
    created: dict[str, tuple[str, str]] = {}

    class _Api:
        @staticmethod
        def create(model: str, rng: str) -> object:
            created["args"] = (model, rng)
            return object()

    pair = tuple(tmp_path / name for name in cvm._BRISQUE_FILENAMES)
    monkeypatch.setattr(cvm, "_BRISQUE_API", _Api)
    monkeypatch.setattr(cvm, "_resolve_model_pair", lambda: pair)

    obj = cvm._load_brisque()

    assert obj is not None
    assert created["args"] == (str(pair[0]), str(pair[1]))


def test_load_brisque_factory_fallback_to_class(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 create 属性的 API → 退回类构造器。"""

    class _Api:
        def __init__(self, model: str, rng: str) -> None:
            self.args = (model, rng)

    monkeypatch.setattr(cvm, "_BRISQUE_API", _Api)
    monkeypatch.setattr(cvm, "_resolve_model_pair", lambda: ("m", "r"))
    obj = cvm._load_brisque()
    assert isinstance(obj, _Api)
    assert obj.args == ("m", "r")


def test_load_brisque_factory_raises_sets_bad_model(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """构造失败（模型损坏）→ None + BAD_MODEL 原因。"""

    class _Api:
        @staticmethod
        def create(model: str, rng: str) -> object:
            raise ValueError("bad yml")

    monkeypatch.setattr(cvm, "_BRISQUE_API", _Api)
    monkeypatch.setattr(cvm, "_resolve_model_pair", lambda: ("m", "r"))
    assert cvm._load_brisque() is None
    assert cvm._BRISQUE_FAILURE == cvm._REASON_BAD_MODEL


# ---------- compute_noise 与降级行为 ----------


class _FakeBrisque:
    """可控的 BRISQUE 评分对象桩。"""

    def __init__(self, score: float | None = None, exc: Exception | None = None) -> None:
        self.score = score
        self.exc = exc

    def compute(self, gray: npt.NDArray[np.uint8]) -> list[float | None]:
        if self.exc is not None:
            raise self.exc
        return [self.score]


def _engine_with_brisque(fake: _FakeBrisque) -> CVEngine:
    """绕过 __init__ 的依赖探测，直接注入评分对象（复用进程内模型缓存语义）。"""
    engine = CVEngine(enable_noise=False)
    engine._brisque_obj = fake
    return engine


def test_engine_enable_noise_unavailable_warns_once(
    brisque_state: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """enable_noise 但依赖/模型不可用 → 构造时告警一次，noise 降级 None。"""
    monkeypatch.setattr(cvm, "_BRISQUE_API", None)  # 与基础环境一致，extras 环境也确定
    monkeypatch.setattr(cvm, "_load_brisque", lambda: None)

    with caplog.at_level(logging.WARNING, logger="flashgaze.core.cv_engine"):
        engine = CVEngine(enable_noise=True)

    assert engine._brisque_obj is None
    assert any("BRISQUE" in r.message for r in caplog.records)
    assert engine.compute_noise("whatever.jpg") is None


def test_compute_noise_normalizes_score() -> None:
    """BRISQUE 原始分越低质量越好：反转映射 100 - raw，clamp 到 [0,100]。"""
    engine = _engine_with_brisque(_FakeBrisque(score=42.0))
    gray = np.zeros((64, 64), dtype=np.uint8)
    assert engine.compute_noise("x.jpg", gray=gray) == 58.0


def test_compute_noise_clamps_bounds() -> None:
    """越界原始分 clamp 到 [0,100]。"""
    gray = np.zeros((64, 64), dtype=np.uint8)
    assert (
        _engine_with_brisque(_FakeBrisque(score=-30.0)).compute_noise("x.jpg", gray=gray) == 100.0
    )
    assert _engine_with_brisque(_FakeBrisque(score=250.0)).compute_noise("x.jpg", gray=gray) == 0.0


def test_compute_noise_nan_returns_none() -> None:
    """NaN/inf 原始分 → None，不污染下游加权评分（FIX #4b-2）。"""
    gray = np.zeros((64, 64), dtype=np.uint8)
    engine = _engine_with_brisque(_FakeBrisque(score=float("nan")))
    assert engine.compute_noise("x.jpg", gray=gray) is None


def test_compute_noise_inf_returns_none() -> None:
    gray = np.zeros((64, 64), dtype=np.uint8)
    engine = _engine_with_brisque(_FakeBrisque(score=float("inf")))
    assert engine.compute_noise("x.jpg", gray=gray) is None


def test_compute_noise_generic_exception_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    """非 cv2.error 的计算异常：告警一次后降级 None，不逐图刷屏（C-10）。"""
    engine = _engine_with_brisque(_FakeBrisque(exc=ValueError("stack overflow")))
    gray = np.zeros((64, 64), dtype=np.uint8)
    with caplog.at_level(logging.WARNING, logger="flashgaze.core.cv_engine"):
        assert engine.compute_noise("x.jpg", gray=gray) is None
        assert engine.compute_noise("x.jpg", gray=gray) is None
    warnings = [r for r in caplog.records if "BRISQUE 计算异常" in r.message]
    assert len(warnings) == 1


def test_compute_noise_cv2_error_silent() -> None:
    """cv2.error 属已知可降级异常：静默 None，不告警。"""
    engine = _engine_with_brisque(_FakeBrisque(exc=cv2.error(cv2.Error.STS_ERROR, "m", "f", 0, 0)))
    assert engine.compute_noise("x.jpg", gray=np.zeros((64, 64), dtype=np.uint8)) is None


def test_compute_noise_gray_none_loads_from_disk(sharp_img: str) -> None:
    """gray 未注入时按路径自行加载（含 _normalize_size 幂等归一化）。"""
    engine = _engine_with_brisque(_FakeBrisque(score=10.0))
    assert engine.compute_noise(sharp_img) == 90.0


# ---------- 其余边界分支 ----------


def test_evaluate_generic_exception_returns_error_result() -> None:
    """解码之外的意外异常 → 带 error 的零分 CVResult，不向上抛。"""
    engine = CVEngine()

    def _boom(
        img_path: str,
    ) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
        raise ValueError("unexpected")

    engine._load_eval_images = _boom  # type: ignore[method-assign]
    result = engine.evaluate("x.jpg")
    assert result.sharpness == 0.0
    assert result.error is not None and result.error.startswith("CV 评估失败")


def test_compute_exposure_empty_histogram_returns_zero(
    monkeypatch: pytest.MonkeyPatch, sharp_img: str
) -> None:
    """直方图总和为 0（退化输入）→ 0.0 而非除零。"""
    monkeypatch.setattr(cv2, "calcHist", lambda *a, **kw: np.zeros((256, 1)))
    engine = CVEngine()
    assert engine.compute_exposure(sharp_img, gray=np.zeros((16, 16), dtype=np.uint8)) == 0.0


def test_compute_color_richness_empty_histogram_returns_zero(
    monkeypatch: pytest.MonkeyPatch, colorful_img: str
) -> None:
    """H 直方图总和为 0 → 0.0。"""
    monkeypatch.setattr(cv2, "calcHist", lambda *a, **kw: np.zeros((180, 1)))
    engine = CVEngine()
    assert (
        engine.compute_color_richness(colorful_img, img=np.zeros((16, 16, 3), dtype=np.uint8))
        == 0.0
    )


def test_compute_composition_unsegmentable_returns_median(dark_img: str) -> None:
    """全黑图 Otsu 无法分割（m00=0）→ 中位分 50。"""
    assert CVEngine().compute_composition(dark_img) == 50.0

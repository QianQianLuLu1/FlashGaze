"""image_io 单元测试（C-01 exclude_dirs + 符号链接过滤 + H-7 解码像素预算）。

验证排除目录内的图片不产出、符号链接文件不产出（H-4/M-16：候选集合不含链接），
且默认行为不变；以及 H-7 的解码像素预算——超过上限的图在解码前被拒（零像素
分配），绝不因解压炸弹而 OOM。
"""

from __future__ import annotations

import os
import shutil
import struct
import tracemalloc
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PIL import Image, ImageOps

from flashgaze.utils import image_io
from flashgaze.utils.image_io import ImageReadError, decode_bgr, iter_images


def _seed(ws: Path, names: list[str]) -> list[Path]:
    out = []
    for n in names:
        p = ws / n
        p.write_bytes(b"fake-image-bytes")
        out.append(p)
    return out


def test_iter_images_excludes_named_dir(tmp_path: Path) -> None:
    """exclude_dirs 内的图片不产出（C-01：导出目录 ./精选）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["a.jpg", "b.jpg"])
    export = ws / "精选"
    export.mkdir()
    _seed(export, ["sel.jpg", "sel2.jpg"])

    result = list(iter_images(str(ws), exclude_dirs={export}))
    names = {Path(p).name for p in result}
    assert names == {"a.jpg", "b.jpg"}
    assert "sel.jpg" not in names


def test_iter_images_excludes_backup_dir(tmp_path: Path) -> None:
    """隐藏的 .flashgaze_backup 被排除（C-01，与 C-19 隐藏目录跳过互补）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["a.jpg"])
    backup = ws / ".flashgaze_backup"
    backup.mkdir()
    _seed(backup, ["bak.jpg"])

    result = list(iter_images(str(ws), exclude_dirs={backup}))
    names = {Path(p).name for p in result}
    assert names == {"a.jpg"}


def test_iter_images_default_no_exclusion(tmp_path: Path) -> None:
    """不传 exclude_dirs 时行为不变，子目录图片照常产出。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["a.jpg"])
    sub = ws / "sub"
    sub.mkdir()
    _seed(sub, ["b.jpg"])
    result = list(iter_images(str(ws)))
    names = {Path(p).name for p in result}
    assert names == {"a.jpg", "b.jpg"}


def _make_symlink(link: Path, target: Path) -> None:
    """创建指向 target 的符号链接；无权限（Windows 非开发者模式）时如实 skip。"""
    try:
        os.symlink(target, link, target_is_directory=False)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无符号链接创建权限（Windows 需开发者模式/管理员），未验证")


def _make_junction(target: Path, link: Path) -> None:
    """创建指向 target 的目录联接（junction，Windows 目录 reparse point）。

    junction 无需符号链接权限（不必开发者模式/管理员）；非 Windows 或创建
    失败时如实 skip，不伪造通过。生产代码不引用 _winapi，仅测试辅助。
    """
    if os.name != "nt":
        pytest.skip("junction 为 Windows 专有能力，非 Windows 平台未验证")
    try:
        import _winapi

        # getattr 而非直接取属性：typeshed 把 CreateJunction 放在 win32 分支里，
        # mypy --platform linux 下解析不到该属性会报 attr-defined，而 os.name 守卫
        # 不做死分支分析、两平台都解析；此处探测一次，缺属性就如实 skip。
        create_junction = getattr(_winapi, "CreateJunction", None)
        if create_junction is None:
            pytest.skip("当前解释器的 _winapi 未提供 CreateJunction，未验证")
        create_junction(str(target), str(link))
    except (OSError, NotImplementedError, ImportError):
        pytest.skip("当前环境无法创建 junction，未验证")


def test_iter_images_skips_symlink_files(tmp_path: Path) -> None:
    """指向 workspace 内真实图的链接文件不产出，真实图恰好产出一次（H-4/M-16）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["real.jpg"])
    _make_symlink(ws / "link.jpg", ws / "real.jpg")

    result = list(iter_images(str(ws)))
    names = [Path(p).name for p in result]
    # 反例保护：普通文件不受影响；链接 resolve 后不得与真实图重复产出
    assert names == ["real.jpg"]


def test_iter_images_skips_symlink_non_recursive(tmp_path: Path) -> None:
    """非递归分支同样过滤链接文件（entry.is_file() 对链接返回 True 的缺陷面）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["real.jpg"])
    _make_symlink(ws / "link.jpg", ws / "real.jpg")

    result = list(iter_images(str(ws), recursive=False))
    names = [Path(p).name for p in result]
    assert names == ["real.jpg"]


def test_iter_images_skips_outbound_symlink(tmp_path: Path) -> None:
    """指向 workspace 外图片的链接不产出：外部真实文件不得进入候选。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    _seed(outside, ["secret.jpg"])
    ws = tmp_path / "ws"
    ws.mkdir()
    _make_symlink(ws / "leak.jpg", outside / "secret.jpg")

    result = list(iter_images(str(ws)))
    assert result == []


def test_iter_images_skips_dangling_symlink(tmp_path: Path) -> None:
    """断链不产出，不制造「解析后不存在路径」进入候选的噪声。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws, ["a.jpg"])
    _make_symlink(ws / "dead.jpg", ws / "missing.jpg")

    result = list(iter_images(str(ws)))
    names = {Path(p).name for p in result}
    assert names == {"a.jpg"}


# ── junction（Windows 目录联接）：H-4/M-16 的同类残留 ────────────────────
#
# Path.is_symlink() 对 junction 恒为 False，os.walk(followlinks=False) 在
# Windows 上仍会进入 junction 目录——junction 内图片重复产出（扭曲
# avg_score 与删除比例分母）、外链 junction 让外部文件进入候选、junction
# 环使扫描不终止。修复前 behavior 见各用例 docstring。


def test_iter_images_skips_junction_dir_duplicates(tmp_path: Path) -> None:
    """junction 目录不进入扫描：junction 内图片不得与真实图重复产出。

    修复前 real.jpg 经 real/ 与 linkdir/ 各产出一次（重复评分、扭曲删除
    比例分母）。反例保护：真实子目录 sub/other.jpg 必须照常产出。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    real = ws / "real"
    real.mkdir()
    (real / "real.jpg").write_bytes(b"fake-image-bytes")
    sub = ws / "sub"
    sub.mkdir()
    (sub / "other.jpg").write_bytes(b"fake-image-bytes")
    _make_junction(real, ws / "linkdir")

    result = list(iter_images(str(ws)))
    names = [Path(p).name for p in result]
    assert sorted(names) == ["other.jpg", "real.jpg"], f"junction 内图片不得重复产出: {names}"
    assert names.count("real.jpg") == 1


def test_iter_images_skips_outbound_junction(tmp_path: Path) -> None:
    """指向 workspace 外目录的 junction 整体不进入：外部文件不得进入候选。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"fake-image-bytes")
    ws = tmp_path / "ws"
    ws.mkdir()
    _make_junction(outside, ws / "linkdir")

    result = list(iter_images(str(ws)))
    assert result == [], f"junction 内的外部图片不得进入候选: {result}"


def test_is_junction_helper(tmp_path: Path) -> None:
    """_is_junction 判定：完好/断链 junction 为 True，普通目录为 False。"""
    from flashgaze.utils.image_io import _is_junction

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "jn"
    _make_junction(real, link)
    assert _is_junction(link) is True
    shutil.rmtree(real)  # 断链后 tag 仍可由 lstat 读出（不跟随目标）
    assert _is_junction(link) is True
    assert _is_junction(tmp_path) is False


def test_is_junction_lstat_outcome_via_injected_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_is_junction 的三条 lstat 结论用注入假 os 命名空间打全，三平台一致。

    真实 junction 用例（_make_junction）在非 Windows 上如实 skip，因此
    「lstat 竞态失败→按非 junction 处理」这条兜底在 12 条 CI 腿上无一覆盖，
    「reparse tag 命中」在 8 条 POSIX 腿上也不可达——两侧都是平台死区，
    只能靠替身把判定逻辑本身钉住（真 junction 用例保留为 Windows 集成真相）。

    实现选择：只替换 image_io 模块内的 os 引用，**绝不 monkeypatch 真 os 模块的
    os.name**——posixpath/ntpath、shutil、pytest 自身上报都读 os.name，全局改写
    的爆炸半径不可控；而 _is_junction 只读 os.name 与 os.lstat，是叶子函数。
    """

    class _NtOs:
        """只暴露 _is_junction 用到的两个成员的最小 os 替身。"""

        name = "nt"

        def __init__(self, lstat_fn: Callable[[Any], Any]) -> None:
            self._lstat_fn = lstat_fn

        def lstat(self, path: Any) -> Any:
            return self._lstat_fn(path)

    def _raise_oserror(_path: Any) -> Any:
        raise OSError("竞态：链接刚被属主删除")

    # 兜底路径：lstat 失败不得抛给扫描层，按非 junction 交给后续 resolve/stat 兜底
    monkeypatch.setattr(image_io, "os", _NtOs(_raise_oserror))
    assert image_io._is_junction(tmp_path / "gone") is False

    # 判定路径：tag 命中为 True（反例：无该属性/ tag 为 0 的普通目录不得误判）
    mount_point = types.SimpleNamespace(st_reparse_tag=image_io._IO_REPARSE_TAG_MOUNT_POINT)
    monkeypatch.setattr(image_io, "os", _NtOs(lambda _p: mount_point))
    assert image_io._is_junction(tmp_path / "jn") is True
    monkeypatch.setattr(image_io, "os", _NtOs(lambda _p: types.SimpleNamespace()))
    assert image_io._is_junction(tmp_path / "plain") is False, "普通目录不得判成 junction"


def test_iter_images_junction_cycle_terminates(tmp_path: Path) -> None:
    """junction 环不得使扫描不终止：环内目录不进入，产出有界。

    本用例仅在修复后运行：改动前 junction 环导致 os.walk 死循环，运行即
    挂死套件，不以挂死演示红灯；红灯由 duplicates / outbound 两条承担。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.jpg").write_bytes(b"fake-image-bytes")
    inner = ws / "inner"
    inner.mkdir()
    (inner / "b.jpg").write_bytes(b"fake-image-bytes")
    _make_junction(ws, inner / "loop")

    result = list(iter_images(str(ws)))
    names = {Path(p).name for p in result}
    assert names == {"a.jpg", "b.jpg"}
    assert len(result) == 2, f"junction 环内图片不得重复产出: {result}"


# ── H-7：解码像素预算（解压炸弹防护）────────────────────────────────────
#
# 修复前：decode_bgr 先按原始分辨率完整解码再降采样，Pillow 自带的
# MAX_IMAGE_PIXELS（≈8947 万告警 / 1.79 亿才抛错）未被收紧，两者之间的
# 灰色地带（如 1 亿像素）可合法分配数百 MB；阶段 2 的 ThreadPoolExecutor
# 还会对每张图并发全分辨率解码。
# 修复后：解码前按文件头尺寸预检，超限即抛 ImageReadError（零像素分配），
# 降级为 error 占位而非 OOM。

_BOMB_SIDE = 10000  # 10000×10000 = 1 亿像素，审查报告指定的亚阈值炸弹样例


def _bmp_header(width: int, height: int) -> bytes:
    """构造仅含头部、却声明巨大尺寸的 BMP——解压炸弹的最小形态。

    文件本体仅 94 字节，头部却声明 width×height 个像素：Pillow 的
    `Image.open` 只读头部即可拿到 size，因此能在不分配任何像素缓冲的
    前提下验证「解码前预检」。末尾附 40 字节伪像素数据（不足一行），
    一旦预检失效，解码必然失败——但那时数百 MB 缓冲已经分配出去了，
    正是本次要杜绝的情形。
    """
    return (
        b"BM"
        + struct.pack("<I", 94)  # bfSize
        + struct.pack("<H", 0)  # bfReserved1
        + struct.pack("<H", 0)  # bfReserved2
        + struct.pack("<I", 54)  # bfOffBits：像素数据偏移
        + struct.pack("<I", 40)  # biSize：BITMAPINFOHEADER
        + struct.pack("<i", width)  # biWidth
        + struct.pack("<i", height)  # biHeight（正数 = 自底向上）
        + struct.pack("<H", 1)  # biPlanes
        + struct.pack("<H", 24)  # biBitCount
        + struct.pack("<I", 0)  # biCompression：BI_RGB
        + struct.pack("<I", 0)  # biSizeImage
        + struct.pack("<I", 0)  # biXPelsPerMeter
        + struct.pack("<I", 0)  # biYPelsPerMeter
        + struct.pack("<I", 0)  # biClrUsed
        + struct.pack("<I", 0)  # biClrImportant
        + b"\x00" * 40  # 伪像素数据（远不足一行，解码必失败）
    )


def test_oversized_image_degrades_to_error(sharp_img: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过像素上限的图在解码前被拒：抛 ImageReadError 而非 OOM（H-7）。

    阈值经环境变量压到 1024 像素，512×512 的真实图即构成「超限」，无需真的
    构造大图即可验证预检生效。修复前该图能正常解码（DID NOT RAISE）。
    """
    monkeypatch.setenv("FLASHGAZE_MAX_IMAGE_PIXELS", "1024")
    with pytest.raises(ImageReadError, match="尺寸超限"):
        decode_bgr(sharp_img)


def test_decompression_bomb_file_rejected_before_alloc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 亿像素炸弹文件在分配像素缓冲之前就被拒（H-7 端到端冒烟）。

    文件本体 94 字节，头部声明 10000×10000。用 tracemalloc 断言峰值增量远
    小于 1 亿×3 字节（300MB），证明拦截确实发生在解码之前、而非分配之后。
    """
    monkeypatch.setenv("FLASHGAZE_MAX_IMAGE_PIXELS", str(64_000_000))
    bomb = tmp_path / "bomb.bmp"
    bomb.write_bytes(_bmp_header(_BOMB_SIDE, _BOMB_SIDE))

    tracemalloc.start()
    try:
        with pytest.raises(ImageReadError, match="尺寸超限"):
            decode_bgr(str(bomb))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 10 * 1024 * 1024, f"预检不应分配像素缓冲，实测峰值 {peak} 字节"


def test_bomb_above_pillow_hard_limit_becomes_image_read_error(tmp_path: Path) -> None:
    """超过 Pillow 硬阈值（2×上限）时，DecompressionBombError 转为 ImageReadError。

    11400×11400 ≈ 1.3 亿像素 > 2×6400 万，Pillow 在 `Image.open` 阶段即抛
    `DecompressionBombError`。该异常只继承 `Exception`（既非 OSError 也非
    RuntimeError），现有的 `except (UnidentifiedImageError, OSError)` 抓不到，
    必须显式转换，否则会退化成误导性的「CV 评估失败」。
    """
    bomb = tmp_path / "bomb.bmp"
    bomb.write_bytes(_bmp_header(11400, 11400))
    with pytest.raises(ImageReadError, match="尺寸超限"):
        decode_bgr(str(bomb))


def test_pixel_budget_env_override_raises_limit(
    sharp_img: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """逃生舱：上调上限后普通图照常解码，真正的炸弹仍被拒（100MP 中画幅可用）。"""
    monkeypatch.setenv("FLASHGAZE_MAX_IMAGE_PIXELS", "1000000")
    # 512×512 = 262144 < 1000000：不得被误伤
    assert decode_bgr(sharp_img).shape[:2] == (512, 512)
    bomb = tmp_path / "bomb.bmp"
    bomb.write_bytes(_bmp_header(_BOMB_SIDE, _BOMB_SIDE))
    with pytest.raises(ImageReadError, match="尺寸超限"):
        decode_bgr(str(bomb))


def test_pixel_budget_env_zero_disables_project_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """置 0 关闭项目上限：预检不再生效，交由 Pillow 自带阈值处理。"""
    from flashgaze.utils import image_io

    monkeypatch.setenv("FLASHGAZE_MAX_IMAGE_PIXELS", "0")
    assert image_io.max_image_pixels() <= 0
    bomb = tmp_path / "bomb.bmp"
    bomb.write_bytes(_bmp_header(_BOMB_SIDE, _BOMB_SIDE))
    with pytest.raises(ImageReadError) as exc:
        decode_bgr(str(bomb))
    # 关闭后不再由项目预检拦截（此处因文件截断而解码失败）
    assert "尺寸超限" not in str(exc.value)


def test_oversized_image_skipped_by_scorer_and_batch_continues(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端降级：超限图降级为 error 占位，且不进入 VLM 阶段 2。

    阶段 2 的 `vlm_targets` 过滤掉一切 `cv.error` 非空的图，故超限图不会在
    ThreadPoolExecutor 里被全分辨率并发解码——这是「优雅降级」的关键不变量。
    """
    from flashgaze.core.cv_engine import CVEngine
    from flashgaze.core.hybrid_scorer import HybridScorer
    from flashgaze.core.vlm_client import VLMClient
    from flashgaze.models.schemas import Config, CVResult, VLMResult

    monkeypatch.setenv("FLASHGAZE_MAX_IMAGE_PIXELS", "1000000")
    for name in ("sharp.jpg", "blurry.jpg"):
        shutil.copy2(fixtures_dir / name, tmp_path / name)
    (tmp_path / "bomb.bmp").write_bytes(_bmp_header(_BOMB_SIDE, _BOMB_SIDE))

    class _FakeVLM:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def judge(
            self,
            img_path: str,
            cv: CVResult | None = None,
            pre_encoded_b64: str | None = None,
            **kwargs: Any,
        ) -> VLMResult:
            self.paths.append(img_path)
            return VLMResult(0.0, "ok", ok=True)

    fake = _FakeVLM()
    config = Config(
        directory=str(tmp_path),
        top=30,
        no_vlm=False,
        weights={"sharpness": 0.5, "exposure": 0.5},
    )
    scored = HybridScorer(CVEngine(), cast(VLMClient, fake), config).score_batch(str(tmp_path))

    by_name = {Path(s.file).name: s for s in scored}
    assert "尺寸超限" in (by_name["bomb.bmp"].error or ""), "超限图应降级为 error 占位"
    assert by_name["bomb.bmp"].score == 0.0
    assert by_name["sharp.jpg"].error is None, "正常图不得被像素预算误伤"
    assert by_name["blurry.jpg"].error is None
    # 关键不变量：超限图不得进入阶段 2，否则会在线程池里被全分辨率解码
    assert {Path(p).name for p in fake.paths} == {"sharp.jpg", "blurry.jpg"}


def test_normal_images_not_rejected_by_budget(
    sharp_img: str, img_4k: str, phone_portrait_img: str
) -> None:
    """反例：收紧上限后，正常分辨率的图一律不受影响（防误伤）。

    覆盖 512×512（0.26M）/ 4K 3840×2160（8.3M）/ 手机竖幅 3024×4032
    （12.2M），均远低于默认 6400 万上限。修复前后均应绿灯。
    """
    expected: dict[str, tuple[int, int]] = {
        sharp_img: (512, 512),
        img_4k: (2160, 3840),
        phone_portrait_img: (4032, 3024),
    }
    for path, shape in expected.items():
        assert decode_bgr(path).shape[:2] == shape, f"{path} 不应被像素预算拦截"


def test_decode_bgr_returns_owned_contiguous_array(sharp_img: str) -> None:
    """decode_bgr 返回自持、C 连续、可写的数组，且像素与旧写法逐位一致。

    把 `np.array(img)` 换成 `np.asarray(img)`（零拷贝视图）后，仍必须返回一份
    独立可写的副本——否则调用方原地修改会污染 Pillow 的缓冲。
    """
    arr = decode_bgr(sharp_img)
    assert arr.flags["OWNDATA"] is True
    assert arr.flags["C_CONTIGUOUS"] is True
    assert arr.flags["WRITEABLE"] is True

    with Image.open(sharp_img) as src:
        ref = np.array(ImageOps.exif_transpose(src).convert("RGB"))[:, :, ::-1].copy()
    assert np.array_equal(arr, ref), "解码像素必须逐位不变"


def _base_is_bytes(base: object) -> bool:
    """经 `object` 形参做 isinstance 判定。

    numpy stubs 把 `ndarray.base` 标为 `None | ndarray`，直接写
    `isinstance(view.base, bytes)` 会被 mypy 判为恒假，并使其后的语句
    unreachable（本项目开了 `warn_unreachable`）。
    """
    return isinstance(base, bytes)


def test_asarray_gives_no_memory_benefit_over_array() -> None:
    """反例护栏：np.asarray 并不比 np.array 省内存，故不采用该「优化」。

    Pillow 12.2 的 `__array_interface__` 返回的是 `tobytes()` 产出的 **bytes
    副本**（`np.asarray` 结果的 `base` 是 bytes），并非指向 Pillow 内部缓冲的
    零拷贝视图。5000×5000 实测两条写法的解码峰值均为约 143 MiB（差值 <0.1MiB），
    换成 np.asarray 无任何收益。本用例钉死该事实，防止日后有人以「消除二次
    拷贝」为名改回 np.asarray 并声称降低了峰值。
    """
    img = Image.new("RGB", (2048, 2048), (1, 2, 3))
    view = np.asarray(img)
    # OWNDATA=False 只是说明它不"拥有"数据，底下仍是一份完整的 bytes 副本
    assert view.flags["OWNDATA"] is False
    assert _base_is_bytes(view.base), "asarray 底下是 tobytes() 副本，非共享缓冲"
    assert np.array(img).flags["OWNDATA"] is True

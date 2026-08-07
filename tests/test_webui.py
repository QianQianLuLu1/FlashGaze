"""FlashGaze WebUI 模块单元测试。

仅覆盖 flashgaze/webui/runner.py 与 gallery.py 中的纯逻辑函数；
所有依赖 gradio 的函数（build_app / main 等）不在此处测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flashgaze.defaults import DEFAULT_SCENE, DEFAULT_TOP
from flashgaze.models.schemas import Config, ImageScore
from flashgaze.webui import is_available
from flashgaze.webui.app import TABLE_HEADERS
from flashgaze.webui.gallery import build_gallery_items, filter_rows
from flashgaze.webui.runner import (
    ScoringResult,
    build_run_config,
    run_scoring,
)
from flashgaze.models.schemas import ExitCode


# ── 辅助构造函数 ──────────────────────────────────────────────

def _make_score(
    file: str,
    path: str,
    *,
    score: float = 80.0,
    selected: bool = False,
    sharpness: float = 70.0,
    exposure: float = 60.0,
    composition: float | None = None,
    noise: float | None = None,
    color: float | None = None,
    face_count: int = 0,
    face_sharpness: float | None = None,
    portrait_bonus: float = 0.0,
    vlm_adjustment: float = 0.0,
    vlm_reason: str = "",
    vlm_provider: str = "",
    deduped: bool = False,
    error: str | None = None,
) -> ImageScore:
    """构造单个 ImageScore（填齐字段，便于 to_rows / gallery 测试）。"""
    return ImageScore(
        file=file,
        path=path,
        sharpness=sharpness,
        exposure=exposure,
        composition=composition,
        vlm_adjustment=vlm_adjustment,
        score=score,
        selected=selected,
        error=error,
        noise=noise,
        color=color,
        face_count=face_count,
        face_sharpness=face_sharpness,
        portrait_bonus=portrait_bonus,
        deduped=deduped,
        vlm_reason=vlm_reason,
        vlm_provider=vlm_provider,
    )


def _make_result(scored: list[ImageScore], config: Config | None = None) -> ScoringResult:
    """构造 ScoringResult（用于 to_rows / gallery / filter_rows 测试）。"""
    if config is None:
        config = build_run_config(".", no_vlm=True)
    return ScoringResult(scored=scored, elapsed_ms=100, config=config)


# ── 1. 导入与常量 ──────────────────────────────────────────────

def test_webui_imports():
    """验证 flashgaze.webui.app 可导入，且 DEFAULT_SCENE 存在于 defaults。"""
    # gradio 未安装时 is_available() 返回 False 也算通过——关键是导入不抛异常
    assert isinstance(is_available(), bool)
    # DEFAULT_SCENE 必须是字符串常量且非空
    assert isinstance(DEFAULT_SCENE, str) and DEFAULT_SCENE
    # TABLE_HEADERS 列数与 to_rows / _row_for 输出列数一致
    assert len(TABLE_HEADERS) == 16


# ── 2-3. build_run_config ──────────────────────────────────────

def test_build_run_config_basic():
    """build_run_config 装配 Config 的关键字段。"""
    config = build_run_config("/tmp/demo")
    assert isinstance(config, Config)
    assert config.directory == "/tmp/demo"
    # 未传 top 时回退到 DEFAULT_TOP
    assert config.top == DEFAULT_TOP
    # 默认 no_vlm 为 False（与 CLI 默认对齐）
    assert config.no_vlm is False


def test_build_run_config_no_vlm():
    """传入 no_vlm=True 时 config.no_vlm 必须为 True。"""
    config = build_run_config("/tmp/demo", no_vlm=True)
    assert config.no_vlm is True


# ── 4. ScoringResult.to_rows ───────────────────────────────────

def test_scoring_result_to_rows():
    """to_rows() 行数与输入等长，列数与 TABLE_HEADERS 对齐。"""
    scored = [
        _make_score("a.jpg", "/tmp/a.jpg", score=90.0, selected=True,
                    composition=80.0, noise=70.0, color=60.0,
                    face_count=1, face_sharpness=85.0, portrait_bonus=2.0,
                    vlm_adjustment=1.5, vlm_reason="好", vlm_provider="qwen"),
        _make_score("b.jpg", "/tmp/b.jpg", score=50.0, selected=False,
                    vlm_reason="", vlm_provider=""),
        _make_score("c.jpg", "/tmp/c.jpg", score=0.0, error="解码失败"),
    ]
    result = _make_result(scored)
    rows = result.to_rows()
    assert len(rows) == len(scored)
    for row in rows:
        assert len(row) == len(TABLE_HEADERS)
    # 最后一列应为错误信息或空串
    assert rows[2][-1] == "解码失败"
    # selected 标记列（倒数第 3 位，索引 -3）应为 "✓" 或 ""
    assert rows[0][-3] == "✓"
    assert rows[1][-3] == ""


# ── 5-6. build_gallery_items ───────────────────────────────────

def test_build_gallery_items_empty():
    """传入 None 或空结果时返回空列表。"""
    assert build_gallery_items(None) == []
    # 空 scored 同样返回空
    empty_result = _make_result([])
    assert build_gallery_items(empty_result) == []


def test_build_gallery_items_filter():
    """only_selected=True 仅返回入选图，且跳过 error 图。"""
    scored = [
        _make_score("keep.jpg", "/tmp/keep.jpg", score=90.0, selected=True),
        _make_score("drop.jpg", "/tmp/drop.jpg", score=40.0, selected=False),
        _make_score("bad.jpg", "/tmp/bad.jpg", score=0.0, selected=True, error="坏图"),
    ]
    result = _make_result(scored)
    items = build_gallery_items(result, only_selected=True)
    # 仅 keep.jpg 同时满足 selected=True 且无 error
    assert len(items) == 1
    assert items[0][0] == "/tmp/keep.jpg"
    # caption 含文件名与分数
    assert "keep.jpg" in items[0][1]
    assert "90.00" in items[0][1]


# ── 7. filter_rows 关键字筛选 ─────────────────────────────────

def test_filter_rows_keyword():
    """关键字匹配文件名或 vlm_reason，结果与 to_rows 同结构。"""
    scored = [
        _make_score("sunset_beach.jpg", "/tmp/sunset_beach.jpg",
                    score=85.0, vlm_reason="夕阳"),
        _make_score("portrait_001.jpg", "/tmp/portrait_001.jpg",
                    score=78.0, vlm_reason="人像"),
        _make_score("landscape.jpg", "/tmp/landscape.jpg",
                    score=70.0, vlm_reason=""),
    ]
    result = _make_result(scored)

    # 关键字 "sunset" 只匹配第一张
    rows_sun = filter_rows(result, keyword="sunset")
    assert len(rows_sun) == 1
    assert rows_sun[0][0] == "sunset_beach.jpg"

    # 关键字 "人像" 匹配 vlm_reason，命中第二张
    rows_portrait = filter_rows(result, keyword="人像")
    assert len(rows_portrait) == 1
    assert rows_portrait[0][0] == "portrait_001.jpg"

    # 空关键字返回全部
    rows_all = filter_rows(result, keyword="")
    assert len(rows_all) == len(scored)

    # only_selected 与 keyword 组合
    scored_sel = [
        _make_score("keep.jpg", "/tmp/keep.jpg", score=90.0, selected=True, vlm_reason="keep"),
        _make_score("drop.jpg", "/tmp/drop.jpg", score=90.0, selected=False, vlm_reason="keep"),
    ]
    result_sel = _make_result(scored_sel)
    rows_combo = filter_rows(result_sel, only_selected=True, keyword="keep")
    assert len(rows_combo) == 1
    assert rows_combo[0][0] == "keep.jpg"


# ── 8-10. run_scoring 端到端 ───────────────────────────────────

def test_run_scoring_empty_directory(tmp_path: Path):
    """传入不存在的目录返回 NO_IMAGES 错误码，且 result 为 None。"""
    missing = str(tmp_path / "does_not_exist")
    code, msg, result = run_scoring(missing, no_vlm=True)
    assert code == ExitCode.NO_IMAGES
    assert result is None
    assert "目录不存在" in msg


def test_run_scoring_no_images(tmp_path: Path):
    """传入存在但无图片的目录，返回 NO_IMAGES 错误码。"""
    code, msg, result = run_scoring(str(tmp_path), no_vlm=True)
    assert code == ExitCode.NO_IMAGES
    assert result is None
    assert "无支持" in msg or "无图片" in msg


@pytest.mark.slow
def test_run_scoring_no_vlm(fixtures_dir: Path):
    """对 tests/fixtures 跑纯离线评分（no_vlm=True），应成功并返回非空结果。"""
    code, msg, result = run_scoring(str(fixtures_dir), no_vlm=True)
    assert code == ExitCode.SUCCESS
    assert result is not None
    assert isinstance(result, ScoringResult)
    # fixtures 中至少有 sharp.jpg / blurry.jpg 等真实图
    assert len(result.scored) > 0
    # to_rows 输出与 scored 等长
    assert len(result.to_rows()) == len(result.scored)
    # 状态消息应包含耗时信息
    assert "ms" in msg or "耗时" in msg

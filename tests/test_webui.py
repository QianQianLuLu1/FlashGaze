"""FlashGaze WebUI 模块单元测试。

仅覆盖 flashgaze/webui/runner.py 与 gallery.py 中的纯逻辑函数；
所有依赖 gradio 的函数（build_app / main 等）不在此处测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flashgaze.defaults import DEFAULT_SCENE, DEFAULT_TOP
from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import Config, ExitCode
from flashgaze.webui import is_available
from flashgaze.webui.app import TABLE_HEADERS, _options_from_inputs
from flashgaze.webui.gallery import build_gallery_items, filter_rows
from flashgaze.webui.runner import (
    ScoringResult,
    build_run_config,
    export_manifest,
    run_scoring,
)
from tests.webui_helpers import make_result as _make_result
from tests.webui_helpers import make_score as _make_score

# ── 1. 导入与常量 ──────────────────────────────────────────────


def test_webui_imports() -> None:
    """验证 flashgaze.webui.app 可导入，且 DEFAULT_SCENE 存在于 defaults。"""
    # gradio 未安装时 is_available() 返回 False 也算通过——关键是导入不抛异常
    assert isinstance(is_available(), bool)
    # DEFAULT_SCENE 必须是字符串常量且非空
    assert isinstance(DEFAULT_SCENE, str) and DEFAULT_SCENE
    # TABLE_HEADERS 列数与 to_rows / _row_for 输出列数一致
    assert len(TABLE_HEADERS) == 18


# ── 2-3. build_run_config ──────────────────────────────────────


def test_build_run_config_basic() -> None:
    """build_run_config 装配 Config 的关键字段。"""
    config = build_run_config("/tmp/demo")
    assert isinstance(config, Config)
    assert config.directory == "/tmp/demo"
    # 未传 top 时回退到 DEFAULT_TOP
    assert config.top == DEFAULT_TOP
    # 默认 no_vlm 为 False（与 CLI 默认对齐）
    assert config.no_vlm is False


def test_build_run_config_no_vlm() -> None:
    """传入 no_vlm=True 时 config.no_vlm 必须为 True。"""
    config = build_run_config("/tmp/demo", ScoringOptions(no_vlm=True))
    assert config.no_vlm is True


def test_build_run_config_unchecked_box_does_not_override() -> None:
    """WebUI 语义：未勾选 = 不覆盖，故 None 不得作为 override 下传。"""
    assert ScoringOptions(no_vlm=False or None).to_config_kwargs() == {}


def test_build_run_config_env_config_file_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M-11：FLASHGAZE_CONFIG_FILE 指向的配置文件在 WebUI 入口同样生效。"""
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"enable_noise": True}), encoding="utf-8")
    monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", str(cfg_file))
    config = build_run_config("/tmp/demo")
    assert config.enable_noise is True


# ── 4. ScoringResult.to_rows ───────────────────────────────────


def test_scoring_result_to_rows() -> None:
    """to_rows() 行数与输入等长，列数与 TABLE_HEADERS 对齐。"""
    scored = [
        _make_score(
            "a.jpg",
            "/tmp/a.jpg",
            score=90.0,
            selected=True,
            composition=80.0,
            noise=70.0,
            color=60.0,
            face_count=1,
            face_sharpness=85.0,
            portrait_bonus=2.0,
            vlm_adjustment=1.5,
            vlm_reason="好",
            vlm_provider="qwen",
        ),
        _make_score(
            "b.jpg", "/tmp/b.jpg", score=50.0, selected=False, vlm_reason="", vlm_provider=""
        ),
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


def test_build_gallery_items_empty() -> None:
    """传入 None 或空结果时返回空列表。"""
    assert build_gallery_items(None) == []
    # 空 scored 同样返回空
    empty_result = _make_result([])
    assert build_gallery_items(empty_result) == []


def test_build_gallery_items_filter() -> None:
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


def test_filter_rows_keyword() -> None:
    """关键字匹配文件名或 vlm_reason，结果与 to_rows 同结构。"""
    scored = [
        _make_score("sunset_beach.jpg", "/tmp/sunset_beach.jpg", score=85.0, vlm_reason="夕阳"),
        _make_score("portrait_001.jpg", "/tmp/portrait_001.jpg", score=78.0, vlm_reason="人像"),
        _make_score("landscape.jpg", "/tmp/landscape.jpg", score=70.0, vlm_reason=""),
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


def test_run_scoring_empty_directory(tmp_path: Path) -> None:
    """传入不存在的目录返回 NO_IMAGES 错误码，且 result 为 None。"""
    missing = str(tmp_path / "does_not_exist")
    code, msg, result = run_scoring(missing, options=ScoringOptions(no_vlm=True))
    assert code == ExitCode.NO_IMAGES
    assert result is None
    assert "目录不存在" in msg


def test_run_scoring_no_images(tmp_path: Path) -> None:
    """传入存在但无图片的目录，返回 NO_IMAGES 错误码。"""
    code, msg, result = run_scoring(str(tmp_path), options=ScoringOptions(no_vlm=True))
    assert code == ExitCode.NO_IMAGES
    assert result is None
    assert "无支持" in msg or "无图片" in msg


@pytest.mark.slow
def test_run_scoring_no_vlm(fixtures_dir: Path) -> None:
    """对 tests/fixtures 跑纯离线评分（no_vlm=True），应成功并返回非空结果。"""
    code, msg, result = run_scoring(str(fixtures_dir), options=ScoringOptions(no_vlm=True))
    assert code == ExitCode.SUCCESS
    assert result is not None
    assert isinstance(result, ScoringResult)
    # fixtures 中至少有 sharp.jpg / blurry.jpg 等真实图
    assert len(result.scored) > 0
    # to_rows 输出与 scored 等长
    assert len(result.to_rows()) == len(result.scored)
    # 状态消息应包含耗时信息
    assert "ms" in msg or "耗时" in msg


# ── 10b. run_scoring C-01 导出目录排除（M-9 回归） ─────────────────


def test_run_scoring_passes_exclude_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scoring 把 exclusion_dirs 传入 iter_images（与 CLI/cleanup/MCP 对齐，C-01）。

    WebUI 曾漏传 exclude_dirs，导出过 ./精选 后重新评分会把导出副本重新计入
    统计，并可能二次导出生成带序号后缀的重复文件。
    """
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        "flashgaze.webui.runner.iter_images",
        # dict.update 返回 None → `or []` 恒返回空列表，避免把记录元组当图片列表下传
        lambda directory, recursive=True, exclude_dirs=(): (
            calls.update(args=(directory, exclude_dirs)) or []
        ),
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    code, _, result = run_scoring(str(ws), options=ScoringOptions(no_vlm=True))

    assert "args" in calls, "iter_images 应被 run_scoring 调用"
    directory_arg, exclude_dirs_arg = calls["args"]
    # 扫描根与其他三入口一致：resolve 后的 workspace
    assert Path(directory_arg).resolve() == ws.resolve()
    assert exclude_dirs_arg, "run_scoring 必须传入非空 exclude_dirs"
    assert (ws / "精选").resolve() in exclude_dirs_arg
    assert (ws / ".flashgaze_backup").resolve() in exclude_dirs_arg
    # 记录桩返回空列表 → 正常落入 NO_IMAGES 分支，不触发评分
    assert code == ExitCode.NO_IMAGES
    assert result is None


# ── 11. _options_from_inputs：dedup_threshold 滑块语义 ─────────────


def _call_options(dedup_threshold_val: float | str | None) -> ScoringOptions:
    """仅关心 dedup_threshold 分支，其余形参传默认值。"""
    return _options_from_inputs(
        None,
        None,
        None,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        dedup_threshold_val,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_options_dedup_threshold_zero_preserved() -> None:
    """#13-1 回归：滑块设 0（精确哈希匹配）必须保留为 0，不能因假值误归并到 None。"""
    opts = _call_options(0)
    assert opts.dedup_threshold == 0


def test_options_dedup_threshold_default_when_cleared() -> None:
    """滑块清空（None / ""）时才回退默认，不把 0 当未填写。"""
    assert _call_options(None).dedup_threshold is None
    assert _call_options("").dedup_threshold is None


def test_options_dedup_threshold_positive_preserved() -> None:
    """正常阈值（如 8）应原样保留。"""
    assert _call_options(8).dedup_threshold == 8


# ── 11b. _options_from_inputs：inf/NaN 不崩（FIX #3-6）─────────────


def test_options_infinity_and_nan_fall_back_to_none() -> None:
    """#3-6 回归：绕过 UI 的 API 直调可注入 inf（JSON 1e999），int(inf) 曾抛
    OverflowError 击穿 WebUI；现在逐字段安全转换，回退 None 让下层配置生效。"""
    opts = _options_from_inputs(
        float("inf"),  # top_val
        None,  # threshold_val
        None,  # scene_val
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        float("inf"),  # dedup_threshold_val
        None,  # vlm_provider_val
        float("inf"),  # workers_val
        None,
        None,
        None,
        None,
    )
    assert opts.top is None
    assert opts.dedup_threshold is None
    assert opts.workers is None

    nan_opts = _options_from_inputs(
        float("nan"),
        None,
        None,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        float("nan"),
        None,
        float("nan"),
        None,
        None,
        None,
        None,
    )
    assert nan_opts.top is None
    assert nan_opts.dedup_threshold is None
    assert nan_opts.workers is None


def test_options_normal_int_values_still_coerced() -> None:
    """回归：_safe_int_or_none 不得破坏既有强转语义（正常值原样保留）。"""
    opts = _options_from_inputs(
        5,
        None,
        None,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        8,
        None,
        3,
        None,
        None,
        None,
        None,
    )
    assert opts.top == 5
    assert opts.dedup_threshold == 8
    assert opts.workers == 3


# ── 12. 导出清单格式（#13-2 XLSX 入口） ───────────────────────────


def test_export_manifest_xlsx(tmp_path: Path) -> None:
    """#13-2 回归：WebUI 下载 XLSX 入口底层 export_manifest 须支持 'xlsx'。"""
    pytest.importorskip("openpyxl")  # XLSX 依赖 openpyxl，缺则跳过
    scored = [
        _make_score("a.jpg", "/tmp/a.jpg", score=90.0, selected=True),
        _make_score("b.jpg", "/tmp/b.jpg", score=50.0),
    ]
    # M-10 后清单路径须落在允许根内：显式把 workspace 设为 tmp_path，
    # 不再隐式依赖「pytest basetemp 恰在系统临时目录内」经临时分支放行
    result = _make_result(
        scored, config=build_run_config(str(tmp_path), ScoringOptions(no_vlm=True))
    )
    out = tmp_path / "report.xlsx"
    ok, _ = export_manifest(result, "xlsx", str(out))
    assert ok is True
    assert out.exists() and out.stat().st_size > 0
    # 'json' / 'csv' 路由未被破坏（回归）
    assert export_manifest(result, "json", str(tmp_path / "r.json"))[0] is True
    assert export_manifest(result, "csv", str(tmp_path / "r.csv"))[0] is True

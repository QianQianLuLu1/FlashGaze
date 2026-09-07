"""FlashGaze Web GUI 组件级测试。

在冒烟测试（build_app 能装配 Blocks）之上加深一层：
1. 组件树与默认值——断言各控件的初始 value / choices / 交互性；
2. 事件绑定（wiring）——通过 ``demo.fns`` 断言每个事件的输入/输出组件
   及其顺序，防止 ``run_btn.click(inputs=[...])`` 顺序错位这类 Gradio 高发 bug；
3. 处理器直接调用——从 ``demo.fns`` 取出闭包处理器（_on_score 等）直接
   调用，覆盖错误提示、结果装配、筛选与导出逻辑。

不调用 ``demo.launch``，不绑定端口，可在无头 CI 安全运行。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

gr = pytest.importorskip("gradio")

if TYPE_CHECKING:
    # 注解用真实类型；运行时 gradio 由上方 importorskip 守卫
    import gradio

from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TOP,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_WORKERS,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.options import ScoringOptions
from flashgaze.models.schemas import ExitCode
from flashgaze.webui.app import TABLE_HEADERS, _weights_from_sliders, build_app
from flashgaze.webui.runner import ScoringResult, build_run_config
from tests.webui_helpers import make_result, make_score

# build_app 会在装配时读取这些环境变量预填默认值，测试前统一清空保证确定性
_PREFILL_ENV_VARS = [
    "FLASHGAZE_API_KEY",
    "FLASHGAZE_API_BASE",
    "FLASHGAZE_MODEL",
    "FLASHGAZE_VLM_PROVIDER",
    "FLASHGAZE_SCENE",
    "FLASHGAZE_WORKERS",
]

# run_btn.click 的 22 个输入组件，顺序必须与 _on_score 形参一致
_SCORE_INPUT_IDS = [
    "fg-directory",
    "fg-top",
    "fg-threshold",
    "fg-scene",
    "fg-no-vlm",
    "fg-enable-composition",
    "fg-enable-noise",
    "fg-enable-color",
    "fg-enable-portrait",
    "fg-enable-dedup",
    "fg-no-downscale",
    "fg-dedup-threshold",
    "fg-w-sharpness",
    "fg-w-exposure",
    "fg-w-composition",
    "fg-w-noise",
    "fg-w-color",
    "fg-vlm-provider",
    "fg-workers",
    "fg-api-key",
    "fg-api-base",
    "fg-model",
]

# 首位 result_state 是 gr.State（无 elem_id），其余为展示组件；
# 末位 fg-download 是 M-8b 新增：新一轮评分开始时收起上一轮的下载组件
_SCORE_OUTPUT_IDS = [
    None,
    "fg-status",
    "fg-summary",
    "fg-table",
    "fg-gallery",
    "fg-export-status",
    "fg-filter-status",
    "fg-download",
]

_EXPECTED_HANDLER_NAMES = {
    "_toggle_vlm",
    "_on_score",
    "_on_filter",
    "_on_export",
    "_on_download_json",
    "_on_download_csv",
    "_on_download_xlsx",
}


# ── 公共 fixture 与工具 ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_prefill_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除 FLASHGAZE_* 预填环境变量，保证 build_app 默认值确定。"""
    for var in _PREFILL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def demo() -> gradio.Blocks:
    return build_app()


def _components(demo: gradio.Blocks) -> dict[str, Any]:
    """elem_id → 组件实例 的映射（只含有 elem_id 的组件）。

    抽成函数：需要「现场 build_app()」的用例（如环境变量预填回归，fixture 的
    demo 在测试体之前已装配，赶不上 monkeypatch.setenv）可直接复用。
    """
    mapping: dict[str, Any] = {}
    for b in demo.blocks.values():
        # elem_id 声明为 str | None；真值收窄为 str 再入键
        if b.elem_id:
            mapping[b.elem_id] = b
    return mapping


@pytest.fixture()
def comps(demo: gradio.Blocks) -> dict[str, Any]:
    """elem_id → 组件实例 的映射（只含有 elem_id 的组件）。"""
    return _components(demo)


def _fn(demo: gradio.Blocks, name: str) -> Any:
    """按处理器函数名从 demo.fns 取出 BlockFunction。"""
    for f in demo.fns.values():
        if getattr(f.fn, "__name__", None) == name:
            return f
    raise AssertionError(f"未找到事件处理器: {name}")


def _elem_ids(blocks: Any) -> list[str | None]:
    return [getattr(b, "elem_id", None) for b in blocks]


def _interactive_flag(update: Any) -> bool | None:
    """兼容 dict / 对象两种 gr.update 返回形态，读取 interactive 字段。"""
    if isinstance(update, dict):
        return cast("bool | None", update.get("interactive"))
    return cast("bool | None", getattr(update, "interactive", None))


def _visible_flag(update: Any) -> bool | None:
    """兼容 dict / 对象两种 gr.update 返回形态，读取 visible 字段。"""
    if isinstance(update, dict):
        return cast("bool | None", update.get("visible"))
    return cast("bool | None", getattr(update, "visible", None))


def _choice_values(choices: Any) -> list[Any]:
    """gradio 6 的 choices 可能是 (value, label) 元组列表，归一化为 value 列表。"""
    return [c[0] if isinstance(c, (tuple, list)) else c for c in choices]


def _form_defaults() -> dict[str, Any]:
    """与 UI 初始状态一致的表单值（_on_score 的 22 个输入）。"""
    return {
        "directory": "",
        "top": DEFAULT_TOP,
        "threshold": None,
        "scene": DEFAULT_SCENE,
        "no_vlm": False,
        "enable_composition": False,
        "enable_noise": False,
        "enable_color": False,
        "enable_portrait": False,
        "enable_dedup": False,
        "no_downscale": False,
        "dedup_threshold": DEFAULT_DEDUP_THRESHOLD,
        "w_sharpness": 0.5,
        "w_exposure": 0.5,
        "w_composition": 0.0,
        "w_noise": 0.0,
        "w_color": 0.0,
        "vlm_provider": DEFAULT_VLM_PROVIDER,
        "workers": DEFAULT_WORKERS,
        "api_key": "",
        "api_base": DEFAULT_API_BASE,
        "model": DEFAULT_MODEL,
    }


def _run_score(demo: gradio.Blocks, **overrides: Any) -> list[tuple[Any, ...]]:
    """按 _on_score 形参顺序直接调用处理器，返回全部 yield 的元组列表。"""
    vals = _form_defaults() | overrides
    order = [
        "directory",
        "top",
        "threshold",
        "scene",
        "no_vlm",
        "enable_composition",
        "enable_noise",
        "enable_color",
        "enable_portrait",
        "enable_dedup",
        "no_downscale",
        "dedup_threshold",
        "w_sharpness",
        "w_exposure",
        "w_composition",
        "w_noise",
        "w_color",
        "vlm_provider",
        "workers",
        "api_key",
        "api_base",
        "model",
    ]
    return list(_fn(demo, "_on_score").fn(*(vals[k] for k in order)))


# ── A. 组件树与默认值 ──────────────────────────────────────────


def test_directory_default_and_initial_dir_prefill() -> None:
    """directory 默认空串；build_app(initial_dir=...) 预填初始目录。"""
    by_id: dict[str, Any] = {}
    for b in build_app().blocks.values():
        if b.elem_id:
            by_id[b.elem_id] = b
    assert by_id["fg-directory"].value == ""
    by_id2: dict[str, Any] = {}
    for b in build_app(initial_dir=str(Path("/tmp/photos"))).blocks.values():
        if b.elem_id:
            by_id2[b.elem_id] = b
    assert by_id2["fg-directory"].value == str(Path("/tmp/photos"))


def test_basic_param_defaults(comps: dict[str, Any]) -> None:
    """top / threshold / dedup_threshold 的默认值与取值范围。"""
    assert comps["fg-top"].value == DEFAULT_TOP
    assert comps["fg-top"].minimum == 1
    assert comps["fg-threshold"].value is None
    assert comps["fg-dedup-threshold"].value == DEFAULT_DEDUP_THRESHOLD


def test_dropdown_choices(comps: dict[str, Any]) -> None:
    """场景与 VLM 提供商的可选项与 defaults 声明一致。"""
    assert _choice_values(comps["fg-scene"].choices) == list(SUPPORTED_SCENES)
    assert _choice_values(comps["fg-vlm-provider"].choices) == list(SUPPORTED_VLM_PROVIDERS)


def test_weight_slider_defaults(comps: dict[str, Any]) -> None:
    """五个权重滑块默认 0.5/0.5/0/0/0，范围 0–1。"""
    for eid in ("fg-w-sharpness", "fg-w-exposure", "fg-w-composition", "fg-w-noise", "fg-w-color"):
        assert comps[eid].minimum == 0.0
        assert comps[eid].maximum == 1.0
    assert comps["fg-w-sharpness"].value == 0.5
    assert comps["fg-w-exposure"].value == 0.5
    assert comps["fg-w-composition"].value == 0.0
    assert comps["fg-w-noise"].value == 0.0
    assert comps["fg-w-color"].value == 0.0


def test_checkbox_defaults(comps: dict[str, Any]) -> None:
    """所有复选框默认不勾选（与 CLI 默认对齐）。"""
    for eid in (
        "fg-no-vlm",
        "fg-enable-composition",
        "fg-enable-noise",
        "fg-enable-color",
        "fg-enable-portrait",
        "fg-enable-dedup",
        "fg-no-downscale",
        "fg-export-move",
        "fg-filter-selected",
    ):
        assert comps[eid].value is False, eid


def test_readonly_status_components(comps: dict[str, Any]) -> None:
    """状态/筛选/导出状态框为只读，避免用户手改伪造状态。"""
    for eid in ("fg-status", "fg-filter-status", "fg-export-status"):
        assert comps[eid].interactive is False, eid
    assert comps["fg-status"].value == "等待启动..."


def test_result_area_initial_state(comps: dict[str, Any]) -> None:
    """结果区初始：摘要零值、空表格（16 列表头、不可交互）、空画廊 4 列。"""
    assert comps["fg-summary"].value == {"total": 0, "selected": 0, "avg_score": 0.0}
    table = comps["fg-table"]
    assert list(table.headers) == TABLE_HEADERS
    assert table.interactive is False
    assert comps["fg-gallery"].columns == 4


def test_elem_ids_unique(comps: dict[str, Any]) -> None:
    """elem_id 不重复（E2E 选择器唯一性的前提）。"""
    assert len(comps) == len(set(comps))


# ── L18：FLASHGAZE_WORKERS 环境变量预填（非法值不得让 build_app 崩溃）────


def test_workers_env_invalid_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """L18 回归：非数字环境变量曾让 int() 抛 ValueError，WebUI 直接起不来。"""
    monkeypatch.setenv("FLASHGAZE_WORKERS", "abc")
    assert _components(build_app())["fg-workers"].value == DEFAULT_WORKERS


def test_workers_env_inf_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """L18 回归：inf/NaN 等非法数值同样回退默认并发数。"""
    for raw in ("inf", "nan", "1e999"):
        monkeypatch.setenv("FLASHGAZE_WORKERS", raw)
        assert _components(build_app())["fg-workers"].value == DEFAULT_WORKERS


def test_workers_env_valid_is_prefilled(monkeypatch: pytest.MonkeyPatch) -> None:
    """L18：合法环境变量仍按原样预填（不因加固而丢失功能）。"""
    monkeypatch.setenv("FLASHGAZE_WORKERS", "8")
    assert _components(build_app())["fg-workers"].value == 8


# ── B. 事件绑定（wiring） ─────────────────────────────────────


def test_all_handlers_registered(demo: gradio.Blocks) -> None:
    """build_app 注册了全部 7 个事件处理器。"""
    names = {getattr(f.fn, "__name__", None) for f in demo.fns.values()}
    assert _EXPECTED_HANDLER_NAMES <= names


def test_run_btn_wiring(demo: gradio.Blocks) -> None:
    """run_btn.click 绑定 _on_score：22 输入 / 8 输出且顺序严格一致。"""
    bf = _fn(demo, "_on_score")
    assert inspect.isgeneratorfunction(bf.fn), "_on_score 必须是生成器以流式更新进度"
    assert _elem_ids(bf.inputs) == _SCORE_INPUT_IDS
    assert _elem_ids(bf.outputs) == _SCORE_OUTPUT_IDS
    # 输出首位是 gr.State（会话级缓存评分结果）
    assert isinstance(bf.outputs[0], gr.State)


def test_no_vlm_toggle_wiring(demo: gradio.Blocks) -> None:
    """no_vlm.change → _toggle_vlm：输入 no_vlm，输出 VLM 配置区 5 组件。"""
    bf = _fn(demo, "_toggle_vlm")
    assert _elem_ids(bf.inputs) == ["fg-no-vlm"]
    assert _elem_ids(bf.outputs) == [
        "fg-vlm-provider",
        "fg-workers",
        "fg-api-key",
        "fg-api-base",
        "fg-model",
    ]


def test_filter_btn_wiring(demo: gradio.Blocks) -> None:
    """filter_btn.click 绑定 _on_filter：4 输入（State + 3 筛选控件）/ 3 输出。"""
    bf = _fn(demo, "_on_filter")
    assert _elem_ids(bf.inputs) == [
        None,
        "fg-filter-selected",
        "fg-filter-min-score",
        "fg-filter-keyword",
    ]
    assert _elem_ids(bf.outputs) == ["fg-table", "fg-gallery", "fg-filter-status"]


def test_export_wiring(demo: gradio.Blocks) -> None:
    """export/json/csv/xlsx 四个按钮均输出到 (export_status, download_file)。"""
    for name, btn_id in (
        ("_on_export", "fg-export-btn"),
        ("_on_download_json", "fg-json-btn"),
        ("_on_download_csv", "fg-csv-btn"),
        ("_on_download_xlsx", "fg-xlsx-btn"),
    ):
        bf = _fn(demo, name)
        assert _elem_ids(bf.outputs) == ["fg-export-status", "fg-download"], name
    # 导出按钮独有：inputs 为 State + 导出目录 + 移动开关
    assert _elem_ids(_fn(demo, "_on_export").inputs) == [
        None,
        "fg-export-dir",
        "fg-export-move",
    ]
    # 三个下载按钮只依赖评分结果 State
    for name in ("_on_download_json", "_on_download_csv", "_on_download_xlsx"):
        assert _elem_ids(_fn(demo, name).inputs) == [None], name


# ── C. 处理器逻辑（直接调用） ─────────────────────────────────


def test_toggle_vlm_disables_vlm_area(demo: gradio.Blocks) -> None:
    """勾选禁用 VLM：provider/api_key/api_base/model 不可交互，workers 保持可编辑。"""
    toggle = _fn(demo, "_toggle_vlm").fn
    provider, workers, api_key, api_base, model = toggle(True)
    assert _interactive_flag(provider) is False
    assert _interactive_flag(workers) is True
    assert _interactive_flag(api_key) is False
    assert _interactive_flag(api_base) is False
    assert _interactive_flag(model) is False


def test_toggle_vlm_reenables(demo: gradio.Blocks) -> None:
    """取消勾选后 VLM 配置区恢复可交互。"""
    provider, workers, api_key, api_base, model = _fn(demo, "_toggle_vlm").fn(False)
    assert _interactive_flag(provider) is True
    assert _interactive_flag(workers) is True
    assert _interactive_flag(api_key) is True
    assert _interactive_flag(api_base) is True
    assert _interactive_flag(model) is True


def test_weights_from_sliders_default() -> None:
    """默认滑块（comp/noise/color=0）只产出 sharpness + exposure。"""
    assert _weights_from_sliders(0.5, 0.5, 0.0, 0.0, 0.0) == {
        "sharpness": 0.5,
        "exposure": 0.5,
    }


def test_weights_from_sliders_optional_dims() -> None:
    """仅 >0 的可选维度进入权重；0 表示不参与。"""
    weights = _weights_from_sliders(0.5, 0.5, 0.2, 0.0, 0.3)
    assert weights == {
        "sharpness": 0.5,
        "exposure": 0.5,
        "composition": 0.2,
        "color": 0.3,
    }


def test_weights_from_sliders_all_zero_returns_none() -> None:
    """全 0 时返回 None，回退默认权重（build_config 归一化的约定）。"""
    assert _weights_from_sliders(0.0, 0.0, 0.0, 0.0, 0.0) is None


def test_on_score_empty_directory(demo: gradio.Blocks) -> None:
    """空目录：先 yield 清空态，再 yield ❌ [1] 请输入图片目录。"""
    yields = _run_score(demo, directory="")
    assert len(yields) == 2
    first = yields[0]
    assert first[0] is None
    assert first[1] == "评分中..."
    assert first[2] == {"total": 0, "selected": 0, "avg_score": 0.0}
    assert first[3] == [] and first[4] == []
    result, status, summary, rows, gallery, _, _, download_update = yields[1]
    assert result is None
    assert status == f"❌ [{int(ExitCode.PARAM_ERROR)}] 请输入图片目录"
    assert summary["total"] == 0
    assert rows == [] and gallery == []
    assert _visible_flag(download_update) is False, "失败时同样要收起下载组件"


def test_on_score_missing_directory(demo: gradio.Blocks, tmp_path: Path) -> None:
    """目录不存在：❌ [2] 目录不存在，且不残留旧结果。"""
    missing = str(tmp_path / "nope")
    yields = _run_score(demo, directory=missing, no_vlm=True)
    result, status, *_ = yields[-1]
    assert result is None
    assert status.startswith(f"❌ [{int(ExitCode.NO_IMAGES)}]")
    assert "目录不存在" in status


def test_on_score_vlm_without_api_key(demo: gradio.Blocks, tmp_path: Path) -> None:
    """有效目录但未禁用 VLM 且无 API Key：❌ [6] 未配置 API Key。"""
    yields = _run_score(demo, directory=str(tmp_path), no_vlm=False, api_key="")
    result, status, *_ = yields[-1]
    assert result is None
    assert status.startswith(f"❌ [{int(ExitCode.CONFIG_ERROR)}]")
    assert "API Key" in status


@pytest.mark.slow
def test_on_score_offline_success(demo: gradio.Blocks, photo_dir: str) -> None:
    """离线评分成功：结果/摘要/表格/画廊装配正确，corrupted 图不进画廊。"""
    yields = _run_score(demo, directory=str(photo_dir), no_vlm=True)
    assert len(yields) == 2, "错误路径之外的评分不应有多余中间 yield"
    result, status, summary, rows, gallery_items, export_st, filter_st, dl_upd = yields[1]
    assert _visible_flag(dl_upd) is False, "新一轮评分应收起上一轮的下载组件"
    assert isinstance(result, ScoringResult)
    assert status.startswith("✅ 完成: 共 4 张")
    assert summary["total"] == 4
    assert 0 < summary["selected"] <= 4
    assert len(rows) == 4
    for row in rows:
        assert len(row) == len(TABLE_HEADERS)
    # corrupted.jpg 解码失败被记为错误行，但不进入画廊
    assert len(gallery_items) == 3
    assert export_st == "" and filter_st == ""


@pytest.mark.slow
def test_on_score_top_one_selects_single(demo: gradio.Blocks, photo_dir: str) -> None:
    """top=1（数字输入交互）：入选数被截断为 1。"""
    yields = _run_score(demo, directory=str(photo_dir), no_vlm=True, top=1)
    _, status, summary, rows, *_ = yields[1]
    assert summary["selected"] == 1
    assert "入选 1 张" in status
    # 表格仍展示全部 4 行（top 只影响入选标记，不过滤行）
    assert len(rows) == 4


@pytest.mark.slow
def test_on_score_zero_threshold_treated_as_unset(demo: gradio.Blocks, photo_dir: str) -> None:
    """回归（E2E 发现）：Gradio 客户端把留空 Number 序列化为 0 发送。

    threshold=0 若被当作「已设置」，selection 走 score>=0 全选分支并静默
    忽略 top；0 必须与未设置等价，top 才能生效。
    """
    yields = _run_score(demo, directory=str(photo_dir), no_vlm=True, top=1, threshold=0)
    _, status, summary, *_ = yields[1]
    assert summary["selected"] == 1
    assert "入选 1 张" in status


def test_on_score_hides_download_component(demo: gradio.Blocks) -> None:
    """M-8b：新一轮评分从第一个 yield 起就收起下载组件（避免下载到过期清单）。"""
    for payload in _run_score(demo, directory=""):
        assert len(payload) == 8, "输出契约已扩展为 8 项"
        assert _visible_flag(payload[7]) is False, "评分全程应隐藏下载组件"


def test_on_filter_without_result(demo: gradio.Blocks) -> None:
    """未评分先筛选：清空视图并提示「请先完成评分」。"""
    rows, gallery_items, status = _fn(demo, "_on_filter").fn(None, False, 0.0, "")
    assert rows == [] and gallery_items == []
    assert status == "请先完成评分"


def test_on_filter_selected_and_keyword(demo: gradio.Blocks) -> None:
    """筛选处理器：仅看入选、关键字、最低分数的组合逻辑与计数消息。"""
    result = make_result(
        [
            make_score("sharp.jpg", "/x/sharp.jpg", score=90.0, selected=True),
            make_score("blurry.jpg", "/x/blurry.jpg", score=50.0, selected=False),
            make_score("sharp2.jpg", "/x/sharp2.jpg", score=70.0, selected=True),
        ]
    )
    handler = _fn(demo, "_on_filter").fn
    rows, items, status = handler(result, True, 0.0, "")
    assert [r[0] for r in rows] == ["sharp.jpg", "sharp2.jpg"]
    assert len(items) == 2
    assert "筛选后 2 条" in status
    rows_kw, _, _ = handler(result, False, 0.0, "sharp")
    assert [r[0] for r in rows_kw] == ["sharp.jpg", "sharp2.jpg"]
    rows_score, _, _ = handler(result, False, 80.0, "")
    assert [r[0] for r in rows_score] == ["sharp.jpg"]


def test_on_export_guards(demo: gradio.Blocks) -> None:
    """导出守卫：无结果时静默；导出目录为空/纯空白时提示填写。"""
    handler = _fn(demo, "_on_export").fn
    assert handler(None, "/tmp/out", False) == ("", None)
    assert handler(make_result([make_score("a.jpg", "/a.jpg")]), "", False) == (
        "请填写导出目录",
        None,
    )
    assert handler(make_result([make_score("a.jpg", "/a.jpg")]), "   ", False) == (
        "请填写导出目录",
        None,
    )


def test_on_export_copies_selected_images(demo: gradio.Blocks, tmp_path: Path) -> None:
    """导出成功：workspace 内的入选图片被复制，非入选图片不复制。

    安全加固后导出目标必须落在被评分的 workspace 内（越界硬拒绝），
    故在此构造一个临时 workspace，并把源图与评分结果的 directory 都指向它。
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    src_selected = ws / "sharp.jpg"
    src_dropped = ws / "blurry.jpg"
    src_selected.write_bytes(b"fake-sel")
    src_dropped.write_bytes(b"fake-drop")
    result = make_result(
        [
            make_score("sharp.jpg", str(src_selected), score=90.0, selected=True),
            make_score("blurry.jpg", str(src_dropped), score=10.0, selected=False),
        ],
        config=build_run_config(str(ws), ScoringOptions(no_vlm=True)),
    )
    dest = ws / "exported"
    _, download = _fn(demo, "_on_export").fn(result, str(dest), False)
    assert download is None
    assert (dest / "sharp.jpg").exists()
    assert not (dest / "blurry.jpg").exists()


def _download_result(fixtures_dir: Path) -> ScoringResult:
    return make_result(
        [
            make_score("sharp.jpg", str(fixtures_dir / "sharp.jpg"), score=90.0, selected=True),
            make_score("blurry.jpg", str(fixtures_dir / "blurry.jpg"), score=50.0),
        ]
    )


def _download_path(update: Any) -> str | None:
    """从下载处理器的第二个返回值提取文件路径（兼容 gr.update dict 与裸路径）。"""
    if update is None:
        return None
    if isinstance(update, dict):
        return cast("str | None", update.get("value"))
    return str(update)


def test_on_download_without_result(demo: gradio.Blocks) -> None:
    """未评分点下载：统一提示「无结果可导出」且不产出文件。"""
    for name in ("_on_download_json", "_on_download_csv", "_on_download_xlsx"):
        msg, path = _fn(demo, name).fn(None)
        assert msg == "无结果可导出", name
        assert path is None, name


def test_on_download_json_writes_manifest(demo: gradio.Blocks, fixtures_dir: Path) -> None:
    """JSON 下载：产出可解析的清单文件，并让隐藏的下载组件可见。"""
    _, update = _fn(demo, "_on_download_json").fn(_download_result(fixtures_dir))
    path = _download_path(update)
    assert path is not None and Path(path).exists()
    assert isinstance(update, dict) and update.get("visible") is True
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data


def test_on_download_json_c08_unique_tmp(demo: gradio.Blocks, fixtures_dir: Path) -> None:
    """C-08 / M-8a 回归：二次下载生成新文件，且**不删**上一次的文件（多会话不串号）。

    旧实现同 key 会 unlink 上一份：--host 0.0.0.0 / --share 下多会话并发下载时，
    后一次下载会删掉前一次会话正在下载的文件（串号 / 拿错结果）。
    """
    handler = _fn(demo, "_on_download_json").fn
    _, first_upd = handler(_download_result(fixtures_dir))
    _, second_upd = handler(_download_result(fixtures_dir))
    first = _download_path(first_upd)
    second = _download_path(second_upd)
    assert first is not None and second is not None
    assert first != second
    assert Path(first).exists(), "上一次下载的文件必须仍然可用"
    assert Path(second).exists()


def test_on_download_tmp_pruned_beyond_window(
    demo: gradio.Blocks, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-8a：独立注册不退化成无限堆积——超出保留窗口的最旧文件被回收。"""
    import flashgaze.webui.app as app_mod

    monkeypatch.setattr(app_mod, "_DOWNLOAD_KEEP_PER_KEY", 3)
    handler = _fn(demo, "_on_download_json").fn
    paths: list[str | None] = []
    for _ in range(4):
        _, update = handler(_download_result(fixtures_dir))
        paths.append(_download_path(update))
    assert len({p for p in paths if p}) == 4, "每次下载都是独立文件"
    assert paths[0] is not None and not Path(paths[0]).exists(), "最旧的一份应被回收"
    assert all(Path(p).exists() for p in paths[1:] if p), "窗口内的文件仍在"


def test_on_download_csv_and_xlsx(demo: gradio.Blocks, fixtures_dir: Path) -> None:
    """CSV / XLSX 下载入口与 JSON 对称（xlsx 依赖 openpyxl，缺则跳过）。"""
    pytest.importorskip("openpyxl")
    result = _download_result(fixtures_dir)
    _, csv_update = _fn(demo, "_on_download_csv").fn(result)
    csv_path = _download_path(csv_update)
    assert csv_path is not None and Path(csv_path).suffix == ".csv"
    assert Path(csv_path).exists()
    _, xlsx_update = _fn(demo, "_on_download_xlsx").fn(result)
    xlsx_path = _download_path(xlsx_update)
    assert xlsx_path is not None and Path(xlsx_path).suffix == ".xlsx"
    assert Path(xlsx_path).stat().st_size > 0
    assert xlsx_update.get("visible") is True

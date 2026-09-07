"""FlashGaze Web GUI 入口（Gradio Blocks）。

启动命令 `flashgaze-webui`。所有 CLI 参数都映射到界面控件，
评分调用复用 `flashgaze.webui.runner.run_scoring`，不引入新的评分代码路径。
"""

from __future__ import annotations

import argparse
import math
import os
import secrets
import sys
import tempfile
import threading
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from flashgaze import __version__
from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_CSV_OUTPUT,
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TOP,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_WORKERS,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.options import ScoringOptions
from flashgaze.utils.logging import get_logger
from flashgaze.webui import is_available
from flashgaze.webui.gallery import build_gallery_items, filter_rows
from flashgaze.webui.runner import (
    ScoringResult,
    export_manifest,
    export_to_dir,
    run_scoring,
)

logger = get_logger()

if TYPE_CHECKING:
    # 仅类型检查期导入：gradio 属可选依赖（[gui] extras），运行时在函数内 lazy import
    import gradio as gr

# ── 表格列定义（与 CSV 列对齐） ──────────────────────────────

TABLE_HEADERS = [
    "文件名",
    "分数",
    "清晰度",
    "曝光",
    "构图",
    "噪点",
    "色彩",
    "人脸数",
    "人脸清晰",
    "人像加分",
    "VLM补偿",
    "VLM理由",
    "VLM提供商",
    "VLM参与",
    "VLM错误",
    "入选",
    "去重",
    "错误",
]


def _ensure_gradio() -> None:
    """延迟导入 gradio，未安装时给出明确提示并退出。"""
    if not is_available():
        print(
            '[FlashGaze] gradio 未安装，请运行: pip install -e ".[gui]"',
            file=sys.stderr,
        )
        raise SystemExit(6)


# C-08：下载临时文件唯一化，避免多会话固定文件名互相覆盖（串号/结果泄露）。
# M-8a：注册键带 uuid——每次下载各自独立注册，互不删除；同一逻辑 key 仅保留最近
# _DOWNLOAD_KEEP_PER_KEY 份，超出按 FIFO 回收，兼顾「不互删」与「避免无限堆积」。
_DOWNLOAD_TMP: dict[str, str] = {}
_DOWNLOAD_KEEP_PER_KEY = 32
# MED-3: _prune_downloads 的「列出 owned → pop」复合序列非原子，--host 0.0.0.0 /
# --share 下多会话并发进入下载回调时，pop 可能命中已被其它线程移除的键而 KeyError、
# 中断一次下载。注册表全部读改写经此锁串行化（锁内不做磁盘 IO 的 unlink）。
_DOWNLOAD_TMP_LOCK = threading.Lock()


def _next_download_path(suffix: str, key: str) -> str:
    """生成唯一临时文件路径供 gr.File 下载。

    每次下载以 `<key>:<uuid4>` 独立注册：--host 0.0.0.0 / --share 下多会话并发
    下载时，任一次下载都不会删掉别的会话正在下载的文件（旧实现按固定 key 覆盖并
    unlink 上一份，导致串号 / 拿到上一份结果）。仅当同一逻辑 key 的存量超过
    _DOWNLOAD_KEEP_PER_KEY 时，才按 FIFO 回收最旧的若干份。
    """
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="flashgaze_")
    os.close(fd)
    with _DOWNLOAD_TMP_LOCK:
        _DOWNLOAD_TMP[f"{key}:{uuid.uuid4().hex}"] = path
    _prune_downloads(key)
    return path


def _prune_downloads(key: str) -> None:
    """回收同一逻辑 key 超出保留窗口的旧临时文件（FIFO）。

    注册表读改写持 _DOWNLOAD_TMP_LOCK 串行化（MED-3）；待删文件的 unlink 在锁外
    执行——路径已从注册表移除、且由 mkstemp 唯一命名，不会被并发线程重复处理，
    锁内做磁盘 IO 只会拉长其它会话下载回调的等待。删除失败（Windows 下文件仍被
    占用）静默跳过，不得中断当前下载。
    """
    with _DOWNLOAD_TMP_LOCK:
        prefix = f"{key}:"
        owned = [k for k in _DOWNLOAD_TMP if k.startswith(prefix)]
        stale: list[str] = []
        while len(owned) > _DOWNLOAD_KEEP_PER_KEY:
            oldest = owned.pop(0)
            stale.append(_DOWNLOAD_TMP.pop(oldest))
    for path in stale:
        try:
            os.unlink(path)
        except OSError:
            pass


def _weights_from_sliders(
    sharpness: float,
    exposure: float,
    composition: float,
    noise: float,
    color: float,
) -> dict[str, float] | None:
    """把五个滑块的值组装成权重 dict（仅当 composition/noise/color > 0 时包含）。

    build_config 内部会自动归一化，这里只需保留原始值。
    """
    weights: dict[str, float] = {
        "sharpness": float(sharpness),
        "exposure": float(exposure),
    }
    if float(composition) > 0:
        weights["composition"] = float(composition)
    if float(noise) > 0:
        weights["noise"] = float(noise)
    if float(color) > 0:
        weights["color"] = float(color)
    total = sum(weights.values())
    if total <= 0:
        return None
    return weights


def _safe_int_or_none(value: Any) -> int | None:
    """int() 强转；非法或非有限值（inf/NaN，如 API 直调注入的 1e999）返回 None。

    FIX(#3-6): int(float('inf')) 抛 OverflowError，不在 (TypeError, ValueError)
    内；表单组件的 minimum/maximum 拦不住绕过 UI 的 API 直调，逐字段兜底。
    """
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _options_from_inputs(
    top_val: float | None,
    threshold_val: float | None,
    scene_val: str | None,
    no_vlm_val: bool,
    enable_comp_val: bool,
    enable_noise_val: bool,
    enable_color_val: bool,
    enable_portrait_val: bool,
    enable_dedup_val: bool,
    no_downscale_val: bool,
    dedup_threshold_val: float | str | None,
    vlm_provider_val: str | None,
    workers_val: float | None,
    api_key_val: str | None,
    api_base_val: str | None,
    model_val: str | None,
    weights: dict[str, float] | None,
) -> ScoringOptions:
    """把 Gradio 组件值装配成 ScoringOptions（唯一的"表单值 → 评分旋钮"适配器）。

    形参顺序与 `run_btn.click(inputs=[...])` 保持一致（directory 与五个权重滑块除外，
    后者由 `_weights_from_sliders` 先合成 weights）。

    两类字段的 None 语义不同，不要混用：

    - **布尔开关**（复选框）：传用户的真实选择。取消勾选是"明确选了关"，
      必须以 False 覆盖 env / 配置文件，与 CLI / MCP 传真实 bool 的语义一致。
      写成 `bool(x) or None` 会把 False 退化成"没表态"，一旦将来给这些开关
      加上环境变量，用户取消勾选就会被静默忽略。
    - **字符串 / 可选值字段**（scene、vlm_provider、api_key、api_base、model）：
      留空表示"用户没填"，故保留 `or None` 让下层配置生效。
    """
    return ScoringOptions(
        top=_safe_int_or_none(top_val) if top_val else None,
        # FIX: Gradio 客户端把留空的 Number 序列化为 0 发送（而非 null）。若把 0
        # 当作「已设置阈值」，selection 会走 score>=0 全选分支并静默忽略 top——
        # 用户填 top=1 却得到全部入选。阈值 0 与未设置的过滤语义等价，统一视为
        # 未设置（与 dedup_threshold 保留 0 的做法不同：那里 0 是精确匹配的合法值）。
        threshold=float(threshold_val) if threshold_val else None,
        scene=scene_val or None,
        no_vlm=bool(no_vlm_val),
        enable_composition=bool(enable_comp_val),
        enable_noise=bool(enable_noise_val),
        enable_color=bool(enable_color_val),
        enable_portrait=bool(enable_portrait_val),
        dedup=bool(enable_dedup_val),
        # FIX(#13-1): dedup_threshold 滑块 minimum=0，用户设 0（精确哈希匹配）是合法值，
        # 不能因 `if dedup_threshold_val` 把 0 当假值归并到 None 而回退默认阈值(8)。
        # 仅当用户清空（None / "" 等非数值）时才回退，与同函数的 threshold 处理一致。
        dedup_threshold=(
            _safe_int_or_none(dedup_threshold_val)
            if isinstance(dedup_threshold_val, (int, float))
            else None
        ),
        no_downscale=bool(no_downscale_val),
        vlm_provider=vlm_provider_val or None,
        workers=_safe_int_or_none(workers_val) if workers_val else None,
        api_key=api_key_val or None,
        api_base=api_base_val or None,
        model=model_val or None,
        weights=weights,
    )


def build_app(
    initial_dir: str = "",
    allowed_roots: list[str] | None = None,
) -> gr.Blocks:
    """装配 Gradio Blocks 应用。

    initial_dir: 由 `flashgaze-webui --dir` 传入，预填到目录输入框（不自动开始评分）。
    """
    import gradio as gr

    # 从环境变量预填默认值，与 CLI 默认值保持一致。
    # 注意：出于安全考虑不预填 API Key（见下方 api_key 文本框），避免把服务端真实
    # 密钥序列化进前端页面配置；留空时评分仍回退使用服务端环境变量。
    env_api_base = os.environ.get("FLASHGAZE_API_BASE", DEFAULT_API_BASE)
    env_model = os.environ.get("FLASHGAZE_MODEL", DEFAULT_MODEL)
    env_provider = os.environ.get("FLASHGAZE_VLM_PROVIDER", DEFAULT_VLM_PROVIDER)
    env_scene = os.environ.get("FLASHGAZE_SCENE", DEFAULT_SCENE)
    # FIX(L18): 原裸 int() 遇非法环境变量（"abc"/"inf"/"1e999"）抛 ValueError，
    # WebUI 直接起不来；与表单字段一致改走 _safe_int_or_none，非法值回退默认。
    # `or DEFAULT_WORKERS` 同时兜住 0 与负数（gr.Number minimum=1）。
    env_workers = (
        _safe_int_or_none(os.environ.get("FLASHGAZE_WORKERS", str(DEFAULT_WORKERS)))
        or DEFAULT_WORKERS
    )

    # Blocks.__enter__ 返回 self；先绑定变量再进 with，使 demo 获得构造器的
    # 静态类型（gr.Blocks）而非 __enter__ 的宽松返回
    demo = gr.Blocks(title="FlashGaze 瞬选灵眸")
    with demo:
        # ── 头部 ────────────────────────────────────────
        gr.HTML(
            f"""
            <div id="fg-header">
              <h1>FlashGaze 瞬选灵眸 · Web GUI</h1>
              <p>CV 客观评分 + VLM 场景补偿 · 与 CLI 完全对齐 · 离线模式可用 · v{__version__}</p>
            </div>
            """,
        )

        # 用 State 缓存当前评分结果，供后续筛选/导出复用
        result_state = gr.State(value=None)

        with gr.Row():
            # ── 左列：参数配置 ────────────────────────────────
            with gr.Column(scale=1, min_width=380):
                gr.Markdown("### 1 · 目录与基础参数")
                directory = gr.Textbox(
                    elem_id="fg-directory",
                    label="图片目录",
                    value=initial_dir or "",
                    placeholder="输入或粘贴图片所在目录的绝对路径（递归扫描子目录）",
                    info="对应 CLI 位置参数 directory",
                )

                with gr.Row():
                    top = gr.Number(
                        elem_id="fg-top",
                        label="选取前 N 张",
                        value=DEFAULT_TOP,
                        precision=0,
                        minimum=1,
                        maximum=10000,
                        info="对应 --top",
                    )
                    threshold = gr.Number(
                        elem_id="fg-threshold",
                        label="分数阈值（可选）",
                        value=None,
                        minimum=0.0,
                        maximum=100.0,
                        info="设置后忽略 top，对应 --threshold",
                    )

                with gr.Row():
                    scene = gr.Dropdown(
                        elem_id="fg-scene",
                        label="场景模式",
                        choices=list(SUPPORTED_SCENES),
                        value=env_scene,
                        info="对应 --scene",
                    )
                    no_vlm = gr.Checkbox(
                        elem_id="fg-no-vlm",
                        label="禁用 VLM（纯离线 CV 评分）",
                        value=False,
                        info="对应 --no-vlm；勾选后 VLM 配置区将被禁用",
                    )

                gr.Markdown("### 2 · CV 增强维度")
                with gr.Row():
                    enable_composition = gr.Checkbox(
                        elem_id="fg-enable-composition",
                        label="构图（三分法）",
                        value=False,
                        info="--enable-composition",
                    )
                    enable_noise = gr.Checkbox(
                        elem_id="fg-enable-noise",
                        label="噪点（BRISQUE）",
                        value=False,
                        info="--enable-noise",
                    )
                    enable_color = gr.Checkbox(
                        elem_id="fg-enable-color",
                        label="色彩丰富度",
                        value=False,
                        info="--enable-color",
                    )
                with gr.Row():
                    enable_portrait = gr.Checkbox(
                        elem_id="fg-enable-portrait",
                        label="人像专项",
                        value=False,
                        info="--enable-portrait",
                    )
                    enable_dedup = gr.Checkbox(
                        elem_id="fg-enable-dedup",
                        label="PHash 去重",
                        value=False,
                        info="--enable-dedup",
                    )
                    no_downscale = gr.Checkbox(
                        elem_id="fg-no-downscale",
                        label="禁用降采样",
                        value=False,
                        info="--no-downscale",
                    )

                dedup_threshold = gr.Number(
                    elem_id="fg-dedup-threshold",
                    label="去重汉明距离阈值",
                    value=DEFAULT_DEDUP_THRESHOLD,
                    precision=0,
                    minimum=0,
                    maximum=64,
                    info="对应 --dedup-threshold，越小越严格",
                )

                gr.Markdown("### 3 · 权重（自动归一化）")
                gr.Markdown(
                    "<span style='font-size:12px;color:#666'>"
                    "composition / noise / color 滑块设为 0 表示不参与加权；"
                    "build_config 会按总和归一化。对应 --weights"
                    "</span>"
                )
                with gr.Row():
                    w_sharpness = gr.Slider(
                        0.0, 1.0, 0.5, step=0.05, label="清晰度", elem_id="fg-w-sharpness"
                    )
                    w_exposure = gr.Slider(
                        0.0, 1.0, 0.5, step=0.05, label="曝光度", elem_id="fg-w-exposure"
                    )
                with gr.Row():
                    w_composition = gr.Slider(
                        0.0, 1.0, 0.0, step=0.05, label="构图", elem_id="fg-w-composition"
                    )
                    w_noise = gr.Slider(
                        0.0, 1.0, 0.0, step=0.05, label="噪点", elem_id="fg-w-noise"
                    )
                    w_color = gr.Slider(
                        0.0, 1.0, 0.0, step=0.05, label="色彩", elem_id="fg-w-color"
                    )

                gr.Markdown("### 4 · VLM 配置")
                with gr.Row():
                    vlm_provider = gr.Dropdown(
                        elem_id="fg-vlm-provider",
                        label="VLM 提供商",
                        choices=list(SUPPORTED_VLM_PROVIDERS),
                        value=env_provider,
                        info="对应 --vlm-provider；所有 provider 走内置 pin-IP 直连层，无需 litellm（litellm 仅可选兜底）",
                    )
                    workers = gr.Number(
                        elem_id="fg-workers",
                        label="并发线程数",
                        value=env_workers,
                        precision=0,
                        minimum=1,
                        maximum=64,
                        info="对应 --workers",
                    )
                api_key = gr.Textbox(
                    elem_id="fg-api-key",
                    label="API Key",
                    value="",
                    type="password",
                    placeholder="留空则使用服务端 FLASHGAZE_API_KEY 环境变量；仅离线模式可不填",
                    info="对应 --api-key；出于安全考虑不预填服务端密钥，留空即复用服务端环境变量",
                )
                with gr.Row():
                    api_base = gr.Textbox(
                        elem_id="fg-api-base",
                        label="API 端点",
                        value=env_api_base,
                        info="对应 --api-base",
                    )
                    model = gr.Textbox(
                        elem_id="fg-model",
                        label="模型名称",
                        value=env_model,
                        info="对应 --model",
                    )

                run_btn = gr.Button(
                    "▶ 开始评分", variant="primary", size="lg", elem_id="fg-run-btn"
                )
                status_box = gr.Textbox(
                    elem_id="fg-status",
                    label="状态",
                    value="等待启动...",
                    interactive=False,
                    lines=2,
                )

            # ── 右列：结果展示 ────────────────────────────────
            with gr.Column(scale=2, min_width=600):
                gr.Markdown("### 5 · 评分结果")
                with gr.Row():
                    summary_box = gr.JSON(
                        elem_id="fg-summary",
                        label="摘要",
                        value={"total": 0, "selected": 0, "avg_score": 0.0},
                    )
                result_table = gr.Dataframe(
                    elem_id="fg-table",
                    headers=TABLE_HEADERS,
                    datatype=[
                        "str",
                        "number",
                        "number",
                        "number",
                        "str",
                        "str",
                        "str",
                        "number",
                        "str",
                        "number",
                        "number",
                        "str",
                        "str",
                        "str",
                        "str",
                        "str",
                    ],
                    value=[],
                    wrap=False,
                    interactive=False,
                    row_count=20,
                    column_count=len(TABLE_HEADERS),
                )

                gr.Markdown("### 6 · 高分图预览")
                gallery = gr.Gallery(
                    elem_id="fg-gallery",
                    label="高分图画廊（按分数降序）",
                    value=[],
                    columns=4,
                    height=400,
                    object_fit="cover",
                    show_label=True,
                )

                with gr.Accordion("筛选（不影响导出，仅刷新表格与画廊）", open=False):
                    with gr.Row():
                        filter_selected = gr.Checkbox(
                            elem_id="fg-filter-selected", label="仅看入选", value=False
                        )
                        filter_min_score = gr.Slider(
                            0.0,
                            100.0,
                            0.0,
                            step=1.0,
                            label="最低分数",
                            elem_id="fg-filter-min-score",
                        )
                        filter_keyword = gr.Textbox(
                            elem_id="fg-filter-keyword",
                            label="关键字（文件名/VLM理由）",
                            value="",
                        )
                    filter_btn = gr.Button("应用筛选", elem_id="fg-filter-btn")
                    filter_status = gr.Textbox(
                        elem_id="fg-filter-status",
                        label="筛选结果",
                        value="",
                        interactive=False,
                    )

                gr.Markdown("### 7 · 导出")
                with gr.Row():
                    export_dir = gr.Textbox(
                        elem_id="fg-export-dir",
                        label="导出目录",
                        value=DEFAULT_EXPORT_DIR,
                        info="对应 --export-dir；相对路径以评分目录为基准解析",
                    )
                    export_move = gr.Checkbox(
                        elem_id="fg-export-move",
                        label="移动而非复制",
                        value=False,
                        info="--move",
                    )
                with gr.Row():
                    export_btn = gr.Button("复制/移动高分图", elem_id="fg-export-btn")
                    json_btn = gr.Button("下载 JSON", elem_id="fg-json-btn")
                    csv_btn = gr.Button("下载 CSV", elem_id="fg-csv-btn")
                    # FIX(#13-2): 与 CLI --xlsx 对等的清单入口，补齐 WebUI 导出能力缺口
                    xlsx_btn = gr.Button("下载 XLSX", elem_id="fg-xlsx-btn")
                download_file = gr.File(label="下载文件", visible=False, elem_id="fg-download")
                export_status = gr.Textbox(
                    elem_id="fg-export-status",
                    label="导出状态",
                    value="",
                    interactive=False,
                )

        # ── 事件：no_vlm 切换时禁用 VLM 配置区 ─────────────
        def _toggle_vlm(no_vlm_val: bool) -> tuple[Any, ...]:
            """禁用 VLM 配置区，避免无效配置。"""
            return (
                gr.update(interactive=not no_vlm_val),  # vlm_provider
                gr.update(interactive=True),  # workers（离线模式也保持可编辑）
                gr.update(interactive=not no_vlm_val),  # api_key
                gr.update(interactive=not no_vlm_val),  # api_base
                gr.update(interactive=not no_vlm_val),  # model
            )

        no_vlm.change(
            _toggle_vlm,
            inputs=[no_vlm],
            outputs=[vlm_provider, workers, api_key, api_base, model],
        )

        # ── 事件：开始评分 ─────────────────────────────────
        def _on_score(
            directory_val: str,
            top_val: float | None,
            threshold_val: float | None,
            scene_val: str | None,
            no_vlm_val: bool,
            enable_comp_val: bool,
            enable_noise_val: bool,
            enable_color_val: bool,
            enable_portrait_val: bool,
            enable_dedup_val: bool,
            no_downscale_val: bool,
            dedup_threshold_val: float | str | None,
            w_sharp_val: float,
            w_exposure_val: float,
            w_comp_val: float,
            w_noise_val: float,
            w_color_val: float,
            vlm_provider_val: str | None,
            workers_val: float | None,
            api_key_val: str | None,
            api_base_val: str | None,
            model_val: str | None,
        ) -> Iterator[tuple[Any, ...]]:
            """生成器：实时更新进度，最终 yield 评分结果。"""
            progress = gr.Progress()

            def progress_cb(done: int, total: int, stage: str = "") -> None:
                ratio = done / max(total, 1)
                progress(ratio, desc=stage or f"{done}/{total}")

            weights = _weights_from_sliders(
                w_sharp_val,
                w_exposure_val,
                w_comp_val,
                w_noise_val,
                w_color_val,
            )

            # 启动时清空旧结果；M-8b：同时收起上一轮的下载组件，
            # 否则用户会看到（并下载到）上一轮评分的过期清单。
            yield (
                None,  # result_state
                "评分中...",  # status
                {"total": 0, "selected": 0, "avg_score": 0.0},  # summary
                [],  # table
                [],  # gallery
                "",  # export_status
                "",  # filter_status
                gr.update(visible=False),  # download_file（M-8b）
            )

            code, msg, result = run_scoring(
                directory_val,
                options=_options_from_inputs(
                    top_val,
                    threshold_val,
                    scene_val,
                    no_vlm_val,
                    enable_comp_val,
                    enable_noise_val,
                    enable_color_val,
                    enable_portrait_val,
                    enable_dedup_val,
                    no_downscale_val,
                    dedup_threshold_val,
                    vlm_provider_val,
                    workers_val,
                    api_key_val,
                    api_base_val,
                    model_val,
                    weights,
                ),
                progress=progress_cb,
                allowed_roots=allowed_roots,
            )

            if code != 0 or result is None:
                yield (
                    None,
                    f"❌ [{int(code)}] {msg}",
                    {"total": 0, "selected": 0, "avg_score": 0.0},
                    [],
                    [],
                    "",
                    "",
                    gr.update(visible=False),  # download_file（M-8b）
                )
                return

            yield (
                result,
                f"✅ {msg}",
                result.summary,
                result.to_rows(),
                build_gallery_items(result, limit=200),
                "",
                "",
                gr.update(visible=False),  # download_file（M-8b）
            )

        run_btn.click(
            _on_score,
            inputs=[
                directory,
                top,
                threshold,
                scene,
                no_vlm,
                enable_composition,
                enable_noise,
                enable_color,
                enable_portrait,
                enable_dedup,
                no_downscale,
                dedup_threshold,
                w_sharpness,
                w_exposure,
                w_composition,
                w_noise,
                w_color,
                vlm_provider,
                workers,
                api_key,
                api_base,
                model,
            ],
            outputs=[
                result_state,
                status_box,
                summary_box,
                result_table,
                gallery,
                export_status,
                filter_status,
                download_file,  # M-8b：新一轮评分收起下载组件
            ],
        )

        # ── 事件：筛选 ─────────────────────────────────────
        def _on_filter(
            result_val: ScoringResult | None,
            only_sel: bool,
            min_score_val: float,
            kw: str,
        ) -> tuple[list[list[Any]], list[tuple[str, str]], str]:
            if not result_val:
                return [], [], "请先完成评分"
            rows = filter_rows(
                result_val,
                only_selected=bool(only_sel),
                min_score=float(min_score_val) if min_score_val > 0 else None,
                keyword=kw or "",
            )
            items = build_gallery_items(
                result_val,
                only_selected=bool(only_sel),
                min_score=float(min_score_val) if min_score_val > 0 else None,
                limit=200,
            )
            return rows, items, f"筛选后 {len(rows)} 条 / 画廊 {len(items)} 张"

        filter_btn.click(
            _on_filter,
            inputs=[result_state, filter_selected, filter_min_score, filter_keyword],
            outputs=[result_table, gallery, filter_status],
        )

        # ── 事件：导出（复制/移动） ───────────────────────
        def _on_export(
            result_val: ScoringResult | None,
            dest_dir_val: str,
            move_val: bool,
        ) -> tuple[str, None]:
            if not result_val:
                return "", None
            # C-26：空串/纯空白导出目录会 resolve 到 CWD 根，误把高分图撒进工作目录，
            # 故显式拦截；越界校验与相对路径解析统一收敛在 export_to_dir——
            # 相对目录以评分目录为基准（N-1 契约对齐），此处透传原始值不按 CWD resolve。
            export_dir = (dest_dir_val or "").strip()
            if not export_dir:
                return "请填写导出目录", None
            _, msg = export_to_dir(result_val, export_dir, move=bool(move_val))
            return msg, None

        export_btn.click(
            _on_export,
            inputs=[result_state, export_dir, export_move],
            outputs=[export_status, download_file],
        )

        # ── 事件：下载 JSON ────────────────────────────────
        def _on_download_json(result_val: ScoringResult | None) -> tuple[str, Any]:
            if not result_val:
                return "无结果可导出", None
            try:
                tmp = _next_download_path(".json", "json")  # C-08：唯一临时文件
                ok, msg = export_manifest(result_val, "json", tmp)
                if not ok:
                    return msg, None
                # 返回裸路径不会改变 visible=False 的初始状态，必须显式 update，
                # 否则下载组件永不出现、用户拿不到文件。
                return msg, gr.update(value=tmp, visible=True)
            except Exception as e:  # noqa: BLE001 — 导出失败转为 UI 错误消息，不崩 WebUI
                return f"JSON 导出失败: {e}", None

        json_btn.click(
            _on_download_json,
            inputs=[result_state],
            outputs=[export_status, download_file],
        )

        # ── 事件：下载 CSV ────────────────────────────────
        def _on_download_csv(result_val: ScoringResult | None) -> tuple[str, Any]:
            if not result_val:
                return "无结果可导出", None
            try:
                # C-08：唯一临时文件；.csv 扩展名沿用 DEFAULT_CSV_OUTPUT 约定
                suffix = os.path.splitext(DEFAULT_CSV_OUTPUT)[1]
                tmp = _next_download_path(suffix, "csv")
                ok, msg = export_manifest(result_val, "csv", tmp)
                if not ok:
                    return msg, None
                return msg, gr.update(value=tmp, visible=True)
            except Exception as e:  # noqa: BLE001 — 导出失败转为 UI 错误消息，不崩 WebUI
                return f"CSV 导出失败: {e}", None

        csv_btn.click(
            _on_download_csv,
            inputs=[result_state],
            outputs=[export_status, download_file],
        )

        # FIX(#13-2): XLSX 清单下载入口，与 JSON/CSV 完全对称
        def _on_download_xlsx(result_val: ScoringResult | None) -> tuple[str, Any]:
            if not result_val:
                return "无结果可导出", None
            try:
                tmp = _next_download_path(".xlsx", "xlsx")
                ok, msg = export_manifest(result_val, "xlsx", tmp)
                if not ok:
                    return msg, None
                return msg, gr.update(value=tmp, visible=True)
            except Exception as e:  # noqa: BLE001 — 导出失败转为 UI 错误消息，不崩 WebUI
                return f"XLSX 导出失败: {e}", None

        xlsx_btn.click(
            _on_download_xlsx,
            inputs=[result_state],
            outputs=[export_status, download_file],
        )

    return demo


def _is_public_binding(host: str | None, share: bool) -> bool:
    """判断是否对外暴露：--share 或 host 为非回环地址。

    仅 127.0.0.1 / localhost / ::1 / 空 视为本机回环，其余（含 0.0.0.0、局域网或公网 IP）
    一律视为对外暴露，需要强制鉴权。host 允许 None（如 local_url 解析失败），按空处理。
    """
    if share:
        return True
    h = (host or "").strip().lower()
    return h not in ("127.0.0.1", "localhost", "::1", "")


def _compute_launch_auth(
    host: str, share: bool, auth_arg: str | None
) -> tuple[str, str] | None:
    """计算 demo.launch 的 auth 参数。

    - 仅回环（默认 127.0.0.1）且非 --share：返回 None（本地无鉴权，向后兼容）。
    - 对外暴露时**强制鉴权**：显式 --auth user:pass 优先；否则自动生成随机令牌
      （用户名 admin）并打印到 stderr，杜绝在无凭据下暴露服务。
    """
    if not _is_public_binding(host, share):
        return None
    if auth_arg:
        parts = auth_arg.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
        # 格式不合法仍退回自动令牌，避免暴露无鉴权
        logger.warning("--auth 格式应为 user:password，已忽略并自动生成令牌")
    token = secrets.token_urlsafe(16)
    print(
        "[FlashGaze][安全] WebUI 对外暴露，已强制开启登录鉴权。\n"
        f"          用户名: admin\n          令牌: {token}\n"
        "          请仅将此令牌告知授权用户；如需固定凭据请用 --auth user:password",
        file=sys.stderr,
    )
    return ("admin", token)


def _build_arg_parser() -> argparse.ArgumentParser:
    """flashgaze-webui CLI 参数解析。"""
    p = argparse.ArgumentParser(
        prog="flashgaze-webui",
        description="FlashGaze Web GUI — 浏览器访问的可视化评分界面",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址（默认 127.0.0.1 仅本机可访问；设为 0.0.0.0 将暴露到局域网/公网，须配合 --auth）",
    )
    p.add_argument(
        "--port",
        type=int,
        default=7860,
        help="监听端口（默认 7860）",
    )
    p.add_argument(
        "--dir",
        dest="initial_dir",
        default="",
        help="初始图片目录（仅作界面预填，不自动开始评分）",
    )
    p.add_argument(
        "--share",
        action="store_true",
        help="启用 Gradio 临时公网链接（会暴露到互联网，强制要求 --auth，已自动生成令牌）",
    )
    p.add_argument(
        "--auth",
        default=None,
        help="对外暴露时的登录凭据，格式 user:password；省略则自动生成随机令牌打印到 stderr",
    )
    p.add_argument(
        "--allow-root",
        action="append",
        dest="allow_roots",
        default=[],
        metavar="DIR",
        help="允许评分的根目录白名单（可重复传入）；提供后仅这些目录内可被扫描，封堵任意目录枚举",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"flashgaze-webui {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """flashgaze-webui 命令入口。"""
    # 先解析参数（让 --version / --help 在无 gradio 时也能正常工作）
    args = _build_arg_parser().parse_args(argv)
    _ensure_gradio()

    # 把初始目录预填到目录输入框（不自动开始评分）
    import gradio as gr

    demo = build_app(initial_dir=args.initial_dir, allowed_roots=args.allow_roots)

    print(
        f"[FlashGaze] Web GUI 启动中: http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    # 公网暴露风险提示（替代原诱导用户 --host 0.0.0.0 的文案）
    if _is_public_binding(args.host, args.share):
        print(
            "[FlashGaze][安全] WebUI 正在对外暴露（--host/--share）。"
            "已强制开启登录鉴权，请勿在不可信网络长期无 --auth 运行。",
            file=sys.stderr,
        )

    fg_css = """
    #fg-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 18px 24px; border-radius: 12px; }
    #fg-header h1 { margin: 0; font-size: 22px; }
    #fg-header p { margin: 4px 0 0; opacity: 0.85; font-size: 13px; }
    .fg-tab { padding: 6px 0; }
    """

    auth = _compute_launch_auth(args.host, args.share, args.auth)
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        auth=auth,
        show_error=False,
        inbrowser=False,
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="slate"),
        css=fg_css,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

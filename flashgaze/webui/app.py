"""FlashGaze Web GUI 入口（Gradio Blocks）。

启动命令 `flashgaze-webui`。所有 CLI 参数都映射到界面控件，
评分调用复用 `flashgaze.webui.runner.run_scoring`，不引入新的评分代码路径。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from flashgaze import __version__
from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_CSV_OUTPUT,
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TOP,
    DEFAULT_VLM_MAX_ADJUSTMENT,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_WORKERS,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.webui import is_available
from flashgaze.webui.gallery import build_gallery_items, filter_rows
from flashgaze.webui.runner import (
    ScoringResult,
    build_json_text,
    export_manifest,
    export_to_dir,
    run_scoring,
)


# ── 表格列定义（与 CSV 列对齐） ──────────────────────────────

TABLE_HEADERS = [
    "文件名", "分数", "清晰度", "曝光", "构图", "噪点", "色彩",
    "人脸数", "人脸清晰", "人像加分", "VLM补偿", "VLM理由",
    "VLM提供商", "入选", "去重", "错误",
]


def _ensure_gradio():
    """延迟导入 gradio，未安装时给出明确提示并退出。"""
    if not is_available():
        print(
            "[FlashGaze] gradio 未安装，请运行: pip install -e \".[gui]\"",
            file=sys.stderr,
        )
        raise SystemExit(6)


def _weights_from_sliders(
    sharpness: float, exposure: float, composition: float, noise: float, color: float,
) -> Optional[dict[str, float]]:
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


def build_app(initial_dir: str = ""):  # noqa: PLR0915  UI 装配函数，拆分会破坏可读性
    """装配 Gradio Blocks 应用。

    initial_dir: 由 `flashgaze-webui --dir` 传入，预填到目录输入框（不自动开始评分）。
    """
    import gradio as gr

    # 从环境变量预填默认值，与 CLI 默认值保持一致
    env_api_key = os.environ.get("FLASHGAZE_API_KEY", "")
    env_api_base = os.environ.get("FLASHGAZE_API_BASE", DEFAULT_API_BASE)
    env_model = os.environ.get("FLASHGAZE_MODEL", DEFAULT_MODEL)
    env_provider = os.environ.get("FLASHGAZE_VLM_PROVIDER", DEFAULT_VLM_PROVIDER)
    env_scene = os.environ.get("FLASHGAZE_SCENE", DEFAULT_SCENE)
    env_workers = int(os.environ.get("FLASHGAZE_WORKERS", str(DEFAULT_WORKERS)))

    with gr.Blocks(title="FlashGaze 瞬选灵眸") as demo:
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
                    label="图片目录",
                    value=initial_dir or "",
                    placeholder="输入或粘贴图片所在目录的绝对路径（递归扫描子目录）",
                    info="对应 CLI 位置参数 directory",
                )

                with gr.Row():
                    top = gr.Number(
                        label="选取前 N 张", value=DEFAULT_TOP,
                        precision=0, minimum=1, maximum=10000,
                        info="对应 --top",
                    )
                    threshold = gr.Number(
                        label="分数阈值（可选）", value=None,
                        minimum=0.0, maximum=100.0,
                        info="设置后忽略 top，对应 --threshold",
                    )

                with gr.Row():
                    scene = gr.Dropdown(
                        label="场景模式", choices=list(SUPPORTED_SCENES),
                        value=env_scene,
                        info="对应 --scene",
                    )
                    no_vlm = gr.Checkbox(
                        label="禁用 VLM（纯离线 CV 评分）",
                        value=False,
                        info="对应 --no-vlm；勾选后 VLM 配置区将被禁用",
                    )

                gr.Markdown("### 2 · CV 增强维度")
                with gr.Row():
                    enable_composition = gr.Checkbox(label="构图（三分法）", value=False, info="--enable-composition")
                    enable_noise = gr.Checkbox(label="噪点（BRISQUE）", value=False, info="--enable-noise")
                    enable_color = gr.Checkbox(label="色彩丰富度", value=False, info="--enable-color")
                with gr.Row():
                    enable_portrait = gr.Checkbox(label="人像专项", value=False, info="--enable-portrait")
                    enable_dedup = gr.Checkbox(label="PHash 去重", value=False, info="--enable-dedup")
                    no_downscale = gr.Checkbox(label="禁用降采样", value=False, info="--no-downscale")

                dedup_threshold = gr.Number(
                    label="去重汉明距离阈值", value=DEFAULT_DEDUP_THRESHOLD,
                    precision=0, minimum=0, maximum=64,
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
                    w_sharpness = gr.Slider(0.0, 1.0, 0.5, 0.05, label="清晰度")
                    w_exposure = gr.Slider(0.0, 1.0, 0.5, 0.05, label="曝光度")
                with gr.Row():
                    w_composition = gr.Slider(0.0, 1.0, 0.0, 0.05, label="构图")
                    w_noise = gr.Slider(0.0, 1.0, 0.0, 0.05, label="噪点")
                    w_color = gr.Slider(0.0, 1.0, 0.0, 0.05, label="色彩")

                gr.Markdown("### 4 · VLM 配置")
                with gr.Row():
                    vlm_provider = gr.Dropdown(
                        label="VLM 提供商",
                        choices=list(SUPPORTED_VLM_PROVIDERS),
                        value=env_provider,
                        info="对应 --vlm-provider；非 qwen 需安装 litellm",
                    )
                    workers = gr.Number(
                        label="并发线程数", value=env_workers,
                        precision=0, minimum=1, maximum=64,
                        info="对应 --workers",
                    )
                api_key = gr.Textbox(
                    label="API Key", value=env_api_key,
                    type="password",
                    placeholder="未设置时仅离线模式可用",
                    info="对应 --api-key；优先读取环境变量 FLASHGAZE_API_KEY",
                )
                with gr.Row():
                    api_base = gr.Textbox(
                        label="API 端点", value=env_api_base,
                        info="对应 --api-base",
                    )
                    model = gr.Textbox(
                        label="模型名称", value=env_model,
                        info="对应 --model",
                    )

                run_btn = gr.Button("▶ 开始评分", variant="primary", size="lg")
                status_box = gr.Textbox(
                    label="状态", value="等待启动...",
                    interactive=False, lines=2,
                )

            # ── 右列：结果展示 ────────────────────────────────
            with gr.Column(scale=2, min_width=600):
                gr.Markdown("### 5 · 评分结果")
                with gr.Row():
                    summary_box = gr.JSON(
                        label="摘要",
                        value={"total": 0, "selected": 0, "avg_score": 0.0},
                    )
                result_table = gr.Dataframe(
                    headers=TABLE_HEADERS,
                    datatype=["str", "number", "number", "number",
                              "str", "str", "str",
                              "number", "str", "number",
                              "number", "str", "str", "str", "str", "str"],
                    value=[],
                    wrap=False,
                    interactive=False,
                    row_count=20,
                    column_count=(len(TABLE_HEADERS), "fixed"),
                )

                gr.Markdown("### 6 · 高分图预览")
                gallery = gr.Gallery(
                    label="高分图画廊（按分数降序）",
                    value=[], columns=4, height=400,
                    object_fit="cover",
                    show_label=True,
                )

                with gr.Accordion("筛选（不影响导出，仅刷新表格与画廊）", open=False):
                    with gr.Row():
                        filter_selected = gr.Checkbox(label="仅看入选", value=False)
                        filter_min_score = gr.Slider(
                            0.0, 100.0, 0.0, 1.0,
                            label="最低分数",
                        )
                        filter_keyword = gr.Textbox(
                            label="关键字（文件名/VLM理由）", value="",
                        )
                    filter_btn = gr.Button("应用筛选")
                    filter_status = gr.Textbox(
                        label="筛选结果", value="", interactive=False,
                    )

                gr.Markdown("### 7 · 导出")
                with gr.Row():
                    export_dir = gr.Textbox(
                        label="导出目录", value=DEFAULT_EXPORT_DIR,
                        info="对应 --export-dir",
                    )
                    export_move = gr.Checkbox(label="移动而非复制", value=False, info="--move")
                with gr.Row():
                    export_btn = gr.Button("复制/移动高分图")
                    json_btn = gr.Button("下载 JSON")
                    csv_btn = gr.Button("下载 CSV")
                download_file = gr.File(label="下载文件", visible=False)
                export_status = gr.Textbox(
                    label="导出状态", value="", interactive=False,
                )

        # ── 事件：no_vlm 切换时禁用 VLM 配置区 ─────────────
        def _toggle_vlm(no_vlm_val: bool):
            """禁用 VLM 配置区，避免无效配置。"""
            return (
                gr.update(interactive=not no_vlm_val),  # vlm_provider
                gr.update(interactive=not no_vlm_val),  # workers
                gr.update(interactive=not no_vlm_val),  # api_key
                gr.update(interactive=not no_vlm_val),  # api_base
                gr.update(interactive=not no_vlm_val),  # model
            )

        no_vlm.change(
            _toggle_vlm, inputs=[no_vlm],
            outputs=[vlm_provider, workers, api_key, api_base, model],
        )

        # ── 事件：开始评分 ─────────────────────────────────
        def _on_score(
            directory_val, top_val, threshold_val, scene_val, no_vlm_val,
            enable_comp_val, enable_noise_val, enable_color_val,
            enable_portrait_val, enable_dedup_val, no_downscale_val,
            dedup_threshold_val,
            w_sharp_val, w_exposure_val, w_comp_val, w_noise_val, w_color_val,
            vlm_provider_val, workers_val, api_key_val, api_base_val, model_val,
        ):
            """生成器：实时更新进度，最终 yield 评分结果。"""
            progress = gr.Progress()

            def progress_cb(done: int, total: int, stage: str = ""):
                ratio = done / max(total, 1)
                progress(ratio, desc=stage or f"{done}/{total}")

            weights = _weights_from_sliders(
                w_sharp_val, w_exposure_val, w_comp_val, w_noise_val, w_color_val,
            )

            # 启动时清空旧结果
            yield (
                None,  # result_state
                "评分中...",  # status
                {"total": 0, "selected": 0, "avg_score": 0.0},  # summary
                [],   # table
                [],   # gallery
                "",   # export_status
                "",   # filter_status
            )

            code, msg, result = run_scoring(
                directory_val,
                top=int(top_val) if top_val else None,
                threshold=float(threshold_val) if threshold_val is not None else None,
                no_vlm=bool(no_vlm_val),
                enable_composition=bool(enable_comp_val),
                enable_noise=bool(enable_noise_val),
                enable_color=bool(enable_color_val),
                enable_portrait=bool(enable_portrait_val),
                dedup=bool(enable_dedup_val),
                dedup_threshold=int(dedup_threshold_val) if dedup_threshold_val else None,
                no_downscale=bool(no_downscale_val),
                api_key=api_key_val or None,
                api_base=api_base_val or None,
                model=model_val or None,
                vlm_provider=vlm_provider_val or None,
                scene=scene_val or None,
                workers=int(workers_val) if workers_val else None,
                weights=weights,
                progress=progress_cb,
            )

            if code != 0 or result is None:
                yield (
                    None,
                    f"❌ [{int(code)}] {msg}",
                    {"total": 0, "selected": 0, "avg_score": 0.0},
                    [], [], "", "",
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
            )

        run_btn.click(
            _on_score,
            inputs=[
                directory, top, threshold, scene, no_vlm,
                enable_composition, enable_noise, enable_color,
                enable_portrait, enable_dedup, no_downscale,
                dedup_threshold,
                w_sharpness, w_exposure, w_composition, w_noise, w_color,
                vlm_provider, workers, api_key, api_base, model,
            ],
            outputs=[
                result_state, status_box, summary_box,
                result_table, gallery, export_status, filter_status,
            ],
        )

        # ── 事件：筛选 ─────────────────────────────────────
        def _on_filter(result_val, only_sel, min_score_val, kw):
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
        def _on_export(result_val, dest_dir_val, move_val):
            if not result_val:
                return "", None
            count, msg = export_to_dir(result_val, dest_dir_val, move=bool(move_val))
            return msg, None

        export_btn.click(
            _on_export,
            inputs=[result_state, export_dir, export_move],
            outputs=[export_status, download_file],
        )

        # ── 事件：下载 JSON ────────────────────────────────
        def _on_download_json(result_val):
            if not result_val:
                return "无结果可导出", None
            try:
                tmp = Path(tempfile.gettempdir()) / "flashgaze_result.json"
                ok, msg = export_manifest(result_val, "json", str(tmp))
                if not ok:
                    return msg, None
                return msg, str(tmp)
            except Exception as e:
                return f"JSON 导出失败: {e}", None

        json_btn.click(
            _on_download_json,
            inputs=[result_state],
            outputs=[export_status, download_file],
        )

        # ── 事件：下载 CSV ────────────────────────────────
        def _on_download_csv(result_val):
            if not result_val:
                return "无结果可导出", None
            try:
                tmp = Path(tempfile.gettempdir()) / DEFAULT_CSV_OUTPUT
                ok, msg = export_manifest(result_val, "csv", str(tmp))
                if not ok:
                    return msg, None
                return msg, str(tmp)
            except Exception as e:
                return f"CSV 导出失败: {e}", None

        csv_btn.click(
            _on_download_csv,
            inputs=[result_state],
            outputs=[export_status, download_file],
        )

    return demo


def _build_arg_parser() -> argparse.ArgumentParser:
    """flashgaze-webui CLI 参数解析。"""
    p = argparse.ArgumentParser(
        prog="flashgaze-webui",
        description="FlashGaze Web GUI — 浏览器访问的可视化评分界面",
    )
    p.add_argument(
        "--host", default="127.0.0.1",
        help="监听地址（默认 127.0.0.1，局域网访问需显式传 0.0.0.0）",
    )
    p.add_argument(
        "--port", type=int, default=7860,
        help="监听端口（默认 7860）",
    )
    p.add_argument(
        "--dir", dest="initial_dir", default="",
        help="初始图片目录（仅作界面预填，不自动开始评分）",
    )
    p.add_argument(
        "--share", action="store_true",
        help="启用 Gradio 临时公网链接（默认关闭，仅本机可访问）",
    )
    p.add_argument(
        "--version", action="version",
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

    demo = build_app(initial_dir=args.initial_dir)

    print(
        f"[FlashGaze] Web GUI 启动中: http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    if args.host == "127.0.0.1":
        print(
            "[FlashGaze] 仅本机可访问；如需局域网访问请用 --host 0.0.0.0",
            file=sys.stderr,
        )

    fg_css = """
    #fg-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 18px 24px; border-radius: 12px; }
    #fg-header h1 { margin: 0; font-size: 22px; }
    #fg-header p { margin: 4px 0 0; opacity: 0.85; font-size: 13px; }
    .fg-tab { padding: 6px 0; }
    """

    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        show_error=True,
        inbrowser=False,
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="slate"),
        css=fg_css,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

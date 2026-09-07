"""FlashGaze Web GUI Playwright E2E 测试。

对真实启动的 Gradio 服务做浏览器级黑盒验证，覆盖：
- 表单交互（目录/数字输入/禁用 VLM 联动/筛选控件）
- 错误提示（空目录 / 目录不存在 / 未配置 API Key）
- 结果渲染（状态、摘要 JSON、评分表格、画廊、导出与下载）

选择器均基于 app.py 中的 elem_id（fg-*），并已对 Gradio 6 的实际 DOM 实证：
- gr.Button 的 elem_id 直接落在 <button> 上；
- status_box 因 lines=2 渲染为 <textarea>，其余单行状态框为 <input>；
- Dataframe 使用虚拟滚动，数据行需按单元格 data-row 属性去重统计；
- Gallery 的条目类名为 .thumbnail-item；
- 下载 gr.File 返回 gr.update(value=..., visible=True) 后才渲染 .file-preview。

运行：pytest tests/e2e -v --browser chromium（依赖 ``pip install -e ".[gui,xlsx]"``
与 ``pip install pytest-playwright``）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytest.importorskip("gradio")
pytest.importorskip("pytest_playwright")

pytestmark = [pytest.mark.e2e]

# lines=2 的状态框渲染为 textarea，单行状态框为 input，两种都兼容
STATUS = "#fg-status textarea, #fg-status input"
FILTER_STATUS = "#fg-filter-status textarea, #fg-filter-status input"
EXPORT_STATUS = "#fg-export-status textarea, #fg-export-status input"

NO_VLM_LABEL = "禁用 VLM（纯离线 CV 评分）"

# 离线评分对 3 有效 + 1 损坏图目录的固定期望值
TOTAL_IMAGES = 4
SELECTED_IMAGES = 3
GALLERY_ITEMS = 3  # 损坏图解码失败，不进画廊


def _status_value(page: Page, selector: str) -> str:
    # 最小环境（typecheck）缺 playwright 时 Page 为 Any，str() 收敛回 str；
    # 真实 playwright 的 input_value() 本就返回 str，此处为幂等包装
    return str(page.locator(selector).first.input_value())


def _wait_status(page: Page, selector: str, fragment: str, timeout: int = 60000) -> None:
    """轮询状态框值直至包含指定片段（Gradio 异步事件完成的可靠信号）。"""
    page.wait_for_function(
        f"() => (document.querySelector('{selector}')?.value ?? '').includes('{fragment}')",
        timeout=timeout,
    )


def _table_row_count(page: Page) -> int:
    """Gradio Dataframe 虚拟滚动下按单元格 data-row 去重统计实际渲染行数。"""
    # evaluate_all 经 JS 求值返回 Any，int() 收敛为行数
    return int(
        page.locator("#fg-table [data-row]").evaluate_all(
            "els => [...new Set(els.map(e => e.getAttribute('data-row')))].length"
        )
    )


def run_offline_scoring(page: Page, directory: str, *, top: int | None = None) -> None:
    """填表并点击评分，等到状态出现 ✅（离线模式评分 4 张图约 2–4 秒）。"""
    page.get_by_label("图片目录").fill(directory)
    no_vlm = page.get_by_label(NO_VLM_LABEL)
    if not no_vlm.is_checked():
        no_vlm.check()
    if top is not None:
        top_input = page.get_by_label("选取前 N 张")
        top_input.fill(str(top))
        top_input.press("Enter")  # gr.Number 在回车/失焦时才提交新值
        expect(top_input).to_have_value(str(top))
    page.locator("#fg-run-btn").click()
    _wait_status(page, STATUS, "✅")


# ── E1 页面加载 ────────────────────────────────────────────────


def test_page_loads(page: Page, webui_url: str) -> None:
    """页面加载：标题、横幅、评分按钮就位。"""
    page.goto(webui_url)
    expect(page).to_have_title("FlashGaze 瞬选灵眸")
    expect(page.locator("#fg-header h1")).to_contain_text("FlashGaze 瞬选灵眸")
    expect(page.locator("#fg-run-btn")).to_be_visible()
    expect(page.locator("#fg-run-btn")).to_contain_text("开始评分")
    expect(page.locator("#fg-table")).to_be_visible()


# ── E2 表单交互：禁用 VLM 联动 ─────────────────────────────────


def test_no_vlm_toggle_disables_vlm_config(page: Page, webui_url: str) -> None:
    """勾选禁用 VLM：VLM 配置区输入禁用、并发线程数保持可编辑；取消后恢复。

    gradio 对禁用的表现因组件而异（实证 Gradio 6）：密码框/下拉保留 input 并置
    disabled，普通文本框（api_base/model）直接移除 input 渲染为静态文本。
    """
    page.goto(webui_url)
    box = page.get_by_label(NO_VLM_LABEL)

    box.check()
    expect(page.locator("#fg-vlm-provider input")).to_be_disabled()
    expect(page.locator("#fg-api-key input")).to_be_disabled()
    expect(page.locator("#fg-api-base input")).to_have_count(0)
    expect(page.locator("#fg-model input")).to_have_count(0)
    expect(page.locator("#fg-workers input")).to_be_enabled()

    box.uncheck()
    # 实证 Gradio 6：api_base/model 一旦渲染过静态文本，重新启用后 input 也不会
    # 恢复（仅 provider/api_key 恢复 input），故恢复方向断言这两者 + 组件仍在。
    expect(page.locator("#fg-vlm-provider input")).to_be_enabled()
    expect(page.locator("#fg-api-key input")).to_be_enabled()
    expect(page.locator("#fg-api-base")).to_be_visible()
    expect(page.locator("#fg-model")).to_be_visible()


# ── E3-E5 错误提示 ────────────────────────────────────────────


def test_empty_directory_error(page: Page, webui_url: str) -> None:
    """空目录点击评分：❌ [1] 请输入图片目录。"""
    page.goto(webui_url)
    page.locator("#fg-run-btn").click()
    _wait_status(page, STATUS, "❌", timeout=30000)
    assert _status_value(page, STATUS) == "❌ [1] 请输入图片目录"


def test_missing_directory_error(page: Page, webui_url: str) -> None:
    """不存在的目录：状态提示目录不存在（ExitCode.NO_IMAGES=3）。"""
    page.goto(webui_url)
    page.get_by_label("图片目录").fill("Z:/flashgaze_definitely_missing_dir")
    page.locator("#fg-run-btn").click()
    _wait_status(page, STATUS, "❌", timeout=30000)
    status = _status_value(page, STATUS)
    assert status.startswith("❌ [3]")
    assert "目录不存在" in status


def test_vlm_without_api_key_error(page: Page, webui_url: str, e2e_photo_dir: Path) -> None:
    """有效目录但未禁用 VLM 且未填 API Key：❌ [6] 未配置 API Key。"""
    page.goto(webui_url)
    no_vlm = page.get_by_label(NO_VLM_LABEL)
    if no_vlm.is_checked():
        no_vlm.uncheck()
    page.get_by_label("API Key").fill("")
    page.get_by_label("图片目录").fill(str(e2e_photo_dir))
    page.locator("#fg-run-btn").click()
    _wait_status(page, STATUS, "❌", timeout=30000)
    status = _status_value(page, STATUS)
    assert status.startswith("❌ [6]")
    assert "API Key" in status


# ── E6-E7 结果渲染 ────────────────────────────────────────────


def test_offline_scoring_renders_results(page: Page, webui_url: str, e2e_photo_dir: Path) -> None:
    """离线评分成功：状态、摘要 JSON、表格 4 行、画廊 3 项全部渲染。"""
    page.goto(webui_url)
    run_offline_scoring(page, str(e2e_photo_dir))
    expect(page.locator(STATUS).first).to_have_value(
        re.compile(r"✅ 完成: 共 4 张，入选 3 张，耗时 \d+ ms")
    )

    summary = page.locator("#fg-summary").inner_text()
    normalized = summary.replace(" ", "").replace("\n", "")
    assert '"total":4' in normalized
    assert '"selected":3' in normalized

    assert _table_row_count(page) == TOTAL_IMAGES
    expect(page.locator("#fg-gallery .thumbnail-item")).to_have_count(GALLERY_ITEMS)


def test_top_one_limits_selection(page: Page, webui_url: str, e2e_photo_dir: Path) -> None:
    """数字输入交互：top=1 时入选数截断为 1，表格仍展示全部行。"""
    page.goto(webui_url)
    run_offline_scoring(page, str(e2e_photo_dir), top=1)
    expect(page.locator(STATUS).first).to_have_value(re.compile("入选 1 张"))
    assert _table_row_count(page) == TOTAL_IMAGES


# ── E8 筛选交互 ──────────────────────────────────────────────


def test_filter_refreshes_table_and_gallery(scored_page: Page, e2e_photo_dir: Path) -> None:
    """仅看入选 + 关键字筛选：表格/画廊刷新，筛选状态给出计数。"""
    page = scored_page

    # 筛选区在折叠面板内，先展开
    page.get_by_text("筛选（不影响导出，仅刷新表格与画廊）").click()
    page.get_by_label("仅看入选").check()
    page.locator("#fg-filter-btn").click()
    _wait_status(page, FILTER_STATUS, "筛选后", timeout=30000)
    assert (
        _status_value(page, FILTER_STATUS)
        == f"筛选后 {SELECTED_IMAGES} 条 / 画廊 {GALLERY_ITEMS} 张"
    )
    assert _table_row_count(page) == SELECTED_IMAGES

    # 关键字 "sharp" 只命中 sharp.jpg（画廊不过滤关键字，与实现一致）
    page.get_by_label("关键字（文件名/VLM理由）").fill("sharp")
    page.locator("#fg-filter-btn").click()
    _wait_status(page, FILTER_STATUS, "筛选后 1 条", timeout=30000)
    assert _table_row_count(page) == 1


# ── E9 导出交互 ──────────────────────────────────────────────


def test_export_copies_selected_images(scored_page: Page, e2e_photo_dir: Path) -> None:
    """复制/移动高分图：入选文件落到导出目录，未入选与损坏图不导出。

    安全加固后导出目标必须落在被评分的 workspace 内（越界硬拒绝），
    故导出到 e2e_photo_dir 的子目录，并在测试后清理避免污染共享夹具。
    """
    page = scored_page
    dest = e2e_photo_dir / "exported"
    page.get_by_label("导出目录").fill(str(dest))
    page.locator("#fg-export-btn").click()
    # 复制模式的成功文案为「复制 N 张到 …」（见 runner.export_to_dir）
    _wait_status(page, EXPORT_STATUS, "复制", timeout=30000)

    exported = sorted(p.name for p in dest.glob("*.jpg") if p.is_file())
    assert exported == ["blurry.jpg", "dark.jpg", "sharp.jpg"]
    # 清理：避免把副本留在共享的 e2e_photo_dir 中影响其它用例
    shutil.rmtree(dest, ignore_errors=True)


# ── E10 下载交互 ─────────────────────────────────────────────


def test_download_json_delivers_file(scored_page: Page, tmp_path: Path) -> None:
    """下载 JSON：状态提示已写入、下载组件出现，且浏览器能真正取回文件。"""
    page = scored_page
    page.locator("#fg-json-btn").click()
    _wait_status(page, EXPORT_STATUS, "已写入", timeout=30000)
    assert ".json" in _status_value(page, EXPORT_STATUS)

    # 修复回归：下载组件此前 visible=False 且处理器不更新可见性，永不出现
    expect(page.locator("#fg-download")).to_be_visible()
    expect(page.locator("#fg-download .filename")).to_contain_text(".json")

    with page.expect_download(timeout=30000) as download_info:
        page.locator("#fg-download a").first.click()
    download = download_info.value
    target = tmp_path / download.suggested_filename
    download.save_as(target)
    assert json.loads(target.read_text(encoding="utf-8"))

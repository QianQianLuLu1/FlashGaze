"""XlsxExporter 测试。

模块顶部 pytest.importorskip("openpyxl")：未安装 [xlsx] extra 时整模块跳过，
安装后自动运行。列顺序以 exporter.MANIFEST_COLUMNS 为单一来源，防漂移。
"""

from __future__ import annotations

import pytest

pytest.importorskip("openpyxl")

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from flashgaze.core.exporter import MANIFEST_COLUMNS
from flashgaze.core.xlsx_exporter import (
    HEADER_FILL,
    HEADER_FONT,
    XlsxExporter,
)
from flashgaze.models.schemas import ImageScore

pytest.importorskip("openpyxl")


def _score(file: str, path: str, score: float, **kw) -> ImageScore:
    return ImageScore(
        file=file,
        path=path,
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=0.0,
        score=score,
        **kw,
    )


def _sample() -> list[ImageScore]:
    return [
        _score("a.jpg", "/p/a.jpg", 92.0, selected=True, vlm_reason="清晰", vlm_provider="qwen"),
        _score("b.jpg", "/p/b.jpg", 55.0, selected=False),
        _score("c.jpg", "/p/c.jpg", 12.0, selected=False, error="corrupt"),
    ]


def test_xlsx_write(tmp_path) -> None:
    """写入成功：文件可被 load_workbook 重新打开，数据行数 = len(scored)+1（表头）。"""
    scored = _sample()
    path = tmp_path / "flashgaze_result.xlsx"
    XlsxExporter().write(scored, str(path))
    assert path.exists()
    wb = load_workbook(str(path))
    ws = wb.active
    assert ws.max_row == len(scored) + 1  # 表头 + 数据行
    # 数据行内容可直接读回（例如首张 score==92.0）
    assert ws.cell(row=2, column=7).value == 92.0


def test_xlsx_headers(tmp_path) -> None:
    """首行与 MANIFEST_COLUMNS 一致（即与 CSV 列顺序完全一致）。"""
    scored = _sample()
    path = tmp_path / "flashgaze_result.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active
    header = [c.value for c in ws[1]]
    assert header == list(MANIFEST_COLUMNS)
    # 表头样式：蓝底白字粗体
    top = ws.cell(row=1, column=1)
    assert top.fill.fgColor.rgb == HEADER_FILL.fgColor.rgb
    assert top.font.color.rgb == HEADER_FONT.color.rgb
    assert top.font.bold is True


def test_xlsx_conditional_formatting(tmp_path) -> None:
    """分数列 G 存在红→黄→绿 ColorScaleRule，且参数正确。"""
    scored = _sample()
    path = tmp_path / "flashgaze_result.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active

    rule = None
    cf_range = None
    for cf in ws.conditional_formatting:
        for r in cf.rules:
            if getattr(r, "type", None) == "colorScale":
                rule = r
                cf_range = str(cf.sqref)
                break
        if rule is not None:
            break
    assert rule is not None, "未找到 ColorScaleRule"
    # openpyxl 3.1.x：阈值与颜色在 rule.colorScale 子对象里（cfvo=阈值，color=颜色）
    cfvo = rule.colorScale.cfvo
    colors = rule.colorScale.color
    assert cfvo[0].val == 0
    assert colors[0].rgb.endswith("FF0000")
    assert cfvo[1].val == 60
    assert colors[1].rgb.endswith("FFFF00")
    assert cfvo[2].val == 100
    assert colors[2].rgb.endswith("00FF00")
    # 作用区间含分数列 G（CSV 第 7 列 -> Excel G）
    assert "G" in cf_range


def test_xlsx_auto_filter(tmp_path) -> None:
    """auto_filter.ref 不为空，且格式为 A1:Q{n}。"""
    scored = _sample()
    path = tmp_path / "flashgaze_result.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active
    ref = ws.auto_filter.ref
    assert ref  # 非空
    assert ref == f"A1:Q{len(scored) + 1}"


def test_xlsx_empty_list_ok(tmp_path) -> None:
    """空 scored 仍生成仅含表头的文件，不抛异常。"""
    path = tmp_path / "empty.xlsx"
    XlsxExporter().write([], str(path))
    assert path.exists()
    wb = load_workbook(str(path))
    ws = wb.active
    assert ws.max_row == 1  # 仅表头
    assert ws.auto_filter.ref == "A1:Q1"


def test_xlsx_selected_written_as_bool(tmp_path) -> None:
    """第 8 列（selected）为 Excel 原生布尔，而非字符串 'True'/'False'。"""
    scored = _sample()
    path = tmp_path / "bool.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active
    # column 8 == selected
    assert isinstance(ws.cell(row=2, column=8).value, bool)
    assert ws.cell(row=2, column=8).value is True
    assert ws.cell(row=3, column=8).value is False

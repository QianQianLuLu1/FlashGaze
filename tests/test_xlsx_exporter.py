"""XlsxExporter 测试。

模块顶部 pytest.importorskip("openpyxl")：未安装 [xlsx] extra 时整模块跳过，
安装后自动运行。列顺序以 exporter.MANIFEST_COLUMNS 为单一来源，防漂移。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("openpyxl")

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from flashgaze.core.xlsx_exporter import (
    HEADER_FILL,
    HEADER_FONT,
    XlsxExporter,
)
from flashgaze.models.schemas import MANIFEST_COLUMNS, ImageScore

pytest.importorskip("openpyxl")


def _score(file: str, path: str, score: float, **kw: Any) -> ImageScore:
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


def test_xlsx_write(tmp_path: Path) -> None:
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


def test_xlsx_headers(tmp_path: Path) -> None:
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


def test_xlsx_conditional_formatting(tmp_path: Path) -> None:
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
    assert cf_range is not None
    assert "G" in cf_range


def test_xlsx_auto_filter(tmp_path: Path) -> None:
    """auto_filter.ref 不为空，且格式为 A1:{末列}{n}（末列由 MANIFEST_COLUMNS 派生）。"""
    scored = _sample()
    path = tmp_path / "flashgaze_result.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active
    ref = ws.auto_filter.ref
    assert ref  # 非空
    last_col = get_column_letter(len(MANIFEST_COLUMNS))
    assert ref == f"A1:{last_col}{len(scored) + 1}"


def test_xlsx_empty_list_ok(tmp_path: Path) -> None:
    """空 scored 仍生成仅含表头的文件，不抛异常。"""
    path = tmp_path / "empty.xlsx"
    XlsxExporter().write([], str(path))
    assert path.exists()
    wb = load_workbook(str(path))
    ws = wb.active
    assert ws.max_row == 1  # 仅表头
    last_col = get_column_letter(len(MANIFEST_COLUMNS))
    assert ws.auto_filter.ref == f"A1:{last_col}1"


def test_xlsx_selected_written_as_bool(tmp_path: Path) -> None:
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


def test_xlsx_row_matches_to_row(tmp_path: Path) -> None:
    """C-09：XLSX 每数据行逐项等价于 ImageScore.to_row()（单一来源，无漂移）。

    selected/deduped 保留原生布尔、None 维度写空串、数值原样，三者一致。
    """
    from flashgaze.models.schemas import ImageScore

    scored = [
        ImageScore(
            file="a.jpg",
            path="/a.jpg",
            sharpness=80.0,
            exposure=70.0,
            composition=None,
            vlm_adjustment=0.0,
            score=92.0,
            selected=True,
            vlm_reason="清晰",
            vlm_provider="qwen",
            noise=60.0,
            color=50.0,
            face_count=1,
            face_sharpness=85.0,
            portrait_bonus=2.0,
        ),
        ImageScore(
            file="b.jpg",
            path="/b.jpg",
            sharpness=55.0,
            exposure=40.0,
            composition=None,
            vlm_adjustment=0.0,
            score=12.0,
            selected=False,
            error="corrupt",
        ),
    ]
    path = tmp_path / "contract.xlsx"
    XlsxExporter().write(scored, str(path))
    wb = load_workbook(str(path))
    ws = wb.active

    def _norm(v: Any) -> Any:
        # openpyxl 把写入的空串 "" 在读回时归一化为 None；与 CSV 的 "" 展示等价
        return None if v == "" or v is None else v

    for i, s in enumerate(scored, start=2):
        xlsx_row = [c.value for c in ws[i]]
        assert [_norm(c) for c in xlsx_row] == [_norm(v) for v in s.to_row()], (
            f"行 {i} 与 to_row() 不一致"
        )

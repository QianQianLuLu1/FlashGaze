"""C-09 清单行映射契约测试。

验证：ImageScore.to_row() 是 CSV/XLSX 的唯一取值来源，三者字段顺序与 None 处理一致。
XLSX 与 to_row() 的逐项对比见 test_xlsx_exporter.py（需 openpyxl）。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from flashgaze.core.exporter import Exporter
from flashgaze.models.schemas import MANIFEST_COLUMNS, Config, ImageScore


def _score(**kw: Any) -> ImageScore:
    base: dict[str, Any] = {
        "file": "a.jpg",
        "path": "/a/a.jpg",
        "sharpness": 80.0,
        "exposure": 70.0,
        "composition": None,
        "vlm_adjustment": 0.0,
        "score": 92.0,
    }
    base.update(kw)
    return ImageScore(**base)


def _sample() -> list[ImageScore]:
    return [
        _score(
            selected=True,
            vlm_reason="清晰",
            vlm_provider="qwen",
            noise=60.0,
            color=50.0,
            face_count=1,
            face_sharpness=85.0,
            portrait_bonus=2.0,
        ),
        _score(selected=False, error="corrupt"),
    ]


def _csv_repr(v: Any) -> str:
    """把 to_row() 的 Python 值序列化成 CSV 单元格字符串，用于逐项对比。"""
    if isinstance(v, bool):
        return "True" if v else "False"
    if v == "":
        return ""
    return str(v)


def test_to_row_matches_manifest_columns() -> None:
    """to_row() 长度与顺序严格对应 MANIFEST_COLUMNS。"""
    s = _sample()[0]
    row = s.to_row()
    assert len(row) == len(MANIFEST_COLUMNS)
    assert row[0] == "a.jpg"
    # None 维度统一转空串
    assert row[MANIFEST_COLUMNS.index("composition")] == ""
    assert row[MANIFEST_COLUMNS.index("error")] == ""


def test_csv_uses_to_row_consistently(tmp_path: Path) -> None:
    """CSV 数据行逐格等价于 to_row()（序列化后），表头与 MANIFEST_COLUMNS 一致。"""
    scored = _sample()
    csv_path = tmp_path / "r.csv"
    Exporter(Config(directory="."))._write_csv(scored, str(csv_path))

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    assert rows[0] == list(MANIFEST_COLUMNS)
    for i, s in enumerate(scored, start=1):
        expected = s.to_row()
        assert rows[i] == [_csv_repr(v) for v in expected]


def test_csv_none_dimensions_written_as_empty(tmp_path: Path) -> None:
    """None 维度在 CSV 中写空串（而非 'None'），与方案 C-09 语义一致。"""
    scored = [_score(composition=None, noise=None, color=None, face_sharpness=None)]
    csv_path = tmp_path / "r.csv"
    Exporter(Config(directory="."))._write_csv(scored, str(csv_path))
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    data = rows[1]
    for col in ("composition", "noise", "color", "face_sharpness"):
        idx = MANIFEST_COLUMNS.index(col)
        assert data[idx] == "", f"列 {col} 应为空串，实际 {data[idx]!r}"


# ── LOW-5: CSV/Excel 公式注入防护 ────────────────────────


def test_to_row_neutralizes_formula_prefixes() -> None:
    """字符串单元格以 = + - @ TAB CR 开头时加 ' 前缀，阻断 Excel 公式求值。

    攻击载体：恶意文件名或 VLM 返回的 reason；数值/布尔列不受影响，
    非 prefix 开头的普通字符串（含中文）原样保留。"""
    s = ImageScore(
        file='=HYPERLINK("http://evil","x").jpg',
        path=str(Path("D:/pics") / "=cmd.jpg"),
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=-1.5,
        score=78.5,
        selected=False,
        vlm_reason="+1 暗调氛围",  # VLM 输出以 "+" 开头的真实场景
        vlm_provider="qwen",
    )
    row = s.to_row()

    assert str(row[MANIFEST_COLUMNS.index("file")]).startswith("'=")
    assert not str(row[MANIFEST_COLUMNS.index("path")]).startswith("'")  # 普通路径不动
    assert row[MANIFEST_COLUMNS.index("vlm_reason")] == "'+1 暗调氛围"
    assert row[MANIFEST_COLUMNS.index("vlm_provider")] == "qwen"
    # 数值列不受影响
    assert row[MANIFEST_COLUMNS.index("score")] == 78.5
    assert row[MANIFEST_COLUMNS.index("vlm_adjustment")] == -1.5
    # 布尔列保留原生类型（XLSX 依赖）
    assert row[MANIFEST_COLUMNS.index("selected")] is False


def test_to_row_ordinary_strings_untouched() -> None:
    """非公式前缀的普通文件名/理由不加前缀，输出与旧格式逐字节一致。"""
    s = ImageScore(
        file="IMG_0001.jpg",
        path="/data/IMG_0001.jpg",
        sharpness=80.0,
        exposure=70.0,
        composition=None,
        vlm_adjustment=0.0,
        score=75.0,
        selected=True,
        vlm_reason="背景虚化为艺术手法",
    )
    row = s.to_row()
    assert row[MANIFEST_COLUMNS.index("file")] == "IMG_0001.jpg"
    assert row[MANIFEST_COLUMNS.index("path")] == "/data/IMG_0001.jpg"
    assert row[MANIFEST_COLUMNS.index("vlm_reason")] == "背景虚化为艺术手法"

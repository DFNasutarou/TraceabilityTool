import pytest

from tracetool import readers
from tracetool.errors import AppError

from .conftest import make_csv, make_xlsx


def test_decode_cp932_auto():
    data = "ID,名前\r\nA,あいう\r\n".encode("cp932")
    text, enc = readers.decode_text(data, None)
    assert enc == "cp932"
    assert "あいう" in text


def test_decode_utf8_bom():
    text, enc = readers.decode_text("﻿ID\r\n".encode("utf-8"), None)
    assert enc == "utf-8-sig"
    assert text.startswith("ID")


def test_csv_with_newline_in_cell_and_header_row():
    data = make_csv([["タイトル"], [], ["ID", "内容"], ["A", "1行目\n2行目"], ["", ""], ["B", "x"]])
    text, _ = readers.decode_text(data, None)
    table = readers.build_table(readers.read_delimited(text, ","), header_row=3)
    assert table.headers == ["ID", "内容"]
    assert [r[2] for r in table.rows] == [["A", "1行目\n2行目"], ["B", "x"]]
    assert [r[1] for r in table.rows] == [4, 6]


def test_xlsx_merged_cells_expand():
    data = make_xlsx({"S": [["ID", "分類", "名前"], ["1", "画面", "a"], ["2", None, "b"], [3, None, "c"]]}, {"S": ["B2:B4"]})
    wb = readers.open_workbook(data)
    table = readers.build_table(readers.read_sheet(wb, "S"), 1, "S")
    assert [r[2] for r in table.rows] == [["1", "画面", "a"], ["2", "画面", "b"], ["3", "画面", "c"]]


def test_merge_tables_header_mismatch():
    t1 = readers.Table(headers=["ID", "A"])
    t2 = readers.Table(headers=["ID", "B"])
    with pytest.raises(AppError):
        readers.merge_tables([("s1", t1), ("s2", t2)])


def test_duplicate_and_empty_headers_renamed():
    table = readers.build_table([["ID", "", "ID"]], 1)
    assert table.headers == ["ID", "列2", "ID(2)"]


def test_xls_rejected():
    with pytest.raises(AppError):
        readers.detect_format("old.xls")

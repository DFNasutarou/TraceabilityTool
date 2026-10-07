"""取り込みの追加機能: データの範囲、シートのプレビュー、ID の自動採番、セル内の改行と enum。"""

from tracetool import readers

from .conftest import make_csv, make_xlsx
from .test_flow import ok


def start_import(client, doc_id, filename, data):
    return ok(client.post("/api/imports", data={"document_id": doc_id}, files={"file": (filename, data)}))


def new_doc(client, name="文書"):
    return ok(client.post("/api/documents", json={"name": name}))["id"]


# --- データの範囲 ------------------------------------------------------------------


def test_build_table_data_range():
    grid = [
        ["ID", "名前"],
        ["（説明の行）", ""],
        ["A-1", "x"],
        ["A-2", "y"],
        ["", ""],
        ["※注記", ""],
    ]
    assert [r[2][0] for r in readers.build_table(grid, 1).rows] == ["（説明の行）", "A-1", "A-2", "※注記"]
    t = readers.build_table(grid, 1, data_start=3, data_end=4)
    assert [(r[1], r[2][0]) for r in t.rows] == [(3, "A-1"), (4, "A-2")]
    t = readers.build_table(grid, 1, data_start=3, stop_at_blank=True)
    assert [r[2][0] for r in t.rows] == ["A-1", "A-2"]


def test_build_table_data_range_errors():
    import pytest

    from tracetool.errors import AppError

    grid = [["ID"], ["1"], ["2"]]
    with pytest.raises(AppError, match="ヘッダ行"):
        readers.build_table(grid, 2, data_start=2)
    with pytest.raises(AppError, match="終了行"):
        readers.build_table(grid, 1, data_start=3, data_end=2)


def test_settings_with_data_range(client):
    doc = new_doc(client)
    data = make_csv([["表題"], ["ID", "名前"], ["説明", ""], ["A-1", "x"], ["A-2", "y"], [], ["以上", ""]])
    s = start_import(client, doc, "a.csv", data)
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings",
                      json={"header_row": 2, "data_start": 4, "stop_at_blank": True}))
    assert r["row_count"] == 2
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 2, "data_start": 4, "data_end": 4}))
    assert r["row_count"] == 1
    v = ok(client.put(f"/api/imports/{s['session_id']}/validate", json={"schema": r["schema"]}))
    assert v["error_count"] == 0 and v["item_count"] == 1
    vid = ok(client.post(f"/api/imports/{s['session_id']}/commit", json={"schema": r["schema"]}))["version_id"]
    settings = ok(client.get(f"/api/documents/{doc}/versions"))[0]["import_settings"]
    assert settings["data_start"] == 4 and settings["data_end"] == 4 and vid


# --- シートのプレビュー --------------------------------------------------------------


def test_preview_switches_sheet_even_if_headers_differ(client):
    doc = new_doc(client)
    data = make_xlsx({"s1": [["ID", "名前"], ["A", "x"]], "s2": [["タイトル"], ["番号", "内容"], ["1", "y"]]})
    s = start_import(client, doc, "a.xlsx", data)
    assert s["sheet_preview"]["sheet"] == "s1"
    p = ok(client.get(f"/api/imports/{s['session_id']}/preview", params={"sheet": "s2"}))
    assert p["sheet"] == "s2"
    assert p["rows"][1] == {"no": 2, "cells": ["番号", "内容"]}
    assert p["suggested_header_row"] == 2 and p["total"] == 3
    # 2 枚のヘッダが違っていても、プレビューは見られる（取り込みの設定はエラー）
    r = client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1, "sheets": ["s1", "s2"]})
    assert r.status_code == 400


def test_preview_shows_head_and_tail(client):
    doc = new_doc(client)
    rows = [["ID"]] + [[f"A-{i}"] for i in range(100)]
    s = start_import(client, doc, "a.csv", make_csv(rows))
    p = s["sheet_preview"]
    nos = [r["no"] for r in p["rows"]]
    assert p["total"] == 101 and nos[:3] == [1, 2, 3] and nos[-1] == 101 and len(nos) == 50


# --- ID の自動採番 -------------------------------------------------------------------


def test_auto_id(client):
    doc = new_doc(client)
    s = start_import(client, doc, "a.csv", make_csv([["名前", "備考"], ["ログイン", ""], ["検索", "x"]]))
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1}))
    schema = r["schema"]
    # ファイルに ID 列が無いので、ID 列を足して自動採番にする
    schema["columns"][0]["type"] = "string"
    schema["columns"].insert(0, {"key": "cid", "name": "ID", "type": "id", "source_header": "名前",
                                 "auto_id": {"prefix": "REQ-", "digits": 3, "start": 1}})
    v = ok(client.put(f"/api/imports/{s['session_id']}/validate", json={"schema": schema}))
    assert v["error_count"] == 0
    assert [i["item_id"] for i in v["preview"]] == ["REQ-001", "REQ-002"]
    ok(client.post(f"/api/imports/{s['session_id']}/commit", json={"schema": v["schema"]}))
    saved = ok(client.get(f"/api/documents/{doc}"))["schema"]
    assert saved["columns"][0]["auto_id"] == {"prefix": "REQ-", "digits": 3, "start": 1}
    assert saved["columns"][0]["source_header"] == "名前"  # 保存はするが、採番中は使わない
    items = ok(client.get(f"/api/documents/{doc}/latest-items"))["items"]
    assert [i["data"]["cid"] for i in items] == ["REQ-001", "REQ-002"]


def test_auto_id_settings_are_clamped():
    from tracetool import colschema

    s = colschema.normalize_schema({"columns": [
        {"key": "a", "name": "ID", "type": "id", "auto_id": {"prefix": " X ", "digits": 99, "start": -5}},
        {"key": "b", "name": "名前", "type": "string", "auto_id": {"prefix": "Y"}},
    ]})
    assert s["columns"][0]["auto_id"] == {"prefix": "X", "digits": 10, "start": 0}
    assert s["columns"][1]["auto_id"] is None  # ID 列以外では無視する
    assert colschema.format_auto_id({"prefix": "T-", "digits": 2, "start": 9}, 2) == "T-11"


# --- セル内の改行と enum ------------------------------------------------------------


def test_crlf_in_cell_is_normalized_and_enum_keeps_newline(client):
    doc = new_doc(client)
    data = 'ID,区分\r\nA,"高\r\n(暫定)"\r\nB,低\r\n'.encode("utf-8")
    s = start_import(client, doc, "a.csv", data)
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1}))
    col = r["schema"]["columns"][1]
    values = ok(client.put(f"/api/imports/{s['session_id']}/distinct", json={"column": col}))["values"]
    assert values == ["高\n(暫定)", "低"]
    col.update(type="enum", enum_values=values)
    v = ok(client.put(f"/api/imports/{s['session_id']}/validate", json={"schema": r["schema"]}))
    assert v["warning_count"] == 0 and v["error_count"] == 0
    assert v["schema"]["columns"][1]["enum_values"] == ["高\n(暫定)", "低"]


def test_new_columns_default_to_low_importance_and_auto_width(client):
    doc = new_doc(client)
    s = start_import(client, doc, "a.csv", make_csv([["ID", "名前"], ["A", "x"]]))
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1}))
    assert {c["importance"] for c in r["schema"]["columns"]} == {"low"}
    assert {c["width"] for c in r["schema"]["columns"]} == {"auto"}


def test_label_break_is_display_setting(client):
    doc = new_doc(client)
    s = start_import(client, doc, "a.csv", make_csv([["ID", "名前"], ["A", "x"]]))
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1}))
    assert {c["label_break"] for c in r["schema"]["columns"]} == {False}
    ok(client.post(f"/api/imports/{s['session_id']}/commit", json={"schema": r["schema"]}))
    # 文書の設定で変えると、取り込み直さなくても表示用のカラム定義に反映される
    d = ok(client.get(f"/api/documents/{doc}"))
    d["schema"]["columns"][1]["label_break"] = True
    ok(client.put(f"/api/documents/{doc}", json={"name": d["name"], "schema": d["schema"]}))
    cols = ok(client.get(f"/api/documents/{doc}/latest-items"))["schema"]["columns"]
    assert [c["label_break"] for c in cols] == [False, True]


def test_display_follows_working_column_order(client):
    """設定画面で列を並べ替えると、取り込み直さなくても横並び表示・項目一覧の列の順に反映される。"""
    doc = new_doc(client)
    s = start_import(client, doc, "a.csv", make_csv([["ID", "名前", "区分", "備考"], ["A", "x", "y", "z"]]))
    r = ok(client.put(f"/api/imports/{s['session_id']}/settings", json={"header_row": 1}))
    vid = ok(client.post(f"/api/imports/{s['session_id']}/commit", json={"schema": r["schema"]}))["version_id"]
    d = ok(client.get(f"/api/documents/{doc}"))
    cols = d["schema"]["columns"]
    # 備考を 2 番目に移し（名前も変える）、区分を設定画面で消す
    cols[3]["name"] = "メモ"
    d["schema"]["columns"] = [cols[0], cols[3], cols[1]]
    ok(client.put(f"/api/documents/{doc}", json={"name": d["name"], "schema": d["schema"]}))
    expected = ["ID", "メモ", "名前", "区分"]  # 消した列は後ろに残す（版にはある）
    assert [c["name"] for c in ok(client.get(f"/api/documents/{doc}/latest-items"))["schema"]["columns"]] == expected
    assert [c["name"] for c in ok(client.get(f"/api/versions/{vid}/items"))["schema"]["columns"]] == expected

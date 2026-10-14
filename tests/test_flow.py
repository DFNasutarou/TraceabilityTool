"""取り込み → リンク → 版の更新 → 要確認 → 差分 → 出力 の一連の流れ。"""

from .conftest import make_csv, make_xlsx

REQ_SCHEMA = {
    "columns": [
        {"key": "rid", "name": "要件ID", "type": "id"},
        {"key": "rname", "name": "要件名", "type": "string"},
        {"key": "rpri", "name": "優先度", "type": "enum", "enum_values": ["高", "中", "低"]},
        {"key": "rmust", "name": "必須", "type": "bool"},
        {"key": "rnote", "name": "備考", "type": "string"},
    ]
}


def scr_schema(req_id=None):
    """画面定義書。上位要件の列は普通の文字列の列（つながりは関連表で表す）。"""
    return {
        "columns": [
            {"key": "sid", "name": "画面ID", "type": "id"},
            {"key": "sname", "name": "画面名", "type": "string"},
            {"key": "sref", "name": "上位要件", "type": "string", "list": {"delimiters": [";"]}},
        ]
    }


def link_schema(req_id, scr_id):
    """要件-画面対応表（関連表）。画面定義書と同じファイルを取り込み、上位要件 → 画面ID のつながりを作る。"""
    return {
        "columns": [
            {"key": "lid", "name": "対応ID", "type": "id", "auto_id": {"prefix": "L-", "digits": 3, "start": 1}},
            {"key": "lup", "name": "上位要件", "type": "string", "list": {"delimiters": [";"]},
             "ref_document_id": req_id, "link_role": "upper"},
            {"key": "llo", "name": "画面", "source_header": "画面ID", "type": "string",
             "ref_document_id": scr_id, "link_role": "lower"},
        ]
    }


def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def do_import(client, doc_id, filename, data, schema=None, header_row=1, sheets=None, label=""):
    """取り込む。setup() で画面定義書に関連表を対応させている場合は、同じファイルを関連表にも取り込む
    （画面定義書の上位要件の列からつながりを作るため）。"""
    result = _import(client, doc_id, filename, data, schema, header_row, sheets, label)
    link = getattr(client, "link_tables", {}).get(doc_id)
    if link is not None and "version_id" in result:
        _import(client, link, filename, data, None, header_row, sheets, "")
    return result


def _import(client, doc_id, filename, data, schema=None, header_row=1, sheets=None, label=""):
    start = ok(client.post("/api/imports", data={"document_id": doc_id}, files={"file": (filename, data)}))
    sid = start["session_id"]
    settings = ok(
        client.put(f"/api/imports/{sid}/settings", json={"header_row": header_row, "sheets": sheets or start["sheets"][:1]})
    )
    if schema is None:
        schema = settings["schema"]
    else:
        # テストで直接渡すカラム定義は、ファイルのヘッダ名 = 列名として対応付ける
        schema = {**schema, "columns": [{"source_header": c["name"], **c} for c in schema["columns"]]}
    v = ok(client.put(f"/api/imports/{sid}/validate", json={"schema": schema}))
    if v["error_count"]:
        return v
    return ok(client.post(f"/api/imports/{sid}/commit", json={"schema": v["schema"], "label": label}))


def req_csv(note1="なし"):
    return make_csv(
        [
            ["要件ID", "要件名", "優先度", "必須", "備考"],
            ["REQ-001", "ログイン", "高", "○", note1],
            ["REQ-002", "検索", "中", "×", ""],
            ["REQ-003", "出力", "最高", "Yes", ""],
        ],
        encoding="cp932",
    )


def setup(client):
    req = ok(client.post("/api/documents", json={"name": "要件定義書", "schema": REQ_SCHEMA}))["id"]
    scr = ok(client.post("/api/documents", json={"name": "画面定義書"}))["id"]
    ok(client.put(f"/api/documents/{scr}", json={"name": "画面定義書", "schema": scr_schema(req)}))
    rel = ok(client.post("/api/relations", json={"upper_doc_id": req, "lower_doc_id": scr}))["id"]
    link = ok(client.post("/api/documents", json={"name": "要件-画面対応表", "schema": link_schema(req, scr)}))["id"]
    client.link_tables = {scr: link}
    return req, scr, rel


def link_doc(client, scr):
    return client.link_tables[scr]


def scr_xlsx():
    return make_xlsx(
        {
            "画面": [
                ["画面定義書"],
                ["画面ID", "画面名", "上位要件"],
                ["SCR-01", "ログイン画面", "REQ-001;REQ-002"],
                ["SCR-02", "検索画面", "REQ-002"],
                ["SCR-03", "設定画面", ""],
                ["SCR-04", "謎画面", "REQ-999"],
            ]
        }
    )


def test_full_flow(client):
    req, scr, rel = setup(client)

    # 要件定義書: CP932 の CSV。enum 外の値は警告で取り込める
    start = ok(client.post("/api/imports", data={"document_id": req}, files={"file": ("req.csv", req_csv())}))
    assert start["encoding"] == "cp932"
    sid = start["session_id"]
    settings = ok(client.put(f"/api/imports/{sid}/settings", json={"header_row": 1}))
    assert settings["unmapped_headers"] == []
    v = ok(client.put(f"/api/imports/{sid}/validate", json={"schema": settings["schema"]}))
    assert v["error_count"] == 0
    assert v["warning_count"] == 1 and "選択肢" in v["warnings"][0]["message"]
    req_v1 = ok(client.post(f"/api/imports/{sid}/commit", json={"schema": v["schema"], "label": "初版"}))["version_id"]

    items = ok(client.get(f"/api/versions/{req_v1}/items"))
    assert items["total"] == 3
    first = items["items"][0]
    assert first["data"]["rmust"] is True and first["data"]["rpri"] == "高"
    assert items["items"][2]["invalid"] == ["rpri"]

    # 画面定義書: XLSX、ヘッダは 2 行目。参照 ID 列から自動リンク
    scr_v1 = do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)["version_id"]
    ev = ok(client.get(f"/api/trace/{rel}"))
    assert ev["upper"]["untraced"] == ["REQ-003"]
    assert ev["lower"]["untraced"] == ["SCR-03", "SCR-04"]
    assert [(l["upper_item_id"], l["lower_item_id"]) for l in ev["broken"]] == [("REQ-999", "SCR-04")]
    assert len(ev["links"]) == 4 and ev["suspect"] == []

    # 項目一覧の絞り込み
    no_upper = ok(client.get(f"/api/versions/{scr_v1}/items", params={"trace": "no_upper"}))
    assert [i["item_id"] for i in no_upper["items"]] == ["SCR-03", "SCR-04"]
    no_lower = ok(client.get(f"/api/versions/{req_v1}/items", params={"trace": "no_lower"}))
    assert [i["item_id"] for i in no_lower["items"]] == ["REQ-003"]

    # 手動リンクの追加
    ok(client.post("/api/links", json={"relation_id": rel, "upper_item_id": "REQ-003", "lower_item_id": "SCR-03"}))
    ev = ok(client.get(f"/api/trace/{rel}"))
    assert ev["upper"]["untraced"] == []

    # 自動リンクを削除（無効化）→ 画面定義書を再取り込みしても無効のまま
    detail = ok(client.get(f"/api/versions/{scr_v1}/item", params={"id": "SCR-02"}))
    link_id = detail["relations"][0]["links"][0]["id"]
    ok(client.delete(f"/api/links/{link_id}"))
    scr_v2 = do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)["version_id"]
    detail = ok(client.get(f"/api/versions/{scr_v2}/item", params={"id": "SCR-02"}))
    assert detail["relations"][0]["links"][0]["active"] is False
    ev = ok(client.get(f"/api/trace/{rel}"))
    assert "SCR-02" in ev["lower"]["untraced"]
    # 手動リンクは再取り込みで失われない
    assert any(l["upper_item_id"] == "REQ-003" and l["origin"] == "manual" for l in ev["links"])
    # 元に戻す
    ok(client.post(f"/api/links/{link_id}/restore"))

    # 要件定義書の新版: 備考の変更だけでも要確認になる
    req_v2 = do_import(client, req, "req.csv", req_csv(note1="変更"), label="第2版")["version_id"]
    ev = ok(client.get(f"/api/trace/{rel}"))
    suspect = [(l["upper_item_id"], l["lower_item_id"]) for l in ev["suspect"]]
    assert suspect == [("REQ-001", "SCR-01")]
    ok(client.post("/api/links/ack", json={"ids": [l["id"] for l in ev["suspect"]]}))
    assert ok(client.get(f"/api/trace/{rel}"))["suspect"] == []

    # 差分
    d = ok(client.get("/api/diff", params={"from": req_v1, "to": req_v2}))
    assert d["added"] == [] and d["removed"] == [] and d["unchanged"] == 2
    assert d["changed"] == [{"item_id": "REQ-001", "cells": [{"key": "rnote", "name": "備考", "old": "なし", "new": "変更"}]}]

    # 出力
    for url in (
        f"/api/export/matrix?relation={rel}&format=xlsx",
        f"/api/export/matrix?relation={rel}&format=csv",
        "/api/export/untraced?format=xlsx",
        f"/api/export/untraced?relation={rel}&format=csv",
        f"/api/export/diff?from={req_v1}&to={req_v2}&format=xlsx",
    ):
        r = client.get(url)
        assert r.status_code == 200, (url, r.text)
        assert len(r.content) > 0

    # 一覧
    docs = ok(client.get("/api/documents"))
    assert [d["latest"]["version_no"] for d in docs] == [2, 2, 2]  # 要件定義書・画面定義書・要件-画面対応表
    rels = ok(client.get("/api/relations"))
    assert rels[0]["upper_untraced"] == 0


def test_import_errors_block_commit(client):
    doc = ok(client.post("/api/documents", json={"name": "A", "schema": REQ_SCHEMA}))["id"]
    data = make_csv([["要件ID", "要件名"], ["R1", "a"], ["R1", "b"], ["", "c"]])
    v = do_import(client, doc, "a.csv", data)
    assert v["error_count"] == 2
    messages = [e["message"] for e in v["errors"]]
    assert any("重複" in m for m in messages) and any("空" in m for m in messages)


def test_link_table_requires_relation(client):
    req = ok(client.post("/api/documents", json={"name": "要件", "schema": REQ_SCHEMA}))["id"]
    scr = ok(client.post("/api/documents", json={"name": "画面", "schema": scr_schema()}))["id"]
    link = ok(client.post("/api/documents", json={"name": "対応表", "schema": link_schema(req, scr)}))["id"]
    data = make_csv([["画面ID", "画面名", "上位要件"], ["S1", "a", "R1"]])
    v = do_import(client, link, "s.csv", data)
    assert v["error_count"] == 1 and "トレース関係" in v["errors"][0]["message"]


def test_ref_column_only_in_link_table(client):
    """仕様書 B に A のキーを書く方式（関連表のキーでない参照 ID 列）は使えない。"""
    req = ok(client.post("/api/documents", json={"name": "要件", "schema": REQ_SCHEMA}))["id"]
    schema = scr_schema()
    schema["columns"][2]["ref_document_id"] = req
    r = client.post("/api/documents", json={"name": "画面", "schema": schema})
    assert r.status_code == 400 and "関連表のキー" in r.json()["error"]["message"]
    # 関連表には上位側・下位側のキーが 1 つずつ必要
    scr = ok(client.post("/api/documents", json={"name": "画面", "schema": scr_schema()}))["id"]
    bad = link_schema(req, scr)
    bad["columns"][2]["link_role"] = "upper"
    r = client.post("/api/documents", json={"name": "対応表", "schema": bad})
    assert r.status_code == 400 and "1 つずつ" in r.json()["error"]["message"]


def test_link_table_cannot_be_in_relation(client):
    req, scr, rel = setup(client)
    r = client.post("/api/relations", json={"upper_doc_id": link_doc(client, scr), "lower_doc_id": req})
    assert r.status_code == 400 and "関連表" in r.json()["error"]["message"]


def test_relation_cycle_rejected(client):
    a = ok(client.post("/api/documents", json={"name": "A"}))["id"]
    b = ok(client.post("/api/documents", json={"name": "B"}))["id"]
    c = ok(client.post("/api/documents", json={"name": "C"}))["id"]
    ok(client.post("/api/relations", json={"upper_doc_id": a, "lower_doc_id": b}))
    ok(client.post("/api/relations", json={"upper_doc_id": b, "lower_doc_id": c}))
    r = client.post("/api/relations", json={"upper_doc_id": c, "lower_doc_id": a})
    assert r.status_code == 400 and "循環" in r.json()["error"]["message"]


def test_first_import_proposes_schema_and_multisheet(client):
    doc = ok(client.post("/api/documents", json={"name": "設計書"}))["id"]
    data = make_xlsx({"s1": [["ID", "名前"], ["D1", "a"]], "s2": [["ID", "名前"], ["D2", "b"]]})
    start = ok(client.post("/api/imports", data={"document_id": doc}, files={"file": ("d.xlsx", data)}))
    assert start["sheets"] == ["s1", "s2"]
    settings = ok(client.put(f"/api/imports/{start['session_id']}/settings", json={"header_row": 1, "sheets": ["s1", "s2"]}))
    assert [c["type"] for c in settings["schema"]["columns"]] == ["id", "string"]
    assert settings["row_count"] == 2
    v = ok(client.put(f"/api/imports/{start['session_id']}/validate", json={"schema": settings["schema"]}))
    assert v["error_count"] == 0 and v["item_count"] == 2


def test_delete_latest_version_regenerates_links(client):
    req, scr, rel = setup(client)
    link = link_doc(client, scr)
    do_import(client, req, "req.csv", req_csv())
    do_import(client, scr, "scr.xlsx", scr_xlsx(), header_row=2)
    data = make_csv([["画面ID", "画面名", "上位要件"], ["SCR-01", "ログイン画面", "REQ-001"]])
    v2 = do_import(client, link, "scr2.csv", data)["version_id"]  # 関連表だけを取り込み直す
    assert len(ok(client.get(f"/api/trace/{rel}"))["links"]) == 1
    ok(client.delete(f"/api/versions/{v2}"))
    assert len(ok(client.get(f"/api/trace/{rel}"))["links"]) == 4
    versions = ok(client.get(f"/api/documents/{link}/versions"))
    assert [v["version_no"] for v in versions] == [1]
    # 削除した版の番号は再利用しない
    do_import(client, link, "scr2.csv", data)
    assert ok(client.get(f"/api/documents/{link}/versions"))[0]["version_no"] == 3

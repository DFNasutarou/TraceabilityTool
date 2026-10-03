"""docs/ の要件定義書・詳細設計書（CSV）が、このツールで取り込めてトレースが取れていることを確認する。"""

from pathlib import Path

from .test_flow import ok

DOCS = Path(__file__).resolve().parent.parent / "docs"

REQ_CLASSES = ["目的", "前提", "用語", "機能", "非機能", "対象外"]
DESIGN_CLASSES = ["技術構成", "起動", "配布", "構成", "データモデル", "処理", "API", "画面", "エラー処理", "セキュリティ", "テスト"]


def req_schema():
    return {
        "columns": [
            {"key": "rid", "name": "要件ID", "source_header": "要件ID", "type": "id"},
            {"key": "rcls", "name": "分類", "source_header": "分類", "type": "enum", "enum_values": REQ_CLASSES},
            {"key": "rgrp", "name": "大項目", "source_header": "大項目", "type": "string"},
            {"key": "rtxt", "name": "要件", "source_header": "要件", "type": "string"},
            {"key": "rnote", "name": "補足", "source_header": "補足", "type": "string"},
        ],
        "display_column": "rtxt",
    }


def design_schema(req_doc_id):
    return {
        "columns": [
            {"key": "did", "name": "設計ID", "source_header": "設計ID", "type": "id"},
            {"key": "dcls", "name": "分類", "source_header": "分類", "type": "enum", "enum_values": DESIGN_CLASSES},
            {"key": "dtgt", "name": "対象", "source_header": "対象", "type": "string"},
            {"key": "dtxt", "name": "設計内容", "source_header": "設計内容", "type": "string"},
            {"key": "dimpl", "name": "実装箇所", "source_header": "実装箇所", "type": "string", "list": {"delimiters": [";"]}},
            {"key": "dref", "name": "上位要件", "source_header": "上位要件", "type": "string",
             "list": {"delimiters": [";"]}, "ref_document_id": req_doc_id},
        ],
        "display_column": "dtgt",
    }


def _import(client, doc_id, path: Path, schema):
    start = ok(client.post("/api/imports", data={"document_id": doc_id}, files={"file": (path.name, path.read_bytes())}))
    sid = start["session_id"]
    ok(client.put(f"/api/imports/{sid}/settings", json={"header_row": 1}))
    v = ok(client.put(f"/api/imports/{sid}/validate", json={"schema": schema}))
    assert v["error_count"] == 0, v["errors"][:5]
    assert v["warning_count"] == 0, v["warnings"][:5]
    return ok(client.post(f"/api/imports/{sid}/commit", json={"schema": v["schema"]}))["version_id"]


def test_project_docs_are_traceable(client):
    req = ok(client.post("/api/documents", json={"name": "要件定義書"}))["id"]
    des = ok(client.post("/api/documents", json={"name": "詳細設計書"}))["id"]
    rel = ok(client.post("/api/relations", json={"upper_doc_id": req, "lower_doc_id": des}))["id"]
    _import(client, req, DOCS / "要件定義書.csv", req_schema())
    _import(client, des, DOCS / "詳細設計書.csv", design_schema(req))

    ev = ok(client.get(f"/api/trace/{rel}"))
    assert ev["broken"] == [], "存在しない要件 ID を参照している設計があります"
    assert ev["upper"]["untraced"] == [], "設計から参照されていない要件があります"
    assert ev["lower"]["untraced"] == [], "上位要件の無い設計があります"

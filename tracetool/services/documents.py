"""文書とカラム定義の管理。"""

from __future__ import annotations

import json
import sqlite3

from .. import colschema
from ..db import now_iso
from ..errors import AppError, NotFound


def _row_to_doc(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "schema": json.loads(row["schema_json"]),
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
    }


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM documents ORDER BY sort_order, id").fetchall()
    return [_row_to_doc(r) for r in rows]


def get_document(conn: sqlite3.Connection, doc_id: int) -> dict:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise NotFound("文書が見つかりません")
    return _row_to_doc(row)


def check_schema(conn: sqlite3.Connection, doc_id: int | None, schema: dict) -> dict:
    """カラム定義を正規化し、誤りがあれば AppError を投げる。"""
    schema = colschema.normalize_schema(schema)
    errors = colschema.validate_schema(schema)
    for col in colschema.columns(schema):
        ref = col.get("ref_document_id")
        if ref is None:
            continue
        if ref == doc_id:
            errors.append(f"参照 ID 列「{col['name']}」の参照先に自分自身は指定できません")
            continue
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (ref,)).fetchone() is None:
            errors.append(f"参照 ID 列「{col['name']}」の参照先文書がありません")
    if errors:
        raise AppError("カラム定義に誤りがあります:\n" + "\n".join(errors), code="invalid_schema")
    return schema


def _check_name(conn: sqlite3.Connection, name: str, doc_id: int | None) -> str:
    name = (name or "").strip()
    if not name:
        raise AppError("文書名を入力してください")
    row = conn.execute("SELECT id FROM documents WHERE name = ?", (name,)).fetchone()
    if row is not None and row["id"] != doc_id:
        raise AppError(f"文書名「{name}」は既に使われています")
    return name


def create_document(conn: sqlite3.Connection, name: str, description: str, schema: dict | None) -> int:
    name = _check_name(conn, name, None)
    schema = colschema.normalize_schema(schema or colschema.empty_schema())
    # 作成直後は列が無くてもよい（取り込み画面で列を作れるようにする）
    if colschema.columns(schema):
        schema = check_schema(conn, None, schema)
    order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM documents").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO documents(name, description, schema_json, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, description or "", json.dumps(schema, ensure_ascii=False), order, now_iso()),
    )
    return cur.lastrowid


def update_document(
    conn: sqlite3.Connection, doc_id: int, name: str, description: str | None, schema: dict | None
) -> None:
    """schema / description が None なら既存の値を維持する。"""
    current = get_document(conn, doc_id)
    name = _check_name(conn, name, doc_id)
    if description is None:
        description = current["description"]
    if schema is None:
        schema = current["schema"]
    schema = colschema.normalize_schema(schema)
    if colschema.columns(schema):
        schema = check_schema(conn, doc_id, schema)
    conn.execute(
        "UPDATE documents SET name = ?, description = ?, schema_json = ? WHERE id = ?",
        (name, description or "", json.dumps(schema, ensure_ascii=False), doc_id),
    )


def referencing_documents(conn: sqlite3.Connection, doc_id: int) -> list[str]:
    """作業中のカラム定義で、この文書を参照 ID 列の参照先にしている文書の名前。"""
    names = []
    for d in list_documents(conn):
        if any(c.get("ref_document_id") == doc_id for c in colschema.columns(d["schema"])):
            names.append(d["name"])
    return names


def delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    get_document(conn, doc_id)
    # 他の文書の作業中定義から、この文書への参照を外す（参照先の無い参照 ID 列を残さない）
    for d in list_documents(conn):
        if d["id"] == doc_id:
            continue
        cols = colschema.columns(d["schema"])
        if not any(c.get("ref_document_id") == doc_id for c in cols):
            continue
        for c in cols:
            if c.get("ref_document_id") == doc_id:
                c["ref_document_id"] = None
        conn.execute(
            "UPDATE documents SET schema_json = ? WHERE id = ?", (json.dumps(d["schema"], ensure_ascii=False), d["id"])
        )
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.execute("DELETE FROM meta WHERE key = ?", (f"max_version_no:{doc_id}",))
    if hasattr(conn, "clear_cache"):
        conn.clear_cache()

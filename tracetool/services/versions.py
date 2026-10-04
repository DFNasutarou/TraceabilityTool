"""版と項目の取得・削除。"""

from __future__ import annotations

import json
import sqlite3

from ..errors import NotFound


def _row_to_version(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "version_no": row["version_no"],
        "label": row["label"],
        "source_filename": row["source_filename"],
        "import_settings": json.loads(row["import_settings"]),
        "schema": json.loads(row["schema_json"]),
        "row_count": row["row_count"],
        "imported_at": row["imported_at"],
    }


def list_versions(conn: sqlite3.Connection, doc_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM versions WHERE document_id = ? ORDER BY version_no DESC", (doc_id,)
    ).fetchall()
    return [_row_to_version(r) for r in rows]


def get_version(conn: sqlite3.Connection, version_id: int) -> dict:
    row = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        raise NotFound("版が見つかりません")
    return _row_to_version(row)


def latest_version(conn: sqlite3.Connection, doc_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM versions WHERE document_id = ? ORDER BY version_no DESC LIMIT 1", (doc_id,)
    ).fetchone()
    return _row_to_version(row) if row else None


def load_items(conn: sqlite3.Connection, version_id: int) -> list[dict]:
    """版の全項目を取り込み順で返す。

    結果はキャッシュを共有するので、呼び出し側で書き換えないこと（必要なら複製する）。
    """
    cache = getattr(conn, "cache", None)
    if cache is not None and version_id in cache["items"]:
        return cache["items"][version_id]
    rows = conn.execute(
        "SELECT item_id, row_no, data_json, invalid_json, content_hash FROM items "
        "WHERE version_id = ? ORDER BY row_no",
        (version_id,),
    ).fetchall()
    items = [
        {
            "item_id": r["item_id"],
            "row_no": r["row_no"],
            "data": json.loads(r["data_json"]),
            "invalid": json.loads(r["invalid_json"]),
            "hash": r["content_hash"],
        }
        for r in rows
    ]
    if cache is not None:
        cache["items"][version_id] = items
    return items


def get_item(conn: sqlite3.Connection, version_id: int, item_id: str) -> dict:
    r = conn.execute(
        "SELECT item_id, row_no, data_json, invalid_json, content_hash FROM items "
        "WHERE version_id = ? AND item_id = ?",
        (version_id, item_id),
    ).fetchone()
    if r is None:
        raise NotFound(f"項目「{item_id}」が見つかりません")
    return {
        "item_id": r["item_id"],
        "row_no": r["row_no"],
        "data": json.loads(r["data_json"]),
        "invalid": json.loads(r["invalid_json"]),
        "hash": r["content_hash"],
    }


def version_hashes(conn: sqlite3.Connection, version_id: int) -> dict[str, str]:
    """版の {項目ID: ハッシュ}。キャッシュを共有するので書き換えないこと。"""
    cache = getattr(conn, "cache", None)
    if cache is not None and version_id in cache["hashes"]:
        return cache["hashes"][version_id]
    rows = conn.execute("SELECT item_id, content_hash FROM items WHERE version_id = ?", (version_id,)).fetchall()
    hashes = {r["item_id"]: r["content_hash"] for r in rows}
    if cache is not None:
        cache["hashes"][version_id] = hashes
    return hashes


def latest_hashes(conn: sqlite3.Connection, doc_id: int) -> dict[str, str]:
    """文書の最新版の {項目ID: ハッシュ}。版が無ければ空。"""
    v = latest_version(conn, doc_id)
    if v is None:
        return {}
    return version_hashes(conn, v["id"])


def delete_version(conn: sqlite3.Connection, version_id: int) -> int:
    """版を削除し、文書 ID を返す。自動リンクの再生成は呼び出し側で行う。"""
    v = get_version(conn, version_id)
    conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))
    if hasattr(conn, "clear_cache"):
        conn.clear_cache()
    return v["document_id"]

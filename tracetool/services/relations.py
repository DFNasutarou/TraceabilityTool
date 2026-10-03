"""トレース関係（上位文書 → 下位文書）の管理。"""

from __future__ import annotations

import sqlite3

from ..errors import AppError, NotFound


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "upper_doc_id": r["upper_doc_id"], "lower_doc_id": r["lower_doc_id"]}


def list_relations(conn: sqlite3.Connection) -> list[dict]:
    return [_row(r) for r in conn.execute("SELECT * FROM relations ORDER BY id").fetchall()]


def get_relation(conn: sqlite3.Connection, rel_id: int) -> dict:
    r = conn.execute("SELECT * FROM relations WHERE id = ?", (rel_id,)).fetchone()
    if r is None:
        raise NotFound("トレース関係が見つかりません")
    return _row(r)


def relation_between(conn: sqlite3.Connection, doc_a: int, doc_b: int) -> dict | None:
    """2 つの文書の間の関係（向きは問わない）。"""
    r = conn.execute(
        "SELECT * FROM relations WHERE (upper_doc_id = ? AND lower_doc_id = ?) "
        "OR (upper_doc_id = ? AND lower_doc_id = ?)",
        (doc_a, doc_b, doc_b, doc_a),
    ).fetchone()
    return _row(r) if r else None


def relations_of(conn: sqlite3.Connection, doc_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM relations WHERE upper_doc_id = ? OR lower_doc_id = ? ORDER BY id", (doc_id, doc_id)
    ).fetchall()
    return [_row(r) for r in rows]


def _reachable(conn: sqlite3.Connection, start: int, goal: int) -> bool:
    """start から下位方向にたどって goal に到達できるか。"""
    edges: dict[int, list[int]] = {}
    for r in conn.execute("SELECT upper_doc_id, lower_doc_id FROM relations").fetchall():
        edges.setdefault(r[0], []).append(r[1])
    stack, seen = [start], set()
    while stack:
        n = stack.pop()
        if n == goal:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(edges.get(n, []))
    return False


def create_relation(conn: sqlite3.Connection, upper_doc_id: int, lower_doc_id: int) -> int:
    if upper_doc_id == lower_doc_id:
        raise AppError("同じ文書どうしの関係は作れません")
    for d in (upper_doc_id, lower_doc_id):
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (d,)).fetchone() is None:
            raise NotFound("文書が見つかりません")
    if relation_between(conn, upper_doc_id, lower_doc_id):
        raise AppError("この 2 つの文書の間には既に関係があります")
    if _reachable(conn, lower_doc_id, upper_doc_id):
        raise AppError("この関係を追加すると上位・下位が循環します")
    cur = conn.execute(
        "INSERT INTO relations(upper_doc_id, lower_doc_id) VALUES (?, ?)", (upper_doc_id, lower_doc_id)
    )
    return cur.lastrowid


def delete_relation(conn: sqlite3.Connection, rel_id: int) -> None:
    get_relation(conn, rel_id)
    conn.execute("DELETE FROM relations WHERE id = ?", (rel_id,))

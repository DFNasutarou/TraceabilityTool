"""トレース関係（上位文書 → 下位文書）の管理。

上位と下位が同じ文書の関係（画面遷移など、文書内のつながり）も作れる。
"""

from __future__ import annotations

import json
import sqlite3

from .. import colschema
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


def sides_of(conn: sqlite3.Connection, doc_id: int) -> list[tuple[dict, bool]]:
    """文書が関わる関係と、その関係で文書が上位側か（True）。

    同じ文書どうしの関係は、上位側・下位側の 2 つとして返す。
    """
    out = []
    for rel in relations_of(conn, doc_id):
        if rel["upper_doc_id"] == doc_id:
            out.append((rel, True))
        if rel["lower_doc_id"] == doc_id:
            out.append((rel, False))
    return out


def missing_link_relation(conn: sqlite3.Connection, schema: dict) -> str | None:
    """関連表の上位側・下位側の参照先の間に、上位 → 下位の関係が無ければ、その旨のメッセージ。"""
    cols = colschema.link_columns(schema)
    if cols is None:
        return None
    up, lo = cols[0]["ref_document_id"], cols[1]["ref_document_id"]
    r = conn.execute("SELECT 1 FROM relations WHERE upper_doc_id = ? AND lower_doc_id = ?", (up, lo)).fetchone()
    if r is not None:
        return None
    names = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM documents WHERE id IN (?, ?)", (up, lo))}
    if up not in names or lo not in names:
        return None  # 参照先の文書が無い場合は別のエラーにする
    pair = f"「{names[up]}」内" if up == lo else f"「{names[up]}」→「{names[lo]}」"
    return (
        f"関連表の上位側・下位側の文書の間に、トレース関係（{pair}）がありません。"
        "列の設定に表示される「関係を登録」ボタン、または文書一覧の下部「トレース関係」で登録してください"
    )


def _reachable(conn: sqlite3.Connection, start: int, goal: int) -> bool:
    """start から下位方向にたどって goal に到達できるか。"""
    edges: dict[int, list[int]] = {}
    for r in conn.execute("SELECT upper_doc_id, lower_doc_id FROM relations").fetchall():
        if r[0] != r[1]:  # 文書内の関係は循環の判定に含めない
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
    for d in (upper_doc_id, lower_doc_id):
        row = conn.execute("SELECT name, schema_json FROM documents WHERE id = ?", (d,)).fetchone()
        if row is None:
            raise NotFound("文書が見つかりません")
        if colschema.is_link_table(json.loads(row["schema_json"])):
            raise AppError(f"「{row['name']}」は関連表です。関連表はつながりを表す文書なので、関係の上位・下位にはできません")
    if relation_between(conn, upper_doc_id, lower_doc_id):
        raise AppError("この文書の間には既に関係があります" if upper_doc_id != lower_doc_id else "この文書内の関係は既にあります")
    if upper_doc_id != lower_doc_id and _reachable(conn, lower_doc_id, upper_doc_id):
        raise AppError("この関係を追加すると上位・下位が循環します")
    cur = conn.execute(
        "INSERT INTO relations(upper_doc_id, lower_doc_id) VALUES (?, ?)", (upper_doc_id, lower_doc_id)
    )
    return cur.lastrowid


def delete_relation(conn: sqlite3.Connection, rel_id: int) -> None:
    get_relation(conn, rel_id)
    conn.execute("DELETE FROM relations WHERE id = ?", (rel_id,))

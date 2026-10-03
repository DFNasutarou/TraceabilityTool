"""リンクの追加・削除・確認と、参照 ID 列からの自動リンク生成。

1 つの（上位項目, 下位項目）の組に対してリンク行は 1 行だけ持ち、生成元をフラグで表す。
有効 = manual OR ((auto_by_upper OR auto_by_lower) AND NOT auto_disabled)
"""

from __future__ import annotations

import sqlite3

from .. import colschema
from ..db import now_iso
from ..errors import AppError, NotFound
from . import relations as rel_svc
from . import versions as ver_svc

ACTIVE_SQL = "(manual = 1 OR ((auto_by_upper = 1 OR auto_by_lower = 1) AND auto_disabled = 0))"


def is_active(link: dict) -> bool:
    return bool(link["manual"] or ((link["auto_by_upper"] or link["auto_by_lower"]) and not link["auto_disabled"]))


def get_link(conn: sqlite3.Connection, link_id: int) -> dict:
    r = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if r is None:
        raise NotFound("リンクが見つかりません")
    return dict(r)


def links_of_relation(conn: sqlite3.Connection, rel_id: int, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM links WHERE relation_id = ?"
    if active_only:
        sql += " AND " + ACTIVE_SQL
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", (rel_id,)).fetchall()]


def _delete_if_unused(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute(
        "DELETE FROM links WHERE id = ? AND manual = 0 AND auto_by_upper = 0 AND auto_by_lower = 0",
        (link_id,),
    )


def regenerate_auto_links(conn: sqlite3.Connection, doc_id: int) -> None:
    """文書の最新版の参照 ID 列から、その文書が生成元の自動リンクを作り直す。"""
    latest = ver_svc.latest_version(conn, doc_id)
    items = ver_svc.load_items(conn, latest["id"]) if latest else []
    schema = latest["schema"] if latest else colschema.empty_schema()

    for rel in rel_svc.relations_of(conn, doc_id):
        is_upper = rel["upper_doc_id"] == doc_id
        other = rel["lower_doc_id"] if is_upper else rel["upper_doc_id"]
        flag = "auto_by_upper" if is_upper else "auto_by_lower"

        ref_cols = [c for c in colschema.columns(schema) if c.get("ref_document_id") == other]
        pairs: set[tuple[str, str]] = set()
        for item in items:
            for col in ref_cols:
                for ref in colschema.ref_values(item["data"].get(col["key"])):
                    pairs.add((item["item_id"], ref) if is_upper else (ref, item["item_id"]))

        existing = conn.execute(
            f"SELECT id, upper_item_id, lower_item_id FROM links WHERE relation_id = ? AND {flag} = 1",
            (rel["id"],),
        ).fetchall()
        flagged = set()
        for r in existing:
            key = (r["upper_item_id"], r["lower_item_id"])
            if key in pairs:
                flagged.add(key)
                continue
            conn.execute(f"UPDATE links SET {flag} = 0 WHERE id = ?", (r["id"],))
            _delete_if_unused(conn, r["id"])

        to_add = pairs - flagged
        if not to_add:
            continue
        upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
        lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
        ts = now_iso()
        for upper_id, lower_id in to_add:
            cur = conn.execute(
                f"UPDATE links SET {flag} = 1 WHERE relation_id = ? AND upper_item_id = ? AND lower_item_id = ?",
                (rel["id"], upper_id, lower_id),
            )
            if cur.rowcount == 0:
                conn.execute(
                    f"INSERT INTO links(relation_id, upper_item_id, lower_item_id, {flag}, "
                    "upper_hash_ack, lower_hash_ack, created_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                    (rel["id"], upper_id, lower_id, upper_hashes.get(upper_id), lower_hashes.get(lower_id), ts),
                )


def add_manual_link(conn: sqlite3.Connection, rel_id: int, upper_item_id: str, lower_item_id: str) -> int:
    rel = rel_svc.get_relation(conn, rel_id)
    upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
    lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
    if upper_item_id not in upper_hashes:
        raise AppError(f"上位文書の最新版に項目「{upper_item_id}」がありません")
    if lower_item_id not in lower_hashes:
        raise AppError(f"下位文書の最新版に項目「{lower_item_id}」がありません")
    row = conn.execute(
        "SELECT id FROM links WHERE relation_id = ? AND upper_item_id = ? AND lower_item_id = ?",
        (rel_id, upper_item_id, lower_item_id),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE links SET manual = 1, auto_disabled = 0, upper_hash_ack = ?, lower_hash_ack = ? WHERE id = ?",
            (upper_hashes[upper_item_id], lower_hashes[lower_item_id], row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO links(relation_id, upper_item_id, lower_item_id, manual, upper_hash_ack, lower_hash_ack, "
        "created_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
        (rel_id, upper_item_id, lower_item_id, upper_hashes[upper_item_id], lower_hashes[lower_item_id], now_iso()),
    )
    return cur.lastrowid


def remove_link(conn: sqlite3.Connection, link_id: int) -> None:
    """リンクを画面から削除する。自動リンクは無効化の印を付けて残す（再取り込みで復活させないため）。"""
    link = get_link(conn, link_id)
    auto = link["auto_by_upper"] or link["auto_by_lower"]
    conn.execute(
        "UPDATE links SET manual = 0, auto_disabled = ? WHERE id = ?", (1 if auto else 0, link_id)
    )
    _delete_if_unused(conn, link_id)


def restore_auto_link(conn: sqlite3.Connection, link_id: int) -> None:
    """無効化した自動リンクを元に戻す。"""
    get_link(conn, link_id)
    conn.execute("UPDATE links SET auto_disabled = 0 WHERE id = ?", (link_id,))


def ack_links(conn: sqlite3.Connection, link_ids: list[int]) -> int:
    """リンクを確認済みにする（確認ハッシュを最新のハッシュで更新する）。"""
    hashes: dict[int, dict[str, str]] = {}
    count = 0
    for link_id in link_ids:
        link = get_link(conn, link_id)
        rel = rel_svc.get_relation(conn, link["relation_id"])
        for d in (rel["upper_doc_id"], rel["lower_doc_id"]):
            if d not in hashes:
                hashes[d] = ver_svc.latest_hashes(conn, d)
        conn.execute(
            "UPDATE links SET upper_hash_ack = ?, lower_hash_ack = ? WHERE id = ?",
            (
                hashes[rel["upper_doc_id"]].get(link["upper_item_id"]),
                hashes[rel["lower_doc_id"]].get(link["lower_item_id"]),
                link_id,
            ),
        )
        count += 1
    return count

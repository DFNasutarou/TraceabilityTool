"""リンクの追加・削除・確認と、関連表からの自動リンク生成。

1 つの（上位項目, 下位項目）の組に対してリンク行は 1 行だけ持ち、生成元をフラグで表す。
有効 = manual OR (auto_by_table AND NOT auto_disabled)

自動リンクは関連表（上位側のキーの列と下位側のキーの列を持つ文書）の最新版の各行から作る。
関係（上位文書 → 下位文書）ごとに、その組を対象にするすべての関連表の行を合わせたものが自動リンクになる。
"""

from __future__ import annotations

import sqlite3

from .. import colschema
from ..db import now_iso
from ..errors import AppError, NotFound
from . import relations as rel_svc
from . import versions as ver_svc

ACTIVE_SQL = "(manual = 1 OR (auto_by_table = 1 AND auto_disabled = 0))"


def is_active(link: dict) -> bool:
    return bool(link["manual"] or (link["auto_by_table"] and not link["auto_disabled"]))


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
    conn.execute("DELETE FROM links WHERE id = ? AND manual = 0 AND auto_by_table = 0", (link_id,))


def fill_missing_acks(conn: sqlite3.Connection, doc_id: int) -> None:
    """確認ハッシュが空のリンクに、この文書の最新版のハッシュを入れる。

    リンクを作った時点で相手の項目がまだ無かった場合（相手文書が未取り込み、リンク切れ）、
    確認ハッシュは空になる。項目が現れた時点のハッシュを「確認済み」の基準にしないと、
    取り込み順だけでリンクが要確認になってしまう。
    """
    hashes = ver_svc.latest_hashes(conn, doc_id)
    if not hashes:
        return
    for rel, as_upper in rel_svc.sides_of(conn, doc_id):
        side = "upper" if as_upper else "lower"
        rows = conn.execute(
            f"SELECT id, {side}_item_id AS item FROM links WHERE relation_id = ? AND {side}_hash_ack IS NULL",
            (rel["id"],),
        ).fetchall()
        for r in rows:
            h = hashes.get(r["item"])
            if h is not None:
                conn.execute(f"UPDATE links SET {side}_hash_ack = ? WHERE id = ?", (h, r["id"]))


def table_pairs(conn: sqlite3.Connection) -> dict[tuple[int, int], set[tuple[str, str]]]:
    """すべての関連表の最新版から、(上位文書, 下位文書) → {(上位 ID, 下位 ID)}。"""
    out: dict[tuple[int, int], set[tuple[str, str]]] = {}
    for row in conn.execute("SELECT id FROM documents").fetchall():
        latest = ver_svc.latest_version(conn, row["id"])
        if latest is None:
            continue
        cols = colschema.link_columns(latest["schema"])
        if cols is None:
            continue
        key = (cols[0]["ref_document_id"], cols[1]["ref_document_id"])
        out.setdefault(key, set()).update(colschema.link_pairs(latest["schema"], ver_svc.load_items(conn, latest["id"])))
    return out


def table_sources(conn: sqlite3.Connection, upper_doc_id: int, lower_doc_id: int) -> dict[tuple[str, str], list[dict]]:
    """(上位 ID, 下位 ID) → その組を作った関連表の行 [{document_id, document, item_id, label}]。"""
    out: dict[tuple[str, str], list[dict]] = {}
    for row in conn.execute("SELECT id, name FROM documents ORDER BY sort_order, id").fetchall():
        latest = ver_svc.latest_version(conn, row["id"])
        if latest is None:
            continue
        cols = colschema.link_columns(latest["schema"])
        if cols is None or (cols[0]["ref_document_id"], cols[1]["ref_document_id"]) != (upper_doc_id, lower_doc_id):
            continue
        disp = colschema.display_column_key(latest["schema"])
        for item in ver_svc.load_items(conn, latest["id"]):
            for pair in colschema.link_pairs(latest["schema"], [item]):
                out.setdefault(pair, []).append(
                    {
                        "document_id": row["id"],
                        "document": row["name"],
                        "item_id": item["item_id"],
                        "label": colschema.as_text(item["data"].get(disp)) if disp else "",
                    }
                )
    return out


def regenerate_auto_links(conn: sqlite3.Connection, doc_id: int | None = None) -> None:
    """関連表から自動リンクを作り直す（すべての関係が対象）。

    関連表の取り込み・編集・版の削除・文書の削除、関係の作成のたびに呼ぶ。関連表の数は多くないため、毎回すべてを作り直す。
    doc_id を指定すると、その文書側の確認ハッシュが空のリンクを埋める（fill_missing_acks）。
    """
    pairs_by_docs = table_pairs(conn)
    for rel in rel_svc.list_relations(conn):
        _regenerate_relation(conn, rel, pairs_by_docs.get((rel["upper_doc_id"], rel["lower_doc_id"]), set()))
    if doc_id is not None:
        fill_missing_acks(conn, doc_id)


def _regenerate_relation(conn: sqlite3.Connection, rel: dict, pairs: set[tuple[str, str]]) -> None:
    existing = conn.execute(
        "SELECT id, upper_item_id, lower_item_id FROM links WHERE relation_id = ? AND auto_by_table = 1", (rel["id"],)
    ).fetchall()
    flagged = set()
    for r in existing:
        key = (r["upper_item_id"], r["lower_item_id"])
        if key in pairs:
            flagged.add(key)
            continue
        conn.execute("UPDATE links SET auto_by_table = 0 WHERE id = ?", (r["id"],))
        _delete_if_unused(conn, r["id"])

    to_add = pairs - flagged
    if not to_add:
        return
    upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
    lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
    ts = now_iso()
    for upper_id, lower_id in to_add:
        cur = conn.execute(
            "UPDATE links SET auto_by_table = 1 WHERE relation_id = ? AND upper_item_id = ? AND lower_item_id = ?",
            (rel["id"], upper_id, lower_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO links(relation_id, upper_item_id, lower_item_id, auto_by_table, "
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
    auto = link["auto_by_table"]
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

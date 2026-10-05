"""項目の ID の付け直し（編集モードで ID を変えたとき）。

ID はリンクと、他の文書の参照 ID 列の値で使われているため、ID を変えるときは次をすべて付け直す。
- リンク: この文書側の項目 ID を新しい ID にする（手動リンク・無効化した自動リンクも含む）
- 他の文書の参照 ID 列: この文書を参照先にしている文書の最新版で、古い ID を新しい ID に書き換える（版は上げない）

ID を変えただけで「要確認」にならないよう、ID 以外が変わっていなければ確認ハッシュも付け替える。
"""

from __future__ import annotations

import json
import sqlite3

from .. import colschema
from ..db import now_iso
from . import documents as doc_svc
from . import relations as rel_svc
from . import versions as ver_svc

_LINK_FLAGS = ("manual", "auto_by_upper", "auto_by_lower")


def _map_ref(value, renames: dict[str, str]):
    """参照 ID 列の値（文字列またはリスト）の中の古い ID を新しい ID にする。"""
    if isinstance(value, list):
        return [renames.get(v, v) if isinstance(v, str) else v for v in value]
    if isinstance(value, str):
        return renames.get(value, value)
    return value


def _referring(conn: sqlite3.Connection, doc_id: int) -> list[tuple[dict, dict, list[dict]]]:
    """この文書を参照先にしている文書: [(文書, 最新版, 参照 ID 列)]。"""
    out = []
    for d in doc_svc.list_documents(conn):
        if d["id"] == doc_id:
            continue
        latest = ver_svc.latest_version(conn, d["id"])
        if latest is None:
            continue
        cols = [c for c in colschema.columns(latest["schema"]) if c.get("ref_document_id") == doc_id]
        if cols:
            out.append((d, latest, cols))
    return out


def impact(conn: sqlite3.Connection, doc_id: int, renames: dict[str, str]) -> dict:
    """ID を付け直すと変わるもの（保存前の確認用）。"""
    olds = list(renames)
    links = []
    for rel in rel_svc.relations_of(conn, doc_id):
        side = "upper" if rel["upper_doc_id"] == doc_id else "lower"
        other = rel["lower_doc_id"] if side == "upper" else rel["upper_doc_id"]
        n = 0
        for i in range(0, len(olds), 500):
            chunk = olds[i : i + 500]
            n += conn.execute(
                f"SELECT COUNT(*) FROM links WHERE relation_id = ? AND {side}_item_id IN ({','.join('?' * len(chunk))})",
                (rel["id"], *chunk),
            ).fetchone()[0]
        if n:
            links.append({"document": doc_svc.get_document(conn, other)["name"], "count": n})
    documents = []
    for d, latest, cols in _referring(conn, doc_id):
        items = [
            i["item_id"]
            for i in ver_svc.load_items(conn, latest["id"])
            if any(r in renames for c in cols for r in colschema.ref_values(i["data"].get(c["key"])))
        ]
        if items:
            documents.append({"document": d["name"], "version_no": latest["version_no"], "count": len(items), "items": items[:20]})
    return {"links": links, "documents": documents}


def rename_links(conn: sqlite3.Connection, doc_id: int, renames: dict[str, str], acks: dict[str, tuple[str, str]]) -> None:
    """この文書側の項目 ID が古い ID のリンクを、新しい ID に付け替える。

    acks: 新しい ID → (付け直す前のハッシュ, ID だけを変えた場合のハッシュ)。確認ハッシュが前者なら後者にする。
    付け替え先と同じ組のリンクが既にあれば（新しい ID へのリンク切れのリンクなど）、生成元のフラグをまとめて 1 行にする。
    """
    olds = list(renames)
    for rel in rel_svc.relations_of(conn, doc_id):
        side = "upper" if rel["upper_doc_id"] == doc_id else "lower"
        rows = []
        for i in range(0, len(olds), 500):
            chunk = olds[i : i + 500]
            rows += [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM links WHERE relation_id = ? AND {side}_item_id IN ({','.join('?' * len(chunk))})",
                    (rel["id"], *chunk),
                ).fetchall()
            ]
        # 入れ替え（A → B、B → A）でも一意制約にかからないよう、先に全部消してから入れ直す
        for r in rows:
            conn.execute("DELETE FROM links WHERE id = ?", (r["id"],))
        for r in rows:
            new_id = renames[r[f"{side}_item_id"]]
            r[f"{side}_item_id"] = new_id
            before, after = acks.get(new_id, (None, None))
            if before is not None and r[f"{side}_hash_ack"] == before:
                r[f"{side}_hash_ack"] = after
            dup = conn.execute(
                "SELECT * FROM links WHERE relation_id = ? AND upper_item_id = ? AND lower_item_id = ?",
                (rel["id"], r["upper_item_id"], r["lower_item_id"]),
            ).fetchone()
            if dup is not None:
                # 確認ハッシュは、付け替えた側（元のリンク）の値を優先する（付け替え先は主にリンク切れで、確認の基準を持たない）
                merged = {f: int(bool(dup[f] or r[f])) for f in _LINK_FLAGS}
                conn.execute(
                    "UPDATE links SET manual = ?, auto_by_upper = ?, auto_by_lower = ?, auto_disabled = ?, "
                    "upper_hash_ack = ?, lower_hash_ack = ? WHERE id = ?",
                    (merged["manual"], merged["auto_by_upper"], merged["auto_by_lower"],
                     int(bool(dup["auto_disabled"] and r["auto_disabled"])),
                     r["upper_hash_ack"] if r["upper_hash_ack"] is not None else dup["upper_hash_ack"],
                     r["lower_hash_ack"] if r["lower_hash_ack"] is not None else dup["lower_hash_ack"],
                     dup["id"]),
                )
                continue
            cols = list(r)
            conn.execute(
                f"INSERT INTO links({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols]
            )


def rename_references(
    conn: sqlite3.Connection, doc_id: int, renames: dict[str, str], valid_ids: set[str]
) -> list[int]:
    """この文書を参照している文書の最新版で、参照 ID 列の古い ID を新しい ID に書き換える。書き換えた文書 ID を返す。

    valid_ids: 保存後のこの文書の項目 ID。付け直した列と、新しい ID を元から参照していた列で、
    参照先がすべてそろえば、その列の警告（参照先に無い ID）を外す。
    """
    changed_docs = []
    for d, latest, cols in _referring(conn, doc_id):
        # 書き換えた項目はハッシュが変わるため、その文書が持つすべての関係で確認ハッシュを付け替える
        # （編集した文書との関係だけでなく、例えば下位文書とのリンクも、参照 ID を直しただけで要確認にしない）
        sides = [(rel["id"], "upper" if rel["upper_doc_id"] == d["id"] else "lower") for rel in rel_svc.relations_of(conn, d["id"])]
        changed = 0
        for item in ver_svc.load_items(conn, latest["id"]):
            data = dict(item["data"])
            touched = []
            for c in cols:
                if c["key"] in data:
                    mapped = _map_ref(data[c["key"]], renames)
                    if mapped != data[c["key"]]:
                        data[c["key"]] = mapped
                        touched.append(c["key"])
            # 警告（参照先に無い ID）を見直す列: 書き換えた列と、新しい ID を元から参照していた列
            new_ids = set(renames.values())
            recheck = set(touched) | {
                c["key"] for c in cols if c["key"] in item["invalid"] and new_ids & set(colschema.ref_values(data.get(c["key"])))
            }
            invalid = [
                k for k in item["invalid"]
                if not (k in recheck and all(r in valid_ids for r in colschema.ref_values(data[k])))
            ]
            if not touched:
                # 値は変わらないので、ハッシュ・リンクはそのまま。警告だけを外す
                if invalid != item["invalid"]:
                    conn.execute(
                        "UPDATE items SET invalid_json = ? WHERE version_id = ? AND item_id = ?",
                        (json.dumps(invalid), latest["id"], item["item_id"]),
                    )
                    changed += 1
                continue
            new_hash = colschema.content_hash(data)
            conn.execute(
                "UPDATE items SET data_json = ?, invalid_json = ?, content_hash = ? WHERE version_id = ? AND item_id = ?",
                (json.dumps(data, ensure_ascii=False), json.dumps(invalid), new_hash, latest["id"], item["item_id"]),
            )
            # 参照 ID を付け直しただけなので、確認済みだったリンクは確認済みのままにする
            for rel_id, side in sides:
                conn.execute(
                    f"UPDATE links SET {side}_hash_ack = ? WHERE relation_id = ? AND {side}_item_id = ? AND {side}_hash_ack = ?",
                    (new_hash, rel_id, item["item_id"], item["hash"]),
                )
            changed += 1
        if changed:
            # 版の書き換えとして数える（この文書を編集中の画面が、古い内容で上書きしないように）
            revision = latest["import_settings"].get("revision", 0) + 1
            settings = {**latest["import_settings"], "ids_renamed_at": now_iso(), "revision": revision}
            conn.execute(
                "UPDATE versions SET import_settings = ? WHERE id = ?", (json.dumps(settings, ensure_ascii=False), latest["id"])
            )
            changed_docs.append(d["id"])
    if changed_docs and hasattr(conn, "clear_cache"):
        conn.clear_cache()
    return changed_docs

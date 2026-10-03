"""項目一覧の検索・絞り込み・ソート・ページング。"""

from __future__ import annotations

import sqlite3

from .. import colschema
from . import trace as trace_svc
from . import versions as ver_svc

TRACE_FILTERS = ("no_upper", "no_lower", "suspect", "broken")


def _sort_key(value):
    """None は最後、数値は数値として、それ以外は文字列として並べる。"""
    if value is None or value == [] or value == "":
        return (2, 0, "")
    if isinstance(value, bool):
        return (0, int(value), "")
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, colschema.as_text(value).casefold())


def query_items(
    conn: sqlite3.Connection,
    version_id: int,
    q: str = "",
    filters: dict[str, str] | None = None,
    sort: str | None = None,
    desc: bool = False,
    trace: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    version = ver_svc.get_version(conn, version_id)
    latest = ver_svc.latest_version(conn, version["document_id"])
    is_latest = latest is not None and latest["id"] == version_id
    items = ver_svc.load_items(conn, version_id)

    summary = trace_svc.item_trace_summary(conn, version["document_id"]) if is_latest else {}
    for item in items:
        item["trace"] = summary.get(item["item_id"])

    q = (q or "").strip().casefold()
    if q:
        items = [
            i
            for i in items
            if q in i["item_id"].casefold() or any(q in colschema.as_text(v).casefold() for v in i["data"].values())
        ]
    for key, text in (filters or {}).items():
        text = text.strip().casefold()
        if not text:
            continue
        if key == "__invalid":
            items = [i for i in items if i["invalid"]]
            continue
        items = [i for i in items if text in colschema.as_text(i["data"].get(key)).casefold()]
    if trace in TRACE_FILTERS and is_latest:
        items = [i for i in items if i["trace"] and i["trace"][trace]]

    if sort:
        if sort in ("upper_count", "lower_count"):
            items.sort(key=lambda i: (i["trace"] or {}).get(sort, 0), reverse=desc)
        elif sort == "row_no":
            items.sort(key=lambda i: i["row_no"], reverse=desc)
        else:
            # 空の値は昇順・降順どちらでも最後に置く
            filled = [i for i in items if _sort_key(i["data"].get(sort))[0] != 2]
            empty = [i for i in items if _sort_key(i["data"].get(sort))[0] == 2]
            filled.sort(key=lambda i: _sort_key(i["data"].get(sort)), reverse=desc)
            items = filled + empty

    total = len(items)
    size = max(1, min(size, 1000))
    page = max(1, page)
    start = (page - 1) * size
    return {
        "version": {k: version[k] for k in ("id", "document_id", "version_no", "label", "imported_at")},
        "schema": version["schema"],
        "is_latest": is_latest,
        "total": total,
        "page": page,
        "size": size,
        "items": items[start : start + size],
    }


def item_detail(conn: sqlite3.Connection, version_id: int, item_id: str) -> dict:
    """項目の値と、関係ごとの上位・下位リンク（最新版のときのみ）。"""
    from . import documents as doc_svc
    from . import links as link_svc
    from . import relations as rel_svc

    version = ver_svc.get_version(conn, version_id)
    item = ver_svc.get_item(conn, version_id, item_id)
    doc_id = version["document_id"]
    latest = ver_svc.latest_version(conn, doc_id)
    is_latest = latest is not None and latest["id"] == version_id

    groups = []
    if is_latest:
        for rel in rel_svc.relations_of(conn, doc_id):
            as_upper = rel["upper_doc_id"] == doc_id
            other_id = rel["lower_doc_id"] if as_upper else rel["upper_doc_id"]
            other_doc = doc_svc.get_document(conn, other_id)
            other_latest = ver_svc.latest_version(conn, other_id)
            other_items = {i["item_id"]: i for i in ver_svc.load_items(conn, other_latest["id"])} if other_latest else {}
            disp = colschema.display_column_key(other_latest["schema"]) if other_latest else None
            upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
            lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
            mine, theirs = ("upper_item_id", "lower_item_id") if as_upper else ("lower_item_id", "upper_item_id")
            rows = conn.execute(
                f"SELECT * FROM links WHERE relation_id = ? AND {mine} = ? ORDER BY id", (rel["id"], item_id)
            ).fetchall()
            entries = []
            for r in rows:
                link = dict(r)
                other_item = other_items.get(link[theirs])
                entries.append(
                    {
                        "id": link["id"],
                        "item_id": link[theirs],
                        "label": colschema.as_text(other_item["data"].get(disp)) if other_item and disp else "",
                        "active": link_svc.is_active(link),
                        "origin": trace_svc.link_origin(link),
                        "auto": bool(link["auto_by_upper"] or link["auto_by_lower"]),
                        "status": trace_svc.link_status(link, upper_hashes, lower_hashes),
                    }
                )
            groups.append(
                {
                    "relation_id": rel["id"],
                    "direction": "lower" if as_upper else "upper",  # 相手が下位文書なら lower
                    "document": {"id": other_id, "name": other_doc["name"]},
                    "version_id": other_latest["id"] if other_latest else None,
                    "links": entries,
                }
            )
    return {
        "version": {k: version[k] for k in ("id", "document_id", "version_no", "label")},
        "schema": version["schema"],
        "is_latest": is_latest,
        "item": item,
        "relations": groups,
    }


def find_items(conn: sqlite3.Connection, doc_id: int, q: str, limit: int = 30) -> list[dict]:
    """リンク追加用に、文書の最新版から ID または表示列で項目を探す。"""
    latest = ver_svc.latest_version(conn, doc_id)
    if latest is None:
        return []
    disp = colschema.display_column_key(latest["schema"])
    q = (q or "").strip().casefold()
    out = []
    for item in ver_svc.load_items(conn, latest["id"]):
        label = colschema.as_text(item["data"].get(disp)) if disp else ""
        if not q or q in item["item_id"].casefold() or q in label.casefold():
            out.append({"item_id": item["item_id"], "label": label})
            if len(out) >= limit:
                break
    return out

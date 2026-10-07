"""項目一覧の検索・絞り込み・ソート・ページング。"""

from __future__ import annotations

import sqlite3

from .. import colschema
from . import relations as rel_svc
from . import trace as trace_svc
from . import versions as ver_svc

TRACE_FILTERS = ("no_upper", "no_lower", "suspect", "broken")
EMPTY = "__empty__"  # 選択式の絞り込みで「空欄」を表す値
OTHER = "__other__"  # 選択式の絞り込みで「選択肢に無い値」を表す値


def _choice_keys(col: dict, value) -> set[str]:
    """選択式の絞り込み（enum・bool）で、セルの値が当てはまる選択肢。"""
    if value is None or value == []:
        return {EMPTY}
    out: set[str] = set()
    enum_values = col.get("enum_values") or []
    for v in value if isinstance(value, list) else [value]:
        if isinstance(v, bool):
            out.add("true" if v else "false")
        elif col["type"] == "enum" and v in enum_values:
            out.add(str(v))
        else:
            out.add(OTHER)  # 選択肢に無い値・真偽のどちらでもない値
    return out


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
    choices: dict[str, list[str]] | None = None,
) -> dict:
    """choices: 列キー → 選んだ選択肢（enum・bool の列の絞り込み。どれかに当てはまる項目を残す）。"""
    version = ver_svc.get_version(conn, version_id)
    latest = ver_svc.latest_version(conn, version["document_id"])
    is_latest = latest is not None and latest["id"] == version_id
    summary = trace_svc.item_trace_summary(conn, version["document_id"]) if is_latest else {}
    # キャッシュ共有の項目を書き換えないよう、複製してからトレース情報を付ける
    items = [dict(i, trace=summary.get(i["item_id"])) for i in ver_svc.load_items(conn, version_id)]
    rels = rel_svc.relations_of(conn, version["document_id"])

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
    cols_by_key = {c["key"]: c for c in colschema.columns(version["schema"])}
    for key, selected in (choices or {}).items():
        col = cols_by_key.get(key)
        if col is None or col["type"] not in ("enum", "bool") or not selected:
            continue
        wanted = set(selected)
        items = [i for i in items if _choice_keys(col, i["data"].get(key)) & wanted]
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
        "schema": display_schema(conn, version["document_id"], version["schema"]),
        "is_latest": is_latest,
        "has_upper": any(r["lower_doc_id"] == version["document_id"] for r in rels),
        "has_lower": any(r["upper_doc_id"] == version["document_id"] for r in rels),
        "total": total,
        "page": page,
        "size": size,
        "items": items[start : start + size],
    }


def item_detail(conn: sqlite3.Connection, version_id: int, item_id: str) -> dict:
    """項目の値と、関係ごとの上位・下位リンク（最新版のときのみ）。"""
    from . import documents as doc_svc
    from . import links as link_svc

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
                        "_order": other_item["row_no"] if other_item else float("inf"),
                    }
                )
            # 相手文書での並び順にする（リンク切れは最後）
            entries.sort(key=lambda e: (e["_order"], e["item_id"]))
            for e in entries:
                del e["_order"]
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


def display_schema(conn: sqlite3.Connection, doc_id: int, schema: dict) -> dict:
    """表示用のカラム定義。版のカラム定義に、文書の作業中定義の列の並び順・列名・重要度・幅・列名の後の改行を重ねる。

    これらは表示だけに使う設定なので、取り込み直さなくても文書の設定画面での変更がすぐに表示に反映されるようにする。
    並び順は作業中定義の順にし、作業中定義に無い列（取り込み後に設定画面で消した列）は後ろに元の順で置く。
    """
    from . import documents as doc_svc

    working_cols = colschema.columns(doc_svc.get_document(conn, doc_id)["schema"])
    working = {c["key"]: c for c in working_cols}
    order = {c["key"]: i for i, c in enumerate(working_cols)}
    version_cols = colschema.columns(schema)
    version_cols = sorted(
        version_cols, key=lambda c: order.get(c["key"], len(order) + version_cols.index(c))
    )
    cols = []
    for c in version_cols:
        w = working.get(c["key"])
        src = w or c
        cols.append(
            {
                **c,
                "name": src.get("name") or c["name"],
                "importance": src.get("importance") or colschema.DEFAULT_IMPORTANCE,
                "width": src.get("width") or "auto",
                "label_break": bool(src.get("label_break")),
            }
        )
    return {**schema, "columns": cols}


def edit_stamp(version: dict) -> str:
    from .editing import version_stamp

    return version_stamp(version)


def latest_items(conn: sqlite3.Connection, doc_id: int) -> dict:
    """横並び表示の「この項目」の列用: 文書の最新版の全項目（取り込み順）と表示用のカラム定義。"""
    from ..errors import AppError

    latest = ver_svc.latest_version(conn, doc_id)
    if latest is None:
        raise AppError("まだ取り込まれていません")
    return {
        "version_id": latest["id"],
        "version_no": latest["version_no"],
        "stamp": edit_stamp(latest),
        "schema": display_schema(conn, doc_id, latest["schema"]),
        "items": [
            {"item_id": i["item_id"], "data": i["data"], "invalid": i["invalid"]}
            for i in ver_svc.load_items(conn, latest["id"])
        ],
    }


def item_neighborhood(conn: sqlite3.Connection, doc_id: int, item_id: str) -> dict:
    """横並び表示用: 項目と、そのリンク先の上位項目・下位項目の全列（各文書の最新版）。

    無効化したリンクは含めない。リンク先が最新版に無い（リンク切れ）場合は data を None にする。
    prev / next は同じ文書の最新版での前後の項目 ID（項目を順にたどるため）。
    """
    from ..errors import AppError
    from . import documents as doc_svc
    from . import links as link_svc

    doc = doc_svc.get_document(conn, doc_id)
    latest = ver_svc.latest_version(conn, doc_id)
    if latest is None:
        raise AppError("まだ取り込まれていません")
    item = ver_svc.get_item(conn, latest["id"], item_id)
    order = [i["item_id"] for i in ver_svc.load_items(conn, latest["id"])]
    pos = order.index(item_id)

    sides: dict[str, list] = {"upper": [], "lower": []}
    for rel in rel_svc.relations_of(conn, doc_id):
        as_upper = rel["upper_doc_id"] == doc_id
        other_id = rel["lower_doc_id"] if as_upper else rel["upper_doc_id"]
        other_latest = ver_svc.latest_version(conn, other_id)
        other_items = ver_svc.load_items(conn, other_latest["id"]) if other_latest else []
        other_pos = {i["item_id"]: n for n, i in enumerate(other_items)}
        upper_hashes = ver_svc.latest_hashes(conn, rel["upper_doc_id"])
        lower_hashes = ver_svc.latest_hashes(conn, rel["lower_doc_id"])
        mine, theirs = ("upper_item_id", "lower_item_id") if as_upper else ("lower_item_id", "upper_item_id")
        rows = conn.execute(
            f"SELECT * FROM links WHERE relation_id = ? AND {mine} = ?", (rel["id"], item_id)
        ).fetchall()
        entries = []
        for r in rows:
            link = dict(r)
            if not link_svc.is_active(link):
                continue
            n = other_pos.get(link[theirs])
            other = other_items[n] if n is not None else None
            entries.append(
                {
                    "link_id": link["id"],
                    "item_id": link[theirs],
                    "data": other["data"] if other else None,
                    "invalid": other["invalid"] if other else [],
                    "status": trace_svc.link_status(link, upper_hashes, lower_hashes),
                    "origin": trace_svc.link_origin(link),
                    "_order": n if n is not None else len(other_items),
                }
            )
        entries.sort(key=lambda e: (e["_order"], e["item_id"]))
        for e in entries:
            del e["_order"]
        sides["lower" if as_upper else "upper"].append(
            {
                "relation_id": rel["id"],
                "document": {"id": other_id, "name": doc_svc.get_document(conn, other_id)["name"]},
                "schema": display_schema(conn, other_id, other_latest["schema"]) if other_latest else colschema.empty_schema(),
                "items": entries,
            }
        )
    return {
        "document": {"id": doc_id, "name": doc["name"]},
        "schema": display_schema(conn, doc_id, latest["schema"]),
        "item": item,
        "prev": order[pos - 1] if pos > 0 else None,
        "next": order[pos + 1] if pos + 1 < len(order) else None,
        "position": pos + 1,
        "total": len(order),
        "upper": sides["upper"],
        "lower": sides["lower"],
    }


def distinct_values(conn: sqlite3.Connection, doc_id: int, key: str) -> dict:
    """文書の最新版で、列に使われている値の一覧（enum の選択肢を作るため）。"""
    from ..errors import AppError

    latest = ver_svc.latest_version(conn, doc_id)
    if latest is None:
        raise AppError("まだ取り込まれていないため、使われている値がありません")
    if key not in {c["key"] for c in colschema.columns(latest["schema"])}:
        raise AppError("この列は最新版にありません（最新版の取り込み後に追加した列です）")
    values = colschema.distinct_texts((i["data"].get(key) for i in ver_svc.load_items(conn, latest["id"])), None)
    if len(values) > colschema.MAX_ENUM_VALUES:
        raise AppError(
            f"使われている値が {len(values)} 種類あり、enum にするには多すぎます（上限 {colschema.MAX_ENUM_VALUES} 種類）"
        )
    return {"values": values, "version_no": latest["version_no"]}


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

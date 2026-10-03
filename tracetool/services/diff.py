"""2 つの版の差分。"""

from __future__ import annotations

import json
import sqlite3

from .. import colschema
from ..errors import AppError
from . import versions as ver_svc


def _same(a, b) -> bool:
    """型まで含めて同じ値か。Python では 1 == True なので、ハッシュと同じく JSON 表現で比べる。"""
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def diff_schema(old: dict, new: dict) -> list[dict]:
    old_cols = {c["key"]: c for c in colschema.columns(old)}
    new_cols = {c["key"]: c for c in colschema.columns(new)}
    changes = []
    for key, c in new_cols.items():
        if key not in old_cols:
            changes.append({"kind": "added", "key": key, "name": c["name"]})
            continue
        o = old_cols[key]
        if o["name"] != c["name"]:
            changes.append({"kind": "renamed", "key": key, "name": c["name"], "old_name": o["name"]})
        if o["type"] != c["type"]:
            changes.append({"kind": "type_changed", "key": key, "name": c["name"], "old_type": o["type"], "new_type": c["type"]})
    for key, o in old_cols.items():
        if key not in new_cols:
            changes.append({"kind": "removed", "key": key, "name": o["name"]})
    return changes


def diff_versions(conn: sqlite3.Connection, from_vid: int, to_vid: int) -> dict:
    old_v = ver_svc.get_version(conn, from_vid)
    new_v = ver_svc.get_version(conn, to_vid)
    if old_v["document_id"] != new_v["document_id"]:
        raise AppError("異なる文書の版どうしは比較できません")
    old_items = {i["item_id"]: i for i in ver_svc.load_items(conn, from_vid)}
    new_items = ver_svc.load_items(conn, to_vid)

    # 列名は新しい版を優先し、削除された列は古い版の名前を使う
    names = {c["key"]: c["name"] for c in colschema.columns(old_v["schema"])}
    names.update({c["key"]: c["name"] for c in colschema.columns(new_v["schema"])})
    order = [c["key"] for c in colschema.columns(new_v["schema"])]
    order += [c["key"] for c in colschema.columns(old_v["schema"]) if c["key"] not in order]

    added, changed = [], []
    unchanged = 0
    for item in new_items:
        old = old_items.pop(item["item_id"], None)
        if old is None:
            added.append({"item_id": item["item_id"], "data": item["data"]})
        elif old["hash"] != item["hash"]:
            cells = [
                {"key": k, "name": names.get(k, k), "old": old["data"].get(k), "new": item["data"].get(k)}
                for k in order
                if not _same(old["data"].get(k), item["data"].get(k))
            ]
            changed.append({"item_id": item["item_id"], "cells": cells})
        else:
            unchanged += 1
    removed = [{"item_id": i["item_id"], "data": i["data"]} for i in old_items.values()]

    return {
        "from": {k: old_v[k] for k in ("id", "version_no", "label", "imported_at")},
        "to": {k: new_v[k] for k in ("id", "version_no", "label", "imported_at")},
        "columns": diff_schema(old_v["schema"], new_v["schema"]),
        "column_names": names,
        "column_order": order,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }

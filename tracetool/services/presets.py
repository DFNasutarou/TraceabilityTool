"""横並び表示の表示設定のプリセット（文書ごと）。

表示設定: 表示しない上位・下位のグループ（"関係ID:upper" / "関係ID:lower"）、表示する列の重要度、折り返し。
文書ごとに 1 つを「既定」にでき、横並び表示を開いたときに使う。
"""

from __future__ import annotations

import json
import sqlite3

from ..db import now_iso
from ..errors import AppError, NotFound
from . import documents as doc_svc

IMPORTANCE = ("low", "mid", "high")


def normalize_settings(raw: dict | None) -> dict:
    raw = raw or {}
    hidden = [str(h) for h in raw.get("hidden") or [] if isinstance(h, str) and h.count(":") == 1]
    return {
        "hidden": sorted(set(hidden)),
        "min_importance": raw.get("min_importance") if raw.get("min_importance") in IMPORTANCE else "low",
        "wrap": bool(raw.get("wrap", True)),
    }


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "document_id": r["document_id"],
        "name": r["name"],
        "settings": normalize_settings(json.loads(r["settings_json"])),
        "is_default": bool(r["is_default"]),
    }


def list_presets(conn: sqlite3.Connection, doc_id: int) -> list[dict]:
    doc_svc.get_document(conn, doc_id)
    rows = conn.execute("SELECT * FROM view_presets WHERE document_id = ? ORDER BY name, id", (doc_id,)).fetchall()
    return [_row(r) for r in rows]


def get_preset(conn: sqlite3.Connection, preset_id: int) -> dict:
    r = conn.execute("SELECT * FROM view_presets WHERE id = ?", (preset_id,)).fetchone()
    if r is None:
        raise NotFound("プリセットが見つかりません")
    return _row(r)


def _check_name(conn: sqlite3.Connection, doc_id: int, name: str, preset_id: int | None) -> str:
    name = (name or "").strip()
    if not name:
        raise AppError("プリセットの名前を入力してください")
    r = conn.execute("SELECT id FROM view_presets WHERE document_id = ? AND name = ?", (doc_id, name)).fetchone()
    if r is not None and r["id"] != preset_id:
        raise AppError(f"プリセット「{name}」は既にあります")
    return name


def _set_default(conn: sqlite3.Connection, doc_id: int, preset_id: int, is_default: bool) -> None:
    if is_default:
        conn.execute("UPDATE view_presets SET is_default = 0 WHERE document_id = ?", (doc_id,))
    conn.execute("UPDATE view_presets SET is_default = ? WHERE id = ?", (int(is_default), preset_id))


def create_preset(conn: sqlite3.Connection, doc_id: int, name: str, settings: dict, is_default: bool = False) -> int:
    doc_svc.get_document(conn, doc_id)
    name = _check_name(conn, doc_id, name, None)
    cur = conn.execute(
        "INSERT INTO view_presets(document_id, name, settings_json, is_default, created_at) VALUES (?, ?, ?, 0, ?)",
        (doc_id, name, json.dumps(normalize_settings(settings), ensure_ascii=False), now_iso()),
    )
    _set_default(conn, doc_id, cur.lastrowid, is_default)
    return cur.lastrowid


def update_preset(
    conn: sqlite3.Connection, preset_id: int, name: str | None, settings: dict | None, is_default: bool | None
) -> None:
    """None の項目は変えない。"""
    p = get_preset(conn, preset_id)
    if name is not None:
        conn.execute(
            "UPDATE view_presets SET name = ? WHERE id = ?", (_check_name(conn, p["document_id"], name, preset_id), preset_id)
        )
    if settings is not None:
        conn.execute(
            "UPDATE view_presets SET settings_json = ? WHERE id = ?",
            (json.dumps(normalize_settings(settings), ensure_ascii=False), preset_id),
        )
    if is_default is not None:
        _set_default(conn, p["document_id"], preset_id, is_default)


def delete_preset(conn: sqlite3.Connection, preset_id: int) -> None:
    get_preset(conn, preset_id)
    conn.execute("DELETE FROM view_presets WHERE id = ?", (preset_id,))

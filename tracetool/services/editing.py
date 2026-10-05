"""項目一覧の編集モード: 画面で編集した最新版の項目を保存する。

保存のしかたは 2 通り:
- new: 新しい版として保存する（版番号を上げる。差分で編集前と比べられる）
- overwrite: 最新版をそのまま書き換える（版番号は変えない）

取り込み済みの項目の ID を変えた場合は、リンクと他の文書の参照 ID も付け直す（renaming.py）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import colschema
from ..db import now_iso
from ..errors import AppError
from . import documents as doc_svc
from . import links as link_svc
from . import relations as rel_svc
from . import renaming
from . import versions as ver_svc

MODES = ("new", "overwrite")
MAX_ERRORS_SHOWN = 10


def _merge_working_schema(working: dict, edited: dict) -> dict:
    """文書の作業中のカラム定義に、編集で足した列と enum の選択肢を加える。

    作業中の定義は、最新版の取り込み後に文書の設定画面で変えられていることがあるため、置き換えずに足すだけにする。
    """
    if not colschema.columns(working):
        return edited
    merged = json.loads(json.dumps(working))
    by_key = {c["key"]: c for c in merged["columns"]}
    for col in colschema.columns(edited):
        w = by_key.get(col["key"])
        if w is None:
            merged["columns"].append(col)
        elif w["type"] == "enum" and col["type"] == "enum":
            w["enum_values"] = list(dict.fromkeys((w.get("enum_values") or []) + (col.get("enum_values") or [])))
    return merged


def build_items(conn: sqlite3.Connection, doc_id: int, schema: dict, rows: list[dict]) -> list[dict]:
    """画面から受け取った行（{"data": {列キー: 値}}）を検証し、保存用の項目にする。

    ID の空欄・重複はエラー。型に合わない値・参照先に無い ID は、取り込みと同じく警告のセルとして保存する。
    """
    cols = colschema.columns(schema)
    idc = colschema.id_column(schema)
    ref_ids: dict[int, set[str]] = {}
    for col in cols:
        ref = col.get("ref_document_id")
        if ref is not None and ref not in ref_ids:
            ref_ids[ref] = set(ver_svc.latest_hashes(conn, ref))

    errors: list[str] = []
    seen: set[str] = set()
    items: list[dict] = []
    for n, row in enumerate(rows, start=1):
        raw: dict[str, Any] = row.get("data") or {}
        data: dict[str, Any] = {}
        invalid: list[str] = []
        for col in cols:
            value, bad = colschema.normalize_edited(col, raw.get(col["key"]))
            if value is None:
                continue
            data[col["key"]] = value
            ref = col.get("ref_document_id")
            if bad or (ref is not None and ref_ids.get(ref) and any(r not in ref_ids[ref] for r in colschema.ref_values(value))):
                invalid.append(col["key"])
        item_id = data.get(idc["key"])
        if item_id is None:
            errors.append(f"{n} 行目: ID が空です")
            continue
        item_id = str(item_id)
        if item_id in seen:
            errors.append(f"{n} 行目: ID「{item_id}」が重複しています")
            continue
        seen.add(item_id)
        items.append({"item_id": item_id, "data": data, "invalid": invalid})
    if errors:
        more = f"\n（ほか {len(errors) - MAX_ERRORS_SHOWN} 件）" if len(errors) > MAX_ERRORS_SHOWN else ""
        raise AppError("保存できません:\n" + "\n".join(errors[:MAX_ERRORS_SHOWN]) + more, code="edit_errors")
    if not items:
        raise AppError("項目が 1 つもありません")
    return items


def collect_renames(base_items: list[dict], rows: list[dict], id_key: str) -> dict[str, str]:
    """各行の orig_id（編集を始めたときの ID）と今の ID から、付け直す ID の対応 {古い ID: 新しい ID} を作る。"""
    base_ids = {i["item_id"] for i in base_items}
    renames: dict[str, str] = {}
    errors: list[str] = []
    used: set[str] = set()
    for n, row in enumerate(rows, start=1):
        orig = row.get("orig_id")
        if orig is None:
            continue
        if orig not in base_ids or orig in used:
            errors.append(f"{n} 行目: 元の ID「{orig}」が正しくありません")
            continue
        used.add(orig)
        new = str((row.get("data") or {}).get(id_key) or "").strip()
        if not new or new == orig:
            continue
        if new in base_ids:
            # 入れ替えや、削除した項目の ID の再利用は、リンクの付け直しを取り違えるため受け付けない
            errors.append(f"{n} 行目: ID「{orig}」を「{new}」に変えられません（編集前に別の項目で使われている ID です）")
            continue
        renames[orig] = new
    if errors:
        raise AppError("保存できません:\n" + "\n".join(errors[:MAX_ERRORS_SHOWN]), code="edit_errors")
    return renames


def rename_impact(conn: sqlite3.Connection, doc_id: int, renames: dict[str, str]) -> dict:
    """ID を付け直すと変わるもの（保存前の確認用）。"""
    doc_svc.get_document(conn, doc_id)
    return renaming.impact(conn, doc_id, renames)


def save(
    conn: sqlite3.Connection, doc_id: int, base_version_id: int, mode: str, schema: dict, rows: list[dict], label: str = ""
) -> dict:
    """編集結果を保存し、{"version_id", "version_no", "mode"} を返す。conn はトランザクション内で渡すこと。"""
    if mode not in MODES:
        raise AppError("保存のしかた（mode）は new か overwrite を指定してください")
    doc = doc_svc.get_document(conn, doc_id)
    latest = ver_svc.latest_version(conn, doc_id)
    if latest is None or latest["id"] != base_version_id:
        raise AppError(
            "編集を始めた後に、この文書の版が変わりました（取り込み・版の削除など）。編集を取り消して、最新版から編集し直してください",
            code="version_conflict",
        )
    schema = doc_svc.check_schema(conn, doc_id, schema)
    for col in colschema.columns(schema):
        ref = col.get("ref_document_id")
        if ref is not None and rel_svc.relation_between(conn, doc_id, ref) is None:
            raise AppError(f"参照 ID 列「{col['name']}」の参照先との間にトレース関係がありません")
    items = build_items(conn, doc_id, schema, rows)
    base_items = ver_svc.load_items(conn, latest["id"])
    idc = colschema.id_column(schema)
    renames = collect_renames(base_items, rows, idc["key"])
    # ID だけを変えた場合のハッシュ（リンクの確認ハッシュを付け替え、ID の変更だけで要確認にしないため）
    base_by_id = {i["item_id"]: i for i in base_items}
    acks = {
        new: (base_by_id[old]["hash"], colschema.content_hash({**base_by_id[old]["data"], idc["key"]: new}))
        for old, new in renames.items()
    }

    settings = {"format": "edit", "base_version_no": latest["version_no"], "edited_at": now_iso()}
    if mode == "new":
        version_id = ver_svc.create_version(conn, doc_id, label, "（画面で編集）", settings, schema, items)
    else:
        version_id = latest["id"]
        # 元の取り込みの設定は残し、編集した日時を足す
        settings = {**latest["import_settings"], "edited_at": settings["edited_at"]}
        ver_svc.replace_items(conn, version_id, schema, items, settings)
        if label:
            conn.execute("UPDATE versions SET label = ? WHERE id = ?", (label, version_id))
    merged = _merge_working_schema(doc["schema"], schema)
    conn.execute("UPDATE documents SET schema_json = ? WHERE id = ?", (json.dumps(merged, ensure_ascii=False), doc_id))
    referring: list[int] = []
    if renames:
        renaming.rename_links(conn, doc_id, renames, acks)
        referring = renaming.rename_references(conn, doc_id, renames)
    link_svc.regenerate_auto_links(conn, doc_id)
    for other in referring:
        link_svc.regenerate_auto_links(conn, other)
    version_no = conn.execute("SELECT version_no FROM versions WHERE id = ?", (version_id,)).fetchone()[0]
    return {"version_id": version_id, "version_no": version_no, "mode": mode, "renamed": len(renames)}

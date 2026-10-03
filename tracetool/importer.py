"""取り込みセッション: アップロード → 読み込み設定 → 列の対応付けと検証 → 確定。

アップロードされたファイルはメモリ上にのみ保持し、ディスクには書かない（F-18）。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from . import colschema, readers
from .db import now_iso
from .errors import AppError, NotFound
from .services import documents as doc_svc
from .services import links as link_svc
from .services import relations as rel_svc
from .services import versions as ver_svc

SESSION_TTL_SEC = 30 * 60
PREVIEW_ROWS = 30
MAX_MESSAGES = 1000


@dataclass
class ImportSession:
    id: str
    document_id: int
    filename: str
    fmt: str
    data: bytes
    encoding: str | None = None
    header_row: int = 1
    sheets: list[str] = field(default_factory=list)
    table: readers.Table | None = None
    last_access: float = field(default_factory=time.monotonic)
    _workbook: Any = None
    _text: str | None = None

    def workbook(self):
        if self._workbook is None:
            self._workbook = readers.open_workbook(self.data)
        return self._workbook

    def text(self, encoding: str | None) -> str:
        if self._text is None or encoding != self.encoding:
            self._text, self.encoding = readers.decode_text(self.data, encoding)
        return self._text

    def raw_grid(self, sheet: str | None) -> list[list[str]]:
        if self.fmt == "xlsx":
            return readers.read_sheet(self.workbook(), sheet or self.workbook().sheetnames[0])
        delimiter = "\t" if self.fmt == "tsv" else ","
        return readers.read_delimited(self.text(self.encoding), delimiter)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ImportSession] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [s for s, v in self._sessions.items() if now - v.last_access > SESSION_TTL_SEC]:
            del self._sessions[sid]

    def add(self, session: ImportSession) -> None:
        with self._lock:
            self._expire()
            self._sessions[session.id] = session

    def get(self, sid: str) -> ImportSession:
        with self._lock:
            self._expire()
            s = self._sessions.get(sid)
            if s is None:
                raise NotFound("取り込みセッションが見つかりません（30 分操作が無いと破棄されます）。最初からやり直してください")
            s.last_access = time.monotonic()
            return s

    def remove(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)


# --- ステップ 1: アップロード ---------------------------------------------------


def start(conn: sqlite3.Connection, store: SessionStore, doc_id: int, filename: str, data: bytes) -> dict:
    doc_svc.get_document(conn, doc_id)
    fmt = readers.detect_format(filename)
    session = ImportSession(id=secrets.token_urlsafe(16), document_id=doc_id, filename=filename, fmt=fmt, data=data)
    sheets: list[str] = []
    if fmt == "xlsx":
        sheets = list(session.workbook().sheetnames)
        session.sheets = sheets[:1]
    else:
        session.text(None)  # 文字コードを自動判定しておく
    store.add(session)
    return {
        "session_id": session.id,
        "filename": filename,
        "format": fmt,
        "encoding": session.encoding,
        "sheets": sheets,
        "preview": session.raw_grid(session.sheets[0] if sheets else None)[:PREVIEW_ROWS],
    }


# --- ステップ 2: 読み込み設定 ---------------------------------------------------


def apply_settings(
    conn: sqlite3.Connection, session: ImportSession, encoding: str | None, header_row: int, sheets: list[str]
) -> dict:
    session.header_row = header_row
    if session.fmt == "xlsx":
        if not sheets:
            raise AppError("シートを 1 つ以上選択してください")
        session.sheets = sheets
        tables = [(s, readers.build_table(session.raw_grid(s), header_row, s)) for s in sheets]
        session.table = readers.merge_tables(tables)
        preview = session.raw_grid(sheets[0])[:PREVIEW_ROWS]
    else:
        session.text(encoding or None)
        grid = session.raw_grid(None)
        session.table = readers.build_table(grid, header_row)
        preview = grid[:PREVIEW_ROWS]

    doc = doc_svc.get_document(conn, session.document_id)
    schema = propose_schema(doc["schema"], session.table.headers)
    used = {c.get("source_header") for c in schema["columns"]}
    return {
        "encoding": session.encoding,
        "headers": session.table.headers,
        "row_count": len(session.table.rows),
        "preview": preview,
        "schema": schema,
        "unmapped_headers": [h for h in session.table.headers if h not in used],
    }


def propose_schema(schema: dict, headers: list[str]) -> dict:
    """作業中のカラム定義をもとに、ファイルのヘッダとの対応付け案を作る。"""
    schema = json.loads(json.dumps(schema))  # 複製
    cols = colschema.columns(schema)
    if not cols:
        # 初回でカラム定義が無い場合は、全ヘッダを string 列として提案し、先頭を ID 列にする
        schema["columns"] = [
            {"key": colschema.new_key(), "name": h, "source_header": h, "type": "id" if i == 0 else "string"}
            for i, h in enumerate(headers)
        ]
        return colschema.normalize_schema(schema)
    used: set[str] = set()
    for col in cols:
        if col.get("source_header") in headers and col["source_header"] not in used:
            used.add(col["source_header"])
    for col in cols:
        if col.get("source_header") in used and col.get("source_header") in headers:
            continue
        if col["name"] in headers and col["name"] not in used:
            col["source_header"] = col["name"]
            used.add(col["name"])
    return schema


# --- ステップ 3: 検証 -----------------------------------------------------------


@dataclass
class BuildResult:
    schema: dict
    items: list[dict]
    errors: list[dict]
    warnings: list[dict]
    error_count: int = 0
    warning_count: int = 0


class _Messages:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.count = 0

    def add(self, message: str, row: str = "", column: str = "") -> None:
        self.count += 1
        if len(self.items) < MAX_MESSAGES:
            self.items.append({"row": row, "column": column, "message": message})


_TYPE_WARNINGS = {
    "int": "整数に変換できません",
    "bool": "真・偽のどちらにも該当しません",
    "enum": "選択肢に無い値です",
}


def build(conn: sqlite3.Connection, session: ImportSession, schema: dict) -> BuildResult:
    if session.table is None:
        raise AppError("読み込み設定が済んでいません")
    errors, warnings = _Messages(), _Messages()
    schema = colschema.normalize_schema(schema)
    for msg in colschema.validate_schema(schema):
        errors.add(msg)
    cols = colschema.columns(schema)
    idc = colschema.id_column(schema)
    header_index = {h: i for i, h in enumerate(session.table.headers)}

    col_index: dict[str, int | None] = {}
    for col in cols:
        src = col.get("source_header")
        col_index[col["key"]] = header_index.get(src) if src else None
        if col_index[col["key"]] is None:
            if col is idc:
                errors.add("ID 列がファイルのどの列にも対応付けられていません", column=col["name"])
            else:
                warnings.add("ファイルに対応する列が無いため、値なしで取り込みます", column=col["name"])

    ref_ids: dict[int, set[str]] = {}
    for col in cols:
        ref = col.get("ref_document_id")
        if ref is None or ref in ref_ids:
            continue
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (ref,)).fetchone() is None:
            errors.add("参照先の文書がありません", column=col["name"])
            ref_ids[ref] = set()
            continue
        if rel_svc.relation_between(conn, session.document_id, ref) is None:
            ref_name = doc_svc.get_document(conn, ref)["name"]
            errors.add(f"参照先文書「{ref_name}」との間にトレース関係がありません。先に関係を登録してください", column=col["name"])
        hashes = ver_svc.latest_hashes(conn, ref)
        if not hashes:
            warnings.add("参照先文書がまだ取り込まれていないため、参照先の存在は確認できません", column=col["name"])
        ref_ids[ref] = set(hashes)

    if errors.count:
        return BuildResult(schema, [], errors.items, warnings.items, errors.count, warnings.count)

    items: list[dict] = []
    seen: dict[str, str] = {}
    multi_sheet = len(session.sheets) > 1
    for sheet, row_no, values in session.table.rows:
        loc = f"{sheet} {row_no}行目" if multi_sheet else f"{row_no}行目"
        data: dict[str, Any] = {}
        invalid: list[str] = []
        for col in cols:
            idx = col_index[col["key"]]
            raw = values[idx] if idx is not None else ""
            value, bad = colschema.normalize_cell(col, raw)
            if value is None:
                continue
            data[col["key"]] = value
            if bad:
                invalid.append(col["key"])
                warnings.add(f"{_TYPE_WARNINGS[col['type']]}: {raw.strip()}", row=loc, column=col["name"])
            ref = col.get("ref_document_id")
            if ref is not None and ref_ids.get(ref):
                missing = [r for r in colschema.ref_values(value) if r not in ref_ids[ref]]
                if missing:
                    warnings.add(f"参照先に存在しない ID: {', '.join(missing)}", row=loc, column=col["name"])
        item_id = data.get(idc["key"])
        if item_id is None:
            errors.add("ID が空です", row=loc, column=idc["name"])
            continue
        item_id = str(item_id)
        if item_id in seen:
            errors.add(f"ID「{item_id}」が重複しています（{seen[item_id]}と同じ）", row=loc, column=idc["name"])
            continue
        seen[item_id] = loc
        items.append({"item_id": item_id, "data": data, "invalid": invalid})
    return BuildResult(schema, items, errors.items, warnings.items, errors.count, warnings.count)


def validate(conn: sqlite3.Connection, session: ImportSession, schema: dict) -> dict:
    result = build(conn, session, schema)
    return {
        "schema": result.schema,
        "errors": result.errors,
        "warnings": result.warnings,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "item_count": len(result.items),
        "preview": result.items[:20],
    }


# --- ステップ 4: 確定 -----------------------------------------------------------


def commit(conn: sqlite3.Connection, session: ImportSession, schema: dict, label: str) -> int:
    """新しい版を作る。conn はトランザクション内で渡すこと。"""
    result = build(conn, session, schema)
    if result.error_count:
        raise AppError(f"エラーが {result.error_count} 件あるため取り込めません", code="import_errors")
    if not result.items:
        raise AppError("取り込む行がありません")
    doc_id = session.document_id
    version_no = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM versions WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    # 削除済みの版の番号も再利用しないよう、過去最大値を meta に残す
    key = f"max_version_no:{doc_id}"
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is not None:
        version_no = max(version_no, int(row["value"]) + 1)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(version_no)))

    settings = {
        "format": session.fmt,
        "encoding": session.encoding,
        "header_row": session.header_row,
        "sheets": session.sheets,
    }
    schema_json = json.dumps(result.schema, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO versions(document_id, version_no, label, source_filename, import_settings, schema_json, "
        "row_count, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, version_no, label or "", session.filename, json.dumps(settings, ensure_ascii=False),
         schema_json, len(result.items), now_iso()),
    )
    version_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO items(version_id, item_id, row_no, data_json, invalid_json, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                version_id,
                it["item_id"],
                n,
                json.dumps(it["data"], ensure_ascii=False),
                json.dumps(it["invalid"]),
                colschema.content_hash(it["data"]),
            )
            for n, it in enumerate(result.items, start=1)
        ],
    )
    conn.execute("UPDATE documents SET schema_json = ? WHERE id = ?", (schema_json, doc_id))
    link_svc.regenerate_auto_links(conn, doc_id)
    return version_id

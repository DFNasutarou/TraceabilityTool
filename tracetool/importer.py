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
from .errors import AppError, NotFound
from .services import documents as doc_svc
from .services import links as link_svc
from .services import relations as rel_svc
from .services import versions as ver_svc

SESSION_TTL_SEC = 30 * 60
PREVIEW_ROWS = 30
PREVIEW_TAIL_ROWS = 20  # データの終了行を指定できるよう、末尾の行もプレビューに含める
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
    data_start: int | None = None
    data_end: int | None = None
    stop_at_blank: bool = False
    sheets: list[str] = field(default_factory=list)
    table: readers.Table | None = None
    last_access: float = field(default_factory=time.monotonic)
    _workbook: Any = None
    _text: str | None = None
    _grids: dict = field(default_factory=dict)  # 読み込んだ表のキャッシュ（シートや文字コードごと）

    def workbook(self):
        if self._workbook is None:
            self._workbook = readers.open_workbook(self.data)
        return self._workbook

    def text(self, encoding: str | None) -> str:
        if self._text is None or (encoding is not None and encoding != self.encoding):
            self._text, self.encoding = readers.decode_text(self.data, encoding)
        return self._text

    def raw_grid(self, sheet: str | None) -> list[list[str]]:
        if self.fmt == "xlsx":
            key = ("xlsx", sheet or self.workbook().sheetnames[0])
            if key not in self._grids:
                self._grids[key] = readers.read_sheet(self.workbook(), key[1])
            return self._grids[key]
        text = self.text(None)
        key = ("text", self.encoding)
        if key not in self._grids:
            delimiter = "\t" if self.fmt == "tsv" else ","
            self._grids[key] = readers.read_delimited(text, delimiter)
        return self._grids[key]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ImportSession] = {}
        self._lock = threading.Lock()

    def start_reaper(self, interval_sec: float = 60.0) -> None:
        """一定間隔で期限切れのセッションを破棄する（画面を閉じた場合もメモリに残し続けない）。"""

        def loop():
            while True:
                time.sleep(interval_sec)
                with self._lock:
                    self._expire()

        threading.Thread(target=loop, name="import-session-reaper", daemon=True).start()

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
    return _start(store, doc_id, filename, readers.detect_format(filename), data)


def start_text(conn: sqlite3.Connection, store: SessionStore, doc_id: int, text: str, fmt: str = "auto") -> dict:
    """貼り付けたテキスト（CSV / TSV）から取り込みを始める。

    fmt が auto の場合、1 行目にタブがあれば TSV、無ければ CSV とみなす
    （Excel からコピーした表はタブ区切りになる）。
    """
    doc_svc.get_document(conn, doc_id)
    if not text.strip():
        raise AppError("貼り付けたテキストが空です")
    if fmt == "auto":
        fmt = "tsv" if "\t" in text.split("\n", 1)[0] else "csv"
    if fmt not in ("csv", "tsv"):
        raise AppError("形式は csv か tsv を指定してください")
    # 画面では「貼り付けたテキスト（TSV）」のように形式を添えて表示する
    return _start(store, doc_id, "貼り付けたテキスト", fmt, text.encode("utf-8"))


def _start(store: SessionStore, doc_id: int, filename: str, fmt: str, data: bytes) -> dict:
    session = ImportSession(id=secrets.token_urlsafe(16), document_id=doc_id, filename=filename, fmt=fmt, data=data)
    sheets: list[str] = []
    if fmt == "xlsx":
        sheets = list(session.workbook().sheetnames)
        session.sheets = sheets[:1]
    else:
        session.text(None)  # 文字コードを自動判定しておく
    store.add(session)
    first = session.sheets[0] if sheets else None
    return {
        "session_id": session.id,
        "filename": filename,
        "format": fmt,
        "encoding": session.encoding,
        "sheets": sheets,
        "preview": session.raw_grid(first)[:PREVIEW_ROWS],
        "suggested_header_row": readers.suggest_header_row(session.raw_grid(first)),
        "sheet_preview": preview(session, first),
    }


def _set_encoding(session: ImportSession, encoding: str | None) -> None:
    if encoding:
        session.text(encoding)
    else:
        session._text = None  # 自動判定に戻す
        session.text(None)


def preview(session: ImportSession, sheet: str | None, encoding: str | None = None) -> dict:
    """読み込み設定の画面に出す、元の表のプレビュー（先頭と末尾の行。行番号付き）。

    取り込むシートの選択や見出しの設定に誤りがあっても表示できるよう、表の組み立てとは切り離す。
    """
    if session.fmt == "xlsx":
        names = session.workbook().sheetnames
        sheet = sheet if sheet in names else names[0]
    else:
        sheet = None
        _set_encoding(session, encoding)
    grid = session.raw_grid(sheet)
    numbered = list(enumerate(grid, start=1))
    if len(numbered) > PREVIEW_ROWS + PREVIEW_TAIL_ROWS:
        numbered = numbered[:PREVIEW_ROWS] + numbered[-PREVIEW_TAIL_ROWS:]
    return {
        "sheet": sheet,
        "encoding": session.encoding,
        "rows": [{"no": n, "cells": cells} for n, cells in numbered],
        "total": len(grid),
        "suggested_header_row": readers.suggest_header_row(grid),
    }


# --- ステップ 2: 読み込み設定 ---------------------------------------------------


def apply_settings(
    conn: sqlite3.Connection,
    session: ImportSession,
    encoding: str | None,
    header_row: int,
    sheets: list[str],
    data_start: int | None = None,
    data_end: int | None = None,
    stop_at_blank: bool = False,
) -> dict:
    session.header_row = header_row
    session.data_start, session.data_end, session.stop_at_blank = data_start, data_end, stop_at_blank
    rng = {"data_start": data_start, "data_end": data_end, "stop_at_blank": stop_at_blank}
    if session.fmt == "xlsx":
        if not sheets:
            raise AppError("シートを 1 つ以上選択してください")
        session.sheets = sheets
        tables = [(s, readers.build_table(session.raw_grid(s), header_row, s, **rng)) for s in sheets]
        session.table = readers.merge_tables(tables)
        preview = session.raw_grid(sheets[0])[:PREVIEW_ROWS]
    else:
        _set_encoding(session, encoding)
        grid = session.raw_grid(None)
        session.table = readers.build_table(grid, header_row, **rng)
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


def distinct_values(session: ImportSession, column: dict) -> dict:
    """取り込み中のファイルで、列に使われている値の一覧（enum の選択肢を作るため）。"""
    if session.table is None:
        raise AppError("読み込み設定が済んでいません")
    src = column.get("source_header")
    if src not in session.table.headers:
        raise AppError("この列はファイルのどの列にも対応付けられていません")
    idx = session.table.headers.index(src)
    delims = (column.get("list") or {}).get("delimiters") if column.get("list") else None
    values = colschema.distinct_texts((row[idx] for _, _, row in session.table.rows), delims)
    return _limit_values(values)


def _limit_values(values: list[str]) -> dict:
    if len(values) > colschema.MAX_ENUM_VALUES:
        raise AppError(
            f"使われている値が {len(values)} 種類あり、enum にするには多すぎます（上限 {colschema.MAX_ENUM_VALUES} 種類）"
        )
    return {"values": values}


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
        if col is idc and col.get("auto_id"):
            col_index[col["key"]] = None  # ファイルの列は使わず、行の順に番号を振る
            continue
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
            errors.add(
                f"参照先文書「{ref_name}」との間にトレース関係がありません。"
                "上の列の設定に表示される「関係を登録」ボタン、または文書一覧の下部「トレース関係」で登録してください",
                column=col["name"],
            )
        hashes = ver_svc.latest_hashes(conn, ref)
        if not hashes:
            warnings.add("参照先文書がまだ取り込まれていないため、参照先の存在は確認できません", column=col["name"])
        ref_ids[ref] = set(hashes)

    if errors.count:
        return BuildResult(schema, [], errors.items, warnings.items, errors.count, warnings.count)

    items: list[dict] = []
    seen: dict[str, str] = {}
    multi_sheet = len(session.sheets) > 1
    auto_id = idc.get("auto_id")
    for n, (sheet, row_no, values) in enumerate(session.table.rows):
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
                    if col["key"] not in invalid:
                        invalid.append(col["key"])
                    warnings.add(f"参照先に存在しない ID: {', '.join(missing)}", row=loc, column=col["name"])
        if auto_id:
            data[idc["key"]] = colschema.format_auto_id(auto_id, n)
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
    settings = {
        "format": session.fmt,
        "encoding": session.encoding,
        "header_row": session.header_row,
        "data_start": session.data_start,
        "data_end": session.data_end,
        "stop_at_blank": session.stop_at_blank,
        "sheets": session.sheets,
    }
    version_id = ver_svc.create_version(conn, doc_id, label, session.filename, settings, result.schema, result.items)
    conn.execute(
        "UPDATE documents SET schema_json = ? WHERE id = ?", (json.dumps(result.schema, ensure_ascii=False), doc_id)
    )
    link_svc.regenerate_auto_links(conn, doc_id)
    return version_id

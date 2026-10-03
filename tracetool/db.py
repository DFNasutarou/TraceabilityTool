"""SQLite への接続とスキーマ管理。

個人利用のローカルツールなので、接続は 1 本を共有し、ロックで直列化する。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  schema_json TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
  id              INTEGER PRIMARY KEY,
  document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no      INTEGER NOT NULL,
  label           TEXT NOT NULL DEFAULT '',
  source_filename TEXT NOT NULL,
  import_settings TEXT NOT NULL,
  schema_json     TEXT NOT NULL,
  row_count       INTEGER NOT NULL,
  imported_at     TEXT NOT NULL,
  UNIQUE (document_id, version_no)
);

CREATE TABLE IF NOT EXISTS items (
  version_id   INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
  item_id      TEXT NOT NULL,
  row_no       INTEGER NOT NULL,
  data_json    TEXT NOT NULL,
  invalid_json TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  PRIMARY KEY (version_id, item_id)
);

CREATE TABLE IF NOT EXISTS relations (
  id           INTEGER PRIMARY KEY,
  upper_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  lower_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  UNIQUE (upper_doc_id, lower_doc_id),
  CHECK (upper_doc_id <> lower_doc_id)
);

CREATE TABLE IF NOT EXISTS links (
  id             INTEGER PRIMARY KEY,
  relation_id    INTEGER NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
  upper_item_id  TEXT NOT NULL,
  lower_item_id  TEXT NOT NULL,
  manual         INTEGER NOT NULL DEFAULT 0,
  auto_by_upper  INTEGER NOT NULL DEFAULT 0,
  auto_by_lower  INTEGER NOT NULL DEFAULT 0,
  auto_disabled  INTEGER NOT NULL DEFAULT 0,
  upper_hash_ack TEXT,
  lower_hash_ack TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (relation_id, upper_item_id, lower_item_id)
);

CREATE INDEX IF NOT EXISTS idx_links_upper ON links(relation_id, upper_item_id);
CREATE INDEX IF NOT EXISTS idx_links_lower ON links(relation_id, lower_item_id);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        # executescript は暗黙に COMMIT するため、トランザクションの外で実行する
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """書き込み用のトランザクション。例外が起きたらロールバックする。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """読み取り用。ロックだけ取る。"""
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()

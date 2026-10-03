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

SCHEMA_VERSION = 2

# ID は AUTOINCREMENT にして、削除した文書・版などの ID を再利用しない
# （再利用すると、残っている参照が無関係の新しい行を指してしまうため）
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  schema_json TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  upper_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  lower_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  UNIQUE (upper_doc_id, lower_doc_id),
  CHECK (upper_doc_id <> lower_doc_id)
);

CREATE TABLE IF NOT EXISTS links (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
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

# 版 1 → 2: ID 列を AUTOINCREMENT にするため、表を作り直す
_REBUILD_TABLES = ("documents", "versions", "items", "relations", "links")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CachingConnection(sqlite3.Connection):
    """読み込み結果のキャッシュを持つ接続。

    cache["items"] / cache["hashes"]: 版 ID → 項目 / ハッシュ（版は不変なので、版の削除時のみ破棄）
    cache["eval"]: トレース評価の結果（書き込みのたびに破棄）
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache: dict[str, dict] = {"items": {}, "hashes": {}, "eval": {}}

    def clear_cache(self, all_: bool = True) -> None:
        if all_:
            self.cache["items"].clear()
            self.cache["hashes"].clear()
        self.cache["eval"].clear()


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn: CachingConnection = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None, factory=CachingConnection
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _schema_version(self) -> int | None:
        exists = self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if not exists:
            return None
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(row[0]) if row else None

    def _init_schema(self) -> None:
        with self._lock:
            current = self._schema_version()
            if current is not None and current < 2:
                self._migrate_v1_to_v2()
            # executescript は暗黙に COMMIT するため、トランザクションの外で実行する
            self._conn.executescript(SCHEMA_SQL)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def _migrate_v1_to_v2(self) -> None:
        conn = self._conn
        conn.execute("PRAGMA foreign_keys = OFF")
        # 名前を変えた表を参照する外部キーを書き換えさせない
        conn.execute("PRAGMA legacy_alter_table = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DROP INDEX IF EXISTS idx_links_upper")
            conn.execute("DROP INDEX IF EXISTS idx_links_lower")
            for t in _REBUILD_TABLES:
                conn.execute(f"ALTER TABLE {t} RENAME TO {t}_v1")
            for stmt in SCHEMA_SQL.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for t in _REBUILD_TABLES:
                conn.execute(f"INSERT INTO {t} SELECT * FROM {t}_v1")
            for t in reversed(_REBUILD_TABLES):
                conn.execute(f"DROP TABLE {t}_v1")
            conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA legacy_alter_table = OFF")
            conn.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def tx(self) -> Iterator[CachingConnection]:
        """書き込み用のトランザクション。例外が起きたらロールバックする。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.clear_cache(all_=False)
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                # ロールバックで消えた版の項目がキャッシュに残らないようにする
                self._conn.clear_cache(all_=True)
                raise
            else:
                self._conn.execute("COMMIT")
                self._conn.clear_cache(all_=False)

    @contextmanager
    def read(self) -> Iterator[CachingConnection]:
        """読み取り用。ロックだけ取る。"""
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()

"""画像のパスの列: 基準フォルダの下にある画像ファイルを画面に表示する。

開けるのは、文書の作業中のカラム定義で画像の列に指定した基準フォルダの下にある、画像の拡張子のファイルだけ。
基準フォルダの外（.. や絶対パスでの指定、リンクをたどった先を含む）は開かない。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import colschema
from .errors import AppError, NotFound
from .services import documents as doc_svc


def resolve(conn: sqlite3.Connection, doc_id: int, key: str, value: str) -> Path:
    col = next((c for c in colschema.columns(doc_svc.get_document(conn, doc_id)["schema"]) if c["key"] == key), None)
    if col is None or not col.get("image") or not col["image"].get("base_dir"):
        raise AppError("この列は画像の列ではありません")
    base = Path(col["image"]["base_dir"])
    if not base.is_dir():
        raise NotFound(f"基準フォルダがありません: {base}")
    value = (value or "").strip().replace("\\", "/")
    if not value:
        raise AppError("画像のパスが空です")
    try:
        file = (base / value).resolve(strict=True)
    except (OSError, RuntimeError):
        raise NotFound(f"画像ファイルがありません: {value}") from None
    if not file.is_relative_to(base.resolve()):
        raise AppError("基準フォルダの外のファイルは表示できません")
    if file.suffix.lower() not in colschema.IMAGE_EXTENSIONS or not file.is_file():
        raise AppError("画像ファイル（" + " / ".join(colschema.IMAGE_EXTENSIONS) + "）ではありません")
    return file

"""カラム定義の検証、セル値の正規化、内容ハッシュの計算。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from typing import Any

COLUMN_TYPES = ("id", "int", "string", "enum", "bool")

DEFAULT_BOOL_TRUE = ["○", "◯", "〇", "Yes", "Y", "TRUE", "1", "有", "あり"]
DEFAULT_BOOL_FALSE = ["×", "✕", "✖", "No", "N", "FALSE", "0", "無", "なし"]

_INT_RE = re.compile(r"^[+-]?\d+(\.0+)?$")


def new_key() -> str:
    return "c" + secrets.token_hex(4)


def empty_schema() -> dict:
    return {"columns": [], "display_column": None}


def columns(schema: dict) -> list[dict]:
    return schema.get("columns", [])


def id_column(schema: dict) -> dict | None:
    for col in columns(schema):
        if col.get("type") == "id":
            return col
    return None


def display_column_key(schema: dict) -> str | None:
    """ID と一緒に表示する列のキー。未指定なら ID 列の次の列。"""
    keys = [c["key"] for c in columns(schema)]
    key = schema.get("display_column")
    if key in keys:
        return key
    idc = id_column(schema)
    for col in columns(schema):
        if col is not idc and col.get("type") != "id":
            return col["key"]
    return None


def normalize_schema(schema: dict) -> dict:
    """画面から受け取ったカラム定義を保存用の形にそろえる。"""
    out_cols = []
    for raw in schema.get("columns", []):
        col = {
            "key": raw.get("key") or new_key(),
            "name": str(raw.get("name", "")).strip(),
            "source_header": (str(raw["source_header"]).strip() if raw.get("source_header") else None),
            "type": raw.get("type", "string"),
            "list": None,
            "enum_values": None,
            "bool_values": None,
            "ref_document_id": None,
        }
        lst = raw.get("list")
        if lst and lst.get("delimiters"):
            col["list"] = {"delimiters": [d for d in lst["delimiters"] if d != ""]}
        if col["type"] == "enum":
            col["enum_values"] = [str(v).strip() for v in (raw.get("enum_values") or []) if str(v).strip()]
        if col["type"] == "bool":
            bv = raw.get("bool_values") or {}
            col["bool_values"] = {
                "true": [str(v).strip() for v in bv.get("true", DEFAULT_BOOL_TRUE) if str(v).strip()],
                "false": [str(v).strip() for v in bv.get("false", DEFAULT_BOOL_FALSE) if str(v).strip()],
            }
        if col["type"] == "string" and raw.get("ref_document_id"):
            col["ref_document_id"] = int(raw["ref_document_id"])
        out_cols.append(col)
    return {"columns": out_cols, "display_column": schema.get("display_column")}


def validate_schema(schema: dict) -> list[str]:
    """カラム定義の誤りを日本語のメッセージで返す。空なら正常。"""
    errors: list[str] = []
    cols = columns(schema)
    if not cols:
        errors.append("列が 1 つも定義されていません")
        return errors
    id_cols = [c for c in cols if c["type"] == "id"]
    if len(id_cols) != 1:
        errors.append(f"ID 型の列はちょうど 1 つ必要です（現在 {len(id_cols)} 個）")
    names: set[str] = set()
    keys: set[str] = set()
    for col in cols:
        label = col["name"] or "(名前なし)"
        if not col["name"]:
            errors.append("名前が空の列があります")
        elif col["name"] in names:
            errors.append(f"列名「{col['name']}」が重複しています")
        names.add(col["name"])
        if col["key"] in keys:
            errors.append(f"列キー「{col['key']}」が重複しています")
        keys.add(col["key"])
        if col["type"] not in COLUMN_TYPES:
            errors.append(f"列「{label}」の型「{col['type']}」は不正です")
        if col["type"] == "id" and col.get("list"):
            errors.append(f"ID 列「{label}」はリスト形式にできません")
        if col["type"] == "enum" and not col.get("enum_values"):
            errors.append(f"enum 列「{label}」に選択肢がありません")
        if col["type"] == "bool":
            bv = col.get("bool_values") or {}
            t = {_fold(v) for v in bv.get("true", [])}
            f = {_fold(v) for v in bv.get("false", [])}
            if not t or not f:
                errors.append(f"bool 列「{label}」に真・偽の文字列を 1 つ以上指定してください")
            elif t & f:
                errors.append(f"bool 列「{label}」で真と偽に同じ文字列があります")
        if col.get("ref_document_id") and col["type"] != "string":
            errors.append(f"参照 ID 列「{label}」は string 型にしてください")
    return errors


def split_list(text: str, delimiters: list[str]) -> list[str]:
    parts = [text]
    for d in delimiters:
        d = {"\\n": "\n", "\\t": "\t"}.get(d, d)
        next_parts: list[str] = []
        for p in parts:
            next_parts.extend(p.split(d))
        parts = next_parts
    return [p.strip() for p in parts if p.strip()]


def _fold(text: str) -> str:
    """全角・半角と英字の大文字小文字を区別しない比較用の形にする。"""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _convert_scalar(col: dict, text: str) -> tuple[Any, bool]:
    """1 つの値を型に合わせて変換する。戻り値は (値, 警告か)。"""
    t = col["type"]
    if t == "int":
        s = unicodedata.normalize("NFKC", text).replace(",", "").strip()
        if _INT_RE.match(s):
            # float を経由すると 2^53 を超える値で精度が落ちるため、小数部（すべて 0）を切り落とす
            return int(s.split(".")[0]), False
        return text, True
    if t == "bool":
        bv = col.get("bool_values") or {}
        key = _fold(text)
        if key in {_fold(v) for v in bv.get("true", [])}:
            return True, False
        if key in {_fold(v) for v in bv.get("false", [])}:
            return False, False
        return text, True
    if t == "enum":
        return text, text not in (col.get("enum_values") or [])
    return text, False


def normalize_cell(col: dict, raw: str | None) -> tuple[Any, bool]:
    """セルの文字列を保存用の値に変換する。戻り値は (値, 警告か)。"""
    text = (raw or "").strip()
    if text == "":
        return None, False
    if col.get("list") and col["type"] != "id":
        values = []
        invalid = False
        for part in split_list(text, col["list"]["delimiters"]):
            v, bad = _convert_scalar(col, part)
            values.append(v)
            invalid = invalid or bad
        return (values or None), invalid
    return _convert_scalar(col, text)


def content_hash(data: dict) -> str:
    """全列の値からハッシュを作る。値が null の列は除く（空の列の追加でハッシュが変わらないように）。"""
    payload = {k: v for k, v in data.items() if v is not None}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_text(value: Any) -> str:
    """表示・検索用の文字列にする。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, list):
        return "; ".join(as_text(v) for v in value)
    return str(value)


def ref_values(value: Any) -> list[str]:
    """参照 ID 列の値を ID の配列にする。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]

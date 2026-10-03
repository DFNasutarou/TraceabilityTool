"""CSV / TSV / XLSX を「行ごとの文字列配列」に変換する。"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from pathlib import PurePath

from .errors import AppError

ENCODINGS = ("utf-8-sig", "utf-8", "cp932")


@dataclass
class Table:
    """ヘッダと、データ行（元ファイルの行番号付き）。"""

    headers: list[str]
    rows: list[tuple[str, int, list[str]]] = field(default_factory=list)  # (シート名, 行番号, 値)


def detect_format(filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext in (".csv", ".txt"):
        return "csv"
    if ext == ".tsv":
        return "tsv"
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext == ".xls":
        raise AppError("旧形式の Excel（.xls）には対応していません。.xlsx で保存し直してください")
    raise AppError(f"対応していないファイル形式です: {ext or '(拡張子なし)'}")


def decode_text(data: bytes, encoding: str | None) -> tuple[str, str]:
    """文字コードを指定または自動判定してデコードする。戻り値は (テキスト, 使った文字コード)。"""
    candidates = (encoding,) if encoding else ENCODINGS
    for enc in candidates:
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if enc == "utf-8" and text.startswith("﻿"):
            text = text[1:]
        return text, enc
    if encoding:
        raise AppError(f"文字コード {encoding} として読み込めませんでした")
    raise AppError("文字コードを判定できませんでした（UTF-8 / Shift_JIS 以外の可能性があります）")


def read_delimited(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [list(r) for r in reader]


def cell_to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def open_workbook(data: bytes):
    import openpyxl

    try:
        # 結合セルの情報が必要なので read_only にはしない
        return openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:  # openpyxl は壊れたファイルで様々な例外を出す
        raise AppError(f"Excel ファイルを開けませんでした: {type(exc).__name__}") from exc


def read_sheet(wb, sheet_name: str) -> list[list[str]]:
    if sheet_name not in wb.sheetnames:
        raise AppError(f"シート「{sheet_name}」がありません")
    ws = wb[sheet_name]
    grid = [[cell_to_str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    # 結合セルは範囲内の全セルに左上の値を展開する
    for rng in ws.merged_cells.ranges:
        top = grid[rng.min_row - 1][rng.min_col - 1] if rng.min_row - 1 < len(grid) else ""
        for r in range(rng.min_row - 1, rng.max_row):
            while r >= len(grid):
                grid.append([])
            row = grid[r]
            while len(row) < rng.max_col:
                row.append("")
            for c in range(rng.min_col - 1, rng.max_col):
                row[c] = top
    return grid


def build_table(grid: list[list[str]], header_row: int, sheet_name: str = "") -> Table:
    """header_row は 1 始まり。"""
    if header_row < 1:
        raise AppError("ヘッダ行は 1 以上を指定してください")
    if header_row > len(grid):
        raise AppError(f"ヘッダ行 {header_row} 行目がありません（全 {len(grid)} 行）")
    headers = [h.strip() for h in grid[header_row - 1]]
    while headers and headers[-1] == "":
        headers.pop()
    if not headers:
        raise AppError(f"ヘッダ行 {header_row} 行目が空です")
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        name = h or f"列{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}({seen[name]})"
        else:
            seen[name] = 1
        headers[i] = name
    table = Table(headers=headers)
    width = len(headers)
    for idx in range(header_row, len(grid)):
        values = (grid[idx] + [""] * width)[:width]
        if all(v.strip() == "" for v in values):
            continue
        table.rows.append((sheet_name, idx + 1, values))
    return table


def merge_tables(tables: list[tuple[str, Table]]) -> Table:
    """複数シートの表を連結する。ヘッダが一致しなければエラー。"""
    first_name, first = tables[0]
    merged = Table(headers=list(first.headers))
    for name, t in tables:
        if t.headers != first.headers:
            raise AppError(f"シート「{name}」のヘッダがシート「{first_name}」と一致しません")
        merged.rows.extend(t.rows)
    return merged

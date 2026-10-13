"""
Google Sheets export ("PMI LA Hub Data Warehouse").

Feed tables — one worksheet per table (Events, Blog, Recordings, News):
  1. read the worksheet back BY HEADER NAME (so a reordered column is harmless),
  2. merge this run's rows into it (src/catalogue.py — merge, never wipe),
  3. write the merged table back with the headers from src/schema.py.
  A table whose collector returned nothing this run is NOT touched at all, so a
  broken scraper can never empty a worksheet (or the Coda table synced from it).

Housekeeping tabs:
  Run Log        one row appended per run (feeds and the weekly link check)
  Link Health    rewritten by the weekly link check (src/linkcheck.py)
  Health Checks  rewritten by the weekly link check: is every source still
                 producing new rows?

Credentials (one of):
  GOOGLE_SERVICE_ACCOUNT_JSON  full contents of the service-account key (CI)
  GOOGLE_SERVICE_ACCOUNT_PATH  path to the key file (local runs)
And:
  GOOGLE_SHEET_ID              from https://docs.google.com/spreadsheets/d/<ID>/edit
"""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional

from src import schema
from src.catalogue import merge

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

RUN_LOG = "Run Log"
RUN_LOG_HEADERS = ["Run At", "Job", "Result", "Summary", "Details"]
# A brand-new Google Sheet starts with one empty tab with this name. It is
# removed once the real tabs exist, so the warehouse only shows real data.
DEFAULT_TAB_NAMES = ("Sheet1",)


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_SHEET_ID") and (
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH")))


def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH")
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    elif path:
        creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    else:
        raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_JSON (CI) or GOOGLE_SERVICE_ACCOUNT_PATH (local)")
    return gspread.authorize(creds)


def open_book():
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID environment variable not set")
    return _client().open_by_key(sheet_id)


def _col_letter(index: int) -> str:
    letters, index = "", index + 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def rows_from_values(table: str, values: List[List[str]]) -> List[Dict]:
    """Sheet values (header row first) -> field-keyed dicts. Columns the
    schema doesn't know are ignored; missing columns read as blank."""
    if not values:
        return []
    h2f = schema.header_to_field(table)
    header = values[0]
    out = []
    for raw in values[1:]:
        row = {}
        for i, h in enumerate(header):
            f = h2f.get(h)
            if not f:
                continue
            v = raw[i] if i < len(raw) else ""
            if f in schema.NUMERIC_FIELDS:
                try:
                    v = float(str(v).replace("$", "").replace(",", "")) if str(v).strip() else None
                except ValueError:
                    v = None
            row[f] = v
        if row.get(schema.TABLES[table]["key"]):
            out.append(row)
    return out


def values_from_rows(table: str, rows: List[Dict]) -> List[List]:
    flds = schema.fields(table)
    out = [schema.headers(table)]
    for r in rows:
        out.append(["" if r.get(f) is None else r.get(f) for f in flds])
    return out


def _worksheet(book, name: str, cols: int):
    import gspread
    try:
        return book.worksheet(name)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=name, rows=2, cols=cols)


def write_tab(book, name: str, values: List[List]) -> None:
    """Replace a whole tab with `values` (header row first). Written first and
    trimmed after, so a sync that fires mid-write never sees an empty tab."""
    cols = max(len(values[0]), 1)
    ws = _worksheet(book, name, cols)
    ws.resize(rows=max(len(values), 2), cols=cols)
    ws.update(values, "A1", value_input_option="RAW")
    ws.format(f"A1:{_col_letter(cols - 1)}1", {"textFormat": {"bold": True}})
    ws.freeze(rows=1)


def append_run_log(book, row: List, keep_last: int = 500) -> None:
    ws = _worksheet(book, RUN_LOG, len(RUN_LOG_HEADERS))
    values = ws.get_all_values()
    if not values or values[0][:len(RUN_LOG_HEADERS)] != RUN_LOG_HEADERS:
        values = [RUN_LOG_HEADERS]
    body = values[1:] + [[str(c) for c in row]]
    write_tab(book, RUN_LOG, [RUN_LOG_HEADERS] + body[-keep_last:])


def read_run_log(book) -> List[Dict[str, str]]:
    import gspread
    try:
        values = book.worksheet(RUN_LOG).get_all_values()
    except gspread.WorksheetNotFound:
        return []
    if not values:
        return []
    head = values[0]
    return [dict(zip(head, r)) for r in values[1:]]


def read_table(book, table: str) -> List[Dict]:
    import gspread
    try:
        ws = book.worksheet(schema.TABLES[table]["worksheet"])
    except gspread.WorksheetNotFound:
        return []
    return rows_from_values(table, ws.get_all_values())


def remove_default_tab(book) -> None:
    """Delete the empty 'Sheet1' a new spreadsheet comes with, once other tabs
    exist. Never deletes a tab that has anything in it."""
    tabs = book.worksheets()
    if len(tabs) < 2:
        return
    for ws in tabs:
        if ws.title in DEFAULT_TAB_NAMES and not any(any(c for c in r) for r in ws.get_all_values()):
            book.del_worksheet(ws)


def export_to_sheets(fresh: Dict[str, List[Dict]], now: str, log=print,
                     keep: Optional[Dict[str, Callable[[Dict], bool]]] = None,
                     book=None) -> Dict[str, int]:
    """fresh: {table: rows from this run}. Returns {table: rows now in sheet}."""
    book = book or open_book()
    keep = keep or {}
    totals: Dict[str, int] = {}

    for table, spec in schema.TABLES.items():
        rows_now = fresh.get(table) or []
        if not rows_now:
            log(f"  {table}: nothing collected this run — worksheet left untouched")
            continue
        ws = _worksheet(book, spec["worksheet"], len(schema.headers(table)))
        existing = rows_from_values(table, ws.get_all_values())
        merged = merge(table, existing, rows_now, now, log=log, keep=keep.get(table))
        write_tab(book, spec["worksheet"], values_from_rows(table, merged))
        totals[table] = len(merged)
    remove_default_tab(book)
    return totals

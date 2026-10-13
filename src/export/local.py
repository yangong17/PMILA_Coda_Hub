"""
No-credentials output: out/<table>.json and out/<table>.csv.

Keys/columns are the SAME header names the Google Sheet uses (src/schema.py),
so a table loaded from these files lines up with a later Sheets-synced table.
Previous files are read back first and merged (same rules as the Sheet), so
repeated local runs behave like the real pipeline.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, List

from src import schema


def _to_header_row(table: str, row: Dict) -> Dict:
    """Header-keyed row. Unknown numbers stay null (so 'unknown' != 'free');
    unknown text becomes ''."""
    out = {}
    for f, h in schema.TABLES[table]["columns"].items():
        v = row.get(f)
        out[h] = v if (v is not None or f in schema.NUMERIC_FIELDS) else ""
    return out


def read_existing(table: str, out_dir: str) -> List[Dict]:
    path = os.path.join(out_dir, f"{table}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    h2f = schema.header_to_field(table)
    return [{h2f[h]: v for h, v in r.items() if h in h2f} for r in data]


def write_table(table: str, rows: List[Dict], out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    out_rows = [_to_header_row(table, r) for r in rows]
    jpath = os.path.join(out_dir, f"{table}.json")
    cpath = os.path.join(out_dir, f"{table}.csv")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out_rows, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(cpath, "w", encoding="utf-8-sig", newline="") as f:  # BOM: Excel-friendly
        w = csv.DictWriter(f, fieldnames=schema.headers(table))
        w.writeheader()
        for r in out_rows:
            w.writerow({k: ("" if v is None else _fmt(v)) for k, v in r.items()})
    return {"json": jpath, "csv": cpath}


def _fmt(v):
    """5.0 -> '5', 1.5 -> '1.5' (no trailing .0 in CSV cells)."""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    return v

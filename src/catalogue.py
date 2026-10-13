"""
Merge a fresh scrape into what we already hold (the Google Sheet, or the
previous out/*.json in local mode). Same policy for every table:

  * keyed on canonical URL (schema.TABLES[t]["key"]);
  * MERGE, never wipe: rows not seen this run are KEPT (marked Stale), so a
    broken scraper or an event that dropped off the calendar never deletes data;
  * a fresh value only overwrites a stored one when it is non-empty, so a
    partial page read can't blank a field we captured earlier;
  * First Seen is kept from the first time a row appeared; Last Updated is the
    run time for rows confirmed this run;
  * Status (events) and Freshness are derived at write time, never stored.

The only rows ever removed are News items older than schema.RETENTION_DAYS,
and rows a caller-supplied `keep` test rejects (used to re-apply the News
headline filters in feeds.yaml to items stored before a filter was added).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from src import config, schema
from src.parsing import canonical_url


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def event_status(start: str, end: str, today: Optional[date] = None) -> str:
    today = today or config.now_pacific().date()
    try:
        s = date.fromisoformat(start) if start else None
        e = date.fromisoformat(end) if end else s
    except ValueError:
        return ""
    if s is None:
        return ""
    if e < today:
        return "Past"
    if s > today:
        return "Upcoming"
    return "In progress" if s < today or e > today else "Today"


def merge(table: str, existing: List[Dict], fresh: List[Dict], now: str,
          today: Optional[date] = None, log=None,
          keep: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
    key = schema.TABLES[table]["key"]
    fields = schema.fields(table)
    say = log or (lambda m: None)

    merged: Dict[str, Dict] = {}
    for r in existing:
        k = canonical_url(r.get(key))
        if k:
            row = dict(r)
            row[key] = k
            merged[k] = row

    keep_days = schema.RETENTION_DAYS.get(table)
    cutoff = ""
    if keep_days:
        cutoff = ((today or config.now_pacific().date()) - timedelta(days=keep_days)).isoformat()
        fresh = [r for r in fresh if not r.get("published") or str(r["published"])[:10] >= cutoff]

    added = updated = 0
    for r in fresh:
        k = canonical_url(r.get(key))
        if not k:
            continue
        prior = merged.get(k)
        row = dict(prior) if prior else {}
        for f in fields:
            if f in schema.DERIVED_FIELDS or f in ("first_seen", "last_updated"):
                continue
            v = r.get(f)
            if not _empty(v):
                row[f] = v
            elif f not in row:
                row[f] = v if f in schema.NUMERIC_FIELDS else (v or "")
        row[key] = k
        row["first_seen"] = (prior or {}).get("first_seen") or now
        row["last_updated"] = now
        merged[k] = row
        if prior:
            updated += 1
        else:
            added += 1

    rows = list(merged.values())
    stale = 0
    for r in rows:
        r["freshness"] = "Current" if r.get("last_updated") == now else "Stale"
        stale += r["freshness"] == "Stale"
        if table == "events":
            r["status"] = event_status(r.get("start_date", ""), r.get("end_date", ""), today)

    dropped = 0
    if cutoff:
        before = len(rows)
        rows = [r for r in rows if not r.get("published") or r["published"][:10] >= cutoff]
        dropped = before - len(rows)

    filtered = 0
    if keep:
        before = len(rows)
        rows = [r for r in rows if keep(r)]
        filtered = before - len(rows)

    sort_field, desc = schema.SORT[table]
    rows.sort(key=lambda r: (str(r.get(sort_field) or ""), str(r.get("title") or r.get("headline") or "")),
              reverse=desc)
    say(f"  {table}: {len(rows)} rows ({added} new, {updated} refreshed, {stale} stale"
        + (f", {dropped} aged out" if dropped else "")
        + (f", {filtered} filtered out" if filtered else "") + ")")
    return rows


def run_timestamp() -> str:
    return config.now_pacific().strftime("%Y-%m-%d %H:%M %Z")

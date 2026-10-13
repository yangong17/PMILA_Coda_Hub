"""
PM Hub feeds — entry point.

Flow (same shape as WebinarHub):
  1. Run every collector. One failing source never kills the run.
  2. Merge each table into the Google Sheet (one worksheet per table), or —
     with --local / no credentials — into out/<table>.json + .csv.
  3. Append a row to the Sheet's Run Log tab (row counts and warnings).

The weekly link and freshness check is a separate entry point:
  python -m src.linkcheck   (see that module)

Usage:
  python -m src.main                 # Sheet (if configured) + out/ snapshot
  python -m src.main --local         # force local files (no Google needed)
  python -m src.main --local --only events,blog
  python -m src.main --local --fixtures tests/fixtures/manifest.json
                                     # offline run against saved pages

Exit code is non-zero only if EVERY source failed (or the Sheet write failed).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src import config, schema                                  # noqa: E402
from src.catalogue import merge, run_timestamp                  # noqa: E402
from src.collectors.news import NewsCollector, stored_row_filter  # noqa: E402
from src.collectors.pmi_la_blog import PmiLaBlogCollector       # noqa: E402
from src.collectors.pmi_la_events import PmiLaEventsCollector   # noqa: E402
from src.collectors.youtube import YouTubeCollector             # noqa: E402
from src.export import local                                    # noqa: E402
from src.export import sheets                                   # noqa: E402
from src.fetching import FixtureFetcher, PoliteFetcher          # noqa: E402

# Order matters only in that Recordings reuses the Blog rows (embedded videos).
ORDER = ["events", "blog", "recordings", "news"]


def build_collector(table, fetcher, results):
    if table == "events":
        return PmiLaEventsCollector(fetcher)
    if table == "blog":
        return PmiLaBlogCollector(fetcher)
    if table == "recordings":
        return YouTubeCollector(fetcher, blog_rows=results.get("blog") or [])
    if table == "news":
        return NewsCollector(fetcher)
    raise ValueError(table)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect PM Hub feeds")
    ap.add_argument("--local", action="store_true", help="write out/*.json + *.csv instead of Google Sheets")
    ap.add_argument("--out", default=str(ROOT / "out"), help="output folder for --local")
    ap.add_argument("--only", default="", help="comma list of tables: " + ",".join(ORDER))
    ap.add_argument("--fixtures", default="", help="replay saved responses from a manifest.json")
    ap.add_argument("--fresh", action="store_true", help="local mode: ignore previous out/ files")
    args = ap.parse_args(argv)

    tables = [t for t in ORDER if not args.only or t in args.only.split(",")]
    fetcher = FixtureFetcher(args.fixtures) if args.fixtures else PoliteFetcher()
    use_sheets = sheets.configured() and not args.local
    sheet_ok = True

    print("=" * 60)
    print(f"PM Hub feeds — {run_timestamp()}")
    print(f"User-Agent: {fetcher.user_agent}")
    print(f"Output: {'Google Sheet' if use_sheets else args.out}")
    print("=" * 60)

    results, failures, warnings = {}, [], {}
    for table in tables:
        c = build_collector(table, fetcher, results)
        print(f"\n── {c.SOURCE_NAME} → {table}")
        try:
            rows = c.run()
        except Exception as e:                       # belt and braces
            rows = []
            c.warnings.append(f"crashed: {e}")
            print(f"  ✗ {c.SOURCE_NAME} crashed: {e}")
        results[table] = rows
        warnings[table] = c.warnings
        if rows:
            print(f"  ✓ {len(rows)} row(s)")
        else:
            failures.append(table)
            print("  ⚠ 0 rows — existing data for this table is left untouched")

    now = run_timestamp()
    keep = {}
    if "news" in tables:
        try:
            keep["news"] = stored_row_filter()
        except Exception as e:                       # a bad feeds.yaml filter
            warnings.setdefault("news", []).append(f"stored-row filter skipped: {e}")

    collected = " · ".join(f"{t} {len(results[t])}" for t in tables)
    all_warnings = [f"[{t}] {w}" for t, ws in warnings.items() for w in ws]
    result = ("Failed" if len(failures) == len(tables)
              else "Partial" if failures or all_warnings else "OK")

    print(f"\n{'─' * 40}")
    if use_sheets:
        print("Syncing to Google Sheet…")
        try:
            book = sheets.open_book()
            totals = sheets.export_to_sheets(results, now, keep=keep, book=book)
            print("  ✓ " + ", ".join(f"{k}: {v}" for k, v in totals.items()))
            sheets.append_run_log(book, [
                now, "feeds", result,
                f"collected: {collected}; in sheet: "
                + " · ".join(f"{k} {v}" for k, v in totals.items()),
                " | ".join(all_warnings)[:2000],
            ])
        except Exception as e:
            sheet_ok = False
            print(f"  ✗ Google Sheets sync failed: {e}")
    if not use_sheets and not args.local:
        print("(Google Sheet not configured — writing local files)")
    # Local files are always written too (in CI they become the run's
    # downloadable snapshot) — from the same scrape, no second round of requests.
    print(f"Writing local files to {args.out}…")
    for table in tables:
        existing = [] if args.fresh else local.read_existing(table, args.out)
        if not results[table] and not existing:
            continue
        merged = merge(table, existing, results[table], now, log=print, keep=keep.get(table))
        paths = local.write_table(table, merged, args.out)
        print(f"    → {paths['json']}")

    print(f"\n{'=' * 60}")
    print(f"Requests made: {fetcher.request_count}")
    for t, ws in warnings.items():
        for w in ws:
            print(f"  ⚠ [{t}] {w}")
    print("=" * 60)
    if use_sheets and not sheet_ok:
        return 1
    return 1 if failures and len(failures) == len(tables) else 0


if __name__ == "__main__":
    sys.exit(main())

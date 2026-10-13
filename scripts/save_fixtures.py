"""
Refresh tests/fixtures with REAL saved responses from the live sites.

The fixtures shipped with the repo were reconstructed from text reads (see
tests/fixtures/build_fixtures.py) because the build sandbox could not reach the
sites directly. Run this once from a normal internet connection, then run
`pytest` — any failure means the parser needs a tweak for the real markup.

    python scripts/save_fixtures.py            # overwrite every fixture
    python scripts/save_fixtures.py --dry-run  # just list what would be fetched

Uses the same polite fetcher as the pipeline (robots.txt, User-Agent, delay).
URLs that robots.txt disallows (YouTube's feed) are skipped and keep their file.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.fetching import PoliteFetcher, RobotsDisallowed  # noqa: E402

MANIFEST = os.path.join(ROOT, "tests", "fixtures", "manifest.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    fetcher = PoliteFetcher()
    ok = skipped = failed = 0
    for url, rel in manifest["responses"].items():
        if args.dry_run:
            print(url)
            continue
        path = os.path.join(os.path.dirname(MANIFEST), rel)
        try:
            body = fetcher.content(url, check_robots=not url.endswith("/robots.txt"))
        except RobotsDisallowed:
            print(f"  skip (robots.txt) {url}")
            skipped += 1
            continue
        except Exception as e:
            print(f"  FAIL {url}: {e}")
            failed += 1
            continue
        with open(path, "wb") as f:
            f.write(body)
        print(f"  saved {url} → {rel} ({len(body):,} bytes)")
        ok += 1
    if not args.dry_run:
        manifest["note"] = "Saved verbatim from the live sites by scripts/save_fixtures.py."
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"\n{ok} saved, {skipped} skipped, {failed} failed. Now run: pytest")


if __name__ == "__main__":
    main()

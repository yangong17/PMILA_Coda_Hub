"""
Weekly health check for the PM Hub: are the links alive, and is every
source still producing new rows?

  python -m src.linkcheck              # Sheet (if configured) + out/ files
  python -m src.linkcheck --local      # read/write out/ only, no Google
  python -m src.linkcheck --limit 20   # quick trial on the first 20 URLs

1. LINKS. Gathers every outbound URL from
     * the Sheet's Events, Blog and Recordings tabs (News links come straight
       from the publishers' feeds every day, so they are not re-checked), and
     * the hub itself: through the Coda API when CODA_API_TOKEN is set
       (src/coda_api.py), otherwise from the snapshot in data/hub_links.csv.
   Each unique URL gets one polite GET (robots.txt honoured, 2 s between hits
   to the same site) and is classed as:
     OK       loads normally
     Login    sends readers to a sign-in page (expected for some PMI pages)
     Broken   404/410, server error, unreachable, a "page not found" page, or a
              redirect to the site's home page (a "soft 404")
     Blocked  the site refuses automated checks (401/403/429); check by hand
     Suspect  loads, but doesn't mention the item it is listed for; if
              ANTHROPIC_API_KEY is set, Claude reads the page and decides
     Skipped  robots.txt asks automated agents to stay away
   YouTube links are checked through YouTube's oEmbed endpoint, which (unlike
   the watch page) says when a video has been removed or made private.

2. FRESHNESS. Checks the scraper is still doing its job:
     * the twice-daily feeds run succeeded in the last 36 hours (Run Log tab)
     * there is at least one upcoming event
     * the chapter blog and each news outlet have published recently

3. OUTPUT. Rewrites the "Link Health" and "Health Checks" tabs, appends a row to
   "Run Log", writes out/link_health.csv + out/health_checks.csv, and prints a
   summary (also shown on the GitHub Actions run page). Exits 1 when any link
   is Broken or any freshness check Fails, so GitHub emails the maintainers.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urlsplit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src import coda_api, config                    # noqa: E402
from src.catalogue import run_timestamp              # noqa: E402
from src.export import local, sheets                 # noqa: E402
from src.fetching import PoliteFetcher, Probe        # noqa: E402

HUB_LINKS_CSV = ROOT / "data" / "hub_links.csv"

# Feed-table columns whose URLs readers click. News is deliberately absent.
FEED_URL_FIELDS = {
    "events": [("url", "Event page"), ("register_url", "Register URL")],
    "blog": [("url", "Post"), ("video_url", "Video URL")],
    "recordings": [("url", "Video")],
}
FEED_TITLE_FIELD = {"events": "title", "blog": "title", "recordings": "title"}
FEED_LABEL = {"events": "Events", "blog": "Blog", "recordings": "Recordings"}

# Freshness thresholds (days unless noted).
FEEDS_RUN_MAX_AGE_HOURS = 36
BLOG_WARN_DAYS, BLOG_FAIL_DAYS = 60, 120
NEWS_FAIL_DAYS = 7
OUTLET_WARN_DAYS = 45

LINK_HEADERS = ["Result", "Note", "URL", "HTTP", "Final URL", "Used In", "Checked At"]
CHECK_HEADERS = ["Check", "Result", "Detail", "Checked At"]
RESULT_ORDER = ["Broken", "Suspect", "Blocked", "Skipped", "Login", "OK"]

SOFT_404 = re.compile(
    r"(\b404\b|page not found|not found|can.t be found|cannot be found|no longer available|"
    r"no longer exists|does not exist|doesn.t exist|page unavailable|event not found|"
    r"has been removed|content unavailable)", re.IGNORECASE)
LOGIN_PATH = re.compile(r"(^|/)(login|log-in|signin|sign-in|sso|auth|account/login)(/|$|\?)", re.IGNORECASE)
STOPWORDS = set("""about after again also among and another any are because been before being
between both but can could does doing during each every from further have having here how
into its just more most much must not now only other our ours over own same should some
such than that the their them then there these they this those through under until very
what when where which while who whom why will with would your yours you for project projects
management manager managers pmi free with online course webinar program""".split())


# ── gathering ────────────────────────────────────────────────────────────────
def links_from_feed_tables(tables: Dict[str, List[Dict]]) -> List[Dict]:
    out = []
    for table, cols in FEED_URL_FIELDS.items():
        for row in tables.get(table) or []:
            if table == "events" and row.get("status") == "Past":
                continue                      # readers no longer see past events
            item = str(row.get(FEED_TITLE_FIELD[table]) or "").strip()
            for field, label in cols:
                url = str(row.get(field) or "").strip()
                if url.startswith(("http://", "https://")):
                    out.append({"Where": FEED_LABEL[table], "Item": item, "Field": label, "URL": url})
    return out


def links_from_csv(path: Path = HUB_LINKS_CSV) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("URL") or "").startswith("http")]


def group_by_url(links: List[Dict]) -> "OrderedDict[str, List[Dict]]":
    grouped: "OrderedDict[str, List[Dict]]" = OrderedDict()
    for ln in links:
        url = ln["URL"].strip()
        if coda_api.is_internal(url):
            continue
        uses = grouped.setdefault(url, [])
        if not any(u["Where"] == ln["Where"] and u["Item"] == ln["Item"] for u in uses):
            uses.append(ln)
    return grouped


def used_in(uses: List[Dict], limit: int = 4) -> str:
    labels = [f"{u['Where']}: {u['Item']}" if u.get("Item") else u["Where"] for u in uses]
    more = len(labels) - limit
    return "; ".join(labels[:limit]) + (f"; +{more} more" if more > 0 else "")


# ── classifying ──────────────────────────────────────────────────────────────
def page_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""


def first_heading(text: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(1))).strip() if m else ""


def visible_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()


def keywords(item: str) -> List[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'\-]+", item.lower())
    return sorted({w.strip("'-") for w in words if len(w) >= 4 and w not in STOPWORDS})


def mentions_item(item: str, page_text: str) -> Optional[bool]:
    """True/False if the page does/doesn't seem to be about `item`;
    None when the item name is too generic to tell."""
    kws = keywords(item)
    if len(kws) < 2:
        return None
    low = page_text.lower()
    hits = sum(1 for k in kws if k in low)
    return hits / len(kws) >= 0.34


def youtube_video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/|live/)|youtu\.be/)([\w-]{11})", url)
    return m.group(1) if m else None


def classify(probe: Probe, uses: List[Dict]) -> Dict:
    """-> {"result", "note"} for one probed URL (YouTube handled by caller)."""
    if probe.robots_blocked:
        return {"result": "Skipped", "note": probe.error}
    if probe.error:
        return {"result": "Broken", "note": f"Unreachable: {probe.error}"}
    st = probe.status or 0
    if st in (404, 410):
        return {"result": "Broken", "note": f"HTTP {st}: page not found"}
    if st in (400, 401, 403, 429, 999):
        return {"result": "Blocked", "note": f"HTTP {st}: the site refuses automated checks; open it by hand"}
    if st >= 400:
        return {"result": "Broken", "note": f"HTTP {st}"}

    orig, final = urlsplit(probe.url), urlsplit(probe.final_url)
    if LOGIN_PATH.search(final.path) or final.netloc.split(".")[0] in ("login", "sso", "idp", "auth"):
        return {"result": "Login", "note": "Opens a sign-in page"}
    went_home = final.path in ("", "/") and (orig.path not in ("", "/") or orig.query) and not final.query
    if went_home:
        return {"result": "Broken", "note": "Redirects to the site's home page (the page was probably removed)"}

    if probe.content_type and "html" not in probe.content_type:
        return {"result": "OK", "note": probe.content_type}
    title, h1 = page_title(probe.text), first_heading(probe.text)
    if SOFT_404.search(title) or SOFT_404.search(h1):
        return {"result": "Broken", "note": f"Shows a not-found page: “{(title or h1)[:80]}”"}

    # Only a link's OWN label says what its page should be about. Links inside a
    # hub page's text (template sources and the like) are labelled with the page
    # name, which tells us nothing about the target.
    items = {u["Item"] for u in uses if u.get("Item") and not str(u.get("Where", "")).startswith("Page:")}
    if len(items) == 1 and all(not str(u.get("Where", "")).startswith("Page:") for u in uses):
        about = mentions_item(next(iter(items)), f"{title} {h1} {visible_text(probe.text)}")
        if about is False:
            return {"result": "Suspect",
                    "note": f"Loads, but doesn't seem to mention this item (page title: “{title[:80]}”)"}
    note = f"Redirects to {probe.final_url}" if probe.final_url.rstrip("/") != probe.url.rstrip("/") else ""
    return {"result": "OK", "note": note}


def check_youtube(fetcher, url: str, video_id: str) -> Dict:
    oembed = ("https://www.youtube.com/oembed?format=json&url="
              + quote(f"https://www.youtube.com/watch?v={video_id}", safe=""))
    p = fetcher.probe(oembed)
    if p.error and not p.robots_blocked:
        return {"result": "Broken", "status": "", "final": url, "note": f"Unreachable: {p.error}"}
    if p.robots_blocked:
        return {"result": "Skipped", "status": "", "final": url, "note": p.error}
    if p.status == 200:
        return {"result": "OK", "status": 200, "final": url, "note": "Video is public"}
    if p.status in (401, 403):
        return {"result": "Broken", "status": p.status, "final": url,
                "note": "Video is private or can't be embedded"}
    return {"result": "Broken", "status": p.status, "final": url, "note": "Video removed or unavailable"}


# ── optional Claude review of Suspect pages ──────────────────────────────────
REVIEW_MODEL = os.environ.get("LINKCHECK_MODEL", "").strip() or "claude-haiku-5-5"
_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "moved", "broken"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}
_REVIEW_SYSTEM = (
    "You check links on a resource hub for project managers. Given the item a link is "
    "listed for and the text of the page it opens, decide: 'ok' if the page is still "
    "about that item (or is the right place to get it), 'moved' if the page loads but "
    "the item seems to have moved or been replaced, 'broken' if the page is an error, "
    "an expired listing or unrelated. Answer in one short sentence."
)


def reviewer_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def review_with_claude(item: str, url: str, probe: Probe, client=None) -> Optional[Dict]:
    try:
        import anthropic
        client = client or anthropic.Anthropic()
        prompt = (f"Item: {item}\nLink: {url}\nPage title: {page_title(probe.text)}\n\n"
                  f"Page text (first 3,000 characters):\n{visible_text(probe.text)[:3000]}")
        resp = client.messages.create(
            model=REVIEW_MODEL, max_tokens=300, system=_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _REVIEW_SCHEMA}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        return {"verdict": data["verdict"], "reason": data.get("reason", "").strip()}
    except Exception as e:                 # the review is a bonus, never a blocker
        print(f"  ⚠ Claude review failed for {url}: {e}")
        return None


# ── running the link check ───────────────────────────────────────────────────
def check_links(grouped: "OrderedDict[str, List[Dict]]", fetcher, now: str,
                reviewer: Optional[Callable] = None, recheck_wait: float = 20,
                log=print) -> List[Dict]:
    results: List[Dict] = []
    probes: Dict[str, Probe] = {}
    total = len(grouped)
    for i, (url, uses) in enumerate(grouped.items(), 1):
        vid = youtube_video_id(url)
        if vid:
            r = check_youtube(fetcher, url, vid)
        else:
            p = fetcher.probe(url)
            probes[url] = p
            c = classify(p, uses)
            r = {"result": c["result"], "note": c["note"], "status": p.status or "",
                 "final": p.final_url}
        results.append({"URL": url, "Used In": used_in(uses), "_uses": uses, **r})
        if i % 25 == 0 or i == total:
            log(f"  checked {i}/{total}")

    # A second chance for failures that may be momentary (timeouts, 5xx).
    flaky = [r for r in results if r["result"] == "Broken"
             and (str(r["note"]).startswith("Unreachable") or str(r["status"]).startswith("5"))]
    if flaky:
        log(f"  re-checking {len(flaky)} link(s) that failed with a timeout or server error…")
        time.sleep(recheck_wait)
        # PoliteFetcher skips a host for the rest of the run once its robots.txt
        # is unreachable; give every host a fresh chance on the second pass.
        getattr(fetcher, "_dead", {}).clear()
        for r in flaky:
            p = fetcher.probe(r["URL"])
            probes[r["URL"]] = p
            c = classify(p, r["_uses"])
            r.update(result=c["result"], note=c["note"], status=p.status or "", final=p.final_url)

    if reviewer:
        for r in results:
            if r["result"] != "Suspect" or r["URL"] not in probes:
                continue
            item = next((u["Item"] for u in r["_uses"] if u.get("Item")), "")
            verdict = reviewer(item, r["URL"], probes[r["URL"]])
            if not verdict:
                continue
            r["note"] = f"Claude: {verdict['reason']}"
            r["result"] = {"ok": "OK", "broken": "Broken"}.get(verdict["verdict"], "Suspect")

    for r in results:
        r["Checked At"] = now
    results.sort(key=lambda r: (RESULT_ORDER.index(r["result"]), r["URL"]))
    return results


# ── freshness checks ─────────────────────────────────────────────────────────
def _as_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_datetime(value) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value)[:16], "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def freshness_checks(tables: Dict[str, List[Dict]], run_log: Optional[List[Dict]],
                     outlets: List[str], today: Optional[date] = None,
                     now: Optional[datetime] = None) -> List[Dict]:
    today = today or config.now_pacific().date()
    now = now or config.now_pacific().replace(tzinfo=None)
    checks: List[Dict] = []

    def add(check, result, detail):
        checks.append({"Check": check, "Result": result, "Detail": detail})

    # 1. The twice-daily feeds job.
    if run_log is None:
        add("Feeds job ran recently", "Skip", "No Google Sheet configured; Run Log not available")
    else:
        feeds_runs = [r for r in run_log if r.get("Job") == "feeds"]
        last = feeds_runs[-1] if feeds_runs else None
        when = _as_datetime(last.get("Run At")) if last else None
        if not when:
            add("Feeds job ran recently", "Fail", "No feeds run recorded in the Run Log")
        elif now - when > timedelta(hours=FEEDS_RUN_MAX_AGE_HOURS):
            add("Feeds job ran recently", "Fail",
                f"Last feeds run was {last['Run At']} (over {FEEDS_RUN_MAX_AGE_HOURS} h ago). "
                "Check the Actions tab: the schedule may be paused or the job failing")
        elif last.get("Result") == "Failed":
            add("Feeds job ran recently", "Fail", f"Last feeds run ({last['Run At']}) failed: {last.get('Details', '')[:300]}")
        else:
            recent = feeds_runs[-14:]                   # about a week of runs
            partial = [r for r in recent if r.get("Result") != "OK"]
            add("Feeds job ran recently", "Warn" if partial else "Pass",
                f"Last run {last['Run At']} ({last.get('Result')}); "
                f"{len(partial)} of the last {len(recent)} runs had warnings")

    # 2. Events.
    events = tables.get("events") or []
    upcoming = [e for e in events if (_as_date(e.get("end_date")) or _as_date(e.get("start_date")) or date.min) >= today]
    add("Upcoming events", "Pass" if upcoming else "Fail",
        f"{len(upcoming)} upcoming event(s)" if upcoming else
        "No upcoming events. Either the calendar scraper broke or the chapter has nothing scheduled; check pmi-la.org/calendar")

    # 3. Blog.
    posts = [d for d in (_as_date(r.get("published")) for r in tables.get("blog") or []) if d]
    if not posts:
        add("Chapter blog is current", "Fail", "No dated blog posts collected")
    else:
        age = (today - max(posts)).days
        result = "Pass" if age <= BLOG_WARN_DAYS else "Warn" if age <= BLOG_FAIL_DAYS else "Fail"
        add("Chapter blog is current", result, f"Newest post is {age} day(s) old ({max(posts)})")

    # 4. News, overall and per outlet.
    news = tables.get("news") or []
    dates = [d for d in (_as_date(r.get("published")) for r in news) if d]
    if not dates:
        add("PM News is current", "Fail", "No dated news items collected")
    else:
        age = (today - max(dates)).days
        add("PM News is current", "Pass" if age <= NEWS_FAIL_DAYS else "Fail",
            f"Newest headline is {age} day(s) old")
    for outlet in outlets:
        od = [d for d in (_as_date(r.get("published")) for r in news if r.get("outlet") == outlet) if d]
        if not od:
            add(f"Outlet: {outlet}", "Warn", "No items in the last 120 days; the feed URL may have changed")
        else:
            age = (today - max(od)).days
            add(f"Outlet: {outlet}", "Pass" if age <= OUTLET_WARN_DAYS else "Warn",
                f"Newest item {age} day(s) old")
    return checks


# ── output ───────────────────────────────────────────────────────────────────
def link_rows(results: List[Dict]) -> List[List]:
    return [[r["result"], r["note"], r["URL"], r["status"], r["final"], r["Used In"], r["Checked At"]]
            for r in results]


def check_rows(checks: List[Dict], now: str) -> List[List]:
    return [[c["Check"], c["Result"], c["Detail"], now] for c in checks]


def summarize(results: List[Dict], checks: List[Dict]) -> Dict:
    counts = {k: sum(r["result"] == k for r in results) for k in RESULT_ORDER}
    fails = [c for c in checks if c["Result"] == "Fail"]
    warns = [c for c in checks if c["Result"] == "Warn"]
    ok = counts["Broken"] == 0 and not fails
    text = (f"{len(results)} links: " + ", ".join(f"{v} {k.lower()}" for k, v in counts.items() if v)
            + f" · checks: {len(checks) - len(fails) - len(warns)} pass, {len(warns)} warn, {len(fails)} fail")
    return {"ok": ok, "counts": counts, "fails": fails, "warns": warns, "text": text}


def markdown_report(results: List[Dict], checks: List[Dict], summary: Dict) -> str:
    lines = ["# PM Hub weekly health check", "", summary["text"], ""]
    attention = [r for r in results if r["result"] in ("Broken", "Suspect", "Blocked")]
    if attention:
        lines += ["## Links to look at", "", "| Result | Link | Used in | Note |", "|---|---|---|---|"]
        for r in attention:
            lines.append(f"| {r['result']} | {r['URL']} | {r['Used In']} | {r['note']} |")
        lines.append("")
    lines += ["## Freshness", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c['Check']} | {c['Result']} | {c['Detail']} |" for c in checks]
    return "\n".join(lines) + "\n"


def write_csv(path: Path, headers: List[str], rows: List[List]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


# ── entry point ──────────────────────────────────────────────────────────────
def enabled_outlets() -> List[str]:
    from src.collectors.news import load_feeds
    try:
        return [fd["name"] for fd in load_feeds()]
    except Exception:
        return []


def main(argv=None, fetcher=None, book=None) -> int:
    ap = argparse.ArgumentParser(description="Weekly PM Hub link and freshness check")
    ap.add_argument("--local", action="store_true", help="use out/ files only; no Google Sheet")
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--limit", type=int, default=0, help="check only the first N URLs (trial runs)")
    ap.add_argument("--no-hub", action="store_true", help="skip the hub's own links")
    args = ap.parse_args(argv)

    now = run_timestamp()
    use_sheets = (book is not None) or (sheets.configured() and not args.local)
    print("=" * 60)
    print(f"PM Hub health check — {now}")
    print("=" * 60)

    # Feed tables + run log.
    tables: Dict[str, List[Dict]] = {}
    run_log = None
    if use_sheets:
        book = book or sheets.open_book()
        for t in ("events", "blog", "recordings", "news"):
            tables[t] = sheets.read_table(book, t)
        run_log = sheets.read_run_log(book)
    else:
        for t in ("events", "blog", "recordings", "news"):
            tables[t] = local.read_existing(t, args.out)
    print("Feed tables: " + ", ".join(f"{t} {len(r)}" for t, r in tables.items()))

    # Hub links.
    links = links_from_feed_tables(tables)
    hub_source = "skipped"
    if not args.no_hub:
        if coda_api.configured():
            try:
                hub = coda_api.CodaClient().all_links()
                hub_source = f"Coda API ({len(hub)} links)"
            except Exception as e:
                hub = links_from_csv()
                hub_source = f"data/hub_links.csv (Coda API failed: {e})"
        else:
            hub = links_from_csv()
            hub_source = "data/hub_links.csv snapshot (set CODA_API_TOKEN to read the live hub)"
        links += hub
    print(f"Hub links: {hub_source}")

    grouped = group_by_url(links)
    if args.limit:
        grouped = OrderedDict(list(grouped.items())[: args.limit])
    print(f"Checking {len(grouped)} unique URL(s)…")

    fetcher = fetcher or PoliteFetcher()
    reviewer = review_with_claude if reviewer_available() else None
    if reviewer:
        print(f"Suspect pages will be reviewed by {REVIEW_MODEL}")
    results = check_links(grouped, fetcher, now, reviewer=reviewer)
    checks = freshness_checks(tables, run_log, enabled_outlets())
    summary = summarize(results, checks)

    out = Path(args.out)
    write_csv(out / "link_health.csv", LINK_HEADERS, link_rows(results))
    write_csv(out / "health_checks.csv", CHECK_HEADERS, check_rows(checks, now))
    report = markdown_report(results, checks, summary)
    (out / "health_report.md").write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report)

    if use_sheets:
        sheets.write_tab(book, "Link Health", [LINK_HEADERS] + link_rows(results))
        sheets.write_tab(book, "Health Checks", [CHECK_HEADERS] + check_rows(checks, now))
        problems = [f"{r['result']}: {r['URL']} ({r['note']})" for r in results if r["result"] == "Broken"]
        problems += [f"{c['Check']}: {c['Detail']}" for c in summary["fails"]]
        sheets.append_run_log(book, [now, "linkcheck", "OK" if summary["ok"] else "Failed",
                                     summary["text"], " | ".join(problems)[:2000]])
        sheets.remove_default_tab(book)

    print("\n" + report)
    print(f"Requests made: {fetcher.request_count}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

# PM Hub Feeds

Keeps the **PMI-LA PM Hub** (Superhuman Docs / Coda) stocked with four live tables:

| Table | Source | What's in each row |
|---|---|---|
| **Events** | pmi-la.org home page + calendar (this month + 3 ahead) + each event page | title, series (MULTI-CHAPTER, WEBINAR, FLAGSHIP, BOOK CLUB, EXAM PREP…), start/end date, start/end time, recurrence, format + location, member / non-member / student-military price, PDUs (+ details, Talent Triangle), registration status + link, ≤200-char teaser, status (Upcoming / Today / In progress / Past) |
| **Blog** | pmi-la.org/blog pages 1–2 + each post | title, published, author (if shown), category, excerpt, embedded video link |
| **Recordings** | YouTube @PMI-LosAngeles (channel `UCoMM0sYo-pY3zdG19PegVfw`) | title, published, video ID, thumbnail, link |
| **News** | the RSS/Atom feeds listed in [`feeds.yaml`](feeds.yaml), minus vendor listicles and off-topic posts | headline, outlet, published, topic, link (never article text) |

…plus a weekly health check that tests every link in the Sheet and the hub and confirms each
source is still producing new rows (**Run Log**, **Link Health**, **Health Checks** tabs). A
broken link or a stalled source fails the run, and GitHub emails the maintainers.

It is the same pattern as WebinarHub:

```
GitHub Action (twice daily)  →  polite collectors read public pages and feeds
                              →  MERGE into a Google Sheet (one tab per table)   ← the memory
Google Sheet  →  Coda/Superhuman Docs (Google Sheets Pack sync tables)          ← what members see
GitHub Action (Mondays)      →  link + freshness check → Link Health tab, email on failure
```

Setup for the Sheet, GitHub and Coda: **[SETUP.md](SETUP.md)**.

## Run it

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

python -m src.main --local            # no Google needed → out/*.json + out/*.csv
python -m src.main                    # Google Sheet (if configured) + out/ snapshot
python -m src.main --local --only events,blog
python -m src.main --local --fixtures tests/fixtures/manifest.json   # offline, saved pages
python -m pytest -q                   # parser tests (offline)

python -m src.linkcheck --local       # weekly health check against out/ files
python -m src.linkcheck --limit 20    # quick trial on the first 20 links
```

`out/events.json`, `blog.json`, `recordings.json`, `news.json` (+ `.csv`) use the **same column
names as the Sheet**, so anything built from them lines up with the synced tables later.
Re-running merges into the previous files the same way the Sheet does; `--fresh` starts over.

## How the data stays trustworthy

* **Merge, never wipe.** Rows are keyed on a canonical URL (tracking parameters removed). A row
  not seen this run is kept and marked `Freshness = Stale`, never deleted, so an event that
  dropped off the calendar or a broken scraper can't empty a Coda table. A blank value from a
  partial read never overwrites a value captured earlier. Only News ages out (120 days).
* **One failing source never kills the run.** Each collector is isolated. A table that
  collected nothing is left exactly as it was.
* **Junk and duplicates are filtered centrally** (`collectors/base.py`): button labels,
  unrendered `{{template}}` cards, date-only "titles", repeated URLs.
* **Stable columns for Coda.** Headers live in one place, [`src/schema.py`](src/schema.py).
  The Pack maps columns by name, so add columns at the end and never rename them.
* **Derived columns are computed at write time.** `Status` (events) and `Freshness` are
  recalculated on every run, so an event flips from Upcoming to Past without anyone touching it.

## Being a good citizen

* `robots.txt` is checked for every host before fetching, and disallowed URLs are skipped.
  There is no override switch. If a host's robots.txt can't be read, that host is skipped too.
* Descriptive User-Agent `PMHubFeeds/0.1 (PMI-LA PM Hub resource-hub sync; …; contact: …)`.
  Set `FEEDS_CONTACT` so site owners can reach you.
* 2 seconds between requests to the same host, 20-second timeouts, and 3 retries with backoff
  (Retry-After is honoured). A full run makes about 37 requests, twice a day.
* **The best fix is to need none of this.** pmi-la.org belongs to our own chapter: ask the
  web/tech committee for an official calendar or blog feed (iCal, RSS or JSON). If they provide
  one, swap that collector for a 20-line feed reader.

## Project layout

```
src/
  main.py                 entry point: run collectors → Sheet and/or out/ files
  linkcheck.py            weekly link + freshness check → Link Health / Health Checks tabs
  coda_api.py             reads every outbound link in the hub (needs CODA_API_TOKEN)
  config.py               all tunables (User-Agent, delay, months ahead, blog pages, channel)
  schema.py               the four tables' columns (THE source of truth for headers)
  fetching.py             PoliteFetcher (robots, UA, delay, retries) + FixtureFetcher (offline)
  parsing.py              pure helpers: dates, times, prices, PDUs, series prefixes, URLs
  catalogue.py            merge-not-wipe logic, Status/Freshness, News retention
  collectors/
    base.py               BaseCollector + sanitize (junk titles, dedupe by URL)
    pmi_la_events.py      calendar + home → event pages
    pmi_la_blog.py        blog listing pages → post pages (category, embedded video)
    youtube.py            channel ID discovery; Data API → RSS → blog-embed fallbacks
    news.py               generic RSS/Atom reader driven by feeds.yaml
  export/
    sheets.py             one worksheet per table, read back by header name, merged, written
    local.py              out/<table>.json + .csv
feeds.yaml                news feed list and headline filters (edit freely)
data/hub_links.csv        snapshot of the hub's links, used when no CODA_API_TOKEN is set
scripts/save_fixtures.py  refresh test fixtures from the live sites
tests/                    pytest suite + fixtures (saved pages, feeds, manifest.json)
.github/workflows/feeds.yml       cron 09:17 and 21:17 UTC + manual "Run workflow"
.github/workflows/linkcheck.yml   Mondays 15:23 UTC + manual "Run workflow"
```

## Known limitations

* **Test fixtures are reconstructed, not saved byte-for-byte.** The build sandbox couldn't reach
  these sites directly, because its egress proxy refused the connections. Page content was read
  on 2026-10-08 with a separate fetch tool that returns text, and the fixture HTML was rebuilt
  around those exact values. The parsers rely on text labels (`Date:`, `Hour:`, `Members:`,
  `PDUs:`, the `/login?eventId=` link) rather than CSS classes, which should transfer to the real
  pages, but **run `python scripts/save_fixtures.py` and `pytest` once from a normal connection
  before trusting a scheduled run.**
* **YouTube's RSS feed is off-limits by robots.txt.** youtube.com/robots.txt has
  `Disallow: /feeds/videos.xml`, so without `YOUTUBE_API_KEY` the Recordings table only contains
  videos embedded in chapter blog posts. In that case the date is the post date, and the
  `Found Via` column says so. Add a free API key (SETUP Part E) for the full channel history.
* **Event location.** Some event pages show the venue only as an image. Those rows get a blank
  Location/Format rather than a guess, and the chapter's own footer address is never used.
* **Times are Pacific** (the site doesn't state a zone, and chapter events are LA-based).
* Blog author is only filled when the post shows a byline. Most chapter posts have none.
* **Some large sites block cloud servers.** If pmi.org or another site answers the GitHub runner
  with 403, its links show as **Blocked** (not Broken) and need an occasional manual look.
* **The link check has not yet run against the live web** from the build sandbox (same proxy
  limit as above). Its rules are covered by tests; the first Monday run is the real proof.

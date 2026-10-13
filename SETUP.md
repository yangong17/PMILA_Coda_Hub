# PM Hub Feeds — Setup Guide

## How it works (the big picture)

```
GitHub Action (twice a day)  →  reads PMI-LA's public pages, the YouTube channel and PM news feeds
                              →  MERGES the results into your Google Sheet   ← the memory
Google Sheet  →  Superhuman Docs / Coda (auto-syncs via the Google Sheets Pack)  ← what members see

GitHub Action (Mondays)      →  checks every link in the Sheet and the hub, and that each source
                                 is still producing new rows → Link Health tab + email if broken
```

The Sheet is the **PMI LA Hub Data Warehouse**
(`1T4oTJl6HhhI5un9bdkOCl-MnljlhiD35T7lzSTLdtC4`). It is the source of truth for everything
scraped:

| Tab | Written by | What's in it |
|---|---|---|
| **Events** | twice-daily job | every PMI-LA calendar event: dates, price, PDUs, talent triangle, links |
| **Blog** | twice-daily job | chapter blog posts: title, date, category, excerpt, embedded video |
| **Recordings** | twice-daily job | chapter YouTube videos |
| **News** | twice-daily job | headlines from the outlets in `feeds.yaml` (last 120 days) |
| **Run Log** | both jobs | one row per run: result, row counts, warnings |
| **Link Health** | Monday job | every link, its result (OK, Broken, Blocked…), and where it's used |
| **Health Checks** | Monday job | is each source still current? Pass / Warn / Fail |

Each run adds new rows and refreshes existing ones. It never wipes a tab: a row that disappears
from the website is kept and marked **Stale** instead of deleted. Coda pulls from the Sheet
automatically, so you never touch code to update the PM Hub.

Hand-curated tables (PDU opportunities, templates, Beyond PMI, programs) stay in the hub, where
they are edited. The Monday job still checks their links.

> **Before you start, ask for an official feed.** pmi-la.org is our own chapter's site. Ask
> the chapter's web/technology committee whether the site (MG2 Manager) can publish the
> calendar or blog as an **iCal, RSS or JSON feed**, or share an export. An official feed is
> more reliable than reading web pages and is the polite option. Until then, this tool reads
> the public pages gently:
> * it **identifies itself** (a User-Agent that names the PM Hub, plus your contact if you set
>   `FEEDS_CONTACT`),
> * it **obeys robots.txt** and skips anything a site asks robots not to read,
> * it keeps a **low request rate**: one request every 2 seconds per site, about 37 requests per
>   run, twice a day.

---

## Part A — Connect your Google Sheet (one-time setup)

> **Already set up WebinarHub? Take the shortcut.** You don't need a Google *API key* for the
> Sheet (an API key can only read public data). You need a **service account**, and the one
> WebinarHub uses works here too:
> 1. Open WebinarHub's service-account `.json` key and copy its `client_email`.
> 2. Share the **PMI LA Hub Data Warehouse** sheet with that email as **Editor** (Step 5 below).
> 3. In the new repo, add the same `.json` contents as the `GOOGLE_SERVICE_ACCOUNT_JSON`
>    secret and `1T4oTJl6HhhI5un9bdkOCl-MnljlhiD35T7lzSTLdtC4` as `GOOGLE_SHEET_ID` (Part C).
>    GitHub secrets belong to one repo, so they have to be added again even though the values
>    are the same.
>
> Then skip to Part C. Steps 1–5 are for starting from scratch.

The tool signs in as a robot account ("service account") so it can write to your sheet from
GitHub without a human logging in. Steps 1–5 create that robot and give it permission to edit
*one* sheet.

### Step 1: Create the Google Sheet
1. Go to [sheets.google.com](https://sheets.google.com) and create a blank sheet.
2. Name it something like **PM Hub Feeds**.
3. Look at the URL: `https://docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`.
   Copy that ID. This is your `GOOGLE_SHEET_ID`.

   *(You don't need to add tabs or headers. The tool creates every tab itself the first time
   it runs, and removes the empty "Sheet1" a new spreadsheet starts with.)*

### Step 2: Create a Google Cloud project
1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click the project dropdown at the top → **New Project** → name it `pm-hub-feeds` → **Create**.
3. Make sure that new project is selected.

### Step 3: Turn on the two APIs
1. Go to **APIs & Services → Library**.
2. Search **Google Sheets API** → click it → **Enable**.
3. Search **Google Drive API** → click it → **Enable**.

### Step 4: Create the service account (the robot) and its key
1. Go to **APIs & Services → Credentials**.
2. **Create Credentials → Service account**. Name it `pm-hub-feeds-bot` → **Create and continue** → **Done**.
3. Click the service account you just made → **Keys** tab → **Add key → Create new key → JSON → Create**.
4. A `.json` file downloads. **This file is the robot's password, so keep it private.**
5. Open the file and find the `"client_email"` line. It looks like
   `pm-hub-feeds-bot@pm-hub-feeds.iam.gserviceaccount.com`. Copy that email.

### Step 5: Share the sheet with the robot
1. Open your Google Sheet → click **Share**.
2. Paste the `client_email` from Step 4, set it to **Editor**, and send.
   *(This is the step everyone forgets. Without it you'll get a "permission denied" error.)*

✅ Your sheet is now linked.

---

## Part B — Connect the PM Hub (Superhuman Docs / Coda) to the Sheet (no code)

Do this **after the first run** (Part C, Step 3), so the four tabs exist.

1. In the PM Hub doc, type `/` and search **Google Sheets**, or go to **Insert → Packs** →
   **Google Sheets**.
2. Connect your Google account and authorize it.
3. Add a **sync table** from the PM Hub Feeds sheet and pick the **Events** tab.
   Repeat for **Blog**, **Recordings** and **News**, so you have four sync tables.
4. In each sync table's settings, turn on **auto-refresh** (daily, or more often on paid plans).
   Anyone can also click **Sync now**.
5. Build the pages from **filtered views** of those tables, for example:
   * *Upcoming events*: Events where `Status` is Upcoming / Today / In progress, sorted by
     `Start Date`. Group by `Series` for "Multi-chapter", "Webinars", "Book Club" and so on.
   * *Free & PDU events*: `Member Price` = 0, or `PDUs` > 0.
   * *Latest from the chapter*: Blog sorted by `Published`, newest first.
   * *Watch*: Recordings with the `Thumbnail URL` column shown as an image.
   * *PM news*: News from the last 14 days, grouped by `Outlet` or `Topic`.

**Don't rename the Sheet's column headers.** The Pack matches columns by name. To add a field,
add a column at the end in `src/schema.py`.

---

## Part C — Run it automatically on GitHub (twice a day)

### Step 1: Put the project on GitHub
Create a new **private** repository and push this folder to it.

### Step 2: Add the repository secrets
Go to your repo → **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
|---|---|---|
| Secret | `GOOGLE_SERVICE_ACCOUNT_JSON` | Open the `.json` key from Part A Step 4, copy **all of it**, and paste it here. |
| Secret | `GOOGLE_SHEET_ID` | The long ID from your sheet URL (Part A Step 1). |
| Secret *(optional)* | `YOUTUBE_API_KEY` | See Part E. Gives the full list of channel videos. |
| Secret *(optional)* | `CODA_API_TOKEN` | See Part G. Lets the Monday check read the live hub. |
| Secret *(optional)* | `ANTHROPIC_API_KEY` | See Part H. Lets Claude judge pages that load but look wrong. |
| Variable *(recommended)* | `FEEDS_CONTACT` | An email address for site owners, e.g. the PM Hub team inbox. Use the **Variables** tab, not Secrets. |

### Step 3: Test it
1. Go to the **Actions** tab → **PM Hub Feeds** → **Run workflow**.
2. Watch the log. You'll see each source and its row count, then `✓ events: N, blog: N, …`.
3. Open the Google Sheet: the four tabs are there. Then do Part B and the rows show up in the PM Hub.

After that it runs by itself at 09:17 and 21:17 UTC (about 2 AM and 2 PM Pacific). Each run
also attaches a JSON/CSV snapshot that you can download from the run page for 14 days.

---

## Part D — Run it on your own computer (optional)

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# No Google at all — writes out/events.json, blog.json, recordings.json, news.json (+ .csv):
python -m src.main --local

# Or point at the real sheet (copy .env.example to .env and fill it in), then:
python -m src.main
```

**Do this once before the first scheduled run:**

```bash
python scripts/save_fixtures.py   # save today's real pages as test fixtures
python -m pytest -q               # every test should pass
```

---

## Part E — Full YouTube history (optional, free)

YouTube's robots.txt asks robots not to read its RSS feeds, and this tool respects that.
Without a key, the **Recordings** table only lists videos embedded in chapter blog posts. For
the whole channel, use YouTube's official API, which is free at this volume:

1. In the same Google Cloud project, go to **APIs & Services → Library** → **YouTube Data API v3** → **Enable**.
2. **Credentials → Create credentials → API key**. Then click it → **Restrict key** → API
   restrictions → **YouTube Data API v3** → Save.
3. Add it as the `YOUTUBE_API_KEY` secret (Part C Step 2).

---

## Part F — The weekly health check

`.github/workflows/linkcheck.yml` runs every Monday at about 8 AM Pacific (or on demand:
**Actions → PM Hub Weekly Health Check → Run workflow**). It needs only the two Google secrets
from Part C; Parts G and H make it better.

It does two things:

1. **Checks every link** readers can click: event, registration, blog and video links from the
   Sheet, plus every link in the hub (PDU opportunities, templates' sources, Beyond PMI,
   programs, paths, certifications). One gentle request per link, robots.txt respected.
2. **Checks the pipeline is alive:** the twice-daily job ran in the last 36 hours, there is at
   least one upcoming event, and the blog and each news outlet have published recently.

Results go to the **Link Health** and **Health Checks** tabs and a row in **Run Log**. The run
page on GitHub shows the same report.

**If anything is Broken or a check Fails, the run fails and GitHub emails you.** Make sure
notifications are on: GitHub → your avatar → **Settings → Notifications → Actions** →
"Send notifications for failed workflows only". Add co-maintainers as repo collaborators so
they get the email too.

| Result | Meaning | What to do |
|---|---|---|
| **Broken** | 404, server error, unreachable, a "page not found" page, or a redirect to the site's home page | Fix or remove the link in the hub (or ignore it if it's an old event row) |
| **Suspect** | Loads, but doesn't mention the item it's listed for | Open it. The item may have moved. |
| **Blocked** | The site refuses automated checks (401/403/429) | Open it by hand once in a while. Some big sites block all cloud servers. |
| **Login** | Sends readers to a sign-in page | Usually expected (e.g. CCRS, the PMI Lexicon) |
| **Skipped** | robots.txt asks robots to stay away | Nothing; check by hand if it matters |

---

## Part G — Let the health check read the live hub (optional, recommended)

Without this, the Monday check uses `data/hub_links.csv`, a snapshot of the hub's links from
October 2026. It goes out of date as the hub changes. With a token, it reads the hub itself.

1. In Superhuman Docs / Coda, open **Account settings → API settings → Generate API token**.
2. Name it `PM Hub health check`. Restrict it to **Read only** and to the **PMI-LA PM Hub** doc.
3. Add it as the `CODA_API_TOKEN` secret. The doc ID defaults to the hub's (`2PnUJeapkp`);
   set a `CODA_DOC_ID` variable only if the hub moves to a new doc.

The token only reads. It can't change the hub.

---

## Part H — Let Claude review doubtful pages (optional, pennies a week)

Most links are judged by simple rules. A few each week land in **Suspect**: the page loads but
doesn't mention the item (e.g. an event that was quietly taken down and now shows the
calendar). With `ANTHROPIC_API_KEY` set, the check sends just those pages (title plus the first
3,000 characters) to Claude, which marks each one OK, Broken or still Suspect, with a reason.

* Model: `claude-haiku-5-5` by default (set a `LINKCHECK_MODEL` variable to change it).
* Expect a handful of calls a week, which costs a few cents.
* You can reuse WebinarHub's key or create a separate one at console.anthropic.com.

Without a key, Suspect links are simply listed for a person to open.

---

## Changing things

| I want to… | Edit |
|---|---|
| add or remove a news source | `feeds.yaml` (name, feed URL, topic, `enabled: false` to pause) |
| keep listicles or off-topic posts out of News | `filters` at the bottom of `feeds.yaml` (also clears matching rows already in the Sheet) |
| change what counts as "stale" in the health check | the thresholds at the top of `src/linkcheck.py` |
| refresh the hub-link snapshot | easiest: set `CODA_API_TOKEN` (Part G) and the snapshot is no longer used |
| look further ahead on the calendar | `CALENDAR_MONTHS_AHEAD` in `src/config.py` |
| read more blog pages | `BLOG_PAGES` in `src/config.py` |
| change the schedule | the `cron` line in `.github/workflows/feeds.yml` |
| add a column | append it in `src/schema.py`, then fill it in the collector |
| recognise a new event series prefix | `KNOWN_SERIES` in `src/parsing.py` (ALL-CAPS prefixes such as `HACKATHON |` are picked up automatically) |

---

## Troubleshooting

Because the Sheet is the source of truth, **troubleshooting almost always means opening the
Google Sheet or the Actions log.** You rarely need to touch code.

| Symptom | Likely cause |
|---|---|
| `403` / "permission denied" from Google | The sheet isn't shared with the robot's `client_email` (Part A Step 5), or it's set to Viewer instead of Editor. |
| "could not load credentials" / JSON error | The `GOOGLE_SERVICE_ACCOUNT_JSON` secret wasn't pasted in full. It must include the `{ … }` braces. |
| A table shows `⚠ 0 rows — existing data … left untouched` | That source changed its layout or was down. The other tables still updated and nothing was lost. Run `pytest` after `scripts/save_fixtures.py` to see which parser broke. |
| `robots.txt disallows …` | The site asked robots not to read that page. That is working as intended. Ask the site owner for a feed. |
| Lots of rows marked **Stale** | Those items are no longer listed on the source. That's normal for past events. Filter on `Freshness` in Coda if you want them hidden. |
| A news outlet shows `failed` or `0 items` | Its feed moved or died. Fix or disable it in `feeds.yaml`. |
| Coda looks stale | Click **Sync now** on the sync table, or check its auto-refresh setting. |
| The Monday check emails about **every** link on one site | That site was down or blocked the check that morning. If it's still failing next week, look at the site. |
| Health check: "Feeds job ran recently: Fail" | The twice-daily job stopped. Open the Actions tab: the job may be failing, or (in a public repo) GitHub may have paused the schedule after 60 days without commits. Re-enable it there. |

"""
Central settings. Everything a maintainer is likely to tweak lives here or in
feeds.yaml, so nobody has to dig through collector code.

Environment variables (all optional unless noted):
  FEEDS_CONTACT        an email or URL put in the User-Agent so site owners can
                       reach whoever runs this (strongly recommended)
  FEEDS_DELAY_SECONDS  pause between two requests to the same host (default 2)
  YOUTUBE_API_KEY      enables the official YouTube Data API for Recordings
  YOUTUBE_CHANNEL_ID   skip channel-ID discovery (default: discovered from the
                       channel page, falling back to KNOWN_CHANNEL_ID)
  GOOGLE_SHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON | GOOGLE_SERVICE_ACCOUNT_PATH
                       enable the Google Sheet export (see SETUP.md)
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

VERSION = "0.1"

PACIFIC = ZoneInfo("America/Los_Angeles")

# ── Politeness ───────────────────────────────────────────────────────────────
_CONTACT = os.environ.get("FEEDS_CONTACT", "").strip()
USER_AGENT = (
    f"PMHubFeeds/{VERSION} (PMI-LA PM Hub resource-hub sync; twice daily, low rate"
    + (f"; contact: {_CONTACT}" if _CONTACT else "")
    + ")"
)
REQUEST_DELAY_SECONDS = float(os.environ.get("FEEDS_DELAY_SECONDS", "2"))
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_RETRIES = 3

# ── PMI-LA site ──────────────────────────────────────────────────────────────
PMI_LA_BASE = "https://pmi-la.org"
# How many months past the current one to scan on the calendar.
CALENDAR_MONTHS_AHEAD = 3
# How many blog listing pages to read (6 posts per page on the current site).
BLOG_PAGES = 2
# Open each blog post to read its category label and any embedded YouTube video
# (one extra request per post). Set False to read the listing pages only.
BLOG_FETCH_DETAILS = True
# The chapter's own mailing address appears in every page footer; it is never an
# event venue, so the location parser ignores lines containing it.
CHAPTER_ADDRESS_MARKERS = ("10866 Washington Blvd",)

# ── YouTube ──────────────────────────────────────────────────────────────────
YOUTUBE_HANDLE_URL = "https://www.youtube.com/@PMI-LosAngeles"
# Discovered from the channel page on 2026-10-08. Used only if live discovery
# fails, so a YouTube page change can't break the Recordings table.
KNOWN_CHANNEL_ID = "UCoMM0sYo-pY3zdG19PegVfw"
YOUTUBE_MAX_VIDEOS = 200

# ── News ─────────────────────────────────────────────────────────────────────
FEEDS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "feeds.yaml")

SNIPPET_MAX_CHARS = 200


def now_pacific() -> datetime:
    return datetime.now(PACIFIC)

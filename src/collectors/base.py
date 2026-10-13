"""
Base class for all collectors.

Unlike WebinarHub (Playwright), every PM Hub source is server-rendered HTML or
a feed, so collectors use plain HTTP through a shared fetcher (src.fetching):
one polite session, robots.txt checked, a delay between requests.

Every collector's output passes through sanitize_rows() before it is returned,
which centrally enforces the same two guarantees as WebinarHub's base.py:

  1. No junk titles  — labels/buttons ("Register", "Continue reading", ...)
     and date-only strings are dropped.
  2. No duplicates   — at most one row per canonical URL within a run.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional

from src.parsing import canonical_url, clean

JUNK_TITLES = {
    "register", "register now", "register for this event", "learn more",
    "read more", "continue reading", "more", "details", "view details",
    "watch", "watch now", "click here", "here", "untitled", "no title",
    "no events to display", "no blog posts to display", "home", "calendar",
    "events", "blog", "next", "previous", "back",
}
_DATE_ONLY = re.compile(r"^[\w\s,.\-/]*\d{4}\s*$")
_TEMPLATE_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]|%\w+%")


def is_valid_title(title: Optional[str]) -> bool:
    t = clean(title)
    if len(t) < 4:
        return False
    if t.lower().rstrip(".!:") in JUNK_TITLES:
        return False
    if _TEMPLATE_PLACEHOLDER.search(t):          # unrendered '{{title}}' cards
        return False
    if _DATE_ONLY.match(t) and len(t) < 22:      # a bare 'October 8, 2026'
        return False
    return True


def sanitize_rows(rows: List[dict], title_field: str = "title",
                  url_field: str = "url", logger=None) -> List[dict]:
    """Drop junk titles, canonicalise URLs, de-duplicate by URL."""
    seen = set()
    cleaned: List[dict] = []
    junk = dupes = 0
    for r in rows:
        url = canonical_url(r.get(url_field))
        title = clean(r.get(title_field))
        if not url or not is_valid_title(title):
            junk += 1
            continue
        if url in seen:
            dupes += 1
            continue
        seen.add(url)
        r[url_field] = url
        r[title_field] = title
        cleaned.append(r)
    if logger and (junk or dupes):
        logger.info(f"Sanitized: kept {len(cleaned)}, dropped {junk} junk, {dupes} duplicate(s)")
    return cleaned


class BaseCollector(ABC):
    """Subclasses set TABLE (events/blog/recordings/news) and SOURCE_NAME and
    implement collect(). run() never raises: a failing source logs and returns
    an empty list, and main.py treats an empty list as 'leave the sheet alone'."""

    TABLE: str = ""
    SOURCE_NAME: str = "Unknown"
    TITLE_FIELD: str = "title"

    def __init__(self, fetcher, log=print):
        self.fetcher = fetcher
        self.log = log
        self.logger = logging.getLogger(f"collector.{self.SOURCE_NAME.lower()}")
        self.warnings: List[str] = []

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log(f"    ⚠ {msg}")

    @abstractmethod
    def collect(self) -> List[dict]:
        ...

    def run(self) -> List[dict]:
        rows = self.collect()
        for r in rows:
            r.setdefault("source", self.SOURCE_NAME)
        before = len(rows)
        rows = sanitize_rows(rows, title_field=self.TITLE_FIELD)
        if before != len(rows):
            self.log(f"    sanitized: kept {len(rows)} of {before}")
        return rows

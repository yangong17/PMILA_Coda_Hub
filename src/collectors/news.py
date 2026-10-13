"""
Generic PM-news collector: reads every enabled feed in feeds.yaml (RSS 2.0,
RSS 1.0/RDF or Atom — feedparser handles all three) and keeps ONLY headline,
outlet, published date and link. Article bodies are never stored.

Per-feed options in feeds.yaml:
  name, url, topic          required (topic is a free label, e.g. "Agile")
  enabled                   default true
  max_items                 default 20
  include_keywords          keep only headlines containing one of these words
                            (whole words, case-insensitive)
  exclude_url_patterns      drop links containing any of these (e.g. /sponsored/)

Global `filters` block in feeds.yaml (applies to every feed):
  english_only              drop headlines that read as another language
  exclude_title_patterns    case-insensitive regexes; a matching headline is
                            dropped (vendor listicles, software round-ups)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

import feedparser
import yaml

from src import config
from src.collectors.base import BaseCollector
from src.parsing import clean


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_feeds(path: str = config.FEEDS_FILE) -> List[dict]:
    feeds = _load_yaml(path).get("feeds", [])
    for fd in feeds:
        for req in ("name", "url"):
            if not fd.get(req):
                raise ValueError(f"feeds.yaml entry missing '{req}': {fd}")
    return [fd for fd in feeds if fd.get("enabled", True)]


def load_filters(path: str = config.FEEDS_FILE) -> dict:
    flt = _load_yaml(path).get("filters") or {}
    for pat in flt.get("exclude_title_patterns") or []:
        re.compile(pat)          # fail loudly on a typo, not silently per item
    return flt


# Short function words that are common in German/Spanish/French/Dutch/
# Portuguese headlines and rare in English ones. Two or more hits = not English.
_FOREIGN_WORDS = {
    "der", "die", "das", "und", "nicht", "mit", "ohne", "wie", "deiner", "deine",
    "ist", "für", "fur", "eine", "einen", "schon", "sind", "auf", "den", "dem",
    "el", "los", "las", "del", "una", "para", "con", "por", "qué", "cómo",
    "les", "des", "une", "pour", "avec", "est", "dans", "het", "een", "voor",
    "não", "uma", "como", "seu", "sua",
}


def looks_english(title: str) -> bool:
    words = re.findall(r"[^\W\d_]+", title.lower())
    return sum(w in _FOREIGN_WORDS for w in words) < 2


def keep_headline(title: str, filters: Optional[dict]) -> bool:
    """Apply the global feeds.yaml filters to one headline."""
    if not filters:
        return True
    if filters.get("english_only") and not looks_english(title):
        return False
    for pat in filters.get("exclude_title_patterns") or []:
        if re.search(pat, title, flags=re.IGNORECASE):
            return False
    return True


def _has_keyword(title: str, keywords: List[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", title, flags=re.IGNORECASE) for k in keywords)


def _published(entry) -> str:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return ""
    # feedparser normalises every date to a UTC struct_time.
    dt = datetime(*st[:6], tzinfo=timezone.utc)
    return dt.astimezone(config.PACIFIC).strftime("%Y-%m-%d %H:%M")


def parse_feed(raw: bytes, feed: dict, feed_url: Optional[str] = None,
               filters: Optional[dict] = None) -> List[dict]:
    parsed = feedparser.parse(raw, response_headers={"content-location": feed_url or feed["url"]})
    base = parsed.feed.get("link") or feed_url or feed["url"]
    include = [str(k) for k in feed.get("include_keywords") or []]
    exclude = feed.get("exclude_url_patterns") or []
    out = []
    for e in parsed.entries:
        title = clean(e.get("title"))
        link = e.get("link") or ""
        if link and not link.startswith(("http://", "https://")):
            link = urljoin(base, link)
        if link.startswith("http://"):
            link = "https://" + link[len("http://"):]
        if not title or not link:
            continue
        if any(p in link for p in exclude):
            continue
        if include and not _has_keyword(title, include):
            continue
        if not keep_headline(title, filters):
            continue
        out.append({
            "headline": title,
            "outlet": feed["name"],
            "published": _published(e),
            "topic": feed.get("topic", ""),
            "url": link,
        })
    out.sort(key=lambda r: r["published"], reverse=True)
    return out[: int(feed.get("max_items", 20))]


class NewsCollector(BaseCollector):
    TABLE = "news"
    SOURCE_NAME = "PM News"
    TITLE_FIELD = "headline"

    def __init__(self, fetcher, log=print, feeds: Optional[List[dict]] = None,
                 filters: Optional[dict] = None):
        super().__init__(fetcher, log)
        self.feeds = feeds if feeds is not None else load_feeds()
        self.filters = filters if filters is not None else load_filters()
        self.per_feed = {}

    def collect(self) -> List[dict]:
        rows: List[dict] = []
        for fd in self.feeds:
            try:
                items = parse_feed(self.fetcher.content(fd["url"]), fd, filters=self.filters)
                self.per_feed[fd["name"]] = len(items)
                self.log(f"    {fd['name']}: {len(items)} item(s)")
                if not items:
                    self.warn(f"{fd['name']} returned 0 items")
                for it in items:
                    it["source"] = f"RSS: {fd['name']}"
                rows.extend(items)
            except Exception as e:
                self.per_feed[fd["name"]] = f"failed: {e}"
                self.warn(f"{fd['name']} failed: {e}")
        return rows


def stored_row_filter(feeds: Optional[List[dict]] = None,
                      filters: Optional[dict] = None):
    """A keep(row) test for News rows already in the Sheet, so tightening a
    filter in feeds.yaml also clears matching items stored by earlier runs.
    Rows from outlets no longer listed (or disabled) are left alone; they age
    out under schema.RETENTION_DAYS like everything else."""
    feeds = feeds if feeds is not None else load_feeds()
    filters = filters if filters is not None else load_filters()
    include = {fd["name"]: [str(k) for k in fd.get("include_keywords") or []] for fd in feeds}

    def keep(row: dict) -> bool:
        title = row.get("headline") or ""
        if not keep_headline(title, filters):
            return False
        words = include.get(row.get("outlet") or "")
        return not words or _has_keyword(title, words)

    return keep

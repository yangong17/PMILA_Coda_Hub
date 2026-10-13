"""
PMI-LA YouTube recordings (@PMI-LosAngeles).

Channel ID discovery: read the channel page and look for the ID in the
canonical link / RSS <link> / embedded JSON. Falls back to config.KNOWN_CHANNEL_ID.

Video list — three routes, tried in order:

  1. YouTube Data API v3 (if YOUTUBE_API_KEY is set). The official, supported
     route: the channel's "uploads" playlist, full history, exact publish times.
     Free quota is ample (each run costs ~1 unit per 50 videos).
  2. The channel RSS feed (feeds/videos.xml?channel_id=...) — 15 latest videos.
     IMPORTANT: as of 2026-10-08 youtube.com/robots.txt contains
     `Disallow: /feeds/videos.xml` for all agents, and this project honours
     robots.txt, so this route is skipped while that rule stands. The code is
     kept (and tested against a fixture) so it starts working on its own if the
     rule is lifted.
  3. Videos embedded in PMI-LA blog posts (the blog collector records them).
     Title comes from YouTube's oEmbed endpoint when robots.txt allows it, else
     the blog post title. "Published" is then the blog post's date, which is an
     approximation of the upload date — the "Found Via" column says so.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

from src import config
from src.collectors.base import BaseCollector
from src.fetching import RobotsDisallowed
from src.parsing import clean

_CHANNEL_PATTERNS = (
    re.compile(r'<link[^>]+rel="canonical"[^>]+href="https://www\.youtube\.com/channel/(UC[\w-]{22})"'),
    re.compile(r'feeds/videos\.xml\?channel_id=(UC[\w-]{22})'),
    re.compile(r'"externalId"\s*:\s*"(UC[\w-]{22})"'),
    re.compile(r'<meta[^>]+itemprop="(?:identifier|channelId)"[^>]+content="(UC[\w-]{22})"'),
    re.compile(r'"channelId"\s*:\s*"(UC[\w-]{22})"'),
    re.compile(r'youtube\.com/channel/(UC[\w-]{22})'),
)
_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
API = "https://www.googleapis.com/youtube/v3"


def find_channel_id(html: str) -> Optional[str]:
    for pat in _CHANNEL_PATTERNS:
        m = pat.search(html or "")
        if m:
            return m.group(1)
    return None


def _pacific(ts: str) -> str:
    """ISO timestamp (any offset) -> 'YYYY-MM-DD HH:MM' Pacific."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo:
        dt = dt.astimezone(config.PACIFIC)
    return dt.strftime("%Y-%m-%d %H:%M")


def _video(video_id: str, title: str, published: str, via: str) -> dict:
    return {
        "title": clean(title),
        "published": published,
        "video_id": video_id,
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "found_via": via,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def parse_channel_feed(xml_bytes: bytes) -> List[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for e in root.findall(f"{_ATOM}entry"):
        vid = e.findtext(f"{_YT}videoId") or ""
        title = e.findtext(f"{_ATOM}title") or ""
        pub = e.findtext(f"{_ATOM}published") or ""
        if vid and title:
            out.append(_video(vid, title, _pacific(pub), "YouTube RSS feed"))
    return out


def parse_api_playlist_items(payload: dict) -> List[dict]:
    out = []
    for it in payload.get("items", []):
        sn = it.get("snippet", {})
        cd = it.get("contentDetails", {})
        vid = cd.get("videoId") or sn.get("resourceId", {}).get("videoId", "")
        title = sn.get("title", "")
        if not vid or title in ("Private video", "Deleted video"):
            continue
        pub = cd.get("videoPublishedAt") or sn.get("publishedAt", "")
        out.append(_video(vid, title, _pacific(pub), "YouTube Data API"))
    return out


class YouTubeCollector(BaseCollector):
    TABLE = "recordings"
    SOURCE_NAME = "PMI-LA YouTube"

    def __init__(self, fetcher, log=print, blog_rows: Optional[List[dict]] = None):
        super().__init__(fetcher, log)
        self.blog_rows = blog_rows or []
        self.channel_id = ""

    def discover_channel_id(self) -> str:
        override = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
        if override:
            return override
        try:
            cid = find_channel_id(self.fetcher.text(config.YOUTUBE_HANDLE_URL))
            if cid:
                self.log(f"    channel ID discovered from channel page: {cid}")
                return cid
            self.warn("channel ID not found in channel page HTML; using known ID")
        except Exception as e:
            self.warn(f"channel page fetch failed ({e}); using known ID")
        return config.KNOWN_CHANNEL_ID

    def via_api(self, key: str) -> List[dict]:
        ch = self.fetcher.json(f"{API}/channels?part=contentDetails&id={self.channel_id}&key={key}",
                               check_robots=False)
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        rows, token = [], ""
        while len(rows) < config.YOUTUBE_MAX_VIDEOS:
            url = (f"{API}/playlistItems?part=snippet,contentDetails&maxResults=50"
                   f"&playlistId={uploads}&key={key}" + (f"&pageToken={token}" if token else ""))
            page = self.fetcher.json(url, check_robots=False)
            rows.extend(parse_api_playlist_items(page))
            token = page.get("nextPageToken", "")
            if not token:
                break
        return rows

    def via_rss(self) -> List[dict]:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"
        return parse_channel_feed(self.fetcher.content(url))

    def via_blog_embeds(self) -> List[dict]:
        rows = []
        for post in self.blog_rows:
            vurl = post.get("video_url") or ""
            m = re.search(r"v=([A-Za-z0-9_-]{11})", vurl)
            if not m:
                continue
            vid = m.group(1)
            title = ""
            try:
                meta = self.fetcher.json(
                    "https://www.youtube.com/oembed?format=json&url=" + quote(vurl, safe=""))
                if (meta.get("author_url") or "").lower().endswith("/@pmi-losangeles") or \
                        "pmi" in (meta.get("author_name") or "").lower():
                    title = meta.get("title", "")
            except Exception as e:
                self.log(f"    (oEmbed unavailable for {vid}: {e})")
            rows.append(_video(vid, title or post.get("title", ""),
                               post.get("published", ""), "PMI-LA blog embed (date = post date)"))
        return rows

    def collect(self) -> List[dict]:
        self.channel_id = self.discover_channel_id()
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        rows: List[dict] = []
        if key:
            try:
                rows = self.via_api(key)
                self.log(f"    YouTube Data API → {len(rows)} video(s)")
            except Exception as e:
                self.warn(f"YouTube Data API failed: {e}")
        if not rows:
            try:
                rows = self.via_rss()
                self.log(f"    channel RSS feed → {len(rows)} video(s)")
            except RobotsDisallowed:
                self.warn("YouTube robots.txt disallows /feeds/videos.xml — RSS route skipped "
                          "(set YOUTUBE_API_KEY for the full video list)")
            except Exception as e:
                self.warn(f"channel RSS feed failed: {e}")
        # Blog embeds are merged in either way: they cover videos the RSS
        # window has rolled past, and dedupe-by-URL removes overlaps.
        seen = {r["video_id"] for r in rows}
        extra = [r for r in self.via_blog_embeds() if r["video_id"] not in seen]
        if extra:
            self.log(f"    blog-embedded videos → {len(extra)} extra")
        return rows + extra

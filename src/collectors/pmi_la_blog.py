"""
PMI-LA blog (pmi-la.org/blog, pages 1..BLOG_PAGES, 6 posts per page).

Listing cards give title, URL, date ("05 October 2026 at 12:45PM"), an optional
author byline and an excerpt. Categories are NOT on the cards, only on each
post's own page, so (if BLOG_FETCH_DETAILS) each post is opened once to read
its category label(s) and any embedded YouTube video — the latter also feeds
the Recordings table.

Like the events parser, this keys on URL patterns and text, not CSS classes.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from src import config
from src.collectors.base import BaseCollector, is_valid_title
from src.parsing import clean, parse_datetime_loose, snippet

BASE = config.PMI_LA_BASE
_POST_PATH = re.compile(r"^/blog/[^/?#]+/?$")
_DATE_IN_TEXT = re.compile(
    r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4}(?:\s+at\s+\d{1,2}:\d{2}\s*[AP]M)?)", re.I)
_YT_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|shorts/|live/)|youtu\.be/)"
                    r"([A-Za-z0-9_-]{11})")
_NOT_EXCERPT = {"continue reading", "read more", "more"}


def _post_href(href: str) -> Optional[str]:
    absu = urljoin(BASE + "/", href)
    p = urlsplit(absu)
    if p.netloc.lower() not in ("pmi-la.org", "www.pmi-la.org"):
        return None
    if not _POST_PATH.match(p.path) or p.query:
        return None
    return f"https://pmi-la.org{p.path.rstrip('/')}"


def _card_for(a: Tag, href: str) -> Tag:
    """Smallest ancestor that contains this post's links and no other post's."""
    node = a
    best = a
    for _ in range(8):
        node = node.parent
        if node is None or node.name in ("body", "html"):
            break
        hrefs = {_post_href(x["href"]) for x in node.find_all("a", href=True)}
        hrefs.discard(None)
        if hrefs == {href}:
            best = node
        else:
            break
    return best


def parse_blog_listing(html: str) -> List[dict]:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    titles: Dict[str, str] = {}
    anchors: Dict[str, Tag] = {}
    for a in soup.find_all("a", href=True):
        href = _post_href(a["href"])
        if not href:
            continue
        text = clean(a.get_text(" "))
        if text.lower() in _NOT_EXCERPT or not text:
            continue
        if len(text) > len(titles.get(href, "")):
            titles[href] = text
            anchors[href] = a

    posts = []
    for href, title in titles.items():
        card = _card_for(anchors[href], href)
        lines = [clean(x) for x in card.get_text("\n").split("\n")]
        lines = [l for l in lines if l]
        published, author = "", ""
        for i, l in enumerate(lines):
            m = _DATE_IN_TEXT.search(l)
            if m:
                dt = parse_datetime_loose(m.group(1))
                published = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                before = clean(l[:m.start()])
                if not before and i > 0 and lines[i - 1] != title:
                    before = lines[i - 1]
                author = re.sub(r"^(by|posted by)\s+", "", before, flags=re.I).strip(" ,|·-")
                break
        # Excerpt = every line after the title up to 'Continue reading'
        # (some excerpts span several short lines, e.g. 'Technology Committee'
        # / 'August 2026').
        parts: List[str] = []
        if title in lines:
            for l in lines[lines.index(title) + 1:]:
                if l.lower() in _NOT_EXCERPT:
                    break
                if _DATE_IN_TEXT.fullmatch(l):
                    continue
                parts.append(l)
        excerpt = " / ".join(parts) if all(len(p) < 40 for p in parts) else " ".join(parts)
        posts.append({"title": title, "url": href, "published": published,
                      "author": author if author != title else "",
                      "excerpt": snippet(excerpt, config.SNIPPET_MAX_CHARS)})
    return posts


def parse_blog_post(html: str) -> dict:
    """Category label(s) and first embedded YouTube video of a single post."""
    soup = BeautifulSoup(html, "lxml")
    video = ""
    for tag in soup.find_all(["iframe", "a", "embed"]):
        src = tag.get("src") or tag.get("href") or ""
        m = _YT_ID.search(src)
        if m:
            video = f"https://www.youtube.com/watch?v={m.group(1)}"
            break

    # Category links all point at blog?categoryId=N. The sidebar lists EVERY
    # category; a post's own labels are the category links outside that list.
    cat_links = [a for a in soup.find_all("a", href=True) if "categoryId=" in a["href"]]
    by_parent: Dict[int, List[Tag]] = {}
    for a in cat_links:
        container = a.find_parent(["ul", "ol", "nav", "aside", "div"])
        by_parent.setdefault(id(container), []).append(a)
    sidebar_ids = {k for k, v in by_parent.items() if len(v) >= 5}
    own = [clean(a.get_text(" ")) for k, v in by_parent.items() if k not in sidebar_ids for a in v]
    names = list(dict.fromkeys(n for n in own if n))

    if not names and cat_links:
        # Fallback: the post's own label(s) are printed as plain text near its
        # date. Every category also appears in the site-wide list (sometimes
        # twice, e.g. desktop + mobile menus), so a name is this post's only if
        # it shows up MORE often than the least-repeated category does.
        # Everything tied (the usual case when the post has no label we can see)
        # means "can't tell": better a blank Category than all sixteen.
        all_names = {clean(a.get_text(" ")) for a in cat_links}
        all_names.discard("")
        for t in soup(["script", "style", "noscript", "template"]):
            t.decompose()
        counts = Counter(clean(x) for x in soup.get_text("\n").split("\n"))
        floor = min((counts.get(n, 0) for n in all_names), default=0)
        names = [n for n in all_names if counts.get(n, 0) > max(floor, 1)]
        if len(names) > 4:                      # still looks like the whole list
            names = []
    return {"category": ", ".join(sorted(names)), "video_url": video}


class PmiLaBlogCollector(BaseCollector):
    TABLE = "blog"
    SOURCE_NAME = "PMI-LA Blog"

    def collect(self) -> List[dict]:
        posts: List[dict] = []
        for page in range(1, config.BLOG_PAGES + 1):
            url = f"{BASE}/blog" + (f"?page={page}" if page > 1 else "")
            try:
                found = parse_blog_listing(self.fetcher.text(url))
                self.log(f"    {url} → {len(found)} post(s)")
                posts.extend(found)
            except Exception as e:
                self.warn(f"blog page {page} failed: {e}")
        posts = [p for p in posts if is_valid_title(p["title"])]
        if config.BLOG_FETCH_DETAILS:
            for p in posts:
                try:
                    p.update(parse_blog_post(self.fetcher.text(p["url"])))
                except Exception as e:
                    self.warn(f"post detail {p['url']} failed: {e}")
        return posts

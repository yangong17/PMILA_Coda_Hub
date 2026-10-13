"""
PMI-LA events (pmi-la.org, an "MG2 Manager" server-rendered site).

1. Discover event IDs from the home page and the calendar month views.
   NOTE: the calendar's `month` parameter is ZERO-based (month=9 is October,
   month=10 is November), verified against the live site on 2026-10-08.
2. Open each event page (calendar?eventId=NNN) and read the labelled fields.

The detail parser works on the page's visible TEXT LINES and their labels
("Date:", "Hour:", "Members:", "PDUs:", a "Location" heading ...) rather than on
CSS classes, so a theme/markup change on the site is far less likely to break
it than a selector-based scraper would be.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, parse_qs

from bs4 import BeautifulSoup

from src import config
from src.collectors.base import BaseCollector
from src.parsing import (clean, extract_pdus, extract_prices, parse_date_range,
                         parse_time_range, snippet, split_series)

BASE = config.PMI_LA_BASE
_EVENT_ID = re.compile(r"[?&]eventId=(\d+)")
_OG_DATE_SUFFIX = re.compile(r"\s+-\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\s*$")

# Lines that start a new labelled field — used to stop multi-line captures.
_LABEL_START = re.compile(
    r"^(date|dates|hour|hours|time|pdus?|members?|non[\s-]?members?|students?|military|"
    r"pricing|price|register|registration|description|speakers?|presenters?|"
    r"share|add to calendar|contact|location|it is no longer possible)\b", re.I)
_VIRTUAL_WORDS = {"virtual", "online", "live webinar", "webinar", "zoom", "virtual event",
                  "microsoft teams", "teams", "online event"}
_ADDRESS_HINT = re.compile(r"\d{2,6}\s+\w+|,\s*[A-Z]{2}\b|\b\d{5}\b|\b(st|ave|blvd|hwy|rd|dr|way)\b\.?", re.I)
_REG_CLOSED = re.compile(r"no longer possible to register|registration (is )?closed|sold out", re.I)


def page_lines(soup: BeautifulSoup) -> List[str]:
    """Visible text as clean lines; a short 'Label:' line is joined to the
    value that follows it (MG2 renders 'PDUs:' and '1.5' as siblings)."""
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    raw = [clean(x) for x in soup.get_text("\n").split("\n")]
    raw = [x for x in raw if x]
    out: List[str] = []
    i = 0
    while i < len(raw):
        line = raw[i]
        if line.endswith(":") and len(line) <= 30 and i + 1 < len(raw):
            line = f"{line} {raw[i + 1]}"
            i += 1
        out.append(line)
        i += 1
    return out


def _value_after(lines: List[str], label: str) -> str:
    pat = re.compile(rf"^{label}\s*:\s*(.+)$", re.I)
    for l in lines:
        m = pat.match(l)
        if m:
            return m.group(1).strip()
    return ""


def event_ids_from_listing(html: str) -> Dict[str, str]:
    """{event_id: listing title} for every pmi-la.org event link on a page."""
    soup = BeautifulSoup(html, "lxml")
    found: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        absu = urljoin(BASE + "/", href)
        host = urlsplit(absu).netloc.lower()
        if host not in ("pmi-la.org", "www.pmi-la.org"):
            continue
        if "calendar" not in urlsplit(absu).path:
            continue
        m = _EVENT_ID.search(absu)
        if not m:
            continue
        title = clean(a.get_text(" "))
        prev = found.get(m.group(1), "")
        if len(title) > len(prev) and title.lower() not in ("learn more", "register", "details"):
            found[m.group(1)] = title
        else:
            found.setdefault(m.group(1), prev)
    return found


def _title(soup: BeautifulSoup, lines: List[str]) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = _OG_DATE_SUFFIX.sub("", clean(og["content"]))
        if t:
            return t
    for tag in ("h1", "h2"):
        h = soup.find(tag)
        if h and clean(h.get_text(" ")):
            return clean(h.get_text(" "))
    return clean(soup.title.get_text()) if soup.title else ""


def _location(lines: List[str]) -> Tuple[str, str]:
    """(format, location) where format is Virtual / In person / Hybrid / ''."""
    captured: List[str] = []
    for i, l in enumerate(lines):
        if l.lower().rstrip(":") in ("location", "venue", "where"):
            for nxt in lines[i + 1:i + 6]:
                if _LABEL_START.match(nxt) or len(nxt) > 90:
                    break
                captured.append(nxt)
            break
    captured = [c for c in captured
                if not any(m in c for m in config.CHAPTER_ADDRESS_MARKERS)]
    virtual = any(c.lower() in _VIRTUAL_WORDS for c in captured)
    if not captured:  # no Location block: accept a standalone 'Virtual' line
        virtual = any(l.lower() in ("virtual", "live webinar", "online") for l in lines)
    physical = [c for c in captured if c.lower() not in _VIRTUAL_WORDS]
    in_person = bool(physical) and any(_ADDRESS_HINT.search(p) for p in physical)
    loc = re.sub(r"\s+,", ",", ", ".join(physical)) if in_person else ""
    if virtual and in_person:
        return "Hybrid", loc
    if in_person:
        return "In person", loc
    if virtual:
        return "Virtual", "Virtual"
    return "", ""


_REG_HREF = re.compile(r"(/login|/register|registration)[^?#]*\?(?:[^#]*&)?eventId=\d+", re.I)


def _register_url(soup: BeautifulSoup, page_url: str) -> str:
    """The event's own registration link: an href carrying an eventId on a
    login/registration path (MG2: /login?eventId=NNN; partner chapters:
    /event-registration?eventId=NNN). A site-wide 'Register'/'Join' nav link
    has no eventId, so it can't be mistaken for one."""
    fallback = ""
    base = page_url if page_url.startswith("http") else BASE + "/"
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if _REG_HREF.search(href):
            return href
        if not fallback and "register for this event" in clean(a.get_text(" ")).lower():
            fallback = href
    return fallback


def _description(soup: BeautifulSoup) -> str:
    for attr, name in (("property", "og:description"), ("name", "description")):
        m = soup.find("meta", attrs={attr: name})
        if m and m.get("content"):
            text = clean(m["content"])
            if len(text) > 25 and text.lower() != "calendar":
                return snippet(text, config.SNIPPET_MAX_CHARS)
    paras = [clean(p.get_text(" ")) for p in soup.find_all("p")]
    paras = [p for p in paras if len(p) > 60 and not _LABEL_START.match(p)]
    return snippet(paras[0], config.SNIPPET_MAX_CHARS) if paras else ""


def parse_event_detail(html: str, url: str, event_id: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    title = _title(soup, [])
    register_url = _register_url(soup, url)
    description = _description(soup)
    lines = page_lines(soup)

    date_text = _value_after(lines, "date") or _value_after(lines, "dates")
    start_date, end_date = parse_date_range(date_text)
    hour_text = _value_after(lines, "hour") or _value_after(lines, "time")
    start_time, end_time = parse_time_range(hour_text)
    recurrence = ""
    for l in lines:
        if re.fullmatch(r"(every|each)\s+(day|week|weekday|monday|tuesday|wednesday|"
                        r"thursday|friday|saturday|sunday)s?", l, re.I):
            recurrence = l
            break

    prices = extract_prices(lines)
    pdus, pdu_details, triangle = extract_pdus(lines)
    fmt, location = _location(lines)
    series, short_title = split_series(title)
    closed = any(_REG_CLOSED.search(l) for l in lines)

    return {
        "title": short_title or title,
        "series": series,
        "full_title": title,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "recurrence": recurrence,
        "time_zone": "PT" if start_time else "",
        "format": fmt,
        "location": location,
        "member_price": prices["member"],
        "non_member_price": prices["non_member"],
        "student_military_price": prices["student_military"],
        "pdus": pdus,
        "pdu_details": pdu_details,
        "talent_triangle": triangle,
        "registration": "Closed" if closed else ("Open" if register_url else ""),
        "register_url": "" if closed else register_url,
        "description": description,
        "event_id": event_id,
        "url": url,
    }


class PmiLaEventsCollector(BaseCollector):
    TABLE = "events"
    SOURCE_NAME = "PMI-LA Calendar"

    def listing_urls(self, today=None) -> List[str]:
        today = today or config.now_pacific().date()
        urls = [BASE + "/"]
        y, m0 = today.year, today.month - 1   # site uses 0-based months
        for _ in range(config.CALENDAR_MONTHS_AHEAD + 1):
            urls.append(f"{BASE}/calendar?month={m0}&year={y}")
            m0 += 1
            if m0 == 12:
                m0, y = 0, y + 1
        return urls

    def collect(self) -> List[dict]:
        ids: Dict[str, str] = {}
        for u in self.listing_urls():
            try:
                found = event_ids_from_listing(self.fetcher.text(u))
                self.log(f"    {u} → {len(found)} event link(s)")
                for k, v in found.items():
                    if len(v) > len(ids.get(k, "")):
                        ids[k] = v
            except Exception as e:
                self.warn(f"listing {u} failed: {e}")
        if not ids:
            self.warn("no event links found on any listing page (layout change?)")
            return []

        rows = []
        for eid in sorted(ids, key=int):
            url = f"{BASE}/calendar?eventId={eid}"
            try:
                row = parse_event_detail(self.fetcher.text(url), url, eid)
            except Exception as e:
                self.warn(f"event {eid} failed: {e}")
                continue
            if not row["full_title"]:
                row["full_title"] = ids[eid]
                row["series"], row["title"] = split_series(ids[eid])
            if not row["start_date"]:
                self.warn(f"event {eid}: no date found on detail page")
            rows.append(row)
        return rows

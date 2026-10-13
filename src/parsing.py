"""
Small, pure text helpers shared by the collectors. Everything here is
deterministic and network-free, so it is what the unit tests cover most.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as _dp

# ── whitespace / text ────────────────────────────────────────────────────────

def clean(text: Optional[str]) -> str:
    """Collapse whitespace, unescape stray HTML entities, trim."""
    if not text:
        return ""
    # Some MG2 pages double-escape (&amp;quot;) so one entity survives parsing.
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("​", "")
    return " ".join(text.split())


def snippet(text: Optional[str], limit: int = 200) -> str:
    """A teaser of at most `limit` characters, cut on a word boundary."""
    t = clean(text)
    if len(t) <= limit:
        return t
    cut = t[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-–—") + "…"


# ── URLs ─────────────────────────────────────────────────────────────────────

_TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|ref|cmpid)$", re.I)


def canonical_url(url: Optional[str]) -> str:
    """Stable identity for a link: https scheme kept as-is, tracking params and
    #fragments removed, host lower-cased. Used as the merge key everywhere."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACKING_PARAMS.match(k)]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


# ── dates ────────────────────────────────────────────────────────────────────

_ORDINAL = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.I)
_MONTH_RE = re.compile(
    r"\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|"
    r"sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\b", re.I)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_RANGE_SPLIT = re.compile(r"\s+(?:to|through|thru|until)\s+|\s*[–—]\s*|\s+-\s+", re.I)


def _parse_one(text: str) -> Optional[date]:
    try:
        return _dp.parse(text, fuzzy=False, default=datetime(1900, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


def parse_date_range(text: Optional[str]) -> Tuple[str, str]:
    """'October 8th, 2026'                  -> ('2026-10-08', '2026-10-08')
       'September 19th to October 24th, 2026' -> ('2026-09-19', '2026-10-24')
       'October 19th to 24th, 2026'          -> ('2026-10-19', '2026-10-24')
       'December 30th, 2026 to January 2nd, 2027' -> both years honoured.
    Returns ('', '') when nothing parseable is found."""
    if not text:
        return "", ""
    t = _ORDINAL.sub(r"\1", clean(text))
    t = re.sub(r"^(date|dates|when)\s*:\s*", "", t, flags=re.I)
    pieces = [p.strip(" ,") for p in _RANGE_SPLIT.split(t, maxsplit=1) if p.strip(" ,")]
    if not pieces:
        return "", ""
    right = pieces[-1]
    if len(pieces) > 1 and not _MONTH_RE.search(right):   # 'October 19 to 24, 2026'
        m = _MONTH_RE.search(pieces[0])
        if m:
            right = f"{m.group(0)} {right}"
    end = _parse_one(right) if _MONTH_RE.search(right) and _YEAR_RE.search(right) else None
    if end is None:
        return "", ""
    if len(pieces) == 1:
        return end.isoformat(), end.isoformat()
    left = pieces[0]
    if not _MONTH_RE.search(left):           # '19 to 24th, 2026' style
        left = f"{end.strftime('%B')} {left}"
    if not _YEAR_RE.search(left):
        left = f"{left}, {end.year}"
    start = _parse_one(left)
    if start is None:
        return end.isoformat(), end.isoformat()
    if start > end and not _YEAR_RE.search(pieces[0]):
        start = start.replace(year=start.year - 1)   # 'Dec 30 to Jan 2, 2027'
    return start.isoformat(), end.isoformat()


def parse_datetime_loose(text: Optional[str]) -> Optional[datetime]:
    """'05 October 2026 at 12:45PM' / RFC-822 / ISO -> datetime (naive or aware)."""
    if not text:
        return None
    t = re.sub(r"\bat\b", " ", clean(text), flags=re.I)
    try:
        return _dp.parse(t, fuzzy=True)
    except (ValueError, OverflowError):
        return None


# ── times ────────────────────────────────────────────────────────────────────

_TIME_TOKEN = re.compile(
    r"(noon|midnight|\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?)", re.I)


def _norm_time(tok: str, fallback_meridiem: str = "") -> str:
    tok = tok.strip().lower().replace(".", "").replace(" ", "")
    if tok == "noon":
        return "12:00 PM"
    if tok == "midnight":
        return "12:00 AM"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", tok)
    if not m:
        return ""
    hour, minute, mer = int(m.group(1)), m.group(2) or "00", (m.group(3) or fallback_meridiem)
    if not mer or not (1 <= hour <= 12):
        return ""
    return f"{hour}:{minute} {mer.upper()}"


def parse_time_range(text: Optional[str]) -> Tuple[str, str]:
    """'Hour: 6:00PM to 7:30PM' -> ('6:00 PM', '7:30 PM');
       '10 - 11:30am' -> ('10:00 AM', '11:30 AM'). ('', '') if none."""
    if not text:
        return "", ""
    t = re.sub(r"^(hour|hours|time)\s*:\s*", "", clean(text), flags=re.I)
    parts = _RANGE_SPLIT.split(t, maxsplit=1)
    toks = []
    for p in parts:
        m = _TIME_TOKEN.search(p)
        if m:
            toks.append(m.group(1))
    if not toks:
        return "", ""
    end_mer = re.search(r"([ap])\.?m", toks[-1], re.I)
    end_mer = (end_mer.group(1) + "m").lower() if end_mer else ""
    start = _norm_time(toks[0], end_mer)
    end = _norm_time(toks[1], "") if len(toks) > 1 else ""
    return start, end


# ── prices ───────────────────────────────────────────────────────────────────

_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")


def parse_price(text: Optional[str]):
    """'$1,100.00' -> 1100.0, 'Free' -> 0.0, '' / unparseable -> None."""
    t = clean(text)
    if not t:
        return None
    m = _MONEY.search(t)
    if m:
        return float(m.group(1).replace(",", ""))
    if re.search(r"\b(free|no cost|complimentary|\$0\b)", t, re.I):
        return 0.0
    m = re.fullmatch(r"([\d,]+(?:\.\d{1,2})?)\s*(usd)?", t, re.I)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


_PRICE_LINE = re.compile(
    r"^(?P<label>non[\s-]?members?|members?|students?\s*(?:and|&|/)\s*military|"
    r"students?|military|general(?: admission)?)\s*(?:price|rate|fee)?\s*:\s*(?P<value>.+)$",
    re.I)


def extract_prices(lines: Iterable[str]) -> dict:
    """Find member / non-member / student-military prices in page lines.
    The first occurrence of each label wins. Also understands the inline form
    'Pricing $5.00 (members), $10.00 (non-members)'."""
    out = {"member": None, "non_member": None, "student_military": None}
    for line in lines:
        m = _PRICE_LINE.match(line.strip())
        if m:
            label = m.group("label").lower()
            if label.startswith("non"):
                key = "non_member"
            elif label.startswith("member"):
                key = "member"
            elif label.startswith(("student", "military")):
                key = "student_military"
            else:
                continue
            if out[key] is None:
                out[key] = parse_price(m.group("value"))
            continue
        for amount, who in re.findall(r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*\(([^)]+)\)", line):
            who = who.lower()
            key = ("non_member" if who.startswith("non") else
                   "member" if who.startswith("member") else None)
            if key and out[key] is None:
                out[key] = float(amount.replace(",", ""))
    return out


# ── PDUs ─────────────────────────────────────────────────────────────────────

_PDU_LABEL = re.compile(r"^PDUs?\s*:\s*([\d.]+)", re.I)
_PDU_INLINE = re.compile(r"(\d+(?:\.\d+)?)\s*PDUs?\b", re.I)
TALENT_TRIANGLE = ("Ways of Working", "Power Skills", "Business Acumen")


def extract_pdus(lines: List[str]) -> Tuple[Optional[float], str, str]:
    """Return (pdu_count, pdu_text, talent_triangle_categories)."""
    count = None
    pdu_lines = [l for l in lines if re.search(r"\bPDUs?\b", l, re.I)]
    for l in pdu_lines:
        m = _PDU_LABEL.match(l.strip())
        if m:
            try:
                count = float(m.group(1).rstrip("."))
            except ValueError:
                pass
            break
    if count is None:
        for l in pdu_lines:
            m = _PDU_INLINE.search(l)
            if m:
                count = float(m.group(1))
                break
    # Short lines only: the descriptive ones ('3 PDU – Ways of Working'), not
    # whole marketing paragraphs that happen to mention PDUs.
    detail = [clean(l) for l in pdu_lines if not _PDU_LABEL.match(l.strip()) and len(l) <= 160]
    text = snippet("; ".join(dict.fromkeys(detail)), 200)
    # Only short label-like lines ('3 PDU – Ways of Working', 'Leadership =
    # Power Skills'), so a nav menu or long paragraph can't add categories.
    short = " ".join(l for l in lines if len(l) <= 60).lower()
    cats = [c for c in TALENT_TRIANGLE if c.lower() in short]
    if count is not None and count == int(count):
        count = float(int(count))
    return count, text, ", ".join(cats)


# ── series prefixes ──────────────────────────────────────────────────────────

# Known PMI-LA series labels (normalised spelling). Matching is case-insensitive,
# so 'Multi-Chapter | ...' and 'MULTI-CHAPTER | ...' land in the same series.
KNOWN_SERIES = {
    "MULTI-CHAPTER": "MULTI-CHAPTER",
    "MULTI CHAPTER": "MULTI-CHAPTER",
    "MULTICHAPTER": "MULTI-CHAPTER",
    "WEBINAR": "WEBINAR",
    "FLAGSHIP": "FLAGSHIP",
    "BOOK CLUB": "BOOK CLUB",
    "NETWORKING": "NETWORKING",
    "WORKSHOP": "WORKSHOP",
    "SOCIAL": "SOCIAL",
    "CAREER CONNECT": "CAREER CONNECT",
    "VOLUNTEER": "VOLUNTEER",
    "PMO SIG": "PMO SIG",
}
_PREFIX = re.compile(r"^\s*([^|:]{2,30}?)\s*[|:]\s*(.+)$")
# Unknown prefixes are only accepted if they look like a label: ALL CAPS words.
_LABELISH = re.compile(r"^[A-Z0-9][A-Z0-9&/\- ]{1,28}$")
_KEYWORD_SERIES = ((re.compile(r"\bprep(aration)? course\b|\bexam prep\b", re.I), "EXAM PREP"),)


def split_series(title: Optional[str]) -> Tuple[str, str]:
    """'MULTI-CHAPTER | Own the Room' -> ('MULTI-CHAPTER', 'Own the Room')
       'WEBINAR: AI Powered EA'      -> ('WEBINAR', 'AI Powered EA')
       'Status: Green. Feeling: Red.' -> ('', 'Status: Green. Feeling: Red.')
       'PMP® (In-Person) Prep Course' -> ('EXAM PREP', <unchanged>)"""
    t = clean(title)
    m = _PREFIX.match(t)
    if m:
        raw, rest = m.group(1).strip(), m.group(2).strip()
        norm = re.sub(r"\s+", " ", raw.upper())
        if norm in KNOWN_SERIES:
            return KNOWN_SERIES[norm], rest
        if _LABELISH.match(raw) and len(raw.split()) <= 3:
            return norm, rest
    for pattern, label in _KEYWORD_SERIES:
        if pattern.search(t):
            return label, t
    return "", t

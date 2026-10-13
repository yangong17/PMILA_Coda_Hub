from datetime import date

import pytest

from src.parsing import (canonical_url, extract_pdus, extract_prices, parse_date_range,
                         parse_price, parse_time_range, snippet, split_series)


# ── dates ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("October 8th, 2026", ("2026-10-08", "2026-10-08")),
    ("Date: October 22nd, 2026", ("2026-10-22", "2026-10-22")),
    ("September 19th to October 24th, 2026", ("2026-09-19", "2026-10-24")),
    ("October 19th to 24th, 2026", ("2026-10-19", "2026-10-24")),
    ("December 30th, 2026 to January 2nd, 2027", ("2026-12-30", "2027-01-02")),
    ("Dec 30 to Jan 2, 2027", ("2026-12-30", "2027-01-02")),
    ("Oct 3 2026", ("2026-10-03", "2026-10-03")),
    ("", ("", "")),
    ("TBD", ("", "")),
    ("Every Saturday", ("", "")),
])
def test_parse_date_range(text, expected):
    assert parse_date_range(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Hour: 6:00PM to 7:30PM", ("6:00 PM", "7:30 PM")),
    ("8:30AM to 5:30PM", ("8:30 AM", "5:30 PM")),
    ("10 - 11:30am", ("10:00 AM", "11:30 AM")),
    ("noon to 1pm", ("12:00 PM", "1:00 PM")),
    ("7:00 p.m.", ("7:00 PM", "")),
    ("", ("", "")),
])
def test_parse_time_range(text, expected):
    assert parse_time_range(text) == expected


# ── prices ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("$5.00", 5.0), ("$1100.00", 1100.0), ("$1,100.00", 1100.0), ("Free", 0.0),
    ("FREE for members", 0.0), ("$0", 0.0), ("25", 25.0), ("", None), ("TBD", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_extract_prices_labelled_lines():
    lines = ["Students and Military: $650.00", "Members: $950.00", "Non members: $1100.00"]
    assert extract_prices(lines) == {"member": 950.0, "non_member": 1100.0, "student_military": 650.0}


def test_extract_prices_non_member_not_mistaken_for_member():
    # 'Non members' contains 'members' — must not overwrite the member price.
    assert extract_prices(["Non members: $10.00", "Members: $5.00"]) == \
        {"member": 5.0, "non_member": 10.0, "student_military": None}


def test_extract_prices_free_and_inline_forms():
    assert extract_prices(["Members: Free", "Non members: Free"])["non_member"] == 0.0
    inline = extract_prices(["Pricing $5.00 (members), $10.00 (non-members)"])
    assert inline["member"] == 5.0 and inline["non_member"] == 10.0


def test_extract_prices_missing_is_none_not_zero():
    assert extract_prices(["Speaker: Jane"]) == {"member": None, "non_member": None, "student_military": None}


# ── PDUs ─────────────────────────────────────────────────────────────────────
def test_extract_pdus_label_and_triangle():
    lines = ["PDUs: 3", "3 PDU – Ways of Working", "Some long paragraph"]
    count, text, tri = extract_pdus(lines)
    assert count == 3.0 and "Ways of Working" in text and tri == "Ways of Working"


def test_extract_pdus_decimal_and_inline_fallback():
    assert extract_pdus(["PDUs: 1.5"])[0] == 1.5
    assert extract_pdus(["Join us for breakfast and 2 PDUs."])[0] == 2.0
    assert extract_pdus(["No credit info"]) == (None, "", "")


# ── series prefixes ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,series,rest", [
    ("MULTI-CHAPTER | Own the Room in 3 Seconds", "MULTI-CHAPTER", "Own the Room in 3 Seconds"),
    ("Multi-Chapter | Leading Change Beyond the Gantt Chart", "MULTI-CHAPTER", "Leading Change Beyond the Gantt Chart"),
    ("WEBINAR: AI Powered EA (Enterprise Architecture)", "WEBINAR", "AI Powered EA (Enterprise Architecture)"),
    ("FLAGSHIP | Fireside Chat on Sustainability", "FLAGSHIP", "Fireside Chat on Sustainability"),
    ('BOOK CLUB | Chapters 7-12 of "How to Measure Anything"', "BOOK CLUB", 'Chapters 7-12 of "How to Measure Anything"'),
    ("PMO SIG: Quarterly Meetup", "PMO SIG", "Quarterly Meetup"),
    ("HACKATHON | Sound of Earth", "HACKATHON", "Sound of Earth"),          # unknown but label-like
    ("PMP® (In-Person) Prep Course (Fall 2026 Session)", "EXAM PREP", "PMP® (In-Person) Prep Course (Fall 2026 Session)"),
])
def test_split_series(title, series, rest):
    assert split_series(title) == (series, rest)


@pytest.mark.parametrize("title", [
    "Status: Green. Feeling: Red. The mental health of the person",  # colon in prose
    "Agile at Scale: Lessons Learned",                               # mixed case → not a label
    "Networking Night in Santa Monica",                              # no separator
])
def test_split_series_leaves_ordinary_titles_alone(title):
    assert split_series(title) == ("", title)


# ── URLs / text ──────────────────────────────────────────────────────────────
def test_canonical_url_strips_tracking_and_fragment():
    u = "https://www.InfoQ.com/presentations/mergequeue/?utm_campaign=x&utm_source=infoq&id=7#top"
    assert canonical_url(u) == "https://www.infoq.com/presentations/mergequeue/?id=7"
    assert canonical_url("//www.youtube.com/embed/abc") == "https://www.youtube.com/embed/abc"


def test_snippet_limits_length_on_word_boundary():
    s = snippet("word " * 100, 200)
    assert len(s) <= 200 and s.endswith("…") and "  " not in s
    assert snippet("short &amp; sweet") == "short & sweet"

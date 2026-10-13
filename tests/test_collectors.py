"""Collector + merge tests against the saved fixtures (no network)."""
import os
from datetime import date

import pytest

from src.catalogue import event_status, merge
from src.collectors.base import is_valid_title, sanitize_rows
from src.collectors.news import NewsCollector, load_feeds, parse_feed
from src.collectors.pmi_la_blog import PmiLaBlogCollector, parse_blog_listing
from src.collectors.pmi_la_events import (PmiLaEventsCollector, event_ids_from_listing,
                                          parse_event_detail)
from src.collectors.youtube import YouTubeCollector, find_channel_id, parse_channel_feed
from src.export.sheets import rows_from_values, values_from_rows
from src.fetching import FixtureFetcher, RobotsDisallowed
from src import schema

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
MANIFEST = os.path.join(FIX, "manifest.json")


@pytest.fixture(scope="module")
def fetcher():
    return FixtureFetcher(MANIFEST, log=lambda *_: None)


def read(rel):
    with open(os.path.join(FIX, rel), encoding="utf-8") as f:
        return f.read()


# ── dedupe / sanitize ────────────────────────────────────────────────────────
def test_sanitize_dedupes_by_canonical_url_and_drops_junk():
    rows = [
        {"title": "Real Title One", "url": "https://x.org/a?utm_source=feed"},
        {"title": "Real Title One (again)", "url": "https://X.org/a#frag"},   # same item
        {"title": "Register", "url": "https://x.org/b"},
        {"title": "October 8, 2026", "url": "https://x.org/c"},
        {"title": "{{title}}", "url": "https://x.org/d"},
        {"title": "No link here", "url": ""},
    ]
    out = sanitize_rows(rows)
    assert [r["url"] for r in out] == ["https://x.org/a"]


def test_is_valid_title():
    assert is_valid_title("Leading Change Beyond the Gantt Chart")
    for junk in ("Continue reading", "Learn more", "REGISTER FOR THIS EVENT", "Oct 3 2026", ""):
        assert not is_valid_title(junk)


def test_merge_keeps_unseen_rows_and_never_blanks_fields():
    existing = [
        {"url": "https://a.org/1", "title": "Old", "author": "Ann", "first_seen": "T0", "last_updated": "T0"},
        {"url": "https://a.org/2", "title": "Gone from site", "first_seen": "T0", "last_updated": "T0"},
    ]
    fresh = [{"url": "https://a.org/1?utm_medium=x", "title": "New title", "author": ""},
             {"url": "https://a.org/3", "title": "Brand new"}]
    rows = {r["url"]: r for r in merge("blog", existing, fresh, now="T1")}
    assert set(rows) == {"https://a.org/1", "https://a.org/2", "https://a.org/3"}
    assert rows["https://a.org/1"]["title"] == "New title"
    assert rows["https://a.org/1"]["author"] == "Ann"            # blank didn't overwrite
    assert rows["https://a.org/1"]["first_seen"] == "T0"
    assert rows["https://a.org/1"]["freshness"] == "Current"
    assert rows["https://a.org/2"]["freshness"] == "Stale"       # kept, flagged


def test_event_status():
    today = date(2026, 10, 8)
    assert event_status("2026-10-14", "2026-10-14", today) == "Upcoming"
    assert event_status("2026-10-08", "2026-10-08", today) == "Today"
    assert event_status("2026-09-19", "2026-10-24", today) == "In progress"
    assert event_status("2026-10-03", "2026-10-03", today) == "Past"
    assert event_status("", "", today) == ""


def test_sheet_round_trip_is_by_header_name():
    rows = [{"url": "https://e.org/1", "title": "T", "member_price": 5.0, "pdus": None}]
    values = values_from_rows("events", rows)
    assert values[0] == schema.headers("events")
    # Reverse the columns, as if someone dragged them around in the Sheet.
    shuffled = [list(reversed(r)) for r in values]
    back = rows_from_values("events", shuffled)[0]
    assert back["url"] == "https://e.org/1" and back["member_price"] == 5.0 and back["pdus"] is None


# ── events ───────────────────────────────────────────────────────────────────
def test_calendar_month_param_is_zero_based():
    urls = PmiLaEventsCollector(None).listing_urls(today=date(2026, 10, 8))
    assert "https://pmi-la.org/calendar?month=9&year=2026" in urls      # October
    assert "https://pmi-la.org/calendar?month=0&year=2027" in urls      # January


def test_listing_finds_ids_and_ignores_other_links():
    ids = event_ids_from_listing(read("pages/calendar_2026_10.html"))
    assert set(ids) == {"793", "809", "734", "837", "867", "842", "834"}
    assert ids["837"].startswith("MULTI-CHAPTER | Own the Room")


def test_event_detail_full_fields():
    ev = parse_event_detail(read("pages/event_793.html"), "https://pmi-la.org/calendar?eventId=793", "793")
    assert (ev["start_date"], ev["end_date"]) == ("2026-09-19", "2026-10-24")
    assert (ev["start_time"], ev["end_time"]) == ("8:30 AM", "5:30 PM")
    assert ev["recurrence"] == "Every Saturday"
    assert (ev["member_price"], ev["non_member_price"], ev["student_military_price"]) == (950.0, 1100.0, 650.0)
    assert ev["pdus"] == 35.0
    assert ev["format"] == "In person" and "22 St James Park W" in ev["location"]
    assert ev["register_url"] == "https://pmi-la.org/login?eventId=793"
    assert ev["series"] == "EXAM PREP"
    assert len(ev["description"]) <= 200


def test_event_detail_virtual_closed_and_double_escaped():
    ev = parse_event_detail(read("pages/event_809.html"), "u", "809")
    assert ev["series"] == "BOOK CLUB"
    assert '"How to Measure Anything' in ev["title"] and "&quot;" not in ev["title"]
    assert ev["format"] == "Virtual" and ev["registration"] == "Closed" and ev["register_url"] == ""
    assert ev["student_military_price"] == 0.0 and ev["pdus"] == 3.0
    assert ev["talent_triangle"] == "Ways of Working"


def test_event_detail_ignores_chapter_address_and_nav_register_link():
    ev = parse_event_detail(read("pages/event_837.html"), "u", "837")
    assert ev["location"] == "" and ev["format"] == ""          # only the footer address exists
    assert ev["register_url"] == "https://pmi-la.org/login?eventId=837"
    assert ev["pdus"] == 1.5


def test_event_detail_external_registration_and_free():
    ev = parse_event_detail(read("pages/event_867.html"), "u", "867")
    assert ev["register_url"] == "https://www.pmihi.org/event-registration?eventId=47805"
    assert ev["member_price"] == 0.0 and ev["non_member_price"] == 0.0


def test_events_collector_unions_home_and_calendar(fetcher):
    rows = PmiLaEventsCollector(fetcher, log=lambda *_: None).run()
    # 871 is only on the home page, not in the October calendar view.
    assert {r["event_id"] for r in rows} == {"734", "793", "809", "834", "837", "842", "867", "871"}
    assert all(r["start_date"] and r["title"] for r in rows)


# ── blog ─────────────────────────────────────────────────────────────────────
def test_blog_listing_parses_cards():
    posts = parse_blog_listing(read("pages/blog_p1.html"))
    assert len(posts) == 6
    first = posts[0]
    assert first["title"].startswith("Decent or Grim")
    assert first["published"] == "2026-10-05 12:45"
    assert first["author"] == "Darci Volt, PMP, MBA, Networker"
    assert posts[1]["author"] == ""                                # no byline on that card
    assert all("Continue reading" not in p["excerpt"] for p in posts)


def test_blog_collector_reads_categories_and_video(fetcher):
    rows = {r["url"]: r for r in PmiLaBlogCollector(fetcher, log=lambda *_: None).run()}
    assert len(rows) == 12
    assert rows["https://pmi-la.org/blog/volunteer-spotlight-on-kenny-santanu-214"]["category"] == \
        "Chapter News, Volunteer Spotlight"
    assert rows["https://pmi-la.org/blog/top-golf-recap-218"]["video_url"] == \
        "https://www.youtube.com/watch?v=nRsmjjYMt-4"


# ── YouTube ──────────────────────────────────────────────────────────────────
def test_find_channel_id():
    assert find_channel_id(read("pages/youtube_channel.html")) == "UCoMM0sYo-pY3zdG19PegVfw"
    assert find_channel_id('{"externalId":"UCabcdefghijklmnopqrstuv"}') == "UCabcdefghijklmnopqrstuv"
    assert find_channel_id("<html></html>") is None


def test_parse_channel_feed():
    with open(os.path.join(FIX, "feeds/youtube_sample_feed.xml"), "rb") as f:
        vids = parse_channel_feed(f.read())
    assert [v["video_id"] for v in vids] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert vids[0]["published"] == "2026-10-04 18:30"            # UTC → Pacific


def test_youtube_rss_respects_robots(fetcher):
    with pytest.raises(RobotsDisallowed):
        fetcher.content("https://www.youtube.com/feeds/videos.xml?channel_id=UCoMM0sYo-pY3zdG19PegVfw")


def test_youtube_collector_falls_back_to_blog_embeds(fetcher):
    blog = [{"title": "October Flagship Recap: Sustainability at Topgolf", "published": "2026-10-05 08:00",
             "video_url": "https://www.youtube.com/watch?v=nRsmjjYMt-4"}]
    c = YouTubeCollector(fetcher, log=lambda *_: None, blog_rows=blog)
    rows = c.run()
    assert c.channel_id == "UCoMM0sYo-pY3zdG19PegVfw"
    assert rows == [pytest.approx(rows[0])] and rows[0]["title"] == "October Flagship Recap"
    assert any("robots.txt disallows" in w for w in c.warnings)


# ── news ─────────────────────────────────────────────────────────────────────
def test_feeds_yaml_is_valid():
    feeds = load_feeds()
    assert 5 <= len(feeds) <= 8
    assert all(f["url"].startswith("https://") for f in feeds)


def test_parse_feed_rss_relative_links_and_atom_filters():
    with open(os.path.join(FIX, "feeds/scrum_org.xml"), "rb") as f:
        items = parse_feed(f.read(), {"name": "Scrum.org Blog", "url": "https://www.scrum.org/resources/blog/rss.xml"})
    assert items[0]["url"].startswith("https://www.scrum.org/resources/blog/")
    assert items[0]["published"] == "2026-10-06 23:00"
    with open(os.path.join(FIX, "feeds/hbr.xml"), "rb") as f:
        hbr = parse_feed(f.read(), {"name": "HBR", "url": "https://feeds.hbr.org/harvardbusiness",
                                    "exclude_url_patterns": ["/sponsored/", "/podcast/"]})
    assert hbr and all("/sponsored/" not in i["url"] and "/podcast/" not in i["url"] for i in hbr)
    assert all(i["url"].startswith("https://hbr.org/") for i in hbr)
    assert set(hbr[0]) == {"headline", "outlet", "published", "topic", "url"}   # no bodies


def test_news_collector_dedupes_cross_posted_items(fetcher):
    c = NewsCollector(fetcher, log=lambda *_: None)
    rows = c.run()
    urls = [r["url"] for r in rows]
    assert len(urls) == len(set(urls))
    assert "https://www.infoq.com/presentations/mergequeue/" in urls     # utm stripped, once
    assert all(isinstance(v, int) and v > 0 for v in c.per_feed.values())


# ── Google Sheets exporter (fake gspread client, no credentials) ─────────────
from sheet_fakes import FakeBook as _FakeBook, FakeWS as _FakeWS  # noqa: E402


def test_export_to_sheets_merges_and_leaves_empty_tables_alone(monkeypatch):
    from src.export import sheets as sx
    old_blog = values_from_rows("blog", [{"url": "https://pmi-la.org/blog/old", "title": "Old post",
                                          "first_seen": "T0", "last_updated": "T0"}])
    old_news = values_from_rows("news", [{"url": "https://n.org/1", "headline": "Kept headline",
                                          "published": "2026-10-01 09:00"}])
    book = _FakeBook({"Blog": _FakeWS(old_blog), "News": _FakeWS(old_news)})
    monkeypatch.setenv("GOOGLE_SHEET_ID", "x")
    monkeypatch.setattr(sx, "_client", lambda: type("C", (), {"open_by_key": lambda self, k: book})())
    totals = sx.export_to_sheets(
        {"blog": [{"url": "https://pmi-la.org/blog/new", "title": "New post"}], "news": [], "events": []},
        now="T1", log=lambda *_: None)
    assert totals == {"blog": 2}
    titles = {r["title"]: r for r in rows_from_values("blog", book.sheets["Blog"].values)}
    assert titles["Old post"]["freshness"] == "Stale" and titles["New post"]["freshness"] == "Current"
    assert book.sheets["News"].values == old_news          # 0 rows collected → untouched
    assert "Events" not in book.sheets                     # not even created


def test_blog_category_not_the_whole_sitewide_list():
    """Real pages repeat the category list (desktop + mobile menus) and print the
    post's own label as plain text. Only that label may come back; if the page
    gives no way to tell, the category is blank, never all of them."""
    from src.collectors.pmi_la_blog import parse_blog_post
    cats = ["Chapter News", "Member News", "Free Webinar", "Career Connect", "PMI Events", "Free Events"]
    menu = "".join(f'<li><a href="https://pmi-la.org/blog?categoryId={i}">{c}</a></li>' for i, c in enumerate(cats))
    own = "<p>05 October 2026 at 08:00AM</p><p>Chapter News</p><h1>Topgolf recap</h1>"
    page = f"<html><body><div>{own}</div><nav><ul>{menu}</ul></nav><aside><ul>{menu}</ul></aside></body></html>"
    assert parse_blog_post(page)["category"] == "Chapter News"
    no_label = f"<html><body><h1>Post</h1><nav><ul>{menu}</ul></nav><aside><ul>{menu}</ul></aside></body></html>"
    assert parse_blog_post(no_label)["category"] == ""


def test_blank_category_from_a_read_page_clears_old_junk_but_missing_key_does_not():
    existing = [{"url": "https://a.org/1", "title": "A", "category": "Everything, Else"},
                {"url": "https://a.org/2", "title": "B", "category": "Kept"}]
    fresh = [{"url": "https://a.org/1", "title": "A", "category": ""},      # detail page read, no label
             {"url": "https://a.org/2", "title": "B"}]                      # detail page failed this run
    rows = {r["url"]: r for r in merge("blog", existing, fresh, now="T1")}
    assert rows["https://a.org/1"]["category"] == ""
    assert rows["https://a.org/2"]["category"] == "Kept"


def test_blog_category_layout_where_every_link_has_its_own_container():
    from src.collectors.pmi_la_blog import parse_blog_post
    cats = [f"Cat {i}" for i in range(12)]
    menu = "".join(f'<div class="c"><a href="https://pmi-la.org/blog?categoryId={i}">{c}</a></div>' for i, c in enumerate(cats))
    page = f"<html><body><p>Cat 3</p><h1>Post</h1>{menu}{menu}</body></html>"
    assert parse_blog_post(page)["category"] in ("Cat 3", "")      # never all twelve


def test_drop_universal_categories():
    from src.collectors.pmi_la_blog import drop_universal_categories
    posts = [{"category": "Chapter News, Volunteer Spotlight"}] + \
            [{"category": "Volunteer Spotlight"} for _ in range(5)]
    out = drop_universal_categories(posts)
    assert out[0]["category"] == "Chapter News"
    assert all(p["category"] == "" for p in out[1:])

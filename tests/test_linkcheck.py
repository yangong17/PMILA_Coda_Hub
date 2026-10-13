"""Weekly link/freshness check and the News filters (no network)."""
from collections import OrderedDict
from datetime import date, datetime

from sheet_fakes import FakeBook, FakeWS

from src import coda_api, linkcheck
from src.collectors.news import keep_headline, load_filters, looks_english, parse_feed, stored_row_filter
from src.export import sheets
from src.fetching import Probe

PAGE = "<html><head><title>{title}</title></head><body><h1>{h1}</h1><p>{body}</p></body></html>"


def html_probe(url, title="Page", h1="", body="", status=200, final=None):
    return Probe(url, status=status, final_url=final or url, content_type="text/html",
                 text=PAGE.format(title=title, h1=h1, body=body))


def uses(item="Some Item", where="PDU Opportunities"):
    return [{"Where": where, "Item": item, "Field": "Link", "URL": "x"}]


# ── classify ─────────────────────────────────────────────────────────────────
def test_classify_hard_failures():
    assert linkcheck.classify(Probe("https://a.org/x", status=404), uses())["result"] == "Broken"
    assert linkcheck.classify(Probe("https://a.org/x", status=410), uses())["result"] == "Broken"
    assert linkcheck.classify(Probe("https://a.org/x", status=503), uses())["result"] == "Broken"
    assert linkcheck.classify(Probe("https://a.org/x", error="timed out"), uses())["result"] == "Broken"


def test_classify_400_is_treated_as_bot_blocking_and_page_links_skip_title_match():
    assert linkcheck.classify(Probe("https://www.pm4ngos.org", status=400), uses())["result"] == "Blocked"
    p = html_probe("https://aisel.aisnet.org/icis1981/20", title="Environmental Scanning--The Impact of the Stakeholder Concept")
    assert linkcheck.classify(p, uses("Template: Stakeholder Register", "Page: Template: Stakeholder Register"))["result"] == "OK"


def test_classify_blocked_and_robots_are_not_failures():
    assert linkcheck.classify(Probe("https://a.org/x", status=403), uses())["result"] == "Blocked"
    assert linkcheck.classify(Probe("https://a.org/x", status=429), uses())["result"] == "Blocked"
    p = Probe("https://a.org/x", error="robots.txt asks…", robots_blocked=True)
    assert linkcheck.classify(p, uses())["result"] == "Skipped"


def test_classify_soft_404_title_and_heading():
    p = html_probe("https://a.org/course/el999", title="Page Not Found | PMI")
    assert linkcheck.classify(p, uses())["result"] == "Broken"
    p = html_probe("https://a.org/course/el999", title="PMI", h1="Sorry, this event no longer exists")
    assert linkcheck.classify(p, uses())["result"] == "Broken"


def test_classify_redirect_to_home_is_a_soft_404():
    p = html_probe("https://pmi-la.org/calendar?eventId=834", title="PMI Los Angeles",
                   final="https://pmi-la.org/")
    r = linkcheck.classify(p, uses("Leading Change Beyond the Gantt Chart"))
    assert r["result"] == "Broken" and "home page" in r["note"]
    # A link that IS the home page is fine.
    p = html_probe("https://www.catchafire.org", title="Catchafire", final="https://www.catchafire.org/")
    assert linkcheck.classify(p, uses("Catchafire"))["result"] == "OK"


def test_classify_login_redirect():
    p = html_probe("https://ccrs.pmi.org/", title="Sign in", final="https://idp.pmi.org/account/login?x=1")
    assert linkcheck.classify(p, uses("Check your cycle in CCRS"))["result"] == "Login"


def test_classify_suspect_when_page_does_not_mention_item():
    p = html_probe("https://pmi-la.org/calendar?eventId=871", title="Calendar | PMI-LA",
                   body="Upcoming events at the chapter. Book Club. Networking night.")
    r = linkcheck.classify(p, uses("Veterans Transition Workshop: Translating Military Leadership",
                                   where="Events"))
    assert r["result"] == "Suspect"
    p = html_probe("https://pmi-la.org/calendar?eventId=871", title="Event | PMI-LA",
                   body="Veterans Transition Workshop on translating military leadership.")
    assert linkcheck.classify(p, uses("Veterans Transition Workshop: Translating Military Leadership",
                                      where="Events"))["result"] == "OK"


def test_classify_skips_title_match_for_shared_or_generic_links():
    shared = uses("Read books") + uses("Mentor others")
    p = html_probe("https://www.pmi.org/earn-pdus", title="Earn PDUs", body="nothing relevant")
    assert linkcheck.classify(p, shared)["result"] == "OK"
    assert linkcheck.mentions_item("IPMA", "anything") is None


def test_classify_pdf_is_ok_without_parsing():
    p = Probe("https://www.pmi.org/handbook.pdf", status=200, content_type="application/pdf")
    assert linkcheck.classify(p, uses())["result"] == "OK"


# ── check_links (fake fetcher) ───────────────────────────────────────────────
class FakeFetcher:
    def __init__(self, answers):
        self.answers = answers          # url -> Probe or list of Probes (successive calls)
        self.request_count = 0
        self.calls = []

    def probe(self, url):
        self.request_count += 1
        self.calls.append(url)
        a = self.answers[url]
        if isinstance(a, list):
            return a.pop(0) if len(a) > 1 else a[0]
        return a


def test_check_links_rechecks_flaky_failures_and_sorts_broken_first():
    good = "https://a.org/good"
    flaky = "https://b.org/flaky"
    dead = "https://c.org/dead"
    f = FakeFetcher({
        good: html_probe(good, title="Good"),
        flaky: [Probe(flaky, error="Read timed out"), html_probe(flaky, title="Back")],
        dead: Probe(dead, status=404),
    })
    grouped = OrderedDict((u, uses("x")) for u in (good, flaky, dead))
    res = linkcheck.check_links(grouped, f, "NOW", recheck_wait=0, log=lambda *_: None)
    assert [r["result"] for r in res] == ["Broken", "OK", "OK"]
    assert res[0]["URL"] == dead
    assert f.calls.count(flaky) == 2 and f.calls.count(dead) == 1


def test_check_links_youtube_uses_oembed():
    url = "https://www.youtube.com/watch?v=nRsmjjYMt-4"
    oembed = ("https://www.youtube.com/oembed?format=json&url="
              "https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DnRsmjjYMt-4")
    f = FakeFetcher({oembed: Probe(oembed, status=404)})
    res = linkcheck.check_links(OrderedDict([(url, uses("Talk", "Recordings"))]), f, "NOW",
                                recheck_wait=0, log=lambda *_: None)
    assert res[0]["result"] == "Broken" and "removed" in res[0]["note"]


def test_check_links_claude_review_settles_suspects():
    url = "https://pmi-la.org/calendar?eventId=871"
    f = FakeFetcher({url: html_probe(url, title="Calendar", body="Book Club")})
    grouped = OrderedDict([(url, uses("Veterans Transition Workshop Military Leadership", "Events"))])
    res = linkcheck.check_links(grouped, f, "NOW", recheck_wait=0, log=lambda *_: None,
                                reviewer=lambda item, u, p: {"verdict": "broken", "reason": "Event gone."})
    assert res[0]["result"] == "Broken" and res[0]["note"] == "Claude: Event gone."


# ── gathering ────────────────────────────────────────────────────────────────
def test_links_from_feed_tables_skips_past_events_and_news():
    tables = {
        "events": [{"title": "Future", "url": "https://pmi-la.org/calendar?eventId=1",
                    "register_url": "https://reg.example/1", "status": "Upcoming"},
                   {"title": "Old", "url": "https://pmi-la.org/calendar?eventId=0", "status": "Past"}],
        "blog": [{"title": "Post", "url": "https://pmi-la.org/blog/post", "video_url": ""}],
        "news": [{"headline": "H", "url": "https://hbr.org/x"}],
    }
    urls = [ln["URL"] for ln in linkcheck.links_from_feed_tables(tables)]
    assert urls == ["https://pmi-la.org/calendar?eventId=1", "https://reg.example/1",
                    "https://pmi-la.org/blog/post"]


def test_group_by_url_dedupes_and_drops_internal_links():
    links = [
        {"Where": "Paths", "Item": "A", "Field": "Go", "URL": "https://pmi.org/x"},
        {"Where": "Paths", "Item": "A", "Field": "Go", "URL": "https://pmi.org/x"},
        {"Where": "Free 60 Plan", "Item": "B", "Field": "Start", "URL": "https://pmi.org/x"},
        {"Where": "Paths", "Item": "C", "Field": "Go", "URL": "https://coda.io/d/_dX/_suY"},
    ]
    g = linkcheck.group_by_url(links)
    assert list(g) == ["https://pmi.org/x"] and len(g["https://pmi.org/x"]) == 2
    assert linkcheck.used_in(g["https://pmi.org/x"]) == "Paths: A; Free 60 Plan: B"


def test_snapshot_csv_loads():
    rows = linkcheck.links_from_csv()
    assert len(rows) > 50
    assert all(r["URL"].startswith("http") for r in rows)


def test_coda_rows_extract_urls_and_skip_unapproved():
    rows = [
        {"name": "Course A", "values": {"Approved": True,
                                         "Link": {"@type": "WebPage", "url": "https://pmi.org/a"},
                                         "Notes": "See [the handbook](https://pmi.org/h.pdf)."}},
        {"name": "Hidden", "values": {"Approved": False, "Link": {"url": "https://pmi.org/b"}}},
        {"name": "Ref", "values": {"Go": {"url": "https://coda.io/d/_dX/_suY"}}},
    ]
    links = coda_api.links_from_rows("PDU Opportunities", rows)
    assert sorted(ln["URL"] for ln in links) == ["https://pmi.org/a", "https://pmi.org/h.pdf"]
    md = "Based on [Brown](https://www.pmi.org/learning/library/charter-7473) and [hub](https://coda.io/d/x)."
    assert [ln["URL"] for ln in coda_api.links_from_markdown("Charter", md)] == [
        "https://www.pmi.org/learning/library/charter-7473"]


# ── freshness ────────────────────────────────────────────────────────────────
def _tables(event_day="2026-10-20", blog_day="2026-10-01", news_day="2026-10-11"):
    return {
        "events": [{"title": "E", "start_date": event_day, "end_date": event_day}],
        "blog": [{"title": "B", "published": blog_day}],
        "news": [{"headline": "N", "outlet": "Scrum.org Blog", "published": news_day + " 09:00"}],
    }


def _results(checks):
    return {c["Check"]: c["Result"] for c in checks}


def test_freshness_all_good():
    log = [{"Run At": "2026-10-12 02:17 PDT", "Job": "feeds", "Result": "OK"}]
    r = _results(linkcheck.freshness_checks(_tables(), log, ["Scrum.org Blog"],
                                            today=date(2026, 10, 12), now=datetime(2026, 10, 12, 9, 0)))
    assert set(r.values()) == {"Pass"}


def test_freshness_flags_stalled_sources():
    log = [{"Run At": "2026-10-09 02:17 PDT", "Job": "feeds", "Result": "OK"}]
    r = _results(linkcheck.freshness_checks(
        _tables(event_day="2026-10-01", blog_day="2026-05-01", news_day="2026-09-20"), log,
        ["Scrum.org Blog", "InfoQ – Agile"], today=date(2026, 10, 12), now=datetime(2026, 10, 12, 9)))
    assert r["Feeds job ran recently"] == "Fail"
    assert r["Upcoming events"] == "Fail"
    assert r["Chapter blog is current"] == "Fail"
    assert r["PM News is current"] == "Fail"
    assert r["Outlet: InfoQ – Agile"] == "Warn"


def test_freshness_without_sheet_skips_run_log():
    r = _results(linkcheck.freshness_checks(_tables(), None, [], today=date(2026, 10, 12)))
    assert r["Feeds job ran recently"] == "Skip"


# ── end to end against a fake Sheet ──────────────────────────────────────────
def test_main_writes_tabs_and_fails_on_broken_links(tmp_path, monkeypatch):
    monkeypatch.delenv("CODA_API_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    events = sheets.values_from_rows("events", [
        {"title": "Leading Change Beyond the Gantt Chart", "url": "https://pmi-la.org/calendar?eventId=834",
         "start_date": "2099-01-01", "end_date": "2099-01-01", "status": "Upcoming"}])
    book = FakeBook({"Sheet1": FakeWS(), "Events": FakeWS(events)})
    url = "https://pmi-la.org/calendar?eventId=834"
    f = FakeFetcher({url: Probe(url, status=404)})
    code = linkcheck.main(["--no-hub", "--out", str(tmp_path)], fetcher=f, book=book)
    assert code == 1
    assert book.sheets["Link Health"].values[1][0] == "Broken"
    assert book.sheets["Health Checks"].values[0] == linkcheck.CHECK_HEADERS
    log = book.sheets["Run Log"].values
    assert log[0] == sheets.RUN_LOG_HEADERS and log[1][1] == "linkcheck" and log[1][2] == "Failed"
    assert "Sheet1" not in book.sheets
    assert (tmp_path / "link_health.csv").exists() and (tmp_path / "health_report.md").exists()


def test_run_log_appends_and_keeps_header():
    book = FakeBook({})
    sheets.append_run_log(book, ["T1", "feeds", "OK", "s", ""])
    sheets.append_run_log(book, ["T2", "feeds", "Partial", "s", "w"])
    vals = book.sheets["Run Log"].values
    assert vals[0] == sheets.RUN_LOG_HEADERS and [r[0] for r in vals[1:]] == ["T1", "T2"]
    assert sheets.read_run_log(book)[-1]["Result"] == "Partial"


def test_default_tab_is_kept_if_it_has_content():
    book = FakeBook({"Sheet1": FakeWS([["notes"]]), "Events": FakeWS()})
    sheets.remove_default_tab(book)
    assert "Sheet1" in book.sheets


# ── news filters ─────────────────────────────────────────────────────────────
def test_news_filters_drop_listicles_and_other_languages():
    flt = load_filters()
    dropped = [
        "14 Best Project Executive Newsletters to Subscribe to in 2026",
        "Top 18 Agile Coaches to Learn From in 2026",
        "10 Best MYOB Acumatica Integrations for 2026",
        "10 Project Management Software Benefits: Why Use It?",
        "Project Time Tracking: Tools, Features and Software Reviews",
        "Der Kobra-Effekt in der KI-Transformation: So misst du den Erfolg deiner KI-Strategie",
    ]
    kept = [
        "AI Changes What Makes a Product Backlog Valuable",
        "5 Things the Scrum Master Shouldn’t Be Doing",
        "What PMOs Must Give Up to Survive AI Transformation",
        "Research: Sleep Deprivation Is a Leadership Problem",
    ]
    assert not any(keep_headline(t, flt) for t in dropped)
    assert all(keep_headline(t, flt) for t in kept)
    assert looks_english("Why Projects Die and What to Do") is True


def test_include_keywords_match_whole_words():
    feed = {"name": "HBR", "url": "https://feeds.hbr.org/x", "include_keywords": ["AI", "team"]}
    xml = b"""<rss version="2.0"><channel><title>t</title><link>https://hbr.org</link>
      <item><title>How AI Is Changing Teams</title><link>https://hbr.org/1</link></item>
      <item><title>What the Honda Super Cub Can Teach Us</title><link>https://hbr.org/2</link></item>
      <item><title>Build a better team</title><link>https://hbr.org/3</link></item>
    </channel></rss>"""
    heads = [r["headline"] for r in parse_feed(xml, feed)]
    assert sorted(heads) == ["Build a better team", "How AI Is Changing Teams"]


def test_stored_row_filter_clears_old_listicles():
    keep = stored_row_filter(feeds=[{"name": "HBR", "url": "u", "include_keywords": ["leader"]}],
                             filters=load_filters())
    assert keep({"headline": "Top 14 Women in Project Management to Follow in 2026", "outlet": "DPM"}) is False
    assert keep({"headline": "Match Your Pace to the Moment", "outlet": "HBR"}) is False
    assert keep({"headline": "What Every Leader Gets Wrong", "outlet": "HBR"}) is True
    assert keep({"headline": "Anything", "outlet": "Retired outlet"}) is True


def test_blocked_link_rechecked_in_browser():
    from collections import OrderedDict
    from src.fetching import Probe
    from src import linkcheck

    class Plain:
        request_count = 0
        _dead = {}
        def probe(self, url):
            return Probe(url, status=403, final_url=url)

    class Browser:
        def probe(self, url):
            if "stillblocked" in url:
                return Probe(url, status=403, final_url=url)
            if "dead" in url:
                return Probe(url, status=404, final_url=url)
            return Probe(url, status=200, final_url=url, content_type="text/html",
                         text="<title>PMI</title>")

    grouped = OrderedDict((u, [{"Where": "Page: x", "Item": "x"}]) for u in
                          ["https://a.org/ok", "https://a.org/stillblocked", "https://a.org/dead"])
    res = {r["URL"]: r["result"] for r in
           linkcheck.check_links(grouped, Plain(), "now", browser=Browser(), recheck_wait=0, log=lambda *a: None)}
    assert res == {"https://a.org/ok": "OK", "https://a.org/stillblocked": "Blocked",
                   "https://a.org/dead": "Broken"}

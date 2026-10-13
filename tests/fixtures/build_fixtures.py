"""
Builds the offline fixtures in tests/fixtures/ (pages/, feeds/, manifest.json).

WHY THIS EXISTS: from the build sandbox, outbound HTTPS to pmi-la.org, YouTube
and every news host was refused by the egress proxy (HTTP 403 on CONNECT), so
the raw pages could not be saved with curl. On 2026-10-08 the same URLs were
read with a separate web-fetch tool, which returns page TEXT (not raw HTML).
The values below — titles, dates, times, prices, PDU lines, locations,
og:descriptions, links, feed items — are copied from those reads. The HTML
around them is RECONSTRUCTED to mimic an MG2 Manager page (nav, labelled
fields, sidebar, footer with the chapter address), so it exercises the parsers
the same way but is not byte-identical to the live site.

FIRST THING TO DO once the pipeline runs somewhere with normal internet (e.g.
GitHub Actions): `python scripts/save_fixtures.py` to replace these with real
saved pages, then re-run pytest.

Run:  python tests/fixtures/build_fixtures.py
"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "pages")
FEEDS = os.path.join(HERE, "feeds")
manifest = {}


def save(url, rel, body):
    path = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    manifest[url] = rel


def e(s):
    return html.escape(s, quote=True)


# ── shared MG2-like chrome ───────────────────────────────────────────────────
def mg2_page(title, body, og_title=None, og_desc=None, raw_og=False):
    def meta(prop, val):
        if val is None:
            return ""
        v = val if raw_og else e(val)
        return f'<meta property="{prop}" content="{v}" />\n'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title>
<meta name="description" content="Calendar" />
{meta("og:title", og_title)}{meta("og:description", og_desc)}<meta name="meta-Author" content="PMI Los Angeles" />
<script>var mg2 = {{"tpl": "{{{{title}}}}"}};</script>
</head><body>
<header class="mg2-header">
  <nav><ul>
    <li><a href="/">Home</a></li><li><a href="/calendar">Calendar</a></li>
    <li><a href="/blog">Blog</a></li><li><a href="/login">Login</a></li>
    <li><a href="https://www.pmi.org/membership/join">Join / Register</a></li>
  </ul></nav>
</header>
<main id="mg2-content">
{body}
</main>
<footer>
  <div class="contact">PMI Los Angeles Chapter<br>10866 Washington Blvd #426, Culver City, CA 90232</div>
  <a href="https://www.youtube.com/@PMI-LosAngeles">YouTube</a>
  <a href="https://www.linkedin.com/company/pmi-la">LinkedIn</a>
</footer>
</body></html>
"""


# ── events (detail pages) ────────────────────────────────────────────────────
EVENTS = {
    "793": dict(
        title="PMP® (In-Person) Prep Course (Fall 2026 Session)",
        og_suffix=" - Sep 19 2026",
        og_desc="PMI-LA is thrilled to announce our in-person Fall Session, the authorized PMP® Prep Course for 2026 at an EVEN lower rate!",
        date="September 19th to October 24th, 2026", hour="8:30AM to 5:30PM", extra_when=["Every Saturday"],
        location=["Mt. Saint Mary's University: Doheny Campus", "22 St James Park W, Los Angeles, CA 90007"],
        pdus="35", pdu_lines=[],
        prices=[("Students and Military", "$650.00"), ("Members", "$950.00"), ("Non members", "$1100.00")],
        register="/login?eventId=793", closed=False,
        body=["PMI-LA is excited to bring back our in-person, authorized PMP® Prep Course! This five-day experience gives you the 35 contact hours required to sit for the exam."]),
    "809": dict(
        title='BOOK CLUB | Chapters 7-12 of "How to Measure Anything in Project Management" by Hubbard, Budzier, & Leed',
        og_suffix="  - Oct 03 2026", double_escaped=True,
        og_desc='The Book Club will hold a virtual session to discuss chapters 7-12 of"How to Measure Anything in Project Management" by Hubbard, Budzier, & Leed',
        date="October 3rd, 2026", hour="11:00AM to 1:00PM", extra_when=[],
        location=["Virtual"],
        pdus="3", pdu_lines=["3 PDU – Ways of Working",
                              "Note: PDU Breakdown is 1 for Reading the book, 1 for Book Discussion, and 1 for the Presentation on PM-related topics.",
                              "Earn PDUs by sharing your thoughts on this popular book with fellow and future project managers."],
        prices=[("Students and Military", "Free"), ("Members", "$5.00"), ("Non members", "$10.00")],
        pricing_inline="Pricing $5.00 (members), $10.00 (non-members)",
        register=None, closed=True,
        body=["Those attendees who registered for chapters 1-6 by 28 August will receive chapters 7-12 free!"]),
    "734": dict(
        title="FLAGSHIP | Fireside Chat on Sustainability, Workforce Development and Project Management Professionals",
        og_suffix=" - Oct 04 2026",
        og_desc="Join us for a fireside chat on sustainability, workforce development, and project management.",
        date="October 4th, 2026", hour="10:00AM to 2:00PM", extra_when=[],
        location=["Top Golf", "400 Pacific Coast Hwy", "El Segundo , CA, 90245"],
        pdus="2", pdu_lines=["But you still have time to join for breakfast, panel discussions, 2 PDUs, and camaraderie in the golfing bays."],
        prices=[("Students and Military", "$40.00"), ("Members", "$60.00"), ("Non members", "$70.00")],
        register=None, closed=True,
        body=["Leadership = Power Skills", "Strategy = Business Acumen"]),
    "837": dict(
        title="MULTI-CHAPTER | Own the Room in 3 Seconds: How to Pitch Your Value, Command the Space, and Build Rapid Credibility",
        og_suffix=" - Oct 08 2026",
        og_desc='Stop talking past people in interviews—master a simple, plug-and-play formula to state your value with precision, build instant credibility, and answer "Why you?" with total confidence.',
        date="October 8th, 2026", hour="6:00PM to 7:30PM", extra_when=[],
        location=[],  # the Location block holds only images on the live page
        pdus="1.5", pdu_lines=[],
        prices=[("Members", "$5.00"), ("Non members", "$10.00")],
        register="/login?eventId=837", closed=False,
        body=["Have you ever spent an hour in an interview or meeting only to find out you were talking past each other?"]),
    "842": dict(
        title="Multi-Chapter | Status: Green. Feeling: Red. The mental health of the person holding everything together.",
        og_suffix=" - Oct 14 2026",
        og_desc="Every project manager has filed a status report that said green while they felt red. This session is about that gap.",
        date="October 14th, 2026", hour="7:00PM to 8:00PM", extra_when=[],
        location=["Live Webinar", "Virtual"],
        pdus="1", pdu_lines=[], category="Leadership = Power Skills (Public Event)",
        prices=[("Members", "$5.00"), ("Non members", "$10.00")],
        register="/login?eventId=842", closed=False,
        body=["Speaker: David Doan, PhD, MBA, RN, PMP"]),
    "867": dict(
        title="WEBINAR: AI Powered EA (Enterprise Architecture)",
        og_suffix=" - Oct 14 2026",
        og_desc="Artificial intelligence is shifting Enterprise Architecture (EA) from static documentation to a dynamic decision engine.",
        date="October 14th, 2026", hour="3:00PM to 4:00PM", extra_when=[],
        location=["Virtual"],
        pdus="1", pdu_lines=[],
        prices=[("Members", "Free"), ("Non members", "Free")],
        register="https://www.pmihi.org/event-registration?eventId=47805", closed=False,
        extra_links=["https://www.pmihi.org/calendar?eventId=47805&month=9&year=2026"],
        body=["Hosted by PMI Honolulu."]),
    "871": dict(
        title="Multi-Chapter | Mission to Marketplace: Military-to-Civilian Career Transition",
        og_suffix=" - Oct 20 2026",
        og_desc="Join Robert Shake as he shares lessons from his journey from military service to senior leadership, with practical insights on leveraging military skills for success in civilian careers.",
        date="October 20th, 2026", hour="5:30PM to 7:00PM", extra_when=[],
        location=["Virtual"],
        pdus="1.5", pdu_lines=[],
        prices=[("Members", "$5.00"), ("Non members", "$10.00")],
        register="/login?eventId=871", closed=False,
        body=["Robert Shake shares advice on moving from military service into civilian leadership careers."]),
    "834": dict(
        title="Multi-Chapter | Leading Change Beyond the Gantt Chart",
        og_suffix=" - Oct 22 2026",
        og_desc="In this session, Wani Iris Manly, Esq. introduces a practical framework for identifying and addressing the human factors that determine whether change succeeds or stalls.",
        date="October 22nd, 2026", hour="4:00PM to 5:00PM", extra_when=[],
        location=["Live Webinar", "Virtual"],
        pdus="1", pdu_lines=[],
        prices=[("Members", "$5.00"), ("Non members", "$10.00")],
        register="/login?eventId=834", closed=False,
        body=["A practical framework for the human side of change."]),
}

for eid, ev in EVENTS.items():
    og_title = ev["title"] + ev["og_suffix"]
    og_desc = ev["og_desc"]
    raw = False
    if ev.get("double_escaped"):   # MG2 double-escapes some og: values
        og_title = e(e(og_title))
        og_desc = e(e(og_desc))
        raw = True
    loc_html = "".join(f"<div>{e(x)}</div>" for x in ev["location"]) or '<img src="/images/logo.png" alt="">'
    prices = "".join(f'<div class="price"><span>{e(k)}:</span> <span>{e(v)}</span></div>' for k, v in ev["prices"])
    if ev.get("pricing_inline"):
        prices = f"<p>{e(ev['pricing_inline'])}</p>" + prices
    pdu_extra = "".join(f"<p>{e(x)}</p>" for x in ev["pdu_lines"])
    cat = f"<div class='category'>Category: {e(ev['category'])}</div>" if ev.get("category") else ""
    reg = ('<p class="closed">It is no longer possible to register for this event.</p>' if ev["closed"]
           else f'<a class="btn" href="{e(ev["register"])}">REGISTER FOR THIS EVENT</a>')
    extra_links = "".join(f'<a href="{e(x)}">More info</a>' for x in ev.get("extra_links", []))
    when_extra = "".join(f"<div>{e(x)}</div>" for x in ev["extra_when"])
    body = f"""
<div class="event-detail">
  <h1><a href="/calendar?eventId={eid}">{e(ev['title'])}</a></h1>
  <div class="when"><span class="label">Date:</span> <span>{e(ev['date'])}</span></div>
  <div class="when"><span class="label">Hour:</span> <span>{e(ev['hour'])}</span></div>
  {when_extra}
  {cat}
  <h3>Location</h3>
  <div class="location">{loc_html}</div>
  <div class="pdu"><span>PDUs:</span><span>{ev['pdus']}</span></div>
  {pdu_extra}
  <div class="pricing">{prices}</div>
  {reg}
  {extra_links}
  <h3>Description</h3>
  <div class="description">{''.join(f'<p>{e(p)}</p>' for p in ev['body'])}</div>
  <div class="share">Share <a href="https://www.facebook.com/sharer.php">Facebook</a></div>
  <div class="contact-us"><h4>Contact</h4><div>10866 Washington Blvd #426, Culver City, CA 90232</div></div>
</div>"""
    save(f"https://pmi-la.org/calendar?eventId={eid}", f"pages/event_{eid}.html",
         mg2_page("PMI Los Angeles Calendar", body, og_title, og_desc, raw_og=raw))


# ── calendar listings / home ─────────────────────────────────────────────────
def card(eid, month, title, when, register=True):
    return f"""<div class="event-item">
  <a class="title" href="calendar?eventId={eid}&month={month}&year=2026">{e(title)}</a>
  <div class="date">{e(when)}</div>
  <a href="calendar?eventId={eid}">Learn more</a>
  {f'<a href="login?eventId={eid}">Register</a>' if register else ''}
</div>"""


OCT_CARDS = [
    card("793", 8, EVENTS["793"]["title"], "19 to 24 2026 · 8:30AM to 5:30PM · Every Saturday"),
    card("809", 9, EVENTS["809"]["title"], "Oct 3 2026 · 11:00AM to 1:00PM", register=False),
    card("734", 9, EVENTS["734"]["title"], "Oct 4 2026 · 10:00AM to 2:00PM", register=False),
    card("837", 9, EVENTS["837"]["title"], "Oct 8 2026 · 6:00PM to 7:30PM"),
    card("867", 9, EVENTS["867"]["title"], "Oct 14 2026 · 3:00PM to 4:00PM"),
    card("842", 9, EVENTS["842"]["title"], "Oct 14 2026 · 7:00PM to 8:00PM"),
    card("834", 9, EVENTS["834"]["title"], "Oct 22 2026 · 4:00PM to 5:00PM"),
]


def calendar_page(month_name, cards, prev_q, next_q):
    inner = "\n".join(cards) if cards else "<p>No events to display</p>"
    return mg2_page("PMI Los Angeles Calendar", f"""
<div class="calendar-nav">
  <a href="calendar?{prev_q}">&lsaquo;</a> <h2>{month_name}</h2> <a href="calendar?{next_q}">&rsaquo;</a>
  <a href="calendar?row">List view</a>
</div>
<h3>Upcoming events</h3>
{inner}
<h3>Past events</h3>
""")


save("https://pmi-la.org/calendar?month=9&year=2026", "pages/calendar_2026_10.html",
     calendar_page("October 2026", OCT_CARDS, "month=8&year=2026", "month=10&year=2026"))
save("https://pmi-la.org/calendar?month=10&year=2026", "pages/calendar_2026_11.html",
     calendar_page("November 2026", [], "month=9&year=2026", "month=11&year=2026"))
save("https://pmi-la.org/calendar?month=11&year=2026", "pages/calendar_2026_12.html",
     calendar_page("December 2026", [], "month=10&year=2026", "month=0&year=2027"))
save("https://pmi-la.org/calendar?month=0&year=2027", "pages/calendar_2027_01.html",
     calendar_page("January 2027", [], "month=11&year=2026", "month=1&year=2027"))

home_cards = [
    (837, "October 8th, 2026", "6:00PM to 7:30PM"),
    (793, "September 19th to October 24th, 2026", "8:30AM to 5:30PM"),
    (867, "October 14th, 2026", "3:00PM to 4:00PM"),
    (842, "October 14th, 2026", "7:00PM to 8:00PM"),
    (871, "October 20th, 2026", "5:30PM to 7:00PM"),
    (834, "October 22nd, 2026", "4:00PM to 5:00PM"),
]
home_body = '<div class="banner">' + "".join(
    f'<a href="https://pmi-la.org/calendar?eventId={i}">{e(EVENTS[str(i)]["title"])}</a>' for i in (809, 734)
) + "</div>\n<section class='events'><h2>Events</h2>" + "".join(
    f'<div class="ev"><a href="https://pmi-la.org/calendar?eventId={i}">{e(EVENTS[str(i)]["title"])}</a>'
    f"<div>{d}</div><div>{h}</div></div>" for i, d, h in home_cards
) + """</section>
<section class="news"><h2>Chapter News</h2><p>No blog posts to display</p>
<div class="tpl"><a href="{{url}}">{{title}}</a></div></section>"""
save("https://pmi-la.org/", "pages/home.html", mg2_page("PMI Los Angeles", home_body))
save("https://pmi-la.org/robots.txt", "pages/pmi-la_robots.txt", "User-agent: *\nAllow: /\n")


# ── blog ─────────────────────────────────────────────────────────────────────
POSTS_P1 = [
    ("whats-the-job-outlook-for-2026", "Decent or Grim – What's the job outlook for 2026?",
     "Darci Volt, PMP, MBA, Networker", "05 October 2026 at 12:45PM",
     ["Employment & Job data snippets are bubbling around a few publications, and these handpicked sources tend to be fairly well-targeted."],
     ["Career Connect"], None),
    ("top-golf-recap-218", "October Flagship Recap: Sustainability at Topgolf", "", "05 October 2026 at 08:00AM",
     ["Watch out Topgolf recap on October 4, 2026."], ["Chapter News"], "nRsmjjYMt-4"),
    ("columbian-relief-fest-216", "Columbian Relief Fest", "", "04 October 2026 at 08:00AM",
     ["Join the Colombian community in Los Angeles on October 10 for an evening of music, food, and community in support of families affected by the August 10 earthqu..."],
     ["Professional Community Events"], None),
    ("building-bridges-not-just-resumes-a-recruiters-guide-for-pmi-la-members",
     "Building Bridges, Not Just Resumes: A Recruiter’s Guide for PMI-LA Members",
     "Emily Gasster, Recruiter @ Insight Global", "03 October 2026 at 05:00PM",
     ["A Perspective from the recruiting side of the search"], ["Career Connect"], None),
    ("october-events-guide-is-now-available-215", "October Events Guide is now available!", "",
     "01 October 2026 at 12:05PM", ["Our October Events Guide is available for download."], ["Chapter News"], None),
    ("volunteer-spotlight-on-kenny-santanu-214", "Volunteer Spotlight on Kenny Santanu", "",
     "30 September 2026 at 12:30PM", ["Technology Committee", "August 2026"],
     ["Chapter News", "Volunteer Spotlight"], None),
]
POSTS_P2 = [
    ("cc-mentors-corner", "Need a boost? Check out our Career Connect MENTOR'S CORNER",
     "Darci Volt, PMP, MBA, Networker", "29 September 2026 at 08:00AM",
     ["Get on a roll with these tried-and-true ideas and perspectives well worth sharing. Curated by the CC team."],
     ["Career Connect"], None),
    ("2027-board-nominations-are-open-211", "2027 Board Nominations are OPEN!", "", "28 September 2026 at 08:00AM",
     ["Board nominations are now open."], ["Chapter News"], None),
    ("pmi-pmocp-accelerator-by-pmo-evolution-213", "PMI-PMOCP Accelerator by PMO Evolution", "",
     "27 September 2026 at 12:00AM",
     ["Build your PMO expertise while preparing for the PMI-PMOCP® certification in this 8-week live online cohort from PMO Evolution."],
     ["Professional Community Events"], None),
    ("santa-monica-in-person-networking-event-recap-212", "Santa Monica In-Person Networking Event Recap", "",
     "26 September 2026 at 08:00PM",
     ["Read the recap of the Santa Monica In-Person Networking event held on September 24, 2026."],
     ["Chapter News"], None),
    ("platinum-edge-certified-scrummaster-csm-3-of-3", "Platinum Edge: Certified ScrumMaster (CSM) - 3 of 3", "",
     "23 September 2026 at 07:10PM",
     ["Date: September 24-25, 2026 Time: 06:00 AM -03:00 PM PDT Location: Virtual On-Line Cost: PMI-LA Chapter Discount code:"],
     ["Expired Events"], None),
    ("wells-bring-hope-annual-fundraiser-17", "Wells Bring Hope Annual Fundraiser", "", "23 September 2026 at 02:00PM",
     ["Date: September 27, 2026 Time: 12:00-4:00 - Assist with Set-up; 2:30-8:00 Assist with Auction or both sessions!"],
     ["Expired Events"], None),
]
SIDEBAR = [(373, "Chapter News"), (398, "Member News"), (399, "Free Webinar"), (428, "Members Books!"),
           (429, "Volunteer of the Month"), (630, "Expired Events"), (631, "Free Events"),
           (632, "Professional Community Events"), (746, "Career Connect"), (896, "Social Impact Organizations"),
           (937, "Social Impact 2"), (938, "Social Impact 3"), (1069, "50th Events"), (1, "Volunteer Spotlight"),
           (2, "PMI Events"), (10, "The PULSE at PMI-LA")]
CAT_ID = {n: i for i, n in SIDEBAR}
sidebar_html = '<aside class="sidebar"><h4>Categories</h4><ul>' + "".join(
    f'<li><a href="https://pmi-la.org/blog?categoryId={i}">{e(n)}</a></li>' for i, n in SIDEBAR) + "</ul></aside>"


def blog_listing(posts, page, pages=61):
    cards = []
    for slug, title, author, when, excerpt, _cats, _vid in posts:
        by = f'<span class="author">{e(author)}</span>' if author else ""
        cards.append(f"""<article class="blog-item">
  <div class="meta">{by}<span class="date">{e(when)}</span></div>
  <h2><a href="https://pmi-la.org/blog/{slug}">{e(title)}</a></h2>
  <div class="excerpt">{''.join(f'<div>{e(x)}</div>' for x in excerpt)}</div>
  <a href="https://pmi-la.org/blog/{slug}">Continue reading</a>
</article>""")
    pager = f'<div class="pager">{page} of {pages} <a href="https://pmi-la.org/blog?page={page + 1}">blog?page={page + 1}</a></div>'
    return mg2_page("PMI Los Angeles Blog", "\n".join(cards) + pager + sidebar_html)


save("https://pmi-la.org/blog", "pages/blog_p1.html", blog_listing(POSTS_P1, 1))
save("https://pmi-la.org/blog?page=2", "pages/blog_p2.html", blog_listing(POSTS_P2, 2))

for slug, title, author, when, excerpt, cats, vid in POSTS_P1 + POSTS_P2:
    by = f'<span class="author">{e(author)}</span>' if author else ""
    labels = "".join(f'<a class="cat" href="https://pmi-la.org/blog?categoryId={CAT_ID[c]}">{e(c)}</a>' for c in cats)
    video = (f'<iframe width="560" height="315" src="//www.youtube.com/embed/{vid}" frameborder="0" allowfullscreen></iframe>'
             if vid else "")
    body = f"""<article class="blog-post">
  <h1>{e(title)}</h1>
  <div class="meta">{by}<span class="date">{e(when)}</span></div>
  <div class="post-categories">{labels}</div>
  <div class="content">{''.join(f'<p>{e(x)}</p>' for x in excerpt)}{video}</div>
</article>{sidebar_html}"""
    save(f"https://pmi-la.org/blog/{slug}", f"pages/post_{slug[:40]}.html",
         mg2_page(title, body, og_title=title, og_desc=" ".join(excerpt)))


# ── YouTube ──────────────────────────────────────────────────────────────────
CID = "UCoMM0sYo-pY3zdG19PegVfw"
save("https://www.youtube.com/@PMI-LosAngeles", "pages/youtube_channel.html", f"""<!DOCTYPE html>
<html><head><title>PMI-Los Angeles - YouTube</title>
<link rel="canonical" href="https://www.youtube.com/channel/{CID}">
<link rel="alternate" type="application/rss+xml" title="RSS" href="https://www.youtube.com/feeds/videos.xml?channel_id={CID}">
<meta property="og:title" content="PMI-Los Angeles">
</head><body><script>var ytInitialData = {{"metadata":{{"channelMetadataRenderer":{{"title":"PMI-Los Angeles","externalId":"{CID}"}}}}}};</script></body></html>
""")
# Only the rules relevant here (the full file is long). Note the feed rule.
save("https://www.youtube.com/robots.txt", "pages/youtube_robots.txt",
     "User-agent: Mediapartners-Google*\nDisallow:\n\nUser-agent: *\nDisallow: /api/\nDisallow: /comment\n"
     "Disallow: /feeds/videos.xml\nDisallow: /get_video_info\nDisallow: /results\nDisallow: /login\n"
     "Disallow: /signup\nDisallow: /live_chat\nDisallow: /verify_age\nDisallow: /watch_ajax\n"
     "Disallow: /youtubei/\nDisallow: /channel_picker\n")
save("https://www.youtube.com/oembed?format=json&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DnRsmjjYMt-4",
     "pages/youtube_oembed_nRsmjjYMt-4.json", json.dumps({
         "title": "October Flagship Recap", "author_name": "PMI-Los Angeles",
         "author_url": "https://www.youtube.com/@PMI-LosAngeles", "type": "video",
         "provider_name": "YouTube", "provider_url": "https://www.youtube.com/",
         "thumbnail_url": "https://i.ytimg.com/vi/nRsmjjYMt-4/hqdefault.jpg",
         "thumbnail_width": 480, "thumbnail_height": 360, "width": 200, "height": 113}, indent=2))


# ── news feeds ───────────────────────────────────────────────────────────────
def rss(title, link, items, base=None, date_tag="pubDate", creator=True):
    xb = f' xml:base="{base}"' if base else ""
    out = [f'<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f"<channel{xb}><title>{e(title)}</title><link>{link}</link><description>{e(title)}</description>"]
    for t, d, l, *rest in items:
        who = f"<dc:creator>{e(rest[0])}</dc:creator>" if rest and creator else ""
        dt = f"<{date_tag}>{d}</{date_tag}>" if date_tag == "pubDate" else f"<dc:date>{d}</dc:date>"
        out.append(f"<item><title>{e(t)}</title><link>{e(l)}</link>{dt}{who}"
                   f"<description>&lt;p&gt;Article body is never stored.&lt;/p&gt;</description></item>")
    out.append("</channel></rss>\n")
    return "\n".join(out)


def atom(title, base, entries):
    out = [f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:base="{base}">'
           f"<title>{e(title)}</title><id>{base}/feed</id><updated>2026-10-06T12:25:54Z</updated>"]
    for t, d, l, *who in entries:
        a = "".join(f"<author><name>{e(n)}</name></author>" for n in who)
        out.append(f'<entry><title>{e(t)}</title><link href="{e(l)}"/><id>{e(base + l)}</id>'
                   f"<published>{d}</published><updated>{d}</updated>{a}</entry>")
    out.append("</feed>\n")
    return "\n".join(out)


INFOQ = "?utm_campaign=infoq_content&utm_source=infoq&utm_medium=feed&utm_term="
save("https://www.scrum.org/resources/blog/rss.xml", "feeds/scrum_org.xml", rss(
    "Scrum.org Blog", "https://www.scrum.org/", [
        ("Der Kobra-Effekt in der KI-Transformation: So misst du den Erfolg deiner KI-Strategie, ohne den Fehler zu wiederholen, an dem schon Agile-Transformationen gescheitert sind",
         "Wed, 07 Oct 2026 06:00:00 +0000", "/resources/blog/der-kobra-effekt-der-ki-transformation-so-misst-du-den-erfolg-deiner-ki-strategie-ohne-den-fehler-zu-wiederholen-dem-schon-agile-transformationen-gescheitert-sind", "Simon Flossmann"),
        ("Your framework isn't broken. Your fundamentals are.", "Tue, 06 Oct 2026 22:00:00 +0000",
         "/resources/blog/your-framework-isnt-broken-your-fundamentals-are", "Steven Deneir"),
        ("The Role of Agency in Scrum: Why Self-Management Without Agency is a Lie", "Tue, 06 Oct 2026 14:00:00 +0000",
         "/resources/blog/role-agency-scrum-why-self-management-without-agency-lie", "Martin Hinshelwood"),
        ("Scrum Day India 2026 Recap: Scrum Teams in the Age of Autonomous Agents", "Mon, 05 Oct 2026 09:29:36 +0000",
         "/resources/blog/scrum-day-india-2026-recap-scrum-teams-age-autonomous-agents", "Sanjay Saini"),
        ("5 Things the Scrum Master Shouldn’t Be Doing", "Sun, 04 Oct 2026 13:00:00 +0000",
         "/resources/blog/5-things-scrum-master-shouldnt-be-doing", "Mary Iqbal"),
        ("Outcome-Based Leadership in Project Management: Measuring What Really Matters", "Sun, 04 Oct 2026 11:35:53 +0000",
         "/resources/blog/outcome-based-leadership-project-management-measuring-what-really-matters", "Dominik Maximini"),
        ("Not All Complexity Can Be Processed Away. Fred Brooks Proved This in 1986.", "Sun, 04 Oct 2026 06:00:00 +0000",
         "/resources/blog/not-all-complexity-can-be-processed-away-fred-brooks-proved-1986", "Ralph Jocham"),
    ], base="https://www.scrum.org/"))
save("https://www.mountaingoatsoftware.com/blog/rss", "feeds/mountaingoat.xml", rss(
    "Mike Cohn's Blog - Succeeding With Agile", "https://www.mountaingoatsoftware.com/blog", [
        ("AI Changes What Makes a Product Backlog Valuable", "2026-09-29T15:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/ai-changes-what-makes-a-product-backlog-valuable", "Mike Cohn"),
        ("AI Can Write Backlog Items. It Can’t Create Shared Understanding", "2026-09-15T15:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/ai-can-write-backlog-items-it-cant-create-shared-understanding", "Mike Cohn"),
        ("What Leaders Do That Keep Scrum Teams Working Like Individuals", "2026-09-01T17:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/what-leaders-do-that-keep-scrum-teams-working-like-individuals", "Mike Cohn"),
        ("Why Your Scrum Team Still Works Like Individuals", "2026-08-11T13:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/why-your-scrum-team-still-works-like-individuals", "Mike Cohn"),
        ("Leading Agile Initiatives: How Leaders Help Agile Change Succeed", "2026-07-28T16:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/leading-agile-initiatives-how-leaders-help-agile-change-succeed", "Mike Cohn"),
        ("Focusing Where We Can Have the Most Impact", "2026-07-07T16:00:00+00:00",
         "https://www.mountaingoatsoftware.com/agile/focusing-where-we-can-have-the-most-impact", "Mike Cohn"),
    ], date_tag="dc:date"))
save("https://feed.infoq.com/culture-methods", "feeds/infoq_culture_methods.xml", rss(
    "InfoQ - Culture & Methods", "https://www.infoq.com", [
        ("Presentation: The Reinvention of the Dev Team", "Wed, 07 Oct 2026 11:00:00 GMT",
         "https://www.infoq.com/presentations/agentic-dev-teams/" + INFOQ + "Culture+%26+Methods", "Hannah Foxwell"),
        ("How to Develop Software Engineering Skills in the Age of AI", "Thu, 01 Oct 2026 11:47:00 GMT",
         "https://www.infoq.com/news/2026/10/software-engineering-skills/" + INFOQ + "Culture+%26+Methods", "Ben Linders"),
        ("Presentation: Keeping the Mainline Green across Diverse Language Monorepos", "Thu, 01 Oct 2026 09:33:00 GMT",
         "https://www.infoq.com/presentations/mergequeue/" + INFOQ + "Culture+%26+Methods", "Dhruva Juloori"),
        ("InfoQ Online Cohorts Address AI Security and Coding Agent Verification", "Wed, 30 Sep 2026 17:00:00 GMT",
         "https://www.infoq.com/news/2026/09/onlinecohorts-ai-certifications/" + INFOQ + "Culture+%26+Methods", "Artenisa Chatziou"),
        ("Presentation: Context is the New Code", "Wed, 30 Sep 2026 11:00:00 GMT",
         "https://www.infoq.com/presentations/context-as-code-devops-agents/" + INFOQ + "Culture+%26+Methods", "Patrick Debois"),
        ("Presentation: From Staff Platform Engineer to a16z Founder: What I Wish I'd Known", "Tue, 29 Sep 2026 09:14:00 GMT",
         "https://www.infoq.com/presentations/staff-founder-lessons/" + INFOQ + "Culture+%26+Methods", "Gonzalo Maldonado"),
    ]))
save("https://feed.infoq.com/agile/", "feeds/infoq_agile.xml", rss(
    "InfoQ - Agile", "https://www.infoq.com", [
        ("Presentation: Building Resilient Platforms: Insights from 20+ Years in Mission-Critical Infrastructure", "Tue, 06 Oct 2026 09:59:00 GMT",
         "https://www.infoq.com/presentations/infrastructure-financial-services-platform/" + INFOQ + "Agile", "Matthew Liste"),
        ("Presentation: Building GenAI Platform at DoorDash", "Sat, 03 Oct 2026 11:00:00 GMT",
         "https://www.infoq.com/presentations/doordash-genai-platform-architecture/" + INFOQ + "Agile", "Siddharth Kodwani, Swaroop Chitlur"),
        ("Presentation: Keeping the Mainline Green across Diverse Language Monorepos", "Thu, 01 Oct 2026 09:33:00 GMT",
         "https://www.infoq.com/presentations/mergequeue/" + INFOQ + "Agile", "Dhruva Juloori"),
        ("Presentation: Context is the New Code", "Wed, 30 Sep 2026 11:00:00 GMT",
         "https://www.infoq.com/presentations/context-as-code-devops-agents/" + INFOQ + "Agile", "Patrick Debois"),
        ("Podcast: The AI Revolution Fails without Psychological Safety for Developers: a Conversation with Erin Doyle", "Mon, 28 Sep 2026 11:00:00 GMT",
         "https://www.infoq.com/podcasts/ai-revolution-psychological-safety/" + INFOQ + "Agile", "Erin Doyle"),
    ]))
TDPM = "https://thedigitalprojectmanager.com"
save("https://thedigitalprojectmanager.com/feed/", "feeds/digital_pm.xml", rss(
    "The Digital Project Manager", TDPM, [
        ("10 Project Management Software Benefits: Why Use It?", "Fri, 02 Oct 2026 20:19:06 +0000", TDPM + "/project-management/why-use-project-management-software-benefits/", "Ben Aston"),
        ("AI’s Hidden Change Management Debt", "Mon, 28 Sep 2026 16:57:46 +0000", TDPM + "/project-management/ais-hidden-change-management-debt/", "Kristen Kerr"),
        ("Top 18 Agile Coaches to Learn From in 2026", "Sat, 26 Sep 2026 16:31:36 +0000", TDPM + "/career/agile-coaches/", "Kristen Kerr"),
        ("Top 14 Women in Project Management to Follow in 2026", "Mon, 21 Sep 2026 15:52:49 +0000", TDPM + "/career/women-in-project-management/", "Kristen Kerr"),
        ("A Delivery Leader’s Take on Measuring Real Impact", "Fri, 18 Sep 2026 22:45:58 +0000", TDPM + "/pmo/how-to-measure-the-true-impact-of-your-projects/", "Kristen Kerr"),
        ("AI in the Wild: How 3 Teams Turned AI Into Real Operational Wins", "Wed, 02 Sep 2026 18:11:16 +0000", TDPM + "/pmo/ai-implementation-case-studies/", "Kristen Kerr"),
        ("Before Your AI Rollout, Fix This", "Tue, 01 Sep 2026 06:55:37 +0000", TDPM + "/pmo/before-your-ai-rollout-fix-this/"),
        ("14 Best Project Executive Newsletters to Subscribe to in 2026", "Tue, 25 Aug 2026 07:36:26 +0000", TDPM + "/project-management/project-executive-newsletters/"),
        ("8 Best COO Newsletters to Subscribe to in 2026", "Tue, 25 Aug 2026 05:13:11 +0000", TDPM + "/career/coo-newsletters/"),
        ("What PMOs Must Give Up to Survive AI Transformation", "Fri, 14 Aug 2026 07:47:44 +0000", TDPM + "/pmo/what-pmos-must-give-up-to-survive-ai-transformation/"),
        ("Delivery leader at Google shares how agentic workflows change PM models", "Mon, 10 Aug 2026 04:31:12 +0000", TDPM + "/pmo/anshumani-ruddra/"),
        ("The AI Data Governance Problem Ops Leaders Can’t Ignore", "Sat, 08 Aug 2026 02:13:27 +0000", TDPM + "/pmo/the-ai-data-governance-problem-ops-leaders-cant-ignore/"),
        ("AI Made This Delivery Head a Founder", "Wed, 29 Jul 2026 23:56:28 +0000", TDPM + "/career/michael-gold/"),
        ("PMBOK chair says project leaders should stop chasing AI tools and start reducing complexity", "Mon, 27 Jul 2026 18:35:57 +0000", TDPM + "/pmo/jesse-fewell/"),
        ("Privacy by Design: Building an AI Strategy That Doesn’t Compromise Trust", "Fri, 24 Jul 2026 23:25:32 +0000", TDPM + "/pmo/privacy-by-design-building-an-ai-strategy-that-doesnt-compromise-trust/"),
    ]))
save("https://www.projectmanager.com/blog/feed", "feeds/projectmanager.xml", rss(
    "Project Management Blog Archives - ProjectManager", "https://www.projectmanager.com/blog", [
        ("Project Time Tracking: Tools, Features and Software Reviews", "Wed, 07 Oct 2026 13:00:18 +0000", "https://www.projectmanager.com/blog/project-time-tracking"),
        ("ERP and Project Management: Bridging Finance and Execution", "Fri, 02 Oct 2026 18:08:54 +0000", "https://www.projectmanager.com/blog/erp-project-management-survey"),
        ("10 Best MYOB Acumatica Integrations for 2026", "Tue, 29 Sep 2026 19:45:43 +0000", "https://www.projectmanager.com/blog/best-myob-acumatica-integrations"),
    ]))
save("https://feeds.hbr.org/harvardbusiness", "feeds/hbr.xml", atom("HBR CMS", "http://hbr.org", [
    ("The AI Risk Your Company Is Overlooking", "2026-10-06T12:25:54Z", "/2026/10/the-ai-risk-your-company-is-overlooking"),
    ("Research: Sleep Deprivation Is a Leadership Problem", "2026-10-06T12:15:18Z", "/2026/10/research-sleep-deprivation-is-a-leadership-problem", "Els van der Helm"),
    ('Getting Your Boss to Buy into Your Strategy (from "Coaching Real Leaders")', "2026-10-06T11:04:04Z", "/podcast/2026/10/getting-your-boss-to-buy-into-your-strategy-from-coaching-real-leaders"),
    ("Optimism Is Now an Essential Leadership Skill", "2026-10-06T10:03:02Z", "/podcast/2026/10/optimism-is-now-an-essential-leadership-skill"),
    ("Research: When Pay Fluctuates, Workers Walk Away", "2026-10-05T12:25:27Z", "/2026/10/research-when-pay-fluctuates-workers-walk-away", "Lindsey D. Cameron", "Jirs Meuris"),
    ("There's No Such Thing as an AI-Ready Culture", "2026-10-05T12:15:14Z", "/2026/10/theres-no-such-thing-as-an-ai-ready-culture", "Sarah Jensen Clayton", "Michael Welch", "Khoi Tu"),
    ("What the Honda Super Cub Can Teach Us About Designing for Global Markets", "2026-10-05T12:05:09Z", "/2026/10/what-the-honda-super-cub-can-teach-us-about-designing-for-global-markets", "Amos Winter", "Vijay Govindarajan"),
    ("Your Workforce Isn't Fighting AI. It's Drawing the Blueprint for It.", "2026-10-02T16:44:05Z", "/sponsored/2026/10/your-workforce-isnt-fighting-ai-its-drawing-the-blueprint-for-it"),
    ("Remembering Howard Stevenson, Who Transformed the Study of Entrepreneurship", "2026-10-02T17:00:15Z", "/2026/10/remembering-howard-stevenson-who-transformed-the-study-of-entrepreneurship"),
    ("Match Your Pace to the Moment", "2026-10-02T12:25:45Z", "/2026/10/match-your-pace-to-the-moment-the-5-tempos-of-leadership"),
    ("Are You Hearing What Your Customers Are Telling You?", "2026-10-02T12:25:56Z", "/2026/10/are-you-hearing-what-your-customers-are-telling-you"),
    ("AI Is Making Verification the Bottleneck for Companies", "2026-10-02T12:15:33Z", "/2026/10/ai-is-making-verification-the-bottleneck-for-companies"),
    ("The Mindsets Leaders Need as AI Accelerates the Pace of Business", "2026-10-02T12:05:46Z", "/2026/10/the-mindsets-leaders-need-as-ai-accelerates-the-pace-of-business"),
    ("Accelerating Agentic AI in Production to Drive Measurable Outcomes", "2026-10-01T13:50:23Z", "/sponsored/2026/10/accelerating-agentic-ai-in-production-to-drive-measurable-outcomes"),
    ("Why Companies Should Support Crisis Volunteer Work", "2026-10-01T12:15:20Z", "/2026/10/why-companies-should-support-crisis-volunteer-work"),
    ("How AI Is Changing Cyber Threats—and Cybersecurity—for SMBs", "2026-10-01T12:05:07Z", "/2026/10/how-ai-is-changing-cyber-threats-and-cybersecurity-for-smbs"),
    ("How AI Is Changing Innovation: Why Speed Alone Isn't a Strategy", "2026-10-01T11:04:26Z", "/podcast/2026/10/how-ai-is-changing-innovation-why-speed-alone-isnt-a-strategy"),
    ("How Leaders Talk About AI Predicts Adoption", "2026-09-30T12:15:50Z", "/2026/09/how-leaders-talk-about-ai-predicts-adoption"),
]))
save("https://www.atlassian.com/blog/teamwork/feed", "feeds/atlassian_teamwork.xml", rss(
    "Teamwork, collaboration, and culture – Work Life by Atlassian", "https://www.atlassian.com/blog/teamwork", [
        ("Stop stitching together HR tools. Start Connecting Them.", "Wed, 22 Jul 2026 18:49:36 +0000", "https://www.atlassian.com/blog/teamwork/marketplace-for-hr"),
        ("How Bruno built community trust at scale with Jira and Released", "Tue, 23 Jun 2026 16:48:03 +0000", "https://www.atlassian.com/blog/jira/how-bruno-built-community-trust-with-jira"),
        ("How Ace Hardware Modernized IT with Jira Service Management", "Wed, 03 Jun 2026 21:49:15 +0000", "https://www.atlassian.com/blog/jira-service-management/how-ace-hardware-transformed-itsm"),
        ("The new shape of teamwork: Designing the Human+AI workforce", "Thu, 28 May 2026 16:43:28 +0000", "https://events.atlassian.com/team-digital/session-preview?sId=4058456"),
        ("The State of Nonprofit Teams 2026", "Wed, 13 May 2026 15:00:00 +0000", "https://www.atlassian.com/blog/teamwork/state-of-nonprofit-teams-2026"),
    ]))

# A sample YouTube channel feed in the documented Atom shape — used ONLY by the
# unit test of parse_channel_feed (the live feed is robots-disallowed). The
# video IDs/titles are placeholders, not real PMI-LA videos.
os.makedirs(FEEDS, exist_ok=True)
with open(os.path.join(FEEDS, "youtube_sample_feed.xml"), "w", encoding="utf-8") as f:
    f.write("""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>SAMPLE CHANNEL</title>
 <entry><id>yt:video:AAAAAAAAAAA</id><yt:videoId>AAAAAAAAAAA</yt:videoId><title>Sample Talk One</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/><published>2026-10-05T01:30:00+00:00</published></entry>
 <entry><id>yt:video:BBBBBBBBBBB</id><yt:videoId>BBBBBBBBBBB</yt:videoId><title>Sample Talk Two</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=BBBBBBBBBBB"/><published>2026-09-01T17:00:00+00:00</published></entry>
</feed>
""")

with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump({"captured": "2026-10-08",
               "note": "Values from live web-fetch reads on 2026-10-08; HTML structure reconstructed. See build_fixtures.py.",
               "responses": manifest}, f, indent=2)
print(f"wrote {len(manifest)} fixtures")

"""
THE one place the four tables' columns are defined.

Each table maps internal field names -> the column header written to the Google
Sheet / CSV. The Coda Google Sheets Pack maps sync-table columns BY HEADER
NAME, so:

  * never rename a header once Coda is syncing (add a new column instead),
  * only ever APPEND new columns at the end, so positions stay stable too.

`key` is the field that identifies a row across runs (the merge key). It is
always a canonical URL, so the same item seen twice is updated, not duplicated.
"""
from collections import OrderedDict

# Columns every table ends with. Filled in by the merge step, not collectors.
_META = [
    ("first_seen", "First Seen"),
    ("last_updated", "Last Updated"),
    ("freshness", "Freshness"),
]

TABLES = OrderedDict([
    ("events", {
        "worksheet": "Events",
        "key": "url",
        "columns": OrderedDict([
            ("title", "Title"),
            ("series", "Series"),
            ("full_title", "Full Title"),
            ("start_date", "Start Date"),
            ("end_date", "End Date"),
            ("start_time", "Start Time"),
            ("end_time", "End Time"),
            ("recurrence", "Recurrence"),
            ("time_zone", "Time Zone"),
            ("format", "Format"),
            ("location", "Location"),
            ("member_price", "Member Price"),
            ("non_member_price", "Non-member Price"),
            ("student_military_price", "Student/Military Price"),
            ("pdus", "PDUs"),
            ("pdu_details", "PDU Details"),
            ("talent_triangle", "Talent Triangle"),
            ("registration", "Registration"),
            ("register_url", "Register URL"),
            ("description", "Description"),
            ("status", "Status"),
            ("event_id", "Event ID"),
            ("url", "URL"),
            ("source", "Source"),
        ] + _META),
    }),
    ("blog", {
        "worksheet": "Blog",
        "key": "url",
        "columns": OrderedDict([
            ("title", "Title"),
            ("published", "Published"),
            ("author", "Author"),
            ("category", "Category"),
            ("excerpt", "Excerpt"),
            ("video_url", "Video URL"),
            ("url", "URL"),
            ("source", "Source"),
        ] + _META),
    }),
    ("recordings", {
        "worksheet": "Recordings",
        "key": "url",
        "columns": OrderedDict([
            ("title", "Title"),
            ("published", "Published"),
            ("video_id", "Video ID"),
            ("thumbnail_url", "Thumbnail URL"),
            ("found_via", "Found Via"),
            ("url", "URL"),
            ("source", "Source"),
        ] + _META),
    }),
    ("news", {
        "worksheet": "News",
        "key": "url",
        "columns": OrderedDict([
            ("headline", "Headline"),
            ("outlet", "Outlet"),
            ("published", "Published"),
            ("topic", "Topic"),
            ("url", "URL"),
            ("source", "Source"),
        ] + _META),
    }),
])

# Numeric columns: None means "not stated" (kept distinct from 0 = free).
NUMERIC_FIELDS = {"member_price", "non_member_price", "student_military_price", "pdus"}

# Fields whose values are DERIVED fresh at write time (never trusted from a
# stored row), like WebinarHub's Status column.
DERIVED_FIELDS = {"status", "freshness"}

# Fields where a blank from a page we DID read successfully is the truth, not a
# gap: it replaces an older value. (Blog categories: an earlier parser put every
# site-wide category on every post, and "none visible" must be able to clear that.)
BLANK_IS_VALID = {"blog": {"category"}}

# News is a rolling window; older items are dropped at write time so the Coda
# sync table stays small. Other tables keep everything (an archive).
RETENTION_DAYS = {"news": 120}

# Sort order for written rows: (field, descending?)
SORT = {
    "events": ("start_date", True),
    "blog": ("published", True),
    "recordings": ("published", True),
    "news": ("published", True),
}


def headers(table: str):
    return list(TABLES[table]["columns"].values())


def fields(table: str):
    return list(TABLES[table]["columns"].keys())


def header_to_field(table: str):
    return {v: k for k, v in TABLES[table]["columns"].items()}

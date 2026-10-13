"""
Read every outbound link in the PM Hub doc through the Coda / Superhuman Docs
REST API, so the weekly link check covers exactly what readers can click.

Needs two settings (see SETUP.md Part G):
  CODA_API_TOKEN   a read-only API token restricted to the hub doc
  CODA_DOC_ID      the hub's doc ID (default 2PnUJeapkp)

What it reads:
  * every table: each URL in any cell (link columns, and links inside text),
    labelled with the row's display value. Rows with an "Approved" checkbox
    that is unticked are skipped, because readers never see them.
  * every visible page: the page is exported as Markdown and the links in its
    text are collected (template sources, "learn more" links and so on).

Links to the hub itself (coda.io / docs.superhuman.com) are left out; the
check is about outside pages going stale.

Without a token, src/linkcheck.py falls back to data/hub_links.csv, a snapshot
of the same links taken when the hub was built.
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, Iterable, Iterator, List, Optional
from urllib.parse import urlsplit

import requests

API = "https://coda.io/apis/v1"
DEFAULT_DOC_ID = "2PnUJeapkp"
INTERNAL_HOSTS = ("coda.io", "docs.superhuman.com")
URL_RE = re.compile(r"https?://[^\s<>\"'\])]+")


def configured() -> bool:
    return bool(os.environ.get("CODA_API_TOKEN"))


def is_internal(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in INTERNAL_HOSTS)


def urls_in(value) -> Iterator[str]:
    """Every http(s) URL inside a rich cell value (dicts, lists, Markdown)."""
    if isinstance(value, str):
        for m in URL_RE.finditer(value):
            yield m.group(0).rstrip(".,;:")
    elif isinstance(value, dict):
        for v in value.values():
            yield from urls_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from urls_in(v)


def _unticked(values: Dict) -> bool:
    v = values.get("Approved")
    return v is False or (isinstance(v, str) and v.strip().lower() == "false")


def links_from_rows(table_name: str, rows: Iterable[Dict]) -> List[Dict]:
    """API rows ({name, values: {column: rich value}}) -> link records."""
    out = []
    for row in rows:
        values = row.get("values") or {}
        if _unticked(values):
            continue
        item = str(row.get("name") or "").strip()
        for column, value in values.items():
            for url in urls_in(value):
                if not is_internal(url):
                    out.append({"Where": table_name, "Item": item, "Field": column, "URL": url})
    return out


def links_from_markdown(page_name: str, markdown: str) -> List[Dict]:
    out = []
    for url in urls_in(markdown):
        if not is_internal(url):
            out.append({"Where": f"Page: {page_name}", "Item": page_name,
                        "Field": "Text link", "URL": url})
    return out


class CodaClient:
    def __init__(self, token: Optional[str] = None, doc_id: Optional[str] = None,
                 log=print, timeout: float = 30):
        self.doc_id = doc_id or os.environ.get("CODA_DOC_ID") or DEFAULT_DOC_ID
        self.log = log
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token or os.environ['CODA_API_TOKEN']}"

    def _get(self, path: str, **params) -> Dict:
        for attempt in range(4):
            resp = self.session.get(f"{API}{path}", params=params, timeout=self.timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt * 2)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"Coda API {resp.status_code} for {path}: {resp.text[:200]}")
            return resp.json()
        raise RuntimeError(f"Coda API kept failing for {path}")

    def _paged(self, path: str, **params) -> Iterator[Dict]:
        token = None
        while True:
            q = dict(params, limit=params.get("limit", 100))
            if token:
                q["pageToken"] = token
            data = self._get(path, **q)
            yield from data.get("items", [])
            token = data.get("nextPageToken")
            if not token:
                return

    def tables(self) -> List[Dict]:
        return list(self._paged(f"/docs/{self.doc_id}/tables", tableTypes="table"))

    def rows(self, table_id: str) -> List[Dict]:
        return list(self._paged(f"/docs/{self.doc_id}/tables/{table_id}/rows",
                                valueFormat="rich", useColumnNames="true", limit=200))

    def pages(self) -> List[Dict]:
        return list(self._paged(f"/docs/{self.doc_id}/pages"))

    def page_markdown(self, page_id: str, wait_seconds: float = 60) -> str:
        resp = self.session.post(f"{API}/docs/{self.doc_id}/pages/{page_id}/export",
                                 json={"outputFormat": "markdown"}, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"export {resp.status_code}: {resp.text[:200]}")
        req_id = resp.json()["id"]
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(2)
            status = self._get(f"/docs/{self.doc_id}/pages/{page_id}/export/{req_id}")
            if status.get("status") == "complete":
                return requests.get(status["downloadLink"], timeout=self.timeout).text
            if status.get("status") == "failed":
                raise RuntimeError(status.get("error") or "export failed")
        raise RuntimeError("export timed out")

    def all_links(self) -> List[Dict]:
        links: List[Dict] = []
        for t in self.tables():
            try:
                links += links_from_rows(t["name"], self.rows(t["id"]))
            except Exception as e:
                self.log(f"  ⚠ table {t.get('name')}: {e}")
        for p in self.pages():
            if p.get("isHidden") or p.get("isEffectivelyHidden"):
                continue
            try:
                links += links_from_markdown(p["name"], self.page_markdown(p["id"]))
            except Exception as e:
                self.log(f"  ⚠ page {p.get('name')}: {e}")
        return links

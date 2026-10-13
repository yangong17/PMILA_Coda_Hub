"""
Second look at links the plain checker was refused on (HTTP 400/401/403/429),
using a real headless Chromium, which loads the page the way a reader's browser
does (JavaScript, cookies, redirects, a browser's own User-Agent).

Used only for links that came back "Blocked". Whatever it finds replaces the
Blocked result; a link that is still refused stays Blocked ("open it by hand").
Nothing here solves CAPTCHAs, rotates IP addresses or hides the traffic: one
visit per link, spaced out, from the runner.

Needs `pip install playwright` and `playwright install --with-deps chromium`
(the workflow does both). Without them available() is False and the check simply
keeps its Blocked results.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlsplit

from .fetching import Probe

try:                                    # optional dependency
    from playwright.sync_api import sync_playwright
except Exception:                       # pragma: no cover
    sync_playwright = None


def available() -> bool:
    return sync_playwright is not None


class BrowserProber:
    def __init__(self, delay: float = 3.0, timeout_ms: int = 30_000, log=print):
        self.delay, self.timeout_ms, self.log = delay, timeout_ms, log
        self._pw = self._browser = self._ctx = None
        self._last: dict = {}

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        ua = self._browser.new_context().new_page().evaluate("navigator.userAgent")
        self._ctx = self._browser.new_context(
            user_agent=ua.replace("HeadlessChrome", "Chrome"),
            locale="en-US", viewport={"width": 1366, "height": 850})
        return self

    def __exit__(self, *exc):
        for obj in (self._ctx, self._browser):
            try:
                obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    def probe(self, url: str, max_chars: int = 300_000) -> Probe:
        host = urlsplit(url).netloc
        wait = self.delay - (time.monotonic() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            status = resp.status if resp else None
            ctype = (resp.headers.get("content-type", "") if resp else "").split(";")[0].lower()
            return Probe(url, status=status, final_url=page.url, content_type=ctype,
                         text=page.content()[:max_chars])
        except Exception as e:
            return Probe(url, error=str(e).splitlines()[0][:160])
        finally:
            page.close()

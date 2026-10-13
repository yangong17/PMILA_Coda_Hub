"""
The only way collectors touch the network. (Named fetching.py, not http.py,
so it can never shadow the standard-library `http` package.)

PoliteFetcher
  * identifies itself with a descriptive User-Agent (config.USER_AGENT)
  * checks robots.txt for every host before fetching, and refuses disallowed
    paths (RobotsDisallowed) — there is deliberately no override switch
  * waits REQUEST_DELAY_SECONDS between two requests to the same host
  * uses timeouts and retries with exponential backoff (honours Retry-After)

FixtureFetcher
  Same interface, but answers from saved files listed in a manifest
  (url -> file). Used by the tests and by `python -m src.main --fixtures ...`
  so parsers can be exercised without network access.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional
from urllib import robotparser
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src import config


class RobotsDisallowed(Exception):
    """robots.txt for this host asks automated agents not to fetch this URL."""


class FetchError(Exception):
    pass


def _short(e: Exception) -> str:
    """One-line reason for a requests error (no giant urllib3 repr)."""
    msg = str(e)
    for marker in ("Tunnel connection failed: ", "Caused by ", "NameResolutionError"):
        if marker in msg:
            return msg[msg.index(marker):][:160].rstrip(")'\"")
    return msg[:160]


class PoliteFetcher:
    def __init__(self, user_agent: str = config.USER_AGENT,
                 delay: float = config.REQUEST_DELAY_SECONDS,
                 timeout: float = config.REQUEST_TIMEOUT_SECONDS,
                 retries: int = config.REQUEST_RETRIES,
                 log=print):
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.8",
        })
        retry = Retry(
            total=retries, connect=retries, read=retries, status=retries,
            backoff_factor=2,  # 2s, 4s, 8s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_hit: Dict[str, float] = {}
        self._robots: Dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._dead: Dict[str, str] = {}
        self.request_count = 0

    # ── robots.txt ───────────────────────────────────────────────────────────
    def _robots_for(self, url: str) -> Optional[robotparser.RobotFileParser]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._dead:
            raise FetchError(f"{origin} skipped this run ({self._dead[origin]})")
        if origin in self._robots:
            return self._robots[origin]
        rp = robotparser.RobotFileParser()
        robots_url = origin + "/robots.txt"
        try:
            self._throttle(parts.netloc)
            resp = self.session.get(robots_url, timeout=self.timeout)
            self.request_count += 1
            if resp.status_code >= 500:
                # RFC 9309: server error -> assume complete disallow.
                rp.disallow_all = True
            elif resp.status_code >= 400:
                # RFC 9309: 4xx (no robots.txt) -> no restrictions.
                rp.allow_all = True
            else:
                rp.parse(resp.text.splitlines())
        except requests.RequestException as e:
            # Nothing is fetched from a host whose robots.txt we couldn't read,
            # and the host is skipped for the rest of this run (fail fast, and
            # don't keep knocking on a server that is down).
            self._dead[origin] = f"robots.txt unreachable: {_short(e)}"
            raise FetchError(f"{origin} {self._dead[origin]}") from None
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return rp is None or rp.can_fetch(self.user_agent, url)

    # ── fetching ─────────────────────────────────────────────────────────────
    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, check_robots: bool = True,
            params: Optional[dict] = None) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        self._throttle(urlsplit(url).netloc)
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise FetchError(f"{url.split('?')[0]}: {_short(e)}") from None
        self.request_count += 1
        if resp.status_code >= 400:
            # Never echo query strings: an API key may be in them.
            raise FetchError(f"HTTP {resp.status_code} for {url.split('?')[0]}")
        return resp

    def text(self, url: str, **kw) -> str:
        resp = self.get(url, **kw)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text

    def content(self, url: str, **kw) -> bytes:
        return self.get(url, **kw).content

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()

    # ── link checking ────────────────────────────────────────────────────────
    def probe(self, url: str, max_bytes: int = 300_000) -> "Probe":
        """One polite GET that never raises: what a reader clicking the link
        would get. Reads at most max_bytes of the body (enough for <title> and
        the opening text), follows redirects, honours robots.txt."""
        try:
            if not self.allowed(url):
                return Probe(url, error="robots.txt asks automated agents not to fetch this page",
                             robots_blocked=True)
        except FetchError as e:
            return Probe(url, error=str(e))
        self._throttle(urlsplit(url).netloc)
        try:
            with self.session.get(url, timeout=self.timeout, stream=True,
                                  allow_redirects=True) as resp:
                self.request_count += 1
                ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                body = b""
                if "html" in ctype or "xml" in ctype or "json" in ctype or not ctype:
                    for chunk in resp.iter_content(16_384):
                        body += chunk
                        if len(body) >= max_bytes:
                            break
                enc = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else "utf-8"
                return Probe(url, status=resp.status_code, final_url=resp.url,
                             content_type=ctype, text=body.decode(enc, errors="replace"))
        except requests.RequestException as e:
            return Probe(url, error=_short(e))


class Probe:
    """Result of PoliteFetcher.probe (plain attributes, easy to fake in tests)."""

    def __init__(self, url: str, status: Optional[int] = None, final_url: str = "",
                 content_type: str = "", text: str = "", error: str = "",
                 robots_blocked: bool = False):
        self.url = url
        self.status = status
        self.final_url = final_url or url
        self.content_type = content_type
        self.text = text
        self.error = error
        self.robots_blocked = robots_blocked


class FixtureFetcher:
    """Replays saved responses. manifest.json maps absolute URL -> file path
    (relative to the manifest). A robots.txt URL that is listed is honoured
    exactly like the live fetcher; one that is not listed allows everything."""

    def __init__(self, manifest_path: str, user_agent: str = config.USER_AGENT, log=print):
        self.user_agent = user_agent
        self.log = log
        self.root = os.path.dirname(os.path.abspath(manifest_path))
        with open(manifest_path, encoding="utf-8") as f:
            self.map: Dict[str, str] = json.load(f)["responses"]
        self._robots: Dict[str, robotparser.RobotFileParser] = {}
        self.request_count = 0

    def _path(self, url: str) -> str:
        if url not in self.map:
            raise FetchError(f"no fixture for {url}")
        return os.path.join(self.root, self.map[url])

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            robots_url = origin + "/robots.txt"
            if robots_url in self.map:
                with open(self._path(robots_url), encoding="utf-8") as f:
                    rp.parse(f.read().splitlines())
            else:
                rp.allow_all = True
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(self.user_agent, url)

    def content(self, url: str, check_robots: bool = True, **_) -> bytes:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        self.request_count += 1
        with open(self._path(url), "rb") as f:
            return f.read()

    def text(self, url: str, **kw) -> str:
        return self.content(url, **kw).decode("utf-8")

    def json(self, url: str, **kw):
        return json.loads(self.text(url, **kw))

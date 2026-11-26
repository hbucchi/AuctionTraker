"""Base class every site scraper extends.

The contract is intentionally tiny so an AI agent (or a human) can fix one
site without touching the others:

* ``scrape()`` yields ``Listing`` objects — fetching + pagination live here.
* Parsing is done by pure functions (``parse_*``) that take raw HTML/JSON and
  return listings. Tests feed them saved fixtures, so a parser can be fixed
  and verified offline.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator

from ..http import PoliteSession
from ..models import Listing


class ScraperError(RuntimeError):
    pass


class BaseScraper(ABC):
    #: short machine name, used in ids ("zuk:238463") and on the CLI
    name: str = ""
    #: home page, for humans reading reports
    base_url: str = ""
    #: hard cap so a pagination bug can never loop forever
    max_pages: int = 200
    #: seconds between requests to this site
    min_interval: float = 1.0
    #: a run returning fewer listings than this is flagged as suspicious
    expected_min_listings: int = 1
    #: extra OpenSSL cipher suites for servers with outdated TLS (None = defaults)
    extra_ciphers: str | None = None

    def __init__(self, max_pages: int | None = None):
        if max_pages is not None:
            self.max_pages = max_pages
        self.log = logging.getLogger(f"scraper.{self.name}")
        self._session: PoliteSession | None = None
        #: total the site itself advertises, when it does; set by scrape()
        #: so the health check can compare coverage
        self.reported_total: int | None = None

    @property
    def session(self) -> PoliteSession:
        if self._session is None:
            self._session = PoliteSession(min_interval=self.min_interval, extra_ciphers=self.extra_ciphers)
        return self._session

    def get(self, url: str, **kw):
        r = self.session.get(url, **kw)
        if "charset" not in r.headers.get("Content-Type", "").lower():
            # requests falls back to ISO-8859-1 when no charset is declared,
            # which turns "m²" into "mÂ²". These sites all serve UTF-8.
            r.encoding = "utf-8"
        if r.status_code >= 400:
            raise ScraperError(f"GET {url} -> HTTP {r.status_code}")
        return r

    @abstractmethod
    def scrape(self) -> Iterator[Listing]:
        """Yield every currently listed opportunity on the site."""

    def run(self) -> list[Listing]:
        """Scrape, finalize and de-duplicate by id (last one wins)."""
        out: dict[str, Listing] = {}
        for item in self.scrape():
            item.finalize()
            out[item.id] = item
        return list(out.values())

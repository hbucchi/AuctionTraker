"""A polite HTTP client: one session per site, retries with backoff, and a
minimum delay between requests so we never hammer anyone's server."""

from __future__ import annotations

import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


class _CipherAdapter(HTTPAdapter):
    """HTTPAdapter whose TLS context also offers extra (older) cipher suites.

    Certificate and hostname verification stay ON; this only widens the list
    of ciphers offered, for servers that don't support modern ones."""

    def __init__(self, extra_ciphers: str, **kw):
        ctx = ssl.create_default_context()
        ctx.set_ciphers(f"DEFAULT:{extra_ciphers}")
        self._ctx = ctx
        super().__init__(**kw)

    def init_poolmanager(self, *args, **kw):
        kw["ssl_context"] = self._ctx
        return super().init_poolmanager(*args, **kw)

    def proxy_manager_for(self, *args, **kw):
        kw["ssl_context"] = self._ctx
        return super().proxy_manager_for(*args, **kw)


class PoliteSession(requests.Session):
    def __init__(self, min_interval: float = 1.0, timeout: float = 30.0, extra_ciphers: str | None = None):
        super().__init__()
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.headers.update({"User-Agent": DEFAULT_UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        retry = Retry(
            total=4,
            backoff_factor=2,  # 2s, 4s, 8s, 16s
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
        )
        adapter = (
            _CipherAdapter(extra_ciphers, max_retries=retry) if extra_ciphers else HTTPAdapter(max_retries=retry)
        )
        self.mount("https://", adapter)
        self.mount("http://", adapter)

    def request(self, method, url, **kwargs):  # type: ignore[override]
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = super().request(method, url, **kwargs)
        finally:
            self._last = time.monotonic()
        log.debug("%s %s -> %s", method, url, resp.status_code)
        return resp

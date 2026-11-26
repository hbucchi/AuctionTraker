"""Picelli Leilões — https://www.picellileiloes.com.br

How the site works (verified 2026-11-26):
* React SPA ("Ares" white-label platform). The HTML is an empty shell; the
  browser builds the page from data it downloads after load.
* We therefore open the public home page in a headless browser (Playwright)
  and read the auctions list the page itself downloads (a response whose URL
  contains ``/rest/v1/auctions`` and ``home_tab=``). We never call the
  backend directly — the scraper sees exactly what a visitor's browser sees.
* One auction usually holds one lot. Auction phases (1º/2º leilão) carry the
  end dates; each lot's ``lot_phases`` carry the minimum bid per phase.
* Auction descriptions (the full edital) contain debtors' personal data
  (names, CPF). We deliberately don't store them.

Needs: ``pip install playwright``. In this repo's cloud container Chromium is
pre-installed; point PLAYWRIGHT_CHROMIUM_PATH at it (see README).
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

from ..models import AuctionRound, Listing
from ..parsing import clean, guess_category, guess_property_type, split_city_uf
from .base import BaseScraper, ScraperError

BASE = "https://www.picellileiloes.com.br"
OPEN_STATUSES = {"aberto", "futuro"}


def auctions_to_listings(auctions: list[dict[str, Any]]) -> list[Listing]:
    out = []
    for a in auctions:
        if a.get("status") not in OPEN_STATUSES or a.get("hidden"):
            continue
        phases = sorted(a.get("auction_phases") or [], key=lambda p: p.get("phase_order") or 0)
        sub = clean(a.get("subtitle")) or ""
        city, uf = split_city_uf(sub.replace(",", " /"))  # "Hortolândia, SP" -> "Hortolândia / SP"
        title = clean(a.get("title")) or a.get("slug") or a["id"]
        lots = [lot for lot in (a.get("lots") or []) if not lot.get("hidden")] or [{"id": a["id"]}]
        for i, lot in enumerate(lots):
            values = {p.get("phase_order"): p.get("announced_value") for p in lot.get("lot_phases") or []}
            rounds = [
                AuctionRound(
                    number=p.get("phase_order") or n,
                    date=p.get("end_date"),
                    min_bid=values.get(p.get("phase_order")),
                )
                for n, p in enumerate(phases, start=1)
            ]
            active = a.get("active_phase_order")
            current = values.get(active) if active in values else None
            out.append(
                Listing(
                    source="picelli",
                    source_id=str(lot["id"]),
                    url=f"{BASE}/leilao/{a.get('slug') or a['id']}",
                    title=title if len(lots) == 1 else f"{title} (lote {i + 1})",
                    category=guess_category(title),
                    property_type=guess_property_type(title),
                    modality=clean(a.get("auction_type")),
                    status=a.get("status"),
                    seller=clean((a.get("sellers") or {}).get("name")),
                    city=city,
                    state=uf,
                    current_price=current,
                    rounds=rounds,
                    image_url=a.get("image_url"),
                    bids_count=a.get("bids_count"),
                    extra={"auction_id": a["id"], "auction_code": a.get("code"), "installments": lot.get("allows_installment")},
                )
            )
    return out


class PicelliScraper(BaseScraper):
    name = "picelli"
    base_url = BASE
    expected_min_listings = 10

    def scrape(self) -> Iterator[Listing]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise ScraperError("playwright is not installed: pip install playwright") from e

        captured: list[str] = []

        def is_auctions(resp) -> bool:
            u = resp.url
            return "/rest/v1/auctions" in u and "home_tab=" in u and resp.ok

        with sync_playwright() as p:
            exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
            try:
                page = browser.new_page()
                # Wait for the one response we need instead of "network idle":
                # analytics and chat widgets can keep the network busy forever.
                with page.expect_response(is_auctions, timeout=120_000) as resp_info:
                    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=120_000)
                captured.append(resp_info.value.text())
            finally:
                browser.close()

        if not captured:
            raise ScraperError("auctions data was not loaded by the home page — site changed?")
        auctions = max((json.loads(c) for c in captured), key=len)
        self.log.info("page loaded %d auctions", len(auctions))
        yield from auctions_to_listings(auctions)

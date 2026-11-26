"""Alfa Leilões — https://www.alfaleiloes.com

How the site works (verified 2026-11-26):
* Server-rendered Django pages. /leiloes/?<filters>&page=N lists ~20 lot
  cards per page; requesting a page past the last one returns HTTP 404.
* We use the same filter the site's own "Leilões abertos" link uses:
  every auction type, status Aberto / Futuro / Em breve.
* Card markup: ``div.home-leiloes-cards`` (see parse_cards). Rounds whose
  minimum bid is struck through (``text-decoration: line-through``) already
  happened without a winner.
"""

from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import AuctionRound, Listing
from ..parsing import (
    clean,
    guess_category,
    guess_property_type,
    parse_area,
    parse_br_datetime,
    parse_brl,
    split_city_uf,
)
from .base import BaseScraper, ScraperError

BASE = "https://www.alfaleiloes.com"
LIST_PARAMS = [
    ("tipo_leilao", "JUDICIAL"),
    ("tipo_leilao", "EXTRAJUDICIAL"),
    ("tipo_leilao", "ALIENAÇÃO PARTICULAR"),
    ("status", "Aberto"),
    ("status", "Futuro"),
    ("status", "Em breve"),
    ("filter_first", "1"),
]


def _split_title(title: str) -> tuple[str, str, str]:
    parts = re.split(r"\s[-–]\s", title, maxsplit=1)
    return (parts[0], " - ", parts[1]) if len(parts) == 2 else (title, "", "")


def parse_cards(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select("div.home-leiloes-cards"):
        a = card.select_one('.card-image a[href^="/lote/"]')
        if not a:
            continue
        href = a["href"]
        m = re.match(r"/lote/(\d+)/", href)
        if not m:
            continue
        title = clean(card.select_one(".card-content").get_text(" ")) if card.select_one(".card-content") else None
        if not title:
            continue
        # "Itatiba (SP) - Terreno no Bairro da Ponte com 1.005m²" (dash or en-dash)
        head, _, rest = _split_title(title)
        city, uf = split_city_uf(head)

        rounds = []
        for i, blk in enumerate(card.select(".card-lances"), start=1):
            txt = blk.get_text(" ")
            money = blk.select_one("[js-money]")
            n = re.search(r"(\d)\s*ª", txt)
            rounds.append(
                AuctionRound(
                    number=int(n.group(1)) if n else i,
                    date=parse_br_datetime(txt),
                    min_bid=parse_brl(money.get_text()) if money else None,
                )
            )
        promo = [clean(p.get_text(" ")) for p in card.select(".card-imagem-text p")]
        discount = None
        for p in promo:
            dm = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*de\s*desconto", p or "", re.I)
            if dm:
                discount = parse_brl(dm.group(1))
        modality = card.select_one(".card-content-judicial p")
        status = card.select_one(".card-status p")
        img = card.select_one(".card-image img")
        out.append(
            Listing(
                source="alfa",
                source_id=m.group(1),
                url=urljoin(BASE, href),
                title=title,
                category=guess_category(title),
                property_type=guess_property_type(rest or title),
                modality=clean(modality.get_text()).lower() if modality else None,
                status=clean(status.get_text()) if status else None,
                city=city,
                state=uf,
                area_m2=parse_area(title),
                discount_pct=discount,
                rounds=rounds,
                image_url=img.get("src") if img else None,
                extra={"promo": [p for p in promo if p]},
            )
        )
    return out


class AlfaScraper(BaseScraper):
    name = "alfa"
    base_url = BASE
    expected_min_listings = 50
    max_pages = 60

    def scrape(self) -> Iterator[Listing]:
        for page in range(1, self.max_pages + 1):
            r = self.session.get(f"{BASE}/leiloes/", params=LIST_PARAMS + [("page", page)])
            if r.status_code == 404:
                break  # past the last page
            if r.status_code >= 400:
                raise ScraperError(f"page {page}: HTTP {r.status_code}")
            batch = parse_cards(r.text)
            if not batch:
                break
            yield from batch

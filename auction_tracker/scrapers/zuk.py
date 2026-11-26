"""Portal Zuk — https://www.portalzuk.com.br

How the site works (verified 2026-11-26):
* GET /leilao-de-imoveis renders the first 30 property cards as server HTML,
  plus a Laravel CSRF token (<input name="_token">) and a session cookie.
* The "Carregar mais" button POSTs to /leilao-de-imoveis/mais with
  ``limit`` = number of cards already on screen and gets the next ~30 cards
  as an HTML fragment. An empty fragment means we reached the end.
  The request needs the ``X-CSRF-TOKEN`` header (the token alone in the body
  returns HTTP 500).
* Card markup: ``div.card-property.card_lotes_div`` (see parse_cards).
* The header counter ("1017 oportunidades") counts some properties twice;
  paging through all of it yields ~4% repeated cards. Measured 2026-11-26:
  three different sort orders all union to the same 979 unique listings, so
  dedup (done in BaseScraper.run) is expected and nothing is lost.
"""

from __future__ import annotations

import re
from typing import Iterator

from bs4 import BeautifulSoup

from ..models import AuctionRound, Listing
from ..parsing import clean, guess_category, parse_area, parse_br_datetime, parse_brl, split_city_uf
from .base import BaseScraper, ScraperError

LIST_URL = "https://www.portalzuk.com.br/leilao-de-imoveis"
MORE_URL = "https://www.portalzuk.com.br/leilao-de-imoveis/mais"


def parse_total(html: str) -> int | None:
    m = re.search(r'list-header-opportunities"><strong>([\d.]+)</strong>', html)
    return int(m.group(1).replace(".", "")) if m else None


def parse_cards(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Listing] = []
    for card in soup.select("div.card-property.card_lotes_div"):
        a = card.select_one(".card-property-image-wrapper a[href]")
        if not a:
            continue
        url = a["href"].split("?")[0]
        m = re.search(r"/(\d+-\d+)$", url)
        source_id = m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]

        # title attr looks like: " em leilão - Rua X, 319 - Sete Lagoas/MG - Sicoob Credisete | Z38041"
        title_attr = clean(a.get("title")) or ""
        seller = None
        parts = [p.strip() for p in title_attr.split(" - ")]
        if len(parts) >= 4:
            seller = clean(parts[-1].split("|")[0])

        ptype = clean(card.select_one(".card-property-price-lote").get_text()) if card.select_one(
            ".card-property-price-lote"
        ) else None

        city = state = neighborhood = street = None
        addr = card.select_one("address.card-property-address")
        if addr:
            spans = addr.find_all("span", recursive=False)
            if spans:
                loc = clean(spans[0].get_text(" "))  # "Sete Lagoas / MG - Morro do Claro"
                if loc:
                    city_part, _, neighborhood = loc.partition(" - ")
                    city, state = split_city_uf(city_part)
                    neighborhood = clean(neighborhood)
            if len(spans) > 1:
                street = clean(spans[1].get_text(" "))

        area = None
        for lab in card.select(".card-property-info-label"):
            area = parse_area(lab.get_text())
            if area:
                break

        rounds: list[AuctionRound] = []
        status = None
        for li in card.select("li.card-property-price"):
            label = clean(li.select_one(".card-property-price-label").get_text()) if li.select_one(
                ".card-property-price-label"
            ) else None
            value_el = li.select_one(".card-property-price-value")
            date_el = li.select_one(".card-property-price-data")
            if not value_el:
                continue
            for pct in value_el.select(".card-property-price-percent"):
                pct.decompose()  # "↓42%" badge would otherwise be read as part of the price
            value_text = value_el.get_text(" ")
            n = re.match(r"(\d)", label or "")
            rounds.append(
                AuctionRound(
                    number=int(n.group(1)) if n else len(rounds) + 1,
                    date=parse_br_datetime(date_el.get_text()) if date_el else None,
                    min_bid=parse_brl(value_text),
                )
            )
            if label and not n:
                status = label  # e.g. "Venda Direta", "Recebendo propostas"

        img = card.select_one(".card-property-image-wrapper img")
        title = " - ".join(x for x in [ptype, street, f"{city}/{state}" if city else None] if x)
        out.append(
            Listing(
                source="zuk",
                source_id=source_id,
                url=url,
                title=title or title_attr,
                category=guess_category(ptype) if ptype else "imovel",
                property_type=ptype,
                status=status,
                seller=seller,
                address=street,
                neighborhood=neighborhood,
                city=city,
                state=state,
                area_m2=area,
                rounds=rounds,
                image_url=img.get("src") if img else None,
                extra={"partner": card.get("data-parceiro") not in (None, "0")},
            )
        )
    return out


class ZukScraper(BaseScraper):
    name = "zuk"
    base_url = "https://www.portalzuk.com.br"
    expected_min_listings = 300
    max_pages = 80  # 30 per page -> 2400 listings cap

    def scrape(self) -> Iterator[Listing]:
        first = self.get(LIST_URL).text
        m = re.search(r'name="_token" value="([^"]+)"', first)
        if not m:
            raise ScraperError("CSRF token not found on listing page")
        token = m.group(1)
        total = self.reported_total = parse_total(first)
        self.log.info("site reports %s listings", total)

        cards = parse_cards(first)
        seen = len(cards)
        own = sum(1 for c in cards if not c.extra.get("partner"))
        yield from cards

        for _ in range(self.max_pages):
            r = self.session.post(
                MORE_URL,
                data={
                    "limit": seen,
                    "count_imovel_zuk": own,
                    "path": LIST_URL,
                    "order": "data_leilao",
                    "div_parceiro_count": 0,
                    "_token": token,
                },
                headers={
                    "X-CSRF-TOKEN": token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": LIST_URL,
                },
            )
            if r.status_code >= 400:
                raise ScraperError(f"load-more failed at offset {seen}: HTTP {r.status_code}")
            batch = parse_cards(r.text)
            if not batch:
                break
            seen += len(batch)
            own += sum(1 for c in batch if not c.extra.get("partner"))
            yield from batch
            if total and seen >= total:
                break

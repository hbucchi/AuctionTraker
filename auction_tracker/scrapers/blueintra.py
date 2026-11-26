"""Biasi Leilões and Frazão Leilões.

Both run on the same white-label ASP.NET auction platform (images are served
from ``*.blueintra.com`` / the same ``/images/lot/..`` layout, same
``/Sale/...`` controllers), but each site is on a different version of it, so
the listing endpoint and card markup differ:

Biasi  (verified 2026-11-26)
  GET /Sale/LotListSearch?categoria=0&subcategoria=0&term=&start=N&limit=48
  -> HTML fragment, ``#leilao-lista-lote[total]`` holds the total count,
     cards are ``a.leilao-lote[data-id]``.

Frazão (verified 2026-11-26)
  GET /Sale/SearchLotResult?loteAtivo=true&start=N&limit=20&page=P
  -> HTML fragment, ``#leilao-lista-lote[total]``, cards are ``#card-lote``
     blocks with ``a.visualizar_lote[data-lote-id]``.
  (Frazão's *other* endpoint, LotListSearch, returns a 10 000-item feed that
  mixes in lots cross-listed from Portal Zuk — don't use it.)
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
from .base import BaseScraper


def parse_total(html: str) -> int | None:
    m = re.search(r'id="leilao-lista-lote"[^>]*total="(\d+)"', html)
    return int(m.group(1)) if m else None


def _status_from_classes(el) -> str | None:
    return clean(el.get_text(" ")) if el else None


# ---------------------------------------------------------------- Biasi ----
BIASI = "https://www.biasileiloes.com.br"


def parse_biasi(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select("a.leilao-lote[data-id]"):
        lot_id = a["data-id"]
        title = clean(a.select_one(".card-title").get_text(" ")) if a.select_one(".card-title") else None
        if not title:
            continue
        # "Loja no Centro - Rio de Janeiro/RJ"
        loc = title.rsplit(" - ", 1)[-1] if " - " in title else title
        city, uf = split_city_uf(loc)
        if not city:
            city, uf = split_city_uf(title)

        price = None
        price_label = None
        for blk in a.select(".price-leiloes"):
            spans = blk.find_all("span")
            if len(spans) >= 2:
                price_label = clean(spans[0].get_text(" "))
                price = parse_brl(spans[-1].get_text())
                break
        bids = None
        for sp in a.find_all("span"):
            m = re.match(r"\s*(\d+)\s+Lances?", sp.get_text())
            if m:
                bids = int(m.group(1))
                break
        status_el = a.select_one("[class*='status-'] span") or a.select_one("[class*='status-']")
        seller_img = a.select_one("img.image-comitente")
        seller = None
        if seller_img and seller_img.get("alt", "").startswith("Logo de "):
            seller = clean(seller_img["alt"][len("Logo de "):])
        img = a.select_one("img.card-img-cover")
        lot_label = a.select_one(".card-label span span")
        out.append(
            Listing(
                source="biasi",
                source_id=lot_id,
                url=urljoin(BIASI, a["href"]),
                title=title,
                category=guess_category(title),
                property_type=guess_property_type(title),
                status=_status_from_classes(status_el),
                seller=seller,
                city=city,
                state=uf,
                current_price=price,
                bids_count=bids,
                image_url=img.get("src") if img else None,
                extra={"price_label": price_label, "lot": clean(lot_label.get_text()) if lot_label else None},
            )
        )
    return out


class BiasiScraper(BaseScraper):
    name = "biasi"
    base_url = BIASI
    expected_min_listings = 100
    page_size = 48

    def scrape(self) -> Iterator[Listing]:
        start, total = 0, None
        for _ in range(self.max_pages):
            r = self.get(
                f"{BIASI}/Sale/LotListSearch",
                params={
                    "categoria": 0,      # 0 = every category (imóveis, veículos, ...)
                    "subcategoria": 0,
                    "term": "",
                    "start": start,
                    "limit": self.page_size,
                    "buscaImovel": "false",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            if total is None:
                total = self.reported_total = parse_total(r.text)
                self.log.info("site reports %s lots", total)
            batch = parse_biasi(r.text)
            if not batch:
                break
            yield from batch
            start += self.page_size
            if total is not None and start >= total:
                break


# --------------------------------------------------------------- Frazão ----
FRAZAO = "https://www.frazaoleiloes.com.br"


def parse_frazao(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select("[id='card-lote']"):
        a = card.select_one("a.visualizar_lote[data-lote-id]")
        if not a:
            continue
        lot_id = a["data-lote-id"]
        href = a.get("href") or ""
        external = clean(a.get("url"))
        url = external or (urljoin(FRAZAO, href) if href and not href.startswith("javascript") else f"{FRAZAO}/lote/{lot_id}")
        title_el = card.select_one(".lot-title-cap b")
        title = clean(title_el.get("title") or title_el.get_text(" ")) if title_el else None
        if not title:
            continue
        # title ends with "..., Rio de Janeiro RJ" or "... - Bertioga/SP"
        city, uf = split_city_uf(title)
        if not uf:
            m = re.search(r"([A-Za-zÀ-ú' ]+?)\s+([A-Z]{2})\s*$", title)
            if m:
                city, uf = split_city_uf(f"{m.group(1).split(',')[-1]}/{m.group(2)}")
        addr_el = card.select_one(".lot-info-cap .text-elipsis-2")
        area_el = card.select_one(".lot-area-cap span")

        rounds = []
        cal = card.select_one(".inf-leilao-calendar")
        if cal:
            for i, div in enumerate(cal.find_all("div", recursive=False), start=1):
                txt = div.get_text(" ")
                price_el = div.select_one(".price-line")
                if not price_el:
                    continue
                n = re.search(r"(\d)\s*º", txt)
                rounds.append(
                    AuctionRound(
                        number=int(n.group(1)) if n else i,
                        date=parse_br_datetime(txt),
                        min_bid=parse_brl(price_el.get_text()),
                    )
                )
        status_el = card.select_one("span.label-md[class*='status-']")  # e.g. "ENVIO DE PROPOSTA"
        seller_img = card.select_one("img.comitente-logo-ico")
        seller = None
        if seller_img and seller_img.get("alt", "").startswith("Logo "):
            seller = clean(seller_img["alt"][len("Logo "):])
        img = card.select_one(".photo-lot > img")
        number = card.select_one("#number-lot")
        out.append(
            Listing(
                source="frazao",
                source_id=lot_id,
                url=url,
                title=title,
                category=guess_category(f"{a.get('data-tipo', '')} {title}"),
                property_type=clean(a.get("data-tipo")) or guess_property_type(title),
                status=_status_from_classes(status_el),
                seller=seller,
                address=clean(addr_el.get_text(" ")) if addr_el else clean(a.get("data-addr")),
                city=city,
                state=uf,
                area_m2=parse_area(area_el.get_text()) if area_el else None,
                rounds=rounds,
                image_url=img.get("src") if img else None,
                extra={
                    "lot": clean(number.get_text()) if number else None,
                    "external_url": external,
                },
            )
        )
    return out


class FrazaoScraper(BaseScraper):
    name = "frazao"
    base_url = FRAZAO
    expected_min_listings = 100
    page_size = 20  # the site's own page size; larger values are ignored

    def scrape(self) -> Iterator[Listing]:
        start, total = 0, None
        for page in range(self.max_pages):
            r = self.get(
                f"{FRAZAO}/Sale/SearchLotResult",
                params={
                    "loteAtivo": "true",
                    "ExibirInternosPrimeiro": "true",
                    "start": start,
                    "limit": self.page_size,
                    "page": page,
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            if total is None:
                total = self.reported_total = parse_total(r.text)
                self.log.info("site reports %s lots", total)
            batch = parse_frazao(r.text)
            if not batch:
                break
            yield from batch
            start += len(batch)
            if total is not None and start >= total:
                break

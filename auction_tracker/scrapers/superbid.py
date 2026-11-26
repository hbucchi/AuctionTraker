"""Superbid — https://www.superbid.net

How the site works (verified 2026-11-26):
* Next.js site. Category pages such as /categorias/imoveis embed their data
  as JSON in ``<script id="__NEXT_DATA__">`` -> props.pageProps.offersList
  ({"total": N, "offers": [...]}).
* ``?pageNumber=P&pageSize=S&orderBy=id:asc`` paginates (1-based
  pageNumber; 60 per page works). Without a stable ``orderBy`` pages overlap
  and ~15% of offers are never seen (measured 2026-11-26: 1077 of 1298). The offer page lives on exchange.superbid.net and its link is in
  the HTML as ``https://exchange.superbid.net/oferta/<slug>-<offerId>``.
* Superbid is a general marketplace (vehicles, machinery, agro, ...). By
  default we only scrape real estate, like the other six sites; pass other
  category slugs (see CATEGORIES) to widen it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

from ..models import AuctionRound, Listing
from ..parsing import clean, iso_from_sql, parse_brl, split_city_uf, state_to_uf
from .base import BaseScraper, ScraperError

BASE = "https://www.superbid.net"
# slug on superbid.net -> our coarse category
CATEGORIES = {
    "imoveis": "imovel",
    "carros-motos": "veiculo",
    "caminhoes-onibus": "veiculo",
}

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_APPRAISAL_RE = re.compile(r"valor\s+de\s+avalia[çc][ãa]o\s*:?\s*R\$\s*([\d.,]+)", re.I)


def extract_offers(html: str) -> tuple[int | None, list[dict[str, Any]], dict[str, str]]:
    m = _NEXT_RE.search(html)
    if not m:
        raise ScraperError("__NEXT_DATA__ not found — page layout changed?")
    data = json.loads(m.group(1))
    ol = data.get("props", {}).get("pageProps", {}).get("offersList") or {}
    links = {
        mm.group(2): mm.group(0)
        for mm in re.finditer(r"https://exchange\.superbid\.net/oferta/([a-z0-9-]*?)-(\d+)(?=[\"'?#])", html)
    }
    return ol.get("total"), ol.get("offers") or [], links


def _template_value(product: dict, prop_id: str) -> str | None:
    for g in (product.get("template") or {}).get("groups") or []:
        for p in g.get("properties") or []:
            if p.get("id") == prop_id and p.get("value"):
                return str(p["value"])
    return None


def offer_to_listing(o: dict[str, Any], links: dict[str, str], category: str) -> Listing:
    oid = str(o["id"])
    product = o.get("product") or {}
    auction = o.get("auction") or {}
    detail = o.get("offerDetail") or {}
    loc = product.get("location") or {}
    city, uf = split_city_uf(loc.get("city"))
    uf = uf or state_to_uf(loc.get("state"))
    if not city:
        # location block missing: fall back to "..., Contenda/PR | ..." in the title or address
        for text in (product.get("shortDesc"), _template_value(product, "endereco")):
            for chunk in re.split(r"[|,]", text or ""):
                c2, u2 = split_city_uf(chunk)
                if c2:
                    city, uf = city or c2, uf or u2
                    break
            if city:
                break
        city = city or clean(loc.get("city"))

    desc_text = BeautifulSoup(product.get("detailedDescription") or "", "lxml").get_text(" ")
    am = _APPRAISAL_RE.search(desc_text)
    appraisal = parse_brl(am.group(1)) if am else None

    sub = product.get("subCategory") or {}
    area = _template_value(product, "areaprivativa") or _template_value(product, "areatotal")
    status = o.get("offerStatus") or {}
    status_txt = (
        "vendido" if status.get("sold") else
        "encerrado" if status.get("closed") or status.get("closedToBids") else
        "aberto" if status.get("giveYourBid") else
        "proposta" if status.get("makeYourProposal") else None
    )
    price = detail.get("currentMinBid") or o.get("price")
    return Listing(
        source="superbid",
        source_id=oid,
        url=links.get(oid, f"https://exchange.superbid.net/oferta/{oid}"),
        # Superbid's own data has "¿" where a dash was lost to an encoding bug on their side
        title=clean((product.get("shortDesc") or "").replace(" ¿ ", " – ")) or oid,
        category=category,
        property_type=clean(sub.get("description")),
        modality=clean(auction.get("modalityDesc")),
        status=status_txt,
        seller=clean(((o.get("seller") or {}).get("company") or [{}])[0].get("fantasyName"))
        or clean((o.get("store") or {}).get("name")),
        address=clean(_template_value(product, "endereco")),
        neighborhood=clean(loc.get("neighborhood")),
        city=city,
        state=uf,
        area_m2=parse_brl(area) if area else None,
        appraisal_value=appraisal,
        current_price=float(price) if price is not None else None,
        rounds=[AuctionRound(number=1, date=iso_from_sql(o.get("endDate")), min_bid=detail.get("initialBidValue"))],
        end_date=iso_from_sql(o.get("endDate")),
        image_url=product.get("thumbnailUrl"),
        bids_count=o.get("totalBids"),
        extra={
            "auction": clean(auction.get("desc")),
            "auctioneer": clean(auction.get("auctioneer")),
            "occupancy": _template_value(product, "situacao"),
            "lat": (loc.get("locationGeo") or {}).get("lat"),
            "lon": (loc.get("locationGeo") or {}).get("lon"),
        },
    )


class SuperbidScraper(BaseScraper):
    name = "superbid"
    base_url = BASE
    expected_min_listings = 300
    page_size = 60
    max_pages = 60

    def __init__(self, max_pages: int | None = None, categories: list[str] | None = None):
        super().__init__(max_pages)
        self.categories = categories or ["imoveis"]

    def scrape(self) -> Iterator[Listing]:
        for slug in self.categories:
            cat = CATEGORIES.get(slug, "outros")
            total = None
            for page in range(1, self.max_pages + 1):
                r = self.get(
                    f"{BASE}/categorias/{slug}",
                    # A unique sort key is essential: the default (relevance) order
                    # reshuffles between requests and silently skips ~15% of offers.
                    params={"pageNumber": page, "pageSize": self.page_size, "orderBy": "id:asc"},
                )
                t, offers, links = extract_offers(r.text)
                if total is None:
                    total = t
                    self.reported_total = (self.reported_total or 0) + (t or 0)
                    self.log.info("%s: site reports %s offers", slug, total)
                if not offers:
                    break
                for o in offers:
                    yield offer_to_listing(o, links, cat)
                if total is not None and page * self.page_size >= total:
                    break

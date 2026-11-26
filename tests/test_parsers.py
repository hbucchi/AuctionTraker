"""Offline parser tests against saved, trimmed snapshots of each site.

When a site changes its layout: capture a new fixture
(``python scripts/capture_fixture.py <site>``), update the expectations
below to match the new snapshot, then fix the parser until tests pass.
"""

import json
from pathlib import Path

import pytest

from auction_tracker.models import CORE_FIELDS
from auction_tracker.scrapers import alfa, blueintra, pgfn, picelli, superbid, zuk

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def finalize(items):
    return [i.finalize() for i in items]


def by_id(items):
    return {i.source_id: i for i in items}


# ------------------------------------------------------------------ per site


def test_zuk():
    html = load("zuk.html")
    assert zuk.parse_total(html) == 1017
    items = by_id(finalize(zuk.parse_cards(html)))
    assert len(items) == 4
    a = items["38174-238463"]
    assert (a.city, a.state, a.neighborhood) == ("Sete Lagoas", "MG", "Morro do Claro")
    assert a.property_type == "Casa"
    assert a.seller == "Sicoob Credisete"
    assert a.area_m2 == 47.6
    assert [(r.number, r.min_bid) for r in a.rounds] == [(1, 200000.0), (2, 150000.0)]
    assert a.rounds[0].date == "2026-11-27T10:00:00-03:00"
    assert a.current_price == 150000.0
    # 1st round already passed (price struck through) and a "-42%" badge next to the 2nd
    b = items["38253-239171"]
    assert [r.min_bid for r in b.rounds] == [216061.95, 124685.38]


def test_biasi():
    html = load("biasi.html")
    assert blueintra.parse_total(html) == 393
    items = by_id(finalize(blueintra.parse_biasi(html)))
    a = items["63410"]
    assert a.url == "https://www.biasileiloes.com.br/lotes/63410/loja-no-centro-rio-de-janeiro-rj"
    assert (a.city, a.state) == ("Rio de Janeiro", "RJ")
    assert a.current_price == 5356637.0
    assert a.seller == "Itaú Unibanco"
    assert a.status == "Liberado para Lance"
    assert a.bids_count == 0


def test_frazao():
    html = load("frazao.html")
    items = by_id(finalize(blueintra.parse_frazao(html)))
    a = items["41337"]
    assert a.title.startswith("06 Salas comerciais")
    assert (a.city, a.state) == ("Rio de Janeiro", "RJ")
    assert a.area_m2 == 551.0
    assert a.current_price == 1290000.0
    assert a.status == "ENVIO DE PROPOSTA"
    assert a.end_date == "2026-09-30T10:00:00-03:00"


def test_alfa():
    items = by_id(finalize(alfa.parse_cards(load("alfa.html"))))
    a = items["10898"]
    assert (a.city, a.state) == ("Itatiba", "SP")
    assert a.property_type == "Terreno"
    assert a.modality == "judicial"
    assert a.area_m2 == 1005.0
    assert a.discount_pct == 40.0
    assert [r.min_bid for r in a.rounds] == [187538.77, 112523.26]
    assert a.current_price == 112523.26


def test_alfa_en_dash_title():
    html = load("alfa.html").replace("Itatiba (SP) - Terreno", "Itatiba (SP) – Terreno")
    a = by_id(alfa.parse_cards(html))["10898"]
    assert (a.city, a.state, a.property_type) == ("Itatiba", "SP", "Terreno")


def test_superbid():
    total, offers, links = superbid.extract_offers(load("superbid.html"))
    assert total == 1301
    items = by_id(finalize(superbid.offer_to_listing(o, links, "imovel") for o in offers))
    a = items["5085075"]
    assert a.url == "https://exchange.superbid.net/oferta/casa-35m-riachao-nova-iguacu-rj-5085075"
    assert (a.city, a.state) == ("Nova Iguaçu", "RJ")
    assert a.appraisal_value == 68000.0
    assert a.current_price == 34000.0
    assert a.discount_pct == 50.0
    assert a.end_date == "2026-11-30T11:08:00-03:00"


def test_pgfn():
    data = json.loads(load("pgfn.json"))
    items = by_id(finalize(pgfn.item_to_listing(x) for x in data["content"]))
    a = items["40984"]
    assert a.url == "https://comprei.pgfn.gov.br/anuncio/detalhe/40984"
    assert (a.city, a.state) == ("Lencois Paulista", "SP")
    assert (a.appraisal_value, a.current_price, a.discount_pct) == (525000, 393750, 25)
    assert a.end_date == "2027-01-31T00:00:00-03:00"
    assert a.modality == "venda direta"
    assert not items["63101"].title.endswith("_")


def test_picelli():
    auctions = json.loads(load("picelli.json"))
    items = finalize(picelli.auctions_to_listings(auctions))
    assert all(i.status in ("aberto", "futuro") for i in items)  # closed auctions dropped
    a = by_id(items)["37365aed-6ffc-4373-9d0f-5ea477a03f91"]
    assert a.url == "https://www.picellileiloes.com.br/leilao/terreno-com-160m-jardim-das-flores"
    assert (a.city, a.state) == ("Hortolândia", "SP")
    assert a.area_m2 == 160.0
    assert [r.min_bid for r in a.rounds] == [255058.94, 138662.18]


# ------------------------------------------------------- cross-site checks

ALL = {
    "zuk": lambda: zuk.parse_cards(load("zuk.html")),
    "biasi": lambda: blueintra.parse_biasi(load("biasi.html")),
    "frazao": lambda: blueintra.parse_frazao(load("frazao.html")),
    "alfa": lambda: alfa.parse_cards(load("alfa.html")),
    "superbid": lambda: [
        superbid.offer_to_listing(o, links, "imovel")
        for _, offers, links in [superbid.extract_offers(load("superbid.html"))]
        for o in offers
    ],
    "pgfn": lambda: [pgfn.item_to_listing(x) for x in json.loads(load("pgfn.json"))["content"]],
    "picelli": lambda: picelli.auctions_to_listings(json.loads(load("picelli.json"))),
}


@pytest.mark.parametrize("site", sorted(ALL))
def test_every_listing_has_identity_and_link(site):
    items = finalize(ALL[site]())
    assert items, f"{site}: parser returned nothing"
    for i in items:
        assert i.source == site
        assert i.source_id and i.url.startswith("https://") and i.title
        assert i.to_dict()["id"] == f"{site}:{i.source_id}"


@pytest.mark.parametrize("site", sorted(ALL))
def test_core_fields_mostly_filled(site):
    items = finalize(ALL[site]())
    for f in CORE_FIELDS:
        rate = sum(1 for i in items if getattr(i, f) not in (None, "")) / len(items)
        assert rate >= 0.6, f"{site}: '{f}' filled in only {rate:.0%}"

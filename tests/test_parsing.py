import pytest

from auction_tracker.models import AuctionRound, Listing
from auction_tracker.parsing import (
    guess_category,
    parse_area,
    parse_br_datetime,
    parse_brl,
    split_city_uf,
    state_to_uf,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("R$ 1.234.567,89", 1234567.89),
        ("R$\n200.000,00 ", 200000.0),
        ("187538,77", 187538.77),
        ("1,290,000.00", 1290000.0),
        ("R$ 5.356.637,00", 5356637.0),
        ("1.005", 1005.0),
        ("sem valor", None),
        (None, None),
    ],
)
def test_parse_brl(text, expected):
    assert parse_brl(text) == expected


def test_parse_area():
    assert parse_area("47,60m² construída") == 47.6
    assert parse_area("Terreno com 1.005m²") == 1005.0
    assert parse_area("Casa 35m2") == 35.0
    assert parse_area("sem área") is None


def test_parse_br_datetime():
    assert parse_br_datetime("27/11/2026 às 10:00") == "2026-11-27T10:00:00-03:00"
    assert parse_br_datetime("Leilão: 30/09/2026 às   10h00") == "2026-09-30T10:00:00-03:00"
    assert parse_br_datetime("09/11/2026") == "2026-11-09T00:00:00-03:00"
    assert parse_br_datetime("31/02/2026") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Sete Lagoas / MG", ("Sete Lagoas", "MG")),
        ("Itatiba (SP)", ("Itatiba", "SP")),
        ("Nova Iguaçu - RJ", ("Nova Iguaçu", "RJ")),
        ("Loja no Centro - Rio de Janeiro/RJ", ("Rio de Janeiro", "RJ")),
        ("R. Padre Anchieta, 339, Vila - Lencois Paulista/SP", ("Lencois Paulista", "SP")),
        ("APARTAMENTO em Pirajá, Salvador, BA", ("Salvador", "BA")),
        ("Sem estado", (None, None)),
    ],
)
def test_split_city_uf(text, expected):
    assert split_city_uf(text) == expected


def test_state_to_uf():
    assert state_to_uf("São Paulo") == "SP"
    assert state_to_uf("rio grande do sul") == "RS"
    assert state_to_uf("MG") == "MG"


def test_guess_category():
    assert guess_category("Apartamento no Centro") == "imovel"
    assert guess_category("HONDA/LEAD 110 moto") == "veiculo"


def test_finalize_derives_price_end_date_and_discount():
    x = Listing(
        source="t", source_id="1", url="https://x", title="Casa 80m²", appraisal_value=200000,
        rounds=[AuctionRound(1, "2026-11-27T10:00:00-03:00", 200000), AuctionRound(2, "2026-11-30T10:00:00-03:00", 120000)],
    ).finalize()
    assert x.current_price == 120000
    assert x.end_date == "2026-11-30T10:00:00-03:00"
    assert x.discount_pct == 40.0
    assert x.area_m2 == 80.0

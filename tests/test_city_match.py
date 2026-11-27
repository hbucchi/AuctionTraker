"""City names as sites write them -> IBGE municipality."""

from auction_tracker.enrich import enrich, find_municipio
from auction_tracker.models import Listing


def name(city, uf, **kw):
    m = find_municipio(city, uf, **kw)
    return m and m["name"]


def test_exact_and_accents():
    assert name("Sao Paulo", "SP") == "São Paulo"


def test_headline_in_city_field():
    assert name("Apartamento no Centro de São Carlos", "SP") == "São Carlos"
    assert name("Casa no Jardim Alah em Açailândia", "MA") == "Açailândia"


def test_dropped_first_word_and_spelling():
    assert name("Antônio da Platina", "PR") == "Santo Antônio da Platina"
    assert name("Santana Do Livramento", "RS") == "Sant'Ana do Livramento"


def test_state_as_city_is_not_guessed():
    assert find_municipio("SP", "SP") is None


def test_coordinates_fallback():
    assert name(None, None, lat=-23.70, lon=-46.70) == "São Paulo"


def test_enrich_renames_city_and_fills_stats():
    x = enrich(Listing(source="biasi", source_id="1", url="u", title="Apartamento", city="Apartamento no Centro de São Carlos", state="SP"))
    assert x.city == "São Carlos" and x.city_population > 200_000

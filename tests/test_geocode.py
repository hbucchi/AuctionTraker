from auction_tracker import geocode
from auction_tracker.models import Listing
from tests.test_firestore_sink import FakeClient


def mk(i, address="Rua Paraná, 374"):
    return Listing(source="t", source_id=str(i), url="https://x", title="Casa", address=address,
                   city="Londrina", state="PR", lat=-23.5, lon=-51.1, geo="cidade")


def test_geocodes_once_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(geocode, "lookup", lambda q, k: calls.append(q) or {"lat": -23.31, "lon": -51.16, "type": "ROOFTOP", "status": "OK"})
    db = FakeClient()
    xs = [mk(1), mk(2)]  # same address: one lookup
    s = geocode.apply(xs, db, api_key="k")
    assert len(calls) == 1 and s["new"] == 1 and s["cached"] == 1
    assert (xs[0].lat, xs[0].geo) == (-23.31, "exato")
    geocode.apply([mk(3)], db, api_key="k")
    assert len(calls) == 1  # served from the Firestore cache


def test_city_level_results_dont_move_pins(monkeypatch):
    monkeypatch.setattr(geocode, "lookup", lambda q, k: {"lat": 1, "lon": 2, "type": "APPROXIMATE", "status": "OK"})
    x = mk(1)
    geocode.apply([x], FakeClient(), api_key="k")
    assert x.geo == "cidade"


def test_no_key_does_nothing():
    x = mk(1)
    assert geocode.apply([x], FakeClient(), api_key=None) == {"cached": 0, "new": 0, "precise": 0}
    assert x.geo == "cidade"


def test_bare_city_is_not_geocoded():
    assert geocode.address_query(mk(1, address=None)) is None

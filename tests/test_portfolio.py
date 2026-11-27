from auction_tracker import portfolio
from tests.test_firestore_sink import FakeClient

STRAT_SP = {"id": "s1", "enabled": True, "sets": {"uf": {"values": ["SP"]}, "kind": {"values": ["apartamento"]}},
            "ranges": {"price": {"min": 100000, "max": 600000}, "roe": {"min": 15}}, "cities": ["Santos/SP"]}
STRAT_RJ = {"id": "s2", "enabled": True, "sets": {"uf": {"values": ["RJ"]}}, "ranges": {"price": {"min": None, "max": 900000}}}


def test_interest_profile_unions_and_widest_range():
    p = portfolio.interest_profile([STRAT_SP, STRAT_RJ, {**STRAT_SP, "enabled": False, "sets": {"uf": {"values": ["MG"]}}}])
    assert p["ufs"] == ["RJ", "SP"] and p["kinds"] == ["apartamento"] and p["cities"] == ["Santos/SP"]
    assert p["price_min"] is None  # STRAT_RJ has no minimum, so the union has none
    assert p["price_max"] == 900000 and p["strategies"] == 2
    f = portfolio.interest_fields([STRAT_SP])
    assert f["interest_ufs"] == ["SP"] and f["interest_kinds"] == ["apartamento"]


def test_portfolio_counts_only_other_users_with_matching_strategies():
    db = FakeClient()
    users = db.collection("users")
    users.document("owner").set({"email": "o@example.com", "strategies": [{"id": "x", "sets": {"uf": {"values": ["SP"]}}}]})
    users.document("b1").set({"strategies": [{"id": "a", "sets": {"uf": {"values": ["SP"]}}, "ranges": {"price": {"max": 500000}}}]})
    users.document("b2").set({"strategies": [{"id": "b", "sets": {"uf": {"values": ["RJ"]}}}]})
    users.document("b3").set({"strategies": [{"id": "c", "enabled": False, "sets": {"uf": {"values": ["SP"]}}}]})
    port = users.document("owner").collection("portfolio")
    port.document("p1").set({"title": "Apartamento 3 quartos", "kind": "apartamento", "city": "Santos", "uf": "SP",
                             "area": 90, "bedrooms": 3, "purchase_price": 300000, "purchase_costs": 30000,
                             "asking_price": 450000, "for_sale": True, "allow_matching": True})
    port.document("p2").set({"title": "Casa", "kind": "casa", "city": "Santos", "uf": "SP", "area": 120,
                             "purchase_price": 200000, "for_sale": True, "allow_matching": False})
    stats = portfolio.run(db, [])
    p1 = db.store["users/owner/portfolio"]["p1"]
    p2 = db.store["users/owner/portfolio"]["p2"]
    assert p1["interested_count"] == 1          # b1 only: b2 wants RJ, b3's strategy is off, owner excluded
    assert p2["interested_count"] is None       # owner didn't allow matching
    assert p1["valuation"] and p1["valuation"]["mid"] > 0 and "gain_pct" in p1
    assert stats == {"users": 1, "properties": 2, "valued": 2, "offered": 1}
    assert db.store["users"]["b1"]["interest_ufs"] == ["SP"]  # interest profiles refreshed

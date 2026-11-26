from auction_tracker import alerts
from tests.test_firestore_sink import FakeClient

NOW = 1796000000
STRAT = {"id": "s1", "name": "Até 50%", "enabled": True, "email": True, "ranges": {"ptm": {"min": None, "max": 50}}}


def item(i, ptm=40):
    return {"id": f"zuk:{i}", "src": "zuk", "url": f"https://x/{i}", "title": f"Casa {i}", "city": "Londrina",
            "uf": "PR", "price": 100000, "ptm": ptm}


def test_first_run_is_baseline_then_only_new_items():
    st, news = alerts.evaluate([STRAT], [item(1), item(2), item(3, ptm=90)], {}, NOW)
    assert news == {} and st["strategies"]["s1"]["baseline"] is True
    assert st["strategies"]["s1"]["seen"] == ["zuk:1", "zuk:2"]

    st2, news2 = alerts.evaluate([STRAT], [item(1), item(2), item(4)], st, NOW)
    assert [i["id"] for i in news2["s1"]] == ["zuk:4"]
    assert st2["strategies"]["s1"]["new"] == ["zuk:4"]


def test_seen_list_forgets_listings_that_disappeared():
    st = {"strategies": {"s1": {"seen": ["zuk:1", "zuk:old"]}}}
    st2, _ = alerts.evaluate([STRAT], [item(1)], st, NOW)
    assert st2["strategies"]["s1"]["seen"] == ["zuk:1"]


def test_disabled_strategies_are_skipped():
    st, news = alerts.evaluate([{**STRAT, "enabled": False}], [item(1)], {}, NOW)
    assert st["strategies"] == {} and news == {}


def test_run_emails_only_new_matches_of_email_strategies():
    db = FakeClient()
    db.collection("users").document("u1").set({"email": "ana@example.com", "name": "Ana Souza",
                                               "strategies": [STRAT, {**STRAT, "id": "s2", "email": False}]})
    sent = []
    alerts.run(db, [item(1)], NOW, send=lambda to, subj, body: sent.append((to, subj, body)))
    assert sent == []  # baseline run
    stats = alerts.run(db, [item(1), item(2)], NOW, send=lambda to, subj, body: sent.append((to, subj, body)))
    assert stats["emails"] == 1 and stats["new"] == 2  # new in both strategies, email only for s1
    to, subj, body = sent[0]
    assert to == "ana@example.com" and "1 novo imóvel" in subj and "Olá Ana" in body and "https://x/2" in body
    assert db.store["alert_state"]["u1"]["strategies"]["s2"]["new"] == ["zuk:2"]

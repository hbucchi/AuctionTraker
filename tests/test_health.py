from auction_tracker.health import SiteReport, assess
from auction_tracker.models import Listing


def mk(n, city="São Paulo"):
    return [
        Listing(source="t", source_id=str(i), url="https://x", title="t", current_price=1.0, city=city, state="SP")
        for i in range(n)
    ]


def test_ok():
    r = assess(SiteReport("t"), mk(100), expected_min=50, previous_count=110)
    assert r.status == "OK" and not r.reasons


def test_fail_when_empty_or_exception():
    assert assess(SiteReport("t"), [], 10, None).status == "FAIL"
    r = SiteReport("t", error="ValueError: boom")
    assert assess(r, mk(100), 10, None).status == "FAIL"


def test_warn_on_drop_and_low_fill_rate():
    r = assess(SiteReport("t"), mk(40), expected_min=10, previous_count=100)
    assert r.status == "WARN" and "fell from 100 to 40" in r.reasons[0]
    r = assess(SiteReport("t"), mk(100, city=None), expected_min=10, previous_count=None)
    assert r.status == "WARN" and any("'city'" in x for x in r.reasons)


def test_warn_when_coverage_below_advertised_total():
    r = assess(SiteReport("t"), mk(1077), expected_min=10, previous_count=None, reported_total=1298)
    assert r.status == "WARN" and "1077 of the 1298" in r.reasons[0]
    r = assess(SiteReport("t"), mk(979), expected_min=10, previous_count=None, reported_total=1017)
    assert r.status == "OK"


def test_limited_run_skips_count_checks():
    r = assess(SiteReport("t"), mk(5), expected_min=100, previous_count=1000, limited=True)
    assert r.status == "OK"

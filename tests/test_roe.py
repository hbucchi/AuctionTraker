"""ROE: pinned cases (shared with web/roe.js) plus hand-checked arithmetic."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from auction_tracker import roe
from auction_tracker.roe import assumptions, chances, flip, roe_range, value_needed

DATA = json.loads((Path(__file__).parent / "roe_cases.json").read_text(encoding="utf-8"))
CASES = DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases(case):
    assert roe_range(case["item"], case["custom"]) == case["expect"]


def test_hand_checked_flip():
    # bid 200k, value 400k, vacant, defaults (renovation midpoint 5%):
    # equity = 200k + 19k fees (9.5%) + 1.5k docs + 20k renovation + 7.2k condo/IPTU (0.15% x 12) = 247.7k
    # back   = 400k - 24k broker = 376k ; gain 128.3k ; tax 19,245 ; profit 109,055
    r = flip(200_000, 400_000, None, False, assumptions())
    assert round(r["equity"]) == 247_700
    assert round(r["profit"]) == 109_055
    assert r["costs"]["legal"] == 0 and r["costs"]["renovation"] == 20_000


def test_lawyer_only_when_needed():
    a = assumptions()
    assert flip(200_000, 400_000, None, False, a)["costs"]["legal"] == 0
    assert flip(200_000, 400_000, None, True, a)["costs"]["legal"] == 6000            # occupied
    assert flip(200_000, 400_000, None, False, a, judicial=True)["costs"]["legal"] == 6000
    assert flip(200_000, 400_000, None, False, assumptions({"legal_on_judicial": 0}), judicial=True)["costs"]["legal"] == 0


def test_javascript_twin_agrees():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "roe_cases.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("case", DATA["chance_cases"], ids=[c["name"] for c in DATA["chance_cases"]])
def test_chance_cases(case):
    assert chances(case["item"], DATA["quantiles"], case["custom"]) == case["expect"]


def test_breakeven_gives_zero_and_target_gives_target():
    a = assumptions()
    for debts, occ in [(None, False), (True, True)]:
        for judicial in (False, True):
            be = value_needed(200_000, 0, debts, occ, a, judicial)
            t = value_needed(200_000, 0.2, debts, occ, a, judicial)
            assert abs(flip(200_000, be, debts, occ, a, judicial)["roe"]) < 1e-9
            assert abs(flip(200_000, t, debts, occ, a, judicial)["roe"] - 0.2) < 1e-9


@pytest.mark.parametrize("case", DATA["ceiling_cases"], ids=lambda c: c["name"])
def test_ceiling_cases(case):
    q = DATA["quantiles"]
    assert roe.ceilings(case["item"], q, None, case["target"], case["chance"]) == case["expect"]


@pytest.mark.parametrize("target", [0, 0.1, 0.2, 0.35])
@pytest.mark.parametrize("debts,occ,judicial", [(None, None, False), (True, True, True), (False, False, False)])
def test_max_bid_gives_exactly_the_target(target, debts, occ, judicial):
    a = roe.assumptions()
    bid = roe.max_bid(450_000, target, debts, occ, a, judicial)
    assert roe.flip(bid, 450_000, debts, occ, a, judicial)["roe"] == pytest.approx(target, abs=1e-9)


def test_value_at_chance_reads_the_quantiles():
    q = [0.5 + 0.05 * i for i in range(19)]  # 5th pct = 0.5 … 95th = 1.4
    assert roe.value_at_chance(100, q, 0.75) == pytest.approx(100 * q[4])  # 25th percentile
    assert roe.value_at_chance(100, q, 0.5) == pytest.approx(100 * q[9])

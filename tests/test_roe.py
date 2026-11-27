"""ROE: pinned cases (shared with web/roe.js) plus hand-checked arithmetic."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from auction_tracker.roe import assumptions, flip, roe_range

CASES = json.loads((Path(__file__).parent / "roe_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases(case):
    assert roe_range(case["item"], case["custom"]) == case["expect"]


def test_hand_checked_flip():
    # bid 200k, value 400k, vacant, defaults:
    # equity = 200k*1.095 + 400k*5% + 400k*0.15%*12 = 219k + 20k + 7.2k = 246.2k
    # back   = 400k*0.94 = 376k ; gain 129.8k ; tax 19.47k ; profit 110.33k
    r = flip(200_000, 400_000, None, False, assumptions())
    assert round(r["equity"]) == 246_200
    assert round(r["profit"]) == 110_330
    assert round(r["roe"], 4) == round(110_330 / 246_200, 4)


def test_javascript_twin_agrees():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "roe_cases.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

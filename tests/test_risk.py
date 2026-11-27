"""Risk factors: shared cases with the JavaScript twin (web/risk.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from auction_tracker.risk import risk

CASES = json.loads((Path(__file__).parent / "risk_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases(case):
    assert risk(case["item"], case["checklist"]) == case["expect"]


def test_unknown_is_never_zero_risk():
    assert risk({"title": "Casa", "price": 100_000})["points"] >= 3


def test_javascript_twin_agrees():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "risk_cases.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

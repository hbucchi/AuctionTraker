"""Pins the strategy rules. web/index.html implements the same rules in
JavaScript; tests/strategy_cases.json is run against both."""

import json
from pathlib import Path

import pytest

from auction_tracker.strategy import matches, preset

CASES = json.loads((Path(__file__).parent / "strategy_cases.json").read_text(encoding="utf-8"))
NOW = CASES["now"]


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_shared_cases(case):
    assert matches(case["strategy"], case["item"], NOW) is case["expect"]


def test_preset_resolves_national_gdp():
    p = preset()
    assert isinstance(p["ranges"]["gdppc"]["min"], int) and p["ranges"]["gdppc"]["min"] > 10_000
    assert p["ranges"]["ptm"]["max"] == 50 and p["toggles"]["official_mv"] is True


def test_javascript_twin_agrees():
    """web/strategy.js must give the same answers (skipped without Node)."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "strategy_cases.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

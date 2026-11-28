"""Runs the similar-lot grouping tests (web/dedupe.js) with node."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_similar_lot_grouping_js():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "dedupe.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

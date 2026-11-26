"""Strategy matching: does a listing satisfy a user's saved strategy?

A strategy is a JSON document (stored in Firestore under users/{uid}) whose
shape is described by web/strategy-fields.json. The web app implements the
same rules in JavaScript; tests/test_strategy.py pins the behaviour so the
two stay in sync.

Rules
-----
* range  {min, max, unknown}: active when min or max is set. A listing whose
  value is missing passes only if ``unknown`` is true. This matters because
  data is incomplete (bedrooms, area, market value...): the user decides
  whether "unknown" means "maybe" or "no".
* set    {values, unknown}: active when values is non-empty.
* city criteria (population, GDP per capita, HDI, agribusiness, capital)
  combine with ``city_mode``: "all" = every active one must pass, "any" = at
  least one. Everything else always combines with AND.
* cities / neighborhoods: optional allow-lists ("Londrina/PR", "Centro").
* debts: "any" | "not_buyer" (drop when buyer pays) | "seller_only".
* hide_ended: drop listings whose deadline has passed (unless still taking
  proposals).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).resolve().parents[1] / "web" / "strategy-fields.json"
DAY = 86400.0


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def next_deadline(item: dict, now: float) -> float | None:
    """Next round still to come, else the final end date."""
    future = [t for t in (_ts(r.get("d")) for r in item.get("rounds") or []) if t and t >= now]
    return min(future) if future else _ts(item.get("end"))


def is_ended(item: dict, now: float) -> bool:
    end = _ts(item.get("end"))
    takes_proposals = bool(re.search(r"proposta", item.get("status") or "", re.I))
    return end is not None and end < now and not takes_proposals


def attr_value(item: dict, attr: str, now: float) -> Any:
    if attr == "days":
        t = next_deadline(item, now)
        return None if t is None else (t - now) / DAY
    return item.get(attr)


def range_ok(v: Any, r: dict) -> bool:
    if v is None:
        return bool(r.get("unknown"))
    if r.get("min") is not None and v < r["min"]:
        return False
    if r.get("max") is not None and v > r["max"]:
        return False
    return True


def range_active(r: dict | None) -> bool:
    return bool(r) and (r.get("min") is not None or r.get("max") is not None)


def matches(strategy: dict, item: dict, now: float | None = None) -> bool:
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    sp = spec()

    if strategy.get("hide_ended", True) and is_ended(item, now):
        return False

    for s in sp["sets"]:
        cfg = (strategy.get("sets") or {}).get(s["key"])
        if not cfg or not cfg.get("values"):
            continue
        v = item.get(s["attr"])
        if v is None:
            if not cfg.get("unknown"):
                return False
        elif v not in cfg["values"]:
            return False

    city_results = []
    for r in sp["ranges"]:
        cfg = (strategy.get("ranges") or {}).get(r["key"])
        if not range_active(cfg):
            continue
        ok = range_ok(attr_value(item, r["attr"], now), cfg)
        if r.get("city"):
            city_results.append(ok)
        elif not ok:
            return False
    for t in sp["toggles"]:
        if (strategy.get("toggles") or {}).get(t["key"]):
            ok = bool(item.get(t["attr"]))
            if t.get("city"):
                city_results.append(ok)
            elif not ok:
                return False
    if city_results:
        if strategy.get("city_mode", "all") == "any":
            if not any(city_results):
                return False
        elif not all(city_results):
            return False

    cities = strategy.get("cities") or []
    if cities:
        here = _norm(f"{item.get('city') or ''}/{item.get('uf') or ''}")
        if here not in {_norm(c) for c in cities}:
            return False

    hoods = [h for h in (strategy.get("neighborhoods") or []) if h.strip()]
    if hoods:
        text = _norm(f"{item.get('hood') or ''} {item.get('title') or ''}")
        if not any(_norm(h) in text for h in hoods):
            return False

    debts = strategy.get("debts", "any")
    if debts == "not_buyer" and item.get("debts") is True:
        return False
    if debts == "seller_only" and item.get("debts") is not False:
        return False

    return True


def preset(name: str = "abaixo50") -> dict:
    """A ready-made strategy from the spec, with placeholders resolved."""
    raw = json.dumps(spec()["presets"][name])
    raw = raw.replace('"NATIONAL_GDP_PC"', str(spec()["reference"]["national_gdp_per_capita"]))
    return json.loads(raw)

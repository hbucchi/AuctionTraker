"""Estimated return on equity of an auction "flip": buy at auction, fix, resell.

Every cost an investor faces, itemized (all in BRL):

    bid                    the auction price
    fees                   auctioneer commission + ITBI + registration (% of bid)
    docs                   certidões, despachante, cartório extras (fixed)
    renovation             a RANGE, from renovation_min_pct to renovation_max_pct of value
    furniture              refurnishing / appliances (% of value; 0 for a plain resale)
    debts                  condo/IPTU arrears, only if the edital puts them on the buyer
    eviction               desocupação costs, only if occupied (also adds months)
    legal                  lawyer, only when needed: occupied property (imissão na posse)
                           or a judicial auction (if legal_on_judicial is on)
    carrying               condo + IPTU while holding, per month

    equity = sum of the above          (all cash, no financing)
    back   = value × (1 − broker%) − capital-gains tax on the profit
    ROE    = (back − equity) / equity

Range: the pessimistic end combines the low value of the valuation's 50% band
with the MAXIMUM renovation; the optimistic end, the high value with the
minimum renovation; the central figure, the central value with the midpoint.
These are estimates built on an estimated value, not a forecast of any deal.

web/roe.js is the browser twin; tests/roe_cases.json checks they agree.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULTS: dict[str, float] = {
    "commission_pct": 5.0,          # leiloeiro, on the bid (usual: 5%)
    "itbi_pct": 3.0,                # municipal transfer tax (2-3% in most cities)
    "registry_pct": 1.5,            # escritura + registro de imóveis
    "docs_fixed": 1500.0,           # certidões, despachante (R$)
    "renovation_min_pct": 0.0,      # of value: best case, nothing to fix
    "renovation_max_pct": 10.0,     # of value: worst case, full refresh
    "furniture_pct": 0.0,           # of value: furnishing for rent / staging
    "debts_pct": 5.0,               # of value, only when debts stay with the buyer
    "eviction_pct": 3.0,            # of value, only when occupied
    "eviction_months": 6.0,         # extra months when occupied
    "legal_fixed": 6000.0,          # lawyer (R$), only when occupied or judicial
    "legal_on_judicial": 1.0,       # 1 = also budget a lawyer for judicial auctions
    "assume_occupied": 0.0,         # 1 = treat unknown occupancy as occupied (conservative)
    "holding_months": 12.0,         # from auction to sale
    "carrying_pct_month": 0.15,     # condo + IPTU while holding, % of value per month
    "broker_pct": 6.0,              # corretor, on the sale
    "tax_pct": 15.0,                # IR on capital gains (pessoa física)
}


def _half_up(x: float) -> int:
    """Round halves up, like JavaScript's Math.round (Python's round() rounds
    halves to even, which would make the two twins disagree by 1 now and then)."""
    return math.floor(x + 0.5)


def assumptions(custom: dict[str, Any] | None = None) -> dict[str, float]:
    a = dict(DEFAULTS)
    custom = dict(custom or {})
    # strategies saved before the renovation range existed had one number
    if custom.get("renovation_pct") not in (None, "") and "renovation_max_pct" not in custom:
        custom.setdefault("renovation_min_pct", custom["renovation_pct"])
        custom["renovation_max_pct"] = custom["renovation_pct"]
    for k, v in custom.items():
        if k in a and v is not None and v != "":
            a[k] = float(v)
    if a["renovation_max_pct"] < a["renovation_min_pct"]:
        a["renovation_max_pct"] = a["renovation_min_pct"]
    return a


def _context(debts: bool | None, occupied: bool | None, judicial: bool, a: dict[str, float]) -> tuple[bool, bool, float]:
    occ = occupied is True or (occupied is None and a["assume_occupied"] >= 1)
    lawyer = occ or (judicial and a["legal_on_judicial"] >= 1)
    months = a["holding_months"] + (a["eviction_months"] if occ else 0)
    return occ, lawyer, months


def costs(price: float, value: float, debts: bool | None, occupied: bool | None, judicial: bool,
          a: dict[str, float], renovation_pct: float) -> dict[str, float]:
    """Every cost of the deal, in BRL, keyed by item."""
    occ, lawyer, months = _context(debts, occupied, judicial, a)
    return {
        "bid": price,
        "fees": price * (a["commission_pct"] + a["itbi_pct"] + a["registry_pct"]) / 100,
        "docs": a["docs_fixed"],
        "renovation": value * renovation_pct / 100,
        "furniture": value * a["furniture_pct"] / 100,
        "debts": value * a["debts_pct"] / 100 if debts is True else 0.0,
        "eviction": value * a["eviction_pct"] / 100 if occ else 0.0,
        "legal": a["legal_fixed"] if lawyer else 0.0,
        "carrying": value * a["carrying_pct_month"] / 100 * months,
    }


def flip(price: float, value: float, debts: bool | None, occupied: bool | None, a: dict[str, float],
         judicial: bool = False, renovation_pct: float | None = None) -> dict[str, Any]:
    if renovation_pct is None:
        renovation_pct = (a["renovation_min_pct"] + a["renovation_max_pct"]) / 2
    c = costs(price, value, debts, occupied, judicial, a, renovation_pct)
    _, _, months = _context(debts, occupied, judicial, a)
    equity = sum(c.values())
    broker = value * a["broker_pct"] / 100
    gain = value - broker - equity
    tax = max(gain, 0) * a["tax_pct"] / 100
    profit = gain - tax
    roe = profit / equity
    annual = (1 + roe) ** (12 / months) - 1 if roe > -1 else -1.0
    return {"roe": roe, "annual": annual, "equity": equity, "profit": profit, "months": months,
            "costs": c, "broker": broker, "tax": tax}


def roe_range(item: dict, custom: dict[str, Any] | None = None) -> dict[str, float] | None:
    """Estimated ROE (in %): pessimistic / central / optimistic, for a
    compact listing (summary.py). None without a valuation."""
    val, price = item.get("val"), item.get("price")
    if not val or not price or price < 1_000 or val.get("flag"):
        return None
    a = assumptions(custom)
    j = item.get("modn") == "judicial"
    d, o = item.get("debts"), item.get("occ")
    lo = flip(price, val["lo50"], d, o, a, j, a["renovation_max_pct"])
    mid = flip(price, val["mid"], d, o, a, j)
    hi = flip(price, val["hi50"], d, o, a, j, a["renovation_min_pct"])
    return {
        "lo": round(100 * lo["roe"], 1), "mid": round(100 * mid["roe"], 1), "hi": round(100 * hi["roe"], 1),
        "annual": round(100 * mid["annual"], 1), "months": mid["months"], "equity": _half_up(mid["equity"]),
    }


def value_needed(price: float, target_roe: float, debts: bool | None, occupied: bool | None, a: dict[str, float],
                 judicial: bool = False, renovation_pct: float | None = None) -> float:
    """Resale value that gives exactly ``target_roe`` (0 = breakeven).

    equity  = price·k + F + value·c     (k: purchase fees, F: fixed costs, c: value-linked costs)
    profit  = (value·(1−b) − equity)·(1−tax)   for a gain
    profit ≥ t·equity  ⇔  value ≥ (price·k + F)·(1+s) / (1 − b − c·(1+s)),  s = t / (1−tax)
    """
    if renovation_pct is None:
        renovation_pct = (a["renovation_min_pct"] + a["renovation_max_pct"]) / 2
    occ, lawyer, months = _context(debts, occupied, judicial, a)
    k = 1 + (a["commission_pct"] + a["itbi_pct"] + a["registry_pct"]) / 100
    fixed = a["docs_fixed"] + (a["legal_fixed"] if lawyer else 0)
    c = (renovation_pct + a["furniture_pct"] + (a["debts_pct"] if debts is True else 0)
         + (a["eviction_pct"] if occ else 0) + a["carrying_pct_month"] * months) / 100
    s = target_roe / (1 - a["tax_pct"] / 100) if target_roe > 0 else target_roe
    denom = 1 - a["broker_pct"] / 100 - c * (1 + s)
    return float("inf") if denom <= 0 else (price * k + fixed) * (1 + s) / denom


def chance_value_at_least(needed: float, mid: float, quantiles: list[float]) -> float:
    """P(true value ≥ needed), from the valuation's measured error
    distribution: quantiles[i] is the (5·(i+1))th percentile of truth/estimate.
    Interpolates linearly; clamps to 2.5%/97.5% outside the measured range."""
    r = needed / mid
    qs = [(5 * (i + 1)) / 100 for i in range(len(quantiles))]
    if r <= quantiles[0]:
        return 0.975
    if r >= quantiles[-1]:
        return 0.025
    for (p0, x0), (p1, x1) in zip(zip(qs, quantiles), zip(qs[1:], quantiles[1:])):
        if x0 <= r <= x1:
            cdf = p0 + (p1 - p0) * ((r - x0) / (x1 - x0) if x1 > x0 else 0)
            return _half_up(1000 * (1 - cdf)) / 1000
    return 0.5


def chances(item: dict, quantiles: dict[str, list[float]] | None, custom: dict[str, Any] | None = None,
            target_roe_pct: float = 20) -> dict[str, float] | None:
    """Estimated chance (%) of any profit and of reaching ``target_roe_pct``,
    at the midpoint renovation budget."""
    val, price = item.get("val"), item.get("price")
    if not val or not price or price < 1_000 or val.get("flag") or not quantiles:
        return None
    q = quantiles.get("many" if (val.get("n") or 0) >= 3 else "few") or quantiles.get("many")
    a = assumptions(custom)
    j = item.get("modn") == "judicial"
    be = value_needed(price, 0, item.get("debts"), item.get("occ"), a, j)
    tgt = value_needed(price, target_roe_pct / 100, item.get("debts"), item.get("occ"), a, j)
    return {
        "profit": _half_up(100 * chance_value_at_least(be, val["mid"], q)),
        "target": _half_up(100 * chance_value_at_least(tgt, val["mid"], q)),
        "breakeven": _half_up(be),
    }

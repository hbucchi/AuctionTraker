"""Return on equity of an auction "flip": buy at auction, fix, resell.

    equity (what you put in)
        bid × (1 + auctioneer commission + ITBI + registration)
      + renovation                     (% of market value)
      + debts                          (% of value, only if the edital puts them on the buyer)
      + eviction                       (% of value, only if occupied; also adds months)
      + carrying costs while holding   (condo + IPTU, % of value per month)

    back at sale
        value × (1 − broker commission)
      − capital-gains tax              (on the profit, if any)

    ROE = (back at sale − equity) / equity

All cash, no financing. The range comes from running it on the low,
central and high ends of the valuation's 50% band (valuation.py): about
half of real appraisals fall inside that band, so roughly half of deals
would land inside the ROE range too, if costs match the assumptions.

web/roe.js is the browser twin; tests/roe_cases.json checks they agree.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULTS: dict[str, float] = {
    "commission_pct": 5.0,          # leiloeiro, on the bid (usual: 5%)
    "itbi_pct": 3.0,                # municipal transfer tax (2-3% in most cities)
    "registry_pct": 1.5,            # escritura + registro de imóveis
    "renovation_pct": 5.0,          # of market value
    "debts_pct": 5.0,               # of value, applied only when debts stay with the buyer
    "eviction_pct": 3.0,            # of value, applied only when occupied
    "eviction_months": 6.0,         # extra months when occupied
    "assume_occupied": 0.0,         # 1 = treat unknown occupancy as occupied (conservative)
    "holding_months": 12.0,         # from auction to sale
    "carrying_pct_month": 0.15,     # condo + IPTU while holding, % of value per month
    "broker_pct": 6.0,              # corretor, on the sale
    "tax_pct": 15.0,                # IR on capital gains (pessoa física)
}


def flip(price: float, value: float, debts: bool | None, occupied: bool | None, a: dict[str, float]) -> dict[str, float]:
    occ = occupied is True or (occupied is None and a["assume_occupied"] >= 1)
    months = a["holding_months"] + (a["eviction_months"] if occ else 0)
    equity = (
        price * (1 + (a["commission_pct"] + a["itbi_pct"] + a["registry_pct"]) / 100)
        + value * a["renovation_pct"] / 100
        + (value * a["debts_pct"] / 100 if debts is True else 0)
        + (value * a["eviction_pct"] / 100 if occ else 0)
        + value * a["carrying_pct_month"] / 100 * months
    )
    gain = value * (1 - a["broker_pct"] / 100) - equity
    profit = gain - max(gain, 0) * a["tax_pct"] / 100
    roe = profit / equity
    annual = (1 + roe) ** (12 / months) - 1 if roe > -1 else -1.0
    return {"roe": roe, "annual": annual, "equity": equity, "profit": profit, "months": months}


def assumptions(custom: dict[str, Any] | None = None) -> dict[str, float]:
    a = dict(DEFAULTS)
    for k, v in (custom or {}).items():
        if k in a and v is not None and v != "":
            a[k] = float(v)
    return a


def roe_range(item: dict, custom: dict[str, Any] | None = None) -> dict[str, float] | None:
    """ROE (in %) at the low / central / high value of the valuation's 50%
    band, for a compact listing (summary.py). None without a valuation."""
    val, price = item.get("val"), item.get("price")
    if not val or not price or price < 1_000 or val.get("flag"):
        return None
    a = assumptions(custom)
    lo = flip(price, val["lo50"], item.get("debts"), item.get("occ"), a)
    mid = flip(price, val["mid"], item.get("debts"), item.get("occ"), a)
    hi = flip(price, val["hi50"], item.get("debts"), item.get("occ"), a)
    return {
        "lo": round(100 * lo["roe"], 1), "mid": round(100 * mid["roe"], 1), "hi": round(100 * hi["roe"], 1),
        "annual": round(100 * mid["annual"], 1), "months": mid["months"], "equity": round(mid["equity"]),
    }


def _half_up(x: float) -> int:
    """Round halves up, like JavaScript's Math.round (Python's round() rounds
    halves to even, which would make the two twins disagree by 1 now and then)."""
    return math.floor(x + 0.5)


def value_needed(price: float, target_roe: float, debts: bool | None, occupied: bool | None, a: dict[str, float]) -> float:
    """Resale value that gives exactly ``target_roe`` (0 = breakeven).

    equity  = price·k + value·c          (k: purchase fees, c: value-linked costs)
    profit  = (value·(1−b) − equity)·(1−tax)   for a gain
    profit ≥ t·equity  ⇔  value ≥ price·k·(1+s) / (1 − b − c·(1+s)),  s = t / (1−tax)
    """
    occ = occupied is True or (occupied is None and a["assume_occupied"] >= 1)
    months = a["holding_months"] + (a["eviction_months"] if occ else 0)
    k = 1 + (a["commission_pct"] + a["itbi_pct"] + a["registry_pct"]) / 100
    c = (a["renovation_pct"] + (a["debts_pct"] if debts is True else 0) + (a["eviction_pct"] if occ else 0)
         + a["carrying_pct_month"] * months) / 100
    s = target_roe / (1 - a["tax_pct"] / 100) if target_roe > 0 else target_roe
    denom = 1 - a["broker_pct"] / 100 - c * (1 + s)
    return float("inf") if denom <= 0 else price * k * (1 + s) / denom


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


def chances(item: dict, quantiles: dict[str, list[float]], custom: dict[str, Any] | None = None,
            target_roe_pct: float = 20) -> dict[str, float] | None:
    """Chance (%) of any profit and of reaching ``target_roe_pct``."""
    val, price = item.get("val"), item.get("price")
    if not val or not price or price < 1_000 or val.get("flag") or not quantiles:
        return None
    q = quantiles.get("many" if (val.get("n") or 0) >= 3 else "few") or quantiles.get("many")
    a = assumptions(custom)
    be = value_needed(price, 0, item.get("debts"), item.get("occ"), a)
    tgt = value_needed(price, target_roe_pct / 100, item.get("debts"), item.get("occ"), a)
    return {
        "profit": _half_up(100 * chance_value_at_least(be, val["mid"], q)),
        "target": _half_up(100 * chance_value_at_least(tgt, val["mid"], q)),
        "breakeven": _half_up(be),
    }

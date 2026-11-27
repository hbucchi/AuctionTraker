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

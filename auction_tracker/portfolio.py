"""Users' own properties ("Meu portfólio") and interest profiles.

Firestore layout
  users/{uid}                     profile, strategies, checklists, last_filters,
                                  interest (+ flat interest_* arrays for queries)
  users/{uid}/portfolio/{pid}     a property the user owns. The user writes the
                                  facts; this daily job adds `valuation`,
                                  `gain_pct`, `interested_count`, `valued_at`.

Matching, privacy first
  A property is offered to the matcher only when its owner ticks both
  "à venda" (for_sale) and "permitir match" (allow_matching). The owner then
  sees how many OTHER users have an active strategy that fits it, a count and
  nothing else: no names, emails or filters are revealed to anyone.

Interest profile
  A summary of what a user is looking for, derived from their enabled
  strategies, stored flat so it can be queried later, e.g.
  users where interest_ufs array-contains "SP".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .enrich import enrich
from .models import Listing
from .strategy import matches
from .summary import to_summary
from .valuation import comps_index, estimate

log = logging.getLogger("portfolio")

KINDS = ("casa", "casa_condominio", "apartamento", "comercial", "galpao", "terreno", "rural", "outros")


def interest_profile(strategies: list[dict]) -> dict[str, Any]:
    """What a user is looking for, across their enabled strategies."""
    active = [s for s in strategies or [] if s.get("enabled", True)]
    ufs, cities, kinds, mods = set(), set(), set(), set()
    pmin, pmax, roe_min = [], [], []
    for s in active:
        sets = s.get("sets") or {}
        ufs |= set((sets.get("uf") or {}).get("values") or [])
        kinds |= set((sets.get("kind") or {}).get("values") or [])
        mods |= set((sets.get("modality") or {}).get("values") or [])
        cities |= {c.strip() for c in s.get("cities") or [] if c.strip()}
        price = (s.get("ranges") or {}).get("price") or {}
        if price.get("min") is not None:
            pmin.append(price["min"])
        if price.get("max") is not None:
            pmax.append(price["max"])
        roe = (s.get("ranges") or {}).get("roe") or {}
        if roe.get("min") is not None:
            roe_min.append(roe["min"])
    return {
        "strategies": len(active),
        "ufs": sorted(ufs), "cities": sorted(cities), "kinds": sorted(kinds), "modalities": sorted(mods),
        # the widest range any strategy accepts
        "price_min": min(pmin) if pmin and len(pmin) == len(active) else None,
        "price_max": max(pmax) if pmax and len(pmax) == len(active) else None,
        "roe_min": min(roe_min) if roe_min and len(roe_min) == len(active) else None,
    }


def interest_fields(strategies: list[dict]) -> dict[str, Any]:
    """User-document fields: the profile plus flat arrays for array-contains queries."""
    p = interest_profile(strategies)
    return {"interest": p, "interest_ufs": p["ufs"], "interest_kinds": p["kinds"], "interest_cities": p["cities"]}


def to_listing(uid: str, pid: str, d: dict) -> Listing:
    """A portfolio entry as a Listing, so it goes through the same enrichment
    and valuation as auction lots. Its "price" is the asking price when for
    sale (that's what buyers' strategies should judge), else what was paid."""
    kind = d.get("kind") if d.get("kind") in KINDS else None
    x = Listing(
        source="portfolio", source_id=f"{uid}/{pid}", url="", title=d.get("title") or "Imóvel",
        property_type=None, address=d.get("address"), neighborhood=d.get("neighborhood"),
        city=d.get("city"), state=(d.get("uf") or "").upper()[:2] or None,
        area_m2=_num(d.get("area")), bedrooms=_int(d.get("bedrooms")),
        current_price=_num(d.get("asking_price")) if d.get("for_sale") else _num(d.get("purchase_price")),
        occupied=d.get("occupied"),
    )
    enrich(x)
    if kind:
        x.kind = kind  # the owner knows better than our title classifier
    return x


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f else None


def invested(d: dict) -> float | None:
    paid = _num(d.get("purchase_price"))
    if not paid:
        return None
    return paid + (_num(d.get("purchase_costs")) or 0) + (_num(d.get("renovation_spent")) or 0)


def run(db: Any, auction_listings: list[Listing]) -> dict[str, int]:
    """Value every portfolio property and count interested users for those
    offered for matching. ``auction_listings`` provide the comparables."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    idx = comps_index(auction_listings)
    users = [(doc.id, doc.to_dict() or {}) for doc in db.collection("users").stream()]
    stats = {"users": 0, "properties": 0, "valued": 0, "offered": 0}

    for uid, user in users:
        # keep everyone's interest profile current (also written by the browser)
        db.collection("users").document(uid).set(interest_fields(user.get("strategies") or []), merge=True)

    for uid, user in users:
        props = list(db.collection("users").document(uid).collection("portfolio").stream())
        if props:
            stats["users"] += 1
        for doc in props:
            d = doc.to_dict() or {}
            stats["properties"] += 1
            x = to_listing(uid, doc.id, d)
            val = estimate(x, idx)
            out: dict[str, Any] = {"valuation": val, "valued_at": now, "kind_detected": x.kind,
                                   "city_population": x.city_population, "city_idhm": x.city_idhm}
            inv = invested(d)
            if val:
                stats["valued"] += 1
                if inv:
                    out["gain_pct"] = round(100 * (val["mid"] / inv - 1), 1)
            if d.get("for_sale") and d.get("allow_matching"):
                stats["offered"] += 1
                item = to_summary(x)
                count = 0
                for other_uid, other in users:
                    if other_uid == uid:
                        continue
                    if any(s.get("enabled", True) and matches({**s, "hide_ended": False}, item)
                           for s in other.get("strategies") or []):
                        count += 1
                out["interested_count"] = count
            else:
                out["interested_count"] = None
            doc.reference.set(out, merge=True)
    return stats

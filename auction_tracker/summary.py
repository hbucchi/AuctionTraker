"""Compact listing format for the web app.

Firestore bills per document read. If the dashboard loaded every listing as
its own document, one page view would cost ~4 000 reads (free tier: 50 000
reads/day). Instead each scraper run also writes summary documents holding a
compact copy of all of a site's listings, so a page view costs ~8 reads.
Firestore documents are limited to 1 MiB, so the summary keeps only what the
list view needs (~550 bytes per listing) and large sites are split across
several documents (Superbid: ~850 KB -> 2 parts).

Firestore can't store arrays directly inside arrays, which is why ``rounds``
is a list of small maps rather than a list of lists.
"""

from __future__ import annotations

from typing import Any

from .models import Listing

TITLE_MAX = 160
MAX_DOC_BYTES = 800_000  # per summary document; Firestore's hard limit is 1 MiB


def to_summary(x: Listing) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": x.id,
        "src": x.source,
        "url": x.url,
        "title": (x.title or "")[:TITLE_MAX],
        "cat": x.category,
        "type": x.property_type,
        "mod": x.modality,
        "status": x.status,
        "seller": x.seller,
        "city": x.city,
        "uf": x.state,
        "hood": x.neighborhood,
        "area": x.area_m2,
        "appraisal": x.appraisal_value,
        "price": x.current_price,
        "disc": x.discount_pct,
        "end": x.end_date,
        "img": x.image_url,
        "bids": x.bids_count,
        "rounds": [{"n": r.number, "d": r.date, "v": r.min_bid} for r in x.rounds],
        # strategy fields (see enrich.py and web/strategy-fields.json)
        "beds": x.bedrooms,
        "kind": x.kind,
        "modn": x.modality_norm,
        "mv": round(x.market_value) if x.market_value else None,
        "mvs": x.market_value_source,
        "ptm": x.price_to_market_pct,
        # True when the market value is the official appraisal (not a FipeZAP estimate)
        "mvo": bool(x.market_value_source) and not x.market_value_source.startswith("FipeZAP"),
        "debts": x.buyer_pays_debts,
        "debtsrc": x.debts_source,
        "occ": x.occupied,
        "lat": x.lat, "lon": x.lon, "geo": x.geo,
        "pop": x.city_population,
        "gdppc": x.city_gdp_per_capita,
        "idhm": x.city_idhm,
        "agro": x.city_agro_share,
        "cap": x.city_capital,
        # five-method valuation: range, central value, confidence, per-method values
        "val": {k: x.valuation[k] for k in ("lo", "mid", "hi", "lo50", "hi50", "n", "conf", "flag") if x.valuation.get(k) is not None}
        if x.valuation else None,
        "vm": x.valuation["methods"] if x.valuation else None,
        "ptmv": x.price_to_valuation_pct,
    }
    # keep False (e.g. debts=False means "seller pays"), drop only empty values
    return {k: v for k, v in d.items() if v is not None and v != [] and v != ""}


def listing_from_dict(d: dict[str, Any]) -> Listing:
    """Rebuild an enriched Listing from a Listing.to_dict() row (a JSONL line)."""
    from .enrich import enrich
    from .models import AuctionRound

    rounds = [AuctionRound(**r) for r in d.get("rounds") or []]
    fields = {k: v for k, v in d.items() if k in Listing.__dataclass_fields__ and k != "rounds"}
    return enrich(Listing(**fields, rounds=rounds))


def load_run(run_dir) -> list[Listing]:
    """All listings of a scrape run directory (data/<run-id>/*.jsonl), enriched and valued."""
    import json
    from pathlib import Path

    from .valuation import valuate_all

    out = []
    for f in sorted(Path(run_dir).glob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            out += [listing_from_dict(json.loads(line)) for line in fh if line.strip()]
    valuate_all(out)
    return out


def from_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Same as to_summary, from a Listing.to_dict() row (e.g. a JSONL line)."""
    return to_summary(listing_from_dict(d))

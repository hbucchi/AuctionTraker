"""Street-level coordinates through the Google Geocoding API (optional).

Without a key, listings sit at their municipality's center (enrich.place).
With GOOGLE_GEOCODING_KEY set (a server key restricted to the Geocoding
API, stored as a GitHub secret, never in the website), each daily run
geocodes addresses it hasn't seen, caches them in Firestore (geocache/*),
and moves the pins to street level.

Cost control: results are cached forever (addresses don't move), and each
run does at most MAX_NEW_PER_RUN new lookups, so after the first few days
only new listings are geocoded (~100/day), well inside Google's free tier.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import requests

from .models import Listing

log = logging.getLogger("geocode")
API = "https://maps.googleapis.com/maps/api/geocode/json"
MAX_NEW_PER_RUN = 800


def address_query(x: Listing) -> str | None:
    """A street address worth geocoding (a city alone isn't: we have its center)."""
    if not x.address or not x.city or not x.state:
        return None
    if not any(ch.isdigit() for ch in x.address) and len(x.address) < 12:
        return None
    parts = [x.address, x.neighborhood, f"{x.city} - {x.state}", "Brasil"]
    return ", ".join(p for p in parts if p)


def _key(q: str) -> str:
    return hashlib.sha1(q.lower().encode()).hexdigest()


def lookup(q: str, api_key: str) -> dict | None:
    r = requests.get(API, params={"address": q, "key": api_key, "region": "br", "language": "pt-BR"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        return {"status": data.get("status")}
    res = data["results"][0]
    loc = res["geometry"]["location"]
    # "ROOFTOP"/"RANGE_INTERPOLATED" = street level; "APPROXIMATE" is often just the city
    return {"lat": loc["lat"], "lon": loc["lng"], "type": res["geometry"].get("location_type"), "status": "OK"}


def apply(listings: list[Listing], db: Any, api_key: str | None = None) -> dict[str, int]:
    api_key = api_key or os.environ.get("GOOGLE_GEOCODING_KEY")
    stats = {"cached": 0, "new": 0, "precise": 0}
    if not api_key:
        return stats
    cache = db.collection("geocache")
    for x in listings:
        if x.geo == "exato":
            continue
        q = address_query(x)
        if not q:
            continue
        ref = cache.document(_key(q))
        snap = ref.get()
        if snap.exists:
            hit = snap.to_dict()
            stats["cached"] += 1
        elif stats["new"] < MAX_NEW_PER_RUN:
            try:
                hit = lookup(q, api_key)
            except requests.RequestException:
                log.exception("geocoding failed")
                continue
            ref.set({**(hit or {}), "q": q})
            stats["new"] += 1
        else:
            continue
        if hit and hit.get("status") == "OK" and hit.get("type") in ("ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"):
            x.lat, x.lon, x.geo = hit["lat"], hit["lon"], "exato"
            stats["precise"] += 1
    return stats

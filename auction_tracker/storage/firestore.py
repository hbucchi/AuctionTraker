"""Firestore sink.

Layout:
  summaries/{source}-{n}  compact copies of a site's listings: {source, part,
                       parts, updated_at, items: [...]}. Usually one document
                       per site; a site whose summary would exceed Firestore's
                       1 MiB document limit is split into several. The web app
                       reads this whole collection: ~8 reads per page view.
  listings/{id}        one document per lot (full Listing), upserted each run,
                       with first_seen_at / last_seen_at, plus the auction's
                       history: snap.YYYYMMDD = {p: price, b: bids, s: status}
                       once a day, and when a lot leaves its site, ended_at
                       and its final price, bids, status and outcome.
  runs/{run_id}        the health report of each run.
  meta/latest          {run_id, updated_at}: one tiny document the web app reads
                       first. If its updated_at matches the copy the browser
                       already holds, the summaries come from the browser's
                       cache instead of being downloaded again (1 read
                       instead of ~8 per visit; data changes once a day).

Security rules (firestore.rules) let signed-in users read and nobody write
from the browser. This sink uses a service account, which bypasses the rules.

Requires ``pip install google-cloud-firestore`` and the env var
GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account key file that
is never committed to git.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..models import Listing
from ..summary import MAX_DOC_BYTES, has_price, to_summary


def _eq(field: str, value):
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
    except ImportError:  # tests use a fake client without the library
        return (field, "==", value)
    return FieldFilter(field, "==", value)


class FirestoreSink:
    BATCH = 400  # Firestore allows at most 500 writes per batch

    def __init__(self, project_id: str | None = None, client: Any = None):
        if client is None:
            from google.cloud import firestore  # optional dependency, imported lazily

            client = firestore.Client(project=project_id)
        self.db = client

    def write(self, source: str, listings: list[Listing], complete: bool = False) -> None:
        """Upload one site's run. ``complete`` means the run covered the whole
        site (no page cap, status OK): only then do lots missing from it
        count as ended."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        day = now[:10].replace("-", "")

        summaries = self.db.collection("summaries")
        # first_seen is carried over from the previous summary (a few reads), so
        # the app can flag listings that appeared since earlier runs.
        prev_docs = list(summaries.where(filter=_eq("source", source)).stream())
        first_seen: dict[str, str] = {}
        previous: dict[str, dict] = {}
        for doc in prev_docs:
            for it in (doc.to_dict() or {}).get("items", []):
                previous[it["id"]] = it
                if it.get("first_seen"):
                    first_seen[it["id"]] = it["first_seen"]

        items = []
        for x in listings:
            if not has_price(x):
                continue  # kept in listings/{id}, but never shown or alerted on
            s = to_summary(x)
            s["first_seen"] = first_seen.get(x.id, now)
            items.append(s)
        parts = chunk_by_size(items, MAX_DOC_BYTES)
        new_ids = {f"{source}-{n}" for n in range(1, len(parts) + 1)}
        batch = self.db.batch()
        for n, part in enumerate(parts, start=1):
            batch.set(
                summaries.document(f"{source}-{n}"),
                {"source": source, "part": n, "parts": len(parts), "updated_at": now, "items": part},
            )
        for doc in prev_docs:  # a site that shrank leaves stale parts behind
            if doc.id not in new_ids:
                batch.delete(doc.reference)
        batch.commit()

        col = self.db.collection("listings")
        writes = []
        for x in listings:
            doc = x.to_dict()
            doc["first_seen_at"] = first_seen.get(x.id, now)
            doc["last_seen_at"] = now
            doc["ended_at"] = None  # a lot can come back (e.g. relisted for a new round)
            # one snapshot a day: merge=True adds the day's key to the map
            doc["snap"] = {day: {"p": x.current_price, "b": x.bids_count, "s": x.status}}
            writes.append((x.id, doc))
        if complete:
            seen = {x.id for x in listings}
            for lid, it in previous.items():
                if lid not in seen:
                    writes.append((lid, ended_record(it, now)))
        for i in range(0, len(writes), self.BATCH):
            batch = self.db.batch()
            for lid, doc in writes[i : i + self.BATCH]:
                batch.set(col.document(lid), doc, merge=True)
            batch.commit()

    def write_report(self, run_id: str, report: dict[str, Any]) -> None:
        self.db.collection("runs").document(run_id).set(report)

    def write_meta(self, run_id: str) -> None:
        """Mark a new data version, after all summaries of the run are written."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.db.collection("meta").document("latest").set({"run_id": run_id, "updated_at": now})


SOLD = re.compile(r"arrematad|vendid|sold", re.I)


def ended_record(it: dict[str, Any], now: str) -> dict[str, Any]:
    """What we know about a lot the day it left its site: its last price,
    bids and status. "sold" only when the site said so; otherwise "gone"
    (sold, unsold, suspended or withdrawn: the site doesn't say)."""
    return {
        "ended_at": now,
        "final_price": it.get("price"),
        "final_bids": it.get("bids"),
        "final_status": it.get("status"),
        "outcome": "sold" if SOLD.search(it.get("status") or "") else "gone",
    }


def chunk_by_size(items: list[dict[str, Any]], max_bytes: int) -> list[list[dict[str, Any]]]:
    """Split items into consecutive groups whose JSON size stays under max_bytes."""
    parts: list[list[dict[str, Any]]] = [[]]
    size = 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False).encode()) + 1
        if parts[-1] and size + n > max_bytes:
            parts.append([])
            size = 0
        parts[-1].append(it)
        size += n
    return parts

"""Firestore sink.

Layout:
  summaries/{source}-{n}  compact copies of a site's listings: {source, part,
                       parts, updated_at, items: [...]}. Usually one document
                       per site; a site whose summary would exceed Firestore's
                       1 MiB document limit is split into several. The web app
                       reads this whole collection: ~8 reads per page view.
  listings/{id}        one document per lot (full Listing), upserted each run,
                       with first_seen_at / last_seen_at, for detail views and
                       history later.
  runs/{run_id}        the health report of each run.

Security rules (firestore.rules) let signed-in users read and nobody write
from the browser. This sink uses a service account, which bypasses the rules.

Requires ``pip install google-cloud-firestore`` and the env var
GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account key file that
is never committed to git.
"""

from __future__ import annotations

import json
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

    def write(self, source: str, listings: list[Listing]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        summaries = self.db.collection("summaries")
        # first_seen is carried over from the previous summary (a few reads), so
        # the app can flag listings that appeared since earlier runs.
        prev_docs = list(summaries.where(filter=_eq("source", source)).stream())
        first_seen: dict[str, str] = {}
        for doc in prev_docs:
            for it in (doc.to_dict() or {}).get("items", []):
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
        for i in range(0, len(listings), self.BATCH):
            batch = self.db.batch()
            for x in listings[i : i + self.BATCH]:
                doc = x.to_dict()
                doc["first_seen_at"] = first_seen.get(x.id, now)
                doc["last_seen_at"] = now
                batch.set(col.document(x.id), doc, merge=True)
            batch.commit()

    def write_report(self, run_id: str, report: dict[str, Any]) -> None:
        self.db.collection("runs").document(run_id).set(report)


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

"""Firestore sink — NOT WIRED UP YET (waiting for the project's credentials).

Planned layout:
  listings/{source:source_id}   one document per lot, upserted each run
                                (fields = Listing.to_dict(), plus first_seen_at
                                and last_seen_at so we can tell new and
                                withdrawn lots apart)
  runs/{run_id}                 the health report of each run

Requires ``pip install google-cloud-firestore`` and a service-account key
exposed through GOOGLE_APPLICATION_CREDENTIALS (never committed to git).
"""

from __future__ import annotations

from ..models import Listing


class FirestoreSink:
    BATCH = 400  # Firestore allows up to 500 writes per batch

    def __init__(self, project_id: str | None = None):
        from google.cloud import firestore  # imported lazily: optional dependency

        self._fs = firestore
        self.db = firestore.Client(project=project_id)

    def write(self, source: str, listings: list[Listing]) -> None:
        col = self.db.collection("listings")
        now = self._fs.SERVER_TIMESTAMP
        for i in range(0, len(listings), self.BATCH):
            batch = self.db.batch()
            for item in listings[i : i + self.BATCH]:
                doc = item.to_dict()
                doc["last_seen_at"] = now
                batch.set(col.document(item.id), doc, merge=True)
            batch.commit()

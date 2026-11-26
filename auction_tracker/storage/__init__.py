"""Where scraped listings go. Every sink upserts by ``Listing.id`` so running
the routine again updates records instead of duplicating them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..models import Listing


class Sink(Protocol):
    def write(self, source: str, listings: list[Listing]) -> None: ...


class JsonlSink:
    """One JSON object per line: data/<run>/<source>.jsonl. Good for local
    runs, diffs and as test input for the Firestore loader."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    def write(self, source: str, listings: list[Listing]) -> None:
        path = self.out_dir / f"{source}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for item in listings:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

"""Normalized data model shared by every scraper.

Every site has its own vocabulary ("praça", "leilão", "lance mínimo",
"valor de avaliação"...). Scrapers translate their site into this single
shape so the database, the dashboard and any analysis never need to know
which site a listing came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuctionRound:
    """One round ("praça") of an auction.

    Brazilian property auctions usually run in two rounds: the 1st round
    asks for at least the appraisal value, and if nobody bids, the 2nd round
    opens a few days later with a lower minimum (often 50-70% of it).
    """

    number: int                    # 1, 2, ...
    date: str | None = None        # ISO 8601, America/Sao_Paulo when known
    min_bid: float | None = None   # minimum bid in BRL


@dataclass
class Listing:
    # --- identity -----------------------------------------------------
    source: str                    # scraper name, e.g. "zuk"
    source_id: str                 # the site's own id for the lot/offer
    url: str                       # public page for a human to open

    # --- description --------------------------------------------------
    title: str
    category: str = "outros"       # "imovel" | "veiculo" | "outros"
    property_type: str | None = None   # "Casa", "Apartamento", "Terreno"...
    modality: str | None = None    # "judicial", "extrajudicial", "venda direta"...
    status: str | None = None      # site status text, lightly normalized
    seller: str | None = None      # comitente / credor (bank, court, ...)

    # --- location -----------------------------------------------------
    address: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None       # two-letter UF, e.g. "SP"

    # --- size ---------------------------------------------------------
    area_m2: float | None = None

    # --- money (BRL) --------------------------------------------------
    appraisal_value: float | None = None   # valor de avaliação
    current_price: float | None = None     # what you'd pay right now (min bid / price)
    discount_pct: float | None = None      # vs appraisal, when the site states or we can compute it
    rounds: list[AuctionRound] = field(default_factory=list)

    # --- timing -------------------------------------------------------
    end_date: str | None = None    # ISO 8601: when bidding (or the last round) closes

    # --- extras -------------------------------------------------------
    image_url: str | None = None
    bids_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)   # site-specific leftovers
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def id(self) -> str:
        """Stable document id: the same lot always maps to the same record,
        so re-running a scrape updates rows instead of duplicating them."""
        return f"{self.source}:{self.source_id}"

    def finalize(self) -> "Listing":
        """Fill fields that can be derived from others."""
        if self.area_m2 is None:
            from .parsing import parse_area  # local import keeps models dependency-free

            self.area_m2 = parse_area(self.title)
        if self.current_price is None and self.rounds:
            # The price that matters is the lowest round still to come; as a
            # simple, predictable rule we take the last round's minimum bid.
            priced = [r for r in self.rounds if r.min_bid is not None]
            if priced:
                self.current_price = priced[-1].min_bid
        if self.end_date is None and self.rounds:
            dated = [r.date for r in self.rounds if r.date]
            if dated:
                self.end_date = max(dated)
        if (
            self.discount_pct is None
            and self.appraisal_value
            and self.current_price is not None
            and self.appraisal_value > 0
        ):
            self.discount_pct = round(100 * (1 - self.current_price / self.appraisal_value), 1)
        if self.state:
            self.state = self.state.strip().upper()[:2]
        return self

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d


# Fields the health check expects to be filled for most listings of a site.
# If the fill-rate of one of these collapses, the site probably changed its
# layout and the scraper needs attention (see AGENT_MAINTENANCE.md).
CORE_FIELDS = ("url", "title", "current_price", "city", "state")

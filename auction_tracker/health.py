"""Run report: is each scraper still healthy?

Sites change their HTML without warning. A broken scraper rarely crashes; it
usually returns *fewer* listings or listings with empty fields. So after each
run we compute, per site:

* count            how many listings came back
* fill_rates       share of listings with each core field filled
* status           OK / WARN / FAIL with human-readable reasons

The AI agent that maintains the scrapers starts from this report
(see AGENT_MAINTENANCE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import CORE_FIELDS, Listing

MIN_FILL_RATE = 0.6      # a core field filled in < 60% of listings is suspicious
MAX_DROP = 0.5           # losing > 50% of listings vs. the previous run is suspicious
MIN_COVERAGE = 0.9       # collecting < 90% of the total the site advertises is suspicious


@dataclass
class SiteReport:
    source: str
    status: str = "OK"
    count: int = 0
    reported_total: int | None = None
    seconds: float = 0.0
    error: str | None = None
    fill_rates: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def flag(self, level: str, reason: str) -> None:
        order = {"OK": 0, "WARN": 1, "FAIL": 2}
        if order[level] > order[self.status]:
            self.status = level
        self.reasons.append(reason)


def fill_rates(listings: list[Listing]) -> dict[str, float]:
    if not listings:
        return {f: 0.0 for f in CORE_FIELDS}
    return {
        f: round(sum(1 for x in listings if getattr(x, f) not in (None, "")) / len(listings), 3)
        for f in CORE_FIELDS
    }


def assess(
    report: SiteReport,
    listings: list[Listing],
    expected_min: int,
    previous_count: int | None,
    limited: bool = False,
    reported_total: int | None = None,
) -> SiteReport:
    report.count = len(listings)
    report.fill_rates = fill_rates(listings)
    if report.error:
        report.flag("FAIL", f"exception: {report.error}")
    if report.count == 0:
        report.flag("FAIL", "no listings returned")
    elif not limited and report.count < expected_min:
        report.flag("WARN", f"only {report.count} listings (expected >= {expected_min})")
    if not limited and previous_count and report.count < previous_count * (1 - MAX_DROP):
        report.flag("WARN", f"count fell from {previous_count} to {report.count}")
    report.reported_total = reported_total
    if not limited and reported_total and report.count < reported_total * MIN_COVERAGE:
        report.flag(
            "WARN",
            f"collected {report.count} of the {reported_total} the site advertises "
            f"({report.count / reported_total:.0%}) — pagination may be skipping items",
        )
    for f, rate in report.fill_rates.items():
        if report.count and rate < MIN_FILL_RATE:
            report.flag("WARN", f"field '{f}' filled in only {rate:.0%} of listings")
    return report

"""Command line entry point.

    python -m auction_tracker list
    python -m auction_tracker scrape                 # every site
    python -m auction_tracker scrape zuk alfa        # some sites
    python -m auction_tracker scrape --max-pages 1   # quick smoke test

Output goes to data/<run-id>/<site>.jsonl plus data/<run-id>/report.json;
data/latest_report.json always holds the most recent report.
Exit code is 1 if any site FAILed, so schedulers/CI can alert on it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .health import SiteReport, assess
from .scrapers import REGISTRY
from .storage import JsonlSink


def _previous_counts(data_dir: Path) -> dict[str, int]:
    p = data_dir / "latest_report.json"
    if not p.exists():
        return {}
    try:
        rep = json.loads(p.read_text())
        if rep.get("max_pages") is not None:
            return {}  # a limited smoke run is no baseline
        return {s["source"]: s["count"] for s in rep.get("sites", [])}
    except (ValueError, KeyError):
        return {}


def cmd_scrape(args: argparse.Namespace) -> int:
    names = args.sites or list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"unknown site(s): {', '.join(unknown)}. Try: {', '.join(REGISTRY)}", file=sys.stderr)
        return 2

    data_dir = Path(args.out)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sink = JsonlSink(data_dir / run_id)
    prev = _previous_counts(data_dir)
    reports = []

    for name in names:
        scraper = REGISTRY[name](max_pages=args.max_pages)
        rep = SiteReport(source=name)
        listings = []
        t0 = time.monotonic()
        try:
            listings = scraper.run()
        except Exception as e:  # one broken site must not stop the others
            logging.getLogger(name).exception("scrape failed")
            rep.error = f"{type(e).__name__}: {e}"
        rep.seconds = round(time.monotonic() - t0, 1)
        if listings:
            sink.write(name, listings)
        assess(
            rep,
            listings,
            scraper.expected_min_listings,
            prev.get(name),
            limited=args.max_pages is not None,
            reported_total=scraper.reported_total,
        )
        reports.append(rep)
        print(f"{rep.status:4} {name:9} {rep.count:6} listings  {rep.seconds:6.1f}s  {'; '.join(rep.reasons)}")

    summary = {
        "run_id": run_id,
        "max_pages": args.max_pages,
        "sites": [asdict(r) for r in reports],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    (data_dir / run_id / "report.json").write_text(text)
    (data_dir / "latest_report.json").write_text(text)
    print(f"\nwrote {data_dir / run_id}")
    return 1 if any(r.status == "FAIL" for r in reports) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auction_tracker")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list available scrapers")
    sp = sub.add_parser("scrape", help="run scrapers")
    sp.add_argument("sites", nargs="*", help=f"subset of: {', '.join(REGISTRY)}")
    sp.add_argument("--max-pages", type=int, default=None, help="cap pages per site (smoke test)")
    sp.add_argument("--out", default="data", help="output directory (default: data)")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.cmd == "list":
        for name, cls in REGISTRY.items():
            print(f"{name:9} {cls.base_url}")
        return 0
    return cmd_scrape(args)


if __name__ == "__main__":
    sys.exit(main())

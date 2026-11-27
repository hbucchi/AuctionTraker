"""Command line entry point.

    python -m auction_tracker list
    python -m auction_tracker scrape                 # every site
    python -m auction_tracker scrape zuk alfa        # some sites
    python -m auction_tracker scrape --max-pages 1   # quick smoke test
    python -m auction_tracker scrape --firestore     # also upload to Firestore
    python -m auction_tracker export-web data/<run-id> web/listings.json

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

from .enrich import enrich
from .valuation import valuate_all
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
    fs = None
    if args.firestore:
        from .storage.firestore import FirestoreSink

        fs = FirestoreSink(project_id=args.project)
    prev = _previous_counts(data_dir)
    reports = []
    results = []

    for name in names:
        scraper = REGISTRY[name](max_pages=args.max_pages)
        rep = SiteReport(source=name)
        listings = []
        t0 = time.monotonic()
        try:
            listings = [enrich(x) for x in scraper.run()]
        except Exception as e:  # one broken site must not stop the others
            logging.getLogger(name).exception("scrape failed")
            rep.error = f"{type(e).__name__}: {e}"
        rep.seconds = round(time.monotonic() - t0, 1)
        assess(
            rep,
            listings,
            scraper.expected_min_listings,
            prev.get(name),
            limited=args.max_pages is not None,
            reported_total=scraper.reported_total,
        )
        reports.append(rep)
        results.append((name, listings, rep))
        print(f"{rep.status:4} {name:9} {rep.count:6} listings  {rep.seconds:6.1f}s  {'; '.join(rep.reasons)}")

    # Valuation compares listings across all sites (auction comparables), so
    # it runs once everything is scraped, before anything is written.
    valuate_all([x for _, listings, _ in results for x in listings])
    if fs is not None:
        from . import geocode

        g = geocode.apply([x for _, listings, _ in results for x in listings], fs.db)
        if g["new"] or g["cached"]:
            print(f"geocoding: {g['new']} new lookups, {g['cached']} cached, {g['precise']} street-level pins")
    for name, listings, rep in results:
        if listings:
            sink.write(name, listings)
        if fs is not None and listings and rep.status != "FAIL":
            # a WARN run still uploads (data is usable); a FAIL keeps yesterday's data
            fs.write(name, listings)

    summary = {
        "run_id": run_id,
        "max_pages": args.max_pages,
        "sites": [asdict(r) for r in reports],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    (data_dir / run_id / "report.json").write_text(text)
    (data_dir / "latest_report.json").write_text(text)
    if fs is not None:
        fs.write_report(run_id, summary)
    print(f"\nwrote {data_dir / run_id}")
    return 1 if any(r.status == "FAIL" for r in reports) else 0


def cmd_alerts(args: argparse.Namespace) -> int:
    """Check every user's strategies against the listings now in Firestore."""
    from . import alerts
    from .storage.firestore import FirestoreSink

    db = FirestoreSink(project_id=args.project).db
    items = []
    for doc in db.collection("summaries").stream():
        items += (doc.to_dict() or {}).get("items", [])
    stats = alerts.run(db, items)
    print(f"alerts: {stats['users']} users, {stats['new']} new matches, {stats['emails']} emails sent")
    return 0


def cmd_export_web(args: argparse.Namespace) -> int:
    """Concatenate a run's JSONL files into the compact JSON the web app reads."""
    from .summary import load_run, to_summary

    run_dir = Path(args.run_dir)
    items = [to_summary(x) for x in load_run(run_dir)]
    run_id = run_dir.name
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        # one record per line keeps the file diff- and grep-friendly
        fh.write('{"run_id": %s, "items": [\n' % json.dumps(run_id))
        fh.write(",\n".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) for i in items))
        fh.write("\n]}\n")
    print(f"wrote {len(items)} listings to {out} ({out.stat().st_size // 1024} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auction_tracker")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list available scrapers")
    sp = sub.add_parser("scrape", help="run scrapers")
    sp.add_argument("sites", nargs="*", help=f"subset of: {', '.join(REGISTRY)}")
    sp.add_argument("--max-pages", type=int, default=None, help="cap pages per site (smoke test)")
    sp.add_argument("--out", default="data", help="output directory (default: data)")
    sp.add_argument("--firestore", action="store_true", help="also upload to Firestore")
    sp.add_argument("--project", default="auctiontraker", help="Firebase project id")
    ap_al = sub.add_parser("alerts", help="email users about listings that newly match their strategies")
    ap_al.add_argument("--project", default="auctiontraker", help="Firebase project id")
    ep = sub.add_parser("export-web", help="build the web app's data file from a run")
    ep.add_argument("run_dir")
    ep.add_argument("out", nargs="?", default="web/listings.json")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.cmd == "list":
        for name, cls in REGISTRY.items():
            print(f"{name:9} {cls.base_url}")
        return 0
    if args.cmd == "export-web":
        return cmd_export_web(args)
    if args.cmd == "alerts":
        return cmd_alerts(args)
    return cmd_scrape(args)


if __name__ == "__main__":
    sys.exit(main())

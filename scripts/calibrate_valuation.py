"""Calibrate the five valuation methods against official auction appraisals.

    python scripts/calibrate_valuation.py data/<run-id>

Writes auction_tracker/data/valuation_calibration.json and prints how
accurate each method is on appraisals it did not see (5-fold cross-validation).
Re-run after refreshing FipeZAP/SINAPI or when the scraped data changes a lot.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_tracker.summary import listing_from_dict  # noqa: E402
from auction_tracker.valuation import CALIB_PATH, METHODS, OFFICIAL_ASSUMED_MDAPE, OFFICIAL_METHOD, OFFICIAL_NAME, calibrate  # noqa: E402


def main() -> int:
    run = Path(sys.argv[1])
    listings = []
    for f in sorted(run.glob("*.jsonl")):
        listings += [listing_from_dict(json.loads(l)) for l in f.open(encoding="utf-8") if l.strip()]
    cal = calibrate(listings)
    CALIB_PATH.write_text(json.dumps(cal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # what the web app shows next to each valuation
    fz = json.loads((ROOT / "auction_tracker" / "data" / "fipezap.json").read_text(encoding="utf-8"))
    sn = json.loads((ROOT / "auction_tracker" / "data" / "sinapi.json").read_text(encoding="utf-8"))
    meta = {
        "methods": {
            OFFICIAL_METHOD: {"name": OFFICIAL_NAME, "mdape": OFFICIAL_ASSUMED_MDAPE, "assumed": True},
            **{m: {"name": name, **cal["scores"][m]} for m, name in METHODS.items()},
        },
        "combined": cal["combined"],
        "interval": cal["interval"],
        "interval50": cal.get("interval50"),
        "residual_quantiles": cal["residual_quantiles"],
        "n_official": cal["n_official"],
        "sources": {"fipezap": fz["month"], "sinapi": sn["month"]},
    }
    spec_path = ROOT / "web" / "strategy-fields.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.setdefault("reference", {})["residual_quantiles"] = cal["residual_quantiles"]
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "web" / "valuation-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"calibrated on {cal['n_official']} official appraisals; size elasticity alpha = {cal['alpha']}")
    print(f"city regression: R² {cal['m3_r2']}, leave-one-city-out error {cal['m3_city_loo_mdape']:.0%}")
    print(f"{'method':58} {'median error':>12} {'within ±20%':>12} {'n':>5}")
    for m, name in METHODS.items():
        s = cal["scores"][m]
        if s["n"]:
            print(f"{m} {name:55} {s['mdape']:>12.0%} {s['within_20pct']:>12.0%} {s['n']:>5}")
        else:
            print(f"{m} {name:55} {'—':>12} {'—':>12} {0:>5}")
    c = cal["combined"]
    print(f"{'combined (weighted)':61} {c['mdape']:>9.0%} {c['within_20pct']:>12.0%} {c['n']:>5}")
    for b, q in cal["interval"].items():
        print(f"80% interval ({b} methods): central × {q['q10']} … × {q['q90']}  (n={q['n']})")
    print("factors:", {k: round(v, 2) for k, v in cal["factors"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())

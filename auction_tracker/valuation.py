"""Five-method property valuation, reconciled into a range.

Brazil's appraisal standard (ABNT NBR 14653) names several approaches; a
professional appraiser runs more than one and reconciles them. We do the
same with public data:

  m1 comparativo   FipeZAP average asking price per m² in the city (by
                   bedroom count when known) × area
  m2 renda         FipeZAP rent per m² ÷ the city's rental yield × area
                   (income capitalization: value = rent / yield)
  m3 regressao     a model learned across FipeZAP's 56 cities that predicts
                   price per m² from city traits (GDP per capita,
                   population, HDI, capital, South/Southeast) — works for
                   every municipality, not just the 56
  m4 comparaveis   median official appraisal per m² of similar auction
                   properties in the same city (≥ 3 comparables)
  m5 custo         replacement cost: SINAPI construction cost per m² in the
                   state × area, depreciated, plus a land share

Tested and left out: for cities FipeZAP doesn't cover, borrowing the
nearest FipeZAP city's price/rent (≤150 km, scaled by the m3 regression)
as extra methods. On 369 held-out appraisals the combined error did not
improve (36.5% vs 36.0%) and the range widened: m3 already predicts a
city's price from its traits, which is what the neighbour adds.

Each raw estimate is multiplied by a calibration factor learned from the
official appraisals we scrape (see calibrate()), and every method gets an
out-of-sample error score: the median absolute percentage error (MdAPE)
when predicting appraisals it did not see during calibration.

Reconciliation
  central weighted geometric mean, weight = 1 / MdAPE²: a method that has
          been twice as accurate counts four times as much (inverse-variance
          weighting, the standard way to combine noisy measurements)
  range   an 80% prediction interval: central × the 10th and 90th
          percentiles of (true appraisal ÷ central estimate) measured on
          held-out appraisals. About 8 in 10 real appraisals fall inside.
  confidence  from how many methods are available and how closely they agree
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from .enrich import _norm, first_round_value, fipezap, municipios
from .models import Listing
from .parsing import parse_areas, parse_share

DATA = Path(__file__).parent / "data"
CALIB_PATH = DATA / "valuation_calibration.json"

RESIDENTIAL = {"casa", "casa_condominio", "apartamento"}
# Warehouses/industrial sheds are left out: too few appraisals to calibrate
# (12), and office/shop price indices badly overvalue them.
COMMERCIAL = {"comercial"}
METHODS = {
    "m1": "Comparativo direto (FipeZAP R$/m²)",
    "m2": "Capitalização da renda (aluguel FipeZAP ÷ rentabilidade)",
    "m3": "Regressão entre cidades (FipeZAP × PIB, população, IDH)",
    "m4": "Comparáveis de leilão (avaliações oficiais na cidade)",
    "m5": "Custo de reposição (SINAPI + terreno)",
}
# The auction's own appraisal (or the 1st-round bid, legally the appraisal),
# when published. It can't be scored like the others (it is the yardstick they
# are calibrated against), so it gets an ASSUMED error: professional
# appraisals typically land within 10-20% of sale prices.
OFFICIAL_METHOD = "m0"
OFFICIAL_NAME = "Avaliação oficial do leilão"
OFFICIAL_ASSUMED_MDAPE = 0.15
OFFICIAL_WEIGHT_VS_MODELS = 3.0  # official appraisal weighs 3x all public-data methods combined (75%)
SOUTH_SOUTHEAST = {"SP", "RJ", "MG", "ES", "PR", "SC", "RS"}
LAND_SHARE = {"apartamento": 0.15, "casa": 0.35, "casa_condominio": 0.30, "comercial": 0.25, "galpao": 0.30}
ATYPICAL_PCT = 20  # bids under 20% of the estimate are flagged ("conferir"), not ranked as bargains
DEPRECIATION = 0.25  # age is unknown; a mid-life building under Ross-Heidecke loses roughly a quarter


@lru_cache(maxsize=1)
def sinapi() -> dict:
    return json.loads((DATA / "sinapi.json").read_text(encoding="utf-8"))


def group(kind: str | None) -> str | None:
    if kind in RESIDENTIAL:
        return "res"
    if kind in COMMERCIAL:
        return "com"
    return None


def usable_area(x: Listing) -> float | None:
    """Built area to value on. Titles often give the lot size for houses
    ("área total", "terreno de 300m²"); valuing a house on its lot at
    built-area prices is badly wrong, so a lot-only mention yields None."""
    g = group(x.kind)
    if not g:
        return None
    built, lot = parse_areas(x.title)
    a = built or x.area_m2
    if not built and lot and x.kind in ("casa", "casa_condominio"):
        return None
    if not a:
        return None
    return a if 15 <= a <= (3_000 if g == "res" else 5_000) else None


def ownership_share(x: Listing) -> float:
    """Fraction of the property being sold: Superbid prefixes titles with the
    share, "(25%) Casa ..."; others write "parte ideal de 50%"."""
    return parse_share(x.title) or 1.0


def official_value(x: Listing) -> float | None:
    """The ground truth we calibrate against: the auction's own appraisal,
    or the 1st-round minimum bid (legally the appraisal)."""
    v = x.appraisal_value if x.appraisal_value and x.appraisal_value > 0 else first_round_value(x)
    a = usable_area(x)
    if not v or not a:
        return None
    v = v / ownership_share(x)  # a 25% share appraised at 100k means the whole is worth 400k
    return v if 300 <= v / a <= 60_000 else None  # drop obvious data errors


def _city(x: Listing) -> dict | None:
    if not x.city or not x.state:
        return None
    return fipezap()["cities"].get(f"{_norm(x.city)}|{x.state}")


def _size_adj(area: float, g: str, alpha: float) -> float:
    """Bigger units sell for less per m². Price/m² ∝ (area / reference)^-alpha."""
    ref = 70.0 if g == "res" else 100.0
    return (area / ref) ** (-alpha)


# ------------------------------------------------------------- raw methods

def _m1(c: dict, x: Listing, a: float, g: str, cal: dict) -> float | None:
    if g == "res":
        pm2 = c.get(f"residential_{min(x.bedrooms, 4)}d") if x.bedrooms else None
        pm2 = pm2 or c.get("residential")
    else:
        pm2 = c.get("commercial")
    return pm2 * a * _size_adj(a, g, cal["alpha"]) if pm2 else None


def _m2(c: dict, x: Listing, a: float, g: str, cal: dict) -> float | None:
    if g == "res":
        rent = (c.get(f"rent_residential_{min(x.bedrooms, 4)}d") if x.bedrooms else None) or c.get("rent_residential")
        y = c.get("yield_monthly_pct")
    else:
        rent, y = c.get("rent_commercial"), c.get("yield_commercial_monthly_pct")
    if not rent or not y:
        return None
    # value = monthly rent / monthly yield  (both per m²)
    return rent / (y / 100) * a * _size_adj(a, g, cal["alpha"])


def raw_m1(x: Listing, cal: dict) -> float | None:
    c, a, g = _city(x), usable_area(x), group(x.kind)
    return _m1(c, x, a, g, cal) if (c and a and g) else None


def raw_m2(x: Listing, cal: dict) -> float | None:
    c, a, g = _city(x), usable_area(x), group(x.kind)
    return _m2(c, x, a, g, cal) if (c and a and g) else None


def city_features(m: dict) -> list[float] | None:
    if not (m.get("gdp_per_capita") and m.get("population") and m.get("idhm")):
        return None
    return [1.0, math.log(m["gdp_per_capita"]), math.log(m["population"]), m["idhm"],
            1.0 if m.get("capital") else 0.0, 1.0 if m["uf"] in SOUTH_SOUTHEAST else 0.0]


def raw_m3(x: Listing, cal: dict) -> float | None:
    a, g = usable_area(x), group(x.kind)
    if not (a and g and x.city and x.state):
        return None
    m = municipios()["by_key"].get(f"{_norm(x.city)}|{x.state}")
    f = city_features(m) if m else None
    if not f:
        return None
    pm2 = math.exp(sum(b * v for b, v in zip(cal["m3_coef"], f)))
    if g == "com":
        pm2 *= cal["m3_commercial_ratio"]
    return pm2 * a * _size_adj(a, g, cal["alpha"])


def raw_m5(x: Listing, cal: dict) -> float | None:
    a, g = usable_area(x), group(x.kind)
    cost = sinapi()["cost_m2"].get(x.state or "")
    if not (a and g and cost):
        return None
    building = cost * a * (1 - DEPRECIATION)
    return building / (1 - LAND_SHARE.get(x.kind, 0.3))


RAW: dict[str, Callable[[Listing, dict], float | None]] = {"m1": raw_m1, "m2": raw_m2, "m3": raw_m3, "m5": raw_m5}


# ------------------------------------------------------------ comparables

def comps_index(listings: Iterable[Listing]) -> dict[tuple[str, str, str], list[tuple[str, float]]]:
    """(city, UF, group) -> [(listing id, official R$/m²)]"""
    idx: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
    for x in listings:
        v = official_value(x)
        if v:
            key = (_norm(x.city or ""), x.state or "", group(x.kind))
            idx.setdefault(key, []).append((x.id, v / usable_area(x)))
    return idx


def raw_m4(x: Listing, idx: dict, min_comps: int = 3) -> tuple[float, int] | None:
    a, g = usable_area(x), group(x.kind)
    if not (a and g):
        return None
    pool = [pm2 for lid, pm2 in idx.get((_norm(x.city or ""), x.state or "", g), []) if lid != x.id]
    if len(pool) < min_comps:
        return None
    return statistics.median(pool) * a, len(pool)


# ------------------------------------------------------------ calibration

def _ols(X: list[list[float]], y: list[float]) -> list[float]:
    """Least squares via the normal equations (XᵀX)β = Xᵀy, solved by
    Gaussian elimination: small enough that we don't need numpy."""
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] + [sum(r[i] * t for r, t in zip(X, y))] for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]
                A[r] = [a - f * b for a, b in zip(A[r], A[i])]
    return [A[i][k] / A[i][i] for i in range(k)]


def fit_city_regression() -> tuple[list[float], float, float, list[dict]]:
    """ln(R$/m²) ~ city traits, fitted on FipeZAP's cities. Returns
    (coefficients, R², leave-one-city-out MdAPE, rows)."""
    muns = municipios()["by_key"]
    rows = []
    for key, c in fipezap()["cities"].items():
        m = muns.get(key)
        f = city_features(m) if m else None
        if f and c.get("residential"):
            rows.append({"key": key, "f": f, "y": math.log(c["residential"]), "com": c.get("commercial"), "res": c["residential"]})
    X, y = [r["f"] for r in rows], [r["y"] for r in rows]
    coef = _ols(X, y)
    pred = [sum(b * v for b, v in zip(coef, f)) for f in X]
    mean = sum(y) / len(y)
    r2 = 1 - sum((a - b) ** 2 for a, b in zip(y, pred)) / sum((a - mean) ** 2 for a in y)
    loo = []
    for i in range(len(rows)):
        c_i = _ols(X[:i] + X[i + 1:], y[:i] + y[i + 1:])
        loo.append(abs(math.exp(sum(b * v for b, v in zip(c_i, X[i])) - y[i]) - 1))
    return coef, r2, statistics.median(loo), rows


def _mdape(pairs: list[tuple[float, float]]) -> float | None:
    errs = [abs(est / true - 1) for est, true in pairs if est and true]
    return statistics.median(errs) if errs else None


def _factor(fac: dict, m: str, kind: str) -> float:
    """Calibration factor for a method and property kind (falls back to the
    residential/commercial group when a kind has too few appraisals)."""
    return fac.get(f"{m}_{kind}") or fac.get(f"{m}_{group(kind)}") or 1.0


def fit_factors(sample: list[Listing], cal: dict, min_n: int = 15) -> dict:
    out = {}
    for m, fn in RAW.items():
        for key, members in (("res", RESIDENTIAL), ("com", COMMERCIAL), *((k, {k}) for k in RESIDENTIAL | COMMERCIAL)):
            r = [official_value(x) / v for x in sample if x.kind in members and (v := fn(x, cal))]
            if len(r) >= min_n:
                out[f"{m}_{key}"] = statistics.median(r)
    return out


def _quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def calibrate(listings: list[Listing], folds: int = 5, seed: int = 7) -> dict:
    """Learn the multipliers that turn each raw method into an appraisal
    estimate, measure every method (and the combined estimate) on appraisals
    held out of the fit, and derive an 80% prediction interval."""
    coef, r2, loo, rows = fit_city_regression()
    ratios = [r["com"] / r["res"] for r in rows if r["com"]]
    cal: dict[str, Any] = {
        "alpha": 0.0,
        "m3_coef": coef,
        "m3_commercial_ratio": statistics.median(ratios) if ratios else 0.85,
        "m3_r2": round(r2, 3),
        "m3_city_loo_mdape": round(loo, 3),
    }
    train = [x for x in listings if official_value(x)]
    random.Random(seed).shuffle(train)
    idx = comps_index(train)

    def cv_estimates(alpha: float) -> list[tuple[Listing, dict[str, float]]]:
        """Out-of-fold estimates: each listing is valued with factors fitted
        on the other folds (m4 is leave-one-out by construction)."""
        c = {**cal, "alpha": alpha}
        out = []
        for k in range(folds):
            fac = fit_factors([x for i, x in enumerate(train) if i % folds != k], c)
            for x in train[k::folds]:
                est = {m: v * _factor(fac, m, x.kind) for m, fn in RAW.items() if (v := fn(x, c))}
                if (r4 := raw_m4(x, idx)):
                    est["m4"] = r4[0]
                out.append((x, est))
        return out

    def score(cv, m):
        return _mdape([(e[m], official_value(x)) for x, e in cv if m in e])

    def combined_score(alpha: float) -> float:
        cv = cv_estimates(alpha)
        c = {**cal, "scores": {m: {"mdape": score(cv, m)} for m in METHODS}}
        return _mdape([(_combine(e, c), official_value(x)) for x, e in cv if e]) or 9

    # size elasticity: the one that makes the final (combined) estimate most accurate
    cal["alpha"] = min((0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35), key=combined_score)
    cv = cv_estimates(cal["alpha"])
    cal["factors"] = fit_factors(train, cal)
    cal["scores"] = {}
    for m in METHODS:
        p = [(e[m], official_value(x)) for x, e in cv if m in e]
        cal["scores"][m] = {
            "mdape": round(_mdape(p), 3) if p else None,
            "within_20pct": round(sum(abs(a / t - 1) <= 0.2 for a, t in p) / len(p), 3) if p else None,
            "n": len(p),
        }

    # combined estimate, scored the same way, and its error distribution
    resid: dict[str, list[float]] = {"many": [], "few": []}
    pairs = []
    for x, e in cv:
        if not e:
            continue
        mid = _combine(e, cal)
        t = official_value(x)
        pairs.append((mid, t))
        resid["many" if len(e) >= 3 else "few"].append(t / mid)
    cal["combined"] = {
        "mdape": round(_mdape(pairs), 3),
        "within_20pct": round(sum(abs(a / t - 1) <= 0.2 for a, t in pairs) / len(pairs), 3),
        "n": len(pairs),
    }
    # 80% prediction interval: the 10th-90th percentile of truth / estimate
    cal["interval"] = {
        b: {"q10": round(_quantile(r, 0.10), 3), "q90": round(_quantile(r, 0.90), 3), "n": len(r)}
        for b, r in resid.items() if len(r) >= 20
    }
    # full error distribution (truth / estimate at every 5th percentile): lets
    # the app answer "how likely is the property worth at least X?"
    cal["residual_quantiles"] = {
        b: [round(_quantile(r, q / 100), 4) for q in range(5, 100, 5)]
        for b, r in resid.items() if len(r) >= 20
    }
    # 50% interval (25th-75th percentile): the "likely" band used for ROE ranges
    cal["interval50"] = {
        b: {"q25": round(_quantile(r, 0.25), 3), "q75": round(_quantile(r, 0.75), 3), "n": len(r)}
        for b, r in resid.items() if len(r) >= 20
    }
    cal["n_official"] = len(train)
    return cal


def _combine(est: dict[str, float], cal: dict) -> float:
    """Weighted geometric mean, weight = 1 / MdAPE² (inverse-variance)."""
    def mdape(m: str) -> float:
        if m == OFFICIAL_METHOD:
            return OFFICIAL_ASSUMED_MDAPE
        return (cal["scores"].get(m) or {}).get("mdape") or 0.5

    w = {m: 1 / max(mdape(m), 0.05) ** 2 for m in est}
    if OFFICIAL_METHOD in est:
        # The public-data methods share inputs (city averages), so they are not
        # independent votes; a professional who inspected THIS property counts
        # three times as much as all of them together.
        models = sum(v for m, v in w.items() if m != OFFICIAL_METHOD)
        w[OFFICIAL_METHOD] = max(w[OFFICIAL_METHOD], OFFICIAL_WEIGHT_VS_MODELS * models)
    return math.exp(sum(w[m] * math.log(v) for m, v in est.items()) / sum(w.values()))


@lru_cache(maxsize=1)
def calibration() -> dict:
    return json.loads(CALIB_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------- reconciliation

def estimate(x: Listing, idx: dict, cal: dict | None = None) -> dict | None:
    cal = cal or calibration()
    if not group(x.kind) or not usable_area(x):
        return None
    est = {m: v * _factor(cal["factors"], m, x.kind) for m, fn in RAW.items() if (v := fn(x, cal))}
    m4 = raw_m4(x, idx)
    if m4:
        est["m4"] = m4[0]
    off = official_value(x)  # whole-property value, like the others
    if off:
        est[OFFICIAL_METHOD] = off
    if not est:
        return None
    share = ownership_share(x)
    est = {m: v * share for m, v in est.items()}  # value of the share being sold
    mid = _combine(est, cal)
    n_models = len([m for m in est if m != OFFICIAL_METHOD])
    band = cal["interval"].get("many" if n_models >= 3 else "few") or cal["interval"].get("many")
    lo, hi = mid * band["q10"], mid * band["q90"]
    b50 = (cal.get("interval50") or {}).get("many" if n_models >= 3 else "few") or {"q25": 0.75, "q75": 1.3}
    agree = max(est.values()) / min(est.values()) - 1
    conf = "alta" if len(est) >= 3 and agree <= 0.35 else "média" if len(est) >= 2 and agree <= 0.8 else "baixa"
    return {
        "lo": round(lo), "mid": round(mid), "hi": round(hi), "n": len(est), "conf": conf,
        # half of real appraisals fall inside lo50..hi50; ROE ranges use this band
        "lo50": round(mid * b50["q25"]), "hi50": round(mid * b50["q75"]),
        "methods": {m: round(v) for m, v in est.items()},
        "comps": m4[1] if m4 else 0,
        "share": share if share < 1 else None,
    }


def valuate_all(listings: list[Listing], history: Iterable[Listing] = ()) -> None:
    """Attach a valuation to every residential/commercial listing. Comparables
    come from this batch plus any extra listings passed in ``history``."""
    try:
        cal = calibration()
    except FileNotFoundError:
        return
    idx = comps_index(list(listings) + list(history))
    for x in listings:
        x.valuation = estimate(x, idx, cal)
        if x.valuation and x.current_price and x.current_price >= 1_000:
            pct = round(100 * x.current_price / x.valuation["mid"], 1)
            if pct < ATYPICAL_PCT:
                # Far below any plausible auction discount: almost always a
                # wrong area or an unmarked fraction. Flag, don't rank as a bargain.
                x.valuation["flag"] = "lance_atipico"
            else:
                x.price_to_valuation_pct = pct

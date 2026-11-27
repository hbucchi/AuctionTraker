"""Derive the fields the strategy filters need from what the scrapers found.

For each listing:

* ``kind``            normalized property type (casa, casa_condominio,
                      apartamento, comercial, terreno, rural, galpao, outros)
* ``modality_norm``   judicial / extrajudicial / venda_direta. Taken from the
                      site when it says so; otherwise inferred from the seller
                      (a court -> judicial; a bank or lender -> extrajudicial,
                      since banks auction properties repossessed under
                      alienação fiduciária, Lei 9.514/97).
* city statistics     population, GDP per capita, HDI, agribusiness share,
                      capital — joined from data/municipios.json by city + UF.
                      Names that don't match exactly ("Casa no Centro em São
                      Carlos", "Antônio da Platina") are recovered by
                      find_municipio(); the city is then renamed to IBGE's.
* ``market_value``    the auction's own appraisal (valor de avaliação) when
                      published; else the 1st round's minimum bid, which the
                      law sets at the appraisal; otherwise FipeZAP's average asking price per
                      m² in that city (by bedroom count when known; the
                      commercial index for commercial property) × the area.
                      Only FipeZAP's own 56 cities: a nearby city's price,
                      even adjusted, missed official appraisals by a median
                      195% in testing (see valuation.py), so it isn't used.
* ``price_to_market_pct``  current price as a % of that market value: her
                      rule "lance mínimo ≤ 50% do valor de mercado" is
                      price_to_market_pct ≤ 50.
"""

from __future__ import annotations

import hashlib
import json
import math
import difflib
import re
from functools import lru_cache
from pathlib import Path

from .models import Listing
from .parsing import parse_bedrooms, parse_occupied, strip_accents

DATA = Path(__file__).parent / "data"


def _norm(s: str) -> str:
    s = strip_accents(s).lower().replace("-", " ").replace("'", " ")
    return " ".join(s.split())


@lru_cache(maxsize=1)
def municipios() -> dict:
    data = json.loads((DATA / "municipios.json").read_text(encoding="utf-8"))
    data["by_key"] = {f"{_norm(m['name'])}|{m['uf']}": m for m in data["municipios"]}
    return data


@lru_cache(maxsize=1)
def fipezap() -> dict:
    return json.loads((DATA / "fipezap.json").read_text(encoding="utf-8"))


# ------------------------------------------------------- city matching ---

# "Casa no Jardim Alah em Açailândia", "Apartamento no Centro de São Carlos":
# some sites put the whole headline in the city field; the city is the tail.
_CITY_TAIL = re.compile(r"\b(?:em|de|do|da)\s+(.+)$")


@lru_cache(maxsize=1)
def _by_uf() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for m in municipios()["municipios"]:
        out.setdefault(m["uf"], {})[_norm(m["name"])] = m
    return out


@lru_cache(maxsize=8192)
def _find(city: str, uf: str) -> dict | None:
    names = _by_uf().get(uf) or {}
    n = _norm(city)
    if not n or n == _norm(uf):
        return None
    if n in names:
        return names[n]
    # the longest tail after "em/de/do/da" that is a municipality
    cand = n
    while (t := _CITY_TAIL.search(cand)):
        cand = t.group(1)
        if cand in names:
            return names[cand]
    # a dropped first word ("Antônio da Platina" for Santo Antônio da Platina)
    tails = [k for k in names if k.endswith(" " + n)]
    if len(tails) == 1:
        return names[tails[0]]
    # spelling variants ("Santana do Livramento" for Sant'Ana do Livramento)
    close = difflib.get_close_matches(n, names, n=1, cutoff=0.88)
    return names[close[0]] if close else None


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def find_municipio(city: str | None, uf: str | None, lat: float | None = None, lon: float | None = None) -> dict | None:
    """IBGE municipality for a scraped city name; failing that, the one
    nearest to the listing's own coordinates (within 30 km)."""
    if city and uf:
        m = municipios()["by_key"].get(f"{_norm(city)}|{uf}") or _find(city, uf)
        if m:
            return m
    if lat is not None and lon is not None:
        best = min((m for m in municipios()["municipios"] if m.get("lat") is not None),
                   key=lambda m: (m["lat"] - lat) ** 2 + (m["lon"] - lon) ** 2, default=None)
        if best and km(lat, lon, best["lat"], best["lon"]) <= 30:
            return best
    return None

# ------------------------------------------------------------------ kind ---

def classify_kind(x: Listing) -> str:
    t = _norm(f"{x.property_type or ''} {x.title or ''}")
    # titles that open with "Terreno"/"Lote" describe land, even "Terreno comercial"
    if re.match(r"(\(.*?\)\s*)?(\w+\s*\(\w\w\)\s*[-–]\s*)?(terreno|lote|gleba|area)\b", _norm(x.title or "")) \
            and not re.search(r"\b(casa|sobrado|galpao|predio)\b", t):
        return "terreno"
    if re.search(r"\b(apartamento|apto|apart|flat|cobertura|kitnet|kitinete|studio|loft)\b", t):
        return "apartamento"
    if re.search(r"\b(casa|sobrado|residencia|bangalo)\b", t):
        if re.search(r"\bcondominio\b", t):
            return "casa_condominio"
        return "casa"
    if re.search(r"\b(galpao|armazem|deposito|barracao|industrial)\b", t):
        return "galpao"
    if re.search(r"\b(sala|salas|loja|lojas|comercial|predio|escritorio|consultorio|hotel|posto)\b", t):
        return "comercial"
    if re.search(r"\b(fazenda|sitio|chacara|rural|gleba|haras)\b", t):
        return "rural"
    if re.search(r"\b(terreno|terrenos|lote|lotes|area)\b", t):
        return "terreno"
    return "outros"


# ------------------------------------------------------------- modality ---

_COURT = re.compile(r"\b(tribunal|vara|justica|juizo|forum|tj[a-z]{2}|trt|trf|falencia|recuperacao judicial)\b")
_LENDER = re.compile(
    r"\b(banco|bank|caixa|itau|bradesco|santander|sicoob|sicredi|cooperativa|cresol|unicred|"
    r"daycoval|inter|btg|safra|poupex|financeira|credito|securitizadora|consorcio|rodobens|bv)\b"
)


def classify_modality(x: Listing) -> str | None:
    m = _norm(x.modality or "")
    if "extrajudicial" in m or "alienacao fiduciaria" in m or "particular" in m:
        return "extrajudicial"
    if "judicial" in m:
        return "judicial"
    if "venda direta" in m or "venda online" in m:
        return "venda_direta"
    who = _norm(f"{x.seller or ''} {x.title or ''}")
    if _COURT.search(who):
        return "judicial"
    if _LENDER.search(_norm(x.seller or "")):
        return "extrajudicial"
    return None


# ---------------------------------------------------------- market value ---

def fipezap_price_m2(x: Listing) -> tuple[float, str] | None:
    fz = fipezap()
    if not x.city or not x.state:
        return None
    c = fz["cities"].get(f"{_norm(x.city)}|{x.state}")
    if not c:
        return None
    if x.kind in ("comercial", "galpao") and c.get("commercial"):
        return c["commercial"], f"FipeZAP comercial {c['city']} {fz['month']}"
    if x.kind in ("casa", "casa_condominio", "apartamento"):
        k = f"residential_{min(x.bedrooms, 4)}d" if x.bedrooms else "residential"
        v = c.get(k) or c.get("residential")
        if v:
            label = f"{min(x.bedrooms, 4)}{'+' if x.bedrooms and x.bedrooms >= 4 else ''} quartos " if x.bedrooms else ""
            return v, f"FipeZAP {label}{c['city']} {fz['month']}".replace("  ", " ")
    return None


def first_round_value(x: Listing) -> float | None:
    """In two-round auctions the 1st round's minimum bid is legally the
    appraisal: CPC art. 891 for judicial auctions, Lei 9.514/97 art. 27 for
    extrajudicial ones (alienação fiduciária)."""
    if len(x.rounds) < 2:
        return None
    first = next((r for r in x.rounds if r.number == 1 and r.min_bid), None)
    if first and x.current_price and first.min_bid > x.current_price:
        return first.min_bid
    return None


def estimate_market_value(x: Listing) -> None:
    first = first_round_value(x)
    if x.appraisal_value and x.appraisal_value > 0:
        x.market_value = x.appraisal_value
        x.market_value_source = "avaliação do leilão"
    elif first:
        x.market_value = first
        x.market_value_source = "1º leilão (= avaliação)"
    elif x.area_m2 and 10 <= x.area_m2 <= (5_000 if x.kind in ("casa", "casa_condominio", "apartamento") else 50_000):
        pm2 = fipezap_price_m2(x)
        if pm2:
            x.market_value = round(pm2[0] * x.area_m2, 2)
            x.market_value_source = pm2[1]
    # prices under R$ 1 000 are placeholders ("faça sua proposta", R$ 0,01)
    # "parte ideal de 60%": the lot is a share of the property
    share = re.search(r"parte ideal (?:de|correspondente a)?\s*(\d{1,2}(?:[.,]\d+)?)\s*%", _norm(x.title or ""))
    if share and x.market_value and x.market_value_source and x.market_value_source.startswith("FipeZAP"):
        pct = float(share.group(1).replace(",", "."))
        x.market_value = round(x.market_value * pct / 100, 2)
        x.market_value_source += f" × parte ideal {pct:g}%"
    if x.market_value and x.current_price and x.current_price >= 1_000:
        x.price_to_market_pct = round(100 * x.current_price / x.market_value, 1)


# ----------------------------------------------------------------- main ---

def enrich(x: Listing) -> Listing:
    if x.bedrooms is None:
        x.bedrooms = parse_bedrooms(x.title)
    x.kind = classify_kind(x)
    if x.occupied is None:
        occ = str((x.extra or {}).get("occupancy") or "")  # Superbid's structured field
        x.occupied = parse_occupied(occ) if occ else parse_occupied(x.title)
    x.modality_norm = classify_modality(x)
    ex = x.extra or {}
    m = find_municipio(x.city, x.state, ex.get("lat"), ex.get("lon"))
    if m:
        if _norm(x.city or "") != _norm(m["name"]) or x.state != m["uf"]:
            x.city, x.state = m["name"], m["uf"]  # IBGE's spelling, so later lookups match
        x.city_population = m.get("population")
        x.city_gdp_per_capita = m.get("gdp_per_capita")
        x.city_idhm = m.get("idhm")
        x.city_agro_share = m.get("agro_share")
        x.city_capital = m.get("capital")
    estimate_market_value(x)
    place(x)
    return x


def place(x: Listing) -> None:
    """Coordinates for the map: the site's own (Superbid), else the
    municipality's center with a small fixed offset per listing so pins in
    the same city don't stack (geocode.py can replace these with street-level
    positions when a Google Geocoding key is configured)."""
    if x.lat is not None and x.lon is not None:
        return
    ex = x.extra or {}
    if ex.get("lat") is not None and ex.get("lon") is not None:
        x.lat, x.lon, x.geo = float(ex["lat"]), float(ex["lon"]), "exato"
        return
    if x.city and x.state:
        m = municipios()["by_key"].get(f"{_norm(x.city)}|{x.state}")
        if m and m.get("lat") is not None:
            h = int(hashlib.md5(x.id.encode()).hexdigest()[:8], 16)
            angle, radius = (h % 360) * math.pi / 180, 0.004 + (h >> 9) % 100 / 100 * 0.016  # 0.4-2 km
            x.lat = round(m["lat"] + radius * math.sin(angle), 5)
            x.lon = round(m["lon"] + radius * math.cos(angle), 5)
            x.geo = "cidade"


def national_gdp_per_capita() -> int:
    return municipios()["national_gdp_per_capita"]

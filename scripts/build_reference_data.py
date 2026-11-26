"""Build the reference data the strategy filters use, from official sources.

    python scripts/build_reference_data.py            # everything
    python scripts/build_reference_data.py --fipezap  # only the monthly price index

Outputs (committed to the repo, small JSON files):

auction_tracker/data/municipios.json  one row per municipality (5 570):
    population      IBGE Census 2022 (SIDRA table 4709)
    gdp_per_capita  municipal GDP / population, R$ (SIDRA table 5938, latest year)
    agro_share      share of the municipality's value added that comes from
                    agriculture & livestock, % (same table) — "força no agronegócio"
    idhm            Municipal Human Development Index, PNUD Atlas 2010 (latest
                    municipal edition), via the IBGE Cidades API
    capital         state capital or Brasília

auction_tracker/data/fipezap.json  latest FipeZAP average asking price, R$/m²,
    per city (56 cities): residential overall and by bedrooms (1-4+), commercial.

Refresh FipeZAP monthly; IBGE data changes yearly at most.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "auction_tracker" / "data"
SIDRA = "https://apisidra.ibge.gov.br/values"
IBGE = "https://servicodados.ibge.gov.br/api/v1"
FIPEZAP_XLSX = "https://downloads.fipe.org.br/indices/fipezap/fipezap-serieshistoricas.xlsx"

CAPITALS = {
    "AC": "Rio Branco", "AL": "Maceió", "AM": "Manaus", "AP": "Macapá", "BA": "Salvador",
    "CE": "Fortaleza", "DF": "Brasília", "ES": "Vitória", "GO": "Goiânia", "MA": "São Luís",
    "MG": "Belo Horizonte", "MS": "Campo Grande", "MT": "Cuiabá", "PA": "Belém", "PB": "João Pessoa",
    "PE": "Recife", "PI": "Teresina", "PR": "Curitiba", "RJ": "Rio de Janeiro", "RN": "Natal",
    "RO": "Porto Velho", "RR": "Boa Vista", "RS": "Porto Alegre", "SC": "Florianópolis",
    "SE": "Aracaju", "SP": "São Paulo", "TO": "Palmas",
}
# FipeZAP sheet names are city names; a few are ambiguous across states.
FIPEZAP_UF = {
    "São Paulo": "SP", "Barueri": "SP", "Campinas": "SP", "Diadema": "SP", "Guarujá": "SP",
    "Guarulhos": "SP", "Osasco": "SP", "Praia Grande": "SP", "Ribeirão Preto": "SP",
    "Santo André": "SP", "Santos": "SP", "São Bernardo do Campo": "SP", "São Caetano do Sul": "SP",
    "São José do Rio Preto": "SP", "São José dos Campos": "SP", "São Vicente": "SP",
    "Rio de Janeiro": "RJ", "Niterói": "RJ", "Belo Horizonte": "MG", "Betim": "MG", "Contagem": "MG",
    "Porto Alegre": "RS", "Canoas": "RS", "Caxias do Sul": "RS", "Novo Hamburgo": "RS",
    "Pelotas": "RS", "Santa Maria": "RS", "São Leopoldo": "RS", "Curitiba": "PR", "Londrina": "PR",
    "São José dos Pinhais": "PR", "Florianópolis": "SC", "Balneário Camboriú": "SC",
    "Blumenau": "SC", "Itajaí": "SC", "Itapema": "SC", "Joinville": "SC", "São José": "SC",
    "Vitória": "ES", "Vila Velha": "ES", "Brasília": "DF", "Goiânia": "GO", "Campo Grande": "MS",
    "Cuiabá": "MT", "Aracaju": "SE", "Fortaleza": "CE", "João Pessoa": "PB", "Maceió": "AL",
    "Natal": "RN", "Recife": "PE", "Salvador": "BA", "São Luís": "MA", "Teresina": "PI",
    "Jaboatão dos Guararapes": "PE", "Belém": "PA", "Manaus": "AM",
}


def norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().replace("-", " ").replace("'", " ").split())


def city_key(name: str, uf: str) -> str:
    return f"{norm(name)}|{uf.upper()}"


def get(url: str, **kw):
    r = requests.get(url, timeout=240, headers={"User-Agent": "auction-tracker/1.0"}, **kw)
    r.raise_for_status()
    return r


def sidra(path: str) -> list[dict]:
    rows = get(f"{SIDRA}/{path}").json()
    return rows[1:]  # first row is the header legend


def build_municipios() -> dict:
    muns = get(f"{IBGE}/localidades/municipios").json()
    pop = {r["D1C"]: int(r["V"]) for r in sidra("t/4709/n6/all/v/93/p/last") if r["V"].isdigit()}
    gdp_rows = sidra("t/5938/n6/all/v/37/p/last")
    gdp_year = gdp_rows[0]["D3N"]
    gdp: dict[str, dict[str, float]] = {}
    for r in gdp_rows:
        try:
            gdp.setdefault(r["D1C"], {})["37"] = float(r["V"]) * 1000  # SIDRA gives thousands of R$
        except ValueError:
            continue
    # The sector breakdown (value added: total 498, agriculture 513) is often
    # published a year after the GDP total ("..." until then), so take the
    # most recent of the last 3 years that has numbers.
    va_year: dict[str, str] = {}
    for r in sidra("t/5938/n6/all/v/498,513/p/last%203"):
        try:
            v = float(r["V"]) * 1000
        except ValueError:
            continue
        code, year = r["D1C"], r["D3N"]
        if year >= va_year.get(code + r["D2C"], ""):
            va_year[code + r["D2C"]] = year
            gdp.setdefault(code, {})[r["D2C"]] = v
    agro_year = max(va_year.values()) if va_year else None
    idhm_raw = get(f"{IBGE}/pesquisas/10111/indicadores/329756/resultados/xxxxxx").json()[0]["res"]
    idhm = {}
    for r in idhm_raw:
        v = (r.get("res") or {}).get("2010")
        if v not in (None, "", "-"):
            idhm[r["localidade"]] = float(v)  # 6-digit code (no check digit)

    out = []
    for m in muns:
        code = str(m["id"])
        uf = m["microrregiao"]["mesorregiao"]["UF"]["sigla"] if m.get("microrregiao") else m["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]
        p = pop.get(code)
        g = gdp.get(code, {})
        row = {
            "code": int(code),
            "name": m["nome"],
            "uf": uf,
            "population": p,
            "gdp_per_capita": round(g["37"] / p) if p and g.get("37") else None,
            "agro_share": round(100 * g["513"] / g["498"], 1) if g.get("498") and g.get("513") is not None else None,
            "idhm": idhm.get(code[:6]),
            "capital": CAPITALS.get(uf) == m["nome"],
        }
        out.append(row)

    tot_gdp = sum(gdp.get(str(m["code"]), {}).get("37", 0) for m in out)
    tot_pop = sum(m["population"] or 0 for m in out)
    return {
        "sources": {
            "population": "IBGE Censo 2022 (SIDRA 4709)",
            "gdp": f"IBGE PIB dos Municípios {gdp_year} (SIDRA 5938)",
            "agro_share": f"IBGE PIB dos Municípios {agro_year}, valor adicionado da agropecuária (SIDRA 5938)",
            "idhm": "PNUD Atlas do Desenvolvimento Humano 2010 (via IBGE Cidades)",
        },
        "gdp_year": int(gdp_year),
        "national_gdp_per_capita": round(tot_gdp / tot_pop),
        "built": date.today().isoformat(),
        "municipios": out,
    }


def build_fipezap() -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(get(FIPEZAP_XLSX).content), read_only=True, data_only=True)
    cities = {}
    month = None
    for name, uf in FIPEZAP_UF.items():
        if name not in wb.sheetnames:
            print(f"warning: FipeZAP has no sheet for {name}", file=sys.stderr)
            continue
        rows = list(wb[name].iter_rows(values_only=True))
        header = rows[2]  # metric names
        sale_res = header.index("Preço médio (R$/m²)")                     # residential sale block
        sale_com = [i for i, c in enumerate(header) if c == "Preço médio (R$/m²)"][2]  # commercial sale
        latest = {}
        for r in rows[4:]:
            if r[1] is None or not hasattr(r[1], "year"):
                continue
            vals = {
                "residential": r[sale_res], "residential_1d": r[sale_res + 1], "residential_2d": r[sale_res + 2],
                "residential_3d": r[sale_res + 3], "residential_4d": r[sale_res + 4], "commercial": r[sale_com],
            }
            vals = {k: round(v) for k, v in vals.items() if isinstance(v, (int, float))}
            if vals.get("residential"):
                latest = vals
                month = max(month or r[1], r[1])
        if latest:
            cities[city_key(name, uf)] = {"city": name, "uf": uf, **latest}
    return {
        "source": "Índice FipeZAP — preço médio de anúncios de venda (R$/m²)",
        "month": month.strftime("%Y-%m") if month else None,
        "built": date.today().isoformat(),
        "cities": cities,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fipezap", action="store_true", help="only refresh the FipeZAP prices")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.fipezap:
        m = build_municipios()
        (OUT / "municipios.json").write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")))
        print(f"municipios.json: {len(m['municipios'])} rows, national GDP per capita R$ {m['national_gdp_per_capita']}")
        # the web app and the alert job read reference values from the strategy spec
        spec_path = ROOT / "web" / "strategy-fields.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        spec["reference"] = {
            "national_gdp_per_capita": m["national_gdp_per_capita"],
            "gdp_year": m["gdp_year"],
            "source": m["sources"]["gdp"],
        }
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    f = build_fipezap()
    (OUT / "fipezap.json").write_text(json.dumps(f, ensure_ascii=False, indent=1))
    print(f"fipezap.json: {len(f['cities'])} cities, month {f['month']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

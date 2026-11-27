"""Risk factors ("pontos de atenção") of an auction lot: a published points
table, not a model. Every point comes with the fact behind it, and missing
information counts as risk: most lots never say whether they are occupied,
and "unknown" is not "fine".

The JavaScript twin is web/risk.js; both are checked against
tests/risk_cases.json. The web app also passes the user's checklist, which
can clear "unknown" points once the user has verified them (or add points
when a lawsuit was found); the alert job has no checklists.

Levels: 0-2 "poucos", 3-5 "atenção", 6+ "muitos" pontos de atenção.
"""

from __future__ import annotations

import re
from typing import Any

SHARE = re.compile(r"parte ideal|fra[cç][aã]o ideal|^\s*\(\s*\d{1,2}(?:[.,]\d+)?\s*%\s*\)", re.I)

TEXT = {
    "occ": "Imóvel ocupado: desocupação leva meses e tem custo",
    "occ_unknown": "Ocupação não informada: confira no edital e visite",
    "debts": "Dívidas de condomínio/IPTU ficam com o arrematante",
    "debts_unknown": "Não informado quem paga condomínio/IPTU atrasados",
    "judicial": "Leilão judicial: prazos do processo e risco de recurso",
    "modality_unknown": "Tipo de leilão não identificado",
    "share": "Venda de fração do imóvel (parte ideal), não do imóvel inteiro",
    "atypical": "Lance muito abaixo do valor estimado: confira área e fração",
    "no_value": "Sem estimativa de valor para comparar",
    "low_conf": "Estimativa de valor com confiança baixa",
    "lawsuit": "Você encontrou ação judicial ligada ao imóvel",
}


def level(points: int) -> str:
    return "low" if points <= 2 else "mid" if points <= 5 else "high"


def risk(item: dict[str, Any], checklist: dict[str, Any] | None = None) -> dict[str, Any]:
    ck = checklist or {}
    f: list[dict[str, Any]] = []

    def add(key: str, pts: int) -> None:
        f.append({"key": key, "pts": pts, "text": TEXT[key]})

    occ = item.get("occ")
    if occ is True:
        add("occ", 3)
    elif occ is None and not ck.get("occupancy"):
        add("occ_unknown", 2)
    debts = item.get("debts")
    if debts is True:
        add("debts", 2)
    elif debts is None and not ck.get("debts"):
        add("debts_unknown", 1)
    modn = item.get("modn")
    if modn == "judicial":
        add("judicial", 1)
    elif not modn:
        add("modality_unknown", 1)
    if SHARE.search(item.get("title") or ""):
        add("share", 2)
    val = item.get("val")
    if val and val.get("flag"):
        add("atypical", 2)
    elif not val:
        add("no_value", 1)
    elif val.get("conf") == "baixa":
        add("low_conf", 1)
    if ck.get("lawsuits_result") == "found":
        add("lawsuit", 3)
    points = sum(x["pts"] for x in f)
    return {"points": points, "level": level(points), "factors": f}

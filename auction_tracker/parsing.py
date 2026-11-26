"""Small, well-tested helpers for the messy text found on Brazilian sites."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

STATE_NAMES = {
    "acre": "AC", "alagoas": "AL", "amazonas": "AM", "amapa": "AP", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "minas gerais": "MG", "mato grosso do sul": "MS",
    "mato grosso": "MT", "para": "PA", "paraiba": "PB", "pernambuco": "PE",
    "piaui": "PI", "parana": "PR", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rondonia": "RO", "roraima": "RR",
    "rio grande do sul": "RS", "santa catarina": "SC", "sergipe": "SE",
    "sao paulo": "SP", "tocantins": "TO",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clean(s: str | None) -> str | None:
    """Collapse whitespace; return None for empty strings."""
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_brl(text: str | None) -> float | None:
    """'R$ 1.234.567,89' -> 1234567.89 ; also accepts '187538,77' and '1,290,000.00'."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"\d[\d.,]*", str(text))
    if not m:
        return None
    num = m.group(0).rstrip(".,")
    if "," in num and "." in num:
        # whichever separator comes last is the decimal one
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".") if re.search(r",\d{1,2}$", num) else num.replace(",", "")
    elif num.count(".") > 1 or re.search(r"\.\d{3}$", num):
        num = num.replace(".", "")  # thousands separators only
    try:
        return float(num)
    except ValueError:
        return None


def parse_area(text: str | None) -> float | None:
    """'47,60m² construída' -> 47.6 ; '1.005m²' -> 1005.0"""
    if not text:
        return None
    m = re.search(r"(\d[\d.,]*)\s*m(?:²|2)", text)
    return parse_brl(m.group(1)) if m else None


_DATE_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})(?:\s*(?:às|as|-)?\s*(\d{1,2})[:h](\d{2}))?", re.IGNORECASE
)


def parse_br_datetime(text: str | None) -> str | None:
    """'27/11/2026 às 10:00' / '30/09/2026 às 10h00' -> '2026-11-27T10:00:00-03:00'.

    Brazil abolished daylight saving in 2019, so São Paulo time is a fixed
    UTC-03:00 offset and we can write it directly without a tz database.
    """
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y, hh, mm = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0))
    except ValueError:
        return None
    return dt.isoformat() + "-03:00"


def iso_from_sql(text: str | None) -> str | None:
    """'2026-11-30 11:08:00' (São Paulo local) -> '2026-11-30T11:08:00-03:00'."""
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").isoformat() + "-03:00"
    except ValueError:
        return None


def split_city_uf(text: str | None) -> tuple[str | None, str | None]:
    """'Sete Lagoas / MG', 'Itatiba (SP)', 'Nova Iguaçu - RJ', 'Centro - Rio de Janeiro/RJ'
    -> (city, UF). Returns (None, None) when no UF is recognizable."""
    if not text:
        return None, None
    t = clean(text) or ""
    m = re.search(r"([^/\-–(),|]+?)\s*(?:/|-|–|\()\s*([A-Z]{2})\)?\s*$", t)
    if m and m.group(2) in UFS:
        return clean(m.group(1)), m.group(2)
    m = re.search(r"([A-Za-zÀ-ú' .]+?)\s*/\s*([A-Z]{2})\b", t)
    if m and m.group(2) in UFS:
        return clean(m.group(1)), m.group(2)
    m = re.search(r"([^,]+),\s*([A-Z]{2})\s*$", t)  # "Apartamento em Pirajá, Salvador, BA"
    if m and m.group(2) in UFS:
        return clean(m.group(1)), m.group(2)
    return None, None


def state_to_uf(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip()
    if n.upper() in UFS:
        return n.upper()
    return STATE_NAMES.get(strip_accents(n).lower())


def guess_category(text: str | None) -> str:
    """Coarse bucket from free text: imovel / veiculo / outros."""
    t = strip_accents((text or "").lower())
    if re.search(
        r"\b(imove(l|is)|casa|apartamento|apto|terreno|sala|loja|galpao|predio|sobrado|chacara|"
        r"sitio|fazenda|lote|area|gleba|comercial|residencial|rural|vaga de garagem|box)\b",
        t,
    ):
        return "imovel"
    if re.search(r"\b(veiculo|carro|moto|caminhao|onibus|trator|kombi|automovel|van)\b", t):
        return "veiculo"
    return "outros"


PROPERTY_TYPES = [
    ("Apartamento", r"\b(apartamento|apto|flat|cobertura|kitnet|studio)\b"),
    ("Casa", r"\b(casa|sobrado)\b"),
    ("Terreno", r"\b(terreno|lote|gleba|area de terra)\b"),
    ("Rural", r"\b(fazenda|sitio|chacara|rural)\b"),
    ("Galpão", r"\b(galpao|armazem|deposito|industrial)\b"),
    ("Comercial", r"\b(sala|loja|comercial|predio|conjunto comercial|escritorio)\b"),
    ("Vaga de garagem", r"\b(vaga de garagem|box)\b"),
]


def guess_property_type(text: str | None) -> str | None:
    t = strip_accents((text or "").lower())
    for name, pattern in PROPERTY_TYPES:
        if re.search(pattern, t):
            return name
    return None

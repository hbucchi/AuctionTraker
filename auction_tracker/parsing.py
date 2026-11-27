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
    if not m:
        return None
    num = m.group(1).rstrip(".,")
    if "," in num:
        # comma present: it is the decimal separator (registries use up to 4
        # decimals, "25,9531 m²"); dots group thousands
        num = num.replace(".", "").replace(",", ".")
    elif num.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", num):
        num = num.replace(".", "")  # "1.005" / "12.500.000": thousands
    # else a single dot with 1, 2 or 4 decimals is a decimal point: "30.83"
    try:
        return float(num)
    except ValueError:
        return None


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


_NUM_WORDS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6}
_BEDROOMS_RE = re.compile(
    r"\b(\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|seis)\s*(?:\(\w+\)\s*)?"
    r"(?:dormitorios?|quartos?|dorms?\b|qtos?\b|qts?\b|suites?)",
)


def parse_bedrooms(text: str | None) -> int | None:
    """'Apto 3 dormitórios', 'casa com três quartos', '2 dorms' -> count.
    Suites count as bedrooms; when several numbers appear (e.g. '3 quartos,
    sendo 1 suíte') the largest is the bedroom total."""
    if not text:
        return None
    t = strip_accents(text.lower())
    found = []
    for m in _BEDROOMS_RE.finditer(t):
        n = m.group(1)
        v = int(n) if n.isdigit() else _NUM_WORDS.get(n)
        if v and 0 < v < 20:
            found.append(v)
    return max(found) if found else None


_BUYER = r"(arrematante|comprador|adquirente|proponente vencedor)"
_DEBTS = r"(condom[ií]nio|iptu|d[eé]bitos?|d[ií]vidas?|tributos?|taxas?)"
_BUYER_PAYS = [
    re.compile(_DEBTS + r"[^.;]{0,160}(por conta|a cargo|de responsabilidade|sob responsabilidade|ser[aã]o? pag[oa]s? pelo)\s+(do|da|pelo)?\s*" + _BUYER),
    re.compile(_BUYER + r"[^.;]{0,80}(arcar[aá]?|responsabiliza|respons[aá]vel|pagar[aá]?|quitar)[^.;]{0,80}" + _DEBTS),
]
_SELLER_PAYS = [
    re.compile(r"livres? e desembara[cç]ad[oa]s?|livres? de (quaisquer )?(d[eé]bitos|[oô]nus|d[ií]vidas)"),
    re.compile(_DEBTS + r"[^.;]{0,160}(por conta|a cargo|de responsabilidade)\s+(do|da)\s+(vendedor|comitente|banco|credor|alienante)"),
]


# texts are accent-stripped before matching, so the patterns must be too
_BUYER_PAYS_ASCII = [re.compile(strip_accents(p.pattern)) for p in _BUYER_PAYS]
_SELLER_PAYS_ASCII = [re.compile(strip_accents(p.pattern)) for p in _SELLER_PAYS]


def debts_on_buyer(text: str | None) -> bool | None:
    """Read a listing/edital text and decide whether condominium/IPTU debts
    stay with the buyer. True = buyer pays, False = seller pays / delivered
    free of debts, None = text doesn't say. A heuristic: always confirm in the
    edital before bidding."""
    if not text:
        return None
    t = strip_accents(text.lower())
    buyer = any(r.search(t) for r in _BUYER_PAYS_ASCII)
    seller = any(r.search(t) for r in _SELLER_PAYS_ASCII)
    if buyer and not seller:
        return True
    if seller and not buyer:
        return False
    return None


_AREA_RE = re.compile(r"(\d[\d.,]*)\s*m(?:²|2)\b")
_LOT_CTX = re.compile(r"(terreno|lote|area total|area do terreno|gleba|fracao ideal|area de terra|\ba\.?\s?t\.?)\W*(?:de|com|medindo)?\W*$")
_BUILT_CTX = re.compile(r"(constru\w*|privativ\w*|util|edificad\w*|area real|a\.?\s?p\.?|a\.?\s?c\.?)\W*(?:de|com)?\W*$")


def parse_areas(text: str | None) -> tuple[float | None, float | None]:
    """Split the areas mentioned in a title into (built, lot).

    'Casa 251m² com Terreno 280m²' -> (251, 280); 'Casa com área total de
    886m²' -> (None, 886); 'Apto 3 dorms 70m² privativos' -> (70, None).
    An area with no qualifier counts as built, the usual way titles are written."""
    if not text:
        return None, None
    t = strip_accents(text.lower())
    built = lot = None
    for m in _AREA_RE.finditer(t):
        value = parse_area(m.group(0))
        before = t[max(0, m.start() - 30): m.start()]
        after = t[m.end(): m.end() + 20]
        if _LOT_CTX.search(before) or re.match(r"\W*(de\s+)?(terreno|lote)", after):
            lot = lot or value
        elif _BUILT_CTX.search(before) or re.match(r"\W*(de\s+)?(area\s+)?(constru|privativ|util)", after) or built is None:
            built = built or value
    return built, lot


_SHARE_RES = [
    re.compile(r"^\W*\(\s*(\d{1,3}(?:[.,]\d+)?)\s*%"),                                  # "(25%) Casa..." (Superbid)
    re.compile(r"\(\s*(\d{1,3}(?:[.,]\d+)?)\s*%\s*-?\s*parte ideal"),                   # "(12,5% - Parte Ideal)"
    re.compile(r"(?:parte|fracao) ideal (?:de |correspondente a |equivalente a )?(\d{1,3}(?:[.,]\d+)?)\s*%"),
    re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*% (?:da|de|do) (?:parte|fracao) ideal"),
]


def parse_share(text: str | None) -> float | None:
    """Fraction of the property being sold: '(25%) Casa' -> 0.25,
    'parte ideal de 60%' -> 0.6. None when the whole property is sold."""
    if not text:
        return None
    t = strip_accents(text.lower())
    for r in _SHARE_RES:
        m = r.search(t)
        if m:
            v = float(m.group(1).replace(",", ".")) / 100
            if 0 < v < 1:
                return v
    return None


def parse_occupied(text: str | None) -> bool | None:
    """'DESOCUPADO', 'imóvel vago' -> False; 'Imóvel ocupado' -> True; else None."""
    if not text:
        return None
    t = strip_accents(text.lower())
    if re.search(r"\b(desocupad[oa]s?|vago|vazio|livre de ocupa|livre e desocupad)", t):
        return False
    if re.search(r"\bocupad[oa]s?\b", t):
        return True
    return None

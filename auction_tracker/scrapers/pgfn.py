"""Comprei (PGFN — Procuradoria-Geral da Fazenda Nacional) — https://comprei.pgfn.gov.br

Federal government direct-sale platform for assets seized in tax-debt cases.
Not a classic auction: assets are sold at a fixed price (often a discount on
the appraisal) through accredited brokers.

How the site works (verified 2026-11-26):
* React SPA. Its public search page calls an anonymous JSON endpoint:
  GET /gateway/anuncio/publico?ufs[0]=<id>&ufs[1]=<id>...&page=P&size=S&sort=1
  (Spring pageable response: content / totalElements / last).
* ``ufs`` are numeric ids from GET /gateway/sdc/uf, not letter codes — sending
  "SP" returns HTTP 500. At least one UF is required.
* Images: /gateway/imagem/anuncio/<imageId>. Public page: /anuncio/detalhe/<id>.
* The ``descricao`` field contains broker contact details; we don't store it.
"""

from __future__ import annotations

from typing import Any, Iterator

from ..models import Listing
from ..parsing import clean, guess_category, guess_property_type, split_city_uf
from .base import BaseScraper

BASE = "https://comprei.pgfn.gov.br"
API = f"{BASE}/gateway"

SITUACAO = {1: "aguardando", 2: "aberto", 3: "em negociação", 4: "vendido"}


def item_to_listing(x: dict[str, Any]) -> Listing:
    addr = clean(x.get("endereco"))
    city, uf = split_city_uf(addr)
    neighborhood = None
    if addr and " - " in addr:
        head = addr.rsplit(" - ", 1)[0]
        neighborhood = clean(head.rsplit(",", 1)[-1])
    title = clean((x.get("titulo") or "").strip("-_ ")) or f"Anúncio {x['id']}"
    imgs = x.get("imagensAnuncio") or []
    return Listing(
        source="pgfn",
        source_id=str(x["id"]),
        url=f"{BASE}/anuncio/detalhe/{x['id']}",
        title=title[:300],
        category=guess_category(title) if guess_category(title) != "outros" else "outros",
        property_type=clean(x.get("tipoImovel")) or guess_property_type(title),
        modality="venda direta",
        status="vendido" if x.get("bemVendido") else SITUACAO.get(x.get("situacaoAnuncio"), None),
        seller=clean(x.get("tituloCredor")),
        address=addr,
        neighborhood=neighborhood,
        city=city,
        state=uf,
        appraisal_value=x.get("valorAvaliacao"),
        current_price=x.get("precoAtual"),
        discount_pct=x.get("desconto"),
        end_date=_br_to_iso(x.get("prazoParaEncerramento")),
        image_url=f"{API}/imagem/anuncio/{imgs[0]}" if imgs else None,
        bids_count=x.get("qtdPropostas"),
        extra={
            "asset_id": x.get("idBem"),
            "registry_number": x.get("matriculaBem"),
            "countdown": clean(x.get("textoContador")),
            "creditor_unit": x.get("siglaCredor"),
        },
    )


def _br_to_iso(s: str | None) -> str | None:
    # "31/01/2027 00:00:00" -> "2027-01-31T00:00:00-03:00"
    if not s or len(s) < 10:
        return None
    d, m, y = s[:10].split("/")
    t = s[11:19] if len(s) >= 19 else "00:00:00"
    return f"{y}-{m}-{d}T{t}-03:00"


class PgfnScraper(BaseScraper):
    name = "pgfn"
    base_url = BASE
    expected_min_listings = 100
    page_size = 100
    max_pages = 50
    # The gov.br server only negotiates RSA key-exchange suites, which Python
    # leaves out by default (curl/browsers still offer them). Verification stays on.
    extra_ciphers = "AES256-GCM-SHA384:AES128-GCM-SHA256"

    def scrape(self) -> Iterator[Listing]:
        ufs = self.get(f"{API}/sdc/uf", headers={"Accept": "application/json"}).json()
        params: list[tuple[str, Any]] = [(f"ufs[{i}]", u["value"]) for i, u in enumerate(ufs)]
        params += [("disponivelProposta", "false"), ("size", self.page_size), ("sort", "1")]
        for page in range(self.max_pages):
            data = self.get(
                f"{API}/anuncio/publico",
                params=params + [("page", page)],
                headers={"Accept": "application/json", "Referer": f"{BASE}/"},
            ).json()
            if page == 0:
                self.reported_total = data.get("totalElements")
                self.log.info("site reports %s offers", self.reported_total)
            for x in data.get("content") or []:
                yield item_to_listing(x)
            if data.get("last", True):
                break

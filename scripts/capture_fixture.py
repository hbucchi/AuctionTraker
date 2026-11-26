"""Capture a small, privacy-safe test fixture for one site.

    python scripts/capture_fixture.py zuk            # fetch live, trim, save
    python scripts/capture_fixture.py zuk --from raw.html   # trim an existing file

Fixtures are deliberately tiny (a few cards) and stripped of free-text
descriptions, which on these sites can contain personal data (debtor names,
CPF numbers, broker phones). Output: tests/fixtures/<site>.<ext>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_tracker.scrapers import REGISTRY  # noqa: E402
from auction_tracker.scrapers import pgfn as pgfn_mod  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
N = 4  # cards per fixture


def _wrap(fragments: list[str], header: str = "") -> str:
    return "<html><body>\n" + header + "\n" + "\n".join(fragments) + "\n</body></html>\n"


def trim_zuk(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    header = soup.select_one("p.list-header-opportunities")
    cards = soup.select("div.card-property.card_lotes_div")[:N]
    return _wrap([str(c) for c in cards], str(header) if header else "")


def trim_blueintra(html: str, card_sel: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("#leilao-lista-lote")
    attrs = " ".join(f'{k}="{v}"' for k, v in (root.attrs.items() if root else []) if k in ("id", "total", "limit", "index"))
    cards = soup.select(card_sel)[:N]
    return _wrap([f"<div {attrs}>"] + [str(c) for c in cards] + ["</div>"])


def trim_alfa(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return _wrap([str(c) for c in soup.select("div.home-leiloes-cards")[:N]])


def trim_superbid(html: str) -> str:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    ol = data["props"]["pageProps"]["offersList"]
    offers = ol["offers"][:N]
    for o in offers:
        p = o.get("product") or {}
        text = BeautifulSoup(p.get("detailedDescription") or "", "lxml").get_text(" ")
        am = re.search(r"valor\s+de\s+avalia[çc][ãa]o\s*:?\s*R\$\s*[\d.,]+", text, re.I)
        p["detailedDescription"] = f"<p>{am.group(0)}</p>" if am else ""
        p.pop("attachments", None)
        p["galleryJson"] = (p.get("galleryJson") or [])[:1]
        o.pop("offerDescription", None)
        o.pop("seller", None)
    slim = {"props": {"pageProps": {"offersList": {"total": ol["total"], "offers": offers}}}}
    links = re.findall(r"https://exchange\.superbid\.net/oferta/[a-z0-9-]+-\d+", html)
    keep = {str(o["id"]) for o in offers}
    links = sorted({u for u in links if u.rsplit("-", 1)[-1] in keep})
    anchors = "\n".join(f'<a href="{u}">offer</a>' for u in links)
    return _wrap([anchors, f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(slim, ensure_ascii=False)}</script>'])


def trim_pgfn(text: str) -> str:
    d = json.loads(text)
    items = d["content"][:N]
    for x in items:
        for k in ("descricao", "nomeCorretor", "telefoneCorretor", "creciCorretor", "emailCredor"):
            x.pop(k, None)
    d["content"] = items
    return json.dumps(d, ensure_ascii=False, indent=1)


def trim_picelli(text: str) -> str:
    auctions = json.loads(text)
    keep = [a for a in auctions if a.get("status") in ("aberto", "futuro")][:N]
    keep += [a for a in auctions if a.get("status") == "encerrado"][:1]  # must be filtered out
    for a in keep:
        a.pop("description", None)
    return json.dumps(keep, ensure_ascii=False, indent=1)


def fetch_live(site: str) -> str:
    s = REGISTRY[site]()
    if site == "zuk":
        return s.get("https://www.portalzuk.com.br/leilao-de-imoveis").text
    if site == "biasi":
        return s.get(f"{s.base_url}/Sale/LotListSearch", params={"categoria": 0, "subcategoria": 0, "start": 0, "limit": 48}).text
    if site == "frazao":
        return s.get(f"{s.base_url}/Sale/SearchLotResult", params={"loteAtivo": "true", "start": 0, "limit": 20, "page": 0}).text
    if site == "alfa":
        return s.get(f"{s.base_url}/leiloes/").text
    if site == "superbid":
        return s.get(f"{s.base_url}/categorias/imoveis").text
    if site == "pgfn":
        ufs = s.get(f"{pgfn_mod.API}/sdc/uf").json()
        params = [(f"ufs[{i}]", u["value"]) for i, u in enumerate(ufs)] + [("page", 0), ("size", 20), ("sort", "1")]
        return s.get(f"{pgfn_mod.API}/anuncio/publico", params=params).text
    raise SystemExit(f"live capture for {site} needs a browser; capture the auctions JSON manually (see AGENT_MAINTENANCE.md)")


TRIM = {
    "zuk": (trim_zuk, "html"),
    "biasi": (lambda h: trim_blueintra(h, "div.col-xs-12:has(> a.leilao-lote)"), "html"),
    "frazao": (lambda h: trim_blueintra(h, "[id='card-lote']"), "html"),
    "alfa": (trim_alfa, "html"),
    "superbid": (trim_superbid, "html"),
    "pgfn": (trim_pgfn, "json"),
    "picelli": (trim_picelli, "json"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=sorted(TRIM))
    ap.add_argument("--from", dest="src", help="trim this saved file instead of fetching live")
    args = ap.parse_args()
    raw = Path(args.src).read_text(encoding="utf-8") if args.src else fetch_live(args.site)
    fn, ext = TRIM[args.site]
    out = FIX / f"{args.site}.{ext}"
    FIX.mkdir(parents=True, exist_ok=True)
    out.write_text(fn(raw), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

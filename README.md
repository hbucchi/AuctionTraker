# AuctionTraker

Monitors Brazilian auctions and builds tailor-made strategy.

This first part is the **scraping routine**: it collects every open
opportunity from seven auction sites and normalizes them into one format,
ready to be loaded into Firestore.

| site | scraper | how it gets data |
|---|---|---|
| [Portal Zuk](https://www.portalzuk.com.br) | `zuk` | server HTML + "load more" POST endpoint |
| [Biasi Leilões](https://www.biasileiloes.com.br) | `biasi` | HTML fragment endpoint (`/Sale/LotListSearch`) |
| [Frazão Leilões](https://www.frazaoleiloes.com.br) | `frazao` | HTML fragment endpoint (`/Sale/SearchLotResult`) |
| [Superbid](https://www.superbid.net) | `superbid` | JSON embedded in the category pages (`__NEXT_DATA__`) |
| [Picelli Leilões](https://www.picellileiloes.com.br) | `picelli` | headless browser; reads the data the home page loads |
| [Alfa Leilões](https://www.alfaleiloes.com) | `alfa` | server HTML, `?page=N` |
| [Comprei / PGFN](https://comprei.pgfn.gov.br) | `pgfn` | public JSON endpoint used by the site's search page |

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # or: export PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome

python -m pytest -q                              # offline tests (no network)
python -m auction_tracker scrape --max-pages 1   # quick live smoke test
python -m auction_tracker scrape                 # everything (~4 min)
python -m auction_tracker scrape zuk pgfn        # some sites
```

Output: `data/<run-id>/<site>.jsonl` (one listing per line) and
`data/<run-id>/report.json` (health of each scraper). The exit code is 1 if
any site failed.

## The data model

Every site maps into `auction_tracker.models.Listing`. Its main fields:

- `id` = `"<site>:<site's own id>"`, stable across runs and used as the database key
- `title`, `category` (`imovel` / `veiculo` / `outros`), `property_type`, `modality`, `status`, `seller`
- `address`, `neighborhood`, `city`, `state` (UF)
- `area_m2`, `appraisal_value`, `current_price`, `discount_pct`
- `rounds`: list of `{number, date, min_bid}` (1st/2nd *praça*), plus `end_date`
- `url`, `image_url`, `bids_count`, `extra` (site-specific leftovers), `scraped_at`

Not every site publishes every field on its listing pages. For example,
Biasi shows no dates and Zuk shows no appraisal value. Those fields stay
`null` instead of being guessed.

## Layout

```
auction_tracker/
  models.py          Listing schema
  parsing.py         BRL money, dates, city/UF, area helpers
  http.py            polite session: retries, backoff, rate limit
  health.py          per-run health report (OK / WARN / FAIL)
  scrapers/<site>.py one file per site; docstring explains how the site works
  storage/           JSONL sink; Firestore sink (to be wired up)
scripts/capture_fixture.py   refresh a trimmed, privacy-safe test fixture
tests/                       offline tests on saved fixtures
AGENT_MAINTENANCE.md         runbook for the weekly AI-agent review
```

## Privacy

Auction notices (editais) contain debtors' names and CPF numbers. The
scrapers deliberately store no free-text descriptions, only structured
fields about the asset. Keep it that way (LGPD).

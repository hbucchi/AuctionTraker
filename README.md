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

## Web app and Firebase

`web/index.html` is the dashboard. On Firebase Hosting it asks for Google
sign-in, then reads the `summaries` collection from Firestore. Without a
Firebase config, it runs as a preview from `web/listings.json`.

```
firebase.json / .firebaserc   hosting (folder web/) + Firestore rules, project "auctiontraker"
firestore.rules               signed-in users read; browsers can never write
web/firebase-config.js        public web config (safe to commit)
.github/workflows/scrape.yml  daily scrape + upload to Firestore
```

Who holds which key:

| Key | Where it lives | Safe to share? |
|---|---|---|
| Web config (`apiKey`, `projectId`...) | `web/firebase-config.js`, in the repo | Yes, it only identifies the project |
| Service-account JSON key | GitHub secret `FIREBASE_SERVICE_ACCOUNT` only | **No**, it's full admin access. Never in the repo, the website or a chat |

Deploy the site and the security rules from your computer:

```bash
npm install -g firebase-tools
firebase login
firebase deploy --only hosting,firestore:rules
```

## Strategies and alerts

Users save **strategies**: sets of criteria with min/max values, e.g. an
investor's rule set of judicial/extrajudicial auctions, houses, apartments
or commercial property ≥ 80 m² with 3+ bedrooms, a minimum bid ≤ 50% of
market value, and cities with > 100k inhabitants, an HDI ≥ 0.7 and GDP per
capita above the national average.

- Criteria are defined once in `web/strategy-fields.json`. The browser
  (`web/strategy.js`) and the alert job (`auction_tracker/strategy.py`) both
  follow it, and `tests/strategy_cases.json` checks that they agree.
- Every numeric criterion has an "include when unknown" switch, because
  sites don't always publish bedrooms, area or appraisal.
- **Market value** comes from the auction's appraisal, or the 1st-round
  minimum bid (which equals the appraisal by law: CPC art. 891 / Lei
  9.514 art. 27), or as a rough fallback FipeZAP R$/m² × area.
- **City data** comes from IBGE (Census 2022 population, municipal GDP and
  agribusiness share) and PNUD (municipal HDI 2010), in
  `auction_tracker/data/` (rebuild: `python scripts/build_reference_data.py`).
- **Debts** (who pays condo/IPTU) are read from Superbid's structured field
  or from listing text; always confirm in the edital.
- **Lawsuits** against the bank are a manual step in each property's
  due-diligence checklist. The app never collects CPFs.
- **Alerts:** after each daily scrape, `python -m auction_tracker alerts`
  finds new matches per user, stores them for the app's "Novo" badges, and
  emails them through Resend when the `RESEND_API_KEY` secret is set.

## Valuation, ROE and map

- **Valuation** (`auction_tracker/valuation.py`) runs five methods: FipeZAP
  comparison, income capitalization, a cross-city regression, auction
  comparables and SINAPI replacement cost. Each is calibrated against
  official auction appraisals and scored on appraisals it didn't see
  (`python scripts/calibrate_valuation.py data/<run-id>`). The app shows the
  weighted central value, an 80% range, and every method with its measured
  error.
- **ROE** (`auction_tracker/roe.py`, browser twin `web/roe.js`) is the return
  of an all-cash flip at the low/central/high end of the valuation's 50%
  band, after auction commission, ITBI, registration, renovation, debts,
  eviction, holding costs, broker and capital-gains tax. Assumptions are
  editable per strategy, and strategies can filter on ROE.
- **Map:** Lista/Mapa switch on the Oportunidades tab, showing whatever the
  filters or strategy select. It uses Google Maps when `window.GOOGLE_MAPS_KEY`
  is set in `web/firebase-config.js` (a browser key restricted to the site's
  domains), otherwise a built-in schematic map. Pins are exact for Superbid
  and for addresses geocoded with the optional `GOOGLE_GEOCODING_KEY` secret;
  the rest sit at their city's center.

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

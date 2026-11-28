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
  is set, otherwise a built-in schematic map. The key comes from the
  `GOOGLE_MAPS_BROWSER_KEY` GitHub secret and is added at deploy time, so it
  never sits in this public repository. Keep it restricted to the site's
  domains and the Maps JavaScript API, with a daily map-load quota (≈300/day)
  to stay in the free tier. Pins are exact for Superbid
  and for addresses geocoded with the optional `GOOGLE_GEOCODING_KEY` secret;
  the rest sit at their city's center.

## Users and portfolios (Firestore)

```
users/{uid}                 email, name, created_at, last_login_at
                            strategies[]        saved searches (see strategy-fields.json)
                            last_filters        the quick filters last used
                            checklists{}        due-diligence progress per lot
                            interest{}          what the user looks for, derived daily from
                                                active strategies: ufs, cities, kinds,
                                                modalities, price_min/max, roe_min
                            interest_ufs[], interest_kinds[], interest_cities[]
                                                flat copies for queries, e.g.
                                                users where interest_ufs array-contains "SP"
users/{uid}/portfolio/{id}  a property the user owns: kind, address, city, uf, area,
                            bedrooms, purchase_price/costs, renovation_spent, status,
                            monthly_rent, asking_price, for_sale, allow_matching
                            + valuation, gain_pct, interested_count (daily job)
alert_state/{uid}           alert job state (read-only for the user)
```

Only the owner can read or write their user document and portfolio. Matching
is opt-in: when a property is marked for sale **and** "permitir match", the
daily job (`python -m auction_tracker portfolio`) counts other users whose
active strategies fit it. The owner sees only that count; no one sees anyone
else's identity, filters or properties.

## Partners and investment groups

The **Parceiros** tab matches investors with similar preferences and lets them
form groups to bid on a property together. Nobody sees who anybody is until
both sides agree; `firestore.rules` enforces this, not just the screen.

| Collection | Who can read | Notes |
|---|---|---|
| `partner_cards/{uid}` | investors who opted in themselves | anonymous: states, types, price range, ticket, goal. A fixed field list, so no name/contact can be stored. Shown under a pseudonym (`handle()` in `web/partners.js`) |
| `connections/{a_b}` | the two people | invite → only the invitee accepts or declines; a declined invite can't be resent |
| `contacts/{uid}` | you + accepted connections | name, e-mail, WhatsApp |
| `groups/{gid}` | public: anyone signed in; private: leader and invitees/members | leader sets quota min/max and the member limit |
| `groups/{gid}/members/{uid}` | yourself; the leader (sees applicants); approved members see approved members | quotas must sit in the leader's range; approvals and accepted invites can't exceed the member limit |

Compatibility (`similarity()` in `web/partners.js`) is a 0–100 score from
shared states and property types (Jaccard index), overlap of price and ticket
ranges, and auction type; criteria either side left open are skipped.

**Opportunities in common.** For each pair (you and a potential partner) the
app counts the open lots that fit both anonymous profiles (`fitsCard`: state,
property type, auction type, price range) and how many fit the two budgets
together (bid ≤ sum of both maximum tickets). Partners are ranked by that
count (top 10), and each group shows the lots that fit every member's profile
and how many fit the amount committed. It runs in the browser on the listings
already loaded: no extra reads, nothing more shared.

Tests: `node tests/partners.test.mjs` (matching) and, with Java installed,
`cd tests/rules && npm install && npm test`: 57 rule checks plus the app's own
partner code run end to end on the Firestore emulator. The deploy workflow
runs them before every deploy. In the preview, the tab runs on sample
investors (labelled "exemplo") kept in the browser.

## Maximum bid, risk factors and lot history

- **Maximum bid** (`max_bid` in `roe.py` / `maxBid` in `roe.js`): the highest
  bid that still gives a target ROE, solved exactly from the same cost model
  as the ROE (capital invested is linear in the bid). Shown at the central
  value and at the value the property beats with a chosen probability (75%
  by default, from the measured valuation errors). Strategy filter:
  "Lance em % do lance máximo".
- **Risk factors** (`risk.py` / `risk.js`, shared cases in
  `tests/risk_cases.json`): a published points table (occupied 3, debts on
  the buyer 2, fraction of the property 2, judicial 1…). Missing information
  counts as risk; ticking the checklist clears it. Strategy filter and sort.
- **History**: the daily job adds `snap.YYYYMMDD = {p, b, s}` (price, bids,
  status) to `listings/{id}`, and when a lot leaves its site after a complete
  run, `ended_at`, final price/bids/status and `outcome` ("sold" when the site
  said so). The detail sheet shows the days on which something changed.

## Group contracts, templates and professionals

- In a group, the leader saves the contract terms (`groups/{gid}.deal`, with a
  version); each member agrees to a version (`agreed_version` on their member
  document). The draft ("minuta") is generated in the browser from the terms
  and the approved quotas, shown on screen and downloadable as PDF (jsPDF,
  loaded on demand). CPF and address can be typed in but stay in that browser.
- **Modelos e serviços** tab: six templates (`web/docs.js`) and a directory of
  professionals (`pros/{uid}`). A listing is created `pending` by its owner
  and published only by an administrator. To make someone an administrator,
  create the document `admins/{their uid}` in the Firebase console
  (Firestore > Start collection `admins` > document id = the uid shown in
  Authentication > Users).

## Daily scraping

Superbid and Picelli refuse GitHub's servers. They are listed in the
repository variable `SCRAPE_KNOWN_BLOCKED` (default `superbid,picelli`) and
reported as BLOCKED instead of failing the run, so a red run means something
new broke. To collect them, register a self-hosted runner on a machine that
can reach them and set the variable `SCRAPE_RUNNER` to its label (and
`SCRAPE_KNOWN_BLOCKED` to `none`). The app hides a site's lots once its data
is more than 3 days old.

## Duplicates, re-runs and the minimum bid

- **Re-runs never duplicate.** Every lot has a fixed id: the site plus the
  site's own lot number (`zuk:38128-239115`). Each run updates the same
  `listings/{id}` document (keeping `first_seen_at`, adding the day's
  snapshot) and rebuilds the site's `summaries/{site}-N` from what the site
  shows that day; leftover parts are deleted, and lots that left the site
  get `ended_at`. Tested in `tests/test_firestore_sink.py`.
- **What looks like duplicates** are separate lots on the sites themselves:
  several identical units under one headline (plots of a development,
  shops of a building), an old page kept online for a relisted property, or
  the same property on two sites. The app groups lots with the same
  headline, city, state and area into one card ("+N lotes semelhantes",
  `web/dedupe.js`), and counts properties rather than lots.
- **Minimum bid R$ 40.000** (`MIN_PRICE` in `summary.py` and in
  `web/index.html`, kept equal by a test): smaller lots and placeholders are
  not shown or alerted on, but are still recorded with their history.

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

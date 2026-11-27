# Scraper maintenance runbook (for the AI agent)

You are reviewing the auction scrapers. Sites change their HTML and APIs without
notice; your job is to notice breakage, fix the affected scraper, and leave
everything else alone. Run this once or twice a week.

## 1. Check health

```bash
pip install -r requirements.txt
export PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium   # only if a pre-installed Chromium exists
python -m pytest -q                        # offline parser tests must pass first
python -m auction_tracker scrape           # full live run, ~4 minutes
cat data/latest_report.json
```

Each site gets `OK`, `WARN` or `FAIL` with reasons:

| Reason in report | What it usually means |
|---|---|
| `exception: ...` / `no listings returned` | URL, endpoint, or required parameter changed; or the site is down. |
| `collected X of the Y the site advertises` | Pagination is skipping items (page size or sort order changed). |
| `count fell from X to Y` | Pagination stops early, or a filter now excludes most items. |
| `field 'F' filled in only N%` | A CSS selector / JSON key for that field changed. |

Before editing anything, open the site in a browser (or `curl` it) and confirm
the problem is on our side. A site having a slow week isn't a bug. Real
volumes, measured on 2026-11-26, are listed under **Baselines**.

## 2. Fix one site

Every scraper is a single file in `auction_tracker/scrapers/`. Its module
docstring describes **how that site works** (endpoints, parameters, markup).
Read it first; it's the fastest way to see what changed.

1. Reproduce: `python -m auction_tracker -v scrape <site> --max-pages 1`
2. Capture a fresh fixture: `python scripts/capture_fixture.py <site>`
   (Picelli needs a browser, so save the `/rest/v1/auctions?...home_tab=...`
   response the home page loads, then run `--from that.json`).
3. Update `tests/test_parsers.py` expectations for that site to match the new
   fixture (open the live page to read the real values).
4. Fix the parser until `pytest` passes, then re-run step 1 without `--max-pages`.
5. Update the "verified YYYY-MM-DD" notes in the scraper's docstring.

Rules:
- Keep the `Listing` schema (`auction_tracker/models.py`) stable. Adding a
  field is fine; renaming or removing one breaks the database and the UI.
- Keep `source_id` stable for the same lot, because it's the database key. If
  a site changes its ids, write it in the commit message.
- **Never store free-text descriptions or personal data.** Editais on these
  sites list debtors' names and CPF numbers; PGFN lists broker phones. Fixtures
  must be trimmed the same way (`scripts/capture_fixture.py` does this).
- Be polite: keep `min_interval` ≥ 1 s, and don't parallelize requests to one site.
- Don't call private/authenticated backends or use keys pulled from a site's
  JavaScript. Use public pages and the public endpoints those pages call
  themselves. If a site moves behind a login or a CAPTCHA, stop and report
  it to the user instead of working around it.

## 3. Report

Commit with a message like `fix(frazao): new card markup for price` and
summarize for the user: which sites were OK, what broke, what you changed, and
anything you couldn't fix.

## Reference data and strategies

- Once a month: `python scripts/build_reference_data.py --fipezap` (new
  FipeZAP month) and commit `auction_tracker/data/fipezap.json`. Once a year,
  run it without `--fipezap` to pick up new IBGE GDP data.
- If you change how a strategy rule works, change BOTH
  `auction_tracker/strategy.py` and `web/strategy.js`, and add a case to
  `tests/strategy_cases.json`. `pytest` runs the cases against both.
- If an enrichment field's coverage drops (market value, bedrooms, debts),
  check `auction_tracker/enrich.py` and the site's scraper; users' alerts
  depend on these fields.

## Valuation

- After refreshing FipeZAP/SINAPI, or when coverage changes a lot, recalibrate:
  `python scripts/calibrate_valuation.py data/<run-id>`. Commit
  `auction_tracker/data/valuation_calibration.json` and `web/valuation-meta.json`.
  Report the printed errors; if the combined median error gets worse than
  ~45%, look for an area or classification parsing regression first.
- Bids under 20% of the estimate are flagged as suspicious, not ranked. If the
  flagged count jumps, a scraper is probably reading the wrong area or missing
  a fractional-share marker.

## Baselines (2026-11-26)

| site | listings | notes |
|---|---|---|
| zuk | ~980 | site counter says ~1017; ~4% are repeated cards, so this is expected |
| biasi | ~390 | all categories (`categoria=0`) |
| frazao | ~430 | active lots; vehicles have no city/state |
| superbid | ~1300 | real estate only (`categories=["imoveis"]`); must sort `orderBy=id:asc` |
| picelli | ~100 | open + upcoming auctions on the home page; needs Playwright |
| alfa | ~240 | open/future/coming-soon filter, all auction types |
| pgfn | ~550 | all 27 UFs in one query; server needs the extra TLS ciphers set in the scraper |

// Runs tests/roe_cases.json against web/roe.js (the browser copy).
import { readFileSync } from "node:fs";
import { roeRange, chances, ceilings, maxBid, flip, roeAssumptions } from "../web/roe.js";
const { cases, chance_cases, ceiling_cases, quantiles } = JSON.parse(readFileSync(new URL("./roe_cases.json", import.meta.url)));
let failed = 0;
for (const c of cases) {
  const got = roeRange(c.item, c.custom);
  if (JSON.stringify(got) !== JSON.stringify(c.expect)) { failed++; console.log(`FAIL ${c.name}: expected ${JSON.stringify(c.expect)}, got ${JSON.stringify(got)}`); }
}
for (const c of chance_cases) {
  const got = chances(c.item, quantiles, c.custom);
  if (JSON.stringify(got) !== JSON.stringify(c.expect)) { failed++; console.log(`FAIL chance ${c.name}: expected ${JSON.stringify(c.expect)}, got ${JSON.stringify(got)}`); }
}
for (const c of ceiling_cases) {
  const got = ceilings(c.item, quantiles, null, c.target, c.chance);
  if (JSON.stringify(got) !== JSON.stringify(c.expect)) { failed++; console.log(`FAIL ceiling ${c.name}: expected ${JSON.stringify(c.expect)}, got ${JSON.stringify(got)}`); }
}
// the ceiling is exact: bidding it gives the target ROE
const a = roeAssumptions();
for (const t of [0, 0.1, 0.25]) {
  const b = maxBid(500000, t, true, true, a, true);
  const r = flip(b, 500000, true, true, a, true).roe;
  if (Math.abs(r - t) > 1e-9) { failed++; console.log(`FAIL maxBid round trip ${t}: roe ${r}`); }
}
console.log(`${cases.length + chance_cases.length - failed}/${cases.length + chance_cases.length} ROE cases passed (JavaScript)`);
process.exit(failed ? 1 : 0);

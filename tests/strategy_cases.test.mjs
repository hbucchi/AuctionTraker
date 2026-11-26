// Runs the shared strategy cases against web/strategy.js (the browser copy).
import { readFileSync } from "node:fs";
import { matchesStrategy } from "../web/strategy.js";

const spec = JSON.parse(readFileSync(new URL("../web/strategy-fields.json", import.meta.url)));
const { now, cases } = JSON.parse(readFileSync(new URL("./strategy_cases.json", import.meta.url)));
let failed = 0;
for (const c of cases) {
  const got = matchesStrategy(spec, c.strategy, c.item, now);
  if (got !== c.expect) { failed++; console.log(`FAIL ${c.name}: expected ${c.expect}, got ${got}`); }
}
console.log(`${cases.length - failed}/${cases.length} strategy cases passed (JavaScript)`);
process.exit(failed ? 1 : 0);

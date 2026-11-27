// Runs tests/roe_cases.json against web/roe.js (the browser copy).
import { readFileSync } from "node:fs";
import { roeRange } from "../web/roe.js";
const { cases } = JSON.parse(readFileSync(new URL("./roe_cases.json", import.meta.url)));
let failed = 0;
for (const c of cases) {
  const got = roeRange(c.item, c.custom);
  if (JSON.stringify(got) !== JSON.stringify(c.expect)) { failed++; console.log(`FAIL ${c.name}: expected ${JSON.stringify(c.expect)}, got ${JSON.stringify(got)}`); }
}
console.log(`${cases.length - failed}/${cases.length} ROE cases passed (JavaScript)`);
process.exit(failed ? 1 : 0);

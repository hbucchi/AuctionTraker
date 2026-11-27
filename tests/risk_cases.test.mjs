// Runs tests/risk_cases.json against web/risk.js (the browser copy).
import { readFileSync } from "node:fs";
import { risk } from "../web/risk.js";
const { cases } = JSON.parse(readFileSync(new URL("./risk_cases.json", import.meta.url)));
let failed = 0;
for (const c of cases) {
  const got = risk(c.item, c.checklist);
  if (JSON.stringify(got) !== JSON.stringify(c.expect)) { failed++; console.log(`FAIL ${c.name}: expected ${JSON.stringify(c.expect)}, got ${JSON.stringify(got)}`); }
}
console.log(`${cases.length - failed}/${cases.length} risk cases passed (JavaScript)`);
process.exit(failed ? 1 : 0);

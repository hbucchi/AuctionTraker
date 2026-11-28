// node tests/dedupe.test.mjs — grouping of similar lots (web/dedupe.js)
import { groupSimilar, similarKey } from "../web/dedupe.js";
let fail = 0;
const ok = (c, n) => { if (!c) { fail++; console.log("FAIL", n); } };
const lot = (id, title, city, uf, area, price) => ({ id, title, city, uf, area, price });
const rows = [
  lot("a1", "Terreno com 350m em Balneário Arroio do Silva/SC", "Balneário Arroio do Silva", "SC", 350, 50000),
  lot("b1", "Casa - Rua X, 10", "Campinas", "SP", 120, 300000),
  lot("a2", "Terreno com 350m em Balneario Arroio do Silva/SC", "Balneario Arroio do Silva", "SC", 350, 50000),
  lot("a3", "TERRENO COM 350M EM BALNEÁRIO ARROIO DO SILVA/SC", "Balneário Arroio do Silva", "SC", 350.2, 50000),
  lot("c1", "Casa - Rua X, 10", "Campinas", "SP", 200, 450000),  // same headline, different size: another property
  lot("d1", "Casa - Rua X, 10", "Sorocaba", "SP", 120, 300000),  // same headline, other city
];
const g = groupSimilar(rows);
ok(g.length === 4, `4 groups (got ${g.length})`);
ok(g[0].lead.id === "a1" && g[0].more.map((x) => x.id).join() === "a2,a3", "accents, case and rounding ignored; first in order leads");
ok(g[1].lead.id === "b1" && g[1].more.length === 0, "different area is not grouped");
ok(g.map((x) => x.lead.id).join() === "a1,b1,c1,d1", "order kept");
ok(g.reduce((n, x) => n + 1 + x.more.length, 0) === rows.length, "nothing dropped");
ok(similarKey(rows[0]) === similarKey(rows[2]), "same key");
console.log(fail ? `${fail} failed` : "dedupe: all passed");
process.exit(fail ? 1 : 0);

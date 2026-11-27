// node tests/partners.test.mjs — exits 1 on failure
import { handle, similarity, rangeOverlap, cardFromStrategies, pairId, quotaOk } from "../web/partners.js";

let fail = 0;
const ok = (cond, name) => { if (!cond) { fail++; console.log("FAIL", name); } };

ok(handle("abc") === handle("abc") && /^Investidor [A-Z2-9]{4}$/.test(handle("abc")), "handle is stable and shaped");
ok(handle("abc") !== handle("abd"), "different users, different handles");

ok(rangeOverlap(100, 200, 150, 300) === 0.5, "half of the shorter range overlaps");
ok(rangeOverlap(100, 200, 300, 400) === 0, "disjoint ranges");
ok(rangeOverlap(null, null, null, null) === null && rangeOverlap(1, 2, null, null) === null, "an open side means no preference");
ok(rangeOverlap(100, null, 150, 300) === 1, "open range contains the other");

const a = { ufs: ["SP", "PR"], kinds: ["apartamento"], modalities: [], price_min: 200e3, price_max: 600e3, ticket_min: 50e3, ticket_max: 150e3 };
const b = { ufs: ["SP"], kinds: ["apartamento", "casa"], modalities: ["judicial"], price_min: 300e3, price_max: 800e3, ticket_min: 100e3, ticket_max: 300e3 };
const s = similarity(a, b);
ok(s.score > 40 && s.score < 90, `partial match scores in between (${s.score})`);
ok(JSON.stringify(s.shared.ufs) === '["SP"]' && JSON.stringify(s.shared.kinds) === '["apartamento"]', "shared criteria listed");
ok(s.parts.modalities === null, "an open side is skipped, not penalised");
ok(similarity(a, a).score === 100, "identical cards score 100");
ok(similarity(a, { ufs: ["AM"], kinds: ["rural"], price_min: 5e6, price_max: 9e6 }).score === 0, "nothing in common scores 0");

const c = cardFromStrategies([
  { enabled: true, sets: { uf: { values: ["SP"] }, kind: { values: ["casa"] } }, ranges: { price: { min: 100000, max: 500000 } } },
  { enabled: true, sets: { uf: { values: ["PR", "SP"] } }, ranges: { price: { min: 50000, max: null } } },
  { enabled: false, sets: { uf: { values: ["AM"] } } },
]);
ok(JSON.stringify(c.ufs) === '["PR","SP"]' && c.price_min === 50000 && c.price_max === 500000, "card from enabled strategies");

ok(pairId("b", "a") === pairId("a", "b") && pairId("a", "b") === "a_b", "pair id is order-free");
ok(quotaOk(50000, { quota_min: 20000, quota_max: 100000 }) && !quotaOk(10, { quota_min: 20000, quota_max: 100000 }), "quota range");

console.log(fail ? `${fail} failed` : "partners: all passed");
process.exit(fail ? 1 : 0);

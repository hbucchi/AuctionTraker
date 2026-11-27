// node tests/partners.test.mjs — exits 1 on failure
import { handle, similarity, rangeOverlap, cardFromStrategies, pairId, quotaOk, fitsCard, sharedListings, combinedTicket, rankByShared, sharedSummary } from "../web/partners.js";

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

// shared opportunities: "two people want an apartment in SP for over R$ 80k"
const L = [
  { id: "1", uf: "SP", kind: "apartamento", modn: "judicial", price: 90e3 },
  { id: "2", uf: "SP", kind: "apartamento", modn: "extrajudicial", price: 300e3 },
  { id: "3", uf: "SP", kind: "apartamento", modn: "judicial", price: 70e3 },   // under 80k
  { id: "4", uf: "RJ", kind: "apartamento", modn: "judicial", price: 200e3 },  // other state
  { id: "5", uf: "SP", kind: "casa", modn: "judicial", price: 200e3 },         // other type
];
const me = { uid: "me", ufs: ["SP"], kinds: ["apartamento"], modalities: [], price_min: 80e3, price_max: null, ticket_min: null, ticket_max: 100e3 };
const p1 = { uid: "p1", ufs: ["SP", "RJ"], kinds: ["apartamento"], modalities: [], price_min: 80e3, price_max: null, ticket_max: 150e3 };
const p2 = { uid: "p2", ufs: ["SP"], kinds: [], modalities: ["judicial"], price_min: null, price_max: 250e3 };
const p3 = { uid: "p3", ufs: ["AM"], kinds: [], modalities: [], price_min: null, price_max: null };
ok(fitsCard(me, L[0]) && !fitsCard(me, L[2]) && !fitsCard(me, L[3]) && !fitsCard(me, L[4]), "card filters state, type and price");
ok(JSON.stringify(sharedListings([me, p1], L).map((x) => x.id)) === '["1","2"]', "listings fitting both");
ok(JSON.stringify(sharedListings([me, p1, p2], L).map((x) => x.id)) === '["1"]', "listings fitting a whole group");
ok(combinedTicket([me, p1]) === 250e3 && combinedTicket([me, p2]) === null, "combined budget, unknown if anyone left it blank");
const r = rankByShared(me, [p3, p2, p1], L);
ok(r.map((x) => x.uid).join() === "p1,p2,p3" && r[0].count === 2 && r[1].count === 1 && r[2].count === 0, "ranked by shared count");
ok(r[0].affordable === 1 && r[1].affordable === null, "R$ 300k is over the pair's R$ 250k: 1 of 2 fits both budgets");
const sm = sharedSummary(r);
ok(sm.opportunities === 2 && sm.partners === 2, "summary: 2 opportunities with 2 partners");

console.log(fail ? `${fail} failed` : "partners: all passed");
process.exit(fail ? 1 : 0);

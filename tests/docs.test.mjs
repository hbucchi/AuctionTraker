// node tests/docs.test.mjs — document templates (web/docs.js)
import { dealContract, shares, TEMPLATES, docHTML, fileName, DRAFT_NOTE } from "../web/docs.js";
let fail = 0;
const ok = (c, n) => { if (!c) { fail++; console.log("FAIL", n); } };
const s = shares([{ quota: 150000 }, { quota: 100000 }, { quota: 50000 }]);
ok(s.total === 300000 && Math.abs(s.rows.reduce((a, r) => a + r.pct, 0) - 100) < 1e-9 && s.rows[0].pct === 50, "shares add up to 100% from quotas");
const d = dealContract({ group: { name: "Apto Moema" }, members: [{ name: "Ana", quota: 150000, role: "leader" }, { name: "Bruno", quota: 50000, role: "member" }],
  terms: { property_title: "Apartamento em Moema", max_bid: 400000, deposit_days: 3, refund_days: 5, call_days: 10, sale_majority_pct: 75, forum_city: "São Paulo", purpose: "revenda" } });
const txt = JSON.stringify(d);
ok(txt.includes("75%") && txt.includes("25%") && txt.includes("400.000"), "contract shows shares and the bid limit");
ok(txt.includes("Ana") && txt.includes("ADMINISTRADOR") && txt.includes("1.314"), "leader named as administrator, co-ownership article cited");
ok(d.blocks.filter((b) => b.sign).length === 1 && d.blocks.find((b) => b.sign).sign.length === 4, "two parties + two witnesses sign");
ok(/CLÁUSULA 1ª/.test(txt) && /CLÁUSULA 8ª/.test(txt), "clauses numbered in order");
ok(!txt.includes("undefined") && !txt.includes("NaN"), "no undefined/NaN in the text");
for (const t of TEMPLATES) {
  const v = Object.fromEntries(t.fields.map(([k, , , def]) => [k, def]));
  const doc = t.build(v), h = docHTML(doc);
  ok(doc.title && h.includes(DRAFT_NOTE.slice(0, 20)) && !h.includes("undefined") && !h.includes("NaN"), `template ${t.id} renders with defaults`);
  const empty = docHTML(t.build({}));
  ok(!empty.includes("undefined") && !empty.includes("NaN"), `template ${t.id} renders with empty answers`);
}
ok(docHTML({ title: "<b>x</b>", blocks: [{ p: "<script>" }] }).includes("&lt;script&gt;"), "HTML is escaped");
ok(fileName("INSTRUMENTO PARTICULAR DE PARCERIA") === "instrumento-particular-de-parceria.pdf" && !fileName("INSTRUMENTO PARTICULAR DE PARCERIA PARA AQUISIÇÃO DE IMÓVEL EM LEILÃO").includes("-.pdf"), "file name");
console.log(fail ? `${fail} failed` : "docs: all passed");
process.exit(fail ? 1 : 0);

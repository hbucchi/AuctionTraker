// Strategy matching — the JavaScript twin of auction_tracker/strategy.py.
// Both are tested against tests/strategy_cases.json; change them together.

import { roeRange, chances, ceilings } from "./roe.js";
import { risk } from "./risk.js";

const DAY_S = 86400; // seconds

const norm = (s) => String(s ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
const ts = (iso) => { if (!iso) return null; const t = Date.parse(iso); return Number.isNaN(t) ? null : t / 1000; };

export function nextDeadline(item, now) {
  const future = (item.rounds || []).map((r) => ts(r.d)).filter((t) => t != null && t >= now);
  return future.length ? Math.min(...future) : ts(item.end);
}

export function isEnded(item, now) {
  const end = ts(item.end);
  const proposals = /proposta/i.test(item.status || "");
  return end != null && end < now && !proposals;
}

function attrValue(spec, item, attr, now, st) {
  if (attr === "days") { const t = nextDeadline(item, now); return t == null ? null : (t - now) / DAY_S; }
  if (attr === "chance") {
    const c = chances(item, spec.reference?.residual_quantiles, (st || {}).roe_assumptions);
    return c == null ? null : c.profit;
  }
  if (attr === "risk") return risk(item).points;
  if (attr === "ceilpct") {
    // bid as % of the maximum bid for the strategy's minimum ROE (20% if none)
    const t = (st || {}).ranges?.roe?.min ?? 20;
    const c = ceilings(item, null, (st || {}).roe_assumptions, t);
    return c == null || !c.central ? null : Math.round(1000 * item.price / c.central) / 10;
  }
  if (attr === "roe" || attr === "roelo") {
    // computed with the strategy's own cost assumptions (roe.js)
    const r = roeRange(item, (st || {}).roe_assumptions);
    return r == null ? null : r[attr === "roe" ? "mid" : "lo"];
  }
  return item[attr] ?? null;
}

const rangeActive = (r) => !!r && (r.min != null || r.max != null);
function rangeOk(v, r) {
  if (v == null) return !!r.unknown;
  if (r.min != null && v < r.min) return false;
  if (r.max != null && v > r.max) return false;
  return true;
}

export function matchesStrategy(spec, st, item, now = Date.now() / 1000) {
  if ((st.hide_ended ?? true) && isEnded(item, now)) return false;

  for (const s of spec.sets) {
    const cfg = (st.sets || {})[s.key];
    if (!cfg || !cfg.values || !cfg.values.length) continue;
    const v = item[s.attr];
    if (v == null) { if (!cfg.unknown) return false; }
    else if (!cfg.values.includes(v)) return false;
  }

  const city = [];
  for (const r of spec.ranges) {
    const cfg = (st.ranges || {})[r.key];
    if (!rangeActive(cfg)) continue;
    const ok = rangeOk(attrValue(spec, item, r.attr, now, st), cfg);
    if (r.city) city.push(ok); else if (!ok) return false;
  }
  for (const t of spec.toggles) {
    if (!(st.toggles || {})[t.key]) continue;
    const ok = !!item[t.attr];
    if (t.city) city.push(ok); else if (!ok) return false;
  }
  if (city.length) {
    if ((st.city_mode || "all") === "any") { if (!city.some(Boolean)) return false; }
    else if (!city.every(Boolean)) return false;
  }

  const cities = st.cities || [];
  if (cities.length) {
    const here = norm(`${item.city || ""}/${item.uf || ""}`);
    if (!cities.map(norm).includes(here)) return false;
  }
  const hoods = (st.neighborhoods || []).filter((h) => h.trim());
  if (hoods.length) {
    const text = norm(`${item.hood || ""} ${item.title || ""}`);
    if (!hoods.some((h) => text.includes(norm(h)))) return false;
  }

  const debts = st.debts || "any";
  if (debts === "not_buyer" && item.debts === true) return false;
  if (debts === "seller_only" && item.debts !== false) return false;
  return true;
}

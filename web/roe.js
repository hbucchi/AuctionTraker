// Estimated ROE of an auction flip — the JavaScript twin of auction_tracker/roe.py.
// Both are tested against tests/roe_cases.json; change them together.

export const ROE_DEFAULTS = {
  commission_pct: 5, itbi_pct: 3, registry_pct: 1.5, docs_fixed: 1500,
  renovation_min_pct: 0, renovation_max_pct: 10, furniture_pct: 0,
  debts_pct: 5, eviction_pct: 3, eviction_months: 6, legal_fixed: 6000, legal_on_judicial: 1,
  assume_occupied: 0, holding_months: 12, carrying_pct_month: 0.15, broker_pct: 6, tax_pct: 15,
};

const halfUp = (x) => Math.floor(x + 0.5);

export function roeAssumptions(custom) {
  const a = { ...ROE_DEFAULTS };
  const c = { ...(custom || {}) };
  // strategies saved before the renovation range existed had one number
  if (c.renovation_pct != null && c.renovation_pct !== "" && !("renovation_max_pct" in c)) {
    if (!("renovation_min_pct" in c)) c.renovation_min_pct = c.renovation_pct;
    c.renovation_max_pct = c.renovation_pct;
  }
  for (const [k, v] of Object.entries(c)) if (k in a && v != null && v !== "") a[k] = Number(v);
  if (a.renovation_max_pct < a.renovation_min_pct) a.renovation_max_pct = a.renovation_min_pct;
  return a;
}

function context(debts, occupied, judicial, a) {
  const occ = occupied === true || (occupied == null && a.assume_occupied >= 1);
  const lawyer = occ || (judicial && a.legal_on_judicial >= 1);
  const months = a.holding_months + (occ ? a.eviction_months : 0);
  return { occ, lawyer, months };
}

export function costs(price, value, debts, occupied, judicial, a, renovationPct) {
  const { occ, lawyer, months } = context(debts, occupied, judicial, a);
  return {
    bid: price,
    fees: price * (a.commission_pct + a.itbi_pct + a.registry_pct) / 100,
    docs: a.docs_fixed,
    renovation: value * renovationPct / 100,
    furniture: value * a.furniture_pct / 100,
    debts: debts === true ? value * a.debts_pct / 100 : 0,
    eviction: occ ? value * a.eviction_pct / 100 : 0,
    legal: lawyer ? a.legal_fixed : 0,
    carrying: value * a.carrying_pct_month / 100 * months,
  };
}

export function flip(price, value, debts, occupied, a, judicial = false, renovationPct = null) {
  if (renovationPct == null) renovationPct = (a.renovation_min_pct + a.renovation_max_pct) / 2;
  const c = costs(price, value, debts, occupied, judicial, a, renovationPct);
  const { months } = context(debts, occupied, judicial, a);
  const equity = Object.values(c).reduce((s, v) => s + v, 0);
  const broker = value * a.broker_pct / 100;
  const gain = value - broker - equity;
  const tax = Math.max(gain, 0) * a.tax_pct / 100;
  const profit = gain - tax;
  const roe = profit / equity;
  const annual = roe > -1 ? (1 + roe) ** (12 / months) - 1 : -1;
  return { roe, annual, equity, profit, months, costs: c, broker, tax };
}

const r1 = (n) => Math.round(n * 10) / 10;

export function roeRange(item, custom) {
  const val = item.val, price = item.price;
  if (!val || !price || price < 1000 || val.flag) return null;
  const a = roeAssumptions(custom);
  const j = item.modn === "judicial", d = item.debts, o = item.occ;
  const lo = flip(price, val.lo50, d, o, a, j, a.renovation_max_pct);
  const mid = flip(price, val.mid, d, o, a, j);
  const hi = flip(price, val.hi50, d, o, a, j, a.renovation_min_pct);
  return { lo: r1(100 * lo.roe), mid: r1(100 * mid.roe), hi: r1(100 * hi.roe), annual: r1(100 * mid.annual), months: mid.months, equity: halfUp(mid.equity) };
}

// Resale value that gives exactly targetRoe (0 = breakeven). See roe.py.
export function valueNeeded(price, targetRoe, debts, occupied, a, judicial = false, renovationPct = null) {
  if (renovationPct == null) renovationPct = (a.renovation_min_pct + a.renovation_max_pct) / 2;
  const { occ, lawyer, months } = context(debts, occupied, judicial, a);
  const k = 1 + (a.commission_pct + a.itbi_pct + a.registry_pct) / 100;
  const fixed = a.docs_fixed + (lawyer ? a.legal_fixed : 0);
  const c = (renovationPct + a.furniture_pct + (debts === true ? a.debts_pct : 0) + (occ ? a.eviction_pct : 0) + a.carrying_pct_month * months) / 100;
  const s = targetRoe > 0 ? targetRoe / (1 - a.tax_pct / 100) : targetRoe;
  const denom = 1 - a.broker_pct / 100 - c * (1 + s);
  return denom <= 0 ? Infinity : (price * k + fixed) * (1 + s) / denom;
}

// P(true value ≥ needed) from the measured error distribution (see roe.py).
export function chanceValueAtLeast(needed, mid, quantiles) {
  const r = needed / mid;
  if (r <= quantiles[0]) return 0.975;
  if (r >= quantiles[quantiles.length - 1]) return 0.025;
  for (let i = 0; i < quantiles.length - 1; i++) {
    const x0 = quantiles[i], x1 = quantiles[i + 1];
    if (x0 <= r && r <= x1) {
      const p0 = (5 * (i + 1)) / 100, p1 = (5 * (i + 2)) / 100;
      const cdf = p0 + (p1 - p0) * (x1 > x0 ? (r - x0) / (x1 - x0) : 0);
      return halfUp(1000 * (1 - cdf)) / 1000;
    }
  }
  return 0.5;
}

export function chances(item, quantiles, custom, targetRoePct = 20) {
  const val = item.val, price = item.price;
  if (!val || !price || price < 1000 || val.flag || !quantiles) return null;
  const q = quantiles[(val.n || 0) >= 3 ? "many" : "few"] || quantiles.many;
  const a = roeAssumptions(custom);
  const j = item.modn === "judicial";
  const be = valueNeeded(price, 0, item.debts, item.occ, a, j);
  const tgt = valueNeeded(price, targetRoePct / 100, item.debts, item.occ, a, j);
  return { profit: halfUp(100 * chanceValueAtLeast(be, val.mid, q)), target: halfUp(100 * chanceValueAtLeast(tgt, val.mid, q)), breakeven: halfUp(be) };
}

// Highest bid that still gives targetRoe if the property sells for `value`:
// valueNeeded() solved for the price. 0 when no bid works. See roe.py.
export function maxBid(value, targetRoe, debts, occupied, a, judicial = false, renovationPct = null) {
  if (renovationPct == null) renovationPct = (a.renovation_min_pct + a.renovation_max_pct) / 2;
  const { occ, lawyer, months } = context(debts, occupied, judicial, a);
  const k = 1 + (a.commission_pct + a.itbi_pct + a.registry_pct) / 100;
  const fixed = a.docs_fixed + (lawyer ? a.legal_fixed : 0);
  const c = (renovationPct + a.furniture_pct + (debts === true ? a.debts_pct : 0) + (occ ? a.eviction_pct : 0) + a.carrying_pct_month * months) / 100;
  const s = targetRoe > 0 ? targetRoe / (1 - a.tax_pct / 100) : targetRoe;
  const price = (value * (1 - a.broker_pct / 100 - c * (1 + s)) / (1 + s) - fixed) / k;
  return Math.max(price, 0);
}

// The value the property beats with probability `chance` (0..1). See roe.py.
export function valueAtChance(mid, quantiles, chance) {
  const cdf = 1 - chance;
  const qs = quantiles.map((_, i) => (5 * (i + 1)) / 100);
  if (cdf <= qs[0]) return mid * quantiles[0];
  if (cdf >= qs[qs.length - 1]) return mid * quantiles[quantiles.length - 1];
  for (let i = 0; i < qs.length - 1; i++) {
    if (qs[i] <= cdf && cdf <= qs[i + 1]) return mid * (quantiles[i] + (quantiles[i + 1] - quantiles[i]) * (cdf - qs[i]) / (qs[i + 1] - qs[i]));
  }
  return mid;
}

export function ceilings(item, quantiles, custom, targetRoePct = 20, chancePct = 75) {
  const val = item.val, price = item.price;
  if (!val || !price || price < 1000 || val.flag) return null;
  const a = roeAssumptions(custom);
  const j = item.modn === "judicial", t = targetRoePct / 100;
  const out = { central: halfUp(maxBid(val.mid, t, item.debts, item.occ, a, j)) };
  const q = quantiles && (quantiles[(val.n || 0) >= 3 ? "many" : "few"] || quantiles.many);
  if (q) out.safe = halfUp(maxBid(valueAtChance(val.mid, q, chancePct / 100), t, item.debts, item.occ, a, j));
  return out;
}

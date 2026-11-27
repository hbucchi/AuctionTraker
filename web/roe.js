// ROE of an auction flip — the JavaScript twin of auction_tracker/roe.py.
// Both are tested against tests/roe_cases.json; change them together.

export const ROE_DEFAULTS = {
  commission_pct: 5, itbi_pct: 3, registry_pct: 1.5, renovation_pct: 5, debts_pct: 5,
  eviction_pct: 3, eviction_months: 6, assume_occupied: 0, holding_months: 12,
  carrying_pct_month: 0.15, broker_pct: 6, tax_pct: 15,
};

export function roeAssumptions(custom) {
  const a = { ...ROE_DEFAULTS };
  for (const [k, v] of Object.entries(custom || {})) if (k in a && v != null && v !== "") a[k] = Number(v);
  return a;
}

export function flip(price, value, debts, occupied, a) {
  const occ = occupied === true || (occupied == null && a.assume_occupied >= 1);
  const months = a.holding_months + (occ ? a.eviction_months : 0);
  const equity = price * (1 + (a.commission_pct + a.itbi_pct + a.registry_pct) / 100)
    + value * a.renovation_pct / 100
    + (debts === true ? value * a.debts_pct / 100 : 0)
    + (occ ? value * a.eviction_pct / 100 : 0)
    + value * a.carrying_pct_month / 100 * months;
  const gain = value * (1 - a.broker_pct / 100) - equity;
  const profit = gain - Math.max(gain, 0) * a.tax_pct / 100;
  const roe = profit / equity;
  const annual = roe > -1 ? (1 + roe) ** (12 / months) - 1 : -1;
  return { roe, annual, equity, profit, months };
}

const r1 = (n) => Math.round(n * 10) / 10;

export function roeRange(item, custom) {
  const val = item.val, price = item.price;
  if (!val || !price || price < 1000 || val.flag) return null;
  const a = roeAssumptions(custom);
  const lo = flip(price, val.lo50, item.debts, item.occ, a);
  const mid = flip(price, val.mid, item.debts, item.occ, a);
  const hi = flip(price, val.hi50, item.debts, item.occ, a);
  return { lo: r1(100 * lo.roe), mid: r1(100 * mid.roe), hi: r1(100 * hi.roe), annual: r1(100 * mid.annual), months: mid.months, equity: Math.round(mid.equity) };
}

// Resale value that gives exactly targetRoe (0 = breakeven). See roe.py.
export function valueNeeded(price, targetRoe, debts, occupied, a) {
  const occ = occupied === true || (occupied == null && a.assume_occupied >= 1);
  const months = a.holding_months + (occ ? a.eviction_months : 0);
  const k = 1 + (a.commission_pct + a.itbi_pct + a.registry_pct) / 100;
  const c = (a.renovation_pct + (debts === true ? a.debts_pct : 0) + (occ ? a.eviction_pct : 0) + a.carrying_pct_month * months) / 100;
  const s = targetRoe > 0 ? targetRoe / (1 - a.tax_pct / 100) : targetRoe;
  const denom = 1 - a.broker_pct / 100 - c * (1 + s);
  return denom <= 0 ? Infinity : price * k * (1 + s) / denom;
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
      return Math.round((1 - cdf) * 1000) / 1000;
    }
  }
  return 0.5;
}

export function chances(item, quantiles, custom, targetRoePct = 20) {
  const val = item.val, price = item.price;
  if (!val || !price || price < 1000 || val.flag || !quantiles) return null;
  const q = quantiles[(val.n || 0) >= 3 ? "many" : "few"] || quantiles.many;
  const a = roeAssumptions(custom);
  const be = valueNeeded(price, 0, item.debts, item.occ, a);
  const tgt = valueNeeded(price, targetRoePct / 100, item.debts, item.occ, a);
  return { profit: Math.round(100 * chanceValueAtLeast(be, val.mid, q)), target: Math.round(100 * chanceValueAtLeast(tgt, val.mid, q)), breakeven: Math.round(be) };
}

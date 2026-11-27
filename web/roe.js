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

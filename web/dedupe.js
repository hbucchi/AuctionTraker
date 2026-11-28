// Similar lots shown once. Auction sites often publish several lots under the
// same headline (identical plots of one development, units of one building)
// or keep an old page for a property that was relisted. Lots with the same
// headline, city, state and area are grouped: the first one in the current
// sort order leads, the others are one click away. Nothing is dropped.

const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export const similarKey = (x) => [norm(x.title), norm(x.city), x.uf || "", x.area ? Math.round(x.area) : ""].join("|");

// rows must already be sorted; returns [{ key, lead, more: [...] }] in that order.
export function groupSimilar(rows) {
  const byKey = new Map(), out = [];
  for (const x of rows) {
    const k = similarKey(x);
    const g = byKey.get(k);
    if (g) g.more.push(x);
    else { const ng = { key: k, lead: x, more: [] }; byKey.set(k, ng); out.push(ng); }
  }
  return out;
}

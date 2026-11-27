// Partner matching: pure functions shared by the web app and its tests.
//
// An investor who opts in publishes an anonymous card (partner_cards/{uid}):
// where and what they want to buy, the price range of the properties, and how
// much they want to put into one deal (their "ticket"). No name, no contact:
// those live in contacts/{uid} and group member docs, readable only after both
// sides agree (see firestore.rules).

export const CARD_FIELDS = ["ufs", "kinds", "modalities", "price_min", "price_max", "ticket_min", "ticket_max", "goal", "updated_at"];
export const GOALS = [["revenda", "Comprar e revender"], ["aluguel", "Comprar para alugar"], ["ambos", "Os dois"]];

// Stable pseudonym from the user id ("Investidor K7Q2"): the same person always
// shows the same name, without revealing who they are.
export function handle(uid) {
  let h = 2166136261;
  for (const ch of String(uid)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";  // no 0/O, 1/I lookalikes
  let s = "";
  for (let i = 0; i < 4; i++) { s += abc[h % abc.length]; h = Math.floor(h / abc.length) || (h ^ 0x9e3779b9) >>> 0; }
  return `Investidor ${s}`;
}

// A card pre-filled from the user's saved strategies (they can edit it).
export function cardFromStrategies(strategies) {
  const on = (strategies || []).filter((s) => s.enabled !== false);
  const union = (key) => [...new Set(on.flatMap((s) => s.sets?.[key]?.values || []))].sort();
  const mins = on.map((s) => s.ranges?.price?.min).filter((v) => v != null && v !== "");
  const maxs = on.map((s) => s.ranges?.price?.max).filter((v) => v != null && v !== "");
  return {
    ufs: union("uf"), kinds: union("kind"), modalities: union("modality"),
    price_min: mins.length ? Math.min(...mins.map(Number)) : null,
    price_max: maxs.length ? Math.max(...maxs.map(Number)) : null,
    ticket_min: null, ticket_max: null, goal: "revenda",
  };
}

// Share of the smaller range covered by the overlap: 1 = one range sits inside
// the other, 0 = no overlap, null = either side left it open.
export function rangeOverlap(a0, a1, b0, b1) {
  const lo0 = a0 ?? 0, lo1 = b0 ?? 0;
  if ((a0 == null && a1 == null) || (b0 == null && b1 == null)) return null;  // no preference on one side
  const hi0 = a1 ?? Infinity, hi1 = b1 ?? Infinity;
  const lo = Math.max(lo0, lo1), hi = Math.min(hi0, hi1);
  if (hi < lo) return 0;
  const shorter = Math.min(hi0 - lo0, hi1 - lo1);
  if (!isFinite(shorter) || shorter <= 0) return 1;  // an open range contains the overlap
  return Math.min(1, (hi - lo) / shorter);
}

// Jaccard index |A∩B| / |A∪B|; an empty list means "any", so it matches fully.
function jaccard(a = [], b = []) {
  if (!a.length || !b.length) return null;
  const A = new Set(a), B = new Set(b);
  const inter = [...A].filter((v) => B.has(v)).length;
  return inter / new Set([...A, ...B]).size;
}

const WEIGHTS = { ufs: 0.35, kinds: 0.25, price: 0.2, ticket: 0.1, modalities: 0.1 };

// How compatible two investors are, 0-100, and what they have in common.
// Each part scores 0..1; parts one side left open are skipped and the
// remaining weights rescaled, so "anything goes" neither helps nor hurts.
export function similarity(a, b) {
  const parts = {
    ufs: jaccard(a.ufs, b.ufs),
    kinds: jaccard(a.kinds, b.kinds),
    modalities: jaccard(a.modalities, b.modalities),
    price: rangeOverlap(a.price_min, a.price_max, b.price_min, b.price_max),
    // tickets need not be equal, only able to sit in the same deal
    ticket: rangeOverlap(a.ticket_min, a.ticket_max, b.ticket_min, b.ticket_max) == null ? null
      : rangeOverlap(a.ticket_min, a.ticket_max, b.ticket_min, b.ticket_max) > 0 ? 1 : 0.4,
  };
  let w = 0, s = 0;
  for (const [k, v] of Object.entries(parts)) if (v != null) { w += WEIGHTS[k]; s += WEIGHTS[k] * v; }
  const common = (x = [], y = []) => (x.length && y.length ? x.filter((v) => y.includes(v)) : x.length ? x : y);
  return {
    score: w ? Math.round((100 * s) / w) : 0,
    parts,
    shared: { ufs: common(a.ufs, b.ufs), kinds: common(a.kinds, b.kinds), modalities: common(a.modalities, b.modalities) },
  };
}

// Same id for the pair whoever invites: one connection per two people.
export const pairId = (u1, u2) => (u1 < u2 ? `${u1}_${u2}` : `${u2}_${u1}`);

// Quota check mirrored by firestore.rules.
export const quotaOk = (q, group) => typeof q === "number" && isFinite(q) && q >= group.quota_min && q <= group.quota_max;

// ---------------------------------------------------------------- shared opportunities
// Which open listings fit a card: state, property type, auction type and price.
// A list left empty means "any". Listings use the compact keys of summary.py.
export function fitsCard(card, x) {
  if (!card) return false;
  if (card.ufs?.length && !card.ufs.includes(x.uf)) return false;
  if (card.kinds?.length && !card.kinds.includes(x.kind)) return false;
  if (card.modalities?.length && !card.modalities.includes(x.modn)) return false;
  if (card.price_min != null && !(x.price >= card.price_min)) return false;
  if (card.price_max != null && !(x.price <= card.price_max)) return false;
  return true;
}

// Listings that fit every card (two partners, or all members of a group).
export function sharedListings(cards, listings) {
  const cs = cards.filter(Boolean);
  return cs.length ? listings.filter((x) => cs.every((c) => fitsCard(c, x))) : [];
}

// How much a set of investors can put in together: the sum of each one's
// maximum ticket (their minimum when no maximum was given). null when any of
// them left it blank, since then nobody knows.
export function combinedTicket(cards) {
  let sum = 0;
  for (const c of cards) {
    const t = c?.ticket_max ?? c?.ticket_min;
    if (t == null) return null;
    sum += t;
  }
  return sum;
}

// Partners ranked by how many open listings fit both them and me; ties broken
// by profile compatibility. Each entry: {uid, card, ids, count, affordable, score}.
export function rankByShared(myCard, cards, listings) {
  const mine = listings.filter((x) => fitsCard(myCard, x));
  return cards.map((c) => {
    const both = mine.filter((x) => fitsCard(c, x));
    const budget = combinedTicket([myCard, c]);
    return {
      uid: c.uid, card: c, ids: both.map((x) => x.id), count: both.length,
      affordable: budget == null ? null : both.filter((x) => x.price <= budget).length,
      score: similarity(myCard, c).score,
    };
  }).sort((a, b) => b.count - a.count || b.score - a.score);
}

// "You have N opportunities that can be shared with M potential partners."
export function sharedSummary(ranked) {
  const ids = new Set();
  let partners = 0;
  for (const r of ranked) if (r.count) { partners++; r.ids.forEach((i) => ids.add(i)); }
  return { opportunities: ids.size, partners };
}

// Risk factors ("pontos de atenção") — the JavaScript twin of
// auction_tracker/risk.py; both are checked against tests/risk_cases.json.
// A points table, not a model: each point names the fact behind it, and
// missing information counts as risk.

const SHARE = /parte ideal|fra[cç][aã]o ideal|^\s*\(\s*\d{1,2}(?:[.,]\d+)?\s*%\s*\)/i;

export const RISK_TEXT = {
  occ: "Imóvel ocupado: desocupação leva meses e tem custo",
  occ_unknown: "Ocupação não informada: confira no edital e visite",
  debts: "Dívidas de condomínio/IPTU ficam com o arrematante",
  debts_unknown: "Não informado quem paga condomínio/IPTU atrasados",
  judicial: "Leilão judicial: prazos do processo e risco de recurso",
  modality_unknown: "Tipo de leilão não identificado",
  share: "Venda de fração do imóvel (parte ideal), não do imóvel inteiro",
  atypical: "Lance muito abaixo do valor estimado: confira área e fração",
  no_value: "Sem estimativa de valor para comparar",
  low_conf: "Estimativa de valor com confiança baixa",
  lawsuit: "Você encontrou ação judicial ligada ao imóvel",
};

export const riskLevel = (points) => (points <= 2 ? "low" : points <= 5 ? "mid" : "high");

export function risk(item, checklist) {
  const ck = checklist || {};
  const f = [];
  const add = (key, pts) => f.push({ key, pts, text: RISK_TEXT[key] });
  if (item.occ === true) add("occ", 3);
  else if (item.occ == null && !ck.occupancy) add("occ_unknown", 2);
  if (item.debts === true) add("debts", 2);
  else if (item.debts == null && !ck.debts) add("debts_unknown", 1);
  if (item.modn === "judicial") add("judicial", 1);
  else if (!item.modn) add("modality_unknown", 1);
  if (SHARE.test(item.title || "")) add("share", 2);
  const val = item.val;
  if (val && val.flag) add("atypical", 2);
  else if (!val) add("no_value", 1);
  else if (val.conf === "baixa") add("low_conf", 1);
  if (ck.lawsuits_result === "found") add("lawsuit", 3);
  const points = f.reduce((s, x) => s + x.pts, 0);
  return { points, level: riskLevel(points), factors: f };
}

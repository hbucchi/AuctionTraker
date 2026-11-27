// Document templates: plain functions from form answers to a document, then
// one renderer to HTML (to read before downloading) and one to PDF (jsPDF).
// Every document is a simplified draft: it says so on top and at the end.
//
// A document: { title, subtitle?, blocks: [ {h} | {p} | {list: [...]} | {table: {head, rows}} | {sign: [{name, sub}]} ] }

export const DRAFT_NOTE = "MINUTA - modelo simplificado gerado pelo AuctionTraker. Não substitui a orientação de um advogado: revise antes de assinar.";

const brl = (n) => (n == null || n === "" || isNaN(Number(n)) ? "R$ ____________" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 }).format(Number(n)));
const pctFmt = (n) => `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(n)}%`;
const blank = (s, n = 30) => (s && String(s).trim() ? String(s).trim() : "_".repeat(n));
const ordinal = (n) => `${n}ª`;

// Shares from committed quotas: each partner's % of the total.
export function shares(members) {
  const total = members.reduce((s, m) => s + (Number(m.quota) || 0), 0);
  return { total, rows: members.map((m) => ({ ...m, pct: total ? (100 * (Number(m.quota) || 0)) / total : 0 })) };
}

function qualification(m) {
  const q = m.qual || {};
  const bits = [q.nationality, q.marital, q.profession].filter(Boolean).join(", ");
  return `${blank(m.name)}${bits ? `, ${bits}` : ", nacionalidade ________, estado civil ________, profissão ________"}, inscrito(a) no CPF sob o nº ${blank(q.cpf, 14)}, residente em ${blank(q.address, 40)}`;
}

// 5a: partnership agreement for buying one property at auction, as co-owners
// (condomínio voluntário, Código Civil arts. 1.314 e seguintes).
export function dealContract({ group, members, terms }) {
  const t = terms || {};
  const { total, rows } = shares(members);
  const leader = rows.find((m) => m.role === "leader") || rows[0] || { name: "" };
  const majority = Number(t.sale_majority_pct) || 51;
  const clause = (() => { let n = 0; return (title) => ({ h: `CLÁUSULA ${ordinal(++n)} - ${title}` }); })();
  const purpose = { revenda: "revenda do imóvel", aluguel: "locação do imóvel", decidir: "destinação a ser decidida pelos SÓCIOS" }[t.purpose || "revenda"];
  return {
    title: "INSTRUMENTO PARTICULAR DE PARCERIA PARA AQUISIÇÃO DE IMÓVEL EM LEILÃO",
    subtitle: group?.name ? `Grupo: ${group.name}` : "",
    blocks: [
      { p: "Pelo presente instrumento particular, as partes abaixo qualificadas, doravante denominadas SÓCIOS, ajustam entre si a presente parceria, que se regerá pelas cláusulas seguintes:" },
      ...rows.map((m, i) => ({ p: `${i + 1}. ${qualification(m)}, titular de ${pctFmt(m.pct)} desta parceria, correspondente ao aporte de ${brl(m.quota)}${m.role === "leader" ? ", doravante também denominado(a) ADMINISTRADOR(A)" : ""}.` })),
      clause("DO OBJETO"),
      { p: `A parceria tem por objeto a união de recursos para a aquisição, em leilão, do imóvel ${blank(t.property_title || group?.target_title, 40)}${t.property_url || group?.target_url ? ` (anúncio: ${t.property_url || group?.target_url})` : ""}, e sua posterior ${purpose}.` },
      { p: `O imóvel será adquirido e registrado em nome de todos os SÓCIOS, em condomínio voluntário, na proporção das participações indicadas acima, nos termos dos arts. 1.314 e seguintes do Código Civil.` },
      clause("DOS APORTES"),
      { table: { head: ["Sócio", "Aporte", "Participação"], rows: [...rows.map((m) => [blank(m.name, 20), brl(m.quota), pctFmt(m.pct)]), ["Total", brl(total), "100%"]] } },
      { p: `Os aportes serão depositados até ${blank(t.deposit_days, 3)} dias antes da data do leilão na conta indicada pelo(a) ADMINISTRADOR(A), que prestará contas de sua utilização a todos os SÓCIOS.` },
      { p: `Não havendo arrematação, os valores serão devolvidos integralmente a cada SÓCIO em até ${blank(t.refund_days, 3)} dias após o leilão.` },
      clause("DA REPRESENTAÇÃO NO LEILÃO"),
      { p: `Os SÓCIOS autorizam ${blank(leader.name)} a representá-los no leilão e a ofertar lances até o limite de ${brl(t.max_bid)}. Lances acima desse valor dependem da concordância por escrito de todos os SÓCIOS.` },
      clause("DAS DESPESAS"),
      { p: "Comissão do leiloeiro, ITBI, registro, certidões, eventuais débitos de condomínio e IPTU, desocupação, reforma, manutenção e demais despesas do imóvel serão suportadas pelos SÓCIOS na proporção de suas participações." },
      { p: `Novos aportes necessários serão comunicados pelo(a) ADMINISTRADOR(A) com prazo mínimo de ${blank(t.call_days, 3)} dias. O SÓCIO que não realizar o aporte no prazo poderá ter sua participação ajustada proporcionalmente, por decisão dos demais.` },
      clause("DAS DECISÕES E DA VENDA"),
      { p: `As decisões sobre a administração, a reforma, a locação e a venda do imóvel serão tomadas por SÓCIOS que representem, no mínimo, ${pctFmt(majority)} das participações.${t.min_sale_price ? ` O imóvel não será vendido por valor inferior a ${brl(t.min_sale_price)} sem a concordância de todos os SÓCIOS.` : ""}` },
      { p: "O SÓCIO que desejar vender sua participação deverá oferecê-la primeiro aos demais SÓCIOS, que terão preferência nas mesmas condições oferecidas a terceiros (art. 504 do Código Civil)." },
      clause("DO RESULTADO"),
      { p: "O resultado da venda ou da locação, deduzidas as despesas, será distribuído aos SÓCIOS na proporção de suas participações. Cada SÓCIO é responsável pelos tributos incidentes sobre sua parte." },
      clause("DO PRAZO"),
      { p: `A parceria vigorará até a venda do imóvel e a distribuição do resultado${t.term_months ? `, com previsão de ${t.term_months} meses` : ""}.` },
      clause("DO FORO"),
      { p: `Fica eleito o foro da comarca de ${blank(t.forum_city, 20)} para dirimir quaisquer questões decorrentes deste instrumento.` },
      ...(t.notes ? [clause("DISPOSIÇÕES ADICIONAIS"), { p: t.notes }] : []),
      { p: `E, por estarem de acordo, as partes assinam o presente instrumento em ${rows.length + 1} vias de igual teor, na presença de duas testemunhas.` },
      { p: `${blank(t.place, 20)}, ____ de ______________ de ______.` },
      { sign: [...rows.map((m) => ({ name: blank(m.name, 24), sub: `CPF: ${blank(m.qual?.cpf, 14)}` })), { name: "Testemunha 1", sub: "Nome e CPF: ____________________" }, { name: "Testemunha 2", sub: "Nome e CPF: ____________________" }] },
    ],
  };
}

// 5b: the standard templates of the "Modelos e serviços" tab. Each has a form
// (fields) and a builder. Field types: text, number, money, textarea, date.
export const TEMPLATES = [
  {
    id: "parceria", title: "Contrato de parceria entre sócios",
    desc: "Para comprar um imóvel em leilão com outras pessoas: participações, aportes, quem dá o lance, despesas e regras de venda.",
    fields: [
      ["partners", "Sócios (um por linha: nome; aporte em R$)", "textarea", "Ana Souza; 150000\nBruno Lima; 100000"],
      ["property_title", "Imóvel", "text", ""], ["property_url", "Link do leilão", "text", ""],
      ["max_bid", "Lance máximo autorizado (R$)", "money", ""], ["purpose", "Destinação (revenda, aluguel ou decidir)", "text", "revenda"],
      ["deposit_days", "Aportes até quantos dias antes do leilão", "number", "3"], ["refund_days", "Devolução em até quantos dias se não arrematar", "number", "5"],
      ["call_days", "Prazo para novos aportes (dias)", "number", "10"], ["sale_majority_pct", "Maioria para decisões (% das participações)", "number", "51"],
      ["min_sale_price", "Preço mínimo de venda (R$, opcional)", "money", ""], ["forum_city", "Foro (cidade)", "text", ""], ["place", "Local da assinatura", "text", ""],
    ],
    build: (v) => {
      const members = String(v.partners || "").split("\n").map((l) => l.split(";")).filter((p) => p[0] && p[0].trim())
        .map(([name, quota], i) => ({ name: name.trim(), quota: Number(String(quota || "").replace(/[^\d.,]/g, "").replace(/\./g, "").replace(",", ".")) || 0, role: i === 0 ? "leader" : "member" }));
      return dealContract({ group: null, members, terms: v });
    },
  },
  {
    id: "procuracao", title: "Procuração para representação em leilão",
    desc: "Autoriza outra pessoa a dar lances e assinar o auto de arrematação em seu nome, até um valor máximo.",
    fields: [
      ["grantor", "Outorgante (quem dá os poderes)", "text", ""], ["grantor_cpf", "CPF do outorgante", "text", ""],
      ["agent", "Outorgado (quem vai representar)", "text", ""], ["agent_cpf", "CPF do outorgado", "text", ""],
      ["property_title", "Imóvel / lote", "text", ""], ["auctioneer", "Leiloeiro ou site", "text", ""],
      ["max_bid", "Lance máximo (R$)", "money", ""], ["valid_until", "Válida até", "date", ""], ["place", "Local", "text", ""],
    ],
    build: (v) => ({
      title: "PROCURAÇÃO PARA REPRESENTAÇÃO EM LEILÃO",
      blocks: [
        { p: `OUTORGANTE: ${blank(v.grantor)}, inscrito(a) no CPF sob o nº ${blank(v.grantor_cpf, 14)}.` },
        { p: `OUTORGADO(A): ${blank(v.agent)}, inscrito(a) no CPF sob o nº ${blank(v.agent_cpf, 14)}.` },
        { h: "PODERES" },
        { p: `Para representar o(a) OUTORGANTE no leilão do imóvel ${blank(v.property_title, 40)}, realizado por ${blank(v.auctioneer, 24)}, podendo cadastrar-se, ofertar lances até o valor máximo de ${brl(v.max_bid)}, assinar o auto de arrematação, efetuar pagamentos com recursos do(a) OUTORGANTE e praticar os demais atos necessários a esse fim.` },
        { p: `Esta procuração é válida até ${blank(v.valid_until ? new Date(v.valid_until + "T12:00").toLocaleDateString("pt-BR") : "", 12)} e não autoriza lances acima do valor indicado.` },
        { p: `${blank(v.place, 20)}, ____ de ______________ de ______.` },
        { sign: [{ name: blank(v.grantor, 24), sub: "Outorgante (assinatura com firma reconhecida, se exigido pelo leiloeiro)" }] },
      ],
    }),
  },
  {
    id: "proposta", title: "Proposta de compra direta",
    desc: "Para imóveis em venda direta ou que não tiveram lances: valor, forma de pagamento e prazo da proposta.",
    fields: [
      ["buyer", "Proponente", "text", ""], ["buyer_cpf", "CPF", "text", ""], ["seller", "Vendedor (banco, comitente)", "text", ""],
      ["property_title", "Imóvel", "text", ""], ["offer", "Valor oferecido (R$)", "money", ""],
      ["payment", "Forma de pagamento", "text", "à vista, em até 5 dias após o aceite"], ["valid_days", "Proposta válida por (dias)", "number", "10"], ["place", "Local", "text", ""],
    ],
    build: (v) => ({
      title: "PROPOSTA DE COMPRA DE IMÓVEL",
      blocks: [
        { p: `À ${blank(v.seller, 30)}.` },
        { p: `Eu, ${blank(v.buyer)}, inscrito(a) no CPF sob o nº ${blank(v.buyer_cpf, 14)}, apresento proposta de compra do imóvel ${blank(v.property_title, 40)}, nas seguintes condições:` },
        { list: [`Valor: ${brl(v.offer)}.`, `Pagamento: ${blank(v.payment, 30)}.`, "Despesas de transferência (ITBI e registro) por conta do comprador, salvo acordo em contrário.", "O imóvel é adquirido no estado em que se encontra, conforme as condições de venda do vendedor.", `Validade da proposta: ${blank(v.valid_days, 3)} dias a contar desta data.`] },
        { p: `${blank(v.place, 20)}, ____ de ______________ de ______.` },
        { sign: [{ name: blank(v.buyer, 24), sub: "Proponente" }] },
      ],
    }),
  },
  {
    id: "notificacao", title: "Notificação extrajudicial ao ocupante",
    desc: "Comunica ao ocupante que o imóvel foi arrematado e propõe prazo para desocupação amigável, antes de qualquer ação judicial.",
    fields: [
      ["owner", "Novo proprietário (arrematante)", "text", ""], ["occupant", "Ocupante (nome, se souber)", "text", ""],
      ["address", "Endereço do imóvel", "text", ""], ["registry", "Matrícula e cartório", "text", ""],
      ["days", "Prazo para desocupar (dias)", "number", "30"], ["contact", "Contato para combinar a saída", "text", ""], ["place", "Local", "text", ""],
    ],
    build: (v) => ({
      title: "NOTIFICAÇÃO EXTRAJUDICIAL",
      blocks: [
        { p: `NOTIFICANTE: ${blank(v.owner)}.` },
        { p: `NOTIFICADO(A): ${blank(v.occupant, 24)}, ocupante do imóvel situado em ${blank(v.address, 40)}.` },
        { p: `Pela presente, comunicamos que o imóvel acima, registrado sob ${blank(v.registry, 30)}, foi adquirido pelo(a) NOTIFICANTE em leilão, conforme documentação disponível para consulta.` },
        { p: `Solicitamos a desocupação voluntária do imóvel no prazo de ${blank(v.days, 3)} dias a contar do recebimento desta notificação, com a entrega das chaves. Estamos à disposição para combinar a data e as condições da saída pelo contato ${blank(v.contact, 24)}.` },
        { p: "Não havendo desocupação no prazo, o(a) NOTIFICANTE poderá adotar as medidas judiciais cabíveis para a imissão na posse, sem prejuízo da cobrança de taxa de ocupação prevista em lei." },
        { p: `${blank(v.place, 20)}, ____ de ______________ de ______.` },
        { sign: [{ name: blank(v.owner, 24), sub: "Notificante" }, { name: "Recebido por", sub: "Nome, data e assinatura: ______________" }] },
      ],
    }),
  },
  {
    id: "recibo", title: "Recibo de aporte entre sócios",
    desc: "Comprova que um sócio depositou sua parte para a compra ou para despesas do imóvel.",
    fields: [
      ["payer", "Sócio que fez o aporte", "text", ""], ["receiver", "Quem recebeu (administrador)", "text", ""],
      ["amount", "Valor (R$)", "money", ""], ["purpose", "Referente a", "text", "aporte para arrematação do imóvel"], ["place", "Local", "text", ""],
    ],
    build: (v) => ({
      title: "RECIBO DE APORTE",
      blocks: [
        { p: `Recebi de ${blank(v.payer)} a quantia de ${brl(v.amount)}, referente a ${blank(v.purpose, 30)}, conforme o contrato de parceria entre os sócios.` },
        { p: `${blank(v.place, 20)}, ____ de ______________ de ______.` },
        { sign: [{ name: blank(v.receiver, 24), sub: "Recebedor(a)" }] },
      ],
    }),
  },
  {
    id: "checklist", title: "Checklist de due diligence",
    desc: "Lista para imprimir e levar ao cartório, ao condomínio e à visita.",
    fields: [["property_title", "Imóvel", "text", ""]],
    build: (v) => ({
      title: "CHECKLIST DE DUE DILIGENCE - IMÓVEL EM LEILÃO",
      subtitle: v.property_title ? `Imóvel: ${v.property_title}` : "",
      blocks: [
        { h: "Edital" }, { list: ["[  ] Forma de pagamento, prazo e comissão do leiloeiro", "[  ] Quem paga condomínio, IPTU e outras dívidas", "[  ] Se o imóvel está ocupado e quem desocupa", "[  ] Possibilidade de financiamento ou parcelamento", "[  ] Ações mencionadas (ex-mutuário, embargos, anulatória)"] },
        { h: "Cartório" }, { list: ["[  ] Matrícula atualizada (ônus, penhoras, indisponibilidades)", "[  ] Certidão de ônus reais", "[  ] Área e descrição batem com o anúncio"] },
        { h: "Prefeitura e condomínio" }, { list: ["[  ] Débitos de IPTU", "[  ] Débitos de condomínio (declaração do síndico)", "[  ] Regularidade da construção (habite-se)"] },
        { h: "Justiça" }, { list: ["[  ] Ações do ex-proprietário contra o banco/credor", "[  ] Processos que envolvam o imóvel"] },
        { h: "Visita" }, { list: ["[  ] Estado de conservação por fora", "[  ] Vizinhança, acesso e transporte", "[  ] Ocupação confirmada (conversar com porteiro ou vizinhos)"] },
      ],
    }),
  },
];

// ---------------------------------------------------------------- renderers
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function docHTML(d) {
  const b = d.blocks.map((x) => {
    if (x.h) return `<h4>${esc(x.h)}</h4>`;
    if (x.p) return `<p>${esc(x.p)}</p>`;
    if (x.list) return `<ul>${x.list.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
    if (x.table) return `<table><thead><tr>${x.table.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${x.table.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    if (x.sign) return `<div class="doc-sign">${x.sign.map((s) => `<div><span class="ln"></span><b>${esc(s.name)}</b><small>${esc(s.sub || "")}</small></div>`).join("")}</div>`;
    return "";
  }).join("");
  return `<article class="doc"><p class="doc-draft">${esc(DRAFT_NOTE)}</p><h3>${esc(d.title)}</h3>${d.subtitle ? `<p class="doc-sub">${esc(d.subtitle)}</p>` : ""}${b}</article>`;
}

// PDF with jsPDF (A4, Helvetica). Returns the jsPDF document.
export function docPDF(d, JsPDF) {
  const pdf = new JsPDF({ unit: "mm", format: "a4" });
  const W = 210, M = 20, maxW = W - 2 * M;
  let y = M;
  const room = (h) => { if (y + h > 297 - M) { pdf.addPage(); y = M; } };
  const text = (s, size, style = "normal", gap = 2, align = "left") => {
    pdf.setFont("helvetica", style); pdf.setFontSize(size);
    const lines = pdf.splitTextToSize(s, maxW);
    const lh = size * 0.42;
    for (const ln of lines) { room(lh); pdf.text(ln, align === "center" ? W / 2 : M, y, { align }); y += lh; }
    y += gap;
  };
  pdf.setTextColor(120, 90, 40); text(DRAFT_NOTE, 8, "italic", 4); pdf.setTextColor(20, 20, 20);
  text(d.title, 13, "bold", d.subtitle ? 1 : 5, "center");
  if (d.subtitle) text(d.subtitle, 10, "normal", 5, "center");
  for (const x of d.blocks) {
    if (x.h) { y += 2; text(x.h, 10.5, "bold", 1.5); }
    else if (x.p) text(x.p, 10.5, "normal", 2.5);
    else if (x.list) { for (const i of x.list) text(`•  ${i}`, 10.5, "normal", 1); y += 2; }
    else if (x.table) {
      const cw = [maxW * 0.5, maxW * 0.28, maxW * 0.22];
      const row = (cells, bold) => {
        room(7); pdf.setFont("helvetica", bold ? "bold" : "normal"); pdf.setFontSize(10);
        let xx = M;
        cells.forEach((c, i) => { pdf.text(pdf.splitTextToSize(String(c), cw[i] - 2)[0], i === 0 ? xx : xx + cw[i] - 2, y, { align: i === 0 ? "left" : "right" }); xx += cw[i]; });
        y += 6; pdf.setDrawColor(220); pdf.line(M, y - 4.2, M + maxW, y - 4.2);
      };
      row(x.table.head, true); x.table.rows.forEach((r, i) => row(r, i === x.table.rows.length - 1)); y += 3;
    } else if (x.sign) {
      y += 6;
      for (const s of x.sign) {
        room(22); y += 12;
        pdf.setDrawColor(60); pdf.line(M, y, M + 90, y);
        pdf.setFont("helvetica", "bold"); pdf.setFontSize(10); pdf.text(s.name, M, y + 5);
        pdf.setFont("helvetica", "normal"); pdf.setFontSize(9); pdf.text(s.sub || "", M, y + 9.5);
        y += 12;
      }
    }
  }
  const pages = pdf.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    pdf.setPage(i); pdf.setFont("helvetica", "normal"); pdf.setFontSize(8); pdf.setTextColor(130);
    pdf.text(`Minuta gerada pelo AuctionTraker · página ${i} de ${pages}`, W / 2, 297 - 10, { align: "center" });
  }
  return pdf;
}

// File name from a title: lowercase, ASCII, hyphens.
export const fileName = (title) => `${title.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 60).replace(/^-+|-+$/g, "")}.pdf`;

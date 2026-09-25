/* Oversiktsseksjonen: dagens bilde, priset inn, idéer, risikobarometer, rentedifferanser, kildestatus. */
import { nb, nb0, nb1, nb2, pct, pct1, rate, signed, bp, cls, shortDate, daysUntil, color, name } from "./format.js";
import { extremeText } from "./calc.js";
import { barCell } from "./charts.js";

const tile = (label, val, sub, extra = "") =>
  `<div class="risk-tile ${extra}"><div class="label">${label}</div><div class="val">${val}</div><div class="sub">${sub}</div></div>`;

/** Fire–seks tall som gir leseren et sted å starte. */
export function renderToday(countries, market) {
  const tiles = [];
  const movers = countries.filter((c) => c.fx && !c.fx.index && c.fx.changes?.w1 != null).sort((a, b) => b.fx.changes.w1 - a.fx.changes.w1);
  if (movers.length >= 2) {
    const b = movers[0], w = movers[movers.length - 1];
    tiles.push(tile("Uken mot NOK", `<span class="pos">▲ ${b.currency} ${pct1(b.fx.changes.w1)}</span>`,
      `<span class="neg">▼ ${w.currency} ${pct1(w.fx.changes.w1)}</span>`));
  }
  const rep = countries.filter((c) => c.curve?.repricing?.w1 != null).sort((a, b) => Math.abs(b.curve.repricing.w1) - Math.abs(a.curve.repricing.w1));
  if (rep.length) {
    const r = rep[0].curve.repricing.w1;
    tiles.push(tile("Størst reprising siste uke", `${name(rep[0])} <span class="${cls(r)}">${bp(r)}</span>`, r > 0 ? "12-mnd-prising, mer haukete" : "12-mnd-prising, mer duete"));
  }
  const withCurve = countries.filter((c) => c.curve).sort((a, b) => a.curve.implied["12m"] - b.curve.implied["12m"]);
  if (withCurve.length >= 2) {
    const d = withCurve[0], h = withCurve[withCurve.length - 1];
    tiles.push(tile("Priset innen 12 mnd", `${h.flag} ${h.currency} <span class="${cls(h.curve.implied["12m"])}">${bp(h.curve.implied["12m"])}</span>`,
      `minst: ${d.flag} ${d.currency} ${bp(d.curve.implied["12m"])}`));
  }
  const carry = countries.filter((c) => c.fwd_fx_1y).sort((a, b) => b.fwd_fx_1y.diff - a.fwd_fx_1y.diff);
  if (carry.length) {
    const c = carry[0];
    tiles.push(tile("Høyest 1-års rente vs. NOK", `${name(c)} <span class="${cls(c.fwd_fx_1y.diff)}">${signed(c.fwd_fx_1y.diff, nb2)} pp</span>`,
      `lavest: ${carry[carry.length - 1].currency} ${signed(carry[carry.length - 1].fwd_fx_1y.diff, nb2)} pp`));
  }
  if (market.vix) {
    const v = market.vix.value, aj = market.audjpy?.changes?.m1;
    // Enkel poengsum: lav VIX og stigende AUD/JPY = på, høy VIX og fallende AUD/JPY = av
    const score = (v < 18 ? 1 : v > 25 ? -1 : 0) + (aj == null ? 0 : aj > 1 ? 1 : aj < -2 ? -1 : 0);
    const mode = score > 0 ? ["på", "pos"] : score < 0 ? ["av", "neg"] : ["nøytral", ""];
    tiles.push(tile("Risikoappetitt", `<span class="${mode[1]}">${mode[0]}</span>`, `VIX ${nb1.format(v)} · AUD/JPY 1m ${pct1(aj)}`));
  }
  const next = countries.filter((c) => c.meeting).sort((a, b) => a.meeting.localeCompare(b.meeting))[0];
  if (next) {
    const d = daysUntil(next.meeting);
    tiles.push(tile("Neste rentemøte", `${next.flag} ${next.bank}`, `${shortDate(next.meeting)} · ${d === 0 ? "i dag" : `om ${d} dager`}`));
  }
  document.getElementById("today").innerHTML = tiles.join("");
}

/** Tabell: priset endring i den korte renten per sentralbank ved 3/6/12/24 mnd. */
export function renderPriced(countries) {
  const rows = countries.filter((c) => c.curve);
  const missing = countries.filter((c) => !c.curve).map((c) => c.currency);
  const panel = document.getElementById("pricedTable");
  if (!rows.length) { panel.innerHTML = `<p class="risk-note">Ingen rentekurver tilgjengelig ennå.</p>`; return; }
  const sorted = [...rows].sort((a, b) => a.curve.implied["12m"] - b.curve.implied["12m"]);
  const maxAbs = Math.max(25, ...rows.flatMap((c) => Object.values(c.curve.implied).map(Math.abs)));
  const cell = (v) => {
    const moves = v == null ? 0 : Math.round(Math.abs(v) / 25);
    const sub = v == null ? "" : `<small>${moves ? `≈ ${moves} ${v < 0 ? "kutt" : "hev."}` : "uendret"}</small>`;
    return barCell(v, maxAbs, bp(v), cls(v, 9), sub);
  };
  const body = sorted.map((c) => {
    const i = c.curve.implied, rep = c.curve.repricing?.w1;
    return `<tr>
      <td title="${c.curve.source} · ${c.curve.date}"><span class="dot" style="background:${color(c)}"></span>${c.flag} ${c.bank}${c.curve.synthetic_anchor ? "<sup>*</sup>" : ""}</td>
      <td>${rate(c.rates.policy)}</td>
      ${cell(i["3m"])}${cell(i["6m"])}${cell(i["12m"])}${cell(i["24m"])}
      <td class="extreme">${extremeText(c.curve)}</td>
      <td class="${cls(rep, 4)}">${bp(rep)}</td>
    </tr>`;
  }).join("");
  const stars = rows.some((c) => c.curve.synthetic_anchor) ? ` <sup>*</sup>Kurven mangler punkter under 6 mnd; 3-mnd-renten er satt lik styringsrenten.` : "";
  panel.innerHTML = `
    <div class="table-scroll"><table class="diff-table priced-table">
      <thead><tr><th>Sentralbank</th><th>Nå</th><th>3 mnd</th><th>6 mnd</th><th>12 mnd</th><th>24 mnd</th><th>Ytterpunkt</th><th>Repris. 1 u</th></tr></thead>
      <tbody>${body}</tbody>
    </table></div>
    <p class="risk-note">Sortert fra mest kutt til mest heving. «Repris. 1 u» = endring i 12-mnd-prisingen siste uke (positivt = mer haukete).
      ${missing.length ? `Ingen daglig kurve for ${missing.join(", ")}.` : ""}${stars}</p>
    <details class="method"><summary>Slik regnes det</summary>
      <p>Priset endring i den korte renten = 3-mnd terminrente ved horisonten minus dagens 3-mnd-rente, regnet fra OIS- eller
      statskurven (kilde i tooltip på banknavnet). Terminrenter inneholder terminpremie, så tallene viser retning og størrelse på
      det som er priset – ikke sannsynligheter. Søylene er skalert mot største utslag i tabellen.</p></details>`;
}

/** Automatisk genererte observasjoner – inspirasjon til videre graving, ikke anbefalinger. */
export function renderIdeas(countries, market) {
  const ideas = [];
  const withCurve = countries.filter((c) => c.curve);
  const i12 = (c) => c.curve.implied["12m"];
  if (withCurve.length >= 2) {
    const by12 = [...withCurve].sort((a, b) => i12(a) - i12(b));
    const dove = by12[0], hawk = by12[by12.length - 1], gap = i12(hawk) - i12(dove);
    if (gap >= 25) ideas.push({ tag: "Sprik i renteforventninger", text:
      `${i12(dove) < 0 ? "Mest lettelser priset" : "Minst innstramming priset"}: <b>${name(dove)}</b> (${bp(i12(dove))} innen 12 mnd).
       ${i12(hawk) > 0 ? "Mest innstramming" : "Minst lettelser"}: <b>${name(hawk)}</b> (${bp(i12(hawk))}). Markedet venter altså at
       rentedifferansen ${hawk.currency}–${dove.currency} øker med ${gap} bp det neste året. Tror du på det motsatte, er
       ${hawk.currency}/${dove.currency} krysset å se på.` });
    const rep = withCurve.filter((c) => c.curve.repricing?.w1 != null).sort((a, b) => Math.abs(b.curve.repricing.w1) - Math.abs(a.curve.repricing.w1));
    if (rep.length && Math.abs(rep[0].curve.repricing.w1) >= 8) {
      const r = rep[0].curve.repricing.w1;
      ideas.push({ tag: "Reprising", text: `Størst bevegelse i forventningene siste uke: <b>${name(rep[0])}</b>, der 12-mnd-prisingen har
        flyttet seg ${bp(r)} (${r > 0 ? "mer haukete" : "mer duete"}). Momentum i renteforventninger smitter ofte over på valutaen –
        sjekk om kursen har hengt med.` });
    }
    for (const c of withCurve) {
      const cpi = c.cpi?.value;
      if (cpi == null) continue;
      if (i12(c) <= -25 && cpi >= 3) ideas.push({ tag: "Kutt tross høy inflasjon", text: `<b>${name(c)}</b>: ${bp(i12(c))} priset innen 12 mnd
        selv om KPI er ${nb1.format(cpi)} %. Skuffer ikke inflasjonen på nedsiden, kan kuttene prises ut igjen – det ville støtte ${c.currency}.` });
      else if (i12(c) >= 25 && cpi <= 1.5) ideas.push({ tag: "Hevinger tross lav inflasjon", text: `<b>${name(c)}</b>: ${bp(i12(c))} priset
        innen 12 mnd med KPI på bare ${nb1.format(cpi)} %. Uteblir hevingene, er ${c.currency} sårbar for at prisingen reverserer.` });
    }
  }
  const carry = countries.filter((c) => c.fwd_fx_1y).sort((a, b) => b.fwd_fx_1y.diff - a.fwd_fx_1y.diff);
  if (carry.length >= 2) {
    const hi = carry[0], lo = carry[carry.length - 1];
    ideas.push({ tag: "Carry mot NOK", text: `Høyest 1-års rente relativt til NOK: <b>${name(hi)}</b> (${signed(hi.fwd_fx_1y.diff, nb2)} pp;
      terminen ligger ${pct(hi.fwd_fx_1y.pct)} fra spot). Lavest: <b>${name(lo)}</b> (${signed(lo.fwd_fx_1y.diff, nb2)} pp). Å eie NOK mot
      ${lo.currency} gir ${nb2.format(-lo.fwd_fx_1y.diff)} pp i årlig carry; terminkursen ${nb.format(lo.fwd_fx_1y.rate)} er breakeven.` });
  }
  const crowded = countries.filter((c) => c.cot?.pct_oi != null && Math.abs(c.cot.pct_oi) >= 25).sort((a, b) => Math.abs(b.cot.pct_oi) - Math.abs(a.cot.pct_oi));
  if (crowded.length) {
    const c = crowded[0];
    ideas.push({ tag: "Posisjonering", text: `Spekulantene er tungt <b>${c.cot.net > 0 ? "long" : "short"} ${name(c)}</b> (${signed(c.cot.pct_oi)} % av
      åpen interesse). Ensidig posisjonering øker faren for brå reversering – en kontrær vinkel, særlig rundt neste rentemøte (${shortDate(c.meeting)}).` });
  }
  const no = countries.find((c) => c.id === "no");
  if (no?.curve) {
    const corr = market?.brent_nok_corr;
    ideas.push({ tag: "Norges Bank", text: `Markedet priser <b>${bp(i12(no))} innen 12 mnd</b> for Norges Bank (${extremeText(no.curve)}). Neste møte
      ${shortDate(no.meeting)}.${market?.brent ? ` Brent ${nb0.format(market.brent.value)} USD${corr != null ? `, 90-dagers korrelasjon olje↔krone ${nb2.format(corr)}` : ""}.` : ""}` });
  }
  document.getElementById("ideas").innerHTML = ideas.slice(0, 6).map((i) => `<div class="idea"><div class="tag">${i.tag}</div><div>${i.text}</div></div>`).join("")
    || `<p class="risk-note">For lite kurvedata til å generere observasjoner ennå.</p>`;
}

export function renderRisk(market) {
  const chg = (v) => `1m <span class="${cls(v)}">${pct1(v)}</span>`;
  const tiles = [];
  if (market.audjpy) tiles.push(tile("AUD/JPY (risk on/off)", nb2.format(market.audjpy.value), chg(market.audjpy.changes?.m1)));
  if (market.vix) tiles.push(tile("VIX", nb2.format(market.vix.value), chg(market.vix.changes?.m1)));
  if (market.brent) tiles.push(tile("Brent (USD)", nb2.format(market.brent.value), chg(market.brent.changes?.m1)));
  document.getElementById("riskTiles").innerHTML = tiles.join("");
  if (market.brent_nok_corr != null) {
    document.getElementById("riskPanel").insertAdjacentHTML("beforeend", `<p class="risk-note">Stigende AUD/JPY og fallende VIX = risikoappetitt,
      som normalt støtter NOK. 90-dagers korrelasjon Brent↔kronestyrke: <b>${nb2.format(market.brent_nok_corr)}</b>.</p>`);
  }
}

export function renderDiffs(countries) {
  const norway = countries.find((c) => c.id === "no");
  if (!norway) return;
  const cell = (a, b) => (a == null || b == null ? `<td>–</td>` : `<td class="${cls(a - b, 0.05)}">${signed(a - b, nb2)}</td>`);
  const rows = countries.filter((c) => c.id !== "no").map((c) => `<tr>
      <td>${name(c)}</td>${cell(c.rates.policy, norway.rates.policy)}${cell(c.rates.m3, norway.rates.m3)}${cell(c.rates.y10, norway.rates.y10)}
      <td class="${cls(c.fwd_fx_1y?.pct)}">${c.fwd_fx_1y ? pct(c.fwd_fx_1y.pct) : "–"}</td></tr>`).join("");
  document.getElementById("diffTable").innerHTML = `
    <table class="diff-table">
      <thead><tr><th>Valuta</th><th>Styringsrente</th><th>3 mnd</th><th>10 år</th><th>1å termin vs. spot</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="risk-note">Positiv differanse = høyere rente enn Norge → isolert sett støtte for valutaen mot NOK.</p>
    <details class="method"><summary>Slik regnes det</summary><p>Terminkursen følger av rentedifferansen for 1 år (dekket renteparitet)
      og er breakeven for en carry-handel, ikke en prognose.</p></details>`;
}

/** Kildestatus i bunnteksten: hvor gamle dataene fra hver kilde er. */
export function renderSources(sources, updated) {
  const el = document.getElementById("sources");
  if (!el || !sources) return;
  const labels = { fx: "Valutakurser (ECB)", i44: "I-44 (Norges Bank)", policy: "Styringsrenter (BIS)", irlt: "10-års renter (OECD)",
    ir3: "3-mnd renter (OECD)", cpi: "KPI (OECD/Eurostat)", unemployment: "Ledighet (OECD/Eurostat)", brent: "Brent (FRED)", vix: "VIX (FRED)",
    cot: "COT (CFTC)", ppp: "PPP (World Bank)", curve_us: "Kurve USD", curve_ea: "Kurve EUR", curve_jp: "Kurve JPY", curve_gb: "Kurve GBP",
    curve_ca: "Kurve CAD", curve_au: "Kurve AUD", curve_se: "Kurve SEK", curve_no: "Kurve NOK" };
  const today = new Date(updated);
  const age = (iso) => (iso ? Math.round((today - new Date(iso.length === 4 ? `${iso}-12-31` : iso.length === 7 ? `${iso}-28` : iso)) / 86400000) : null);
  const limit = (k) => (k === "ppp" ? 800 : k === "cot" ? 14 : ["irlt", "ir3", "cpi", "unemployment"].includes(k) ? 75 : 10);
  const items = Object.entries(sources).map(([k, s]) => {
    const a = age(s.latest);
    const stale = !s.ok || a == null || a > limit(k);
    return { label: labels[k] || k, ok: s.ok, latest: s.latest, stale, error: s.error };
  });
  const bad = items.filter((i) => i.stale);
  el.innerHTML = `<details class="method"><summary>Kildestatus: ${items.length - bad.length} av ${items.length} oppdatert${bad.length ? ` · <span class="neg">${bad.length} bak</span>` : ""}</summary>
    <ul class="sources">${items.map((i) => `<li class="${i.stale ? "neg" : ""}">${i.stale ? "⚠" : "✓"} ${i.label}: ${i.latest ?? "ingen data"}${i.ok ? "" : ` (feilet: ${i.error ?? "ukjent"})`}</li>`).join("")}</ul></details>`;
}

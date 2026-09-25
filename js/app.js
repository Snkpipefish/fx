/* G10 Valutadashboard – leser data/*.json og rendrer oversikt + landskort. */

const nb = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 4 });
const nb0 = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });
const nb1 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nb2 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb2.format(v)} %`);
const pct1 = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb1.format(v)} %`);
const rate = (v) => (v == null ? "–" : `${nb2.format(v)} %`);
const signed = (v, fmt = nb1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${fmt.format(v)}`);
const thousands = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb1.format(v / 1000)}k`);
const bp = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb0.format(v)} bp`);
const cls = (v, dead = 0) => (v == null ? "" : v > dead ? "pos" : v < -dead ? "neg" : "");

const dateFmt = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "short" });

// Fast farge per land, så sammenligningsgrafen og rentebanen bruker samme farger
const COLORS = {
  us: "#2563eb", ea: "#f59e0b", jp: "#10b981", gb: "#ef4444", ch: "#8b5cf6",
  ca: "#06b6d4", au: "#ec4899", nz: "#84cc16", se: "#f97316", no: null, // no = tekstfargen
};

let cssVar;
const color = (c) => COLORS[c.id] ?? cssVar("--text");
const name = (c) => `${c.flag} ${c.currency}`;

function changeChip(label, value, invert) {
  const shown = value == null ? null : invert ? -value : value;
  return `<span class="chip">${label} <b class="${cls(shown)}">${pct(shown)}</b></span>`;
}

/** «bunn 3,10 % om 14 mnd» – ytterpunktet i den impliserte rentebanen. */
function extremeText(curve) {
  const e = curve?.extreme;
  if (!e) return "";
  if (Math.abs(e.bp) < 10) return `flat bane neste 2 år`;
  return `${e.bp < 0 ? "bunn" : "topp"} ${rate(e.level)} om ${e.months} mnd`;
}

/**
 * Datadrevet retningssignal for valutaen (heuristikk, ikke prognose):
 *  - rentesignal: hva rentekurven priser av endringer neste 6 mnd
 *                 (fallback: 3 mnd-rente minus styringsrente)
 *  - momentum:    kursutvikling mot NOK siste 3 mnd
 *  - realrente:   styringsrente minus KPI å/å
 */
function directionSignal(c) {
  const invert = c.fx?.index; // I-44: lavere indeks = sterkere krone
  const parts = [];
  let score = 0;

  const imp6 = c.curve?.implied?.["6m"];
  const m3 = c.rates?.m3, policy = c.rates?.policy;
  if (imp6 != null) {
    score += Math.max(-1, Math.min(1, imp6 / 40)) * 0.45;
    if (Math.abs(imp6) > 15) parts.push(`markedet priser <b>${bp(imp6)} innen 6 mnd</b>`);
    else parts.push("markedet priser <b>om lag uendret rente</b> neste 6 mnd");
  } else if (m3 != null && policy != null) {
    const spread = m3 - policy;
    score += Math.max(-1, Math.min(1, spread / 0.4)) * 0.45;
    if (spread > 0.15) parts.push("pengemarkedet priser <b>renteheving</b>");
    else if (spread < -0.15) parts.push("pengemarkedet priser <b>rentekutt</b>");
    else parts.push("pengemarkedet priser <b>uendret rente</b>");
  }

  let mom = c.fx?.changes?.m3;
  if (mom != null) {
    if (invert) mom = -mom;
    score += Math.max(-1, Math.min(1, mom / 4)) * 0.35;
    if (mom > 0.5) parts.push("valutaen har <b>styrket seg</b> siste 3 mnd");
    else if (mom < -0.5) parts.push("valutaen har <b>svekket seg</b> siste 3 mnd");
  }

  const cpi = c.cpi?.value;
  if (policy != null && cpi != null) {
    const real = policy - cpi;
    score += Math.max(-1, Math.min(1, real / 2)) * 0.2;
    if (real > 0.5) parts.push("positiv realrente");
    else if (real < -0.5) parts.push("negativ realrente");
  }

  const dir = score > 0.12 ? "up" : score < -0.12 ? "down" : "flat";
  const arrow = { up: "▲", down: "▼", flat: "▶" }[dir];
  const word = { up: "Styrkende drivere", down: "Svekkende drivere", flat: "Nøytralt bilde" }[dir];
  return { dir, arrow, word, text: parts.join(" · ") || "For lite data" };
}

function fxLine(c) {
  if (!c.fx) return `<div class="fx-value">–</div>`;
  if (c.fx.index) {
    return `<div class="fx-value">I-44: ${nb.format(c.fx.value)} <small>importveid kroneindeks (lavere = sterkere NOK)</small></div>`;
  }
  return `<div class="fx-value">${c.fx.per} ${c.currency} = ${nb.format(c.fx.value)} NOK</div>`;
}

function pppLine(c) {
  if (!c.ppp) return "";
  if (c.ppp.valuation == null) return `PPP: <b>referansevaluta</b>`;
  const v = c.ppp.valuation;
  const word = v > 0 ? "overvurdert" : "undervurdert";
  const proxy = c.ppp.proxy ? ` <small>(proxy: ${c.ppp.proxy})</small>` : "";
  return `PPP mot USD: <b>${nb1.format(Math.abs(v))} % ${word}</b>${proxy}`;
}

function cotLine(c) {
  if (!c.cot) {
    return c.currency === "NOK" || c.currency === "SEK"
      ? `<span>Spekulativ posisjonering: <small>ingen likvide futures for ${c.currency}</small></span>`
      : "";
  }
  const oi = c.cot.pct_oi != null ? ` · ${signed(c.cot.pct_oi)} % av OI` : "";
  const wk = c.cot.change_w != null ? ` · uke: ${thousands(c.cot.change_w)}` : "";
  return `<span>Spek. netto (CFTC): <b class="${cls(c.cot.net)}">${thousands(c.cot.net)}</b>${oi}${wk}</span>`;
}

function pricedRows(c) {
  const rows = [];
  const imp = c.curve?.implied;
  if (imp) {
    const star = c.curve.synthetic_anchor ? "*" : "";
    rows.push(`<div class="meta-row">
      <span title="${c.curve.source}">Priset inn${star}: <b class="${cls(imp["6m"], 9)}">6m ${bp(imp["6m"])}</b> ·
        <b class="${cls(imp["12m"], 9)}">12m ${bp(imp["12m"])}</b> · <b class="${cls(imp["24m"], 9)}">2å ${bp(imp["24m"])}</b></span>
      <span>${extremeText(c.curve)}</span></div>`);
  }
  const f = c.fwd_fx_1y;
  if (f) {
    rows.push(`<div class="meta-row">
      <span>1 års termin: <b>${nb.format(f.rate)} NOK</b>
        <small>(${pct(f.pct)} vs. spot · rentediff. 1 år ${signed(f.diff, nb2)} pp${f.from_curve ? "" : ", fra 3 mnd-renter"})</small></span></div>`);
  }
  return rows.join("");
}

function card(c, market) {
  const sig = directionSignal(c);
  const inv = c.fx?.index;
  const ch = c.fx?.changes || {};
  const meeting = c.meeting ? dateFmt.format(new Date(c.meeting)) : "–";
  const curve = c.rates.y10 != null && c.rates.m3 != null ? c.rates.y10 - c.rates.m3 : null;
  const volChip = c.vol30 != null
    ? `<span class="chip">vol <b>${nb1.format(c.vol30)} %</b></span>` : "";
  const brentRow = c.id === "no" && market?.brent
    ? `<div class="meta-row"><span>Brent: <b>${nb2.format(market.brent.value)} USD</b> <small>(1m ${pct1(market.brent.changes?.m1)})</small></span>
       <span>90d-korr. olje↔NOK: <b>${market.brent_nok_corr != null ? nb2.format(market.brent_nok_corr) : "–"}</b></span></div>`
    : "";
  return `
  <article class="card" id="card-${c.id}">
    <div class="card-head">
      <span class="flag">${c.flag}</span>
      <h2>${c.name}</h2>
      <span class="ccy">${c.currency}</span>
    </div>
    ${fxLine(c)}
    <div class="changes">
      ${changeChip("1d", ch.d1, inv)}${changeChip("1u", ch.w1, inv)}${changeChip("1m", ch.m1, inv)}${changeChip("3m", ch.m3, inv)}${changeChip("1å", ch.y1, inv)}${volChip}
    </div>
    <div class="chart-wrap"><canvas id="chart-${c.id}"></canvas></div>
    <div class="rates">
      <div class="rate-box"><div class="label">Styring</div><div class="val">${rate(c.rates.policy)}</div></div>
      <div class="rate-box"><div class="label">3 mnd</div><div class="val">${rate(c.rates.m3)}</div></div>
      <div class="rate-box"><div class="label">10 år</div><div class="val">${rate(c.rates.y10)}</div></div>
      <div class="rate-box"><div class="label">Kurve 10å−3m</div><div class="val">${curve != null ? signed(curve, nb2) : "–"}</div></div>
    </div>
    <div class="chart-label">Styringsrente 2 år</div>
    <div class="chart-wrap-sm"><canvas id="policy-${c.id}"></canvas></div>
    <div class="meta-row">
      <span>KPI å/å: <b>${c.cpi ? rate(Math.round(c.cpi.value * 10) / 10) : "–"}</b> <small>(${c.cpi?.period ?? ""})</small></span>
      <span>Ledighet: <b>${c.unemployment ? rate(c.unemployment.value) : "–"}</b> <small>(${c.unemployment?.period ?? ""})</small></span>
    </div>
    <div class="meta-row">
      <span>${pppLine(c)}</span>
      <span>${c.bank}: <b>${meeting}</b></span>
    </div>
    ${pricedRows(c)}
    ${c.cot || c.currency === "NOK" || c.currency === "SEK" ? `<div class="meta-row">${cotLine(c)}</div>` : ""}
    ${brentRow}
    <div class="signal ${sig.dir}">
      <span class="arrow">${sig.arrow}</span>
      <span class="expl"><b>${sig.word}.</b> ${sig.text}</span>
    </div>
  </article>`;
}

function baseLineOptions(tooltipLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: tooltipLabel } },
    },
    scales: {
      x: {
        ticks: {
          color: cssVar("--muted"), maxTicksLimit: 5, maxRotation: 0,
          callback(value) { return dateFmt.format(new Date(this.getLabelForValue(value))); },
        },
        grid: { display: false },
      },
      y: {
        ticks: { color: cssVar("--muted"), maxTicksLimit: 4 },
        grid: { color: cssVar("--border") },
      },
    },
  };
}

function drawFxChart(c, history) {
  const key = c.fx?.index ? "I44" : c.currency;
  const series = history.fx?.[key];
  if (!series) return;
  const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
  const per = c.fx?.per ?? 1;
  new Chart(document.getElementById(`chart-${c.id}`), {
    type: "line",
    data: {
      labels: entries.map(([d]) => d),
      datasets: [{
        data: entries.map(([, v]) => v * per),
        borderColor: cssVar("--accent"), borderWidth: 1.6, pointRadius: 0, tension: 0.2,
      }],
    },
    options: baseLineOptions((item) => c.fx?.index
      ? `I-44: ${nb.format(item.parsed.y)}`
      : `${per} ${c.currency} = ${nb.format(item.parsed.y)} NOK`),
  });
}

function drawPolicyChart(c, history) {
  const series = history.policy?.[c.bis] ?? history.policy?.[{
    us: "US", ea: "XM", jp: "JP", gb: "GB", ch: "CH", ca: "CA", au: "AU", nz: "NZ", se: "SE", no: "NO",
  }[c.id]];
  if (!series) return;
  const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
  new Chart(document.getElementById(`policy-${c.id}`), {
    type: "line",
    data: {
      labels: entries.map(([d]) => d),
      datasets: [{
        data: entries.map(([, v]) => v),
        borderColor: cssVar("--flat"), borderWidth: 1.4, pointRadius: 0, stepped: true,
      }],
    },
    options: baseLineOptions((item) => `Styringsrente: ${rate(item.parsed.y)}`),
  });
}

function renderMovers(countries) {
  const rows = countries
    .filter((c) => c.fx && !c.fx.index && c.fx.changes?.w1 != null)
    .map((c) => ({ ...c, w1: c.fx.changes.w1 }))
    .sort((a, b) => b.w1 - a.w1);
  if (rows.length < 2) return;
  const best = rows[0], worst = rows[rows.length - 1];
  const fmt = (c) => `<b>${name(c)}</b> <span class="${c.w1 > 0 ? "pos" : "neg"}">${pct(c.w1)}</span>`;
  document.getElementById("movers").innerHTML = `
    <span class="mover">Sterkest mot NOK siste uke: ${fmt(best)}</span>
    <span class="mover">Svakest mot NOK siste uke: ${fmt(worst)}</span>`;
}

function renderComparison(countries, history) {
  const datasets = [];
  let labels = null;
  for (const c of countries) {
    if (!c.fx || c.fx.index) continue;
    const series = history.fx?.[c.currency];
    if (!series) continue;
    const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
    if (!labels || entries.length > labels.length) labels = entries.map(([d]) => d);
    const base = entries[0][1];
    datasets.push({
      label: name(c),
      data: Object.fromEntries(entries.map(([d, v]) => [d, +(v / base * 100).toFixed(2)])),
      borderColor: color(c),
      borderWidth: 1.6, pointRadius: 0, tension: 0.2,
    });
  }
  // Chart.js håndterer objekt-data via parsing-nøkler; map til labels-akse
  const mapped = datasets.map((ds) => ({ ...ds, data: labels.map((d) => ds.data[d] ?? null) }));
  new Chart(document.getElementById("comparisonChart"), {
    type: "line",
    data: { labels, datasets: mapped },
    options: {
      ...baseLineOptions((item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}`),
      plugins: {
        legend: { display: true, position: "bottom", labels: { color: cssVar("--text"), boxWidth: 18, boxHeight: 3 } },
        tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}` } },
      },
      spanGaps: true,
    },
  });
}

/**
 * «Hva er priset inn»: tabell med priset endring i den korte renten per
 * sentralbank ved 3/6/12/24 mnd, ytterpunktet i banen og reprising siste uke.
 */
function renderPriced(countries) {
  const rows = countries.filter((c) => c.curve);
  const missing = countries.filter((c) => !c.curve).map((c) => c.currency);
  const panel = document.getElementById("pricedTable");
  if (!rows.length) {
    panel.innerHTML = `<p class="risk-note">Ingen rentekurver tilgjengelig ennå.</p>`;
    return;
  }
  const sorted = [...rows].sort((a, b) => a.curve.implied["12m"] - b.curve.implied["12m"]);
  const cell = (v) => {
    if (v == null) return `<td>–</td>`;
    const moves = Math.round(Math.abs(v) / 25);
    const sub = moves ? `<small>≈ ${moves} ${v < 0 ? "kutt" : "hev."}</small>` : `<small>uendret</small>`;
    return `<td class="${cls(v, 9)}">${bp(v)}${sub}</td>`;
  };
  const body = sorted.map((c) => {
    const i = c.curve.implied;
    const rep = c.curve.repricing?.w1;
    const star = c.curve.synthetic_anchor ? "<sup>*</sup>" : "";
    return `<tr>
      <td title="${c.curve.source} · ${c.curve.date}"><span class="dot" style="background:${color(c)}"></span>${c.flag} ${c.bank}${star}</td>
      <td>${rate(c.rates.policy)}</td>
      ${cell(i["3m"])}${cell(i["6m"])}${cell(i["12m"])}${cell(i["24m"])}
      <td class="extreme">${extremeText(c.curve)}</td>
      <td class="${cls(rep, 4)}">${bp(rep)}</td>
    </tr>`;
  }).join("");
  const stars = rows.some((c) => c.curve.synthetic_anchor)
    ? ` <sup>*</sup>Kurven mangler punkter under 6 mnd; 3-mnd-renten er satt lik styringsrenten.` : "";
  panel.innerHTML = `
    <div class="table-scroll"><table class="diff-table priced-table">
      <thead><tr><th>Sentralbank</th><th>Nå</th><th>3 mnd</th><th>6 mnd</th><th>12 mnd</th><th>24 mnd</th><th>Ytterpunkt</th><th>Repris. 1 u</th></tr></thead>
      <tbody>${body}</tbody>
    </table></div>
    <p class="risk-note">Priset endring i den korte renten = 3-mnd terminrente ved horisonten minus dagens 3-mnd-rente,
      regnet fra OIS- eller statskurven (kilde i tooltip). Terminrenter inneholder terminpremie, så tallene viser retning og
      størrelse på det som er priset – ikke sannsynligheter. «Repris. 1 u» = endring i 12-mnd-prisingen siste uke
      (positivt = mer haukete). Sortert fra mest kutt til mest heving.${stars}
      ${missing.length ? ` Ingen daglig kurve tilgjengelig for ${missing.join(", ")}.` : ""}</p>`;
}

/** Implisert rentebane 0–24 mnd frem for hvert land med kurve. */
function renderPathChart(countries) {
  const rows = countries.filter((c) => c.curve?.path);
  if (!rows.length) return;
  const labels = rows[0].curve.path.map((_, m) => m);
  new Chart(document.getElementById("pathChart"), {
    type: "line",
    data: {
      labels,
      datasets: rows.map((c) => ({
        label: name(c),
        data: c.curve.path,
        borderColor: color(c),
        borderWidth: c.id === "no" ? 2.6 : 1.6,
        pointRadius: 0, tension: 0.25,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, position: "bottom", labels: { color: cssVar("--text"), boxWidth: 18, boxHeight: 3 } },
        tooltip: {
          callbacks: {
            title: (items) => items[0].label === "0" ? "Nå" : `Om ${items[0].label} mnd`,
            label: (item) => {
              const start = item.dataset.data[0];
              return `${item.dataset.label}: ${rate(item.parsed.y)} (${bp(Math.round((item.parsed.y - start) * 100))})`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: cssVar("--muted"), maxRotation: 0, autoSkip: false,
            callback(value) { const m = +this.getLabelForValue(value); return m === 0 ? "nå" : m % 6 === 0 ? `${m} mnd` : null; },
          },
          grid: { display: false },
        },
        y: { ticks: { color: cssVar("--muted"), callback: (v) => `${nb1.format(v)} %` }, grid: { color: cssVar("--border") } },
      },
    },
  });
}

/**
 * Automatisk genererte observasjoner fra dataene – ment som inspirasjon til
 * å grave videre, ikke som anbefalinger.
 */
function renderIdeas(countries, market) {
  const ideas = [];
  const withCurve = countries.filter((c) => c.curve);
  const i12 = (c) => c.curve.implied["12m"];

  if (withCurve.length >= 2) {
    const by12 = [...withCurve].sort((a, b) => i12(a) - i12(b));
    const dove = by12[0], hawk = by12[by12.length - 1];
    const gap = i12(hawk) - i12(dove);
    if (gap >= 25) {
      ideas.push({
        tag: "Sprik i renteforventninger",
        text: `${i12(dove) < 0 ? "Mest lettelser priset" : "Minst innstramming priset"}: <b>${name(dove)}</b>
          (${bp(i12(dove))} innen 12 mnd). ${i12(hawk) > 0 ? "Mest innstramming" : "Minst lettelser"}: <b>${name(hawk)}</b>
          (${bp(i12(hawk))}). Markedet venter altså at rentedifferansen ${hawk.currency}–${dove.currency} øker med ${gap} bp det
          neste året. Tror du på det motsatte, er ${hawk.currency}/${dove.currency} krysset å se på.`,
      });
    }
    const rep = withCurve.filter((c) => c.curve.repricing?.w1 != null)
      .sort((a, b) => Math.abs(b.curve.repricing.w1) - Math.abs(a.curve.repricing.w1));
    if (rep.length && Math.abs(rep[0].curve.repricing.w1) >= 8) {
      const r = rep[0].curve.repricing.w1;
      ideas.push({
        tag: "Reprising",
        text: `Størst bevegelse i forventningene siste uke: <b>${name(rep[0])}</b>, der 12-mnd-prisingen har flyttet seg
          ${bp(r)} (${r > 0 ? "mer haukete" : "mer duete"}). Momentum i renteforventninger smitter ofte over på valutaen
          – sjekk om kursen har hengt med.`,
      });
    }
    for (const c of withCurve) {
      const cpi = c.cpi?.value;
      if (cpi == null) continue;
      if (i12(c) <= -25 && cpi >= 3) {
        ideas.push({
          tag: "Kutt tross høy inflasjon",
          text: `<b>${name(c)}</b>: ${bp(i12(c))} priset innen 12 mnd selv om KPI er ${nb1.format(cpi)} %. Skuffer ikke
            inflasjonen på nedsiden, kan kuttene prises ut igjen – det ville støtte ${c.currency}.`,
        });
      } else if (i12(c) >= 25 && cpi <= 1.5) {
        ideas.push({
          tag: "Hevinger tross lav inflasjon",
          text: `<b>${name(c)}</b>: ${bp(i12(c))} priset innen 12 mnd med KPI på bare ${nb1.format(cpi)} %. Uteblir
            hevingene, er ${c.currency} sårbar for at prisingen reverserer.`,
        });
      }
    }
  }

  const carry = countries.filter((c) => c.fwd_fx_1y).sort((a, b) => b.fwd_fx_1y.diff - a.fwd_fx_1y.diff);
  if (carry.length >= 2) {
    const hi = carry[0], lo = carry[carry.length - 1];
    ideas.push({
      tag: "Carry mot NOK",
      text: `Høyest 1-års rente relativt til NOK: <b>${name(hi)}</b> (${signed(hi.fwd_fx_1y.diff, nb2)} pp; terminen ligger
        ${pct(hi.fwd_fx_1y.pct)} fra spot). Lavest: <b>${name(lo)}</b> (${signed(lo.fwd_fx_1y.diff, nb2)} pp). Å eie NOK mot
        ${lo.currency} gir ${nb2.format(-lo.fwd_fx_1y.diff)} pp i årlig carry; terminkursen ${nb.format(lo.fwd_fx_1y.rate)}
        er breakeven for handelen.`,
    });
  }

  const crowded = countries.filter((c) => c.cot?.pct_oi != null && Math.abs(c.cot.pct_oi) >= 25)
    .sort((a, b) => Math.abs(b.cot.pct_oi) - Math.abs(a.cot.pct_oi));
  if (crowded.length) {
    const c = crowded[0];
    ideas.push({
      tag: "Posisjonering",
      text: `Spekulantene er tungt <b>${c.cot.net > 0 ? "long" : "short"} ${name(c)}</b> (${signed(c.cot.pct_oi)} % av åpen
        interesse). Ensidig posisjonering øker faren for brå reversering – en kontrær vinkel, særlig rundt neste rentemøte
        (${c.meeting ? dateFmt.format(new Date(c.meeting)).replace(/\.$/, "") : "dato ukjent"}).`,
    });
  }

  const no = countries.find((c) => c.id === "no");
  if (no?.curve) {
    const corr = market?.brent_nok_corr;
    ideas.push({
      tag: "Norges Bank",
      text: `Markedet priser <b>${bp(i12(no))} innen 12 mnd</b> for Norges Bank (${extremeText(no.curve)}).
        Neste møte ${no.meeting ? dateFmt.format(new Date(no.meeting)).replace(/\.$/, "") : "–"}.${market?.brent
          ? ` Brent ${nb0.format(market.brent.value)} USD${corr != null ? `, 90-dagers korrelasjon olje↔krone ${nb2.format(corr)}` : ""}.` : ""}`,
    });
  }

  document.getElementById("ideas").innerHTML = ideas.slice(0, 6).map((i) =>
    `<div class="idea"><div class="tag">${i.tag}</div><div>${i.text}</div></div>`).join("")
    || `<p class="risk-note">For lite kurvedata til å generere observasjoner ennå.</p>`;
}

function renderRisk(market) {
  const tiles = [];
  const tile = (label, val, sub) =>
    `<div class="risk-tile"><div class="label">${label}</div><div class="val">${val}</div><div class="sub">${sub}</div></div>`;
  const chg = (v) => `1m <span class="${cls(v)}">${pct1(v)}</span>`;
  if (market.audjpy) tiles.push(tile("AUD/JPY (risk on/off)", nb2.format(market.audjpy.value), chg(market.audjpy.changes?.m1)));
  if (market.vix) tiles.push(tile("VIX", nb2.format(market.vix.value), chg(market.vix.changes?.m1)));
  if (market.brent) tiles.push(tile("Brent (USD)", nb2.format(market.brent.value), chg(market.brent.changes?.m1)));
  document.getElementById("riskTiles").innerHTML = tiles.join("");
  const corr = market.brent_nok_corr;
  if (corr != null) {
    document.getElementById("riskPanel").insertAdjacentHTML("beforeend",
      `<p class="risk-note">Stigende AUD/JPY og fallende VIX = risikoappetitt, som normalt støtter NOK.
       90-dagers korrelasjon Brent↔kronestyrke: <b>${nb2.format(corr)}</b>.</p>`);
  }
}

function renderDiffs(countries) {
  const norway = countries.find((c) => c.id === "no");
  if (!norway) return;
  const cell = (a, b) => {
    if (a == null || b == null) return `<td>–</td>`;
    const d = a - b;
    return `<td class="${cls(d, 0.05)}">${signed(d, nb2)}</td>`;
  };
  const rows = countries.filter((c) => c.id !== "no").map((c) => `
    <tr>
      <td>${name(c)}</td>
      ${cell(c.rates.policy, norway.rates.policy)}
      ${cell(c.rates.m3, norway.rates.m3)}
      ${cell(c.rates.y10, norway.rates.y10)}
      <td class="${cls(c.fwd_fx_1y?.pct)}">${c.fwd_fx_1y ? pct(c.fwd_fx_1y.pct) : "–"}</td>
    </tr>`).join("");
  document.getElementById("diffTable").innerHTML = `
    <table class="diff-table">
      <thead><tr><th>Valuta</th><th>Styringsrente</th><th>3 mnd</th><th>10 år</th><th>1å termin vs. spot</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="risk-note">Positiv differanse = høyere rente enn Norge → isolert sett støtte for valutaen mot NOK.
      Terminkursen følger av rentedifferansen (dekket renteparitet) og er breakeven for en carry-handel, ikke en prognose.</p>`;
}

async function init() {
  const bust = `?v=${Date.now()}`;
  const [dashboard, history] = await Promise.all([
    fetch(`data/dashboard.json${bust}`).then((r) => r.json()),
    fetch(`data/history.json${bust}`).then((r) => r.json()),
  ]);

  const css = getComputedStyle(document.documentElement);
  cssVar = (name) => css.getPropertyValue(name).trim();

  const updated = new Date(dashboard.updated);
  document.getElementById("updated").textContent =
    `Sist oppdatert: ${updated.toLocaleString("nb-NO", { dateStyle: "long", timeStyle: "short" })}`;

  const market = dashboard.market || {};
  renderMovers(dashboard.countries);
  renderPriced(dashboard.countries);
  renderPathChart(dashboard.countries);
  renderIdeas(dashboard.countries, market);
  renderRisk(market);
  renderDiffs(dashboard.countries);

  const grid = document.getElementById("grid");
  grid.innerHTML = dashboard.countries.map((c) => card(c, market)).join("");
  renderComparison(dashboard.countries, history);
  dashboard.countries.forEach((c) => { drawFxChart(c, history); drawPolicyChart(c, history); });
}

init().catch((err) => {
  document.getElementById("grid").innerHTML =
    `<p class="loading">Kunne ikke laste data: ${err.message}</p>`;
});

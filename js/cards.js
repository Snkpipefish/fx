/* Landskortene: kompakt som standard, «Vis detaljer» viser renter, KPI, posisjonering m.m. */
import { nb, nb1, nb2, pct, pct1, rate, signed, thousands, bp, pp, moves, cls, shortDate, cssVar } from "./format.js";
import { directionSignal, extremeText } from "./calc.js";
import { sparkline } from "./charts.js";

const changeChip = (label, value, invert) => {
  const shown = value == null ? null : invert ? -value : value;
  return `<span class="chip">${label} <b class="${cls(shown)}">${pct(shown)}</b></span>`;
};

const fxLine = (c) => !c.fx ? `<div class="fx-value">–</div>` : c.fx.index
  ? `<div class="fx-value">I-44: ${nb.format(c.fx.value)} <small>importveid kroneindeks (lavere = sterkere NOK)</small></div>`
  : `<div class="fx-value">${c.fx.per} ${c.currency} = ${nb.format(c.fx.value)} NOK</div>`;

function pppLine(c) {
  if (!c.ppp) return "";
  if (c.ppp.valuation == null) return `PPP: <b>referansevaluta</b>`;
  const v = c.ppp.valuation;
  return `PPP mot USD: <b>${nb1.format(Math.abs(v))} % ${v > 0 ? "overvurdert" : "undervurdert"}</b>${c.ppp.proxy ? ` <small>(proxy: ${c.ppp.proxy})</small>` : ""}`;
}

function cotLine(c) {
  if (!c.cot) return c.currency === "NOK" || c.currency === "SEK" ? `<span>Spekulativ posisjonering: <small>ingen likvide futures for ${c.currency}</small></span>` : "";
  const oi = c.cot.pct_oi != null ? ` · ${signed(c.cot.pct_oi)} % av OI` : "";
  const wk = c.cot.change_w != null ? ` · uke: ${thousands(c.cot.change_w)}` : "";
  return `<span>Spek. netto (CFTC): <b class="${cls(c.cot.net)}">${thousands(c.cot.net)}</b>${oi}${wk}</span>`;
}

/** Én setning i vanlig norsk om hva markedet venter av sentralbanken. */
function expectLine(c) {
  const imp = c.curve?.implied;
  if (!imp) return `<div class="expect"><span>Ingen rentekurve for ${c.currency} – markedets forventninger vises ikke.</span></div>`;
  const v = imp["12m"];
  const what = Math.abs(v) < 13 ? "om lag <b>uendret rente</b>" : `<b>${moves(v)}</b>`;
  return `<div class="expect"><span>Markedet venter ${what} fra ${c.bank} neste 12 mnd <small>(${pp(v)} · ${extremeText(c.curve)})</small></span></div>`;
}

function pricedRow(c) {
  const imp = c.curve?.implied;
  if (!imp) return "";
  return `<div class="meta-row"><span title="${c.curve.source}">Priset inn${c.curve.synthetic_anchor ? "*" : ""}:
      <b class="${cls(imp["6m"], 9)}">6 mnd ${pp(imp["6m"])}</b> · <b class="${cls(imp["12m"], 9)}">12 mnd ${pp(imp["12m"])}</b> ·
      <b class="${cls(imp["24m"], 9)}">2 år ${pp(imp["24m"])}</b></span></div>`;
}

export function card(c, market) {
  const sig = directionSignal(c);
  const inv = c.fx?.index, ch = c.fx?.changes || {};
  const curve = c.rates.y10 != null && c.rates.m3 != null ? c.rates.y10 - c.rates.m3 : null;
  const f = c.fwd_fx_1y;
  return `
  <article class="card" id="card-${c.id}">
    <div class="card-head"><span class="flag">${c.flag}</span><h2>${c.name}</h2><span class="ccy">${c.currency}</span></div>
    ${fxLine(c)}
    <div class="changes">
      ${changeChip("1d", ch.d1, inv)}${changeChip("1u", ch.w1, inv)}${changeChip("1m", ch.m1, inv)}${changeChip("3m", ch.m3, inv)}${changeChip("1å", ch.y1, inv)}
      ${c.vol30 != null ? `<span class="chip">vol <b>${nb1.format(c.vol30)} %</b></span>` : ""}
    </div>
    <div class="spark-wrap" id="spark-${c.id}"></div>
    ${expectLine(c)}
    <div class="details">
      ${pricedRow(c)}
      <div class="rates">
        <div class="rate-box"><div class="label">Styring</div><div class="val">${rate(c.rates.policy)}</div></div>
        <div class="rate-box"><div class="label">3 mnd</div><div class="val">${rate(c.rates.m3)}</div></div>
        <div class="rate-box"><div class="label">10 år</div><div class="val">${rate(c.rates.y10)}</div></div>
        <div class="rate-box"><div class="label">Kurve 10å−3m</div><div class="val">${curve != null ? signed(curve, nb2) : "–"}</div></div>
      </div>
      <div class="chart-label">Styringsrente 2 år</div>
      <div class="spark-wrap sm" id="policy-${c.id}"></div>
      <div class="meta-row">
        <span>KPI å/å: <b>${c.cpi ? rate(Math.round(c.cpi.value * 10) / 10) : "–"}</b> <small>(${c.cpi?.period ?? ""})</small></span>
        <span>Ledighet: <b>${c.unemployment ? rate(c.unemployment.value) : "–"}</b> <small>(${c.unemployment?.period ?? ""})</small></span>
      </div>
      <div class="meta-row"><span>${pppLine(c)}</span><span>${c.bank}: <b>${shortDate(c.meeting)}</b></span></div>
      ${f ? `<div class="meta-row"><span>1 års termin: <b>${nb.format(f.rate)} NOK</b> <small>(${pct(f.pct)} vs. spot · rentediff. 1 år ${signed(f.diff, nb2)} pp${f.from_curve ? "" : ", fra 3 mnd-renter"})</small></span></div>` : ""}
      ${c.cot || c.currency === "NOK" || c.currency === "SEK" ? `<div class="meta-row">${cotLine(c)}</div>` : ""}
      ${c.id === "no" && market?.brent ? `<div class="meta-row"><span>Brent: <b>${nb2.format(market.brent.value)} USD</b> <small>(1m ${pct1(market.brent.changes?.m1)})</small></span>
        <span>90d-korr. olje↔NOK: <b>${market.brent_nok_corr != null ? nb2.format(market.brent_nok_corr) : "–"}</b></span></div>` : ""}
    </div>
    <div class="signal ${sig.dir}"><span class="arrow" aria-hidden="true">${sig.arrow}</span>
      <span class="expl"><b>${sig.word}.</b> ${sig.text}</span></div>
  </article>`;
}

export function renderCards(countries, market) {
  document.getElementById("grid").innerHTML = countries.map((c) => card(c, market)).join("");
}

/** Fyller sparklines når historikken er lastet. */
export function fillSparklines(countries, history) {
  const bis = { us: "US", ea: "XM", jp: "JP", gb: "GB", ch: "CH", ca: "CA", au: "AU", nz: "NZ", se: "SE", no: "NO" };
  for (const c of countries) {
    const fx = history.fx?.[c.fx?.index ? "I44" : c.currency];
    if (fx) {
      document.getElementById(`spark-${c.id}`).innerHTML = sparkline(fx, {
        stroke: cssVar("--accent"), scale: c.fx?.per ?? 1,
        label: c.fx?.index ? "I-44 siste år" : `${c.fx.per} ${c.currency} i NOK siste år`,
      });
    }
    const policy = history.policy?.[bis[c.id]];
    if (policy) {
      document.getElementById(`policy-${c.id}`).innerHTML = sparkline(policy, { stepped: true, stroke: cssVar("--flat"),
        label: `${c.bank} styringsrente siste 2 år`, fmt: (v) => rate(v) });
    }
  }
}

/** Kompakt/detaljert visning, husket per nettleser. */
export function setupCardMode() {
  const grid = document.getElementById("grid"), btn = document.getElementById("cardMode");
  let mode = "compact";
  try { mode = localStorage.getItem("cardMode") || mode; } catch { /* privat modus o.l. */ }
  const apply = () => {
    grid.classList.toggle("compact", mode === "compact");
    btn.textContent = mode === "compact" ? "Vis detaljer" : "Vis kompakt";
    btn.setAttribute("aria-pressed", mode !== "compact");
  };
  btn.addEventListener("click", () => {
    mode = mode === "compact" ? "full" : "compact";
    try { localStorage.setItem("cardMode", mode); } catch { /* ignorer */ }
    apply();
  });
  apply();
}

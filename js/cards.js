/* Land for land: rolige kort med kurs, sparkline og én setning om hva markedet venter. */
import { nb, nb1, nb2, pct, pct1, rate, signed, thousands, pp, moves, cls, shortDate, cssVar } from "./format.js";
import { directionSignal, extremeText } from "./calc.js";
import { sparkline } from "./charts.js";

const chip = (label, value, invert) => {
  const v = value == null ? null : invert ? -value : value;
  return `<span class="chip">${label} <b class="${cls(v)}">${pct1(v)}</b></span>`;
};

function expectLine(c) {
  const imp = c.curve?.implied;
  if (!imp) return `<p class="expect muted">Ingen rentekurve for ${c.currency}, så markedets forventninger vises ikke.</p>`;
  const v = imp["12m"];
  const what = Math.abs(v) < 13 ? "om lag <b>uendret rente</b>" : `<b>${moves(v)}</b>`;
  return `<p class="expect">Markedet venter ${what} fra ${c.bank} neste 12 mnd <span class="muted">(${pp(v)} · ${extremeText(c.curve)})</span>.</p>`;
}

function pppLine(c) {
  if (!c.ppp) return "";
  if (c.ppp.valuation == null) return `Kjøpekraft: <b>referansevaluta</b>`;
  const v = c.ppp.valuation;
  return `Kjøpekraft mot USD: <b>${nb1.format(Math.abs(v))} % ${v > 0 ? "dyr" : "billig"}</b>${c.ppp.proxy ? ` <small>(proxy: ${c.ppp.proxy})</small>` : ""}`;
}

function cotLine(c) {
  if (!c.cot) return c.currency === "NOK" || c.currency === "SEK" ? `Spekulanter: <small>ingen likvide futures for ${c.currency}</small>` : "";
  const oi = c.cot.pct_oi != null ? ` (${signed(c.cot.pct_oi)} % av åpen interesse)` : "";
  return `Spekulanter: <b class="${cls(c.cot.net)}">${thousands(c.cot.net)}</b> netto${oi}`;
}

export function card(c, market) {
  const sig = directionSignal(c);
  const inv = c.fx?.index, ch = c.fx?.changes || {};
  const fx = !c.fx ? "–" : c.fx.index ? `I-44 ${nb.format(c.fx.value)}` : `${c.fx.per} ${c.currency} = ${nb.format(c.fx.value)} kr`;
  const f = c.fwd_fx_1y, imp = c.curve?.implied;
  const row = (a, b) => `<div class="row"><span>${a}</span><span>${b}</span></div>`;
  return `
  <article class="card" id="card-${c.id}">
    <header><span class="flag">${c.flag}</span><div><h3>${c.name}</h3><span class="ccy">${c.currency}${c.fx?.index ? " · importveid indeks, lavere = sterkere krone" : ""}</span></div></header>
    <div class="fx">${fx}</div>
    <div class="chips-row">${chip("uke", ch.w1, inv)}${chip("måned", ch.m1, inv)}${chip("år", ch.y1, inv)}</div>
    <div class="spark-wrap" id="spark-${c.id}"></div>
    ${expectLine(c)}
    <div class="signal ${sig.dir}"><span class="pill">${sig.arrow} ${sig.word}</span><span class="muted">${sig.text}</span></div>
    <div class="details">
      <div class="rates">
        <div title="${c.rates.policy_source ?? ""}"><span>Styring</span><b>${rate(c.rates.policy)}</b></div>
        <div title="${c.rates.m3_source ?? ""}"><span>3 mnd ${({ OIS: "OIS", statsveksel: "veksel", statspapir: "stat" })[c.rates.m3_source] ?? "mnd.snitt"}</span><b>${rate(c.rates.m3)}</b></div>
        <div title="${c.rates.y10_source ?? ""}"><span>10 år${c.rates.y10_source === "statsobligasjon" ? "" : " (mnd.snitt)"}</span><b>${rate(c.rates.y10)}</b></div>
        <div title="${c.cpi_core?.label ?? ""}"><span>Inflasjon${c.cpi_core ? " / kjerne" : ""}</span><b>${c.cpi ? nb1.format(Math.round(c.cpi.value * 10) / 10) : "–"}${c.cpi_core ? ` / ${nb1.format(c.cpi_core.value)}` : ""} %</b></div>
      </div>
      ${c.policy_change ? row(`${c.policy_change.to > c.policy_change.from ? "Hevet" : "Kuttet"} ${shortDate(c.policy_change.date)}: <b>${rate(c.policy_change.from)} → ${rate(c.policy_change.to)}</b>`,
        c.policy_change.fx_since != null ? `<span title="Målt mot handelspartnerne (I-44-justert)">${c.currency} siden: <b class="${cls(c.policy_change.fx_since)}">${pct1(c.policy_change.fx_since)}</b></span>` : "") : ""}
      <div class="spark-wrap sm" id="policy-${c.id}"></div>
      ${imp ? row("Priset inn", `<b class="${cls(imp["6m"], 9)}">6 mnd ${pp(imp["6m"])}</b> · <b class="${cls(imp["12m"], 9)}">12 mnd ${pp(imp["12m"])}</b> · <b class="${cls(imp["24m"], 9)}">2 år ${pp(imp["24m"])}</b>`) : ""}
      ${row(`Ledighet <b>${c.unemployment ? rate(c.unemployment.value) : "–"}</b>`, `${c.bank}: <b>${shortDate(c.meeting)}</b>`)}
      ${row(pppLine(c), c.vol30 != null ? `Svingninger <b>${nb1.format(c.vol30)} %</b>` : "")}
      ${f ? row(`1 års termin <b>${nb.format(f.rate)}</b> <small>(${pct(f.pct)} vs. spot)</small>`, `Renteforskjell 1 år <b>${signed(f.diff, nb2)} pp</b>`) : ""}
      ${c.cot || c.currency === "NOK" || c.currency === "SEK" ? row(cotLine(c), "") : ""}
      ${c.id === "no" && market?.brent ? row(`Brent <b>${nb2.format(market.brent.value)} USD</b> <small>(${pct1(market.brent.changes?.m1)} 1m)</small>`, `Olje↔krone 90 d: <b>${market.brent_nok_corr != null ? nb2.format(market.brent_nok_corr) : "–"}</b>`) : ""}
    </div>
  </article>`;
}

export function renderCards(countries, market) {
  document.getElementById("grid").innerHTML = countries.map((c) => card(c, market)).join("");
}

export function fillSparklines(countries, history) {
  const bis = { us: "US", ea: "XM", jp: "JP", gb: "GB", ch: "CH", ca: "CA", au: "AU", nz: "NZ", se: "SE", no: "NO" };
  for (const c of countries) {
    const fx = history.fx?.[c.fx?.index ? "I44" : c.currency];
    if (fx) document.getElementById(`spark-${c.id}`).innerHTML = sparkline(fx, { stroke: cssVar("--accent"), scale: c.fx?.per ?? 1,
      label: c.fx?.index ? "I-44 siste år" : `${c.fx.per} ${c.currency} i kroner siste år` });
    const policy = history.policy?.[bis[c.id]];
    if (policy) document.getElementById(`policy-${c.id}`).innerHTML = sparkline(policy, { stepped: true, stroke: cssVar("--muted"),
      label: `${c.bank} styringsrente siste 2 år`, fmt: (v) => rate(v) });
  }
}

export function setupCardMode() {
  const grid = document.getElementById("grid"), btn = document.getElementById("cardMode");
  let mode = "compact";
  try { mode = localStorage.getItem("cardMode") || mode; } catch { /* privat modus o.l. */ }
  const apply = () => {
    grid.classList.toggle("compact", mode === "compact");
    btn.textContent = mode === "compact" ? "Vis detaljer" : "Vis mindre";
    btn.setAttribute("aria-pressed", mode !== "compact");
  };
  btn.addEventListener("click", () => { mode = mode === "compact" ? "full" : "compact"; try { localStorage.setItem("cardMode", mode); } catch { /* ignorer */ } apply(); });
  apply();
}

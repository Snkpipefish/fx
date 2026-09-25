/* Land for land: rolige kort med konvensjonelt kryss, utvikling mot G10-kurven, sparkline og én setning om hva markedet venter. */
import { nb, nb1, nb2, pct, pct1, rate, signed, thousands, pp, moves, corr, cls, shortDate, cssVar } from "./format.js";
import { directionSignal, extremeText } from "./calc.js";
import { sparkline } from "./charts.js";

const chip = (label, value) => `<span class="chip">${label} <b class="${cls(value)}">${pct1(value)}</b></span>`;

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

/**
 * Posisjonering: TFF «leveraged funds» (hedgefond) er spekulantene i snever forstand; legacy
 * «non-commercial» inkluderer også kapitalforvaltere og vises som ikke-kommersielle.
 */
function cotLine(c) {
  if (!c.cot) return c.currency === "NOK" || c.currency === "SEK" ? `Spekulanter: <small>ingen likvide futures for ${c.currency}</small>` : "";
  const oi = c.cot.pct_oi != null ? ` (${signed(c.cot.pct_oi)} % av åpen interesse)` : "";
  const legacy = `<b class="${cls(c.cot.net)}">${thousands(c.cot.net)}</b> netto${oi}`;
  if (c.cot.lev_net == null) return `Spekulanter: ${legacy}${cotCheck(c.cot)}`;
  return `Spekulanter <small title="Hedgefond (TFF leveraged funds), netto">(hedgefond)</small>: <b class="${cls(c.cot.lev_net)}">${thousands(c.cot.lev_net)}</b>
    <span class="muted" title="Legacy non-commercial: spekulanter og kapitalforvaltere">· ikke-kommersielle ${legacy}</span>${cotCheck(c.cot)}`;
}

/** Stort ukesving: vis om det finnes i alle CFTC-rapportene, og om det var rulleuke. */
function cotCheck(cot) {
  if (!cot.unusual) return cot.roll_week ? ` <small class="muted">· rulleuke</small>` : "";
  const size = cot.z_w != null ? `${nb1.format(Math.abs(cot.z_w))}σ` : `OI ${signed(cot.oi_change_pct)} %`;
  const verdict = cot.confirmed === true ? `bekreftet i futures+opsjoner og TFF` : cot.confirmed === false ? `⚠ ubekreftet – andre rapporter viser noe annet` : `⚠ ubekreftet`;
  return ` <small class="${cot.confirmed === true ? "muted" : "neg"}">· uvanlig stort sving (${size}), ${verdict}${cot.roll_week ? ", rulleuke" : ""}</small>`;
}

/** Konvensjonelt kryss som «USD/NOK 9,5066» – slik markedet noterer det. */
const quoteText = (c) => (c.fx?.quote ? `${c.fx.quote.pair} ${nb.format(c.fx.quote.value)}` : "–");

export function card(c, market) {
  const sig = directionSignal(c);
  const ch = c.fx?.changes || {};
  const f = c.fwd_fx_1y, imp = c.curve?.implied;
  const k = market?.corr?.[c.currency];
  const row = (a, b) => `<div class="row"><span>${a}</span><span>${b}</span></div>`;
  return `
  <article class="card" id="card-${c.id}">
    <header><span class="flag">${c.flag}</span><div><h3>${c.name}</h3><span class="ccy">${c.currency}${c.fx?.basket != null ? ` · mot G10-kurven ${nb1.format(c.fx.basket)} <small>(100 = ett år siden)</small>` : ""}</span></div></header>
    <div class="fx">${quoteText(c)}</div>
    <div class="chips-row"><span class="chip lbl">mot kurven</span>${chip("uke", ch.w1)}${chip("måned", ch.m1)}${chip("år", ch.y1)}</div>
    <div class="spark-wrap" id="spark-${c.id}"></div>
    ${expectLine(c)}
    <div class="signal ${sig.dir}"><span class="pill">${sig.arrow} ${sig.word}</span><span class="muted">${sig.text}</span></div>
    <div class="details">
      <div class="rates">
        <div title="${c.rates.policy_source ?? ""}"><span>Styring${c.rates.policy_unconfirmed ? " ⚠" : ""}</span><b>${rate(c.rates.policy)}</b></div>
        <div title="${c.rates.m3_source ?? ""}"><span>3 mnd ${({ OIS: "OIS", statsveksel: "veksel", statspapir: "stat" })[c.rates.m3_source] ?? "mnd.snitt"}</span><b>${rate(c.rates.m3)}</b></div>
        <div title="${c.rates.y10_source ?? ""}"><span>10 år${c.rates.y10_source === "statsobligasjon" ? "" : " (mnd.snitt)"}</span><b>${rate(c.rates.y10)}</b></div>
        <div title="${c.cpi_core?.label ?? ""}"><span>Inflasjon${c.cpi_core ? " / kjerne" : ""}</span><b>${c.cpi ? nb1.format(Math.round(c.cpi.value * 10) / 10) : "–"}${c.cpi_core ? ` / ${nb1.format(c.cpi_core.value)}` : ""} %</b></div>
      </div>
      ${c.policy_change ? row(`${c.policy_change.to > c.policy_change.from ? "Hevet" : "Kuttet"} ${shortDate(c.policy_change.date)}: <b>${rate(c.policy_change.from)} → ${rate(c.policy_change.to)}</b>`,
        c.policy_change.fx_since != null ? `<span title="Målt mot G10-kurven">${c.currency} siden: <b class="${cls(c.policy_change.fx_since)}">${pct1(c.policy_change.fx_since)}</b></span>` : "") : ""}
      <div class="spark-wrap sm" id="policy-${c.id}"></div>
      <div class="spark-legend" id="policy-legend-${c.id}"></div>
      ${imp ? row("Priset inn", `<b class="${cls(imp["6m"], 9)}">6 mnd ${pp(imp["6m"])}</b> · <b class="${cls(imp["12m"], 9)}">12 mnd ${pp(imp["12m"])}</b> · <b class="${cls(imp["24m"], 9)}">2 år ${pp(imp["24m"])}</b>`) : ""}
      ${row(`Ledighet <b>${c.unemployment ? rate(c.unemployment.value) : "–"}</b>`, `${c.bank}: <b>${shortDate(c.meeting)}</b>`)}
      ${row(pppLine(c), c.vol30 != null ? `Svingninger mot kurven <b>${nb1.format(c.vol30)} %</b>` : "")}
      ${f ? row(`1 års termin ${f.pair} <b>${nb.format(f.rate)}</b> <small>(${pct(f.pct)} vs. spot)</small>`,
        `Renteforskjell 1 år <b>${signed(f.diff_basket, nb2)} pp</b> <small>mot kurven${f.diff_usd != null ? `, ${signed(f.diff_usd, nb2)} pp mot USD` : ""}</small>`) : ""}
      ${c.cot || c.currency === "NOK" || c.currency === "SEK" ? row(cotLine(c), "") : ""}
      ${k ? row(`<span title="90-dagers korrelasjon mellom daglige avkastninger, kurvindeks mot Brent og TTF">Olje↔${c.currency} 90 d: <b>${corr(k.oil)}</b>${k.gas != null ? ` · gass <b>${corr(k.gas)}</b>` : ""}</span>`,
        `<span title="Korrelasjon mot AUD/JPY: positiv = risk-on-valuta, negativ = trygg havn">Risikoappetitt <b>${corr(k.risk)}</b></span>`) : ""}
    </div>
  </article>`;
}

export function renderCards(countries, market) {
  document.getElementById("grid").innerHTML = countries.map((c) => card(c, market)).join("");
}

export function fillSparklines(countries, history) {
  const bis = { us: "US", ea: "XM", jp: "JP", gb: "GB", ch: "CH", ca: "CA", au: "AU", nz: "NZ", se: "SE", no: "NO" };
  for (const c of countries) {
    const idx = history.basket?.[c.currency];
    if (idx) document.getElementById(`spark-${c.id}`).innerHTML = sparkline(idx, { stroke: cssVar("--accent"), fmt: (v) => nb1.format(v),
      label: `${c.currency} mot G10-kurven siste år (100 = start)` });
    // Styringsrenten (trapp) med renten markedet ventet om 12 mnd (stiplet) fra snapshots – reprisingen over tid
    const policy = history.policy?.[bis[c.id]];
    const path12 = history.path12?.[c.currency];
    if (policy) {
      const from = path12 && Object.keys(path12).length >= 20 ? Object.keys(path12).sort()[0] : null;
      const shown = from ? Object.fromEntries(Object.entries(policy).filter(([d]) => d >= from)) : policy;
      document.getElementById(`policy-${c.id}`).innerHTML = sparkline(shown, { stepped: true, stroke: cssVar("--muted"),
        label: `${c.bank} styringsrente ${from ? "siste år" : "siste 2 år"}`, fmt: (v) => rate(v),
        overlay: from ? { series: path12, label: "renten markedet ventet om 12 mnd", stroke: cssVar("--accent") } : null });
      document.getElementById(`policy-legend-${c.id}`).innerHTML = from
        ? `<span><i class="leg step"></i>styringsrente</span><span><i class="leg dash"></i>ventet om 12 mnd (markedet, samme dag)</span>`
        : `<span><i class="leg step"></i>styringsrente siste 2 år</span>`;
    }
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

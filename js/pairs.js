/* Motposten – ingen posisjon står alene. Se calc.js for logikken (pairCandidates). */
import { nb, nb1, nb2, pct, pct1, rate, signed, bp, cls, name } from "./format.js";
import { legInfo, pairSeries, pairCandidates, realizedVol } from "./calc.js";
import { barCell } from "./charts.js";

export function renderPairs(dashboard, history) {
  const countries = dashboard.countries;
  const info = legInfo(countries, history);
  const legSel = document.getElementById("pairLeg"), dirSel = document.getElementById("pairDir");
  legSel.innerHTML = countries.map((c) => `<option value="${c.id}">${c.flag} ${c.currency} – ${c.name}</option>`).join("");
  legSel.value = "us";

  const corrWord = (v) => (v == null ? "–" : nb2.format(v));
  const riskLabel = (v) => (v == null ? "" : v > 0.3 ? "risk-on-valuta" : v < -0.3 ? "trygg havn" : "risikonøytral");
  const describeLeg = (c) => {
    const i = info[c.id], bits = [];
    if (i.imp12 != null) bits.push(`${c.bank}s prisede bane (<b>${bp(i.imp12)}</b> innen 12 mnd)`);
    if (i.r1y != null) bits.push(`1-års rente <b>${rate(i.r1y)}</b>`);
    if (i.riskCorr != null) bits.push(`risikokorrelasjon <b>${corrWord(i.riskCorr)}</b> (${riskLabel(i.riskCorr)})`);
    if (i.oilCorr != null) bits.push(`oljekorrelasjon <b>${corrWord(i.oilCorr)}</b>`);
    if (c.id !== "no" && i.m3 != null) bits.push(`3 mnd-momentum mot NOK <b>${pct(i.m3)}</b>`);
    if (c.cot?.pct_oi != null) bits.push(`spekulanter <b>${signed(c.cot.pct_oi)} % av OI</b>`);
    if (c.ppp?.valuation != null) bits.push(`PPP <b>${nb1.format(Math.abs(c.ppp.valuation))} % ${c.ppp.valuation > 0 ? "dyr" : "billig"}</b> mot USD`);
    return bits.join(" · ");
  };

  const render = () => {
    const chosen = countries.find((c) => c.id === legSel.value);
    const isLong = dirSel.value === "long";
    const rows = pairCandidates({ countries, info, chosen, isLong, volOf: (L, S) => realizedVol(pairSeries(history, L, S)) });
    const maxCarry = Math.max(1, ...rows.map((r) => Math.abs(r.carry ?? 0)));
    const pairName = (r) => `<b>${r.L.flag} ${r.L.currency}</b>/<b>${r.S.flag} ${r.S.currency}</b>`;
    const riskCell = (d) => (d == null ? "–" : Math.abs(d) < 0.25 ? `<span class="pos">nøytraliserer</span>` : `<span class="neg">bærer risikosyn (Δ ${signed(d, nb2)})</span>`);
    const body = rows.map((r) => `<tr>
        <td>${pairName(r)}${r.other.id === "no" ? ` <small>(= «bare cash»)</small>` : ""}</td>
        ${barCell(r.carry, maxCarry, r.carry == null ? "–" : `${signed(r.carry, nb2)} pp`, cls(r.carry, 0.05))}
        <td class="${r.gap != null && r.gap >= 25 ? "neg" : ""}" title="Positivt = markedet priser allerede mer for long-beinet">${bp(r.gap)}</td>
        <td class="${cls(r.mom, 0.05)}">${r.mom == null ? "–" : pct1(r.mom)}</td>
        <td>${riskCell(r.dRisk)}</td>
        <td>${r.dOil == null ? "–" : Math.abs(r.dOil) < 0.25 ? `<span class="pos">lik</span>` : `Δ ${signed(r.dOil, nb2)}`}</td>
        <td>${r.vol == null ? "–" : `${nb1.format(r.vol)} %`}</td>
        <td class="tags">${r.tags.map(([t, why]) => `<span class="tag-chip ${t === "allerede priset" ? "warn" : ""}" title="${why}">${t}</span>`).join("")}</td>
      </tr>`).join("");
    const best = rows[0];
    const bestTags = best.tags.filter(([t]) => t !== "allerede priset" && t !== "carry").map(([t]) => t);
    const bits = [...bestTags, ...(best.carry != null ? [`carry ${signed(best.carry, nb2)} pp`] : [])];
    const summary = best && bits.length
      ? `<p class="pair-best">Flest treff: <b>long ${best.L.flag} ${best.L.currency} / short ${best.S.flag} ${best.S.currency}</b> (${bits.join(", ")}).</p>` : "";
    const legWord = isLong ? "Long" : "Short";
    const cashNote = chosen.id === "no"
      ? `Å sitte i NOK er også en posisjon: lang olje (korrelasjon ${corrWord(info.no.oilCorr)}), ${riskLabel(info.no.riskCorr)} og Norges Banks bane.`
      : `Selger du bare NOK for å kjøpe ${chosen.currency}, er motposten «cash» – men NOK er selv en posisjon: lang olje (korrelasjon ${corrWord(info.no.oilCorr)}), ${riskLabel(info.no.riskCorr)} og Norges Banks prisede bane (${bp(info.no.imp12)} innen 12 mnd).`;
    document.getElementById("pairResult").innerHTML = `
      <p class="pair-own"><b>${legWord} ${chosen.flag} ${chosen.currency}</b> betyr at du eier: ${describeLeg(chosen)}.
        ${isLong ? "Og du er implisitt short alt du ikke kjøpte." : "Og du er implisitt long alt annet."} ${cashNote}</p>
      ${summary}
      <div class="table-scroll"><table class="diff-table pair-table">
        <thead><tr><th>Paret (long/short)</th><th>Carry 1 år</th><th>Priset rentegap 12 mnd</th><th>Momentum 3 mnd</th>
          <th>Risikoappetitt</th><th>Olje</th><th>Vol 30 d</th><th>Passer til</th></tr></thead>
        <tbody>${body}</tbody>
      </table></div>
      <p class="risk-note">Rangert etter antall treff, deretter carry. Hold musen over merkelappene for begrunnelse. Observasjoner, ikke anbefalinger.</p>
      <details class="method"><summary>Slik regnes det</summary><p>Carry = 1-års rente i long-beinet minus short-beinet (fra rentekurvene,
        ellers 3 mnd-renter). Priset rentegap = hvor mye mer heving/mindre kutt markedet priser for long-beinet enn short-beinet – positivt
        betyr at synet ditt delvis allerede ligger i kursen. Risikoappetitt/olje = om begge beina har lik 90-dagers korrelasjon med AUD/JPY
        og Brent (målt mot I-44-kurven); «nøytraliserer» betyr at paret ikke er et skjult veddemål på risiko eller olje. Vol = realisert
        volatilitet i paret siste 30 dager.</p></details>`;
  };
  legSel.addEventListener("change", render);
  dirSel.addEventListener("change", render);
  render();
}

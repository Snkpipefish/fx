/* Motposten – ingen posisjon står alene. Se calc.js for logikken (pairCandidates). */
import { nb, nb1, nb2, pct, pct1, rate, signed, bp, pp, moves, cls, name } from "./format.js";
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
    if (i.imp12 != null) bits.push(`renteforventningene til ${c.bank} (<b>${moves(i.imp12)}</b> neste år)`);
    if (i.r1y != null) bits.push(`en rente på <b>${rate(i.r1y)}</b> i året`);
    if (i.riskCorr != null) bits.push(`en valuta som er <b>${riskLabel(i.riskCorr)}</b> (samvariasjon med risikoappetitt ${corrWord(i.riskCorr)})`);
    if (c.id !== "no" && i.m3 != null) bits.push(`en kurs som har gått <b>${pct(i.m3)}</b> mot kronen siste 3 mnd`);
    if (c.cot?.pct_oi != null) bits.push(`en posisjon spekulantene alt er <b>${c.cot.pct_oi > 0 ? "long" : "short"}</b> i (${signed(c.cot.pct_oi)} % av åpen interesse)`);
    if (c.ppp?.valuation != null) bits.push(`en valuta som er <b>${nb1.format(Math.abs(c.ppp.valuation))} % ${c.ppp.valuation > 0 ? "dyr" : "billig"}</b> mot USD målt i kjøpekraft`);
    return bits.join(", ");
  };

  // Merkelappene fra calc.js i vanlig norsk
  const TAG_TEXT = {
    carry: "får betalt for å vente", risikonøytral: "isolerer rentesynet", oljenøytral: "lik oljeeksponering",
    momentum: "medvind siste 3 mnd", kontrær: "motsatt av flokken", "allerede priset": "ligger alt i kursen", "mot strømmen": "mot markedets prising",
  };
  const render = () => {
    const chosen = countries.find((c) => c.id === legSel.value);
    const isLong = dirSel.value === "long";
    const rows = pairCandidates({ countries, info, chosen, isLong, volOf: (L, S) => realizedVol(pairSeries(history, L, S)) });
    const maxCarry = Math.max(1, ...rows.map((r) => Math.abs(r.carry ?? 0)));
    const pairName = (r) => `<b>${r.L.flag} ${r.L.currency}</b> / <b>${r.S.flag} ${r.S.currency}</b>`;
    const riskCell = (d) => (d == null ? "–" : Math.abs(d) < 0.25 ? `<span class="pos">ja</span>` : `<span class="neg">nei</span> <small>(Δ ${signed(d, nb2)})</small>`);
    // Positivt gap = markedet priser alt mer for long-beinet (synet ligger i kursen); negativt = du går mot prisingen
    const gapCell = (g) => (g == null ? "–" : Math.abs(g) < 13 ? `<span class="muted">lite</span>` : g > 0
      ? `<span class="neg">ja</span> <small>${moves(g)} mer for long-beinet</small>` : `nei <small>markedet priser ${moves(-g)} mer for short-beinet</small>`);
    const body = rows.map((r) => `<tr>
        <td>${pairName(r)}${r.other.id === "no" ? ` <small>(= bare cash)</small>` : ""}</td>
        ${barCell(r.carry, maxCarry, r.carry == null ? "–" : `${signed(r.carry, nb2)} pp`, cls(r.carry, 0.05))}
        <td title="Hvor mye mer heving/mindre kutt markedet allerede priser for det ene beinet">${gapCell(r.gap)}</td>
        <td>${riskCell(r.dRisk)}</td>
        <td class="extra ${cls(r.mom, 0.05)}">${r.mom == null ? "–" : pct1(r.mom)}</td>
        <td class="extra">${r.dOil == null ? "–" : Math.abs(r.dOil) < 0.25 ? `<span class="pos">lik</span>` : `Δ ${signed(r.dOil, nb2)}`}</td>
        <td class="extra">${r.vol == null ? "–" : `${nb1.format(r.vol)} %`}</td>
        <td class="tags">${r.tags.map(([t, why]) => `<span class="tag-chip ${t === "allerede priset" ? "warn" : ""}" title="${why}">${TAG_TEXT[t] ?? t}</span>`).join("")}</td>
      </tr>`).join("");
    const best = rows[0];
    const bestTags = best.tags.filter(([t]) => t !== "allerede priset" && t !== "carry").map(([t]) => TAG_TEXT[t] ?? t);
    const bits = [...bestTags, ...(best.carry != null ? [`carry ${signed(best.carry, nb2)} pp i året`] : [])];
    const summary = best && bits.length
      ? `<p class="lead">Beste match ut fra dataene: <b>long ${best.L.flag} ${best.L.currency} / short ${best.S.flag} ${best.S.currency}</b> (${bits.join(", ")}).</p>` : "";
    const legWord = isLong ? "Long" : "Short";
    const cashNote = chosen.id === "no"
      ? `Å sitte i kroner er også en posisjon: den følger oljeprisen (korrelasjon ${corrWord(info.no.oilCorr)}) og Norges Banks rente.`
      : `Selger du bare kroner for å kjøpe ${chosen.currency}, er kronen motparten – og den følger oljeprisen (korrelasjon ${corrWord(info.no.oilCorr)}) og Norges Banks rente (${moves(info.no.imp12)} ventet neste år).`;
    document.getElementById("pairResult").innerHTML = `
      <p class="pair-own"><b>${legWord} ${chosen.flag} ${chosen.currency}</b> betyr at du eier: ${describeLeg(chosen)}.
        ${isLong ? "Og du er samtidig short alt du ikke kjøpte." : "Og du er samtidig long alt annet."} ${cashNote}</p>
      ${summary}
      <div class="table-scroll"><table class="diff-table pair-table" id="pairTable">
        <thead><tr><th>Paret (long / short)</th><th>Får betalt for å vente</th><th>Ligger alt i kursen?</th><th>Reagerer likt på risiko?</th>
          <th class="extra">Siste 3 mnd</th><th class="extra">Olje</th><th class="extra">Svingninger</th><th>Passer til</th></tr></thead>
        <tbody>${body}</tbody>
      </table></div>
      <p class="risk-note"><label class="toggle"><input type="checkbox" id="pairMore"> vis flere kolonner (momentum, olje, volatilitet)</label>
        · Rangert etter antall treff, deretter carry. Hold musen over merkelappene for begrunnelse. Observasjoner, ikke anbefalinger.</p>
      <details class="method"><summary>Slik regnes det</summary><p>«Får betalt for å vente» (carry) = 1-års rente i long-beinet minus short-beinet.
        «Ligger alt i kursen?» = hvor mye mer heving/mindre kutt markedet allerede priser for det ene beinet; er det mye, trenger du at det skjer
        enda mer for å tjene på handelen. «Reagerer likt på risiko?» = om begge valutaene har samme 90-dagers samvariasjon med AUD/JPY
        (målt mot I-44-kurven), så paret ikke blir et skjult veddemål på risikoappetitt. Svingninger = realisert volatilitet i paret siste 30 dager.</p></details>`;
    document.getElementById("pairMore").addEventListener("change", (e) => document.getElementById("pairTable").classList.toggle("more", e.target.checked));
  };
  legSel.addEventListener("change", render);
  dirSel.addEventListener("change", render);
  render();
}

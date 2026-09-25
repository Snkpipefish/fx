/* Finn motparten: velg valuta (chips) og retning, få tre forslag med begrunnelse – hele tabellen bak «Vis alle». */
import { nb, nb1, nb2, pct, pct1, rate, signed, pp, moves, cls, name } from "./format.js";
import { legInfo, pairSeries, pairCandidates, realizedVol } from "./calc.js";

const TAG_TEXT = {
  carry: "får betalt for å vente", risikonøytral: "isolerer rentesynet", oljenøytral: "lik oljeeksponering",
  momentum: "medvind siste 3 mnd", kontrær: "motsatt av flokken", "allerede priset": "ligger alt i kursen", "mot strømmen": "mot markedets prising",
};

export function renderPairs(dashboard, history) {
  const countries = dashboard.countries;
  const info = legInfo(countries, history);
  const chips = document.getElementById("pairLeg"), dir = document.getElementById("pairDir");
  let leg = "us", isLong = true;
  chips.innerHTML = countries.map((c) => `<button type="button" data-id="${c.id}">${c.flag} ${c.currency}</button>`).join("");

  const corrWord = (v) => (v == null ? "–" : nb2.format(v));
  const riskLabel = (v) => (v == null ? "" : v > 0.3 ? "en risk-on-valuta" : v < -0.3 ? "en trygg havn" : "nøytral til risikoappetitt");
  const describeLeg = (c) => {
    const i = info[c.id], bits = [];
    if (i.imp12 != null) bits.push(`renteforventningene til ${c.bank} (<b>${moves(i.imp12)}</b> neste år)`);
    if (i.r1y != null) bits.push(`en rente på <b>${rate(i.r1y)}</b> i året`);
    if (i.riskCorr != null) bits.push(`<b>${riskLabel(i.riskCorr)}</b>`);
    if (c.id !== "no" && i.m3 != null) bits.push(`en kurs som har gått <b>${pct(i.m3)}</b> mot kronen siste 3 mnd`);
    if (c.cot?.pct_oi != null && Math.abs(c.cot.pct_oi) >= 15) bits.push(`en posisjon spekulantene alt er tungt <b>${c.cot.pct_oi > 0 ? "long" : "short"}</b> i`);
    return bits.join(", ");
  };
  const why = (r) => r.tags.filter(([t]) => t !== "allerede priset").map(([t]) => TAG_TEXT[t] ?? t);
  const stat = (lbl, val) => `<div class="pc-stat"><span>${lbl}</span><b>${val}</b></div>`;
  const cardFor = (title, r, reason) => `
    <div class="pair-card">
      <div class="pc-title">${title}</div>
      <div class="pc-pair">long ${r.L.flag} ${r.L.currency} <span class="muted">/</span> short ${r.S.flag} ${r.S.currency}</div>
      <p class="pc-why">${reason}</p>
      <div class="pc-stats">
        ${stat("Renteforskjell", r.carry == null ? "–" : `${signed(r.carry, nb2)} pp/år`)}
        ${stat("Alt i kursen?", r.gap == null ? "–" : Math.abs(r.gap) < 13 ? "lite" : r.gap > 0 ? `ja, ${moves(r.gap)}` : `nei`)}
        ${stat("Lik risikoprofil?", r.dRisk == null ? "–" : Math.abs(r.dRisk) < 0.25 ? "ja" : "nei")}
        ${stat("Svingninger", r.vol == null ? "–" : `${nb1.format(r.vol)} %`)}
      </div>
    </div>`;

  const render = () => {
    const chosen = countries.find((c) => c.id === leg);
    chips.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.id === leg));
    dir.querySelectorAll("button").forEach((b) => b.classList.toggle("on", (b.dataset.dir === "long") === isLong));
    const rows = pairCandidates({ countries, info, chosen, isLong, volOf: (L, S) => realizedVol(pairSeries(history, L, S)) });
    const best = rows[0];
    const carry = [...rows].filter((r) => r.carry != null).sort((a, b) => b.carry - a.carry)[0];
    const neutral = [...rows].filter((r) => r.dRisk != null && Math.abs(r.dRisk) < 0.25).sort((a, b) => Math.abs(a.dRisk) - Math.abs(b.dRisk))[0];
    const cards = [];
    if (best) cards.push(cardFor("Beste match", best, why(best).length ? `Treffer på ${why(best).join(", ")}.` : "Flest treff i dataene."));
    if (carry && carry !== best) cards.push(cardFor("Mest betalt for å vente", carry, `Du får ${nb2.format(carry.carry)} prosentpoeng i året i renteforskjell mens du venter.`));
    if (neutral && neutral !== best && neutral !== carry) cards.push(cardFor("Renest rentesyn", neutral, `Begge valutaene reagerer likt på risikoappetitt, så paret handler om renter – ikke om børsen.`));
    const cashNote = chosen.id === "no"
      ? `Å sitte i kroner er også en posisjon: den følger oljeprisen og Norges Banks rente.`
      : `Selger du bare kroner, er kronen motparten – og den følger oljeprisen (samvariasjon ${corrWord(info.no.oilCorr)}) og Norges Banks rente (${moves(info.no.imp12)} ventet neste år).`;
    const gapCell = (g) => (g == null ? "–" : Math.abs(g) < 13 ? `<span class="muted">lite</span>` : g > 0
      ? `<span class="neg">ja</span> <small>${moves(g)} mer for long-beinet</small>` : `nei <small>markedet priser ${moves(-g)} mer for short-beinet</small>`);
    const table = rows.map((r) => `<tr>
        <td><b>${r.L.flag} ${r.L.currency}</b> / <b>${r.S.flag} ${r.S.currency}</b>${r.other.id === "no" ? ` <small>(= bare cash)</small>` : ""}</td>
        <td class="${cls(r.carry, 0.05)}">${r.carry == null ? "–" : `${signed(r.carry, nb2)} pp`}</td>
        <td>${gapCell(r.gap)}</td>
        <td>${r.dRisk == null ? "–" : Math.abs(r.dRisk) < 0.25 ? `<span class="pos">ja</span>` : `<span class="neg">nei</span>`}</td>
        <td class="${cls(r.mom, 0.05)}">${r.mom == null ? "–" : pct1(r.mom)}</td>
        <td>${r.vol == null ? "–" : `${nb1.format(r.vol)} %`}</td>
        <td class="tags">${r.tags.map(([t, w]) => `<span class="tag ${t === "allerede priset" ? "warn" : ""}" title="${w}">${TAG_TEXT[t] ?? t}</span>`).join("")}</td>
      </tr>`).join("");
    document.getElementById("pairResult").innerHTML = `
      <p class="lead"><b>${isLong ? "Long" : "Short"} ${chosen.flag} ${chosen.currency}</b> betyr at du eier ${describeLeg(chosen)}.
        ${isLong ? "Og du er samtidig short alt du ikke kjøpte." : "Og du er samtidig long alt annet."} ${cashNote}</p>
      <div class="pair-cards">${cards.join("")}</div>
      <details class="more"><summary>Vis alle ${rows.length} kandidatene</summary>
        <div class="table-scroll"><table class="tbl">
          <thead><tr><th>Paret (long / short)</th><th>Renteforskjell</th><th>Alt i kursen?</th><th>Lik risikoprofil?</th><th>Siste 3 mnd</th><th>Svingninger</th><th>Kjennetegn</th></tr></thead>
          <tbody>${table}</tbody></table></div>
        <p class="note">Rangert etter antall treff, deretter renteforskjell. Hold musen over merkelappene for begrunnelse.</p>
      </details>
      <details class="more"><summary>Slik regnes det</summary><p class="note">Renteforskjell = 1-års rente i long-beinet minus short-beinet.
        «Alt i kursen?» = om markedet allerede priser mer heving for det beinet du kjøper; da må enda mer skje for at du skal tjene.
        «Lik risikoprofil?» = om begge valutaene svinger likt med risikoappetitten (AUD/JPY) siste 90 dager. Svingninger = realisert volatilitet
        i paret siste 30 dager. Observasjoner, ikke råd.</p></details>`;
  };
  chips.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { leg = b.dataset.id; render(); } });
  dir.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { isLong = b.dataset.dir === "long"; render(); } });
  render();
}

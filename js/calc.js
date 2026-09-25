/* Ren beregningslogikk uten DOM – testes med node --test (tests/calc.test.mjs). */
import { bp, rate, moves, sortedEntries } from "./format.js";

export function dailyReturns(series) {
  const e = sortedEntries(series);
  const out = {};
  for (let i = 1; i < e.length; i++) {
    if (e[i - 1][1] > 0 && e[i][1] > 0) out[e[i][0]] = Math.log(e[i][1] / e[i - 1][1]);
  }
  return out;
}

/** Pearson-korrelasjon mellom to {dato: avkastning} på felles datoer, siste `window` dager. */
export function correlation(ra, rb, window = 90) {
  const days = Object.keys(ra).filter((d) => d in rb).sort().slice(-window);
  if (days.length < 20) return null;
  const a = days.map((d) => ra[d]), b = days.map((d) => rb[d]);
  const ma = a.reduce((s, v) => s + v, 0) / a.length, mb = b.reduce((s, v) => s + v, 0) / b.length;
  let cov = 0, va = 0, vb = 0;
  for (let i = 0; i < a.length; i++) { cov += (a[i] - ma) * (b[i] - mb); va += (a[i] - ma) ** 2; vb += (b[i] - mb) ** 2; }
  return va && vb ? cov / Math.sqrt(va * vb) : null;
}

/** Annualisert realisert volatilitet (%) fra daglige logavkastninger. */
export function realizedVol(series, window = 30) {
  const r = Object.values(dailyReturns(series)).slice(-window);
  if (r.length < 10) return null;
  const m = r.reduce((s, v) => s + v, 0) / r.length;
  const v = r.reduce((s, x) => s + (x - m) ** 2, 0) / (r.length - 1);
  return Math.sqrt(v) * Math.sqrt(252) * 100;
}

/** Spotrente ved 1 år fra kurven (lineært interpolert), ellers 3 mnd-renten. */
export function rate1y(c) {
  const pts = Object.entries(c.curve?.points || {}).map(([t, v]) => [+t, v]).sort((a, b) => a[0] - b[0]);
  if (!pts.length) return c.rates?.m3 ?? null;
  if (1 <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    if (1 <= pts[i][0]) { const [t0, r0] = pts[i - 1], [t1, r1] = pts[i]; return r0 + (r1 - r0) * (1 - t0) / (t1 - t0); }
  }
  return pts[pts.length - 1][1];
}

/** «bunn 3,10 % om 14 mnd» – ytterpunktet i den impliserte rentebanen. */
export function extremeText(curve) {
  const e = curve?.extreme;
  if (!e) return "";
  if (Math.abs(e.bp) < 10) return "flat bane neste 2 år";
  return `${e.bp < 0 ? "bunn" : "topp"} ${rate(e.level)} om ${e.months} mnd`;
}

/**
 * Inflasjonen banken styrer etter: kjernemålet når det er bankens målvariabel (kjerne-PCE,
 * trimmet gjennomsnitt, CPI-trim/median, KPI-JAE, KPIF), ellers samlet KPI (BoE, SNB, BoJ, RBNZ).
 */
export function targetInflation(c) {
  if (c.cpi_core?.is_target && c.cpi_core.value != null) {
    return { value: c.cpi_core.value, label: c.cpi_core.label.split(" (")[0], note: " (mot målvariabelen)" };
  }
  if (c.cpi?.value != null) return { value: c.cpi.value, label: "KPI", note: "" };
  return { value: c.cpi_core?.value ?? null, label: c.cpi_core?.label?.split(" (")[0] ?? "", note: c.cpi_core ? " (mot kjerne)" : "" };
}

/**
 * Datadrevet retningssignal for valutaen (heuristikk, ikke prognose), vist som «2 av 3 drivere»:
 *  - rente:      hva rentekurven priser av endringer neste 6 mnd (fallback: 3 mnd-rente minus styringsrente)
 *  - momentum:   kursutvikling mot NOK siste 3 mnd
 *  - realrente:  styringsrente minus inflasjonen banken styrer etter
 * Hver driver får en pil (▲ ▼ ▶); samlet retning krever at minst to peker samme vei. Den gamle
 * vektede summen (0,45/0,35/0,20) beholdes som `score` til scripts/backtest_signal.py har
 * kalibrert vektene mot ekte avkastning; da kan den tas i bruk igjen.
 */
export function directionSignal(c) {
  const invert = c.fx?.index; // I-44: lavere indeks = sterkere krone
  const drivers = [];
  let score = 0;
  const clamp = (v) => Math.max(-1, Math.min(1, v));
  const arrowOf = (d) => ({ up: "▲", down: "▼", flat: "▶" }[d]);

  const imp6 = c.curve?.implied?.["6m"];
  const m3 = c.rates?.m3, policy = c.rates?.policy;
  if (imp6 != null) {
    score += clamp(imp6 / 40) * 0.45;
    const dir = imp6 > 15 ? "up" : imp6 < -15 ? "down" : "flat";
    drivers.push({ key: "rente", dir, text: Math.abs(imp6) > 15 ? `markedet venter <b>${moves(imp6)}</b> innen 6 mnd` : "markedet venter <b>uendret rente</b> neste 6 mnd" });
  } else if (m3 != null && policy != null) {
    const spread = m3 - policy;
    score += clamp(spread / 0.4) * 0.45;
    const dir = spread > 0.15 ? "up" : spread < -0.15 ? "down" : "flat";
    drivers.push({ key: "rente", dir, text: `pengemarkedet venter <b>${dir === "up" ? "renteheving" : dir === "down" ? "rentekutt" : "uendret rente"}</b>` });
  }

  let mom = c.fx?.changes?.m3;
  if (mom != null) {
    if (invert) mom = -mom;
    score += clamp(mom / 4) * 0.35;
    const dir = mom > 0.5 ? "up" : mom < -0.5 ? "down" : "flat";
    drivers.push({ key: "momentum", dir, text: dir === "up" ? "valutaen har <b>styrket seg</b> siste 3 mnd" : dir === "down" ? "valutaen har <b>svekket seg</b> siste 3 mnd" : "kursen har ligget <b>stille</b> siste 3 mnd" });
  }

  // Realrente mot det banken faktisk styrer etter: målvariabelen der vi har den, ellers samlet KPI
  const target = targetInflation(c);
  if (policy != null && target.value != null) {
    const real = policy - target.value;
    score += clamp(real / 2) * 0.2;
    const dir = real > 0.5 ? "up" : real < -0.5 ? "down" : "flat";
    drivers.push({ key: "realrente", dir, text: dir === "up" ? `positiv realrente${target.note}` : dir === "down" ? `negativ realrente${target.note}` : `realrente rundt 0${target.note}` });
  }

  const ups = drivers.filter((d) => d.dir === "up").length, downs = drivers.filter((d) => d.dir === "down").length;
  const dir = ups >= 2 && ups > downs ? "up" : downs >= 2 && downs > ups ? "down" : "flat";
  const arrow = arrowOf(dir);
  const n = drivers.length;
  const word = !n ? "For lite data"
    : dir === "up" ? `${ups} av ${n} drivere styrker` : dir === "down" ? `${downs} av ${n} drivere svekker`
    : ups && downs ? "Delt bilde" : "Nøytralt bilde";
  const text = drivers.map((d) => `${arrowOf(d.dir)} ${d.text}`).join(" · ") || "For lite data";
  return { dir, arrow, word, score, drivers, ups, downs, text };
}

/**
 * Egenskaper per valuta til motpost-modulen. Hver valuta måles mot Norges Banks
 * handelsvektede kurv (I-44), så NOK-støy ikke farger korrelasjonene:
 * X/NOK ÷ I-44 ≈ X mot kurven; NOK selv = 1/I-44.
 */
export function legInfo(countries, history) {
  const i44 = history.fx?.I44 || {};
  const riskRet = dailyReturns(history.market?.audjpy || {});
  const oilRet = dailyReturns(history.market?.brent || {});
  const gasRet = dailyReturns(history.market?.ttf || {});
  const worldSeries = (c) => {
    if (c.id === "no") return Object.fromEntries(Object.entries(i44).map(([d, v]) => [d, 1 / v]));
    const s = history.fx?.[c.currency] || {};
    return Object.fromEntries(Object.entries(s).filter(([d]) => i44[d]).map(([d, v]) => [d, v / i44[d]]));
  };
  const info = {};
  for (const c of countries) {
    const wr = dailyReturns(worldSeries(c));
    info[c.id] = {
      riskCorr: correlation(wr, riskRet),
      oilCorr: correlation(wr, oilRet),
      gasCorr: correlation(wr, gasRet),
      r1y: rate1y(c),
      imp12: c.curve?.implied?.["12m"] ?? null,
      m3: c.id === "no" ? 0 : c.fx?.changes?.m3 ?? null, // endring mot NOK siste 3 mnd
    };
  }
  return info;
}

/** Kursserie for paret long/short (NOK per enhet av long-beinet målt i short-beinet). */
export function pairSeries(history, L, S) {
  const l = L.id === "no" ? null : history.fx?.[L.currency] || {};
  const s = S.id === "no" ? null : history.fx?.[S.currency] || {};
  if (!l) return Object.fromEntries(Object.entries(s).map(([d, v]) => [d, 1 / v]));
  if (!s) return l;
  return Object.fromEntries(Object.entries(l).filter(([d]) => s[d]).map(([d, v]) => [d, v / s[d]]));
}

/**
 * Kandidater til motposten for valgt valuta og retning. Returnerer rader sortert
 * etter antall positive treff, deretter carry – bevisst enkelt og forklarbart.
 */
export function pairCandidates({ countries, info, chosen, isLong, volOf }) {
  const rows = countries.filter((c) => c.id !== chosen.id).map((other) => {
    const L = isLong ? chosen : other, S = isLong ? other : chosen;
    const iL = info[L.id], iS = info[S.id];
    const carry = iL.r1y != null && iS.r1y != null ? iL.r1y - iS.r1y : null;
    const gap = iL.imp12 != null && iS.imp12 != null ? iL.imp12 - iS.imp12 : null;
    const mom = iL.m3 != null && iS.m3 != null ? ((1 + iL.m3 / 100) / (1 + iS.m3 / 100) - 1) * 100 : null;
    const dRisk = iL.riskCorr != null && iS.riskCorr != null ? iL.riskCorr - iS.riskCorr : null;
    const dOil = iL.oilCorr != null && iS.oilCorr != null ? iL.oilCorr - iS.oilCorr : null;
    const dGas = iL.gasCorr != null && iS.gasCorr != null ? iL.gasCorr - iS.gasCorr : null;
    const vol = volOf ? volOf(L, S) : null;
    const crowded = S.cot?.pct_oi != null && S.cot.pct_oi >= 20 ? S.cot.pct_oi : null;
    const tags = [];
    if (carry != null && carry > 0.5) tags.push(["carry", `Du får betalt ${carry.toFixed(2).replace(".", ",")} pp i året for å vente`]);
    if (dRisk != null && Math.abs(dRisk) < 0.25) tags.push(["risikonøytral", "Begge beina reagerer likt på risikoappetitt – paret isolerer rente-/makrosynet"]);
    // Energinøytral: lik eksponering mot både olje og gass (gass teller bare der vi har korrelasjonen)
    if (dOil != null && Math.abs(dOil) < 0.25 && (dGas == null || Math.abs(dGas) < 0.25)) tags.push(["energinøytral", dGas == null ? "Lik oljeeksponering på begge sider" : "Lik eksponering mot olje og gass på begge sider"]);
    if (mom != null && mom > 1) tags.push(["momentum", `Paret har gått ${mom.toFixed(1).replace(".", ",")} % din vei siste 3 mnd`]);
    if (crowded != null) tags.push(["kontrær", `Ikke-kommersielle er +${crowded} % av OI long ${S.currency} – short-beinet er fullt`]);
    if (gap != null && gap >= 25) tags.push(["allerede priset", `Markedet priser ${bp(gap)} mer for ${L.currency} enn ${S.currency} – du trenger mer enn det som ligger i kurven`]);
    if (gap != null && gap <= -25) tags.push(["mot strømmen", `Markedet priser ${bp(-gap)} mer for ${S.currency}; du satser på at det reverseres`]);
    return { L, S, other, carry, gap, mom, dRisk, dOil, dGas, vol, crowded, tags };
  });
  const positive = (r) => r.tags.filter(([t]) => t !== "allerede priset").length;
  rows.sort((a, b) => positive(b) - positive(a) || (b.carry ?? -99) - (a.carry ?? -99));
  return rows;
}


/**
 * Totalavkastning av å eie valuta X finansiert i kroner: kursendring pluss renteforskjellen
 * dag for dag, TR_t = TR_{t−1} · S_t/S_{t−1} · (1 + (r_X − r_NOK)/100/360 · dager).
 * Rentene er månedlige 3-mnd-renter ({«ÅÅÅÅ-MM»: %}); siste kjente måned brukes fremover.
 * Returnerer {dato: indeks} rebasert til 100 på første dato, eller null uten renter.
 */
export function totalReturn(fxSeries, ratesX, ratesNok) {
  const e = sortedEntries(fxSeries);
  if (e.length < 2 || !ratesX || !ratesNok) return null;
  const monthly = (rates) => { const m = Object.keys(rates).sort(); return (day) => { let v = null; for (const k of m) { if (k <= day.slice(0, 7)) v = rates[k]; else break; } return v; }; };
  const rx = monthly(ratesX), rn = monthly(ratesNok);
  const out = { [e[0][0]]: 100 };
  let tr = 100;
  for (let i = 1; i < e.length; i++) {
    const [d0, s0] = e[i - 1], [d1, s1] = e[i];
    const days = Math.round((new Date(d1) - new Date(d0)) / 86400000);
    const carry = rx(d0) != null && rn(d0) != null ? (rx(d0) - rn(d0)) / 100 / 360 * days : 0;
    tr = tr * (s1 / s0) * (1 + carry);
    out[d1] = +tr.toFixed(3);
  }
  return out;
}

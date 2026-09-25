/* Redaksjonell oversikt: hero, renteforventninger (hantelgraf), kronen (søyleliste), tre ting, kildestatus. */
import { nb0, nb1, nb2, pct1, rate, signed, pp, moves, cls, shortDate, daysUntil, color, name } from "./format.js";
import { extremeText } from "./calc.js";
import { dumbbellChart, barList } from "./charts.js";

const longDate = new Intl.DateTimeFormat("nb-NO", { weekday: "long", day: "numeric", month: "long" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const i12 = (c) => c.curve.implied["12m"];
/** Hva banen er lest ut av: futures på styringsrenten, OIS eller statskurve (inkl. terminpremie). */
export const curveKind = (c) => ({ futures: "futures", ois: "OIS", govt: "statskurve", zero: "statskurve" })[c.curve?.kind] ?? "";

/** Overskriften: hva markedet venter, i én setning. */
function headline(rows) {
  if (!rows.length) return "Rentekurvene er ikke tilgjengelige ennå.";
  const up = rows.filter((c) => i12(c) >= 13), down = rows.filter((c) => i12(c) <= -13);
  const who = (list) => list.map((c) => c.name).join(", ").replace(/, ([^,]*)$/, " og $1");
  if (up.length === rows.length) return "Markedet venter høyere renter fra alle sentralbankene det neste året.";
  if (down.length === rows.length) return "Markedet venter lavere renter fra alle sentralbankene det neste året.";
  if (up.length && down.length) return `Markedet venter hevinger i ${who(up)}, og kutt i ${who(down)}.`;
  if (up.length) return `Markedet venter hevinger i ${who(up)} – og uendret rente ellers.`;
  if (down.length) return `Markedet venter kutt i ${who(down)} – og uendret rente ellers.`;
  return "Markedet venter om lag uendrede renter det neste året.";
}

export function renderHero(countries, market, updated) {
  const rows = countries.filter((c) => c.curve);
  document.getElementById("kicker").textContent = `G10 valutabrief · ${cap(longDate.format(new Date(updated)))}`;
  document.getElementById("headline").textContent = headline(rows);

  const stats = [];
  // 1) Nærmest et vedtak: banken med neste møte der markedet priser en bevegelse
  const soon = countries.filter((c) => c.next_meeting && (c.next_meeting.bp != null ? Math.abs(c.next_meeting.bp) >= 10 : Math.abs(c.next_meeting.bp_3m ?? 0) >= 13))
    .sort((a, b) => a.next_meeting.date.localeCompare(b.next_meeting.date))[0];
  if (soon) {
    const nm = soon.next_meeting, d = daysUntil(nm.date);
    const what = nm.prob != null ? `<span title="${nm.source}">~${Math.round(nm.prob * 100)} % for ${nm.move ?? "bevegelse"}</span>`
      : nm.bp != null ? `<span title="${nm.source}">${pp(nm.bp)} priset</span>` : `kurven priser ${moves(nm.bp_3m)} innen 3 mnd`;
    stats.push([`<span class="text">${soon.flag} ${soon.bank.replace("Reserve Bank of ", "RB ")}</span>`, `nærmest et vedtak: ${shortDate(nm.date)}, ${d === 0 ? "i dag" : `om ${d} dager`} · ${what}`]);
  }
  // 2) Mest priset på 12 mnd, som nivå fra → til
  if (rows.length) {
    const most = [...rows].sort((a, b) => Math.abs(i12(b)) - Math.abs(i12(a)))[0];
    stats.push([`<span class="text nowrap">${rate(most.rates.policy)} → ${rate(most.curve.path[12])}</span>`, `mest priset på 12 mnd: ${most.bank}, ${moves(i12(most))} <span title="Antall hevinger belønner lavt utgangspunkt; sier ikke at vedtaket er nært">– fra lavt nivå</span>`]);
  }
  // 3) Størst uenighet med bankens eget anslag
  const gaps = rows.filter((c) => c.cb_path?.level != null).map((c) => ({ c, gap: c.curve.path[12] - c.cb_path.level })).sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  if (gaps.length) {
    const { c, gap } = gaps[0];
    stats.push([`<span class="${cls(gap)}">${signed(gap, nb2)} pp</span>`, `størst uenighet med banken selv: ${c.currency} ligger ${gap > 0 ? "over" : "under"} ${c.bank}s eget anslag`]);
  }
  // 4) Ukens sterkeste mot kronen
  const movers = countries.filter((c) => c.fx && !c.fx.index && c.fx.changes?.w1 != null).sort((a, b) => b.fx.changes.w1 - a.fx.changes.w1);
  if (movers.length) {
    const b = movers[0];
    stats.push([`<span class="${cls(b.fx.changes.w1)}">${pct1(b.fx.changes.w1)}</span>`, `${b.currency} er sterkest mot kronen denne uken`]);
  }
  document.getElementById("heroStats").innerHTML = stats.slice(0, 4).map(([big, lbl]) =>
    `<div class="stat"><div class="big">${big}</div><div class="lbl">${lbl}</div></div>`).join("");
}

/** Seksjon 1: rente nå og ventet om 12 mnd, som hantelgraf, pluss tekstliste. */
export function renderRates(countries) {
  const rows = countries.filter((c) => c.curve && c.rates.policy != null).sort((a, b) => i12(a) - i12(b));
  const missing = countries.filter((c) => !c.curve).map((c) => c.currency);
  const el = document.getElementById("rates");
  if (!rows.length) { el.innerHTML = `<p class="note">Ingen rentekurver tilgjengelig ennå.</p>`; return; }
  const chartRows = rows.map((c) => ({
    id: c.id, flag: c.flag, label: c.bank.replace("Reserve Bank of ", "RB ").replace("Swiss National Bank", "SNB"), short: c.currency,
    now: c.rates.policy, expected: c.curve.path[12], six: c.curve.path[6], color: color(c),
    text: `${rate(c.curve.path[12])} (${moves(i12(c))})`, textShort: rate(c.curve.path[12]),
    title: `${c.bank}: ${rate(c.rates.policy)} nå, ${rate(c.curve.path[12])} ventet om 12 mnd (${pp(i12(c))}) · ${c.curve.source}`,
    bank: c.cb_path?.level ?? null,
    bankTitle: c.cb_path ? `${c.bank}s eget anslag: ${rate(c.cb_path.level)} ${c.cb_path.horizon} (${c.cb_path.source})` : "",
  }));
  // Hvor ligger markedet lengst fra sentralbankens egen bane?
  const gaps = rows.filter((c) => c.cb_path?.level != null)
    .map((c) => ({ c, gap: c.curve.path[12] - c.cb_path.level }))
    .sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  const gapText = gaps.length ? `<p class="lead">Markedet ligger lengst fra sentralbankens eget anslag for
    ${gaps.slice(0, 3).map(({ c, gap }) => `<b>${c.currency}</b> (${gap > 0 ? "over" : "under"} med ${nb2.format(Math.abs(gap))} pp)`).join(", ")}.
    Der har kursen mest å tape hvis banken får rett.</p>` : "";
  const list = rows.map((c) => {
    const r = c.curve.repricing?.w1;
    const week = r == null || Math.abs(r) < 5 ? "" : ` <span class="${cls(r)}">${r > 0 ? "↑" : "↓"} ${r > 0 ? "høyere" : "lavere"} enn for en uke siden</span>`;
    const src = c.rates.policy_source && c.rates.policy_source !== "BIS" ? ` <small>(${c.rates.policy_source})</small>` : "";
    const bank = c.cb_path ? ` · banken selv: ${rate(c.cb_path.level)} ${c.cb_path.horizon}` : "";
    const kind = curveKind(c) ? ` <small class="muted" title="${c.curve.source}">${curveKind(c)}</small>` : "";
    return `<li><b>${c.flag} ${c.bank}</b>${kind} · ${rate(c.rates.policy)} nå${src} → <b>${moves(i12(c))}</b> neste 12 mnd
      <span class="muted">(${pp(i12(c))}, ${extremeText(c.curve)}${bank})</span>${week}</li>`;
  }).join("");
  el.innerHTML = `
    <div id="dumbbell"></div>
    ${gapText}
    <details class="more"><summary>Vis som liste</summary><ul class="plain">${list}</ul></details>
    <p class="note">Én heving eller ett kutt = 0,25 prosentpoeng. Lest ut av futures på styringsrenten (USD, AUD, CAD), OIS (GBP) eller statskurven (øvrige, med terminpremie), oppdatert hver ukedag.
      ${missing.length ? `Ingen kurve tilgjengelig for ${missing.join(" og ")}.` : ""}</p>`;
  // Kompakt graf på smale skjermer; tegnes på nytt når bredden krysser grensen
  const mq = window.matchMedia("(max-width: 640px)");
  const draw = () => { document.getElementById("dumbbell").innerHTML = dumbbellChart(chartRows, { compact: mq.matches }); };
  mq.addEventListener("change", draw);
  draw();
}

/** Seksjon 2: kronen – hvem har gått mest mot NOK, valgbar horisont, pluss risikobildet. */
export function renderKrone(countries, market) {
  const no = countries.find((c) => c.id === "no");
  const horizons = [["w1", "uke"], ["m1", "måned"], ["m3", "3 mnd"], ["y1", "år"]];
  const el = document.getElementById("krone");
  const draw = (h) => {
    const rows = countries.filter((c) => c.fx && !c.fx.index && c.fx.changes?.[h] != null)
      .map((c) => ({ label: c.currency, flag: c.flag, value: c.fx.changes[h] })).sort((a, b) => b.value - a.value);
    document.getElementById("kroneBars").innerHTML = barList(rows, (v) => pct1(v));
    document.querySelectorAll("#kroneChips button").forEach((b) => b.classList.toggle("on", b.dataset.h === h));
  };
  const nokChange = no?.fx?.changes?.w1 != null ? -no.fx.changes.w1 : null; // I-44: lavere = sterkere krone
  const risk = (() => {
    if (!market.vix) return "";
    const v = market.vix.value, aj = market.audjpy?.changes?.m1;
    const score = (v < 18 ? 1 : v > 25 ? -1 : 0) + (aj == null ? 0 : aj > 1 ? 1 : aj < -2 ? -1 : 0);
    const word = score > 0 ? "høy" : score < 0 ? "lav" : "nøytral";
    return `Risikoappetitten er <b>${word}</b> (VIX ${nb1.format(v)}${aj != null ? `, AUD/JPY ${pct1(aj)} siste måned` : ""})${score > 0 ? ", som normalt støtter kronen" : score < 0 ? ", som normalt svekker kronen" : ""}.`;
  })();
  const oil = (() => {
    if (!market.brent && !market.brent_fut) return "";
    const parts = [];
    if (market.brent_fut) parts.push(`Brent-futures koster <b>${nb0.format(market.brent_fut.value)} USD</b> (${pct1(market.brent_fut.changes?.m1)} siste måned, ${market.brent_fut.contract ?? "front-kontrakten"})`);
    if (market.brent) parts.push(`fysisk Brent (Dated, ${shortDate(market.brent.date)}) <b>${nb0.format(market.brent.value)} USD</b>`);
    let premium = "";
    if (market.brent_premium) {
      const d = market.brent_premium.value;
      premium = Math.abs(d) >= 3 ? ` Spotpremien på ${nb0.format(d)} USD samme dag er et ${d > 0 ? "tegn på stramt fysisk marked" : "tegn på slakt fysisk marked"}.` : "";
    }
    const corr = market.brent_nok_corr != null ? ` Kronen har fulgt oljen med korrelasjon ${nb2.format(market.brent_nok_corr)} siste 90 dager.` : "";
    return `<p class="lead">${parts.join(", ")}.${premium}${corr}</p>`;
  })();
  const gas = market.ttf ? `<p class="lead">Gass (TTF) koster <b>${nb0.format(market.ttf.value)} EUR/MWh</b> (${pct1(market.ttf.changes?.m1)} siste måned).</p>` : "";
  el.innerHTML = `
    <p class="lead">${nokChange != null ? `Kronen er <b class="${cls(nokChange)}">${pct1(nokChange)}</b> mot handelspartnerne denne uken (I-44).` : ""}
      ${risk}</p>${oil}${gas}
    <div class="chips" id="kroneChips">${horizons.map(([h, l]) => `<button type="button" data-h="${h}">${l}</button>`).join("")}</div>
    <div id="kroneBars"></div>
    <p class="note">Positivt = valutaen har styrket seg mot kronen. Kilde: ECBs referansekurser.</p>`;
  el.querySelectorAll("#kroneChips button").forEach((b) => b.addEventListener("click", () => draw(b.dataset.h)));
  draw("w1");
}

/** Seksjon 3: tre ting å legge merke til – automatisk fra dataene. */
export function renderIdeas(countries, market) {
  const ideas = [];
  const withCurve = countries.filter((c) => c.curve);
  if (withCurve.length >= 2) {
    const by12 = [...withCurve].sort((a, b) => i12(a) - i12(b));
    const dove = by12[0], hawk = by12[by12.length - 1], gap = i12(hawk) - i12(dove);
    if (gap >= 25) {
      // Kontekst i vanlige setninger: hva er priset for neste møte, nylig vedtak, bankens eget anslag
      const context = (c, name) => {
        const nm = c.next_meeting, pc = c.policy_change, out = [];
        const soonBp = nm?.bp ?? nm?.bp_3m ?? null;
        if (pc && pc.to > pc.from && daysUntil(pc.date) > -45) out.push(`${name} hevet nettopp (${shortDate(pc.date)}).`);
        if (nm && soonBp != null) out.push(Math.abs(soonBp) < 10
          ? `Bare ${pp(soonBp)} er priset for ${out.length ? "møtet" : name + "s møte"} ${shortDate(nm.date)} – syklusen ligger lenger ut.`
          : `${pp(soonBp)} er priset for ${out.length ? "møtet" : name + "s møte"} ${shortDate(nm.date)}.`);
        if (c.cb_path) out.push(`${out.length ? "Banken" : name} sier selv ${rate(c.cb_path.level)} ${c.cb_path.horizon}.`);
        return out.join(" ");
      };
      ideas.push({ tag: "Størst sprik", text:
        `Markedet venter <b>${moves(i12(hawk))}</b> fra ${hawk.bank}, men bare <b>${moves(i12(dove))}</b> fra ${dove.bank}. Renteforskjellen
         ${hawk.currency}–${dove.currency} ventes altså å øke med ${nb2.format(gap / 100)} pp. ${context(hawk, hawk.bank)} ${context(dove, dove.bank)}
         Tror du markedet tar feil, er ${hawk.currency}/${dove.currency} paret å se på.` });
    }
    const rep = withCurve.filter((c) => c.curve.repricing?.w1 != null).sort((a, b) => Math.abs(b.curve.repricing.w1) - Math.abs(a.curve.repricing.w1));
    if (rep.length && Math.abs(rep[0].curve.repricing.w1) >= 8) {
      const r = rep[0].curve.repricing.w1;
      ideas.push({ tag: "I bevegelse", text: `Forventningene til <b>${rep[0].bank}</b> har flyttet seg mest siste uke: ${r > 0 ? "høyere" : "lavere"} rente
        ventet (${pp(r)}). Slike skift smitter ofte over på valutaen – sjekk om ${rep[0].currency} har hengt med.` });
    }
    for (const c of withCurve) {
      // Målvariabelen der den finnes (KPIF, KPI-JAE, kjerne), ellers KPI
      const cpi = c.cpi_core?.value ?? c.cpi?.value;
      if (cpi == null) continue;
      const which = c.cpi_core ? ` (${c.cpi_core.label.split(" (")[0]})` : "";
      if (i12(c) <= -25 && cpi >= 3) ideas.push({ tag: "Kutt tross høy inflasjon", text: `Markedet venter <b>${moves(i12(c))}</b> fra ${c.bank} selv om
        inflasjonen${which} er ${nb1.format(cpi)} %. Faller ikke inflasjonen, kan kuttene forsvinne fra kursen – det ville støtte ${c.currency}.` });
      else if (i12(c) >= 25 && cpi <= 1.5) ideas.push({ tag: "Hevinger tross lav inflasjon", text: `Markedet venter <b>${moves(i12(c))}</b> fra ${c.bank} med en
        inflasjon${which} på bare ${nb1.format(cpi)} %. Uteblir hevingene, er ${c.currency} sårbar.` });
    }
  }
  const delivered = countries.filter((c) => c.policy_change && c.policy_change.to > c.policy_change.from && c.policy_change.fx_since != null && c.policy_change.fx_since < 0)
    .sort((a, b) => a.policy_change.fx_since - b.policy_change.fx_since);
  for (const c of delivered.slice(0, 1)) {
    const pc = c.policy_change;
    const carry = c.fwd_fx_1y && c.fwd_fx_1y.diff > 0 ? ` Renteforskjellen mot kronen er likevel ${signed(c.fwd_fx_1y.diff, nb2)} pp i ${c.currency}s favør.` : "";
    ideas.push({ tag: "Heving levert, kurs ikke fulgt", text: `${c.bank} hevet til <b>${rate(pc.to)}</b> ${shortDate(pc.date)}, men ${c.currency} er
      <b>${pct1(pc.fx_since)}</b> mot handelspartnerne siden. Enten var hevingen alt i kursen, eller så la banken vekt på pause videre.${carry}` });
  }
  const carry = countries.filter((c) => c.fwd_fx_1y).sort((a, b) => b.fwd_fx_1y.diff - a.fwd_fx_1y.diff);
  if (carry.length >= 2) {
    const lo = carry[carry.length - 1];
    ideas.push({ tag: "Betalt for å vente", text: `Å eie kroner mot <b>${lo.currency}</b> gir ${nb2.format(-lo.fwd_fx_1y.diff)} prosentpoeng i året i renteforskjell.
      Kursen må gå ${nb2.format(Math.abs(lo.fwd_fx_1y.pct))} % mot deg før det spises opp – det er terminkursen ${nb2.format(lo.fwd_fx_1y.rate)}.` });
  }
  const crowded = countries.filter((c) => c.cot?.pct_oi != null && Math.abs(c.cot.pct_oi) >= 25).sort((a, b) => Math.abs(b.cot.pct_oi) - Math.abs(a.cot.pct_oi));
  if (crowded.length) {
    const c = crowded[0];
    ideas.push({ tag: "Alle på samme side", text: `Spekulantene er tungt <b>${c.cot.net > 0 ? "long" : "short"} ${c.currency}</b> (${signed(c.cot.pct_oi)} % av åpen
      interesse). Når alle sitter likt, blir reverseringene brå – særlig rundt rentemøtet ${shortDate(c.meeting)}.` });
  }
  const shown = ideas.slice(0, 4);
  const words = ["Ingenting", "Én ting", "To ting", "Tre ting", "Fire ting"];
  const h = document.getElementById("ideasHeading");
  if (h) h.textContent = `${words[shown.length]} å legge merke til`;
  document.getElementById("ideas").innerHTML = shown.map((i, n) =>
    `<div class="idea"><div class="num">0${n + 1}</div><div><div class="tag">${i.tag}</div><p>${i.text}</p></div></div>`).join("")
    || `<p class="note">For lite data til å peke på noe ennå.</p>`;
}

/** Kildestatus i bunnteksten. */
export function renderSources(sources, updated) {
  const el = document.getElementById("sources");
  if (!el || !sources) return;
  const labels = { fx: "Valutakurser (ECB)", i44: "I-44 (Norges Bank)", policy: "Styringsrenter (BIS)", irlt: "10-års renter (OECD)",
    ir3: "3-mnd renter (OECD)", cpi: "KPI (OECD/Eurostat)", unemployment: "Ledighet (OECD/Eurostat)", brent: "Brent (FRED)", vix: "VIX (FRED)",
    cot: "COT (CFTC)", ppp: "PPP (World Bank)", cpi_core: "Kjerne-KPI (OECD/Eurostat)", ons_cpi: "KPI Storbritannia (ONS)", ssb_kpi_jae: "KPI-JAE (SSB)", scb_kpif: "KPIF (SCB)",
    brent_fut: "Brent-futures (Yahoo)", ttf: "TTF-gass (Yahoo)", curve_us: "Kurve USD", curve_ea: "Kurve EUR", curve_jp: "Kurve JPY", curve_gb: "Kurve GBP",
    curve_ca: "Kurve CAD", curve_au: "Kurve AUD", curve_se: "Kurve SEK", curve_no: "Kurve NOK",
    futures_us: "Fed funds-futures (CME/Yahoo)", futures_au: "Cash rate-futures (ASX)", futures_ca: "CORRA-futures (TMX)" };
  const today = new Date(updated);
  const age = (iso) => (iso ? Math.round((today - new Date(iso.length === 4 ? `${iso}-12-31` : iso.length === 7 ? `${iso}-28` : iso)) / 86400000) : null);
  const limit = (k) => (k === "ppp" ? 800 : k === "cot" ? 14 : ["irlt", "ir3", "cpi", "cpi_core", "ons_cpi", "ssb_kpi_jae", "scb_kpif", "unemployment"].includes(k) ? 75 : 10);
  const items = Object.entries(sources).map(([k, s]) => {
    const a = age(s.latest);
    return { label: labels[k] || k, ok: s.ok, latest: s.latest, stale: !s.ok || a == null || a > limit(k), error: s.error };
  });
  const bad = items.filter((i) => i.stale);
  el.innerHTML = `<details class="more"><summary>Kildestatus: ${items.length - bad.length} av ${items.length} oppdatert${bad.length ? ` · <span class="neg">${bad.length} bak</span>` : ""}</summary>
    <ul class="sources">${items.map((i) => `<li class="${i.stale ? "neg" : ""}">${i.stale ? "⚠" : "✓"} ${i.label}: ${i.latest ?? "ingen data"}${i.ok ? "" : ` (feilet: ${i.error ?? "ukjent"})`}</li>`).join("")}</ul></details>`;
}

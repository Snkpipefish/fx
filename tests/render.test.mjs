/* Frontend-tester: hver seksjon rendres fra fixtures i jsdom, uten nettleser.
 * Kjør: node --test tests/render.test.mjs   (UPDATE_SNAPSHOTS=1 for å skrive idé-snapshots på nytt) */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "index.html"), "utf8");
const fixture = (name) => JSON.parse(readFileSync(join(here, "fixtures", name), "utf8"));
const TODAY = "2026-09-25";

// Ett jsdom-vindu for hele fila: ES-moduler importeres én gang og leser `document` ved kall.
const dom = new JSDOM(html, { url: "https://example.test/" });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
globalThis.localStorage = dom.window.localStorage;
globalThis.HTMLElement = dom.window.HTMLElement;
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.matchMedia = dom.window.matchMedia;
// Chart.js brukes bare til to linjegrafer; en stub registrerer kallene
const charts = [];
globalThis.Chart = class { constructor(canvas, config) { this.canvas = canvas; this.data = config.data; this.options = config.options; charts.push(this); }
  update() {} setDatasetVisibility() {} isDatasetVisible() { return true; } static getChart() { return null; } };

const overview = await import("../js/overview.js");
const cards = await import("../js/cards.js");
const pairs = await import("../js/pairs.js");
const chartsMod = await import("../js/charts.js");

function reset() {
  document.documentElement.innerHTML = new JSDOM(html).window.document.documentElement.innerHTML;
  charts.length = 0;
}

/** Samme rekkefølge som app.js. */
function renderAll(dashboard, history) {
  reset();
  const { countries, market } = dashboard;
  overview.renderHero(countries, market, dashboard.updated);
  overview.renderRates(countries);
  chartsMod.setupPathChart(countries);
  overview.renderKrone(countries, market);
  overview.renderIdeas(countries, market);
  cards.renderCards(countries, market);
  cards.setupCardMode();
  overview.renderSources(dashboard.sources, dashboard.updated);
  cards.fillSparklines(countries, history);
  chartsMod.drawComparison(countries, history);
  chartsMod.drawPathChart(countries);
  pairs.renderPairs(dashboard, history);
  return document.body;
}

const clone = (o) => JSON.parse(JSON.stringify(o));
const base = fixture("dashboard.json");
const history = fixture("history.json");

/** Fixtures: normal dag, vedtaksdag, land uten kurve, syntetisk anker (JPY/CHF finnes i normal dag). */
const variants = {
  normal: () => clone(base),
  vedtaksdag: () => {
    const d = clone(base);
    const no = d.countries.find((c) => c.id === "no");
    // Mest negativ kursreaksjon av alle, så det er dette vedtaket idéen plukker
    no.policy_change = { date: TODAY, from: 4.25, to: 4.5, fx_since: -2.5, path12_change_bp: -12, tone: "duete", measured: ["2026-09-24", TODAY] };
    no.rates.policy_unconfirmed = TODAY;
    no.next_meeting = { date: TODAY, bp: 25, move: "heving", source: "test" };
    return d;
  },
  "uten-kurve": () => {
    const d = clone(base);
    for (const id of ["nz", "ch"]) {
      const c = d.countries.find((x) => x.id === id);
      c.curve = null; c.next_meeting = { date: "2026-10-28" }; c.fwd_fx_1y = null;
    }
    return d;
  },
  "syntetisk-anker": () => {
    const d = clone(base);
    const jp = d.countries.find((c) => c.id === "jp");
    assert.equal(jp.curve.synthetic_anchor, true, "fixture: JPY skal ha syntetisk anker");
    d.countries.forEach((c) => { if (c.curve) { c.curve.repricing = {}; c.curve.repricing_detail = {}; c.curve.path_w1 = null; } });
    return d;
  },
};

const FORBIDDEN = /\b(NaN|undefined|null|\[object Object\])\b/;

for (const [name, make] of Object.entries(variants)) {
  test(`render ${name}: ingen tomme verdier, riktig antall idéer, hero og signaler`, () => {
    const dashboard = make();
    const body = renderAll(dashboard, history);
    const text = body.textContent;
    const bad = text.match(FORBIDDEN);
    assert.equal(bad, null, `fant «${bad?.[0]}» i DOM: …${text.slice(Math.max(0, (bad?.index ?? 0) - 80), (bad?.index ?? 0) + 40)}…`);
    assert.doesNotMatch(body.innerHTML, /undefined|NaN/, "attributter uten tomme verdier");

    // Hero: fire bokser
    assert.equal(body.querySelectorAll("#heroStats .stat").length, 4, "fire hero-stats");
    assert.notEqual(document.getElementById("headline").textContent, "Laster dagens bilde …");

    // Tre ting: overskriften teller det som vises
    const ideas = body.querySelectorAll("#ideas .idea");
    const words = ["Ingenting", "Én ting", "To ting", "Tre ting", "Fire ting"];
    assert.equal(document.getElementById("ideasHeading").textContent, `${words[ideas.length]} å legge merke til`);
    assert.ok(ideas.length >= 1 && ideas.length <= 4);

    // Kort: ett per land, signal på hvert
    const cardEls = body.querySelectorAll("#grid .card");
    assert.equal(cardEls.length, dashboard.countries.length);
    for (const el of cardEls) assert.ok(el.querySelector(".signal .pill")?.textContent.trim(), `signal på ${el.id}`);

    // Renter: land uten kurve nevnes, land med kurve står i lista
    const withCurve = dashboard.countries.filter((c) => c.curve);
    assert.equal(body.querySelectorAll("#rates ul.plain li").length, withCurve.length);
    for (const c of dashboard.countries.filter((x) => !x.curve)) assert.ok(text.includes(c.currency), `${c.currency} uten kurve nevnes`);

    // Kilder og grafer: automatiske kilder pluss egen gruppe for manuelt vedlikeholdte filer
    assert.ok(body.querySelectorAll("#sources li").length > 20);
    assert.match(document.getElementById("sources").textContent, /Manuelt vedlikeholdt/);
    assert.equal(body.querySelectorAll("#sources ul.sources")[1].querySelectorAll("li").length, 4);
    assert.match(document.getElementById("sources").textContent, /gyldig til 25\. nov/);
    assert.equal(charts.length, 2, "sammenligningsgraf og rentebane tegnet");
    assert.ok(body.querySelector("#pairResult .pair-card"), "motpost-modulen gir minst ett forslag");
  });

  test(`idéer ${name}: tekst-snapshot`, () => {
    renderAll(make(), history);
    const got = [...document.querySelectorAll("#ideas .idea")].map((el) =>
      `${el.querySelector(".tag").textContent}\n${el.querySelector("p").textContent.replace(/\s+/g, " ").trim()}`).join("\n\n") + "\n";
    const file = join(here, "fixtures", `ideas-${name}.txt`);
    if (process.env.UPDATE_SNAPSHOTS || !existsSync(file)) writeFileSync(file, got);
    assert.equal(got, readFileSync(file, "utf8"), `idé-teksten for «${name}» har endret seg (UPDATE_SNAPSHOTS=1 for å godta)`);
  });
}

test("vedtaksdag: kalendervakt og vedtakstone vises", () => {
  const body = renderAll(variants.vedtaksdag(), history);
  assert.match(body.textContent, /ubekreftet etter møtet/);
  assert.match(document.getElementById("ideas").textContent, /Duete heving|duete/);
});

test("kortmodus: knappen bytter mellom kompakt og detaljert", () => {
  renderAll(variants.normal(), history);
  const grid = document.getElementById("grid"), btn = document.getElementById("cardMode");
  assert.ok(grid.classList.contains("compact"));
  btn.click();
  assert.ok(!grid.classList.contains("compact"));
  assert.equal(btn.textContent, "Vis mindre");
});

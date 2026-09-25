import { test } from "node:test";
import assert from "node:assert/strict";
import { correlation, realizedVol, rate1y, directionSignal, pairCandidates, dailyReturns, totalReturn } from "../js/calc.js";

const series = (vals) => Object.fromEntries(vals.map((v, i) => [`2026-01-${String(i + 1).padStart(2, "0")}`, v]));

test("dailyReturns gir logavkastning", () => {
  const r = dailyReturns(series([100, 110]));
  assert.ok(Math.abs(r["2026-01-02"] - Math.log(1.1)) < 1e-12);
});

test("correlation er 1 for identiske serier og −1 for motsatte", () => {
  const a = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`d${i}`, Math.sin(i)]));
  const b = Object.fromEntries(Object.entries(a).map(([d, v]) => [d, -v]));
  assert.ok(Math.abs(correlation(a, a) - 1) < 1e-12);
  assert.ok(Math.abs(correlation(a, b) + 1) < 1e-12);
  assert.equal(correlation({ d1: 1 }, { d1: 1 }), null, "for få observasjoner");
});

test("realizedVol er null for konstant serie og positiv for svingende", () => {
  assert.equal(realizedVol(series(Array(20).fill(5))), 0);
  assert.ok(realizedVol(series(Array.from({ length: 20 }, (_, i) => 100 + (i % 2)))) > 0);
  assert.equal(realizedVol(series([1, 2, 3])), null);
});

test("rate1y interpolerer kurven og faller tilbake på 3 mnd", () => {
  assert.equal(rate1y({ curve: { points: { "0.5": 2, "2": 4 } } }), 2 + (4 - 2) * (0.5 / 1.5));
  assert.equal(rate1y({ curve: { points: { "1": 3.3 } } }), 3.3);
  assert.equal(rate1y({ rates: { m3: 4.1 } }), 4.1);
  assert.equal(rate1y({}), null);
});

test("directionSignal teller drivere: minst to må peke samme vei", () => {
  const up = directionSignal({ curve: { implied: { "6m": 60 } }, fx: { changes: { m3: 3 } }, rates: { policy: 4 }, cpi: { value: 2 } });
  assert.equal(up.dir, "up");
  assert.equal(up.word, "3 av 3 drivere styrker");
  assert.deepEqual(up.drivers.map((d) => d.dir), ["up", "up", "up"]);
  const down = directionSignal({ rates: { policy: 4, m3: 3.2 }, fx: { changes: { m3: -3 } }, cpi: { value: 5 } });
  assert.equal(down.dir, "down");
  assert.equal(down.word, "3 av 3 drivere svekker");
  assert.match(down.text, /rentekutt/);
  // To mot én: retningen følger flertallet, ordlyden sier «2 av 3»
  const two = directionSignal({ curve: { implied: { "6m": 60 } }, fx: { changes: { m3: 3 } }, rates: { policy: 2 }, cpi: { value: 4 } });
  assert.equal(two.dir, "up");
  assert.equal(two.word, "2 av 3 drivere styrker");
  // Én opp, én ned, én flat: delt bilde, ikke en vektet sum som vipper
  const split = directionSignal({ curve: { implied: { "6m": 60 } }, fx: { changes: { m3: -3 } }, rates: { policy: 4 }, cpi: { value: 4 } });
  assert.equal(split.dir, "flat");
  assert.equal(split.word, "Delt bilde");
  // I-44 inverteres: fallende indeks = sterkere krone
  const nok = directionSignal({ fx: { index: true, changes: { m3: -3 } }, curve: { implied: { "6m": 30 } }, rates: { policy: 4.5 }, cpi: { value: 3 } });
  assert.equal(nok.drivers.find((d) => d.key === "momentum").dir, "up");
  assert.equal(directionSignal({}).word, "For lite data");
});

test("pairCandidates rangerer etter treff og setter riktige merkelapper", () => {
  const countries = [
    { id: "us", currency: "USD", flag: "", cot: { pct_oi: 30 } },
    { id: "jp", currency: "JPY", flag: "", cot: { pct_oi: -10 } },
    { id: "no", currency: "NOK", flag: "" },
  ];
  const info = {
    us: { r1y: 4, imp12: 50, m3: 2, riskCorr: 0.1, oilCorr: 0.2 },
    jp: { r1y: 1, imp12: 90, m3: -1, riskCorr: -0.6, oilCorr: 0.1 },
    no: { r1y: 4.5, imp12: 30, m3: 0, riskCorr: 0.2, oilCorr: 0.3 },
  };
  const rows = pairCandidates({ countries, info, chosen: countries[0], isLong: true });
  assert.equal(rows.length, 2);
  const jpy = rows.find((r) => r.S.id === "jp");
  assert.equal(jpy.carry, 3);
  assert.equal(jpy.gap, -40);
  assert.ok(jpy.tags.some(([t]) => t === "carry"));
  assert.ok(jpy.tags.some(([t]) => t === "mot strømmen"));
  assert.ok(!jpy.tags.some(([t]) => t === "risikonøytral"), "ulik risikoprofil");
  const nok = rows.find((r) => r.S.id === "no");
  assert.ok(nok.tags.some(([t]) => t === "risikonøytral"));
  assert.equal(rows[0].S.id, "jp", "flest treff først");
  // short-retning bytter bein
  const short = pairCandidates({ countries, info, chosen: countries[0], isLong: false });
  assert.equal(short[0].S.id, "us");
  assert.ok(short.find((r) => r.L.id === "jp").tags.some(([t]) => t === "kontrær"), "USD er fullt long → kontrær");
});

test("totalReturn: kurs pluss renteforskjell dag for dag, rebasert til 100", () => {
  const fx = { "2026-01-01": 10, "2026-01-31": 10, "2026-03-02": 11 };
  const tr = totalReturn(fx, { "2025-12": 4.0, "2026-02": 5.0 }, { "2025-12": 4.0, "2026-02": 3.0 });
  assert.equal(tr["2026-01-01"], 100);
  assert.equal(tr["2026-01-31"], 100);                       // 30 dager uten renteforskjell, flat kurs
  // 31. jan → 2. mar: 30 dager, renten for januar (ingen februar-verdi ennå på d0) er lik → bare kurs: 110
  assert.equal(tr["2026-03-02"], 110);
  const tr2 = totalReturn({ "2026-02-01": 10, "2026-03-03": 10 }, { "2026-02": 5.0 }, { "2026-02": 3.0 });
  assert.equal(tr2["2026-03-03"], +(100 * (1 + 0.02 / 360 * 30)).toFixed(3)); // 2 pp carry i 30 dager
  assert.equal(totalReturn(fx, null, {}), null);
  assert.equal(totalReturn({ "2026-01-01": 10 }, {}, {}), null);
});

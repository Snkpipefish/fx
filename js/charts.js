/* Grafer: SVG-sparklines for kortene (ingen bibliotek) og Chart.js for oversikten. */
import { nb, nb1, nb2, bp, rate, cssVar, color, name, shortDate, sortedEntries } from "./format.js";

/** Liten SVG-linjegraf med tekstalternativ. `fmt` formaterer verdier til aria-tekst. */
export function sparkline(series, { stepped = false, stroke = "currentColor", label = "", fmt = (v) => nb.format(v), scale = 1 } = {}) {
  const e = sortedEntries(series).map(([d, v]) => [d, v * scale]);
  if (e.length < 2) return "";
  const vals = e.map(([, v]) => v);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const W = 100, H = 30;
  const pts = e.map(([, v], i) => [+(i / (e.length - 1) * W).toFixed(2), +(H - 2 - (v - min) / span * (H - 4)).toFixed(2)]);
  const d = pts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : stepped ? `H${p[0]}V${p[1]}` : `L${p[0]},${p[1]}`)).join("");
  const text = `${label}: fra ${fmt(vals[0])} (${shortDate(e[0][0])}) til ${fmt(vals[vals.length - 1])} (${shortDate(e[e.length - 1][0])}), lavest ${fmt(min)}, høyest ${fmt(max)}`;
  return `
    <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${text}"><title>${text}</title>
      <path class="spark-area" d="${d}L${W},${H}L0,${H}Z"/><path class="spark-line" d="${d}" style="stroke:${stroke}"/></svg>
    <div class="spark-labels"><span>${shortDate(e[0][0])}</span><span>lav ${fmt(min)} · høy ${fmt(max)}</span><span>${shortDate(e[e.length - 1][0])}</span></div>`;
}

/** Tabellcelle med liten søyle bak tallet, skalert mot `maxAbs`. */
export function barCell(v, maxAbs, text, extraCls = "", sub = "") {
  if (v == null) return `<td>–</td>`;
  const w = Math.min(50, Math.abs(v) / (maxAbs || 1) * 50);
  const style = v >= 0 ? `left:50%;width:${w.toFixed(1)}%` : `right:50%;width:${w.toFixed(1)}%`;
  return `<td class="bar-cell ${extraCls}"><i class="bar ${v >= 0 ? "pos" : "neg"}" style="${style}"></i><span>${text}${sub}</span></td>`;
}

function baseLineOptions(tooltipLabel) {
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: tooltipLabel } } },
    scales: {
      x: {
        ticks: { color: cssVar("--muted"), maxTicksLimit: 5, maxRotation: 0,
          callback(value) { return shortDate(this.getLabelForValue(value)); } },
        grid: { display: false },
      },
      y: { ticks: { color: cssVar("--muted"), maxTicksLimit: 4 }, grid: { color: cssVar("--border") } },
    },
  };
}

const legend = () => ({ display: true, position: "bottom", labels: { color: cssVar("--text"), boxWidth: 18, boxHeight: 3 } });

export function drawComparison(countries, history) {
  const datasets = [];
  let labels = null;
  for (const c of countries) {
    if (!c.fx || c.fx.index) continue;
    const series = history.fx?.[c.currency];
    if (!series) continue;
    const entries = sortedEntries(series);
    if (!labels || entries.length > labels.length) labels = entries.map(([d]) => d);
    const base = entries[0][1];
    datasets.push({
      label: name(c), borderColor: color(c), borderWidth: 1.6, pointRadius: 0, tension: 0.2,
      data: Object.fromEntries(entries.map(([d, v]) => [d, +(v / base * 100).toFixed(2)])),
    });
  }
  if (!labels) return;
  const mapped = datasets.map((ds) => ({ ...ds, data: labels.map((d) => ds.data[d] ?? null) }));
  new Chart(document.getElementById("comparisonChart"), {
    type: "line",
    data: { labels, datasets: mapped },
    options: {
      ...baseLineOptions((item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}`),
      plugins: { legend: legend(), tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}` } } },
      spanGaps: true,
    },
  });
}

/** Implisert rentebane 0–24 mnd frem, med valgfritt lag for én uke siden (stiplet). */
/** Tegner rentebanen første gang <details> åpnes (skjult canvas får ellers null størrelse). */
export function setupPathChart(countries) {
  const det = document.getElementById("pathDetails");
  if (!det) return;
  let drawn = false;
  det.addEventListener("toggle", () => { if (det.open && !drawn) { drawn = true; drawPathChart(countries); } });
}

export function drawPathChart(countries) {
  const rows = countries.filter((c) => c.curve?.path);
  if (!rows.length) return;
  const labels = rows[0].curve.path.map((_, m) => m);
  const now = rows.map((c) => ({
    label: name(c), data: c.curve.path, borderColor: color(c),
    borderWidth: c.id === "no" ? 2.6 : 1.6, pointRadius: 0, tension: 0.25, week: false,
  }));
  const week = rows.filter((c) => c.curve.path_w1).map((c) => ({
    label: `${name(c)} for 1 uke siden`, data: c.curve.path_w1, borderColor: color(c),
    borderWidth: 1.2, borderDash: [4, 3], pointRadius: 0, tension: 0.25, hidden: true, week: true,
  }));
  const chart = new Chart(document.getElementById("pathChart"), {
    type: "line",
    data: { labels, datasets: [...now, ...week] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { ...legend(), labels: { ...legend().labels, filter: (item) => !item.text.includes("uke siden") } },
        tooltip: {
          callbacks: {
            title: (items) => (items[0].label === "0" ? "Nå" : `Om ${items[0].label} mnd`),
            label: (item) => `${item.dataset.label}: ${rate(item.parsed.y)} (${bp(Math.round((item.parsed.y - item.dataset.data[0]) * 100))})`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: cssVar("--muted"), maxRotation: 0, autoSkip: false,
            callback(value) { const m = +this.getLabelForValue(value); return m === 0 ? "nå" : m % 6 === 0 ? `${m} mnd` : null; } },
          grid: { display: false },
        },
        y: { ticks: { color: cssVar("--muted"), callback: (v) => `${nb1.format(v)} %` }, grid: { color: cssVar("--border") } },
      },
    },
  });
  const toggle = document.getElementById("pathWeek");
  if (toggle) {
    toggle.disabled = week.length === 0;
    toggle.addEventListener("change", () => {
      chart.data.datasets.forEach((ds, i) => { if (ds.week) chart.setDatasetVisibility(i, toggle.checked); });
      chart.update();
    });
  }
}

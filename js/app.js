/* Inngangspunkt: laster dashboard.json først og rendrer alt som ikke trenger historikk,
 * deretter history.json for sparklines, sammenligningsgraf og motpost-modulen. */
import { renderToday, renderPriced, renderIdeas, renderRisk, renderSources } from "./overview.js";
import { drawComparison, setupPathChart } from "./charts.js";
import { renderCards, fillSparklines, setupCardMode } from "./cards.js";
import { renderPairs } from "./pairs.js";

async function init() {
  const bust = `?v=${Date.now()}`;
  const getJson = (file) => fetch(`data/${file}${bust}`).then((r) => { if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`); return r.json(); });
  const historyPromise = getJson("history.json");
  const dashboard = await getJson("dashboard.json");

  const updated = new Date(dashboard.updated);
  document.getElementById("updated").textContent =
    `Sist oppdatert: ${updated.toLocaleString("nb-NO", { dateStyle: "long", timeStyle: "short" })}`;
  const market = dashboard.market || {};
  const countries = dashboard.countries;

  renderToday(countries, market);
  renderPriced(countries);
  setupPathChart(countries);
  renderIdeas(countries, market);
  renderRisk(market);
  renderCards(countries, market);
  setupCardMode();
  renderSources(dashboard.sources, dashboard.updated);

  const history = await historyPromise;
  fillSparklines(countries, history);
  drawComparison(countries, history);
  renderPairs(dashboard, history);
}

init().catch((err) => {
  document.getElementById("grid").innerHTML = `<p class="loading">Kunne ikke laste data: ${err.message}</p>`;
  console.error(err);
});

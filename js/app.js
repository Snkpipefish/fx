/* Inngangspunkt: dashboard.json først (alt som ikke trenger historikk), deretter history.json. */
import { renderHero, renderRates, renderStrength, renderCross, renderIdeas, renderSources } from "./overview.js";
import { drawComparison, setupPathChart } from "./charts.js";
import { renderCards, fillSparklines, setupCardMode } from "./cards.js";
import { renderPairs } from "./pairs.js";

async function init() {
  const bust = `?v=${Date.now()}`;
  const getJson = (file) => fetch(`data/${file}${bust}`).then((r) => { if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`); return r.json(); });
  const historyPromise = getJson("history.json");
  const dashboard = await getJson("dashboard.json");
  const market = dashboard.market || {}, countries = dashboard.countries;

  document.getElementById("updated").textContent =
    `Oppdatert ${new Date(dashboard.updated).toLocaleString("nb-NO", { dateStyle: "medium", timeStyle: "short" })}`;
  renderHero(countries, market, dashboard.updated);
  renderRates(countries);
  setupPathChart(countries);
  renderStrength(countries, market);
  renderIdeas(countries, market);
  renderCards(countries, market);
  setupCardMode();
  renderSources(dashboard.sources, dashboard.updated);

  const history = await historyPromise;
  fillSparklines(countries, history);
  drawComparison(countries, history);
  renderCross(countries, history);
  renderPairs(dashboard, history);
}

init().catch((err) => {
  document.getElementById("grid").innerHTML = `<p class="note">Kunne ikke laste data: ${err.message}</p>`;
  console.error(err);
});

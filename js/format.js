/* Formatering, farger og små hjelpere som deles av alle modulene. Ingen DOM ved import. */

export const nb = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 4 });
export const nb0 = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });
export const nb1 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const nb2 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Prosent med fortegn; avrundet null vises som «0,0 %», ikke «−0,0 %». */
export const pct = (v) => (v == null ? "–" : Math.abs(v) < 0.005 ? "0,00 %" : `${v > 0 ? "+" : ""}${nb2.format(v)} %`);
export const pct1 = (v) => (v == null ? "–" : Math.abs(v) < 0.05 ? "0,0 %" : `${v > 0 ? "+" : ""}${nb1.format(v)} %`);
export const rate = (v) => (v == null ? "–" : `${nb2.format(v)} %`);
export const signed = (v, fmt = nb1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${fmt.format(v)}`);
export const thousands = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb1.format(v / 1000)}k`);
export const bp = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb0.format(v)} bp`);
/** Korrelasjon som «0,37» / «−0,42» (to desimaler, uten plusstegn). */
export const corr = (v) => (v == null ? "–" : nb2.format(v));
/** CSS-klasse for fortegn, med dødsone rundt null. */
export const cls = (v, dead = 0) => (v == null ? "" : v > dead ? "pos" : v < -dead ? "neg" : "");

export const dateFmt = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "short" });
/** «5. nov» uten avsluttende punktum, så setninger ikke får dobbelt punktum. */
export const shortDate = (iso) => (iso ? dateFmt.format(new Date(iso)).replace(/\.$/, "") : "–");
export const daysUntil = (iso) => Math.round((new Date(iso) - new Date(new Date().toDateString())) / 86400000);

// Fast farge per land, så alle grafer og tabeller bruker samme farger. Ingen valuta er hjemmevaluta.
export const COLORS = {
  us: "#2563eb", ea: "#f59e0b", jp: "#10b981", gb: "#ef4444", ch: "#8b5cf6",
  ca: "#06b6d4", au: "#ec4899", nz: "#84cc16", se: "#f97316", no: "#78716c",
};

let cssCache = null;
export function cssVar(name) {
  if (!cssCache) cssCache = getComputedStyle(document.documentElement);
  return cssCache.getPropertyValue(name).trim();
}
export const color = (c) => COLORS[c.id] ?? cssVar("--text");
export const name = (c) => `${c.flag} ${c.currency}`;
export const sortedEntries = (series) => Object.entries(series || {}).sort(([a], [b]) => a.localeCompare(b));

/** Basispunkter som «≈ 3 hevinger» / «≈ 2 kutt» / «uendret» (25 bp per møte). */
export function moves(v) {
  if (v == null) return "–";
  const n = Math.round(Math.abs(v) / 25);
  if (n === 0) return "uendret";
  return `≈ ${n} ${v < 0 ? "kutt" : n === 1 ? "heving" : "hevinger"}`;
}
/** Basispunkter som prosentpoeng: «+0,75 pp». */
export const pp = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb2.format(v / 100)} pp`);

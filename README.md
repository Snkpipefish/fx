# G10 Valutabrief

Redaksjonell «brief» over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) sett fra et norsk perspektiv, i én kolonne med fem kapitler:

1. **Hva venter markedet av sentralbankene?** Hantelgraf med renten nå og renten markedet priser om 12 måneder (og en markør for 6 måneder), i vanlig norsk («≈ 3 hevinger»). Hele rentebanen 24 måneder frem og metodeforklaring ligger bak «vis»-lenker.
2. **Kronen.** Én setning om kronen, risikoappetitten (VIX, AUD/JPY), oljen og gassen (hvilken av dem som har forklart kronen best siste 90 dager), en søyleliste over hvem som har gått mest mot kronen (uke/måned/3 mnd/år) og en linjegraf over alle valutaene mot kronen siste år, med bryter for totalavkastning (kurs pluss renteforskjellen mot kronen dag for dag).
3. **Tre ting å legge merke til.** Automatisk genererte observasjoner: sprik i renteforventninger, reprising, kutt/hevinger som ikke rimer med inflasjonen, renteforskjell mot kronen, ensidig posisjonering.
4. **Finn motparten til en handel.** Velg valuta (chips) og retning, få tre forslag («Beste match», «Mest betalt for å vente», «Renest rentesyn») med begrunnelse, og hele kandidattabellen bak «Vis alle». Bygger på ideen om at én posisjon alltid er to, og at motparten bør velges bevisst.
5. **Land for land.** Kort per land med kurs, utvikling, sparkline og én setning om hva markedet venter av sentralbanken; «Vis detaljer» åpner renter, inflasjon (samlet og bankens eget kjernemål der det finnes: kjerne-PCE, trimmet gjennomsnitt, CPI-trim/median, KPI-JAE, KPIF), ledighet, kjøpekraft, terminkurs og posisjonering.

Øverst står en overskrift som oppsummerer dagen med fire bokser som måler ulike ting: banken som er nærmest et vedtak, mest priset på 12 måneder (som nivå fra → til, siden antall hevinger belønner lavt utgangspunkt), størst uenighet med bankens eget anslag (det som gir kursutslag), og ukens sterkeste valuta mot kronen. Nederst ligger ordliste, kilder og kildestatus. Designet bruker Fraunces (overskrifter) og Inter (brødtekst), varme nøytrale farger og egne SVG-grafer; Chart.js brukes bare til de to linjegrafene.

## Slik virker det

- Frontenden er delt i ES-moduler under `js/`: `format.js` (formatering/farger), `calc.js` (ren beregningslogikk, testet), `charts.js` (SVG-sparklines og Chart.js-grafer), `overview.js`, `cards.js`, `pairs.js` og `app.js` (inngang). Chart.js ligger lokalt i `js/vendor/`.
- Siden laster `data/dashboard.json` først og rendrer alt som ikke trenger historikk; `data/history.json` hentes parallelt og fyller sparklines, sammenligningsgraf og motpost-modul når den er klar. Kurvehistorikken ligger i `data/curves.json` og brukes bare av hentescriptet.
- Landskortene er kompakte som standard («Vis detaljer» husker valget i nettleseren). Øverst ligger en stripe med dagens bilde: ukens sterkeste/svakeste, største reprising, mest priset innen 12 mnd, høyeste carry, risikoappetitt og neste rentemøte.
- [scripts/fetch_data.py](scripts/fetch_data.py) henter data fra gratis API-er (Frankfurter/ECB, Norges Bank, BIS, OECD, FRED, CFTC (legacy, futures+opsjoner og TFF, så store ukesving kan kontrolleres mot hverandre), World Bank og sentralbankenes kurvedata – ingen nøkler) og skriver `data/dashboard.json` og `data/history.json`. Rentebanen for USD, AUD og CAD leses ut av futures på styringsrenten (fed funds via Yahoo, ASX 30-dagers cash rate, CORRA fra Montréal-børsen), som gir prising per måned og per rentemøte; statskurven brukes for punktene og for banen utover siste kontrakt. NZD bruker ASXs 90-dagers bankvekselfutures per kvartal med OECDs 3-måneders rente som nåpunkt (RBNZ ligger bak Cloudflare, som også blokkerer GitHub-runnere; [scripts/fetch_rbnz.py](scripts/fetch_rbnz.py) henter B2-tabellen med Playwright der det er mulig, og brukes da til punktene). GBP bruker BoE OIS, øvrige statspapirkurver. AUD og CHF har statskurver som publiseres månedlig (RBA F17, SNB `rendeiduebd`) og forskyves daglig med markedsrentene.
- Hver kjøring skriver også et kompakt snapshot til `data/snapshots/ÅÅÅÅ-MM-DD.json` (kurs, styringsrente, bane, priset, posisjonering og marked per land), og fyller ut bakover fra historikken første gang. Snapshotene er grunnlaget for reprisingshistorikk og kalibrering av retningssignalet; `history.json` får serien `path12` per valuta fra dem.
- GitHub Actions ([.github/workflows/update.yml](.github/workflows/update.yml)) kjører skriptet hver ukedag kl. 06:45 UTC, committer nye data og publiserer siden til GitHub Pages. Alt skjer i skyen – ingen lokal maskin trengs.
- Frontenden er statisk HTML/CSS/JS med [Chart.js](https://www.chartjs.org/) fra CDN.

## Tester og kildeovervåking

```bash
python3 -m unittest discover -s tests -v   # terminrenter, markedsanker, futures, kilder, xlsx-leser
npm ci && node --test tests/*.test.mjs     # calc.js (korrelasjon, signal, motpost, totalavkastning) + rendering av alle seksjoner i jsdom
```

Rendering-testene (`tests/render.test.mjs`) bygger hele siden fra `tests/fixtures/` i fire varianter (normal dag, vedtaksdag, land uten kurve, syntetisk anker) og sjekker at ingen tomme verdier havner i DOM, at overskriften «N ting å legge merke til» stemmer med antall idéer, og at idé-tekstene er uendret mot snapshots (`UPDATE_SNAPSHOTS=1 node --test tests/render.test.mjs` godtar nye tekster).

Testene kjøres i GitHub Actions før innhentingen. Alle kilder hentes parallelt med korte timeouts, og `dashboard.json` inneholder `sources` med status og nyeste dato per kilde (vises under «Kildestatus» i bunnteksten). Etter publisering kjører [scripts/check_sources.py](scripts/check_sources.py), som gir rød kjøring hvis en kilde er mer enn 10 dager gammel (14 for COT, 75 for månedlige serier) – et varsel som ikke stopper oppdateringen.

## Manuelt vedlikehold

Tre små JSON-filer i `data/` holdes ved like for hånd:

- `meetings.json` – neste rentemøter per sentralbank.
- `policy_overrides.json` – rentevedtak seriene ennå ikke har fanget opp. Styringsrentene hentes nå direkte fra Norges Bank, Riksbanken, Bank of Canada, ECB, FRED (Fed), Bank of England, RBA og SNB, med BIS som historikk; bare Bank of Japan og RBNZ er avhengige av fila. Posten (annonseringsdato) brukes til serien viser samme rente, med fem dagers slingringsmonn for virkningsdato; avviker serien lenger enn det, vinner serien og innhentingen varsler. Kalendervakt: er et møte passert uten at serien dekker det, merkes renten «ubekreftet etter møtet» på kortet og i kildestatus.
- `meeting_odds.json` – hva markedet priser for neste rentemøte, som reserve for banker uten futures. For USD, AUD og CAD regnes møteprisingen automatisk fra futures på styringsrenten, for GBP fra 1- og 3-måneders OIS; ellers brukes denne filen, og til sist kurvens 3-måneders prising som indikasjon (statsveksler har knapphetspremie som ikke lar seg skille fra priset bevegelse).
- `cb_paths.json` – sentralbankenes egne renteanslag (dot plot, rentebane), som vises som en rombe i hantelgrafen og gir setningen «markedet ligger lengst fra bankens eget anslag for …». Fed (SEP), Norges Bank (PPR-tallsett) og Riksbanken (utfall och prognoser) hentes automatisk og sammenlignes ved 12 måneders horisont; fila er reserve for dem og eneste kilde for RBNZ. Hver post har `as_of` og `valid_until` (neste rapportdato), og anslaget merkes «utdatert» etter den.


Rentemøtedatoene i [data/meetings.json](data/meetings.json) må oppdateres når sentralbankene publiserer neste års kalender (typisk én gang i året). Datoer i fortiden ignoreres automatisk. Alle fire filene har `as_of` og vises som egen gruppe «Manuelt vedlikeholdt» i kildestatus: kalenderen varsler 45 dager før en bank går tom for oppførte møter (og gir rød kjøring når den er tom), registrerte vedtak merkes «kan fjernes» når serien har bekreftet dem, utgåtte møteodds og utløpte bankbaner merkes.

## Videre arbeid

Kjente svakheter og avtalt løsning per punkt ligger i [docs/PLAN.md](docs/PLAN.md).

## Kjør lokalt

```bash
python3 scripts/fetch_data.py   # hent ferske data
python3 -m http.server 8000     # åpne http://localhost:8000
```

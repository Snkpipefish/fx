# G10 Valutabrief – uten hjemmevaluta

Redaksjonell «brief» over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) i én kolonne med fem kapitler. Siden er en nøytral variant av [valuta](https://github.com/Snkpipefish/valuta): **ingen valuta er hjemmevaluta**. Der originalen måler alt mot kronen og I-44, måles hver valuta her mot **G10-kurven** – et likevektet geometrisk snitt av de ni andre – og kryssene vises slik markedet noterer dem (EUR/USD, USD/JPY, USD/NOK …).

1. **Hva venter markedet av sentralbankene?** Hantelgraf med renten nå og renten markedet priser om 12 måneder (og en markør for 6 måneder), i vanlig norsk («≈ 3 hevinger»). Hele rentebanen 24 måneder frem og metodeforklaring ligger bak «vis»-lenker.
2. **Sterkt og svakt.** Risikoappetitten (VIX, AUD/JPY) og hvilke valutaer som har fulgt den tettest siste 90 dager, oljen og gassen og hvilke valutaer som har fulgt dem, en søyleliste over hvem som har gått mest mot G10-kurven (uke/måned/3 mnd/år), en krysstabell med alle 90 parene for samme horisont, og en linjegraf over alle ti valutaene mot kurven siste år, med bryter for totalavkastning (kurs pluss renteforskjellen mot kurven dag for dag).
3. **Tre ting å legge merke til.** Automatisk genererte observasjoner: sprik i renteforventninger, reprising, kutt/hevinger som ikke rimer med inflasjonen, heving levert uten at kursen fulgte (målt mot kurven), største renteforskjell på tvers av G10, ensidig posisjonering.
4. **Finn motparten til en handel.** Velg valuta (chips) og retning, få tre forslag («Beste match», «Mest betalt for å vente», «Renest rentesyn») med begrunnelse, og hele kandidattabellen bak «Vis alle». Korrelasjonene mot risikoappetitt, olje og gass måles for hver valuta mot kurven, så ingen enkeltvalutas støy farger dem.
5. **Land for land.** Kort per land med konvensjonelt kryss mot USD, utvikling mot kurven, sparkline av kurvindeksen, én setning om hva markedet venter av sentralbanken og et retningssignal som teller tre drivere (rente, momentum mot kurven, realrente); «Vis detaljer» åpner renter, inflasjon (samlet og bankens eget kjernemål der det finnes), ledighet, kjøpekraft, terminkurs for krysset, renteforskjell mot kurven og mot USD, posisjonering og korrelasjoner mot olje, gass og risikoappetitt.

Øverst står en overskrift som oppsummerer dagen med fire bokser: banken som er nærmest et vedtak, mest priset på 12 måneder, størst uenighet med bankens eget anslag, og ukens sterkeste og svakeste valuta mot kurven. Nederst ligger ordliste, kilder og kildestatus. Designet bruker Fraunces (overskrifter) og Inter (brødtekst), begge selvhostet som variable woff2 under `css/fonts/` (OFL), varme nøytrale farger og egne SVG-grafer; Chart.js brukes bare til de to linjegrafene. Siden laster ingenting fra tredjepart.

## G10-kurven

Kursene hentes som ECB-referansekurser med USD som base og lagres som verdien av 1 enhet av hver valuta i USD (USD selv = 1). Kurvindeksen for valuta X er

    log I_X(t) = log(X/USD)(t) − (1/9) · Σ_{Y≠X} log(Y/USD)(t)

rebasert til 100 på første dag i vinduet. Numerairen faller bort (samme kurv om alt måles i EUR), summen av logendringene over de ti er null, og et kryss X/Y er alltid `fx[X] ÷ fx[Y]`. Alt som før var «mot kronen» eller «I-44-justert» – kursendringer, momentum i retningssignalet, kursreaksjon etter vedtak, volatilitet, totalavkastning og korrelasjoner – er nå mot kurven. Renteforskjellen 1 år vises både mot kurven (snittet av de andres 1-årsrenter) og mot USD; terminkursen regnes for det konvensjonelle krysset med dekket renteparitet.

## Slik virker det

- Frontenden er delt i ES-moduler under `js/`: `format.js` (formatering/farger), `calc.js` (ren beregningslogikk, testet: korrelasjon, signal, motpost, totalavkastning, kurvrenter, krysstabell), `charts.js` (SVG-sparklines og Chart.js-grafer), `overview.js`, `cards.js`, `pairs.js` og `app.js` (inngang). Chart.js ligger lokalt i `js/vendor/`.
- Siden laster `data/dashboard.json` først og rendrer alt som ikke trenger historikk; `data/history.json` hentes parallelt og fyller sparklines, sammenligningsgraf, krysstabell og motpost-modul når den er klar. `history.json` har `fx` (USD-termer), `basket` (kurvindeks per valuta), styringsrenter, COT, marked, `path12` og 3-mnd-renter. Kurvehistorikken ligger i `data/curves.json` og brukes bare av hentescriptet.
- Landskortene er kompakte som standard («Vis detaljer» husker valget i nettleseren).
- [scripts/fetch_data.py](scripts/fetch_data.py) henter data fra gratis API-er (Frankfurter/ECB, BIS, OECD, FRED, CFTC (legacy, futures+opsjoner og TFF), World Bank, sentralbankenes styringsrenter og kurvedata – ingen nøkler) og skriver `data/dashboard.json` og `data/history.json`. Rentebanen for USD, AUD og CAD leses ut av futures på styringsrenten (fed funds via Yahoo, ASX 30-dagers cash rate, CORRA fra Montréal-børsen); NZD bruker ASXs 90-dagers bankvekselfutures med OECDs 3-måneders rente som nåpunkt ([scripts/fetch_rbnz.py](scripts/fetch_rbnz.py) henter RBNZs B2-tabell med Playwright der det er mulig). GBP bruker BoE OIS, øvrige statspapirkurver (AUD og CHF månedlige kurver forskjøvet daglig med markedsrentene, JPY med JSDAs statsveksler). Hver kurve har en sikkerhet (`confidence`); kurver med lav sikkerhet holdes ute av hero-tallene og «størst sprik». Banen ankres på markedets 3-måneders rente minus en basis målt mot styringsrenten slik den faktisk ble, og interpoleres monotont kubisk (PCHIP).
- Hver kjøring skriver også et kompakt snapshot til `data/snapshots/ÅÅÅÅ-MM-DD.json` (kurs i USD, kurs mot kurven, styringsrente, bane, priset, posisjonering og marked per land), og fyller ut bakover fra historikken første gang. Snapshotene er grunnlaget for reprisingshistorikk og kalibrering av retningssignalet (`scripts/backtest_signal.py` regresserer 4-ukers avkastning mot kurven på de tre faktorene).
- GitHub Actions ([.github/workflows/update.yml](.github/workflows/update.yml)) kjører skriptet hver ukedag kl. 06:45 UTC, committer nye data og publiserer siden til GitHub Pages. Alt skjer i skyen – ingen lokal maskin trengs.

## Tester og kildeovervåking

```bash
python3 -m unittest discover -s tests -v   # terminrenter, markedsanker, futures, kilder, kurv, kryss, terminkurs
npm ci && node --test tests/*.test.mjs     # calc.js + rendering av alle seksjoner i jsdom (ingen krone-formuleringer, krysstabell 10×10)
```

Skjermbilder: `npx playwright test` fotograferer hver seksjon i tre bredder (390/768/1280) fra fixtures med frosset klokke og sammenligner mot baselines i `tests/screenshots/` (`npx playwright test -u` godtar nye). Kjører i en egen workflow ([.github/workflows/screenshots.yml](.github/workflows/screenshots.yml)) ved endringer i frontenden.

Rendering-testene (`tests/render.test.mjs`) bygger hele siden fra `tests/fixtures/` i fire varianter (normal dag, vedtaksdag, land uten kurve, syntetisk anker) og sjekker at ingen tomme verdier havner i DOM, at overskriften «N ting å legge merke til» stemmer med antall idéer, og at idé-tekstene er uendret mot snapshots (`UPDATE_SNAPSHOTS=1 node --test tests/render.test.mjs` godtar nye tekster).

Alle kilder hentes parallelt med korte timeouts, og `dashboard.json` inneholder `sources` med status og nyeste dato per kilde (vises under «Kildestatus» i bunnteksten). Etter publisering kjører [scripts/check_sources.py](scripts/check_sources.py), som gir rød kjøring hvis en kilde er for gammel – et varsel som ikke stopper oppdateringen.

## Manuelt vedlikehold

Fire små JSON-filer i `data/` holdes ved like for hånd, som i originalen: `meetings.json` (neste rentemøter), `policy_overrides.json` (vedtak seriene ennå ikke har fanget opp – bare Bank of Japan og RBNZ er avhengige av fila), `meeting_odds.json` (møteprising som reserve for banker uten futures) og `cb_paths.json` (sentralbankenes egne renteanslag som reserve; Fed, Norges Bank og Riksbanken hentes automatisk). Alle har `as_of` og vises som egen gruppe «Manuelt vedlikeholdt» i kildestatus.

## Videre arbeid

Kjente svakheter og avtalt løsning per punkt ligger i [docs/PLAN.md](docs/PLAN.md).

## Kjør lokalt

```bash
python3 scripts/fetch_data.py   # hent ferske data
python3 -m http.server 8000     # åpne http://localhost:8000
```

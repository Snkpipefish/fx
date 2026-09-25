# G10 Valutabrief

Redaksjonell «brief» over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) sett fra et norsk perspektiv, i én kolonne med fem kapitler:

1. **Hva venter markedet av sentralbankene?** Hantelgraf med renten nå og renten markedet priser om 12 måneder (og en markør for 6 måneder), i vanlig norsk («≈ 3 hevinger»). Hele rentebanen 24 måneder frem og metodeforklaring ligger bak «vis»-lenker.
2. **Kronen.** Én setning om kronen, risikoappetitten (VIX, AUD/JPY) og oljen, en søyleliste over hvem som har gått mest mot kronen (uke/måned/3 mnd/år) og en linjegraf over alle valutaene mot kronen siste år.
3. **Tre ting å legge merke til.** Automatisk genererte observasjoner: sprik i renteforventninger, reprising, kutt/hevinger som ikke rimer med inflasjonen, renteforskjell mot kronen, ensidig posisjonering.
4. **Finn motparten til en handel.** Velg valuta (chips) og retning, få tre forslag («Beste match», «Mest betalt for å vente», «Renest rentesyn») med begrunnelse, og hele kandidattabellen bak «Vis alle». Bygger på ideen om at én posisjon alltid er to, og at motparten bør velges bevisst.
5. **Land for land.** Kort per land med kurs, utvikling, sparkline og én setning om hva markedet venter av sentralbanken; «Vis detaljer» åpner renter, inflasjon, ledighet, kjøpekraft, terminkurs og posisjonering.

Øverst står en overskrift som oppsummerer dagen med fire bokser som måler ulike ting: banken som er nærmest et vedtak, mest priset på 12 måneder (som nivå fra → til, siden antall hevinger belønner lavt utgangspunkt), størst uenighet med bankens eget anslag (det som gir kursutslag), og ukens sterkeste valuta mot kronen. Nederst ligger ordliste, kilder og kildestatus. Designet bruker Fraunces (overskrifter) og Inter (brødtekst), varme nøytrale farger og egne SVG-grafer; Chart.js brukes bare til de to linjegrafene.

## Slik virker det

- Frontenden er delt i ES-moduler under `js/`: `format.js` (formatering/farger), `calc.js` (ren beregningslogikk, testet), `charts.js` (SVG-sparklines og Chart.js-grafer), `overview.js`, `cards.js`, `pairs.js` og `app.js` (inngang). Chart.js ligger lokalt i `js/vendor/`.
- Siden laster `data/dashboard.json` først og rendrer alt som ikke trenger historikk; `data/history.json` hentes parallelt og fyller sparklines, sammenligningsgraf og motpost-modul når den er klar. Kurvehistorikken ligger i `data/curves.json` og brukes bare av hentescriptet.
- Landskortene er kompakte som standard («Vis detaljer» husker valget i nettleseren). Øverst ligger en stripe med dagens bilde: ukens sterkeste/svakeste, største reprising, mest priset innen 12 mnd, høyeste carry, risikoappetitt og neste rentemøte.
- [scripts/fetch_data.py](scripts/fetch_data.py) henter data fra gratis API-er (Frankfurter/ECB, Norges Bank, BIS, OECD, FRED, CFTC, World Bank og sentralbankenes kurvedata – ingen nøkler) og skriver `data/dashboard.json` og `data/history.json`.
- GitHub Actions ([.github/workflows/update.yml](.github/workflows/update.yml)) kjører skriptet hver ukedag kl. 06:45 UTC, committer nye data og publiserer siden til GitHub Pages. Alt skjer i skyen – ingen lokal maskin trengs.
- Frontenden er statisk HTML/CSS/JS med [Chart.js](https://www.chartjs.org/) fra CDN.

## Tester og kildeovervåking

```bash
python3 -m unittest discover -s tests -v   # terminrenter, interpolasjon, xlsx-leser
node --test tests/*.test.mjs               # korrelasjon, volatilitet, signal, motpost-rangering
```

Testene kjøres i GitHub Actions før innhentingen. Alle kilder hentes parallelt med korte timeouts, og `dashboard.json` inneholder `sources` med status og nyeste dato per kilde (vises under «Kildestatus» i bunnteksten). Etter publisering kjører [scripts/check_sources.py](scripts/check_sources.py), som gir rød kjøring hvis en kilde er mer enn 10 dager gammel (14 for COT, 75 for månedlige serier) – et varsel som ikke stopper oppdateringen.

## Manuelt vedlikehold

Tre små JSON-filer i `data/` holdes ved like for hånd:

- `meetings.json` – neste rentemøter per sentralbank.
- `policy_overrides.json` – rentevedtak BIS-serien ennå ikke har fanget opp (BIS henger typisk noen dager etter). Posten brukes fra vedtaksdatoen og kan fjernes når BIS er à jour.
- `meeting_odds.json` – hva markedet priser for neste rentemøte der det finnes kilder med møtedato-oppløsning (ASX RBA Rate Tracker, CORRA-/SOFR-futures). Brukes i «nærmest et vedtak»-boksen og i «Størst sprik»; ellers brukes kurvens 3-måneders prising som indikasjon.
- `cb_paths.json` – sentralbankenes egne renteanslag (dot plot, rentebane), som vises som en rombe i hantelgrafen og gir setningen «markedet ligger lengst fra bankens eget anslag for …».


Rentemøtedatoene i [data/meetings.json](data/meetings.json) må oppdateres når sentralbankene publiserer neste års kalender (typisk én gang i året). Datoer i fortiden ignoreres automatisk.

## Kjør lokalt

```bash
python3 scripts/fetch_data.py   # hent ferske data
python3 -m http.server 8000     # åpne http://localhost:8000
```

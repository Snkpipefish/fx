# G10 Valutadashboard

Dashboard over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) sett fra et norsk perspektiv. Per land vises:

- **Valutakurs mot NOK** med endring siste dag/uke/måned/3 mnd/år, realisert volatilitet og 1 års kursgraf (Norge vises som Norges Banks importveide kroneindeks I-44)
- **Renter**: styringsrente (BIS) med 2 års historikk-graf, 3-mnd pengemarkedsrente, 10-års statsrente og rentekurve-helning (OECD)
- **Inflasjon og arbeidsledighet**: siste KPI å/å og ledighetsrate (OECD)
- **PPP-verdivurdering**: over-/undervurdering mot USD basert på kjøpekraftsparitet (World Bank; Tyskland som proxy for eurosonen)
- **Spekulativ posisjonering (COT)**: netto non-commercial posisjon fra CFTC per valuta-future (ukentlig; finnes ikke for NOK/SEK)
- **Neste rentemøte** per sentralbank (fra [data/meetings.json](data/meetings.json))
- **Priset inn**: hva rentekurven priser av endringer i den korte renten om 6/12/24 mnd, ytterpunktet i banen («bunn 3,10 % om 14 mnd») og 1-års terminkurs mot NOK (breakeven for carry)
- **Retningssignal**: en enkel heuristikk basert på rentedifferanse (3 mnd minus styringsrente), kursmomentum og realrente – *ikke* en prognose eller investeringsråd

Øverst på siden ligger en oversiktsseksjon med:

- **Toppmovers**: sterkeste og svakeste valuta mot NOK siste uke
- **Hva er priset inn?**: tabell per sentralbank med priset endring i den korte renten ved 3/6/12/24 mnd (i basispunkter og «≈ antall kutt/hevinger»), ytterpunktet i banen og reprising siste uke – sortert fra mest kutt til mest heving
- **Implisert rentebane**: graf over styringsrenten markedet priser 0–24 måneder frem, per land
- **Motposten – ingen posisjon står alene**: velg en valuta du vil være long eller short i, og siden viser hva du egentlig eier (priset rentebane, 1-års rente, risiko- og oljekorrelasjon, momentum, posisjonering, PPP) og rangerer kandidater til den andre siden av paret etter carry, priset rentegap, momentum, om paret nøytraliserer risikoappetitt/olje, volatilitet og posisjonering. Bygger på ideen om at én posisjon alltid er to (posisjonen + cash) og at long i én ting er implisitt short i alt du ikke kjøpte, så motposten bør velges bevisst som en pakke
- **Idéer fra dataene**: automatisk genererte observasjoner (sprik i renteforventninger, reprising, kutt tross høy inflasjon, carry mot NOK, ensidig posisjonering) – inspirasjon til videre graving, ikke anbefalinger
- **Sammenligningsgraf**: alle valutaene mot NOK, rebasert til 100 for ett år siden
- **Risikobarometer**: AUD/JPY, VIX og Brent-olje (med 90-dagers korrelasjon olje↔krone)
- **Rentedifferanse-tabell**: hvert lands renter minus de norske, pluss 1-års terminkurs relativt til spot

## Slik regnes «priset inn»

Per land hentes en daglig rentekurve med løpetider fra 1 mnd til 10 år:

| Land | Kilde | Type |
|---|---|---|
| USA | FRED (DGS-seriene) | statspapirer |
| Eurosonen | ECB, AAA-statskurve (Svensson) | statspapirer |
| Japan | Finansdepartementet (MoF) | statsobligasjoner, 1 år og lenger |
| Storbritannia | Bank of England | **OIS-kurve** (1–60 mnd + 10 år) |
| Canada | Bank of Canada (Valet) | statskasseveksler + referanseobligasjoner |
| Australia | RBA-tabellene F1/F2 | OIS/statspapirer (RBA blokkerer en del automatiske kall; faller bort hvis kilden feiler) |
| Sverige | Riksbanken | statsskuldväxlar + statsobligasjoner |
| Norge | Norges Bank | nullkupong statskurve + 3-mnd statskasseveksel |

Sveits og New Zealand mangler daglig kurve (SNBs API er ikke oppdatert siden 2025, RBNZ blokkerer automatiske kall) og får derfor ikke «priset inn»-tall.

Fra spotkurven regnes 3-måneders terminrenter: `f(h) = (r(h+¼)·(h+¼) − r(h)·h) / ¼`. Priset endring ved horisont *h* er `f(h) − r(¼)`, og nivået i rentebanen er styringsrenten pluss denne endringen. Dermed faller et konstant basis-avvik mellom statspapirer og styringsrente bort. Terminrenter inneholder likevel terminpremie, så tallene skal leses som retning og størrelse på det som er priset, ikke som sannsynligheter. For kurver uten punkter under 6 mnd (Japan) settes 3-mnd-renten lik styringsrenten (merket med `*`).

Kurvehistorikken lagres i `data/curves.json` og bygges opp over tid. BoE og MoF publiserer bare inneværende måned per fil, så første kjøring backfyller fra arkivfiler.

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
node --test tests/                         # korrelasjon, volatilitet, signal, motpost-rangering
```

Testene kjøres i GitHub Actions før innhentingen. Alle kilder hentes parallelt med korte timeouts, og `dashboard.json` inneholder `sources` med status og nyeste dato per kilde (vises under «Kildestatus» i bunnteksten). Etter publisering kjører [scripts/check_sources.py](scripts/check_sources.py), som gir rød kjøring hvis en kilde er mer enn 10 dager gammel (14 for COT, 75 for månedlige serier) – et varsel som ikke stopper oppdateringen.

## Manuelt vedlikehold

Rentemøtedatoene i [data/meetings.json](data/meetings.json) må oppdateres når sentralbankene publiserer neste års kalender (typisk én gang i året). Datoer i fortiden ignoreres automatisk.

## Kjør lokalt

```bash
python3 scripts/fetch_data.py   # hent ferske data
python3 -m http.server 8000     # åpne http://localhost:8000
```

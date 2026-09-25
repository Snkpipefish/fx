# Plan: det som står igjen

Status per 25. september 2026. Hvert punkt har **problemet** (fra gjennomgangen samme dag) og **løsningen** vi har blitt enige om. Arbeidsform: én PR per punkt, med fixture-test i `tests/` før frontend-endring. Punktene er sortert etter hvor mye de påvirker tallene.

Kryss av (`[x]`) når en PR er slått sammen, og skriv PR-nummer bak.

## Datakvalitet

- [ ] **Ulike instrumenter / terminpremie.**
  *Problem:* OIS for GBP, statspapirer for USD/EUR/CAD/SEK/JPY, nullkupong for NOK, 1-mnd veksel + obligasjoner for AUD. «Priset inn» og carry er ikke sammenlignbare på tvers, og statskurvene inneholder terminpremie. For banker med syntetisk anker (JPY, AUD) følger `path[0]` styringsrenten, så reprising skiller ikke «vedtak levert» fra «forventninger flyttet».
  *Løsning:*
  1. ✅ *(PR «markedsanker», 25. sep 2026)* Anker banen på markedets frontrente, ikke styringsrenten: `path[0] = r_3m − s`, der `s` er rullerende 250-dagers median av `r_3m − styringsrente`. Nivået flytter seg bare når markedet flytter seg, og «vedtak levert»-hoppet forsvinner (løser også reprisingspunktet under). Implementert i `curve_basis`/`curve_metrics`; `implied` er nå bane minus styringsrente, så et møte innenfor 3-mnd-vinduet telles med. Kjent egenskap: i en lang hevingssyklus inneholder medianen også det markedet typisk har priset innenfor 3 mnd, så banen ligger noen bp lavt (NOK: 3 mnd-anker 11 bp under styringsrenten rett etter septemberhevingen).
  2. ✅ *(PR «futures», 25. sep 2026)* Bytt til møtebaserte instrumenter der de finnes gratis: USD = fed funds-futures per måned via Yahoo (`ZQ{mnd}{åå}.CBT`, ett års historikk per kontrakt), AUD = ASX 30-dagers cash rate-futures (Markit-JSON bak RBA Rate Tracker, kun dagens snapshot – historikk bygges opp i `curves.json`), CAD = TMX CORRA-futures COA 1 mnd + CRA 3 mnd (data-row-JSON i HTML, snapshot), GBP = BoE OIS (har vi). EUR/SEK/NOK/JPY: statspapirer, merket «statskurve» i lista. Kontrakter normaliseres til perioder `[start, slutt, rente]`; `futures_metrics` gir banen (skjøtet på statskurven utover siste kontrakt), `meeting_implied_futures` gir bp per møte og overstyrer `meeting_odds.json`. Basis for futures = median siste 20 dager av (månedskontrakt − månedens gjennomsnittlige styringsrente), som er eksakt også i måneder med vedtak; startpunktet renses tilsvarende. Reprising for AUD/CAD kommer først når snapshot-historikken er bygget opp (uke/måned).

- [ ] **CHF og NZD uten kurve.**
  *Problem:* SNBs API er frosset på juli 2025, RBNZ svarer 403. Begge mangler «priset inn», motpart-tall og rentegap.
  *Løsning:* SNB-kuben vi treffer er «2002-metodikk (til juli 2025)», byttet til ny metodikk. Hent `rendoblid` (daglige spotrenter, Konføderasjonen) fra `data.snb.ch/api/cube/rendoblid/data/csv/en`. RBNZ 403 er Cloudflare: prøv fulle nettleserheadere + HTTP/2 først, ellers last ned B2-tabellen med Playwright i Actions (samme oppsett som skjermbildene). Alternativ uten RBNZ: NZFMA daglige BKBM/swap-fixings.

- [ ] **AUD-kurven er grov.**
  *Problem:* Frontpunkt 1-mnd bankveksel, neste punkt 2 år. Alt mellom er interpolasjon; «toppen om 21 mnd» er regnestykke, ikke marked.
  *Løsning:* RBA tabell F17 gir daglig nullkupongkurve i kvartalssteg fra 0,25 til 10 år (`f17-yields.csv`, serier `FZCY25D` … `FZCY1000D`), sjekk oppdateringslag. F1 har bankveksler 1/3/6 mnd for fronten. Da trengs verken syntetisk anker eller interpolasjon fra 1 mnd til 2 år. Merk: RBA blokkerer curl, men ikke urllib.

- [ ] **Dated Brent-lag.**
  *Problem:* FREDs Dated Brent henger tre dager etter, spotpremien regnes på ulike datoer.
  *Løsning:* `premium = brent_dated[t] − brent_fut[t]` for siste dato der begge finnes, vis «per dd.mm». Legg serien i `history.market` for 90-dagers snitt. Yahoo BZ=F: hent to kontrakter (nov/des) og regn d1/w1 innen samme kontrakt; front til utløp.

- [ ] **Styringsrenter er manuelle til BIS er à jour.**
  *Problem:* Glemmes `policy_overrides.json`, er tallene feil i noen dager etter hvert vedtak.
  *Løsning:* Automatiser der API finnes:
  | Bank | Kilde |
  |---|---|
  | Norges Bank | `data.norges-bank.no/api/data/IR/B.KPRA.SD.?format=csv&lastNObservations=1` |
  | Riksbanken | SWEA `Observations/Latest/SECBREPOEFF` |
  | BoC | Valet `V39079` |
  | ECB | `FM/B.U2.EUR.4F.KR.DFR.LEV` |
  | Fed | FRED `DFEDTARU` / `DFEDTARL` |
  | BoE | IADB `IUDBEDR` |
  | RBA | `f1-data.csv` (`FIRMMCRTD`) |
  | SNB | kube `snbpolizid` (sjekk) |
  BoJ og RBNZ: behold override, men legg til *kalendervakt*: hvis `meetings.json` har et møte ≤ i dag og `policy_date` < møtedato, vis «ubekreftet etter møtet» på kortet og i kildestatus.

- [ ] **Neste-møte-prising er manuell.**
  *Problem:* `meeting_odds.json` finnes bare for RBA og BoC. Andre banker viser kurvens 3-mnd-prising, som ikke skiller møtet fra resten av kvartalet.
  *Løsning:* Generisk `meetingImplied(curve, meetings, policy)` i `calc.js`: med 1 mnd/3 mnd-rente og `n` dager til møtet, `Δ = (r_3m − s − p) · 90 / (90 − n)`; to møter i vinduet gir rest fordelt til møte 2. Test mot RBA/BoC-tallene vi har manuelt. Overstyr med futures der de finnes (USD, AUD, CAD, GBP-OIS).

- [ ] **Sentralbankenes baner oppdateres ikke.**
  *Problem:* `cb_paths.json` finnes bare for Fed, Riksbanken, Norges Bank og RBNZ, og vedlikeholdes for hånd.
  *Løsning:* Halvautomatisk: Fed SEP-tabellen (`fomcprojtabl{yyyymmdd}.htm`, median), Norges Bank PPR-xlsx («tabeller og figurer»), Riksbanken prognosetabell-xlsx, RBNZ MPS-xlsx (via Playwright). Parse-feil gir varsel, ikke krasj. Legg `valid_until` = neste rapportdato i `cb_paths.json`.

- [ ] **COT JPY er ikke verifisert.**
  *Problem:* +212k netto på to uker med +130k i åpen interesse. Kontraktsrullen 16. sep kan blåse opp åpen interesse; ikke sjekket mot kombinert-rapporten.
  *Løsning:* Hent legacy futures-only, futures+options combined og TFF; finnes svinget i alle tre er det reelt. Regel: `|Δnet| > 3σ (52 uker)` eller `ΔOI > 25 %` på én uke gir «ubekreftet». Marker rulleuker (3. onsdag mar/jun/sep/des).

- [ ] **Kjerneinflasjon er ikke bankens målvariabel.**
  *Problem:* USD, GBP, CAD, AUD, CHF, JPY bruker OECDs «uten mat og energi» (Fed: PCE, RBA: trimmet gjennomsnitt).
  *Løsning:* USD: FRED `PCEPILFE` (regn å/å). AUD: ABS Data API, månedlig CPI-indikator, «annual trimmed mean». CAD: Valet CPI-trim/median. SEK: SCB PxWeb KPIF. NOK: SSB API KPI-JAE. JPY: e-Stat ex fersk mat (gratis appId), ellers behold OECD med etikett. GBP/CHF: headline er målet, kjerne kun visning.

## Modell og tekst

- [ ] **Reprising.**
  *Problem:* Skiller ikke «vedtak levert» fra «forventninger flyttet» (se første punkt).
  *Løsning:* Med markedsanker blir `repricing = path[12] − path_w1[12]` rent forventningsskift. Vis dekomponert: «+35 bp, hvorav 25 levert».

- [ ] **«Heving levert, kurs ikke fulgt».**
  *Problem:* Treffer NZD, der årsaken var signal om pause, ikke «selg på nyheten». Regelen kjenner ikke bankens kommunikasjon.
  *Løsning:* Klassifiser vedtaket datadrevet: endring i `path[12]` fra dagen før til dagen etter vedtaket. Falt forwardene: «duete heving, kursen fulgte signalet». Steg/uendret og kurs ned: «selg på nyheten». Mål kursen I-44-justert, og carry-setningen bare når `diff > 0`.

- [ ] **Vektene i retningssignalet.**
  *Problem:* Fast vekting (0,45/0,35/0,20) uten empirisk grunnlag.
  *Løsning:* Start med daglige snapshots i repoet (`data/snapshots/YYYY-MM-DD.json` fra Actions), uten historikk kan ingenting kalibreres. `scripts/backtest_signal.py`: regress 4-ukers I-44-justert avkastning på de tre faktorene. Inntil da: vis tre piler, komposittsignal som «2 av 3 drivere».

- [ ] **Reprisingshistorikk.**
  *Problem:* Bare endring siste uke og måned vises, ikke utviklingen over tid.
  *Løsning:* Fra snapshots: linje per bank av `path[12]` over tid, som ny sparkline under rentekortet. Avhenger av snapshots-punktet over.

- [ ] **Totalavkastning i sammenligningsgrafen.**
  *Problem:* Grafen viser kurs mot NOK, ikke totalavkastning med carry.
  *Løsning:* `TR_t = TR_{t−1} · S_t/S_{t−1} · (1 + (r_X − r_NOK)/360 · dager)` med OECD 3 mnd månedlig (hent full historikk av `ir3`). Toggle «kurs / med carry» i grafen.

## Teknisk

- [ ] **TTF inngår ikke i beregningene.**
  *Problem:* Gass står bare i teksten; korrelasjon gass↔krone er ikke regnet. (`ttf` ligger allerede i `history.market`.)
  *Løsning:* Regn `ttf_nok_corr` som for Brent, og bytt «oljenøytral» til «energinøytral» (begge |Δcorr| < 0,25). Vis hvilken av olje/gass som forklarer kronen best siste 90 dager. TTF=F har samme rulleproblem som BZ=F.

- [ ] **Frontend-tester.**
  *Problem:* Bare beregningene testes. Tekstlogikken i idéene (som ga «Tre ting» med fire punkter) fanges ikke.
  *Løsning:* `node --test` + jsdom: render hver seksjon fra fixtures (normal dag, vedtaksdag, manglende kurve, syntetisk anker). Assert: ingen `NaN`/`undefined`/`null` i DOM, antall idéer = tallet i overskriften, 4 hero-stats, signal på hvert kort; tekst-snapshot av idéene per fixture. Deploy-workflow feiler på rød test.

- [ ] **Manuelle filer uten varsel.**
  *Problem:* Kildesjekken dekker API-kilder, ikke `meetings.json`, `policy_overrides.json`, `cb_paths.json` og `meeting_odds.json`.
  *Løsning:* Gi alle fire `as_of` + `valid_until`, ta dem inn i `renderSources` som egen gruppe «manuelt vedlikeholdt» med samme ⚠-logikk.

- [ ] **Skrifter fra Google Fonts.**
  *Problem:* Siden er ikke uavhengig av tredjepart (`index.html` linje 8–10).
  *Løsning:* Fraunces og Inter er OFL: last ned woff2, subset til latin med `pyftsubset`, `@font-face` + `font-display: swap` + `<link rel=preload>`. Fjern Google-lenkene.

- [ ] **Skjermbilder.**
  *Problem:* Testnettleseren er upålitelig, mobilkontroll gjøres med DOM-målinger og enkeltbilder.
  *Løsning:* Playwright i Actions (`npx playwright install --with-deps chromium`), viewport 390/768/1280, `locator.screenshot()` per seksjon lastet opp som artifact, assert `scrollWidth <= clientWidth + 1`, `toHaveScreenshot` med `maxDiffPixelRatio: 0.02` mot baselines.

## Avhengigheter

- Markedsanker (punkt 1) må inn før reprising-dekomponering og «heving levert»-klassifisering.
- Snapshots må inn før vektkalibrering og reprisingshistorikk.
- Playwright-oppsettet deles av RBNZ-nedlasting, RBNZ MPS-xlsx og skjermbildene, så sett det opp én gang.

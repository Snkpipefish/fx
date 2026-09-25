#!/usr/bin/env python3
"""Henter markedsdata for G10-landene og skriver data/dashboard.json, data/history.json
og data/curves.json (kurvehistorikk, brukes bare av dette scriptet).

Kilder (alle gratis, uten API-nøkkel):
  - Valutakurser:      Frankfurter (ECB-referansekurser)
  - I-44 kroneindeks:  Norges Bank
  - Styringsrenter:    BIS (WS_CBPOL)
  - 10-års og 3-mnd:   OECD (DSD_STES@DF_FINMARK)
  - KPI å/å:           OECD (DSD_PRICES@DF_PRICES_ALL, Japan via DF_G20_PRICES)
  - Arbeidsledighet:   OECD (DSD_LFS@DF_IALFS_UNE_M)
  - Brent og VIX:      FRED (offentlig fredgraph.csv, uten nøkkel)
  - COT-posisjonering: CFTC Socrata (legacy futures-only, datasett 6dca-aqww;
                       samme kilde som bedrock-prosjektets cot_cftc-modul)
  - PPP (kjøpekraft):  World Bank (PA.NUS.PPP; Tyskland som proxy for eurosonen)
  - Rentekurver:       FRED (USA), ECB (eurosonen), MoF (Japan), Bank of England
                       (OIS), Bank of Canada, RBA, Riksbanken, Norges Bank
                       (nullkupong) – grunnlag for «hva er priset inn»

Kjøres uten argumenter. Feiler én kilde beholdes forrige verdi fra eksisterende
JSON-filer, slik at en enkelt nede-tjeneste ikke velter hele oppdateringen.
"""

import concurrent.futures
import csv
import html
import io
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

COUNTRIES = [
    {"id": "us", "name": "USA", "currency": "USD", "bank": "Federal Reserve", "flag": "🇺🇸", "bis": "US", "oecd": "USA"},
    {"id": "ea", "name": "Eurosonen", "currency": "EUR", "bank": "ECB", "flag": "🇪🇺", "bis": "XM", "oecd": "EA20"},
    {"id": "jp", "name": "Japan", "currency": "JPY", "bank": "Bank of Japan", "flag": "🇯🇵", "bis": "JP", "oecd": "JPN", "per": 100},
    {"id": "gb", "name": "Storbritannia", "currency": "GBP", "bank": "Bank of England", "flag": "🇬🇧", "bis": "GB", "oecd": "GBR"},
    {"id": "ch", "name": "Sveits", "currency": "CHF", "bank": "Swiss National Bank", "flag": "🇨🇭", "bis": "CH", "oecd": "CHE"},
    {"id": "ca", "name": "Canada", "currency": "CAD", "bank": "Bank of Canada", "flag": "🇨🇦", "bis": "CA", "oecd": "CAN"},
    {"id": "au", "name": "Australia", "currency": "AUD", "bank": "Reserve Bank of Australia", "flag": "🇦🇺", "bis": "AU", "oecd": "AUS"},
    {"id": "nz", "name": "New Zealand", "currency": "NZD", "bank": "Reserve Bank of New Zealand", "flag": "🇳🇿", "bis": "NZ", "oecd": "NZL", "cpi_freq": "Q"},
    {"id": "se", "name": "Sverige", "currency": "SEK", "bank": "Riksbanken", "flag": "🇸🇪", "bis": "SE", "oecd": "SWE"},
    {"id": "no", "name": "Norge", "currency": "NOK", "bank": "Norges Bank", "flag": "🇳🇴", "bis": "NO", "oecd": "NOR"},
]

OECD_BASE = "https://sdmx.oecd.org/public/rest/data"

# CFTC-kontraktnavn per land (legacy futures-only). NOK/SEK har ingen
# likvide futures og mangler derfor COT-data.
COT_CONTRACTS = {
    "us": "USD INDEX",
    "ea": "EURO FX",
    "jp": "JAPANESE YEN",
    "gb": "BRITISH POUND",
    "ch": "SWISS FRANC",
    "ca": "CANADIAN DOLLAR",
    "au": "AUSTRALIAN DOLLAR",
    "nz": "NZ DOLLAR",
}

# World Bank-koder for PPP. Eurosonen mangler i World Bank; Tyskland brukes som proxy.
PPP_ISO = {"us": "USA", "ea": "DEU", "jp": "JPN", "gb": "GBR", "ch": "CHE",
           "ca": "CAN", "au": "AUS", "nz": "NZL", "se": "SWE", "no": "NOR"}


def fetch(url, timeout=45, attempts=3, errors="strict"):
    """HTTP GET med få, korte forsøk. Kildene hentes parallelt, så én treg kilde
    skal ikke koste mer enn sin egen timeout."""
    # Accept-headeren er nødvendig: FRED (Akamai) lar forespørsler uten den henge til timeout
    req = urllib.request.Request(url, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors=errors)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(3 * (attempt + 1))


def to_float(value):
    """Tallverdi eller None – filtrerer bort NaN/inf som ville gitt ugyldig JSON."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def fetch_fx_history():
    """1 års daglig historikk: verdien av 1 enhet av hver valuta i NOK."""
    end = date.today()
    start = end - timedelta(days=370)
    symbols = ",".join(c["currency"] for c in COUNTRIES if c["currency"] != "NOK")
    url = f"https://api.frankfurter.dev/v1/{start}..{end}?base=NOK&symbols={symbols}"
    raw = json.loads(fetch(url))
    series = {}
    for day, rates in sorted(raw["rates"].items()):
        for cur, val in rates.items():
            if val:
                series.setdefault(cur, {})[day] = round(1.0 / val, 5)
    return series


def fetch_i44_history():
    """Norges Banks importveide kroneindeks (I-44). Lavere = sterkere krone."""
    start = date.today() - timedelta(days=370)
    url = (
        "https://data.norges-bank.no/api/data/EXR/B.I44.NOK.SP"
        f"?startPeriod={start}&format=csv"
    )
    raw = fetch(url)
    series = {}
    for row in csv.DictReader(io.StringIO(raw), delimiter=";"):
        value = to_float(row.get("OBS_VALUE"))
        if value is not None:
            series[row["TIME_PERIOD"]] = value
    return series


def fetch_policy_rates():
    """Styringsrenter fra BIS med 2 års historikk for trend."""
    start = date.today() - timedelta(days=730)
    areas = "+".join(c["bis"] for c in COUNTRIES)
    url = (
        f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{areas}"
        f"?startPeriod={start}&format=csv"
    )
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
        value = to_float(row.get("OBS_VALUE"))
        if area and period and value is not None:
            series.setdefault(area, {})[period] = value
    return series


# ---------------------------------------------------------------------------
# Styringsrenter direkte fra sentralbankene (BIS henger typisk noen dager etter vedtak).
# Hver henter gir {dato: rente} for de siste ukene; ECB gir bare endringsdatoer (trapp).
# ---------------------------------------------------------------------------
POLICY_SOURCE_LABELS = {"no": "Norges Bank", "se": "Riksbanken", "ca": "Bank of Canada", "ea": "ECB",
                        "us": "Fed (FRED, midtpunkt i intervallet)", "gb": "Bank of England", "au": "RBA", "ch": "SNB"}
POLICY_LOOKBACK_DAYS = 60
OVERRIDE_GRACE_DAYS = 5  # dager etter et manuelt vedtak der den offisielle serien får lov å henge etter (virkningsdato)


def policy_start():
    return str(date.today() - timedelta(days=POLICY_LOOKBACK_DAYS))


def parse_norges_bank_policy(csv_text):
    out = {}
    for row in csv.DictReader(io.StringIO(csv_text), delimiter=";"):
        value = to_float(row.get("OBS_VALUE"))
        if row.get("TIME_PERIOD") and value is not None:
            out[row["TIME_PERIOD"]] = value
    return out


def fetch_policy_no():
    return parse_norges_bank_policy(fetch(f"https://data.norges-bank.no/api/data/IR/B.KPRA.SD.?format=csv&startPeriod={policy_start()}", timeout=60))


def fetch_policy_se():
    obs = json.loads(fetch("https://api.riksbank.se/swea/v1/Observations/Latest/SECBREPOEFF", timeout=60))
    value = to_float(obs.get("value"))
    if not obs.get("date") or value is None:
        raise RuntimeError("uventet svar fra Riksbanken")
    return {obs["date"]: value}


def parse_valet(payload, series_id):
    out = {}
    for obs in payload.get("observations", []):
        value = to_float((obs.get(series_id) or {}).get("v"))
        if obs.get("d") and value is not None:
            out[obs["d"]] = value
    return out


def fetch_policy_ca():
    return parse_valet(json.loads(fetch(f"https://www.bankofcanada.ca/valet/observations/V39079/json?start_date={policy_start()}", timeout=60)), "V39079")


def parse_ecb_csv(csv_text):
    out = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        value = to_float(row.get("OBS_VALUE"))
        if row.get("TIME_PERIOD") and value is not None:
            out[row["TIME_PERIOD"]] = value
    return out


def expand_daily(series, until):
    """Trapp → daglige observasjoner (virkedager) fra første dato t.o.m. `until`, så
    kildestatusen viser dagens dato og ikke siste endringsdato."""
    if not series:
        return {}
    out, day, end = {}, date.fromisoformat(min(series)), date.fromisoformat(until)
    while day <= end:
        if day.weekday() < 5:
            out[str(day)] = value_at_or_before(series, str(day))
        day += timedelta(days=1)
    return out


def fetch_policy_ea():
    """Innskuddsrenten (DFR) som endringsdatoer: en trapp, siste verdi gjelder til neste endring."""
    changes = parse_ecb_csv(fetch("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.DFR.LEV?lastNObservations=3&format=csvdata", timeout=60))
    return expand_daily(changes, str(date.today()))


def fetch_policy_us():
    """Midtpunktet i fed funds-intervallet (FRED DFEDTARU/DFEDTARL), som BIS-serien."""
    upper, lower = fetch_fred_series("DFEDTARU"), fetch_fred_series("DFEDTARL")
    start = policy_start()
    return {d: round((upper[d] + lower[d]) / 2, 4) for d in upper if d in lower and d >= start}


def parse_boe_csv(csv_text):
    out = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        value = to_float(row.get("IUDBEDR"))
        try:
            day = str(datetime.strptime((row.get("DATE") or "").strip(), "%d %b %Y").date())
        except ValueError:
            continue
        if value is not None:
            out[day] = value
    return out


def fetch_policy_gb():
    start = date.fromisoformat(policy_start()).strftime("%d/%b/%Y")
    url = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
           f"&Datefrom={start}&Dateto=now&SeriesCodes=IUDBEDR&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    return parse_boe_csv(fetch(url, timeout=60))


def fetch_policy_au():
    return {d: v["0"] for d, v in rba_series("f1-data", {"FIRMMCRTD": 0}, policy_start()).items() if "0" in v}


def fetch_policy_ch():
    text = fetch(SNB_CUBE.format(cube="snbgwdzid", sel="D0(LZ)", start=policy_start()), timeout=60)
    return {d: v["0"] for d, v in parse_snb_cube(text, {"LZ": 0}).items() if "0" in v}


POLICY_FETCHERS = {"no": fetch_policy_no, "se": fetch_policy_se, "ca": fetch_policy_ca, "ea": fetch_policy_ea,
                   "us": fetch_policy_us, "gb": fetch_policy_gb, "au": fetch_policy_au, "ch": fetch_policy_ch}


def merge_policy(bis, official):
    """BIS-historikk der sentralbankens egen serie overstyrer fra sin første dato og
    fremover (også for dager BIS mangler). Sparsom offisiell serie (ECB: endringsdatoer)
    videreføres som trapp. Returnerer ny dict."""
    merged = dict(bis)
    if not official:
        return merged
    first = min(official)
    for day in set(merged) | set(official):
        if day >= first:
            merged[day] = value_at_or_before(official, day)
    return merged


def apply_policy_override(series, ov, today, grace_days=OVERRIDE_GRACE_DAYS):
    """Manuelt registrert vedtak (annonseringsdato). Gjelder når serien ikke har nådd
    vedtaksdatoen, eller viser gammel rente inntil `grace_days` etter (seriene fører
    virkningsdato). Viser serien fortsatt noe annet senere enn det, stoler vi på serien.
    Returnerer (serie, status) der status er «brukt», «bekreftet», «avvik» eller None."""
    if not ov or not ov.get("date") or ov.get("rate") is None or ov["date"] > today:
        return series, None
    policy_day, policy = latest(series)
    if policy_day and policy_day >= ov["date"] and abs(policy - ov["rate"]) < 1e-9:
        return series, "bekreftet"
    grace = str(date.fromisoformat(ov["date"]) + timedelta(days=grace_days))
    if policy_day and policy_day > grace:
        return series, "avvik"
    out = {d: (ov["rate"] if d >= ov["date"] else v) for d, v in series.items()}
    out[ov["date"]] = ov["rate"]
    return out, "brukt"


def unconfirmed_meeting(meetings, policy_day, today):
    """Møtedato som er passert, men som styringsrenteserien ennå ikke dekker (dato < møtet)."""
    passed = [m for m in meetings if m <= today and (policy_day is None or m > policy_day)]
    return max(passed) if passed else None


# ---------------------------------------------------------------------------
# Sentralbankenes egne rentebaner (halvautomatisk): Fed SEP, Norges Bank PPR, Riksbanken.
# RBNZ ligger bak Cloudflare og vedlikeholdes i data/cb_paths.json, som også er reserve.
# Hver henter gir {"path": {iso-dato: nivå}, "as_of": dato, "label": tekst}.
# ---------------------------------------------------------------------------
FED_CALENDAR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
NB_PPR_LIST = "https://www.norges-bank.no/aktuelt/nyheter-og-hendelser/Publikasjoner/Pengepolitisk-rapport-med-vurdering-av-finansiell-stabilitet/"
RB_FORECASTS = "https://www.riksbank.se/globalassets/media/statistik/makro/sve/utfall-och-prognoser.xlsx"


def parse_fed_sep(html_text):
    """Median for fed funds-renten per år fra SEP-tabellen: {«ÅÅÅÅ-12-31»: nivå, «longer_run»: nivå}."""
    table = next((t for t in re.findall(r"<table.*?</table>", html_text, re.S) if "Federal funds rate" in t and "Median" in t), None)
    if not table:
        raise RuntimeError("fant ikke SEP-tabellen")
    rows = [[re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            for r in re.findall(r"<tr.*?</tr>", table, re.S)]
    years = next((r for r in rows if r and re.fullmatch(r"20\d\d", r[0])), None)
    ffr = next((r for r in rows if r and r[0].startswith("Federal funds rate")), None)
    if not years or not ffr:
        raise RuntimeError("fant ikke år- eller renteraden i SEP-tabellen")
    out = {}
    for label, value in zip(years, ffr[1:]):
        v = to_float(value)
        if v is None:
            continue
        if re.fullmatch(r"20\d\d", label):
            out[f"{label}-12-31"] = v
        elif label.lower().startswith("longer"):
            out["longer_run"] = v
    if not out:
        raise RuntimeError("tom renterad i SEP-tabellen")
    return out


def fetch_cb_path_us():
    calendar = fetch(FED_CALENDAR, timeout=60)
    links = sorted(set(re.findall(r"fomcprojtabl(\d{8})\.htm", calendar)))
    if not links:
        raise RuntimeError("ingen SEP-tabeller i FOMC-kalenderen")
    stamp = links[-1]
    path = parse_fed_sep(fetch(f"https://www.federalreserve.gov/monetarypolicy/fomcprojtabl{stamp}.htm", timeout=60))
    as_of = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    return {"path": path, "as_of": as_of, "label": f"FOMC dot plot (median), {as_of}"}


def parse_nb_tallsett(xlsx_bytes):
    """Styringsrenten (nivå), kvartalsvis anslag, fra arket «Data A» i PPR-tallsettet."""
    rows = xlsx_sheet_rows(xlsx_bytes, "Data A")
    header = next((c for _, c in rows if c.get("A") == "Dato"), None)
    col = next((k for k, v in (header or {}).items() if isinstance(v, str) and v.startswith("Styringsrenten (nivå)")), None)
    if not col:
        raise RuntimeError("fant ikke kolonnen «Styringsrenten (nivå)» i Data A")
    out = {}
    for _, c in rows:
        if isinstance(c.get("A"), (int, float)) and isinstance(c.get(col), (int, float)):
            out[excel_date(c["A"])] = round(c[col], 3)
    if not out:
        raise RuntimeError("ingen rentebane i Data A")
    return out


def fetch_cb_path_no():
    listing = fetch(NB_PPR_LIST, timeout=60)
    pages = sorted(set(re.findall(r'href="(/aktuelt/publikasjoner/Pengepolitisk-rapport/(\d{4})/ppr-(\d)\d{4}/)"', listing)),
                   key=lambda m: (m[1], m[2]))
    if not pages:
        raise RuntimeError("ingen PPR-sider i listen")
    href, year, no = pages[-1]
    page = fetch("https://www.norges-bank.no" + href, timeout=60)
    m = re.search(r'href="(/contentassets/[^"]*tallsett-ppr-[^"?]*\.xlsx)(?:\?v=(\d{8}))?', page)
    if not m:
        raise RuntimeError(f"fant ikke tallsett-xlsx på {href}")
    req = urllib.request.Request("https://www.norges-bank.no" + m.group(1), headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        path = parse_nb_tallsett(resp.read())
    stamp = m.group(2)
    as_of = f"{stamp[4:]}-{stamp[2:4]}-{stamp[:2]}" if stamp else str(date.today())
    return {"path": path, "as_of": as_of, "label": f"Norges Bank, Pengepolitisk rapport {no}/{year[2:]}"}


def parse_rb_forecasts(xlsx_bytes):
    """Riksbankens styrränteprognose (kvartalssnitt) fra arket SEQRATENAYNA: nyeste rapport i kolonne B."""
    rows = xlsx_sheet_rows(xlsx_bytes, "SEQRATENAYNA")
    cells = {c.get("A"): c for _, c in rows if isinstance(c.get("A"), str)}
    report = (cells.get("PPR") or {}).get("B")
    published = (cells.get("Publiceringsdatum") or {}).get("B")
    out = {}
    for _, c in rows:
        a = c.get("A")
        if isinstance(a, str) and DATE_RE.match(a) and isinstance(c.get("B"), (int, float)):
            out[a] = round(c["B"], 3)
    if not out or not report:
        raise RuntimeError("fant ikke prognosen i SEQRATENAYNA")
    as_of = excel_date(published) if isinstance(published, (int, float)) else str(date.today())
    return {"path": out, "as_of": as_of, "label": f"Riksbanken, Penningpolitisk rapport {report}"}


def fetch_cb_path_se():
    req = urllib.request.Request(RB_FORECASTS, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return parse_rb_forecasts(resp.read())


CB_PATH_FETCHERS = {"us": fetch_cb_path_us, "no": fetch_cb_path_no, "se": fetch_cb_path_se}


def cb_path_at(path, target):
    """Bankens anslag ved horisonten: første datapunkt på eller etter `target` (kvartals-
    eller årsslutt), ellers siste punkt. Returnerer (dato, nivå) eller (None, None)."""
    dated = sorted((d, v) for d, v in path.items() if DATE_RE.match(d))
    if not dated:
        return None, None
    later = [(d, v) for d, v in dated if d >= target]
    return later[0] if later else dated[-1]


def horizon_text(day):
    d = date.fromisoformat(day)
    if d.month == 12 and d.day == 31:
        return f"utgangen av {d.year}"
    return f"{(d.month - 1) // 3 + 1}. kvartal {d.year}"


def fetch_oecd_rates(measure):
    """Månedlige renter fra OECD: IRLT (10 år) eller IR3TIB (3 mnd)."""
    start = date.today() - timedelta(days=430)
    areas = "+".join(c["oecd"] for c in COUNTRIES)
    url = (
        f"{OECD_BASE}/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
        f"{areas}.M.{measure}.PA.....?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
    )
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
        value = to_float(row.get("OBS_VALUE"))
        if area and period and value is not None:
            series.setdefault(area, {})[period] = value
    return series


def fetch_cpi():
    """KPI å/å per land, flettet fra flere dataflyter.

    Europa gikk over til COICOP 2018-klassifisering i januar 2026, og OECDs
    gamle dataflyt (COICOP 1999) sluttet da å oppdatere NOR/SWE/CHE/EA.
    Vi spør derfor begge flytene og fletter – nyeste observasjon vinner.
    Eurosonen finnes ikke i 2018-flyten og hentes fra Eurostat (EA21).
    Japan ligger kun i G20-dataflyten (1999); New Zealand er kvartalsvis.
    """
    start = date.today() - timedelta(days=430)
    result = {}
    monthly = [c["oecd"] for c in COUNTRIES if c["oecd"] != "JPN" and c.get("cpi_freq") != "Q"]
    queries = [
        ("DSD_PRICES@DF_PRICES_ALL,1.0", "+".join(monthly), "M"),
        ("DSD_PRICES@DF_PRICES_ALL,1.0", "NZL", "Q"),
        ("DSD_G20_PRICES@DF_G20_PRICES,1.0", "JPN", "M"),
        ("DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL,1.0", "+".join(monthly) + "+JPN", "M"),
        ("DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL,1.0", "NZL", "Q"),
    ]
    for flow, areas, freq in queries:
        url = (
            f"{OECD_BASE}/OECD.SDD.TPS,{flow}/"
            f"{areas}.{freq}.N.CPI.PA._T.N.GY?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
        )
        try:
            raw = fetch(url, timeout=120)
        except Exception as exc:  # én delspørring skal ikke velte resten
            print(f"  ADVARSEL: KPI-spørring feilet for {areas}: {exc}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(raw)):
            area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
            value = to_float(row.get("OBS_VALUE"))
            if area and period and value is not None:
                result.setdefault(area, {})[period] = value

    # Eurosonen: HICP å/å fra Eurostat (ECOICOP ver. 2). Lagres som EA20
    # slik at oppslaget i main() treffer.
    try:
        raw = fetch(
            "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
            "?format=JSON&geo=EA21&coicop18=TOTAL&unit=RCH_A&lastTimePeriod=4"
        )
        data = json.loads(raw)
        periods = {v: k for k, v in data["dimension"]["time"]["category"]["index"].items()}
        for i, v in data["value"].items():
            if v is not None:
                result.setdefault("EA20", {})[periods[int(i)]] = v
    except Exception as exc:
        print(f"  ADVARSEL: Eurostat-HICP feilet: {exc}", file=sys.stderr)
    return result


def fetch_fred_series(series_id, days=400):
    """Serie fra FREDs offentlige CSV-endepunkt (Brent, VIX, PCE), siste `days` dager."""
    start = date.today() - timedelta(days=days)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        value = to_float(row.get(series_id))
        if value is not None:
            series[row["observation_date"]] = value
    return series


def fetch_yahoo(symbol, decimals=2):
    """Daglige sluttkurser for et Yahoo Finance-symbol (uoffisielt, men åpent endepunkt)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (valuta-dashboard)", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    out = {}
    for ts, close in zip(result["timestamp"], closes):
        value = to_float(close)
        if value is not None:
            out[str(date.fromtimestamp(ts))] = round(value, decimals)
    return out


BRENT_MONTH_CODES = "FGHJKMNQUVXZ"


def brent_front_contracts(today=None):
    """Yahoo-symboler for nærmeste og neste Brent-kontrakt som ikke har utløpt.

    ICE Brent for leveringsmåned M utløper siste virkedag i måned M−2, så i
    september er novemberkontrakten front (utløper 30. september).
    """
    today = today or date.today()
    # Første kandidat: leveringsmåned = inneværende måned + 2
    y, m = today.year, today.month + 2
    if m > 12:
        y, m = y + 1, m - 12
    out = []
    while len(out) < 2:
        out.append(f"BZ{BRENT_MONTH_CODES[m - 1]}{str(y)[2:]}.NYM")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


BRENT_MONTHS = {"F": "jan", "G": "feb", "H": "mar", "J": "apr", "K": "mai", "M": "jun", "N": "jul", "Q": "aug", "U": "sep", "V": "okt", "X": "nov", "Z": "des"}


def brent_label(symbol):
    code = symbol[2:5]
    return f"{BRENT_MONTHS[code[0]]}. 20{code[1:]}-kontrakten ({symbol.split('.')[0]})"


def fetch_brent_futures():
    """De to nærmeste Brent-kontraktene (ikke Yahoos rullende BZ=F, som hopper mellom
    kontrakter). Endringer regnes innenfor samme kontrakt; front-kontrakten brukes til
    utløp. Returnerer {"front": serie, "next": serie, "front_label", "next_label"}."""
    symbols = brent_front_contracts()
    front, nxt = fetch_yahoo(symbols[0]), fetch_yahoo(symbols[1])
    if not front and not nxt:
        raise RuntimeError(f"ingen data for {symbols[0]} eller {symbols[1]}")
    return {"front": front, "next": nxt, "front_label": brent_label(symbols[0]), "next_label": brent_label(symbols[1])}


def brent_front_and_next(fut):
    """Velger front-kontrakten så lenge den har ferske kurser; har neste kontrakt en nyere
    dato (front utløpt eller uten handel), rulles det til den. Returnerer
    (front-serie, front-etikett, neste-serie, neste-etikett)."""
    front, nxt = fut.get("front") or {}, fut.get("next") or {}
    if nxt and (not front or max(nxt) > max(front)):
        return nxt, fut.get("next_label"), {}, None
    return front, fut.get("front_label"), nxt, fut.get("next_label")


def premium_series(dated, fut):
    """Spotpremie per dag: Dated Brent minus front-kontrakten samme dato (bare dager der begge finnes)."""
    return {d: round(dated[d] - fut[d], 2) for d in sorted(set(dated) & set(fut))}


def trailing_mean(series, days=90):
    """Gjennomsnitt av verdiene siste `days` kalenderdager fra siste observasjon."""
    day, _ = latest(series)
    if not day:
        return None
    cutoff = str(date.fromisoformat(day) - timedelta(days=days))
    values = [v for d, v in series.items() if d > cutoff]
    return round(sum(values) / len(values), 2) if values else None


def fetch_ons_cpi():
    """Britisk KPI å/å (ONS-serie D7G7) – ONS publiserer før OECD og uten revisjonslag."""
    raw = json.loads(fetch("https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data", timeout=60))
    months = {"January": "01", "February": "02", "March": "03", "April": "04", "May": "05", "June": "06",
              "July": "07", "August": "08", "September": "09", "October": "10", "November": "11", "December": "12"}
    out = {}
    for row in raw.get("months", []):
        value = to_float(row.get("value"))
        if value is not None and row.get("month") in months:
            out[f"{row['year']}-{months[row['month']]}"] = value
    return out


def fetch_ssb_kpi_jae():
    """KPI-JAE 12-måneders endring fra SSB (tabell 14706, 2025=100) – Norges Banks målvariabel."""
    query = {"query": [
        {"code": "KPIavledetSerie", "selection": {"filter": "item", "values": ["KPI-JAE"]}},
        {"code": "ContentsCode", "selection": {"filter": "item", "values": ["Tolvmanedersendring"]}},
        {"code": "Tid", "selection": {"filter": "top", "values": ["4"]}}],
        "response": {"format": "json"}}
    req = urllib.request.Request("https://data.ssb.no/api/v0/no/table/14706", data=json.dumps(query).encode(),
                                 headers={"User-Agent": "valuta-dashboard/1.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8-sig"))
    out = {}
    for row in data["data"]:
        value = to_float(row["values"][0])
        if value is not None:
            out[row["key"][-1].replace("M", "-")] = value
    return out


def fetch_scb_kpif():
    """KPIF 12-månadsförändring fra SCB (tabell KPIF2020) – Riksbankens målvariabel."""
    query = {"query": [
        {"code": "ContentsCode", "selection": {"filter": "item", "values": ["000007ZM"]}},
        {"code": "Tid", "selection": {"filter": "top", "values": ["4"]}}],
        "response": {"format": "json"}}
    req = urllib.request.Request("https://api.scb.se/OV0104/v1/doris/sv/ssd/START/PR/PR0101/PR0101G/KPIF2020",
                                 data=json.dumps(query).encode(),
                                 headers={"User-Agent": "valuta-dashboard/1.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8-sig"))
    out = {}
    for row in data["data"]:
        value = to_float(row["values"][0])
        if value is not None:
            out[row["key"][-1].replace("M", "-")] = value
    return out


def fetch_cpi_core():
    """KPI uten mat og energi å/å (OECD, begge klassifiseringer – nyeste observasjon vinner)."""
    start = date.today() - timedelta(days=430)
    result = {}
    areas = "+".join(c["oecd"] for c in COUNTRIES)
    for flow in ("DSD_PRICES@DF_PRICES_ALL,1.0", "DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL,1.0"):
        url = (f"{OECD_BASE}/OECD.SDD.TPS,{flow}/{areas}.M.N.CPI.PA._TXCP01_NRG.N.GY"
               f"?startPeriod={start:%Y-%m}&format=csvfilewithlabels")
        try:
            raw = fetch(url, timeout=90)
        except Exception as exc:
            print(f"  ADVARSEL: kjerne-KPI feilet for {flow}: {exc}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(raw)):
            area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
            value = to_float(row.get("OBS_VALUE"))
            if area and period and value is not None:
                result.setdefault(area, {})[period] = value
    # Eurosonen: HICP uten energi og mat fra Eurostat (OECD mangler EA i 2026)
    try:
        raw = fetch("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
                    "?format=JSON&geo=EA21&coicop18=TOT_X_NRG_FOOD&unit=RCH_A&lastTimePeriod=4", timeout=60)
        data = json.loads(raw)
        periods = {v: k for k, v in data["dimension"]["time"]["category"]["index"].items()}
        for i, v in data["value"].items():
            if v is not None:
                result.setdefault("EA20", {})[periods[int(i)]] = v
    except Exception as exc:
        print(f"  ADVARSEL: Eurostat kjerne-HICP feilet: {exc}", file=sys.stderr)
    return result


# Sentralbankenes egne kjernemål der OECDs «uten mat og energi» ikke er målvariabelen
def yoy_from_index(index):
    """{«ÅÅÅÅ-MM»: å/å-endring i %} fra en månedlig indeks {«ÅÅÅÅ-MM-DD»: nivå}."""
    out = {}
    for day, value in index.items():
        prev = f"{int(day[:4]) - 1}{day[4:]}"
        if prev in index and index[prev]:
            out[day[:7]] = round((value / index[prev] - 1) * 100, 2)
    return out


def fetch_pce_core():
    """Kjerne-PCE å/å (FRED PCEPILFE, indeks 2017=100) – Feds målvariabel."""
    return yoy_from_index(fetch_fred_series("PCEPILFE", days=800))


def parse_abs_csv(csv_text):
    out = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        value = to_float(row.get("OBS_VALUE"))
        if row.get("TIME_PERIOD") and value is not None:
            out[row["TIME_PERIOD"]] = value
    return out


def fetch_abs_trimmed_mean():
    """Trimmet gjennomsnitt å/å, månedlig, sesongjustert (ABS CPI: mål 3, indeks 999902,
    justering 20, Australia 50) – RBAs foretrukne kjernemål."""
    start = (date.today() - timedelta(days=430)).strftime("%Y-%m")
    url = f"https://data.api.abs.gov.au/rest/data/ABS,CPI/3.999902.20.50.M?startPeriod={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "application/vnd.sdmx.data+csv;labels=id"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return parse_abs_csv(resp.read().decode("utf-8"))


def boc_core_average(payload):
    """Snitt av CPI-trim og CPI-median (å/å) per måned fra Valet-svaret."""
    trim, median = parse_valet(payload, "CPI_TRIM"), parse_valet(payload, "CPI_MEDIAN")
    return {d[:7]: round((trim[d] + median[d]) / 2, 2) for d in trim if d in median}


def fetch_boc_core():
    """Bank of Canadas foretrukne kjernemål: snittet av CPI-trim og CPI-median (Valet)."""
    start = date.today() - timedelta(days=430)
    payload = json.loads(fetch(f"https://www.bankofcanada.ca/valet/observations/CPI_TRIM,CPI_MEDIAN/json?start_date={start}", timeout=60))
    return boc_core_average(payload)


# Målvariabel per bank: (kilde-nøkkel, etikett). Øvrige viser OECDs «uten mat og energi» som visning.
CORE_TARGETS = {
    "us": ("pce_core", "Kjerne-PCE (FRED)"),
    "au": ("abs_trimmed", "Trimmet gjennomsnitt (ABS, sesongjustert)"),
    "ca": ("boc_core", "CPI-trim/median (Bank of Canada)"),
    "no": ("ssb_kpi_jae", "KPI-JAE (SSB)"),
    "se": ("scb_kpif", "KPIF (SCB)"),
}
CORE_NOTES = {
    "jp": "KPI uten mat og energi (OECD) – BoJ styrer etter KPI uten fersk mat",
    "gb": "KPI uten mat og energi (OECD) – målet er samlet KPI",
    "ch": "KPI uten mat og energi (OECD) – målet er samlet KPI",
    "nz": "KPI uten mat og energi (OECD) – målet er samlet KPI",
}


COT_DATASETS = {
    # Socrata-datasett hos CFTC: legacy futures-only, legacy futures+options, TFF futures-only (leveraged funds)
    "legacy": ("6dca-aqww", "noncomm_positions_long_all", "noncomm_positions_short_all"),
    "combined": ("jun7-fc8e", "noncomm_positions_long_all", "noncomm_positions_short_all"),
    "tff": ("gpe5-46if", "lev_money_positions_long", "lev_money_positions_short"),
}
COT_SIGMA_WEEKS = 52
COT_SIGMA_LIMIT = 3.0
COT_OI_LIMIT_PCT = 25.0


def fetch_cot_dataset(dataset, long_field, short_field, start):
    contracts = "','".join(COT_CONTRACTS.values())
    query = urllib.parse.urlencode({
        "$select": f"report_date_as_yyyy_mm_dd,contract_market_name,{long_field},{short_field},open_interest_all",
        "$where": f"contract_market_name in('{contracts}') AND report_date_as_yyyy_mm_dd >= '{start}'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "5000",
    })
    out = {}
    for row in json.loads(fetch(f"https://publicreporting.cftc.gov/resource/{dataset}.json?{query}", timeout=120)):
        long_, short = to_float(row.get(long_field)), to_float(row.get(short_field))
        if long_ is None or short is None:
            continue
        oi = to_float(row.get("open_interest_all"))
        out.setdefault(row["contract_market_name"], {})[row["report_date_as_yyyy_mm_dd"][:10]] = (int(long_ - short), int(oi) if oi else None)
    return out


def fetch_cot():
    """Netto spekulativ posisjonering fra CFTC, ukentlig, ca. 1 år.

    Hovedserien er legacy futures-only (non-commercial). I tillegg hentes legacy
    futures+options (net_comb) og TFF leveraged funds (lev), så et stort ukesving kan
    kontrolleres mot de andre rapportene. Netto = long − short."""
    start = date.today() - timedelta(days=400)
    legacy = fetch_cot_dataset(*COT_DATASETS["legacy"], start)
    extra = {}
    for key in ("combined", "tff"):
        try:
            extra[key] = fetch_cot_dataset(*COT_DATASETS[key], start)
            time.sleep(1)
        except Exception as exc:  # tilleggsrapportene er kontroll, ikke krav
            print(f"  ADVARSEL: COT {key} feilet ({exc})", file=sys.stderr)
            extra[key] = {}
    by_contract = {}
    for contract, days in legacy.items():
        for day, (net, oi) in days.items():
            entry = {"net": net, "oi": oi}
            comb = extra.get("combined", {}).get(contract, {}).get(day)
            lev = extra.get("tff", {}).get(contract, {}).get(day)
            if comb:
                entry["net_comb"] = comb[0]
            if lev:
                entry["lev"] = lev[0]
            by_contract.setdefault(contract, {})[day] = entry
    return by_contract


def is_roll_week(report_day):
    """Rapportdato (tirsdag) i uka der valutafutures ruller: tredje onsdag i mar/jun/sep/des."""
    d = date.fromisoformat(report_day)
    if d.month not in (3, 6, 9, 12):
        return False
    imm = third_wednesday(d.year, d.month)
    return -6 <= (imm - d).days <= 1


def cot_flags(series, sigma_weeks=COT_SIGMA_WEEKS):
    """Kontroll av siste ukesving: Δnet i standardavvik (siste 52 ukeendringer før denne),
    ΔOI i prosent, rulleuke, og om svinget finnes med samme fortegn i futures+options og TFF.
    unusual = |Δnet| > 3σ eller ΔOI > 25 %; confirmed = True/False når kontrollseriene finnes."""
    days = sorted(series)
    if len(days) < 2:
        return {}
    last, prev = series[days[-1]], series[days[-2]]
    change = last["net"] - prev["net"]
    nets = [series[d]["net"] for d in days]
    diffs = [b - a for a, b in zip(nets, nets[1:])][:-1][-sigma_weeks:]
    sigma = statistics.pstdev(diffs) if len(diffs) >= 8 else None
    z = round(change / sigma, 1) if sigma else None
    oi_pct = round((last["oi"] / prev["oi"] - 1) * 100, 1) if last.get("oi") and prev.get("oi") else None
    unusual = (z is not None and abs(z) > COT_SIGMA_LIMIT) or (oi_pct is not None and oi_pct > COT_OI_LIMIT_PCT)
    checks = []
    for key in ("net_comb", "lev"):
        if last.get(key) is not None and prev.get(key) is not None:
            other = last[key] - prev[key]
            checks.append(other != 0 and (other > 0) == (change > 0) and abs(other) >= abs(change) / 4)
    out = {"z_w": z, "oi_change_pct": oi_pct, "roll_week": is_roll_week(days[-1]), "unusual": unusual,
           "confirmed": all(checks) if len(checks) == 2 else None}
    if last.get("lev") is not None:
        out["lev_net"] = last["lev"]
    return out


def fetch_ppp():
    """PPP-kurs (lokal valuta per internasjonal dollar) fra World Bank, siste år."""
    isos = ";".join(sorted(set(PPP_ISO.values())))
    year = date.today().year
    url = (
        f"https://api.worldbank.org/v2/country/{isos}/indicator/PA.NUS.PPP"
        f"?format=json&date={year - 5}:{year}&per_page=300"
    )
    raw = json.loads(fetch(url).encode().decode("utf-8-sig"))
    latest_by_iso = {}
    for row in raw[1] or []:
        value = to_float(row.get("value"))
        if value is None:
            continue
        iso = row["countryiso3code"]
        if iso not in latest_by_iso or row["date"] > latest_by_iso[iso][0]:
            latest_by_iso[iso] = (row["date"], value)
    return latest_by_iso


def fetch_unemployment():
    """Arbeidsledighetsrate (sesongjustert) fra OECD.

    Sveits/New Zealand publiserer kun kvartalsvis; eurosonen mangler helt hos
    OECD og hentes fra Eurostat (geo-kode EA21) i stedet.
    """
    start = date.today() - timedelta(days=430)
    series = {}
    monthly = "+".join(c["oecd"] for c in COUNTRIES if c["oecd"] not in ("CHE", "NZL", "EA20"))
    for areas, freq in [(monthly, "M"), ("CHE+NZL", "Q")]:
        url = (
            f"{OECD_BASE}/OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/"
            f"{areas}.UNE_LF_M...Y._T.Y_GE15..{freq}?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
        )
        try:
            raw = fetch(url, timeout=120)
        except Exception as exc:
            print(f"  ADVARSEL: ledighet feilet for {areas}: {exc}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(raw)):
            area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
            value = to_float(row.get("OBS_VALUE"))
            if area and period and value is not None:
                series.setdefault(area, {})[period] = value

    try:
        raw = fetch(
            "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m"
            "?format=JSON&geo=EA21&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&lastTimePeriod=3"
        )
        data = json.loads(raw)
        periods = {v: k for k, v in data["dimension"]["time"]["category"]["index"].items()}
        # Lagres under OECD-koden EA20 slik at oppslaget i main() treffer
        series["EA20"] = {periods[int(i)]: v for i, v in data["value"].items()}
    except Exception as exc:
        print(f"  ADVARSEL: Eurostat-ledighet feilet: {exc}", file=sys.stderr)
    return series


# ---------------------------------------------------------------------------
# Rentekurver: hva markedet har priset inn av renteendringer, og hvor langt frem
# ---------------------------------------------------------------------------
#
# Per land hentes en daglig rentekurve (OIS der det finnes, ellers statspapirer)
# med løpetider fra 1 mnd til 10 år. Fra kurven regnes terminrenter, som viser
# hvilken kort rente markedet «forventer» på ulike tidspunkt fremover.
# Terminrenter inneholder også terminpremie, så tallene er en indikasjon på
# prising – ikke sannsynligheter.

CURVE_SOURCES = {
    "us": ("govt", "amerikanske statspapirer (FRED)"),
    "ea": ("govt", "AAA-statskurve eurosonen (ECB)"),
    "jp": ("govt", "japanske statsobligasjoner (MoF)"),
    "gb": ("ois", "OIS-kurve (Bank of England)"),
    "ca": ("govt", "kanadiske statspapirer (Bank of Canada)"),
    "au": ("zero", "nullkupong statskurve (RBA F17, månedlig) forskjøvet med daglige obligasjonsrenter"),
    "se": ("govt", "svenske statspapirer (Riksbanken)"),
    "no": ("zero", "nullkupong statskurve (Norges Bank)"),
    "nz": ("swap", "90-dagers bankveksel + swaprenter (RBNZ B2)"),
    "ch": ("govt", "statskurve (SNB, publisert månedlig) forskjøvet daglig med SARON og 10-års rente"),
}

# Løpetider (år) som lagres i historikken. Nøkkel i JSON = f"{tenor:g}".
CURVE_TENORS = (1 / 12, 0.25, 0.5, 1, 2, 3, 5, 10)

# Løpetider som renses bort per land (punkter fra kilder vi har sluttet å bruke).
CURVE_DROP_TENORS = {"au": {"0.083"}}  # 1-mnd bankveksel fra før F17-kurven (kredittpåslag)


def tenor_key(years):
    return f"{round(years, 3):g}"


def curve_start():
    return date.today() - timedelta(days=400)


def xlsx_sheet_rows(xlsx_bytes, sheet_name):
    """Minimal xlsx-leser med kun standardbiblioteket.

    Returnerer [(radnr, {kolonnebokstav: verdi})] der verdi er float for tall,
    str for delte tekststrenger og None for feil/tomme celler.
    """
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    workbook = z.read("xl/workbook.xml").decode("utf-8")
    rid = None
    for tag in re.findall(r"<sheet [^>]*>", workbook):
        name = re.search(r'name="([^"]*)"', tag)
        ref = re.search(r'r:id="([^"]*)"', tag)
        if name and ref and name.group(1).strip().lower() == sheet_name.lower():
            rid = ref.group(1)
    if not rid:
        raise ValueError(f"fant ikke arket {sheet_name!r}")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    target = None
    for tag in re.findall(r"<Relationship [^>]*>", rels):
        if re.search(rf'Id="{re.escape(rid)}"', tag):
            target = re.search(r'Target="([^"]*)"', tag).group(1)
    sheet_xml = z.read("xl/" + target.lstrip("/").removeprefix("xl/")).decode("utf-8")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8"), re.S):
            shared.append("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)))
    rows = []
    for rownum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sheet_xml, re.S):
        cells = {}
        for col, attrs, inner in re.findall(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', body, re.S):
            v = re.search(r"<v>([^<]*)</v>", inner or "")
            if not v:
                cells[col] = None
            elif 't="s"' in attrs:
                cells[col] = shared[int(v.group(1))]
            elif 't="' in attrs and 't="n"' not in attrs:  # t="e" (feil), t="str" (formeltekst) o.l.
                cells[col] = None
            else:
                cells[col] = to_float(v.group(1))
        rows.append((int(rownum), cells))
    return rows


def excel_date(serial):
    return str(date(1899, 12, 30) + timedelta(days=int(serial)))


def parse_boe_ois(xlsx_bytes, start):
    """Spotrenter fra BoEs OIS-arbeidsbok: 1–60 mnd fra kortende-arket, 10 år fra hele kurven."""
    def grid(sheet, header_label, to_years):
        header, data = None, {}
        for _, cells in xlsx_sheet_rows(xlsx_bytes, sheet):
            a = cells.get("A")
            if isinstance(a, str) and a.strip().lower().startswith(header_label):
                header = {col: to_years(v) for col, v in cells.items() if col != "A" and isinstance(v, float)}
            elif isinstance(a, float) and a > 30000 and header:
                day = excel_date(a)
                if day < start:
                    continue
                for col, v in cells.items():
                    if col in header and isinstance(v, float):
                        data.setdefault(day, {})[header[col]] = v
        return data

    out = {}
    for day, vals in grid("3. spot, short end", "months", lambda m: round(m) / 12).items():
        for years in (1 / 12, 0.25, 0.5, 1, 2, 3, 5):
            for t, v in vals.items():
                if abs(t - years) < 1e-6:
                    out.setdefault(day, {})[tenor_key(years)] = round(v, 4)
    for day, vals in grid("4. spot curve", "years", lambda y: round(y * 2) / 2).items():
        if 10.0 in vals:
            out.setdefault(day, {})[tenor_key(10)] = round(vals[10.0], 4)
    return out


def fetch_curve_gb(existing_days):
    """BoE OIS-kurve. Inneværende måned fra 'latest'-zip; hele arkivet ved første kjøring."""
    start = str(curve_start())
    base = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/"
    urls = [base + "latest-yield-curve-data.zip"]
    if existing_days < 150:
        urls.append(base + "oisddata.zip")
    out = {}
    for url in urls:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (valuta-dashboard)"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            archive = zipfile.ZipFile(io.BytesIO(resp.read()))
        for name in archive.namelist():
            if not name.lower().startswith("ois") or not name.endswith(".xlsx"):
                continue
            if "to present" not in name and "current month" not in name:
                continue
            for day, vals in parse_boe_ois(archive.read(name), start).items():
                out.setdefault(day, {}).update(vals)
    return out


def fetch_curve_us():
    """Amerikanske statsrenter (constant maturity) fra FRED."""
    ids = {"DGS1MO": 1 / 12, "DGS3MO": 0.25, "DGS6MO": 0.5, "DGS1": 1,
           "DGS2": 2, "DGS3": 3, "DGS5": 5, "DGS10": 10}
    out = {}
    for sid, years in ids.items():
        for day, v in fetch_fred_series(sid).items():
            out.setdefault(day, {})[tenor_key(years)] = v
    return out


def fetch_curve_ea():
    """ECBs AAA-statskurve for eurosonen (Svensson-modell), daglig."""
    tenors = {"SR_3M": 0.25, "SR_6M": 0.5, "SR_1Y": 1, "SR_2Y": 2, "SR_3Y": 3, "SR_5Y": 5, "SR_10Y": 10}
    url = (
        "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM."
        + "+".join(tenors) + f"?format=csvdata&detail=dataonly&startPeriod={curve_start()}"
    )
    out = {}
    for row in csv.DictReader(io.StringIO(fetch(url, timeout=120))):
        years = tenors.get(row.get("DATA_TYPE_FM"))
        value = to_float(row.get("OBS_VALUE"))
        if years and value is not None:
            out.setdefault(row["TIME_PERIOD"], {})[tenor_key(years)] = round(value, 4)
    return out


def fetch_curve_jp(existing_days):
    """Japanske statsobligasjonsrenter fra finansdepartementet (MoF)."""
    base = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    urls = [base + "jgbcme.csv"]
    if existing_days < 150:
        urls.append(base + "historical/jgbcme_all.csv")
    start = str(curve_start())
    tenors = {"1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10}
    out = {}
    for url in urls:
        # Filene har en japansk (Shift-JIS) fotnote; ugyldige byte erstattes
        lines = fetch(url, timeout=120, errors="replace").splitlines()
        header_idx = next(i for i, line in enumerate(lines) if line.startswith("Date,"))
        for row in csv.DictReader(io.StringIO("\n".join(lines[header_idx:]))):
            try:
                day = str(datetime.strptime(row["Date"], "%Y/%m/%d").date())
            except (ValueError, KeyError):
                continue
            if day < start:
                continue
            for col, years in tenors.items():
                value = to_float(row.get(col))
                if value is not None:
                    out.setdefault(day, {})[tenor_key(years)] = value
    return out


def fetch_curve_ca():
    """Statskasseveksler og referanseobligasjoner fra Bank of Canada (Valet)."""
    ids = {"V80691342": 1 / 12, "V80691344": 0.25, "V80691345": 0.5, "V80691346": 1,
           "BD.CDN.2YR.DQ.YLD": 2, "BD.CDN.3YR.DQ.YLD": 3, "BD.CDN.5YR.DQ.YLD": 5, "BD.CDN.10YR.DQ.YLD": 10}
    url = f"https://www.bankofcanada.ca/valet/observations/{','.join(ids)}/json?start_date={curve_start()}"
    out = {}
    for obs in json.loads(fetch(url, timeout=120)).get("observations", []):
        for sid, years in ids.items():
            value = to_float((obs.get(sid) or {}).get("v"))
            if value is not None:
                out.setdefault(obs["d"], {})[tenor_key(years)] = value
    return out


def fetch_curve_se():
    """Statsskuldväxlar og statsobligasjoner fra Riksbanken. API-et tillater få kall
    per minutt, derfor pause mellom seriene."""
    ids = {"SETB3MBENCH": 0.25, "SETB6MBENCH": 0.5, "SEGVB2YC": 2, "SEGVB5YC": 5, "SEGVB10YC": 10}
    out = {}
    for i, (sid, years) in enumerate(ids.items()):
        if i:
            time.sleep(16)
        url = f"https://api.riksbank.se/swea/v1/Observations/{sid}/{curve_start()}"
        try:
            raw = fetch(url, timeout=60, attempts=1)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            time.sleep(65)
            raw = fetch(url, timeout=60, attempts=1)
        for obs in json.loads(raw):
            value = to_float(obs.get("value"))
            if value is not None:
                out.setdefault(obs["date"], {})[tenor_key(years)] = value
    return out


def fetch_curve_no():
    """Nullkupongrenter (6 mnd–10 år) og 3-mnd statskasseveksel fra Norges Bank."""
    start = curve_start()
    tenors = {"3M": 0.25, "6M": 0.5, "12M": 1, "2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10}
    out = {}
    for url in (
        f"https://data.norges-bank.no/api/data/GOVT_ZEROCOUPON/B.6M+12M+2Y+3Y+5Y+10Y?startPeriod={start}&format=csv",
        f"https://data.norges-bank.no/api/data/GOVT_GENERIC_RATES/B.3M.TBIL?startPeriod={start}&format=csv",
    ):
        for row in csv.DictReader(io.StringIO(fetch(url, timeout=120)), delimiter=";"):
            years = tenors.get(row.get("TENOR"))
            value = to_float(row.get("OBS_VALUE"))
            if years and value is not None:
                out.setdefault(row["TIME_PERIOD"], {})[tenor_key(years)] = value
    return out


def rba_table(name):
    """RBA-statistikktabell som CSV: (serie-ID → kolonneindeks, datarader [(dag, rad)])."""
    rows = list(csv.reader(io.StringIO(fetch(f"https://www.rba.gov.au/statistics/tables/csv/{name}.csv", timeout=120))))
    ids = next((r for r in rows if r and r[0].strip() == "Series ID"), None)
    if not ids:
        raise RuntimeError(f"fant ikke «Series ID»-raden i {name}")
    columns = {sid.strip(): idx for idx, sid in enumerate(ids) if idx and sid.strip()}
    data = []
    for row in rows:
        try:
            data.append((str(datetime.strptime(row[0].strip(), "%d-%b-%Y").date()), row))
        except (ValueError, IndexError):
            continue
    return columns, data


def rba_series(name, wanted, start):
    """{dag: {løpetid: rente}} for utvalgte serie-ID-er (wanted: {serie-ID: løpetid i år})."""
    columns, data = rba_table(name)
    out = {}
    for day, row in data:
        if day < start:
            continue
        for sid, years in wanted.items():
            idx = columns.get(sid)
            value = to_float(row[idx]) if idx is not None and idx < len(row) else None
            if value is not None:
                out.setdefault(day, {})[tenor_key(years)] = value
    return out


RBA_ZERO_TENORS = {f"FZCY{int(t * 100)}D": t for t in (0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 7, 10)}
RBA_DAILY = {"FIRMMBAB30D": 1 / 12}  # F1: 1-mnd bankveksel (brukes bare til forskyvning av fronten)
RBA_BONDS = {"FCMYGBAG2D": 2, "FCMYGBAG3D": 3, "FCMYGBAG5D": 5, "FCMYGBAG10D": 10}  # F2: statsobligasjoner


def shift_zero_curve(zero, daily, start):
    """Daglig kurve fra RBAs månedlige nullkupongkurve (F17) og daglige markedsrenter.

    F17 publiseres få dager etter månedsslutt, så for dager etter siste F17-dato
    forskyves nullkupongkurven med endringen i de daglige rentene siden den datoen:
    Δ(T) interpoleres lineært i løpetid mellom instrumentene som finnes begge dager
    (1-mnd veksel, 2/3/5/10-års obligasjoner), flatt utenfor. På F17-datoer brukes
    kurven direkte. Den daglige 1-mnd-vekselen lagres ikke (kredittpåslag)."""
    out = {}
    zero_days = sorted(zero)
    for day in sorted(set(daily) | set(zero)):
        if day < start:
            continue
        base_day = max((z for z in zero_days if z <= day), default=None)
        if base_day is None:
            continue
        curve = dict(zero[base_day])
        if day != base_day:
            ref, now = daily.get(base_day, {}), dict(daily.get(day, {}))
            # Et instrument som mangler akkurat denne dagen (f.eks. SARON-fixing før publisering)
            # tas fra siste dag det finnes, inntil en uke tilbake – ellers ville resten av
            # kurven blitt forskjøvet med de andre instrumentenes endring.
            for t in ref:
                if t not in now:
                    recent = [d for d in daily if d < day and t in daily[d] and d >= str(date.fromisoformat(day) - timedelta(days=7))]
                    if recent:
                        now[t] = daily[max(recent)][t]
            deltas = sorted((float(t), now[t] - ref[t]) for t in now if t in ref)
            if not deltas:
                continue

            def delta(T):
                if T <= deltas[0][0]:
                    return deltas[0][1]
                for (t0, d0), (t1, d1) in zip(deltas, deltas[1:]):
                    if T <= t1:
                        return d0 + (d1 - d0) * (T - t0) / (t1 - t0)
                return deltas[-1][1]

            curve = {t: round(v + delta(float(t)), 3) for t, v in curve.items()}
        out[day] = curve
    return out


def fetch_curve_au():
    """RBA F17 (nullkupongkurve, månedlig) forskjøvet daglig med F1 (1-mnd veksel) og F2
    (statsobligasjoner 2–10 år). Gir tette løpetider fra 3 mnd uten kredittpåslag og uten
    interpolasjon fra 1 mnd til 2 år."""
    start = str(curve_start())
    zero = rba_series("f17-yields", RBA_ZERO_TENORS, str(date.fromisoformat(start) - timedelta(days=45)))
    daily = rba_series("f1-data", RBA_DAILY, str(date.fromisoformat(start) - timedelta(days=45)))
    for day, vals in rba_series("f2-data", RBA_BONDS, str(date.fromisoformat(start) - timedelta(days=45))).items():
        daily.setdefault(day, {}).update(vals)
    if not zero:
        raise RuntimeError("ingen nullkupongkurve i F17")
    return shift_zero_curve(zero, daily, start)


RBNZ_B2_URL = "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx"
RBNZ_B2_FILE = Path(__file__).resolve().parent.parent / ".cache" / "rbnz-b2.xlsx"
RBNZ_B2 = {"INM.DB03.NZZV": 0.25, "INM.DS01.NZZC": 1, "INM.DS02.NZZC": 2, "INM.DS03.NZZC": 3, "INM.DS04.NZZC": 4,
           "INM.DS05.NZZC": 5, "INM.DS07.NZZC": 7, "INM.DS10.NZZC": 10}  # 90-dagers veksel + swap (begge BKBM-baserte)


def parse_rbnz_b2(xlsx_bytes, start, wanted=RBNZ_B2):
    """RBNZ tabell B2 (daglige engrosrenter): {dag: {løpetid: rente}} for valgte serie-ID-er.
    Arket «Data» har en rad «Series Id» med kolonnenøkler og datoer som Excel-serienumre."""
    rows = xlsx_sheet_rows(xlsx_bytes, "Data")
    ids = next((cells for _, cells in rows if cells.get("A") == "Series Id"), None)
    if not ids:
        raise RuntimeError("fant ikke «Series Id»-raden i B2")
    columns = {sid: col for col, sid in ids.items() if col != "A"}
    out = {}
    for _, cells in rows:
        serial = cells.get("A")
        if not isinstance(serial, (int, float)):
            continue
        day = excel_date(serial)
        if day < start:
            continue
        for sid, years in wanted.items():
            value = cells.get(columns.get(sid))
            if isinstance(value, (int, float)):
                out.setdefault(day, {})[tenor_key(years)] = value
    return out


def fetch_curve_nz():
    """NZD-kurven leses fra RBNZ B2, lastet ned på forhånd av scripts/fetch_rbnz.py
    (Playwright – rbnz.govt.nz ligger bak Cloudflare og avviser vanlige HTTP-klienter).
    Fila må være fersk (samme kjøring), ellers regnes kilden som feilet og lagret
    kurvehistorikk brukes videre."""
    path = Path(os.environ.get("RBNZ_B2_FILE", RBNZ_B2_FILE))
    if not path.exists():
        raise RuntimeError(f"{path} mangler – kjør scripts/fetch_rbnz.py først")
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > 12:
        raise RuntimeError(f"{path} er {age_hours:.0f} timer gammel")
    out = parse_rbnz_b2(path.read_bytes(), str(curve_start()))
    if not out:
        raise RuntimeError("ingen kurvepunkter i B2")
    return out


SNB_CUBE = "https://data.snb.ch/api/cube/{cube}/data/csv/en?dimSel={sel}&fromDate={start}"
SNB_RATES_XLSX = "https://www.snb.ch/public/rates/interestRates.xlsx"
SNB_ZERO_TENORS = {"1J": 1, "2J": 2, "3J": 3, "5J": 5, "7J": 7, "10J": 10}


def parse_snb_cube(csv_text, tenors):
    """SNB-kube som CSV (semikolon; Date;D0;D1;Value): {dag: {løpetid: rente}} for
    løpetidskodene i `tenors`. Tomme verdier hoppes over."""
    out = {}
    for row in csv.reader(io.StringIO(csv_text), delimiter=";"):
        if len(row) < 3 or not DATE_RE.match(row[0]):
            continue
        code, value = row[-2], to_float(row[-1])
        if code in tenors and value is not None:
            out.setdefault(row[0], {})[tenor_key(tenors[code])] = value
    return out


def parse_snb_rates(xlsx_bytes, start):
    """SNBs «aktuelle renter»-arbeidsbok: daglig SARON (kolonne SARH) og 10-års spotrente
    på eidgenössische obligasjoner (R10). Kolonnene identifiseres fra raden med kodene."""
    rows = xlsx_sheet_rows(xlsx_bytes, "Interest_Rates")
    header = next((cells for _, cells in rows if "SARH" in cells.values() and "R10" in cells.values()), None)
    if not header:
        raise RuntimeError("fant ikke kolonneraden (SARH/R10) i interestRates.xlsx")
    cols = {code: col for col, code in header.items()}
    out = {}
    for _, cells in rows:
        serial = cells.get("A")
        if not isinstance(serial, (int, float)):
            continue
        day = excel_date(serial)
        if day < start:
            continue
        saron, r10 = cells.get(cols["SARH"]), cells.get(cols["R10"])
        if isinstance(saron, (int, float)):
            out.setdefault(day, {})[tenor_key(1 / 365)] = saron
        if isinstance(r10, (int, float)):
            out.setdefault(day, {})["10"] = r10
    return out


def fetch_curve_ch():
    """Sveitsiske spotrenter (Konføderasjonen, 1–10 år) fra SNB-kuben rendeiduebd, som har
    daglige rader men publiseres månedlig. Som for AUD brukes kurven som form og forskyves
    daglig med endringen i SARON (front) og 10-års spotrente fra snb.ch (interestRates.xlsx)."""
    start = str(curve_start())
    early = str(date.fromisoformat(start) - timedelta(days=45))
    zero = parse_snb_cube(fetch(SNB_CUBE.format(cube="rendeiduebd", sel="D0(CHF)", start=early), timeout=120), SNB_ZERO_TENORS)
    if not zero:
        raise RuntimeError("ingen spotrenter i rendeiduebd")
    req = urllib.request.Request(SNB_RATES_XLSX, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        daily = parse_snb_rates(resp.read(), early)
    return shift_zero_curve(zero, daily, start)


BASIS_WINDOW = 250  # handledager i medianen for basis 3 mnd-rente − styringsrente

# ---------------------------------------------------------------------------
# Møtebaserte instrumenter: futures på styringsrenten der de finnes gratis.
# Hver kontrakt normaliseres til en periode [start, slutt] med implisert
# gjennomsnittsrente (100 − pris), så banen kan bygges likt for alle kilder.
# ---------------------------------------------------------------------------
FUTURES_SOURCES = {
    "us": "fed funds-futures per måned (CME via Yahoo)",
    "au": "30-dagers cash rate-futures (ASX)",
    "ca": "CORRA-futures 1 mnd og 3 mnd (Montréal-børsen)",
    "nz": "90-dagers bankvekselfutures (ASX) med OECDs 3-mnd-rente som front",
}
FUTURES_MAX_MONTHS = 24


def month_span(year, month):
    """(første, siste) dag i en kalendermåned som ISO-strenger."""
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return str(first), str(last)


def add_months(d, n):
    y, m = d.year, d.month + n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y, m, min(d.day, 28))


def third_wednesday(year, month):
    """IMM-dato: tredje onsdag i måneden (referanseperiodene for 3-mnd CORRA-futures)."""
    first = date(year, month, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 14)


def previous_business_day(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_futures_us(today=None, max_months=FUTURES_MAX_MONTHS):
    """30-dagers fed funds-futures (ZQ) fra CME via Yahoo, én kontrakt per måned fra
    inneværende måned. Yahoo gir ett års historikk per kontrakt, så basis og reprising
    kan regnes fra dag én. Stopper når to måneder på rad mangler."""
    today = today or date.today()
    out, misses = {}, 0
    for n in range(max_months):
        d = add_months(date(today.year, today.month, 1), n)
        symbol = f"ZQ{BRENT_MONTH_CODES[d.month - 1]}{str(d.year)[2:]}.CBT"
        try:
            series = fetch_yahoo(symbol, decimals=4)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                misses += 1
                if misses >= 2:
                    break
                continue
            raise
        misses = 0
        start, end = month_span(d.year, d.month)
        for day, price in series.items():
            out.setdefault(day, []).append([start, end, round(100 - price, 4)])
        time.sleep(0.3)
    if not out:
        raise RuntimeError("ingen fed funds-kontrakter funnet")
    return out


def parse_asx_ib(payload):
    """ASX 30 Day Interbank Cash Rate Futures (IB): {dag: [[start, slutt, rente], ...]}.
    Kontraktsmåned leses av symbolet (IBV2026 = oktober 2026), datoen er siste oppgjør."""
    out = {}
    for item in payload.get("data", {}).get("items", []):
        m = re.fullmatch(r"IB([FGHJKMNQUVXZ])(\d{4})", item.get("symbol") or "")
        price = to_float(item.get("pricePreviousSettlement"))
        day = item.get("datePreviousSettlement")
        if not m or price is None or not day:
            continue
        month, year = BRENT_MONTH_CODES.index(m.group(1)) + 1, int(m.group(2))
        out.setdefault(day, []).append([*month_span(year, month), round(100 - price, 4)])
    return out


def parse_asx_bb(payload):
    """ASX NZ 90 Day Bank Bill Futures (BB): {dag: [[start, slutt, rente], ...]}. Kontrakten
    gjør opp mot 90-dagers BKBM på utløpsdagen, så perioden er de 90 dagene fra utløp.
    Kontrakter uten siste handel (priceLastTrade tom) er illikvide med stående oppgjørspris
    og hoppes over."""
    out = {}
    for item in payload.get("data", {}).get("items", []):
        m = re.fullmatch(r"BB([FGHJKMNQUVXZ])(\d{4})", item.get("symbol") or "")
        price = to_float(item.get("pricePreviousSettlement"))
        day, expiry = item.get("datePreviousSettlement"), item.get("dateExpiry")
        if not m or price is None or not day or not expiry or item.get("priceLastTrade") is None:
            continue
        end = str(date.fromisoformat(expiry) + timedelta(days=90))
        out.setdefault(day, []).append([expiry, end, round(100 - price, 4)])
    return out


def fetch_futures_nz():
    url = "https://asx.api.markitdigital.com/asx-research/1.0/derivatives/interest-rate/bb/futures?days=1&height=179&width=179"
    out = parse_asx_bb(json.loads(fetch(url, timeout=60)))
    if not out:
        raise RuntimeError("ingen BB-kontrakter i svaret fra ASX")
    return out


def add_monthly_front(futures_series, monthly):
    """Legger en syntetisk front-periode for dagens kalendermåned fra en månedlig 3-mnd-rente
    ({«ÅÅÅÅ-MM»: rente}, f.eks. OECD): nyeste måned til og med dagens måned. Gir
    kvartalskontrakter et nåpunkt og en basis (renten er et månedssnitt som henger litt etter)."""
    months = sorted(m for m in monthly if monthly[m] is not None)
    out = {}
    for day, periods in futures_series.items():
        usable = [m for m in months if m <= day[:7]]
        extra = []
        if usable:
            y, mo = map(int, day[:7].split("-"))
            extra = [[*month_span(y, mo), monthly[usable[-1]]]]
        out[day] = [p for p in periods if not p[0].endswith("-01")] + extra
    return out


def fetch_futures_au():
    url = "https://asx.api.markitdigital.com/asx-research/1.0/derivatives/interest-rate/ib/futures?days=1&height=179&width=179"
    out = parse_asx_ib(json.loads(fetch(url, timeout=60)))
    if not out:
        raise RuntimeError("ingen IB-kontrakter i svaret fra ASX")
    return out


def parse_tmx_rows(html_text):
    """Kontraktsrader (data-row=JSON) fra Montréal-børsens kurstabell."""
    rows = []
    for raw in re.findall(r"data-row='([^']+)'", html_text):
        try:
            rows.append(json.loads(html.unescape(raw)))
        except ValueError:
            continue
    return rows


def corra_periods(rows, day):
    """COA (1 mnd, kalendermåned) og CRA (3 mnd, IMM-onsdag til IMM-onsdag) → perioder."""
    periods = []
    for row in rows:
        m = re.fullmatch(r"(COA|CRA)([FGHJKMNQUVXZ])(\d{2})", row.get("symbol") or "")
        price = to_float(row.get("settlement_price"))
        if not m or not price:
            continue
        kind, month, year = m.group(1), BRENT_MONTH_CODES.index(m.group(2)) + 1, 2000 + int(m.group(3))
        if kind == "COA":
            start, end = month_span(year, month)
        else:
            start = str(third_wednesday(year, month))
            end = row.get("expiry_date") or str(third_wednesday(year + (month + 2) // 12, (month + 2) % 12 + 1))
        periods.append([start, end, round(100 - price, 4)])
    return {day: periods} if periods else {}


def fetch_futures_ca():
    """Sist oppgjør for CORRA-futures fra m-x.ca (forsinkede kurser). Oppgjøret gjelder
    forrige virkedag."""
    rows = []
    for root in ("COA", "CRA"):
        page = fetch(f"https://www.m-x.ca/en/trading/data/quotes?symbol={root}*", timeout=60)
        rows += parse_tmx_rows(page)
        time.sleep(1)
    out = corra_periods(rows, str(previous_business_day(date.today())))
    if not out:
        raise RuntimeError("ingen CORRA-kontrakter funnet på m-x.ca")
    return out


def _mid(period):
    a, b = date.fromisoformat(period[0]).toordinal(), date.fromisoformat(period[1]).toordinal()
    return (a + b) / 2


def futures_rate_at(periods, day):
    """Implisert rente på en dato: kontrakten som dekker dagen, ellers lineært mellom
    nærmeste periodemidtpunkter (flat utenfor). None uten perioder."""
    if not periods:
        return None
    iso = str(day)
    covering = [p for p in periods if p[0] <= iso <= p[1]]
    if covering:
        # Overlapp (1 mnd inne i et 3-mnd-vindu): korteste periode er mest presis
        return _shortest(covering)[2]
    pts = sorted((_mid(p), p[2]) for p in periods)
    x = day.toordinal()
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, r0), (x1, r1) in zip(pts, pts[1:]):
        if x <= x1:
            return r0 + (r1 - r0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


FUTURES_BASIS_WINDOW = 20  # dager i medianen for basis kontrakt − styringsrente (teknisk påslag, ikke terminpremie)


def _shortest(periods):
    return min(periods, key=lambda p: date.fromisoformat(p[1]).toordinal() - date.fromisoformat(p[0]).toordinal())


def current_month_contract(periods, day):
    """Kalendermånedskontrakten som dekker dagen (1-mnd-kontrakter starter den 1.)."""
    iso = str(day)
    cur = [p for p in periods if p[0] <= iso <= p[1] and p[0].endswith("-01")]
    return _shortest(cur) if cur else None


def month_policy_average(policy_series, period, as_of):
    """Gjennomsnittlig styringsrente over kontraktsperioden, slik den er kjent per as_of
    (dager etter as_of får siste kjente rente). Kontrakten er et snitt av den faktiske
    over-natten-renten, så dette er riktig sammenligningsgrunnlag også i måneder med vedtak."""
    start, end = date.fromisoformat(period[0]), date.fromisoformat(period[1])
    as_of = min(date.fromisoformat(as_of), end)
    values = []
    for n in range((end - start).days + 1):
        v = value_at_or_before(policy_series, str(min(start + timedelta(days=n), as_of)))
        if v is None:
            return None
        values.append(v)
    return sum(values) / len(values)


def futures_basis(series, policy_series, day, window=FUTURES_BASIS_WINDOW):
    """Median over siste `window` dager av (inneværende måneds kontrakt − månedens
    gjennomsnittlige styringsrente). Måler det tekniske påslaget mellom over-natten-renten
    kontrakten gjør opp mot og styringsrenten (EFFR mot midtpunktet, CORRA mot målet).
    Kort vindu, siden påslaget flytter seg med likviditeten, ikke med rentesyklusen.
    Månedssnittet regnes med alt som er kjent per `day`, så dagene før et vedtak måles
    mot renten som faktisk kom (kontrakten hadde den priset), ikke mot den gamle."""
    if not policy_series:
        return None
    values = []
    for d in sorted((d for d in series if d <= day), reverse=True):
        cur = current_month_contract(series[d], d)
        avg = month_policy_average(policy_series, cur, day) if cur else None
        if avg is not None:
            values.append(cur[2] - avg)
        if len(values) >= window:
            break
    return statistics.median(values) if values else None


def futures_metrics(periods, policy, basis, today, govt_path=None, policy_series=None):
    """Bane fra futures: path[m] = implisert rente midt i måned m − basis. Inneværende
    måned renses for vedtak tidligere i måneden (kontrakten er et snitt av gammel og ny
    rente). Utover siste kontrakt skjøtes statskurvens bane på (samme form, forskjøvet)."""
    if not periods or policy is None:
        return None
    cur = current_month_contract(periods, today)
    front = futures_rate_at(periods, today)
    if cur and policy_series:
        avg = month_policy_average(policy_series, cur, str(today))
        if avg is not None:
            front = cur[2] - avg + policy  # nivået etter månedens vedtak
    if basis is None:
        basis = front - policy
    last_end = max(date.fromisoformat(p[1]) for p in periods)
    path, horizon = [], None
    for m in range(FUTURES_MAX_MONTHS + 1):
        target = add_months(date(today.year, today.month, 15), m)
        if m == 0:
            path.append(round(front - basis, 3))
            horizon = 0
        elif target <= last_end:
            path.append(round(futures_rate_at(periods, target) - basis, 3))
            horizon = m
        elif govt_path and len(govt_path) > m:
            path.append(round(path[horizon] + govt_path[m] - govt_path[horizon], 3))
        else:
            path.append(path[-1])
    implied = {f"{m}m": round((path[m] - policy) * 100) for m in (3, 6, 12, 24)}
    extreme_m = max(range(1, len(path)), key=lambda m: abs(path[m] - path[0]))
    return {
        "implied": implied,
        "path": path,
        "extreme": {"months": extreme_m, "level": path[extreme_m], "bp": round((path[extreme_m] - path[0]) * 100)},
        "anchor": {"rate_front": round(front, 3), "basis": round(basis, 3), "kind": "futures"},
        "synthetic_anchor": False,
        "horizon_months": horizon,
    }


def meeting_implied_futures(periods, meeting, meetings, policy, basis, today=None, min_days=5):
    """Priset endring (bp) på ett møte fra månedskontrakter. Renten før møtet er
    styringsrente + basis. Etter møtet: kontrakten for måneden etter hvis den er
    uten møte, ellers løses møtemåneden: F = (k·før + (N−k)·etter)/N, der k er dager
    t.o.m. møtedagen. None hvis oppløsningen ikke holder (for få dager, 3-mnd-kontrakt)."""
    if not periods or policy is None or basis is None:
        return None
    today = today or date.today()
    d = date.fromisoformat(meeting)
    if d < today:
        return None
    before = policy + basis
    others = {m for m in meetings if m != meeting and m >= str(today)}

    def month_contract(y, mo):
        start, end = month_span(y, mo)
        return next((p for p in periods if p[0] == start and p[1] == end), None)

    ny, nm = (d.year + (d.month == 12), d.month % 12 + 1)
    nxt = month_contract(ny, nm)
    after = None
    if nxt and not any(nxt[0] <= m <= nxt[1] for m in others):
        after = nxt[2]
    else:
        cur = month_contract(d.year, d.month)
        if cur and not any(cur[0] <= m <= cur[1] for m in others):
            n_days = (date.fromisoformat(cur[1]) - date.fromisoformat(cur[0])).days + 1
            k = d.day
            if n_days - k >= min_days:
                after = (n_days * cur[2] - k * before) / (n_days - k)
    if after is None:
        return None
    bp = round((after - before) * 100)
    return {"bp": bp, "move": "heving" if bp >= 13 else "kutt" if bp <= -13 else "uendret"}




def curve_points(points, policy):
    """Sorterte (løpetid, rente)-punkter, med syntetisk 3-mnd-punkt lik styringsrenten
    når kurven mangler alt under 6 mnd (statsobligasjonskurver som starter på 1–2 år)."""
    pts = sorted((float(t), v) for t, v in points.items() if v is not None)
    synthetic = bool(pts) and pts[0][0] > 0.5
    if synthetic and policy is not None:
        pts.insert(0, (0.25, policy))
    return pts, synthetic


def spot_rate(pts, T):
    """Spotrente ved løpetid T, lineært interpolert mellom punktene (flat utenfor)."""
    if T <= pts[0][0]:
        return pts[0][1]
    for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
        if T <= t1:
            return r0 + (r1 - r0) * (T - t0) / (t1 - t0)
    return pts[-1][1]


def front_rate(points, policy):
    """3-mnd spotrenten fra kurven (markedets frontrente), None hvis kurven er ubrukelig."""
    pts, _ = curve_points(points, policy)
    return spot_rate(pts, 0.25) if pts else None


def curve_basis(series, policy_series, day, window=BASIS_WINDOW):
    """Basis s = median over siste `window` kurvedager t.o.m. `day` av
    (3-mnd-rente − styringsrente). Fanger terminpremie/kredittpåslag i instrumentet
    uten å følge dagens vedtak. None hvis ingen dager kan regnes."""
    values = []
    for d in sorted((d for d in series if d <= day), reverse=True):
        policy = value_at_or_before(policy_series, d) if policy_series else None
        front = front_rate(series[d], policy) if policy is not None else None
        if front is not None:
            values.append(front - policy)
        if len(values) >= window:
            break
    return statistics.median(values) if values else None


def curve_metrics(points, policy, basis=None):
    """Implisert bane for den korte renten fra en spotkurve.

    points: {tenor_år: rente %}. Spotrenten interpoleres lineært mellom kjente
    løpetider (flat utenfor). 3-mnd terminrenten ved horisont h (år) er
    f(h) = (r(h+0,25)·(h+0,25) − r(h)·h) / 0,25, dvs. den korte renten markedet
    priser for perioden som starter om h. Banen ankres på markedets frontrente:
    path[m] = f(m/12) − s, der s (basis) er medianen av 3-mnd-rente − styringsrente
    over det siste året (curve_basis). Da flytter nivået seg bare når markedet
    flytter seg, ikke når styringsrenteserien oppdateres etter et vedtak. Uten
    historikk (basis=None) brukes dagens avvik, dvs. path[0] = styringsrenten.
    Priset endring (implied) = path[m] − styringsrenten, så et fullt priset vedtak
    innenfor 3-måneders-vinduet telles med. Mangler kurven punkter under 6 mnd,
    settes 3-mnd-renten lik styringsrenten (synthetic_anchor).
    """
    pts, synthetic = curve_points(points, policy)
    # Krever minst tre ekte punkter, ett på 2 år eller lenger, og et korteste punkt på høyst 2 år
    raw = pts[1:] if synthetic else pts
    if policy is None or len(raw) < 3 or raw[-1][0] < 2 or raw[0][0] > 2:
        return None

    def fwd(h):
        return (spot_rate(pts, h + 0.25) * (h + 0.25) - spot_rate(pts, h) * h) / 0.25

    front = fwd(0)  # = 3-mnd spotrenten
    if basis is None:
        basis = front - policy
    path = [round(fwd(m / 12) - basis, 3) for m in range(25)]
    implied = {f"{m}m": round((path[m] - policy) * 100) for m in (3, 6, 12, 24)}
    extreme_m = max(range(1, 25), key=lambda m: abs(path[m] - path[0]))
    return {
        "implied": implied,
        "path": path,
        "extreme": {"months": extreme_m, "level": path[extreme_m],
                    "bp": round((path[extreme_m] - path[0]) * 100)},
        "anchor": {"rate_3m": round(front, 3), "basis": round(basis, 3),
                   "kind": "syntetisk" if synthetic else "marked"},
        "synthetic_anchor": synthetic,
    }


def meeting_implied_curve(points, policy, basis, meetings, today=None, window=90, max_days=80):
    """Priset endring (bp) på neste møte lest ut av 1 mnd- og 3 mnd-renten i en spotkurve.

    3-mnd-renten er snittet av styringsrenten de neste 90 dagene pluss basis (s): med ett
    møte om n dager er (r_3m − s − p) = Δ·(90 − n)/90, altså Δ = (r_3m − s − p)·90/(90 − n).
    Finnes et 1-mnd-punkt og ingen møte de første 30 dagene, gir det basisen direkte
    (r_1m − p); ligger møtet innenfor 1 mnd, gir 1-mnd-renten Δ for det, og 3-mnd-renten
    resten til møte 2. To møter i 3-mnd-vinduet uten 1-mnd-punkt deles likt. Møter
    nærmere vinduets slutt enn `max_days` gir for få dager å måle på → None."""
    if not points or policy is None:
        return None
    today = today or date.today()
    pts, synthetic = curve_points(points, policy)
    if not pts or synthetic:
        return None  # syntetisk anker: 3-mnd-renten er satt lik styringsrenten, ingen informasjon
    r3 = spot_rate(pts, 0.25)
    r1 = points.get(tenor_key(1 / 12))
    upcoming = sorted(m for m in meetings if m >= str(today))
    inside = [(m, (date.fromisoformat(m) - today).days + 1) for m in upcoming]
    inside = [(m, n) for m, n in inside if n <= window]
    if not inside:
        return None
    (m1, n1), rest = inside[0], inside[1:]
    if n1 > max_days:
        return None
    s = basis
    if r1 is not None and n1 > 30:
        s = r1 - policy  # ingen møte i 1-mnd-vinduet: 1-mnd-renten er ren basis
    if s is None:
        return None
    x3 = r3 - s - policy
    if r1 is not None and n1 <= 25:
        delta1 = (r1 - s - policy) * 30 / (30 - n1)
    elif rest and rest[0][1] <= max_days:
        n2 = rest[0][1]
        delta1 = x3 * window / ((window - n1) + (window - n2))  # likt fordelt på to møter
    else:
        delta1 = x3 * window / (window - n1)
    bp = round(delta1 * 100)
    return {"bp": bp, "move": "heving" if bp >= 13 else "kutt" if bp <= -13 else "uendret",
            "source": f"rentekurven ({'1 og 3' if r1 is not None else '3'} mnd), fordelt på møtet"}


def curve_at(series, target_day):
    """Kurvepunktene på eller like før en dato."""
    days = [d for d in series if d <= target_day]
    return series[max(days)] if days else None


def build_curve(cid, series, policy_series, futures_series=None):
    """Lager dashboard-objektet for et lands rentekurve, inkl. reprising siste uke/måned.
    Finnes futures på styringsrenten (futures_series), overstyrer de banen og prisingen;
    statskurven beholdes for punktene (3 mnd, 10 år, terminkurs) og for skjøten utover
    siste kontrakt."""
    series = series or {}
    policy_day, policy = latest(policy_series)
    # Kilder med flere delserier kan mangle de korte punktene på siste dag;
    # bruk nyeste dag (inntil en uke tilbake) der kurven er komplett nok.
    day, metrics, basis = None, None, None
    for candidate in sorted(series, reverse=True)[:7]:
        if curve_metrics(series[candidate], policy):
            day = candidate
            break
    if day:
        # Samme basis for dagens og tidligere baner, så reprising er rent forventningsskift
        basis = curve_basis(series, policy_series, day)
        metrics = curve_metrics(series[day], policy, basis)
    elif not futures_series or policy is None:
        return None
    else:
        day = str(date.today())  # bare futures: «kurvedato» settes av futures-dagen under
    kind, source = CURVE_SOURCES.get(cid, ("futures", "futures"))
    repricing, y2_change, path_w1 = {}, {}, None
    for label, days in (("w1", 7), ("m1", 30)) if metrics else ():
        past_day = str(date.fromisoformat(day) - timedelta(days=days))
        past = curve_at(series, past_day)
        if not past:
            continue
        past_policy = value_at_or_before(policy_series, past_day) if policy_series else policy
        past_metrics = curve_metrics(past, past_policy if past_policy is not None else policy, basis)
        if past_metrics:
            # Nivåbasert med felles basis: renten markedet priser om 12 mnd nå minus det samme
            # for en uke/måned siden – uavhengig av om styringsrenten ble endret i mellomtiden.
            repricing[label] = round((metrics["path"][12] - past_metrics["path"][12]) * 100)
            if label == "w1":
                path_w1 = past_metrics["path"]
        if series[day].get("2") is not None and past.get("2") is not None:
            y2_change[label] = round((series[day]["2"] - past["2"]) * 100)
    out = {
        "date": day,
        "kind": kind,
        "source": source,
        "points": {k: round(v, 3) for k, v in sorted(series[day].items(), key=lambda kv: float(kv[0]))} if metrics else {},
        "repricing": repricing,
        "y2_change": y2_change,
        "path_w1": path_w1,
        **(metrics or {}),
    }
    fut_day = max((d for d in (futures_series or {}) if d >= str(date.fromisoformat(day) - timedelta(days=7))), default=None)
    if not fut_day and not metrics:
        return None
    if fut_day:
        fut_basis = futures_basis(futures_series, policy_series, fut_day)
        fut = futures_metrics(futures_series[fut_day], policy, fut_basis, date.fromisoformat(fut_day), metrics["path"] if metrics else None, policy_series)
        if fut:
            fut_rep, fut_w1 = {}, None
            for label, days in (("w1", 7), ("m1", 30)):
                past_day = str(date.fromisoformat(fut_day) - timedelta(days=days))
                past_key = max((d for d in futures_series if d <= past_day), default=None)
                if not past_key:
                    continue  # snapshot-kilder uten historikk ennå: ingen reprising før den bygges opp
                past_govt = curve_at(series, past_day) if series else None
                past_govt_metrics = curve_metrics(past_govt, policy, basis) if past_govt else None
                past_fut = futures_metrics(futures_series[past_key], value_at_or_before(policy_series, past_key) or policy, fut["anchor"]["basis"],
                                           date.fromisoformat(past_key), past_govt_metrics["path"] if past_govt_metrics else None, policy_series)
                if past_fut:
                    fut_rep[label] = round((fut["path"][12] - past_fut["path"][12]) * 100)
                    if label == "w1":
                        fut_w1 = past_fut["path"]
            horizon = fut.pop("horizon_months")
            splice = (f" + {source} etter {horizon} mnd" if metrics else f", flat etter {horizon} mnd") if horizon is not None and horizon < FUTURES_MAX_MONTHS else ""
            out.update({
                "kind": "futures",
                "date": fut_day if not metrics else day,
                "source": FUTURES_SOURCES.get(cid, "futures") + splice,
                "govt_source": source if metrics else None,
                "futures_date": fut_day,
                "futures": futures_series[fut_day],
                "repricing": fut_rep,
                "path_w1": fut_w1,
                **fut,
            })
    return out


def rate_at_tenor(points, years):
    """Spotrente ved en løpetid, lineært interpolert mellom nærmeste punkter."""
    pts = sorted((float(t), v) for t, v in (points or {}).items() if v is not None)
    if not pts:
        return None
    if years <= pts[0][0]:
        return pts[0][1]
    for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
        if years <= t1:
            return r0 + (r1 - r0) * (years - t0) / (t1 - t0)
    return pts[-1][1]


def realized_vol(series, window=30):
    """Annualisert realisert volatilitet (%) fra daglige logavkastninger."""
    values = [v for _, v in sorted(series.items())][-(window + 1):]
    if len(values) < window // 2:
        return None
    returns = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 1)


def correlation(series_a, series_b, window=90):
    """Pearson-korrelasjon mellom daglige avkastninger på felles datoer."""
    common = sorted(set(series_a) & set(series_b))[-(window + 1):]
    if len(common) < 20:
        return None
    ra = [series_a[b] / series_a[a] - 1 for a, b in zip(common, common[1:])]
    rb = [series_b[b] / series_b[a] - 1 for a, b in zip(common, common[1:])]
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    var_a = sum((x - ma) ** 2 for x in ra)
    var_b = sum((y - mb) ** 2 for y in rb)
    if var_a == 0 or var_b == 0:
        return None
    return round(cov / math.sqrt(var_a * var_b), 2)


def latest(series):
    """(periode, verdi) for siste observasjon i en {periode: verdi}-dict."""
    if not series:
        return None, None
    period = max(series)
    return period, series[period]


def value_at_or_before(series, target_day):
    """Siste verdi på eller før en gitt dato (håndterer helger/helligdager)."""
    candidates = [d for d in series if d <= target_day]
    return series[max(candidates)] if candidates else None


def pct_change(series, days):
    day, value = latest(series)
    if not day:
        return None
    past = value_at_or_before(series, str(date.fromisoformat(day) - timedelta(days=days)))
    if not past:
        return None
    return round((value / past - 1) * 100, 2)


DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")  # ÅÅÅÅ, ÅÅÅÅ-MM eller ÅÅÅÅ-MM-DD


def newest_date(obj):
    """Nyeste periode (YYYY, YYYY-MM eller YYYY-MM-DD) som forekommer som nøkkel eller som
    første element i et par (World Bank-PPP lagres som {iso: (år, verdi)}). Lister som
    begynner med en dato er kontraktsperioder [start, slutt, rente] og teller ikke –
    de peker fremover i tid, observasjonsdagen er nøkkelen."""
    best = None
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and DATE_RE.match(k) and (best is None or k > best):
                    best = k
                stack.append(v)
        elif isinstance(cur, (list, tuple)):
            if cur and isinstance(cur[0], str) and DATE_RE.match(cur[0]):
                if len(cur) == 2 and (best is None or cur[0] > best):
                    best = cur[0]
                continue
            stack.extend(cur)
    return best


def run_parallel(jobs, workers=8):
    """Kjører {navn: funksjon} parallelt. Returnerer (resultater, status) der status
    per kilde er {"ok": bool, "error": str|None, "latest": nyeste dato i dataene}."""
    results, status = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
                status[name] = {"ok": True, "error": None, "latest": newest_date(results[name])}
                print(f"  {name}: ok (nyeste {status[name]['latest']})")
            except Exception as exc:
                results[name] = None
                status[name] = {"ok": False, "error": str(exc)[:200], "latest": None}
                print(f"  ADVARSEL: {name} feilet ({exc}) – beholder forrige data", file=sys.stderr)
    return results, status


def load_existing(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    DATA_DIR.mkdir(exist_ok=True)
    dashboard_path = DATA_DIR / "dashboard.json"
    history_path = DATA_DIR / "history.json"
    old_dashboard = {c["id"]: c for c in load_existing(dashboard_path).get("countries", [])}
    old_history = load_existing(history_path)

    curves_path = DATA_DIR / "curves.json"
    old_curves = load_existing(curves_path).get("curve") or old_history.get("curve", {})
    old_futures = load_existing(curves_path).get("futures") or {}
    old_status = load_existing(dashboard_path).get("sources", {})

    # Alle kilder hentes parallelt; én treg eller nede tjeneste koster bare sin egen timeout.
    # BoE og MoF gir bare inneværende måned per fil, så kurvehistorikken bygges opp
    # over tid og backfylles fra arkivfiler første gang.
    print("Henter kilder parallelt ...")
    jobs = {
        "fx": fetch_fx_history,
        "i44": fetch_i44_history,
        "policy": fetch_policy_rates,
        "irlt": lambda: fetch_oecd_rates("IRLT"),
        "ir3": lambda: fetch_oecd_rates("IR3TIB"),
        "cpi": fetch_cpi,
        "unemployment": fetch_unemployment,
        "brent": lambda: fetch_fred_series("DCOILBRENTEU"),
        "brent_fut": fetch_brent_futures,
        "ttf": lambda: fetch_yahoo("TTF=F"),
        "cpi_core": fetch_cpi_core,
        "ons_cpi": fetch_ons_cpi,
        "ssb_kpi_jae": fetch_ssb_kpi_jae,
        "scb_kpif": fetch_scb_kpif,
        "pce_core": fetch_pce_core,
        "abs_trimmed": fetch_abs_trimmed_mean,
        "boc_core": fetch_boc_core,
        "vix": lambda: fetch_fred_series("VIXCLS"),
        "cot": fetch_cot,
        "ppp": fetch_ppp,
        "curve_us": fetch_curve_us,
        "curve_ea": fetch_curve_ea,
        "curve_jp": lambda: fetch_curve_jp(len(old_curves.get("JPY", {}))),
        "curve_gb": lambda: fetch_curve_gb(len(old_curves.get("GBP", {}))),
        "curve_ca": fetch_curve_ca,
        "curve_au": fetch_curve_au,
        "curve_se": fetch_curve_se,
        "curve_no": fetch_curve_no,
        "curve_ch": fetch_curve_ch,
        "futures_us": fetch_futures_us,
        "futures_au": fetch_futures_au,
        "futures_ca": fetch_futures_ca,
        "futures_nz": fetch_futures_nz,
        **{f"policy_{cid}": fn for cid, fn in POLICY_FETCHERS.items()},
        **{f"cb_path_{cid}": fn for cid, fn in CB_PATH_FETCHERS.items()},
    }
    # RBNZ ligger bak Cloudflare, som også blokkerer GitHub-runnere; B2-kurven hentes bare
    # når scripts/fetch_rbnz.py har lagt fila klar (f.eks. lokalt)
    if Path(os.environ.get("RBNZ_B2_FILE", RBNZ_B2_FILE)).exists():
        jobs["curve_nz"] = fetch_curve_nz
    results, status = run_parallel(jobs)
    sources = {k: v for k, v in results.items() if not k.startswith(("curve_", "futures_", "policy_", "cb_path_"))}
    official_policy = {k[7:]: v for k, v in results.items() if k.startswith("policy_")}
    auto_cb_paths = {k[8:]: v for k, v in results.items() if k.startswith("cb_path_")}
    for cid, auto in auto_cb_paths.items():  # banen peker fremover; kildens dato er rapportdatoen
        if auto and auto.get("as_of") and status.get(f"cb_path_{cid}", {}).get("ok"):
            status[f"cb_path_{cid}"]["latest"] = auto["as_of"]
    curves = {k[6:]: v for k, v in results.items() if k.startswith("curve_")}
    futures = {k[8:]: v for k, v in results.items() if k.startswith("futures_")}

    # Kildestatus: ved feil beholdes forrige vellykkede dato, så alder kan overvåkes
    today_iso = str(date.today())
    for name, st in status.items():
        prev = old_status.get(name, {})
        if st["ok"]:
            st["fetched"] = today_iso
        else:
            st["latest"] = prev.get("latest")
            st["fetched"] = prev.get("fetched")

    meetings = load_existing(DATA_DIR / "meetings.json")
    overrides = {k: v for k, v in load_existing(DATA_DIR / "policy_overrides.json").items() if not k.startswith("_")}
    cb_paths = {k: v for k, v in load_existing(DATA_DIR / "cb_paths.json").items() if not k.startswith("_")}
    meeting_odds = {k: v for k, v in load_existing(DATA_DIR / "meeting_odds.json").items() if not k.startswith("_")}
    today = str(date.today())

    # Britisk KPI fra ONS overstyrer OECD når ONS er nyere
    if sources.get("ons_cpi") and sources.get("cpi") is not None:
        sources["cpi"].setdefault("GBR", {}).update(sources["ons_cpi"])

    # USD-kryss trengs for PPP-verdivurdering (lokal valuta per USD)
    usd_nok = (sources["fx"] or {}).get("USD") or old_history.get("fx", {}).get("USD", {})
    _, usd_nok_last = latest(usd_nok)

    countries = []
    history = {"fx": {}, "policy": {}, "cot": {}, "market": {}}
    curve_history, futures_history = {}, {}
    for c in COUNTRIES:
        cur, per = c["currency"], c.get("per", 1)
        old = old_dashboard.get(c["id"], {})

        # Valutakurs: NOK-verdi per enhet (Norge bruker I-44-indeksen)
        if cur == "NOK":
            fx_series = sources["i44"] or old_history.get("fx", {}).get("I44", {})
            fx_key, invert = "I44", True
        else:
            fx_series = (sources["fx"] or {}).get(cur) or old_history.get("fx", {}).get(cur, {})
            fx_key, invert = cur, False
        fx_day, fx_value = latest(fx_series)
        fx = old.get("fx")
        if fx_day:
            fx = {
                "value": round(fx_value * per, 4),
                "per": per,
                "date": fx_day,
                "index": invert,  # I-44: lavere indeks = sterkere valuta
                "changes": {
                    "d1": pct_change(fx_series, 1),
                    "w1": pct_change(fx_series, 7),
                    "m1": pct_change(fx_series, 30),
                    "m3": pct_change(fx_series, 91),
                    "y1": pct_change(fx_series, 365),
                },
            }
        history["fx"][fx_key] = fx_series

        # Renter
        policy_series = dict((sources["policy"] or {}).get(c["bis"]) or old_history.get("policy", {}).get(c["bis"], {}))
        policy_source = "BIS"
        # Sentralbankens egen serie overstyrer BIS der den finnes (BIS henger etter vedtak)
        official = official_policy.get(c["id"])
        if official:
            policy_series = merge_policy(policy_series, official)
            policy_source = POLICY_SOURCE_LABELS.get(c["id"], "sentralbanken")
        # Manuelt registrert vedtak (annonseringsdato) bruker vi til seriene har fått det med seg
        ov = overrides.get(c["id"])
        policy_series, ov_status = apply_policy_override(policy_series, ov, today)
        if ov_status == "brukt":
            policy_source = "vedtak (manuelt registrert)"
        elif ov_status == "avvik":
            print(f"  ADVARSEL: policy_overrides.json for {c['id']} ({ov['rate']} fra {ov['date']}) avviker fra "
                  f"{policy_source}-serien, som brukes", file=sys.stderr)
        policy_day, policy = latest(policy_series)
        # Kalendervakt: et møte er passert uten at serien dekker det – tallet kan være utdatert
        unconfirmed = unconfirmed_meeting(meetings.get(c["id"], []), policy_day, today)
        if unconfirmed:
            policy_source += f" – ubekreftet etter møtet {unconfirmed}"
        key = f"policy_{c['id']}"
        if key in status:
            if unconfirmed:
                status[key]["warn"] = f"ubekreftet etter møtet {unconfirmed}"
        elif official is None and c["id"] in ("jp", "nz"):
            status[key] = {"ok": policy_day is not None, "error": None, "latest": policy_day, "fetched": today_iso,
                           "warn": f"ubekreftet etter møtet {unconfirmed}" if unconfirmed else None}
        history["policy"][c["bis"]] = policy_series
        # Nylig renteendring (siste 30 dager): dato, fra, til
        policy_change = None
        if policy_series and policy_day:
            past_day = str(date.fromisoformat(policy_day) - timedelta(days=30))
            past_val = value_at_or_before(policy_series, past_day)
            if past_val is not None and abs(past_val - policy) > 1e-9:
                change_day = min(d for d in policy_series if d > past_day and abs(policy_series[d] - past_val) > 1e-9)
                # BIS fører virkningsdato; bruk annonseringsdatoen (siste møte inntil 7 dager før)
                announced = [d for d in meetings.get(c["id"], [])
                             if d <= change_day and d >= str(date.fromisoformat(change_day) - timedelta(days=7))]
                if ov and ov.get("date") and ov["date"] == change_day:
                    announced = [ov["date"]]  # manuelt registrert vedtak: datoen er annonseringsdatoen
                policy_change = {"date": max(announced) if announced else change_day, "from": past_val, "to": policy}
        _, y10 = latest((sources["irlt"] or {}).get(c["oecd"], {}))
        _, m3 = latest((sources["ir3"] or {}).get(c["oecd"], {}))
        old_rates = old.get("rates", {})
        rates = {
            "policy": policy if policy is not None else old_rates.get("policy"),
            "policy_date": policy_day or old_rates.get("policy_date"),
            "policy_source": policy_source,
            "policy_unconfirmed": unconfirmed,
            "m3": m3 if m3 is not None else old_rates.get("m3"),
            "y10": y10 if y10 is not None else old_rates.get("y10"),
            "m3_source": "OECD (månedssnitt)",
            "y10_source": "OECD (månedssnitt)",
        }

        # Endring i styringsrente siste 6 mnd (til retningsindikatoren)
        if policy_series and policy_day:
            past = value_at_or_before(policy_series, str(date.fromisoformat(policy_day) - timedelta(days=182)))
            rates["policy_6m_change"] = round(policy - past, 3) if past is not None else None

        # Inflasjon
        cpi_period, cpi_value = latest((sources["cpi"] or {}).get(c["oecd"], {}))
        cpi = {"value": cpi_value, "period": cpi_period} if cpi_period else old.get("cpi")

        core_period, core_value = latest((sources["cpi_core"] or {}).get(c["oecd"], {}))
        core_label = "HICP uten energi og mat (Eurostat)" if c["id"] == "ea" else CORE_NOTES.get(c["id"], "KPI uten mat og energi (OECD)")
        is_target = False  # ECB, BoE, SNB, BoJ og RBNZ styrer etter samlet KPI/HICP; kjernen er visning
        # Sentralbankens egen målvariabel der den finnes (kjerne-PCE, trimmet gjennomsnitt, CPI-trim/median, KPI-JAE, KPIF)
        target = CORE_TARGETS.get(c["id"])
        if target and sources.get(target[0]):
            core_period, core_value = latest(sources[target[0]])
            core_label, is_target = target[1], True
        elif target:
            core_label += " – målvariabelen kunne ikke hentes"
        cpi_core = ({"value": core_value, "period": core_period, "label": core_label, "is_target": is_target}
                    if core_period else old.get("cpi_core"))

        # Arbeidsledighet
        une_period, une_value = latest((sources["unemployment"] or {}).get(c["oecd"], {}))
        unemployment = {"value": une_value, "period": une_period} if une_period else old.get("unemployment")

        # PPP-verdivurdering: + = valutaen er dyr mot USD ift. kjøpekraft, − = billig
        ppp = old.get("ppp")
        ppp_entry = (sources["ppp"] or {}).get(PPP_ISO[c["id"]])
        if ppp_entry and usd_nok_last and (fx or cur == "NOK"):
            year, ppp_rate = ppp_entry
            if cur == "NOK":
                market_vs_usd = usd_nok_last
            else:
                cur_nok = fx["value"] / per if fx else None
                market_vs_usd = usd_nok_last / cur_nok if cur_nok else None
            if market_vs_usd:
                ppp = {
                    "rate": ppp_rate,
                    "year": year,
                    "valuation": None if cur == "USD" else round((ppp_rate / market_vs_usd - 1) * 100, 1),
                    "proxy": "Tyskland" if c["id"] == "ea" else None,
                }

        # COT: netto spekulativ posisjonering (ukentlig)
        cot = old.get("cot")
        contract = COT_CONTRACTS.get(c["id"])
        cot_series = (sources["cot"] or {}).get(contract) if contract else None
        if not cot_series and contract:
            cot_series = old_history.get("cot", {}).get(cur)
        if cot_series:
            days = sorted(cot_series)
            last, prev = cot_series[days[-1]], cot_series[days[-2]] if len(days) > 1 else None
            cot = {
                "net": last["net"],
                "change_w": last["net"] - prev["net"] if prev else None,
                "pct_oi": round(last["net"] / last["oi"] * 100, 1) if last.get("oi") else None,
                "date": days[-1],
                **cot_flags(cot_series),
            }
            history["cot"][cur] = cot_series

        # Rentekurve: nye observasjoner flettes inn i lagret historikk (maks 400 dager)
        curve_series = {d: dict(v) for d, v in old_curves.get(cur, {}).items()}
        for day, vals in (curves.get(c["id"]) or {}).items():
            curve_series.setdefault(day, {}).update(vals)
        cutoff = str(date.today() - timedelta(days=400))
        drop = CURVE_DROP_TENORS.get(c["id"], set())
        curve_series = {d: {t: r for t, r in v.items() if t not in drop}
                        for d, v in curve_series.items() if d >= cutoff}
        curve_series = {d: v for d, v in curve_series.items() if v}
        # Futures på styringsrenten: dagens snapshot (ASX, TMX) eller historikk (Yahoo) flettes inn
        futures_series = {d: list(v) for d, v in old_futures.get(cur, {}).items() if d >= cutoff}
        futures_series.update(futures.get(c["id"]) or {})
        if c["id"] == "nz" and futures_series:
            # Kvartalskontraktene starter først om 2–3 mnd; OECDs 3-mnd-rente (månedssnitt) gir nåpunktet
            futures_series = add_monthly_front(futures_series, (sources["ir3"] or {}).get(c["oecd"], {}))
        curve = build_curve(c["id"], curve_series, policy_series, futures_series) if c["id"] in CURVE_SOURCES else None
        if curve_series:
            curve_history[cur] = curve_series
        if futures_series:
            futures_history[cur] = futures_series
        if curve:
            # Dagsferske kurvepunkter foran OECDs månedssnitt der kurven har dem
            if curve["points"].get("0.25") is not None:
                rates["m3"] = curve["points"]["0.25"]
                rates["m3_source"] = "OIS" if curve["kind"] == "ois" else "statsveksel" if curve["kind"] != "govt" or c["id"] in ("us", "no", "se", "ca") else "statspapir"
            if curve["points"].get("10") is not None:
                rates["y10"], rates["y10_source"] = curve["points"]["10"], "statsobligasjon"
            if curve["kind"] not in ("ois", "futures"):
                curve["source"] += " – inkl. terminpremie"
        # Kursutvikling siden vedtaket, målt mot handelspartnerne (X/NOK ÷ I-44; NOK = 1/I-44),
        # så kronens egne bevegelser ikke farger bildet
        if policy_change and fx_series:
            i44 = sources["i44"] or old_history.get("fx", {}).get("I44", {})
            def world(day):
                if cur == "NOK":
                    v = value_at_or_before(fx_series, day)
                    return 1 / v if v else None
                x, b = value_at_or_before(fx_series, day), value_at_or_before(i44, day)
                return x / b if x and b else None
            base, now = world(policy_change["date"]), world(fx_day)
            if base and now:
                policy_change["fx_since"] = round((now / base - 1) * 100, 2)

        # Sentralbankens egen bane: automatisk der den finnes, ellers manuell fil (med gyldighetsdato)
        horizon_day = str(add_months(date.today(), 12))
        cb_path, auto = None, auto_cb_paths.get(c["id"])
        if auto and auto.get("path"):
            at_day, level = cb_path_at(auto["path"], horizon_day)
            if level is not None:
                cb_path = {"level": level, "horizon": horizon_text(at_day), "source": auto["label"], "as_of": auto.get("as_of"),
                           "path": {d: v for d, v in sorted(auto["path"].items()) if DATE_RE.match(d) and d >= today}}
        if cb_path is None and cb_paths.get(c["id"]):
            manual = cb_paths[c["id"]]
            cb_path = {k: manual[k] for k in ("level", "horizon", "source", "as_of", "valid_until") if k in manual}
            key = f"cb_path_{c['id']}"
            expired = manual.get("valid_until") and manual["valid_until"] < today
            if key in status and not status[key]["ok"]:
                status[key]["warn"] = "bruker manuell reserve i cb_paths.json"
            elif key not in status:
                status[key] = {"ok": True, "error": None, "latest": manual.get("as_of"), "fetched": today_iso,
                               "warn": f"manuell, gyldig til {manual['valid_until']} – utløpt" if expired else None}
            if expired:
                cb_path["stale"] = True

        # Neste rentemøte fra den statiske kalenderen, og hva markedet priser for det
        upcoming = [d for d in meetings.get(c["id"], []) if d >= today]
        odds = meeting_odds.get(c["id"])
        next_meeting = None
        if upcoming:
            next_meeting = {"date": min(upcoming)}
            implied_next = meeting_implied_futures(curve["futures"], next_meeting["date"], upcoming, policy,
                                                   curve["anchor"]["basis"]) if curve and curve.get("futures") else None
            if implied_next:
                next_meeting.update({**implied_next, "source": FUTURES_SOURCES[c["id"]]})
            elif odds and odds.get("date") == next_meeting["date"]:
                next_meeting.update({k: odds[k] for k in ("bp", "prob", "move", "source") if k in odds})
            elif curve:
                # Uten futures: les møtet ut av 1/3-mnd-renten der fronten følger styringsrenten (OIS,
                # swap). Statsveksler har knapphetspremie som ikke kan skilles fra priset bevegelse
                # med medianbasisen, så der vises bare 3-mnd-prisingen som indikasjon.
                from_curve = meeting_implied_curve(curve.get("points"), policy, (curve.get("anchor") or {}).get("basis"), upcoming) \
                    if curve["kind"] in ("ois", "swap") else None
                next_meeting["bp_3m"] = curve["implied"]["3m"]
                next_meeting.update(from_curve or {"source": "rentekurven (3 mnd)"})
        countries.append({
            **{k: c[k] for k in ("id", "name", "currency", "bank", "flag")},
            "fx": fx,
            "rates": rates,
            "cpi": cpi,
            "cpi_core": cpi_core,
            "policy_change": policy_change,
            "cb_path": cb_path,
            "unemployment": unemployment,
            "ppp": ppp,
            "cot": cot,
            "curve": curve,
            "vol30": realized_vol(fx_series) if fx_series else None,
            "meeting": min(upcoming) if upcoming else None,
            "next_meeting": next_meeting,
        })

    # 1-års terminkurs mot NOK fra rentedifferansen (dekket renteparitet). Terminen
    # er breakeven for en carry-handel – ikke en prognose for kursen.
    norway = next(c for c in countries if c["id"] == "no")
    nok_1y = rate_at_tenor((norway.get("curve") or {}).get("points"), 1)
    nok_from_curve = nok_1y is not None
    if nok_1y is None:
        nok_1y = norway["rates"].get("m3")
    for c in countries:
        if c["id"] == "no" or not c.get("fx") or nok_1y is None:
            continue
        for_1y = rate_at_tenor((c.get("curve") or {}).get("points"), 1)
        from_curve = nok_from_curve and for_1y is not None
        if for_1y is None:
            for_1y = c["rates"].get("m3")
        if for_1y is None:
            continue
        spot = c["fx"]["value"]
        fwd = spot * (1 + nok_1y / 100) / (1 + for_1y / 100)
        c["fwd_fx_1y"] = {
            "rate": round(fwd, 4),
            "pct": round((fwd / spot - 1) * 100, 2),
            "diff": round(for_1y - nok_1y, 2),
            "from_curve": from_curve,
        }

    # Markedsindikatorer på tvers av landene
    fx_all = sources["fx"] or old_history.get("fx", {})
    brent = sources["brent"] or old_history.get("market", {}).get("brent", {})
    old_market = load_existing(dashboard_path).get("market", {}) if old_dashboard else {}
    if sources["brent_fut"]:
        brent_fut, brent_fut_label, brent_next, brent_next_label = brent_front_and_next(sources["brent_fut"])
    else:  # kilden feilet: forrige front-kontrakt fra historikken
        brent_fut, brent_fut_label = old_history.get("market", {}).get("brent_fut", {}), (old_market.get("brent_fut") or {}).get("contract")
        brent_next, brent_next_label = old_history.get("market", {}).get("brent_next", {}), (old_market.get("brent_next") or {}).get("contract")
    ttf = sources["ttf"] or old_history.get("market", {}).get("ttf", {})
    vix = sources["vix"] or old_history.get("market", {}).get("vix", {})
    audjpy = {}
    aud, jpy = fx_all.get("AUD", {}), fx_all.get("JPY", {})
    for day in sorted(set(aud) & set(jpy)):
        if jpy[day]:
            audjpy[day] = round(aud[day] / jpy[day], 3)
    brent_premium = premium_series(brent, brent_fut)
    history["market"] = {"brent": brent, "brent_fut": brent_fut, "brent_next": brent_next, "brent_premium": brent_premium,
                         "ttf": ttf, "vix": vix, "audjpy": audjpy}

    def snapshot(series, decimals=2):
        day, value = latest(series)
        if not day:
            return None
        return {
            "value": round(value, decimals),
            "date": day,
            "changes": {"d1": pct_change(series, 1), "w1": pct_change(series, 7),
                        "m1": pct_change(series, 30), "y1": pct_change(series, 365)},
        }

    # Oljekorrelasjon for NOK: daglige avkastninger Brent vs. kronestyrke (invertert I-44)
    i44 = history["fx"].get("I44", {})
    nok_strength = {d: 1 / v for d, v in i44.items() if v}
    market = {
        "brent": snapshot(brent),          # Dated Brent (fysisk spot, FRED)
        "brent_fut": snapshot(brent_fut),  # ICE Brent front-kontrakt (Yahoo, kontrakt for kontrakt)
        "ttf": snapshot(ttf),              # TTF-gass front-måned, EUR/MWh (Yahoo TTF=F)
        "vix": snapshot(vix),
        "audjpy": snapshot(audjpy, 3),
        "brent_nok_corr": correlation(brent, nok_strength),
    }
    if market["brent_fut"]:
        market["brent_fut"]["contract"] = brent_fut_label
        # Spotpremie: Dated Brent minus front-kontrakten på samme dato (FRED henger noen dager
        # etter, så datoen vises), med 90-dagers snitt fra historikken som referanse
        prem_day, prem = latest(brent_premium)
        if prem_day:
            market["brent_premium"] = {"value": prem, "date": prem_day, "avg90": trailing_mean(brent_premium)}
        # Kalenderspread front − neste kontrakt: positiv = backwardation (stramt marked)
        if brent_next:
            spread_days = sorted(set(brent_fut) & set(brent_next))
            if spread_days:
                d = spread_days[-1]
                market["brent_next"] = {"value": round(brent_next[d], 2), "date": d, "contract": brent_next_label}
                market["brent_spread"] = {"value": round(brent_fut[d] - brent_next[d], 2), "date": d}

    dashboard_path.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "countries": countries, "market": market, "sources": status},
        ensure_ascii=False, indent=1, allow_nan=False))
    # history.json lastes av siden; kurvehistorikken brukes bare av dette scriptet
    # (reprising) og ligger derfor i egen fil.
    history_path.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False))
    curves_path.write_text(json.dumps({"curve": curve_history, "futures": futures_history}, ensure_ascii=False, allow_nan=False))
    print(f"Skrev {dashboard_path}, {history_path} og {curves_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Henter markedsdata for G10-landene og skriver data/dashboard.json + data/history.json.

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

import csv
import io
import json
import math
import re
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


def fetch(url, timeout=60, attempts=4, errors="strict"):
    # Accept-headeren er nødvendig: FRED (Akamai) lar forespørsler uten den henge til timeout
    req = urllib.request.Request(url, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors=errors)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


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


def fetch_fred_series(series_id):
    """Daglig serie fra FREDs offentlige CSV-endepunkt (Brent, VIX)."""
    start = date.today() - timedelta(days=400)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        value = to_float(row.get(series_id))
        if value is not None:
            series[row["observation_date"]] = value
    return series


def fetch_cot():
    """Netto spekulativ posisjonering (non-commercial) fra CFTC, ukentlig 1 år.

    Samme Socrata-datasett som bedrock-prosjektet bruker (6dca-aqww, legacy
    futures-only). Netto = long − short; lagres sammen med open interest.
    """
    start = date.today() - timedelta(days=400)
    contracts = "','".join(COT_CONTRACTS.values())
    query = urllib.parse.urlencode({
        "$select": "report_date_as_yyyy_mm_dd,contract_market_name,"
                   "noncomm_positions_long_all,noncomm_positions_short_all,open_interest_all",
        "$where": f"contract_market_name in('{contracts}') "
                  f"AND report_date_as_yyyy_mm_dd >= '{start}'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "5000",
    })
    raw = fetch(f"https://publicreporting.cftc.gov/resource/6dca-aqww.json?{query}", timeout=120)
    by_contract = {}
    for row in json.loads(raw):
        long_ = to_float(row.get("noncomm_positions_long_all"))
        short = to_float(row.get("noncomm_positions_short_all"))
        oi = to_float(row.get("open_interest_all"))
        if long_ is None or short is None:
            continue
        day = row["report_date_as_yyyy_mm_dd"][:10]
        by_contract.setdefault(row["contract_market_name"], {})[day] = {
            "net": int(long_ - short),
            "oi": int(oi) if oi else None,
        }
    return by_contract


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
    "au": ("govt", "bankveksler + statsobligasjoner (RBA)"),
    "se": ("govt", "svenske statspapirer (Riksbanken)"),
    "no": ("zero", "nullkupong statskurve (Norges Bank)"),
}

# Løpetider (år) som lagres i historikken. Nøkkel i JSON = f"{tenor:g}".
CURVE_TENORS = (1 / 12, 0.25, 0.5, 1, 2, 3, 5, 10)


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
            elif 't="' in attrs:  # t="e" (feil), t="str" (formeltekst) o.l.
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


def fetch_curve_au():
    """RBA-tabellene F1 (pengemarked) og F2 (statsobligasjoner), daglige CSV-er.

    Kolonner velges ut fra tittelen («3-month OIS», «2 year bond»). RBAs
    OIS-serier opphørte i 2022, så per rad brukes første kolonne med verdi:
    OIS hvis den finnes, ellers bankveksler (BABs/NCDs), ellers statskasseveksler.
    """
    start = str(curve_start())
    out = {}
    for table in ("f1", "f2"):
        raw = fetch(f"https://www.rba.gov.au/statistics/tables/csv/{table}-data.csv", timeout=120)
        rows = list(csv.reader(io.StringIO(raw)))
        titles = next((r for r in rows if r and r[0].strip().lower() == "title"), None)
        if not titles:
            continue
        candidates = {}  # løpetid (år) -> [kolonneindekser i prioritert rekkefølge]
        for idx, title in enumerate(titles):
            m = re.search(r"(\d+)-?\s*(month|year)", title, re.I)
            if not m or idx == 0 or "indexed" in title.lower():
                continue
            years = int(m.group(1)) / (12 if m.group(2).lower() == "month" else 1)
            if table == "f1" and years >= 1:
                continue
            low = title.lower()
            priority = 0 if "ois" in low else 1 if "bab" in low or "ncd" in low else 2
            candidates.setdefault(years, []).append((priority, idx))
        for row in rows:
            try:
                day = str(datetime.strptime(row[0].strip(), "%d-%b-%Y").date())
            except (ValueError, IndexError):
                continue
            if day < start:
                continue
            for years, cols in candidates.items():
                for _, idx in sorted(cols):
                    value = to_float(row[idx]) if idx < len(row) else None
                    if value is not None:
                        out.setdefault(day, {})[tenor_key(years)] = value
                        break
    return out


def curve_metrics(points, policy):
    """Implisert bane for den korte renten fra en spotkurve.

    points: {tenor_år: rente %}. Spotrenten interpoleres lineært mellom kjente
    løpetider (flat utenfor). 3-mnd terminrenten ved horisont h (år) er
    f(h) = (r(h+0,25)·(h+0,25) − r(h)·h) / 0,25, dvs. den korte renten markedet
    priser for perioden som starter om h. Priset endring = f(h) − r(0,25), og
    nivået = styringsrente + priset endring, slik at et konstant basis-avvik
    mellom statspapirer og styringsrente faller bort. Mangler kurven punkter
    under 6 mnd, antas 3-mnd-renten lik styringsrenten (synthetic_anchor).
    """
    pts = sorted((float(t), v) for t, v in points.items() if v is not None)
    if policy is None or len(pts) < 3 or pts[-1][0] < 2 or pts[0][0] > 1:
        return None
    synthetic = pts[0][0] > 0.5
    if synthetic:
        pts.insert(0, (0.25, policy))

    def r(T):
        if T <= pts[0][0]:
            return pts[0][1]
        for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
            if T <= t1:
                return r0 + (r1 - r0) * (T - t0) / (t1 - t0)
        return pts[-1][1]

    def fwd(h):
        return (r(h + 0.25) * (h + 0.25) - r(h) * h) / 0.25

    anchor = fwd(0)
    path = [round(policy + fwd(m / 12) - anchor, 3) for m in range(25)]
    implied = {f"{m}m": round((fwd(m / 12) - anchor) * 100) for m in (3, 6, 12, 24)}
    extreme_m = max(range(1, 25), key=lambda m: abs(path[m] - path[0]))
    return {
        "implied": implied,
        "path": path,
        "extreme": {"months": extreme_m, "level": path[extreme_m],
                    "bp": round((path[extreme_m] - path[0]) * 100)},
        "synthetic_anchor": synthetic,
    }


def curve_at(series, target_day):
    """Kurvepunktene på eller like før en dato."""
    days = [d for d in series if d <= target_day]
    return series[max(days)] if days else None


def build_curve(cid, series, policy_series):
    """Lager dashboard-objektet for et lands rentekurve, inkl. reprising siste uke/måned."""
    if not series:
        return None
    policy_day, policy = latest(policy_series)
    # Kilder med flere delserier kan mangle de korte punktene på siste dag;
    # bruk nyeste dag (inntil en uke tilbake) der kurven er komplett nok.
    day, metrics = None, None
    for candidate in sorted(series, reverse=True)[:7]:
        metrics = curve_metrics(series[candidate], policy)
        if metrics:
            day = candidate
            break
    if not metrics:
        return None
    kind, source = CURVE_SOURCES[cid]
    repricing, y2_change = {}, {}
    for label, days in (("w1", 7), ("m1", 30)):
        past_day = str(date.fromisoformat(day) - timedelta(days=days))
        past = curve_at(series, past_day)
        if not past:
            continue
        past_policy = value_at_or_before(policy_series, past_day) if policy_series else policy
        past_metrics = curve_metrics(past, past_policy if past_policy is not None else policy)
        if past_metrics:
            repricing[label] = metrics["implied"]["12m"] - past_metrics["implied"]["12m"]
        if series[day].get("2") is not None and past.get("2") is not None:
            y2_change[label] = round((series[day]["2"] - past["2"]) * 100)
    return {
        "date": day,
        "kind": kind,
        "source": source,
        "points": {k: round(v, 3) for k, v in sorted(series[day].items(), key=lambda kv: float(kv[0]))},
        "repricing": repricing,
        "y2_change": y2_change,
        **metrics,
    }


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

    sources = {}
    for name, fn in [
        ("fx", fetch_fx_history),
        ("i44", fetch_i44_history),
        ("policy", fetch_policy_rates),
        ("irlt", lambda: fetch_oecd_rates("IRLT")),
        ("ir3", lambda: fetch_oecd_rates("IR3TIB")),
        ("cpi", fetch_cpi),
        ("unemployment", fetch_unemployment),
        ("brent", lambda: fetch_fred_series("DCOILBRENTEU")),
        ("vix", lambda: fetch_fred_series("VIXCLS")),
        ("cot", fetch_cot),
        ("ppp", fetch_ppp),
    ]:
        print(f"Henter {name} ...")
        try:
            sources[name] = fn()
        except Exception as exc:
            print(f"  ADVARSEL: {name} feilet ({exc}) – beholder forrige data", file=sys.stderr)
            sources[name] = None

    # Rentekurver per land (grunnlag for «hva er priset inn»). BoE og MoF gir bare
    # inneværende måned per fil, så historikken bygges opp over tid og backfylles
    # fra arkivfiler første gang.
    old_curves = old_history.get("curve", {})
    curve_fetchers = {
        "us": fetch_curve_us,
        "ea": fetch_curve_ea,
        "jp": lambda: fetch_curve_jp(len(old_curves.get("JPY", {}))),
        "gb": lambda: fetch_curve_gb(len(old_curves.get("GBP", {}))),
        "ca": fetch_curve_ca,
        "au": fetch_curve_au,
        "se": fetch_curve_se,
        "no": fetch_curve_no,
    }
    curves = {}
    for cid, fn in curve_fetchers.items():
        print(f"Henter rentekurve {cid} ...")
        try:
            curves[cid] = fn()
        except Exception as exc:
            print(f"  ADVARSEL: rentekurve {cid} feilet ({exc}) – beholder forrige data", file=sys.stderr)
            curves[cid] = None

    meetings = load_existing(DATA_DIR / "meetings.json")
    today = str(date.today())

    # USD-kryss trengs for PPP-verdivurdering (lokal valuta per USD)
    usd_nok = (sources["fx"] or {}).get("USD") or old_history.get("fx", {}).get("USD", {})
    _, usd_nok_last = latest(usd_nok)

    countries = []
    history = {"fx": {}, "policy": {}, "cot": {}, "market": {}, "curve": {}}
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
        policy_series = (sources["policy"] or {}).get(c["bis"]) or old_history.get("policy", {}).get(c["bis"], {})
        policy_day, policy = latest(policy_series)
        history["policy"][c["bis"]] = policy_series
        _, y10 = latest((sources["irlt"] or {}).get(c["oecd"], {}))
        _, m3 = latest((sources["ir3"] or {}).get(c["oecd"], {}))
        old_rates = old.get("rates", {})
        rates = {
            "policy": policy if policy is not None else old_rates.get("policy"),
            "policy_date": policy_day or old_rates.get("policy_date"),
            "m3": m3 if m3 is not None else old_rates.get("m3"),
            "y10": y10 if y10 is not None else old_rates.get("y10"),
        }

        # Endring i styringsrente siste 6 mnd (til retningsindikatoren)
        if policy_series and policy_day:
            past = value_at_or_before(policy_series, str(date.fromisoformat(policy_day) - timedelta(days=182)))
            rates["policy_6m_change"] = round(policy - past, 3) if past is not None else None

        # Inflasjon
        cpi_period, cpi_value = latest((sources["cpi"] or {}).get(c["oecd"], {}))
        cpi = {"value": cpi_value, "period": cpi_period} if cpi_period else old.get("cpi")

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
            }
            history["cot"][cur] = cot_series

        # Rentekurve: nye observasjoner flettes inn i lagret historikk (maks 400 dager)
        curve_series = {d: dict(v) for d, v in old_curves.get(cur, {}).items()}
        for day, vals in (curves.get(c["id"]) or {}).items():
            curve_series.setdefault(day, {}).update(vals)
        cutoff = str(date.today() - timedelta(days=400))
        curve_series = {d: v for d, v in curve_series.items() if d >= cutoff}
        curve = build_curve(c["id"], curve_series, policy_series) if c["id"] in CURVE_SOURCES else None
        if curve_series:
            history["curve"][cur] = curve_series

        # Neste rentemøte fra den statiske kalenderen
        upcoming = [d for d in meetings.get(c["id"], []) if d >= today]
        countries.append({
            **{k: c[k] for k in ("id", "name", "currency", "bank", "flag")},
            "fx": fx,
            "rates": rates,
            "cpi": cpi,
            "unemployment": unemployment,
            "ppp": ppp,
            "cot": cot,
            "curve": curve,
            "vol30": realized_vol(fx_series) if fx_series else None,
            "meeting": min(upcoming) if upcoming else None,
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
    vix = sources["vix"] or old_history.get("market", {}).get("vix", {})
    audjpy = {}
    aud, jpy = fx_all.get("AUD", {}), fx_all.get("JPY", {})
    for day in sorted(set(aud) & set(jpy)):
        if jpy[day]:
            audjpy[day] = round(aud[day] / jpy[day], 3)
    history["market"] = {"brent": brent, "vix": vix, "audjpy": audjpy}

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
        "brent": snapshot(brent),
        "vix": snapshot(vix),
        "audjpy": snapshot(audjpy, 3),
        "brent_nok_corr": correlation(brent, nok_strength),
    }

    dashboard_path.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "countries": countries, "market": market},
        ensure_ascii=False, indent=1, allow_nan=False))
    history_path.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False))
    print(f"Skrev {dashboard_path} og {history_path}")


if __name__ == "__main__":
    main()

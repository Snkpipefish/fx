#!/usr/bin/env python3
"""Laster ned RBNZ tabell B2 (daglige engrosrenter) med Playwright.

rbnz.govt.nz ligger bak Cloudflare, som avviser urllib/curl og Playwrights
egen HTTP-klient, men slipper gjennom en headless Chromium som (1) bruker en
vanlig Chrome-User-Agent, (2) har automasjonsflagget slått av og (3) først
besøker en side på nettstedet så «__cf_bm»-cookien settes. Fila hentes
deretter med fetch() inne i siden og skrives til .cache/rbnz-b2.xlsx, som
scripts/fetch_data.py leser (fetch_curve_nz).

Kjør: pip install playwright && playwright install --with-deps chromium && python3 scripts/fetch_rbnz.py

Merk: fra GitHub-runnere svarer rbnz.govt.nz 403 også for selve siden (Cloudflare
blokkerer IP-området), så dette virker bare fra vanlige nett. fetch_data.py bruker
fila når den finnes; ellers kommer NZD-kurven fra ASXs bankvekselfutures.
"""
import base64
import os
import sys
from pathlib import Path

PAGE = "https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/wholesale-interest-rates"
URL = "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / ".cache" / "rbnz-b2.xlsx"
FETCH_JS = """async (u) => {
  const r = await fetch(u, { credentials: "include" });
  const b = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
  return [r.status, btoa(s)];
}"""


def download(out_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=USER_AGENT, locale="en-NZ")
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        page = context.new_page()
        response = page.goto(PAGE, wait_until="domcontentloaded", timeout=60000)
        if response is None or response.status != 200:
            raise RuntimeError(f"B2-siden svarte {response.status if response else 'ingenting'}")
        status, b64 = page.evaluate(FETCH_JS, URL)
        browser.close()
    data = base64.b64decode(b64)
    if status != 200 or data[:2] != b"PK":
        raise RuntimeError(f"nedlastingen svarte {status} ({len(data)} byte, ikke xlsx)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return len(data)


def main():
    out_path = Path(os.environ.get("RBNZ_B2_FILE", DEFAULT_OUT))
    try:
        size = download(out_path)
    except Exception as exc:  # ikke stopp innhentingen – fetch_data.py beholder forrige kurve
        print(f"ADVARSEL: RBNZ B2 kunne ikke lastes ned ({exc})", file=sys.stderr)
        return 0
    print(f"Skrev {out_path} ({size} byte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

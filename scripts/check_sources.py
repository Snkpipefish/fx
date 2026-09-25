#!/usr/bin/env python3
"""Feiler (exit 1) hvis en kilde i data/dashboard.json er for gammel. Kjøres etter publisering
i GitHub Actions, så en rød kjøring fungerer som varsel uten å stoppe oppdateringen."""
import json
import sys
from datetime import date
from pathlib import Path

MONTHLY = {"irlt", "ir3", "cpi", "cpi_core", "ons_cpi", "unemployment", "ppp"}
LIMITS = {"cot": 14, "ppp": 800}  # ukentlig / årlig med 1–2 års etterslep
DEFAULT_DAYS, MONTHLY_DAYS = 10, 75


def age_days(period):
    if not period:
        return None
    if len(period) == 4:  # YYYY: årsdata
        period += "-12-31"
    elif len(period) == 7:  # YYYY-MM: regn fra månedsslutt-ish
        period += "-28"
    return (date.today() - date.fromisoformat(period)).days


def main():
    sources = json.loads((Path(__file__).resolve().parent.parent / "data" / "dashboard.json").read_text()).get("sources", {})
    stale = []
    for name, st in sources.items():
        limit = LIMITS.get(name, MONTHLY_DAYS if name in MONTHLY else DEFAULT_DAYS)
        age = age_days(st.get("latest"))
        if age is None or age > limit:
            stale.append(f"{name}: nyeste {st.get('latest')} ({age} dager, grense {limit}){'' if st.get('ok') else ' – siste henting feilet: ' + str(st.get('error'))}")
    if stale:
        print("GAMLE KILDER:\n  " + "\n  ".join(stale))
        sys.exit(1)
    print(f"Alle {len(sources)} kilder er ferske.")


if __name__ == "__main__":
    main()

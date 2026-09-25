#!/usr/bin/env python3
"""Kalibrerer vektene i retningssignalet mot det som faktisk skjedde.

Leser data/snapshots/ÅÅÅÅ-MM-DD.json og regresserer 4-ukers avkastning mot
G10-kurven (fx_world: likevektet kurv av de ni andre valutaene) på de tre faktorene i calc.js,
skalert som der: rente = clamp(priset 6 mnd / 40 bp), momentum = clamp(kurs 3 mnd / 4 %),
realrente = clamp((styringsrente − målinflasjon) / 2 pp). Koeffisientene er da direkte
sammenlignbare med dagens faste vekter 0,45 / 0,35 / 0,20.

Kjør: python3 scripts/backtest_signal.py [--horizon 28] [--rate-from 6m|12m] [--json ut.json]
Krever komplette observasjoner (alle tre faktorer + kurs 4 uker senere). Utfylte snapshots
(backfilled) mangler priset 6 mnd og målinflasjon, så de første ekte kalibreringene kommer
etter noen måneder med daglige kjøringer. Med --rate-from 12m brukes bane[12] − styringsrente
som rentefaktor, som også finnes i utfylte snapshots (men realrenten mangler fortsatt der).
"""
import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"
FACTORS = ("rente", "momentum", "realrente")
CURRENT_WEIGHTS = {"rente": 0.45, "momentum": 0.35, "realrente": 0.20}
MIN_OBS = 120  # komplette observasjoner før tallene betyr noe


def clamp(v):
    return max(-1.0, min(1.0, v))


def factors_from(rec, rate_from="6m"):
    """(rente, momentum, realrente) skalert som i calc.js, None der grunnlaget mangler."""
    rate = None
    if rate_from == "6m" and rec.get("implied") and rec["implied"].get("6m") is not None:
        rate = clamp(rec["implied"]["6m"] / 40)
    elif rate_from == "12m" and rec.get("path") and rec["path"][3] is not None and rec.get("policy") is not None:
        rate = clamp((rec["path"][3] - rec["policy"]) * 100 / 40)
    mom = clamp(rec["fx_m3"] / 4) if rec.get("fx_m3") is not None else None
    real = clamp((rec["policy"] - rec["cpi_target"]) / 2) if rec.get("policy") is not None and rec.get("cpi_target") is not None else None
    return rate, mom, real


def load_snapshots(snapshot_dir):
    out = {}
    for path in sorted(snapshot_dir.glob("????-??-??.json")):
        try:
            out[path.stem] = json.loads(path.read_text())
        except ValueError:
            continue
    return out


def observations(snapshots, horizon_days=28, rate_from="6m", factors=FACTORS):
    """[(dato, land, faktorer, avkastning %)] for dager med de valgte faktorene og kurs
    `horizon_days` senere (første snapshot på eller etter måldatoen, inntil 5 dager sent)."""
    days = sorted(snapshots)
    idx = [FACTORS.index(f) for f in factors]
    rows = []
    for day in days:
        target = date.fromisoformat(day) + timedelta(days=horizon_days)
        later = [d for d in days if target <= date.fromisoformat(d) <= target + timedelta(days=5)]
        if not later:
            continue
        nxt = snapshots[later[0]]
        for cid, rec in snapshots[day].get("countries", {}).items():
            f = tuple(factors_from(rec, rate_from)[i] for i in idx)
            now, then = rec.get("fx_world"), (nxt.get("countries", {}).get(cid) or {}).get("fx_world")
            if None in f or not now or not then:
                continue
            rows.append((day, cid, f, (then / now - 1) * 100))
    return rows


def ols(xs, ys):
    """Minste kvadraters metode med konstantledd (normalligninger, ingen numpy).
    Returnerer (koeffisienter inkl. konstant først, t-verdier, R²)."""
    n, k = len(xs), len(xs[0]) + 1
    X = [[1.0, *x] for x in xs]
    xtx = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(X[r][i] * ys[r] for r in range(n)) for i in range(k)]
    inv = invert(xtx)
    beta = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    resid = [ys[r] - sum(X[r][i] * beta[i] for i in range(k)) for r in range(n)]
    sse = sum(e * e for e in resid)
    ybar = sum(ys) / n
    sst = sum((y - ybar) ** 2 for y in ys) or 1e-12
    sigma2 = sse / max(n - k, 1)
    tvals = [beta[i] / math.sqrt(sigma2 * inv[i][i]) if inv[i][i] > 0 else float("nan") for i in range(k)]
    return beta, tvals, 1 - sse / sst


def invert(m):
    """Gauss-Jordan-invers av en liten matrise."""
    k = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(k)] for i, row in enumerate(m)]
    for i in range(k):
        pivot = max(range(i, k), key=lambda r: abs(a[r][i]))
        a[i], a[pivot] = a[pivot], a[i]
        if abs(a[i][i]) < 1e-12:
            raise ValueError("singulær matrise – faktorene er lineært avhengige eller konstante")
        div = a[i][i]
        a[i] = [v / div for v in a[i]]
        for r in range(k):
            if r != i:
                f = a[r][i]
                a[r] = [rv - f * iv for rv, iv in zip(a[r], a[i])]
    return [row[k:] for row in a]


def calibrate(rows, factors=FACTORS):
    """Regresjon av avkastning på faktorene; foreslåtte vekter = koeffisientenes andel av
    summen av absoluttverdier (fortegn beholdes), så de kan settes rett inn i calc.js."""
    xs = [list(f) for _, _, f, _ in rows]
    ys = [y for *_, y in rows]
    beta, tvals, r2 = ols(xs, ys)
    coef = dict(zip(factors, beta[1:]))
    tv = dict(zip(factors, tvals[1:]))
    total = sum(abs(v) for v in coef.values()) or 1.0
    weights = {k: round(v / total, 2) for k, v in coef.items()}
    return {"n": len(rows), "days": len({d for d, *_ in rows}), "countries": len({c for _, c, *_ in rows}),
            "intercept": round(beta[0], 4), "coef": {k: round(v, 4) for k, v in coef.items()},
            "t": {k: round(v, 2) for k, v in tv.items()}, "r2": round(r2, 4), "weights": weights,
            "current": CURRENT_WEIGHTS, "reliable": len(rows) >= MIN_OBS}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horizon", type=int, default=28, help="dager frem for avkastningen (standard 28)")
    ap.add_argument("--rate-from", choices=("6m", "12m"), default="6m", help="rentefaktor: priset 6 mnd (som calc.js) eller bane[12] − styringsrente")
    ap.add_argument("--factors", default=",".join(FACTORS), help="kommaseparert delmengde av rente,momentum,realrente (utfylte snapshots mangler realrente)")
    ap.add_argument("--json", type=Path, help="skriv resultatet som JSON hit")
    ap.add_argument("--snapshots", type=Path, default=SNAPSHOT_DIR)
    args = ap.parse_args(argv)
    factors = tuple(f.strip() for f in args.factors.split(",") if f.strip())
    if any(f not in FACTORS for f in factors) or not factors:
        ap.error(f"--factors må være en delmengde av {','.join(FACTORS)}")
    snaps = load_snapshots(args.snapshots)
    rows = observations(snaps, args.horizon, args.rate_from, factors)
    print(f"{len(snaps)} snapshots, {len(rows)} komplette observasjoner (faktorer {', '.join(factors)}, rentefaktor fra {args.rate_from}, horisont {args.horizon} dager)")
    if len(rows) < 4:
        print(f"For få observasjoner til å regne noe. Utfylte snapshots mangler priset 6 mnd og målinflasjon; "
              f"trenger ca. {MIN_OBS} komplette (≈ {MIN_OBS // 10} dager × 10 land) fra daglige kjøringer.")
        return 0
    res = calibrate(rows, factors)
    print(f"Dager {res['days']}, land {res['countries']}, R² {res['r2']:.3f}, konstant {res['intercept']:+.3f} %")
    print(f"{'faktor':<10} {'koeff':>8} {'t':>7} {'foreslått vekt':>15} {'i dag':>7}")
    for k in factors:
        print(f"{k:<10} {res['coef'][k]:>+8.3f} {res['t'][k]:>7.2f} {res['weights'][k]:>+15.2f} {CURRENT_WEIGHTS[k]:>7.2f}")
    if not res["reliable"]:
        print(f"Bare {res['n']} observasjoner – under {MIN_OBS}; ikke bytt vekter ennå.")
    if args.json:
        args.json.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"Skrev {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

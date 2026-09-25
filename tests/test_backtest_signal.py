"""Tester for scripts/backtest_signal.py (kjør: python3 -m unittest discover tests)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("bt", Path(__file__).resolve().parent.parent / "scripts" / "backtest_signal.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


class BacktestTest(unittest.TestCase):
    def test_factors_from_snapshot(self):
        rec = {"implied": {"6m": 20}, "fx_m3": -2.0, "policy": 4.0, "cpi_target": 3.0, "path": [None, None, None, 4.8, None]}
        self.assertEqual(bt.factors_from(rec), (0.5, -0.5, 0.5))
        self.assertEqual(bt.factors_from(rec, "12m"), (1.0, -0.5, 0.5))  # (4.8 − 4.0) = 80 bp → clamp
        back = {"implied": None, "fx_m3": 1.0, "policy": 4.0, "cpi_target": None, "path": [None, None, None, 4.2, None]}
        self.assertEqual(bt.factors_from(back), (None, 0.25, None))
        self.assertEqual(bt.factors_from(back, "12m")[0], 0.5)

    def test_ols_recovers_known_coefficients(self):
        import random
        random.seed(1)
        xs, ys = [], []
        for _ in range(400):
            f = [random.uniform(-1, 1) for _ in range(3)]
            xs.append(f)
            ys.append(0.3 + 2.0 * f[0] - 1.0 * f[1] + 0.5 * f[2] + random.gauss(0, 0.05))
        beta, t, r2 = bt.ols(xs, ys)
        for got, want in zip(beta, (0.3, 2.0, -1.0, 0.5)):
            self.assertAlmostEqual(got, want, places=1)
        self.assertGreater(r2, 0.99)
        self.assertTrue(all(abs(v) > 10 for v in t[1:]))
        with self.assertRaises(ValueError):
            bt.ols([[1.0, 2.0, 3.0]] * 5, [1.0] * 5)  # konstante faktorer

    def test_observations_and_calibrate(self):
        from datetime import date, timedelta
        snaps = {}
        start = date(2026, 1, 5)
        for i in range(70):
            d = start + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            import math
            f, g, h = i / 70 - 0.5, math.sin(i / 5), math.cos(i / 9)  # tre uavhengige faktorer
            snaps[str(d)] = {"date": str(d), "countries": {
                "us": {"fx_world": 1.0 + 0.001 * i, "implied": {"6m": 40 * f}, "fx_m3": 4 * g, "policy": 4.0, "cpi_target": 4.0 - 2 * h},
                "jp": {"fx_world": 2.0 - 0.001 * i, "implied": {"6m": -40 * f}, "fx_m3": -4 * g, "policy": 1.0, "cpi_target": 1.0 + 2 * h},
                "nz": {"fx_world": None, "implied": None, "fx_m3": None, "policy": None, "cpi_target": None}}}
        rows = bt.observations(snaps, horizon_days=28)
        self.assertTrue(rows)
        self.assertTrue(all(c in ("us", "jp") for _, c, _, _ in rows))
        first = rows[0]
        self.assertEqual(first[0], "2026-01-05")
        self.assertAlmostEqual(first[3], (snaps["2026-02-02"]["countries"]["us"]["fx_world"] / snaps["2026-01-05"]["countries"]["us"]["fx_world"] - 1) * 100)
        with tempfile.TemporaryDirectory() as tmp:
            for d, rec in snaps.items():
                (Path(tmp) / f"{d}.json").write_text(json.dumps(rec))
            out = Path(tmp) / "res.json"
            self.assertEqual(bt.main(["--snapshots", tmp, "--json", str(out)]), 0)
            res = json.loads(out.read_text())
            self.assertEqual(set(res["weights"]), set(bt.FACTORS))
            self.assertAlmostEqual(sum(abs(v) for v in res["weights"].values()), 1.0, places=1)
            self.assertFalse(res["reliable"])  # under 120 observasjoner
            self.assertEqual(bt.main(["--snapshots", tmp, "--factors", "rente,momentum"]), 0)  # delmengde
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(bt.main(["--snapshots", empty]), 0)  # tom katalog: «for få observasjoner»


if __name__ == "__main__":
    unittest.main()

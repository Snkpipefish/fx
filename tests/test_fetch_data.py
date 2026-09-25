"""Tester for beregningene i scripts/fetch_data.py (kjør: python3 -m unittest discover tests)."""
import importlib.util
import io
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("fetch_data", Path(__file__).resolve().parent.parent / "scripts" / "fetch_data.py")
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)


class CurveMetricsTest(unittest.TestCase):
    def test_flat_curve_prices_no_change(self):
        m = fd.curve_metrics({"0.25": 4.0, "1": 4.0, "2": 4.0, "5": 4.0}, 4.0)
        self.assertEqual(m["implied"], {"3m": 0, "6m": 0, "12m": 0, "24m": 0})
        self.assertTrue(all(abs(p - 4.0) < 1e-9 for p in m["path"]))
        self.assertFalse(m["synthetic_anchor"])

    def test_steep_curve_prices_hikes(self):
        m = fd.curve_metrics({"0.25": 4.0, "0.5": 4.25, "1": 4.5, "2": 5.0}, 4.0)
        self.assertGreater(m["implied"]["6m"], 0)
        self.assertGreater(m["implied"]["12m"], m["implied"]["6m"])
        self.assertEqual(m["extreme"]["bp"], round((max(m["path"]) - m["path"][0]) * 100))

    def test_basis_cancels_out(self):
        """Et konstant påslag mellom statspapirer og styringsrente skal ikke gi priset endring."""
        m = fd.curve_metrics({"0.25": 4.4, "1": 4.4, "2": 4.4}, 4.0)
        self.assertEqual(m["implied"]["12m"], 0)
        self.assertEqual(m["path"][0], 4.0)

    def test_synthetic_anchor_when_short_end_missing(self):
        m = fd.curve_metrics({"1": 1.6, "2": 1.9, "5": 2.4, "10": 3.0}, 1.0)
        self.assertTrue(m["synthetic_anchor"])
        self.assertGreater(m["implied"]["12m"], 0)

    def test_rejects_too_sparse_curves(self):
        self.assertIsNone(fd.curve_metrics({"2": 4.0, "10": 4.5}, 4.0))
        self.assertIsNone(fd.curve_metrics({"0.25": 4.0, "0.5": 4.0, "1": 4.0}, 4.0))
        self.assertIsNone(fd.curve_metrics({"0.25": 4.0, "1": 4.0, "2": 4.0}, None))


class HelpersTest(unittest.TestCase):
    def test_rate_at_tenor_interpolates(self):
        pts = {"0.5": 2.0, "2": 4.0}
        self.assertAlmostEqual(fd.rate_at_tenor(pts, 1), 2 + 2 * (0.5 / 1.5))
        self.assertEqual(fd.rate_at_tenor(pts, 0.1), 2.0)
        self.assertEqual(fd.rate_at_tenor(pts, 9), 4.0)
        self.assertIsNone(fd.rate_at_tenor({}, 1))

    def test_build_curve_uses_latest_complete_day(self):
        series = {
            "2026-09-23": {"0.25": 4.0, "1": 4.2, "2": 4.4, "5": 4.5},
            "2026-09-24": {"2": 4.4, "5": 4.5},  # korte punkter mangler
        }
        curve = fd.build_curve("no", series, {"2026-09-01": 4.0})
        self.assertEqual(curve["date"], "2026-09-23")
        self.assertIn("path_w1", curve)

    def test_newest_date(self):
        self.assertEqual(fd.newest_date({"a": {"2026-01-05": 1, "2026-02": 2}, "b": [{"2025-12-31": 3}]}), "2026-02")
        self.assertIsNone(fd.newest_date({"x": 1}))

    def test_xlsx_sheet_rows_minimal_workbook(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>months:</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1/12</f><v>1</v></c></row>'
                       '<row r="2"><c r="A2"><v>46266</v></c><c r="B2"><v>3.5</v></c><c r="C2" t="e"><v>#VALUE!</v></c></row></sheetData></worksheet>')
        rows = fd.xlsx_sheet_rows(buf.getvalue(), "data")
        self.assertEqual(rows[0], (1, {"A": "months:", "B": 1.0}))
        self.assertEqual(rows[1], (2, {"A": 46266.0, "B": 3.5, "C": None}))
        self.assertEqual(fd.excel_date(46266), "2026-09-01")


class MarketAnchorTest(unittest.TestCase):
    """Banen ankres på markedets 3-mnd-rente minus basis, ikke på styringsrenten."""

    def hike_fixture(self):
        # Uke før vedtak: 3 mnd-renten priser en fullt ventet heving (4,00 → 4,25) om en uke.
        # Terminrentene lenger ut er identiske før og etter; bare styringsrenten og fronten flytter.
        # Vinteren/våren: ingen heving priset, veksel 5 bp over styringsrenten (normal basis).
        calm = {"0.25": 4.05, "0.5": 4.10, "1": 4.20, "2": 4.40, "5": 4.50}
        before = {"0.25": 4.23, "0.5": 4.30, "1": 4.40, "2": 4.60, "5": 4.70}
        after = {"0.25": 4.25, "0.5": 4.30, "1": 4.40, "2": 4.60, "5": 4.70}
        series = {f"2026-0{m}-{d:02d}": dict(calm) for m in (3, 4, 5, 6, 7) for d in (5, 15, 25)}
        series.update({"2026-09-01": dict(before), "2026-09-08": dict(before), "2026-09-15": dict(after)})
        policy = {"2026-01-01": 4.0, "2026-09-15": 4.25}
        return series, policy

    def test_delivered_hike_gives_no_repricing(self):
        series, policy = self.hike_fixture()
        curve = fd.build_curve("no", series, policy)
        self.assertEqual(curve["date"], "2026-09-15")
        self.assertEqual(curve["repricing"]["w1"], 0)
        # Nivået om 12 mnd er det samme før og etter vedtaket
        self.assertAlmostEqual(curve["path"][12], curve["path_w1"][12], places=6)

    def test_implied_counts_priced_meeting_inside_3m_window(self):
        series, policy = self.hike_fixture()
        basis = fd.curve_basis(series, policy, "2026-09-08")
        before = fd.curve_metrics(series["2026-09-08"], 4.0, basis)
        after = fd.curve_metrics(series["2026-09-15"], 4.25, basis)
        # Før vedtaket: hevingen ligger i 3-mnd-vinduet og skal telles med i «priset innen 3 mnd»
        self.assertGreaterEqual(before["implied"]["3m"], 20)
        # Etter vedtaket: 25 bp er levert, så priset endring fra ny styringsrente faller tilsvarende
        self.assertAlmostEqual(before["implied"]["3m"] - after["implied"]["3m"], 25, delta=3)
        self.assertEqual(before["anchor"]["kind"], "marked")

    def test_basis_is_median_of_front_minus_policy(self):
        series = {f"2026-01-{d:02d}": {"0.25": 4.0 + b, "1": 4.5, "2": 4.6} for d, b in
                  ((1, 0.10), (2, 0.12), (3, 0.90), (4, 0.11), (5, 0.13))}  # én dag med støy
        basis = fd.curve_basis(series, {"2025-12-01": 4.0}, "2026-01-05")
        self.assertAlmostEqual(basis, 0.12)
        # Vinduet begrenses bakover fra oppgitt dag
        self.assertAlmostEqual(fd.curve_basis(series, {"2025-12-01": 4.0}, "2026-01-02"), 0.11)
        self.assertIsNone(fd.curve_basis(series, {}, "2026-01-05"))
        self.assertIsNone(fd.curve_basis({}, {"2025-12-01": 4.0}, "2026-01-05"))

    def test_without_history_path_starts_at_policy(self):
        m = fd.curve_metrics({"0.25": 4.4, "1": 4.4, "2": 4.4}, 4.0)
        self.assertEqual(m["path"][0], 4.0)
        self.assertAlmostEqual(m["anchor"]["basis"], 0.4)
        self.assertEqual(m["anchor"]["rate_3m"], 4.4)

    def test_synthetic_anchor_has_zero_basis(self):
        series = {"2026-09-01": {"1": 1.6, "2": 1.9, "5": 2.4}, "2026-09-08": {"1": 1.6, "2": 1.9, "5": 2.4}}
        basis = fd.curve_basis(series, {"2026-01-01": 1.0}, "2026-09-08")
        self.assertEqual(basis, 0.0)
        m = fd.curve_metrics(series["2026-09-08"], 1.0, basis)
        self.assertTrue(m["synthetic_anchor"])
        self.assertEqual(m["anchor"]["kind"], "syntetisk")
        self.assertEqual(m["path"][0], 1.0)


if __name__ == "__main__":
    unittest.main()


class OverrideTest(unittest.TestCase):
    """Manuelt registrerte vedtak skal overstyre BIS-serien fra vedtaksdatoen."""

    def test_override_logic_matches_main(self):
        # Speiler logikken i main(): BIS 4,25 t.o.m. 24.9, vedtak 4,50 den 23.9
        series = {"2026-09-22": 4.25, "2026-09-23": 4.25, "2026-09-24": 4.25}
        ov = {"date": "2026-09-23", "rate": 4.5}
        policy_day, policy = fd.latest(series)
        if policy_day < ov["date"] or policy != ov["rate"]:
            for d in list(series):
                if d >= ov["date"]:
                    series[d] = ov["rate"]
            series[ov["date"]] = ov["rate"]
        self.assertEqual(series["2026-09-22"], 4.25)
        self.assertEqual(series["2026-09-24"], 4.5)
        self.assertEqual(fd.latest(series), ("2026-09-24", 4.5))
        # curve_metrics ankrer nå på 4,50: flat kurve på 4,5 gir null priset endring
        m = fd.curve_metrics({"0.25": 4.5, "1": 4.5, "2": 4.5}, fd.latest(series)[1])
        self.assertEqual(m["implied"]["12m"], 0)


class BrentContractTest(unittest.TestCase):
    def test_front_contract_rolls_after_expiry(self):
        from datetime import date as d
        self.assertEqual(fd.brent_front_contracts(d(2026, 9, 25)), ["BZX26.NYM", "BZZ26.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 10, 1)), ["BZZ26.NYM", "BZF27.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 11, 30))[0], "BZF27.NYM")

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
        self.assertEqual(fd.newest_date({"2025-01-01": ("2023", 1.2)}), "2025-01-01")  # PPP: (år, verdi) teller ikke over nøkkelen
        # Futures: kontraktsperioder peker fremover; observasjonsdagen er nyeste dato
        self.assertEqual(fd.newest_date({"2026-09-25": [["2026-10-01", "2026-10-31", 4.0], ["2028-01-01", "2028-01-31", 4.2]]}), "2026-09-25")

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


class FuturesTest(unittest.TestCase):
    """Møtebaserte instrumenter: kontrakter → perioder → bane og møteprising."""

    def test_calendar_helpers(self):
        self.assertEqual(fd.month_span(2026, 12), ("2026-12-01", "2026-12-31"))
        self.assertEqual(fd.month_span(2027, 2), ("2027-02-01", "2027-02-28"))
        from datetime import date as d
        self.assertEqual(fd.add_months(d(2026, 11, 15), 3), d(2027, 2, 15))
        self.assertEqual(fd.add_months(d(2026, 1, 31), 1), d(2026, 2, 28))
        self.assertEqual(fd.third_wednesday(2026, 9), d(2026, 9, 16))
        self.assertEqual(fd.third_wednesday(2026, 12), d(2026, 12, 16))
        self.assertEqual(fd.third_wednesday(2027, 3), d(2027, 3, 17))
        self.assertEqual(fd.previous_business_day(d(2026, 9, 28)), d(2026, 9, 25))  # mandag → fredag

    def test_parse_asx_ib(self):
        payload = {"data": {"items": [
            {"symbol": "IBU2026", "pricePreviousSettlement": 95.645, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "IBV2026", "pricePreviousSettlement": 95.425, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "IBX2026", "pricePreviousSettlement": None, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "XYZ", "pricePreviousSettlement": 95.0, "datePreviousSettlement": "2026-09-25"}]}}
        out = fd.parse_asx_ib(payload)
        self.assertEqual(out, {"2026-09-25": [["2026-09-01", "2026-09-30", 4.355], ["2026-10-01", "2026-10-31", 4.575]]})

    def test_parse_tmx_and_corra_periods(self):
        page = ("<tr data-row='{&quot;symbol&quot;:&quot;COAV26&quot;,&quot;settlement_price&quot;:97.695,&quot;expiry_date&quot;:&quot;2026-11-02&quot;}'></tr>"
                "<tr data-row='{&quot;symbol&quot;:&quot;CRAZ26&quot;,&quot;settlement_price&quot;:97.22,&quot;expiry_date&quot;:&quot;2027-03-17&quot;}'></tr>"
                "<tr data-row='{&quot;symbol&quot;:&quot;CRAH27&quot;,&quot;settlement_price&quot;:0}'></tr>")
        rows = fd.parse_tmx_rows(page)
        self.assertEqual(len(rows), 3)
        periods = fd.corra_periods(rows, "2026-09-24")["2026-09-24"]
        self.assertEqual(periods[0], ["2026-10-01", "2026-10-31", 2.305])
        self.assertEqual(periods[1], ["2026-12-16", "2027-03-17", 2.78])  # IMM-onsdag til utløp
        self.assertEqual(len(periods), 2)  # pris 0 = ingen handel, hoppes over
        # Uten expiry_date regnes sluttdatoen som IMM-onsdagen tre måneder senere
        p = fd.corra_periods([{"symbol": "CRAU26", "settlement_price": 97.625}], "d")["d"][0]
        self.assertEqual((p[0], p[1]), ("2026-09-16", "2026-12-16"))

    def monthly(self, rates, year=2026, first_month=9):
        out = []
        for i, r in enumerate(rates):
            y, m = year + (first_month - 1 + i) // 12, (first_month - 1 + i) % 12 + 1
            out.append([*fd.month_span(y, m), r])
        return out

    def test_futures_rate_at_prefers_covering_short_period(self):
        from datetime import date as d
        periods = self.monthly([4.0, 4.1, 4.2]) + [["2026-09-16", "2026-12-16", 4.3]]
        self.assertEqual(fd.futures_rate_at(periods, d(2026, 10, 10)), 4.1)
        # Mellom periodene interpoleres det mellom midtpunkter; utenfor er det flatt
        self.assertEqual(fd.futures_rate_at([["2026-09-01", "2026-09-30", 4.0], ["2026-11-01", "2026-11-30", 4.2]], d(2026, 10, 16)), 4.1)
        self.assertEqual(fd.futures_rate_at(periods, d(2030, 1, 1)), 4.2)  # flatt fra siste midtpunkt (nov)
        self.assertIsNone(fd.futures_rate_at([], d(2026, 1, 1)))

    def test_futures_basis_handles_month_with_policy_change(self):
        from datetime import date as d
        # EFFR-kontrakten ligger 4 bp under midtpunktet. 17. sep heves renten 3,96 → 4,21;
        # september-kontrakten er da et snitt: 16 dager på 3,92 og 14 dager på 4,17.
        policy = {"2026-01-01": 3.96, "2026-09-17": 4.21}
        sep_blend = round((16 * 3.92 + 14 * 4.17) / 30, 4)
        series = {}
        for day in ("2026-08-10", "2026-08-20", "2026-09-10", "2026-09-25"):
            m = int(day[5:7])
            series[day] = [[*fd.month_span(2026, m), sep_blend if m == 9 else 3.92], [*fd.month_span(2026, m + 1), 4.17]]
        # Også 10. sep (før vedtaket) måles kontrakten mot den faktiske månedsrenten, som er kjent 25. sep
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-09-25"), -0.04, places=4)  # sep_blend er avrundet
        # Regnet 10. sep, uten kjennskap til vedtaket, ser september-kontrakten for høy ut (+0,077); august-dagene holder medianen
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-09-10"), -0.04, places=4)
        self.assertAlmostEqual(fd.futures_basis({"2026-09-10": series["2026-09-10"]}, policy, "2026-09-10"), sep_blend - 3.96, places=4)
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-08-20"), -0.04, places=6)
        self.assertIsNone(fd.futures_basis(series, {}, "2026-09-25"))
        # Banens startpunkt renses for vedtaket: nivået etter hevingen, ikke månedssnittet
        m = fd.futures_metrics(series["2026-09-25"], 4.21, -0.04, d(2026, 9, 25), None, policy)
        self.assertAlmostEqual(m["path"][0], 4.21, places=3)
        self.assertAlmostEqual(m["anchor"]["rate_front"], 4.17, places=3)
        self.assertEqual(fd.month_policy_average(policy, fd.month_span(2026, 8), "2026-08-20"), 3.96)
        self.assertIsNone(fd.month_policy_average({}, fd.month_span(2026, 8), "2026-08-20"))

    def test_futures_metrics_path_and_splice(self):
        from datetime import date as d
        # Sep–Nov 4,00, fra desember 4,50 (en heving priset i november), basis 0
        periods = self.monthly([4.0, 4.0, 4.0, 4.5, 4.5, 4.5])
        govt = [4.0] * 25
        govt[12], govt[24] = 4.6, 5.0  # statskurven stiger utover skjøten
        m = fd.futures_metrics(periods, 4.0, 0.0, d(2026, 9, 25), govt)
        self.assertEqual(m["path"][0], 4.0)
        self.assertEqual(m["path"][3], 4.5)
        self.assertEqual(m["implied"]["3m"], 50)
        self.assertEqual(m["horizon_months"], 5)
        # Etter siste kontrakt (feb 2027) følger banen statskurvens form fra skjøtepunktet
        self.assertAlmostEqual(m["path"][12], 4.5 + govt[12] - govt[5], places=6)
        self.assertEqual(m["anchor"]["kind"], "futures")
        # Uten statskurve holdes siste nivå
        self.assertEqual(fd.futures_metrics(periods, 4.0, 0.0, d(2026, 9, 25))["path"][24], 4.5)
        self.assertIsNone(fd.futures_metrics([], 4.0, 0.0, d(2026, 9, 25)))

    def test_meeting_implied_from_next_clean_month(self):
        from datetime import date as d
        # RBA 29. sep: september-kontrakten har bare én dag etter møtet, oktober er uten møte
        periods = self.monthly([4.355, 4.575, 4.695])
        r = fd.meeting_implied_futures(periods, "2026-09-29", ["2026-09-29", "2026-11-03"], 4.35, 0.005, today=d(2026, 9, 25))
        self.assertEqual(r, {"bp": 22, "move": "heving"})

    def test_meeting_implied_solves_partial_month(self):
        from datetime import date as d
        # Møte 10. oktober, nytt møte 15. november (november-kontrakten kan ikke brukes).
        # Oktober: 10 dager på 4,00 og 21 dager på 4,25 → kontrakt 4,169
        oct_rate = (10 * 4.0 + 21 * 4.25) / 31
        periods = self.monthly([4.0, round(oct_rate, 4), 4.4])
        r = fd.meeting_implied_futures(periods, "2026-10-10", ["2026-10-10", "2026-11-15"], 4.0, 0.0, today=d(2026, 9, 25))
        self.assertEqual(r["bp"], 25)
        # For få dager igjen i møtemåneden og møte i neste måned → ingen tall
        periods = self.monthly([4.0, 4.1, 4.4])
        self.assertIsNone(fd.meeting_implied_futures(periods, "2026-10-29", ["2026-10-29", "2026-11-15"], 4.0, 0.0, today=d(2026, 9, 25)))
        # Passert møte
        self.assertIsNone(fd.meeting_implied_futures(periods, "2026-09-01", ["2026-09-01"], 4.0, 0.0, today=d(2026, 9, 25)))

    def test_build_curve_prefers_futures_and_reprices_within_futures(self):
        govt_day = {"0.25": 4.05, "0.5": 4.1, "1": 4.2, "2": 4.4, "5": 4.5}
        series = {"2026-09-01": dict(govt_day), "2026-09-18": dict(govt_day), "2026-09-25": dict(govt_day)}
        policy = {"2026-01-01": 4.0}
        fut = {
            "2026-09-18": self.monthly([3.96] + [4.0] * 5),          # for en uke siden: ingenting priset
            "2026-09-25": self.monthly([3.96] + [4.25] * 5),         # nå: en heving priset fra oktober
        }
        curve = fd.build_curve("us", series, policy, fut)
        self.assertEqual(curve["kind"], "futures")
        self.assertEqual(curve["futures_date"], "2026-09-25")
        self.assertIn("fed funds", curve["source"])
        self.assertEqual(curve["govt_source"], fd.CURVE_SOURCES["us"][1])
        self.assertAlmostEqual(curve["anchor"]["basis"], -0.04)
        self.assertEqual(curve["path"][0], 4.0)
        self.assertEqual(curve["path"][3], 4.29)
        self.assertEqual(curve["repricing"]["w1"], 25)
        self.assertIsNone(curve["repricing"].get("m1"))  # ingen futures-historikk 30 dager tilbake
        self.assertEqual(curve["points"]["0.25"], 4.05)  # statskurvens punkter beholdes
        # Uten futures faller alt tilbake til statskurven
        self.assertEqual(fd.build_curve("us", series, policy, {})["kind"], "govt")


class RbaCurveTest(unittest.TestCase):
    def test_shift_zero_curve(self):
        zero = {"2026-08-31": {"0.25": 4.46, "1": 4.61, "2": 4.70, "10": 5.10}}
        daily = {
            "2026-08-31": {"0.083": 4.40, "2": 4.20, "10": 4.60},
            "2026-09-24": {"0.083": 4.42, "2": 4.40, "10": 4.70},  # front +2 bp, 2 år +20 bp, 10 år +10 bp
            "2026-09-25": {"2": 4.40},                              # 10 år mangler denne dagen
        }
        out = fd.shift_zero_curve(zero, daily, "2026-08-01")
        self.assertEqual(out["2026-08-31"], zero["2026-08-31"])  # F17-dato brukes direkte
        d = out["2026-09-24"]
        self.assertAlmostEqual(d["2"], 4.90)
        self.assertAlmostEqual(d["10"], 5.20)
        # 1 år ligger mellom 1 mnd (+0,02) og 2 år (+0,20): lineært i løpetid
        self.assertAlmostEqual(d["1"], 4.61 + 0.02 + (0.20 - 0.02) * (1 - 1 / 12) / (2 - 1 / 12), places=3)
        self.assertAlmostEqual(d["0.25"], 4.46 + 0.02 + (0.20 - 0.02) * (0.25 - 1 / 12) / (2 - 1 / 12), places=3)
        self.assertNotIn("0.083", d)  # vekselen lagres ikke
        # 25. sep mangler 1 mnd og 10 år: de tas fra dagen før (carry-forward), så 10 år følger sin egen endring
        self.assertAlmostEqual(out["2026-09-25"]["10"], 5.20)
        self.assertAlmostEqual(out["2026-09-25"]["2"], 4.90)
        # Uten noen nylig observasjon forskyves alt med det som finnes
        lone = fd.shift_zero_curve(zero, {"2026-08-31": daily["2026-08-31"], "2026-10-20": {"2": 4.40}}, "2026-08-01")
        self.assertAlmostEqual(lone["2026-10-20"]["10"], 5.30)
        # Dager før første F17-dato og uten daglige endringer hoppes over
        self.assertNotIn("2026-07-01", fd.shift_zero_curve(zero, {"2026-07-01": {"2": 4.0}}, "2026-01-01"))
        self.assertEqual(fd.shift_zero_curve(zero, {"2026-09-01": {"7": 1.0}}, "2026-01-01").get("2026-09-01"), None)

    def test_zero_curve_gives_smooth_path_without_synthetic_anchor(self):
        # Med tette løpetider fra 3 mnd trenger AUD verken syntetisk anker eller 1 mnd→2 år-interpolasjon
        points = {"0.25": 4.46, "0.5": 4.55, "0.75": 4.59, "1": 4.61, "1.25": 4.63, "1.5": 4.65, "1.75": 4.66,
                  "2": 4.67, "2.5": 4.69, "3": 4.70, "4": 4.74, "5": 4.78, "7": 4.90, "10": 5.05}
        m = fd.curve_metrics(points, 4.35)
        self.assertFalse(m["synthetic_anchor"])
        self.assertEqual(m["anchor"]["kind"], "marked")
        steps = [b - a for a, b in zip(m["path"], m["path"][1:])]
        self.assertTrue(all(abs(x) < 0.15 for x in steps), steps)  # ingen kink i banen

    def test_rba_zero_tenor_ids(self):
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY25D"], 0.25)
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY175D"], 1.75)
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY1000D"], 10)


class RbnzCurveTest(unittest.TestCase):
    def b2_workbook(self, id_label="Series Id"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{id_label}</t></si><si><t>INM.DP1.N</t></si><si><t>INM.DB03.NZZV</t></si>"
                       "<si><t>INM.DS01.NZZC</t></si><si><t>INM.DS10.NZZC</t></si><si><t>Unit</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData>'
                       '<row r="4"><c r="A4" t="s"><v>5</v></c></row>'
                       '<row r="5"><c r="A5" t="s"><v>0</v></c><c r="B5" t="s"><v>1</v></c><c r="C5" t="s"><v>2</v></c><c r="D5" t="s"><v>3</v></c><c r="E5" t="s"><v>4</v></c></row>'
                       '<row r="6"><c r="A6"><v>46288</v></c><c r="B6"><v>2.75</v></c><c r="C6"><v>3.19</v></c><c r="D6"><v>3.7</v></c><c r="E6"><v>4.7</v></c></row>'
                       '<row r="7"><c r="A7"><v>46289</v></c><c r="B7"><v>2.75</v></c><c r="C7"><v>3.21</v></c><c r="D7"><v>3.75</v></c><c r="E7" t="e"><v>#N/A</v></c></row>'
                       '</sheetData></worksheet>')
        return buf.getvalue()

    def test_parse_rbnz_b2(self):
        out = fd.parse_rbnz_b2(self.b2_workbook(), "2026-09-23")
        self.assertEqual(out, {"2026-09-23": {"0.25": 3.19, "1": 3.7, "10": 4.7}, "2026-09-24": {"0.25": 3.21, "1": 3.75}})
        self.assertEqual(fd.parse_rbnz_b2(self.b2_workbook(), "2026-09-25"), {})  # startdato filtrerer
        with self.assertRaises(RuntimeError):
            fd.parse_rbnz_b2(self.b2_workbook(id_label="Serie"), "2026-01-01")

    def test_fetch_curve_nz_requires_fresh_file(self):
        import os, tempfile, time as t
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b2.xlsx")
            os.environ["RBNZ_B2_FILE"] = path
            try:
                with self.assertRaises(RuntimeError):  # mangler
                    fd.fetch_curve_nz()
                with open(path, "wb") as f:
                    f.write(self.b2_workbook())
                self.assertIn("2026-09-24", fd.fetch_curve_nz())
                os.utime(path, (t.time() - 20 * 3600, t.time() - 20 * 3600))
                with self.assertRaises(RuntimeError):  # for gammel
                    fd.fetch_curve_nz()
            finally:
                del os.environ["RBNZ_B2_FILE"]


class SnbCurveTest(unittest.TestCase):
    def test_parse_snb_cube(self):
        text = ('\ufeff"CubeId";"rendeiduebd"\n"PublishingDate";"2026-09-01 14:30"\n\n"Date";"D0";"D1";"Value"\n'
                '"2026-08-28";"CHF";"1J";"-0.12"\n"2026-08-28";"CHF";"2J";\n"2026-08-28";"CHF";"10J";"0.47"\n'
                '"2026-08-28";"CHF";"20J";"0.61"\n"2026-08-31";"CHF";"1J";"-0.1"\n')
        self.assertEqual(fd.parse_snb_cube(text, fd.SNB_ZERO_TENORS),
                         {"2026-08-28": {"1": -0.12, "10": 0.47}, "2026-08-31": {"1": -0.1}})

    def test_parse_snb_rates_reads_numeric_typed_cells(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Interest_Rates" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>SNBLZ</t></si><si><t>SARH</t></si><si><t>R10</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData>'
                       '<row r="10"><c r="B10" t="s"><v>0</v></c><c r="H10" t="s"><v>1</v></c><c r="I10" t="s"><v>2</v></c></row>'
                       '<row r="12"><c r="A12" t="n"><v>46289.0</v></c><c r="B12" t="n"><v>0.0</v></c><c r="H12" t="n"><v>-0.04</v></c><c r="I12" t="n"><v>0.615</v></c></row>'
                       '<row r="13"><c r="A13" t="n"><v>46288.0</v></c><c r="H13" t="n"><v>-0.05</v></c><c r="I13" t="e"><v>#N/A</v></c></row>'
                       '</sheetData></worksheet>')
        out = fd.parse_snb_rates(buf.getvalue(), "2026-09-01")
        self.assertEqual(out, {"2026-09-24": {"0.003": -0.04, "10": 0.615}, "2026-09-23": {"0.003": -0.05}})

    def test_shifted_snb_curve_gets_synthetic_anchor(self):
        zero = {"2026-08-31": {"1": -0.10, "2": -0.05, "5": 0.26, "10": 0.47}}
        daily = {"2026-08-31": {"0.003": -0.04, "10": 0.47}, "2026-09-24": {"0.003": -0.04, "10": 0.615}}
        curve = fd.shift_zero_curve(zero, daily, "2026-08-01")["2026-09-24"]
        self.assertAlmostEqual(curve["10"], 0.615)
        self.assertAlmostEqual(curve["1"], -0.10 + 0.145 * (1 - 1 / 365) / (10 - 1 / 365), places=3)  # front uendret, 10 år +14,5 bp
        m = fd.curve_metrics(curve, 0.0)
        self.assertTrue(m["synthetic_anchor"])


class NzFuturesTest(unittest.TestCase):
    def test_parse_asx_bb_skips_illiquid(self):
        payload = {"data": {"items": [
            {"symbol": "BBZ2026", "dateExpiry": "2026-12-14", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 96.49, "priceLastTrade": 96.48},
            {"symbol": "BBH2027", "dateExpiry": "2027-03-08", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 96.09, "priceLastTrade": 96.09},
            {"symbol": "BBH2028", "dateExpiry": "2028-03-13", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 95.64, "priceLastTrade": None}]}}
        out = fd.parse_asx_bb(payload)
        self.assertEqual(out, {"2026-09-25": [["2026-12-14", "2027-03-14", 3.51], ["2027-03-08", "2027-06-06", 3.91]]})

    def test_add_monthly_front(self):
        fut = {"2026-09-25": [["2026-12-14", "2027-03-14", 3.51]], "2026-07-10": [["2026-09-14", "2026-12-13", 3.2]]}
        out = fd.add_monthly_front(fut, {"2026-06": 3.05, "2026-08": 3.10, "2026-10": None})
        self.assertEqual(out["2026-09-25"], [["2026-12-14", "2027-03-14", 3.51], ["2026-09-01", "2026-09-30", 3.10]])
        self.assertEqual(out["2026-07-10"][-1], ["2026-07-01", "2026-07-31", 3.05])
        self.assertEqual(fd.add_monthly_front(fut, {})["2026-09-25"], fut["2026-09-25"])

    def test_build_curve_from_futures_only(self):
        from datetime import date as d
        policy = {"2026-01-01": 2.75}
        fut = fd.add_monthly_front({"2026-09-25": [["2026-12-14", "2027-03-14", 3.51], ["2027-03-08", "2027-06-06", 3.91], ["2027-06-14", "2027-09-12", 4.2]]},
                                   {"2026-08": 3.05})
        curve = fd.build_curve("nz", {}, policy, fut)
        self.assertEqual(curve["kind"], "futures")
        self.assertEqual(curve["date"], "2026-09-25")
        self.assertEqual(curve["points"], {})
        self.assertIsNone(curve["govt_source"])
        self.assertIn("flat etter", curve["source"])
        # basis = OECD-månedsrente − styringsrente = 0,30; front renset → bane starter på styringsrenten
        self.assertAlmostEqual(curve["anchor"]["basis"], 0.30)
        self.assertAlmostEqual(curve["path"][0], 2.75)
        self.assertAlmostEqual(curve["path"][6], 3.91 - 0.30)  # mars 2027-kontrakten dekker midten av mars
        self.assertEqual(curve["repricing"], {})
        self.assertIsNone(fd.build_curve("nz", {}, policy, {}))
        self.assertIsNone(fd.build_curve("nz", {}, {}, fut))


if __name__ == "__main__":
    unittest.main()


class OverrideTest(unittest.TestCase):
    """Manuelt registrerte vedtak overstyrer serien til den har fått vedtaket med seg."""

    def test_override_within_grace(self):
        # Serien fører virkningsdato: 4,25 t.o.m. 24.9, vedtaket 4,50 annonsert 23.9
        series = {"2026-09-22": 4.25, "2026-09-23": 4.25, "2026-09-24": 4.25}
        ov = {"date": "2026-09-23", "rate": 4.5}
        out, st = fd.apply_policy_override(series, ov, "2026-09-25")
        self.assertEqual(st, "brukt")
        self.assertEqual((out["2026-09-22"], out["2026-09-23"], out["2026-09-24"]), (4.25, 4.5, 4.5))
        self.assertEqual(series["2026-09-24"], 4.25)  # original urørt
        # Serien har ikke nådd vedtaksdatoen ennå
        self.assertEqual(fd.apply_policy_override({"2026-09-20": 4.25}, ov, "2026-09-25")[1], "brukt")
        # curve_metrics ankrer på 4,50: flat kurve på 4,5 gir null priset endring
        m = fd.curve_metrics({"0.25": 4.5, "1": 4.5, "2": 4.5}, fd.latest(out)[1])
        self.assertEqual(m["implied"]["12m"], 0)

    def test_override_confirmed_or_conflicting(self):
        ov = {"date": "2026-09-23", "rate": 4.5}
        self.assertEqual(fd.apply_policy_override({"2026-09-24": 4.5}, ov, "2026-09-25")[1], "bekreftet")
        # Mer enn fem dager etter vedtaket viser serien fortsatt 4,25: serien vinner, fila avviker
        series = {"2026-09-24": 4.25, "2026-09-30": 4.25}
        out, st = fd.apply_policy_override(series, ov, "2026-10-01")
        self.assertEqual((st, out), ("avvik", series))
        # Fremtidig eller ufullstendig post ignoreres
        self.assertEqual(fd.apply_policy_override(series, {"date": "2026-10-05", "rate": 4.5}, "2026-10-01")[1], None)
        self.assertEqual(fd.apply_policy_override(series, {"date": "2026-09-23"}, "2026-10-01")[1], None)
        self.assertEqual(fd.apply_policy_override(series, None, "2026-10-01"), (series, None))


class PolicySourcesTest(unittest.TestCase):
    def test_merge_policy_official_wins_from_first_date(self):
        bis = {"2026-09-10": 4.25, "2026-09-15": 4.25, "2026-09-22": 4.25}
        official = {"2026-09-15": 4.25, "2026-09-25": 4.5}
        out = fd.merge_policy(bis, official)
        self.assertEqual(out, {"2026-09-10": 4.25, "2026-09-15": 4.25, "2026-09-22": 4.25, "2026-09-25": 4.5})
        # Trapp (ECB): endringsdato 12.3 gjelder for alle senere dager, også BIS-dager med annen verdi
        self.assertEqual(fd.merge_policy({"2026-03-11": 2.75, "2026-03-13": 2.75}, {"2026-03-12": 2.5}),
                         {"2026-03-11": 2.75, "2026-03-12": 2.5, "2026-03-13": 2.5})
        self.assertEqual(fd.merge_policy(bis, {}), bis)

    def test_unconfirmed_meeting(self):
        meetings = ["2026-08-13", "2026-09-23", "2026-11-05"]
        self.assertEqual(fd.unconfirmed_meeting(meetings, "2026-09-22", "2026-09-25"), "2026-09-23")
        self.assertIsNone(fd.unconfirmed_meeting(meetings, "2026-09-23", "2026-09-25"))
        self.assertIsNone(fd.unconfirmed_meeting(meetings, "2026-09-24", "2026-09-22"))  # møtet er ikke kommet
        self.assertEqual(fd.unconfirmed_meeting(meetings, None, "2026-09-25"), "2026-09-23")

    def test_expand_daily(self):
        out = fd.expand_daily({"2026-09-16": 2.5, "2026-09-23": 2.25}, "2026-09-25")
        self.assertEqual(out, {"2026-09-16": 2.5, "2026-09-17": 2.5, "2026-09-18": 2.5, "2026-09-21": 2.5, "2026-09-22": 2.5,
                               "2026-09-23": 2.25, "2026-09-24": 2.25, "2026-09-25": 2.25})  # helg hoppes over
        self.assertEqual(fd.expand_daily({}, "2026-09-25"), {})

    def test_parsers(self):
        nb = ('FREQ;Frequency;TIME_PERIOD;OBS_VALUE;CALC_METHOD\nB;Business;2026-09-23;4.25;\nB;Business;2026-09-24;4.25;\n')
        self.assertEqual(fd.parse_norges_bank_policy(nb), {"2026-09-23": 4.25, "2026-09-24": 4.25})
        valet = {"observations": [{"d": "2026-09-24", "V39079": {"v": "2.25"}}, {"d": "2026-09-23", "V39079": {"v": None}}]}
        self.assertEqual(fd.parse_valet(valet, "V39079"), {"2026-09-24": 2.25})
        ecb = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nFM.B.U2.EUR.4F.KR.DFR.LEV,B,2025-03-12,2.5,A\n"
        self.assertEqual(fd.parse_ecb_csv(ecb), {"2025-03-12": 2.5})
        boe = "DATE,IUDBEDR\n23 Sep 2026,3.75\n24 Sep 2026,3.75\nrubbish,\n"
        self.assertEqual(fd.parse_boe_csv(boe), {"2026-09-23": 3.75, "2026-09-24": 3.75})


class BrentContractTest(unittest.TestCase):
    def test_front_rolls_to_next_when_front_is_stale(self):
        fut = {"front": {"2026-09-24": 105.3, "2026-09-25": 104.0}, "next": {"2026-09-24": 103.0, "2026-09-25": 102.5},
               "front_label": "nov", "next_label": "des"}
        self.assertEqual(fd.brent_front_and_next(fut), (fut["front"], "nov", fut["next"], "des"))
        fut["next"]["2026-09-30"] = 101.0  # front utløpt: neste kontrakt har nyere kurs
        front, label, nxt, nlabel = fd.brent_front_and_next(fut)
        self.assertEqual((label, nxt, nlabel), ("des", {}, None))
        self.assertEqual(front, fut["next"])
        self.assertEqual(fd.brent_front_and_next({"front": {}, "next": {}, "front_label": "a", "next_label": "b"})[0], {})

    def test_premium_series_and_trailing_mean(self):
        dated = {"2026-09-18": 118.0, "2026-09-19": 117.0, "2026-09-22": 114.89}
        fut = {"2026-09-18": 104.0, "2026-09-22": 99.25, "2026-09-25": 105.3}
        prem = fd.premium_series(dated, fut)
        self.assertEqual(prem, {"2026-09-18": 14.0, "2026-09-22": 15.64})  # bare felles datoer
        self.assertEqual(fd.trailing_mean(prem), 14.82)
        self.assertEqual(fd.trailing_mean({"2026-06-01": 2.0, "2026-09-22": 16.0}), 16.0)  # 1. juni er utenfor 90 dager
        self.assertIsNone(fd.trailing_mean({}))
        self.assertEqual(fd.brent_label("BZX26.NYM"), "nov. 2026-kontrakten (BZX26)")

    def test_front_contract_rolls_after_expiry(self):
        from datetime import date as d
        self.assertEqual(fd.brent_front_contracts(d(2026, 9, 25)), ["BZX26.NYM", "BZZ26.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 10, 1)), ["BZZ26.NYM", "BZF27.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 11, 30))[0], "BZF27.NYM")

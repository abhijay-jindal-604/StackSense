import re
import unittest
from datetime import date

from stacksense.kb import eol
from stacksense.kb.sources import SOURCES


class EolTable(unittest.TestCase):
    def test_size_and_unique_keys(self):
        self.assertGreaterEqual(len(eol.ROWS), 56)
        keys = [r.key for r in eol.ROWS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_row_integrity(self):
        for r in eol.ROWS:
            self.assertRegex(r.date, r"^\d{4}-\d{2}-\d{2}$", r.key)
            date.fromisoformat(r.date)
            if r.mainstream_end:
                date.fromisoformat(r.mainstream_end)
                self.assertLessEqual(r.mainstream_end, r.date, r.key)
            self.assertIn(r.source, SOURCES, r.key)
            self.assertIn(r.conf, (eol.V, eol.U), r.key)
            self.assertIn(r.kind, ("eol", "extended_end", "retired", "end_of_sale", "archived", "deprecated"), r.key)
            self.assertTrue(r.replacement and r.label, r.key)

    def test_anchor_is_fixed(self):
        self.assertEqual(eol.KB_DATE, date(2026, 11, 12))

    def test_plan_dates(self):
        want = {("nodejs", "20"): "2026-04-30", ("postgresql", "14"): "2026-11-12", ("dotnet", "8"): "2026-11-10",
                ("sqlserver", "2019"): "2030-01-08", ("mysql", "8.0"): "2026-04-30",
                ("azure_ad_b2c", None): "2025-05-01", ("gcp_iot_core", None): "2023-08-16"}
        for (p, v), d in want.items():
            self.assertEqual(eol.lookup(p, v).date, d, (p, v))


class Lookup(unittest.TestCase):
    def test_version_capture_forms(self):
        cases = [("SQL Server", "2019", "sqlserver_2019"), ("node", "18", "nodejs_18"), ("Node.js", "v20.11.1", "nodejs_20"),
                 ("postgres", "12", "postgresql_12"), ("python", "3.10.4", "python_3_10"),
                 ("python", "2.7", "python_2_7"), (".NET Framework", "4.6.1", "dotnet_framework_4_6_1"),
                 ("spring boot", "2.5.1", "spring_boot_2"), ("windows server", "2012", "windows_server_2012")]
        for p, v, key in cases:
            self.assertEqual(eol.lookup(p, v).key, key, (p, v))

    def test_prefix_is_numeric_not_textual(self):
        self.assertIsNone(eol.lookup("python", "3.1"))       # 3.1 is not 3.10
        self.assertIsNone(eol.lookup("python", "3"))         # a bare major gives no verdict
        self.assertIsNone(eol.lookup("nodejs", "2"))         # not 20 or 22
        self.assertIsNone(eol.lookup("sqlserver", None))     # no version, no verdict
        self.assertIsNone(eol.lookup("nonexistent", "1"))

    def test_service_rows_need_no_version(self):
        self.assertEqual(eol.lookup("minio").kind, "archived")
        self.assertEqual(eol.lookup("azure cache redis").date, "2028-09-30")
        self.assertEqual(eol.lookup("azure_cache_redis", "enterprise").date, "2027-03-31")

    def test_status_on(self):
        old = eol.status_on(eol.lookup("php", "7.4"))
        self.assertEqual(old["state"], "ended")
        self.assertLess(old["days"], 0)
        self.assertEqual(old["anchor"], "2026-11-12")
        self.assertEqual(eol.status_on(eol.lookup("postgresql", "14"))["state"], "ended")   # EOL on the anchor day
        self.assertEqual(eol.status_on(eol.lookup("postgresql", "15"))["state"], "ending_soon")
        self.assertEqual(eol.status_on(eol.lookup("postgresql", "17"))["state"], "supported")
        s19 = eol.status_on(eol.lookup("sqlserver", "2019"))
        self.assertEqual(s19["state"], "supported")
        self.assertTrue(s19["mainstream_ended"])
        self.assertIsNone(eol.status_on(eol.lookup("php", "7.4"))["mainstream_ended"])

    def test_status_moves_with_anchor_only(self):
        row = eol.lookup("nodejs", "22")
        self.assertEqual(eol.status_on(row, date(2027, 5, 1))["state"], "ended")
        self.assertEqual(eol.status_on(row)["state"], "ending_soon")
        self.assertEqual(eol.status_on(row), eol.status_on(row))

    def test_verdict(self):
        self.assertEqual(eol.verdict("node", "18")["state"], "ended")
        self.assertIsNone(eol.verdict("node", None))

    def test_lookup_deterministic(self):
        a = [eol.lookup(r.product, r.cycle or None) for r in eol.ROWS]
        b = [eol.lookup(r.product, r.cycle or None) for r in eol.ROWS]
        self.assertEqual(a, b)
        for r in eol.ROWS:
            if re.match(r"^\d", r.cycle):
                self.assertEqual(eol.lookup(r.product, r.cycle).key, r.key, r.key)


if __name__ == "__main__":
    unittest.main()

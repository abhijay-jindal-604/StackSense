import json
import pathlib
import unittest
from datetime import date

from stacksense import existing
from stacksense.kb import eol

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _systems(rel):
    d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    return d["infrastructure"]["existing_systems"]


def _by(report, pid):
    return [m for m in report.matches if m.pattern_id == pid]


class P5(unittest.TestCase):
    def setUp(self):
        self.r = existing.analyse(_systems("scenarios/public/P5.json"))

    def test_all_recognised(self):
        self.assertEqual(self.r.unmatched, ())

    def test_kinds_and_reuse(self):
        kinds = {m.kind for m in self.r.matches}
        self.assertTrue({"entra_id", "sqlserver", "microsoft_365", "on_prem"} <= kinds)
        self.assertIn("identity:entra_id", _by(self.r, "entra_id")[0].reuse_targets)
        self.assertIn("database:sqlserver", _by(self.r, "sqlserver")[0].reuse_targets)
        self.assertIn("saas:microsoft_graph", _by(self.r, "microsoft_365")[0].reuse_targets)

    def test_multi_hit_string_gives_product_and_qualifier(self):
        sql = _by(self.r, "sqlserver")[0]
        onp = _by(self.r, "on_prem")[0]
        self.assertEqual(sql.raw, onp.raw)
        self.assertEqual(sql.version, "2019")
        self.assertEqual(onp.family, "infrastructure")
        self.assertIsNone(onp.eol)

    def test_sqlserver_2019_judged_with_anchor(self):
        ev = _by(self.r, "sqlserver")[0].eol
        self.assertEqual(ev["state"], "supported")
        self.assertTrue(ev["mainstream_ended"])
        self.assertEqual(ev["anchor"], eol.KB_DATE.isoformat())

    def test_note_names_the_raw_string(self):
        for m in self.r.matches:
            self.assertTrue(m.integration_note.startswith(m.raw + ": "), m.pattern_id)


class Eol(unittest.TestCase):
    def test_h09_all_ended(self):
        r = existing.analyse(_systems("scenarios/edge/H09_eol_legacy_systems.json"))
        self.assertEqual(r.unmatched, ())
        evs = [m.eol for m in r.matches if m.eol]
        self.assertEqual(len(evs), 4)
        self.assertTrue(all(e["state"] == "ended" for e in evs))

    def test_h10_dates_present(self):
        r = existing.analyse(_systems("scenarios/edge/H10_p5_eol_azure.json"))
        evs = [m.eol for m in r.matches if m.eol]
        self.assertEqual(len(evs), 3)
        self.assertTrue(all(e["state"] in ("ended", "ending_soon") and e["date"] for e in evs))
        self.assertTrue(any(m.pattern_id == "azure_ad_b2c" for m in r.matches))

    def test_anchor_override_changes_state(self):
        early = existing.analyse([".NET 8 services"], today_anchor=date(2026, 1, 1))
        late = existing.analyse([".NET 8 services"])
        self.assertNotEqual(early.matches[0].eol["state"], "ended")
        self.assertEqual(late.matches[0].eol["state"], "ended")
        self.assertEqual(early.matches[0].eol["anchor"], "2026-01-01")


class Edge(unittest.TestCase):
    def test_unmatched_and_order(self):
        r = existing.analyse(["Zorblax 9000", "MySQL 5.7", "  ", "", "Flurbo"])
        self.assertEqual(r.unmatched, ("Zorblax 9000", "Flurbo"))
        self.assertEqual([m.pattern_id for m in r.matches], ["mysql"])

    def test_empty_and_none(self):
        self.assertEqual(existing.analyse(None), existing.ExistingReport())
        self.assertEqual(existing.analyse([]), existing.ExistingReport())

    def test_negation(self):
        r = existing.analyse(["no Oracle database here", "without MySQL 5.7"])
        self.assertEqual(r.matches, ())
        self.assertEqual(len(r.unmatched), 2)

    def test_deterministic(self):
        s = ["Windows Server 2012 R2", "PHP 7.4 monolith", "On-prem SQL Server 2019", "x"]
        self.assertEqual(existing.analyse(s), existing.analyse(list(s)))


if __name__ == "__main__":
    unittest.main()

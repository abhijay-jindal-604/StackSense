import unittest

from stacksense import engine, output


class EngineSkeletonTests(unittest.TestCase):
    def test_garbage_never_raises_and_conforms(self):
        for raw in (None, [], "x", 5, {}, {"project": 5}, {"scenario_id": 7}):
            r = engine.recommend(raw)
            self.assertEqual(output.check(r), [], repr(raw))
            self.assertEqual(r["status"], "invalid_input", repr(raw))

    def test_valid_input_produces_stack(self):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "scenarios" / "public" / "P1.json"
        r = engine.recommend(json.loads(p.read_text(encoding="utf-8")))
        self.assertEqual(output.check(r), [])
        self.assertIsNotNone(r["stack"])
        self.assertIn(r["status"], ("ok", "ok_with_warnings"))
        self.assertNotIn("ENGINE_NOT_IMPLEMENTED", [w["code"] for w in r["warnings"]])

    def test_infeasible_has_critical_and_nearest_feasible(self):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "scenarios" / "edge" / "H33_rbi_with_us_residency.json"
        r = engine.recommend(json.loads(p.read_text(encoding="utf-8")))
        self.assertEqual(r["status"], "infeasible")
        self.assertIsNone(r["stack"])
        self.assertEqual(output.check(r), [])
        self.assertIn("RESIDENCY_COMPLIANCE_CONFLICT", [w["code"] for w in r["warnings"]])
        self.assertIn("infrastructure.data_residency", [n["field"] for n in r["nearest_feasible"]])
        self.assertIn("rbi_localisation", r["summary"])

    def test_internal_error_is_contained(self):
        from unittest import mock
        with mock.patch.object(engine, "_pipeline", side_effect=RuntimeError("boom")):
            r = engine.recommend({"scenario_id": "E1"})
        self.assertEqual(r["status"], "infeasible")
        self.assertTrue(engine.is_internal_error(r))
        self.assertEqual(output.check(r), [])

    def test_load_error(self):
        from stacksense.io import LoadedScenario
        r = engine.recommend_loaded(LoadedScenario("a.json", None, "bad json", []))
        self.assertEqual(r["status"], "invalid_input")
        self.assertEqual(r["validation_errors"][0]["field"], "$")
        self.assertEqual(output.check(r), [])


class ScenarioIdTests(unittest.TestCase):
    def test_id_comes_from_validated_profile(self):
        r = engine.recommend({"scenario_id": "  Z1  "})
        self.assertEqual(r["scenario_id"], "Z1")
        self.assertIsNone(engine.recommend({"scenario_id": ["x"]})["scenario_id"])
        self.assertIsNone(engine.recommend(None)["scenario_id"])


if __name__ == "__main__":
    unittest.main()


class EolAnchorAssumptionTests(unittest.TestCase):
    def test_anchor_assumption_added_once_when_eol_judged(self):
        import json
        from pathlib import Path
        from stacksense.kb import eol
        raw = json.loads((Path(__file__).resolve().parent.parent / "scenarios" / "public" / "P5.json").read_text())
        text = f"EOL judgements use the knowledge-base date {eol.KB_DATE.isoformat()} (kb.eol.KB_DATE), not the system clock."
        out = engine.recommend(raw)
        self.assertEqual(out["assumptions"].count(text), 1)
        raw["infrastructure"]["existing_systems"] = []
        self.assertNotIn(text, engine.recommend(raw)["assumptions"])

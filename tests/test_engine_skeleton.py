import unittest

from stacksense import engine, output


class EngineSkeletonTests(unittest.TestCase):
    def test_garbage_never_raises_and_conforms(self):
        for raw in (None, [], "x", 5, {}, {"project": 5}, {"scenario_id": 7}):
            r = engine.recommend(raw)
            self.assertEqual(output.check(r), [], repr(raw))
            self.assertEqual(r["status"], "invalid_input", repr(raw))

    def test_valid_input_stub(self):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "scenarios" / "public" / "P1.json"
        r = engine.recommend(json.loads(p.read_text(encoding="utf-8")))
        self.assertEqual(output.check(r), [])
        self.assertIsNone(r["stack"])
        self.assertIn("ENGINE_NOT_IMPLEMENTED", [w["code"] for w in r["warnings"]])

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

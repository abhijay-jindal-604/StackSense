"""diff.py (plan 3.21) and sensitivity.py (plan 11.3)."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from stacksense import diff, engine, output, sensitivity

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"


def load(sid: str) -> dict:
    return json.loads((PUBLIC / f"{sid}.json").read_text(encoding="utf-8"))


class DiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p1 = load("P1")
        cls.out1 = engine.recommend(copy.deepcopy(cls.p1), trace=False)

    def test_identical_outputs_have_no_changes(self):
        d = diff.diff(self.out1, self.out1, scenario_a=self.p1, scenario_b=self.p1)
        self.assertEqual(d["changed_layers"], [])
        self.assertEqual(d["changed_fields"], [])
        self.assertFalse(d["status"]["changed"] or d["cost"]["changed"])
        self.assertEqual(d["warnings"], {"added": [], "removed": []})
        for k in diff.CORE_LAYERS:
            self.assertIn(k, d["layers"])

    def test_drivers_are_changed_inputs_cited_in_driven_by(self):
        p6 = load("P6")
        v = copy.deepcopy(p6)
        v["infrastructure"]["open_source_only"] = True
        a = engine.recommend(copy.deepcopy(p6), trace=False)
        b = engine.recommend(copy.deepcopy(v), trace=False)
        d = diff.diff(a, b, scenario_a=p6, scenario_b=v)
        self.assertEqual(d["changed_fields"], ["infrastructure.open_source_only"])
        self.assertTrue(d["changed_layers"])
        for key in d["changed_layers"]:
            self.assertTrue(set(d["layers"][key]["drivers"]) <= {"infrastructure.open_source_only"}, key)

    def test_outputs_only_and_render(self):
        b = copy.deepcopy(self.out1)
        b["status"] = "ok_with_warnings"
        b["stack"]["hosting"] = dict(b["stack"]["hosting"], choice="Somewhere else", driven_by=["priorities.cost"])
        d = diff.diff(self.out1, b)
        self.assertNotIn("changed_fields", d)
        self.assertEqual(d["changed_layers"], ["hosting"])
        lines = diff.render(d)
        self.assertTrue(any(l.startswith("hosting: ") and "-> Somewhere else" in l for l in lines))
        self.assertTrue(any(l.startswith("status: ") and "->" in l for l in lines))

    def test_repeated_warning_code_counts(self):
        b = copy.deepcopy(self.out1)
        b["warnings"] = list(b["warnings"]) + [{"code": "SUPPORTING_GAP", "severity": "warning", "message": "x",
                                                 "fields": []}] * 2
        self.assertEqual(diff.diff(self.out1, b)["warnings"]["added"], ["SUPPORTING_GAP", "SUPPORTING_GAP"])

    def test_changed_fields_flatten(self):
        self.assertEqual(diff.changed_fields({"a": {"b": 1, "c": [1]}}, {"a": {"b": 2, "c": [1], "d": 0}}),
                         ["a.b", "a.d"])
        self.assertTrue(diff.is_output(self.out1))
        self.assertFalse(diff.is_output(self.p1))


class SensitivityTests(unittest.TestCase):
    def test_rows_cover_every_flip_and_are_deterministic(self):
        p3 = load("P3")
        r1 = sensitivity.run(copy.deepcopy(p3))
        r2 = sensitivity.run(copy.deepcopy(p3))
        self.assertEqual(r1, r2)
        self.assertEqual([r["field"] for r in r1["rows"]], [f for f, _ in sensitivity.FLIPS])
        self.assertTrue(any(r.get("effect") for r in r1["rows"]))
        md = sensitivity.markdown(r1)
        self.assertIn("| `scale.geographic_spread` |", md)

    def test_variants_produce_conformant_outputs(self):
        p2 = load("P2")
        for path, spec in sensitivity.FLIPS:
            v = copy.deepcopy(p2)
            sensitivity._set(v, path, sensitivity.flip_value(p2, path, spec)[1])
            out = engine.recommend(v)
            self.assertEqual(output.check(out), [], path)


if __name__ == "__main__":
    unittest.main()

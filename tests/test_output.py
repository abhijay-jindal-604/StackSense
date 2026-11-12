import copy
import json
import unittest

from stacksense import output


def comp(choice="X", alts=True):
    return {
        "choice": choice,
        "justification": "Fits team.languages=[python].",
        "driven_by": ["team.languages"],
        "alternatives": [{"choice": "Y", "why_not": "Heavier."}] if alts else [],
        "tradeoffs": ["Some downside."],
    }


def ok_result():
    return output.build(
        status="ok", scenario_id="T1", summary="A monolith.", architecture_style="monolith",
        stack={
            "frontend": comp("Astro"), "backend": comp("Django"),
            "database": comp("None"), "hosting": comp("Fly.io"),
            "supporting": [dict(comp("Redis"), layer="cache"), dict(comp("Sentry"), layer="observability")],
        },
        estimated_monthly_cost_usd={"min": 0, "max": 20, "assumptions": ["Free tiers."]},
        warnings=[{"code": "B", "severity": "info", "message": "m", "fields": ["a.b"]}],
        assumptions=["a"], budget_verdict={"within": True},
    )


class OutputCheckTests(unittest.TestCase):
    def test_valid_ok(self):
        self.assertEqual(output.check(ok_result()), [])

    def test_valid_ok_with_warnings(self):
        r = ok_result()
        r["warnings"] = output.sort_warnings(r["warnings"] + [{"code": "A", "severity": "critical", "message": "m", "fields": []}])
        r["status"] = "ok_with_warnings"
        self.assertEqual(output.check(r), [])

    def test_valid_invalid_input(self):
        r = output.build(status="invalid_input", validation_errors=[{"field": "$", "message": "x"}], scenario_id="Q")
        self.assertIsNone(r["stack"])
        self.assertEqual(output.check(r), [])
        self.assertEqual(list(r)[:2], ["scenario_id", "engine_version"])

    def test_valid_infeasible(self):
        r = output.build(status="infeasible", scenario_id="I",
                         warnings=[{"code": "HARD", "severity": "critical", "message": "m", "fields": []}],
                         stack=ok_result()["stack"])
        self.assertIsNone(r["stack"])  # forced to null
        self.assertEqual(output.check(r), [])

    def test_key_order_and_trace(self):
        r = ok_result()
        self.assertEqual(list(r), [k for k in output.KEY_ORDER if k != "decision_trace"])
        r2 = output.build(status="invalid_input", validation_errors=[{"field": "a", "message": "b"}], decision_trace={"t": 1})
        self.assertEqual(list(r2)[-1], "decision_trace")
        json.loads(output.dumps(r2))

    def test_dumps(self):
        s = output.dumps({"a": "é"})
        self.assertTrue(s.endswith("\n"))
        self.assertIn("é", s)
        self.assertIn('\n  "a"', s)

    def _broken(self, mutate, expect):
        r = ok_result()
        mutate(r)
        errs = output.check(r)
        self.assertTrue(any(expect in e for e in errs), (expect, errs))

    def test_hand_broken(self):
        S = lambda r: r["stack"]
        cases = [
            (lambda r: r.update(status="bogus"), "status: must be one of"),
            (lambda r: r.update(architecture_style="blob"), "architecture_style"),
            (lambda r: r.update(architecture_style="other"), "'other'"),
            (lambda r: S(r).pop("database"), "stack.database: missing"),
            (lambda r: S(r)["backend"].pop("justification"), "justification"),
            (lambda r: S(r)["backend"].update(driven_by=[]), "driven_by"),
            (lambda r: S(r)["hosting"].update(alternatives=[]), "at least one"),
            (lambda r: S(r)["hosting"].update(alternatives=[{"choice": "a"}]), "why_not"),
            (lambda r: S(r)["supporting"][0].update(layer="forms"), "layer"),
            (lambda r: S(r)["supporting"].reverse(), "fixed layer order"),
            (lambda r: S(r)["frontend"].update(tradeoffs="x"), "tradeoffs"),
            (lambda r: r["estimated_monthly_cost_usd"].update(min=50), "min must be <= max"),
            (lambda r: r["estimated_monthly_cost_usd"].update(max=1.5), "integers"),
            (lambda r: r["estimated_monthly_cost_usd"].update(max=True), "integers"),
            (lambda r: r.pop("estimated_monthly_cost_usd"), "estimated_monthly_cost_usd"),
            (lambda r: r.update(warnings="x"), "warnings: must be a list"),
            (lambda r: r.update(validation_errors=[{"field": "a", "message": "m"}]), "must be empty"),
            (lambda r: r.update(assumptions=[1]), "assumptions"),
            (lambda r: r.update(llm_used="no"), "llm_used"),
            (lambda r: r.pop("stack"), "stack: missing"),
            (lambda r: r.update(summary=None), "summary"),
        ]
        for mutate, expect in cases:
            with self.subTest(expect=expect):
                self._broken(mutate, expect)

    def test_broken_status_rules(self):
        r = output.build(status="invalid_input", validation_errors=[{"field": "a", "message": "m"}])
        r["stack"] = ok_result()["stack"]
        self.assertTrue(any("must be null" in e for e in output.check(r)))
        r = output.build(status="invalid_input")
        self.assertTrue(any("non-empty" in e for e in output.check(r)))
        r = ok_result()
        r["status"] = "ok_with_warnings"
        self.assertTrue(any("needs at least one" in e for e in output.check(r)))
        r = ok_result()
        r["warnings"].append({"code": "C", "severity": "warning", "message": "m", "fields": []})
        r["warnings"] = output.sort_warnings(r["warnings"])
        self.assertTrue(any("must not carry" in e for e in output.check(r)))
        self.assertEqual(output.check([]), ["result: must be an object"])
        self.assertEqual(output.check(copy.deepcopy(ok_result())), [])

    def test_infeasible_with_stack_fails(self):
        r = output.build(status="infeasible")
        r["stack"] = ok_result()["stack"]
        self.assertTrue(output.check(r))


class WarningShapeTests(unittest.TestCase):
    def test_t_warn_00_shape_and_order(self):
        ws = [
            {"code": "Z", "severity": "info", "message": "m", "fields": []},
            {"code": "B", "severity": "warning", "message": "m", "fields": ["a"]},
            {"code": "A", "severity": "warning", "message": "m", "fields": []},
            {"code": "Y", "severity": "critical", "message": "m", "fields": []},
        ]
        r = output.build(status="ok_with_warnings", warnings=ws)
        self.assertEqual([w["code"] for w in r["warnings"]], ["Y", "A", "B", "Z"])
        for w in r["warnings"]:
            self.assertEqual(sorted(w), ["code", "fields", "message", "severity"])
        r2 = ok_result()
        r2["status"] = "ok_with_warnings"
        r2["warnings"] = ws  # unsorted
        self.assertTrue(any("sorted" in e for e in output.check(r2)))
        r2["warnings"] = [{"code": "A", "severity": "fatal", "message": "m", "fields": "x"}]
        errs = output.check(r2)
        self.assertTrue(any("severity" in e for e in errs) and any("fields" in e for e in errs))


class ReviewRegressionTests(unittest.TestCase):
    def test_summary_non_empty(self):
        r = ok_result()
        r["summary"] = "  "
        self.assertTrue(any(e.startswith("summary") for e in output.check(r)))
        self.assertNotEqual(output.build(status="ok")["summary"], "")

    def test_infeasible_needs_critical(self):
        r = output.build(status="infeasible", warnings=[{"code": "A", "severity": "info", "message": "m", "fields": []}])
        self.assertTrue(any("critical" in e for e in output.check(r)))

    def test_cost_assumptions_non_empty(self):
        for bad in ([], [""], ["ok", "  "]):
            r = ok_result()
            r["estimated_monthly_cost_usd"]["assumptions"] = bad
            self.assertTrue(any("assumptions" in e for e in output.check(r)), bad)
        r = output.build(status="invalid_input", validation_errors=[{"field": "$", "message": "x"}])
        self.assertEqual(r["estimated_monthly_cost_usd"]["assumptions"], ["No cost estimate: no stack was produced."])


if __name__ == "__main__":
    unittest.main()

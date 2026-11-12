import copy
import json
import math
import random
import unittest
from pathlib import Path

from stacksense.validate import Validated, validate

ROOT = Path(__file__).resolve().parent.parent


def base():
    with open(ROOT / "scenarios" / "public" / "P2.json", encoding="utf-8") as fh:
        return json.load(fh)


def fields(v):
    return [e["field"] for e in v.errors]


class ValidateTests(unittest.TestCase):
    def test_valid_returns_dataclass(self):
        v = validate(base())
        self.assertIsInstance(v, Validated)
        self.assertEqual(v.errors, [])
        self.assertEqual(v.profile["scenario_id"], "P2")
        self.assertIn("project.type", v.provided)
        self.assertNotIn("scale.traffic_pattern", v.provided - {"scale.traffic_pattern"})

    def test_blocker_null_p95(self):
        raw = base()
        raw["requirements"]["p95_latency_ms"] = None
        v = validate(raw)
        self.assertEqual(v.errors, [])
        self.assertIsNone(v.profile["requirements.p95_latency_ms"])
        self.assertIn("requirements.p95_latency_ms", v.provided)
        self.assertEqual(sum("p95_latency_ms" in a for a in v.assumptions), 1)

    def test_absent_p95_single_assumption(self):
        raw = base()
        raw["requirements"].pop("p95_latency_ms", None)
        v = validate(raw)
        self.assertEqual(sum("p95_latency_ms" in a for a in v.assumptions), 1)

    def test_val01_missing_required_all_reported(self):
        v = validate({})
        for p in ["project.type", "project.platforms", "scale.users_at_launch", "scale.users_12_months",
                  "team.size", "team.experience", "team.languages", "budget.monthly_infra_usd",
                  "timeline.mvp_weeks"]:
            self.assertIn(p, fields(v))

    def test_val02_null_required(self):
        raw = base()
        raw["team"]["size"] = None
        v = validate(raw)
        self.assertEqual(fields(v), ["team.size"])

    def test_val03_fill_defaults(self):
        v = validate({}, fill_defaults=True)
        self.assertEqual(v.errors, [])
        self.assertEqual(sum(a.startswith("DEFAULTED") for a in v.assumptions), 9)
        self.assertEqual(v.profile["team.languages"], [])

    def test_val04_wrong_types(self):
        raw = base()
        raw["team"]["size"] = "5"
        raw["requirements"]["realtime"] = "true"
        raw["project"]["name"] = 5
        raw["project"]["platforms"] = "web"
        raw["budget"]["monthly_infra_usd"] = [1]
        v = validate(raw)
        msgs = {e["field"]: e["message"] for e in v.errors}
        self.assertEqual(sorted(msgs), ["budget.monthly_infra_usd", "project.name", "project.platforms",
                                        "requirements.realtime", "team.size"])
        self.assertIn("an integer", msgs["team.size"])
        self.assertIn("without quotes", msgs["team.size"])
        self.assertIn("a number", msgs["budget.monthly_infra_usd"])
        self.assertNotIn("a integer", " ".join(msgs.values()))

    def test_val05_negative(self):
        raw = base()
        raw["scale"]["users_12_months"] = -1
        raw["team"]["size"] = 0
        raw["requirements"]["p95_latency_ms"] = 0
        self.assertEqual(sorted(fields(validate(raw))),
                         ["requirements.p95_latency_ms", "scale.users_12_months", "team.size"])

    def test_val06_non_integer_float_and_integral_float(self):
        raw = base()
        raw["team"]["size"] = 2.5
        self.assertEqual(fields(validate(raw)), ["team.size"])
        raw["team"]["size"] = 3.0
        v = validate(raw)
        self.assertEqual(v.errors, [])
        self.assertEqual(v.profile["team.size"], 3)
        self.assertEqual(sum("team.size" in a and "normalised" in a for a in v.assumptions), 1)

    def test_val07_bool_as_int(self):
        raw = base()
        raw["team"]["size"] = True
        raw["scale"]["users_12_months"] = False
        self.assertEqual(sorted(fields(validate(raw))), ["scale.users_12_months", "team.size"])

    def test_val08_unknown_enum_suggestion(self):
        raw = base()
        raw["project"]["type"] = "marketplce"
        v = validate(raw)
        self.assertEqual(fields(v), ["project.type"])
        self.assertIn("Did you mean 'marketplace'", v.errors[0]["message"])

    def test_val09_priority_range(self):
        raw = base()
        raw["priorities"]["cost"] = 6
        raw["priorities"]["security"] = 0
        self.assertEqual(sorted(fields(validate(raw))), ["priorities.cost", "priorities.security"])

    def test_val10_empty_platforms(self):
        raw = base()
        raw["project"]["platforms"] = []
        self.assertEqual(fields(validate(raw)), ["project.platforms"])

    def test_val11_wrong_section_type_no_cascade(self):
        raw = base()
        raw["team"] = "oops"
        v = validate(raw)
        self.assertEqual(fields(v), ["team"])
        raw["scale"] = [1]
        self.assertEqual(fields(validate(raw)), ["scale", "team"])

    def test_val12_oversized_and_nan(self):
        raw = base()
        raw["project"]["description"] = "x" * 4001
        raw["infrastructure"]["existing_systems"] = ["a"] * 51
        raw["scale"]["users_12_months"] = 10 ** 13
        raw["budget"]["monthly_infra_usd"] = float("nan")
        raw["team"]["size"] = float("inf")
        v = validate(raw)
        self.assertEqual(sorted(fields(v)), ["budget.monthly_infra_usd", "infrastructure.existing_systems",
                                             "project.description", "scale.users_12_months", "team.size"])
        raw = base()
        raw["project"]["description"] = "x" * 4000
        raw["infrastructure"]["existing_systems"] = ["a%d" % i for i in range(50)]
        self.assertEqual(validate(raw).errors, [])

    def test_val13_normalisations_one_assumption_each(self):
        raw = base()
        raw["requirements"]["availability"] = 99.9
        raw["compliance"] = ["GDPR", "dpdp"]
        raw["team"]["languages"] = ["Node", "python", "python"]
        raw["project"]["type"] = " Marketplace "
        v = validate(raw)
        self.assertEqual(v.errors, [])
        for needle in ["availability", "compliance normalised", "team.languages normalised", "project.type"]:
            self.assertEqual(sum(needle in a for a in v.assumptions), 1, needle)
        self.assertEqual(v.profile["requirements.availability"], "99.9")
        self.assertEqual(v.profile["team.languages"], ["javascript", "python"])

    def test_scenario_id(self):
        raw = base()
        raw["scenario_id"] = 7
        v = validate(raw)
        self.assertEqual(v.profile["scenario_id"], "7")
        self.assertTrue(any("scenario_id" in a for a in v.assumptions))
        raw["scenario_id"] = ["x"]
        self.assertEqual(fields(validate(raw)), ["scenario_id"])
        del raw["scenario_id"]
        v = validate(raw)
        self.assertEqual(v.errors, [])
        self.assertIsNone(v.profile["scenario_id"])

    def test_cross_field_notices(self):
        raw = base()
        raw["scale"]["users_at_launch"] = 5000
        raw["scale"]["users_12_months"] = 100
        raw["scale"]["peak_concurrent_users"] = 500
        raw["project"]["platforms"] = ["api_only", "web"]
        v = validate(raw)
        self.assertEqual(v.errors, [])
        codes = {n["code"] for n in v.notices}
        self.assertTrue({"USERS_12M_BELOW_LAUNCH", "PEAK_EXCEEDS_USERS",
                         "API_ONLY_WITH_OTHER_PLATFORMS"} <= codes)

    def test_unknown_fields_notice(self):
        raw = base()
        raw["options"] = {"llm": True}
        raw["team"]["sizee"] = 3
        v = validate(raw)
        self.assertEqual(v.errors, [])
        self.assertEqual(sum(n["code"] == "UNKNOWN_FIELD" for n in v.notices), 2)

    def test_growth_default_and_notifications(self):
        raw = base()
        v = validate(raw)
        self.assertEqual(v.profile["team.growth_12_months"], v.profile["team.size"])
        self.assertNotIn("team.growth_12_months", v.provided)
        raw["requirements"]["notifications"] = ["none"]
        self.assertEqual(fields(validate(raw)), ["requirements.notifications"])
        raw["requirements"]["notifications"] = []
        self.assertEqual(validate(raw).errors, [])

    def test_invariant_complete_profile_when_valid(self):
        from stacksense.schema import FIELDS
        v = validate(base())
        for p in FIELDS:
            self.assertIn(p, v.profile)

    def test_total_function_fuzz(self):
        rnd = random.Random(1234)
        vals = [None, True, 0, -1, 1.5, float("nan"), float("inf"), "", "x", "web", [], [1], ["web"], {}, {"a": 1},
                10 ** 30, "x" * 5000, [[]], {"a": {"b": [1]}}]
        deep = []
        for _ in range(5000):
            deep = [deep]
        for _ in range(300):
            raw = copy.deepcopy(base())
            for _ in range(rnd.randint(1, 6)):
                sec = rnd.choice(list(raw.keys()))
                if isinstance(raw[sec], dict) and raw[sec]:
                    raw[sec][rnd.choice(list(raw[sec].keys()))] = rnd.choice(vals)
                else:
                    raw[sec] = rnd.choice(vals)
            v = validate(raw)
            self.assertIsInstance(v, Validated)
            json.dumps(v.errors)
        for bad in [None, 1, "s", [], [{}], deep, {"project": deep}, {"team": {"size": deep}},
                    {1: 2}, {"scenario_id": deep}]:
            self.assertIsInstance(validate(bad), Validated)
            self.assertIsInstance(validate(bad, fill_defaults=True), Validated)

    def test_non_dict_root(self):
        v = validate([1])
        self.assertEqual(fields(v), ["$"])

    def test_deterministic(self):
        a, b = validate(base()), validate(base())
        self.assertEqual((a.profile, a.errors, a.assumptions, a.notices, a.provided),
                         (b.profile, b.errors, b.assumptions, b.notices, b.provided))


class ReviewRegressionTests(unittest.TestCase):
    def _v(self, **kw):
        r = base()
        for path, val in kw.items():
            sec, key = path.split("__")
            r[sec][key] = val
        return validate(r)

    def test_huge_availability_no_dollar_error(self):
        r = base()
        r["requirements"]["availability"] = 10 ** 400
        r["team"]["size"] = "x"
        v = validate(r)
        self.assertEqual(sorted(fields(v)), ["requirements.availability", "team.size"])
        self.assertNotIn("$", fields(v))

    def test_availability_exact_only(self):
        self.assertEqual(self._v(requirements__availability=99.95).profile["requirements.availability"], "99.95")
        self.assertEqual(self._v(requirements__availability=99).profile["requirements.availability"], "99")
        v = self._v(requirements__availability=99.949999)
        self.assertEqual(fields(v), ["requirements.availability"])
        self.assertIn("99.95", v.errors[0]["message"])

    def test_blank_languages(self):
        v = self._v(team__languages=["  ", ""])
        self.assertEqual(fields(v), ["team.languages"])
        v = self._v(team__languages=["python", " ", ""])
        self.assertEqual(v.errors, [])
        self.assertEqual(v.profile["team.languages"], ["python"])
        self.assertEqual(sum("blank items removed" in a for a in v.assumptions), 1)

    def test_objective_c_not_swift(self):
        v = self._v(team__languages=["Objective-C", "objc"])
        self.assertNotIn("swift", v.profile["team.languages"])

    def test_growth_default_assumption_and_scenario_id(self):
        r = base()
        r["team"].pop("growth_12_months", None)
        v = validate(r)
        self.assertTrue(any("team.growth_12_months" in a and "team.size" in a for a in v.assumptions))
        for bad in (None, [], {"scenario_id": 5, "team": 3}, {"scenario_id": "  A  "}):
            p = validate(bad).profile
            self.assertIn("scenario_id", p)
        self.assertEqual(validate({"scenario_id": "  A  "}).profile["scenario_id"], "A")


if __name__ == "__main__":
    unittest.main()

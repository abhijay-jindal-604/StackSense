"""Explanations (T-EXP-01..07), description signals and the host-bundled filter rule."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from stacksense import engine, explain, filters, kb, schema
from stacksense.description import extract
from stacksense.existing import analyse
from stacksense.profile import derive
from stacksense.scoring import Contribution, Scored
from stacksense.validate import validate

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
EDGE = ROOT / "scenarios" / "edge"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")
CORE = ("frontend", "backend", "database", "hosting")
_CACHE: dict = {}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def result(sid: str) -> dict:
    if sid not in _CACHE:
        _CACHE[sid] = engine.recommend(load(PUBLIC / f"{sid}.json"))
    return _CACHE[sid]


def prof(raw: dict):
    v = validate(raw)
    assert not v.errors, v.errors
    return derive(v, extract(v.profile.get("project.description")),
                  analyse(v.profile.get("infrastructure.existing_systems")))


class ExplanationTests(unittest.TestCase):
    def test_driven_by_valid_paths(self):                       # T-EXP-01
        valid = set(schema.FIELDS) | {"compliance", "project.description"}
        for sid in SIDS:
            for layer in CORE:
                db = result(sid)["stack"][layer]["driven_by"]
                self.assertTrue(db, f"{sid} {layer}")
                self.assertLessEqual(len(db), explain.MAX_DRIVEN_BY)
                for f in db:
                    self.assertIn(f, valid, f"{sid} {layer}: {f}")

    def test_justification_quotes_an_input(self):              # T-EXP-02
        for sid in SIDS:
            for layer in CORE:
                j = result(sid)["stack"][layer]["justification"]
                self.assertRegex(j, r"[a-z_]+\.[a-z_0-9]+=|compliance=", f"{sid} {layer}: {j}")

    def test_alternatives_and_tradeoffs(self):                  # T-EXP-03/04
        for sid in SIDS:
            for layer in CORE:
                c = result(sid)["stack"][layer]
                self.assertGreaterEqual(len(c["alternatives"]), 1)
                self.assertLessEqual(len(c["alternatives"]), explain.MAX_ALTERNATIVES)
                names = [a["choice"] for a in c["alternatives"]]
                self.assertEqual(len(names), len(set(names)), f"{sid} {layer}")
                self.assertNotIn(c["choice"], names)
                self.assertTrue(c["tradeoffs"], f"{sid} {layer}")

    def test_unique_justifications_within_output(self):        # T-EXP-05
        for sid in SIDS:
            js = [result(sid)["stack"][l]["justification"] for l in CORE]
            self.assertEqual(len(js), len(set(js)), sid)

    def test_summary_at_most_two_sentences(self):              # T-EXP-06
        for sid in SIDS:
            s = result(sid)["summary"]
            self.assertLessEqual(len(re.findall(r"[.!?](?:\s+[A-Z]|$)", s)), 2, s)

    def test_none_components_name_the_inputs(self):
        r = result("P1")
        for layer in ("backend", "database"):
            c = r["stack"][layer]
            self.assertIn("requirements.auth=none", c["justification"])
            self.assertIn("requirements.auth", c["driven_by"])
            self.assertTrue(c["alternatives"])

    def test_why_not_numbers(self):
        win = Scored({"id": "a", "name": "A"}, 5.0, (Contribution("skill_fit", 4.0, ("team.languages",), "x knows A."),))
        alt = Scored({"id": "b", "name": "B"}, 1.0, (Contribution("skill_fit", -3.0, ("team.languages",), "nobody knows B."),))
        text = explain.why_not(win, alt)
        self.assertIn("-3 vs +4 skill_fit", text)
        self.assertIn("1 vs 5", text)

    def test_top_drivers_order(self):
        cs = [Contribution("a", 2.0, ("x.b",), "r"), Contribution("b", -3.0, ("x.a",), "r"),
              Contribution("c", 1.0, ("x.b",), "r")]
        self.assertEqual(explain.top_drivers(cs, 2), ["x.a", "x.b"])

    def test_trace_contains_rejections_and_constants(self):
        t = result("P2")["decision_trace"]
        self.assertTrue(t["layers"]["backend"]["rejected"])
        self.assertTrue(all("reason_text" in r for r in t["layers"]["backend"]["rejected"]))
        self.assertEqual(t["constants"]["kb_version"], result("P2")["kb_version"])


class DescriptionSignalTests(unittest.TestCase):
    def test_mismatch_is_info_and_names_field(self):
        r = engine.recommend(load(EDGE / "H36_description_field_mismatch.json"), trace=False)
        mm = [w for w in r["warnings"] if w["code"] == "DESCRIPTION_MISMATCH"]
        self.assertEqual(len(mm), 3)
        self.assertTrue(all(w["severity"] == "info" for w in mm))
        self.assertTrue(all("project.description" in w["fields"] for w in mm))

    def test_signal_is_info(self):
        sig = [w for w in result("P4")["warnings"] if w["code"] == "DESCRIPTION_SIGNAL"]
        self.assertTrue(sig)
        self.assertTrue(all(w["severity"] == "info" for w in sig))


class HostBundledFilterTests(unittest.TestCase):
    def test_bundled_inherits_host_region(self):
        p = prof(load(PUBLIC / "P2.json"))
        logs = kb.get("platform_builtin_logs")
        ok_host = kb.get("do_app_platform")
        self.assertIsNone(filters.check(logs, p, "observability", hosts=[ok_host]))

    def test_bundled_fails_with_failing_host(self):
        p = prof(load(PUBLIC / "P2.json"))
        logs = kb.get("platform_builtin_logs")
        bad_host = kb.get("render")
        self.assertIsNotNone(filters.check(bad_host, p, "hosting"))
        rej = filters.check(logs, p, "observability", hosts=[bad_host])
        self.assertIsNotNone(rej)
        self.assertEqual(rej.rule, "F4")
        self.assertIn("part of the host", rej.reason_text)

    def test_bundled_fails_closed_without_host(self):
        p = prof(load(PUBLIC / "P2.json"))
        rej = filters.check(kb.get("platform_builtin_logs"), p, "observability", hosts=[])
        self.assertIsNotNone(rej)
        self.assertTrue(rej.unverified)

    def test_host_bundled_scope(self):
        self.assertTrue(filters.host_bundled(kb.get("cdn_host_builtin"), "cdn"))
        self.assertTrue(filters.host_bundled(kb.get("platform_builtin_logs"), "observability"))
        self.assertFalse(filters.host_bundled(kb.get("supabase_auth"), "auth"))
        self.assertFalse(filters.host_bundled(kb.get("vercel"), "hosting"))


# ------------------------------------------------------------------ Phase 2 review fixes
def run(sid: str, **paths) -> dict:
    raw = load(PUBLIC / f"{sid}.json")
    for path, value in paths.items():
        node = raw
        parts = path.split("__")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    return engine.recommend(raw)


class ReviewFixesTest(unittest.TestCase):
    def test_hard_fields_lead_driven_by(self):
        # finding 3: residency / compliance / explicit cloud are never cut by the cap of 8
        cases = [result(sid) for sid in SIDS] + [run("P3", infrastructure__data_residency="eu"),
                                                 run("P6", compliance=["dpdp", "iso27001"])]
        for r in cases:
            prof_res = r["decision_trace"]["profile"]["effective_residency"]
            for layer in ("database", "hosting"):
                comp = r["stack"][layer]
                self.assertLessEqual(len(comp["driven_by"]), explain.MAX_DRIVEN_BY)
                if prof_res != "none":
                    self.assertIn("infrastructure.data_residency", comp["driven_by"], (r["scenario_id"], layer))
        p6 = run("P6", compliance=["dpdp", "iso27001"])
        self.assertIn("compliance", p6["stack"]["database"]["driven_by"][:3])
        self.assertIn("compliance", p6["stack"]["hosting"]["driven_by"][:3])

    def test_self_managed_choice_names_engine(self):
        # finding 2 + 7: the engine is named and on-premise text reads "runs on premises"
        for dep in ("on_premise", "air_gapped", "self_hosted_cloud_vm"):
            r = run("P6", infrastructure__deployment_model=dep)
            self.assertIsNotNone(r["stack"], dep)
            db = r["stack"]["database"]
            name = kb.get(db["kb_id"])["name"]
            self.assertTrue(db["choice"].startswith("Self-managed "), db["choice"])
            self.assertIn(name.split(" ")[0], db["choice"])
            for layer in CORE:
                self.assertNotIn("runs in on premises", r["stack"][layer]["justification"], (dep, layer))

    def test_combo_level_why_not_cites_combination_terms(self):
        # finding 4: an alternative that wins on its own layer score is explained by the full stack
        pat = re.compile(r"scores [\d.-]+ on its own .*but the best full stack built around it scores")
        seen = 0
        for r in [result(sid) for sid in SIDS]:
            for layer in CORE:
                for a in r["stack"][layer]["alternatives"]:
                    if pat.search(a["why_not"]) and "budget fallback" not in a["why_not"]:
                        seen += 1
                        tail = a["why_not"].split(": ", 1)[-1]
                        self.assertRegex(tail, r"its stack|its best|in its stack", a["why_not"])
        self.assertGreater(seen, 0)

    def test_none_database_with_baas_backend(self):
        # finding 1: a BaaS / commerce back end with database None is not called "pre-rendered pages"
        p = prof(load(PUBLIC / "P2.json"))
        none_db = Scored(kb.get("none"), 0.0, ())
        comp = explain.component("database", none_db, [], [], p, backend=Scored(kb.get("shopify"), 1.0, ()))
        self.assertNotIn("pre-rendered", comp["justification"])
        self.assertIn("Shopify", comp["justification"])
        static = explain.component("database", none_db, [], [], p, backend=Scored(kb.get("none_backend"), 0.0, ()))
        self.assertIn("pre-rendered", static["justification"])

    def test_budget_fallback_assumption(self):
        # finding 5: the plan 7 trade sentence when a cheaper stack replaces the best one
        r = run("P5", budget__monthly_infra_usd=100)
        chose = [a for a in r["assumptions"] if a.startswith("Chose ")]
        self.assertEqual(len(chose), 1)
        self.assertIn("to fit USD 100/month", chose[0])
        self.assertNotEqual(r["budget_verdict"]["verdict"], "exceeded")
        self.assertIsNotNone(r["decision_trace"]["combinations"])

    def test_no_compatible_stack_names_blocker(self):
        # finding 8: residency=other is named as the blocking hard filter
        r = engine.recommend(load(EDGE / "H32_residency_other.json"))
        w = next(w for w in r["warnings"] if w["code"] == engine.NO_COMBINATION_CODE)
        self.assertEqual(w["fields"][0], "infrastructure.data_residency")
        self.assertIn("infrastructure.data_residency=other", w["message"])

    def test_nearest_feasible_pairs(self):
        # finding 9: no single relaxation works -> pairs of relaxations are reported
        r = run("P4", infrastructure__data_residency="eu", infrastructure__cloud_preference="azure")
        self.assertEqual(r["status"], "infeasible")
        near = r["nearest_feasible"]
        self.assertTrue(near)
        self.assertTrue(all(len(n["fields"]) >= 1 and "together with" in n["message"] for n in near))
        self.assertLessEqual(len(near), engine.NEAREST_PAIR_LIMIT)


if __name__ == "__main__":
    unittest.main()

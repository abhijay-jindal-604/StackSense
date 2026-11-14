"""Conflict and warning rules (plan 3.6, 6.3; T-WARN-01).

* catalogue completeness: every code the package can emit is in ``conflicts.CATALOGUE``; every plan 6.3
  code is either in the catalogue or listed in ``NOT_EMITTED`` with a reason;
* each implemented rule fires on a minimal perturbation of a public scenario and not on that base;
* public scenarios carry the 8.1 info codes and no conflict code of severity warning/critical that 8.1
  rules out (P1 stays ``ok``; P3 has no LATENCY_AGGRESSIVE without a global audience);
* ``imply:`` / valued ``relax:`` effects re-derive the profile exactly once;
* hard-vs-hard conflicts give ``infeasible`` with ``nearest_feasible``.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from stacksense import conflicts, engine, kb
from stacksense.existing import ExistingMatch, ExistingReport
from stacksense.kb import eol
from stacksense.validate import validate

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "stacksense"
PUBLIC = ROOT / "scenarios" / "public"

PLAN_63 = (
    "BUDGET_EXCEEDED BUDGET_TIGHT ZERO_BUDGET_SCALE FREE_TIER_LIMITS BUDGET_HEADROOM TIMELINE_TIGHT "
    "TIMELINE_PLATFORMS MANY_PLATFORMS_SMALL_TEAM AVAILABILITY_VS_TEAM AVAILABILITY_VS_BUDGET "
    "AVAILABILITY_SINGLE_NODE LATENCY_AGGRESSIVE LATENCY_UNREALISTIC SEO_WITHOUT_WEB OFFLINE_API_ONLY "
    "API_ONLY_WITH_CLIENTS OFFLINE_WEB_LIMITS OFFLINE_CONFLICTS RBI_IMPLIES_INDIA RESIDENCY_COMPLIANCE_CONFLICT "
    "RESIDENCY_UNVERIFIABLE GDPR_TRANSFER GDPR_NOTES DPDP_NOTES PCI_SCOPE PCI_WITHOUT_PAYMENTS HIPAA_BAA "
    "HIPAA_BUDGET COMPLIANCE_ORG_SCOPE CLOUD_VS_DEPLOYMENT CLOUD_ONPREM_APPLIANCE CLOUD_NONE_INTERPRETED "
    "CLOUD_REGION_GAP AIRGAP_EXTERNAL_DEPENDENCY ONPREM_NO_SAAS ONPREM_OPS_GAP SELF_HOSTED_VM_OPS "
    "EOL_EXISTING_SYSTEM EXISTING_SYSTEM_UNRECOGNISED EXISTING_SYSTEM_CONFLICT SKILL_MISMATCH "
    "SKILL_GAP_NO_LEARNING BEGINNER_COMPLEXITY SOLO_BUS_FACTOR SCALE_INCONSISTENT HYPERGROWTH "
    "OVERENGINEERING_AVOIDED LOCK_IN_RISK MULTI_TENANT_ISOLATION ML_GPU_COST LLM_DATA_RESIDENCY PHONE_OTP_DLT "
    "STRIPE_INDIA DESCRIPTION_MISMATCH DESCRIPTION_SIGNAL UNKNOWN_FIELD DUPLICATE_KEY DEFAULTS_APPLIED "
    "PROJECT_TYPE_OTHER VENDOR_RISK"
).split()

_EMIT_RES = (
    re.compile(r'_warning\(\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'"code":\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'_CODE\s*=\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'\bconflict\(\s*"([A-Z][A-Z0-9_]+)"'),
)


def emitted_codes() -> set[str]:
    """Every warning code literal the package emits (grep of the source, KB excluded)."""
    out: set[str] = set()
    for f in sorted(PKG.rglob("*.py")):
        if "kb" in f.relative_to(PKG).parts:
            continue
        text = f.read_text(encoding="utf-8")
        for rx in _EMIT_RES:
            out.update(rx.findall(text))
    from stacksense import supporting
    out.update(supporting.GAP_CODES)
    return out


def load(sid: str) -> dict:
    return json.loads((PUBLIC / f"{sid}.json").read_text(encoding="utf-8"))


def perturb(sid: str, **changes) -> dict:
    """Public scenario with dotted-path changes (``team__size=1`` -> team.size)."""
    raw = copy.deepcopy(load(sid))
    for key, value in changes.items():
        node = raw
        parts = key.split("__")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    return raw


def pre(raw) -> list:
    v = validate(raw)
    assert not v.errors, v.errors
    _, found = engine.derive_with_conflicts(v)
    return found


def pre_codes(raw) -> dict[str, str]:
    return {c.code: c.severity for c in pre(raw)}


_RESULTS: dict = {}


def run(sid: str) -> dict:
    if sid not in _RESULTS:
        _RESULTS[sid] = engine.recommend(load(sid))
    return _RESULTS[sid]


def codes(result) -> dict[str, set]:
    out: dict[str, set] = {}
    for w in result["warnings"]:
        out.setdefault(w["code"], set()).add(w["severity"])
    return out


# ------------------------------------------------------------------ fakes for post_checks unit tests
class FakeOffering:
    def __init__(self, family=None, region=None, offering=None):
        self.family, self.region, self.offering = family, region, offering


class FakeCombo:
    def __init__(self, *, frontend=(), backend="none_backend", database="none", hosting=None, offering=None):
        self._st = {"frontend": [kb.get(i) for i in frontend], "backend": kb.get(backend),
                    "database": kb.get(database), "hosting": kb.get(hosting) if hosting else None}
        self.database_offering = offering

    def stack(self):
        return dict(self._st)


class FakeSel:
    def __init__(self, layer, rid):
        self.layer, self.tech = layer, kb.get(rid)


class FakeSup:
    def __init__(self, *sels):
        self.selections = tuple(FakeSel(layer, rid) for layer, rid in sels)


class FakeCost:
    def __init__(self, lo, hi, verdict, warnings=()):
        self.min, self.max, self.verdict, self.warnings = lo, hi, verdict, tuple(warnings)


def profile(raw):
    v = validate(raw)
    assert not v.errors, v.errors
    p, _ = engine.derive_with_conflicts(v)
    return p


def post_codes(raw, combo, sup=None, cost=None, ranked=None) -> dict[str, str]:
    return {c.code: c.severity for c in conflicts.post_checks(profile(raw), combo, sup or FakeSup(), cost, ranked)}


# ================================================================== catalogue
class CatalogueTests(unittest.TestCase):
    def test_every_emitted_code_is_catalogued(self):
        missing = sorted(emitted_codes() - set(conflicts.CATALOGUE))
        self.assertEqual(missing, [], "codes emitted by the package but not in conflicts.CATALOGUE")

    def test_emitted_grep_finds_known_emitters(self):
        found = emitted_codes()
        for code in ("BUDGET_EXCEEDED", "SUPPORTING_GAP", "NO_FEASIBLE_CANDIDATE", "NO_COMPATIBLE_STACK",
                     "EXISTING_SYSTEM_UNRECOGNISED", "DESCRIPTION_SIGNAL", "DESCRIPTION_MISMATCH",
                     "UNKNOWN_FIELD", "DUPLICATE_KEY", "ZERO_BUDGET_SCALE", "CLOUD_VS_DEPLOYMENT"):
            self.assertIn(code, found)

    def test_plan_codes_catalogued_or_explained(self):
        self.assertEqual(len(PLAN_63), 60)
        for code in PLAN_63:
            self.assertTrue(code in conflicts.CATALOGUE or code in conflicts.NOT_EMITTED, code)
        for code, why in conflicts.NOT_EMITTED.items():
            self.assertTrue(why, code)

    def test_entries_well_formed(self):
        for code, e in conflicts.CATALOGUE.items():
            self.assertTrue(set(e.severity) <= {"critical", "warning", "info"}, code)
            self.assertTrue(e.template.strip(), code)
            self.assertTrue(e.effect == "none" or e.effect == "infeasible"
                            or e.effect.startswith(("imply:", "relax:")), code)
            self.assertRegex(code, r"^[A-Z][A-Z0-9_]+$")

    def test_engine_emitted_warnings_use_catalogue_severity(self):
        for sid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            for w in run(sid)["warnings"]:
                self.assertIn(w["code"], conflicts.CATALOGUE, sid)
                self.assertIn(w["severity"], conflicts.CATALOGUE[w["code"]].severity, (sid, w["code"]))

    def test_conflict_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            conflicts.conflict("DPDP_NOTES", severity="critical")


# ================================================================== pre-selection rules
PRE_CASES = (
    # (code, severity, base, changes)
    ("RBI_IMPLIES_INDIA", "warning", "P4", {"infrastructure__data_residency": "none"}),
    ("RESIDENCY_COMPLIANCE_CONFLICT", "critical", "P4", {"infrastructure__data_residency": "us"}),
    ("RESIDENCY_UNVERIFIABLE", "critical", "P2", {"infrastructure__data_residency": "other"}),
    ("DPDP_NOTES", "info", "P3", {"compliance": ["gdpr", "dpdp"]}),
    ("PCI_WITHOUT_PAYMENTS", "info", "P5", {"compliance": ["iso27001", "pci_dss"]}),
    ("COMPLIANCE_ORG_SCOPE", "info", "P2", {"compliance": ["dpdp", "soc2"]}),
    ("PHONE_OTP_DLT", "info", "P3", {"requirements__auth": "phone_otp", "infrastructure__data_residency": "india"}),
    ("CLOUD_VS_DEPLOYMENT", "critical", "P4", {"infrastructure__deployment_model": "air_gapped"}),
    ("CLOUD_ONPREM_APPLIANCE", "warning", "P4", {"infrastructure__deployment_model": "on_premise"}),
    ("CLOUD_NONE_INTERPRETED", "info", "P3", {"infrastructure__cloud_preference": "none"}),
    ("ONPREM_NO_SAAS", "info", "P3", {"infrastructure__deployment_model": "on_premise"}),
    ("ONPREM_OPS_GAP", "critical", "P1", {"infrastructure__deployment_model": "on_premise"}),
    ("SELF_HOSTED_VM_OPS", "warning", "P2", {"infrastructure__deployment_model": "self_hosted_cloud_vm"}),
    ("TIMELINE_PLATFORMS", "critical", "P2", {"timeline__mvp_weeks": 3}),
    ("TIMELINE_TIGHT", "warning", "P6", {"timeline__mvp_weeks": 2}),
    ("MANY_PLATFORMS_SMALL_TEAM", "warning", "P2", {"project__platforms": ["web", "android", "ios"]}),
    ("BEGINNER_COMPLEXITY", "warning", "P2", {"team__experience": "beginner"}),
    ("SOLO_BUS_FACTOR", "info", "P2", {"team__size": 1}),
    ("AVAILABILITY_VS_TEAM", "critical", "P2", {"requirements__availability": "99.99"}),
    ("LATENCY_AGGRESSIVE", "warning", "P3", {"scale__geographic_spread": "global"}),
    ("LATENCY_UNREALISTIC", "critical", "P3", {"requirements__p95_latency_ms": 15}),
    ("SEO_WITHOUT_WEB", "warning", "P6", {"requirements__seo_critical": True}),
    ("OFFLINE_API_ONLY", "warning", "P3", {"project__platforms": ["api_only"], "requirements__offline_support": True}),
    ("OFFLINE_WEB_LIMITS", "info", "P2", {"requirements__offline_support": True}),
    ("OFFLINE_CONFLICTS", "info", "P2", {"requirements__offline_support": True}),
    ("HYPERGROWTH", "info", "P2", {"scale__users_12_months": 150000, "scale__users_at_launch": 2000}),
    ("ML_GPU_COST", "warning", "P3", {"requirements__ml_features": "training"}),
    ("PROJECT_TYPE_OTHER", "info", "P2", {"project__type": "other"}),
)


class PreRuleTests(unittest.TestCase):
    def test_each_rule_fires_on_perturbation_not_on_base(self):
        for code, sev, base, changes in PRE_CASES:
            with self.subTest(code=code):
                self.assertNotIn(code, pre_codes(load(base)), f"{code} fires on base {base}")
                got = pre_codes(perturb(base, **changes))
                self.assertIn(code, got, f"{code} does not fire on {base} {changes}")
                self.assertEqual(got[code], sev)

    def test_onprem_ops_gap_is_warning_at_capacity_two(self):
        got = pre_codes(perturb("P6", infrastructure__deployment_model="on_premise"))
        self.assertEqual(got.get("ONPREM_OPS_GAP"), "warning")    # mixed, no devops: capacity 2

    def test_timeline_rules_quiet_for_single_static_site(self):
        # P1: 2 weeks, one engineer, but one static web client and no backend: nothing to parallelise.
        got = pre_codes(load("P1"))
        self.assertNotIn("TIMELINE_TIGHT", got)
        self.assertNotIn("TIMELINE_PLATFORMS", got)

    def test_defaults_applied(self):
        raw = load("P2")
        del raw["team"]["size"]
        v = validate(raw, fill_defaults=True)
        self.assertFalse(v.errors)
        found = {c.code: c for c in conflicts.detect(engine._derive(v), v)}
        self.assertIn("DEFAULTS_APPLIED", found)
        self.assertIn("team.size", found["DEFAULTS_APPLIED"].fields)
        self.assertNotIn("DEFAULTS_APPLIED", {c.code for c in conflicts.detect(engine._derive(validate(load("P2"))),
                                                                              validate(load("P2")))})

    def test_messages_plain_and_filled(self):
        for code, _, base, changes in PRE_CASES:
            for c in pre(perturb(base, **changes)):
                self.assertNotIn("{", c.message, c.code)
                self.assertNotIn("}", c.message, c.code)

    def test_eol_existing_system_severities(self):
        p = profile(load("P5"))
        matches = (
            ExistingMatch(raw="PHP 7.4 monolith", pattern_id="php", family="framework", kind="php",
                          eol=eol.verdict("php", "7.4")),
            ExistingMatch(raw="On-prem SQL Server 2019", pattern_id="sqlserver", family="database", kind="sqlserver",
                          eol=eol.verdict("sqlserver", "2019")),
            ExistingMatch(raw="On-prem SQL Server 2019", pattern_id="on_prem", family="infrastructure",
                          kind="on_prem"),
        )
        p2 = dataclasses.replace(p, existing=ExistingReport(matches=matches))
        found = [c for c in conflicts.detect(p2) if c.code in ("EOL_EXISTING_SYSTEM", "EXISTING_SYSTEM_CONFLICT")]
        sev = {(c.code, c.severity) for c in found}
        self.assertIn(("EOL_EXISTING_SYSTEM", "critical"), sev)        # PHP 7.4 ended
        self.assertIn(("EOL_EXISTING_SYSTEM", "warning"), sev)         # SQL Server 2019 mainstream ended
        self.assertIn(("EXISTING_SYSTEM_CONFLICT", "warning"), sev)    # on-prem DB with an Azure stack
        self.assertTrue(any("2030-01-08" in c.message for c in found))


    def test_on_prem_detected_from_sibling_match_not_text(self):
        p = profile(load("P5"))

        def codes(raw, extra):
            ms = (ExistingMatch(raw=raw, pattern_id="sqlserver", family="database", kind="sqlserver"),) + extra
            q = dataclasses.replace(p, existing=ExistingReport(matches=ms))
            return {c.code for c in conflicts.detect(q)}
        sib = ExistingMatch(raw="SQL Server 2019 (datacentre)", pattern_id="on_prem", family="infrastructure",
                            kind="on_prem")
        self.assertIn("EXISTING_SYSTEM_CONFLICT", codes("SQL Server 2019 (datacentre)", (sib,)))
        self.assertNotIn("EXISTING_SYSTEM_CONFLICT", codes("on-prem SQL Server 2019", ()))
        other = dataclasses.replace(sib, raw="something else")
        self.assertNotIn("EXISTING_SYSTEM_CONFLICT", codes("SQL Server 2019 (datacentre)", (other,)))


# ================================================================== effects
class EffectTests(unittest.TestCase):
    def test_imply_rederives_profile_once(self):
        raw = perturb("P4", infrastructure__data_residency="none")
        v = validate(raw)
        with mock.patch.object(engine, "_derive", wraps=engine._derive) as d:
            p, found = engine.derive_with_conflicts(v)
        self.assertEqual(d.call_count, 2)
        self.assertEqual(p.residency, "india")
        self.assertEqual(conflicts.profile_changes(found), {"infrastructure.data_residency": "india"})
        self.assertTrue(any(a.startswith("infrastructure.data_residency treated as india")
                            for a in conflicts.assumptions(found)))

    def test_no_effect_derives_once(self):
        with mock.patch.object(engine, "_derive", wraps=engine._derive) as d:
            engine.derive_with_conflicts(validate(load("P2")))
        self.assertEqual(d.call_count, 1)

    def test_relax_with_value_applied_and_recorded(self):
        raw = perturb("P2", requirements__availability="99.99")
        p = profile(raw)
        self.assertEqual(p.values["requirements.availability"], "99.95")
        r = engine.recommend(raw)
        self.assertIn(r["status"], ("ok_with_warnings",))
        self.assertTrue(any(x.startswith("RELAXED: requirements.availability") for x in r["relaxed_constraints"]))
        self.assertTrue(any(x.startswith("RELAXED: requirements.availability") for x in r["assumptions"]))
        self.assertEqual(codes(r)["AVAILABILITY_VS_TEAM"], {"critical"})

    def test_zero_budget_relaxes_budget(self):
        r = engine.recommend(perturb("P2", budget__monthly_infra_usd=0))
        self.assertIn("ZERO_BUDGET_SCALE", codes(r))
        rel = [x for x in r["relaxed_constraints"] if x.startswith("RELAXED: budget.monthly_infra_usd")]
        self.assertEqual(len(rel), 1)          # BUDGET_EXCEEDED and ZERO_BUDGET_SCALE share one entry
        self.assertEqual(sum(1 for w in r["warnings"] if w["code"] == "BUDGET_EXCEEDED"), 1)   # not repeated

    def test_air_gapped_explicit_cloud_infeasible_with_nearest(self):
        r = engine.recommend(perturb("P4", infrastructure__deployment_model="air_gapped"))
        self.assertEqual(r["status"], "infeasible")
        self.assertIsNone(r["stack"])
        self.assertEqual(codes(r).get("CLOUD_VS_DEPLOYMENT"), {"critical"})
        fields = {n["field"] for n in r["nearest_feasible"]}
        self.assertIn("infrastructure.cloud_preference", fields)
        self.assertIn("infrastructure.deployment_model", fields)

    def test_rbi_with_us_infeasible_names_residency(self):
        r = engine.recommend(perturb("P4", infrastructure__data_residency="us"))
        self.assertEqual(r["status"], "infeasible")
        self.assertIn("infrastructure.data_residency", {n["field"] for n in r["nearest_feasible"]})
        self.assertEqual(sum(1 for w in r["warnings"] if w["code"] == "RESIDENCY_COMPLIANCE_CONFLICT"), 1)

    def test_merge_skips_codes_emitted_elsewhere(self):
        c = conflicts.conflict("DPDP_NOTES")
        self.assertEqual(conflicts.merge([{"code": "DPDP_NOTES"}], [c]), [])
        self.assertEqual(conflicts.merge([], [c]), [c.warning()])


# ================================================================== post-selection rules
class PostRuleTests(unittest.TestCase):
    def test_budget_rules(self):
        exceeded = FakeCost(500, 900, "exceeded", [{"code": "BUDGET_EXCEEDED"}])
        got = post_codes(load("P2"), FakeCombo(), cost=exceeded)
        self.assertIn("BUDGET_EXCEEDED", got)            # relax effect only (warning comes from cost.py)
        self.assertNotIn("ZERO_BUDGET_SCALE", got)
        self.assertIn("ZERO_BUDGET_SCALE", post_codes(perturb("P2", budget__monthly_infra_usd=0), FakeCombo(),
                                                      cost=exceeded))
        self.assertNotIn("ZERO_BUDGET_SCALE", post_codes(load("P1"), FakeCombo(), cost=FakeCost(0, 0, "free_tier_only")))
        hip = perturb("P3", compliance=["hipaa"], infrastructure__data_residency="us")
        self.assertEqual(post_codes(hip, FakeCombo(), cost=exceeded).get("HIPAA_BUDGET"), "critical")
        self.assertNotIn("HIPAA_BUDGET", post_codes(hip, FakeCombo(), cost=FakeCost(100, 200, "within")))
        self.assertIn("AVAILABILITY_VS_BUDGET", post_codes(load("P4"), FakeCombo(), cost=exceeded))
        self.assertNotIn("AVAILABILITY_VS_BUDGET", post_codes(load("P4"), FakeCombo(), cost=FakeCost(1, 2, "within")))

    def test_availability_vs_budget_uses_cost_multiplier(self):
        c = FakeCost(500, 900, "exceeded", [{"code": "BUDGET_EXCEEDED"}])
        c.availability_multiplier = (1.30, 1.75)
        found = [x for x in conflicts.post_checks(profile(load("P4")), FakeCombo(), FakeSup(), c)
                 if x.code == "AVAILABILITY_VS_BUDGET"]
        self.assertEqual(len(found), 1)
        self.assertIn("30-75%", found[0].message)

    def test_budget_exceeded_text_matches_fallback_mode(self):
        c = FakeCost(500, 900, "exceeded", [{"code": "BUDGET_EXCEEDED"}])

        def text(mode):
            got = conflicts.post_checks(profile(load("P2")), FakeCombo(), FakeSup(), c, budget_mode=mode)
            return next(x.assumption for x in got if x.code == "BUDGET_EXCEEDED")
        self.assertIn("cheapest stack that meets the hard constraints", text("cheapest"))
        self.assertNotIn("best meets", text("cheapest"))
        self.assertIn("recommended stack is kept", text(None))

    def test_pci_scope_makes_no_vendor_claim(self):
        got = conflicts.post_checks(profile(load("P2")), FakeCombo(), FakeSup(("payments", "razorpay")), None)
        msg = next(x.message for x in got if x.code == "PCI_SCOPE")
        self.assertNotIn("SAQ A", msg)
        self.assertNotIn("hosted checkout", msg)
        self.assertIn("reduces your PCI DSS scope", msg)

    def test_single_node(self):
        combo = FakeCombo(backend="django", database="sqlite", hosting="hetzner_compose")
        got = conflicts.post_checks(profile(load("P2")), combo, FakeSup(), None)
        names = [c.message for c in got if c.code == "AVAILABILITY_SINGLE_NODE"]
        self.assertEqual(len(names), 2)
        self.assertFalse([c for c in conflicts.post_checks(profile(load("P1")), combo, FakeSup(), None)
                          if c.code == "AVAILABILITY_SINGLE_NODE"])    # availability 99

    def test_cold_start_latency(self):
        combo = FakeCombo(backend="nestjs", database="postgres", hosting="aws_lambda_host")
        lam = kb.get("aws_lambda_host")
        if "cold_start" not in lam["caps"] or "min_instances" in lam["caps"]:
            self.skipTest("KB: Lambda host caps changed")
        self.assertIn("LATENCY_AGGRESSIVE", post_codes(load("P3"), combo))
        self.assertNotIn("LATENCY_AGGRESSIVE", post_codes(load("P3"), FakeCombo(backend="nestjs", database="postgres",
                                                                               hosting="aws_ecs_fargate")))

    def test_gdpr_region(self):
        combo_eu = FakeCombo(backend="nestjs", database="postgres", hosting="aws_ecs_fargate",
                             offering=FakeOffering("aws", "eu-central-1"))
        combo_us = FakeCombo(backend="nestjs", database="postgres", hosting="aws_ecs_fargate",
                             offering=FakeOffering("aws", "us-east-1"))
        self.assertEqual(post_codes(load("P3"), combo_eu).get("GDPR_NOTES"), "info")
        got = post_codes(load("P3"), combo_us)
        self.assertEqual(got.get("GDPR_TRANSFER"), "warning")
        self.assertNotIn("GDPR_NOTES", got)
        self.assertNotIn("GDPR_NOTES", post_codes(load("P2"), combo_eu))

    def test_payments_notes(self):
        sup = FakeSup(("payments", "razorpay"))
        got = post_codes(load("P2"), FakeCombo(), sup)
        self.assertIn("PCI_SCOPE", got)
        self.assertIn("STRIPE_INDIA", got)
        got = post_codes(load("P3"), FakeCombo(), FakeSup(("payments", "stripe")))
        self.assertIn("PCI_SCOPE", got)
        self.assertNotIn("STRIPE_INDIA", got)
        self.assertNotIn("PCI_SCOPE", post_codes(load("P5"), FakeCombo(), FakeSup()))

    def test_hipaa_baa_names_vendors(self):
        hip = perturb("P3", compliance=["hipaa"], infrastructure__data_residency="us")
        combo = FakeCombo(backend="nestjs", database="postgres", hosting="aws_ecs_fargate")
        found = [c for c in conflicts.post_checks(profile(hip), combo, FakeSup(), None) if c.code == "HIPAA_BAA"]
        self.assertEqual(len(found), 1)
        self.assertIn("AWS ECS on Fargate", found[0].message)
        self.assertNotIn("HIPAA_BAA", post_codes(load("P3"), combo))

    def test_multi_tenant_and_llm(self):
        combo = FakeCombo(backend="nestjs", database="postgres", hosting="aws_ecs_fargate")
        self.assertIn("MULTI_TENANT_ISOLATION", post_codes(load("P3"), combo))
        self.assertNotIn("MULTI_TENANT_ISOLATION", post_codes(load("P2"), combo))
        rag = perturb("P4", requirements__ml_features="llm_rag")
        self.assertEqual(post_codes(rag, combo).get("LLM_DATA_RESIDENCY"), "warning")
        self.assertNotIn("LLM_DATA_RESIDENCY", post_codes(load("P4"), combo))

    def test_skill_mismatch(self):
        combo = FakeCombo(frontend=["react_native_expo"], backend="django", database="postgres",
                          hosting="do_app_platform")
        self.assertNotIn("SKILL_MISMATCH", post_codes(load("P6"), combo))
        got = [c for c in conflicts.post_checks(profile(perturb("P6", team__languages=["python"])), combo,
                                                 FakeSup(), None) if c.code == "SKILL_MISMATCH"]
        self.assertEqual(len(got), 1)
        self.assertIn("React Native", got[0].message)

    def test_skill_gap_no_learning_and_overengineering(self):
        raw = perturb("P6", team__languages=["python"], team__willing_to_learn=False)
        p = profile(raw)
        ranked, _ = engine.core_candidates(p)
        got = {c.code: c for c in conflicts.post_checks(p, None, FakeSup(), None, ranked)}
        self.assertEqual(got["SKILL_GAP_NO_LEARNING"].severity, "critical")
        self.assertEqual(got["SKILL_GAP_NO_LEARNING"].kind, "relax")
        p5 = profile(load("P5"))
        ranked5, _ = engine.core_candidates(p5)
        found = [c for c in conflicts.post_checks(p5, None, FakeSup(), None, ranked5)
                 if c.code == "OVERENGINEERING_AVOIDED"]
        self.assertTrue(found)
        self.assertTrue(all("Kubernetes" in c.message or "distributed SQL" in c.message for c in found))
        self.assertNotIn("SKILL_GAP_NO_LEARNING", {c.code for c in conflicts.post_checks(p5, None, FakeSup(), None,
                                                                                       ranked5)})

    def test_lock_in(self):
        combo = FakeCombo(backend="firebase", database="firestore", hosting="firebase_hosting"
                          if kb.get("firebase_hosting") else None)
        self.assertEqual(post_codes(load("P3"), combo).get("LOCK_IN_RISK"), "info")
        low = perturb("P3", infrastructure__lock_in_tolerance="low")
        self.assertEqual(post_codes(low, combo).get("LOCK_IN_RISK"), "warning")
        self.assertNotIn("LOCK_IN_RISK", post_codes(load("P3"), FakeCombo(backend="nestjs", database="postgres")))


# ================================================================== public scenarios vs 8.1
EXPECT_INFO = {
    "P2": {"DPDP_NOTES", "PHONE_OTP_DLT", "STRIPE_INDIA", "PCI_SCOPE"},
    "P3": {"GDPR_NOTES", "MULTI_TENANT_ISOLATION", "PCI_SCOPE"},
    "P4": {"PCI_SCOPE", "DPDP_NOTES", "COMPLIANCE_ORG_SCOPE", "PHONE_OTP_DLT", "STRIPE_INDIA"},
    "P6": {"OFFLINE_CONFLICTS", "PROJECT_TYPE_OTHER", "PHONE_OTP_DLT", "DPDP_NOTES"},
}
CONFLICT_SOURCES = {code for code, e in conflicts.CATALOGUE.items() if e.source == "conflicts"}


class PublicTests(unittest.TestCase):
    def test_expected_info_codes(self):
        for sid, want in EXPECT_INFO.items():
            got = codes(run(sid))
            for code in sorted(want):
                self.assertIn(code, got, sid)
                self.assertEqual(got[code], {"info"}, (sid, code))

    def test_p1_has_no_conflict_warnings(self):
        r = run("P1")
        self.assertEqual(r["status"], "ok")
        self.assertFalse(set(codes(r)) & CONFLICT_SOURCES)

    def test_p3_latency_only_when_global(self):
        self.assertNotIn("LATENCY_AGGRESSIVE", codes(run("P3")))

    def test_no_infeasible_or_relaxation_in_public(self):
        for sid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            r = run(sid)
            self.assertNotEqual(r["status"], "infeasible", sid)
            self.assertFalse([c for c in pre(load(sid)) if c.kind in ("infeasible", "relax", "imply")], sid)

    def test_deterministic(self):
        a = engine.recommend(perturb("P2", requirements__availability="99.99", budget__monthly_infra_usd=0))
        b = engine.recommend(perturb("P2", requirements__availability="99.99", budget__monthly_infra_usd=0))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()

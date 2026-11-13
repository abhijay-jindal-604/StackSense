"""Tests for stacksense.supporting (plan 3.11, 5.4 C2, 6.1, 7, 8.1)."""
from __future__ import annotations

import copy
import json
import random
import unittest
from pathlib import Path

from stacksense import filters, output, supporting
from stacksense.cost import CostLine
from stacksense.description import extract
from stacksense.existing import analyse
from stacksense.profile import derive
from stacksense.validate import validate
from tests.helpers import assert_no_hard_violation, record_violations

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"

BASE = {
    "scenario_id": "T",
    "project": {"name": "Test", "type": "web_app", "description": "", "platforms": ["web"]},
    "scale": {"users_at_launch": 500, "users_12_months": 5000, "peak_concurrent_users": 100,
              "data_volume_gb_12_months": 5, "traffic_pattern": "steady", "workload": "balanced"},
    "team": {"size": 3, "experience": "intermediate", "languages": ["typescript", "javascript"], "has_devops": False},
    "budget": {"monthly_infra_usd": 200},
    "timeline": {"mvp_weeks": 10},
    "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none",
                       "existing_systems": []},
    "requirements": {"realtime": False, "offline_support": False, "full_text_search": False,
                     "file_media_storage": False, "payments": False, "auth": "none", "multi_tenant": False,
                     "ml_features": "none", "seo_critical": False, "availability": "99.9", "p95_latency_ms": None},
    "compliance": [],
    "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "performance": 3, "maintainability": 3,
                   "security": 3},
}
CORE = dict(frontend=["react_vite"], backend="nestjs", database="postgres", hosting=["do_app_platform"])
ONPREM_CORE = dict(frontend=["react_vite"], backend="django", database="postgres", hosting=["onprem_compose"])

# Core stacks of plan 8.1 ("primary") used as fixtures while combine.py is being written.
PUBLIC_CORES = {
    "P1": dict(frontend=["astro"], backend="none_backend", database="none", hosting=["cloudflare_pages"]),
    "P2": dict(frontend=["nextjs", "react_native_expo"], backend="supabase", database="postgres",
               hosting=["vercel", "supabase_cloud"]),
    "P3": dict(frontend=["react_vite"], backend="fastify", database="postgres", hosting=["aws_ecs_fargate"]),
    "P4": dict(frontend=["react_vite", "kmp_compose"], backend="spring_boot", database="postgres",
               hosting=["aws_ecs_fargate"]),
    "P5": dict(frontend=["blazor"], backend="aspnet_core", database="sqlserver", hosting=["azure_app_service"]),
    "P6": dict(frontend=["react_native_expo"], backend="django", database="postgres", hosting=["do_app_platform"]),
}


def scenario(**over) -> dict:
    """BASE with dotted-path overrides, e.g. scenario(**{"requirements.auth": "social"})."""
    d = copy.deepcopy(BASE)
    for path, value in over.items():
        cur = d
        parts = path.split(".")
        for k in parts[:-1]:
            cur = cur.setdefault(k, {})
        cur[parts[-1]] = value
    return d


def profile(raw: dict):
    v = validate(raw)
    assert not v.errors, v.errors
    return derive(v, extract(v.profile.get("project.description")),
                  analyse(v.profile.get("infrastructure.existing_systems")))


def run(raw=None, core=None, **kw):
    raw = raw if raw is not None else scenario()
    p = profile(raw)
    return p, supporting.select(p, core or CORE, **kw)


def as_output(res) -> dict:
    return {"stack": {"supporting": res.components()}, "warnings": list(res.warnings), "relaxed_constraints": []}


def load_public(sid):
    return json.loads((PUBLIC / f"{sid}.json").read_text())


# ------------------------------------------------------------------ triggers
class TriggerTests(unittest.TestCase):
    def slots(self, raw, core=None, **kw):
        _, res = run(raw, core, **kw)
        return {s.slot for s in res.selections} | {g.slot for g in res.gaps}

    def test_auth(self):
        for mode in ("email_password", "social", "phone_otp", "enterprise_sso"):
            self.assertIn("auth", self.slots(scenario(**{"requirements.auth": mode})), mode)
        self.assertNotIn("auth", self.slots(scenario()))

    def test_storage_explicit_and_signal(self):
        self.assertIn("storage", self.slots(scenario(**{"requirements.file_media_storage": True})))
        self.assertIn("storage", self.slots(scenario(**{"project.description": "Agents upload photos of each site."})))
        self.assertNotIn("storage", self.slots(scenario()))

    def test_cdn(self):
        self.assertIn("cdn", self.slots(scenario(**{"requirements.seo_critical": True})))
        self.assertIn("cdn", self.slots(scenario(**{"scale.workload": "read_heavy"})))
        self.assertNotIn("cdn", self.slots(scenario()))
        self.assertNotIn("cdn", self.slots(scenario(**{"requirements.seo_critical": True,
                                                       "project.platforms": ["android"]})))
        self.assertNotIn("cdn", self.slots(scenario(**{"scale.workload": "read_heavy",
                                                       "project.description": "Used only by employees."})))

    def test_cache(self):
        self.assertIn("cache", self.slots(scenario(**{"requirements.p95_latency_ms": 150})))
        self.assertNotIn("cache", self.slots(scenario(**{"requirements.p95_latency_ms": 500})))
        big = {"scale.users_12_months": 200000, "scale.peak_concurrent_users": 5000}
        self.assertIn("cache", self.slots(scenario(**big, **{"scale.workload": "read_heavy"})))
        self.assertNotIn("cache", self.slots(scenario(**{"scale.workload": "read_heavy"})))

    def test_queue(self):
        self.assertIn("queue", self.slots(scenario(**{"requirements.payments": True})))
        self.assertIn("queue", self.slots(scenario(**{"requirements.background_jobs": True})))
        self.assertIn("queue", self.slots(scenario(**{"scale.workload": "write_heavy", "scale.traffic_pattern": "spiky"})))
        self.assertNotIn("queue", self.slots(scenario(**{"scale.workload": "write_heavy"})))
        self.assertNotIn("queue", self.slots(scenario()))

    def test_search(self):
        self.assertIn("search", self.slots(scenario(**{"requirements.full_text_search": True})))
        self.assertNotIn("search", self.slots(scenario()))

    def test_realtime(self):
        self.assertIn("realtime", self.slots(scenario(**{"requirements.realtime": True})))
        self.assertIn("realtime", self.slots(scenario(**{"project.description": "Buyers chat with sellers."})))
        self.assertIn("realtime", self.slots(scenario(**{"project.type": "realtime_collab"})))
        self.assertNotIn("realtime", self.slots(scenario()))

    def test_payments(self):
        self.assertIn("payments", self.slots(scenario(**{"requirements.payments": True})))
        self.assertNotIn("payments", self.slots(scenario()))

    def test_ml(self):
        self.assertIn("ml", self.slots(scenario(**{"requirements.ml_features": "inference_api"})))
        rag = self.slots(scenario(**{"requirements.ml_features": "llm_rag"}))
        self.assertTrue({"ml.llm", "ml.vector"} <= rag, rag)
        self.assertFalse({s for s in self.slots(scenario()) if s.startswith("ml")})

    def test_ci_cd_and_mobile(self):
        self.assertIn("ci_cd", self.slots(scenario()))
        self.assertNotIn("ci_cd.mobile", self.slots(scenario()))
        mob = dict(CORE, frontend=["react_vite", "react_native_expo"])
        self.assertIn("ci_cd.mobile", self.slots(scenario(**{"project.platforms": ["web", "android"]}), mob))

    def test_observability_only_with_backend(self):
        self.assertIn("observability", self.slots(scenario()))
        p1 = load_public("P1")
        _, res = run(p1, PUBLIC_CORES["P1"])
        self.assertNotIn("observability", res.layers())
        self.assertTrue(any("observability" in a.lower() for a in res.assumptions))

    def test_other_slots(self):
        self.assertIn("other.sms", self.slots(scenario(**{"requirements.auth": "phone_otp"})))
        self.assertIn("other.email", self.slots(scenario(**{"requirements.auth": "email_password"})))
        self.assertIn("other.secrets", self.slots(scenario(**{"compliance": ["soc2"]})))
        self.assertIn("other.waf", self.slots(scenario(**{"compliance": ["pci_dss"]})))
        mob = dict(CORE, frontend=["react_native_expo"])
        self.assertIn("other.offline_sync", self.slots(scenario(**{"project.platforms": ["android"],
                                                                   "requirements.offline_support": True}), mob))
        self.assertIn("other.maps", self.slots(scenario(**{"project.description": "Pins GPS-tagged visits on a map."})))
        self.assertIn("other.integration", self.slots(scenario(**{"infrastructure.existing_systems": ["Microsoft 365"]})))
        none = self.slots(scenario())
        for s in ("other.sms", "other.email", "other.secrets", "other.waf", "other.offline_sync", "other.maps",
                  "other.integration", "other.registry"):
            self.assertNotIn(s, none)

    def test_skipped_records_reason(self):
        _, res = run()
        skipped = {s for s, _, _ in res.skipped}
        self.assertIn("payments", skipped)
        self.assertTrue(all(why.startswith("not needed") for _, _, why in res.skipped))


# ------------------------------------------------------------------ hard constraints
class HardConstraintTests(unittest.TestCase):
    def assert_clean(self, raw, res, p):
        assert_no_hard_violation(self, raw, as_output(res))
        for s in res.selections:
            slot = supporting.SLOT_BY_ID[s.slot]
            self.assertIsNone(filters.check(s.tech, p, slot.kb_layer), s.id)
            self.assertEqual(record_violations(s.tech, slot.kb_layer, p), [], s.id)

    def everything(self, **over):
        return scenario(**{"requirements.auth": "phone_otp", "requirements.payments": True,
                           "requirements.realtime": True, "requirements.file_media_storage": True,
                           "requirements.full_text_search": True, "requirements.ml_features": "llm_rag",
                           "requirements.p95_latency_ms": 150, "requirements.notifications": ["email", "push"],
                           "project.platforms": ["web", "android"], **over})

    def test_residency_india(self):
        raw = self.everything(**{"infrastructure.data_residency": "india"})
        p, res = run(raw, dict(CORE, frontend=["react_vite", "react_native_expo"]))
        self.assert_clean(raw, res, p)
        self.assertTrue(res.selections)
        for g in res.gaps:   # nothing silently dropped
            self.assertIn(g.code, supporting.GAP_CODES)
            self.assertTrue(g.message)

    def test_hipaa(self):
        raw = self.everything(**{"compliance": ["hipaa"], "infrastructure.cloud_preference": "aws",
                                 "budget.monthly_infra_usd": 3000})
        p, res = run(raw, dict(frontend=["react_vite"], backend="nestjs", database="postgres",
                               hosting=["aws_ecs_fargate"]))
        self.assert_clean(raw, res, p)
        self.assertIsNotNone(res.get("other.secrets"))

    def test_air_gapped(self):
        raw = self.everything(**{"infrastructure.deployment_model": "air_gapped",
                                 "infrastructure.cloud_preference": "none"})
        p, res = run(raw, ONPREM_CORE)
        self.assert_clean(raw, res, p)
        for s in res.selections:
            self.assertTrue(s.tech["self_hostable"], s.id)
            self.assertFalse(s.tech["needs_internet"], s.id)
        self.assertEqual(res.gap("payments").code, "AIRGAP_EXTERNAL_DEPENDENCY")
        self.assertEqual(res.gap("other.sms").code, "AIRGAP_EXTERNAL_DEPENDENCY")
        self.assertIsNone(res.get("payments"))
        self.assertEqual(res.get("other.registry").id, "harbor_registry")
        self.assertNotIn("cdn", res.layers())

    def test_open_source_only(self):
        raw = self.everything(**{"infrastructure.open_source_only": True})
        p, res = run(raw)
        self.assert_clean(raw, res, p)
        for s in res.selections:
            if s.tech["layer"] != "payments":
                self.assertTrue(s.tech["open_source"], s.id)

    def test_explicit_cloud(self):
        raw = self.everything(**{"infrastructure.cloud_preference": "azure", "infrastructure.data_residency": "eu"})
        p, res = run(raw, dict(frontend=["react_vite"], backend="aspnet_core", database="postgres",
                               hosting=["azure_app_service"]))
        self.assert_clean(raw, res, p)
        for s in res.selections:
            aff = set(s.tech["cloud_affinity"])
            if s.layer in filters.INFRA_LAYERS:
                self.assertFalse(aff & {"aws", "gcp"}, s.id)

    def test_never_deprecated(self):
        for sid in PUBLIC_CORES:
            _, res = run(load_public(sid), PUBLIC_CORES[sid])
            for s in res.selections:
                self.assertEqual(s.tech["status"], "maintained", s.id)
                self.assertNotIn(s.id, ("minio_community", "azure_cache_for_redis", "azure_ad_b2c",
                                        "google_cloud_iot_core"))

    def test_gap_never_picks_rejected(self):
        # Perturb P4 with a regime no India payment gateway attests (hipaa) so payments has a gap.
        raw = load_public("P4")
        raw["compliance"] = sorted(set(raw["compliance"]) | {"hipaa"})
        p, res = run(raw, PUBLIC_CORES["P4"])
        gap = res.gap("payments")
        self.assertIsNotNone(gap)
        self.assertEqual(gap.severity, "critical")
        self.assertIsNone(res.get("payments"))
        self.assertIn("compliance", gap.fields)
        self.assertIn(gap.warning()["code"], supporting.GAP_CODES)
        self.assertTrue(all(isinstance(r, filters.Rejection) for r in gap.rejected))


# ------------------------------------------------------------------ C2 managed realtime
class ManagedRealtimeTests(unittest.TestCase):
    VERCEL = dict(frontend=["nextjs"], backend="nextjs_api", database="postgres", hosting=["vercel"])

    def test_c2_managed_on_function_host(self):
        raw = scenario(**{"requirements.realtime": True})
        p, res = run(raw, self.VERCEL, needs_managed_realtime=True)
        rt = res.get("realtime")
        self.assertIsNotNone(rt)
        self.assertTrue(rt.tech["saas"] and not rt.tech["self_hostable"], rt.id)
        self.assertTrue(any("C2" in i.reason_text for i in rt.incompatible))
        self.assertTrue(res.needs_managed_realtime)

    def test_no_self_hosted_ws_on_function_host_even_without_flag(self):
        raw = scenario(**{"requirements.realtime": True})
        _, res = run(raw, self.VERCEL)
        rt = res.get("realtime")
        self.assertTrue(rt.tech["saas"] and not rt.tech["self_hostable"], rt.id)

    def test_c2_workers_allows_durable_objects(self):
        raw = scenario(**{"project.type": "realtime_collab", "requirements.realtime": True})
        core = dict(frontend=["react_vite"], backend="cloudflare_workers_hono", database="cloudflare_d1",
                    hosting=["cloudflare_workers_host"])
        _, res = run(raw, core, needs_managed_realtime=True)
        self.assertEqual(res.get("realtime").id, "cloudflare_durable_objects")

    def test_c2_gap_when_no_managed_service_passes(self):
        raw = scenario(**{"requirements.realtime": True, "infrastructure.deployment_model": "on_premise",
                          "infrastructure.cloud_preference": "none"})
        _, res = run(raw, ONPREM_CORE, needs_managed_realtime=True)
        self.assertIsNone(res.get("realtime"))
        self.assertIsNotNone(res.gap("realtime"))

    def test_without_c2_container_host_may_self_host(self):
        raw = scenario(**{"requirements.realtime": True})
        _, res = run(raw, dict(CORE, hosting=["aws_ecs_fargate"]))
        self.assertIsNotNone(res.get("realtime"))
        self.assertFalse(res.get("realtime").incompatible and
                         any("C2" in i.reason_text for i in res.get("realtime").incompatible))


# ------------------------------------------------------------------ determinism, order, cost lines
class DeterminismTests(unittest.TestCase):
    def test_repeatable(self):
        for sid in sorted(PUBLIC_CORES):
            raw = load_public(sid)
            a = run(raw, PUBLIC_CORES[sid])[1]
            b = run(copy.deepcopy(raw), PUBLIC_CORES[sid])[1]
            self.assertEqual(json.dumps(a.trace(), sort_keys=True), json.dumps(b.trace(), sort_keys=True))
            self.assertEqual(a.components(), b.components())

    def test_input_order_irrelevant(self):
        rng = random.Random(7)
        raw = load_public("P2")
        base = run(raw, PUBLIC_CORES["P2"])[1].ids()
        for _ in range(3):
            core = copy.deepcopy(PUBLIC_CORES["P2"])
            rng.shuffle(core["hosting"])
            shuffled = copy.deepcopy(raw)
            rng.shuffle(shuffled["compliance"])
            self.assertEqual(run(shuffled, core)[1].ids(), base)

    def test_output_order_and_components(self):
        order = list(output.SUPPORTING_LAYERS)
        for sid in sorted(PUBLIC_CORES):
            _, res = run(load_public(sid), PUBLIC_CORES[sid])
            idx = [order.index(s.layer) for s in res.selections]
            self.assertEqual(idx, sorted(idx))
            others = [s.tech["name"] for s in res.selections if s.layer == "other"]
            self.assertEqual(others, sorted(others))
            for comp in res.components():
                errs = []
                output._check_component(comp, sid, False, errs)
                self.assertEqual(errs, [], comp)
                self.assertLessEqual(len(comp["driven_by"]), supporting.SW["max_driven_by"])

    def test_cost_lines(self):
        raw = scenario(**{"requirements.file_media_storage": True, "requirements.auth": "phone_otp",
                          "scale.data_volume_gb_12_months": 50})
        p, res = run(raw)
        lines = res.cost_lines(p)
        self.assertTrue(all(isinstance(ln, CostLine) for ln in lines))
        self.assertEqual({ln.component_id for ln in lines}, set(res.ids()))
        st = next(ln for ln in lines if ln.component_id == res.get("storage").id)
        self.assertEqual(st.role, "usage")
        self.assertGreater(st.max, 0)
        sms = res.get("other.sms")
        if sms is not None:
            ln = next(ln for ln in lines if ln.component_id == sms.id)
            self.assertAlmostEqual(ln.max, round(p.users * 2 * 0.08, 2))
        for ln in lines:
            self.assertLessEqual(ln.min, ln.max)

    def test_bundled_costs_zero(self):
        p, res = run(load_public("P2"), PUBLIC_CORES["P2"])
        lines = {ln.component_id: ln for ln in res.cost_lines(p)}
        self.assertEqual((lines["supabase_auth"].min, lines["supabase_auth"].max), (0, 0))


# ------------------------------------------------------------------ public scenarios (plan 8.1)
class PublicScenarioTests(unittest.TestCase):
    cache: dict = {}

    def res(self, sid):
        if sid not in self.cache:
            raw = load_public(sid)
            self.cache[sid] = (raw,) + run(raw, PUBLIC_CORES[sid])
        return self.cache[sid]

    def assert_layers(self, sid, layers):
        raw, p, res = self.res(sid)
        missing = [l for l in layers if l not in res.layers()]
        self.assertEqual(missing, [], f"{sid}: selected {res.ids()}; gaps {[g.slot for g in res.gaps]}")
        assert_no_hard_violation(self, raw, as_output(res))

    def chosen(self, sid, slot):
        sel = self.res(sid)[2].get(slot)
        return sel.id if sel else None

    def test_p1(self):
        _, _, res = self.res("P1")
        self.assertEqual(sorted(res.layers()), ["cdn", "ci_cd"])
        self.assertEqual(self.chosen("P1", "cdn"), "cdn_host_builtin")
        self.assertIn(self.chosen("P1", "ci_cd"), ("host_native_git_deploys", "github_actions"))
        self.assertEqual(res.gaps, ())

    def test_p2(self):
        self.assert_layers("P2", ["auth", "storage", "realtime", "search", "payments", "cdn", "queue", "ci_cd"])
        self.assertEqual(self.chosen("P2", "auth"), "supabase_auth")
        self.assertEqual(self.chosen("P2", "storage"), "supabase_storage")
        self.assertEqual(self.chosen("P2", "realtime"), "supabase_realtime")
        self.assertEqual(self.chosen("P2", "search"), "pg_fts")
        self.assertIn(self.chosen("P2", "payments"), ("razorpay", "cashfree", "payu"))
        self.assertEqual(self.chosen("P2", "cdn"), "cdn_host_builtin")
        self.assertEqual(self.chosen("P2", "queue"), "pg_boss")
        self.assertNotIn("stripe", self.res("P2")[2].ids())

    @unittest.expectedFailure
    def test_p2_sms_msg91(self):
        # KB gap: kb.regions['msg91'] India = UNKNOWN, so MSG91 fails F4 closed under data_residency=india.
        self.assertEqual(self.chosen("P2", "other.sms"), "msg91")

    @unittest.expectedFailure
    def test_p2_push_fcm(self):
        # KB gap: kb.regions['fcm'] India = UNKNOWN (FCM fails F4); APNs cannot target android.
        self.assertEqual(self.chosen("P2", "other.push"), "firebase_cloud_messaging")

    @unittest.expectedFailure
    def test_p2_observability(self):
        # KB/filter gap: platform_builtin_logs is unbound (no region cells) and Sentry has no India region;
        # host-bundled services should inherit the host's region (filters change requested).
        self.assertIn("observability", self.res("P2")[2].layers())

    def test_p3(self):
        self.assert_layers("P3", ["realtime", "cache", "storage", "auth", "payments", "cdn", "queue", "ci_cd",
                                  "observability"])
        self.assertEqual(self.chosen("P3", "realtime"), "yjs_hocuspocus")
        self.assertEqual(self.chosen("P3", "payments"), "stripe")
        self.assertIn(self.chosen("P3", "cache"), ("valkey_self", "elasticache_valkey"))
        self.assertIn(self.chosen("P3", "auth"), ("auth0", "supabase_auth", "amazon_cognito", "keycloak", "workos",
                                                  "authjs_better_auth"))
        self.assertEqual(self.chosen("P3", "ci_cd"), "github_actions")

    def test_p4(self):
        self.assert_layers("P4", ["auth", "storage", "ml", "queue", "cache", "cdn", "ci_cd", "observability", "other"])
        self.assertIn(self.chosen("P4", "auth"), ("amazon_cognito", "spring_security"))
        self.assertEqual(self.chosen("P4", "storage"), "amazon_s3")
        self.assertIn(self.chosen("P4", "ml"), ("onnx_runtime", "amazon_sagemaker_ai"))
        self.assertEqual(self.chosen("P4", "queue"), "amazon_sqs")
        self.assertEqual(self.chosen("P4", "cache"), "elasticache_valkey")
        self.assertEqual(self.chosen("P4", "cdn"), "amazon_cloudfront")
        self.assertEqual(self.chosen("P4", "ci_cd"), "github_actions")
        self.assertEqual(self.chosen("P4", "observability"), "amazon_cloudwatch_xray")
        self.assertEqual(self.chosen("P4", "other.secrets"), "aws_kms_secrets_manager")
        self.assertEqual(self.chosen("P4", "other.waf"), "aws_waf")
        _, _, res = self.res("P4")
        for s in res.selections:
            if s.layer in filters.INFRA_LAYERS:
                self.assertFalse(set(s.tech["cloud_affinity"]) & {"gcp", "azure"}, s.id)

    def test_p4_payments_razorpay(self):
        self.assertEqual(self.chosen("P4", "payments"), "razorpay")

    @unittest.expectedFailure
    def test_p4_sms_msg91(self):
        self.assertEqual(self.chosen("P4", "other.sms"), "msg91")

    def test_p5(self):
        self.assert_layers("P5", ["auth", "storage", "ci_cd", "observability", "other"])
        self.assertEqual(self.chosen("P5", "storage"), "azure_blob")
        self.assertEqual(self.chosen("P5", "observability"), "azure_application_insights")
        self.assertEqual(self.chosen("P5", "other.secrets"), "azure_key_vault")
        self.assertIn(self.chosen("P5", "ci_cd"), ("github_actions", "azure_pipelines"))
        self.assertNotIn(self.chosen("P5", "auth"), ("auth0", "keycloak", "amazon_cognito", "azure_ad_b2c"))

    @unittest.expectedFailure
    def test_p5_auth_entra_id(self):
        # KB gap: kb.regions['entra_id'] India = UNKNOWN, so Entra ID fails F4 closed under residency india.
        self.assertEqual(self.chosen("P5", "auth"), "entra_id_workforce")

    @unittest.expectedFailure
    def test_p5_graph_integration(self):
        # Same KB gap (Microsoft Graph is bound to 'entra_id' regions).
        self.assertEqual(self.chosen("P5", "other.integration"), "microsoft_graph_api")

    def test_p6(self):
        self.assert_layers("P6", ["storage", "auth", "queue", "ci_cd", "observability", "other"])
        self.assertIn(self.chosen("P6", "storage"), ("do_spaces", "supabase_storage"))
        self.assertIn(self.chosen("P6", "auth"), ("django_auth", "supabase_auth"))
        self.assertIn(self.chosen("P6", "other.offline_sync"), ("powersync", "watermelondb"))
        self.assertIn(self.chosen("P6", "queue"), ("procrastinate", "pg_boss"))

    @unittest.expectedFailure
    def test_p6_sms_msg91(self):
        self.assertEqual(self.chosen("P6", "other.sms"), "msg91")


if __name__ == "__main__":
    unittest.main()

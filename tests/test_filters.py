import copy
import json
import random
import unittest
from pathlib import Path
from unittest import mock

from stacksense import filters, kb
from stacksense.filters import RULES, Rejection, apply_hard, check, check_all, check_offering, filter_layer, viable_offerings
from stacksense.kb import bindings
from stacksense.kb.model import CORE_LAYERS, service, tech
from stacksense.kb.sources import SOURCES
from stacksense.profile import derive
from stacksense.validate import validate
from tests import helpers

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def raw(sid="P2", **kw):
    """Scenario with overrides; keyword a__b means path a.b (value None deletes the key)."""
    r = copy.deepcopy(load(sid))
    for key, value in kw.items():
        parts = key.split("__")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return r


def P(sid="P2", **kw):
    v = validate(raw(sid, **kw))
    assert v.errors == [], v.errors
    return derive(v)


def R(rid):
    r = kb.get(rid)
    assert r is not None, rid
    return r


def rule(rid, p, **kw):
    r = check(R(rid), p, **kw)
    return r.rule if r else None


def synth(layer="frontend_desktop", kind="native", id="t_x", **kw):
    kw.setdefault("cost", {"xs": (0, 0), "s": (0, 0), "m": (0, 0), "l": (0, 0)})
    return tech(id, kw.pop("name", id.upper()), layer, kind, **kw)


IN = "infrastructure"


class F1Status(unittest.TestCase):
    def test_retired_and_deprecated(self):
        p = P("P1")
        r = check(R("angularjs"), p)
        self.assertEqual(r.rule, "F1")
        self.assertIn("retired", r.reason_text)
        self.assertIn("Angular", r.reason_text)
        self.assertEqual(r.fields, ())
        self.assertEqual(rule("create_react_app", p), "F1")
        self.assertEqual(rule("aws_app_runner", p), "F1")   # maintenance_only
        self.assertIsNone(rule("angular", p))

    def test_replaced_by_id_named(self):
        r = check(R("postgres_14"), P("P2"))
        self.assertEqual(r.rule, "F1")
        self.assertIn("PostgreSQL", r.reason_text)


class F2Deployment(unittest.TestCase):
    def test_on_premise(self):
        p = P(infrastructure__deployment_model="on_premise", infrastructure__data_residency="none")
        self.assertEqual(rule("vercel", p), "F2")
        self.assertIn("SaaS-only", check(R("vercel"), p).reason_text)
        self.assertIsNone(rule("k3s_onprem", p))
        self.assertIsNone(rule("aws_outposts", p))

    def test_public_cloud_vms_not_on_premise(self):
        for d in ("on_premise", "air_gapped"):
            p = P(infrastructure__deployment_model=d, infrastructure__data_residency="none")
            for vm in ("do_droplets_compose", "hetzner_compose", "amazon_ec2_lightsail",
                       "azure_virtual_machines", "google_compute_engine"):
                with self.subTest(d=d, vm=vm):
                    r = check(R(vm), p)
                    self.assertEqual(r.rule, "F2")
                    self.assertEqual(r.fields, ("infrastructure.deployment_model",))

    def test_air_gapped_needs_no_internet(self):
        p = P(infrastructure__deployment_model="air_gapped", infrastructure__data_residency="none")
        self.assertEqual(rule("aws_outposts", p), "F2")
        self.assertIn("internet", check(R("aws_outposts"), p).reason_text)
        self.assertIsNone(rule("rke2_harbor_airgap", p))
        self.assertEqual(rule("unity6", p, platform="android"), "F2")

    def test_managed_cloud_excludes_onprem_hosts(self):
        p = P("P1")
        self.assertEqual(rule("k3s_onprem", p), "F2")
        self.assertEqual(rule("aws_outposts", p), "F2")
        self.assertIsNone(rule("do_droplets_compose", p))

    def test_self_hosted_cloud_vm(self):
        p = P(infrastructure__deployment_model="self_hosted_cloud_vm")
        self.assertEqual(rule("render", p), "F2")
        self.assertEqual(rule("vercel", p), "F2")
        self.assertIsNone(rule("do_droplets_compose", p))
        self.assertEqual(rule("firebase", p), "F2")
        self.assertEqual(rule("aws_lambda_apigw", p), "F2")
        self.assertIsNone(rule("supabase", p))       # self-hostable


class F3Cloud(unittest.TestCase):
    def test_explicit_cloud(self):
        p = P("P4")   # aws, india
        for rid in ("azure_app_service", "render", "google_cloud_run"):
            self.assertEqual(rule(rid, p), "F3", rid)
        self.assertIn("cloud_preference=aws", check(R("render"), p).reason_text)
        self.assertEqual(rule("cloudflare_d1", p), "F3")
        self.assertEqual(rule("azure_functions", p), "F3")
        self.assertEqual(rule("cosmosdb", p), "F3")
        self.assertIsNone(rule("aws_ecs_fargate", p))
        self.assertIsNone(rule("fastapi", p))
        self.assertIsNone(rule("nextjs", p))         # not an infrastructure layer
        self.assertIsNone(rule("postgres", p))       # RDS offering

    def test_engine_without_cloud_offering(self):
        p = P("P2", infrastructure__cloud_preference="aws", infrastructure__data_residency="none", compliance=[])
        r = check(R("neo4j"), p)
        self.assertEqual(r.rule, "F3")
        self.assertIn("No managed", r.reason_text)

    def test_cloud_none(self):
        p = P(infrastructure__cloud_preference="none")
        r = check(R("aws_ecs_fargate"), p)
        self.assertEqual(r.rule, "F3b")
        self.assertIn("cloud_preference=none", r.reason_text)
        self.assertEqual(rule("dynamodb", p), "F3b")
        self.assertIsNone(rule("do_app_platform", p))
        self.assertIsNone(rule("postgres", p))       # DigitalOcean / Supabase offerings


class F4Residency(unittest.TestCase):
    def test_verified_absence(self):
        p = P("P2")
        r = check(R("render"), p)
        self.assertEqual(r.rule, "F4")
        self.assertFalse(r.unverified)
        self.assertIn("India", r.reason_text)
        self.assertIn("data_residency=india", r.reason_text)
        self.assertEqual(r.fields, ("infrastructure.data_residency",))
        self.assertIn("render_regions", r.sources)
        self.assertIsNone(rule("vercel", p))
        self.assertIsNone(rule("do_app_platform", p))

    def test_compute_hosts_and_functions_fail_closed(self):
        p = P("P2")
        for rid in ("cloudflare_pages", "cloudflare_workers_host", "azure_static_web_apps", "azure_container_apps"):
            r = check(R(rid), p)
            self.assertEqual(r.rule, "F4", rid)
            self.assertTrue(r.unverified, rid)
            self.assertIn("fail closed", r.reason_text)
        r = check(R("cloudflare_workers_hono"), p)
        self.assertEqual((r.rule, r.unverified), ("F4", True))
        self.assertEqual(rule("firebase", p), "F4")

    def test_static_only_hosting_exempt(self):
        p = P("P2")
        self.assertIsNone(rule("github_pages", p))
        self.assertIsNone(rule("cloudflare_pages", p, static_only=True))
        p1 = P("P1", infrastructure__data_residency="india")
        self.assertFalse(p1.needs_backend)
        self.assertIsNone(rule("cloudflare_pages", p1))
        self.assertIsNone(rule("netlify", p1))

    def test_frameworks_not_checked(self):
        p = P("P2")
        for rid in ("nextjs", "fastapi", "flutter"):
            self.assertIsNone(rule(rid, p, platform="android" if rid == "flutter" else None), rid)

    def test_record_star_cells_need_self_hosting(self):
        p = P("P2")   # managed_cloud, india
        for rid in ("clickhouse", "neo4j", "influxdb3"):
            r = check(R(rid), p)
            self.assertEqual(r.rule, "F4", rid)
            self.assertNotIn("*", r.reason_text)
        self.assertIsNone(rule("mongodb", p))        # Atlas / DigitalOcean in India
        self.assertIsNone(rule("postgres", p))
        ps = P("P2", infrastructure__deployment_model="self_hosted_cloud_vm")
        for rid in ("clickhouse", "neo4j", "influxdb3", "mongodb"):
            self.assertIsNone(rule(rid, ps), rid)

    def test_other_residency(self):
        p = P(infrastructure__data_residency="other")
        r = check(R("vercel"), p)
        self.assertEqual((r.rule, r.unverified), ("F4", True))
        self.assertEqual(rule("postgres", p), "F4")
        po = P(infrastructure__data_residency="other", infrastructure__deployment_model="on_premise")
        self.assertIsNone(rule("postgres", po))
        self.assertIsNone(rule("onprem_compose", po))

    def test_other_residency_allows_region_portable_hosts(self):
        p = P(infrastructure__data_residency="other")          # managed_cloud
        portable = [h for h in kb.by_layer("hosting") if h.get("kind") in ("vm", "k8s", "container")]
        self.assertTrue(portable)
        for h in portable:
            self.assertIsNone(rule(h["id"], p), h["id"])
            why = filters.residency_pass_reason(h, p, "hosting")
            self.assertIn("region-portable", why, h["id"])
            self.assertIn("deploy it in your jurisdiction", why)
            self.assertIn("RESIDENCY_UNVERIFIABLE", why)
        for rid in ("hetzner_compose", "do_droplets_compose", "google_compute_engine", "aws_ecs_fargate"):
            self.assertTrue(filters.region_portable(R(rid), "hosting"), rid)

    def test_other_residency_rejects_region_pinned_managed(self):
        p = P(infrastructure__data_residency="other")
        pinned = [h for h in kb.by_layer("hosting") if h.get("status") == "maintained"
                  and h.get("kind") in ("paas", "static_host", "serverless_fn")
                  and filters.handles_personal_data(h, p, "hosting", False)]   # GitHub Pages: static only
        self.assertTrue(pinned)
        for h in pinned:
            r = check(h, p, static_only=False)
            self.assertIsNotNone(r, h["id"])
            self.assertEqual((r.rule, r.unverified), ("F4", True), h["id"])
            self.assertIn("pinned to its vendor's regions", r.reason_text)
            self.assertIn("fail closed", r.reason_text)
            self.assertIsNone(filters.residency_pass_reason(h, p, "hosting"))
        for rid in ("postgres", "mongodb", "dynamodb", "firestore"):   # managed offerings / SaaS databases
            self.assertEqual(rule(rid, p), "F4", rid)
        for rid in ("amazon_ses", "sentry", "auth0", "upstash_redis"):  # region-pinned SaaS services
            self.assertEqual(rule(rid, p), "F4", rid)
        for off in kb.OFFERINGS:                                       # every managed offering
            if off["host"] != "self_hosted":
                r = check_offering(off, p)
                self.assertIsNotNone(r, off["id"])
                self.assertIn(r.rule, ("F1", "F4"), off["id"])
        # an unknown host kind is not portable: fails closed
        self.assertFalse(filters.region_portable(dict(R("hetzner_compose"), kind="mystery"), "hosting"))
        self.assertFalse(filters.region_portable(R("hetzner_compose"), "database"))

    def test_other_residency_in_host_and_self_hosted_components(self):
        p = P(infrastructure__data_residency="other")
        for rid in ("sqlite", "valkey_self", "keycloak", "grafana_prometheus_loki", "pocketbase"):
            self.assertIsNone(rule(rid, p), rid)
        self.assertIn("inside the application host", filters.residency_pass_reason(R("sqlite"), p))
        ps = P(infrastructure__data_residency="other", infrastructure__deployment_model="self_hosted_cloud_vm")
        self.assertIsNone(rule("postgres", ps))
        self.assertIn("self-hosted", filters.residency_pass_reason(R("postgres"), ps))
        self_off = next(o for o in kb.OFFERINGS if o["engine"] == "postgres" and o["host"] == "self_hosted")
        self.assertIn("self-managed", filters.residency_pass_reason(self_off, p, "database"))

    def test_portability_only_changes_other_residency(self):
        for res in ("india", "eu", "us"):
            p = P(infrastructure__data_residency=res)
            self.assertIsNone(filters.residency_pass_reason(R("hetzner_compose"), p, "hosting"), res)
            for h in sorted(kb.by_layer("hosting"), key=lambda r: r["id"]):
                r = check(h, p, static_only=False)
                if r is not None and r.rule == "F4":
                    self.assertNotIn("region-portable", r.reason_text)
                    self.assertNotIn("pinned to its vendor", r.reason_text)
        # Hetzner has no India region: portability does not override a named country
        self.assertEqual(rule("hetzner_compose", P(infrastructure__data_residency="india")), "F4")
        self.assertIsNone(rule("hetzner_compose", P(infrastructure__data_residency="none")))
        self.assertIsNone(filters.residency_pass_reason(R("hetzner_compose"), P(), "hosting"))

    def test_rbi_implies_india(self):
        p = P("P3", compliance=["rbi_localisation"])
        self.assertEqual(p.effective_residency, "india")
        r = check(R("render"), p)
        self.assertEqual(r.rule, "F4")
        self.assertEqual(r.fields, ("infrastructure.data_residency", "compliance"))
        self.assertIn("rbi_localisation", r.reason_text)

    def test_none_residency_passes(self):
        self.assertIsNone(rule("render", P("P3")))


class F5Compliance(unittest.TestCase):
    def test_pci(self):
        p = P("P4")
        r = check(R("amazon_ec2_lightsail"), p)
        self.assertEqual(r.rule, "F5")
        self.assertIn("pci_dss", r.reason_text)
        self.assertEqual(r.fields, ("compliance",))
        self.assertIsNone(rule("aws_ecs_fargate", p))

    def test_hipaa_combined_gap_fails_closed(self):
        p = P("P2", compliance=["hipaa"])
        r = check(R("supabase"), p)
        self.assertEqual((r.rule, r.unverified), ("F5", True))
        self.assertIn("Mumbai", r.reason_text)
        self.assertIsNone(rule("supabase", P("P3", compliance=["hipaa"])))   # plan:hipaa_addon, no residency

    def test_gdpr_unknown_fails_closed(self):
        r = check(R("fly_io"), P("P3"))
        self.assertEqual((r.rule, r.unverified), ("F5", True))
        self.assertIn("gdpr", r.reason_text)

    def test_plan_not_enough_for_pci(self):
        self.assertTrue(filters._attest_ok("hipaa", "plan:x"))
        self.assertFalse(filters._attest_ok("pci_dss", "plan:x"))
        for v in ("no", "unknown", "na"):
            self.assertFalse(filters._attest_ok("soc2", v))

    def test_na_fails(self):
        pay = service("t_pay", "Pay", "payments", "gateway", saas=True, cloud_affinity=["independent"])
        with mock.patch.dict(bindings.BINDINGS, {"t_pay": (None, "razorpay")}):
            r = check(pay, P("P3", compliance=["hipaa"]))
            self.assertEqual(r.rule, "F5")
            self.assertIn("hipaa", r.reason_text)
            self.assertIsNone(check(pay, P("P3", compliance=["pci_dss"])))

    def test_unbound_saas_fails_closed(self):
        rec = synth("backend", "serverless_fn", saas=True, attest={"soc2": "yes"})
        r = check(rec, P("P3", compliance=["iso27001"]), hosts=kb.by_layer("hosting"))
        self.assertEqual((r.rule, r.unverified), ("F5", True))
        rec2 = synth("backend", "serverless_fn", saas=True)
        r2 = check(rec2, P("P2"), hosts=kb.by_layer("hosting"))
        self.assertEqual((r2.rule, r2.unverified), ("F4", True))

    def test_self_hosted_inherits(self):
        p = P("P2", compliance=["hipaa"], infrastructure__deployment_model="on_premise")
        self.assertIsNone(rule("supabase", p, hosts=kb.by_layer("hosting")))
        self.assertIsNone(rule("postgres", p))


class F6OpenSource(unittest.TestCase):
    def test_open_source_only(self):
        p = P("P3", infrastructure__open_source_only=True, compliance=[])
        r = check(R("firebase"), p)
        self.assertEqual(r.rule, "F6")
        self.assertIn("open_source_only=true", r.reason_text)
        self.assertEqual(rule("mongodb", p), "F6")
        self.assertIsNone(rule("postgres", p))
        self.assertIsNone(rule("aws_ecs_fargate", p))   # hosting exempt
        self.assertIsNone(rule("firebase", P("P3", compliance=[])))


class F7Platform(unittest.TestCase):
    def test_frontend_platform(self):
        p = P("P4")
        self.assertEqual(rule("compose_android", p, platform="ios"), "F7")
        self.assertIsNone(rule("compose_android", p, platform="android"))
        r = check(R("swiftui_ios"), P("P6"))   # android only
        self.assertEqual(r.rule, "F7")
        self.assertIn("android", r.reason_text)
        self.assertEqual(r.fields, ("project.platforms",))

    def test_backend_runtime_needs_a_host(self):
        p = P("P3")
        r = check(R("fastapi"), p, hosts=[])
        self.assertEqual(r.rule, "F7")
        self.assertTrue(r.fields)
        self.assertEqual(rule("fastapi", p, hosts=[R("github_pages")]), "F7")
        self.assertIsNone(rule("fastapi", p, hosts=[R("render")]))
        self.assertIsNone(rule("pocketbase", p, hosts=[R("do_droplets_compose")]))

    def test_backend_fields_from_host_rejections(self):
        p = P("P2", infrastructure__deployment_model="air_gapped", infrastructure__data_residency="none", compliance=[])
        r = check(R("shopify"), p)
        self.assertEqual(r.rule, "F2")
        kept, _ = filter_layer("hosting", p)
        self.assertTrue(kept)


class F8Capability(unittest.TestCase):
    def test_offline(self):
        p = P("P6")
        rec = synth("frontend_desktop", caps=[], platforms=["desktop"])
        r = check(rec, p)
        self.assertEqual(r.rule, "F8")
        self.assertEqual(r.fields, ("requirements.offline_support",))
        self.assertIsNone(check(synth("frontend_desktop", caps=["offline"], platforms=["desktop"]), p))
        self.assertIsNone(check(rec, P("P3")))

    def test_latency_cold_start(self):
        p = P("P3", requirements__p95_latency_ms=40)
        r = check(R("railway"), p)
        self.assertEqual(r.rule, "F8")
        self.assertIn("p95_latency_ms=40", r.reason_text)
        self.assertIsNone(rule("vercel", p))          # min_instances
        self.assertIsNone(rule("railway", P("P3")))   # 100 ms
        self.assertIsNone(rule("railway", P("P1", requirements__p95_latency_ms=40)))   # static site


class Ordering(unittest.TestCase):
    def test_first_failure_and_check_all(self):
        p = P("P2", infrastructure__cloud_preference="aws")
        allr = check_all(R("render"), p)
        self.assertEqual([r.rule for r in allr][:2], ["F3", "F4"])
        self.assertEqual(check(R("render"), p).rule, "F3")
        self.assertEqual([r.rule for r in allr], sorted((r.rule for r in allr), key=RULES.index))

    def test_deterministic_and_sorted(self):
        rng = random.Random(7)
        for sid in SIDS:
            p = P(sid)
            for layer in CORE_LAYERS:
                cands = list(kb.by_layer(layer))
                k1, r1 = apply_hard(cands, p, layer)
                rng.shuffle(cands)
                k2, r2 = apply_hard(cands, p, layer)
                self.assertEqual([x["id"] for x in k1], [x["id"] for x in k2])
                self.assertEqual(r1, r2)
                self.assertEqual([x["id"] for x in k1], sorted(x["id"] for x in k1))
                self.assertEqual([x.tech_id for x in r1], sorted(x.tech_id for x in r1))
                self.assertEqual(len(k1) + len(r1), len(cands))

    def test_records_not_mutated(self):
        before = json.dumps(kb.export_body(), sort_keys=True)
        for sid in SIDS:
            for layer in CORE_LAYERS:
                filter_layer(layer, P(sid))
        self.assertEqual(json.dumps(kb.export_body(), sort_keys=True), before)


class RejectionShape(unittest.TestCase):
    def test_every_rejection_well_formed(self):
        for sid in SIDS:
            p = P(sid)
            for layer in CORE_LAYERS:
                _, rej = filter_layer(layer, p)
                for r in rej:
                    with self.subTest(sid=sid, id=r.tech_id):
                        self.assertIsInstance(r, Rejection)
                        self.assertIn(r.rule, RULES)
                        self.assertEqual(r.code, filters.RULE_CODES[r.rule])
                        self.assertTrue(r.reason_text.strip().endswith("."))
                        self.assertTrue(set(r.sources) <= set(SOURCES))
                        if r.rule != "F1":
                            self.assertTrue(r.fields)
                            self.assertTrue(r.sources, r.reason_text)
                        json.dumps(r.to_dict())

    def test_unverified_only_on_fact_rules(self):
        for sid in SIDS:
            for layer in CORE_LAYERS:
                for r in filter_layer(layer, P(sid))[1]:
                    if r.unverified:
                        self.assertIn(r.rule, ("F3", "F3b", "F4", "F5"))


class Offerings(unittest.TestCase):
    def test_offering_rules(self):
        p = P("P2")
        fly = next(o for o in kb.OFFERINGS if o["id"] == "postgres__fly")
        self.assertEqual(check_offering(fly, p).rule, "F4")
        self.assertEqual([o["id"] for o in viable_offerings("postgres", P("P4"))], ["postgres__aws"])
        self.assertEqual([o["id"] for o in viable_offerings("postgres", P("P5"))], ["postgres__azure"])
        self.assertEqual([o["id"] for o in viable_offerings("postgres", P("P2", infrastructure__deployment_model="on_premise"))],
                         ["postgres__self_hosted"])


class PublicScenarioSurvivors(unittest.TestCase):
    def needed_layers(self, p):
        out = ["hosting"]
        if "web" in p.clients:
            out.append("frontend_web")
        if {"android", "ios"} & set(p.clients):
            out.append("frontend_mobile")
        if "desktop" in p.clients:
            out.append("frontend_desktop")
        if p.needs_backend:
            out += ["backend", "database"]
        return out

    def test_each_needed_core_layer_survives(self):
        for sid in SIDS:
            p = P(sid)
            for layer in self.needed_layers(p):
                with self.subTest(sid=sid, layer=layer):
                    kept, _ = filter_layer(layer, p)
                    real = [k for k in kept if k.get("kind") != "none"]
                    self.assertGreaterEqual(len(real), 1)
            for plat in p.clients:
                layer = "frontend_web" if plat == "web" else "frontend_desktop" if plat == "desktop" else "frontend_mobile"
                self.assertTrue(filter_layer(layer, p, platform=plat)[0], (sid, plat))


class IndependentRecheck(unittest.TestCase):
    """T-HARD-01 at filter level: whatever the filters keep, the independent helper finds clean."""

    PERTURB = {
        "infrastructure__deployment_model": ["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"],
        "infrastructure__data_residency": ["none", "india", "eu", "us", "other"],
        "infrastructure__cloud_preference": ["any", "aws", "gcp", "azure", "none"],
        "compliance": [[], ["gdpr"], ["hipaa"], ["pci_dss"], ["soc2", "iso27001"], ["rbi_localisation"], ["dpdp"]],
    }

    def profiles(self, n=60):
        rng = random.Random(2026)
        for sid in SIDS:
            yield sid, P(sid)
        for i in range(n):
            sid = SIDS[i % len(SIDS)]
            kw = {k: rng.choice(v) for k, v in self.PERTURB.items() if rng.random() < 0.7}
            yield f"{sid}{kw}", P(sid, **kw)

    def test_kept_records_pass_independent_check(self):
        for label, p in self.profiles():
            for layer in CORE_LAYERS:
                kept, _ = filter_layer(layer, p)
                for rec in kept:
                    v = helpers.record_violations(rec, layer, p)
                    if p.effective_residency == "other" and filters.region_portable(rec, layer):
                        # plan 6.3 / H32: region-portable hosts pass residency=other (critical
                        # RESIDENCY_UNVERIFIABLE declares it); the helper predates that rule
                        v = [x for x in v if x[0] != "infrastructure.data_residency"]
                    self.assertEqual(v, [], f"{label} {layer} {rec['id']}")

    def test_viable_offerings_pass_independent_check(self):
        for label, p in self.profiles(30):
            for rec in kb.by_layer("database"):
                for off in viable_offerings(rec["id"], p):
                    self.assertEqual(helpers.record_violations(rec, "database", p, off), [], f"{label} {off['id']}")


class Helper(unittest.TestCase):
    def comp(self, choice, **kw):
        return {"choice": choice, "justification": "x", "driven_by": ["x"], "alternatives": [], **kw}

    def out(self, hosting="Vercel", database="Amazon RDS for PostgreSQL 17 (Multi-AZ, ap-south-1)", **kw):
        stack = {"frontend": self.comp("Next.js 16"), "backend": self.comp("FastAPI"),
                 "database": self.comp(database), "hosting": self.comp(hosting), "supporting": []}
        return {"status": "ok_with_warnings", "stack": stack, "warnings": [], "relaxed_constraints": [], **kw}

    def test_clean_output_passes(self):
        helpers.assert_no_hard_violation(self, raw("P2"), self.out())

    def test_violation_detected(self):
        self.assertTrue(helpers.hard_violations(raw("P2"), self.out(hosting="Render")))
        with self.assertRaises(AssertionError):
            helpers.assert_no_hard_violation(self, raw("P2"), self.out(hosting="Render"))
        self.assertTrue(helpers.hard_violations(raw("P4"), self.out(hosting="Azure App Service")))
        self.assertTrue(helpers.hard_violations(raw("P2"), self.out(database="Neo4j")))

    def test_declared_relaxation_accepted(self):
        w = {"code": "RESIDENCY_RELAXED", "severity": "critical", "message": "m",
             "fields": ["infrastructure.data_residency"]}
        helpers.assert_no_hard_violation(self, raw("P2"), self.out(hosting="Render", warnings=[w]))
        w2 = dict(w, severity="warning")
        self.assertTrue(helpers.hard_violations(raw("P2"), self.out(hosting="Render", warnings=[w2])))
        helpers.assert_no_hard_violation(self, raw("P2"), self.out(
            hosting="Render", relaxed_constraints=["RELAXED: infrastructure.data_residency"]))

    def test_unresolved_component_and_null_stack(self):
        self.assertTrue(helpers.hard_violations(raw("P2"), self.out(hosting="Mystery Cloud")))
        helpers.assert_no_hard_violation(self, raw("P2"), {"status": "infeasible", "stack": None})

    def test_id_keys_resolve(self):
        rec, off = helpers.resolve({"choice": "whatever", "kb_id": "render"})
        self.assertEqual(rec["id"], "render")
        rec, off = helpers.resolve({"choice": "x", "offering_id": "postgres__aws"})
        self.assertEqual((rec["id"], off["id"]), ("postgres", "postgres__aws"))

    def test_retired_never_excused(self):
        w = {"code": "X", "severity": "critical", "message": "m", "fields": ["status"]}
        self.assertTrue(helpers.hard_violations(raw("P1"), self.out(hosting="Vercel", warnings=[w]) | {
            "stack": dict(self.out()["stack"], frontend=self.comp("AngularJS"))}))


if __name__ == "__main__":
    unittest.main()

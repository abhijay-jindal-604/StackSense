"""Architecture style rules (plan 3.12, 6.2; T-ARCH-01..06)."""
import copy
import json
import random
import unittest
from pathlib import Path

from stacksense import architecture, kb, scoring
from stacksense.architecture import decide
from stacksense.output import ARCH_STYLES
from stacksense.profile import derive
from stacksense.schema import FIELDS
from stacksense.validate import validate

PUBLIC = Path(__file__).resolve().parent.parent / "scenarios" / "public"


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def prof(sid="P2", raw=None, **paths):
    """Profile from a public scenario with overrides; keys use '__' for dots."""
    r = copy.deepcopy(raw if raw is not None else load(sid))
    for path, value in paths.items():
        parts = path.split("__")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    v = validate(r)
    assert v.errors == [], v.errors
    return derive(v)


def stack(**ids):
    out = {}
    for slot, rid in ids.items():
        if slot == "database_offering":
            out[slot] = rid if isinstance(rid, dict) else next(o for o in kb.OFFERINGS if o["id"] == rid)
        else:
            out[slot] = kb.get(rid)
            assert out[slot] is not None, rid
    return out


SERVER = dict(backend="nestjs", database="postgres", hosting="aws_ecs_fargate")


class TestRules(unittest.TestCase):
    def test_r1_other_for_invalid_and_infeasible(self):
        p = prof("P2")
        for status in ("invalid_input", "infeasible"):
            d = decide(p, stack(**SERVER), status=status)
            self.assertEqual((d.style, d.rule), ("other", "R1"))
        self.assertEqual(decide(None).style, "other")

    def test_r2_static_without_backend(self):
        d = decide(prof("P1"), stack(frontend="astro", backend="none_backend", database="none",
                                     hosting="cloudflare_pages"))
        self.assertEqual((d.style, d.rule), ("static", "R2"))
        self.assertIn("project.type", d.driven_by)
        self.assertIn("requirements.auth=none", d.reason)
        self.assertEqual(decide(prof("P1"), {}).style, "static")

    def test_r3_serverless_baas_and_functions(self):
        p = prof("P2")
        d = decide(p, stack(backend="supabase", database="postgres", hosting="supabase_cloud"))
        self.assertEqual((d.style, d.rule), ("serverless", "R3"))
        self.assertEqual(decide(p, stack(backend="aws_lambda_apigw", hosting="aws_lambda_host")).style,
                         "serverless")
        self.assertEqual(decide(p, stack(backend="fastapi", hosting="aws_lambda_host")).style, "serverless")

    def test_r3_driven_by_comes_from_scoring(self):
        p = prof("P2")
        sc = scoring.score(kb.get("supabase"), p, scoring.context("backend"))
        d = decide(p, {"backend": sc, "hosting": kb.get("supabase_cloud")})
        top = sorted((c for c in sc.contributions if c.value > 0), key=lambda c: (-c.value, c.key))[:2]
        self.assertEqual(set(d.driven_by), {f for c in top for f in c.fields})

    def test_self_hosted_baas_is_not_serverless(self):
        d = decide(prof("P6"), stack(backend="pocketbase", hosting="do_droplets_compose"))
        self.assertNotEqual(d.style, "serverless")
        self.assertEqual(d.style, "monolith")

    def test_r4_hybrid(self):
        cloud_store = {"id": "cloud_store", "name": "Cloud object store", "layer": "storage", "kind": "object",
                       "saas": True, "self_hostable": False, "caps": []}
        p = prof("P5", infrastructure__deployment_model="on_premise", infrastructure__cloud_preference="any")
        base = stack(backend="aspnet_core", database="sqlserver", hosting="onprem_compose")
        self.assertEqual(decide(p, base).style, "monolith")
        d = decide(p, base, [cloud_store])
        self.assertEqual((d.style, d.rule), ("hybrid", "R4"))
        self.assertIn("infrastructure.deployment_model", d.driven_by)
        # hybrid appliance host
        p2 = prof("P4", infrastructure__deployment_model="on_premise")
        self.assertEqual(decide(p2, stack(backend="spring_boot", hosting="aws_outposts")).style, "hybrid")
        # existing on-prem database stays the primary store behind a cloud app
        existing = {"id": "sqlserver__existing", "name": "On-prem SQL Server 2019", "kind": "existing_onprem",
                    "engine": "sqlserver", "host": "on_premise", "cost": {}}
        d3 = decide(prof("P5"), {**stack(backend="aspnet_core", hosting="azure_app_service"),
                                 "database_offering": existing})
        self.assertEqual(d3.style, "hybrid")
        self.assertIn("infrastructure.existing_systems", d3.driven_by)

    def test_r5_microservices_needs_all_thresholds(self):
        big = dict(team__size=25, team__has_devops=True, team__experience="senior",
                   scale__users_12_months=3_000_000, priorities__scalability=5)
        d = decide(prof("P3", **big), stack(**SERVER))
        self.assertEqual((d.style, d.rule), ("microservices", "R5"))
        self.assertIn("priorities.scalability", d.driven_by)
        self.assertNotEqual(decide(prof("P3", **{**big, "team__size": 19}), stack(**SERVER)).style, "microservices")
        self.assertNotEqual(decide(prof("P3", **{**big, "priorities__scalability": 3}), stack(**SERVER)).style,
                            "microservices")
        self.assertNotEqual(decide(prof("P3", **{**big, "scale__users_12_months": 400_000}), stack(**SERVER)).style,
                            "microservices")

    def test_r6_service_oriented(self):
        d = decide(prof("P4", team__size=10), stack(backend="spring_boot", hosting="aws_ecs_fargate"))
        self.assertEqual((d.style, d.rule), ("service_oriented", "R6"))
        gw = {"id": "rt_gw", "name": "Realtime gateway", "layer": "realtime", "kind": "gateway", "caps": []}
        ml = {"id": "ml_ep", "name": "ML endpoint", "layer": "ml", "kind": "x", "caps": ["separate_service"]}
        p = prof("P3", team__size=6)
        self.assertEqual(decide(p, stack(**SERVER), [gw]).style, "modular_monolith")
        d2 = decide(p, stack(**SERVER), [gw, ml])
        self.assertEqual(d2.style, "service_oriented")
        self.assertIn("requirements.realtime", d2.driven_by)
        self.assertEqual(decide(prof("P3", team__size=5), stack(**SERVER), [gw, ml]).style, "modular_monolith")

    def test_r7_r8(self):
        self.assertEqual(decide(prof("P3"), stack(**SERVER)).rule, "R7")
        d = decide(prof("P2"), stack(backend="django", hosting="do_app_platform"))
        self.assertEqual(d.style, "modular_monolith")          # marketplace
        self.assertIn("project.type", d.driven_by)
        d5 = decide(prof("P5"), stack(backend="aspnet_core", hosting="azure_app_service"))
        self.assertEqual((d5.style, d5.rule), ("monolith", "R8"))
        mt = decide(prof("P5", requirements__multi_tenant=True), stack(backend="aspnet_core", hosting="azure_app_service"))
        self.assertEqual(mt.style, "modular_monolith")
        self.assertIn("requirements.multi_tenant", mt.driven_by)


class TestPublicExpectations(unittest.TestCase):
    """Plan 8.1 styles for plausible stacks (expectations, not branches)."""
    CASES = {
        "P1": (dict(frontend="astro", backend="none_backend", hosting="cloudflare_pages"), {"static"}),
        "P2": (dict(backend="supabase", hosting="supabase_cloud"), {"serverless"}),
        "P3": (dict(backend="fastify", hosting="aws_ecs_fargate"), {"modular_monolith", "service_oriented"}),
        "P4": (dict(backend="spring_boot", hosting="aws_ecs_fargate"), {"modular_monolith", "service_oriented"}),
        "P5": (dict(backend="aspnet_core", hosting="azure_app_service"), {"monolith"}),
        "P6": (dict(backend="django", hosting="do_app_platform"), {"monolith"}),
    }

    def test_public(self):
        for sid, (ids, ok) in self.CASES.items():
            with self.subTest(sid=sid):
                d = decide(prof(sid), stack(**ids))
                self.assertIn(d.style, ok)
        self.assertEqual(decide(prof("P2"), stack(backend="nestjs", hosting="do_app_platform")).style,
                         "modular_monolith")


class TestInvariants(unittest.TestCase):
    def test_shape_and_fields(self):
        for sid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            p = prof(sid)
            for b in ("none_backend", "supabase", "django", "spring_boot"):
                d = decide(p, stack(backend=b, hosting="aws_ecs_fargate"))
                self.assertIn(d.style, ARCH_STYLES)
                self.assertNotEqual(d.style, "other")
                self.assertTrue(d.reason.strip())
                self.assertTrue(d.driven_by)
                for f in d.driven_by:
                    self.assertIn(f, FIELDS, f)
                self.assertEqual(d.checks[-1][:2], (d.rule, True))
                self.assertTrue(all(not m for _, m, _ in d.checks[:-1]))
                self.assertEqual(d.as_dict()["style"], d.style)
                self.assertEqual(d.as_contribution().fields, d.driven_by)

    def test_thresholds_shared_with_scoring(self):
        self.assertIs(architecture.MICRO_MIN_TEAM, scoring.MICRO_MIN_TEAM)
        self.assertEqual(architecture.SOA_MIN_OPS, scoring.K8S_MIN_OPS)

    def test_random_no_overengineering(self):
        """T-ARCH-03: microservices impossible below MICRO_MIN_TEAM / size l / ops 4 (seeded)."""
        rng = random.Random(2611)
        backends = ("django", "nestjs", "spring_boot", "fastify", "supabase", "aws_lambda_apigw")
        for _ in range(300):
            team = rng.choice((1, 2, 5, 8, 9, 12, 19, 20, 30, 60))
            users = rng.choice((500, 30_000, 300_000, 3_000_000, 9_000_000))
            exp = rng.choice(("beginner", "intermediate", "senior", "mixed"))
            devops = rng.random() < 0.5
            scal = rng.randint(1, 5)
            p = prof("P3", team__size=team, team__experience=exp, team__has_devops=devops,
                     scale__users_12_months=users, scale__users_at_launch=min(users, 100),
                     scale__peak_concurrent_users=max(1, users // 20), priorities__scalability=scal)
            d = decide(p, stack(backend=rng.choice(backends), hosting="aws_ecs_fargate"))
            if d.style == "microservices":
                self.assertGreaterEqual(team, scoring.MICRO_MIN_TEAM)
                self.assertGreaterEqual(p.ops_capacity, 4)
                self.assertIn(p.size, ("l", "xl"))
            if d.style == "service_oriented":
                self.assertGreaterEqual(team, architecture.SOA_RUNTIME_MIN_TEAM)

    def test_deterministic(self):
        p = prof("P4")
        s = stack(backend="spring_boot", hosting="aws_ecs_fargate")
        self.assertEqual(decide(p, s), decide(p, dict(reversed(list(s.items())))))


if __name__ == "__main__":
    unittest.main()

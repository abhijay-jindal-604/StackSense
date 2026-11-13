"""Cost model, core lines (plan 3.13, 7). Phase 3 extends with supporting/usage lines and multipliers."""
import copy
import json
import random
import unittest
from pathlib import Path

from stacksense import cost, kb, output
from stacksense.cost import CostLine, estimate
from stacksense.kb import costs
from stacksense.profile import derive
from stacksense.validate import validate

PUBLIC = Path(__file__).resolve().parent.parent / "scenarios" / "public"


def prof(sid="P2", **paths):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        r = json.load(fh)
    r = copy.deepcopy(r)
    for path, value in paths.items():
        parts = path.split("__")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    v = validate(r)
    assert v.errors == [], v.errors
    return derive(v)


def offering(oid):
    return next(o for o in kb.OFFERINGS if o["id"] == oid)


def comps(**ids):
    out = {}
    for slot, rid in ids.items():
        if slot == "database_offering":
            out[slot] = offering(rid)
        elif isinstance(rid, (list, tuple)):
            out[slot] = [kb.get(i) for i in rid]
        else:
            out[slot] = kb.get(rid)
    return out


P2_SUPABASE = dict(frontend=["nextjs", "react_native_expo"], frontend_hosting="vercel", backend="supabase",
                   database="postgres", database_offering="postgres__supabase", hosting="supabase_cloud")


def codes(c):
    return [w["code"] for w in c.warnings]


class TestRoundSig(unittest.TestCase):
    def test_half_away_from_zero(self):
        self.assertEqual([costs.round_sig(x) for x in (0.5, 1.5, 2.5, -2.5, 9.5, 94.5, 0.4)],
                         [1, 2, 3, -3, 10, 95, 0])
        self.assertEqual(costs.round_sig(1234), 1200)
        self.assertEqual(costs.round_sig(2550), 2600)
        self.assertEqual(costs.round_sig(0), 0)
        self.assertIsInstance(costs.round_sig(2.5), int)


class TestCoreLines(unittest.TestCase):
    def test_static_free(self):
        c = estimate(prof("P1"), comps(frontend="astro", backend="none_backend", database="none",
                                       hosting="cloudflare_pages"))
        self.assertEqual((c.min, c.max), (0, 0))
        self.assertEqual(c.verdict, "free_tier_only")
        self.assertEqual([ln.component_id for ln in c.lines], ["astro", "cloudflare_pages"])
        self.assertIn("FREE_TIER_LIMITS", codes(c))
        self.assertNotIn("BUDGET_TIGHT", codes(c))

    def test_bundle_counts_supabase_once(self):
        c = estimate(prof("P2"), comps(**P2_SUPABASE))
        ids = [ln.component_id for ln in c.lines]
        self.assertIn("postgres__supabase+supabase+supabase_cloud", ids)
        bundle = next(ln for ln in c.lines if ln.members)
        self.assertEqual((bundle.min, bundle.max), (25, 110))      # largest of 25-75, 25-110, 25-75 at s
        self.assertEqual(bundle.role, "database")
        self.assertEqual((c.min, c.max), (45, 190))                # + Vercel 20-80
        self.assertEqual(c.verdict, "tight")
        w = next(w for w in c.warnings if w["code"] == "BUDGET_TIGHT")
        self.assertEqual(w["severity"], "warning")
        self.assertIn("budget.monthly_infra_usd", w["fields"])
        self.assertTrue(any("counted once" in a for a in c.assumptions))

    def test_offering_replaces_engine_band(self):
        p = prof("P6")
        engine_only = estimate(p, comps(backend="django", database="postgres", hosting="do_app_platform"))
        with_off = estimate(p, comps(backend="django", database="postgres",
                                     database_offering="postgres__digitalocean", hosting="do_app_platform"))
        db_e = next(ln for ln in engine_only.lines if ln.slot == "database")
        db_o = next(ln for ln in with_off.lines if ln.slot == "database")
        self.assertEqual((db_e.min, db_e.max), tuple(kb.get("postgres")["cost"]["s"]))
        self.assertEqual((db_o.min, db_o.max), tuple(offering("postgres__digitalocean")["cost"]["s"]))
        self.assertEqual(db_o.component_id, "postgres__digitalocean")
        self.assertIn("managed offering", db_o.basis)

    def test_same_host_counted_once(self):
        c = estimate(prof("P3"), comps(frontend="react_vite", frontend_hosting="aws_ecs_fargate",
                                       backend="fastify", hosting="aws_ecs_fargate"))
        self.assertEqual(sum(1 for ln in c.lines if ln.component_id == "aws_ecs_fargate"), 1)

    def test_missing_size_band_uses_nearest_and_says_so(self):
        p = prof("P6")                                              # size s; tigerbeetle only at l
        c = estimate(p, comps(backend="django", database="tigerbeetle", hosting="do_app_platform"))
        db = next(ln for ln in c.lines if ln.slot == "database")
        self.assertTrue(db.derived)
        self.assertEqual((db.min, db.max), tuple(kb.get("tigerbeetle")["cost"]["l"]))
        self.assertTrue(any("size l band is used" in a for a in c.assumptions))

    def test_xl_derived(self):
        p = prof("P3", scale__users_12_months=9_000_000)
        self.assertEqual(p.size, "xl")
        c = estimate(p, comps(backend="fastify", hosting="aws_ecs_fargate"))
        host = c.lines[-1]
        self.assertEqual((host.min, host.max), (1500 * 3, 6000 * 3))
        self.assertTrue(host.derived)
        self.assertTrue(any("quote needed" in a for a in c.assumptions))

    def test_extra_lines_appended(self):
        extra = CostLine(slot="storage", component_id="s3", name="Amazon S3", min=1, max=3, basis="usage",
                         role="usage")
        base = estimate(prof("P4"), comps(backend="spring_boot", hosting="aws_ecs_fargate"))
        c = estimate(prof("P4"), comps(backend="spring_boot", hosting="aws_ecs_fargate"), extra_lines=[extra])
        self.assertEqual(c.lines[-1], extra)
        self.assertEqual(c.max, costs.round_sig(sum(ln.max for ln in base.lines) + 3))


class TestBudget(unittest.TestCase):
    def test_exceeded_is_critical(self):
        c = estimate(prof("P2", budget__monthly_infra_usd=10), comps(**P2_SUPABASE))
        self.assertEqual(c.verdict, "exceeded")
        w = next(w for w in c.warnings if w["code"] == "BUDGET_EXCEEDED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("USD 45-190", w["message"])

    def test_headroom_and_within(self):
        s = comps(backend="aspnet_core", database="sqlserver", database_offering="sqlserver__azure",
                  hosting="azure_app_service")
        c = estimate(prof("P5"), s)
        self.assertEqual(c.verdict, "tight")                        # 100-400 at s vs 300 (core only)
        rich = estimate(prof("P5", budget__monthly_infra_usd=50_000), s)
        self.assertEqual(rich.verdict, "headroom")
        self.assertIn("BUDGET_HEADROOM", codes(rich))
        mid = estimate(prof("P5", budget__monthly_infra_usd=1000), s)
        self.assertEqual(mid.verdict, "within")
        self.assertFalse({"BUDGET_TIGHT", "BUDGET_EXCEEDED", "BUDGET_HEADROOM"} & set(codes(mid)))

    def test_never_silent_random(self):
        rng = random.Random(1311)
        hosts = ("vercel", "aws_ecs_fargate", "do_app_platform", "azure_app_service", "fly_io", "cloudflare_pages")
        dbs = ("postgres__aws", "postgres__digitalocean", "postgres__supabase", "mongodb__atlas", None)
        for _ in range(200):
            budget = rng.choice((0, 5, 20, 50, 150, 400, 1500, 6000, 100_000))
            users = rng.choice((1000, 30_000, 300_000, 3_000_000))
            p = prof("P3", budget__monthly_infra_usd=budget, scale__users_12_months=users,
                     scale__peak_concurrent_users=max(1, users // 20))
            spec = dict(backend="fastify", hosting=rng.choice(hosts))
            off = rng.choice(dbs)
            if off:
                spec.update(database=offering(off)["engine"], database_offering=off)
            c = estimate(p, comps(**spec))
            self.assertLessEqual(c.min, c.max)
            self.assertIn(c.verdict, cost.VERDICTS)
            if c.max > budget:
                self.assertTrue({"BUDGET_TIGHT", "BUDGET_EXCEEDED"} & set(codes(c)), (budget, c.min, c.max))
            if c.min > budget:
                self.assertIn("BUDGET_EXCEEDED", codes(c))
            self.assertEqual(c, estimate(p, comps(**spec)))           # deterministic

    def test_output_conformance(self):
        c = estimate(prof("P2"), comps(**P2_SUPABASE))
        res = output.build(status="ok_with_warnings", estimated_monthly_cost_usd=c.to_output(),
                           warnings=list(c.warnings), stack=None)
        errs = [e for e in output.check(res) if e.startswith(("estimated_monthly_cost_usd", "warnings"))]
        self.assertEqual(errs, [])
        self.assertEqual(set(c.to_output()), {"min", "max", "assumptions"})
        bv = c.budget_verdict()
        self.assertEqual((bv["verdict"], bv["estimate_min"], bv["estimate_max"]), ("tight", 45, 190))
        json.dumps(c.trace())

    def test_assumptions_always(self):
        c = estimate(prof("P4"), comps(backend="spring_boot", hosting="aws_ecs_fargate"))
        text = " ".join(c.assumptions)
        self.assertIn("USD list prices", text)
        self.assertIn("Excluded:", text)
        self.assertIn("india regions", text)
        self.assertIn("size class m", text)


if __name__ == "__main__":
    unittest.main()

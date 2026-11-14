import copy
import dataclasses
import json
import random
import unittest
from pathlib import Path

from stacksense import kb, scoring
from stacksense.description import Signal
from stacksense.existing import ExistingMatch, ExistingReport
from stacksense.kb.model import CORE_LAYERS, SUPPORTING_LAYERS, tech
from stacksense.profile import derive
from stacksense.schema import FIELDS
from stacksense.scoring import W, LayerContext, context, rank, score
from stacksense.validate import validate

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def prof(raw=None, sid="P2", signals=(), existing=None, **paths):
    """Profile from a public scenario with dotted-path overrides (value None deletes the key)."""
    r = copy.deepcopy(raw if raw is not None else load(sid))
    for path, value in paths.items():
        parts = path.split("__") if "__" in path else path.split(".")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    v = validate(r)
    assert v.errors == [], v.errors
    return derive(v, signals, existing)


def ov(**kw):
    """Map keyword names like requirements__realtime to dotted overrides."""
    return {k.replace("__", "."): v for k, v in kw.items()}


def P(sid="P2", signals=(), existing=None, **kw):
    return prof(sid=sid, signals=signals, existing=existing, **ov(**kw))


def rec(layer="backend", kind="framework", id="t_x", **kw):
    kw.setdefault("cost", {"xs": (0, 0), "s": (0, 0), "m": (0, 0), "l": (0, 0)})
    return tech(id, kw.pop("name", id.upper()), layer, kind, **kw)


def contrib(t, p, layer=None, **ctx):
    s = score(t, p, LayerContext(layer=layer or t["layer"], **ctx))
    return s


def value(t, p, key, layer=None, **ctx):
    return contrib(t, p, layer, **ctx).value(key)


def literal_ok(c, p):
    """A non-zero contribution's reason quotes the literal value of at least one of its fields."""
    for f in c.fields:
        v = p.values.get(f) if f in p.values else None
        if f"{f}={scoring.fmt(v)}" in c.reason:
            return True
        if f"{f} includes" in c.reason or f"{f} mentions" in c.reason:
            return True
        if f == "team.languages" and f"team.languages={scoring.fmt(v)}" in c.reason:
            return True
        if f in c.reason and v is not None and scoring.fmt(v) in c.reason:
            return True
    return False


class TableAndTypes(unittest.TestCase):
    def test_w_has_every_contribution_constant(self):
        for k in ("priorities_scale", "skill_known_factor", "skill_penalty", "ops_over_factor",
                  "scale_over_per_class", "scale_under_per_class", "budget_share", "budget_none_free",
                  "req_native", "req_poor", "type_best", "type_avoid", "reuse_exact", "reuse_ecosystem",
                  "reuse_licence", "lock_in_factor", "availability_below", "latency_cold_start",
                  "timeline_factor", "traffic_elastic", "workload_write_good", "geo_wide_good",
                  "data_shape_match", "gdpr_eu_region", "growth_typed", "device", "security_factor",
                  "overengineering", "K8S_MIN_OPS", "K8S_MIN_SIZE", "MICRO_MIN_TEAM", "SOA_MIN_TEAM",
                  "MICRO_MIN_SIZE"):
            self.assertIn(k, W)
        self.assertEqual(W["budget_share"]["hosting"], 0.40)
        self.assertEqual(W["budget_share"]["database"], 0.25)
        self.assertEqual(W["budget_share"]["supporting"], 0.35)
        self.assertEqual(len(scoring.CONTRIBUTION_KEYS), 21)
        json.dumps(W)  # printable in the report

    def test_requirement_table_covers_every_requirement_field(self):
        covered = {path for path, *_ in scoring.REQUIREMENT_RULES}
        elsewhere = {"requirements.availability", "requirements.p95_latency_ms",
                     "requirements.consistency", "requirements.data_shape"}
        for path in FIELDS:
            if path.startswith("requirements."):
                with self.subTest(path):
                    self.assertTrue(path in covered or path in elsewhere)

    def test_context_shares(self):
        self.assertEqual(LayerContext("hosting").share(), 0.40)
        self.assertEqual(LayerContext("database").share(), 0.25)
        self.assertAlmostEqual(LayerContext("auth", supporting_layers=5).share(), 0.07)
        self.assertEqual(LayerContext("hosting", budget_share=0.1).share(), 0.1)


class Invariants(unittest.TestCase):
    def test_sum_rounding_fields_reasons_over_kb_and_scenarios(self):
        records = list(kb.RECORDS)
        self.assertGreater(len(records), 100)
        for sid in SIDS:
            p = P(sid)
            for r in records:
                ctx = LayerContext(r["layer"], supporting_layers=3)
                s = score(r, p, ctx)
                with self.subTest(sid=sid, id=r["id"]):
                    self.assertEqual(s.total, sum(c.value for c in s.contributions))
                    keys = [c.key for c in s.contributions]
                    self.assertEqual(len(keys), len(set(keys)))
                    for c in s.contributions:
                        self.assertIn(c.key, scoring.CONTRIBUTION_KEYS)
                        self.assertNotEqual(c.value, 0)
                        self.assertEqual(c.value, round(c.value, 2))
                        self.assertGreaterEqual(len(c.fields), 1)
                        self.assertTrue(all(f in FIELDS for f in c.fields), c.fields)
                        self.assertTrue(c.reason.strip())
                        self.assertTrue(literal_ok(c, p), (c.key, c.fields, c.reason))

    def test_contributions_ranges(self):
        bounds = {"priorities": (0, 10), "skill_fit": (-8, 4), "ops_fit": (-7.5, 1), "scale_fit": (-12, 1),
                  "budget_fit": (-8, 3), "requirement_fit": (-12, 10), "type_affinity": (-3, 3),
                  "reuse": (0, 5.5), "lock_in": (-4.5, 0), "availability_fit": (-10, 0),
                  "latency_fit": (-5, 2), "timeline_fit": (-3, 3), "traffic_fit": (-1.5, 1.5),
                  "workload_fit": (-1.5, 1.5), "geo_fit": (-2, 2), "data_fit": (-4, 6), "gdpr_pref": (0, 2),
                  "growth_fit": (-2, 3), "device_fit": (-3, 2), "security_fit": (-3.5, 2),
                  "overengineering": (-10, 0)}
        for sid in SIDS:
            p = P(sid)
            for r in kb.RECORDS:
                for c in score(r, p, LayerContext(r["layer"])).contributions:
                    lo, hi = bounds[c.key]
                    self.assertTrue(lo <= c.value <= hi, (sid, r["id"], c.key, c.value))


class Priorities(unittest.TestCase):
    def test_formula(self):
        p = P()
        best = rec(attrs={k: 5 for k in ("cost_efficiency", "dev_velocity", "scalability", "performance",
                                         "maintainability", "security")})
        self.assertEqual(value(best, p, "priorities"), 10)
        worst = rec(attrs={k: 1 for k in ("cost_efficiency", "dev_velocity", "scalability", "performance",
                                          "maintainability", "security")})
        self.assertEqual(value(worst, p, "priorities"), 2)
        mixed = rec(attrs={"cost_efficiency": 5, "dev_velocity": 1})
        # P2 weights: cost 4, ttm 5, others 3 -> (4*5 + 5*1 + 3*3*4) / (5*21) * 10
        self.assertEqual(value(mixed, p, "priorities"), round(10 * (20 + 5 + 36) / (5 * 21), 2))
        c = contrib(mixed, p).get("priorities")
        self.assertEqual(c.fields, ("priorities.time_to_market", "priorities.cost"))
        self.assertIn("priorities.time_to_market=5", c.reason)


class SkillFit(unittest.TestCase):
    def test_known_and_affinity(self):
        p = P()  # javascript, typescript, python
        self.assertEqual(value(rec(languages=["python"]), p, "skill_fit"), 4)
        p3 = P("P3")  # typescript, go
        r = rec(languages=["javascript"])
        self.assertEqual(value(r, p3, "skill_fit"), 3.6)
        c = contrib(r, p3).get("skill_fit")
        self.assertIn("team.languages=[typescript, go]", c.reason)
        self.assertIn("affinity 0.9", c.reason)

    def test_penalties(self):
        r = rec(languages=["elixir"])
        self.assertEqual(value(r, P("P3"), "skill_fit"), -2)                  # senior
        self.assertEqual(value(r, P(team__experience="intermediate"), "skill_fit"), -3)
        self.assertEqual(value(r, P(team__experience="beginner"), "skill_fit"), -4)
        self.assertEqual(value(r, P(team__willing_to_learn=False), "skill_fit"), -6)
        # beginner, unwilling, high delivery pressure -> capped at -8
        p = P("P1", team__willing_to_learn=False)
        self.assertGreaterEqual(p.delivery_pressure, 2)
        self.assertEqual(value(rec(languages=["elixir"], layer="frontend_web", kind="spa"), p, "skill_fit"), -8)
        c = contrib(rec(languages=["elixir"], layer="frontend_web", kind="spa"), p).get("skill_fit")
        self.assertIn("team.willing_to_learn", c.fields)

    def test_html_css_ssg_and_sql(self):
        p = P("P1", team__languages=["html", "css"])
        self.assertEqual(value(rec(layer="frontend_web", kind="ssg", languages=["javascript"]), p, "skill_fit"), 3.2)
        self.assertLess(value(rec(layer="frontend_web", kind="spa", languages=["javascript"]), p, "skill_fit"), 0)
        p5 = P("P5")  # csharp, sql, javascript
        self.assertEqual(value(rec(layer="database", kind="relational"), p5, "skill_fit"), 1)
        self.assertEqual(value(rec(layer="database", kind="document"), p5, "skill_fit"), -1)
        self.assertEqual(value(rec(layer="database", kind="relational"), P(), "skill_fit"), 0)

    def test_empty_languages_and_language_neutral(self):
        p = dataclasses.replace(P(), languages=())
        self.assertEqual(value(rec(languages=["go"], attrs={"popularity": 5}), p, "skill_fit"), 1.2)
        self.assertEqual(value(rec(languages=[]), P(), "skill_fit"), 0)


class OpsScaleBudget(unittest.TestCase):
    def test_ops(self):
        p = P()  # capacity 2
        self.assertEqual(value(rec(ops_burden=4), p, "ops_fit"), -3)
        self.assertEqual(value(rec(ops_burden=2), p, "ops_fit"), 0)
        p3 = P("P3", priorities__cost=5)  # capacity 5
        vm = rec(layer="hosting", kind="vm", ops_burden=1)
        self.assertEqual(value(vm, p3, "ops_fit"), 1)
        self.assertEqual(value(vm, P("P3"), "ops_fit"), 0)  # priorities.cost=2

    def test_scale(self):
        p = P()  # size s
        self.assertEqual(value(rec(scale_ceiling="xs"), p, "scale_fit"), -4)
        self.assertEqual(value(rec(scale_floor="l"), P("P1"), "scale_fit"), -7.5)  # xs, 3 classes under
        self.assertEqual(value(rec(attrs={"scalability": 5}), P("P3"), "scale_fit"), 1)
        self.assertEqual(value(rec(attrs={"scalability": 5}), p, "scale_fit"), 0)
        c = contrib(rec(scale_ceiling="xs"), p).get("scale_fit")
        self.assertIn("scale.users_12_months=30000", c.reason)

    def test_budget(self):
        free = rec(layer="hosting", kind="static_host", cost={"xs": (0, 0)},
                   free_tier={"limit": "free", "commercial_use": True})
        paid = rec(layer="hosting", kind="paas", cost={"xs": (5, 10)})
        nc = rec(layer="hosting", kind="static_host", cost={"xs": (0, 0)},
                 free_tier={"limit": "hobby", "commercial_use": False})
        p1 = P("P1")  # budget 0, xs
        self.assertEqual(value(free, p1, "budget_fit"), 3)
        self.assertEqual(value(paid, p1, "budget_fit"), -8)
        self.assertEqual(value(nc, p1, "budget_fit"), W["budget_free_noncommercial"])
        p = P(budget__monthly_infra_usd=100)  # size s, hosting share 40
        band = lambda lo, hi: rec(layer="hosting", kind="paas", cost={"s": (lo, hi)})
        self.assertEqual(value(band(10, 50), p, "budget_fit"), 0)            # mid 30 <= 40
        self.assertEqual(value(band(60, 100), p, "budget_fit"), -3)          # mid 80 = 2x share
        self.assertEqual(value(band(90, 400), p, "budget_fit"), -7.84)       # -3 x log2(245 / 40)
        self.assertEqual(value(band(200, 2000), p, "budget_fit"), -8)        # floor W["budget_fit_min"]
        # smooth: crossing min = budget adds a term that starts at 0 (no step), then -3 per doubling
        below, above = value(band(99, 120), p, "budget_fit"), value(band(101, 120), p, "budget_fit")
        self.assertLess(abs(below - above), 0.2)
        self.assertLess(value(band(150, 170), p, "budget_fit"), above)
        # cost differences stay visible at low budgets (the old -6 cap made every pricier option equal)
        lowp = P(budget__monthly_infra_usd=20)
        self.assertLess(value(band(60, 100), lowp, "budget_fit"), value(band(20, 40), lowp, "budget_fit"))
        self.assertEqual(value(rec(), p, "budget_fit"), 0)                   # free framework: no term
        # a product billed as one plan across layers is compared with the shares of every layer it covers
        self.assertEqual(scoring.bundle_share("supabase"), 1.05)
        self.assertEqual(scoring.bundle_share("supabase_cloud"), 1.05)
        self.assertIsNone(scoring.bundle_share("nestjs"))
        # supporting layers share 0.35 across the triggered layers
        sup = band(10, 20)
        self.assertEqual(value(sup, p, "budget_fit", layer="auth", supporting_layers=1), 0)
        self.assertLess(value(sup, p, "budget_fit", layer="auth", supporting_layers=5), 0)


class Requirements(unittest.TestCase):
    def test_seo(self):
        p = P()  # seo_critical true
        self.assertEqual(value(rec(layer="frontend_web", kind="ssg", caps=["ssg"]), p, "requirement_fit"), 2)
        self.assertEqual(value(rec(layer="frontend_web", kind="spa", caps=["spa"]), p, "requirement_fit"), -3)
        self.assertEqual(value(rec(layer="frontend_web", kind="spa", caps=["ssr"]), p, "requirement_fit"), 0)
        c = contrib(rec(layer="frontend_web", kind="spa"), p).get("requirement_fit")
        self.assertIn("requirements.seo_critical=true", c.reason)
        self.assertEqual(c.parts[0][0], "requirements.seo_critical")
        self.assertEqual(value(rec(layer="frontend_web", kind="spa"), P(requirements__seo_critical=False),
                               "requirement_fit"), 0)

    def test_realtime(self):
        p = P(requirements__file_media_storage=False, requirements__auth="none")
        self.assertEqual(value(rec(caps=["websocket", "long_lived_conn"]), p, "requirement_fit"), 2)
        self.assertEqual(value(rec(kind="serverless_fn", caps=["cold_start"]), p, "requirement_fit"), -3)
        self.assertEqual(value(rec(layer="hosting", kind="static_host"), p, "requirement_fit"), -3)
        self.assertEqual(value(rec(layer="hosting", kind="container", caps=["websocket", "long_lived_conn"]), p,
                               "requirement_fit"), 2)

    def test_database_rules(self):
        p = P()  # fts, payments
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["acid", "fts_builtin"]), p,
                               "requirement_fit"), 4)
        self.assertEqual(value(rec(layer="database", kind="document"), p, "requirement_fit"), -3)
        rag = P(requirements__ml_features="llm_rag", requirements__payments=False,
                requirements__full_text_search=False)
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["vector"]), rag, "requirement_fit"), 2)

    def test_auth_ml_jobs_cms_offline_push(self):
        sso = P("P5")
        self.assertEqual(value(rec(caps=["enterprise_sso"]), sso, "requirement_fit"), 2)
        self.assertEqual(value(rec(kind="baas"), sso, "requirement_fit"), -3)
        ml = P("P4")
        self.assertGreaterEqual(value(rec(languages=["python"], caps=["ml_python"]), ml, "requirement_fit"), 2)
        self.assertLess(value(rec(kind="baas"), ml, "requirement_fit"), 0)
        jobs = P(requirements__background_jobs=True, requirements__realtime=False,
                 requirements__file_media_storage=False, requirements__auth="none")
        self.assertEqual(value(rec(caps=["background_jobs"]), jobs, "requirement_fit"), 2)
        self.assertEqual(value(rec(layer="hosting", kind="static_host"), jobs, "requirement_fit"), -3)
        md = P("P1", requirements__cms="git_markdown")
        self.assertEqual(value(rec(layer="frontend_web", kind="ssg", caps=["ssg", "git_markdown"]), md,
                               "requirement_fit"), 4)
        sig = P("P1", signals=(Signal("git_markdown", "Markdown", "cms=git_markdown"),))
        c = contrib(rec(layer="frontend_web", kind="ssg", caps=["ssg", "git_markdown"]), sig).get("requirement_fit")
        self.assertEqual(c.value, 4)
        self.assertIn("project.description", c.fields)
        off = P("P6")  # offline + media
        self.assertEqual(value(rec(layer="frontend_mobile", kind="cross_platform", caps=["offline_sqlite"]), off,
                               "requirement_fit"), 2)
        self.assertEqual(value(rec(layer="frontend_mobile", kind="pwa", caps=["offline"]), off,
                               "requirement_fit"), -3)
        push = P("P6", requirements__notifications=["push"])
        self.assertEqual(value(rec(layer="frontend_mobile", kind="cross_platform",
                                   caps=["offline_sqlite", "push_notifications"]), push, "requirement_fit"), 4)

    def test_server_needed(self):
        static = P("P1")
        self.assertEqual(value(rec(kind="none", id="t_none"), static, "requirement_fit"), 2)
        self.assertEqual(value(rec(), static, "requirement_fit"), -3)
        self.assertEqual(value(rec(layer="hosting", kind="static_host"), static, "requirement_fit"), 2)
        self.assertEqual(value(rec(layer="hosting", kind="vm"), static, "requirement_fit"), -3)
        self.assertEqual(value(rec(kind="none", layer="database"), P(), "requirement_fit"), -3)


class OtherContributions(unittest.TestCase):
    def test_type_and_lock_in(self):
        p = P()  # marketplace
        self.assertEqual(value(rec(best_for=["marketplace"]), p, "type_affinity"), 3)
        self.assertEqual(value(rec(avoid_for=["marketplace"]), p, "type_affinity"), -3)
        self.assertEqual(value(rec(lock_in=3), P(infrastructure__lock_in_tolerance="low"), "lock_in"), -4.5)
        self.assertEqual(value(rec(lock_in=3), p, "lock_in"), -1.5)
        self.assertEqual(value(rec(lock_in=3), P(infrastructure__lock_in_tolerance="high"), "lock_in"), 0)

    def test_reuse(self):
        r = rec(id="t_dotnet", languages=["csharp"])
        exact = ExistingReport(matches=(ExistingMatch("Our API", "x", "framework", "aspnet",
                                                      reuse_targets=("t_dotnet",)),))
        self.assertEqual(value(r, P(existing=exact), "reuse"), 4)
        eco = ExistingReport(matches=(ExistingMatch("On-prem SQL Server 2019", "sqlserver", "database",
                                                    "sqlserver"),))
        self.assertEqual(value(r, P(existing=eco), "reuse"), 2)
        lic = P(existing=eco, infrastructure__existing_licences=["microsoft_enterprise"])
        self.assertEqual(value(r, lic, "reuse"), 3.5)
        c = contrib(r, lic).get("reuse")
        self.assertIn("On-prem SQL Server 2019", c.reason)
        self.assertEqual(value(r, P(), "reuse"), 0)  # p.existing empty today

    def test_availability(self):
        db = rec(layer="database", kind="relational")
        self.assertEqual(value(db, P("P4"), "availability_fit"), -5)                 # 99.95
        self.assertEqual(value(db, P(requirements__availability="99.99"), "availability_fit"), -10)
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["multi_az"]),
                               P(requirements__availability="99.99"), "availability_fit"), -5)
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["multi_region"]),
                               P(requirements__availability="99.99"), "availability_fit"), 0)
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["distributed_sql", "multi_az"]),
                               P("P1"), "availability_fit"), -1)
        self.assertEqual(value(rec(), P("P4"), "availability_fit"), 0)  # frameworks are not judged

    def test_latency(self):
        fast = rec(attrs={"performance": 5})
        self.assertEqual(value(fast, P("P3"), "latency_fit"), 2)                    # p95 100
        self.assertEqual(value(fast, P("P4"), "latency_fit"), 1)                    # p95 300 -> half
        self.assertEqual(value(fast, P(), "latency_fit"), 0)                        # p95 500
        self.assertEqual(value(fast, P("P1"), "latency_fit"), 0)                    # null
        cold = rec(layer="hosting", kind="serverless_fn", caps=["cold_start"])
        self.assertEqual(value(cold, P("P3"), "latency_fit"), -3)
        self.assertEqual(value(rec(layer="hosting", kind="paas", caps=["cold_start", "min_instances"]), P("P3"),
                               "latency_fit"), 0)

    def test_timeline(self):
        p = P("P1")  # pressure 3
        self.assertEqual(value(rec(attrs={"dev_velocity": 5}), p, "timeline_fit"), 3)
        self.assertEqual(value(rec(attrs={"dev_velocity": 1}), p, "timeline_fit"), -3)
        self.assertEqual(value(rec(attrs={"dev_velocity": 5}), P("P3"), "timeline_fit"), 0)

    def test_traffic(self):
        spiky = P("P3")  # spiky, m
        self.assertEqual(value(rec(layer="hosting", kind="paas", caps=["autoscaling"]), spiky, "traffic_fit"), 1.5)
        self.assertEqual(value(rec(layer="hosting", kind="vm", caps=["fixed_capacity"]), spiky, "traffic_fit"), -1.5)
        steady_m = P("P3", scale__traffic_pattern="steady")
        self.assertEqual(value(rec(layer="hosting", kind="vm"), steady_m, "traffic_fit"), 1)
        self.assertEqual(value(rec(layer="hosting", kind="vm"), P(), "traffic_fit"), 0)  # steady, s

    def test_workload(self):
        wh = P("P3")
        self.assertEqual(value(rec(layer="database", kind="kv", caps=["lsm_writes"]), wh, "workload_fit"), 1.5)
        self.assertEqual(value(rec(layer="database", kind="embedded", caps=["embedded"]), wh, "workload_fit"), -1.5)
        self.assertEqual(value(rec(layer="database", kind="relational", caps=["read_replicas"]), P("P1"),
                               "workload_fit"), 1)

    def test_geo(self):
        g = P(scale__geographic_spread="global")
        self.assertEqual(value(rec(layer="hosting", kind="paas", caps=["edge"]), g, "geo_fit"), 2)
        self.assertEqual(value(rec(layer="hosting", kind="paas"), g, "geo_fit"), -2)
        india = rec(layer="hosting", kind="paas", regions={"india": ["ap-south-1"]})
        self.assertEqual(value(india, P(), "geo_fit"), 1)
        self.assertEqual(value(india, P("P3"), "geo_fit"), 0)  # residency none

    def test_data_and_gdpr(self):
        p3 = P("P3")  # strong (payments), relational, multi-tenant, gdpr with residency none
        pg = rec(layer="database", kind="relational", caps=["acid", "rls_multi_tenant"],
                 regions={"eu": ["eu-central-1"]}, data_at_rest=True)
        self.assertEqual(value(pg, p3, "data_fit"), 6)
        self.assertEqual(value(rec(layer="database", kind="document"), p3, "data_fit"), -4)
        self.assertEqual(value(rec(layer="database", kind="graph"), P(requirements__data_shape="graph",
                                                                     requirements__payments=False,
                                                                     requirements__consistency="eventual"),
                               "data_fit"), 4)
        self.assertEqual(value(pg, p3, "gdpr_pref"), 2)
        self.assertEqual(value(pg, P(), "gdpr_pref"), 0)

    def test_growth(self):
        p = P(team__growth_12_months=12)
        self.assertEqual(value(rec(languages=["typescript"], attrs={"maintainability": 5}), p, "growth_fit"), 3)
        self.assertEqual(value(rec(languages=["python"], attrs={"maintainability": 1}), p, "growth_fit"), -2)
        self.assertEqual(value(rec(languages=["typescript"], attrs={"maintainability": 5}), P(), "growth_fit"), 0)

    def test_device(self):
        sig = (Signal("low_end_devices", "low-end Android phones", "device=low_end"),)
        p = P("P6", signals=sig)
        m = lambda kind, **kw: rec(layer="frontend_mobile", kind=kind, **kw)
        self.assertEqual(value(m("native", languages=["kotlin"]), p, "device_fit"), 2)
        self.assertEqual(value(m("cross_platform", languages=["dart"]), p, "device_fit"), 1)
        self.assertEqual(value(m("cross_platform", languages=["typescript"]), p, "device_fit"), -0.5)
        self.assertEqual(value(m("hybrid_webview", languages=["typescript"]), p, "device_fit"), -1.5)
        self.assertEqual(value(m("pwa"), p, "device_fit"), -1.5)
        self.assertEqual(value(rec(layer="frontend_desktop", kind="webview_shell"), p, "device_fit"), -3)
        self.assertEqual(value(m("native"), P("P6"), "device_fit"), 0)
        self.assertIn("low-end Android phones", contrib(m("native"), p).get("device_fit").reason)

    def test_security(self):
        p4 = P("P4")  # security 5, fintech, pci/rbi
        self.assertEqual(value(rec(attrs={"security": 5}), p4, "security_fit"), 2)
        self.assertEqual(value(rec(kind="baas", attrs={"security": 3}), p4, "security_fit"), -1.5)
        self.assertEqual(value(rec(attrs={"security": 5}), P(), "security_fit"), 0)

    def test_overengineering_k8s_and_distributed_sql(self):
        k8s = rec(layer="hosting", kind="k8s", ops_burden=4, scale_floor="m")
        self.assertEqual(value(k8s, P(), "overengineering"), W["overengineering"])    # ops 2, size s
        self.assertEqual(value(k8s, P("P3"), "overengineering"), 0)                  # ops 5, size m
        small = P("P3", scale__users_12_months=3000, scale__users_at_launch=100, scale__peak_concurrent_users=50,
                  scale__data_volume_gb_12_months=1)
        self.assertEqual(value(k8s, small, "overengineering"), W["overengineering"])  # ops 5, size xs
        onprem = P("P3", scale__users_12_months=3000, scale__users_at_launch=100, scale__peak_concurrent_users=50,
                   scale__data_volume_gb_12_months=1, infrastructure__deployment_model="on_premise")
        self.assertEqual(value(k8s, onprem, "overengineering"), 0)                    # on-prem, team 5
        dsql = rec(layer="database", kind="relational", caps=["acid", "distributed_sql"])
        self.assertEqual(value(dsql, P("P3"), "overengineering"), W["overengineering"])
        self.assertEqual(value(dsql, P("P3", scale__geographic_spread="global"), "overengineering"), 0)
        self.assertTrue(scoring.k8s_allowed(P("P4")))
        self.assertFalse(scoring.k8s_allowed(P("P2")))


class Ranking(unittest.TestCase):
    def test_sort_order_and_tie_break(self):
        p = P()
        a = rec(id="t_b", attrs={"dev_velocity": 5})
        b = rec(id="t_a", attrs={"dev_velocity": 5})
        c = rec(id="t_c", attrs={"dev_velocity": 1})
        out = rank("backend", [c, a, b], p, context("backend"))
        self.assertEqual([s.tech["id"] for s in out], ["t_a", "t_b", "t_c"])
        self.assertEqual(out[0].total, out[1].total)
        self.assertGreater(out[1].total, out[2].total)

    def test_shuffle_determinism(self):
        rng = random.Random(1234)
        for sid in SIDS:
            p = P(sid)
            for layer in CORE_LAYERS:
                cands = kb.by_layer(layer)
                base = [(s.tech["id"], s.total, s.contributions) for s in rank(layer, cands, p, context(layer))]
                for _ in range(3):
                    shuffled = list(cands)
                    rng.shuffle(shuffled)
                    again = [(s.tech["id"], s.total, s.contributions)
                             for s in rank(layer, shuffled, p, context(layer))]
                    self.assertEqual(base, again)

    def test_rank_layer_overrides_ctx(self):
        p = P()
        out = rank("hosting", kb.by_layer("hosting"), p, LayerContext("backend"))
        self.assertTrue(all(s.tech["layer"] == "hosting" for s in out))


class Monotonicity(unittest.TestCase):
    PRICED = ("hosting", "database", "backend")

    def test_mono_01_budget_never_lowers_budget_fit(self):
        for sid in SIDS:
            raw = load(sid)
            base_budget = raw["budget"]["monthly_infra_usd"]
            for factor in (2, 10):
                p0 = P(sid)
                p1 = P(sid, budget__monthly_infra_usd=base_budget * factor)
                for layer in self.PRICED:
                    for r in kb.by_layer(layer):
                        with self.subTest(sid=sid, factor=factor, id=r["id"]):
                            v0 = value(r, p0, "budget_fit", layer=layer)
                            v1 = value(r, p1, "budget_fit", layer=layer)
                            self.assertGreaterEqual(v1, v0)
            # from a positive base, more budget never lowers the total either
            if base_budget > 0:
                p0, p1 = P(sid), P(sid, budget__monthly_infra_usd=base_budget * 10)
                for layer in self.PRICED:
                    for r in kb.by_layer(layer):
                        self.assertGreaterEqual(score(r, p1, context(layer)).total,
                                                score(r, p0, context(layer)).total)

    def test_mono_04_ops_capacity(self):
        for sid in SIDS:
            raw = load(sid)
            small = P(sid)
            bigger = P(sid, team__has_devops=True, team__size=max(6, raw["team"]["size"]))
            self.assertGreaterEqual(bigger.ops_capacity, small.ops_capacity)
            for layer in CORE_LAYERS:
                for r in kb.by_layer(layer):
                    with self.subTest(sid=sid, id=r["id"]):
                        self.assertGreaterEqual(value(r, bigger, "ops_fit", layer=layer),
                                                value(r, small, "ops_fit", layer=layer))
        # Kubernetes is penalised below the thresholds and not above them
        for r in kb.by_layer("hosting"):
            if r["kind"] != "k8s":
                continue
            for sid in ("P1", "P2", "P5", "P6"):
                self.assertEqual(value(r, P(sid), "overengineering"), W["overengineering"], (sid, r["id"]))
            for sid in ("P3", "P4"):
                self.assertEqual(value(r, P(sid), "overengineering"), 0, (sid, r["id"]))
            # lowering devops/team below the threshold re-introduces the penalty
            weak = P("P3", team__has_devops=False, team__experience="intermediate")
            self.assertLess(weak.ops_capacity, scoring.K8S_MIN_OPS)
            self.assertEqual(value(r, weak, "overengineering"), W["overengineering"])

    def test_mono_05_cost_priority(self):
        cheap = rec(id="t_cheap", attrs={"cost_efficiency": 5, "performance": 2})
        dear = rec(id="t_dear", attrs={"cost_efficiency": 1, "performance": 5})
        lo = rank("backend", [cheap, dear], P(priorities__cost=1, priorities__performance=5), context("backend"))
        hi = rank("backend", [cheap, dear], P(priorities__cost=5, priorities__performance=1), context("backend"))
        self.assertEqual(lo[0].tech["id"], "t_dear")
        self.assertEqual(hi[0].tech["id"], "t_cheap")
        # On the real KB: raising priorities.cost 1 -> 5 never lowers the mean cost_efficiency of the top 3
        for sid in SIDS:
            for layer in ("hosting", "database"):
                cands = [r for r in kb.by_layer(layer) if r["status"] == "maintained"]
                m = {}
                for w in (1, 5):
                    top = rank(layer, cands, P(sid, priorities__cost=w), context(layer))[:3]
                    m[w] = sum(s.tech["attrs"]["cost_efficiency"] for s in top) / 3
                self.assertGreaterEqual(m[5], m[1], (sid, layer))
                # and every candidate's priorities term moves with its own cost_efficiency
                for r in cands:
                    d = (value(r, P(sid, priorities__cost=5), "priorities", layer=layer)
                         - value(r, P(sid, priorities__cost=1), "priorities", layer=layer))
                    p = P(sid, priorities__cost=1)
                    others = [(k, p.weight(k)) for k in scoring.PRIORITY_ATTR if k != "cost"]
                    mean = sum(w * r["attrs"][scoring.PRIORITY_ATTR[k]] for k, w in others) / sum(w for _, w in others)
                    if r["attrs"]["cost_efficiency"] > mean + 0.01:
                        self.assertGreater(d, -0.011, (sid, r["id"]))


if __name__ == "__main__":
    unittest.main()

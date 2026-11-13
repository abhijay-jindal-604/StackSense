"""Combination search and compatibility (plan 3.9, 5.4)."""
import copy
import json
import random
import unittest
from dataclasses import replace
from pathlib import Path

from stacksense import architecture, combine, cost, description, existing, filters, kb, scoring
from stacksense.combine import T, search
from stacksense.profile import derive
from stacksense.scoring import Scored
from stacksense.validate import validate
from tests import helpers

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def prof(sid="P2", raw=None, **paths):
    r = copy.deepcopy(raw if raw is not None else load(sid))
    for path, value in paths.items():
        parts = path.split("__")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    v = validate(r)
    assert v.errors == [], v.errors
    signals = description.extract(r.get("project", {}).get("description"))
    return derive(v, signals, existing.analyse(r.get("infrastructure", {}).get("existing_systems")))


def ranked_for(p):
    """Filter and score every core layer the way the engine does (scoring/filters public API)."""
    hosts, _ = filters.filter_layer("hosting", p)
    out = {}
    for layer in ("frontend_web", "frontend_mobile", "frontend_desktop", "backend", "database", "hosting"):
        if layer == "frontend_web" and "web" not in p.clients:
            continue
        if layer == "frontend_mobile" and not any(c in p.clients for c in ("android", "ios")):
            continue
        if layer == "frontend_desktop" and "desktop" not in p.clients:
            continue
        kw = {"hosts": hosts} if layer == "backend" else {}
        kept, _ = filters.filter_layer(layer, p, **kw)
        out[layer] = scoring.rank(layer, kept, p, scoring.context(layer))
    return out


def S(tid, total=10.0):
    rec = kb.get(tid)
    assert rec is not None, tid
    return Scored(rec, total, ())


def web(tid, total=10.0):
    return combine.ClientPart("frontend_web", ("web",), S(tid, total))


def output_stack(c):
    """Minimal statement-shaped stack for tests.helpers (ids, not names)."""
    hosting = [{"kb_id": c.hosting.tech["id"]}]
    if c.separate_frontend_host:
        hosting.append({"kb_id": c.frontend_hosting.tech["id"]})
    off = c.database_offering.offering
    return {"stack": {
        "frontend": [{"kb_id": r["id"]} for pt in c.parts for r in pt.records()],
        "backend": {"kb_id": c.backend.tech["id"]},
        "database": {"kb_id": c.database.tech["id"], "offering_id": off["id"] if off else None},
        "hosting": hosting}}


# ------------------------------------------------------------------ hard rules
class HardRulesTest(unittest.TestCase):
    def setUp(self):
        self.p1, self.p2, self.p3, self.p4 = prof("P1"), prof("P2"), prof("P3"), prof("P4")

    def bh(self, be, host, p, cache=None):
        return combine.check_backend_host(S(be), S(host), p, {} if cache is None else cache)

    def test_c1_runtime_on_host(self):
        r, _ = self.bh("fastify", "github_pages", self.p3)
        self.assertTrue(r[1].startswith("C1 "), r)
        self.assertIn("node", r[1])
        r, _ = self.bh("fastify", "cloudflare_workers_host", self.p3)
        self.assertEqual(r[0], "C1")
        self.assertIsNone(self.bh("nestjs", "aws_lambda_host", self.p1)[0])     # Lambda runs node
        self.assertIsNone(self.bh("aspnet_core", "azure_app_service", self.p1)[0])

    def test_c1_functions_product_needs_its_own_functions_host(self):
        self.assertIsNone(self.bh("aws_lambda_apigw", "aws_lambda_host", self.p1)[0])
        self.assertIsNone(self.bh("cloudflare_workers_hono", "cloudflare_workers_host", self.p1)[0])
        for be, host in (("aws_lambda_apigw", "vercel"), ("aws_lambda_apigw", "aws_ecs_fargate"),
                         ("cloudflare_workers_hono", "vercel"), ("gcp_cloud_run_functions", "aws_lambda_host")):
            r, _ = self.bh(be, host, self.p1)
            self.assertEqual(r[0], "C1", (be, host))

    def test_c2_realtime(self):
        self.assertEqual(self.bh("nestjs", "aws_ecs_fargate", self.p3), (None, ()))
        r, flags = self.bh("nestjs", "vercel", self.p3)
        self.assertIsNone(r)
        self.assertEqual(flags, ("needs_managed_realtime",))
        # no managed realtime service available -> dropped
        r, flags = self.bh("nestjs", "vercel", self.p3, cache={"realtime": []})
        self.assertEqual(r[0], "C2")
        self.assertIn("requirements.realtime=true", r[1])
        # BaaS with built-in realtime needs no long-lived host
        self.assertEqual(self.bh("supabase", "supabase_cloud", self.p2), (None, ()))
        # no realtime requirement -> no flag
        self.assertEqual(self.bh("nestjs", "vercel", self.p1), (None, ()))

    def test_c3_database_on_host(self):
        cache = {}
        res = combine.resolve_database(S("nestjs"), S("postgres"), S("fly_io"), self.p2, cache)
        self.assertFalse(res.ok)
        self.assertEqual(res.rule, "C3")
        combo, rej = combine._evaluate(web("nextjs"), S("nestjs"), S("postgres"), S("fly_io"), [], self.p2, {})
        self.assertIsNone(combo)
        self.assertEqual(rej[:2], ("database", "hosting"))
        self.assertTrue(rej[4].startswith("C3 database on host:"))
        res = combine.resolve_database(S("nestjs"), S("sqlserver"), S("vercel"), self.p1, {})
        self.assertFalse(res.ok)

    def test_c4_frontend_needs_a_host(self):
        r = combine.check_frontend_backend(web("nextjs"), S("none_backend"), self.p2)
        self.assertEqual(r[0], "C4")             # needs_backend is true for P2
        self.assertIsNone(combine.check_frontend_backend(web("astro"), S("none_backend"), self.p1))
        fe_host, r = combine.choose_frontend_host(web("astro"), S("none_backend"), S("aws_ecs_fargate"), [], self.p1)
        self.assertIsNone(fe_host)
        self.assertEqual(r[0], "C4")
        # Next.js static export is allowed for a site without a backend
        fe_host, r = combine.choose_frontend_host(web("nextjs"), S("none_backend"), S("github_pages"), [], self.p1)
        self.assertIsNone(r)
        self.assertEqual(fe_host.tech["id"], "github_pages")
        # SSR needs a node host: Supabase Cloud cannot serve it and GitHub Pages is static only
        fe_host, r = combine.choose_frontend_host(web("nextjs"), S("supabase"), S("supabase_cloud"),
                                                  [S("github_pages")], self.p2)
        self.assertEqual(r[0], "C4")
        fe_host, r = combine.choose_frontend_host(web("nextjs"), S("supabase"), S("supabase_cloud"),
                                                  [S("github_pages"), S("vercel", 1.0), S("render", 1.5)], self.p2)
        self.assertEqual(fe_host.tech["id"], "vercel")       # +1.5 Next.js/Vercel synergy beats 0.5 points
        # backend None with a database is invalid
        r = combine.check_backend_database(S("none_backend"), S("postgres"), self.p1)
        self.assertEqual(r[0], "C4")

    def test_frontend_host_prefers_app_host_then_same_provider(self):
        fe_host, _ = combine.choose_frontend_host(web("nextjs"), S("nestjs"), S("aws_ecs_fargate"),
                                                  [S("vercel", 50)], self.p3)
        self.assertEqual(fe_host.tech["id"], "aws_ecs_fargate")
        fe_host, _ = combine.choose_frontend_host(web("react_vite"), S("nestjs"), S("aws_ecs_fargate"),
                                                  [S("vercel", 50), S("aws_amplify", 1)], self.p3)
        self.assertEqual(fe_host.tech["id"], "aws_amplify")
        # no same-provider static host: the container serves the built assets itself
        fe_host, _ = combine.choose_frontend_host(web("react_vite"), S("nestjs"), S("aws_ecs_fargate"),
                                                  [S("vercel", 50)], self.p3)
        self.assertEqual(fe_host.tech["id"], "aws_ecs_fargate")
        # server templates are rendered by the backend host
        fe_host, _ = combine.choose_frontend_host(web("htmx_templates"), S("django"), S("render"), [], self.p2)
        self.assertEqual(fe_host.tech["id"], "render")

    def test_c5_baas_coupling(self):
        for be, db in (("supabase", "mysql"), ("firebase", "postgres"), ("pocketbase", "postgres"),
                       ("shopify", "postgres")):
            r = combine.check_backend_database(S(be), S(db), self.p1)
            self.assertEqual(r[0], "C5", (be, db))
        self.assertIsNone(combine.check_backend_database(S("supabase"), S("postgres"), self.p1))
        self.assertIsNone(combine.check_backend_database(S("firebase"), S("firestore"), self.p1))
        self.assertEqual(self.bh("supabase", "vercel", self.p2)[0][0], "C5")
        self.assertIsNone(self.bh("supabase", "supabase_cloud", self.p2)[0])
        self.assertEqual(self.bh("shopify", "vercel", self.p1)[0][0], "C5")
        self.assertIsNone(self.bh("shopify", "shopify_hosted", self.p1)[0])
        self.assertIsNone(self.bh("firebase", "firebase_app_hosting", self.p1)[0])
        self.assertEqual(self.bh("firebase", "vercel", self.p1)[0][0], "C5")
        self.assertIsNone(self.bh("pocketbase", "hetzner_compose", self.p1)[0])
        self.assertEqual(self.bh("pocketbase", "vercel", self.p1)[0][0], "C5")
        selfp = prof("P2", infrastructure__deployment_model="self_hosted_cloud_vm")
        self.assertIsNone(self.bh("supabase", "do_droplets_compose", selfp)[0])   # self-hosted Supabase
        # the database comes from the Supabase family
        res = combine.resolve_database(S("supabase"), S("postgres"), S("supabase_cloud"), self.p2, {})
        self.assertEqual(res.offering["id"], "postgres__supabase")

    def test_c6_frontend_backend_pairing(self):
        self.assertEqual(combine.check_frontend_backend(web("blazor"), S("nestjs"), self.p2)[0], "C6")
        self.assertIsNone(combine.check_frontend_backend(web("blazor"), S("aspnet_core"), self.p2))
        self.assertEqual(combine.check_frontend_backend(web("htmx_templates"), S("supabase"), self.p2)[0], "C6")
        self.assertIsNone(combine.check_frontend_backend(web("htmx_templates"), S("django"), self.p2))
        self.assertEqual(combine.check_frontend_backend(web("react_vite"), S("nextjs_api"), self.p2)[0], "C6")
        self.assertIsNone(combine.check_frontend_backend(web("nextjs"), S("nextjs_api"), self.p2))
        self.assertEqual(combine.check_frontend_backend(None, S("nextjs_api"), prof("P6"))[0], "C6")

    def test_c7_pooler(self):
        self.assertTrue(combine._needs_pooler(S("aws_lambda_apigw"), S("aws_lambda_host")))
        self.assertTrue(combine._needs_pooler(S("nestjs"), S("vercel")))
        self.assertFalse(combine._needs_pooler(S("nestjs"), S("aws_ecs_fargate")))
        self.assertFalse(combine._needs_pooler(S("supabase"), S("supabase_cloud")))
        res = combine.resolve_database(S("nestjs"), S("postgres"), S("fly_io"), self.p1, {})
        self.assertEqual(res.offering["id"], "postgres__fly")
        res = combine.resolve_database(S("nestjs"), S("postgres"), S("aws_lambda_host"), self.p1, {})
        self.assertEqual(res.offering["id"], "postgres__aws")
        from stacksense import offerings
        self.assertTrue(offerings.has_pooler(res.offering))

    def test_c8_kubernetes_threshold(self):
        r, _ = self.bh("nestjs", "amazon_eks", self.p2)        # ops capacity 2, size s
        self.assertEqual(r[0], "C8")
        self.assertIn("operations capacity", r[1])
        self.assertIsNone(self.bh("spring_boot", "amazon_eks", self.p4)[0])   # team 8 with DevOps, size m

    def test_rejection_reasons_name_the_rule(self):
        res = search(ranked_for(self.p2), self.p2)
        self.assertTrue(res.rejected_pairs)
        for rp in res.rejected_pairs:
            a, b, reason = rp
            self.assertIn(rp.rule, combine.RULE_NAMES)
            self.assertTrue(reason.startswith(f"{rp.rule} {combine.RULE_NAMES[rp.rule]}: "))
            self.assertTrue(a and b)
        self.assertEqual(res.rejected_pairs, sorted(res.rejected_pairs))
        self.assertEqual(len(res.rejected_pairs), len(set(res.rejected_pairs)))


# ------------------------------------------------------------------ soft terms
class SynergyTest(unittest.TestCase):
    def setUp(self):
        self.p1, self.p2, self.p4 = prof("P1"), prof("P2"), prof("P4")

    def syn(self, fe, be, db, host, fe_host, p, flags=()):
        res = combine.resolve_database(S(be), S(db), S(host), p, {})
        fe_part = web(fe) if fe else None
        out = combine.synergies(fe_part, S(be), S(db), S(host), S(fe_host) if fe_host else None, res, p, flags)
        return {c.key: c.value for c in out}, out

    def test_table_within_cap(self):
        self.assertEqual(T["K"], 6)
        for k, v in T["synergy"].items():
            self.assertLessEqual(abs(v), T["synergy_cap"], k)
        self.assertLessEqual(T["synergy_cap"], 2.0)
        for k in ("client_shared_language", "one_codebase", "two_natives", "web_reuse"):
            self.assertLessEqual(abs(T[k]), 2.5)

    def test_values(self):
        v, _ = self.syn("nextjs", "nestjs", "postgres", "vercel", "vercel", self.p1)
        self.assertEqual(v["framework_host"], 1.5)
        self.assertEqual(v["shared_language"], 1.5)
        v, _ = self.syn("astro", "none_backend", "none", "netlify", "netlify", self.p1)
        self.assertEqual(v, {"ssg_static_host": 1.5})
        v, _ = self.syn("blazor", "aspnet_core", "sqlserver", "azure_app_service", "azure_app_service", prof("P5"))
        self.assertEqual((v["backend_host"], v["blazor_aspnet"], v["same_cloud"]), (1.5, 1.5, 1.0))
        v, _ = self.syn("react_vite", "spring_boot", "postgres", "aws_ecs_fargate", "aws_amplify", self.p4)
        self.assertEqual(v["jvm_containers"], 1.0)
        self.assertEqual(v["same_cloud"], 1.0)
        self.assertNotIn("shared_language", v)              # team.size 8 > 5 and no shared language
        v, _ = self.syn("react_vite", "django", "postgres", "do_app_platform", "do_app_platform", self.p2)
        self.assertEqual(v["batteries_postgres"], 1.0)
        v, _ = self.syn("nextjs", "supabase", "postgres", "supabase_cloud", "vercel", self.p2)
        self.assertEqual(v["supabase_client"], 1.0)
        self.assertEqual(v["same_cloud"], 1.0)              # Supabase Postgres on Supabase Cloud
        self.assertEqual(v["framework_host"], 1.5)
        v, _ = self.syn("astro", "cloudflare_workers_hono", "cloudflare_d1", "cloudflare_workers_host",
                        "cloudflare_pages", self.p1)
        self.assertEqual(v["workers_d1"], 1.5)
        self.assertEqual(v["ssg_static_host"], 1.5)

    def test_bff_split_and_managed_realtime(self):
        v, out = self.syn("nextjs", "django", "postgres", "do_app_platform", "do_app_platform", self.p2)
        self.assertEqual(v["bff_split"], -1.0)               # team.size 3, Next.js server + Python API
        c = next(x for x in out if x.key == "bff_split")
        self.assertIn("team.size=3", c.reason)
        self.assertEqual(c.fields, ("team.size",))
        big = prof("P2", team__size=4)
        v, _ = self.syn("nextjs", "django", "postgres", "do_app_platform", "do_app_platform", big)
        self.assertNotIn("bff_split", v)
        v, out = self.syn("nextjs", "nestjs", "postgres", "vercel", "vercel", self.p2, ("needs_managed_realtime",))
        self.assertEqual(v["managed_realtime"], -1.0)

    def test_every_synergy_is_a_cited_contribution(self):
        _, out = self.syn("nextjs", "nestjs", "postgres", "vercel", "vercel", self.p1)
        for c in out:
            self.assertIsInstance(c, scoring.Contribution)
            self.assertTrue(c.reason.endswith(").") or c.reason.endswith("."))
            self.assertIn(c.key, T["synergy"])

    def test_language_penalty(self):
        self.assertEqual(combine.choose_languages([kb.get("nextjs"), kb.get("nestjs")], self.p2), ("javascript",))
        self.assertEqual(combine.choose_languages([kb.get("blazor"), kb.get("aspnet_core")], self.p2), ("csharp",))
        self.assertEqual(combine.choose_languages([kb.get("react_vite"), kb.get("supabase")], self.p2), ("javascript",))
        self.assertEqual(combine.choose_languages([None, kb.get("supabase")], self.p2), ())
        langs = combine.choose_languages([kb.get("nextjs"), kb.get("django")], self.p2)
        self.assertEqual(len(langs), 2)
        pen = combine.language_penalty(langs, self.p2)      # team.size 3
        self.assertEqual(pen.value, -0.75)
        self.assertIn("team.size", pen.fields)
        pen = combine.language_penalty(("java", "typescript"), self.p4)   # team.size 8
        self.assertEqual(pen.value, round(-0.75 * 0.3, 2))
        self.assertEqual(combine.language_penalty(("a", "b", "c"), self.p2).value, -1.5)
        self.assertIsNone(combine.language_penalty(("typescript",), self.p2))
        self.assertIsNone(combine.language_penalty((), self.p2))

    def test_combo_score_is_the_sum(self):
        res = search(ranked_for(self.p2), self.p2)
        for c in [res.best] + res.runners_up:
            fe = c.frontend.scored.total if c.frontend else 0.0
            self.assertAlmostEqual(c.layer_total, round(fe + c.backend.total + c.database.total + c.hosting.total, 2))
            self.assertAlmostEqual(c.score, round(c.layer_total + sum(s.value for s in c.synergies), 2))


# ------------------------------------------------------------------ clients after the core
class ClientPickTest(unittest.TestCase):
    def test_codebase_terms(self):
        both = prof("P4", team__size=3)
        rn = combine.ClientPart("frontend_mobile", ("android", "ios"), S("react_native_expo"))
        natives = combine.ClientPart("frontend_mobile", ("android",), S("compose_android"),
                                     S("swiftui_ios"), ("ios",))
        self.assertEqual([c.value for c in combine.codebase_terms(rn, both)], [2.5])
        self.assertEqual([c.value for c in combine.codebase_terms(natives, both)], [-2.0])
        big = prof("P4")      # team.size 8: no one-codebase bonus, no two-native penalty
        self.assertEqual(combine.codebase_terms(rn, big), [])
        self.assertEqual(combine.codebase_terms(natives, big), [])
        expected = f"{kb.get('compose_android')['name']} (Android) and {kb.get('swiftui_ios')['name']} (iOS)"
        self.assertEqual(natives.label, expected)   # plan 5.4: both native toolkits joined

    def test_joined_natives_from_options(self):
        p = prof("P4")
        opts = combine._client_options("frontend_mobile", [S("compose_android", 9), S("swiftui_ios", 8),
                                                           S("react_native_expo", 7)], p)
        ids = [o.id for o in opts]
        self.assertEqual(ids, ["compose_android+swiftui_ios", "swiftui_ios+compose_android", "react_native_expo"])
        android_only = prof("P6")
        opts = combine._client_options("frontend_mobile", [S("compose_android"), S("swiftui_ios")], android_only)
        self.assertEqual([o.id for o in opts], ["compose_android"])

    def test_shared_language_and_web_reuse(self):
        p = prof("P2")
        res = search(ranked_for(p), p)
        best = res.best
        combo = replace(best, frontend=web("nextjs"), backend=S("django"), clients=())
        rn = combine.ClientPart("frontend_mobile", ("android",), S("react_native_expo"))
        flutter = combine.ClientPart("frontend_mobile", ("android",), S("flutter"))
        self.assertEqual({c.key: c.value for c in combine.client_terms(rn, combo, p)}.get("shared_language"), 2.0)
        self.assertNotIn("shared_language", {c.key for c in combine.client_terms(flutter, combo, p)})
        combo = replace(best, frontend=web("react_vite"), clients=())
        self.assertEqual({c.key: c.value for c in combine.client_terms(rn, combo, p)}.get("web_reuse"), 1.0)
        combo = replace(best, frontend=web("angular"), clients=())
        self.assertNotIn("web_reuse", {c.key for c in combine.client_terms(rn, combo, p)})

    def test_composite_label_and_parts(self):
        p2 = prof("P2")
        best = search(ranked_for(p2), p2).best
        self.assertEqual([pt.layer for pt in best.parts], ["frontend_web", "frontend_mobile"])
        label = best.frontend_label
        self.assertTrue(label.startswith(best.parts[0].scored.tech["name"] + " (web) + "), label)
        self.assertTrue(label.endswith("(Android)"), label)
        p1 = prof("P1")
        best = search(ranked_for(p1), p1).best
        self.assertEqual(best.frontend_label, best.frontend.scored.tech["name"])   # single web part: plain name
        p6 = prof("P6")
        best = search(ranked_for(p6), p6).best
        self.assertEqual(best.frontend.layer, "frontend_mobile")   # no web client: mobile in the primary slot
        self.assertTrue(best.frontend_label.endswith("(Android)"))


# ------------------------------------------------------------------ ordering, widening, infeasible
class OrderTest(unittest.TestCase):
    def test_total_order_tie_breaks(self):
        p = prof("P1")
        res = search(ranked_for(p), p)
        base = res.best
        a = replace(base, score=50.0, languages=("javascript",), cost_mid=10.0, ops_burden=2)
        self.assertLess(combine._order_key(replace(a, score=50.00001)), combine._order_key(replace(a, score=49.9)))
        self.assertEqual(combine._order_key(replace(a, score=50.00001))[0], combine._order_key(a)[0])  # 4 decimals
        fewer = replace(a, languages=("javascript",))
        more = replace(a, languages=("go", "javascript"))
        self.assertLess(combine._order_key(fewer), combine._order_key(more))
        cheap, dear = replace(a, cost_mid=5.0), replace(a, cost_mid=6.0)
        self.assertLess(combine._order_key(cheap), combine._order_key(dear))
        low_ops, high_ops = replace(a, ops_burden=1), replace(a, ops_burden=3)
        self.assertLess(combine._order_key(low_ops), combine._order_key(high_ops))
        other = res.runners_up[0]
        x = replace(a, cost_mid=5.0, ops_burden=1)
        y = replace(other, score=50.0, languages=("javascript",), cost_mid=5.0, ops_burden=1)
        first = min((x, y), key=combine._order_key)
        self.assertEqual(first.ids, min(x.ids, y.ids))

    def test_sort_is_a_total_order_independent_of_input_order(self):
        p = prof("P2")
        r = ranked_for(p)
        cache, passed = {}, []
        hosts = r["hosting"]
        fes = combine._client_options("frontend_web", r["frontend_web"][:3], p)
        for fe in fes:
            for be in r["backend"][:3]:
                for db in r["database"][:3]:
                    for h in hosts[:4]:
                        c, _ = combine._evaluate(fe, be, db, h, hosts, p, cache)
                        if c:
                            passed.append(c)
        # force ties on score so the later keys decide
        tied = [replace(c, score=round(c.score)) for c in passed]
        ref = [c.ids for c in combine._sort(tied, p)]
        rng = random.Random(7)
        for _ in range(3):
            shuffled = tied[:]
            rng.shuffle(shuffled)
            self.assertEqual([c.ids for c in combine._sort(shuffled, p)], ref)
        out = combine._sort(tied, p)
        keys = [combine._order_key(c) for c in out if c.cost_mid is not None]
        self.assertEqual(len(set(c.ids for c in out)), len(out))
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            self.assertLessEqual((-round(a.score, 4), len(a.languages)), (-round(b.score, 4), len(b.languages)))
        self.assertTrue(keys)

    def test_best_and_runners_ordered(self):
        p = prof("P3")
        res = search(ranked_for(p), p)
        allc = [res.best] + res.runners_up
        self.assertLessEqual(len(res.runners_up), T["runners_up"])
        for a, b in zip(allc, allc[1:]):
            self.assertLessEqual(combine._order_key(a), combine._order_key(b))
        self.assertEqual(len({c.ids for c in allc}), len(allc))


class WideningTest(unittest.TestCase):
    def test_widen_to_full_lists(self):
        p = prof("P1")
        failing = ["nestjs", "fastify", "django", "rails", "laravel", "spring_boot"]   # need a server
        ranked = {"frontend_web": [S("astro", 20)],
                  "backend": [S(b, 20 - i) for i, b in enumerate(failing)] + [S("none_backend", 1)],
                  "database": [S("none", 5)], "hosting": [S("github_pages", 5)]}
        res = search(ranked, p)
        self.assertTrue(res.widened)
        self.assertEqual(res.k, 7)
        self.assertEqual(res.best.backend.tech["id"], "none_backend")
        self.assertEqual(res.best.hosting.tech["id"], "github_pages")
        self.assertTrue(all(r.rule == "C1" for r in res.rejected_pairs))
        self.assertEqual(len(res.rejected_pairs), 6)
        # without the 7th candidate nothing passes -> infeasible, backend x hosting reported
        ranked["backend"] = ranked["backend"][:6]
        res = search(ranked, p)
        self.assertFalse(res.feasible)
        self.assertEqual(res.infeasible_pair, ("backend", "hosting"))
        self.assertIn("C1", res.infeasible_reason)

    def test_no_widening_when_top_k_passes(self):
        p = prof("P1")
        res = search(ranked_for(p), p)
        self.assertFalse(res.widened)
        self.assertEqual(res.k, 6)
        self.assertLessEqual(res.considered, 6 ** 4)


class InfeasibleTest(unittest.TestCase):
    def test_database_host_pair_reported(self):
        p = prof("P2")
        ranked = {"frontend_web": [S("nextjs")], "frontend_mobile": [S("react_native_expo")],
                  "backend": [S("nestjs")], "database": [S("postgres")], "hosting": [S("fly_io")]}
        res = search(ranked, p)
        self.assertIsNone(res.best)
        self.assertEqual(res.runners_up, [])
        self.assertEqual(res.infeasible_pair, ("database", "hosting"))
        self.assertIn("C3 database on host", res.infeasible_reason)
        self.assertEqual(res.rejected_pairs[0].a, "postgres")
        self.assertEqual(res.rejected_pairs[0].b, "fly_io")
        self.assertEqual(res.to_dict()["infeasible_pair"], ["database", "hosting"])

    def test_empty_layer(self):
        p = prof("P2")
        r = ranked_for(p)
        r["database"] = []
        res = search(r, p)
        self.assertEqual(res.infeasible_pair, ("database", "database"))
        r = ranked_for(p)
        r["frontend_mobile"] = []
        res = search(r, p)
        self.assertEqual(res.infeasible_pair, ("frontend_mobile", "frontend_mobile"))


class DeterminismTest(unittest.TestCase):
    def test_same_result_twice(self):
        for sid in ("P2", "P4"):
            p = prof(sid)
            a = json.dumps(search(ranked_for(p), p).to_dict(), sort_keys=True)
            b = json.dumps(search(ranked_for(p), p).to_dict(), sort_keys=True)
            self.assertEqual(a, b)


# ------------------------------------------------------------------ public scenarios
class PublicSmokeTest(unittest.TestCase):
    def test_public_scenarios(self):
        for sid in SIDS:
            with self.subTest(sid=sid):
                p = prof(sid)
                res = search(ranked_for(p), p)
                self.assertTrue(res.feasible, res.infeasible_reason)
                best = res.best
                self.assertTrue(best.database_offering.ok)
                helpers.assert_no_hard_violation(self, load(sid), output_stack(best))
                for c in res.runners_up:
                    helpers.assert_no_hard_violation(self, load(sid), output_stack(c))
                # the combo feeds cost.estimate and architecture.decide directly
                est = cost.estimate(p, best.stack())
                self.assertLessEqual(est.min, est.max)
                arch = architecture.decide(p, best.stack(), status="ok")
                self.assertTrue(arch.style)
                self.assertIsNotNone(best.cost_mid)
                # every required client platform is covered
                covered = set()
                for pt in best.parts:
                    covered.update(pt.platforms + pt.partner_platforms)
                self.assertTrue(set(p.clients) <= covered, (sid, p.clients, covered))
                if p.cloud_explicit and p.cloud:
                    self.assertEqual(best.database_offering.family, p.cloud)

    def test_hard_constraint_facts_on_public_picks(self):
        p1 = prof("P1")
        b = search(ranked_for(p1), p1).best
        self.assertEqual(b.backend.tech["id"], "none_backend")
        self.assertEqual(b.database.tech["id"], "none")
        for sid in ("P2", "P4", "P6"):            # india residency: database region in India
            p = prof(sid)
            b = search(ranked_for(p), p).best
            off = b.database_offering.offering
            self.assertIn(b.database_offering.region, off["regions"]["india"])
        p5 = prof("P5")
        b = search(ranked_for(p5), p5).best
        self.assertEqual(combine.offerings.provider_family(b.hosting.tech), "azure")


if __name__ == "__main__":
    unittest.main()

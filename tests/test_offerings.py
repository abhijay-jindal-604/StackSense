"""Managed-offering resolver (plan 3.10, 5.4 rules C3/C5/C7)."""
import copy
import json
import unittest
from pathlib import Path

from stacksense import filters, kb, offerings
from stacksense.offerings import NoOffering, Resolved, provider_family, resolve
from stacksense.profile import derive
from stacksense.validate import validate
from tests import helpers

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def prof(sid="P2", **paths):
    """Profile from a public scenario with dotted-path overrides (``a__b`` = ``a.b``)."""
    r = copy.deepcopy(load(sid))
    for path, value in paths.items():
        parts = path.split("__")
        node = r
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    v = validate(r)
    assert v.errors == [], v.errors
    return derive(v)


class ProviderFamilyTest(unittest.TestCase):
    def test_families(self):
        self.assertEqual(provider_family("aws_ecs_fargate"), "aws")
        self.assertEqual(provider_family("azure_app_service"), "azure")
        self.assertEqual(provider_family("google_cloud_run"), "gcp")
        self.assertEqual(provider_family("supabase_cloud"), "supabase")
        self.assertEqual(provider_family("cloudflare_workers_host"), "cloudflare")
        self.assertEqual(provider_family("cloudflare_workers_hono"), "cloudflare")
        self.assertEqual(provider_family("do_app_platform"), "digitalocean")
        self.assertEqual(provider_family("fly_io"), "fly")
        self.assertEqual(provider_family("onprem_compose"), "onprem")
        self.assertEqual(provider_family("postgres__aws"), None)   # ids of offerings are not records
        off = next(o for o in kb.OFFERINGS if o["id"] == "postgres__aws")
        self.assertEqual(provider_family(off), "aws")
        self.assertIsNone(provider_family(None))


class ResolveManagedTest(unittest.TestCase):
    def test_postgres_on_ecs_india_is_rds_mumbai(self):
        p = prof("P4")   # aws explicit, india, rbi + pci, 99.95
        r = resolve("postgres", "aws_ecs_fargate", p)
        self.assertIsInstance(r, Resolved)
        self.assertEqual(r.offering["id"], "postgres__aws")
        self.assertEqual(r.region, "ap-south-1")
        self.assertEqual(r.kind, "managed")
        self.assertTrue(r.same_provider)
        self.assertIn("Multi-AZ", r.display)          # availability 99.95 names the HA option
        self.assertIn("ap-south-1", r.display)
        self.assertTrue(r.choice("PostgreSQL").startswith("PostgreSQL (Amazon RDS for PostgreSQL 17"))
        self.assertTrue(any("data_residency=india" in x for x in r.reasons))
        self.assertIsNone(filters.check_offering(r.offering, p))

    def test_fly_managed_postgres_india_fails_c3(self):
        p = prof("P2")
        r = resolve("postgres", "fly_io", p)
        self.assertIsInstance(r, NoOffering)
        self.assertEqual(r.rule, "C3")
        self.assertIn("infrastructure.data_residency", r.fields)
        self.assertIn("India", r.reason)
        self.assertFalse(r.ok)
        self.assertEqual(r.to_dict()["rule"], "C3")

    def test_fly_without_residency_uses_fly_postgres(self):
        p = prof("P1")
        r = resolve("postgres", "fly_io", p)
        self.assertEqual(r.offering["id"], "postgres__fly")
        self.assertTrue(r.same_provider)

    def test_azure_sql_only_on_azure(self):
        p5 = prof("P5")
        r = resolve("sqlserver", "azure_app_service", p5)
        self.assertEqual(r.offering["id"], "sqlserver__azure")
        self.assertIn("centralindia", r.display)
        p1 = prof("P1")
        for host in ("vercel", "render", "cloudflare_pages", "do_app_platform"):
            res = resolve("sqlserver", host, p1)
            self.assertIsInstance(res, NoOffering, host)
            self.assertEqual(res.rule, "C3")
        res = resolve("sqlserver", "aws_ecs_fargate", p1)
        self.assertEqual(res.offering["id"], "sqlserver__aws")   # never the Azure product on AWS

    def test_proprietary_cloud_products_stay_on_their_cloud(self):
        p1 = prof("P1")
        self.assertEqual(resolve("dynamodb", "aws_lambda_host", p1).offering["id"], "dynamodb__aws")
        self.assertFalse(resolve("dynamodb", "vercel", p1).ok)
        self.assertFalse(resolve("dynamodb", "google_cloud_run", p1).ok)
        self.assertEqual(resolve("firestore", "firebase_app_hosting", p1).offering["id"], "firestore__gcp")
        self.assertFalse(resolve("firestore", "netlify", p1).ok)
        self.assertFalse(resolve("cosmosdb", "aws_ecs_fargate", p1).ok)

    def test_open_engine_from_independent_host_may_use_hyperscaler(self):
        p1 = prof("P1")
        r = resolve("mysql", "vercel", p1)
        self.assertTrue(r.ok)
        self.assertIn(r.family, ("aws", "azure", "gcp"))

    def test_hyperscaler_host_never_uses_another_hyperscaler(self):
        p1 = prof("P1")
        for host in ("aws_ecs_fargate", "azure_app_service", "google_cloud_run"):
            r = resolve("postgres", host, p1)
            self.assertTrue(r.ok)
            self.assertEqual(r.family, provider_family(host))

    def test_d1_only_with_workers(self):
        p1 = prof("P1")
        for host in ("cloudflare_workers_host", "cloudflare_pages"):
            self.assertEqual(resolve("cloudflare_d1", host, p1).offering["id"], "cloudflare_d1__cloudflare")
        for host in ("vercel", "aws_ecs_fargate", "fly_io"):
            r = resolve("cloudflare_d1", host, p1)
            self.assertIsInstance(r, NoOffering, host)
            self.assertEqual(r.rule, "C3")

    def test_explicit_cloud_restricts_offerings(self):
        p4 = prof("P4")   # cloud_preference aws
        r = resolve("postgres", "aws_lambda_host", p4)
        self.assertEqual(r.family, "aws")
        self.assertFalse(resolve("postgres", "supabase_cloud", p4, require_family="supabase").ok)


class PoolerTest(unittest.TestCase):
    def test_functions_hosts_need_a_pooler(self):
        p1 = prof("P1")
        for host in ("aws_lambda_host", "cloudflare_workers_host", "vercel"):
            r = resolve("postgres", host, p1, needs_pooler=True)
            self.assertTrue(r.ok, host)
            self.assertTrue(offerings.has_pooler(r.offering), (host, r.offering["id"]))
            self.assertTrue(any("pooler" in x for x in r.reasons))
        self.assertEqual(resolve("postgres", "aws_lambda_host", p1, needs_pooler=True).offering["id"],
                         "postgres__aws")      # RDS Proxy

    def test_offering_without_pooler_is_skipped(self):
        p1 = prof("P1")
        self.assertEqual(resolve("postgres", "fly_io", p1).offering["id"], "postgres__fly")
        r = resolve("postgres", "fly_io", p1, needs_pooler=True)
        self.assertNotEqual(r.offering["id"], "postgres__fly")

    def test_no_pooled_offering_is_c7(self):
        p1 = prof("P1")
        r = resolve("postgres", "fly_io", p1, needs_pooler=True, require_family="fly")
        self.assertIsInstance(r, NoOffering)
        self.assertEqual(r.rule, "C7")
        self.assertIn("postgres__fly", r.nearest)

    def test_auth_proxy_is_not_a_pooler(self):
        cloud_sql = next(o for o in kb.OFFERINGS if o["id"] == "postgres__gcp")
        self.assertFalse(offerings.has_pooler(cloud_sql))
        rds = next(o for o in kb.OFFERINGS if o["id"] == "postgres__aws")
        self.assertTrue(offerings.has_pooler(rds))

    def test_d1_and_documents_need_no_pooler(self):
        p1 = prof("P1")
        self.assertTrue(resolve("cloudflare_d1", "cloudflare_workers_host", p1, needs_pooler=True).ok)
        self.assertTrue(resolve("dynamodb", "aws_lambda_host", p1, needs_pooler=True).ok)


class BaaSCouplingTest(unittest.TestCase):
    def test_supabase_family(self):
        p2 = prof("P2")
        r = resolve("postgres", "supabase_cloud", p2, require_family="supabase")
        self.assertEqual(r.offering["id"], "postgres__supabase")
        self.assertEqual(r.region, "ap-south-1")
        self.assertEqual(r.display, "Supabase Postgres 17 (Supabase Cloud, ap-south-1)")   # no "(...) (...)"

    def test_wrong_family_is_c5(self):
        p2 = prof("P2")
        r = resolve("mysql", "supabase_cloud", p2, require_family="supabase")
        self.assertIsInstance(r, NoOffering)
        self.assertEqual(r.rule, "C5")


class SelfHostedTest(unittest.TestCase):
    def test_self_hosted_cloud_vm_resolves_self_managed(self):
        p = prof("P2", infrastructure__deployment_model="self_hosted_cloud_vm")
        r = resolve("postgres", "do_droplets_compose", p)
        self.assertEqual(r.kind, "self_managed")
        self.assertEqual(r.offering["id"], "postgres__self_hosted")
        # review finding 2: the display names the engine and where it runs
        self.assertEqual(r.display, "Self-managed PostgreSQL 17 (on DigitalOcean Droplets + Docker Compose, BLR1)")
        r2 = resolve("postgres", "supabase_cloud", p, require_family="supabase")
        self.assertIsInstance(r2, NoOffering)    # supabase_cloud is not a VM/container host

    def test_on_premise_and_static_host(self):
        p = prof("P5", infrastructure__deployment_model="on_premise", infrastructure__cloud_preference="none")
        r = resolve("postgres", "onprem_compose", p)
        self.assertEqual(r.kind, "self_managed")
        self.assertEqual(r.display, "Self-managed PostgreSQL 17 (on premises)")
        self.assertEqual(r.region, "on premises")
        bad = resolve("postgres", "vercel", p)
        self.assertIsInstance(bad, NoOffering)
        self.assertIn("infrastructure.deployment_model", bad.fields)

    def test_saas_only_engine_fails_closed_self_hosted(self):
        p = prof("P2", infrastructure__deployment_model="self_hosted_cloud_vm")
        r = resolve("dynamodb", "do_droplets_compose", p)
        self.assertIsInstance(r, NoOffering)
        self.assertEqual(r.rule, "C3")


class InHostAndNoneTest(unittest.TestCase):
    def test_sqlite_needs_persistent_disk(self):
        p1 = prof("P1")
        r = resolve("sqlite", "hetzner_compose", p1)
        self.assertEqual(r.kind, "in_host")
        self.assertTrue(r.display.startswith("Self-managed SQLite (on Hetzner"), r.display)
        self.assertFalse(resolve("sqlite", "aws_ecs_fargate", p1).ok)
        self.assertFalse(resolve("sqlite", "vercel", p1).ok)
        self.assertFalse(resolve("sqlite", "hetzner_compose", p1, require_family="supabase").ok)

    def test_none_engine(self):
        r = resolve("none", "netlify", prof("P1"))
        self.assertEqual(r.kind, "none")
        self.assertEqual(r.choice("None"), "None")

    def test_unknown_engine_raises(self):
        with self.assertRaises(ValueError):
            resolve("no_such_engine", "vercel", prof("P1"))


class InvariantTest(unittest.TestCase):
    def test_resolved_offerings_pass_the_hard_filters(self):
        """Every managed resolution passes filters.check_offering and the independent re-check."""
        for sid in SIDS:
            p = prof(sid)
            hosts, _ = filters.filter_layer("hosting", p)
            dbs, _ = filters.filter_layer("database", p)
            for db in dbs:
                for h in hosts:
                    for pool in (False, True):
                        r = resolve(db, h, p, needs_pooler=pool)
                        if not r.ok or r.kind != "managed":
                            continue
                        self.assertIsNone(filters.check_offering(r.offering, p), (sid, db["id"], h["id"]))
                        self.assertEqual(helpers._offering_violations(r.offering, db, p), [],
                                         (sid, db["id"], h["id"]))
                        if p.cloud_explicit and p.cloud:
                            self.assertEqual(r.family, p.cloud)

    def test_deterministic(self):
        p = prof("P2")
        hosts, _ = filters.filter_layer("hosting", p)
        a = [resolve("postgres", h, p).to_dict() for h in hosts]
        b = [resolve("postgres", h, p).to_dict() for h in reversed(hosts)][::-1]
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(
            [resolve("postgres", h["id"], p).to_dict() for h in hosts], sort_keys=True))


if __name__ == "__main__":
    unittest.main()


class SelfManagedNameTests(unittest.TestCase):
    def test_no_duplicated_or_misleading_version_token(self):
        names = {o["id"]: o["name"] for o in kb.OFFERINGS if o["host"] == "self_hosted"}
        self.assertEqual(names["influxdb3__self_hosted"], "Self-managed InfluxDB 3")
        self.assertEqual(names["sqlserver__self_hosted"], "Self-managed Microsoft SQL Server 2022")
        self.assertEqual(names["timescaledb__self_hosted"], "Self-managed TimescaleDB 2 (PostgreSQL extension)")
        for n in names.values():
            toks = n.split()
            self.assertTrue(all(a != b for a, b in zip(toks, toks[1:])), n)
            self.assertNotIn("Azure", n)

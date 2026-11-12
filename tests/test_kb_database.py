import unittest

from stacksense import kb
from stacksense.kb import database, model, offerings
from stacksense.kb.sources import SOURCES

DB = [r for r in kb.RECORDS if r["layer"] == "database"]
DB_IDS = {r["id"] for r in DB}
MAINT = [r for r in DB if r["status"] == "maintained"]
REQUIRED_ENGINES = {"postgres", "mysql", "mariadb", "sqlserver", "sqlite", "cloudflare_d1", "cockroachdb", "yugabytedb",
                    "mongodb", "dynamodb", "firestore", "cosmosdb", "cassandra_scylla", "timescaledb", "influxdb3",
                    "clickhouse", "bigquery", "snowflake", "neo4j", "tigerbeetle"}


def _has(rec, prefix):
    return any(f["text"].startswith(prefix) and f["source_key"] in SOURCES for f in rec["facts"])


class DatabaseCounts(unittest.TestCase):
    def test_twenty_engines_plus_none(self):
        engines = {r["id"] for r in MAINT} - {"none"}
        self.assertEqual(engines, REQUIRED_ENGINES)
        self.assertIn("none", {r["id"] for r in MAINT})
        self.assertGreaterEqual(kb.counts()["database"], kb.MIN_COUNTS["database"])

    def test_non_maintained_records_explain_rejections(self):
        nm = {r["id"]: r for r in DB if r["status"] != "maintained"}
        for rid in ("amazon_qldb", "fauna", "mysql_80", "mongodb_60", "postgres_14"):
            self.assertIn(rid, nm)
            self.assertIn(nm[rid]["replaced_by"], DB_IDS)
        self.assertTrue(all(r["status"] != "maintained" for r in nm.values()))

    def test_versions(self):
        by = {r["id"]: r for r in DB}
        self.assertEqual(by["postgres"]["current_major"], "17")
        self.assertEqual(by["mysql"]["current_major"], "8.4")
        self.assertEqual(by["mongodb"]["current_major"], "8.0")


class DatabaseModel(unittest.TestCase):
    def test_integrity(self):
        self.assertEqual(kb.integrity_problems(), [])
        for r in DB:
            self.assertEqual(model.record_problems(r), [], r["id"])

    def test_own_sources_unique_and_resolve(self):
        from stacksense.kb import sources_database
        for k in sources_database.SOURCES:
            self.assertIn(k, SOURCES)
            self.assertEqual(SOURCES[k], sources_database.SOURCES[k])
            title, url, date = SOURCES[k]
            self.assertTrue(url.startswith("https://"))
            self.assertEqual(date, "2026-11-13")

    def test_scoring_inputs_present(self):
        for r in MAINT:
            self.assertTrue(set(model.ATTR_KEYS) <= set(r["attrs"]), r["id"])
            self.assertTrue(r["strengths"] or r["id"] == "none" or r["tradeoffs"], r["id"])

    def test_data_at_rest_records_have_region_and_attestation_facts(self):
        for r in DB:
            if not r["data_at_rest"]:
                continue
            with self.subTest(r["id"]):
                self.assertTrue(_has(r, "Region"), "region fact")
                self.assertTrue(_has(r, "Attestation"), "attestation fact")

    def test_fail_closed_when_region_unverified(self):
        by = {r["id"]: r for r in DB}
        for rid in ("cosmosdb", "snowflake"):
            self.assertEqual(by[rid]["regions"], {"india": [], "eu": [], "us": []})
        self.assertEqual(by["cloudflare_d1"]["regions"]["india"], [])
        for k in by["snowflake"]["attest"]:
            self.assertEqual(by["snowflake"]["attest"][k], "no")

    def test_deterministic_sorted_lists(self):
        for r in DB:
            self.assertEqual(r["caps"], sorted(r["caps"]))
            self.assertEqual(r["sources"], sorted(r["sources"]))


class OfferingsT(unittest.TestCase):
    def test_every_engine_is_a_database_record(self):
        for o in kb.OFFERINGS:
            self.assertIn(o["engine"], DB_IDS, o["id"])
        self.assertEqual(len({o["id"] for o in kb.OFFERINGS}), len(kb.OFFERINGS))

    def test_offering_facts_and_sources(self):
        for o in kb.OFFERINGS:
            with self.subTest(o["id"]):
                self.assertTrue(_has(o, "Region"))
                self.assertTrue(_has(o, "Attestation"))
                self.assertTrue(o["sources"])
                self.assertTrue(all(s in SOURCES for s in o["sources"]))
                self.assertEqual(o["id"], f"{o['engine']}__{o['host']}")

    def test_no_eol_versions_in_maintained(self):
        import re
        for rec in list(MAINT) + [o for o in kb.OFFERINGS if o["status"] == "maintained"]:
            name = rec["name"]
            for m in re.finditer(r"PostgreSQL\s+(\d+)", name):
                self.assertGreaterEqual(int(m.group(1)), 15, name)
            self.assertNotIn("MySQL 8.0", name)
            major = rec.get("current_major")
            if major and "postgres" in (rec.get("engine") or rec["id"]):
                self.assertGreaterEqual(int(major), 15, rec["id"])
            if major and (rec.get("engine") or rec["id"]) == "mysql":
                self.assertNotEqual(major, "8.0")

    def test_coverage(self):
        have = {(o["engine"], o["host"]) for o in kb.OFFERINGS}
        for pair in [("postgres", "aws"), ("postgres", "azure"), ("postgres", "gcp"), ("postgres", "digitalocean"),
                     ("postgres", "supabase"), ("postgres", "neon"), ("postgres", "fly"), ("postgres", "self_hosted"),
                     ("mysql", "aws"), ("sqlserver", "aws"), ("sqlserver", "azure"), ("mongodb", "atlas"),
                     ("dynamodb", "aws"), ("firestore", "gcp"), ("cosmosdb", "azure"), ("cloudflare_d1", "cloudflare"),
                     ("clickhouse", "self_hosted"), ("timescaledb", "self_hosted")]:
            self.assertIn(pair, have)
        for r in MAINT:
            if r["self_hostable"] and r["id"] != "none":
                self.assertIn((r["id"], "self_hosted"), have, r["id"])

    def test_known_gaps_fail_closed(self):
        by = {o["id"]: o for o in kb.OFFERINGS}
        self.assertEqual(by["postgres__fly"]["regions"]["india"], [])      # no MPG in bom
        self.assertEqual(by["postgres__neon"]["regions"]["india"], [])     # no Neon India region
        self.assertEqual(by["sqlserver__azure"]["regions"]["india"], [])   # unverified
        self.assertIn("BLR1", by["postgres__digitalocean"]["regions"]["india"])
        self.assertIn("ap-south-1", by["postgres__aws"]["regions"]["india"])
        self.assertIn("centralindia", by["postgres__azure"]["regions"]["india"])
        self.assertEqual(by["postgres__fly"]["attest"]["hipaa_baa"], "no")

    def test_cost_monotone(self):
        for o in kb.OFFERINGS:
            self.assertEqual(model.cost_problems(o["cost"]), [], o["id"])


if __name__ == "__main__":
    unittest.main()

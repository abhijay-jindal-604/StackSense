import re
import unittest

from stacksense import kb
from stacksense.kb import backend, model
from stacksense.kb.sources import SOURCES
from stacksense.kb import sources_backend

BAAS = [r for r in backend.RECORDS if r["kind"] == "baas"]
OLD_VERSION = re.compile(r"\.NET (8|9)\b|Node\.js 20\b", re.I)


class BackendKbTests(unittest.TestCase):
    def test_count(self):
        maintained = [r for r in backend.RECORDS if r["status"] == "maintained"]
        self.assertGreaterEqual(len(maintained), 26)  # 25 candidates plus None
        self.assertEqual(kb.counts()["backend"], len(maintained))
        self.assertGreaterEqual(kb.counts()["backend"], kb.MIN_COUNTS["backend"])

    def test_has_none_option(self):
        none = [r for r in backend.RECORDS if r["name"] == "None"]
        self.assertEqual(len(none), 1)

    def test_models_valid_and_layer(self):
        for r in backend.RECORDS:
            with self.subTest(id=r["id"]):
                self.assertEqual(model.record_problems(r), [])
                self.assertEqual(r["layer"], "backend")

    def test_ids_unique(self):
        ids = [r["id"] for r in backend.RECORDS]
        self.assertEqual(len(ids), len(set(ids)))
        names = [r["name"] for r in backend.RECORDS]
        self.assertEqual(len(names), len(set(names)))

    def test_baas_region_facts(self):
        self.assertGreaterEqual(len(BAAS), 4)
        for r in BAAS:
            with self.subTest(id=r["id"]):
                self.assertTrue(r["data_at_rest"])
                self.assertTrue(any(r["regions"][g] for g in ("india", "eu", "us")), "no region data")
                texts = " ".join(f["text"].lower() for f in r["facts"])
                self.assertTrue("region" in texts or "self-hosted" in texts or "location" in texts)

    def test_supabase_matches_regions_module(self):
        from stacksense.kb import regions
        res = regions.ENTRIES["supabase"]["residency"]
        sup = kb.get("supabase")
        for g in ("india", "eu", "us"):
            self.assertEqual(sup["regions"][g], res[g])

    def test_firebase_auth_fails_closed_for_india_and_eu(self):
        fb = kb.get("firebase")
        self.assertEqual(fb["regions"]["india"], [])
        self.assertEqual(fb["regions"]["eu"], [])

    def test_no_stale_versions(self):
        for r in backend.RECORDS:
            with self.subTest(id=r["id"]):
                blob = " ".join([r["name"], str(r["current_major"])])
                self.assertIsNone(OLD_VERSION.search(blob))
        self.assertIn(".NET 10", kb.get("aspnet_core")["name"])

    def test_sources_resolve_and_no_collisions(self):
        for r in backend.RECORDS:
            for k in r["sources"] + [f["source_key"] for f in r["facts"]]:
                with self.subTest(id=r["id"], key=k):
                    self.assertIn(k, SOURCES)
        for k, v in sources_backend.SOURCES.items():
            self.assertEqual(SOURCES[k], tuple(v))
            self.assertTrue(v[1].startswith("https://"))

    def test_runtime_values(self):
        allowed = {"node", "python", "jvm", "dotnet", "go", "ruby", "php", "beam", "edge_js", "baas", "saas", None}
        for r in backend.RECORDS:
            self.assertIn(r["runtime"], allowed, r["id"])

    def test_rationale_facts_present(self):
        for r in backend.RECORDS:
            with self.subTest(id=r["id"]):
                self.assertGreaterEqual(len(r["facts"]), 1)
                self.assertGreaterEqual(len(r["strengths"]), 1)


if __name__ == "__main__":
    unittest.main()

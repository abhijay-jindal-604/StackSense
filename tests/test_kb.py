import re
import unittest

from stacksense import kb, schema
from stacksense.kb import costs, languages, model
from stacksense.kb.sources import SOURCES

ATTRS = {k: 3 for k in model.ATTR_KEYS}


def _tech(**kw):
    base = dict(id="x_one", name="X One", layer="backend", kind="framework", sources=["django_docs"])
    base.update(kw)
    return model.tech(**base)


class KbCountsT01(unittest.TestCase):
    def test_minimum_counts(self):
        counts = kb.counts()
        for layer, minimum in kb.MIN_COUNTS.items():
            with self.subTest(layer=layer):
                if not any(r["layer"] == layer for r in kb.RECORDS):
                    self.skipTest(f"layer {layer} has no records yet (minimum {minimum})")
                self.assertGreaterEqual(counts[layer], minimum, f"layer {layer}")


class KbIntegrityT02(unittest.TestCase):
    def test_registry_integrity(self):
        self.assertEqual(kb.integrity_problems(), [])

    def test_unique_ids(self):
        ids = [r["id"] for r in kb.RECORDS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_version_stable(self):
        self.assertEqual(kb.kb_version(), kb.kb_version())
        self.assertRegex(kb.kb_version(), r"^[0-9a-f]{12}$")
        self.assertEqual(kb.export()["kb_version"], kb.kb_version())

    def test_by_layer_sorted(self):
        for layer in model.LAYERS:
            ids = [r["id"] for r in kb.by_layer(layer)]
            self.assertEqual(ids, sorted(ids))

    def test_synthetic_problems_detected(self):
        bad = _tech()
        bad["attrs"]["security"] = 9
        self.assertTrue(model.record_problems(bad))
        bad = _tech()
        bad["cost"] = {"s": [10, 20], "m": [5, 30]}
        self.assertTrue(model.cost_problems(bad["cost"]))


class KbSourcesT03(unittest.TestCase):
    def test_schema_sources_resolve(self):
        for name, spec in schema.FIELDS.items():
            for k in spec.get("sources", []):
                self.assertIn(k, SOURCES, f"{name}: {k}")

    def test_urls_https_unique_and_dated(self):
        urls = [v[1] for v in SOURCES.values()]
        self.assertTrue(all(u.startswith("https://") for u in urls))
        self.assertEqual(len(urls), len(set(urls)))
        for k, v in SOURCES.items():
            self.assertEqual(len(v), 3, k)
            self.assertTrue(v[0], k)
            self.assertRegex(v[2], r"^\d{4}-\d{2}-\d{2}$", k)

    def test_plan_keys_present(self):
        for k in ("supabase_hipaa_projects", "vercel_bom1_pricing", "do_spaces_blr", "firebase_privacy",
                  "bedrock_india_cris", "cf_regional_services_apac", "r2_data_location",
                  "azure_managed_redis", "azure_cdn_classic_retirement", "azure_cdn_comparison",
                  "afd_tier_migration", "ms_sql2019_lifecycle", "eol_nodejs", "eol_mysql", "pg_versioning",
                  "dotnet_8_9_eos", "fly_mpg", "endoflife_api", "python_markdown", "playwright",
                  "archivo_font", "claude_api_messages"):
            self.assertIn(k, SOURCES)
        self.assertNotEqual(SOURCES["rbi_digital_lending"][1], "https://www.rbi.org.in/")
        self.assertNotEqual(SOURCES["trai_dlt"][1], "https://www.trai.gov.in/")

    def test_record_sources_resolve(self):
        for r in list(kb.RECORDS) + list(kb.OFFERINGS):
            for k in r["sources"] + [f["source_key"] for f in r["facts"]]:
                self.assertIn(k, SOURCES, r["id"])


class ConstructorTests(unittest.TestCase):
    def test_tech_defaults_and_shape(self):
        r = _tech(languages=["python", "go"], caps=["b", "a"])
        self.assertEqual(r["languages"], ["go", "python"])
        self.assertEqual(r["caps"], ["a", "b"])
        self.assertEqual(r["attrs"], ATTRS)
        self.assertEqual(r["attest"]["hipaa_baa"], "no")
        self.assertEqual(r["regions"], {"india": [], "eu": [], "us": []})
        self.assertEqual(r["status"], "maintained")
        self.assertEqual(set(r), set(_tech()))

    def test_rejects_bad_values(self):
        for kw in (dict(layer="nope"), dict(layer="auth"), dict(status="old"), dict(scale_floor="l", scale_ceiling="s"),
                   dict(attrs={"security": 6}), dict(attrs={"bogus": 1}), dict(cost={"s": (5, 1)}),
                   dict(cost={"s": (1, 5), "m": (0, 9)}), dict(status="deprecated"), dict(ops_burden=7),
                   dict(attest={"soc2": "maybe"}), dict(id="Bad Id"), dict(lock_in=4)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                _tech(**kw)

    def test_deprecated_with_replacement(self):
        r = _tech(status="deprecated", replaced_by="y_two")
        self.assertEqual(r["replaced_by"], "y_two")

    def test_service_and_offering_and_fact(self):
        s = model.service(id="s_one", name="S One", layer="cache", kind="kv", triggers=["b", "a"])
        self.assertEqual(s["triggers"], ["a", "b"])
        with self.assertRaises(ValueError):
            model.service(id="s_two", name="S", layer="backend", kind="kv")
        o = model.offering("o_one", "x_one", "aws", "X on AWS", regions={"india": ["ap-south-1"]},
                           cost={"s": (1, 2), "m": (2, 3)}, ha_options=["Multi-AZ"])
        self.assertEqual(o["regions"]["india"], ["ap-south-1"])
        f = model.fact("text", "django_docs", "V")
        self.assertEqual(f["confidence"], "V")
        with self.assertRaises(ValueError):
            model.fact("text", "django_docs", "Z")

    def test_size_helpers(self):
        self.assertEqual(model.SIZE_CLASSES, ("xs", "s", "m", "l", "xl"))
        self.assertTrue(model.size_le("s", "m"))
        self.assertFalse(model.size_le("l", "m"))
        self.assertEqual(model.size_max("s", "l", "m"), "l")
        with self.assertRaises(ValueError):
            model.size_index("xxl")


class CostConstantsTests(unittest.TestCase):
    def test_size_class(self):
        self.assertEqual(costs.size_class(5000, 100, 5), "xs")
        self.assertEqual(costs.size_class(1000, 100, 50), "s")
        self.assertEqual(costs.size_class(1000, 5000, 5), "m")
        self.assertEqual(costs.size_class(10, 1, 20000), "xl")
        self.assertEqual(costs.size_class(5_000_001, 1, 1), "xl")

    def test_band_for(self):
        c = {"s": [1, 2], "l": [10, 20]}
        self.assertEqual(costs.band_for(c, "s"), (1, 2, False))
        self.assertIsNone(costs.band_for(c, "m"))
        self.assertEqual(costs.band_for(c, "xl"), (30, 60, True))

    def test_round_sig(self):
        self.assertEqual(costs.round_sig(1234), 1200)
        self.assertEqual(costs.round_sig(95), 95)
        self.assertEqual(costs.round_sig(0), 0)
        self.assertEqual(costs.round_sig(2550), 2600)


class LanguageTests(unittest.TestCase):
    def test_aliases(self):
        langs, notes = languages.normalize(["JS", "C#", "golang", "React", "cobol", "Postgres"])
        self.assertEqual(langs, ["cobol", "csharp", "go", "javascript", "sql", "typescript"])
        self.assertEqual(len(notes), 1)

    def test_affinity(self):
        self.assertEqual(languages.affinity("python", "python"), 1.0)
        self.assertEqual(languages.affinity("typescript", "javascript"), 0.9)
        self.assertEqual(languages.affinity("javascript", "typescript"), 0.9)
        self.assertEqual(languages.affinity("python", "java"), 0.0)
        self.assertTrue(languages.is_known(["kotlin"], ["java"]))
        self.assertFalse(languages.is_known(["csharp"], ["typescript"]))
        self.assertEqual(languages.best_affinity(["go"], []), 1.0)


if __name__ == "__main__":
    unittest.main()

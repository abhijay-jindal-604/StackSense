import unittest

from stacksense import schema
from stacksense.kb import compliance, regions
from stacksense.kb.regions import UNKNOWN, regions_for
from stacksense.kb.compliance import attestation, attestation_in_region
from stacksense.kb.sources_facts import SOURCES as FACT_SOURCES

try:
    from stacksense.kb.sources import SOURCES as MERGED
except Exception:  # pragma: no cover
    MERGED = None


class TestShape(unittest.TestCase):
    def test_every_entry_is_list_or_unknown(self):
        for key, e in regions.ENTRIES.items():
            self.assertEqual(sorted(e["residency"]), sorted(schema.RESIDENCY), key)
            for res, val in e["residency"].items():
                self.assertTrue(val == UNKNOWN or isinstance(val, list), (key, res))
                if isinstance(val, list):
                    self.assertTrue(all(isinstance(x, str) for x in val), (key, res))

    def test_none_is_unconstrained_and_other_unverifiable(self):
        for key, e in regions.ENTRIES.items():
            self.assertEqual(e["residency"]["none"], ["*"], key)
            if key != "self_hosted":
                self.assertEqual(e["residency"]["other"], UNKNOWN, key)

    def test_unknown_inputs_fail_closed(self):
        self.assertEqual(regions_for("nonexistent", "india"), UNKNOWN)
        self.assertEqual(regions_for("aws", "mars"), UNKNOWN)
        self.assertEqual(attestation("nonexistent", "hipaa"), "unknown")
        self.assertEqual(attestation("aws", "bogus"), "unknown")

    def test_regimes_match_schema_enum(self):
        self.assertEqual(sorted(compliance.REGIMES), sorted(schema.COMPLIANCE))
        for row in compliance.ATTEST.values():
            for r in schema.COMPLIANCE:
                v = row[r]
                self.assertTrue(v in compliance.ATTEST_VALUES_FIXED or v.startswith("plan:"), v)


class TestSources(unittest.TestCase):
    def _all_keys(self):
        for k, e in regions.ENTRIES.items():
            for s in e["sources"]:
                yield "regions:" + k, s
        for k, e in compliance.ATTEST.items():
            for s in e["sources"]:
                yield "compliance:" + k, s
        for (v, r), ss in compliance.FACT_SOURCES.items():
            for s in ss:
                yield "cell:%s/%s" % (v, r), s

    def test_keys_resolve_in_fact_registry(self):
        for where, s in self._all_keys():
            self.assertIn(s, FACT_SOURCES, where)
        for k, (title, url, accessed) in FACT_SOURCES.items():
            self.assertTrue(url.startswith("https://"), k)
            self.assertEqual(accessed, "2026-11-13")

    def test_keys_resolve_in_merged_registry(self):
        if MERGED is None or not all(k in MERGED for k in FACT_SOURCES):
            self.skipTest("merged kb.sources registry not ready yet")
        for where, s in self._all_keys():
            self.assertIn(s, MERGED, where)

    def test_every_non_unknown_fact_has_a_source(self):
        for k, row in compliance.ATTEST.items():
            if k == "self_hosted":
                continue
            if any(row[r] not in ("unknown", "na") for r in schema.COMPLIANCE):
                self.assertTrue(row["sources"], k)
        for k, e in regions.ENTRIES.items():
            if k not in ("self_hosted", "github_actions", "msg91", "entra_id"):
                self.assertTrue(e["sources"], k)


class TestKeyFacts(unittest.TestCase):
    def test_no_india_region(self):
        for p in ("render", "railway", "neon", "clerk", "auth0", "sentry", "firebase_auth", "cloudflare_r2", "cloudflare_d1"):
            self.assertEqual(regions_for(p, "india"), [], p)
        self.assertFalse(regions.region_ok("neon", "india"))

    def test_india_regions(self):
        self.assertEqual(regions_for("supabase", "india"), ["ap-south-1"])
        self.assertIn("bom1", regions_for("vercel", "india"))
        self.assertIn("BLR1", regions_for("digitalocean", "india"))
        self.assertIn("ap-south-1", regions_for("aws", "india"))
        self.assertIn("asia-south1", regions_for("gcp", "india"))
        self.assertIn("centralindia", regions_for("azure", "india"))

    def test_product_level_exceptions(self):
        self.assertEqual(regions_for("fly", "india"), ["bom"])
        self.assertEqual(regions_for("fly_managed_postgres", "india"), [])
        self.assertEqual(regions_for("bedrock", "india"), ["in.*"])
        self.assertNotIn("global.*", sum((v for v in regions.ENTRIES["bedrock"]["residency"].values() if isinstance(v, list)), []))
        self.assertIn("jurisdiction:eu", regions_for("cloudflare_r2", "eu"))
        self.assertEqual(regions_for("cloudflare", "india"), UNKNOWN)
        self.assertEqual(regions_for("azure_managed_redis", "india"), UNKNOWN)

    def test_eu_excludes_non_eu_regions(self):
        self.assertNotIn("eu-west-2", regions_for("aws", "eu"))
        self.assertNotIn("eu-central-2", regions_for("aws", "eu"))
        self.assertNotIn("eu-west-2", regions_for("supabase", "eu"))
        self.assertNotIn("LON1", regions_for("digitalocean", "eu"))
        self.assertNotIn("lhr", regions_for("fly", "eu"))

    def test_stripe_excluded_for_india(self):
        self.assertEqual(regions_for("stripe", "india"), [])
        self.assertEqual(attestation("razorpay", "rbi_localisation"), "yes")

    def test_supabase_hipaa_india_unknown(self):
        self.assertEqual(attestation("supabase", "hipaa"), "plan:hipaa_addon")
        self.assertEqual(attestation_in_region("supabase", "hipaa", "india"), "unknown")
        self.assertEqual(attestation_in_region("supabase", "hipaa", "us"), "plan:hipaa_addon")

    def test_attestations(self):
        self.assertEqual(attestation("aws", "hipaa"), "yes")
        self.assertEqual(attestation("vercel", "hipaa"), "plan:pro_addon")
        self.assertEqual(attestation("neon", "hipaa"), "plan:scale")
        self.assertEqual(attestation("self_hosted", "pci_dss"), "self")
        self.assertEqual(attestation("fly", "hipaa"), "unknown")
        self.assertEqual(attestation("digitalocean", "iso27001"), "unknown")
        self.assertEqual(attestation("upstash", "pci_dss"), "no")
        self.assertEqual(attestation("aws", "dpdp"), "na")
        self.assertFalse(compliance.passes("fly", "hipaa"))
        self.assertTrue(compliance.passes("render", "hipaa"))


if __name__ == "__main__":
    unittest.main()

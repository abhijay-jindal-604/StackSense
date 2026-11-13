"""Region and attestation facts have one source of truth (kb.regions / kb.compliance, applied by kb.bindings)."""
import re
import unittest

from stacksense import kb
from stacksense.kb import bindings, compliance, regions
from stacksense.kb.sources import SOURCES

ALL = list(kb.RECORDS) + list(kb.OFFERINGS)
BY_ID = {r["id"]: r for r in ALL}
_ATTEST_TEXT = re.compile(r"\b(HIPAA|BAA|SOC ?2|ISO ?27001|PCI|GDPR|DPA|attestations?|Attestation)\b")


def _claims(rec):
    return sorted(k for k, v in rec["attest"].items() if v == "yes" or v.startswith("plan:"))


class BindingsAgree(unittest.TestCase):
    def test_binding_keys_exist(self):
        for rid, (rk, ak) in bindings.BINDINGS.items():
            self.assertIn(rid, BY_ID, rid)
            if rk is not None:
                self.assertIn(regions.ALIASES.get(rk, rk), regions.ENTRIES, (rid, rk))
            if ak is not None:
                self.assertIn(compliance.ALIASES.get(ak, ak), compliance.ATTEST, (rid, ak))

    def test_bound_cells_equal_regions_and_compliance(self):
        for rid, (rk, ak) in bindings.BINDINGS.items():
            rec = BY_ID[rid]
            if rk is not None:
                self.assertEqual(rec["regions"], bindings.regions_dict(rk), rid)
            if ak is not None:
                self.assertEqual(rec["attest"], bindings.attest_dict(ak), rid)

    def test_every_vendor_claim_is_bound(self):
        """A record/offering that claims an attestation or a concrete region list must take it from the
        fact modules; only self-hosted ("*" / self) and claim-free records may stay unbound."""
        for rec in ALL:
            if rec["id"] in bindings.BINDINGS:
                continue
            self.assertEqual(_claims(rec), [], rec["id"])
            for g, v in rec["regions"].items():
                self.assertIn(v, ([], ["*"]), (rec["id"], g))

    def test_kb_consistency_problems_empty(self):
        self.assertEqual(kb.consistency_problems(), [])

    def test_unknown_fails_closed_in_records(self):
        for rid, (rk, ak) in bindings.BINDINGS.items():
            if ak is None:
                continue
            for mk, regime in bindings.ATTEST_MAP.items():
                if compliance.attestation(ak, regime) in ("unknown", "na"):
                    self.assertEqual(BY_ID[rid]["attest"][mk], "no", (rid, mk))
            if rk is None:
                continue
            for g in ("india", "eu", "us"):
                if regions.regions_for(rk, g) == regions.UNKNOWN:
                    self.assertEqual(BY_ID[rid]["regions"][g], [], (rid, g))


class FactSources(unittest.TestCase):
    def test_every_v_fact_has_a_resolving_source(self):
        for rec in ALL:
            for f in rec["facts"]:
                if f["confidence"] == "V":
                    self.assertTrue(f["source_key"], rec["id"])
                    self.assertIn(f["source_key"], SOURCES, (rec["id"], f["text"][:60]))

    def test_no_attestation_yes_rests_on_a_k_fact(self):
        for rec in ALL:
            if rec["status"] != "maintained" or not _claims(rec):
                continue
            self.assertIn(rec["id"], bindings.BINDINGS, rec["id"])
            for f in rec["facts"]:
                if _ATTEST_TEXT.search(f["text"]):
                    self.assertNotEqual(f["confidence"], "K", (rec["id"], f["text"][:80]))

    def test_fact_module_sources_read_this_pass(self):
        for key, e in list(regions.ENTRIES.items()) + list(compliance.ATTEST.items()):
            for s in e["sources"]:
                self.assertIn(s, SOURCES, (key, s))
                self.assertEqual(SOURCES[s][2], "2026-11-13", (key, s))


class ReconciledFacts(unittest.TestCase):
    """The conflicts found when the five KB tasks were merged, pinned to their verified answers."""

    def test_vercel_hipaa_is_pro_addon(self):
        self.assertEqual(compliance.attestation("vercel", "hipaa"), "plan:pro_addon")
        self.assertEqual(BY_ID["vercel"]["attest"]["hipaa_baa"], "plan:pro_addon")

    def test_supabase_gdpr_dpa(self):
        self.assertEqual(compliance.attestation("supabase", "gdpr"), "yes")
        self.assertEqual(BY_ID["supabase"]["attest"]["gdpr_dpa"], "yes")
        self.assertEqual(BY_ID["postgres__supabase"]["attest"]["gdpr_dpa"], "yes")

    def test_hyperscaler_attestations_are_per_service(self):
        self.assertEqual(BY_ID["amazon_ec2_lightsail"]["attest"]["hipaa_baa"], "no")
        self.assertEqual(BY_ID["aws_app_runner"]["attest"]["hipaa_baa"], "no")
        self.assertEqual(BY_ID["aws_ecs_fargate"]["attest"]["hipaa_baa"], "yes")
        self.assertEqual(BY_ID["firebase_app_hosting"]["attest"]["soc2"], "no")
        self.assertEqual(BY_ID["google_cloud_run"]["attest"]["pci_dss"], "yes")
        self.assertEqual(BY_ID["azure_app_service"]["attest"]["hipaa_baa"], "no")  # Azure per-service list unreadable
        self.assertEqual(BY_ID["postgres__azure"]["attest"]["hipaa_baa"], "yes")    # product page verified

    def test_mainstream_azure_india_stack_passes_residency_and_iso(self):
        for rid in ("azure_app_service", "sqlserver__azure"):
            self.assertIn("centralindia", BY_ID[rid]["regions"]["india"], rid)
            self.assertEqual(BY_ID[rid]["attest"]["iso27001"], "yes", rid)

    def test_fly_has_no_india_region(self):
        self.assertEqual(BY_ID["fly_io"]["regions"]["india"], [])

    def test_bedrock_regions_are_region_ids(self):
        for g in ("india", "eu", "us"):
            v = regions.regions_for("bedrock", g)
            self.assertTrue(isinstance(v, list) and v, g)
            self.assertTrue(all(re.match(r"^[a-z]{2}-[a-z]+-\d$", x) for x in v), v)
        self.assertEqual(regions.INFERENCE_PROFILES["bedrock"]["india"], "in.")

    def test_regions_for_returns_region_ids_only(self):
        for key in regions.ENTRIES:
            if key == "self_hosted":
                continue
            for g in ("india", "eu", "us"):
                v = regions.regions_for(key, g)
                if v != regions.UNKNOWN:
                    self.assertFalse(any("*" in x for x in v), (key, g, v))


class CoreCheck(unittest.TestCase):
    def test_kb_check_core_is_clean(self):
        self.assertEqual(kb.check(core_only=True), [])


if __name__ == "__main__":
    unittest.main()

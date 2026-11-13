"""Supporting-layer knowledge base (plan 4.3, T-KB-01/04/05)."""
import unittest

from stacksense import kb
from stacksense.kb import bindings, model, services_app, services_data, services_ops
from stacksense.kb.sources import SOURCES

MODULES = (services_data, services_app, services_ops)
RECS = [r for m in MODULES for r in m.RECORDS]
BY_ID = {r["id"]: r for r in RECS}
DENY = {"minio_community": "storage", "azure_cache_for_redis": "cache", "azure_ad_b2c": "auth",
        "google_cloud_iot_core": "realtime", "firebase_dynamic_links": "other", "azure_cdn_classic": "cdn",
        "azure_cdn_edgio": "cdn", "azure_front_door_classic": "cdn", "azure_media_services": "other",
        "adal_azure_ad_graph": "auth"}


class SupportingKb(unittest.TestCase):
    def test_layers_and_counts(self):
        self.assertTrue({r["layer"] for r in RECS} <= set(model.SUPPORTING_LAYERS))
        counts = kb.counts()
        for layer in model.SUPPORTING_LAYERS:
            with self.subTest(layer=layer):
                self.assertGreaterEqual(counts[layer], 4)
                self.assertGreaterEqual(counts[layer], kb.MIN_COUNTS[layer])

    def test_deny_list_not_recommendable(self):
        for rid, layer in DENY.items():
            with self.subTest(id=rid):
                r = BY_ID[rid]
                self.assertEqual(r["layer"], layer)
                self.assertIn(r["status"], ("deprecated", "retired"))
                self.assertTrue(r["replaced_by"])
        self.assertTrue(all(r["status"] != "maintained" for r in RECS if r["id"] in DENY))

    def test_records_valid_and_sourced(self):
        for r in RECS:
            with self.subTest(id=r["id"]):
                self.assertEqual(model.record_problems(r), [])
                self.assertTrue(r["sources"])
                self.assertTrue(r["strengths"])
                self.assertTrue(r["tradeoffs"])
                for k in r["sources"] + [f["source_key"] for f in r["facts"]]:
                    self.assertIn(k, SOURCES)
                self.assertTrue(r["cost"])

    def test_data_at_rest_records_have_region_and_attestation_facts(self):
        for r in RECS:
            if not r["data_at_rest"] or r["status"] != "maintained":
                continue
            with self.subTest(id=r["id"]):
                self.assertIn(r["id"], bindings.BINDINGS)
                rk, ak = bindings.BINDINGS[r["id"]]
                if (rk, ak) == services_data.SELF:
                    self.assertEqual(r["regions"]["india"], ["*"])
                    self.assertEqual(r["attest"]["hipaa_baa"], "self")
                    continue
                self.assertIsNotNone(rk)
                self.assertIsNotNone(ak)
                texts = [f["text"] for f in r["facts"]]
                if any("unconfirmed" in t and "fails closed" in t for t in texts):
                    continue  # kb row without a cited page: explicit fail-closed fact instead
                self.assertTrue(any(t.startswith("Region") for t in texts))
                self.assertTrue(any(t.startswith("Attestation") for t in texts))

    def test_unverified_vendors_fail_closed(self):
        for rid in ("algolia", "ably", "datadog", "claude_api", "paddle", "backblaze_b2", "elastic_cloud"):
            r = BY_ID[rid]
            self.assertEqual(r["regions"], {"india": [], "eu": [], "us": []}, rid)
            self.assertEqual(set(r["attest"].values()), {"no"}, rid)
        self.assertEqual(BY_ID["razorpay"]["regions"]["india"], ["india"])
        self.assertEqual(BY_ID["firebase_authentication"]["regions"]["india"], [])
        self.assertEqual(BY_ID["amazon_s3"]["attest"]["hipaa_baa"], "yes")
        self.assertEqual(BY_ID["azure_service_bus"]["attest"]["hipaa_baa"], "no")  # Azure per-service list unreadable

    def test_separate_service_tags(self):
        tagged = {r["id"] for r in RECS if "separate_service" in r["caps"]}
        for rid in ("rabbitmq_self", "apache_kafka_self", "meilisearch_self", "centrifugo", "vllm_self"):
            self.assertIn(rid, tagged)
        for rid in ("pg_fts", "pg_boss", "native_websockets", "onnx_runtime", "pgvector", "redis_jobs"):
            self.assertNotIn(rid, tagged)

    def test_consistency_and_check(self):
        self.assertEqual(kb.consistency_problems(), [])
        self.assertEqual(kb.check(), [])


if __name__ == "__main__":
    unittest.main()

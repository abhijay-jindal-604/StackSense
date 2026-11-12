import unittest

from stacksense import kb
from stacksense.kb import hosting, model
from stacksense.kb.sources import SOURCES

RUNTIMES = {"node", "python", "jvm", "dotnet", "go", "ruby", "php", "beam", "edge_js", "baas", "saas", "static"}
HYBRID_CLOUD = {"aws_outposts": "aws", "azure_local": "azure", "google_distributed_cloud": "gcp"}


def _by_id():
    return {r["id"]: r for r in hosting.RECORDS}


class HostingKbT1F(unittest.TestCase):
    def test_count_and_layer(self):
        m = [r for r in hosting.RECORDS if r["status"] == "maintained"]
        self.assertGreaterEqual(len(m), 30)
        self.assertTrue(all(r["layer"] == "hosting" for r in hosting.RECORDS))
        self.assertGreaterEqual(kb.counts()["hosting"], 30)

    def test_valid_and_sources_resolve(self):
        for r in hosting.RECORDS:
            with self.subTest(id=r["id"]):
                self.assertEqual(model.record_problems(r), [])
                for k in r["sources"] + [f["source_key"] for f in r["facts"]]:
                    self.assertIn(k, SOURCES)
        self.assertEqual(kb.integrity_problems(), [])

    def test_kinds(self):
        allowed = {"static_host", "paas", "container", "k8s", "vm", "onprem", "hybrid_appliance", "serverless_fn"}
        self.assertTrue({r["kind"] for r in hosting.RECORDS} <= allowed)

    def test_runtime_lists(self):
        for r in hosting.RECORDS:
            with self.subTest(id=r["id"]):
                self.assertIsInstance(r["runtime"], list)
                self.assertTrue(r["runtime"])
                self.assertTrue(set(r["runtime"]) <= RUNTIMES)

    def test_no_india_region(self):
        recs = _by_id()
        for rid in ("render", "railway"):
            self.assertEqual(recs[rid]["regions"]["india"], [])

    def test_known_india_regions(self):
        recs = _by_id()
        self.assertEqual(recs["vercel"]["regions"]["india"], ["bom1"])
        self.assertEqual(recs["do_app_platform"]["regions"]["india"], ["BLR1"])
        self.assertIn("bom", recs["fly_io"]["regions"]["india"])

    def test_airgapped_do_not_need_internet(self):
        recs = _by_id()
        for rid in ("rke2_harbor_airgap", "openshift_disconnected"):
            self.assertFalse(recs[rid]["needs_internet"])
            self.assertTrue(recs[rid]["self_hostable"])
        for r in hosting.RECORDS:
            if r["kind"] == "onprem":
                self.assertTrue(r["self_hostable"])
                self.assertFalse(r["needs_internet"])

    def test_hybrid_appliances(self):
        recs = _by_id()
        hyb = {r["id"] for r in hosting.RECORDS if r["kind"] == "hybrid_appliance"}
        self.assertEqual(hyb, set(HYBRID_CLOUD))
        for rid, cloud in HYBRID_CLOUD.items():
            self.assertEqual(recs[rid]["cloud_affinity"], [cloud])
            self.assertTrue(recs[rid]["self_hostable"])

    def test_app_runner_not_recommendable(self):
        r = _by_id()["aws_app_runner"]
        self.assertNotEqual(r["status"], "maintained")
        self.assertTrue(r["replaced_by"])

    def test_cost_bands_monotone(self):
        for r in hosting.RECORDS:
            self.assertEqual(model.cost_problems(r["cost"]), [], r["id"])


if __name__ == "__main__":
    unittest.main()

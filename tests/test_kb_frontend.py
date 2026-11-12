import unittest

from stacksense import kb
from stacksense.kb import frontend, model
from stacksense.kb.sources import SOURCES
from stacksense.kb import sources_frontend

LAYERS = ("frontend_web", "frontend_mobile", "frontend_desktop", "frontend_game")
NEVER = {"create_react_app": "frontend_web", "angularjs": "frontend_web", "gatsby": "frontend_web",
         "xamarin": "frontend_mobile", "cordova_shell": "frontend_mobile"}


def _maintained(layer):
    return [r for r in frontend.RECORDS if r["layer"] == layer and r["status"] == "maintained"]


class FrontendKb(unittest.TestCase):
    def test_counts_per_layer(self):
        for layer in LAYERS:
            with self.subTest(layer=layer):
                self.assertGreaterEqual(len(_maintained(layer)), kb.MIN_COUNTS[layer])
        self.assertEqual({r["layer"] for r in frontend.RECORDS} - set(LAYERS), set())

    def test_records_valid_and_ids_unique(self):
        ids = [r["id"] for r in frontend.RECORDS]
        self.assertEqual(len(ids), len(set(ids)))
        for r in frontend.RECORDS:
            self.assertEqual(model.record_problems(r), [], r["id"])

    def test_registry_has_no_frontend_problems(self):
        for p in kb.check():
            self.assertFalse(any(layer in p for layer in LAYERS), p)
        self.assertEqual(kb.integrity_problems(), [])

    def test_maintained_records_complete(self):
        for r in frontend.RECORDS:
            if r["status"] != "maintained":
                continue
            with self.subTest(id=r["id"]):
                self.assertTrue(r["sources"])
                self.assertTrue(r["strengths"])
                self.assertTrue(r["tradeoffs"])
                self.assertTrue(r["facts"])
                for k in r["sources"] + [f["source_key"] for f in r["facts"]]:
                    self.assertIn(k, SOURCES)
                if r["id"] != "framework_templates" and r["current_major"] is None:
                    self.assertIn(r["id"], {"compose_android", "swiftui_ios", "pwa"})

    def test_never_recommended_are_not_maintained(self):
        by_id = {r["id"]: r for r in frontend.RECORDS}
        for rid, layer in NEVER.items():
            with self.subTest(id=rid):
                self.assertIn(rid, by_id)
                self.assertEqual(by_id[rid]["layer"], layer)
                self.assertNotEqual(by_id[rid]["status"], "maintained")
                self.assertTrue(by_id[rid]["replaced_by"])

    def test_framework_templates_kind(self):
        rec = {r["id"]: r for r in frontend.RECORDS}["framework_templates"]
        self.assertEqual(rec["kind"], "server_templates")
        self.assertEqual(rec["languages"], [])

    def test_capability_vocabulary(self):
        by_id = {r["id"]: r for r in frontend.RECORDS}
        for rid in ("nextjs", "nuxt", "astro"):
            self.assertIn("ssr", by_id[rid]["caps"])
        self.assertIn("ssg", by_id["hugo"]["caps"])
        self.assertIn("offline", by_id["react_native_expo"]["caps"])
        self.assertNotIn("store_billing", by_id["pwa"]["caps"])
        self.assertIn("low_end_devices", by_id["compose_android"]["caps"])

    def test_frontend_sources_do_not_collide(self):
        for k, v in sources_frontend.SOURCES.items():
            self.assertEqual(SOURCES[k], tuple(v))
            self.assertTrue(v[1].startswith("https://"))


if __name__ == "__main__":
    unittest.main()

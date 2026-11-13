import json
import re
import unittest
from pathlib import Path

from stacksense.description import Signal, extract
from stacksense.kb.keywords import RULES
from stacksense.kb.sources import SOURCES

PUBLIC = Path(__file__).resolve().parent.parent / "scenarios" / "public"


def ids(text):
    return [s.id for s in extract(text)]


class RuleTable(unittest.TestCase):
    def test_unique_ids_and_sources(self):
        names = [r.id for r in RULES]
        self.assertEqual(len(names), len(set(names)))
        for r in RULES:
            self.assertRegex(r.effect, r"^[a-z_]+(=[a-z_]+)?$", r.id)
            for p in r.patterns:
                re.compile(p)
            if r.source:
                self.assertIn(r.source, SOURCES, r.id)

    def test_ids_consumed_elsewhere_exist(self):
        for need in ("sensors", "social_graph", "ledger", "booking", "inventory", "recommendation",
                     "fraud", "low_end_devices"):
            self.assertIn(need, [r.id for r in RULES])


class Extract(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(extract(None), ())
        self.assertEqual(extract(""), ())
        self.assertEqual(extract("   "), ())

    def test_case_insensitive_and_effect(self):
        s = extract("A DOUBLE ENTRY Ledger")
        self.assertEqual(s, (Signal("ledger", "DOUBLE ENTRY", "consistency=strong", ("requirements.consistency",)),))

    def test_deterministic_order_and_dedup(self):
        a = extract("ledger for ledger entries, with photos and a chat inbox and images")
        self.assertEqual(a, extract("ledger for ledger entries, with photos and a chat inbox and images"))
        self.assertEqual(len({s.id for s in a}), len(a))
        order = [r.id for r in RULES]
        self.assertEqual([s.id for s in a], sorted((s.id for s in a), key=order.index))

    def test_booking_not_facebook(self):
        self.assertNotIn("booking", ids("Share on Facebook and read a notebook"))
        self.assertIn("booking", ids("Customers book electricians"))
        self.assertIn("booking", ids("Online booking for clinics"))
        self.assertNotIn("booking", ids("An online store selling books"))

    def test_negation(self):
        self.assertNotIn("subscription", ids("There are no subscriptions"))
        self.assertNotIn("chat", ids("Support without chat or messaging"))
        self.assertIn("chat", ids("No wait list, but users can chat"))
        self.assertIn("ledger", ids("Not a toy. It keeps a ledger."))

    def test_word_boundaries(self):
        self.assertNotIn("upi", ids("Anticipation of a stupid rupture"))
        self.assertNotIn("sensors", ids("Nonsensorial"))
        self.assertNotIn("kyc", ids("lucky"))
        self.assertNotIn("rag", ids("A storage and fragment tool"))
        self.assertIn("rag", ids("RAG over the knowledge base"))
        self.assertNotIn("government", ids("governments"))
        self.assertNotIn("global", ids("global state in the app"))
        self.assertIn("global", ids("Used worldwide"))

    def test_effects(self):
        eff = {s.id: s.effect for s in extract("Markdown blog; MQTT sensor telemetry; follow friends; recommend items")}
        self.assertEqual(eff["markdown"], "cms=git_markdown")
        self.assertEqual(eff["sensors"], "data_shape=time_series")
        self.assertEqual(eff["social_graph"], "data_shape=graph")
        self.assertEqual(eff["recommendation"], "data_shape=graph")
        self.assertEqual({s.id: s.effect for s in extract("non-technical editors")}["cms_editors"], "cms=headless")

    def test_other_rules(self):
        self.assertIn("inventory", ids("Track stock levels per warehouse"))
        self.assertNotIn("inventory", ids("stock market news"))
        self.assertIn("fraud", ids("Detects fraudulent transfers"))
        self.assertIn("low_end_devices", ids("Runs on 2GB RAM phones"))
        self.assertIn("low_end_devices", ids("feature phone users"))
        self.assertIn("intermittent_connectivity", ids("works offline on 2G"))
        self.assertIn("multi_city", ids("Launching in 3 cities"))
        self.assertIn("health", ids("Patients see prescriptions"))
        self.assertIn("children", ids("Learning app for kids"))
        self.assertIn("internal_only", ids("Back-office tool"))
        self.assertIn("gps", ids("show nearby shops on a map"))

    def test_rename_does_not_change_signals(self):
        self.assertEqual(ids("Acme: customers book slots"), ids("Zeta: customers book slots"))


class PublicScenarios(unittest.TestCase):
    EXPECT = {
        "P1": {"markdown"},
        "P2": {"chat", "booking", "multi_city"},
        "P3": {"subscription", "collaborative_editing"},
        "P4": {"ledger", "upi", "kyc_documents", "credit_scoring"},
        "P5": {"internal_only"},
        "P6": {"gps", "photos", "low_end_devices", "intermittent_connectivity"},
    }

    def test_public(self):
        for sid, want in self.EXPECT.items():
            with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
                d = json.load(fh)["project"]["description"]
            self.assertEqual(set(ids(d)), want, sid)


if __name__ == "__main__":
    unittest.main()

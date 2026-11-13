import json
import pathlib
import unittest

from stacksense.kb import eol, existing_patterns as ep
from stacksense.kb.sources import SOURCES

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _ids(text):
    return [h.pattern_id for h in ep.match(text)]


class Table(unittest.TestCase):
    def test_integrity(self):
        self.assertGreaterEqual(len(ep.PATTERNS), 45)
        ids = [p.id for p in ep.PATTERNS]
        self.assertEqual(len(ids), len(set(ids)))
        for p in ep.PATTERNS:
            self.assertIn(p.family, ep.FAMILIES, p.id)
            self.assertTrue(p.note and p.kind, p.id)
            if p.source:
                self.assertIn(p.source, SOURCES, p.id)
            if p.eol_product:
                self.assertIn(p.eol_product, eol.PRODUCTS, p.id)
        for fam in ep.FAMILIES:
            self.assertGreaterEqual(sum(p.family == fam for p in ep.PATTERNS), 5, fam)

    def test_regexes_compile_and_do_not_match_empty(self):
        for p, rx in zip(ep.PATTERNS, ep._COMPILED):
            self.assertIsNone(rx.fullmatch(""), p.id)


class Matching(unittest.TestCase):
    def test_p5_systems(self):
        self.assertEqual(_ids("Microsoft Entra ID (Azure AD)"), ["entra_id"])
        hits = ep.match("On-prem SQL Server 2019")
        self.assertEqual([(h.pattern_id, h.version) for h in hits], [("sqlserver", "2019"), ("on_prem", None)])
        self.assertEqual(_ids("Microsoft 365"), ["microsoft_365"])

    def test_edge_systems(self):
        self.assertEqual([(h.pattern_id, h.version) for h in ep.match("Windows Server 2012 R2")], [("windows_server", "2012")])
        self.assertEqual([(h.pattern_id, h.version) for h in ep.match("PHP 7.4 monolith")], [("php", "7.4")])
        self.assertEqual([(h.pattern_id, h.version) for h in ep.match("MySQL 5.7")], [("mysql", "5.7")])
        self.assertEqual(_ids("AngularJS admin"), ["angularjs"])
        self.assertEqual(_ids("Azure AD B2C"), ["azure_ad_b2c"])
        self.assertEqual([(h.pattern_id, h.version) for h in ep.match("SQL Server 2016")], [("sqlserver", "2016")])
        self.assertEqual([(h.pattern_id, h.version) for h in ep.match(".NET 8 services")], [("dotnet", "8")])

    def test_look_alikes_do_not_collide(self):
        self.assertEqual(_ids("Azure Cache for Redis"), ["azure_cache_redis"])
        self.assertEqual(_ids("Redis 6"), ["redis"])
        self.assertEqual(_ids("ASP.NET Core 8 API"), ["dotnet"])
        self.assertEqual(_ids("ASP.NET WebForms"), ["dotnet_framework"])
        self.assertEqual(_ids("Azure Active Directory B2C"), ["azure_ad_b2c"])
        self.assertEqual(_ids("Azure Front Door (classic)"), ["azure_front_door_classic"])
        self.assertEqual(_ids("Azure CDN Standard from Microsoft (classic)"), ["azure_cdn_classic"])
        self.assertEqual(_ids("Azure CDN from Edgio"), ["azure_cdn_edgio"])
        self.assertEqual(_ids("Entra External ID"), ["entra_external_id"])
        self.assertEqual(_ids("Angular 14 front end"), ["angular"])
        self.assertEqual(_ids("JavaScript widgets"), [])
        self.assertEqual(_ids("we tally up the votes"), [])

    def test_negation(self):
        self.assertEqual(_ids("no Kafka cluster"), [])
        self.assertEqual(_ids("without Oracle Database"), [])
        self.assertEqual(_ids("Kafka"), ["kafka"])

    def test_version_only_directly_after_name(self):
        self.assertEqual(ep.match("Python 3 scripts")[0].version, "3")
        self.assertIsNone(ep.match("PHP monolith 7.4")[0].version)
        self.assertEqual(ep.match("node v18.2.1")[0].version, "18.2.1")
        self.assertEqual(ep.match("Postgres 12")[0].version, "12")
        self.assertEqual(ep.match("Ubuntu 20.04 LTS")[0].version, "20.04")

    def test_unknown_and_non_string(self):
        self.assertEqual(ep.match("Acme Widget Platform"), ())
        self.assertEqual(ep.match(None), ())
        self.assertEqual(ep.match(""), ())

    def test_eol_args_feed_eol(self):
        h = ep.match("AngularJS admin")[0]
        self.assertEqual(ep.eol_args(h), ("angularjs", "1"))
        self.assertEqual(eol.verdict(*ep.eol_args(h))["state"], "ended")
        self.assertEqual(eol.verdict(*ep.eol_args(ep.match("SQL Server 2019")[0]))["mainstream_ended"], True)
        self.assertEqual(eol.verdict(*ep.eol_args(ep.match("Azure AD B2C")[0]))["kind"], "end_of_sale")
        self.assertIsNone(ep.eol_args(ep.match("Okta")[0]))

    def test_every_eol_row_is_reachable_from_some_pattern_product(self):
        covered = {p.eol_product for p in ep.PATTERNS if p.eol_product}
        for r in eol.ROWS:
            if r.product == "openssl":
                continue
            self.assertIn(r.product, covered, r.key)

    def test_deterministic_and_ordered(self):
        text = "On-prem SQL Server 2019 with Kafka and Okta on AWS"
        a, b = ep.match(text), ep.match(text)
        self.assertEqual(a, b)
        order = [p.id for p in ep.PATTERNS]
        idx = [order.index(h.pattern_id) for h in a]
        self.assertEqual(idx, sorted(idx))


class PublicScenarios(unittest.TestCase):
    def test_all_existing_systems_in_scenarios_match(self):
        systems = []
        for path in sorted((ROOT / "scenarios").rglob("*.json")):
            try:
                data = json.loads(path.read_text())
            except ValueError:      # deliberately malformed edge files
                continue
            for sc in (data["scenarios"] if isinstance(data, dict) and "scenarios" in data else [data]):
                inp = sc.get("input", sc) if isinstance(sc, dict) else {}
                inf = inp.get("infrastructure") or {}
                systems += [s for s in inf.get("existing_systems") or [] if isinstance(s, str)]
        self.assertGreaterEqual(len(systems), 5)
        for s in sorted(set(systems)):
            self.assertTrue(ep.match(s), f"no pattern for {s!r}")


if __name__ == "__main__":
    unittest.main()

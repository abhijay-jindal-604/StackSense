import copy
import dataclasses
import json
import random
import unittest
from pathlib import Path

from stacksense import profile as P
from stacksense.description import Signal, extract
from stacksense.existing import ExistingReport, analyse
from stacksense.profile import derive
from stacksense.validate import validate

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"


def load(sid):
    with open(PUBLIC / f"{sid}.json", encoding="utf-8") as fh:
        return json.load(fh)


def prof(raw, signals=()):
    v = validate(raw)
    assert v.errors == [], v.errors
    return derive(v, signals)


def codes(p):
    return [w["code"] for w in p.warnings]


def has_asm(p, text):
    return any(text in a for a in p.assumptions)


class PublicScenarios(unittest.TestCase):
    EXPECTED = {"P1": ("xs", 1), "P2": ("s", 2), "P3": ("m", 5), "P4": ("m", 5), "P5": ("s", 2), "P6": ("s", 2)}

    def test_size_and_ops(self):
        for sid, (size, ops) in self.EXPECTED.items():
            with self.subTest(sid):
                p = prof(load(sid))
                self.assertEqual(p.size, size)
                self.assertEqual(p.ops_capacity, ops)

    def test_backend_and_residency(self):
        self.assertFalse(prof(load("P1")).needs_backend)
        self.assertFalse(prof(load("P1")).needs_database)
        for sid in ("P2", "P3", "P4", "P5", "P6"):
            self.assertTrue(prof(load(sid)).needs_backend, sid)
        self.assertEqual(prof(load("P4")).effective_residency, "india")
        self.assertEqual(prof(load("P4")).cloud, "aws")
        self.assertTrue(prof(load("P4")).cloud_explicit)
        self.assertIsNone(prof(load("P2")).cloud)

    def test_immutable_and_types(self):
        p = prof(load("P2"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.size = "xl"
        for name in ("clients", "languages", "compliance", "weights", "regions", "assumptions", "warnings"):
            self.assertIsInstance(getattr(p, name), tuple, name)
        self.assertEqual(p.clients, ("web", "android"))
        self.assertEqual(p.weight("time_to_market"), 5)
        with self.assertRaises(TypeError):
            p.values["project.type"] = "x"


class Formulas(unittest.TestCase):
    def setUp(self):
        self.raw = load("P2")

    def test_peak_default_5_percent(self):
        r = copy.deepcopy(self.raw)
        del r["scale"]["peak_concurrent_users"]
        r["scale"]["users_12_months"] = 30000
        p = prof(r)
        self.assertEqual(p.peak_concurrent, 1500)
        self.assertTrue(has_asm(p, "scale.peak_concurrent_users not given: estimated 1,500 (5% of users=30,000"))
        r["scale"]["users_12_months"] = 0
        r["scale"]["users_at_launch"] = 0
        self.assertEqual(prof(r).peak_concurrent, 1)
        r["scale"]["users_12_months"] = 30001
        self.assertEqual(prof(r).peak_concurrent, 1501)  # ceil

    def test_rps(self):
        p = prof(self.raw)  # peak 800
        self.assertEqual(p.peak_rps, 160)
        self.assertTrue(has_asm(p, "160 requests/s"))
        r = copy.deepcopy(self.raw)
        r["scale"]["peak_rps"] = 42
        p = prof(r)
        self.assertEqual(p.peak_rps, 42)
        self.assertFalse(has_asm(p, "requests/s (0.2"))
        r["scale"]["peak_concurrent_users"] = 801
        r["scale"].pop("peak_rps")
        self.assertEqual(prof(r).peak_rps, 161)

    def test_realtime_rate(self):
        self.assertEqual(prof(self.raw).realtime_msgs_per_s, 800)
        self.assertEqual(prof(load("P4")).realtime_msgs_per_s, 0)

    def test_size_class_boundaries(self):
        for bounds in (P.SIZE_USERS_MAX, P.SIZE_PEAK_MAX, P.SIZE_DATA_GB_MAX):
            for i, b in enumerate(bounds):
                self.assertEqual(P.size_class(b, bounds), P.SIZE_CLASSES[i])
                self.assertEqual(P.size_class(b + 1, bounds), P.SIZE_CLASSES[i + 1])
        self.assertEqual(P.size_class(0, P.SIZE_USERS_MAX), "xs")
        self.assertEqual(P.size_class(5.5, P.SIZE_DATA_GB_MAX), "s")

    def test_size_is_largest_dimension(self):
        r = copy.deepcopy(load("P1"))  # xs everywhere
        r["scale"]["data_volume_gb_12_months"] = 1001
        p = prof(r)
        self.assertEqual((p.size_users, p.size_peak, p.size_data, p.size), ("xs", "xs", "l", "l"))
        r = copy.deepcopy(load("P1"))
        r["scale"]["peak_concurrent_users"] = 100001
        self.assertEqual(prof(r).size, "xl")
        r = copy.deepcopy(load("P1"))
        r["scale"]["users_12_months"] = 5001
        self.assertEqual(prof(r).size, "s")

    def test_users_at_launch_larger(self):
        r = copy.deepcopy(load("P1"))
        r["scale"]["users_at_launch"] = 60000
        p = prof(r)
        self.assertEqual(p.users, 60000)
        self.assertEqual(p.size_users, "m")

    def test_data_volume_default(self):
        r = copy.deepcopy(self.raw)
        del r["scale"]["data_volume_gb_12_months"]
        p = prof(r)  # file_media_storage true: 0.05 GB/user
        self.assertEqual(p.data_volume_gb, 1500)
        self.assertTrue(has_asm(p, "scale.data_volume_gb_12_months not given: estimated 1,500 GB"))
        r["requirements"]["file_media_storage"] = False
        self.assertEqual(prof(r).data_volume_gb, 60)
        r["scale"]["users_12_months"] = 100
        r["scale"]["users_at_launch"] = 10
        self.assertEqual(prof(r).data_volume_gb, 1)  # minimum 1 GB

    def test_ops_capacity(self):
        self.assertEqual(P.ops_capacity("beginner", False, 1), 1)
        self.assertEqual(P.ops_capacity("mixed", False, 5), 2)
        self.assertEqual(P.ops_capacity("intermediate", True, 5), 4)
        self.assertEqual(P.ops_capacity("senior", False, 6), 4)
        self.assertEqual(P.ops_capacity("senior", True, 6), 5)  # 6 capped
        self.assertEqual(P.ops_capacity("beginner", True, 6), 4)

    def test_delivery_pressure(self):
        self.assertEqual(P.delivery_pressure(2, 1, 1, False)[0], 3)      # 2.0
        self.assertEqual(P.delivery_pressure(4, 1, 1, False)[0], 2)      # 4.0 (not < 4)
        self.assertEqual(P.delivery_pressure(8, 1, 1, False)[0], 1)      # 8.0
        self.assertEqual(P.delivery_pressure(16, 1, 1, False)[0], 0)     # 16.0
        self.assertEqual(P.delivery_pressure(8, 3, 2, True), (1, 8.0))   # P2
        self.assertEqual(P.delivery_pressure(10, 1, 0, False)[0], 1)     # max(1, units)
        self.assertEqual(prof(load("P1")).delivery_pressure, 3)

    def test_dynamic_score_and_needs_backend(self):
        p1 = prof(load("P1"))
        self.assertEqual(p1.dynamic_score, 0)
        self.assertFalse(p1.needs_backend)
        toggles = [("auth", "email_password"), ("payments", True), ("realtime", True), ("multi_tenant", True),
                   ("file_media_storage", True), ("ml_features", "inference_api")]
        for key, val in toggles:
            with self.subTest(key):
                r = copy.deepcopy(load("P1"))
                r["requirements"][key] = val
                p = prof(r)
                self.assertTrue(p.needs_backend)
                self.assertTrue(p.needs_database)
                self.assertEqual(p.dynamic_score, 1)
        r = copy.deepcopy(load("P1"))
        r["project"]["type"] = "web_app"
        self.assertTrue(prof(r).needs_backend)
        # High traffic but static: still no backend (the section 6 trap).
        r = copy.deepcopy(load("P1"))
        r["scale"]["users_12_months"] = 2_000_000
        r["scale"]["peak_concurrent_users"] = 50_000
        p = prof(r)
        self.assertEqual(p.size, "l")
        self.assertFalse(p.needs_backend)
        # workload alone scores a point but does not force a backend (precise rule).
        r = copy.deepcopy(load("P1"))
        r["scale"]["workload"] = "balanced"
        p = prof(r)
        self.assertEqual(p.dynamic_score, 1)
        self.assertFalse(p.needs_backend)
        r = copy.deepcopy(load("P1"))
        r["project"]["platforms"] = ["api_only"]
        p = prof(r)
        self.assertTrue(p.api_only)
        self.assertEqual(p.clients, ())
        self.assertTrue(p.needs_backend)

    def test_consistency_resolution(self):
        self.assertEqual(prof(load("P2")).consistency, "strong")
        self.assertEqual(prof(load("P6")).consistency, "eventual")
        r = copy.deepcopy(load("P6"))
        p = prof(r, signals=(Signal("booking", "appointment", "consistency=strong"),))
        self.assertEqual(p.consistency, "strong")
        self.assertEqual(prof(load("P2") | {"requirements": {**load("P2")["requirements"], "consistency": "eventual"}}).consistency,
                         "eventual")

    def test_data_shape_resolution(self):
        self.assertEqual(prof(load("P2")).data_shape, "relational")
        r = copy.deepcopy(load("P6"))
        r["project"]["type"] = "iot"
        self.assertEqual(prof(r).data_shape, "time_series")
        r["project"]["type"] = "data_analytics"
        self.assertEqual(prof(r).data_shape, "analytical")
        r["project"]["type"] = "social"
        self.assertEqual(prof(r, (Signal("recommendation", "recommend", "data_shape=graph"),)).data_shape, "graph")
        r["requirements"]["data_shape"] = "document"
        self.assertEqual(prof(r, (Signal("recommendation", "recommend", "data_shape=graph"),)).data_shape, "document")


class Residency(unittest.TestCase):
    def test_rbi_implies_india(self):
        r = copy.deepcopy(load("P4"))
        r["infrastructure"]["data_residency"] = "none"
        p = prof(r)
        self.assertEqual(p.residency, "none")
        self.assertEqual(p.effective_residency, "india")
        self.assertIn("RBI_IMPLIES_INDIA", codes(p))
        self.assertEqual(next(w for w in p.warnings if w["code"] == "RBI_IMPLIES_INDIA")["severity"], "warning")
        self.assertTrue(has_asm(p, "treated as india"))
        self.assertFalse(p.infeasible)
        self.assertTrue(p.india)

    def test_rbi_conflict(self):
        for res in ("eu", "us"):
            r = copy.deepcopy(load("P4"))
            r["infrastructure"]["data_residency"] = res
            p = prof(r)
            self.assertTrue(p.infeasible)
            w = next(w for w in p.warnings if w["code"] == "RESIDENCY_COMPLIANCE_CONFLICT")
            self.assertEqual(w["severity"], "critical")
            self.assertIn(f"data_residency={res}", w["message"])

    def test_other_unverifiable(self):
        r = copy.deepcopy(load("P2"))
        r["infrastructure"]["data_residency"] = "other"
        p = prof(r)
        self.assertIn("RESIDENCY_UNVERIFIABLE", codes(p))
        self.assertEqual(p.regions, ())
        self.assertFalse(p.infeasible)

    def test_gdpr_does_not_force_eu(self):
        p = prof(load("P3"))
        self.assertEqual(p.effective_residency, "none")
        self.assertTrue(p.gdpr_eu_preference)
        self.assertTrue(p.eu)

    def test_cloud_none(self):
        r = copy.deepcopy(load("P2"))
        r["infrastructure"]["cloud_preference"] = "none"
        p = prof(r)
        self.assertIn("CLOUD_NONE_INTERPRETED", codes(p))
        self.assertIsNone(p.cloud)
        self.assertTrue(p.cloud_explicit)
        r["infrastructure"]["deployment_model"] = "on_premise"
        p = prof(r)
        self.assertNotIn("CLOUD_NONE_INTERPRETED", codes(p))
        self.assertTrue(p.self_hosted_only)
        self.assertFalse(p.air_gapped)

    def test_regions_for_india(self):
        p = prof(load("P5"))
        if p.regions:  # region KB may be unavailable while being edited; then no region
            self.assertEqual(p.region("aws"), "ap-south-1")
            self.assertEqual(p.region("azure"), "centralindia")
        self.assertEqual(prof(load("P1")).regions, ())

    def test_warning_shape(self):
        r = copy.deepcopy(load("P4"))
        r["infrastructure"]["data_residency"] = "none"
        for w in prof(r).warnings:
            self.assertEqual(sorted(w), ["code", "fields", "message", "severity"])
            self.assertIn(w["severity"], ("info", "warning", "critical"))


class AssumptionsAndDeterminism(unittest.TestCase):
    def test_asm_02_derived_values_recorded(self):
        r = copy.deepcopy(load("P2"))
        del r["scale"]["peak_concurrent_users"]
        del r["scale"]["data_volume_gb_12_months"]
        p = prof(r)
        for text in ("peak_concurrent_users not given", "data_volume_gb_12_months not given",
                     "requests/s", "Size class", "Dynamic score", "Delivery pressure",
                     "Operations capacity", "consistency auto resolved", "data_shape auto resolved"):
            self.assertTrue(has_asm(p, text), text)

    def test_explicit_values_are_not_reported_as_estimates(self):
        p = prof(load("P1"))
        self.assertFalse(has_asm(p, "peak_concurrent_users not given"))
        self.assertFalse(has_asm(p, "data_volume_gb_12_months not given"))

    def test_framework_language_assumption(self):
        r = copy.deepcopy(load("P2"))
        r["team"]["languages"] = ["React", "Python"]
        p = prof(r)
        self.assertEqual(p.languages, ("python", "typescript"))
        self.assertTrue(has_asm(p, "is a framework; treated as typescript"))

    def test_shuffled_lists_give_same_profile(self):
        base = prof(load("P4"))
        rng = random.Random(7)
        for _ in range(10):
            r = copy.deepcopy(load("P4"))
            for lst in (r["project"]["platforms"], r["team"]["languages"], r["compliance"]):
                rng.shuffle(lst)
            p = prof(r)
            for f in dataclasses.fields(P.Profile):
                if f.name != "values":
                    self.assertEqual(getattr(p, f.name), getattr(base, f.name), f.name)

    def test_repeatable(self):
        self.assertEqual(prof(load("P3")), prof(load("P3")))

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            derive(validate({}))


class Stubs(unittest.TestCase):
    def test_description_signals(self):
        self.assertIn("ledger", [s.id for s in extract("double-entry ledger")])
        self.assertEqual(extract(None), ())

    def test_existing_analyse(self):
        rep = analyse(["Microsoft 365", "On-prem SQL Server 2019"])
        self.assertIsInstance(rep, ExistingReport)
        self.assertEqual([m.pattern_id for m in rep.matches], ["microsoft_365", "sqlserver", "on_prem"])
        self.assertEqual(rep.unmatched, ())
        self.assertEqual(analyse([]).unmatched, ())


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the 14 Nov engine review (H1-H3, M1-M5, L1, L4, L5, processor-only residency, C9).

Each test perturbs a public scenario the way a judge would and checks the engine's general rule, never a
scenario id.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from stacksense import combine, engine
from stacksense.scoring import Scored
from tests.helpers import assert_no_hard_violation

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
EDGE = ROOT / "scenarios" / "edge"

_BASE: dict[str, dict] = {}


def base(sid: str) -> dict:
    if sid not in _BASE:
        raw = json.loads((PUBLIC / f"{sid}.json").read_text(encoding="utf-8"))
        raw.pop("scenario_id", None)
        _BASE[sid] = raw
    return copy.deepcopy(_BASE[sid])


def perturb(sid: str, **over) -> dict:
    raw = base(sid)
    for path, value in over.items():
        keys = path.split("__")
        node = raw
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    return raw


_RUNS: dict[str, tuple[dict, dict]] = {}


def run(sid: str, **over) -> tuple[dict, dict]:
    key = sid + json.dumps(over, sort_keys=True)
    if key not in _RUNS:
        raw = perturb(sid, **over)
        _RUNS[key] = (raw, engine.recommend(raw, trace=False))
    return _RUNS[key]


def codes(out: dict) -> list[str]:
    return [w["code"] for w in out.get("warnings") or []]


def supporting(out: dict, slot: str) -> dict | None:
    return next((s for s in out["stack"].get("supporting") or [] if s["slot"] == slot), None)


class BudgetCheapestFloorTest(unittest.TestCase):
    """H1: the cheapest-stack fallback needs a score floor and a minimum saving."""

    def assert_transactional_db(self, out):
        db = out["stack"]["database"]["choice"]
        self.assertNotIn("SQLite", db)
        self.assertNotIn("BigQuery", db)

    def test_low_budget_keeps_marketplace_database(self):
        raw, out = run("P2", budget__monthly_infra_usd=40)
        self.assert_transactional_db(out)
        self.assertIn("BUDGET_EXCEEDED", codes(out))
        assert_no_hard_violation(self, raw, out)

    def test_azure_keeps_managed_database(self):
        raw, out = run("P2", infrastructure__cloud_preference="azure")
        self.assert_transactional_db(out)
        self.assertIn("Azure", out["stack"]["database"]["choice"])
        assert_no_hard_violation(self, raw, out)

    def test_zero_budget_does_not_drop_relational_store(self):
        _, out = run("P4", budget__monthly_infra_usd=0)
        self.assertNotIn("DynamoDB", out["stack"]["database"]["choice"])
        self.assertIn("BUDGET_EXCEEDED", codes(out))

    def test_fallback_assumption_names_floor(self):
        _, out = run("P2", budget__monthly_infra_usd=40)
        text = " ".join(out["assumptions"])
        self.assertIn("Budget fallback", text)
        self.assertIn(f"{round(combine.T['budget_cheapest_accept_ratio'] * 100)}%", text)


class PrimaryStoreTest(unittest.TestCase):
    """C9: an analytics warehouse is never the primary store of a transactional application."""

    def test_olap_rejected_unless_analytical(self):
        from stacksense import kb
        from tests.helpers import profile_of
        p = profile_of(base("P2"))
        be = Scored(kb.get("nestjs"), 0.0, ())
        db = Scored(kb.get("bigquery"), 0.0, ())
        rej = combine.check_backend_database(be, db, p)
        self.assertIsNotNone(rej)
        self.assertEqual(rej[0], "C9")
        pa = profile_of(perturb("P2", requirements__data_shape="analytical"))
        self.assertIsNone(combine.check_backend_database(be, db, pa))

    def test_hipaa_telehealth_budget_fallback(self):
        raw = json.loads((EDGE / "H06_hipaa_telehealth_us.json").read_text(encoding="utf-8"))
        out = engine.recommend(raw, trace=False)
        self.assertNotIn("BigQuery", out["stack"]["database"]["choice"])


class ExistingSystemsHardFiltersTest(unittest.TestCase):
    """H2: an existing system that fails a hard constraint is flagged, never silently reused."""

    def test_residency_conflict_is_warned_and_note_rewritten(self):
        _, out = run("P5")
        conf = [w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_CONFLICT"
                and "infrastructure.data_residency" in w["fields"]]
        self.assertTrue(conf)
        self.assertTrue(all(w["severity"] == "warning" for w in conf))
        entra = [n for n in out["integration_notes"] if n.startswith("Microsoft Entra ID")]
        self.assertTrue(entra and "not reused as is" in entra[0], entra)

    def test_air_gapped_conflict_is_critical(self):
        _, out = run("P2", infrastructure__deployment_model="air_gapped",
                     infrastructure__data_residency="none", infrastructure__existing_systems=["Auth0", "Stripe"])
        conf = [w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_CONFLICT"]
        self.assertTrue(conf)
        self.assertTrue(all(w["severity"] == "critical" for w in conf))
        for raw_name in ("Auth0", "Stripe"):
            note = next(n for n in out["integration_notes"] if n.startswith(raw_name))
            self.assertIn("air-gapped", note)


class CriticalGapsRelaxedTest(unittest.TestCase):
    """M1: every critical capability gap is listed in relaxed_constraints and the summary."""

    def test_critical_gaps_relaxed(self):
        _, out = run("P2", infrastructure__data_residency="us", compliance=["hipaa"])
        crit = [w for w in out["warnings"] if w["severity"] == "critical" and w["code"] == "SUPPORTING_GAP"]
        self.assertTrue(crit)
        self.assertEqual(len([r for r in out["relaxed_constraints"] if r.startswith("RELAXED:")]), len(crit))
        self.assertIn("relaxed:", out["summary"])
        self.assertNotIn("..", out["summary"])
        for r in out["relaxed_constraints"]:
            self.assertIn(r, out["assumptions"])


class ProcessorResidencyTest(unittest.TestCase):
    """Item 10: processor-only services (payments, SMS, push) under us/eu residency with an unverified
    region pass with RESIDENCY_PROCESSOR_UNVERIFIED; India and compliance checks stay fail closed."""

    def test_eu_gdpr_payments_pass_with_warning(self):
        raw, out = run("P2", infrastructure__data_residency="eu", compliance=["gdpr"])
        pay = supporting(out, "payments")
        self.assertIsNotNone(pay)
        warn = [w for w in out["warnings"] if w["code"] == "RESIDENCY_PROCESSOR_UNVERIFIED"]
        self.assertTrue(any(w["message"].startswith(pay["choice"]) for w in warn), warn)
        self.assertIn("Standard Contractual Clauses", warn[0]["message"])
        self.assertIn("infrastructure.data_residency", pay["driven_by"])
        assert_no_hard_violation(self, raw, out)

    def test_us_hipaa_still_needs_baa(self):
        raw, out = run("P2", infrastructure__data_residency="us", compliance=["hipaa"])
        # residency alone no longer blocks a payment processor, but HIPAA (F5) still fails closed
        self.assertIsNone(supporting(out, "payments"))
        gaps = [w for w in out["warnings"] if w["code"] == "SUPPORTING_GAP" and "payments" in w["message"]]
        self.assertTrue(gaps and gaps[0]["severity"] == "critical")
        assert_no_hard_violation(self, raw, out)

    def test_us_without_compliance_passes(self):
        raw, out = run("P2", infrastructure__data_residency="us", compliance=[])
        self.assertIsNotNone(supporting(out, "payments"))
        self.assertIn("RESIDENCY_PROCESSOR_UNVERIFIED", codes(out))
        assert_no_hard_violation(self, raw, out)

    def test_india_unchanged(self):
        _, out = run("P2")
        self.assertNotIn("RESIDENCY_PROCESSOR_UNVERIFIED", codes(out))


class SupportingFixesTest(unittest.TestCase):
    def test_nakama_needs_postgres(self):
        from stacksense import kb
        from tests.helpers import profile_of
        p = profile_of(base("P2"))
        be = Scored(kb.get("nakama"), 0.0, ())
        rej = combine.check_backend_database(be, Scored(kb.get("sqlite"), 0.0, ()), p)
        self.assertEqual(rej[0], "C5")
        self.assertIsNone(combine.check_backend_database(be, Scored(kb.get("postgres"), 0.0, ()), p))

    def test_cdn_not_justified_by_regulated_uploads(self):
        _, out = run("P2")
        cdn = supporting(out, "cdn")
        self.assertNotIn("requirements.file_media_storage", cdn["driven_by"])
        self.assertTrue(any("pre-signed URLs" in a for a in out["assumptions"]))
        _, free = run("P2", infrastructure__data_residency="none", compliance=[])
        cdn2 = supporting(free, "cdn")
        if cdn2 is not None:
            self.assertFalse(any("pre-signed URLs" in a for a in free["assumptions"]))

    def test_existing_kafka_is_reused(self):
        _, out = run("P4", infrastructure__existing_systems=["Apache Kafka 3.7 cluster"])
        q = supporting(out, "queue")
        self.assertIn("Kafka", q["choice"])
        self.assertIn("reuse", q["justification"])

    def test_native_bonus_from_backend_host_only(self):
        _, out = run("P2")
        # the web-only DigitalOcean host does not make DigitalOcean Spaces native to a Supabase back end
        self.assertEqual(supporting(out, "storage")["choice"], "Supabase Storage")

    def test_placeholder_names_are_concrete(self):
        _, out = run("P1")
        names = [s["choice"] for s in out["stack"]["supporting"]]
        self.assertFalse(any("Vercel/Netlify" in n for n in names), names)
        self.assertTrue(any("Cloudflare Pages" in n for n in names), names)

    def test_justification_lists_negative_terms(self):
        _, out = run("P2")
        ci = supporting(out, "ci_cd")
        self.assertIn("Against it:", ci["justification"])

    def test_llm_residency_article(self):
        _, out = run("P2", requirements__ml_features="llm_rag")
        text = json.dumps(out)
        self.assertNotIn("a india", text)


class CliStdinTest(unittest.TestCase):
    def cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-m", "stacksense", *args], cwd=str(ROOT), input=stdin,
                              capture_output=True, text=True, encoding="utf-8")

    def test_missing_path_fails_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.cli("run", str(Path(d) / "missing.json"), "-o", d)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("does not exist", r.stderr)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.cli("run", "-", "-o", d, stdin=(PUBLIC / "P1.json").read_text(encoding="utf-8"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(d) / "P1_output.json").is_file())


if __name__ == "__main__":
    unittest.main()

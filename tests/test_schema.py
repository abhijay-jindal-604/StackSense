import glob
import json
import unittest
from pathlib import Path

from stacksense import schema
from stacksense.kb.sources import SOURCES
from stacksense.validate import validate

ROOT = Path(__file__).resolve().parent.parent

PT = ["content_site", "web_app", "saas_b2b", "ecommerce", "marketplace", "social", "realtime_collab",
      "fintech", "healthtech", "data_analytics", "iot", "ai_ml_product", "internal_tool", "gaming",
      "api_platform", "other"]
# Literal copy of statement section 3.1: path -> (type, required, allowed values, default)
TABLE = {
    "project.name": ("string", False, None, None),
    "project.type": ("enum", True, PT, None),
    "project.description": ("string", False, None, None),
    "project.platforms": ("list", True, ["web", "android", "ios", "desktop", "api_only"], None),
    "scale.users_at_launch": ("integer", True, None, None),
    "scale.users_12_months": ("integer", True, None, None),
    "scale.peak_concurrent_users": ("integer", False, None, None),
    "scale.traffic_pattern": ("enum", False, ["steady", "spiky", "seasonal"], "steady"),
    "scale.workload": ("enum", False, ["read_heavy", "balanced", "write_heavy"], "balanced"),
    "scale.data_volume_gb_12_months": ("number", False, None, None),
    "team.size": ("integer", True, None, None),
    "team.experience": ("enum", True, ["beginner", "intermediate", "senior", "mixed"], None),
    "team.languages": ("list", True, None, None),
    "team.has_devops": ("boolean", False, None, False),
    "budget.monthly_infra_usd": ("number", True, None, None),
    "timeline.mvp_weeks": ("integer", True, None, None),
    "infrastructure.cloud_preference": ("enum", False, ["any", "aws", "gcp", "azure", "none"], "any"),
    "infrastructure.deployment_model": ("enum", False,
                                        ["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"],
                                        "managed_cloud"),
    "infrastructure.data_residency": ("enum", False, ["none", "india", "eu", "us", "other"], "none"),
    "infrastructure.existing_systems": ("list", False, None, []),
    "requirements.realtime": ("boolean", False, None, False),
    "requirements.offline_support": ("boolean", False, None, False),
    "requirements.full_text_search": ("boolean", False, None, False),
    "requirements.file_media_storage": ("boolean", False, None, False),
    "requirements.payments": ("boolean", False, None, False),
    "requirements.auth": ("enum", False,
                          ["none", "email_password", "social", "phone_otp", "enterprise_sso"], "none"),
    "requirements.multi_tenant": ("boolean", False, None, False),
    "requirements.ml_features": ("enum", False, ["none", "inference_api", "llm_rag", "training"], "none"),
    "requirements.seo_critical": ("boolean", False, None, False),
    "requirements.availability": ("enum", False, ["99", "99.9", "99.95", "99.99"], "99.9"),
    "requirements.p95_latency_ms": ("integer", False, None, None),
    "compliance": ("list", False, ["gdpr", "dpdp", "hipaa", "pci_dss", "rbi_localisation", "soc2", "iso27001"], []),
}
for _k in ["cost", "time_to_market", "scalability", "performance", "maintainability", "security"]:
    TABLE["priorities." + _k] = ("integer", False, None, 3)

EXTRAS = {
    "scale.geographic_spread": "global", "scale.peak_rps": 100, "team.willing_to_learn": False,
    "team.growth_12_months": 5, "infrastructure.existing_licences": ["oracle", "aws_credits"],
    "infrastructure.lock_in_tolerance": "low", "infrastructure.open_source_only": True,
    "requirements.notifications": ["email", "push", "sms"], "requirements.background_jobs": True,
    "requirements.consistency": "strong", "requirements.data_shape": "relational", "requirements.cms": "headless",
}


class SchemaTests(unittest.TestCase):
    def test_sch01_standard_fields_match_statement_table(self):
        std = {p: s for p, s in schema.FIELDS.items() if not s["extra"]}
        self.assertEqual(sorted(std), sorted(TABLE))
        for path, (typ, req, allowed, default) in TABLE.items():
            s = std[path]
            self.assertEqual(s["type"], typ, path)
            self.assertEqual(s["required"], req, path)
            self.assertEqual(s["default"], default, path)
            got = s["enum"] if s["enum"] is not None else s["item_enum"]
            self.assertEqual(got, allowed, path)
        self.assertTrue(schema.FIELDS["requirements.p95_latency_ms"]["nullable"])

    def test_extras_count_and_shape(self):
        extras = sorted(p for p, s in schema.FIELDS.items() if s["extra"])
        self.assertEqual(len(extras), 12)
        self.assertEqual(extras, sorted(EXTRAS))
        self.assertNotIn("none", schema.FIELDS["requirements.notifications"]["item_enum"])
        self.assertIn("none", schema.FIELDS["infrastructure.existing_licences"]["item_enum"])
        self.assertNotIn("options", schema.TOP_LEVEL_ALLOWED)

    def test_spec_keys(self):
        for p, s in schema.FIELDS.items():
            self.assertIn(s["constraint"], ("hard", "soft", "info"), p)
            self.assertIsInstance(s["step"], int, p)
            self.assertIn("unit", s)
        hard = sorted(p for p, s in schema.FIELDS.items() if s["constraint"] == "hard")
        self.assertEqual(hard, ["compliance", "infrastructure.cloud_preference",
                                "infrastructure.data_residency", "infrastructure.deployment_model"])

    def test_sch02_public_scenarios_and_all_extras(self):
        files = sorted(glob.glob(str(ROOT / "scenarios" / "public" / "P*.json")))
        self.assertEqual(len(files), 6)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                self.assertEqual(validate(json.load(fh)).errors, [], f)
        with open(files[0], encoding="utf-8") as fh:
            raw = json.load(fh)
        for path, val in EXTRAS.items():
            sec, key = path.split(".")
            raw.setdefault(sec, {})[key] = val
        v = validate(raw)
        self.assertEqual(v.errors, [])
        for path in EXTRAS:
            self.assertIn(path, v.provided)

    def test_sch03_documentation_fields(self):
        for p, s in schema.FIELDS.items():
            self.assertTrue(s["why"].strip(), p)
            self.assertTrue(s["affects"] or p == "project.name", p)
            if s["extra"]:
                self.assertTrue(s["sources"], p)

    def test_all_source_keys_exist(self):
        for p, s in schema.FIELDS.items():
            for k in s["sources"]:
                self.assertIn(k, SOURCES, f"{p}: {k}")

    def test_ui_schema(self):
        ui = schema.schema_for_ui()
        n = sum(len(g["fields"]) for g in ui["groups"])
        self.assertEqual(n, len(schema.FIELDS))


if __name__ == "__main__":
    unittest.main()

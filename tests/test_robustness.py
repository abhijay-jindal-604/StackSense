"""Robustness, integrity and locality suites of plan section 9 not covered elsewhere.

T-FUZZ-01 (seeded mutations never crash), T-HARD-01 (seeded random valid scenarios: zero hard-constraint
violations), T-DET-02 (PYTHONHASHSEED independence), T-INT-01 (no scenario names in the engine),
T-PERT-01/02 (locality and no-op perturbations), T-MONO-03 (a compliance regime never enlarges a candidate
set), T-PERF-01, T-PORT-01 (explicit encodings), T-DOC-01 (README items).
"""
from __future__ import annotations

import ast
import copy
import json
import os
import random
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

from stacksense import diff, engine, filters, output, schema
from tests.helpers import hard_violations, profile_of

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "stacksense"
PUBLIC = ROOT / "scenarios" / "public"
PIDS = ("P1", "P2", "P3", "P4", "P5", "P6")
STATUSES = {"ok", "ok_with_warnings", "infeasible", "invalid_input"}
CORE = ("frontend", "backend", "database", "hosting")


def load(sid: str) -> dict:
    return json.loads((PUBLIC / f"{sid}.json").read_text(encoding="utf-8"))


BASES = {sid: load(sid) for sid in PIDS}


def setp(doc: dict, path: str, value) -> dict:
    node = doc
    parts = path.split(".")
    for k in parts[:-1]:
        node = node.setdefault(k, {})
    node[parts[-1]] = value
    return doc


def getp(doc: dict, path: str):
    node = doc
    for k in path.split("."):
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


# ------------------------------------------------------------------ T-FUZZ-01
_JUNK = (None, True, -1, 0, 10 ** 12, 3.7, "", "zzz", [], {}, [None], {"a": {"b": {"c": {}}}}, "x" * 300)


def _paths(doc, prefix=""):
    if isinstance(doc, dict):
        for k in sorted(doc):
            p = f"{prefix}.{k}" if prefix else k
            yield p
            yield from _paths(doc[k], p)


def _mutate(rng: random.Random, doc: dict) -> dict:
    doc = copy.deepcopy(doc)
    paths = list(_paths(doc))
    for _ in range(rng.randint(1, 3)):
        path = rng.choice(paths)
        parts = path.split(".")
        parent = doc
        for k in parts[:-1]:
            parent = parent.get(k) if isinstance(parent, dict) else None
        if not isinstance(parent, dict):
            continue
        op = rng.randrange(5)
        if op == 0:
            parent.pop(parts[-1], None)
        elif op == 1:
            parent[parts[-1]] = rng.choice(_JUNK)
        elif op == 2:
            parent[parts[-1]] = rng.choice((10 ** 9, -10 ** 9, 1e308, 0))
        elif op == 3:
            parent[parts[-1]] = rng.choice(("other", "none", "GLOBAL", "aws ", "managed-cloud", "india"))
        else:
            parent[parts[-1]] = {"nested": [parent.get(parts[-1])]}
    return doc


class FuzzTests(unittest.TestCase):
    def test_t_fuzz_01_mutations_never_crash(self):
        rng = random.Random(26)
        for i in range(400):
            raw = _mutate(rng, BASES[rng.choice(PIDS)])
            out = engine.recommend(raw, trace=False)
            self.assertIn(out["status"], STATUSES, i)
            self.assertFalse(engine.is_internal_error(out), (i, out.get("warnings")))
            self.assertEqual(output.check(out), [], i)


# ------------------------------------------------------------------ T-HARD-01
def _random_valid(rng: random.Random) -> dict:
    raw = copy.deepcopy(BASES[rng.choice(PIDS)])
    setp(raw, "infrastructure.data_residency", rng.choice(schema.RESIDENCY))
    setp(raw, "infrastructure.deployment_model", rng.choice(schema.DEPLOYMENT))
    setp(raw, "infrastructure.cloud_preference", rng.choice(schema.CLOUDS))
    regimes = [c for c in schema.COMPLIANCE if c != "none"]
    setp(raw, "compliance", sorted(rng.sample(regimes, rng.randint(0, 2))))
    users = rng.choice((200, 5_000, 50_000, 400_000, 3_000_000))
    setp(raw, "scale.users_12_months", users)
    setp(raw, "scale.users_at_launch", max(1, users // rng.choice((2, 10, 50))))
    setp(raw, "scale.peak_concurrent_users", max(1, users // rng.choice((10, 50, 200))))
    setp(raw, "budget.monthly_infra_usd", rng.choice((0, 20, 150, 1_500, 20_000)))
    return raw


class HardConstraintSweep(unittest.TestCase):
    def test_t_hard_01_random_valid_scenarios(self):
        rng = random.Random(2026)
        seen = 0
        for i in range(60):
            raw = _random_valid(rng)
            out = engine.recommend(copy.deepcopy(raw), trace=False)
            if out["status"] == "invalid_input":
                continue
            seen += 1
            self.assertEqual(hard_violations(raw, out), [], (i, raw.get("infrastructure"), raw.get("compliance")))
        self.assertGreater(seen, 40)


# ------------------------------------------------------------------ T-DET-02
class HashSeedTests(unittest.TestCase):
    def test_t_det_02_hash_seed_independent(self):
        code = ("import json,sys; from pathlib import Path; from stacksense import engine, output\n"
                "for s in ('P1','P2','P3','P4','P5','P6'):\n"
                "    raw=json.loads(Path('scenarios/public/%s.json'%s).read_text(encoding='utf-8'))\n"
                "    sys.stdout.write(output.dumps(engine.recommend(raw)))\n")
        outs = set()
        for seed in ("0", "1", "42", "random"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            outs.add(r.stdout)
        self.assertEqual(len(outs), 1)


# ------------------------------------------------------------------ T-INT-01
_NAMES = ("DevFolio", "FixIt", "BoardRoom", "QuickCredit", "PeopleDesk", "KhetSurvey")


class IntegrityTests(unittest.TestCase):
    def test_t_int_01_no_scenario_names_or_ids_in_engine(self):
        bad = []
        for f in sorted(PKG.rglob("*.py")):
            text = f.read_text(encoding="utf-8")
            for n in _NAMES:
                if n in text:
                    bad.append(f"{f.relative_to(ROOT)}: {n}")
            for m in re.finditer(r"""["']P[1-6]["']""", text):
                bad.append(f"{f.relative_to(ROOT)}: {m.group(0)}")
            for m in re.finditer(r"""["']H[0-3][0-9](_[A-Za-z0-9]+)?["']""", text):
                bad.append(f"{f.relative_to(ROOT)}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_scenario_id_read_only_by_io_and_output(self):
        users = []
        for f in sorted(PKG.rglob("*.py")):
            if f.name in ("io.py", "output.py", "cli.py", "server.py", "engine.py", "sensitivity.py", "diff.py",
                          "schema.py", "validate.py"):   # echo / validate the field only
                continue
            if "scenario_id" in f.read_text(encoding="utf-8"):
                users.append(str(f.relative_to(ROOT)))
        self.assertEqual(users, [])


# ------------------------------------------------------------------ T-PERT-01 / 02
# (base, field path, new value): single soft-field perturbations
PERTURBATIONS = (
    ("P1", "priorities.cost", 1), ("P1", "timeline.mvp_weeks", 12), ("P1", "team.size", 3),
    ("P1", "requirements.availability", "99.9"), ("P1", "scale.users_12_months", 20_000),
    ("P2", "priorities.performance", 4), ("P2", "timeline.mvp_weeks", 20), ("P2", "team.experience", "senior"),
    ("P2", "requirements.full_text_search", False), ("P2", "scale.data_volume_gb_12_months", 80),
    ("P3", "priorities.time_to_market", 2), ("P3", "team.size", 8), ("P3", "requirements.file_media_storage", False),
    ("P3", "budget.monthly_infra_usd", 3_000), ("P3", "scale.traffic_pattern", "steady"),
    ("P4", "priorities.scalability", 3), ("P4", "team.size", 15), ("P4", "timeline.mvp_weeks", 30),
    ("P4", "budget.monthly_infra_usd", 8_000), ("P4", "scale.users_12_months", 600_000),
    ("P5", "priorities.cost", 5), ("P5", "team.experience", "intermediate"), ("P5", "timeline.mvp_weeks", 16),
    ("P5", "requirements.availability", "99.95"), ("P5", "scale.users_at_launch", 800),
    ("P6", "priorities.time_to_market", 3), ("P6", "team.size", 4), ("P6", "budget.monthly_infra_usd", 150),
    ("P6", "requirements.offline_support", True), ("P6", "scale.data_volume_gb_12_months", 60),
)


def _affects(path: str) -> set:
    f = schema.FIELDS.get(path) or {}
    return set(f.get("affects") or [])


class PerturbationTests(unittest.TestCase):
    def test_t_pert_01_changed_core_layers_are_declared(self):
        problems = []
        for sid, path, value in PERTURBATIONS:
            base = BASES[sid]
            if getp(base, path) == value:
                continue
            var = setp(copy.deepcopy(base), path, value)
            a = engine.recommend(copy.deepcopy(base), trace=False)
            b = engine.recommend(var, trace=False)
            if b["status"] == "invalid_input":
                problems.append(f"{sid} {path}={value}: invalid_input")
                continue
            d = diff.diff(a, b)
            changed = {k for k in d["changed_layers"] if k in CORE}
            undeclared = changed - _affects(path)
            if undeclared:
                problems.append(f"{sid} {path}={value}: changed {sorted(undeclared)} not in affects "
                                f"{sorted(_affects(path))}")
        self.assertEqual(problems, [])

    def test_t_pert_02_noop_perturbations_change_nothing(self):
        for sid in PIDS:
            base = BASES[sid]
            a = engine.recommend(copy.deepcopy(base), trace=False)
            var = copy.deepcopy(base)
            var["scenario_id"] = "renamed-" + str(base.get("scenario_id", sid))
            if isinstance(var.get("project"), dict):
                var["project"]["name"] = "Totally Different Name"
            for path in ("project.platforms", "team.languages", "compliance"):
                v = getp(var, path)
                if isinstance(v, list):
                    setp(var, path, list(reversed(v)))
            b = engine.recommend(var, trace=False)
            d = diff.diff(a, b)
            self.assertEqual(d["changed_layers"], [], sid)
            self.assertFalse(d["status"]["changed"] or d["cost"]["changed"], sid)
            self.assertEqual(d["warnings"], {"added": [], "removed": []}, sid)


# ------------------------------------------------------------------ T-MONO-03
class ComplianceNeverEnlarges(unittest.TestCase):
    def test_t_mono_03(self):
        layers = ("backend", "database", "hosting", "auth", "storage", "observability", "payments")
        for sid in PIDS:
            base = BASES[sid]
            p0 = profile_of(base)
            for regime in [c for c in schema.COMPLIANCE if c != "none"]:
                if regime in (base.get("compliance") or []):
                    continue
                var = copy.deepcopy(base)
                var["compliance"] = sorted(set(var.get("compliance") or []) | {regime})
                p1 = profile_of(var)
                for layer in layers:
                    k0 = {r["id"] for r in filters.filter_layer(layer, p0)[0]}
                    k1 = {r["id"] for r in filters.filter_layer(layer, p1)[0]}
                    self.assertTrue(k1 <= k0, f"{sid}+{regime} {layer}: {sorted(k1 - k0)}")


# ------------------------------------------------------------------ T-PERF-01
class PerformanceTests(unittest.TestCase):
    def test_t_perf_01_public_under_one_second_each(self):
        for sid in PIDS:
            t = time.perf_counter()
            engine.recommend(copy.deepcopy(BASES[sid]))
            self.assertLess(time.perf_counter() - t, 1.0, sid)


# ------------------------------------------------------------------ T-PORT-01
class PortabilityTests(unittest.TestCase):
    def test_t_port_01_text_opens_name_an_encoding(self):
        bad = []
        for f in sorted(list(PKG.rglob("*.py")) + list((ROOT / "tools").glob("*.py"))):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                kws = {k.arg for k in node.keywords}
                if name in ("read_text", "write_text") and "encoding" not in kws:
                    bad.append(f"{f.relative_to(ROOT)}:{node.lineno} {name}")
                if name == "open" and isinstance(fn, ast.Name) and "encoding" not in kws:
                    mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                    if "b" not in str(mode):
                        bad.append(f"{f.relative_to(ROOT)}:{node.lineno} open")
        self.assertEqual(bad, [])


# ------------------------------------------------------------------ T-DOC-01
class ReadmeTests(unittest.TestCase):
    def test_t_doc_01_readme_covers_the_nine_items(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        heads = [h.lower() for h in re.findall(r"^#+ (.+)$", text, flags=re.M)]
        joined = "\n".join(heads)
        self.assertTrue(heads and heads[0].startswith("stacksense"))
        for needle in ("architecture", "technology", "prerequisites", "setup", "scenario", "llm",
                       "structure", "credits"):
            self.assertIn(needle, joined, needle)


if __name__ == "__main__":
    unittest.main()

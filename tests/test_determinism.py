"""Determinism (T-DET-01, T-DET-03, T-DET-04)."""
from __future__ import annotations

import ast
import json
import random
import re
import unittest
from pathlib import Path

from stacksense import engine, output

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"
PACKAGE = ROOT / "stacksense"
SIDS = ("P1", "P2", "P3", "P4", "P5", "P6")
SHUFFLE_LISTS = ("compliance", "platforms", "languages")


def load(sid: str) -> dict:
    return json.loads((PUBLIC / f"{sid}.json").read_text(encoding="utf-8"))


def shuffled(obj, rng: random.Random):
    """Same document with dict key order shuffled at every level (list order kept)."""
    if isinstance(obj, dict):
        keys = list(obj)
        rng.shuffle(keys)
        return {k: shuffled(obj[k], rng) for k in keys}
    if isinstance(obj, list):
        return [shuffled(x, rng) for x in obj]
    return obj


def shuffle_lists(obj, rng: random.Random):
    """Shuffle the order-free input lists (compliance, platforms, languages)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            v = shuffle_lists(v, rng)
            if k in SHUFFLE_LISTS and isinstance(v, list):
                v = list(v)
                rng.shuffle(v)
            out[k] = v
        return out
    return obj


def core_choices(r: dict) -> list:
    return [r["stack"][l]["choice"] for l in ("frontend", "backend", "database", "hosting")] + \
        [s["choice"] for s in r["stack"]["supporting"]]


class DeterminismTests(unittest.TestCase):
    def test_same_input_twice_identical_bytes(self):            # T-DET-01
        for sid in SIDS:
            raw = load(sid)
            self.assertEqual(output.dumps(engine.recommend(raw)), output.dumps(engine.recommend(load(sid))), sid)

    def test_key_order_shuffled_identical_bytes(self):          # T-DET-03 (keys)
        rng = random.Random(26)
        for sid in SIDS:
            base = output.dumps(engine.recommend(load(sid)))
            for _ in range(3):
                self.assertEqual(output.dumps(engine.recommend(shuffled(load(sid), rng))), base, sid)

    def test_list_order_shuffled_same_stack_and_warnings(self):  # T-DET-03 (lists)
        rng = random.Random(26)
        for sid in SIDS:
            base = engine.recommend(load(sid))
            for _ in range(3):
                r = engine.recommend(shuffle_lists(load(sid), rng))
                self.assertEqual(r["status"], base["status"], sid)
                self.assertEqual(core_choices(r), core_choices(base), sid)
                self.assertEqual(sorted((w["code"], w["severity"]) for w in r["warnings"]),
                                 sorted((w["code"], w["severity"]) for w in base["warnings"]), sid)
                self.assertEqual(r["estimated_monthly_cost_usd"], base["estimated_monthly_cost_usd"], sid)

    def test_no_trace_variant_is_deterministic(self):
        for sid in SIDS:
            a = engine.recommend(load(sid), trace=False)
            self.assertNotIn("decision_trace", a)
            self.assertEqual(output.dumps(a), output.dumps(engine.recommend(load(sid), trace=False)))


class SourceTreeTests(unittest.TestCase):                       # T-DET-04
    FORBIDDEN = (r"\bdatetime\.now\b", r"\bdatetime\.utcnow\b", r"\bdate\.today\b", r"\btime\.time\b",
                 r"\btime\.monotonic\b", r"\btime\.perf_counter\b", r"\bimport\s+random\b", r"\bfrom\s+random\b",
                 r"\brandom\.", r"\buuid\b", r"\bos\.urandom\b", r"\bsecrets\.")

    def files(self):
        return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)

    def test_no_clock_or_randomness(self):
        bad = []
        for path in self.files():
            text = path.read_text(encoding="utf-8")
            for pat in self.FORBIDDEN:
                for m in re.finditer(pat, text):
                    line = text.count("\n", 0, m.start()) + 1
                    bad.append(f"{path.relative_to(ROOT)}:{line}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_no_iteration_over_set_literals_or_calls(self):
        """``for x in set(...)`` / ``for x in {...}`` without sorted() is hash-order dependent."""
        bad = []
        for path in self.files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                iters = []
                if isinstance(node, (ast.For, ast.comprehension)):
                    iters.append(node.iter)
                for it in iters:
                    if isinstance(it, (ast.Set, ast.SetComp)) or (
                            isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                            and it.func.id in ("set", "frozenset")):
                        bad.append(f"{path.relative_to(ROOT)}:{it.lineno}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

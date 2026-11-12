import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "scenarios" / "public"


def cli(*args):
    return subprocess.run([sys.executable, "-m", "stacksense", *args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8")


class CliTests(unittest.TestCase):
    def test_run_file(self):
        with tempfile.TemporaryDirectory() as d:
            r = cli("run", str(PUBLIC / "P1.json"), "-o", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")
            self.assertTrue((Path(d) / "P1_output.json").is_file())
            self.assertTrue(r.stdout.isascii())

    def test_run_dir_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            r = cli("run", str(PUBLIC), "-o", d, "--quiet")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")
            names = {p.name for p in Path(d).iterdir()}
            for i in range(1, 7):
                self.assertIn(f"P{i}_output.json", names)

    def test_run_array_file(self):
        with tempfile.TemporaryDirectory() as d:
            r = cli("run", str(PUBLIC.parent / "stacksense_public_scenarios.json"), "-o", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")
            self.assertEqual(len(r.stdout.strip().splitlines()), 6)

    def test_invalid_input_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"project": 5}', encoding="utf-8")
            r = cli("run", str(bad), "-o", str(Path(d) / "out"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("invalid_input", r.stdout)
            res = json.loads((Path(d) / "out" / "bad_output.json").read_text(encoding="utf-8"))
            self.assertEqual(res["status"], "invalid_input")

    def test_validate_exit_codes(self):
        r = cli("validate", str(PUBLIC / "P1.json"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("valid", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"project": 5}', encoding="utf-8")
            r = cli("validate", str(bad))
            self.assertEqual(r.returncode, 1)
            self.assertIn("invalid", r.stdout)

    def test_fill_defaults(self):
        raw = json.loads((PUBLIC / "P1.json").read_text(encoding="utf-8"))
        del raw["timeline"]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.json"
            f.write_text(json.dumps(raw), encoding="utf-8")
            r = cli("run", str(f), "-o", d + "/a")
            self.assertEqual(r.returncode, 0, r.stderr)
            strict = json.loads(next((Path(d) / "a").iterdir()).read_text(encoding="utf-8"))
            r = cli("run", str(f), "-o", d + "/b", "--fill-defaults")
            self.assertEqual(r.returncode, 0, r.stderr)
            filled = json.loads(next((Path(d) / "b").iterdir()).read_text(encoding="utf-8"))
            self.assertEqual(strict["status"], "invalid_input")
            self.assertNotEqual(filled["status"], "invalid_input")
            self.assertTrue(filled["assumptions"])

    def test_selftest(self):
        r = cli("selftest")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.isascii())

    def test_later_subcommands(self):
        r = cli("serve")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not available yet", r.stderr)
        self.assertIn("wizard", cli("--help").stdout)


if __name__ == "__main__":
    unittest.main()

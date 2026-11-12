import json
import tempfile
import unittest
from pathlib import Path

from stacksense import output
from stacksense.io import MAX_BYTES, load_scenarios, output_name, write_output


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def w(self, name, data, mode="w"):
        p = self.dir / name
        if mode == "wb":
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")
        return p

    def test_object(self):
        r = load_scenarios(self.w("a.json", '{"scenario_id": "A"}'))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].source_name, "a.json")
        self.assertEqual(r[0].raw, {"scenario_id": "A"})
        self.assertIsNone(r[0].load_error)
        self.assertEqual(r[0].notices, [])

    def test_array(self):
        r = load_scenarios(self.w("arr.json", '[{"a":1}, 5, {"a":2}]'))
        self.assertEqual([x.source_name for x in r], ["arr.json[0]", "arr.json[1]", "arr.json[2]"])
        self.assertIsNone(r[0].load_error)
        self.assertIn("Element 1", r[1].load_error)
        self.assertIsNone(r[1].raw)
        self.assertEqual(r[2].raw, {"a": 2})

    def test_directory_sorted_and_non_json_ignored(self):
        self.w("b.json", "{}")
        self.w("a.json", "[{}, {}]")
        self.w("notes.txt", "hello")
        r = load_scenarios(self.dir)
        self.assertEqual([x.source_name for x in r], ["a.json[0]", "a.json[1]", "b.json"])

    def test_bom(self):
        r = load_scenarios(self.w("bom.json", b"\xef\xbb\xbf" + b'{"x": 1}', "wb"))
        self.assertIsNone(r[0].load_error)
        self.assertEqual(r[0].raw, {"x": 1})

    def test_invalid_json_has_line_column(self):
        r = load_scenarios(self.w("bad.json", '{\n  "a": 1,\n  "b": }\n'))
        self.assertIsNone(r[0].raw)
        self.assertIn("line 3", r[0].load_error)
        self.assertIn("column", r[0].load_error)

    def test_empty_and_whitespace_file(self):
        for n, c in (("e1.json", ""), ("e2.json", "  \n")):
            r = load_scenarios(self.w(n, c))
            self.assertIn("empty", r[0].load_error.lower())
        r = load_scenarios(self.w("e3.json", "[]"))
        self.assertIsNotNone(r[0].load_error)

    def test_duplicate_keys_last_wins_with_notice(self):
        r = load_scenarios(self.w("d.json", '{"a": 1, "a": 2, "b": {"c": 1, "c": 3}}'))
        self.assertIsNone(r[0].load_error)
        self.assertEqual(r[0].raw, {"a": 2, "b": {"c": 3}})
        self.assertEqual([n["code"] for n in r[0].notices], ["DUPLICATE_KEY", "DUPLICATE_KEY"])
        self.assertTrue(all(n["severity"] == "info" and n["fields"] == [] for n in r[0].notices))

    def test_oversize_refused(self):
        pad = " " * (MAX_BYTES + 1)
        r = load_scenarios(self.w("big.json", "{}" + pad))
        self.assertIsNone(r[0].raw)
        self.assertIn("5 MB", r[0].load_error)

    def test_nan_literals_rejected(self):
        for lit in ("NaN", "Infinity", "-Infinity"):
            r = load_scenarios(self.w("n.json", '{"a": %s}' % lit))
            self.assertIsNone(r[0].raw, lit)
            self.assertIn("not allowed", r[0].load_error)

    def test_misc_never_raises(self):
        self.assertIn("does not exist", load_scenarios(self.dir / "nope.json")[0].load_error)
        self.assertIn("UTF-8", load_scenarios(self.w("l1.json", b"\xff\xfe{}", "wb"))[0].load_error)
        self.assertIn("expected an object", load_scenarios(self.w("s.json", '"hi"'))[0].load_error)
        self.assertIsNotNone(load_scenarios(self.w("deep.json", "[" * 100000))[0].load_error)
        self.assertEqual(load_scenarios(self.dir / "emptydir_missing"), load_scenarios(self.dir / "emptydir_missing"))

    def test_public_scenarios(self):
        pub = Path(__file__).resolve().parent.parent / "scenarios" / "public"
        if not pub.is_dir():
            self.skipTest("no public scenarios")
        r = load_scenarios(pub)
        self.assertEqual(len(r), 12)
        self.assertTrue(all(x.load_error is None for x in r))


class NameWriteTests(unittest.TestCase):
    def test_output_name(self):
        self.assertEqual(output_name("P1", "x.json", None), "P1_output.json")
        self.assertEqual(output_name("../a b/c", "x.json", 0), "_a_b_c_output.json")
        self.assertEqual(output_name(None, "my.json", None), "my_output.json")
        self.assertEqual(output_name(None, "arr.json[3]", 3), "arr_3_output.json")
        self.assertEqual(output_name("", "weird name!.json", 1), "weird_name__1_output.json")
        self.assertEqual(output_name(None, "", None), "scenario_output.json")
        self.assertEqual(output_name(None, "..json", None), "scenario_output.json")

    def test_write_output_roundtrip(self):
        res = output.invalid_input_result("Z9", [{"field": "$", "message": "Bad ünï"}])
        with tempfile.TemporaryDirectory() as td:
            p = write_output(res, Path(td) / "sub", "Z9_output.json")
            self.assertEqual(p.name, "Z9_output.json")
            text = p.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertIn("ünï", text)
            self.assertEqual(json.loads(text), res)
            self.assertEqual(output.check(json.loads(text)), [])


if __name__ == "__main__":
    unittest.main()

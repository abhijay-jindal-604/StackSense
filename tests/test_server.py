"""HTTP server tests (plan 10.3): endpoints, error paths, byte-identity with the engine."""
from __future__ import annotations

import http.client
import json
import socket
import threading
import unittest
from pathlib import Path

from stacksense import engine, output, server
from stacksense.io import MAX_BYTES

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = sorted((ROOT / "scenarios" / "public").glob("P*.json"))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.make_server("127.0.0.1", 0, quiet=True)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(5)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
            conn.request(method, path, body=data, headers=headers or {})
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def get_json(self, path):
        st, _, b = self.req("GET", path)
        return st, json.loads(b)

    def post_json(self, path, body):
        st, h, b = self.req("POST", path, body)
        return st, h, b

    # ---------------------------------------------------------------- API
    def test_bound_to_loopback(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_health(self):
        st, d = self.get_json("/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        self.assertNotIn("llm", d)
        self.assertTrue(d["engine_version"] and d["kb_version"])

    def test_no_cors_header(self):
        _, h, _ = self.req("GET", "/api/health")
        self.assertFalse([k for k in h if k.lower().startswith("access-control")])

    def test_schema(self):
        st, d = self.get_json("/api/schema")
        self.assertEqual(st, 200)
        self.assertTrue(d["groups"])

    def test_scenarios_list_and_get(self):
        st, rows = self.get_json("/api/scenarios")
        self.assertEqual(st, 200)
        ids = [r["id"] for r in rows]
        for i in range(1, 7):
            self.assertIn(f"P{i}", ids)
        self.assertTrue(any(r["category"] == "edge" for r in rows))
        self.assertTrue(all(set(r) == {"id", "title", "category", "file"} for r in rows))
        st, sc = self.get_json("/api/scenarios/P2")
        self.assertEqual(st, 200)
        self.assertEqual(sc, json.loads((ROOT / "scenarios" / "public" / "P2.json").read_text()))
        self.assertEqual(self.get_json("/api/scenarios/NOPE")[0], 404)
        self.assertEqual(self.get_json("/api/scenarios/..%2F..%2Fetc%2Fpasswd")[0], 404)

    def test_validate(self):
        sc = json.loads(PUBLIC[0].read_text())
        st, _, b = self.post_json("/api/validate", {"scenario": sc})
        d = json.loads(b)
        self.assertEqual(st, 200)
        self.assertEqual(d["errors"], [])
        self.assertIn("notices", d)
        self.assertIn("assumptions", d)
        st, _, b = self.post_json("/api/validate", {"scenario": {}, "fill_defaults": False})
        self.assertTrue(json.loads(b)["errors"])
        st, _, b = self.post_json("/api/validate", {"scenario": {}, "fill_defaults": "yes"})
        self.assertEqual(st, 400)

    def test_recommend_matches_engine_for_public(self):
        self.assertEqual(len(PUBLIC), 6)
        for f in PUBLIC:
            raw = json.loads(f.read_text())
            st, h, b = self.post_json("/api/recommend", {"scenario": raw})
            self.assertEqual(st, 200, f.name)
            self.assertIn("application/json", h["Content-Type"])
            self.assertEqual(b.decode("utf-8"), output.dumps(engine.recommend(raw)), f.name)

    def test_recommend_fill_defaults_and_ignores_unknown_keys(self):
        raw = json.loads(PUBLIC[0].read_text())
        st, _, b = self.post_json("/api/recommend", {"scenario": raw, "fill_defaults": True, "llm": True, "bogus": 1})
        self.assertEqual(st, 200)
        self.assertEqual(b.decode(), output.dumps(engine.recommend(raw, fill_defaults=True)))

    def test_recommend_invalid_scenario_is_200_invalid_input(self):
        st, _, b = self.post_json("/api/recommend", {"scenario": {}})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(b)["status"], "invalid_input")

    def test_recommend_repeatable(self):
        raw = json.loads(PUBLIC[1].read_text())
        a = self.post_json("/api/recommend", {"scenario": raw})[2]
        b = self.post_json("/api/recommend", {"scenario": raw})[2]
        self.assertEqual(a, b)

    def test_kb_endpoints(self):
        st, d = self.get_json("/api/kb")
        self.assertEqual(st, 200)
        self.assertTrue(d["records"] and d["stats"]["records"] == len(d["records"]))
        rid = d["records"][0]["id"]
        st, rec = self.get_json(f"/api/kb/{rid}")
        self.assertEqual((st, rec["id"]), (200, rid))
        self.assertEqual(self.get_json("/api/kb/does-not-exist")[0], 404)
        st, src = self.get_json("/api/sources")
        self.assertEqual(st, 200)
        self.assertTrue(src and set(src[0]) == {"key", "title", "url", "accessed"})

    def test_warnings_sensitivity_diff_and_no_llm_route(self):
        st, rows = self.get_json("/api/warnings")
        self.assertEqual(st, 200)
        self.assertIn("RESIDENCY_UNVERIFIABLE", {r["code"] for r in rows})
        st, sens = self.get_json("/api/sensitivity?base=P1")
        self.assertEqual(st, 200)
        self.assertEqual(sens["scenario_id"], "P1")
        self.assertTrue(sens["rows"] and "| Extra field |" in sens["markdown"])
        self.assertEqual(self.get_json("/api/sensitivity?base=nope")[0], 404)
        self.assertEqual(self.get_json("/api/sensitivity")[0], 400)
        p1 = json.loads((ROOT / "scenarios" / "public" / "P1.json").read_text(encoding="utf-8"))
        p1b = json.loads(json.dumps(p1))
        p1b.setdefault("requirements", {})["cms"] = "headless"
        st, _, body = self.post_json("/api/diff", {"a": p1, "b": p1b})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual(d["changed_fields"], ["requirements.cms"])
        self.assertIn("layers", d)
        self.assertEqual(self.post_json("/api/diff", {"a": p1})[0], 400)
        self.assertEqual(self.post_json("/api/diff", {"a": [], "b": {}})[0], 400)
        st, _, b = self.post_json("/api/llm/suggest", {"description": "x"})
        self.assertEqual(st, 404)
        self.assertIn("error", json.loads(b))

    # ---------------------------------------------------------------- errors
    def test_bad_json(self):
        for body in (b"{not json", b"", b"[1,2]", b"\xff\xfe", b'{"scenario": NaN}'):
            st, _, b = self.post_json("/api/recommend", body)
            self.assertEqual(st, 400, body)
            self.assertIn("error", json.loads(b))

    def test_missing_scenario_key(self):
        st, _, b = self.post_json("/api/recommend", {"fill_defaults": True})
        self.assertEqual(st, 400)

    def test_oversize_body(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            s.sendall(f"POST /api/recommend HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                      f"Content-Length: {MAX_BYTES + 1}\r\n\r\n".encode())
            data = b""
            while b'"error"' not in data:  # headers and body may arrive in separate segments
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            s.close()
        self.assertTrue(data.startswith(b"HTTP/1.1 413"), data[:60])
        self.assertIn(b'"error"', data)

    def test_method_and_path_errors(self):
        self.assertEqual(self.req("GET", "/api/nope")[0], 404)
        self.assertEqual(self.req("GET", "/api/recommend")[0], 405)
        self.assertEqual(self.req("POST", "/api/health", b"{}")[0], 405)
        self.assertEqual(self.req("POST", "/index.html", b"{}")[0], 405)
        st, _, b = self.req("GET", "/api/nope")
        self.assertIn("error", json.loads(b))

    # ---------------------------------------------------------------- static
    def test_static_traversal_and_unknown(self):
        for p in ("/../", "/../server.py", "/%2e%2e/server.py", "/..%2fserver.py", "/a/../../server.py",
                  "/%2e%2e%2f%2e%2e%2fCLAUDE.md", "/..\\server.py", "/%00.html"):
            st, _, b = self.req("GET", p)
            self.assertIn(st, (400, 404), p)
            self.assertNotIn(b"ThreadingHTTPServer", b, p)
        self.assertEqual(self.req("GET", "/missing.html")[0], 404)
        self.assertEqual(self.req("GET", "/server.py")[0], 404)  # extension not allow-listed

    def test_static_content_types(self):
        web = Path(server._WEB)
        web.mkdir(exist_ok=True)
        files = {"zz_test.html": "text/html", "zz_test.css": "text/css", "zz_test.js": "text/javascript",
                 "zz_test.svg": "image/svg+xml"}
        try:
            for n in files:
                (web / n).write_text("x", encoding="utf-8")
            for n, ct in files.items():
                st, h, b = self.req("GET", "/" + n)
                self.assertEqual(st, 200, n)
                self.assertTrue(h["Content-Type"].startswith(ct), n)
                self.assertEqual(b, b"x")
            st, h, b = self.req("HEAD", "/zz_test.css")
            self.assertEqual((st, b), (200, b""))
        finally:
            for n in files:
                (web / n).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

"""Local HTTP server: JSON API (plan 10.3) plus static UI from ``web/`` (plan 3.19).

Standard library only. No cookies, no CORS headers, no clock or randomness in responses.
"""
from __future__ import annotations

import json
import mimetypes
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__, engine, kb, output, schema
from .io import MAX_BYTES, _parse_text
from .validate import validate

_ROOT = Path(__file__).resolve().parent
_WEB = _ROOT / "web"
_SCENARIO_DIRS = (("public", _ROOT.parent / "scenarios" / "public"), ("edge", _ROOT.parent / "scenarios" / "edge"))
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8",
    ".map": "application/json",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _scenario_index() -> dict:
    """id -> {id, title, category, file, path}; ids are scenario_id (file stem if absent), first one wins."""
    out: dict = {}
    for category, d in _SCENARIO_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            sid = data.get("scenario_id")
            sid = sid if isinstance(sid, str) and sid.strip() else f.stem
            proj = data.get("project")
            title = proj.get("name") if isinstance(proj, dict) and isinstance(proj.get("name"), str) else f.stem
            out.setdefault(sid, {"id": sid, "title": title, "category": category, "file": f.name, "path": f})
    return out


def _all_records() -> dict:
    return {r["id"]: r for r in list(kb.RECORDS) + list(kb.OFFERINGS)}


def _read_body(handler) -> bytes:
    raw_len = handler.headers.get("Content-Length")
    if raw_len is None:
        raise ApiError(400, "Content-Length header is required for POST.")
    try:
        n = int(raw_len)
    except ValueError:
        raise ApiError(400, "Invalid Content-Length.") from None
    if n < 0:
        raise ApiError(400, "Invalid Content-Length.")
    if n > MAX_BYTES:
        raise ApiError(413, f"Request body is {n} bytes; the limit is {MAX_BYTES} bytes (5 MB).")
    return handler.rfile.read(n)


def _json_body(handler) -> dict:
    data = _read_body(handler)
    try:
        value, _ = _parse_text(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ApiError(400, "Body is not valid UTF-8.") from None
    except (ValueError, RecursionError) as e:
        raise ApiError(400, f"Invalid JSON: {e}") from None
    if not isinstance(value, dict):
        raise ApiError(400, "Body must be a JSON object.")
    return value


def _flag(body: dict, key: str) -> bool:
    v = body.get(key, False)
    if not isinstance(v, bool):
        raise ApiError(400, f"'{key}' must be true or false.")
    return v


def _need_scenario(body: dict, key: str = "scenario"):
    if key not in body:
        raise ApiError(400, f"Body must contain '{key}'.")
    return body[key]


class Handler(BaseHTTPRequestHandler):
    server_version = "StackSense"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # noqa: D401
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, ctype: str, head_only: bool = False, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json(self, status: int, obj, head_only: bool = False):
        text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        self._send(status, text.encode("utf-8"), "application/json; charset=utf-8", head_only)

    def _error(self, status: int, message: str):
        self.close_connection = True if status == 413 else self.close_connection
        self._json(status, {"error": message})

    def _dispatch(self, method: str):
        head = method == "HEAD"
        try:
            parts = urlsplit(self.path)
            path = parts.path
            if path.startswith("/api/") or path == "/api":
                self._api(method, path, parts.query, head)
            elif method in ("GET", "HEAD"):
                self._static(path, head)
            else:
                raise ApiError(405, "Method not allowed.")
        except ApiError as e:
            self._error(e.status, e.message)
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            try:
                self._error(500, "Internal server error.")
            except OSError:
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PATCH(self):
        self._dispatch("PATCH")

    # ------------------------------------------------------------ static
    def _static(self, path: str, head: bool):
        rel = unquote(path)
        if "\x00" in rel or "\\" in rel:
            raise ApiError(400, "Bad path.")
        segs = [s for s in rel.split("/") if s != ""]
        if any(s in (".", "..") for s in segs):
            raise ApiError(400, "Bad path.")
        if not segs:
            segs = ["index.html"]
        target = _WEB.joinpath(*segs)
        ctype = _STATIC_TYPES.get(target.suffix.lower())
        if ctype is None:
            raise ApiError(404, "Not found.")
        try:
            real = target.resolve(strict=True)
            real.relative_to(_WEB.resolve())
        except (OSError, ValueError):
            raise ApiError(404, "Not found.") from None
        if not real.is_file():
            raise ApiError(404, "Not found.")
        self._send(200, real.read_bytes(), ctype, head, cache="no-cache")

    # ------------------------------------------------------------ API
    def _api(self, method: str, path: str, query: str, head: bool):
        p = path.rstrip("/") or "/"
        segs = p.split("/")[2:]  # after '', 'api'
        route = segs[0] if segs else ""
        get_only = {"health", "schema", "scenarios", "kb", "sources", "warnings", "sensitivity"}
        post_only = {"validate", "recommend", "diff"}
        if route in get_only:
            if method not in ("GET", "HEAD"):
                raise ApiError(405, "Use GET for this endpoint.")
        elif route in post_only:
            if method != "POST":
                raise ApiError(405, "Use POST for this endpoint.")
        else:
            raise ApiError(404, "Unknown API path.")
        n = len(segs)

        if route == "health" and n == 1:
            return self._json(200, {"ok": True, "engine_version": __version__, "kb_version": kb.kb_version()}, head)
        if route == "schema" and n == 1:
            return self._json(200, schema.schema_for_ui(), head)
        if route == "scenarios" and n == 1:
            rows = [{k: v for k, v in e.items() if k != "path"} for e in _scenario_index().values()]
            rows.sort(key=lambda r: (r["category"] != "public", r["id"]))
            return self._json(200, rows, head)
        if route == "scenarios" and n == 2:
            entry = _scenario_index().get(unquote(segs[1]))
            if entry is None:
                raise ApiError(404, "Unknown scenario.")
            return self._json(200, json.loads(entry["path"].read_text(encoding="utf-8-sig")), head)
        if route == "kb" and n == 1:
            return self._json(200, {**kb.export(), "stats": kb.stats()}, head)
        if route == "kb" and n == 2:
            rec = _all_records().get(unquote(segs[1]))
            if rec is None:
                raise ApiError(404, "Unknown knowledge-base record.")
            return self._json(200, rec, head)
        if route == "sources" and n == 1:
            rows = [{"key": k, "title": v[0], "url": v[1], "accessed": v[2]} for k, v in sorted(kb.SOURCES.items())]
            return self._json(200, rows, head)
        if route == "warnings" and n == 1:
            from . import conflicts
            rows = [{"code": code, "severity": list(e.severity), "fields": list(e.fields), "template": e.template,
                     "effect": e.effect, "emitted_by": e.source,
                     "not_emitted": conflicts.NOT_EMITTED.get(code)}
                    for code, e in sorted(conflicts.CATALOGUE.items())]
            return self._json(200, rows, head)
        if route == "sensitivity" and n == 1:
            from . import sensitivity
            base = (parse_qs(query or "").get("base") or [""])[0]
            entry = _scenario_index().get(base)
            if entry is None:
                raise ApiError(404 if base else 400, "Query parameter 'base' must name a known scenario id.")
            raw = json.loads(entry["path"].read_text(encoding="utf-8-sig"))
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            res = sensitivity.run(raw)
            return self._json(200, {**res, "markdown": sensitivity.markdown(res)}, head)
        if route == "validate" and n == 1:
            body = _json_body(self)
            raw = _need_scenario(body)
            v = validate(raw, fill_defaults=_flag(body, "fill_defaults"))
            return self._json(200, {"errors": list(v.errors), "notices": list(v.notices),
                                    "assumptions": list(v.assumptions)})
        if route == "recommend" and n == 1:
            body = _json_body(self)
            raw = _need_scenario(body)
            fill = _flag(body, "fill_defaults")
            result = engine.recommend(raw, fill_defaults=fill)
            return self._send(200, output.dumps(result).encode("utf-8"), "application/json; charset=utf-8")
        if route == "diff" and n == 1:
            from . import diff as _diff
            body = _json_body(self)
            a, b = _need_scenario(body, "a"), _need_scenario(body, "b")
            if not isinstance(a, dict) or not isinstance(b, dict):
                raise ApiError(400, "'a' and 'b' must be JSON objects (scenarios or outputs).")
            fill = _flag(body, "fill_defaults")
            sa = None if _diff.is_output(a) else a
            sb = None if _diff.is_output(b) else b
            oa = a if sa is None else engine.recommend(a, fill_defaults=fill, trace=False)
            ob = b if sb is None else engine.recommend(b, fill_defaults=fill, trace=False)
            d = _diff.diff(oa, ob, scenario_a=sa, scenario_b=sb) if sa is not None and sb is not None \
                else _diff.diff(oa, ob)
            return self._json(200, d)
        raise ApiError(404, "Unknown API path.")


def make_server(host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.quiet = quiet
    return srv


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> int:
    srv = make_server(host, port)
    shown = srv.server_address[0]
    url = f"http://{shown}:{srv.server_address[1]}/"
    print(f"StackSense serving on {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0

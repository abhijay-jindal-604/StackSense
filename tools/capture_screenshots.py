#!/usr/bin/env python3
"""Capture the report screenshots from the running StackSense web UI (tooling only).

Starts `python3 -m stacksense serve --port 8799`, drives the real UI with Playwright
for Python (a development-only tool, not needed to run the engine) in the print theme
(`?shot=1`, fixed 1180 px sheet, device scale factor 2), writes PNGs to
<root>/report/screenshots/ and a manifest.json (file, URL, clip, git commit) as
provenance, then stops the server by PID. Nothing is edited after capture: each PNG is
a clip of the rendered page between two DOM landmarks.

S30 is the one exception to "a UI screen": it is real command output (the public run
and the unittest summary), captured by this script and rendered verbatim into a
<pre> page labelled "command output".

Usage (from source/):  python3 tools/capture_screenshots.py [--only S10,S11]
"""
import argparse
import html
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("capture_screenshots.py needs Playwright for Python (dev-only): pip install playwright")

SRC = pathlib.Path(__file__).resolve().parent.parent
ROOT = SRC.parent
OUT = ROOT / "report" / "screenshots"
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}/?shot=1"
VIEW = {"width": 1200, "height": 900}

# JS: union box of the elements matched by `top` and `bottom` selectors (page coordinates)
BOX_JS = """([top, bottom, left]) => {
  const q = (s) => { const e = document.querySelector(s); if (!e) throw new Error('no element ' + s); return e.getBoundingClientRect(); };
  const t = q(top), b = q(bottom), l = left ? q(left) : null;
  const x = l ? l.left : 0, w = l ? l.width : document.documentElement.clientWidth;
  return { x: x + scrollX, y: t.top + scrollY, w, bottom: b.bottom + scrollY };
}"""


def shot(page, name, url, top, bottom, left=None, pad=12, max_h=None, before=None, manifest=None):
    page.goto(BASE + url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(900)
    if before:
        before(page)
        page.wait_for_timeout(700)
    box = page.evaluate(BOX_JS, [top, bottom, left])
    h = box["bottom"] - box["y"] + 2 * pad
    if max_h:
        h = min(h, max_h)
    clip = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad), "width": box["w"] + 2 * pad, "height": h}
    clip["width"] = min(clip["width"], VIEW["width"] - clip["x"])
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True, clip=clip)
    manifest.append({"file": path.name, "url": BASE + url, "clip": {k: round(v) for k, v in clip.items()}})
    print(f"{name}: {round(clip['width'])}x{round(clip['height'])}  {url}")


def open_info(page):
    page.evaluate("document.querySelectorAll('details.info').forEach((d) => d.open = true)")


def whatif_refit(page):
    """P2 with infrastructure.data_residency india -> none (the default field of the what-if bar)."""
    page.locator(".wival").get_by_text("none", exact=True).first.click()
    page.locator("#refit").click()
    page.wait_for_timeout(2500)


def kb_retired(page):
    """Whole catalogue filtered to retired products."""
    page.locator("#main").get_by_text("All", exact=True).first.click()
    page.wait_for_timeout(400)
    sel = page.locator("#main select").first
    pick = next((o for o in sel.locator("option").all_text_contents() if "retired" in o.lower()), None)
    if pick:
        sel.select_option(label=pick)


def terminal_page(tmp: pathlib.Path) -> str:
    """Run the real commands and render their output verbatim (S30)."""
    outdir = tmp / "outputs"
    run = subprocess.run([sys.executable, "-m", "stacksense", "run", "scenarios/public", "-o", str(outdir)],
                         cwd=SRC, capture_output=True, text=True)
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                           cwd=SRC, capture_output=True, text=True)
    tail = "\n".join(tests.stderr.strip().splitlines()[-4:])
    body = ("$ python3 -m stacksense run scenarios/public -o outputs\n" + (run.stdout + run.stderr).strip()
            .replace(str(outdir), "outputs") + "\n\n$ python3 -m unittest discover -s tests\n...\n" + tail + "\n")
    page = tmp / "terminal.html"
    page.write_text("<!doctype html><meta charset=utf-8><body style='margin:0;background:#11161D'>"
                    "<div id=t style='width:1100px;padding:18px 22px;font:14px/1.5 monospace;color:#E8E2D4'>"
                    "<div style='color:#F3B53A;margin-bottom:8px'>command output (captured by tools/capture_screenshots.py)</div>"
                    f"<pre style='margin:0;white-space:pre-wrap'>{html.escape(body)}</pre></div>", encoding="utf-8")
    return page.as_uri()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="comma-separated shot ids")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SRC, capture_output=True, text=True).stdout.strip()
    srv = subprocess.Popen([sys.executable, "-m", "stacksense", "serve", "--port", str(PORT)], cwd=SRC,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    manifest: list = []
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            sys.exit("server did not start")
        R = "&run=1#/result"
        overview = dict(top=".sheet-head", bottom="#bolts")
        warnings = dict(top=".panel.notes", bottom=".panel.notes", left=".panel.notes", max_h=980)
        detail = dict(top="#ptabs", bottom="#detail .bars", left=".detail-wrap")
        shots = [
            ("S01", "&scenario=P2#/q/3", dict(top=".sheet-head", bottom=".sheet-foot", before=open_info, max_h=1500)),
            ("S02", "&scenario=P2#/q/6", dict(top=".sheet-head", bottom=".sheet-foot", max_h=1500)),
            ("S03", "&scenario=P2#/", dict(top=".scenarios, #main section:last-of-type", bottom="#main section:last-of-type")),
            ("S10", "&scenario=P1" + R, overview),
            ("S11", "&scenario=P2&stratum=backend" + R, detail),
            ("S12", "&scenario=P2&tab=warnings" + R, warnings),
            ("S13", "&scenario=P4&stratum=database" + R, dict(detail, bottom="#detail .chips")),
            ("S14", "&scenario=P4&tab=cost" + R, dict(warnings, max_h=1100)),
            ("S15", "&scenario=P3" + R, overview),
            ("S16", "&scenario=P5" + R, overview),
            ("S17", "&scenario=P6&stratum=frontend" + R, overview),
            ("S18", "&scenario=P3&stratum=database" + R, dict(top="#detail .bars", bottom="#detail table.alt", left=".detail-wrap", max_h=900)),
            ("S19", "&scenario=P2&run=1#/whatif", dict(top=".sheet-head", bottom=".sheet-foot", before=whatif_refit, max_h=1500)),
            ("S20", "&scenario=H21_empty_object" + R, dict(top=".sheet-head", bottom=".sheet-foot", max_h=1250)),
            ("S21", "&scenario=H21_empty_object&fill=1" + R, overview),
            ("S22", "&scenario=H23" + R, dict(top=".sheet-head", bottom=".sheet-foot", max_h=1000)),
            ("S23", "&scenario=H02" + R, dict(top=".sheet-head", bottom=".strip.hz")),
            ("S24", "&scenario=H04" + R, overview),
            ("S25", "&scenario=H06&tab=warnings" + R, warnings),
            ("S26", "&scenario=H10&tab=notes" + R, warnings),
            ("S27", "&scenario=H13" + R, dict(top=".sheet-head", bottom=".sheet-foot", max_h=1300)),
            ("S28", "&scenario=H14&tab=warnings" + R, warnings),
            ("S29", "&scenario=H09&tab=warnings" + R, warnings),
            ("S31", "#/kb", dict(top=".sheet-head", bottom=".sheet-foot", before=kb_retired, max_h=1300)),
            ("S32", "&scenario=P2&run=1#/sens", dict(top=".sheet-head", bottom=".sheet-foot")),
        ]
        with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
            br = p.chromium.launch()
            for name, url, kw in shots:
                if only and name not in only:
                    continue
                page = br.new_page(viewport=VIEW, device_scale_factor=2)
                try:
                    shot(page, name, url, manifest=manifest, **kw)
                except Exception as e:  # report and carry on; a missing shot is visible in the manifest
                    print(f"{name}: FAILED {e}", file=sys.stderr)
                page.close()
            if not only or "S30" in only:
                page = br.new_page(viewport=VIEW, device_scale_factor=2)
                uri = terminal_page(pathlib.Path(tmp))
                page.goto(uri)
                page.locator("#t").screenshot(path=str(OUT / "S30.png"))
                manifest.append({"file": "S30.png", "url": "command output", "clip": "#t"})
                print("S30: command output")
                page.close()
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
    mpath = OUT / "manifest.json"
    old = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() and only else {"shots": []}
    keep = [s for s in old.get("shots", []) if s["file"] not in {m["file"] for m in manifest}]
    mpath.write_text(json.dumps({"git_commit": commit, "viewport": VIEW, "device_scale_factor": 2,
                                 "shots": sorted(keep + manifest, key=lambda s: s["file"])}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

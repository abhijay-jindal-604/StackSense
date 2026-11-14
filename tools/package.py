#!/usr/bin/env python3
"""Assemble the submission folder StackSense26_<FullName>/ (statement 9.3). Stdlib only.

    <root>/dist/StackSense26_Abhijay_Jindal/
        source/   tracked files of the source/ git tree (minus src/, docs/, caches, dist/)
        outputs/  P1_output.json ... P6_output.json from <root>/outputs
        Report_Abhijay_Jindal.pdf

Usage (from anywhere; paths resolve relative to this script, root = script/../..):
    python3 tools/package.py --verify                  # build + checks
    python3 tools/package.py --no-report --verify      # before the PDF exists
    python3 tools/package.py --report PATH --zip --tests

Only <root>/dist is ever wiped. Exit status is non-zero if --verify has any FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

NAME = "Abhijay_Jindal"
SRC_DIR = Path(__file__).resolve().parent.parent      # <root>/source
ROOT = SRC_DIR.parent                                  # <root>
DIST = ROOT / "dist"
FOLDER = f"StackSense26_{NAME}"
PDF_NAME = f"Report_{NAME}.pdf"
SCENARIO_IDS = [f"P{i}" for i in range(1, 7)]

EXCLUDE_TOP = {"src", "docs", "dist", ".git"}
EXCLUDE_PARTS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

# Statement 9.3/10: sections 1-10 must fit in 15 pages; appendices are optional, up to 10 more.
# The PDF page count cannot separate them, so: <=15 PASS, 16-25 WARN (appendices assumed), >25 FAIL.
PAGE_LIMIT, PAGE_HARD_LIMIT = 15, 25

# The nine mandatory README items (statement 9.4). Each: (label, [regexes]); an item passes when
# every regex matches somewhere in README.md (case-insensitive, multiline).
README_ITEMS = [
    # 1. Project name and a one-paragraph overview.
    ("1 project name + overview", [r"^#\s+\S", r"^[A-Za-z].{80,}$"]),
    # 2. System architecture: a diagram (image or ASCII) and a short description of each module and the data flow.
    ("2 system architecture + modules + data flow", [r"^#+.*architecture", r"data flow|flows? (from|through)|pipeline", r"```|!\[[^\]]*\]\("]),
    # 3. Technology used to build the engine, with versions.
    ("3 technology used with versions", [r"^#+.*(technolog|tech stack)", r"python\s*3\.\d+"]),
    # 4. Prerequisites (runtime versions, OS notes).
    ("4 prerequisites", [r"^#+.*prerequisite", r"windows|macos|linux"]),
    # 5. Step-by-step local setup and run commands.
    ("5 setup and run steps", [r"^#+.*(setup|set up|install|getting started)", r"python3? -m stacksense|py -3 -m stacksense"]),
    # 6. How to run a scenario JSON file and where the output JSON is written.
    ("6 run a scenario + output location", [r"^#+.*(run a scenario|scenario file|running a scenario)", r"-o\b|--output|output.*written|written to"]),
    # 7. How to switch off all LLM features (if any are used).
    ("7 LLM switch-off", [r"^#+.*llm", r"\boff\b|no[- ]llm|disable|not used|none"]),
    # 8. Project structure overview.
    ("8 project structure", [r"^#+.*(project structure|structure|layout)", r"stacksense/"]),
    # 9. Credits: every third-party library, dataset and API used.
    ("9 credits", [r"^#+.*(credits|acknowledg)", r"python|licen[cs]e|font|standard library|none"]),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "localhost")
HOME_RE = re.compile(r"/home/[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+|[A-Za-z]:\\Users\\")


def author_email() -> str:
    """The git author email (read at runtime so this shipped file holds no address)."""
    r = subprocess.run(["git", "-C", str(SRC_DIR), "config", "user.email"], capture_output=True, text=True)
    return r.stdout.strip().lower()


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def tracked_files() -> list[str]:
    """Paths (relative to source/) of git-tracked files that exist on disk."""
    r = subprocess.run(["git", "-C", str(SRC_DIR), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        die("git ls-files failed: " + r.stderr.decode(errors="replace").strip())
    out = []
    for rel in r.stdout.decode("utf-8").split("\0"):
        if not rel:
            continue
        parts = Path(rel).parts
        if parts[0] in EXCLUDE_TOP or EXCLUDE_PARTS & set(parts) or rel.endswith(".pyc"):
            continue
        if (SRC_DIR / rel).is_file():
            out.append(rel)
    return sorted(out)


def dirty_note() -> None:
    r = subprocess.run(["git", "-C", str(SRC_DIR), "status", "--porcelain"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        n = len(r.stdout.strip().splitlines())
        print(f"note: {n} uncommitted change(s) in source/; only the working-tree copy of tracked files "
              "ships, untracked files do not")


def build(report: Path | None, no_report: bool) -> Path:
    out = DIST / FOLDER
    if DIST.exists():
        shutil.rmtree(DIST)           # only ever <root>/dist
    (out / "source").mkdir(parents=True)
    (out / "outputs").mkdir()
    files = tracked_files()
    for rel in files:
        dst = out / "source" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC_DIR / rel, dst)
    print(f"source/: {len(files)} tracked files")
    n = 0
    for sid in SCENARIO_IDS:
        f = ROOT / "outputs" / f"{sid}_output.json"
        if f.is_file():
            shutil.copy2(f, out / "outputs" / f.name)
            n += 1
        else:
            print(f"warning: missing {f}")
    print(f"outputs/: {n} files")
    if not no_report:
        pdf = report or (ROOT / "report" / PDF_NAME)
        if pdf.is_file():
            shutil.copy2(pdf, out / PDF_NAME)
            print(f"report: {pdf}")
        else:
            print(f"warning: report PDF not found: {pdf}")
    dirty_note()
    return out


def page_count(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", pdf.read_bytes()))


def text_files(base: Path):
    for p in sorted(base.rglob("*")):
        if p.is_file():
            try:
                yield p, p.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue  # binary (fonts, images)


class Results:
    def __init__(self) -> None:
        self.failed = 0

    def report(self, ok: bool | None, name: str, detail: str = "") -> None:
        tag = "WARN" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            self.failed += 1
        print(f"{tag}  {name}" + (f" -- {detail}" if detail else ""))


def verify(out: Path, no_report: bool, run_tests: bool) -> int:
    R = Results()
    src, outs = out / "source", out / "outputs"

    # a. README with the nine items
    readme = src / "README.md"
    if not readme.is_file():
        R.report(False, "a. source/README.md exists")
    else:
        R.report(True, "a. source/README.md exists")
        text = readme.read_text(encoding="utf-8")
        for label, pats in README_ITEMS:
            miss = [p for p in pats if not re.search(p, text, re.I | re.M)]
            R.report(not miss, f"a. README item {label}", "missing pattern: " + miss[0] if miss else "")

    # b. .env.example
    R.report((src / ".env.example").is_file(), "b. source/.env.example exists")

    # c. outputs parse and pass the engine's own checker (stacksense.output.check)
    sys.dont_write_bytecode = True  # keep the packaged copy free of __pycache__
    sys.path.insert(0, str(src))
    try:
        from stacksense import output as engine_output  # packaged copy
        checker = engine_output.check
    except Exception as e:  # noqa: BLE001
        checker = None
        R.report(False, "c. import packaged stacksense.output", repr(e))
    for sid in SCENARIO_IDS:
        f = outs / f"{sid}_output.json"
        if not f.is_file():
            R.report(False, f"c. outputs/{f.name}", "missing")
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            R.report(False, f"c. outputs/{f.name}", f"invalid JSON: {e}")
            continue
        if checker is None:
            continue
        problems = checker(data)
        R.report(not problems, f"c. outputs/{f.name} parses and conforms",
                 "; ".join(problems[:3]) + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""))
        if isinstance(data, dict) and data.get("scenario_id") not in (None, sid):
            R.report(False, f"c. {f.name} scenario_id matches", f"got {data.get('scenario_id')!r}")

    # d. PDF
    pdf = out / PDF_NAME
    if no_report and not pdf.exists():
        R.report(None, "d. report PDF", "skipped (--no-report): " + PDF_NAME + " absent from folder")
    elif not pdf.is_file():
        R.report(False, "d. report PDF exists", PDF_NAME)
    else:
        n = page_count(pdf)
        if n <= PAGE_LIMIT:
            R.report(True, "d. PDF page count", f"{n} pages (limit {PAGE_LIMIT} for sections 1-10)")
        elif n <= PAGE_HARD_LIMIT:
            R.report(None, "d. PDF page count",
                     f"{n} pages: only OK if sections 1-10 end by page {PAGE_LIMIT} and the rest is appendices (<=10 pages)")
        else:
            R.report(False, "d. PDF page count", f"{n} pages > {PAGE_HARD_LIMIT} (15 + 10 appendix pages)")

    # e. forbidden entries
    bad = []
    for p in out.rglob("*"):
        rel = p.relative_to(out)
        parts = rel.parts
        if p.name in ("__pycache__", ".git") or p.suffix == ".pyc" or (
                p.is_dir() and p.name in ("src", "docs") and len(parts) <= 2):
            bad.append(str(rel))
    R.report(not bad, "e. no src/ docs/ __pycache__ .git *.pyc", ", ".join(bad[:5]))

    # f. personal data / secrets
    emails, homes, envs = [], [], []
    me = author_email()
    for p, t in text_files(out):
        rel = str(p.relative_to(out))
        for m in EMAIL_RE.findall(t):
            if (me and m.lower() == me) or not m.lower().endswith(ALLOWED_EMAIL_DOMAINS):
                emails.append(f"{rel}: {m}")
        if HOME_RE.search(t):
            homes.append(rel)
    for p in out.rglob(".env*"):
        if p.name != ".env.example":
            envs.append(str(p.relative_to(out)))
    R.report(not emails, "f. no email addresses in shipped files (example.* excepted)", "; ".join(sorted(set(emails))[:6]))
    R.report(not homes, "f. no absolute home paths in shipped files", ", ".join(sorted(set(homes))[:6]))
    R.report(not envs, "f. no .env file besides .env.example", ", ".join(envs))

    # g. tests, only on request
    if run_tests:
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                           cwd=src, capture_output=True, text=True,
                           env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
        R.report(r.returncode == 0, "g. unittest discover -s tests", (r.stderr.strip().splitlines() or [""])[-1])
    return 1 if R.failed else 0


def make_zip(out: Path) -> Path:
    z = out.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, Path(out.name) / p.relative_to(out))
    return z


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", type=Path, help=f"PDF to ship (default <root>/report/{PDF_NAME})")
    ap.add_argument("--no-report", action="store_true", help="do not ship a PDF")
    ap.add_argument("--verify", action="store_true", help="run checks on the built folder; non-zero exit on FAIL")
    ap.add_argument("--tests", action="store_true", help="with --verify: also run the unit tests (slow)")
    ap.add_argument("--zip", action="store_true", help="also write dist/<folder>.zip")
    args = ap.parse_args()
    if args.report and args.no_report:
        die("--report and --no-report are exclusive")
    out = build(args.report.resolve() if args.report else None, args.no_report)
    print(f"built {out}")
    if args.zip:
        print(f"zip: {make_zip(out)}")
    if args.verify:
        sys.exit(verify(out, args.no_report, args.tests))


if __name__ == "__main__":
    main()

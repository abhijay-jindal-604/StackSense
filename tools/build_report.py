#!/usr/bin/env python3
"""Build the project report PDF from Markdown (tooling only; no engine logic).

Pipeline: Markdown -> standalone HTML (python-markdown) -> PDF (headless Chrome).
Images are referenced relative to the Markdown file (e.g. screenshots/01-intake.png).

Layout (root = parent of source/, the folder that holds report/):
    <root>/report/report.md, report/architecture.svg, report/screenshots/*.png
    <root>/report/Report_Abhijay_Jindal.pdf   (default output)

Usage (paths default relative to this script, so any cwd works):
    python3 tools/build_report.py                      # run from source/
    python3 tools/build_report.py REPORT.md -o OUT.pdf --max-pages 15
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys

try:
    import markdown
except ImportError:  # tooling-only dependency; the engine itself never needs it
    sys.exit("build_report.py needs python-markdown (pip install markdown); "
             "it is a report tool only, not needed to run the engine.")

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # <root>/source/tools/ -> <root>
DEFAULT_SOURCE = ROOT / "report" / "report.md"
DEFAULT_PDF = ROOT / "report" / "Report_Abhijay_Jindal.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 14pt; margin-top: 1.4em; border-bottom: 1px solid #bbb; page-break-after: avoid; }
h3 { font-size: 12pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 0.6em 0; font-size: 9.5pt; }
th, td { border: 1px solid #999; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eee; }
code { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 9pt; background: #f3f3f3; padding: 0 2px; }
pre { background: #f6f6f6; padding: 8px; overflow-x: auto; font-size: 8.5pt; page-break-inside: avoid; }
img { max-width: 100%; border: 1px solid #ccc; margin: 0.4em 0; page-break-inside: avoid; }
blockquote { border-left: 3px solid #888; margin-left: 0; padding-left: 10px; color: #444; }
.pagebreak { page-break-before: always; }
"""

CHROME_CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def find_chrome() -> str:
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    sys.exit("No Chrome/Chromium found (tried: " + ", ".join(CHROME_CANDIDATES)
             + "); install one or print the HTML to PDF manually.")


def count_pages(pdf: pathlib.Path) -> int:
    """Count /Type /Page objects (not /Pages) in a PDF, stdlib only.

    Chrome writes page objects uncompressed; object streams are not expected here.
    """
    data = pdf.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=pathlib.Path, nargs="?", default=DEFAULT_SOURCE,
                    help=f"Markdown report (default {DEFAULT_SOURCE})")
    ap.add_argument("-o", "--output", type=pathlib.Path,
                    help=f"PDF path (default {DEFAULT_PDF} for the default source, else next to the source)")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="warn (and exit 3) if the PDF has more pages than this")
    args = ap.parse_args()

    src = args.source.resolve()
    if not src.is_file():
        sys.exit(f"report source not found: {src}")
    if args.output:
        out_pdf = args.output.resolve()
    elif src == DEFAULT_SOURCE.resolve():
        out_pdf = DEFAULT_PDF
    else:
        out_pdf = src.with_suffix(".pdf")
    out_html = out_pdf.with_suffix(".html")

    body = markdown.markdown(
        src.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<base href='{src.parent.as_uri()}/'><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )
    out_html.write_text(html, encoding="utf-8")

    subprocess.run(
        [find_chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out_pdf}", out_html.as_uri()],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"wrote {out_pdf}")
    if not out_pdf.is_file():
        sys.exit("Chrome did not produce a PDF")
    pages = count_pages(out_pdf)
    print(f"pages: {pages}")
    if args.max_pages is not None and pages > args.max_pages:
        print(f"WARNING: {pages} pages exceeds --max-pages {args.max_pages}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()

"""Generate the report's reference tables from the code so they cannot drift (plan 11.2 appendices).

    python3 tools/report_tables.py -o report/tables        # writes one Markdown file per table

A_fields.md (input schema), B_candidates.md (candidates per layer), C_warnings.md (warning catalogue),
E_eol.md (end-of-life table), G_sources.md (source registry). Standard library only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stacksense import conflicts, kb, schema  # noqa: E402
from stacksense.kb import eol  # noqa: E402


def _cell(x) -> str:
    if x is None or x == [] or x == "":
        return ""
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (list, tuple)):
        return ", ".join(str(i) for i in x)
    return str(x).replace("|", "\\|").replace("\n", " ")


def fields_table() -> str:
    rows = ["| Field | Type / allowed values | Req. | Kind | Why it matters | Affects |", "|---|---|---|---|---|---|"]
    for path, f in schema.FIELDS.items():
        t = f["type"]
        if f.get("enum"):
            t += ": " + _cell(f["enum"])
        elif f.get("item_enum"):
            t += " of " + _cell(f["item_enum"])
        if f.get("minimum") is not None or f.get("maximum") is not None:
            t += f" [{_cell(f.get('minimum'))}..{_cell(f.get('maximum'))}]"
        kind = f["constraint"] + (" (extra)" if f["extra"] else "")
        rows.append(f"| `{path}` | {_cell(t)} | {'yes' if f['required'] else ''} | {kind} | {_cell(f['why'])} | "
                    f"{_cell(f['affects'])} |")
    return "\n".join(rows) + "\n"


def candidates_table() -> str:
    out = []
    for layer in kb.LAYERS:
        recs = sorted(kb.by_layer(layer), key=lambda r: r["id"])
        out.append(f"**{layer}** ({len(recs)})\n")
        out.append("| Candidate | Kind | Languages | Lock-in | Ops | Sources |")
        out.append("|---|---|---|---|---|---|")
        for r in recs:
            out.append(f"| {_cell(r['name'])} | {_cell(r.get('kind'))} | {_cell(r.get('languages'))} | "
                       f"{_cell(r.get('lock_in'))} | {_cell(r.get('ops_burden'))} | {_cell(r.get('sources'))} |")
        out.append("")
    return "\n".join(out)


def warnings_table() -> str:
    rows = ["| Code | Severity | Fields | Message template | Effect |", "|---|---|---|---|---|"]
    for code, e in sorted(conflicts.CATALOGUE.items()):
        rows.append(f"| `{code}` | {_cell(e.severity)} | {_cell(e.fields)} | {_cell(e.template)} | {_cell(e.effect)} |")
    return "\n".join(rows) + "\n"


def eol_table() -> str:
    rows = [f"Anchor date: {eol.KB_DATE.isoformat()} (`kb.eol.KB_DATE`).", "",
            "| Product / cycle | Kind | Date | Replacement | Source |", "|---|---|---|---|---|"]
    for r in eol.ROWS:
        rows.append(f"| {_cell(r.label)} | {_cell(r.kind)} | {_cell(r.date)} | {_cell(r.replacement)} | {_cell(r.source)} |")
    return "\n".join(rows) + "\n"


def sources_table() -> str:
    rows = ["| Key | Title | URL | Accessed |", "|---|---|---|---|"]
    for k, v in sorted(kb.SOURCES.items()):
        title, url, accessed = (list(v) + ["", "", ""])[:3]
        rows.append(f"| `{k}` | {_cell(title)} | {_cell(url)} | {_cell(accessed)} |")
    return "\n".join(rows) + "\n"


TABLES = {"A_fields.md": fields_table, "B_candidates.md": candidates_table, "C_warnings.md": warnings_table,
          "E_eol.md": eol_table, "G_sources.md": sources_table}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="report/tables")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in TABLES.items():
        (out / name).write_text(fn(), encoding="utf-8", newline="\n")
        print(f"wrote {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

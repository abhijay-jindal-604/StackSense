"""Sensitivity table for the report (plan 11.3): flip one extra field at a time on a base scenario.

    python3 tools/sensitivity.py --base P2 [--base P3 ...] [--json] [-o report/sensitivity.md]

``--base`` takes a public scenario id (P1-P6) or a path to a scenario file. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stacksense import sensitivity  # noqa: E402
from stacksense.io import load_scenarios  # noqa: E402

PUBLIC = ROOT / "scenarios" / "public"


def _load(base: str) -> dict:
    path = Path(base)
    if not path.exists():
        path = PUBLIC / f"{base}.json"
    loaded = load_scenarios(path)
    if not loaded or loaded[0].load_error:
        raise SystemExit(f"cannot load {base}: {loaded[0].load_error if loaded else 'no scenario'}")
    return loaded[0].raw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", action="append", required=True, help="public id (P1-P6) or scenario file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)
    results = [sensitivity.run(_load(b)) for b in args.base]
    if args.json:
        text = json.dumps(results, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    else:
        text = "\n".join(sensitivity.markdown(r) for r in results)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

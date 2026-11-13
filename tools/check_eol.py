#!/usr/bin/env python3
"""Print the end-of-life table (kb/eol.py) with sources, flag rows past the fixed KB date.

Usage (from source/):
    python3 tools/check_eol.py              # offline: table, sources, past-anchor flags
    python3 tools/check_eol.py --live       # also diff each endoflife.date-backed row against the API
    python3 tools/check_eol.py --strict     # exit 1 when a source key is missing or a live diff differs

Offline mode needs no network and no clock: "past" means date <= kb.eol.KB_DATE.  Dev tool only; the
engine never calls it.  Standard library only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from stacksense.kb import eol  # noqa: E402
from stacksense.kb.sources import SOURCES  # noqa: E402

API = "https://endoflife.date/api/v1/products/{}"
SLUG = {"nodejs": "nodejs", "python": "python", "php": "php", "dotnet": "dotnet", "dotnet_framework": "dotnetfx",
        "java": "oracle-jdk", "spring_boot": "spring-boot", "postgresql": "postgresql", "mysql": "mysql",
        "sqlserver": "mssqlserver", "mongodb": "mongodb", "elasticsearch": "elasticsearch",
        "windows_server": "windows-server", "centos": "centos", "ubuntu": "ubuntu", "rhel": "rhel",
        "angularjs": "angularjs", "vue": "vue", "django": "django", "rails": "rails", "openssl": "openssl"}
RELEASE = {("spring_boot", "2"): "2.7", ("angularjs", "1"): "1.8", ("dotnet_framework", "4.5"): "4.5",
           ("sqlserver", "2012"): "11.0-sp4", ("sqlserver", "2014"): "12.0-sp3", ("sqlserver", "2016"): "13.0-sp3",
           ("sqlserver", "2017"): "14.0", ("sqlserver", "2019"): "15.0", ("elasticsearch", "7"): "7",
           ("windows_server", "2012"): "2012-r2", ("windows_server", "2016"): "2016", ("vue", "2"): "2.7"}


def live_date(row: eol.EolRow, cache: dict) -> str | None:
    slug = SLUG.get(row.product)
    if slug is None:
        return None
    if slug not in cache:
        try:
            with urllib.request.urlopen(API.format(slug), timeout=20) as resp:
                cache[slug] = json.load(resp)["result"]["releases"]
        except Exception as exc:  # network problems must not break the offline use of this tool
            print(f"  ! {slug}: {exc}", file=sys.stderr)
            cache[slug] = []
    want = RELEASE.get((row.product, row.cycle), row.cycle)
    for rel in cache[slug]:
        if rel["name"] == want:
            return rel.get("eolFrom")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="diff endoflife.date-backed rows against the API")
    ap.add_argument("--strict", action="store_true", help="exit 1 on a missing source or a live difference")
    args = ap.parse_args(argv)
    problems = 0
    cache: dict = {}
    print(f"KB_DATE (anchor): {eol.KB_DATE.isoformat()}   rows: {len(eol.ROWS)}")
    print(f"{'key':32} {'kind':12} {'date':10} {'state':12} {'conf':10} source")
    for row in eol.ROWS:
        st = eol.status_on(row)
        flag = "PAST" if st["state"] == "ended" else st["state"]
        src = SOURCES.get(row.source)
        if src is None:
            problems += 1
        url = src[1] if src else "MISSING SOURCE KEY"
        line = f"{row.key:32} {row.kind:12} {row.date:10} {flag:12} {row.conf:10} {row.source} <{url}>"
        if args.live:
            ld = live_date(row, cache)
            if ld is not None and ld != row.date:
                line += f"   LIVE DIFFERS: {ld}"
                problems += 1
        print(line)
    past = sum(1 for r in eol.ROWS if eol.status_on(r)["state"] == "ended")
    unver = [r.key for r in eol.ROWS if r.conf != eol.V]
    print(f"\n{past} of {len(eol.ROWS)} rows are past the anchor; unverified rows: {', '.join(unver) or 'none'}")
    if problems:
        print(f"{problems} problem(s)")
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())

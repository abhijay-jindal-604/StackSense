"""Command line interface (plan section 3.20). Only this module reads the environment."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import engine, output
from .io import load_scenarios, output_name, write_output
from .validate import validate

_LATER = ("serve", "wizard", "explain", "diff")
_PUBLIC_DIR = Path(__file__).resolve().parent.parent / "scenarios" / "public"


def _ascii(s) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def _out(s: str = "") -> None:
    print(_ascii(s))


def _err(s: str) -> None:
    print(_ascii(s), file=sys.stderr)


def _label(result: dict, loaded) -> str:
    sid = result.get("scenario_id")
    return sid if isinstance(sid, str) and sid else loaded.source_name


def _stack_cols(result: dict) -> str:
    stack = result.get("stack")
    if not isinstance(stack, dict):
        return " | ".join(["-"] * 4)
    return " | ".join(str((stack.get(k) or {}).get("choice", "-")) for k in output.CORE_LAYERS)


def _cost(result: dict) -> str:
    if result.get("stack") is None:
        return "-"
    c = result.get("estimated_monthly_cost_usd") or {}
    return f"${c.get('min', 0)}-{c.get('max', 0)}"


def _cmd_run(args) -> int:
    loaded_list = load_scenarios(Path(args.path))
    out_dir = Path(args.output)
    code = 0
    for i, loaded in enumerate(loaded_list):
        idx = i if "[" in loaded.source_name else None
        result = engine.recommend_loaded(loaded, fill_defaults=args.fill_defaults, trace=not args.no_trace)
        problems = output.check(result)
        for p in problems:
            _err(f"{loaded.source_name}: output check: {p}")
        if engine.is_internal_error(result):
            code = 2
        try:
            target = write_output(result, out_dir, output_name(result.get("scenario_id"), loaded.source_name, idx))
        except OSError as e:
            _err(f"{loaded.source_name}: cannot write output: {e.strerror or e}")
            return 2
        if not args.quiet:
            _out(f"{_label(result, loaded)}  {result['status']}  {_stack_cols(result)}  {_cost(result)}  -> {target}")
    return code


def _cmd_validate(args) -> int:
    bad = 0
    for loaded in load_scenarios(Path(args.path)):
        if loaded.load_error is not None:
            bad += 1
            _out(f"{loaded.source_name}  invalid")
            _out(f"  $: {loaded.load_error}")
            continue
        v = validate(loaded.raw, fill_defaults=args.fill_defaults)
        notices = list(loaded.notices) + [n for n in v.notices if n not in loaded.notices]
        if v.errors:
            bad += 1
            _out(f"{loaded.source_name}  invalid")
            for e in v.errors:
                _out(f"  {e['field']}: {e['message']}")
        else:
            _out(f"{loaded.source_name}  valid")
        for n in notices:
            _out(f"  [{n.get('severity')}] {n.get('code')}: {n.get('message')}")
    return 1 if bad else 0


def _cmd_selftest(args) -> int:
    loaded_list = load_scenarios(_PUBLIC_DIR) if _PUBLIC_DIR.is_dir() else []
    files = [l for l in loaded_list if "[" not in l.source_name and l.source_name.startswith("P")]
    if len(files) != 6:
        _err(f"selftest: expected 6 public scenarios in {_PUBLIC_DIR}, found {len(files)}")
        return 2
    failed = 0
    for loaded in files:
        result = engine.recommend_loaded(loaded)
        problems = output.check(result)
        if problems or engine.is_internal_error(result):
            failed += 1
        _out(f"{_label(result, loaded)}  {result['status']}  {'FAIL' if problems else 'conformant'}")
        for p in problems:
            _err(f"{loaded.source_name}: {p}")
    _out(f"selftest: {len(files) - failed}/{len(files)} scenarios conform")
    return 0 if failed == 0 else 1


def _cmd_later(args) -> int:
    _err(f"{args.command}: not available yet")
    return 2


def _cmd_kb(args) -> int:
    import json

    from . import kb
    action = args.kb_action
    if action == "export":
        text = json.dumps(kb.export(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        if args.out:
            try:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            except OSError as e:
                _err(f"cannot write {args.out}: {e.strerror or e}")
                return 2
            _out(f"kb {kb.kb_version()}: wrote {args.out}")
        else:
            sys.stdout.write(text)
        return 0
    if action == "stats":
        st = kb.stats()
        _out(f"kb_version {st['kb_version']}: {st['records']} records, {st['offerings']} offerings, "
             f"{st['sources_registered']} sources ({st['sources_cited_by_records']} cited)")
        for layer in kb.LAYERS:
            _out(f"  {layer:<16} {st['maintained_per_layer'][layer]:>3} / min {st['minimum_per_layer'][layer]}")
        return 0
    problems = kb.check()
    for p in problems:
        _out(p)
    _out(f"kb check: {len(problems)} problem(s)")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stacksense", description="StackSense tech stack recommendation engine")
    sub = ap.add_subparsers(dest="command", metavar="command")
    r = sub.add_parser("run", help="recommend stacks for a scenario file or directory")
    r.add_argument("path")
    r.add_argument("-o", "--output", default="outputs")
    r.add_argument("--fill-defaults", action="store_true")
    r.add_argument("--no-trace", action="store_true")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=_cmd_run)
    v = sub.add_parser("validate", help="validate scenario files")
    v.add_argument("path")
    v.add_argument("--fill-defaults", action="store_true")
    v.set_defaults(func=_cmd_validate)
    s = sub.add_parser("selftest", help="run the public scenarios and check output conformance")
    s.set_defaults(func=_cmd_selftest)
    k = sub.add_parser("kb", help="knowledge base: export, stats, check")
    ksub = k.add_subparsers(dest="kb_action", metavar="action", required=True)
    ke = ksub.add_parser("export", help="dump the knowledge base as JSON")
    ke.add_argument("-o", "--out", default=None)
    ksub.add_parser("stats", help="record counts per layer")
    ksub.add_parser("check", help="integrity and minimum-count problems (exit 1 if any)")
    k.set_defaults(func=_cmd_kb)
    for name in _LATER:
        p = sub.add_parser(name, help="not available yet", add_help=False)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=_cmd_later)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 2
    except Exception as exc:  # noqa: BLE001
        _err(f"internal error: {type(exc).__name__}: {exc}")
        return 2

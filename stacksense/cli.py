"""Command line interface (plan section 3.20). Only this module reads the environment."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import engine, output
from .io import load_scenarios, output_name, write_output
from .validate import validate

_LATER = ("wizard",)
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


def _array_index(source_name: str):
    """Element index from a ``file.json[n]`` source name; None for non-array files."""
    m = re.search(r"\[(\d+)\]$", source_name)
    return int(m.group(1)) if m else None


def _unique_name(name: str, scenario_id, source_name: str, index, used: set) -> str:
    """Return ``name`` unless already written this run; then add the source stem, then a counter."""
    if name.lower() not in used:
        return name
    stem = re.sub(r"\[\d+\]$", "", source_name)
    stem = re.sub(r"\.json$", "", stem, flags=re.IGNORECASE)
    if index is not None:
        stem = f"{stem}_{index}"
    sid = scenario_id.strip() if isinstance(scenario_id, str) and scenario_id.strip() else "scenario"
    alt = output_name(f"{sid}__{stem}", source_name, None)
    cand, n = alt, 2
    while cand.lower() in used:
        cand = alt[:-len("_output.json")] + f"_{n}_output.json"
        n += 1
    return cand


def _run_exit_code(code: int, problems, result: dict) -> int:
    """Exit code 2 for an internal error or any output conformance problem (plan 3.16/3.20)."""
    if problems or engine.is_internal_error(result):
        return 2
    return code


def _cmd_run(args) -> int:
    loaded_list = load_scenarios(Path(args.path))
    out_dir = Path(args.output)
    code = 0
    used: set = set()
    for loaded in loaded_list:
        idx = _array_index(loaded.source_name)
        result = engine.recommend_loaded(loaded, fill_defaults=args.fill_defaults, trace=not args.no_trace)
        problems = output.check(result)
        for p in problems:
            _err(f"{loaded.source_name}: output check: {p}")
        code = _run_exit_code(code, problems, result)
        sid = result.get("scenario_id")
        base = output_name(sid, loaded.source_name, idx)
        name = _unique_name(base, sid, loaded.source_name, idx, used)
        if name != base:
            _err(f"{loaded.source_name}: output name {base} already used; writing {name}")
        used.add(name.lower())
        try:
            target = write_output(result, out_dir, name)
        except OSError as e:
            _err(f"{loaded.source_name}: cannot write output: {e.strerror or e}")
            code = 2
            continue
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


def _load_one(path: str, fill_defaults: bool = False):
    """(scenario or None, output) for a scenario or output file; the first element of an array file."""
    loaded = load_scenarios(Path(path))
    if not loaded:
        raise ValueError(f"{path}: no scenario found")
    first = loaded[0]
    if first.load_error:
        raise ValueError(f"{first.source_name}: {first.load_error}")
    from . import diff as _diff
    if _diff.is_output(first.raw):
        return None, first.raw
    return first.raw, engine.recommend_loaded(first, fill_defaults=fill_defaults)


def _cmd_diff(args) -> int:
    import json

    from . import diff as _diff
    try:
        sa, a = _load_one(args.a, args.fill_defaults)
        sb, b = _load_one(args.b, args.fill_defaults)
    except (OSError, ValueError) as e:
        _err(str(e))
        return 2
    d = _diff.diff(a, b, scenario_a=sa, scenario_b=sb) if sa is not None and sb is not None else _diff.diff(a, b)
    if args.json:
        sys.stdout.write(json.dumps(d, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    else:
        for line in _diff.render(d):
            _out(line)
    return 0


_TRACE_LAYERS = {"frontend": ("frontend_web", "frontend_mobile")}


def _cmd_explain(args) -> int:
    try:
        _, out = _load_one(args.path, args.fill_defaults)
    except (OSError, ValueError) as e:
        _err(str(e))
        return 2
    trace = out.get("decision_trace") or {}
    _out(f"{out.get('scenario_id')}  {out.get('status')}  architecture: {out.get('architecture_style')}")
    prof = trace.get("profile") or {}
    if prof:
        _out("profile: " + ", ".join(f"{k}={prof[k]}" for k in sorted(prof)))
    layers = trace.get("layers") or {}
    wanted = [args.layer] if args.layer else list(layers)
    keys = []
    for w in wanted:
        keys += [k for k in _TRACE_LAYERS.get(w, (w,)) if k in layers]
    if args.layer and not keys:
        _err(f"no trace for layer {args.layer}; layers: {', '.join(layers) or '(none)'}")
        return 2
    for key in keys:
        lt = layers[key]
        _out("")
        _out(f"== {key}: {lt.get('candidates')} candidates, {len(lt.get('rejected') or [])} rejected by hard filters")
        _out(f"  {'rank':<4} {'candidate':<40} {'score':>7}  top contributions")
        for i, t in enumerate(lt.get("top") or [], 1):
            cs = sorted(t.get("contributions") or [], key=lambda c: (-abs(c.get("value", 0)), c.get("key", "")))[:3]
            parts = ", ".join(f"{c['key']} {c['value']:+g}" for c in cs)
            _out(f"  {i:<4} {str(t.get('name'))[:40]:<40} {t.get('total', 0):>7.2f}  {parts}")
        rej = lt.get("rejected") or []
        if rej:
            _out(f"  {'rejected':<45} {'rule':<5} reason")
            for r in rej[:args.max_rejected]:
                _out(f"  {str(r.get('name'))[:45]:<45} {str(r.get('rule')):<5} {r.get('reason_text')}")
            if len(rej) > args.max_rejected:
                _out(f"  ... {len(rej) - args.max_rejected} more")
    if not args.layer:
        combos = trace.get("combinations") or {}
        if combos:
            _out("")
            _out(f"== combinations: {combos.get('considered')} considered, {combos.get('passed')} passed")
            for i, c in enumerate(combos.get("top") or [], 1):
                _out(f"  {i:<4} {' + '.join(str(x) for x in (c.get('ids') or []))[:90]}  score {c.get('score', '-')}")
        arch = trace.get("architecture") or {}
        if arch:
            _out("")
            _out(f"== architecture: {arch.get('style')} (rule {arch.get('rule')}): {arch.get('reason')}")
    stack = out.get("stack") or {}
    if stack and not args.layer:
        _out("")
        _out("== chosen")
        for k in output.CORE_LAYERS:
            c = stack.get(k) or {}
            _out(f"  {k:<10} {c.get('choice')}  [driven by {', '.join(c.get('driven_by') or [])}]")
    return 0


def _cmd_later(args) -> int:
    _err(f"{args.command}: not available yet")
    return 2


def _cmd_serve(args) -> int:
    from . import server
    try:
        return server.serve(args.host, args.port, args.open)
    except OSError as e:
        _err(f"cannot start server on {args.host}:{args.port}: {e.strerror or e}")
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
    core = getattr(args, "core", False)
    problems = kb.check(core_only=core)
    for p in problems:
        _out(p)
    _out(f"kb check{' --core' if core else ''}: {len(problems)} problem(s)")
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
    sv = sub.add_parser("serve", help="start the local web UI and JSON API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--open", action="store_true", help="open the browser")
    sv.set_defaults(func=_cmd_serve)
    k = sub.add_parser("kb", help="knowledge base: export, stats, check")
    ksub = k.add_subparsers(dest="kb_action", metavar="action", required=True)
    ke = ksub.add_parser("export", help="dump the knowledge base as JSON")
    ke.add_argument("-o", "--out", default=None)
    ksub.add_parser("stats", help="record counts per layer")
    kc = ksub.add_parser("check", help="integrity, source, consistency and minimum-count problems (exit 1 if any)")
    kc.add_argument("--core", action="store_true",
                    help="minimum counts for core layers only (frontend, backend, database, hosting)")
    k.set_defaults(func=_cmd_kb)
    d = sub.add_parser("diff", help="what-if diff of two scenarios or two outputs")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--json", action="store_true", help="print the diff as JSON")
    d.add_argument("--fill-defaults", action="store_true")
    d.set_defaults(func=_cmd_diff)
    e = sub.add_parser("explain", help="print the decision trace of a scenario or output as text tables")
    e.add_argument("path")
    e.add_argument("--layer", default=None, help="frontend, backend, database or hosting")
    e.add_argument("--max-rejected", type=int, default=10)
    e.add_argument("--fill-defaults", action="store_true")
    e.set_defaults(func=_cmd_explain)
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

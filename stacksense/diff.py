"""What-if diff of two recommendations (plan section 3.21).

``diff(a, b)`` compares two section 4 outputs layer by layer. Each layer entry is
``{from, to, changed, drivers}``, where ``drivers`` lists the input field paths that differ between the two
scenarios and appear in either side's ``driven_by``. When the scenarios are not supplied (two outputs only),
``drivers`` falls back to the fields in the symmetric difference of the two ``driven_by`` lists of a changed
layer. Status, cost band and warning codes are compared too. Used by ``cli diff``, ``/api/diff``,
``tools/sensitivity.py`` and the locality tests. Pure and deterministic.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

CORE_LAYERS = ("frontend", "backend", "database", "hosting")


def is_output(doc: Any) -> bool:
    """True for a section 4 output (as opposed to a section 3 scenario)."""
    return isinstance(doc, Mapping) and "status" in doc and "stack" in doc and "engine_version" in doc


def flatten(doc: Any, prefix: str = "") -> dict[str, Any]:
    """Dotted field paths -> leaf values (lists are leaves, compared as wholes)."""
    out: dict[str, Any] = {}
    if isinstance(doc, Mapping):
        for k in sorted(doc):
            path = f"{prefix}.{k}" if prefix else str(k)
            v = doc[k]
            if isinstance(v, Mapping) and v:
                out.update(flatten(v, path))
            else:
                out[path] = v
    return out


def changed_fields(a: Mapping | None, b: Mapping | None) -> list[str]:
    """Field paths whose values differ between two scenarios (missing counts as a difference)."""
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        return []
    fa, fb = flatten(a), flatten(b)
    return sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))


def _layers(output: Mapping) -> dict[str, dict]:
    stack = output.get("stack") if isinstance(output, Mapping) else None
    if not isinstance(stack, Mapping):
        return {}
    out = {k: stack[k] for k in CORE_LAYERS if isinstance(stack.get(k), Mapping)}
    for item in stack.get("supporting") or []:
        if isinstance(item, Mapping):
            key = f"supporting.{item.get('slot') or item.get('layer') or 'other'}"
            n, base = 2, key
            while key in out:
                key = f"{base}#{n}"
                n += 1
            out[key] = item
    return out


def _drivers(x: Mapping | None, y: Mapping | None, fields: Iterable[str] | None) -> list[str]:
    dx = list((x or {}).get("driven_by") or [])
    dy = list((y or {}).get("driven_by") or [])
    if fields is None:
        return sorted(set(dx) ^ set(dy))
    cited = set(dx) | set(dy)
    hits = []
    for f in fields:
        # a changed leaf (scale.peak_rps) matches a cited path or a cited parent/child
        if any(f == c or f.startswith(c + ".") or c.startswith(f + ".") for c in cited):
            hits.append(f)
    return sorted(set(hits))


def _cost(output: Mapping) -> dict | None:
    c = output.get("estimated_monthly_cost_usd") if isinstance(output, Mapping) else None
    if not isinstance(c, Mapping):
        return None
    return {"min": c.get("min"), "max": c.get("max")}


def _codes(output: Mapping) -> list[str]:
    return sorted({w.get("code") for w in (output.get("warnings") or []) if isinstance(w, Mapping)})


def diff(a: Mapping, b: Mapping, *, scenario_a: Mapping | None = None,
         scenario_b: Mapping | None = None) -> dict:
    """Diff output ``a`` (before) against output ``b`` (after)."""
    fields = changed_fields(scenario_a, scenario_b) if scenario_a is not None and scenario_b is not None else None
    la, lb = _layers(a), _layers(b)
    layers = {}
    for key in list(CORE_LAYERS) + sorted(k for k in set(la) | set(lb) if k not in CORE_LAYERS):
        x, y = la.get(key), lb.get(key)
        fx = x.get("choice") if x else None
        fy = y.get("choice") if y else None
        changed = fx != fy
        layers[key] = {"from": fx, "to": fy, "changed": changed,
                       "drivers": _drivers(x, y, fields) if changed else []}
    ca, cb = _codes(a), _codes(b)
    cost_a, cost_b = _cost(a), _cost(b)
    out = {
        "status": {"from": a.get("status"), "to": b.get("status"), "changed": a.get("status") != b.get("status")},
        "architecture_style": {"from": a.get("architecture_style"), "to": b.get("architecture_style"),
                               "changed": a.get("architecture_style") != b.get("architecture_style")},
        "layers": layers,
        "changed_layers": [k for k, v in layers.items() if v["changed"]],
        "cost": {"from": cost_a, "to": cost_b, "changed": cost_a != cost_b,
                 "delta_min": _delta(cost_a, cost_b, "min"), "delta_max": _delta(cost_a, cost_b, "max")},
        "warnings": {"added": sorted(set(cb) - set(ca)), "removed": sorted(set(ca) - set(cb))},
    }
    if fields is not None:
        out["changed_fields"] = fields
    return out


def _delta(x: Mapping | None, y: Mapping | None, k: str):
    if not x or not y or not isinstance(x.get(k), (int, float)) or not isinstance(y.get(k), (int, float)):
        return None
    return y[k] - x[k]


def render(d: Mapping) -> list[str]:
    """Plain-text lines for the CLI."""
    lines = []
    if d.get("changed_fields"):
        lines.append("Changed inputs: " + ", ".join(d["changed_fields"]))
    st = d["status"]
    lines.append(f"status: {st['from']} -> {st['to']}" if st["changed"] else f"status: {st['from']} (unchanged)")
    ar = d["architecture_style"]
    if ar["changed"]:
        lines.append(f"architecture_style: {ar['from']} -> {ar['to']}")
    for key, v in d["layers"].items():
        if v["changed"]:
            why = f"  [driven by {', '.join(v['drivers'])}]" if v["drivers"] else ""
            lines.append(f"{key}: {v['from'] or '(none)'} -> {v['to'] or '(none)'}{why}")
    unchanged = [k for k, v in d["layers"].items() if not v["changed"]]
    if unchanged:
        lines.append("unchanged: " + ", ".join(unchanged))
    c = d["cost"]
    if c["changed"] and c["from"] and c["to"]:
        lines.append(f"cost USD/month: {c['from']['min']}-{c['from']['max']} -> {c['to']['min']}-{c['to']['max']}")
    elif c["from"]:
        lines.append(f"cost USD/month: {c['from']['min']}-{c['from']['max']} (unchanged)")
    w = d["warnings"]
    if w["added"]:
        lines.append("warnings added: " + ", ".join(w["added"]))
    if w["removed"]:
        lines.append("warnings removed: " + ", ".join(w["removed"]))
    return lines

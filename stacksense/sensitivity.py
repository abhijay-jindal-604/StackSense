"""One-at-a-time sensitivity of the recommendation to the extra input fields (plan section 11.3).

``run(base)`` takes a scenario, sets one extra field at a time to a contrasting value and records the
diff (``diff.diff``) against the unmodified run: which layers changed, warnings added/removed and the
cost delta. The flips are generic (the same list for every base scenario); nothing here knows scenario
ids. It is the evidence that each extra input changes the output, used by ``tools/sensitivity.py``
and ``/api/sensitivity``.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from . import diff as _diff
from . import engine

# (field path, value to set, or a callable(current) -> value). The value contrasts with the default.
FLIPS: tuple[tuple[str, Any], ...] = (
    ("scale.geographic_spread", "global"),
    ("scale.peak_rps", 5000),
    ("team.willing_to_learn", lambda cur: not (True if cur is None else bool(cur))),
    ("team.growth_12_months", lambda cur: 15),
    ("infrastructure.lock_in_tolerance", "low"),
    ("infrastructure.open_source_only", True),
    ("infrastructure.existing_licences", ["microsoft_enterprise"]),
    ("requirements.notifications", ["push", "sms"]),
    ("requirements.background_jobs", True),
    ("requirements.consistency", "eventual"),
    ("requirements.data_shape", "time_series"),
    ("requirements.cms", "headless"),
)

_MISSING = object()


def _get(doc: Mapping, path: str):
    node: Any = doc
    for k in path.split("."):
        if not isinstance(node, Mapping) or k not in node:
            return _MISSING
        node = node[k]
    return node


def _set(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    node = doc
    for k in parts[:-1]:
        nxt = node.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            node[k] = nxt
        node = nxt
    node[parts[-1]] = value


def flip_value(scenario: Mapping, path: str, spec):
    cur = _get(scenario, path)
    cur = None if cur is _MISSING else cur
    value = spec(cur) if callable(spec) else spec
    return cur, value


def run(scenario: Mapping, flips=FLIPS, *, fill_defaults: bool = False) -> dict:
    """Sensitivity rows for one base scenario."""
    base_out = engine.recommend(copy.deepcopy(scenario), fill_defaults=fill_defaults, trace=False)
    rows = []
    for path, spec in flips:
        cur, value = flip_value(scenario, path, spec)
        if cur == value:
            rows.append({"field": path, "from": cur, "to": value, "skipped": "already set to this value"})
            continue
        variant = copy.deepcopy(scenario)
        _set(variant, path, value)
        out = engine.recommend(variant, fill_defaults=fill_defaults, trace=False)
        d = _diff.diff(base_out, out, scenario_a=scenario, scenario_b=variant)
        rows.append({
            "field": path, "from": cur, "to": value,
            "status": d["status"]["to"],
            "changed_layers": d["changed_layers"],
            "changes": {k: {"from": v["from"], "to": v["to"]} for k, v in d["layers"].items() if v["changed"]},
            "warnings_added": d["warnings"]["added"],
            "warnings_removed": d["warnings"]["removed"],
            "cost_from": d["cost"]["from"], "cost_to": d["cost"]["to"],
            "effect": bool(d["changed_layers"] or d["warnings"]["added"] or d["warnings"]["removed"]
                           or d["cost"]["changed"] or d["status"]["changed"]),
        })
    return {"scenario_id": base_out.get("scenario_id"), "status": base_out.get("status"),
            "cost": base_out.get("estimated_monthly_cost_usd", {}) and
            {k: base_out["estimated_monthly_cost_usd"].get(k) for k in ("min", "max")},
            "rows": rows}


def _fmt(v) -> str:
    if v is None:
        return "(absent)"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def _cost(c) -> str:
    return f"{c['min']}-{c['max']}" if isinstance(c, Mapping) else "-"


def markdown(result: Mapping) -> str:
    """The report table (plan 11.3) for one base scenario."""
    lines = [f"Base {result['scenario_id']} ({result['status']}, USD {_cost(result.get('cost'))}/month)", "",
             "| Extra field | Flip | Layers changed | Warnings added / removed | Cost USD/month |",
             "|---|---|---|---|---|"]
    for r in result["rows"]:
        flip = f"{_fmt(r['from'])} -> {_fmt(r['to'])}"
        if r.get("skipped"):
            lines.append(f"| `{r['field']}` | {flip} | (skipped: {r['skipped']}) | | |")
            continue
        layers = "; ".join(f"{k}: {v['from'] or '(none)'} -> {v['to'] or '(none)'}" for k, v in r["changes"].items())
        warn = ", ".join([f"+{c}" for c in r["warnings_added"]] + [f"-{c}" for c in r["warnings_removed"]])
        cost = _cost(r["cost_from"]) + (f" -> {_cost(r['cost_to'])}" if r["cost_from"] != r["cost_to"] else "")
        lines.append(f"| `{r['field']}` | {flip} | {layers or 'none'} | {warn or 'none'} | {cost} |")
    return "\n".join(lines) + "\n"

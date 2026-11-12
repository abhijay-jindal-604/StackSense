"""Result construction, serialisation and the hand-written section 4 conformance checker."""
from __future__ import annotations

import json
from typing import Any, Iterable

from . import __version__

STATUSES = ("ok", "ok_with_warnings", "infeasible", "invalid_input")
ARCH_STYLES = (
    "static", "monolith", "modular_monolith", "serverless",
    "service_oriented", "microservices", "hybrid", "other",
)
CORE_LAYERS = ("frontend", "backend", "database", "hosting")
# Order is the statement's list order; supporting[] must follow it (T-OUT-03).
SUPPORTING_LAYERS = (
    "cache", "queue", "search", "auth", "storage", "cdn", "realtime",
    "payments", "ml", "ci_cd", "observability", "other",
)
SEVERITIES = ("critical", "warning", "info")  # sort order, most severe first

KEY_ORDER = (
    "scenario_id", "engine_version", "kb_version", "status", "summary",
    "architecture_style", "stack", "estimated_monthly_cost_usd", "budget_verdict",
    "warnings", "assumptions", "validation_errors", "compliance_notes",
    "integration_notes", "relaxed_constraints", "nearest_feasible", "llm_used",
    "decision_trace",
)


def sort_warnings(warnings: Iterable[dict]) -> list[dict]:
    """critical > warning > info, then code, then message (stable and deterministic)."""
    def key(w: dict) -> tuple:
        sev = w.get("severity")
        rank = SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES)
        return (rank, str(w.get("code", "")), str(w.get("message", "")))
    return sorted(warnings, key=key)


def build(
    *,
    status: str,
    scenario_id: str | None = None,
    summary: str | None = None,
    architecture_style: str = "other",
    stack: dict | None = None,
    estimated_monthly_cost_usd: dict | None = None,
    budget_verdict: Any = None,
    warnings: Iterable[dict] = (),
    assumptions: Iterable[str] = (),
    validation_errors: Iterable[dict] = (),
    compliance_notes: Iterable[Any] = (),
    integration_notes: Iterable[Any] = (),
    relaxed_constraints: Iterable[Any] = (),
    nearest_feasible: Iterable[Any] = (),
    llm_used: bool = False,
    decision_trace: Any = None,
    engine_version: str = __version__,
    kb_version: str = "unversioned",
) -> dict:
    """Assemble a result dict in the fixed key order. ``decision_trace=None`` omits that key.

    Warnings are sorted here. For ``invalid_input``/``infeasible`` the stack is forced to
    None. Missing summary and cost get neutral defaults.
    """
    validation_errors = list(validation_errors)
    if stack is not None and status in ("invalid_input", "infeasible"):
        stack = None
    if summary is None:
        if status == "invalid_input":
            n = len(validation_errors)
            summary = f"No stack was recommended because the input is not valid ({n} problem{'s' if n != 1 else ''} found)."
        elif status == "infeasible":
            summary = "No stack satisfies all hard constraints together, so none is recommended."
        else:
            summary = "Recommendation produced; see the stack and warnings for details."
    if estimated_monthly_cost_usd is None:
        estimated_monthly_cost_usd = {
            "min": 0, "max": 0,
            "assumptions": ["No cost estimate: no stack was produced."],
        }
    values = {
        "scenario_id": scenario_id,
        "engine_version": engine_version,
        "kb_version": kb_version,
        "status": status,
        "summary": summary,
        "architecture_style": architecture_style,
        "stack": stack,
        "estimated_monthly_cost_usd": estimated_monthly_cost_usd,
        "budget_verdict": budget_verdict,
        "warnings": sort_warnings(warnings),
        "assumptions": list(assumptions),
        "validation_errors": validation_errors,
        "compliance_notes": list(compliance_notes),
        "integration_notes": list(integration_notes),
        "relaxed_constraints": list(relaxed_constraints),
        "nearest_feasible": list(nearest_feasible),
        "llm_used": llm_used,
        "decision_trace": decision_trace,
    }
    out = {k: values[k] for k in KEY_ORDER if not (k == "decision_trace" and decision_trace is None)}
    return out


def invalid_input_result(scenario_id: str | None, errors: Iterable[dict], assumptions: Iterable[str] = ()) -> dict:
    """An ``invalid_input`` result; ``errors`` are ``{field, message}`` dicts (e.g. load errors use field "$")."""
    return build(status="invalid_input", scenario_id=scenario_id,
                 validation_errors=errors, assumptions=assumptions)


def dumps(result: dict) -> str:
    """Pretty JSON (indent 2, non-ASCII kept) with a trailing newline."""
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- checker

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _check_component(c: Any, where: str, core: bool, errs: list[str]) -> None:
    if not isinstance(c, dict):
        errs.append(f"{where}: must be an object")
        return
    for k in ("choice", "justification"):
        if not isinstance(c.get(k), str) or not c.get(k, "").strip():
            errs.append(f"{where}.{k}: must be a non-empty string")
    db = c.get("driven_by")
    if not _is_str_list(db) or not db:
        errs.append(f"{where}.driven_by: must be a non-empty list of strings")
    alts = c.get("alternatives")
    if not isinstance(alts, list):
        errs.append(f"{where}.alternatives: must be a list")
    else:
        if core and len(alts) < 1:
            errs.append(f"{where}.alternatives: needs at least one entry for core layers")
        for i, a in enumerate(alts):
            if not (isinstance(a, dict) and isinstance(a.get("choice"), str) and a.get("choice")
                    and isinstance(a.get("why_not"), str) and a.get("why_not")):
                errs.append(f"{where}.alternatives[{i}]: must be {{choice, why_not}} non-empty strings")
    if "tradeoffs" in c and not _is_str_list(c["tradeoffs"]):
        errs.append(f"{where}.tradeoffs: must be a list of strings")


def check(result: Any) -> list[str]:
    """Return a list of section 4 conformance problems (empty list = conformant)."""
    errs: list[str] = []
    if not isinstance(result, dict):
        return ["result: must be an object"]
    status = result.get("status")
    if status not in STATUSES:
        errs.append(f"status: must be one of {list(STATUSES)}")
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        errs.append("summary: must be a non-empty string")
    if result.get("architecture_style") not in ARCH_STYLES:
        errs.append(f"architecture_style: must be one of {list(ARCH_STYLES)}")
    elif status in ("ok", "ok_with_warnings") and result["architecture_style"] == "other":
        errs.append("architecture_style: 'other' is only allowed for invalid_input/infeasible")
    if "scenario_id" in result and result["scenario_id"] is not None and not isinstance(result["scenario_id"], str):
        errs.append("scenario_id: must be a string or null")

    # stack
    if "stack" not in result:
        errs.append("stack: missing")
    else:
        stack = result["stack"]
        if status in ("invalid_input", "infeasible"):
            if stack is not None:
                errs.append(f"stack: must be null when status is {status}")
        elif status in ("ok", "ok_with_warnings"):
            if not isinstance(stack, dict):
                errs.append("stack: must be an object")
            else:
                for layer in CORE_LAYERS:
                    if layer not in stack:
                        errs.append(f"stack.{layer}: missing")
                    else:
                        _check_component(stack[layer], f"stack.{layer}", True, errs)
                sup = stack.get("supporting", [])
                if not isinstance(sup, list):
                    errs.append("stack.supporting: must be a list")
                else:
                    last = -1
                    for i, s in enumerate(sup):
                        w = f"stack.supporting[{i}]"
                        _check_component(s, w, False, errs)
                        layer = s.get("layer") if isinstance(s, dict) else None
                        if layer not in SUPPORTING_LAYERS:
                            errs.append(f"{w}.layer: must be one of {list(SUPPORTING_LAYERS)}")
                        else:
                            idx = SUPPORTING_LAYERS.index(layer)
                            if idx < last:
                                errs.append(f"{w}.layer: supporting[] must follow the fixed layer order")
                            last = max(last, idx)

    # cost
    cost = result.get("estimated_monthly_cost_usd")
    if not isinstance(cost, dict):
        errs.append("estimated_monthly_cost_usd: must be an object")
    else:
        lo, hi = cost.get("min"), cost.get("max")
        if not _is_int(lo) or not _is_int(hi):
            errs.append("estimated_monthly_cost_usd: min and max must be integers")
        else:
            if lo < 0:
                errs.append("estimated_monthly_cost_usd.min: must be >= 0")
            if lo > hi:
                errs.append("estimated_monthly_cost_usd: min must be <= max")
        ca = cost.get("assumptions")
        if not _is_str_list(ca) or not ca or not all(x.strip() for x in ca):
            errs.append("estimated_monthly_cost_usd.assumptions: must be a non-empty list of non-empty strings")

    # warnings
    warns = result.get("warnings")
    if not isinstance(warns, list):
        errs.append("warnings: must be a list")
        warns = []
    keys = []
    for i, w in enumerate(warns):
        p = f"warnings[{i}]"
        if not isinstance(w, dict):
            errs.append(f"{p}: must be an object")
            continue
        if not isinstance(w.get("code"), str) or not w.get("code"):
            errs.append(f"{p}.code: must be a non-empty string")
        if w.get("severity") not in SEVERITIES:
            errs.append(f"{p}.severity: must be one of critical, warning, info")
        if not isinstance(w.get("message"), str) or not w.get("message"):
            errs.append(f"{p}.message: must be a non-empty string")
        if not _is_str_list(w.get("fields")):
            errs.append(f"{p}.fields: must be a list of strings")
        if w.get("severity") in SEVERITIES and isinstance(w.get("code"), str):
            keys.append((SEVERITIES.index(w["severity"]), w["code"]))
    if keys != sorted(keys):
        errs.append("warnings: must be sorted critical > warning > info, then by code")

    # assumptions / validation errors
    if not _is_str_list(result.get("assumptions")):
        errs.append("assumptions: must be a list of strings")
    verrs = result.get("validation_errors")
    if not isinstance(verrs, list):
        errs.append("validation_errors: must be a list")
        verrs = []
    for i, e in enumerate(verrs):
        if not (isinstance(e, dict) and isinstance(e.get("field"), str) and isinstance(e.get("message"), str)):
            errs.append(f"validation_errors[{i}]: must be {{field, message}} strings")
    if status == "invalid_input" and not verrs:
        errs.append("validation_errors: must be non-empty when status is invalid_input")
    if status in ("ok", "ok_with_warnings", "infeasible") and verrs:
        errs.append(f"validation_errors: must be empty when status is {status}")

    # status vs warning severities (D7)
    sev = {w.get("severity") for w in warns if isinstance(w, dict)}
    if status == "infeasible" and "critical" not in sev:
        errs.append("warnings: 'infeasible' needs at least one critical warning")
    if status == "ok" and sev & {"warning", "critical"}:
        errs.append("status: 'ok' must not carry warning or critical warnings")
    if status == "ok_with_warnings" and not sev & {"warning", "critical"}:
        errs.append("status: 'ok_with_warnings' needs at least one warning or critical warning")

    for k in ("compliance_notes", "integration_notes", "relaxed_constraints", "nearest_feasible"):
        if k in result and not isinstance(result[k], list):
            errs.append(f"{k}: must be a list")
    if "llm_used" in result and not isinstance(result["llm_used"], bool):
        errs.append("llm_used: must be a boolean")
    return errs

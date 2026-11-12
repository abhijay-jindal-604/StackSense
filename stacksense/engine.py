"""Recommendation pipeline (plan section 3.17). Phase 0 skeleton: validation only."""
from __future__ import annotations

from typing import Any

from . import output
from .io import LoadedScenario
from .validate import validate

INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


def _scenario_id(raw: Any) -> str | None:
    if isinstance(raw, dict) and isinstance(raw.get("scenario_id"), str):
        return raw["scenario_id"]
    return None


def _warning(code: str, severity: str, message: str, fields=()) -> dict:
    return {"code": code, "severity": severity, "message": message, "fields": list(fields)}


def recommend(raw: Any, *, fill_defaults: bool = False, trace: bool = True, llm=None) -> dict:
    """Return a section 4 result for one scenario. Never raises."""
    try:
        return _pipeline(raw, fill_defaults=fill_defaults, trace=trace, llm=llm)
    except Exception as exc:  # noqa: BLE001 - total function by contract
        return output.build(
            status="infeasible",
            scenario_id=_scenario_id(raw),
            summary="The engine hit an internal error, so no stack is recommended.",
            warnings=[_warning(INTERNAL_ERROR_CODE, "critical",
                               f"Internal error ({type(exc).__name__}). Please report this input.")],
        )


def is_internal_error(result: dict) -> bool:
    return any(w.get("code") == INTERNAL_ERROR_CODE for w in result.get("warnings", []))


def _pipeline(raw, *, fill_defaults, trace, llm) -> dict:
    # 1. validate
    v = validate(raw, fill_defaults=fill_defaults)
    sid = v.profile.get("scenario_id") if isinstance(v.profile, dict) else None
    if not isinstance(sid, str):
        sid = _scenario_id(raw)
    if v.errors:
        return output.build(status="invalid_input", scenario_id=sid, validation_errors=v.errors,
                            assumptions=v.assumptions, warnings=v.notices)
    # TODO(phase 2): 2. description.extract, existing.analyse, profile.derive
    # TODO(phase 2): 3. conflicts.detect; apply imply/relax/infeasible effects
    # TODO(phase 2): 4. per core layer: KB candidates -> filters.apply_hard -> scoring.rank
    # TODO(phase 2): 5. combine.search -> offerings.resolve
    # TODO(phase 2): 6. supporting.select, architecture.decide, cost.estimate, conflicts.post_checks
    # TODO(phase 2): 7. empty core layer / hard conflict -> nearest_feasible, infeasible
    # TODO(phase 2): 8. explain.*, status.decide, output.build, optional llm.reword
    warnings = list(v.notices) + [_warning(
        "ENGINE_NOT_IMPLEMENTED", "critical", "Recommendation logic is not built yet")]
    return output.build(status="infeasible", scenario_id=sid, stack=None,
                        warnings=warnings, assumptions=v.assumptions)


def recommend_loaded(loaded: LoadedScenario, **kw) -> dict:
    """Recommend for a scenario read by ``io.load_scenarios``; load errors become invalid_input."""
    if loaded.load_error is not None:
        return output.build(status="invalid_input", scenario_id=None,
                            validation_errors=[{"field": "$", "message": loaded.load_error}],
                            warnings=list(loaded.notices))
    result = recommend(loaded.raw, **kw)
    if loaded.notices and not is_internal_error(result):
        have = {(w.get("code"), w.get("message")) for w in result["warnings"]}
        extra = [n for n in loaded.notices if (n.get("code"), n.get("message")) not in have]
        if extra:
            result = dict(result)
            result["warnings"] = output.sort_warnings(result["warnings"] + extra)
    return result

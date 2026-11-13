"""Result status (decision D7, plan section 3.15).

* validation errors                                  -> ``invalid_input`` (stack null)
* hard-vs-hard contradiction / empty core layer      -> ``infeasible`` (stack null)
* any relaxed soft constraint                        -> ``ok_with_warnings``
* any warning of severity ``warning`` or ``critical`` -> ``ok_with_warnings``
* otherwise (no warnings, or only ``info``)          -> ``ok``
"""
from __future__ import annotations

ATTENTION_SEVERITIES = frozenset({"warning", "critical"})


def decide(errors, warnings, relaxed, feasible: bool) -> str:
    if errors:
        return "invalid_input"
    if not feasible:
        return "infeasible"
    if relaxed or any(w.get("severity") in ATTENTION_SEVERITIES for w in warnings or ()):
        return "ok_with_warnings"
    return "ok"

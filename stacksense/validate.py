"""Validation and normalisation of a scenario.

Policy (documented in the report):
* Wrong types, negative numbers, unknown enum values and out-of-range priorities are field-level
  validation errors -> status "invalid_input", stack null. Never raises.
* Missing *required* fields are validation errors by default. With ``fill_defaults=True`` (CLI
  ``--fill-defaults``, UI toggle) they are filled with documented conservative defaults and every
  fill is listed in ``assumptions``.
* Missing *optional* fields always get their documented default, recorded in ``assumptions``.
* Harmless normalisations (case/whitespace in enums, numeric availability 99.9 -> "99.9",
  duplicate list items, 3.0 -> 3) are accepted and recorded as assumptions.
* Unknown keys are ignored with an info warning, so files with extra fields still run.
"""
from __future__ import annotations

import difflib
import math
from typing import Any

from .schema import FIELDS, SECTIONS, TOP_LEVEL_ALLOWED

# Conservative defaults used only in fill_defaults mode for required fields.
REQUIRED_FALLBACKS = {
    "project.type": "web_app",
    "project.platforms": ["web"],
    "scale.users_at_launch": 1000,
    "scale.users_12_months": 10000,
    "team.size": 2,
    "team.experience": "intermediate",
    "team.languages": [],
    "budget.monthly_infra_usd": 100,
    "timeline.mvp_weeks": 12,
}

LANG_ALIASES = {
    "js": "javascript", "node": "javascript", "nodejs": "javascript", "node.js": "javascript",
    "ts": "typescript", "c#": "csharp", "c-sharp": "csharp", ".net": "csharp", "dotnet": "csharp",
    "golang": "go", "py": "python", "python3": "python", "c++": "cpp", "objective-c": "swift",
    "rb": "ruby", "elixir": "elixir", "html5": "html", "css3": "css", "postgres": "sql",
    "postgresql": "sql", "mysql": "sql", "t-sql": "sql", "tsql": "sql", "plsql": "sql",
}


def _get(d: Any, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _suggest(value, allowed):
    m = difflib.get_close_matches(str(value).lower(), [str(a) for a in allowed], n=1, cutoff=0.6)
    return f" Did you mean '{m[0]}'?" if m else ""


def validate(raw: Any, fill_defaults: bool = False):
    """Return (profile, errors, assumptions, notices).

    profile: flat dict path -> normalised value (None if invalid).
    errors: list of {field, message}.
    assumptions: list of strings.
    notices: list of warning dicts (info severity) about ignored/unknown input.
    """
    errors: list[dict] = []
    assumptions: list[str] = []
    notices: list[dict] = []
    profile: dict[str, Any] = {}

    if not isinstance(raw, dict):
        errors.append({"field": "$", "message": f"Scenario must be a JSON object, got {_type_name(raw)}."})
        return profile, errors, assumptions, notices

    # Unknown keys --------------------------------------------------------
    for key in sorted(raw.keys()):
        if key not in TOP_LEVEL_ALLOWED:
            notices.append({"code": "UNKNOWN_FIELD", "severity": "info",
                            "message": f"Top-level field '{key}' is not part of the schema and was ignored.",
                            "fields": [key]})
    for section in SECTIONS:
        sec = raw.get(section)
        if section == "compliance":
            continue
        if sec is None:
            continue
        if not isinstance(sec, dict):
            errors.append({"field": section, "message": f"'{section}' must be an object, got {_type_name(sec)}."})
            continue
        known = {p.split(".", 1)[1] for p in FIELDS if p.startswith(section + ".")}
        for key in sorted(sec.keys()):
            if key not in known:
                notices.append({"code": "UNKNOWN_FIELD", "severity": "info",
                                "message": f"Field '{section}.{key}' is not recognised and was ignored."
                                           + _suggest(key, sorted(known)),
                                "fields": [f"{section}.{key}"]})

    # Field by field ------------------------------------------------------
    for path, spec in FIELDS.items():
        present, value = _get(raw, path)
        if not present or (value is None and not spec["nullable"]):
            if present and value is None and spec["required"]:
                pass  # treat explicit null like missing for required fields
            if spec["required"]:
                if fill_defaults:
                    fb = REQUIRED_FALLBACKS[path]
                    profile[path] = fb
                    assumptions.append(f"DEFAULTED required field {path} = {fb!r} (missing in input; "
                                       f"--fill-defaults mode).")
                else:
                    errors.append({"field": path, "message": "Required field is missing."})
                    profile[path] = None
                continue
            default = spec["default"]
            profile[path] = list(default) if isinstance(default, list) else default
            if spec["extra"]:
                continue  # extras are silent when absent; summarised once below
            if path in ("project.name", "project.description"):
                continue
            if path == "scale.peak_concurrent_users" or path == "scale.data_volume_gb_12_months":
                continue  # derived later with explicit assumption
            if path == "requirements.p95_latency_ms":
                assumptions.append("requirements.p95_latency_ms not given: no explicit latency target; "
                                   "engine assumes interactive web norms (p95 < 1000 ms).")
                continue
            assumptions.append(f"{path} not given: default {default!r} applied.")
            continue

        ok, norm, note = _check_value(path, spec, value)
        if not ok:
            errors.append({"field": path, "message": note})
            profile[path] = None
        else:
            profile[path] = norm
            if note:
                assumptions.append(note)

    # p95 explicit null is allowed
    present, value = _get(raw, "requirements.p95_latency_ms")
    if present and value is None:
        assumptions.append("requirements.p95_latency_ms is null: no explicit latency target; engine assumes "
                           "interactive web norms (p95 < 1000 ms).")

    extras_used = sorted(p for p, s in FIELDS.items() if s["extra"] and _get(raw, p)[0])
    if extras_used:
        assumptions.append("StackSense extended inputs supplied: " + ", ".join(extras_used) + ".")
    else:
        assumptions.append("No StackSense extended inputs supplied; their documented defaults were used "
                           "(geographic_spread=single_country, lock_in_tolerance=medium, "
                           "consistency/data_shape inferred).")

    # Cross-field structural checks that make the input invalid --------
    plats = profile.get("project.platforms")
    if isinstance(plats, list) and len(plats) == 0:
        errors.append({"field": "project.platforms", "message": "At least one platform is required."})

    return profile, errors, assumptions, notices


def _check_value(path, spec, value):
    """Return (ok, normalised_value, note_or_error_message)."""
    t = spec["type"]
    if t == "string":
        if not isinstance(value, str):
            return False, None, f"Expected a string, got {_type_name(value)}."
        return True, value.strip(), None

    if t == "boolean":
        if isinstance(value, bool):
            return True, value, None
        hint = " Use JSON true/false without quotes." if isinstance(value, str) and value.lower() in (
            "true", "false", "yes", "no") else ""
        return False, None, f"Expected a boolean, got {_type_name(value)} {value!r}.{hint}"

    if t in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, None, f"Expected a {t}, got {_type_name(value)} {value!r}."
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False, None, "Number must be finite."
        note = None
        if t == "integer" and isinstance(value, float):
            if not value.is_integer():
                return False, None, f"Expected an integer, got {value!r}."
            note = f"{path}: {value!r} normalised to integer {int(value)}."
            value = int(value)
        mn, mx = spec["minimum"], spec["maximum"]
        if mn is not None:
            if spec["exclusive_min"] and value <= mn:
                return False, None, f"Must be greater than {mn}, got {value}."
            if not spec["exclusive_min"] and value < mn:
                return False, None, f"Must be >= {mn}, got {value}."
        if mx is not None and value > mx:
            return False, None, f"Must be <= {mx}, got {value}."
        return True, value, note

    if t == "enum":
        allowed = spec["enum"]
        if path == "requirements.availability" and isinstance(value, (int, float)) and not isinstance(value, bool):
            s = ("%g" % value)
            if s in allowed:
                return True, s, f"{path}: numeric {value!r} normalised to string \"{s}\"."
            return False, None, f"Unknown value {value!r}. Allowed: {', '.join(allowed)}."
        if not isinstance(value, str):
            return False, None, f"Expected one of {', '.join(allowed)}, got {_type_name(value)} {value!r}."
        if value in allowed:
            return True, value, None
        low = value.strip().lower()
        if low in allowed:
            return True, low, f"{path}: '{value}' normalised to '{low}'."
        return False, None, f"Unknown value '{value}'. Allowed: {', '.join(allowed)}.{_suggest(value, allowed)}"

    if t == "list":
        if not isinstance(value, list):
            return False, None, f"Expected a list, got {_type_name(value)}."
        out, notes, bad = [], [], []
        for i, item in enumerate(value):
            if not isinstance(item, str):
                bad.append(f"item {i} must be a string, got {_type_name(item)}")
                continue
            v = item.strip()
            if spec["item_enum"]:
                low = v.lower()
                if low not in spec["item_enum"]:
                    bad.append(f"unknown value '{item}' (allowed: {', '.join(spec['item_enum'])})"
                               + _suggest(item, spec["item_enum"]).rstrip())
                    continue
                if low != v:
                    notes.append(f"'{item}'->'{low}'")
                v = low
            elif path == "team.languages":
                low = v.lower()
                mapped = LANG_ALIASES.get(low, low)
                if mapped != v:
                    notes.append(f"'{item}'->'{mapped}'")
                v = mapped
            if v not in out:
                out.append(v)
            else:
                notes.append(f"duplicate '{item}' removed")
        if bad:
            return False, None, "; ".join(bad) + "."
        return True, out, (f"{path} normalised: " + ", ".join(notes) + ".") if notes else None

    return False, None, f"Unsupported type {t}"

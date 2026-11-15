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
* Hostile input is bounded: strings over 4000 characters, lists over 50 items and numbers above 1e12
  are validation errors. ``validate`` is a total function and never raises.
"""
from __future__ import annotations

import difflib
import math
from dataclasses import dataclass, field
from typing import Any

from .schema import FIELDS, SECTIONS, TOP_LEVEL_ALLOWED

MAX_STR = 4000
MAX_LIST = 50
MAX_NUM = 1e12

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
    "golang": "go", "py": "python", "python3": "python", "c++": "cpp", "objc": "objective-c", "obj-c": "objective-c",
    "rb": "ruby", "elixir": "elixir", "html5": "html", "css3": "css", "postgres": "sql",
    "postgresql": "sql", "mysql": "sql", "t-sql": "sql", "tsql": "sql", "plsql": "sql",
}



@dataclass(frozen=True)
class Validated:
    """Result of validate().

    profile: flat dict path -> normalised value (None where invalid), plus "scenario_id".
    errors: list of {field, message}.  assumptions: list of strings.
    notices: list of {code, severity, message, fields}.
    provided: schema paths explicitly present in the input (null on a non-nullable field counts as absent).
    """
    profile: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    provided: frozenset = frozenset()


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


def _a(noun: str) -> str:
    return ("an " if noun[:1] in "aeiou" else "a ") + noun


def _short(v) -> str:
    try:
        r = repr(v)
    except Exception:  # pragma: no cover - hostile objects
        return "<unprintable>"
    return r if len(r) <= 60 else r[:57] + "..."


def _suggest(value, allowed):
    try:
        m = difflib.get_close_matches(str(value)[:100].lower(), [str(a) for a in allowed], n=1, cutoff=0.6)
    except Exception:  # pragma: no cover
        return ""
    return f" Did you mean '{m[0]}'?" if m else ""


def validate(raw: Any, fill_defaults: bool = False) -> Validated:
    """Validate and normalise a scenario. Total function: never raises."""
    try:
        return _validate(raw, fill_defaults)
    except Exception as exc:  # pragma: no cover - safety net for hostile input
        return Validated({}, [{"field": "$", "message": f"Input could not be processed ({type(exc).__name__})."}],
                         [], [], frozenset())


def _validate(raw: Any, fill_defaults: bool) -> Validated:
    errors: list[dict] = []
    assumptions: list[str] = []
    notices: list[dict] = []
    profile: dict[str, Any] = {}
    provided: set[str] = set()

    profile["scenario_id"] = None
    if not isinstance(raw, dict):
        errors.append({"field": "$", "message": f"Scenario must be a JSON object, got {_type_name(raw)}."})
        return Validated(profile, errors, assumptions, notices, frozenset())

    # scenario_id ---------------------------------------------------------
    sid = raw.get("scenario_id")
    if sid is None:
        profile["scenario_id"] = None
    elif isinstance(sid, str):
        profile["scenario_id"] = sid.strip()[:MAX_STR] or None
        if len(sid) > MAX_STR:
            errors.append({"field": "scenario_id", "message": f"Text is too long ({len(sid)} characters; maximum {MAX_STR})."})
    elif isinstance(sid, int) and not isinstance(sid, bool) and abs(sid) <= MAX_NUM:
        profile["scenario_id"] = str(sid)
        assumptions.append(f"scenario_id: number {sid} converted to string \"{sid}\".")
    else:
        profile["scenario_id"] = None
        errors.append({"field": "scenario_id",
                       "message": f"scenario_id must be a string, got {_type_name(sid)} {_short(sid)}."})

    # Unknown keys --------------------------------------------------------
    for key in sorted(str(k) for k in raw.keys()):
        if key not in TOP_LEVEL_ALLOWED:
            notices.append({"code": "UNKNOWN_FIELD", "severity": "info",
                            "message": f"Top-level field '{key[:100]}' is not part of the schema and was ignored.",
                            "fields": [key[:100]]})
    bad_sections: set[str] = set()
    for section in SECTIONS:
        sec = raw.get(section)
        if section == "compliance" or sec is None:
            continue
        if not isinstance(sec, dict):
            bad_sections.add(section)
            errors.append({"field": section, "message": f"'{section}' must be an object, got {_type_name(sec)}."})
            continue
        known = {p.split(".", 1)[1] for p in FIELDS if p.startswith(section + ".")}
        for key in sorted(str(k) for k in sec.keys()):
            if key not in known:
                notices.append({"code": "UNKNOWN_FIELD", "severity": "info",
                                "message": f"Field '{section}.{key[:100]}' is not recognised and was ignored."
                                           + _suggest(key, sorted(known)),
                                "fields": [f"{section}.{key[:100]}"]})

    # Field by field ------------------------------------------------------
    deferred_growth = False
    for path, spec in FIELDS.items():
        section = path.split(".", 1)[0]
        present, value = _get(raw, path)
        if section in bad_sections:
            # Section already reported once; no cascade of "missing" errors.
            profile[path] = None if spec["required"] else _copy_default(spec["default"])
            continue
        if present and value is None and spec["nullable"]:
            provided.add(path)
            profile[path] = None
            if path == "requirements.p95_latency_ms":
                assumptions.append("requirements.p95_latency_ms is null: no explicit latency target; engine "
                                   "assumes interactive web norms (p95 < 1000 ms).")
            continue
        if not present or value is None:
            if spec["required"]:
                if fill_defaults:
                    fb = REQUIRED_FALLBACKS[path]
                    profile[path] = list(fb) if isinstance(fb, list) else fb
                    assumptions.append(f"DEFAULTED required field {path} = {fb!r} (missing in input; "
                                       f"--fill-defaults mode).")
                else:
                    errors.append({"field": path, "message": "Required field is null." if present
                                   else "Required field is missing."})
                    profile[path] = None
                continue
            if path == "team.growth_12_months":
                deferred_growth = True
                profile[path] = None
                continue
            default = spec["default"]
            profile[path] = _copy_default(default)
            if spec["extra"] or path in ("project.name", "project.description",
                                         "scale.peak_concurrent_users", "scale.data_volume_gb_12_months"):
                continue  # silent / derived later with an explicit assumption
            if path == "requirements.p95_latency_ms":
                assumptions.append("requirements.p95_latency_ms not given: no explicit latency target; "
                                   "engine assumes interactive web norms (p95 < 1000 ms).")
                continue
            assumptions.append(f"{path} not given: default {default!r} applied.")
            continue

        provided.add(path)
        ok, norm, note = _check_value(path, spec, value)
        if not ok:
            errors.append({"field": path, "message": note})
            profile[path] = None
        else:
            profile[path] = norm
            if note:
                assumptions.append(note)

    if deferred_growth:
        size = profile.get("team.size")
        profile["team.growth_12_months"] = size if isinstance(size, int) else None
        if isinstance(size, int):
            assumptions.append(f"team.growth_12_months not given: defaulted to team.size ({size}).")

    extras_used = sorted(p for p, s in FIELDS.items() if s["extra"] and p in provided)
    if extras_used:
        assumptions.append("StackSense extended inputs supplied: " + ", ".join(extras_used) + ".")
    else:
        assumptions.append("No StackSense extended inputs supplied; their documented defaults were used "
                           "(geographic_spread=single_country, lock_in_tolerance=medium, "
                           "team.growth_12_months=team.size, consistency/data_shape inferred).")

    # Cross-field structural checks that make the input invalid --------
    plats = profile.get("project.platforms")
    if isinstance(plats, list) and len(plats) == 0 and "project" not in bad_sections \
            and not any(e["field"] == "project.platforms" for e in errors):
        errors.append({"field": "project.platforms", "message": "At least one platform is required."})

    # Cross-field notices (not errors) -----------------------------------
    launch, u12 = profile.get("scale.users_at_launch"), profile.get("scale.users_12_months")
    peak = profile.get("scale.peak_concurrent_users")
    if isinstance(launch, (int, float)) and isinstance(u12, (int, float)) and u12 < launch:
        notices.append({"code": "SCALE_INCONSISTENT", "severity": "warning",
                        "message": f"users_12_months ({u12}) is lower than users_at_launch ({launch}); "
                                   f"sizing used the larger figure.",
                        "fields": ["scale.users_at_launch", "scale.users_12_months"]})
    if isinstance(peak, (int, float)) and isinstance(u12, (int, float)) and peak > u12:
        notices.append({"code": "SCALE_INCONSISTENT", "severity": "warning",
                        "message": f"peak_concurrent_users ({peak}) is higher than users_12_months ({u12}); "
                                   f"sizing used the larger figure.",
                        "fields": ["scale.peak_concurrent_users", "scale.users_12_months"]})
    if isinstance(plats, list) and "api_only" in plats and len(plats) > 1:
        others = ", ".join(x for x in plats if x != "api_only")
        notices.append({"code": "API_ONLY_WITH_CLIENTS", "severity": "info",
                        "message": f"api_only listed with {others}: treating the API as a first-party public "
                                   f"surface in addition to the clients.",
                        "fields": ["project.platforms"]})

    return Validated(profile, errors, assumptions, notices, frozenset(provided))


def _copy_default(default):
    return list(default) if isinstance(default, list) else default


def _check_value(path, spec, value):
    """Return (ok, normalised_value, note_or_error_message)."""
    t = spec["type"]
    if t == "string":
        if not isinstance(value, str):
            return False, None, f"Expected a string, got {_type_name(value)} {_short(value)}."
        if len(value) > MAX_STR:
            return False, None, f"Text is too long ({len(value)} characters; maximum {MAX_STR})."
        return True, value.strip(), None

    if t == "boolean":
        if isinstance(value, bool):
            return True, value, None
        hint = " Use JSON true/false without quotes." if isinstance(value, str) and value.lower() in (
            "true", "false", "yes", "no") else ""
        return False, None, f"Expected a boolean, got {_type_name(value)} {_short(value)}.{hint}"

    if t in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            hint = " Use a JSON number without quotes." if isinstance(value, str) else ""
            return False, None, f"Expected {_a(t)}, got {_type_name(value)} {_short(value)}.{hint}"
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False, None, "Number must be finite (NaN and Infinity are not allowed)."
        if abs(value) > MAX_NUM:
            return False, None, "Number is too large (maximum 1e12)."
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
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                return False, None, "Number must be finite (NaN and Infinity are not allowed)."
            if abs(value) > MAX_NUM:
                return False, None, "Number is too large (maximum 1e12)."
            for a in allowed:
                if value == float(a):
                    return True, a, f"{path}: numeric {_short(value)} normalised to string \"{a}\"."
            return False, None, f"Unknown value {_short(value)}. Allowed: {', '.join(allowed)}."
        if not isinstance(value, str):
            return False, None, f"Expected one of {', '.join(allowed)}, got {_type_name(value)} {_short(value)}."
        if len(value) > MAX_STR:
            return False, None, f"Text is too long ({len(value)} characters; maximum {MAX_STR})."
        if value in allowed:
            return True, value, None
        low = value.strip().lower()
        if low in allowed:
            return True, low, f"{path}: '{value}' normalised to '{low}'."
        return False, None, f"Unknown value '{value[:60]}'. Allowed: {', '.join(allowed)}.{_suggest(value, allowed)}"

    if t == "list":
        if not isinstance(value, list):
            return False, None, f"Expected a list, got {_type_name(value)}."
        if len(value) > MAX_LIST:
            return False, None, f"List is too long ({len(value)} items; maximum {MAX_LIST})."
        out, notes, bad = [], [], []
        for i, item in enumerate(value):
            if not isinstance(item, str):
                bad.append(f"item {i} must be a string, got {_type_name(item)}")
                continue
            if len(item) > MAX_STR:
                bad.append(f"item {i} is too long ({len(item)} characters; maximum {MAX_STR})")
                continue
            v = item.strip()
            if not v:
                if "blank items removed" not in notes:
                    notes.append("blank items removed")
                continue
            if spec["item_enum"]:
                low = v.lower()
                if low not in spec["item_enum"]:
                    bad.append(f"Unknown value '{item[:60]}'. Allowed: {', '.join(spec['item_enum'])}."
                               + _suggest(item, spec["item_enum"]).rstrip())
                    continue
                if low != item:
                    notes.append(f"'{item}'->'{low}'")
                v = low
            elif path == "team.languages":
                low = v.lower()
                mapped = LANG_ALIASES.get(low, low)
                if mapped != item:
                    notes.append(f"'{item}'->'{mapped}'")
                v = mapped
            if v not in out:
                out.append(v)
            else:
                notes.append(f"duplicate '{item}' removed")
        if bad:
            return False, None, " ".join((b[:1].upper() + b[1:]) + ("" if b[-1] in ".?" else ".") for b in bad)
        if not out and value and not bad:
            return False, None, "List contains only blank items; give at least one non-empty value."
        return True, out, (f"{path} normalised: " + ", ".join(notes) + ".") if notes else None

    return False, None, f"Unsupported type {t}"

"""Scenario loading and result writing.

Invariant: ``load_scenarios`` never raises on bad content. Every problem
becomes a ``LoadedScenario`` with ``load_error`` set, which callers turn into
an ``invalid_input`` result (see ``output.invalid_input_result``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NamedTuple

from . import output

MAX_BYTES = 5 * 1024 * 1024


class LoadedScenario(NamedTuple):
    """One scenario read from disk.

    source_name: file name; array elements are ``name.json[i]``.
    raw: the parsed object (None when load_error is set).
    load_error: human-readable message, or None.
    notices: list of warning-shaped dicts ``{code, severity, message, fields}``
        (currently only ``DUPLICATE_KEY`` info notices). For an array file the
        file's notices are attached to every element. May be empty.
    """

    source_name: str
    raw: Any | None
    load_error: str | None
    notices: list


def _fail(name: str, msg: str) -> LoadedScenario:
    return LoadedScenario(name, None, msg, [])


def _parse_text(text: str) -> tuple[Any, list]:
    """Parse JSON text; raises ValueError (incl. JSONDecodeError) on failure."""
    dups: list[str] = []

    def hook(pairs: list[tuple[str, Any]]) -> dict:
        d: dict = {}
        for k, v in pairs:
            if k in d and k not in dups:
                dups.append(k)
            d[k] = v  # last wins
        return d

    def bad_const(tok: str) -> Any:
        raise ValueError(f"non-finite number literal {tok} is not allowed")

    value = json.loads(text, object_pairs_hook=hook, parse_constant=bad_const)
    notices = [
        {
            "code": "DUPLICATE_KEY",
            "severity": "info",
            "message": f"Key '{k}' appears more than once in the file; the last value was used.",
            "fields": [],
        }
        for k in dups
    ]
    return value, notices


def _load_file(path: Path) -> list[LoadedScenario]:
    name = path.name
    try:
        size = path.stat().st_size
    except OSError as e:
        return [_fail(name, f"Cannot read file: {e.strerror or e}")]
    if size > MAX_BYTES:
        return [_fail(name, f"File is {size} bytes; the limit is {MAX_BYTES} bytes (5 MB).")]
    try:
        data = path.read_bytes()
    except OSError as e:
        return [_fail(name, f"Cannot read file: {e.strerror or e}")]
    return load_bytes(name, data)


def load_bytes(name: str, data: bytes) -> list[LoadedScenario]:
    """Parse scenario JSON bytes (a file's content or standard input) under the label ``name``."""
    if len(data) > MAX_BYTES:
        return [_fail(name, f"Input is {len(data)} bytes; the limit is {MAX_BYTES} bytes (5 MB).")]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return [_fail(name, f"File is not valid UTF-8 (byte {e.start}).")]
    if not text.strip():
        return [_fail(name, "File is empty.")]
    try:
        value, notices = _parse_text(text)
    except json.JSONDecodeError as e:
        return [_fail(name, f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}.")]
    except (ValueError, RecursionError) as e:
        return [_fail(name, f"Invalid JSON: {e}")]
    if isinstance(value, dict):
        return [LoadedScenario(name, value, None, notices)]
    if isinstance(value, list):
        if not value:
            return [_fail(name, "File contains an empty array; expected at least one scenario object.")]
        out = []
        for i, el in enumerate(value):
            label = f"{name}[{i}]"
            if isinstance(el, dict):
                out.append(LoadedScenario(label, el, None, list(notices)))
            else:
                out.append(_fail(label, f"Element {i} is {_type_name(el)}, expected a JSON object."))
        return out
    return [_fail(name, f"Top-level JSON value is {_type_name(value)}, expected an object or an array of objects.")]


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "a boolean"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "a string"
    if isinstance(v, list):
        return "an array"
    return "an object"


def load_scenarios(path: Path) -> list[LoadedScenario]:
    """Load one scenario file (object or array) or every ``*.json`` in a directory (sorted by name)."""
    path = Path(path)
    try:
        if path.is_dir():
            out: list[LoadedScenario] = []
            for f in sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".json"):
                out.extend(_load_file(f))
            return out
        if path.is_file():
            return _load_file(path)
    except OSError as e:
        return [_fail(path.name, f"Cannot read path: {e.strerror or e}")]
    return [_fail(path.name or str(path), "Path does not exist.")]


_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def output_name(scenario_id: str | None, source_name: str, index: int | None) -> str:
    """File name for a result: ``<id>_output.json``, else ``<stem>[_<index>]_output.json``."""
    if isinstance(scenario_id, str):
        sid = _SAFE.sub("_", scenario_id.strip())[:100].strip(".")
        if sid:
            return f"{sid}_output.json"
    stem = re.sub(r"\[\d+\]$", "", source_name)
    stem = re.sub(r"\.json$", "", stem, flags=re.IGNORECASE)
    stem = _SAFE.sub("_", stem)[:100].strip(".") or "scenario"
    if index is not None:
        stem = f"{stem}_{index}"
    return f"{stem}_output.json"


def write_output(result: dict, out_dir: Path, name: str) -> Path:
    """Write ``result`` to ``out_dir/name`` (created if needed) using ``output.dumps``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / Path(name).name
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(output.dumps(result))
    return target

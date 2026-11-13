"""Deterministic description signals (plan section 3.4).

``extract(description)`` turns ``project.description`` into a tuple of :class:`Signal` records using
the keyword/regex table in ``kb/keywords.py`` (plan section 6.5): case-insensitive, word-boundary
matched, evaluated in table order. A signal may add a supporting need or an info warning, or set an
inferred value for a field that is ``auto``/absent; it never overrides an explicitly provided field.

Negated mentions ("no payments", "without chat") do not fire a rule. Output order is table order, one
signal per rule id (the first non-negated match of the first matching pattern).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .kb.keywords import RULES


@dataclass(frozen=True)
class Signal:
    """One matched description rule.

    id: rule id from kb/keywords.py (for example ``ledger``, ``booking``, ``sensors``).
    matched_text: the exact substring of the description that matched.
    effect: short machine-readable effect, for example ``consistency=strong``.
    fields: schema paths the signal relates to (tuple, for DESCRIPTION_MISMATCH and driven_by).
    """
    id: str
    matched_text: str
    effect: str
    fields: tuple[str, ...] = ()


Signals = tuple[Signal, ...]


_NEGATION = re.compile(r"\b(?:no|not|without|never|nor|zero|neither|excluding|except)\b(?:\W+\w+){0,2}\W*$",
                       re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[.;:!?\n]|\b(?:but|however|although)\b|,\s*(?:and|but)\b", re.IGNORECASE)
_COMPILED = None


def _compiled():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = tuple((r, tuple(re.compile(p, re.IGNORECASE) for p in r.patterns)) for r in RULES)
    return _COMPILED


def _negated(text: str, start: int) -> bool:
    before = text[max(0, start - 40):start]
    cut = 0
    for m in _CLAUSE_BREAK.finditer(before):
        cut = m.end()
    return bool(_NEGATION.search(before[cut:]))


def extract(description: str | None) -> Signals:
    """Return the signals found in ``description`` (pure, deterministic, table order)."""
    if not isinstance(description, str) or not description.strip():
        return ()
    out: list[Signal] = []
    seen: set[str] = set()
    for rule, pats in _compiled():
        if rule.id in seen:
            continue
        for pat in pats:
            hit = next((m for m in pat.finditer(description) if not _negated(description, m.start())), None)
            if hit:
                seen.add(rule.id)
                out.append(Signal(rule.id, hit.group(0), rule.effect, rule.fields))
                break
    return tuple(out)

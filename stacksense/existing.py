"""Existing-system analysis (plan section 3.5).

``analyse(systems, today_anchor)`` matches each ``infrastructure.existing_systems`` string against
the patterns in ``kb/existing_patterns.py`` (plan section 6.6) and returns an :class:`ExistingReport`.
``today_anchor`` defaults to the KB date constant (``kb.eol.KB_DATE``), never the system clock.

Unmatched systems (input order) are returned in ``unmatched``; the engine turns each
unmatched system into an ``EXISTING_SYSTEM_UNRECOGNISED`` info warning and a generic integration
note, so nothing is ignored silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .kb import eol, existing_patterns


@dataclass(frozen=True)
class ExistingMatch:
    """One recognised existing system.

    raw: the input string. pattern_id: matching pattern. family: identity/database/framework/
    messaging/saas/infrastructure. kind: product kind (for example ``sqlserver``). version: captured
    version or None. reuse_targets: layers/candidate ids it can be reused as. integration_note:
    plain-language note. eol: EOL verdict dict (or None) from kb/eol.py.
    """
    raw: str
    pattern_id: str
    family: str
    kind: str
    version: str | None = None
    reuse_targets: tuple[str, ...] = ()
    integration_note: str = ""
    eol: dict | None = None


@dataclass(frozen=True)
class ExistingReport:
    matches: tuple[ExistingMatch, ...] = ()
    unmatched: tuple[str, ...] = ()


def analyse(systems, today_anchor: date | None = None) -> ExistingReport:
    """Classify existing systems (deterministic; the clock is never read).

    Strings are processed in input order. Every pattern hit becomes one :class:`ExistingMatch`
    (pattern-table order within a string), so "On-prem SQL Server 2019" yields a ``sqlserver`` match
    (version 2019, EOL verdict) and an ``on_prem`` infrastructure match. Both keep the same ``raw``.
    A string with no hit goes to ``unmatched``. The EOL verdict is judged on ``today_anchor``
    (default ``kb.eol.KB_DATE``); the verdict dict carries that date under ``anchor``.
    """
    anchor = today_anchor or eol.KB_DATE
    matches: list[ExistingMatch] = []
    unmatched: list[str] = []
    for raw in (systems or ()):
        if not isinstance(raw, str) or not raw.strip():
            continue
        hits = existing_patterns.match(raw)
        if not hits:
            unmatched.append(raw)
            continue
        for h in hits:
            pat = existing_patterns.BY_ID[h.pattern_id]
            args = existing_patterns.eol_args(h)
            verdict = eol.verdict(args[0], args[1], anchor=anchor) if args else None
            note = f"{raw}: {pat.note}" if pat.note else ""
            matches.append(ExistingMatch(raw=raw, pattern_id=h.pattern_id, family=h.family, kind=h.kind,
                                         version=h.version, reuse_targets=tuple(pat.reuse),
                                         integration_note=note, eol=verdict))
    return ExistingReport(matches=tuple(matches), unmatched=tuple(unmatched))

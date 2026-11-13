"""Existing-system analysis (plan section 3.5).

``analyse(systems, today_anchor)`` matches each ``infrastructure.existing_systems`` string against
the patterns in ``kb/existing_patterns.py`` (plan section 6.6) and returns an :class:`ExistingReport`.
``today_anchor`` defaults to the KB date constant (``kb.eol.KB_DATE``), never the system clock.

STATUS: interface only. The pattern table is filled in Phase 4; until then every system is returned
in ``unmatched`` (input order, which validate() already de-duplicated). Later stages turn each
unmatched system into an ``EXISTING_SYSTEM_UNRECOGNISED`` info warning and a generic integration
note, so nothing is ignored silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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
    """Classify existing systems. Placeholder until Phase 4: everything is ``unmatched``."""
    items = tuple(str(s) for s in (systems or ()) if isinstance(s, str) and s.strip())
    return ExistingReport(matches=(), unmatched=items)

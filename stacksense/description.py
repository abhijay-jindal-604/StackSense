"""Deterministic description signals (plan section 3.4).

``extract(description)`` turns ``project.description`` into a tuple of :class:`Signal` records using
the keyword/regex table in ``kb/keywords.py`` (plan section 6.5): case-insensitive, word-boundary
matched, evaluated in table order. A signal may add a supporting need or an info warning, or set an
inferred value for a field that is ``auto``/absent; it never overrides an explicitly provided field.

STATUS: interface only. The rule table is filled in Phase 3; until then ``extract`` returns ``()``
for every input, so the rest of the pipeline (``profile.derive`` and later stages) can already be
coded and tested against the final types.
"""
from __future__ import annotations

from dataclasses import dataclass


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


def extract(description: str | None) -> Signals:
    """Return the signals found in ``description``.

    Placeholder until Phase 3: always returns an empty tuple. Pure and deterministic.
    """
    return ()

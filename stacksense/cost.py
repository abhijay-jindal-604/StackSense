"""Monthly cost estimate and budget verdict (plan sections 3.13 and 7).

``estimate(p, components, extra_lines=())`` returns a :class:`Cost`:

* one :class:`CostLine` per chosen core component (frontend, frontend host, backend, database, host),
  priced from the component's KB band at the profile size class (``kb.costs.band_for``). When a
  managed or self-managed database offering (``kb.offerings``) is given, its band replaces the engine
  band. Components billed as one plan (:data:`BUNDLED_BILLS`, for example a Supabase project that is
  backend, database and host at once) become one line, so nothing is counted twice.
* ``extra_lines``: further :class:`CostLine` objects appended unchanged (Phase 3: supporting services,
  usage lines, compliance overhead).
* the total band: sum of line mins and maxes, each rounded to two significant figures (``round_sig``),
  in USD per month (``CURRENCY_NOTE``).
* the budget verdict against ``budget.monthly_infra_usd`` and warning dicts ``{code, severity,
  message, fields}``: ``BUDGET_EXCEEDED`` (critical), ``BUDGET_TIGHT`` (warning), ``BUDGET_HEADROOM``
  and ``FREE_TIER_LIMITS`` (info). An estimate above the budget is never silent.

``components`` is a mapping; keys (all optional): ``frontend`` (record or list of records, one per
platform), ``frontend_hosting``, ``backend``, ``database``, ``database_offering``, ``hosting``. Values
may be KB dicts or :class:`~stacksense.scoring.Scored`. A ``none`` backend/database is skipped.

TODO(phase 3):
* supporting-service band lines and usage lines (object storage, egress, SMS OTP) via ``extra_lines``
  (or a ``supporting=`` argument building them with :func:`band_line`);
* availability and traffic multipliers (``kb.costs.AVAILABILITY_MULTIPLIERS``, ``TRAFFIC_MULTIPLIERS``,
  ``FAILOVER_TOOLING_SHARE``) applied to compute/database lines before summing (``CostLine.role``
  already tells compute from database);
* compliance overhead lines (``COMPLIANCE_OVERHEAD``) and the on-premise hardware formula
  (``ONPREM_*``);
* the budget fallback of plan 7 (top ``BUDGET_FALLBACK_TOP_N`` combinations, accept at
  ``BUDGET_FALLBACK_ACCEPT_RATIO``) lives in ``combine.py``: it calls :func:`estimate` per candidate
  combination and compares ``Cost.min`` with the budget; when no fallback exists, the engine adds the
  ``RELAXED: budget.monthly_infra_usd ...`` assumption and the cheapest-stack sentence to
  ``BUDGET_EXCEEDED``;
* ``ZERO_BUDGET_SCALE`` belongs to ``conflicts.py``.

Pure and deterministic: no clock, no randomness; lines keep input order, bundles sort by id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .kb import costs as _costs
from .kb.model import SIZE_CLASSES, size_index
from .scoring import Scored, _size_text, fmt, val

CURRENCY = "USD"
PERIOD = "month"
BUDGET_FIELD = "budget.monthly_infra_usd"
VERDICTS = ("within", "tight", "exceeded", "free_tier_only", "headroom")

# Core component slots in output order, with the cost role used by Phase 3 multipliers.
CORE_SLOTS: tuple[tuple[str, str], ...] = (
    ("frontend", "code"), ("frontend_hosting", "compute"), ("backend", "compute"),
    ("database", "database"), ("hosting", "compute"),
)
NONE_KINDS = ("none",)

# Products billed as one plan: the KB bands of the members are estimates of the same bill, so they
# merge into one line (band = largest min, largest max) instead of being summed.
BUNDLED_BILLS: tuple[tuple[frozenset, str], ...] = (
    (frozenset({"supabase", "supabase_cloud", "postgres__supabase"}),
     "one Supabase project plan covers the API, Postgres database, auth, storage and hosting"),
    (frozenset({"firebase", "firestore__gcp"}),
     "Firebase (Blaze) bills Cloud Functions and Firestore usage on one pay-as-you-go plan"),
    (frozenset({"shopify", "shopify_hosted"}),
     "the Shopify subscription covers both the commerce backend and its hosting"),
    (frozenset({"cloudflare_workers_hono", "cloudflare_workers_host"}),
     "the Workers code and the Workers host are the same Workers Paid usage"),
    (frozenset({"aws_lambda_apigw", "aws_lambda_host"}),
     "the Lambda functions and their Lambda/API Gateway host are the same usage bill"),
)


@dataclass(frozen=True)
class CostLine:
    """One priced item. ``min``/``max`` in USD per month (unrounded)."""
    slot: str                         # frontend | frontend_hosting | backend | database | hosting | <layer> | usage
    component_id: str                 # record id, offering id, or "a+b" for a bundle
    name: str
    min: float
    max: float
    basis: str                        # plain-language: where the numbers come from
    source_keys: tuple[str, ...] = ()
    role: str = "compute"             # code | compute | database | service | usage | overhead
    derived: bool = False             # band not listed at this size (xl from l x 3, or nearest size)
    free_tier: dict | None = None     # record free_tier when the band starts at USD 0
    members: tuple[str, ...] = ()     # bundled component ids

    def as_dict(self) -> dict:
        return {"slot": self.slot, "component_id": self.component_id, "name": self.name,
                "min": self.min, "max": self.max, "basis": self.basis,
                "source_keys": list(self.source_keys), "role": self.role, "derived": self.derived,
                **({"members": list(self.members)} if self.members else {})}


@dataclass(frozen=True)
class Cost:
    min: int
    max: int
    size: str
    lines: tuple[CostLine, ...]
    assumptions: tuple[str, ...]
    budget: float | None
    verdict: str                      # one of VERDICTS
    warnings: tuple[dict, ...] = ()
    currency: str = CURRENCY
    period: str = PERIOD

    def to_output(self) -> dict:
        """``estimated_monthly_cost_usd`` block of statement section 4."""
        return {"min": self.min, "max": self.max, "assumptions": list(self.assumptions)}

    def budget_verdict(self) -> dict:
        """``budget_verdict`` extra output field (plan D12)."""
        return {"verdict": self.verdict, "budget_usd": self.budget, "estimate_min": self.min,
                "estimate_max": self.max, "currency": self.currency}

    def trace(self) -> list[dict]:
        """``decision_trace.cost_lines``."""
        return [ln.as_dict() for ln in self.lines]


# ------------------------------------------------------------------ helpers
def _rec(x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, Scored):
        return x.tech
    if isinstance(x, dict):
        return x
    tech = getattr(x, "tech", None)
    return tech if isinstance(tech, dict) else (dict(x) if isinstance(x, Mapping) else None)


def _many(x) -> list[dict]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [r for r in (_rec(i) for i in x) if r is not None]
    r = _rec(x)
    return [r] if r is not None else []


def _n(x: float) -> str:
    x = round(float(x), 2)
    return f"{int(x):,}" if x.is_integer() else f"{x:,.2f}"


def _pricing_sources(rec: dict) -> tuple[str, ...]:
    src = list(rec.get("sources") or [])
    src += [f["source_key"] for f in rec.get("facts") or [] if f.get("text", "").startswith("Cost")]
    pricing = sorted({k for k in src if "pricing" in k})
    return tuple(pricing) if pricing else tuple(sorted(set(src)))


def band(cost: Mapping, size: str) -> tuple[float, float, bool, str]:
    """``(min, max, derived, note)`` for ``size``. When the band is missing at that size, use the
    nearest larger listed size (a floor above the project: you pay its minimum), else the nearest
    smaller one; ``derived`` is then True and ``note`` says so. No band at all -> (0, 0, True, note)."""
    got = _costs.band_for(dict(cost or {}), size)
    if got is not None:
        lo, hi, derived = got
        note = (f"size xl is not listed: l band x {_costs.XL_FROM_L_FACTOR} (quote needed)" if derived else "")
        return lo, hi, derived, note
    idx = size_index(size)
    order = [s for s in SIZE_CLASSES[idx + 1:]] + [s for s in reversed(SIZE_CLASSES[:idx])]
    for s in order:
        b = (cost or {}).get(s)
        if b is not None:
            return b[0], b[1], True, f"no band listed at size {size}; the size {s} band is used"
    return 0, 0, True, "no cost band in the knowledge base"


def band_line(rec: dict, size: str, slot: str, role: str, basis: str | None = None) -> CostLine:
    """A line priced from a record's or offering's cost band (also used by Phase 3 for services)."""
    lo, hi, derived, note = band(rec.get("cost") or {}, size)
    text = basis or f"KB cost band at size {size}"
    if note:
        text += f" ({note})"
    ft = rec.get("free_tier") if lo == 0 and rec.get("saas") else None
    return CostLine(slot=slot, component_id=rec["id"], name=rec["name"], min=lo, max=hi, basis=text,
                    source_keys=_pricing_sources(rec), role=role, derived=derived,
                    free_tier=ft if ft and ft.get("limit") else None)


def _bundle_lines(lines: list[CostLine]) -> tuple[list[CostLine], list[str]]:
    """Merge lines whose components are billed as one plan; drop exact duplicates."""
    notes: list[str] = []
    out: list[CostLine] = []
    seen: set[str] = set()
    for ln in lines:                                   # duplicates (same host for frontend and backend)
        if ln.component_id in seen:
            continue
        seen.add(ln.component_id)
        out.append(ln)
    for members, why in BUNDLED_BILLS:
        hit = [ln for ln in out if ln.component_id in members]
        if len(hit) < 2:
            continue
        ids = tuple(sorted(ln.component_id for ln in hit))
        first = hit[0]
        names = " + ".join(ln.name for ln in hit)
        merged = CostLine(
            slot=first.slot, component_id="+".join(ids), name=names,
            min=max(ln.min for ln in hit), max=max(ln.max for ln in hit),
            basis=f"one bill: {why}; band = the largest of the members' bands",
            source_keys=tuple(sorted({k for ln in hit for k in ln.source_keys})),
            role="database" if any(ln.role == "database" for ln in hit) else first.role,
            derived=any(ln.derived for ln in hit),
            free_tier=next((ln.free_tier for ln in hit if ln.free_tier), None) if all(
                ln.min == 0 for ln in hit) else None,
            members=ids)
        pos = out.index(first)
        out = [ln for ln in out if ln.component_id not in members]
        out.insert(min(pos, len(out)), merged)
        notes.append(f"{names} are billed as one plan ({why}), so they are counted once "
                     f"(USD {_n(merged.min)}-{_n(merged.max)}).")
    return out, notes


def core_lines(p, components: Mapping[str, Any]) -> tuple[list[CostLine], list[str]]:
    """Lines for the chosen core components (before bundling) and per-line notes."""
    size = p.size
    lines: list[CostLine] = []
    notes: list[str] = []
    for slot, role in CORE_SLOTS:
        if slot == "database":
            db = _rec(components.get("database"))
            off = _rec(components.get("database_offering"))
            if db is not None and db.get("kind") in NONE_KINDS:
                continue
            if off is not None and off.get("cost"):
                kind = "self-managed" if off.get("kind") == "self_managed" else "managed"
                lines.append(band_line(off, size, slot, role,
                                       f"{kind} offering band at size {size}"))
            elif db is not None:
                lines.append(band_line(db, size, slot, role,
                                       f"database engine band at size {size} (no managed offering resolved)"))
            continue
        for rec in _many(components.get(slot)):
            if rec.get("kind") in NONE_KINDS:
                continue
            if role == "code":
                basis = "framework/toolkit: free; its running cost is the host's"
            else:
                basis = None
            lines.append(band_line(rec, size, slot, role, basis))
    for ln in lines:
        if ln.derived and ln.basis:
            notes.append(f"{ln.name}: {ln.basis}.")
    return lines, notes


def _warning(code: str, severity: str, message: str, fields) -> dict:
    return {"code": code, "severity": severity, "message": message, "fields": list(fields)}


def verdict_for(lo: int, hi: int, budget: float | None) -> str:
    """Plan 7 budget verdict (before any Phase 3 fallback)."""
    if budget is None:
        return "within"
    if budget == 0 and hi == 0:
        return "free_tier_only"
    if lo > budget:
        return "exceeded"
    if hi > budget:
        return "tight"
    if hi > 0 and budget >= _costs.BUDGET_HEADROOM_FACTOR * hi:
        return "headroom"
    return "within"


def _budget_warnings(p, lo: int, hi: int, budget: float | None, verdict: str,
                     lines: Iterable[CostLine]) -> list[dict]:
    out: list[dict] = []
    if budget is None:
        return out
    b = fmt(budget)
    if verdict == "exceeded":
        out.append(_warning("BUDGET_EXCEEDED", "critical",
                            f"Estimated USD {lo:,}-{hi:,}/month exceeds the budget of USD {b} "
                            f"({BUDGET_FIELD}={b}).", [BUDGET_FIELD]))
    elif verdict == "tight":
        out.append(_warning("BUDGET_TIGHT", "warning",
                            f"Budget USD {b} covers the low end of the estimate (USD {lo:,}-{hi:,}); growth "
                            f"to 12-month scale may exceed it.", [BUDGET_FIELD, "scale.users_12_months"]))
    elif verdict == "headroom":
        out.append(_warning("BUDGET_HEADROOM", "info",
                            f"Budget USD {b} is at least {_costs.BUDGET_HEADROOM_FACTOR} x the estimate "
                            f"(USD {lo:,}-{hi:,}); the budget allows more than this workload needs, and "
                            "simplicity was preferred over spend.", [BUDGET_FIELD]))
    free = [ln for ln in lines if ln.free_tier and ln.min == 0]
    if free:
        parts = []
        for ln in free:
            text = f"{ln.name} free tier: {ln.free_tier['limit'].rstrip('.')}."
            if ln.free_tier.get("commercial_use") is False:
                text += " It does not allow commercial use: move to the paid plan before launching a business."
            parts.append(text)
        out.append(_warning("FREE_TIER_LIMITS", "info", " ".join(parts), [BUDGET_FIELD]))
    return out


# ------------------------------------------------------------------ estimate
def estimate(p, components: Mapping[str, Any], extra_lines: Iterable[CostLine] = ()) -> Cost:
    """Core cost band, budget verdict and budget warnings for one stack (plan 7)."""
    raw, notes = core_lines(p, components or {})
    lines, bundle_notes = _bundle_lines(raw)
    lines = lines + list(extra_lines or ())
    lo_sum = sum(float(ln.min) for ln in lines)
    hi_sum = sum(float(ln.max) for ln in lines)
    lo, hi = _costs.round_sig(lo_sum), _costs.round_sig(hi_sum)
    hi = max(lo, hi)
    budget = val(p, BUDGET_FIELD)
    budget = float(budget) if isinstance(budget, (int, float)) and not isinstance(budget, bool) else None
    verdict = verdict_for(lo, hi, budget)

    asm: list[str] = [
        f"Monthly cost is an order-of-magnitude band in {_costs.CURRENCY_NOTE}, not a quote, for "
        f"{_size_text(p)}.",
    ]
    priced = [f"{ln.name} USD {_n(ln.min)}-{_n(ln.max)}" for ln in lines
              if not (ln.role == "code" and ln.max == 0)]
    free_code = [ln.name for ln in lines if ln.role == "code" and ln.max == 0]
    if priced:
        asm.append("Priced components: " + "; ".join(priced) + f". Totals are rounded to "
                   f"{_costs.SIGNIFICANT_FIGURES} significant figures.")
    if free_code:
        asm.append("No licence or hosting cost of their own: " + ", ".join(free_code)
                   + " (frameworks and toolkits run on the priced hosts).")
    asm.extend(bundle_notes)
    asm.extend(notes)
    if any(ln.free_tier for ln in lines):
        asm.append("The low end assumes free tiers hold at launch traffic; the high end is the paid plan.")
    if p.effective_residency not in ("none", "other"):
        asm.append(f"Prices are for {p.effective_residency} regions; regional price differences (about "
                   "+5-10% in Mumbai or Central India) sit inside each band's maximum.")
    asm.append("Excluded: " + ", ".join(_costs.ALWAYS_EXCLUDED) + ".")
    if budget is not None:
        asm.append(f"Compared with {BUDGET_FIELD}={fmt(budget)}: verdict {verdict}.")

    warnings = _budget_warnings(p, lo, hi, budget, verdict, lines)
    return Cost(min=lo, max=hi, size=p.size, lines=tuple(lines), assumptions=tuple(asm), budget=budget,
                verdict=verdict, warnings=tuple(warnings))


__all__ = ["CURRENCY", "PERIOD", "VERDICTS", "BUNDLED_BILLS", "CostLine", "Cost", "band", "band_line",
           "core_lines", "verdict_for", "estimate"]

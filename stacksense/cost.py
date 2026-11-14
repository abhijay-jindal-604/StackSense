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

Phase 3 (plan 7), applied inside :func:`estimate` after bundling, in this order:

* on-premise/air-gapped hosts: the host band is replaced by amortised hardware (``ONPREM_*``) and
  open-source self-managed databases on it cost nothing extra (:func:`_onprem`);
* availability multipliers on compute/database lines (``AVAILABILITY_MULTIPLIERS``) and traffic
  multipliers for spiky/seasonal traffic on autoscaling vs fixed hosts (``TRAFFIC_MULTIPLIERS``);
* usage lines: object storage (only when ``extra_lines`` carries no storage line: supporting.py
  prices the selected storage service itself) and stack-wide internet egress (``EGRESS_PROFILES``);
* compliance overhead per regime and size (``COMPLIANCE_OVERHEAD``), less WAF/secrets services already
  priced in ``extra_lines``;
* +10% failover tooling at 99.99.
SMS OTP is priced by supporting.py when an SMS sender is selected; otherwise an assumption states the
unpriced volume. The budget fallback lives in ``combine.apply_budget`` (it calls :func:`estimate`).

Pure and deterministic: no clock, no randomness; lines keep input order, bundles sort by id.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    multiplier: tuple[float, float] = (1.0, 1.0)   # (min, max) factor applied by availability/traffic

    def as_dict(self) -> dict:
        return {"slot": self.slot, "component_id": self.component_id, "name": self.name,
                "min": self.min, "max": self.max, "basis": self.basis,
                "source_keys": list(self.source_keys), "role": self.role, "derived": self.derived,
                **({"members": list(self.members)} if self.members else {}),
                **({"multiplier": list(self.multiplier)} if self.multiplier != (1.0, 1.0) else {})}


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
    # availability target -> (compute factor, database factor) applied (plan 7); used by
    # conflicts.AVAILABILITY_VS_BUDGET
    availability_multiplier: tuple[float, float] = (1.0, 1.0)
    # USD (min, max) per month the availability factors and failover tooling add (unrounded sum, 2 dp)
    availability_uplift: tuple[float, float] = (0.0, 0.0)
    storage_gb: float = 0.0            # object storage volume priced (GB-month)
    egress_gb: float = 0.0             # internet egress volume priced (GB/month)

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


# ------------------------------------------------------------------ phase 3 helpers (plan 7)
SELF_HOST_KINDS = ("onprem",)                      # amortised-hardware formula applies
OWN_UPLINK_KINDS = ("onprem", "hybrid_appliance")  # egress over the organisation's own uplink
TRAFFIC_PATTERNS = ("spiky", "seasonal")
STORAGE_SLOT = "storage"


def _r2(x: float) -> float:
    return round(float(x), 2)


def _record_index(components: Mapping[str, Any]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for slot, _role in CORE_SLOTS:
        for rec in _many(components.get(slot)):
            out.setdefault(rec["id"], rec)
    off = _rec(components.get("database_offering"))
    if off is not None:
        out.setdefault(off["id"], off)
    return out


def _lookup(cid: str, recs: Mapping[str, dict]) -> dict | None:
    if cid in recs:
        return recs[cid]
    from . import kb as _kb                          # lazy: kb is loaded by the time estimate runs
    return _kb.get(cid)


def _line_recs(ln: CostLine, recs: Mapping[str, dict]) -> list[dict]:
    ids = ln.members or (ln.component_id,)
    return [r for r in (_lookup(i, recs) for i in ids) if r is not None]


def _provider(rec: dict | None) -> str | None:
    if not rec:
        return None
    from .supporting import provider_of             # lazy: supporting imports this module
    return provider_of(rec)


def _availability(p) -> str:
    a = val(p, "requirements.availability", "99.9")
    return a if a in _costs.AVAILABILITY_MULTIPLIERS else "99.9"


def _scales(rec_list: list[dict]) -> str:
    """``autoscaling`` or ``fixed`` for a compute line's records."""
    caps = {c for r in rec_list for c in (r.get("caps") or ())}
    kinds = {r.get("kind") for r in rec_list}
    if "fixed_capacity" in caps or (not caps & {"autoscaling", "scale_to_zero"} and kinds & {"vm", "onprem"}):
        return "fixed"
    return "autoscaling" if caps & {"autoscaling", "scale_to_zero"} else "fixed"


def _onprem(p, components: Mapping[str, Any], lines: list[CostLine]) -> tuple[list[CostLine], list[str]]:
    """Plan 7 on-premise/air-gapped: cloud bill 0, amortised hardware x nodes + power/colocation."""
    host = _rec(components.get("hosting"))
    if host is None or host.get("kind") not in SELF_HOST_KINDS:
        return lines, []
    size = p.size
    derived = size not in _costs.ONPREM_NODES
    n_lo, n_hi = _costs.ONPREM_NODES.get(size, _costs.ONPREM_NODES["l"])
    if derived:
        n_lo, n_hi = n_lo * _costs.XL_FROM_L_FACTOR, n_hi * _costs.XL_FROM_L_FACTOR
    s_lo, s_hi = _costs.ONPREM_SERVER_MONTH
    w_lo, w_hi = _costs.ONPREM_POWER_COLO_MONTH
    lo, hi = n_lo * (s_lo + w_lo), n_hi * (s_hi + w_hi)
    nodes = f"{n_lo}" if n_lo == n_hi else f"{n_lo}-{n_hi}"
    basis = (f"amortised hardware: {nodes} node(s) at size {size} x (USD {s_lo}-{s_hi} per server-month over "
             f"{_costs.ONPREM_AMORTISATION_YEARS} years + USD {w_lo}-{w_hi} power/colocation per node)"
             + (" (size xl: l node count x 3, quote needed)" if derived else ""))
    out: list[CostLine] = []
    for ln in lines:
        if ln.component_id == host["id"]:
            ln = replace(ln, min=lo, max=hi, basis=basis, derived=derived or ln.derived, free_tier=None)
        elif ln.slot == "database":
            off = _rec(components.get("database_offering"))
            db = _rec(components.get("database"))
            oss = bool((db or {}).get("open_source", True))
            if (off is None or off.get("kind") == "self_managed") and oss:
                ln = replace(ln, min=0, max=0, free_tier=None,
                             basis="open-source engine on the self-operated servers counted in the hardware estimate")
        out.append(ln)
    note = (f"On-premise/air-gapped hosting: the cloud bill is USD 0; the estimate is amortised hardware for "
            f"{nodes} node(s) (USD {s_lo}-{s_hi} per server-month over {_costs.ONPREM_AMORTISATION_YEARS} years) "
            f"plus USD {w_lo}-{w_hi} power/colocation per node = USD {_n(lo)}-{_n(hi)}/month. Staff cost "
            "(operations, on-call) is excluded.")
    return out, [note]


def _multiply(p, lines: list[CostLine], recs: Mapping[str, dict],
              components: Mapping[str, Any] | None = None) -> tuple[list[CostLine], list[str], tuple]:
    """Availability factors on compute/database lines, then the traffic factor on compute lines.
    Managed static/edge hosts take no availability factor; serving pre-built files (no server-rendered
    frontend) they take no traffic factor either, because their bursts are bytes served, which the
    egress line already prices."""
    components = components or {}
    avail = _availability(p)
    f_comp, f_db = _costs.AVAILABILITY_MULTIPLIERS[avail]
    pattern = val(p, "scale.traffic_pattern", "steady")
    out: list[CostLine] = []
    up_lo = up_hi = 0.0
    traffic_hits: dict[str, list[str]] = {}
    exempt_hits: list[str] = []
    static_hits: list[str] = []
    serves_ssr = any(r.get("kind") in _costs.SERVER_RENDERED_FRONTEND_KINDS for r in _many(components.get("frontend")))
    for ln in lines:
        if ln.role not in ("compute", "database"):
            out.append(ln)
            continue
        f = f_comp if ln.role == "compute" else f_db
        line_recs = _line_recs(ln, recs)
        exempt = bool(line_recs) and all(r.get("kind") in _costs.AVAILABILITY_EXEMPT_KINDS for r in line_recs)
        if exempt and f != 1.0:
            f = 1.0
            exempt_hits.append(ln.name)
        m_lo, m_hi = f, f
        notes = []
        if f != 1.0:
            notes.append(f"x{fmt(f)} for {avail}% availability")
            up_lo += ln.min * (f - 1)
            up_hi += ln.max * (f - 1)
        static_files = exempt and not serves_ssr
        if static_files and ln.role == "compute" and pattern in TRAFFIC_PATTERNS:
            static_hits.append(ln.name)
        elif ln.role == "compute" and pattern in TRAFFIC_PATTERNS:
            mode = _scales(line_recs)
            t_lo, t_hi = _costs.TRAFFIC_MULTIPLIERS[mode][pattern]
            if (t_lo, t_hi) != (1.0, 1.0) and ln.max > 0:
                # min: product (idles less); max: the larger factor (standby capacity absorbs bursts)
                m_lo, m_hi = m_lo * t_lo, max(m_hi, t_hi)
                notes.append(f"min x{fmt(t_lo)}, max x{fmt(t_hi)} for {pattern} traffic on "
                             f"{'an autoscaling' if mode == 'autoscaling' else 'a fixed-capacity'} host"
                             + (f" (max x{fmt(m_hi)}: the larger of the availability and traffic factors, "
                                "not their product)" if f != 1.0 else ""))
                traffic_hits.setdefault(mode, []).append(ln.name)
        if notes and ln.max > 0:
            ln = replace(ln, min=_r2(ln.min * m_lo), max=_r2(ln.max * m_hi),
                         basis=f"{ln.basis}; {'; '.join(notes)}", multiplier=(round(m_lo, 4), round(m_hi, 4)))
        out.append(ln)
    asm = [f"Availability {avail}%: compute x{fmt(f_comp)}, database x{fmt(f_db)}"
           + {"99": " (single instance acceptable)", "99.9": " (single region, managed; instances at size m and "
              "above are already in the bands)", "99.95": " (multi-AZ standby)",
              "99.99": " (multi-AZ plus warm cross-region DR)"}[avail]
           + (f", adding about USD {_n(up_lo)}-{_n(up_hi)}/month before traffic adjustment" if up_hi else "") + "."]
    if exempt_hits:
        asm.append(f"No availability factor on {', '.join(exempt_hits)}: managed static/edge hosting is replicated "
                   "across zones by the provider, so there is no standby instance to pay for.")
    if static_hits:
        asm.append(f"No traffic factor on {', '.join(static_hits)}: it serves pre-built files, so a {pattern} burst "
                   "is extra bytes served, already priced in the egress line.")
    if pattern in TRAFFIC_PATTERNS:
        parts = []
        for mode in ("autoscaling", "fixed"):
            if mode in traffic_hits:
                t_lo, t_hi = _costs.TRAFFIC_MULTIPLIERS[mode][pattern]
                what = ("autoscaling hosts pay for bursts and idle less" if mode == "autoscaling"
                        else "fixed hosts are provisioned for peak")
                parts.append(f"{', '.join(traffic_hits[mode])}: min x{fmt(t_lo)}, max x{fmt(t_hi)} ({what})")
        asm.append(f"Traffic pattern {pattern}: " + ("; ".join(parts) if parts else "no priced compute line to adjust")
                   + ".")
    else:
        asm.append(f"Traffic pattern {pattern}: no traffic multiplier.")
    return out, asm, ((f_comp, f_db), (up_lo, up_hi))


def _storage_key_for(provider: str | None) -> str:
    return {"cloudflare": "r2", "digitalocean": "spaces"}.get(provider or "", "hyperscaler")


def _storage_line(p, components: Mapping[str, Any], extras: list[CostLine]) -> tuple[CostLine | None, float]:
    """Object storage usage when the project stores files: ``D_media = data_volume_gb x 0.8``.
    supporting.py prices the selected storage service; this line is only added when no storage line
    was passed (a core-only estimate, or a storage gap)."""
    if not val(p, "requirements.file_media_storage"):
        return None, 0.0
    gb = _r2(p.data_volume_gb * _costs.MEDIA_SHARE_OF_DATA)
    if any(ln.slot == STORAGE_SLOT for ln in extras):
        return None, gb
    host = _rec(components.get("hosting")) or _rec(components.get("frontend_hosting"))
    if host is not None and host.get("kind") in OWN_UPLINK_KINDS:
        return CostLine(slot="usage", component_id="object_storage", name="Object storage (self-operated)",
                        min=0, max=0, basis=f"usage: {fmt(gb)} GB on the self-operated servers",
                        source_keys=(), role="usage"), gb
    prov = _provider(host)
    key = _storage_key_for(prov)
    lo_r, hi_r = _costs.OBJECT_STORAGE_RATE_GB_MONTH[key]
    floor = _costs.OBJECT_STORAGE_MINIMUM.get(key, 0)
    src = {"r2": ("cloudflare_pricing", "r2_docs"), "spaces": ("do_pricing",)}.get(
        key, _costs.PROVIDER_PRICING_SOURCE.get(prov or "aws", ("aws_pricing",)))
    return CostLine(slot="usage", component_id="object_storage", name="Object storage (no storage service priced)",
                    min=max(floor, _r2(gb * lo_r)), max=max(floor, _r2(gb * hi_r)),
                    basis=(f"usage: {fmt(gb)} GB stored ({fmt(_costs.MEDIA_SHARE_OF_DATA)} x data volume "
                           f"{fmt(p.data_volume_gb)} GB) x USD {lo_r:g}-{hi_r:g}/GB-month"
                           + (f", minimum USD {floor}" if floor else "")),
                    source_keys=tuple(src), role="usage"), gb


def _egress_profile(rec: dict | None) -> tuple[str, tuple[str, ...], str]:
    """(profile key, source keys, provider label) for the record serving the traffic."""
    if rec is None:
        return "hyperscaler", ("aws_pricing",), "unknown host"
    if rec.get("kind") in OWN_UPLINK_KINDS:
        return "self", (), rec["name"]
    key = _costs.EGRESS_PROFILE_BY_ID.get(rec["id"])
    prov = _provider(rec)
    if key is None:
        key = _costs.EGRESS_PROFILE_BY_PROVIDER.get(prov or "")
    if key is None:
        return "hyperscaler", ("aws_pricing",), f"{rec['name']} (egress terms not in the knowledge base: " \
                                                "hyperscaler rate assumed)"
    src = _costs.EGRESS_PROFILE_SOURCE.get(key) or _costs.PROVIDER_PRICING_SOURCE.get(prov or "", ())
    if key == "cloudflare" and rec["id"] == "cloudflare_r2":
        src = ("cloudflare_pricing", "r2_docs")
    return key, tuple(src), rec["name"]


def _included(profile: dict, size: str) -> float:
    inc = profile["included"]
    return inc.get(size, inc.get("l") if size == "xl" and "l" in inc else inc.get("*", 0))


def egress_per_user(p) -> float:
    """GB per user per month for the project's type (``kb.costs.EGRESS_GB_PER_USER_BY_TYPE``)."""
    return _costs.egress_gb_per_user(val(p, "project.type"))


def media_heavy(p) -> bool:
    """File storage with at least ``MEDIA_HEAVY_GB_PER_USER`` stored media per user."""
    if not val(p, "requirements.file_media_storage") or p.users <= 0:
        return False
    return p.data_volume_gb * _costs.MEDIA_SHARE_OF_DATA / p.users >= _costs.MEDIA_HEAVY_GB_PER_USER


def _egress_line(p, components: Mapping[str, Any], extras: list[CostLine], recs) -> tuple[CostLine, float]:
    """Stack-wide internet egress: ``U x 50 MB`` served by the client-facing host, plus (media-heavy)
    ``U x 50 MB x 2`` media downloads served by the object store; free allowances once per provider."""
    base = _r2(p.users * egress_per_user(p))
    heavy = media_heavy(p)
    media = _r2(base * (_costs.EGRESS_MEDIA_FACTOR - 1)) if heavy else 0.0
    fe_host = _rec(components.get("frontend_hosting"))
    host = _rec(components.get("hosting"))
    serving = fe_host if (fe_host is not None and fe_host.get("kind") not in NONE_KINDS) else host
    if p.self_hosted_only:
        serving = {"id": "self", "name": "self-operated servers", "kind": "onprem"}
    store_rec = None
    for ln in extras:
        if ln.slot == STORAGE_SLOT:
            store_rec = _lookup(ln.component_id, recs)
            break
    media_from = store_rec or host or serving
    if p.self_hosted_only:
        media_from = serving
    volumes: dict[str, list] = {}
    for gb, rec in ((base, serving), (media, media_from)):
        if gb <= 0:
            continue
        key, src, label = _egress_profile(rec)
        slot = volumes.setdefault(key, [0.0, set(), []])
        slot[0] += gb
        slot[1].update(src)
        if label not in slot[2]:
            slot[2].append(label)
    lo = hi = 0.0
    parts = []
    src_all: set[str] = set()
    for key in sorted(volumes):
        gb, src, labels = volumes[key]
        prof = _costs.EGRESS_PROFILES[key]
        inc = _included(prof, p.size)
        billable = max(0.0, gb - inc) if inc != _costs.UNMETERED else 0.0
        r_lo, r_hi = prof["rate"]
        if key == "fly" and p.india:
            r_lo = r_hi
        lo += billable * r_lo
        hi += billable * r_hi
        src_all |= src
        inc_txt = "unmetered" if inc == _costs.UNMETERED else f"{fmt(inc)} GB included"
        parts.append(f"{fmt(_r2(gb))} GB via {' / '.join(labels)} ({prof['note']}; {inc_txt}; "
                     f"{fmt(_r2(billable))} GB billable)")
    total = _r2(base + media)
    basis = (f"usage: {fmt(total)} GB/month egress = {fmt(egress_per_user(p) * 1000)} MB/user x "
             f"{p.users:,} users" + (f" x {_costs.EGRESS_MEDIA_FACTOR} (media-heavy)" if heavy else "")
             + (": " + "; ".join(parts) if parts else ""))
    return CostLine(slot="usage", component_id="egress", name="Internet egress (data transfer out)",
                    min=_r2(lo), max=_r2(hi), basis=basis, source_keys=tuple(sorted(src_all)),
                    role="usage"), total


def _overhead_band(regime: str, size: str) -> tuple[float, float, bool]:
    table = _costs.COMPLIANCE_OVERHEAD[regime]
    if size == "xs":
        return (*table["s"], False)
    if size == "xl":
        lo, hi = table["l"]
        return lo * _costs.XL_FROM_L_FACTOR, hi * _costs.XL_FROM_L_FACTOR, True
    return (*table[size], False)


def _compliance_lines(p, components: Mapping[str, Any], extras: list[CostLine],
                      recs) -> tuple[list[CostLine], list[str]]:
    regimes = [r for r in p.compliance if r in _costs.COMPLIANCE_OVERHEAD]
    if not regimes:
        return [], []
    host = _rec(components.get("hosting")) or _rec(components.get("frontend_hosting"))
    prov = _provider(host)
    host_src = _costs.PROVIDER_PRICING_SOURCE.get(prov or "", ())
    lines: list[CostLine] = []
    subsumed: list[tuple[str, str]] = []
    for reg in regimes:
        lo, hi, derived = _overhead_band(reg, p.size)
        src = (_costs.COMPLIANCE_OVERHEAD_SOURCES.get(reg, ())
               + _costs.COMPLIANCE_PROVIDER_SOURCES.get(reg, {}).get(prov or "", ()) + host_src)
        by = next((r for r in _costs.COMPLIANCE_SUBSUMED_BY.get(reg, ()) if r in regimes), None)
        if by is not None:
            subsumed.append((reg, by))
            lines.append(CostLine(slot="compliance", component_id=f"overhead_{reg}", name=f"{reg} compliance overhead",
                                  min=0, max=0, basis=f"covered by the {by} overhead line (same log retention, backup "
                                                      f"and scanning tooling; counted once)",
                                  source_keys=tuple(dict.fromkeys(src)), role="overhead"))
            continue
        size_txt = "s band (xs uses s)" if p.size == "xs" else (
            "l band x 3 (quote needed)" if derived else f"{p.size} band")
        lines.append(CostLine(slot="compliance", component_id=f"overhead_{reg}", name=f"{reg} compliance overhead",
                              min=lo, max=hi, basis=f"overhead at size {size_txt}: {_costs.COMPLIANCE_OVERHEAD_TEXT[reg]}",
                              source_keys=tuple(dict.fromkeys(src)), role="overhead", derived=derived))
    notes: list[str] = [f"The {reg} overhead (log retention, backup, vulnerability scanning) is inside the {by} "
                        "overhead line, so it is counted once." for reg, by in subsumed]
    tooling = [ln for ln in extras
               if _kind_of(_lookup(ln.component_id, recs)) in _costs.COMPLIANCE_TOOLING_SUBS and ln.max > 0]
    targets = [ln for ln in lines if ln.component_id[len("overhead_"):] in _costs.COMPLIANCE_TOOLING_REGIMES]
    if tooling and targets:
        c_lo = sum(ln.min for ln in tooling)
        c_hi = sum(ln.max for ln in tooling)
        big = max(targets, key=lambda ln: (ln.max, ln.min, ln.component_id))
        n_lo = _r2(max(0.0, big.min - c_lo))
        new = replace(big, min=n_lo, max=_r2(max(n_lo, big.max - c_hi)),
                      basis=f"{big.basis}; less USD {_n(c_lo)}-{_n(c_hi)} already priced as "
                            f"{', '.join(ln.name for ln in tooling)}")
        lines = [new if ln is big else ln for ln in lines]
        notes.append(f"Compliance tooling already in the stack ({', '.join(ln.name for ln in tooling)}) is "
                     f"credited against the {big.name} line so it is not counted twice.")
    summ = "; ".join(f"{ln.name.split(' ')[0]} USD {_n(ln.min)}-{_n(ln.max)}" for ln in lines if ln.max or ln.min)
    notes.insert(0, f"Compliance overhead added at size {p.size} (plan 7): {summ}. Audit and certification fees "
                    "are excluded.")
    return lines, notes


def _kind_of(rec: dict | None) -> str | None:
    """Service kind of a supporting record (``waf``, ``secrets``, ``sms`` ...)."""
    if not rec:
        return None
    return rec.get("sub") or rec.get("kind")


def _payments_needed(p, extras: list[CostLine]) -> bool:
    return bool(val(p, "requirements.payments")) or any(ln.slot == "payments" for ln in extras)


def _sms_needed(p) -> bool:
    return val(p, "requirements.auth") == "phone_otp" or "sms" in (val(p, "requirements.notifications") or [])


def _sms_priced(extras: list[CostLine], recs) -> bool:
    for ln in extras:
        rec = _lookup(ln.component_id, recs) or {}
        if _kind_of(rec) == "sms" or "sms" in (rec.get("caps") or ()):
            return True
    return False


def _region_text(p) -> str:
    res = p.effective_residency
    if res not in ("none", "other"):
        return (f"Prices are for {res} regions; regional price differences (about +5-10% in Mumbai or "
                "Central India) sit inside each band's maximum.")
    if res == "other":
        return "Region: data_residency=other; prices are each provider's list prices for its default regions."
    return "Region: no data-residency constraint; prices are each provider's list prices for its default regions."


# ------------------------------------------------------------------ estimate
def estimate(p, components: Mapping[str, Any], extra_lines: Iterable[CostLine] = ()) -> Cost:
    """Cost band, budget verdict and budget warnings for one stack (plan 7).

    Pure: the result depends only on ``p``, ``components`` and ``extra_lines``."""
    comps = components or {}
    recs = _record_index(comps)
    raw, notes = core_lines(p, comps)
    lines, bundle_notes = _bundle_lines(raw)
    lines, onprem_notes = _onprem(p, comps, lines)
    lines, mult_notes, (avail_mult, uplift) = _multiply(p, lines, recs, comps)
    extras = list(extra_lines or ())
    lines = lines + extras
    storage, storage_gb = _storage_line(p, comps, extras)
    if storage is not None:
        lines.append(storage)
    egress, egress_gb = _egress_line(p, comps, extras, recs)
    lines.append(egress)
    over, over_notes = _compliance_lines(p, comps, extras, recs)
    lines += over
    share = _costs.FAILOVER_TOOLING_SHARE.get(_availability(p))
    if share:
        b_lo = sum(float(ln.min) for ln in lines)
        b_hi = sum(float(ln.max) for ln in lines)
        f_lo, f_hi = _r2(b_lo * share), _r2(b_hi * share)
        lines.append(CostLine(slot="availability", component_id="failover_tooling",
                              name="Failover tooling (cross-region DR)", min=f_lo, max=f_hi,
                              basis=f"{fmt(share * 100)}% of the total for {_availability(p)}% availability "
                                    "(health checks, replication, DNS failover, DR drills)",
                              source_keys=_costs.PROVIDER_PRICING_SOURCE.get(
                                  _provider(_rec(comps.get("hosting"))) or "aws", ("aws_pricing",)),
                              role="overhead"))
        uplift = (uplift[0] + f_lo, uplift[1] + f_hi)
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
    asm.extend(onprem_notes)
    if any(ln.free_tier for ln in lines):
        asm.append("The low end assumes free tiers hold at launch traffic; the high end is the paid plan.")
    asm.append(_region_text(p))
    asm.extend(mult_notes)
    media_txt = (f"{fmt(storage_gb)} GB ({fmt(_costs.MEDIA_SHARE_OF_DATA)} x data volume "
                 f"{fmt(p.data_volume_gb)} GB, file_media_storage=true)" if storage_gb
                 else "0 GB (no file_media_storage)")
    asm.append(f"Usage volumes: object storage {media_txt}; internet egress {fmt(egress_gb)} GB/month "
               f"({fmt(egress_per_user(p) * 1000)} MB per user per month for project.type="
               f"{val(p, 'project.type')}"
               + (f" x {_costs.EGRESS_MEDIA_FACTOR} for media-heavy use" if media_heavy(p) else "")
               + f"), priced at USD {_n(egress.min)}-{_n(egress.max)} after free allowances.")
    asm.extend(over_notes)
    if share:
        asm.append(f"Failover tooling for {_availability(p)}% availability adds {fmt(share * 100)}% of the total.")
    if _sms_needed(p):
        msgs = p.users * _costs.SMS_PER_USER_MONTH
        r_lo, r_hi = _costs.SMS_RATE_INDIA if p.india else _costs.SMS_RATE_OTHER
        route = "India DLT route" if p.india else "international route"
        if _sms_priced(extras, recs):
            asm.append(f"SMS one-time passwords are priced at {msgs:,} messages/month "
                       f"({_costs.SMS_PER_USER_MONTH} per user) x USD {r_lo:g}-{r_hi:g} ({route}).")
        else:
            asm.append(f"SMS one-time passwords are not priced because no SMS provider is in the stack (see the "
                       f"supporting-service gap); at {msgs:,} messages/month ({_costs.SMS_PER_USER_MONTH} per user) "
                       f"x USD {r_lo:g}-{r_hi:g} ({route}) they would add about USD "
                       f"{_n(msgs * r_lo)}-{_n(msgs * r_hi)}/month.")
    if _payments_needed(p, extras):
        fee = _costs.PAYMENT_FEE_NOTE
        asm.append("Payment gateway fees are a percentage of transaction value, not infrastructure, and are "
                   f"excluded: about {fmt(fee['india_domestic_pct'])}% per domestic transaction in India, "
                   f"{fee['stripe_us']} per card payment on Stripe in the US.")
    asm.append("Excluded: " + ", ".join(_costs.ALWAYS_EXCLUDED) + ".")
    if budget is not None:
        asm.append(f"Compared with {BUDGET_FIELD}={fmt(budget)}: verdict {verdict}.")

    warnings = _budget_warnings(p, lo, hi, budget, verdict, lines)
    return Cost(min=lo, max=hi, size=p.size, lines=tuple(lines), assumptions=tuple(asm), budget=budget,
                verdict=verdict, warnings=tuple(warnings), availability_multiplier=tuple(avail_mult),
                availability_uplift=(_r2(uplift[0]), _r2(uplift[1])), storage_gb=float(storage_gb),
                egress_gb=float(egress_gb))


__all__ = ["CURRENCY", "PERIOD", "VERDICTS", "BUNDLED_BILLS", "CostLine", "Cost", "band", "band_line",
           "core_lines", "verdict_for", "estimate", "media_heavy"]

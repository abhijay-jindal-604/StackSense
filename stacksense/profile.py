"""Derived project profile (plan sections 3.3 and 5.1).

``derive(v, signals, existing)`` turns a *valid* ``Validated`` result into an immutable
:class:`Profile`: every quantity the filters, scoring, architecture and cost stages need, computed
by the formulas of plan section 5.1. Every value that is not a straight copy of an input appends one
plain-language assumption with its formula and inputs (``Profile.assumptions``). Situations that
need the user's attention (RBI inference, residency conflicts, unverifiable residency, the reading
of ``cloud_preference=none``) become warning dicts ``{code, severity, message, fields}`` on
``Profile.warnings``; messages are filled only with input values and derived numbers.

Pure and deterministic: no clock, no randomness, no environment reads, sets always sorted.
"""
from __future__ import annotations

import math
from types import MappingProxyType
from dataclasses import dataclass, field
from typing import Any

from .description import Signals
from .existing import ExistingReport
from .kb import languages as _languages
from .schema import PLATFORMS, PRIORITY_KEYS

# ------------------------------------------------------------------ constants (plan 5.1)
SIZE_CLASSES: tuple[str, ...] = ("xs", "s", "m", "l", "xl")
# Upper bounds (inclusive) for xs, s, m, l; anything above the last bound is xl.
SIZE_USERS_MAX: tuple[int, ...] = (5_000, 50_000, 500_000, 5_000_000)
SIZE_PEAK_MAX: tuple[int, ...] = (100, 1_000, 10_000, 100_000)
SIZE_DATA_GB_MAX: tuple[float, ...] = (5, 100, 1_000, 10_000)

PEAK_SHARE = 0.05                 # peak concurrent = 5% of 12-month users
RPS_PER_CONCURRENT = 0.2          # one request per active user every 5 s
REALTIME_MSGS_PER_CONCURRENT = 1.0
DATA_GB_PER_USER = 0.002          # 2 MB per user
DATA_GB_PER_USER_MEDIA = 0.05     # 50 MB per user when file_media_storage
DATA_GB_MIN = 1

OPS_BASE: dict[str, int] = {"beginner": 1, "mixed": 2, "intermediate": 2, "senior": 3}
OPS_DEVOPS_BONUS = 2
OPS_LARGE_TEAM_SIZE = 6
OPS_LARGE_TEAM_BONUS = 1
OPS_MAX = 5

# delivery pressure: weeks_per_client_per_engineer < bound -> pressure
PRESSURE_BOUNDS: tuple[tuple[float, int], ...] = ((4, 3), (8, 2), (16, 1))
PRESSURE_MAX = 3

STATIC_PROJECT_TYPES = frozenset({"content_site"})
STRONG_CONSISTENCY_TYPES = frozenset({"fintech", "ecommerce", "marketplace", "healthtech"})
STRONG_CONSISTENCY_SIGNALS = frozenset({"ledger", "booking", "inventory"})
GRAPH_SIGNALS = frozenset({"social_graph", "recommendation", "fraud"})
TIME_SERIES_SIGNALS = frozenset({"sensors"})
HYPERSCALERS = ("aws", "gcp", "azure")
CLIENT_PLATFORMS: tuple[str, ...] = tuple(p for p in PLATFORMS if p != "api_only")
EU_PREFERENCE_BONUS = 2           # gdpr with residency none: preference for EU regions (scoring)


@dataclass(frozen=True)
class Profile:
    # sizing
    users: int                       # max(users_12_months, users_at_launch)
    peak_concurrent: int
    peak_rps: int
    realtime_msgs_per_s: int         # 0 unless requirements.realtime
    data_volume_gb: float
    size: str                        # xs/s/m/l/xl = max of the three sub-classes
    size_users: str
    size_peak: str
    size_data: str
    # team / delivery
    ops_capacity: int                # 0-5
    delivery_pressure: int           # 0-3
    weeks_per_client_per_engineer: float
    languages: tuple[str, ...]       # canonical, sorted
    # shape of the product
    dynamic_score: int               # 0-8
    needs_backend: bool
    needs_database: bool
    clients: tuple[str, ...]         # ordered subset of web/android/ios/desktop
    api_only: bool
    # infrastructure (hard constraints)
    residency: str                   # as given
    effective_residency: str         # after RBI inference
    regions: tuple[tuple[str, str], ...]   # sorted (provider, preferred region id)
    cloud_preference: str            # raw value: any/aws/gcp/azure/none
    cloud: str | None                # explicit hyperscaler or None
    cloud_explicit: bool             # cloud_preference provided and not 'any'
    deployment: str
    self_hosted_only: bool           # on_premise or air_gapped
    air_gapped: bool
    compliance: tuple[str, ...]      # sorted
    # data
    consistency: str                 # strong/eventual
    data_shape: str                  # relational/document/key_value/time_series/graph/analytical
    money: bool
    # preferences
    weights: tuple[tuple[str, int], ...]   # sorted (priority key, 1..5)
    india: bool
    eu: bool
    gdpr_eu_preference: bool         # gdpr with residency none: EU regions preferred
    # bookkeeping
    infeasible: bool
    assumptions: tuple[str, ...]
    warnings: tuple[dict, ...]
    signals: Signals = ()
    existing: ExistingReport | None = None
    values: Any = field(default=None, compare=False, repr=False)   # read-only view of the validated flat dict

    def weight(self, key: str) -> int:
        for k, w in self.weights:
            if k == key:
                return w
        raise KeyError(key)

    def region(self, provider: str) -> str | None:
        for p, r in self.regions:
            if p == provider:
                return r
        return None


# ------------------------------------------------------------------ helpers
def _n(x) -> str:
    """Format a number for messages: thousands separators, no trailing .0."""
    if isinstance(x, float):
        if x.is_integer():
            x = int(x)
        else:
            return f"{round(x, 2):,}"
    return f"{x:,}"


def size_class(value: float, bounds) -> str:
    for cls, bound in zip(SIZE_CLASSES, bounds):
        if value <= bound:
            return cls
    return SIZE_CLASSES[-1]


def larger_class(*classes: str) -> str:
    return max(classes, key=SIZE_CLASSES.index)


def estimate_peak(users: int) -> int:
    return max(1, math.ceil(PEAK_SHARE * users))


def estimate_rps(peak: int) -> int:
    return math.ceil(RPS_PER_CONCURRENT * peak)


def estimate_data_gb(users: int, media: bool) -> float:
    per_user = DATA_GB_PER_USER_MEDIA if media else DATA_GB_PER_USER
    return max(DATA_GB_MIN, round(users * per_user, 2))


def ops_capacity(experience: str, has_devops: bool, team_size: int) -> int:
    score = OPS_BASE.get(experience, 1)
    if has_devops:
        score += OPS_DEVOPS_BONUS
    if team_size >= OPS_LARGE_TEAM_SIZE:
        score += OPS_LARGE_TEAM_BONUS
    return min(OPS_MAX, score)


def delivery_pressure(mvp_weeks: int, team_size: int, client_count: int, needs_backend: bool) -> tuple[int, float]:
    units = max(1, client_count + (1 if needs_backend else 0))
    wpce = mvp_weeks * team_size / units
    for bound, pressure in PRESSURE_BOUNDS:
        if wpce < bound:
            return pressure, wpce
    return 0, wpce


def _warning(code, severity, message, fields) -> dict:
    return {"code": code, "severity": severity, "message": message, "fields": list(fields)}


def _regions(residency: str) -> tuple[tuple[str, str], ...]:
    """Preferred region per provider for the effective residency (none when unconstrained/unknown).

    Imported lazily: any failure of the region KB means 'no region' (fail closed downstream)."""
    if residency in ("none", "other"):
        return ()
    try:
        from .kb import regions as kb_regions
        out = []
        for provider in sorted(kb_regions.ENTRIES):
            ids = kb_regions.regions_for(provider, residency)
            if isinstance(ids, list) and ids and ids[0] != "*":
                out.append((provider, str(ids[0])))
        return tuple(out)
    except Exception:
        return ()


# ------------------------------------------------------------------ derive
def derive(v, signals: Signals = (), existing: ExistingReport | None = None) -> Profile:
    """Derive the profile from a valid ``Validated`` result (raises ValueError if it has errors)."""
    if v.errors:
        raise ValueError("derive() needs a valid input; validation reported errors.")
    p = v.profile
    provided = v.provided
    signals = tuple(signals or ())
    sig_ids = sorted({s.id for s in signals})
    asm: list[str] = []
    warns: list[dict] = []

    # ---- sizing ------------------------------------------------------
    u12 = int(p["scale.users_12_months"])
    launch = int(p["scale.users_at_launch"])
    users = max(u12, launch)
    if launch > u12:
        asm.append(f"Sizing uses users_at_launch={_n(launch)} because it is larger than "
                   f"users_12_months={_n(u12)}.")

    if p.get("scale.peak_concurrent_users") is not None:
        peak = int(p["scale.peak_concurrent_users"])
    else:
        peak = estimate_peak(users)
        asm.append(f"scale.peak_concurrent_users not given: estimated {_n(peak)} "
                   f"({_n(int(PEAK_SHARE * 100))}% of users={_n(users)}, minimum 1).")

    if p.get("scale.peak_rps") is not None:
        rps = int(p["scale.peak_rps"])
    else:
        rps = estimate_rps(peak)
        asm.append(f"Peak request rate estimated at {_n(rps)} requests/s "
                   f"({RPS_PER_CONCURRENT} x peak concurrent users={_n(peak)}; one request per active user every 5 s).")

    realtime = bool(p.get("requirements.realtime"))
    rt_rate = math.ceil(REALTIME_MSGS_PER_CONCURRENT * peak) if realtime else 0
    if realtime:
        asm.append(f"Realtime message rate estimated at {_n(rt_rate)} messages/s "
                   f"({REALTIME_MSGS_PER_CONCURRENT} x peak concurrent users={_n(peak)}).")

    media = bool(p.get("requirements.file_media_storage"))
    if p.get("scale.data_volume_gb_12_months") is not None:
        data_gb = p["scale.data_volume_gb_12_months"]
        data_gb = float(data_gb) if isinstance(data_gb, float) else int(data_gb)
    else:
        data_gb = estimate_data_gb(users, media)
        per_mb = int((DATA_GB_PER_USER_MEDIA if media else DATA_GB_PER_USER) * 1000)
        why = " because file_media_storage is true" if media else ""
        asm.append(f"scale.data_volume_gb_12_months not given: estimated {_n(data_gb)} GB "
                   f"({per_mb} MB per user{why} x users={_n(users)}, minimum {DATA_GB_MIN} GB).")

    s_users = size_class(users, SIZE_USERS_MAX)
    s_peak = size_class(peak, SIZE_PEAK_MAX)
    s_data = size_class(data_gb, SIZE_DATA_GB_MAX)
    size = larger_class(s_users, s_peak, s_data)
    asm.append(f"Size class {size}: the largest of users {_n(users)} -> {s_users}, peak concurrent "
               f"{_n(peak)} -> {s_peak}, data {_n(data_gb)} GB -> {s_data}.")

    # ---- shape -------------------------------------------------------
    platforms = list(p["project.platforms"])
    clients = tuple(c for c in CLIENT_PLATFORMS if c in platforms)
    api_only = "api_only" in platforms
    ptype = p["project.type"]
    auth = p["requirements.auth"]
    payments = bool(p["requirements.payments"])
    multi = bool(p["requirements.multi_tenant"])
    ml = p["requirements.ml_features"]
    workload = p["scale.workload"]
    points = [
        ("auth != none", auth != "none"), ("payments", payments), ("realtime", realtime),
        ("multi_tenant", multi), ("file_media_storage", media), ("ml_features != none", ml != "none"),
        ("workload != read_heavy", workload != "read_heavy"),
        ("project.type is not a static type", ptype not in STATIC_PROJECT_TYPES),
    ]
    dynamic = sum(1 for _, on in points if on)
    static = (auth == "none" and not payments and not realtime and not multi and not media
              and ml == "none" and ptype in STATIC_PROJECT_TYPES)
    needs_backend = (not static) or api_only
    on_list = [name for name, on in points if on]
    asm.append(f"Dynamic score {dynamic}/8 (" + (", ".join(on_list) if on_list else "no dynamic features")
               + "); " + ("a server backend and database are needed." if needs_backend else
                          "no server backend or database is needed: the site can be pre-rendered static pages."))
    if api_only and static:
        asm.append("project.platforms includes api_only, so a backend is needed even though no dynamic feature is set.")

    team_size = int(p["team.size"])
    weeks = int(p["timeline.mvp_weeks"])
    pressure, wpce = delivery_pressure(weeks, team_size, len(clients), needs_backend)
    units = max(1, len(clients) + (1 if needs_backend else 0))
    asm.append(f"Delivery pressure {pressure}/{PRESSURE_MAX}: {weeks} weeks x {team_size} engineer(s) / "
               f"{units} deliverable(s) = {_n(round(wpce, 2))} engineer-weeks each "
               f"(pressure 3 below 4, 2 below 8, 1 below 16).")

    exp = p["team.experience"]
    devops = bool(p["team.has_devops"])
    ops = ops_capacity(exp, devops, team_size)
    parts = [f"base {OPS_BASE.get(exp, 1)} ({exp})"]
    if devops:
        parts.append(f"+{OPS_DEVOPS_BONUS} (has_devops)")
    if team_size >= OPS_LARGE_TEAM_SIZE:
        parts.append(f"+{OPS_LARGE_TEAM_BONUS} (team.size {team_size} >= {OPS_LARGE_TEAM_SIZE})")
    asm.append(f"Operations capacity {ops}/{OPS_MAX}: " + " ".join(parts) + f", capped at {OPS_MAX}.")

    langs, lang_notes = _languages.normalize(p["team.languages"])
    for note in lang_notes:
        asm.append(note + ".")

    # ---- infrastructure ----------------------------------------------
    compliance = tuple(sorted(set(p["compliance"])))
    residency = p["infrastructure.data_residency"]
    effective = residency
    infeasible = False
    if "rbi_localisation" in compliance:
        if residency == "none":
            effective = "india"
            asm.append("infrastructure.data_residency treated as india because compliance includes "
                       "rbi_localisation (payment data must be stored only in India).")
            warns.append(_warning("RBI_IMPLIES_INDIA", "warning",
                                  "rbi_localisation requires payment data to be stored only in India; "
                                  "data_residency treated as india.",
                                  ["compliance", "infrastructure.data_residency"]))
        elif residency in ("eu", "us"):
            infeasible = True
            warns.append(_warning("RESIDENCY_COMPLIANCE_CONFLICT", "critical",
                                  f"rbi_localisation (India-only payment data) contradicts "
                                  f"data_residency={residency}.",
                                  ["compliance", "infrastructure.data_residency"]))
    if residency == "other":
        warns.append(_warning("RESIDENCY_UNVERIFIABLE", "critical",
                              "data_residency=other does not name a country; only self-hostable components "
                              "were used. Specify the country to check managed regions.",
                              ["infrastructure.data_residency"]))
    gdpr_pref = "gdpr" in compliance and effective == "none"
    if gdpr_pref:
        asm.append(f"compliance includes gdpr but data_residency is none: EU regions are preferred "
                   f"(+{EU_PREFERENCE_BONUS}), not required.")

    cloud_pref = p["infrastructure.cloud_preference"]
    cloud = cloud_pref if cloud_pref in HYPERSCALERS else None
    cloud_explicit = "infrastructure.cloud_preference" in provided and cloud_pref != "any"
    deployment = p["infrastructure.deployment_model"]
    if cloud_pref == "none" and deployment in ("managed_cloud", "self_hosted_cloud_vm"):
        asm.append("cloud_preference=none read as 'no AWS, GCP or Azure account': independent providers "
                   "or self-hosting are used.")
        warns.append(_warning("CLOUD_NONE_INTERPRETED", "info",
                              "cloud_preference=none read as 'avoid AWS/GCP/Azure accounts'; independent "
                              "providers used.", ["infrastructure.cloud_preference"]))
    regions = _regions(effective)

    # ---- data --------------------------------------------------------
    cons_in = p["requirements.consistency"]
    if cons_in in ("strong", "eventual"):
        consistency = cons_in
    else:
        reasons = []
        if payments:
            reasons.append("payments is true")
        if ptype in STRONG_CONSISTENCY_TYPES:
            reasons.append(f"project.type is {ptype}")
        strong_sigs = [s for s in sig_ids if s in STRONG_CONSISTENCY_SIGNALS]
        if strong_sigs:
            reasons.append("description mentions " + ", ".join(strong_sigs))
        consistency = "strong" if reasons else "eventual"
        asm.append(f"requirements.consistency auto resolved to {consistency}"
                   + (" because " + "; ".join(reasons) + "." if reasons else
                      ": no payments, money-handling project type or ledger/booking/inventory signal."))

    shape_in = p["requirements.data_shape"]
    if shape_in != "auto":
        data_shape = shape_in
    else:
        if ptype == "iot":
            data_shape, why = "time_series", "project.type is iot"
        elif ptype == "data_analytics":
            data_shape, why = "analytical", "project.type is data_analytics"
        elif any(s in TIME_SERIES_SIGNALS for s in sig_ids):
            data_shape, why = "time_series", "description mentions sensor/telemetry data"
        elif any(s in GRAPH_SIGNALS for s in sig_ids):
            data_shape, why = "graph", "description mentions " + ", ".join(s for s in sig_ids if s in GRAPH_SIGNALS)
        else:
            data_shape, why = "relational", "default for transactional application data"
        asm.append(f"requirements.data_shape auto resolved to {data_shape} ({why}).")

    money = payments or ptype == "fintech" or "pci_dss" in compliance or "rbi_localisation" in compliance

    weights = tuple(sorted((k, int(p[f"priorities.{k}"])) for k in PRIORITY_KEYS))
    india = effective == "india" or "dpdp" in compliance or "rbi_localisation" in compliance
    eu = effective == "eu" or "gdpr" in compliance

    return Profile(
        users=users, peak_concurrent=peak, peak_rps=rps, realtime_msgs_per_s=rt_rate,
        data_volume_gb=data_gb, size=size, size_users=s_users, size_peak=s_peak, size_data=s_data,
        ops_capacity=ops, delivery_pressure=pressure, weeks_per_client_per_engineer=round(wpce, 2),
        languages=tuple(langs), dynamic_score=dynamic, needs_backend=needs_backend,
        needs_database=needs_backend, clients=clients, api_only=api_only,
        residency=residency, effective_residency=effective, regions=regions,
        cloud_preference=cloud_pref, cloud=cloud, cloud_explicit=cloud_explicit, deployment=deployment,
        self_hosted_only=deployment in ("on_premise", "air_gapped"), air_gapped=deployment == "air_gapped",
        compliance=compliance, consistency=consistency, data_shape=data_shape, money=money,
        weights=weights, india=india, eu=eu, gdpr_eu_preference=gdpr_pref, infeasible=infeasible,
        assumptions=tuple(asm), warnings=tuple(warns), signals=signals, existing=existing, values=MappingProxyType(dict(p)),
    )

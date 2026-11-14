"""Candidate scoring (plan sections 3.8, 5.3, 5.3.1, 5.5 and the thresholds of 6.2).

``score(tech, p, ctx)`` returns a :class:`Scored` whose ``total`` is the exact sum of its
contributions. Each contribution is rounded to 2 decimals *before* summing, carries the input field
paths that drove it and a plain-language reason that quotes the literal input value(s), so
``explain.py`` can turn the list into justifications without any per-scenario text. Contributions
whose value rounds to 0 are omitted.

``rank(layer, candidates, p, ctx)`` scores every candidate and sorts by
``(-round(total, 4), tech["id"])`` (total order, independent of input order).

Every weight and threshold lives in the module-level table :data:`W` (the report prints it and the
tests import it). The architecture thresholds of plan 6.2 (``MICRO_MIN_TEAM`` ... ``K8S_MIN_SIZE``)
are module constants shared with ``architecture.py``/``combine.py``; scoring enforces the Kubernetes
and distributed-SQL thresholds as the ``overengineering`` penalty so the stack and the architecture
style cannot disagree.

Pure and deterministic: no clock, no randomness, sets always sorted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .kb import costs as _costs
from .kb import languages as _languages
from .kb.model import SIZE_CLASSES, SUPPORTING_LAYERS, size_index
from .schema import PRIORITY_KEYS

# ------------------------------------------------------------------ shared thresholds (plan 6.2)
MICRO_MIN_TEAM = 20
MICRO_MIN_SIZE = "l"
SOA_MIN_TEAM = 9
K8S_MIN_OPS = 4
K8S_MIN_SIZE = "m"
K8S_ONPREM_MIN_TEAM = 4          # on-prem/air-gapped exception of plan 5.4 C8
DISTRIBUTED_SQL_MIN_SIZE = "l"

# ------------------------------------------------------------------ weights (plan 5.3)
PRIORITY_ATTR = {
    "cost": "cost_efficiency", "time_to_market": "dev_velocity", "scalability": "scalability",
    "performance": "performance", "maintainability": "maintainability", "security": "security",
}

W: dict[str, Any] = {
    # 1 priorities: 10 * sum(p_k * a_k) / (5 * sum(p_k))
    "priorities_scale": 10, "priorities_attr_max": 5, "priorities_driver_count": 2,
    # 2 skill_fit
    "skill_known_threshold": _languages.KNOWN_THRESHOLD, "skill_known_factor": 4,
    "skill_penalty": {"senior": -2, "intermediate": -3, "mixed": -3, "beginner": -4},
    "skill_unwilling_factor": 2, "skill_pressure_min": 2, "skill_pressure_penalty": -1,
    "skill_min": -8, "skill_no_languages_factor": 0.6,
    "skill_html_css_ssg": _languages.HTML_CSS_SSG_AFFINITY,
    "skill_sql_bonus": _languages.SQL_SKILL_BONUS, "skill_sql_penalty": _languages.SQL_SKILL_PENALTY,
    "sql_kinds": ("embedded", "olap", "relational", "timeseries"),
    # 3 ops_fit
    "ops_over_factor": -1.5, "ops_slack_factor": 0.5, "ops_slack_max": 1, "ops_slack_cost_min": 4,
    "self_managed_kinds": ("onprem", "vm"),
    # 4 scale_fit
    "scale_over_per_class": -4, "scale_under_per_class": -2.5, "scale_within_factor": 0.5,
    "scale_within_min_size": "m", "scale_min": -12,
    # 5 budget_fit
    "budget_share": {"hosting": 0.40, "database": 0.25, "supporting": 0.35,
                     "backend": 0.40, "frontend": 0.25},
    "budget_free_ok": 3, "budget_free_noncommercial": -1.5, "budget_none_free": -8,
    # B > 0 (smooth, continuous in budget and cost): -slope per doubling of mid over the layer share,
    # a further -slope per doubling of min over the whole budget, floored at budget_fit_min
    "budget_over_slope": 3, "budget_whole_slope": 3, "budget_fit_min": -8,
    # 6 requirement_fit (table REQUIREMENT_RULES below)
    "req_native": 2, "req_workable": 0, "req_poor": -3, "req_min": -12, "req_max": 10,
    # 7 type_affinity
    "type_best": 3, "type_avoid": -3,
    # 8 reuse
    "reuse_exact": 4, "reuse_ecosystem": 2, "reuse_licence": 1.5,
    # 9 lock_in
    "lock_in_factor": {"low": -1.5, "medium": -0.5, "high": 0},
    # 10 availability_fit
    "availability_below": -5, "availability_no_redundancy": -5, "availability_overbuilt": -1,
    # 11 latency_fit
    "latency_tight_ms": 100, "latency_moderate_ms": 300, "latency_perf_factor": 1,
    "latency_cold_start": -3, "latency_moderate_share": 0.5,
    # 12 timeline_fit
    "timeline_factor": 0.5,
    # 13 traffic_fit
    "traffic_elastic": 1.5, "traffic_fixed": -1.5, "traffic_reserved": 1, "traffic_min_size": "m",
    "reserved_kinds": ("container", "hybrid_appliance", "k8s", "onprem", "vm"),
    # 14 workload_fit
    "workload_write_good": 1.5, "workload_write_bad": -1.5, "workload_read_good": 1,
    # 15 geo_fit
    "geo_wide_good": 2, "geo_wide_bad": -2, "geo_local_region": 1,
    # 16 data_fit
    "data_shape_match": 4, "data_non_acid_strong": -4, "data_rls": 2,
    # 17 gdpr_pref
    "gdpr_eu_region": 2,
    # 18 growth_fit
    "growth_ratio": 2, "growth_min": 10, "growth_maint_factor": 1, "growth_typed": 1,
    # 19 device_fit
    "device": {"native": 2, "cross_compiled": 1, "cross_js": -0.5, "webview": -1.5, "desktop_shell": -3},
    # 20 security_fit
    "security_priority_min": 4, "security_factor": 1, "security_baas_client": -1.5,
    "security_regimes": ("hipaa", "pci_dss", "rbi_localisation"),
    "security_baas_types": ("fintech", "healthtech"),
    # 21 overengineering (plan 3.12 / 6.2 thresholds enforced in scoring)
    "overengineering": -10,
    "MICRO_MIN_TEAM": MICRO_MIN_TEAM, "MICRO_MIN_SIZE": MICRO_MIN_SIZE, "SOA_MIN_TEAM": SOA_MIN_TEAM,
    "K8S_MIN_OPS": K8S_MIN_OPS, "K8S_MIN_SIZE": K8S_MIN_SIZE, "K8S_ONPREM_MIN_TEAM": K8S_ONPREM_MIN_TEAM,
    "DISTRIBUTED_SQL_MIN_SIZE": DISTRIBUTED_SQL_MIN_SIZE,
}

CONTRIBUTION_KEYS = (
    "priorities", "skill_fit", "ops_fit", "scale_fit", "budget_fit", "requirement_fit",
    "type_affinity", "reuse", "lock_in", "availability_fit", "latency_fit", "timeline_fit",
    "traffic_fit", "workload_fit", "geo_fit", "data_fit", "gdpr_pref", "growth_fit", "device_fit",
    "security_fit", "overengineering",
)

FRONTEND_LAYERS = ("frontend_web", "frontend_mobile", "frontend_desktop", "frontend_game")
CODE_LAYERS = FRONTEND_LAYERS + ("backend",)
MANAGED_BACKEND_KINDS = ("baas", "commerce_saas", "serverless_fn")
TYPED_LANGUAGES = ("csharp", "dart", "fsharp", "go", "java", "kotlin", "rust", "scala", "swift",
                   "typescript")
SHAPE_KINDS = {
    "relational": ("embedded", "relational"), "document": ("document",),
    "key_value": ("kv", "wide_column"), "time_series": ("timeseries",), "graph": ("graph",),
    "analytical": ("olap",),
}
DYNAMIC_FIELDS = ("requirements.auth", "requirements.payments", "requirements.realtime",
                  "requirements.multi_tenant", "requirements.file_media_storage",
                  "requirements.ml_features", "project.type")
SIZE_FIELDS = ("scale.users_12_months", "scale.peak_concurrent_users", "scale.data_volume_gb_12_months")
# Ecosystem tags for reuse (#8): what an existing system or licence makes cheaper to adopt.
LICENCE_ECOSYSTEM = {
    "microsoft_enterprise": ("azure", "dotnet", "sqlserver"), "oracle": ("jvm", "oracle"),
    "aws_credits": ("aws",), "gcp_credits": ("gcp",), "azure_credits": ("azure",),
}
KIND_ECOSYSTEM = {
    "entra_id": ("azure", "dotnet"), "active_directory": ("azure", "dotnet"),
    "sqlserver": ("azure", "dotnet", "sqlserver"), "microsoft365": ("azure", "dotnet"),
    "oracle_db": ("jvm", "oracle"), "oracle": ("jvm", "oracle"),
}
LANGUAGE_ECOSYSTEM = {"csharp": "dotnet", "fsharp": "dotnet", "java": "jvm", "kotlin": "jvm",
                      "scala": "jvm", "python": "python", "javascript": "node", "typescript": "node"}


# ------------------------------------------------------------------ data types
@dataclass(frozen=True)
class Contribution:
    """One scoring term. ``parts`` (optional) lists sub-terms ``(field, value, text)`` when one
    contribution aggregates several requirements (``requirement_fit``)."""
    key: str
    value: float
    fields: tuple[str, ...]
    reason: str
    parts: tuple[tuple[str, float, str], ...] = ()


@dataclass(frozen=True)
class Scored:
    tech: dict
    total: float
    contributions: tuple[Contribution, ...]

    def get(self, key: str) -> Contribution | None:
        for c in self.contributions:
            if c.key == key:
                return c
        return None

    def value(self, key: str) -> float:
        c = self.get(key)
        return c.value if c else 0.0


@dataclass(frozen=True)
class LayerContext:
    """What the candidate is being scored for.

    layer: core or supporting layer name. platform: client platform for frontend layers
    (web/android/ios/desktop). supporting_layers: number of triggered supporting layers that share
    the supporting budget. budget_share: override of the layer's share of the monthly budget
    (None = ``W["budget_share"]``)."""
    layer: str
    platform: str | None = None
    supporting_layers: int = 1
    budget_share: float | None = None

    def share(self, tech: dict | None = None) -> float:
        if self.budget_share is not None:
            return self.budget_share
        shares = W["budget_share"]
        if self.layer in SUPPORTING_LAYERS:
            return shares["supporting"] / max(1, self.supporting_layers)
        if self.layer in FRONTEND_LAYERS:
            return shares["frontend"]
        bundle = bundle_share(tech["id"]) if tech else None
        if bundle is not None:
            return bundle
        return shares.get(self.layer, shares["supporting"])


_BUNDLE_SHARES: dict[str, float] = {}


def bundle_share(record_id: str) -> float | None:
    """Budget share of a product billed as one plan across core layers (``cost.BUNDLED_BILLS``, e.g. a
    Supabase project is backend + database + host): the sum of the shares of the layers it spans, so
    one plan price is compared with the budget it actually covers. None for other records."""
    if not _BUNDLE_SHARES:
        from . import kb
        from .cost import BUNDLED_BILLS   # cost imports scoring: resolved lazily
        shares = W["budget_share"]
        for members, _why in BUNDLED_BILLS:
            layers = set()
            for mid in members:
                rec = kb.get(mid)
                layer = rec.get("layer") if rec else None
                if layer is None and any(o["id"] == mid for o in kb.OFFERINGS):
                    layer = "database"
                if layer in shares:
                    layers.add(layer)
            total = round(sum(shares[x] for x in sorted(layers)), 4)
            for mid in members:
                _BUNDLE_SHARES[mid] = total
        _BUNDLE_SHARES.setdefault("", 0.0)
    v = _BUNDLE_SHARES.get(record_id)
    return v if v else None


# ------------------------------------------------------------------ helpers
def fmt(value) -> str:
    """Literal input value as it appears in JSON-like text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            return f"{round(value, 2):,}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(fmt(v) for v in value) + "]"
    return str(value)


def _num(x: float) -> str:
    x = round(x, 2)
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _signed(x: float) -> str:
    x = round(x, 2)
    return ("+" if x > 0 else "") + _num(x)


def val(p, path: str, default=None):
    vals = getattr(p, "values", None)
    if vals is None:
        return default
    return vals.get(path, default)


def _caps(tech) -> list:
    return tech.get("caps") or []


def _has(tech, *caps) -> bool:
    have = _caps(tech)
    return any(c in have for c in caps)


def _attr(tech, key) -> float:
    return (tech.get("attrs") or {}).get(key, 3)


def _sig_ids(p) -> list[str]:
    return sorted({s.id for s in (getattr(p, "signals", ()) or ())})


def _size_ge(a: str, b: str) -> bool:
    return size_index(a) >= size_index(b)


def _size_fields(p) -> tuple[str, ...]:
    """Inputs behind the size class: the sub-dimensions that reach p.size."""
    out = []
    u12 = val(p, "scale.users_12_months")
    launch = val(p, "scale.users_at_launch")
    users_field = "scale.users_at_launch" if (isinstance(launch, (int, float)) and isinstance(u12, (int, float))
                                              and launch > u12) else "scale.users_12_months"
    if p.size_users == p.size:
        out.append(users_field)
    if p.size_peak == p.size:
        out.append("scale.peak_concurrent_users" if val(p, "scale.peak_concurrent_users") is not None
                   else users_field)
    if p.size_data == p.size:
        out.append("scale.data_volume_gb_12_months" if val(p, "scale.data_volume_gb_12_months") is not None
                   else users_field)
    seen, res = set(), []
    for f in out or [users_field]:
        if f not in seen:
            seen.add(f)
            res.append(f)
    return tuple(res)


def _size_text(p) -> str:
    def dim(path, derived, cls, unit=""):
        given = val(p, path)
        if given is not None:
            return f"{path}={fmt(given)}{unit} -> {cls}"
        return f"{path.split('.')[-1]} estimated {fmt(derived)}{unit} -> {cls}"
    u12, launch = val(p, "scale.users_12_months"), val(p, "scale.users_at_launch")
    upath = ("scale.users_at_launch" if isinstance(launch, (int, float)) and isinstance(u12, (int, float))
             and launch > u12 else "scale.users_12_months")
    return (f"size class {p.size} ({dim(upath, p.users, p.size_users)}, "
            f"{dim('scale.peak_concurrent_users', p.peak_concurrent, p.size_peak)}, "
            f"{dim('scale.data_volume_gb_12_months', p.data_volume_gb, p.size_data, ' GB')})")


def _cap1(text: str) -> str:
    return text[:1].upper() + text[1:]


def _resolved_cms(p) -> tuple[str | None, str]:
    cms = val(p, "requirements.cms", "auto")
    if cms and cms != "auto":
        return cms, f"requirements.cms={cms}"
    for s in getattr(p, "signals", ()) or ():
        eff = getattr(s, "effect", "") or ""
        if eff.startswith("cms="):
            return eff.split("=", 1)[1], f"project.description mentions '{s.matched_text}' (cms={eff.split('=', 1)[1]})"
    return None, ""


def _is_k8s(tech) -> bool:
    return tech.get("kind") == "k8s" or _has(tech, "kubernetes")


def _languages_label(p) -> str:
    raw = val(p, "team.languages")
    return "team.languages=" + fmt(raw if raw is not None else list(p.languages))


# ------------------------------------------------------------------ 1 priorities
def _priorities(tech, p, ctx):
    num = den = 0.0
    drivers = []
    for k in PRIORITY_KEYS:
        w = p.weight(k)
        a = _attr(tech, PRIORITY_ATTR[k])
        num += w * a
        den += w
        drivers.append((-abs(w * (a - 3)), PRIORITY_KEYS.index(k), k, w, a))
    value = W["priorities_scale"] * num / (W["priorities_attr_max"] * den) if den else 0.0
    drivers.sort()
    top = drivers[:W["priorities_driver_count"]]
    fields = tuple(f"priorities.{k}" for _, _, k, _, _ in top)
    detail = ", ".join(f"priorities.{k}={w} x {PRIORITY_ATTR[k]} {_num(a)}/5" for _, _, k, w, a in top)
    reason = (f"Weighted fit of {tech['name']}'s attributes to the six priorities is {_num(value)}/10; "
              f"strongest effects: {detail}.")
    return value, fields, reason


# ------------------------------------------------------------------ 2 skill_fit
def _skill(tech, p, ctx):
    langs = list(p.languages)
    if ctx.layer == "database" or tech.get("layer") == "database":
        if "sql" not in langs or tech.get("kind") == "none":
            return None
        if tech.get("kind") in W["sql_kinds"]:
            return (W["skill_sql_bonus"], ("team.languages",),
                    f"{_languages_label(p)} includes SQL, which {tech['name']} speaks.")
        return (W["skill_sql_penalty"], ("team.languages",),
                f"{_languages_label(p)} includes SQL, but {tech['name']} is not queried with SQL.")
    rec = tech.get("languages") or []
    if not rec:
        return None
    if not langs:
        v = W["skill_no_languages_factor"] * (_attr(tech, "popularity") - 3)
        return (v, ("team.languages",),
                f"team.languages is empty, so skill fit falls back to popularity "
                f"{_num(_attr(tech, 'popularity'))}/5 of {tech['name']}.")
    best, pair = 0.0, None
    for k in sorted(langs):
        for n in sorted(rec):
            a = _languages.affinity(k, n)
            if tech.get("kind") == "ssg" and k in ("html", "css"):
                a = max(a, W["skill_html_css_ssg"])
            if a > best:
                best, pair = a, (k, n)
    rec_txt = "/".join(rec)
    if best >= W["skill_known_threshold"]:
        k, n = pair
        how = f"includes {k}" if k == n else f"includes {k}, close to {n}"
        return (W["skill_known_factor"] * best, ("team.languages",),
                f"{_languages_label(p)} {how}, which {tech['name']} uses (affinity {_num(best)}).")
    exp = val(p, "team.experience", "intermediate")
    v = W["skill_penalty"].get(exp, W["skill_penalty"]["intermediate"])
    fields = ["team.languages", "team.experience"]
    extra = []
    willing = val(p, "team.willing_to_learn", True)
    if willing is False:
        v *= W["skill_unwilling_factor"]
        fields.append("team.willing_to_learn")
        extra.append("team.willing_to_learn=false doubles the penalty")
    if p.delivery_pressure >= W["skill_pressure_min"]:
        v += W["skill_pressure_penalty"]
        fields.append("timeline.mvp_weeks")
        extra.append(f"timeline.mvp_weeks={fmt(val(p, 'timeline.mvp_weeks'))} leaves little time to learn "
                     f"(delivery pressure {p.delivery_pressure}/3)")
    v = max(W["skill_min"], v)
    near = f" (best affinity {_num(best)} from {pair[0]})" if pair else ""
    reason = (f"{_languages_label(p)} does not include {rec_txt} needed by {tech['name']}{near}; "
              f"team.experience={exp}" + ("; " + "; ".join(extra) if extra else "") + ".")
    return v, tuple(fields), reason


# ------------------------------------------------------------------ 3 ops_fit
def _ops(tech, p, ctx):
    burden = tech.get("ops_burden", 0)
    cap = p.ops_capacity
    fields = ("team.has_devops", "team.experience", "team.size")
    team = (f"team.experience={val(p, 'team.experience')}, team.has_devops={fmt(val(p, 'team.has_devops'))}, "
            f"team.size={fmt(val(p, 'team.size'))}")
    if burden > cap:
        v = W["ops_over_factor"] * (burden - cap)
        return v, fields, (f"{tech['name']} needs operations effort {_num(burden)}/5 but the team's capacity is "
                           f"{cap}/5 ({team}).")
    cost_w = p.weight("cost")
    if cost_w >= W["ops_slack_cost_min"] and tech.get("kind") in W["self_managed_kinds"] and cap > burden:
        v = min(W["ops_slack_max"], W["ops_slack_factor"] * (cap - burden))
        return v, fields + ("priorities.cost",), (
            f"Self-managed {tech['name']} (ops {_num(burden)}/5) fits the team's capacity {cap}/5 ({team}) and "
            f"is cheaper, which priorities.cost={cost_w} rewards.")
    return None


# ------------------------------------------------------------------ 4 scale_fit
def _scale(tech, p, ctx):
    size = size_index(p.size)
    floor, ceil = size_index(tech["scale_floor"]), size_index(tech["scale_ceiling"])
    fields = _size_fields(p)
    if size > ceil:
        v = max(W["scale_min"], W["scale_over_per_class"] * (size - ceil))
        return v, fields, f"{_cap1(_size_text(p))} is above {tech['name']}'s ceiling {tech['scale_ceiling']}."
    if size < floor:
        v = max(W["scale_min"], W["scale_under_per_class"] * (floor - size))
        return v, fields, (f"{_cap1(_size_text(p))} is below {tech['name']}'s floor {tech['scale_floor']} "
                           f"(over-engineering for this size).")
    if _size_ge(p.size, W["scale_within_min_size"]):
        v = W["scale_within_factor"] * (_attr(tech, "scalability") - 3)
        return v, fields, (f"{_cap1(_size_text(p))} is within {tech['name']}'s range; scalability "
                           f"{_num(_attr(tech, 'scalability'))}/5 matters at this size.")
    return None


# ------------------------------------------------------------------ 5 budget_fit
def _budget(tech, p, ctx):
    band = _costs.band_for(tech.get("cost") or {}, p.size)
    if band is None:
        return None  # not offered at this size: scale_fit covers it
    lo, hi, _derived = band
    if ctx.layer in CODE_LAYERS and lo == 0 and hi == 0:
        return None  # frameworks and toolkits cost nothing themselves
    fields = ("budget.monthly_infra_usd",) + _size_fields(p)
    got = budget_fit_value(tech["name"], lo, hi, tech.get("free_tier") or {}, ctx.share(tech), p)
    if got is None:
        return None
    return got[0], fields, got[1]


def budget_fit_value(name: str, lo: float, hi: float, free_tier: dict, share_frac: float, p
                     ) -> tuple[float, str] | None:
    """budget_fit for a priced item with band ``lo``-``hi`` and budget share ``share_frac`` (also used
    by ``combine.py`` for items billed once across layers). Smooth in budget and cost for budget > 0:
    ``-(slope x log2(mid / share) + slope x log2(min / budget) when min > budget)``, floored."""
    budget = val(p, "budget.monthly_infra_usd", 0) or 0
    btxt = f"budget.monthly_infra_usd={fmt(budget)}"
    if budget == 0:
        ft = free_tier or {}
        if lo == 0:
            if ft and ft.get("commercial_use") is False:
                return (W["budget_free_noncommercial"],
                        f"{btxt}: {name} is free at size {p.size}, but its free tier excludes commercial use.")
            return (W["budget_free_ok"], f"{btxt}: {name} costs USD 0 at size {p.size}"
                    + (f" (free tier: {ft.get('limit')})." if ft.get("limit") else "."))
        return (W["budget_none_free"],
                f"{btxt}, but {name} costs at least USD {_num(lo)}/month at size {p.size} and has no free option.")
    share = budget * share_frac
    mid = (lo + hi) / 2
    if share <= 0 or mid <= share:
        return None
    over = W["budget_over_slope"] * math.log2(mid / share)
    whole = W["budget_whole_slope"] * math.log2(lo / budget) if lo > budget else 0.0
    v = round(max(W["budget_fit_min"], -(over + whole)), 2)
    if not v:
        return None
    text = (f"{name} costs about USD {_num(mid)}/month (USD {_num(lo)}-{_num(hi)}) at size {p.size}, "
            f"{_num(round(mid / share, 1))}x this layer's share USD {_num(share)} of {btxt}")
    if whole:
        text += "; its minimum alone is above the whole budget"
    return v, text + "."


# ------------------------------------------------------------------ 6 requirement_fit (plan 5.3.1)
# Each rule: (requirement field, layers, active(p) -> bool, judge(tech, p) -> (value, why) | None).
def _rq_seo(t, p):
    k = t.get("kind")
    if k == "spa":
        if _has(t, "ssg", "ssr"):
            return W["req_workable"], f"{t['name']} is a client-side SPA that can pre-render with an add-on"
        return W["req_poor"], f"{t['name']} renders only in the browser (client-only SPA)"
    if k in ("ssg", "ssr", "server_templates") or _has(t, "ssg", "ssr", "server_templates"):
        return W["req_native"], f"{t['name']} serves pre-rendered or server-rendered HTML ({k})"
    return W["req_poor"], f"{t['name']} does not serve crawlable HTML"


def _rq_realtime_backend(t, p):
    if _has(t, "realtime_builtin") or (_has(t, "websocket") and _has(t, "long_lived_conn")):
        return W["req_native"], f"{t['name']} keeps WebSocket connections open"
    if t.get("kind") in ("serverless_fn", "none") or _has(t, "static_only"):
        return W["req_poor"], f"{t['name']} handles requests only and cannot hold connections open"
    return W["req_workable"], f"{t['name']} needs an add-on for WebSockets"


def _rq_realtime_host(t, p):
    if _has(t, "long_lived_conn") and _has(t, "websocket"):
        if _has(t, "cold_start") and _has(t, "scale_to_zero"):
            return W["req_workable"], f"{t['name']} supports WebSockets with request-time limits and needs min instances"
        return W["req_native"], f"{t['name']} supports long-lived WebSocket connections"
    if t.get("kind") in ("static_host", "serverless_fn"):
        return W["req_poor"], f"{t['name']} cannot hold long-lived connections"
    return W["req_workable"], f"{t['name']} needs extra setup for long-lived connections"


def _rq_offline_mobile(t, p):
    if _has(t, "offline_sqlite"):
        return W["req_native"], f"{t['name']} stores data on the device in SQLite"
    if t.get("kind") == "pwa":
        if val(p, "requirements.file_media_storage"):
            return W["req_poor"], f"{t['name']} cannot reliably queue large media uploads in the background"
        return W["req_workable"], f"{t['name']} works offline through a service worker"
    if _has(t, "offline"):
        return W["req_workable"], f"{t['name']} works offline with a plugin store"
    return W["req_poor"], f"{t['name']} has no offline storage"


def _rq_offline_desktop(t, p):
    if _has(t, "offline"):
        return W["req_native"], f"{t['name']} runs fully on the device"
    return W["req_poor"], f"{t['name']} needs a connection"


def _rq_offline_backend(t, p):
    if _has(t, "offline"):
        return W["req_native"], f"{t['name']} syncs offline client changes itself"
    return None


def _rq_fts(t, p):
    if t.get("kind") == "none":
        return None
    if _has(t, "fts_builtin"):
        return W["req_native"], f"{t['name']} has built-in full-text search"
    return W["req_workable"], f"{t['name']} needs an external search engine"


def _rq_media_backend(t, p):
    if _has(t, "storage_builtin"):
        return W["req_native"], f"{t['name']} has a built-in file storage API"
    return None


def _rq_payments_db(t, p):
    if t.get("kind") == "none":
        return None
    if _has(t, "acid"):
        return W["req_native"], f"{t['name']} has ACID transactions for payment records"
    return W["req_poor"], f"{t['name']} is not ACID, a poor system of record for payments"


def _rq_sso(t, p):
    if _has(t, "enterprise_sso"):
        return W["req_native"], f"{t['name']} has first-class OIDC/SAML single sign-on"
    if t.get("kind") in ("baas", "commerce_saas"):
        return W["req_poor"], f"{t['name']} offers no enterprise SAML/OIDC sign-on on its standard plans"
    if t.get("kind") == "none":
        return None
    return W["req_workable"], f"{t['name']} needs a generic OIDC library"


def _rq_phone_otp(t, p):
    if _has(t, "phone_otp"):
        return W["req_native"], f"{t['name']} has phone OTP sign-in with SMS hooks"
    if t.get("kind") == "framework":
        return W["req_native"], f"{t['name']} can send OTPs through any SMS provider"
    return None


def _rq_basic_auth(t, p):
    if _has(t, "auth_builtin"):
        return W["req_native"], f"{t['name']} has built-in user accounts and sessions"
    return None


def _rq_multi_tenant_db(t, p):
    if t.get("kind") == "embedded" and _size_ge(p.size, "m"):
        return W["req_poor"], f"{t['name']} is a single-file store, unsuited to many tenants at size {p.size}"
    return None  # row-level security is credited once, in data_fit


def _rq_multi_tenant_backend(t, p):
    if _has(t, "rls_multi_tenant"):
        return W["req_native"], f"{t['name']} enforces tenant isolation with row-level security"
    return None


def _rq_vector(t, p):
    if t.get("kind") == "none":
        return None
    if _has(t, "vector"):
        return W["req_native"], f"{t['name']} stores vector embeddings"
    return W["req_workable"], f"{t['name']} needs an external vector database"


def _rq_ml_backend(t, p):
    if _has(t, "ml_python") or (t.get("kind") == "framework" and "python" in (t.get("languages") or [])):
        return W["req_native"], f"{t['name']} runs Python model code in-process"
    if t.get("kind") == "baas" or t.get("runtime") == "edge_js":
        return W["req_poor"], f"{t['name']} cannot host the model-serving path"
    if t.get("runtime") in ("jvm", "dotnet"):
        return W["req_workable"], f"{t['name']} can serve models through ONNX Runtime"
    return None


def _rq_jobs_backend(t, p):
    if _has(t, "background_jobs"):
        return W["req_native"], f"{t['name']} has a built-in background job runner"
    if t.get("kind") == "none" or _has(t, "static_only"):
        return W["req_poor"], f"{t['name']} cannot run background work"
    if t.get("kind") == "serverless_fn":
        return W["req_workable"], f"{t['name']} runs jobs as functions plus a queue"
    return None


def _rq_jobs_host(t, p):
    if _has(t, "background_jobs"):
        return W["req_native"], f"{t['name']} runs worker processes or scheduled jobs"
    if t.get("kind") == "static_host":
        return W["req_poor"], f"{t['name']} serves static files and cannot run workers"
    return None


def _rq_cms_git_frontend(t, p):
    if _has(t, "git_markdown"):
        return W["req_native"], f"{t['name']} builds pages from Markdown files in git"
    if t.get("kind") == "spa":
        return W["req_poor"], f"{t['name']} has no Markdown content pipeline"
    if t.get("kind") in ("ssr", "ssg"):
        return W["req_workable"], f"{t['name']} supports Markdown through an MDX add-on"
    return None


def _rq_cms_headless_backend(t, p):
    if _has(t, "cms_headless"):
        return W["req_native"], f"{t['name']} is a headless CMS with an editor UI"
    if t.get("kind") == "none" or _has(t, "static_only"):
        return W["req_poor"], f"{t['name']} gives editors no admin UI"
    if _has(t, "admin_ui"):
        return W["req_workable"], f"{t['name']} has an admin UI that can be customised for content"
    return None


def _rq_push(t, p):
    if _has(t, "push_notifications"):
        return W["req_native"], f"{t['name']} supports FCM/APNs push notifications"
    return W["req_poor"], f"{t['name']} cannot receive push notifications"


def _dynamic_text(p) -> str:
    on = []
    if val(p, "requirements.auth", "none") != "none":
        on.append(f"requirements.auth={val(p, 'requirements.auth')}")
    for f in ("payments", "realtime", "multi_tenant", "file_media_storage"):
        if val(p, f"requirements.{f}"):
            on.append(f"requirements.{f}=true")
    if val(p, "requirements.ml_features", "none") != "none":
        on.append(f"requirements.ml_features={val(p, 'requirements.ml_features')}")
    if not on:
        on.append(f"project.type={val(p, 'project.type')}")
    return ", ".join(on)


def _static_text(p) -> str:
    return (f"requirements.auth={val(p, 'requirements.auth')}, requirements.payments=false, "
            f"requirements.realtime=false, project.type={val(p, 'project.type')}")


def _rq_dynamic_server(t, p):
    none = t.get("kind") == "none"
    if p.needs_backend:
        if none:
            return W["req_poor"], f"server logic is needed ({_dynamic_text(p)}) but {t['name']} provides none"
        return None
    if none:
        return W["req_native"], f"no feature needs a server ({_static_text(p)})"
    return W["req_poor"], f"{t['name']} adds a server although no feature needs one ({_static_text(p)})"


def _rq_dynamic_host(t, p):
    if p.needs_backend:
        return None
    k = t.get("kind")
    if k == "static_host" or (k == "serverless_fn" and _has(t, "edge")):
        return W["req_native"], f"pre-rendered pages need only static hosting, which {t['name']} provides ({_static_text(p)})"
    if k in W["reserved_kinds"]:
        return W["req_poor"], (f"{t['name']} runs servers although the site can be pre-rendered static pages "
                               f"({_static_text(p)})")
    return None


def _active(path, test=bool):
    return lambda p: test(val(p, path))


REQUIREMENT_RULES: tuple[tuple[str, tuple[str, ...], Callable, Callable], ...] = (
    ("requirements.seo_critical", ("frontend_web",), _active("requirements.seo_critical"), _rq_seo),
    ("requirements.realtime", ("backend",), _active("requirements.realtime"), _rq_realtime_backend),
    ("requirements.realtime", ("hosting",), _active("requirements.realtime"), _rq_realtime_host),
    ("requirements.offline_support", ("frontend_mobile",), _active("requirements.offline_support"), _rq_offline_mobile),
    ("requirements.offline_support", ("frontend_desktop",), _active("requirements.offline_support"), _rq_offline_desktop),
    ("requirements.offline_support", ("backend",), _active("requirements.offline_support"), _rq_offline_backend),
    ("requirements.full_text_search", ("database",), _active("requirements.full_text_search"), _rq_fts),
    ("requirements.file_media_storage", ("backend",), _active("requirements.file_media_storage"), _rq_media_backend),
    ("requirements.payments", ("database",), _active("requirements.payments"), _rq_payments_db),
    ("requirements.auth", ("backend",), _active("requirements.auth", lambda v: v == "enterprise_sso"), _rq_sso),
    ("requirements.auth", ("backend",), _active("requirements.auth", lambda v: v == "phone_otp"), _rq_phone_otp),
    ("requirements.auth", ("backend",), _active("requirements.auth", lambda v: v in ("email_password", "social")),
     _rq_basic_auth),
    ("requirements.multi_tenant", ("database",), _active("requirements.multi_tenant"), _rq_multi_tenant_db),
    ("requirements.multi_tenant", ("backend",), _active("requirements.multi_tenant"), _rq_multi_tenant_backend),
    ("requirements.ml_features", ("database",), _active("requirements.ml_features", lambda v: v == "llm_rag"), _rq_vector),
    ("requirements.ml_features", ("backend",),
     _active("requirements.ml_features", lambda v: v in ("inference_api", "training")), _rq_ml_backend),
    ("requirements.background_jobs", ("backend",), _active("requirements.background_jobs"), _rq_jobs_backend),
    ("requirements.background_jobs", ("hosting",), _active("requirements.background_jobs"), _rq_jobs_host),
    ("requirements.cms", ("frontend_web",), lambda p: _resolved_cms(p)[0] == "git_markdown", _rq_cms_git_frontend),
    ("requirements.cms", ("backend",), lambda p: _resolved_cms(p)[0] == "headless", _rq_cms_headless_backend),
    ("requirements.notifications", ("frontend_mobile",),
     _active("requirements.notifications", lambda v: "push" in (v or ())), _rq_push),
    # Whether a server is needed at all (plan 5.1 dynamic score).
    ("dynamic", ("backend", "database"), lambda p: True, _rq_dynamic_server),
    ("dynamic", ("hosting",), lambda p: True, _rq_dynamic_host),
)
# Fields covered elsewhere: availability (#10), p95_latency_ms (#11), consistency and data_shape (#16).


def _requirement_label(path, p) -> str:
    if path == "dynamic":
        return ""
    if path == "requirements.cms":
        return _resolved_cms(p)[1]
    v = val(p, path)
    if path == "requirements.notifications":
        return f"{path} includes push"
    return f"{path}={fmt(v)}"


def _requirements(tech, p, ctx):
    parts = []
    for path, layers, active, judge in REQUIREMENT_RULES:
        if ctx.layer not in layers or not active(p):
            continue
        res = judge(tech, p)
        if res is None:
            continue
        v, why = res
        label = _requirement_label(path, p)
        text = f"{label}: {why}" if label else why[0].upper() + why[1:]
        fields = DYNAMIC_FIELDS if path == "dynamic" else ((path, "project.description") if path == "requirements.cms"
                                                           and val(p, path) == "auto" else (path,))
        parts.append((fields, float(v), f"{text} ({_signed(v)})"))
    if not parts:
        return None
    total = max(W["req_min"], min(W["req_max"], sum(v for _, v, _ in parts)))
    if round(total, 2) == 0 and all(v == 0 for _, v, _ in parts):
        return None
    fields, seen = [], set()
    for fs, v, _ in parts:
        if v == 0:
            continue
        for f in fs:
            if f not in seen:
                seen.add(f)
                fields.append(f)
    if not fields:
        for fs, _, _ in parts:
            for f in fs:
                if f not in seen:
                    seen.add(f)
                    fields.append(f)
    reason = "; ".join(t for _, _, t in parts) + "."
    flat = tuple((fs[0], round(v, 2), t) for fs, v, t in parts)
    return total, tuple(fields), reason, flat


# ------------------------------------------------------------------ 7 type_affinity
def _type(tech, p, ctx):
    t = val(p, "project.type")
    if t in (tech.get("best_for") or []):
        return W["type_best"], ("project.type",), f"project.type={t} is listed among {tech['name']}'s best uses."
    if t in (tech.get("avoid_for") or []):
        return W["type_avoid"], ("project.type",), f"project.type={t} is a poor match for {tech['name']}."
    return None


# ------------------------------------------------------------------ 8 reuse
def _tech_ecosystems(tech) -> set:
    eco = {c for c in (tech.get("cloud_affinity") or []) if c in ("aws", "azure", "gcp")}
    if tech.get("underlying_cloud") in ("aws", "azure", "gcp"):
        eco.add(tech["underlying_cloud"])
    rt = tech.get("runtime")
    for r in (rt if isinstance(rt, list) else [rt]):
        if r in ("dotnet", "jvm", "python", "node"):
            eco.add(r)
    for lang in tech.get("languages") or []:
        if lang in LANGUAGE_ECOSYSTEM:
            eco.add(LANGUAGE_ECOSYSTEM[lang])
    eco.add(tech.get("id"))  # a record is its own ecosystem (e.g. an existing SQL Server -> sqlserver)
    return eco


def _reuse(tech, p, ctx):
    ex = getattr(p, "existing", None)
    v, fields, why = 0.0, [], []
    matches = list(getattr(ex, "matches", ()) or ()) if ex else []
    exact = [m for m in matches if tech["id"] in (m.reuse_targets or ())
             and not (m.eol and m.eol.get("status") in ("eol", "retired", "unsupported"))]
    teco = _tech_ecosystems(tech)
    if exact:
        v += W["reuse_exact"]
        why.append(f"infrastructure.existing_systems includes '{exact[0].raw}', which {tech['name']} reuses")
        fields.append("infrastructure.existing_systems")
    else:
        for m in matches:
            meco = set(m.reuse_targets or ())
            meco |= set(KIND_ECOSYSTEM.get(m.kind, ()))
            common = sorted(meco & teco)
            if common:
                v += W["reuse_ecosystem"]
                why.append(f"infrastructure.existing_systems includes '{m.raw}', in the same {common[0]} "
                           f"ecosystem as {tech['name']}")
                fields.append("infrastructure.existing_systems")
                break
    lic = [x for x in (val(p, "infrastructure.existing_licences") or []) if x in LICENCE_ECOSYSTEM]
    for x in sorted(lic):
        common = sorted(set(LICENCE_ECOSYSTEM[x]) & teco)
        if common:
            v += W["reuse_licence"]
            why.append(f"infrastructure.existing_licences includes {x}, which covers {tech['name']}")
            fields.append("infrastructure.existing_licences")
            break
    if not v:
        return None
    return v, tuple(fields), "; ".join(why) + "."


# ------------------------------------------------------------------ 9 lock_in
def _lock_in(tech, p, ctx):
    tol = val(p, "infrastructure.lock_in_tolerance", "medium")
    li = tech.get("lock_in", 0)
    factor = W["lock_in_factor"].get(tol, W["lock_in_factor"]["medium"])
    if not li or not factor:
        return None
    return (factor * li, ("infrastructure.lock_in_tolerance",),
            f"infrastructure.lock_in_tolerance={tol} and {tech['name']} has lock-in {li}/3.")


# ------------------------------------------------------------------ 10 availability_fit
def _max_sla(tech) -> float:
    if _has(tech, "multi_region"):
        return 99.99
    if _has(tech, "multi_az"):
        return 99.95
    return 99.9


def _infra_like(tech, ctx) -> bool:
    return ctx.layer in ("hosting", "database") or (ctx.layer == "backend" and tech.get("kind") in MANAGED_BACKEND_KINDS)


def _availability(tech, p, ctx):
    if not _infra_like(tech, ctx) or tech.get("kind") == "none":
        return None
    target_s = str(val(p, "requirements.availability", "99.9"))
    try:
        target = float(target_s)
    except ValueError:
        return None
    v, why = 0.0, []
    sla = _max_sla(tech)
    if sla < target:
        v += W["availability_below"]
        why.append(f"{tech['name']} supports about {_num(sla)}% (no "
                   f"{'multi-region' if target >= 99.99 else 'multi-AZ'} option)")
    if target >= 99.99 and not _has(tech, "multi_region", "multi_az"):
        v += W["availability_no_redundancy"]
        why.append(f"{tech['name']} has neither multi-AZ nor multi-region deployment")
    if target <= 99 and (_has(tech, "distributed_sql") or tech.get("kind") == "hybrid_appliance"):
        v += W["availability_overbuilt"]
        why.append(f"{tech['name']} is priced for multi-node redundancy that a 99% target does not need")
    if not v:
        return None
    return v, ("requirements.availability",), f"requirements.availability={target_s}: " + "; ".join(why) + "."


# ------------------------------------------------------------------ 11 latency_fit
def _latency(tech, p, ctx):
    if ctx.layer not in ("backend", "database", "hosting") or tech.get("kind") == "none":
        return None
    ms = val(p, "requirements.p95_latency_ms")
    if ms is None:
        return None
    if ms <= W["latency_tight_ms"]:
        share = 1.0
    elif ms <= W["latency_moderate_ms"]:
        share = W["latency_moderate_share"]
    else:
        return None
    perf = _attr(tech, "performance")
    v = share * W["latency_perf_factor"] * (perf - 3)
    why = [f"{tech['name']} performance {_num(perf)}/5"]
    if _has(tech, "cold_start") and not _has(tech, "min_instances"):
        v += share * W["latency_cold_start"]
        why.append("cold starts with no minimum-instance option")
    if not round(v, 2):
        return None
    return v, ("requirements.p95_latency_ms",), f"requirements.p95_latency_ms={fmt(ms)}: " + ", ".join(why) + "."


# ------------------------------------------------------------------ 12 timeline_fit
def _timeline(tech, p, ctx):
    if not p.delivery_pressure:
        return None
    dv = _attr(tech, "dev_velocity")
    v = p.delivery_pressure * W["timeline_factor"] * (dv - 3)
    if not v:
        return None
    return v, ("timeline.mvp_weeks", "team.size", "project.platforms"), (
        f"timeline.mvp_weeks={fmt(val(p, 'timeline.mvp_weeks'))} with team.size={fmt(val(p, 'team.size'))} for "
        f"project.platforms {fmt(val(p, 'project.platforms'))} gives delivery pressure {p.delivery_pressure}/3; "
        f"{tech['name']} development speed {_num(dv)}/5.")


# ------------------------------------------------------------------ 13 traffic_fit
def _traffic(tech, p, ctx):
    if ctx.layer != "hosting":
        return None
    pat = val(p, "scale.traffic_pattern", "steady")
    big = _size_ge(p.size, W["traffic_min_size"])
    if pat in ("spiky", "seasonal"):
        if _has(tech, "scale_to_zero", "autoscaling"):
            return W["traffic_elastic"], ("scale.traffic_pattern",), (
                f"scale.traffic_pattern={pat}: {tech['name']} scales automatically with load.")
        if big and (tech.get("kind") == "vm" or _has(tech, "fixed_capacity")):
            return W["traffic_fixed"], ("scale.traffic_pattern",) + _size_fields(p), (
                f"scale.traffic_pattern={pat}: {tech['name']} is fixed capacity, sized for the peak at {p.size}.")
        return None
    if pat == "steady" and big and tech.get("kind") in W["reserved_kinds"]:
        return W["traffic_reserved"], ("scale.traffic_pattern",) + _size_fields(p), (
            f"scale.traffic_pattern=steady at size {p.size}: {tech['name']} can use reserved capacity.")
    return None


# ------------------------------------------------------------------ 14 workload_fit
def _workload(tech, p, ctx):
    if ctx.layer != "database" or tech.get("kind") == "none":
        return None
    wl = val(p, "scale.workload", "balanced")
    if wl == "write_heavy":
        if _has(tech, "lsm_writes", "write_scaling"):
            return W["workload_write_good"], ("scale.workload",), (
                f"scale.workload=write_heavy: {tech['name']} scales write throughput.")
        if tech.get("kind") == "embedded" or _has(tech, "embedded"):
            return W["workload_write_bad"], ("scale.workload",), (
                f"scale.workload=write_heavy: {tech['name']} allows a single writer at a time.")
    elif wl == "read_heavy" and _has(tech, "read_replicas", "edge"):
        return W["workload_read_good"], ("scale.workload",), (
            f"scale.workload=read_heavy: {tech['name']} offers read replicas or edge reads.")
    return None


# ------------------------------------------------------------------ 15 geo_fit
def _geo(tech, p, ctx):
    if not _infra_like(tech, ctx) or tech.get("kind") == "none":
        return None
    spread = val(p, "scale.geographic_spread", "single_country")
    if spread in ("global", "multi_region"):
        if _has(tech, "edge", "multi_region"):
            return W["geo_wide_good"], ("scale.geographic_spread",), (
                f"scale.geographic_spread={spread}: {tech['name']} serves from many regions or the edge.")
        if tech.get("kind") in ("paas", "baas"):
            return W["geo_wide_bad"], ("scale.geographic_spread",), (
                f"scale.geographic_spread={spread}: {tech['name']} runs in one region only.")
        return None
    res = p.effective_residency
    if res in ("india", "eu", "us") and (tech.get("regions") or {}).get(res):
        return W["geo_local_region"], ("scale.geographic_spread", "infrastructure.data_residency"), (
            f"scale.geographic_spread={spread} with infrastructure.data_residency={val(p, 'infrastructure.data_residency')}: "
            f"{tech['name']} has a region in {res}.")
    return None


# ------------------------------------------------------------------ 16 data_fit
def _data(tech, p, ctx):
    if ctx.layer != "database" or tech.get("kind") == "none":
        return None
    v, why, fields = 0.0, [], []
    shape_in = val(p, "requirements.data_shape", "auto")
    shape_label = f"requirements.data_shape={shape_in}" + (f" (resolved to {p.data_shape})" if shape_in == "auto" else "")
    if tech.get("kind") in SHAPE_KINDS.get(p.data_shape, ()):
        v += W["data_shape_match"]
        why.append(f"{shape_label} matches {tech['name']} ({tech['kind']})")
        fields.append("requirements.data_shape")
        if shape_in == "auto":
            fields.append("project.type")
    if p.consistency == "strong" and not _has(tech, "acid"):
        v += W["data_non_acid_strong"]
        cin = val(p, "requirements.consistency", "auto")
        lab = f"requirements.consistency={cin}" + (" (resolved to strong)" if cin == "auto" else "")
        why.append(f"{lab} but {tech['name']} has no ACID transactions")
        fields.append("requirements.consistency")
        if cin == "auto":
            if val(p, "requirements.payments"):
                fields.append("requirements.payments")
            fields.append("project.type")
    if val(p, "requirements.multi_tenant") and _has(tech, "rls_multi_tenant"):
        v += W["data_rls"]
        why.append(f"requirements.multi_tenant=true and {tech['name']} has row-level security for tenant isolation")
        fields.append("requirements.multi_tenant")
    if not v:
        return None
    seen, out = set(), []
    for f in fields:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return v, tuple(out), "; ".join(why) + "."


# ------------------------------------------------------------------ 17 gdpr_pref
def _gdpr(tech, p, ctx):
    if not p.gdpr_eu_preference:
        return None
    if (tech.get("regions") or {}).get("eu") and (tech.get("data_at_rest") or tech.get("region_selectable")):
        return W["gdpr_eu_region"], ("compliance",), (
            f"compliance includes gdpr with infrastructure.data_residency=none: {tech['name']} can keep data in an EU region.")
    return None


# ------------------------------------------------------------------ 18 growth_fit
def _growth(tech, p, ctx):
    if ctx.layer not in CODE_LAYERS or not tech.get("languages"):
        return None
    size = val(p, "team.size", 1) or 1
    growth = val(p, "team.growth_12_months")
    if growth is None or growth < W["growth_ratio"] * size or growth < W["growth_min"]:
        return None
    m = _attr(tech, "maintainability")
    v = W["growth_maint_factor"] * (m - 3)
    typed = sorted(set(tech.get("languages") or []) & set(TYPED_LANGUAGES))
    why = f"{tech['name']} maintainability {_num(m)}/5"
    if typed:
        v += W["growth_typed"]
        why += f" and typed {typed[0]}"
    if not v:
        return None
    return v, ("team.growth_12_months", "team.size"), (
        f"team.growth_12_months={fmt(growth)} from team.size={fmt(size)}: a growing team needs structure; {why}.")


# ------------------------------------------------------------------ 19 device_fit
def _device(tech, p, ctx):
    if ctx.layer not in ("frontend_mobile", "frontend_desktop"):
        return None
    sig = [s for s in (getattr(p, "signals", ()) or ()) if s.id == "low_end_devices"]
    if not sig:
        return None
    k, d = tech.get("kind"), W["device"]
    langs = tech.get("languages") or []
    if k == "native":
        v, why = d["native"], "native code has the smallest memory footprint"
    elif k == "cross_platform":
        if any(x in langs for x in ("javascript", "typescript")):
            v, why = d["cross_js"], "the JavaScript runtime adds memory overhead"
        elif _has(tech, "low_end_devices") or any(x in langs for x in ("dart", "kotlin")):
            v, why = d["cross_compiled"], "compiled ahead of time with a modest footprint"
        else:
            v, why = d["cross_js"], "the cross-platform runtime adds memory overhead"
    elif k in ("hybrid_webview", "pwa"):
        v, why = d["webview"], "a WebView is slow and memory-hungry on low-end phones"
    elif k == "webview_shell":
        v = d["webview"] if _has(tech, "small_footprint") else d["desktop_shell"]
        why = "it bundles a browser engine"
    else:
        return None
    return v, ("project.description",), (
        f"project.description mentions '{sig[0].matched_text}' (low-end devices): {tech['name']} - {why}.")


# ------------------------------------------------------------------ 20 security_fit
def _security(tech, p, ctx):
    sec_w = p.weight("security")
    regimes = [c for c in p.compliance if c in W["security_regimes"]]
    v, why, fields = 0.0, [], []
    if sec_w >= W["security_priority_min"] or regimes:
        s = _attr(tech, "security")
        v += W["security_factor"] * (s - 3)
        lab = []
        if sec_w >= W["security_priority_min"]:
            lab.append(f"priorities.security={sec_w}")
            fields.append("priorities.security")
        if regimes:
            lab.append(f"compliance includes {', '.join(regimes)}")
            fields.append("compliance")
        why.append(f"{' and '.join(lab)}: {tech['name']} security {_num(s)}/5")
    ptype = val(p, "project.type")
    if tech.get("kind") == "baas" and ptype in W["security_baas_types"]:
        v += W["security_baas_client"]
        why.append(f"project.type={ptype}: {tech['name']} lets clients query data directly, so access rules are the only guard")
        fields.append("project.type")
    if not round(v, 2):
        return None
    return v, tuple(fields), "; ".join(why) + "."


# ------------------------------------------------------------------ 21 overengineering (plan 3.12, 6.2)
def k8s_allowed(p) -> bool:
    """Kubernetes threshold (plan 5.4 C8 / 6.2): ops capacity and size, or on-prem with a real team."""
    if p.ops_capacity < K8S_MIN_OPS:
        return False
    if _size_ge(p.size, K8S_MIN_SIZE):
        return True
    return bool(p.self_hosted_only) and (val(p, "team.size", 0) or 0) >= K8S_ONPREM_MIN_TEAM


def distributed_sql_allowed(p) -> bool:
    if _size_ge(p.size, DISTRIBUTED_SQL_MIN_SIZE):
        return True
    return val(p, "scale.geographic_spread") == "global" and p.consistency == "strong"


def _overengineering(tech, p, ctx):
    if ctx.layer == "hosting" and _is_k8s(tech) and not k8s_allowed(p):
        return W["overengineering"], ("team.has_devops", "team.experience", "team.size") + _size_fields(p), (
            f"{tech['name']} is Kubernetes, which needs operations capacity >= {K8S_MIN_OPS} (team has "
            f"{p.ops_capacity}: team.experience={val(p, 'team.experience')}, team.has_devops="
            f"{fmt(val(p, 'team.has_devops'))}, team.size={fmt(val(p, 'team.size'))}) and size >= {K8S_MIN_SIZE} "
            f"({_size_text(p)}).")
    if ctx.layer == "database" and _has(tech, "distributed_sql") and not distributed_sql_allowed(p):
        return W["overengineering"], _size_fields(p) + ("scale.geographic_spread",), (
            f"{tech['name']} is distributed SQL, justified only at size >= {DISTRIBUTED_SQL_MIN_SIZE} or a global "
            f"audience with strong consistency ({_size_text(p)}, scale.geographic_spread="
            f"{val(p, 'scale.geographic_spread')}).")
    return None


# ------------------------------------------------------------------ assembly
_TERMS: tuple[tuple[str, Callable], ...] = (
    ("priorities", _priorities), ("skill_fit", _skill), ("ops_fit", _ops), ("scale_fit", _scale),
    ("budget_fit", _budget), ("requirement_fit", _requirements), ("type_affinity", _type),
    ("reuse", _reuse), ("lock_in", _lock_in), ("availability_fit", _availability),
    ("latency_fit", _latency), ("timeline_fit", _timeline), ("traffic_fit", _traffic),
    ("workload_fit", _workload), ("geo_fit", _geo), ("data_fit", _data), ("gdpr_pref", _gdpr),
    ("growth_fit", _growth), ("device_fit", _device), ("security_fit", _security),
    ("overengineering", _overengineering),
)


def context(layer: str, *, platform: str | None = None, supporting_layers: int = 1,
            budget_share: float | None = None) -> LayerContext:
    return LayerContext(layer=layer, platform=platform, supporting_layers=supporting_layers,
                        budget_share=budget_share)


def score(tech: dict, p, ctx: LayerContext) -> Scored:
    """Score one candidate: sum of the 21 contributions of plan 5.3 (+3.12 penalty)."""
    out: list[Contribution] = []
    for key, fn in _TERMS:
        res = fn(tech, p, ctx)
        if res is None:
            continue
        parts: tuple = ()
        if len(res) == 4:
            value, fields, reason, parts = res
        else:
            value, fields, reason = res
        value = round(float(value), 2)
        if value == 0:
            continue
        out.append(Contribution(key, value, tuple(fields), reason, tuple(parts)))
    total = sum(c.value for c in out)
    return Scored(tech, total, tuple(out))


def rank(layer: str, candidates: Iterable[dict], p, ctx: LayerContext | None = None) -> list[Scored]:
    """Score and sort candidates by ``(-round(total, 4), id)``."""
    ctx = ctx or LayerContext(layer=layer)
    if ctx.layer != layer:
        ctx = LayerContext(layer=layer, platform=ctx.platform, supporting_layers=ctx.supporting_layers,
                           budget_share=ctx.budget_share)
    scored = [score(t, p, ctx) for t in candidates]
    return sorted(scored, key=lambda s: (-round(s.total, 4), s.tech["id"]))

"""Architecture style (plan sections 3.12 and 6.2).

``decide(p, stack, supporting=(), status="ok")`` returns an :class:`ArchitectureDecision`: the style id
(one of ``output.ARCH_STYLES``), the id of the rule that matched (``R1`` ... ``R8``, first match wins),
a plain-language reason that quotes the input values, the input field paths that drove it
(``driven_by``) and the outcome of every rule checked before the match (``checks``), so a reader can
see why a heavier style was *not* chosen.

It runs after the stack is chosen, so it describes what was actually picked. The size/team thresholds
are the constants of :mod:`stacksense.scoring` (imported, never duplicated); scoring enforces the same
thresholds as penalties, so the style and the stack cannot disagree.

``stack`` is a mapping with any of these keys (missing key = not chosen):

* ``frontend``: KB record, :class:`~stacksense.scoring.Scored`, or a list of them (one per platform)
* ``backend``, ``database``, ``hosting`` (the host that runs the backend), ``frontend_hosting``
  (separate host for the web frontend, if any): KB record or ``Scored``
* ``database_offering``: offering dict (``kb.offerings``); ``kind == "existing_onprem"`` marks an
  existing on-premise database kept as the primary store (rule 4)

``supporting`` is an iterable of supporting-service records (or ``Scored``). A supporting component
counts as an independently scaled runtime service for rule 6 when its ``caps`` contain
``separate_service`` or its ``kind`` is in :data:`SEPARATE_SERVICE_KINDS` and its layer is in
:data:`RUNTIME_SERVICE_LAYERS`.

Pure and deterministic: no clock, no randomness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .kb.model import size_index
from .scoring import (
    DYNAMIC_FIELDS, MICRO_MIN_SIZE, MICRO_MIN_TEAM, SOA_MIN_TEAM, K8S_MIN_OPS, K8S_MIN_SIZE,
    Contribution, Scored, _size_fields, _size_text, fmt, val,
)

# ------------------------------------------------------------------ rule constants (plan 6.2)
SOA_MIN_SIZE = K8S_MIN_SIZE              # rule 6: size >= m (same threshold as Kubernetes)
SOA_MIN_OPS = K8S_MIN_OPS                # rules 5 and 6: ops capacity >= 4
MICRO_MIN_SCALABILITY = 4                # rule 5: priorities.scalability >= 4
SOA_RUNTIME_MIN_COMPONENTS = 3           # rule 6b: API + realtime gateway + ML service
SOA_RUNTIME_MIN_TEAM = 6
MODULAR_MIN_TEAM = 4                     # rule 7
MODULAR_MIN_SIZE = "m"
MODULAR_TYPES = ("ecommerce", "fintech", "healthtech", "marketplace", "saas_b2b")

INVALID_STATUSES = ("invalid_input", "infeasible")
SELF_MANAGED_HOST_KINDS = ("container", "hybrid_appliance", "k8s", "onprem", "vm")
RUNTIME_SERVICE_LAYERS = ("ml", "realtime", "search", "queue")
SEPARATE_SERVICE_KINDS = ("endpoint", "gateway", "server")
SEPARATE_SERVICE_CAP = "separate_service"
# supporting layers whose SaaS (non-self-hostable) choice makes an on-prem core 'hybrid'
CLOUD_RUNTIME_LAYERS = ("auth", "cache", "cdn", "ml", "queue", "realtime", "search", "storage")
OPS_FIELDS = ("team.experience", "team.has_devops", "team.size")

RULES = {
    "R1": "status is invalid_input or infeasible",
    "R2": "no server backend",
    "R3": "managed functions or a managed BaaS carry the custom logic",
    "R4": "on-premise core combined with cloud components, a hybrid appliance, or an on-premise "
          "system of record behind a cloud app",
    "R5": f"team.size >= {MICRO_MIN_TEAM}, size >= {MICRO_MIN_SIZE}, ops capacity >= {SOA_MIN_OPS} "
          f"and priorities.scalability >= {MICRO_MIN_SCALABILITY}",
    "R6": f"team.size >= {SOA_MIN_TEAM}, size >= {SOA_MIN_SIZE} and ops capacity >= {SOA_MIN_OPS}; or "
          f">= {SOA_RUNTIME_MIN_COMPONENTS} independently scaled runtime services with team.size >= "
          f"{SOA_RUNTIME_MIN_TEAM}",
    "R7": f"team.size >= {MODULAR_MIN_TEAM}, size >= {MODULAR_MIN_SIZE}, multi_tenant, or project.type "
          f"in {list(MODULAR_TYPES)}",
    "R8": "otherwise",
}
STYLE_PHRASE = {
    "other": "No architecture style", "static": "Static site", "serverless": "Serverless",
    "hybrid": "Hybrid (on-premise and cloud)", "microservices": "Microservices",
    "service_oriented": "Service-oriented", "modular_monolith": "Modular monolith", "monolith": "Monolith",
}


@dataclass(frozen=True)
class ArchitectureDecision:
    style: str
    rule: str                                  # R1 ... R8 (plan 6.2 row number)
    reason: str                                # plain language, quotes input values
    driven_by: tuple[str, ...]                 # input field paths
    checks: tuple[tuple[str, bool, str], ...] = field(default=())   # (rule, matched, why) in order

    @property
    def phrase(self) -> str:
        return STYLE_PHRASE.get(self.style, self.style)

    def as_contribution(self) -> Contribution:
        """The decision as a zero-valued Contribution (plan 3.12 ``reasons`` format)."""
        return Contribution("architecture_style", 0.0, self.driven_by, self.reason)

    def as_dict(self) -> dict:
        return {"style": self.style, "rule": self.rule, "reason": self.reason,
                "driven_by": list(self.driven_by),
                "checks": [{"rule": r, "matched": m, "why": w} for r, m, w in self.checks]}


# ------------------------------------------------------------------ helpers
def _rec(x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, Scored):
        return x.tech
    if isinstance(x, Mapping):
        return dict(x) if not isinstance(x, dict) else x
    tech = getattr(x, "tech", None)
    return tech if isinstance(tech, dict) else None


def _many(x) -> list[dict]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [r for r in (_rec(i) for i in x) if r is not None]
    r = _rec(x)
    return [r] if r is not None else []


def _kind(r: dict | None) -> str | None:
    return None if r is None else r.get("kind")


def _caps(r: dict | None) -> list:
    return (r or {}).get("caps") or []


def _uniq(fields: Iterable[str]) -> tuple[str, ...]:
    seen, out = set(), []
    for f in fields:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return tuple(out)


def _driver_fields(x, limit: int = 2) -> tuple[str, ...]:
    """Fields of the top positive scoring contributions of a chosen component (if scored)."""
    if not isinstance(x, Scored):
        return ()
    pos = sorted((c for c in x.contributions if c.value > 0), key=lambda c: (-c.value, c.key))
    out: list[str] = []
    for c in pos[:limit]:
        out.extend(c.fields)
    return _uniq(out)


def _ge(a: str, b: str) -> bool:
    return size_index(a) >= size_index(b)


def _team(p) -> int:
    t = val(p, "team.size", 0)
    return int(t) if isinstance(t, (int, float)) else 0


def _ops_text(p) -> str:
    return (f"operations capacity {p.ops_capacity}/5 (team.experience={val(p, 'team.experience')}, "
            f"team.has_devops={fmt(val(p, 'team.has_devops'))}, team.size={fmt(val(p, 'team.size'))})")


def _is_cloud_runtime(r: dict) -> bool:
    return bool(r.get("saas")) and not r.get("self_hostable")


def _separate_services(supporting: list[dict]) -> list[dict]:
    return [r for r in supporting
            if r.get("layer") in RUNTIME_SERVICE_LAYERS
            and (SEPARATE_SERVICE_CAP in _caps(r) or r.get("kind") in SEPARATE_SERVICE_KINDS)]


# ------------------------------------------------------------------ decide
def decide(p, stack: Mapping[str, Any] | None = None, supporting: Iterable = (), *,
           status: str = "ok") -> ArchitectureDecision:
    """Apply the plan 6.2 rules in order; the first match wins."""
    checks: list[tuple[str, bool, str]] = []

    def done(style, rule, reason, fields):
        checks.append((rule, True, reason))
        return ArchitectureDecision(style, rule, reason, _uniq(fields), tuple(checks))

    def miss(rule, why):
        checks.append((rule, False, why))

    # R1 -------------------------------------------------------------
    if p is None or status in INVALID_STATUSES or getattr(p, "infeasible", False):
        return done("other", "R1", f"No stack was recommended (status {status if p is not None else 'invalid_input'}), "
                    "so there is no architecture to describe.", ())
    miss("R1", f"status is {status}.")

    stack = stack or {}
    raw_backend = stack.get("backend")
    backend = _rec(raw_backend)
    host = _rec(stack.get("hosting"))
    fe_host = _rec(stack.get("frontend_hosting"))
    offering = _rec(stack.get("database_offering"))
    sup_raw = list(supporting or ())
    sup = _many(sup_raw)
    team = _team(p)
    size_fields = _size_fields(p)
    size_text = _size_text(p)

    # R2 -------------------------------------------------------------
    if backend is None or _kind(backend) == "none":
        if not p.needs_backend:
            why = ("No dynamic feature is requested (" + ", ".join(
                f"{f}={fmt(val(p, f))}" for f in DYNAMIC_FIELDS) + "), so the site is pre-rendered pages "
                   "served from a static host with no server or database to run.")
        else:
            why = "No server backend was chosen, so the product is served as static files."
        return done("static", "R2", why, DYNAMIC_FIELDS + ("project.platforms",))
    miss("R2", f"a backend is used ({backend.get('name')}).")

    # R3 -------------------------------------------------------------
    bkind = _kind(backend)
    hkind = _kind(host)
    managed_baas = bkind == "baas" and bool(backend.get("saas")) and hkind not in SELF_MANAGED_HOST_KINDS
    if bkind == "serverless_fn" or managed_baas or hkind == "serverless_fn":
        if bkind == "serverless_fn":
            what = f"{backend['name']} runs the custom logic as managed functions"
        elif managed_baas:
            what = (f"{backend['name']} is a managed backend-as-a-service; custom logic runs in its "
                    "edge/cloud functions")
        else:
            what = f"{backend['name']} is deployed as functions on {host['name']}"
        fields = _driver_fields(raw_backend) or ("team.size", "team.experience", "team.has_devops",
                                                  "timeline.mvp_weeks")
        reason = (f"{what}, so there are no servers to manage; the team scales by usage instead of "
                  f"by instances ({_ops_text(p)}).")
        return done("serverless", "R3", reason, fields)
    miss("R3", f"{backend['name']} runs as a server process"
               + (f" on {host['name']}" if host else "") + ".")

    # R4 -------------------------------------------------------------
    hybrid_why, hybrid_fields = None, ()
    if hkind == "hybrid_appliance":
        hybrid_why = (f"{host['name']} runs cloud services on premises (infrastructure.deployment_model="
                      f"{p.deployment}, infrastructure.cloud_preference={p.cloud_preference}).")
        hybrid_fields = ("infrastructure.deployment_model", "infrastructure.cloud_preference")
    elif p.self_hosted_only:
        cloud_parts = [r for r in ([fe_host] if fe_host else []) if _is_cloud_runtime(r)]
        if offering and offering.get("kind") == "managed":
            cloud_parts.append(offering)
        cloud_parts += [r for r in sup if r.get("layer") in CLOUD_RUNTIME_LAYERS and _is_cloud_runtime(r)]
        if cloud_parts:
            names = ", ".join(sorted({r["name"] for r in cloud_parts}))
            hybrid_why = (f"The core runs on premises (infrastructure.deployment_model={p.deployment}) while "
                          f"{names} run in the cloud.")
            hybrid_fields = ("infrastructure.deployment_model",)
    elif offering and offering.get("kind") == "existing_onprem":
        hybrid_why = (f"The existing on-premise database ({offering.get('name')}) stays the primary store "
                      f"while the application runs in the cloud ({host['name'] if host else 'managed cloud'}).")
        hybrid_fields = ("infrastructure.existing_systems", "infrastructure.deployment_model")
    if hybrid_why:
        return done("hybrid", "R4", hybrid_why, hybrid_fields)
    miss("R4", "all runtime components run in one environment "
               f"(infrastructure.deployment_model={p.deployment}).")

    # R5 -------------------------------------------------------------
    scal = p.weight("scalability")
    micro_ok = (team >= MICRO_MIN_TEAM and _ge(p.size, MICRO_MIN_SIZE) and p.ops_capacity >= SOA_MIN_OPS
                and scal >= MICRO_MIN_SCALABILITY)
    micro_fields = ("team.size",) + size_fields + OPS_FIELDS + ("priorities.scalability",)
    if micro_ok:
        return done("microservices", "R5",
                    f"team.size={team} (>= {MICRO_MIN_TEAM}) can own separate services, {size_text} is at "
                    f"least {MICRO_MIN_SIZE}, {_ops_text(p)} can run them, and priorities.scalability={scal} "
                    "asks for parts that scale and deploy independently.", micro_fields)
    unmet = []
    if team < MICRO_MIN_TEAM:
        unmet.append(f"team.size={team} < {MICRO_MIN_TEAM}")
    if not _ge(p.size, MICRO_MIN_SIZE):
        unmet.append(f"size class {p.size} < {MICRO_MIN_SIZE}")
    if p.ops_capacity < SOA_MIN_OPS:
        unmet.append(f"operations capacity {p.ops_capacity} < {SOA_MIN_OPS}")
    if scal < MICRO_MIN_SCALABILITY:
        unmet.append(f"priorities.scalability={scal} < {MICRO_MIN_SCALABILITY}")
    miss("R5", "microservices need " + RULES["R5"] + "; here " + ", ".join(unmet) + ".")

    # R6 -------------------------------------------------------------
    soa_a = team >= SOA_MIN_TEAM and _ge(p.size, SOA_MIN_SIZE) and p.ops_capacity >= SOA_MIN_OPS
    if soa_a:
        return done("service_oriented", "R6",
                    f"team.size={team} (>= {SOA_MIN_TEAM}) at {size_text} with {_ops_text(p)} can split the "
                    "product into a few coarse services owned by separate sub-teams, without the overhead "
                    "of fine-grained microservices.", ("team.size",) + size_fields + OPS_FIELDS)
    services = _separate_services(sup)
    runtime_count = 1 + len(services)
    if runtime_count >= SOA_RUNTIME_MIN_COMPONENTS and team >= SOA_RUNTIME_MIN_TEAM:
        names = ", ".join([backend["name"]] + sorted(r["name"] for r in services))
        req_fields = []
        layers = {r.get("layer") for r in services}
        if "realtime" in layers:
            req_fields.append("requirements.realtime")
        if "ml" in layers:
            req_fields.append("requirements.ml_features")
        if "search" in layers:
            req_fields.append("requirements.full_text_search")
        return done("service_oriented", "R6",
                    f"{runtime_count} runtime parts scale independently ({names}) and team.size={team} "
                    f"(>= {SOA_RUNTIME_MIN_TEAM}) can own them separately.",
                    ("team.size",) + tuple(sorted(req_fields)))
    miss("R6", f"services need team.size >= {SOA_MIN_TEAM} at size >= {SOA_MIN_SIZE} with operations "
               f"capacity >= {SOA_MIN_OPS}, or >= {SOA_RUNTIME_MIN_COMPONENTS} independently scaled runtime "
               f"parts with team.size >= {SOA_RUNTIME_MIN_TEAM}; here team.size={team}, size class {p.size}, "
               f"operations capacity {p.ops_capacity}, {runtime_count} runtime part(s).")

    # R7 -------------------------------------------------------------
    ptype = val(p, "project.type")
    multi = bool(val(p, "requirements.multi_tenant", False))
    why7, f7 = [], []
    if team >= MODULAR_MIN_TEAM:
        why7.append(f"team.size={team} (>= {MODULAR_MIN_TEAM}) needs clear module boundaries to work in parallel")
        f7.append("team.size")
    if _ge(p.size, MODULAR_MIN_SIZE):
        why7.append(f"{size_text} is large enough that modules should be separable later")
        f7.extend(size_fields)
    if multi:
        why7.append("requirements.multi_tenant=true needs tenant isolation enforced in one place")
        f7.append("requirements.multi_tenant")
    if ptype in MODULAR_TYPES:
        why7.append(f"project.type={ptype} has distinct domains (for example payments and accounts) worth "
                    "keeping apart")
        f7.append("project.type")
    tail = (f". Separate services are not justified yet: they need team.size >= {SOA_MIN_TEAM} at size >= "
            f"{SOA_MIN_SIZE} with operations capacity >= {SOA_MIN_OPS} (here team.size={team}, size class "
            f"{p.size}, operations capacity {p.ops_capacity}).")
    if why7:
        return done("modular_monolith", "R7",
                    "One deployable organised as modules: " + "; ".join(why7) + tail, f7)
    miss("R7", f"team.size={team} < {MODULAR_MIN_TEAM}, size class {p.size} < {MODULAR_MIN_SIZE}, "
               f"requirements.multi_tenant={fmt(multi)}, project.type={ptype}.")

    # R8 -------------------------------------------------------------
    return done("monolith", "R8",
                f"One deployable is simplest for team.size={team} at {size_text} "
                f"(project.type={ptype}, requirements.multi_tenant={fmt(multi)}): one codebase, one "
                "deploy, one database, nothing to coordinate between services.",
                ("team.size",) + size_fields + ("project.type", "requirements.multi_tenant"))

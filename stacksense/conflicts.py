"""Conflict and warning rules (plan sections 3.6 and 6.3).

Two entry points:

* :func:`detect` ``(p, v=None) -> list[Conflict]`` runs on the derived profile *before* selection
  (input-only rules: contradictions between fields, notes that depend only on inputs).
* :func:`post_checks` ``(p, combo, supporting, cost, ranked=None) -> list[Conflict]`` runs after the
  stack is chosen (rules that need the chosen components, their regions or the cost band).

Each :class:`Conflict` carries a warning (``code, severity, message, fields``) and an ``effect``:

* ``none``                     - the warning only;
* ``imply:<field>=<value>``    - the input implies a value for another field; the engine sets it and
  re-derives the profile once (:func:`profile_changes`, :func:`apply_changes`);
* ``relax:<field>[=<value>]``  - a soft requirement cannot be met as given; it is recorded in
  ``relaxed_constraints`` and as a ``RELAXED: ...`` assumption, and when a value is given the
  profile is re-derived with it (for example the 99.95% design instead of 99.99%);
* ``infeasible``               - two hard constraints contradict each other; the result is
  ``infeasible`` with ``nearest_feasible``.

:data:`CATALOGUE` is the single table of every warning code the engine can emit (also codes emitted
by other modules: ``validate``, ``io``, ``profile``, ``supporting``, ``cost``, ``engine``), with
severity, fields, message template, effect and the emitting module. Messages are built only from
these templates, filled with input values and derived numbers; nothing is written per scenario.

Pure and deterministic: no clock, no randomness, sets are always sorted.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from . import kb
from .kb import costs as _costs
from .kb import languages as _languages
from .kb import regions as _regions
from .scoring import Scored, fmt, val

C, W, I = "critical", "warning", "info"
RELAXED_PREFIX = "RELAXED:"
HYPERSCALERS = ("aws", "gcp", "azure")
CLOUD_NAMES = {"aws": "AWS", "gcp": "Google Cloud", "azure": "Azure"}
SIZE_ORDER = ("xs", "s", "m", "l", "xl")
AVAILABILITY_ORDER = ("99", "99.9", "99.95", "99.99")


# ================================================================== catalogue
@dataclass(frozen=True)
class Entry:
    severity: tuple[str, ...]        # allowed severities (first is the usual one)
    fields: tuple[str, ...]
    template: str
    effect: str = "none"             # none | imply | relax:<field> | infeasible
    source: str = "conflicts"        # module that emits the code


def _e(sev, fields, template, effect="none", source="conflicts") -> Entry:
    sev = (sev,) if isinstance(sev, str) else tuple(sev)
    return Entry(sev, tuple(fields), template, effect, source)


BUDGET = "budget.monthly_infra_usd"
CATALOGUE: dict[str, Entry] = {
    # ---- budget and cost (cost.py emits the band verdicts; conflicts adds the relax effects)
    "BUDGET_EXCEEDED": _e(C, [BUDGET], "Estimated USD {min}-{max}/month exceeds the budget of USD {budget}.",
                          f"relax:{BUDGET}", "cost"),
    "BUDGET_TIGHT": _e(W, [BUDGET, "scale.users_12_months"],
                       "Budget USD {budget} covers the low end of the estimate (USD {min}-{max}); growth to "
                       "12-month scale may exceed it.", source="cost"),
    "BUDGET_HEADROOM": _e(I, [BUDGET], "Budget allows more than this workload needs; simplicity was preferred "
                                       "over spend.", source="cost"),
    "FREE_TIER_LIMITS": _e(I, [BUDGET], "{name} free tier: {limit}. {commercial_note}", source="cost"),
    "ZERO_BUDGET_SCALE": _e(C, [BUDGET, "scale.users_12_months"],
                            "USD 0/month cannot serve {users} users with {features}: the cheapest stack that meets "
                            "the hard constraints is estimated at USD {min}-{max}/month once free tiers run out. "
                            "The budget is treated as a target, not a limit.", f"relax:{BUDGET}"),
    "HIPAA_BUDGET": _e(C, ["compliance", BUDGET],
                       "No BAA-covered stack found fits USD {budget}/month (estimate USD {min}-{max}); free and "
                       "hobby tiers do not include a BAA.", f"relax:{BUDGET}"),
    "AVAILABILITY_VS_BUDGET": _e(W, ["requirements.availability", BUDGET],
                                 "Multi-AZ redundancy for {availability}% adds about {pct}% to compute and database "
                                 "cost, and the estimate (USD {min}-{max}) already strains the USD {budget} budget."),
    # ---- timeline and team
    "TIMELINE_TIGHT": _e(W, ["timeline.mvp_weeks", "team.size", "project.platforms"],
                         "{weeks} week(s) for {n} client(s) and a backend with {size} engineer(s) is aggressive "
                         "({wpce} engineer-weeks per deliverable); scope the MVP."),
    "TIMELINE_PLATFORMS": _e(C, ["timeline.mvp_weeks", "project.platforms", "team.size"],
                             "{n} platforms in {weeks} week(s) with {size} engineer(s): recommending one "
                             "cross-platform codebase and a phased platform rollout.",
                             "relax:project.platforms"),
    "MANY_PLATFORMS_SMALL_TEAM": _e(W, ["project.platforms", "team.size"],
                                    "{n} client platforms ({platforms}) for {size} engineer(s); a shared codebase "
                                    "is assumed."),
    "BEGINNER_COMPLEXITY": _e(W, ["team.experience"],
                              "A beginner team is taking on {features}; managed services were preferred to reduce "
                              "risk."),
    "SOLO_BUS_FACTOR": _e(I, ["team.size"], "One engineer for a size-{size} product: fully managed services are "
                                            "preferred to limit on-call load."),
    "SKILL_MISMATCH": _e(W, ["team.languages"],
                         "{name} uses {lang}, which is not in team.languages ({langs}); chosen because {reason}. "
                         "Budget {weeks} week(s) of ramp-up."),
    "SKILL_GAP_NO_LEARNING": _e(C, ["team.languages", "team.willing_to_learn"],
                                "No {layer} option that passes the hard constraints matches team.languages "
                                "({langs}) and team.willing_to_learn=false; {name} is the closest.",
                                "relax:team.willing_to_learn"),
    # ---- availability and latency
    "AVAILABILITY_VS_TEAM": _e(C, ["requirements.availability", "team.experience", "team.has_devops", "team.size"],
                               "99.99% (4.3 minutes/month) needs multi-AZ failover and on-call maturity; the team "
                               "profile ({experience}, has_devops={has_devops}, size {size}, operations capacity "
                               "{ops}/5) cannot operate it. Recommending the 99.95% design.",
                               "relax:requirements.availability"),
    "AVAILABILITY_SINGLE_NODE": _e(W, ["requirements.availability"],
                                   "{name} is a single node; {availability}% is not guaranteed without a standby."),
    "LATENCY_AGGRESSIVE": _e(W, ["requirements.p95_latency_ms", "scale.geographic_spread"],
                             "p95 <= {p95} ms for {spread} users needs {need}."),
    "LATENCY_UNREALISTIC": _e(C, ["requirements.p95_latency_ms"],
                              "A p95 of {p95} ms end to end is not achievable for {reason}; it is treated as a "
                              "best-effort target.", "relax:requirements.p95_latency_ms"),
    # ---- platforms and requirements
    "SEO_WITHOUT_WEB": _e(W, ["requirements.seo_critical", "project.platforms"],
                          "seo_critical=true but no web platform is listed ({platforms}); search engines index web "
                          "pages only. Ignored for the stack."),
    "OFFLINE_API_ONLY": _e(W, ["requirements.offline_support", "project.platforms"],
                           "offline_support applies to clients; an API-only product cannot work offline. Ignored."),
    "API_ONLY_WITH_CLIENTS": _e(I, ["project.platforms"],
                                "api_only listed with {others}: treating the API as a first-party public surface in "
                                "addition to the clients.", source="validate"),
    "OFFLINE_WEB_LIMITS": _e(I, ["requirements.offline_support"],
                             "Offline on the web relies on a service worker and IndexedDB; storage can be evicted "
                             "by the browser."),
    "OFFLINE_CONFLICTS": _e(I, ["requirements.offline_support"],
                            "Offline writes need a conflict policy (last-write-wins per field is assumed) and an "
                            "outbox that syncs when the connection returns."),
    # ---- residency and compliance
    "RBI_IMPLIES_INDIA": _e(W, ["compliance", "infrastructure.data_residency"],
                            "rbi_localisation requires payment data to be stored only in India; data_residency "
                            "treated as india.", "imply:infrastructure.data_residency=india"),
    "RESIDENCY_COMPLIANCE_CONFLICT": _e(C, ["compliance", "infrastructure.data_residency"],
                                        "rbi_localisation (India-only payment data) contradicts "
                                        "data_residency={residency}.", "infeasible"),
    "RESIDENCY_UNVERIFIABLE": _e(C, ["infrastructure.data_residency"],
                                 "data_residency=other does not name a country; only self-hostable components were "
                                 "used. Specify the country to check managed regions."),
    "GDPR_TRANSFER": _e(W, ["compliance"],
                        "{name} keeps personal data in {region}, outside the EU; a DPA and Standard Contractual "
                        "Clauses are required."),
    "GDPR_NOTES": _e(I, ["compliance"],
                     "GDPR: {where} chosen for the database; enable data-subject export and erasure and keep a DPA "
                     "with each processor."),
    "DPDP_NOTES": _e(I, ["compliance"],
                     "DPDP Act 2023: consent records, breach notification and a grievance contact are required; "
                     "cross-border transfer is allowed except to notified countries."),
    "PCI_SCOPE": _e(I, ["compliance", "requirements.payments"],
                    "Card data should never touch your servers: using {gateway}'s hosted payment page or tokenisation "
                    "keeps card numbers off your systems and reduces your PCI DSS scope. Storing card numbers "
                    "yourself would bring full PCI DSS scope."),
    "PCI_WITHOUT_PAYMENTS": _e(I, ["compliance", "requirements.payments"],
                               "pci_dss listed but payments=false; controls applied to hosting only."),
    "HIPAA_BAA": _e(W, ["compliance"],
                    "HIPAA: sign a BAA with {vendors}; use only the HIPAA-eligible services listed.{plan_note}"),
    "COMPLIANCE_ORG_SCOPE": _e(I, ["compliance"],
                               "{regime} certifies your organisation, not only the tools; the chosen vendors hold "
                               "{regime} reports you can inherit controls from."),
    "LLM_DATA_RESIDENCY": _e(W, ["requirements.ml_features", "infrastructure.data_residency"],
                             "Prompts contain user data: use {profile} so inference stays in {region}; global "
                             "inference profiles are excluded."),
    "PHONE_OTP_DLT": _e(I, ["requirements.auth"],
                        "SMS OTP in India needs a DLT-registered sender and template (TRAI); allow about a week for "
                        "approval."),
    "STRIPE_INDIA": _e(I, ["requirements.payments", "infrastructure.data_residency"],
                       "Stripe is invite-only for new Indian businesses; {gateway} supports UPI and cards."),
    # ---- cloud and deployment
    "CLOUD_VS_DEPLOYMENT": _e(C, ["infrastructure.cloud_preference", "infrastructure.deployment_model"],
                              "cloud_preference={cloud} cannot be met in an air-gapped deployment: {cloud_name} "
                              "services and its on-premise appliances ({appliance}) need connectivity to "
                              "{cloud_name}.",
                              "infeasible"),
    "CLOUD_ONPREM_APPLIANCE": _e(W, ["infrastructure.cloud_preference", "infrastructure.deployment_model"],
                                 "On-premise with {cloud_name} means a hybrid appliance ({appliance}); minimum commitment "
                                 "is far above typical budgets."),
    "CLOUD_NONE_INTERPRETED": _e(I, ["infrastructure.cloud_preference"],
                                 "cloud_preference=none read as 'avoid AWS/GCP/Azure accounts'; independent providers "
                                 "used.", source="profile"),
    "CLOUD_REGION_GAP": _e(C, ["infrastructure.cloud_preference", "infrastructure.data_residency"],
                           "{cloud} has no {service} in {region}; {fallback} used instead.", source="supporting"),
    "AIRGAP_EXTERNAL_DEPENDENCY": _e(C, ["infrastructure.deployment_model"],
                                     "{requirement} needs an external service, which an air-gapped network cannot "
                                     "reach. It is left out; {workaround}.", "relax:<requirement>", "supporting"),
    "SUPPORTING_GAP": _e((C, W), ["the triggering requirement"],
                         "No {layer} service passes the hard constraints for {requirement}; {workaround}.",
                         source="supporting"),
    "ONPREM_NO_SAAS": _e(I, ["infrastructure.deployment_model"],
                         "deployment_model={deployment}: only self-hostable components were considered; SaaS and "
                         "public CDNs are excluded."),
    "ONPREM_OPS_GAP": _e((C, W), ["infrastructure.deployment_model", "team.has_devops"],
                         "Self-hosting everything needs infrastructure skills the team profile lacks (operations "
                         "capacity {ops}/5, has_devops={has_devops}); the simplest self-hosted layout was chosen."),
    "SELF_HOSTED_VM_OPS": _e(W, ["infrastructure.deployment_model", "team.has_devops"],
                             "You will patch, back up and monitor the VMs yourselves; no one on the team operates "
                             "infrastructure (has_devops=false)."),
    # ---- existing systems
    "EOL_EXISTING_SYSTEM": _e((C, W, I), ["infrastructure.existing_systems"], "{system}: {status_text} ({date}). "
                                                                               "{advice}"),
    "EXISTING_SYSTEM_UNRECOGNISED": _e(I, ["infrastructure.existing_systems"],
                                       "'{raw}' was not recognised; assumed reachable through an API or scheduled "
                                       "export.", source="engine"),
    "EXISTING_SYSTEM_CONFLICT": _e(W, ["infrastructure.existing_systems", "infrastructure.deployment_model"],
                                   "{system} is on-premise while the new stack runs in {where}; a private link or "
                                   "scheduled sync is needed."),
    # ---- scale and shape
    "SCALE_INCONSISTENT": _e(W, ["scale.users_at_launch", "scale.users_12_months",
                                 "scale.peak_concurrent_users"],
                             "{detail}; sizing used the larger figure.", source="validate"),
    "HYPERGROWTH": _e(I, ["scale.users_at_launch", "scale.users_12_months"],
                      "{x}x growth in 12 months: start on the smallest tier of the same stack and scale up; the "
                      "estimate shown is for month 12 ({users} users)."),
    "OVERENGINEERING_AVOIDED": _e(I, ["team.size", "scale.users_12_months", "team.has_devops"],
                                  "{name} was not used although it otherwise ranked in the top {k} for the {layer}: "
                                  "{threshold_text}"),
    "LOCK_IN_RISK": _e((I, W), ["infrastructure.lock_in_tolerance"],
                       "{name} has a proprietary API; moving away means rewriting the {area} code."),
    "MULTI_TENANT_ISOLATION": _e(I, ["requirements.multi_tenant"],
                                 "Tenant isolation by {mechanism}; test it with cross-tenant access tests."),
    "ML_GPU_COST": _e(W, ["requirements.ml_features"],
                      "{what} needs GPU capacity, which is not in this estimate and usually dominates it."),
    # ---- description and input notices
    "DESCRIPTION_MISMATCH": _e(I, ["project.description"],
                               "The description mentions '{text}' but {field}={value}; the explicit field was used.",
                               source="engine"),
    "DESCRIPTION_SIGNAL": _e(I, ["project.description"], "'{text}' in the description -> {effect}.",
                             source="engine"),
    "UNKNOWN_FIELD": _e(I, ["the field"], "Unknown field '{field}' was ignored.", source="validate"),
    "DUPLICATE_KEY": _e(I, ["the field"], "Key '{key}' appears twice; the last value was used.", source="io"),
    "DEFAULTS_APPLIED": _e(W, ["those fields"],
                           "{n} required field(s) were missing and filled with defaults: {paths}."),
    "PROJECT_TYPE_OTHER": _e(I, ["project.type"],
                             "project.type=other: priors were taken from requirements and the description "
                             "({inferred})."),
    "VENDOR_RISK": _e(I, [], "{name}: {risk}."),
    # ---- infeasibility (engine)
    "NO_FEASIBLE_CANDIDATE": _e(C, ["the hard-constraint fields"],
                                "No {layer} passes the hard constraints ({constraints}): {reasons}", source="engine"),
    "NO_COMPATIBLE_STACK": _e(C, ["infrastructure.deployment_model", "infrastructure.cloud_preference"],
                              "No combination of the remaining options works together: {reason}.", source="engine"),
    "INTERNAL_ERROR": _e(C, [], "Internal error ({error}). Please report this input.", source="engine"),
}

# Codes of plan 6.3 that are documented but not emitted (reason in NOT_EMITTED).
NOT_EMITTED: dict[str, str] = {
    "VENDOR_RISK": "the KB has no per-record risk facts yet",
}


# ================================================================== conflict
@dataclass(frozen=True)
class Conflict:
    code: str
    severity: str
    message: str
    fields: tuple[str, ...]
    effect: str = "none"
    assumption: str | None = None      # plain-language note added when the effect is applied

    def warning(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "fields": list(self.fields)}

    @property
    def kind(self) -> str:
        return self.effect.split(":", 1)[0]

    def target(self) -> tuple[str | None, Any]:
        """(field, value) of an imply/relax effect; value is None when nothing is substituted."""
        if ":" not in self.effect:
            return None, None
        body = self.effect.split(":", 1)[1]
        if "=" in body:
            f, v = body.split("=", 1)
            return f, v
        return body, None

    def relaxed(self) -> str | None:
        if self.kind != "relax":
            return None
        f, _ = self.target()
        return f"{RELAXED_PREFIX} {f}: {self.assumption or self.message}"


def conflict(code: str, effect: str | None = None, *, severity: str | None = None, fields=None,
             assumption: str | None = None, **kw) -> Conflict:
    """Build a Conflict from the catalogue entry of ``code`` (template filled with ``kw``)."""
    e = CATALOGUE[code]
    sev = severity or e.severity[0]
    if sev not in e.severity:
        raise ValueError(f"{code}: severity {sev} not in catalogue {e.severity}")
    eff = effect if effect is not None else e.effect
    msg = e.template.format(**kw)
    msg = re.sub(r"\s+", " ", msg).strip()
    return Conflict(code, sev, msg, tuple(fields if fields is not None else e.fields), eff, assumption)


# ================================================================== helpers
def _n(x) -> str:
    if isinstance(x, float):
        if x.is_integer():
            x = int(x)
        else:
            return f"{round(x, 2):,}"
    if isinstance(x, int) and not isinstance(x, bool):
        return f"{x:,}"
    return str(x)


def _join(items: Iterable[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _size_ge(a: str, b: str) -> bool:
    return SIZE_ORDER.index(a) >= SIZE_ORDER.index(b)


def _avail_ge(a, b: str) -> bool:
    return a in AVAILABILITY_ORDER and AVAILABILITY_ORDER.index(a) >= AVAILABILITY_ORDER.index(b)


def _rec(x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, Scored):
        return x.tech
    if isinstance(x, Mapping):
        return dict(x)
    t = getattr(x, "tech", None)
    if isinstance(t, dict):
        return t
    s = getattr(x, "scored", None)
    return s.tech if isinstance(s, Scored) else None


def _is_none(rec) -> bool:
    return not rec or rec.get("kind") == "none"


def _appliances(cloud: str) -> list[dict]:
    return sorted((r for r in kb.by_layer("hosting")
                   if r.get("kind") == "hybrid_appliance" and cloud in (r.get("cloud_affinity") or ())),
                  key=lambda r: r["id"])


def _features(p) -> list[str]:
    out = []
    if val(p, "requirements.realtime"):
        out.append("realtime")
    if val(p, "requirements.multi_tenant"):
        out.append("multi-tenancy")
    if val(p, "requirements.payments"):
        out.append("payments")
    ml = val(p, "requirements.ml_features", "none")
    if ml and ml != "none":
        out.append(f"ml_features={ml}")
    if p.compliance:
        out.append("compliance (" + ", ".join(p.compliance) + ")")
    return out


def _best_affinity(team: Iterable[str], needed: Iterable[str]) -> tuple[float, str | None]:
    best, lang = 0.0, None
    for k in sorted(team):
        for n in sorted(needed):
            a = _languages.affinity(k, n)
            if a > best:
                best, lang = a, n
    return best, lang


def _mismatch(p, tech: dict) -> bool:
    """True when the record names languages and none is close to team.languages (affinity < threshold)."""
    needed = list(tech.get("languages") or ())
    if not needed or not p.languages or tech.get("kind") == "none":
        return False
    if tech.get("kind") == "ssg" and set(p.languages) & {"html", "css"}:
        return False
    best, _ = _best_affinity(p.languages, needed)
    return best < _languages.KNOWN_THRESHOLD


# ================================================================== pre-selection rules
def detect(p, v=None) -> list[Conflict]:
    """Input-only rules of plan 6.3 (run before selection). ``v`` (Validated) adds DEFAULTS_APPLIED."""
    out: list[Conflict] = []
    add = out.append
    residency, eff = p.residency, p.effective_residency
    comp = set(p.compliance)
    clients = list(p.clients)
    platforms = list(val(p, "project.platforms") or [])
    size_team = int(val(p, "team.size", 1) or 1)
    weeks = val(p, "timeline.mvp_weeks")
    exp = val(p, "team.experience")
    devops = bool(val(p, "team.has_devops"))

    # ---- residency and compliance
    if "rbi_localisation" in comp and residency == "none":
        add(conflict("RBI_IMPLIES_INDIA", assumption="infrastructure.data_residency treated as india because "
                     "compliance includes rbi_localisation (payment data must be stored only in India)."))
    if "rbi_localisation" in comp and residency in ("eu", "us"):
        add(conflict("RESIDENCY_COMPLIANCE_CONFLICT", residency=residency))
    if residency == "other":
        add(conflict("RESIDENCY_UNVERIFIABLE"))
    if "dpdp" in comp:
        add(conflict("DPDP_NOTES"))
    if "pci_dss" in comp and not val(p, "requirements.payments"):
        add(conflict("PCI_WITHOUT_PAYMENTS"))
    orgs = [r for r in ("soc2", "iso27001") if r in comp]
    if orgs:
        add(conflict("COMPLIANCE_ORG_SCOPE", regime=_join(orgs)))
    if val(p, "requirements.auth") == "phone_otp" and p.india and not p.air_gapped:
        add(conflict("PHONE_OTP_DLT"))

    # ---- cloud and deployment
    if p.cloud in HYPERSCALERS and p.cloud_explicit:
        apps = _appliances(p.cloud)
        names = _join([a["name"] for a in apps]) or "none in the knowledge base"
        if p.air_gapped and not any(not a.get("needs_internet", True) for a in apps):
            add(conflict("CLOUD_VS_DEPLOYMENT", cloud=p.cloud, cloud_name=CLOUD_NAMES[p.cloud], appliance=names))
        elif p.deployment == "on_premise":
            add(conflict("CLOUD_ONPREM_APPLIANCE", cloud_name=CLOUD_NAMES[p.cloud], appliance=names))
    if p.cloud_preference == "none" and p.deployment in ("managed_cloud", "self_hosted_cloud_vm"):
        add(conflict("CLOUD_NONE_INTERPRETED"))
    if p.self_hosted_only:
        add(conflict("ONPREM_NO_SAAS", deployment=p.deployment))
        if p.ops_capacity < 3:
            add(conflict("ONPREM_OPS_GAP", severity=C if p.ops_capacity < 2 else W, ops=p.ops_capacity,
                         has_devops=fmt(devops)))
    if p.deployment == "self_hosted_cloud_vm" and not devops:
        add(conflict("SELF_HOSTED_VM_OPS"))

    # ---- timeline, platforms, team
    n_cl = len(clients)
    if isinstance(weeks, int) and n_cl >= 2 and ((weeks <= 4 and n_cl >= 3) or weeks * size_team < 6 * n_cl):
        add(conflict("TIMELINE_PLATFORMS", n=n_cl, weeks=weeks, size=size_team,
                     assumption=f"{', '.join(clients)} are not all launched in parallel: one cross-platform "
                                f"codebase ships first and the remaining platforms follow in phases "
                                f"(timeline.mvp_weeks={weeks}, team.size={size_team})."))
    if p.delivery_pressure >= 3 and p.needs_backend:
        add(conflict("TIMELINE_TIGHT", weeks=weeks, n=n_cl, size=size_team,
                     wpce=_n(p.weeks_per_client_per_engineer)))
    if n_cl >= 3 and size_team <= 3:
        add(conflict("MANY_PLATFORMS_SMALL_TEAM", n=n_cl, platforms=", ".join(clients), size=size_team))
    feats = _features(p)
    if exp == "beginner" and feats:
        add(conflict("BEGINNER_COMPLEXITY", features=_join(feats)))
    if size_team == 1 and _size_ge(p.size, "s"):
        add(conflict("SOLO_BUS_FACTOR", size=p.size))

    # ---- availability and latency
    avail = val(p, "requirements.availability")
    if avail == "99.99" and p.ops_capacity < 4:
        add(conflict("AVAILABILITY_VS_TEAM", effect="relax:requirements.availability=99.95",
                     experience=exp, has_devops=fmt(devops), size=size_team, ops=p.ops_capacity,
                     assumption="99.99 -> 99.95: the stack is designed for 99.95% "
                                "(multi-AZ, no multi-region active-active) because operations capacity is "
                                f"{p.ops_capacity}/5 (needs 4)."))
    p95 = val(p, "requirements.p95_latency_ms")
    spread = val(p, "scale.geographic_spread", "single_country")
    ml = val(p, "requirements.ml_features", "none")
    if isinstance(p95, (int, float)) and not isinstance(p95, bool):
        reason = None
        if p95 <= 20 and clients:
            reason = "a client that reaches the server over the public internet (one round trip alone is longer)"
        elif p95 <= 50 and ml == "llm_rag":
            reason = "a request that retrieves documents and calls a language model"
        if reason:
            add(conflict("LATENCY_UNREALISTIC", p95=_n(p95), reason=reason,
                         assumption=f"{_n(p95)} ms is treated as a best-effort target; "
                                    "the stack is the lowest-latency option that meets the hard constraints."))
        elif p95 <= 100 and spread in ("multi_region", "global"):
            add(conflict("LATENCY_AGGRESSIVE", p95=_n(p95), spread=spread,
                         need="regional replicas or edge compute close to each user group"))

    # ---- platforms and requirements
    if val(p, "requirements.seo_critical") and "web" not in platforms:
        add(conflict("SEO_WITHOUT_WEB", platforms=", ".join(platforms)))
    offline = bool(val(p, "requirements.offline_support"))
    if offline and not clients and p.api_only:
        add(conflict("OFFLINE_API_ONLY"))
    if offline and "web" in clients:
        add(conflict("OFFLINE_WEB_LIMITS"))
    writes = (val(p, "scale.workload") != "read_heavy" or val(p, "requirements.file_media_storage")
              or val(p, "requirements.payments"))
    if offline and clients and p.needs_backend and writes:
        add(conflict("OFFLINE_CONFLICTS"))

    # ---- scale
    u12, launch = int(val(p, "scale.users_12_months", 0) or 0), int(val(p, "scale.users_at_launch", 0) or 0)
    if launch > 0 and u12 >= 50 * launch and u12 >= 100_000:
        add(conflict("HYPERGROWTH", x=_n(u12 // launch), users=_n(u12)))

    # ---- ML
    if ml == "training" or (ml == "llm_rag" and p.self_hosted_only):
        what = "Model training" if ml == "training" else "Self-hosted LLM inference"
        add(conflict("ML_GPU_COST", what=what))

    # ---- project type, defaults
    if val(p, "project.type") == "other":
        sig = sorted({s.id for s in (p.signals or ())})
        inferred = ("description signals: " + ", ".join(sig)) if sig else "no description signals"
        add(conflict("PROJECT_TYPE_OTHER", inferred=inferred))
    if v is not None:
        dflt = [a.split()[3] for a in (v.assumptions or ()) if a.startswith("DEFAULTED required field ")]
        if dflt:
            add(conflict("DEFAULTS_APPLIED", fields=tuple(dflt), n=len(dflt), paths=", ".join(dflt)))

    # ---- existing systems (needs existing.py matches; inactive until they carry EOL verdicts)
    out.extend(_existing(p))
    return out


def _is_on_prem(ex, m) -> bool:
    """True when a sibling match for the same input string carries the on_prem qualifier."""
    return any(o.raw == m.raw and o.kind == "on_prem" for o in (getattr(ex, "matches", ()) or ()))


def _existing(p) -> list[Conflict]:
    out = []
    ex = getattr(p, "existing", None)
    for m in (getattr(ex, "matches", ()) or ()):
        ev = getattr(m, "eol", None)
        if isinstance(ev, dict) and ev.get("date"):
            days = ev.get("days")
            state = ev.get("state")
            label = ev.get("label") or m.raw
            rep = ev.get("replacement")
            advice = f"Plan the move to {rep}." if rep else "Plan an upgrade."
            sev = None
            if state == "ended":
                sev, text = C, f"{label} support has ended"
            elif (isinstance(days, int) and days <= 365) or ev.get("mainstream_ended"):
                sev = W
                text = (f"{label} reaches end of support soon" if isinstance(days, int) and days <= 365 else
                        f"{label} mainstream support ended {ev.get('mainstream_end')}; extended support ends")
            elif isinstance(days, int) and days <= 3 * 365:
                sev, text = I, f"{label} reaches end of support within three years"
            if sev:
                out.append(conflict("EOL_EXISTING_SYSTEM", severity=sev, system=m.raw, status_text=text,
                                    date=ev["date"], advice=advice))
        if (getattr(m, "family", "") == "database" and _is_on_prem(ex, m)
                and p.deployment in ("managed_cloud", "self_hosted_cloud_vm")):
            where = p.cloud or "a managed cloud"
            out.append(conflict("EXISTING_SYSTEM_CONFLICT", system=m.raw, where=where))
    return out


# ================================================================== effects
def infeasible(conflicts: Iterable[Conflict]) -> bool:
    return any(c.kind == "infeasible" for c in conflicts)


def profile_changes(conflicts: Iterable[Conflict]) -> dict[str, Any]:
    """Field -> value for every imply effect and every relax effect that names a value (first wins)."""
    out: dict[str, Any] = {}
    for c in conflicts:
        if c.kind in ("imply", "relax"):
            f, v = c.target()
            if f and v is not None and f not in out:
                out[f] = v
    return out


def apply_changes(v, changes: Mapping[str, Any]):
    """Copy of the Validated result with the implied/relaxed values set (input otherwise unchanged)."""
    prof = dict(v.profile)
    prof.update(changes)
    return dataclasses.replace(v, profile=prof)


def relaxed(conflicts: Iterable[Conflict]) -> list[str]:
    """``RELAXED: ...`` lines, one per relaxed field (first conflict per field wins)."""
    seen, out = set(), []
    for c in conflicts:
        if c.kind != "relax":
            continue
        f, _ = c.target()
        if f in seen:
            continue
        seen.add(f)
        out.append(c.relaxed())
    return out


def assumptions(conflicts: Iterable[Conflict]) -> list[str]:
    """Assumption lines for imply effects (relax lines come from :func:`relaxed`)."""
    return [c.assumption for c in conflicts if c.kind == "imply" and c.assumption]


def merge(existing: Iterable[dict], conflicts: Iterable[Conflict]) -> list[dict]:
    """Warnings of ``conflicts`` whose code was not already emitted by another module."""
    have = {w.get("code") for w in existing}
    return [c.warning() for c in conflicts if c.code not in have]


# ================================================================== post-selection rules
def _core(combo) -> dict[str, list[dict]]:
    """Layer -> records of the chosen combination (frontend parts, backend, database, hosts)."""
    out: dict[str, list[dict]] = {"frontend": [], "backend": [], "database": [], "hosting": [], "backend_host": []}
    if combo is None:
        return out
    st = combo.stack() if hasattr(combo, "stack") else dict(combo)
    bh = _rec(st.get("hosting"))
    if bh and not _is_none(bh):
        out["backend_host"].append(bh)
    for r in st.get("frontend") or []:
        rec = _rec(r)
        if rec and not _is_none(rec):
            out["frontend"].append(rec)
    for layer in ("backend", "database", "hosting", "frontend_hosting"):
        rec = _rec(st.get(layer))
        if rec and not _is_none(rec):
            key = "hosting" if layer == "frontend_hosting" else layer
            if rec["id"] not in {x["id"] for x in out[key]}:
                out[key].append(rec)
    return out


def _sel_records(supporting) -> list[tuple[str, dict]]:
    out = []
    for s in (getattr(supporting, "selections", ()) or ()):
        out.append((s.layer, s.tech))
    return out


def _db_region(combo, p) -> tuple[str | None, str | None]:
    """(provider family, region id) of the chosen database offering, when known."""
    off = getattr(combo, "database_offering", None)
    return getattr(off, "family", None), getattr(off, "region", None)


def _in_eu(family: str | None, region: str | None) -> bool | None:
    if not region:
        return None
    if not family:
        return None
    try:
        ids = _regions.regions_for(family, "eu")
    except Exception:  # noqa: BLE001 - unknown provider: cannot tell
        return None
    if not isinstance(ids, list) or not ids or ids[0] == "*":
        return None
    return region in ids


def _hipaa_vendors(records: Iterable[dict]) -> tuple[list[str], list[str]]:
    vendors, plans = [], []
    for r in records:
        a = (r.get("attest") or {}).get("hipaa_baa")
        if a == "yes" and r["name"] not in vendors:
            vendors.append(r["name"])
        elif isinstance(a, str) and a.startswith("plan") and r["name"] not in vendors:
            vendors.append(r["name"])
            plan = a.split(":", 1)[1].replace("_", " ") if ":" in a else "a specific plan"
            plans.append(f"{r['name']} covers HIPAA only with its {plan}")
    return vendors, plans


def post_checks(p, combo, supporting=None, cost=None, ranked: Mapping[str, list] | None = None,
                *, existing_warnings: Iterable[dict] = (), budget_mode: str | None = None) -> list[Conflict]:
    """Rules of plan 6.3 that need the chosen stack (combo), supporting services and the cost band.

    Budget verdict warnings come from cost.py; this adds their relax effects and the budget codes cost.py
    does not emit. ``existing_warnings`` are the warnings already collected (used to avoid repeats)."""
    out: list[Conflict] = []
    add = out.append
    core = _core(combo)
    sel = _sel_records(supporting)
    have = {w.get("code") for w in existing_warnings}
    comp = set(p.compliance)
    budget = val(p, BUDGET)
    budget = float(budget) if isinstance(budget, (int, float)) and not isinstance(budget, bool) else None
    lo, hi = (getattr(cost, "min", None), getattr(cost, "max", None)) if cost is not None else (None, None)
    verdict = getattr(cost, "verdict", None)
    cost_codes = {w.get("code") for w in (getattr(cost, "warnings", ()) or ())} | have

    # ---- budget
    if budget is not None and lo is not None:
        b = fmt(budget)
        kept = ("the cheapest stack that meets the hard constraints is kept"
                if budget_mode == "cheapest" else
                "the stack chosen by the budget fallback is kept, as no cheaper option met the hard constraints"
                if budget_mode == "fallback" else
                "the recommended stack is kept")
        relax_text = (f"USD {b}/month is below the estimate USD {lo:,}-{hi:,}/month; {kept} "
                      "and the budget is treated as a target.")
        if budget == 0 and (_size_ge(p.size, "m") or lo > 0):
            feats = _features(p) or [f"a size-{p.size} workload"]
            add(conflict("ZERO_BUDGET_SCALE", users=_n(p.users), features=_join(feats), min=f"{lo:,}",
                         max=f"{hi:,}", assumption=relax_text))
        if "hipaa" in comp and verdict == "exceeded":
            add(conflict("HIPAA_BUDGET", budget=b, min=f"{lo:,}", max=f"{hi:,}", assumption=relax_text))
        if verdict == "exceeded" and "BUDGET_EXCEEDED" in cost_codes:
            add(conflict("BUDGET_EXCEEDED", min=f"{lo:,}", max=f"{hi:,}", budget=b, assumption=relax_text))
        avail = val(p, "requirements.availability")
        if _avail_ge(avail, "99.95") and verdict == "exceeded":
            mult = tuple(getattr(cost, "availability_multiplier", None) or (1.0, 1.0))
            pct = f"{round((mult[0] - 1) * 100):d}-{round((mult[1] - 1) * 100):d}"
            add(conflict("AVAILABILITY_VS_BUDGET", availability=avail, pct=pct, min=f"{lo:,}", max=f"{hi:,}",
                         budget=b))

    # ---- availability, latency
    avail = val(p, "requirements.availability")
    if _avail_ge(avail, "99.9"):
        for r in core["database"]:
            if r.get("kind") == "embedded" or "embedded" in (r.get("caps") or ()):
                add(conflict("AVAILABILITY_SINGLE_NODE", name=r["name"], availability=avail))
        for r in core["backend_host"]:
            caps = r.get("caps") or ()
            if r.get("kind") in ("vm", "onprem") and "fixed_capacity" in caps and "multi_az" not in caps:
                add(conflict("AVAILABILITY_SINGLE_NODE", name=r["name"], availability=avail))
    p95 = val(p, "requirements.p95_latency_ms")
    if (isinstance(p95, (int, float)) and not isinstance(p95, bool) and p95 <= 100
            and "LATENCY_AGGRESSIVE" not in have and "LATENCY_UNREALISTIC" not in have):
        backend_hosts = [r for r in core["backend_host"] if "cold_start" in (r.get("caps") or ())
                         and "min_instances" not in (r.get("caps") or ())]
        if backend_hosts and p.needs_backend:
            add(conflict("LATENCY_AGGRESSIVE", p95=_n(p95),
                         spread=val(p, "scale.geographic_spread", "single_country"),
                         need=f"warm instances: {backend_hosts[0]['name']} has cold starts"))

    # ---- compliance with the chosen components
    db_family, db_region = _db_region(combo, p)
    if "gdpr" in comp and core["database"]:
        eu = _in_eu(db_family, db_region)
        name = core["database"][0]["name"]
        if eu is False:
            add(conflict("GDPR_TRANSFER", name=name, region=db_region))
        else:
            where = (f"EU region {db_region}" if eu else
                     "an EU region" if p.effective_residency == "eu" else
                     "a self-managed or unspecified region (keep it in the EU)")
            add(conflict("GDPR_NOTES", where=where))
    pay = [r for layer, r in sel if layer == "payments"]
    if pay and ("pci_dss" in comp or val(p, "requirements.payments")):
        add(conflict("PCI_SCOPE", gateway=pay[0]["name"]))
    if val(p, "requirements.payments") and p.india and not p.air_gapped:
        gw = next((r["name"] for r in pay if r["id"] != "stripe"), None)
        add(conflict("STRIPE_INDIA", gateway=gw or "an India-licensed gateway such as Razorpay or Cashfree"))
    if "hipaa" in comp:
        off = getattr(getattr(combo, "database_offering", None), "offering", None)
        recs = ([r for layer in ("backend", "database", "hosting") for r in core[layer]]
                + ([off] if isinstance(off, dict) and off.get("attest") else []) + [r for _, r in sel])
        vendors, plans = _hipaa_vendors(recs)
        if not vendors:
            vendors = ["each vendor that stores or processes health data (self-hosted components need your own "
                       "safeguards)"]
        note = (" " + "; ".join(plans) + ".") if plans else ""
        add(conflict("HIPAA_BAA", vendors=_join(vendors), plan_note=note))
    if val(p, "requirements.multi_tenant") and core["database"]:
        db = core["database"][0]
        mech = (f"row-level security in {db['name']} with a tenant_id column on every table"
                if "rls_multi_tenant" in (db.get("caps") or ()) else
                f"a tenant_id key checked in every {db['name']} query")
        add(conflict("MULTI_TENANT_ISOLATION", mechanism=mech))
    ml = val(p, "requirements.ml_features", "none")
    if ml == "llm_rag" and p.effective_residency not in ("none",):
        mls = [r for layer, r in sel if layer == "ml"]
        region = (p.regions[0][1] if p.regions else p.effective_residency)
        prof = (f"{mls[0]['name']} with a {p.effective_residency} region or in-country inference profile"
                if mls else "an in-region model endpoint")
        add(conflict("LLM_DATA_RESIDENCY", profile=prof,
                     region=p.effective_residency if p.effective_residency != "other" else "the required country"))

    # ---- skills
    langs = ", ".join(p.languages) or "none listed"
    pressure_weeks = 1 if p.delivery_pressure >= 2 else 2 if p.delivery_pressure == 1 else 3
    for layer in ("frontend", "backend"):
        for r in core[layer]:
            if _mismatch(p, r):
                _, lang = _best_affinity(p.languages, r["languages"])
                need = "/".join(r["languages"])
                reason = _skill_reason(r, layer, ranked)
                add(conflict("SKILL_MISMATCH", name=r["name"], lang=need, langs=langs, reason=reason,
                             weeks=pressure_weeks))
    if val(p, "team.willing_to_learn") is False and ranked:
        for layer in sorted(ranked):
            cands = [s for s in ranked[layer] if (s.tech.get("languages") or ())]
            if cands and all(_mismatch(p, s.tech) for s in cands):
                add(conflict("SKILL_GAP_NO_LEARNING", layer=layer.replace("_", " "), langs=langs,
                             name=cands[0].tech["name"],
                             assumption=f"false cannot be met for the {layer.replace('_', ' ')}: "
                                        f"{cands[0].tech['name']} needs {'/'.join(cands[0].tech['languages'])}."))
                break

    # ---- over-engineering avoided (a threshold-blocked candidate that would otherwise be top-3)
    if ranked:
        k = 3
        for layer in sorted(ranked):
            items = list(ranked[layer])
            for s in items:
                c = s.get("overengineering")
                if c is None or c.value >= 0:
                    continue
                without = s.total - c.value
                better = sum(1 for o in items if o is not s and o.total > without)
                if better < k:
                    add(conflict("OVERENGINEERING_AVOIDED", name=s.tech["name"], k=k,
                                 layer=layer.replace("_", " "), threshold_text=c.reason, fields=c.fields))

    # ---- lock-in
    tol = val(p, "infrastructure.lock_in_tolerance", "medium")
    seen = set()
    for layer, r in [(lyr, r) for lyr in ("frontend", "backend", "database", "hosting") for r in core[lyr]] + sel:
        if r.get("lock_in") == 3 and r["id"] not in seen:
            seen.add(r["id"])
            add(conflict("LOCK_IN_RISK", severity=W if tol == "low" else I, name=r["name"],
                         area=layer.replace("_", " ")))
    return out


def _skill_reason(rec: dict, layer: str, ranked) -> str:
    """Why the mismatched record still won: its top positive scoring contributions."""
    sc = None
    for lyr, items in (ranked or {}).items():
        for s in items:
            if s.tech.get("id") == rec["id"]:
                sc = s
                break
        if sc:
            break
    if sc is None:
        return "no option in team.languages passed the hard constraints and scoring"
    pos = sorted((c for c in sc.contributions if c.value > 0), key=lambda c: (-c.value, c.key))[:2]
    if not pos:
        return "no option in team.languages passed the hard constraints and scoring"
    return ("its strongest scoring terms outweigh the skill penalty ("
            + ", ".join(f"{c.key.replace('_', ' ')} {c.value:+.2f}" for c in pos) + ")")


__all__ = ["CATALOGUE", "NOT_EMITTED", "Entry", "Conflict", "conflict", "detect", "post_checks", "infeasible",
           "profile_changes", "apply_changes", "relaxed", "assumptions", "merge", "RELAXED_PREFIX"]

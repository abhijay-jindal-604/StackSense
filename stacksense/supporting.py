"""Supporting-service selection (plan sections 3.11, 4.3, 5.4 rule C2, 6.1 and 7).

``select(p, core, *, needs_managed_realtime=False) -> SupportingResult``

For every *slot* in :data:`SLOTS` (one need inside a supporting layer, for example ``auth`` or
``other.sms``) the trigger rules of plan 6.1 are evaluated against explicit requirements,
description signals, compliance and the chosen core stack. A slot whose trigger does not fire is
recorded in ``SupportingResult.skipped`` with the conditions that were checked. A triggered slot:

1. takes the KB records of its layer restricted to the slot's kinds (scope, not a rejection);
2. runs the hard filters (``filters.apply_hard``); failures are kept as :class:`filters.Rejection`;
3. runs the compatibility gates against the chosen core stack (:func:`_compat`): bundled services
   need their back end, in-process libraries need the back end's runtime, VPC-bound hyperscaler
   services need a host on that cloud, self-managed servers need a host that runs containers,
   C2 (managed realtime), and so on; failures are kept as :class:`Incompatible`;
4. scores the survivors with the plan 6.1 subset of ``scoring.score`` (contributions 1, 3, 4, 5, 9,
   20) plus the supporting affinity terms (native +3, bundled +2, reuse +2, new vendor -2) and the
   selection-note terms of plan 6.1 (all weights in :data:`SW`);
5. picks the best by ``(-round(total, 4), id)``.

If nothing survives, the slot becomes a :class:`SupportingGap` with a warning
(``AIRGAP_EXTERNAL_DEPENDENCY``, ``CLOUD_REGION_GAP`` or ``SUPPORTING_GAP``); a filtered-out or
incompatible candidate is never chosen.

``core`` describes the chosen core stack with plain ids or KB records (see :class:`CoreStack`); this
module does not depend on ``combine.py``. ``needs_managed_realtime`` is plan 5.4 rule C2: when True
the realtime layer is restricted to vendor-operated realtime services compatible with the host.

``SupportingResult.cost_lines(p)`` returns :class:`cost.CostLine` objects for ``cost.estimate(...,
extra_lines=...)``: a band line per selected service, usage lines for object storage, media egress
and SMS OTP (plan 7), and zero lines for services billed inside the back end's plan.

Pure and deterministic: no clock, no randomness, every set iterated sorted, ties broken by id.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from . import filters, kb
from . import scoring as _scoring
from .cost import CostLine, band_line
from .kb import costs as _costs
from .kb.bindings import BINDINGS
from .kb.model import size_index
from .output import SUPPORTING_LAYERS as OUTPUT_LAYER_ORDER
from .scoring import DYNAMIC_FIELDS, Contribution, LayerContext, Scored, _size_fields, fmt, val

# ================================================================== constants (one table)
SW: dict[str, Any] = {
    # affinity terms (plan 6.1)
    "native": 3, "bundled": 2, "reuse": 2, "new_vendor": -2,
    # requirement fit inside a layer
    "req_native": 2, "req_poor": -3, "org_bonus": 1,
    # selection-note fits (plan 6.1 "Selection notes")
    "fit_good": 2, "fit_bad": -2, "fit_wrong": -3, "fit_small": 1, "overengineering": -10,
    "deployment_tag": 2, "india_gateway": 3, "india_invite_only": -3, "dlt_sms": 3,
    "ci_default": 2,
    # thresholds
    "cache_p95_ms": 200, "cache_read_min_size": "m", "cache_fanout_min_size": "m",
    "sessions_min_size": "m",
    "queue_db_max_size": "s", "queue_db_max_ops": 2, "queue_managed_min_size": "m",
    "kafka_min_size": "l", "kafka_min_ops": 4, "kafka_min_msgs": 5000,
    "search_db_max_gb": 100, "search_db_max_size": "s", "search_cluster_min_size": "l",
    "algolia_min_ttm": 4,
    "onnx_max_share_usd": 150, "onnx_max_size": "s",
    "vector_cluster_min_size": "l",
    "signalr_service_min_size": "m",
    "host_git_max_team": 2, "small_stack_max_size": "s",
    "datadog_min_budget": 3000, "datadog_min_size": "m",
    "paddle_max_team": 3,
    "api_gateway_min_size": "m",
    "max_driven_by": 8, "max_alternatives": 4, "max_tradeoffs": 4,
    # budget term inside a slot (calibration 14 Nov): compare with the cheapest compatible option when the
    # layer's share is below it, so the floor of scoring.W never ties cheap and dear options at low budgets
    # (that tie flipped EAS Build / fastlane as the budget fell)
    "budget_relative": True,
    # SMS gap severity when the chosen auth offers a non-SMS sign-in (calibration 14 Nov)
    "sms_gap_with_fallback": "warning",
}
SMS_GAP_SLOT = "other.sms"
SMS_FALLBACK_MODES = ("email_password", "social")
SMS_FALLBACK_CAPS = ("magic_links", "passkeys")

# Contributions of scoring.score that apply to supporting layers (plan 6.1: 1, 3, 4, 5, 9, 20).
SCORE_KEYS = ("priorities", "ops_fit", "scale_fit", "budget_fit", "lock_in", "security_fit")

HYPERSCALERS = ("aws", "azure", "gcp")
GENERAL_RUNTIMES = ("beam", "dotnet", "go", "jvm", "node", "php", "python", "ruby")
CONTAINER_HOST_KINDS = ("container", "hybrid_appliance", "k8s", "onprem", "paas", "vm")
FUNCTION_BACKEND_KINDS = ("baas", "commerce_saas", "none", "serverless_fn")
POSTGRES_ENGINES = ("postgres", "postgres_14", "timescaledb", "yugabytedb", "cockroachdb")
RELATIONAL_KIND = "relational"
SELF_DEPLOYMENTS = ("self_hosted_cloud_vm", "on_premise", "air_gapped")

# Kinds that run inside the application process or need no server of their own.
IN_PROCESS_KINDS = ("bundled", "db_backed", "db_native", "inference_library", "library", "maps",
                    "mobile_ci", "native", "none", "offline_sync", "redis_backed", "static_index",
                    "vector_store")
K8S_ONLY_KINDS = ("gitops", "model_serving")
# Kinds priced at USD 0 because they run inside the application process (plan 7 table: "ML: in-process
# ONNX 0 (uses app compute)"); the host band already pays for that compute.
COST_IN_APP_COMPUTE_KINDS = ("inference_library",)
SELF_OPERATED_ONLY_KINDS = ("filesystem",)      # a disk/NFS volume: only on servers the team runs
# Layers / other-kinds whose hyperscaler-only services need a host on that cloud (VPC-bound or
# operating on that cloud's resources). Storage, CDN, auth, email, push, maps and integrations are
# reachable over public APIs and only get the affinity terms.
SAME_CLOUD_LAYERS = ("cache", "ci_cd", "ml", "observability", "queue", "realtime", "search")
SAME_CLOUD_OTHER_KINDS = ("api_gateway", "secrets", "waf")
# Services usable only with one host family.
HOST_BOUND = {"cloudflare_durable_objects": "cloudflare", "cloudflare_queues": "cloudflare",
              "cloudflare_kv": "cloudflare"}
# Required database engines of database-coupled services.
DB_REQUIREMENT = {
    "pg_boss": POSTGRES_ENGINES, "procrastinate": POSTGRES_ENGINES, "river_queue": POSTGRES_ENGINES,
    "oban": POSTGRES_ENGINES, "pg_fts": POSTGRES_ENGINES, "pgvector": POSTGRES_ENGINES,
    "sqlserver_fts": ("sqlserver",), "hangfire": ("sqlserver",) + POSTGRES_ENGINES,
    "jobrunr": RELATIONAL_KIND, "solid_queue": RELATIONAL_KIND,
    "powersync": POSTGRES_ENGINES + ("mongodb", "mongodb_60", "mysql", "mysql_80"),
}
# Frontend requirement of client-side tooling.
FRONTEND_REQUIREMENT = {"expo_eas_build": ("react_native_expo",), "watermelondb": ("react_native_expo",)}
# Provider family of a KB region binding key (host and service share a family -> "native").
PROVIDER_ALIASES = {
    "aws": "aws", "gcp": "gcp", "azure_foundational": "azure", "azure_mainstream": "azure",
    "azure_strategic": "azure", "azure_managed_redis": "azure", "azure_container_apps": "azure",
    "azure_static_web_apps": "azure", "cloudflare": "cloudflare", "cloudflare_r2": "cloudflare",
    "digitalocean": "digitalocean", "supabase": "supabase", "vercel": "vercel", "netlify": "netlify",
    "fly": "fly", "render": "render", "railway": "railway", "hetzner": "hetzner",
    "firebase_auth": "gcp", "firebase_app_hosting": "gcp", "cognito": "aws", "bedrock": "aws",
    "entra_id": "azure", "fcm": "gcp",
}
# Existing-system text -> KB ids it lets the stack reuse (used when existing.analyse has no match).
EXISTING_ALIASES = {
    "entra_id_workforce": ("entra id", "azure ad", "azure active directory", "active directory"),
    "microsoft_graph_api": ("microsoft 365", "office 365", "m365", "sharepoint", "microsoft teams", "outlook"),
    "keycloak": ("keycloak",), "zitadel": ("zitadel",), "amazon_cognito": ("cognito",),
    "auth0": ("auth0", "okta customer identity"), "azure_pipelines": ("azure devops", "azure pipelines"),
    "gitlab_ci_saas": ("gitlab",), "gitlab_self_managed": ("gitlab",), "jenkins": ("jenkins",),
    "github_actions": ("github",), "sentry": ("sentry",), "datadog": ("datadog",),
    "grafana_prometheus_loki": ("prometheus", "grafana"), "rabbitmq_self": ("rabbitmq",),
    "apache_kafka_self": ("kafka",), "metabase": ("metabase",), "apache_superset": ("superset",),
    "stripe": ("stripe",), "razorpay": ("razorpay",),
}
SECRETS_REGIMES = ("hipaa", "iso27001", "pci_dss", "rbi_localisation", "soc2")
WAF_PUBLIC_TYPES = ("fintech", "healthtech")
STORAGE_SIGNALS = ("kyc_documents", "photos", "video")
REALTIME_SIGNALS = ("chat", "collaborative_editing", "live_tracking")
QUEUE_SIGNALS = ("notifications", "intermittent_connectivity")
REALTIME_TYPES = ("realtime_collab", "gaming")
WIDE_SPREAD = ("multi_region", "global")
MOBILE = ("android", "ios")
INTERNET_NEEDS = ("payments", "other.sms", "other.push", "other.email", "cdn")   # air-gap gap code

GAP_CODES = ("AIRGAP_EXTERNAL_DEPENDENCY", "CLOUD_REGION_GAP", "SUPPORTING_GAP")


# ================================================================== data types
@dataclass(frozen=True)
class CoreStack:
    """The chosen core stack as KB records. Build with :meth:`of` from ids, records or ``Scored``."""
    backend: dict | None = None
    database: dict | None = None
    hosts: tuple[dict, ...] = ()
    frontends: tuple[dict, ...] = ()
    provider: str | None = None          # explicit provider family override (else from hosts)
    frontend_hosts: tuple[dict, ...] = ()  # hosts that serve only the frontend (subset of ``hosts``)

    @classmethod
    def of(cls, core: Any) -> "CoreStack":
        if isinstance(core, CoreStack):
            return core
        get = (core.get if isinstance(core, Mapping) else lambda k, d=None: getattr(core, k, d))

        def rec(x):
            if x is None:
                return None
            if isinstance(x, Scored):
                return x.tech
            if isinstance(x, str):
                r = kb.get(x)
                if r is None:
                    raise ValueError(f"unknown KB id {x!r} in core stack")
                return r
            if isinstance(x, Mapping):
                return dict(x)
            t = getattr(x, "tech", None)
            return t if isinstance(t, dict) else None

        def many(x):
            if x is None:
                return ()
            items = x if isinstance(x, (list, tuple)) else [x]
            return tuple(r for r in (rec(i) for i in items) if r is not None)

        hosts = many(get("hosting", None) or get("hosts", None))
        fe_only = tuple(h for h in many(get("frontend_hosting", None)) if h["id"] not in {x["id"] for x in hosts})
        hosts += fe_only
        return cls(backend=rec(get("backend", None)), database=rec(get("database", None)), hosts=hosts,
                   frontends=many(get("frontend", None) or get("frontends", None)),
                   provider=get("provider", None), frontend_hosts=fe_only)


@dataclass(frozen=True)
class Incompatible:
    """A candidate that passed the hard filters but cannot work with the chosen core stack."""
    tech_id: str
    name: str
    layer: str
    reason_text: str
    fields: tuple[str, ...] = ()
    rule: str = "COMPAT"
    code: str = "compatibility"

    def to_dict(self) -> dict:
        return {"tech_id": self.tech_id, "name": self.name, "layer": self.layer, "rule": self.rule,
                "code": self.code, "fields": list(self.fields), "reason_text": self.reason_text}


@dataclass(frozen=True)
class Selection:
    slot: str                                   # e.g. "auth", "other.sms"
    layer: str                                  # output layer
    chosen: Scored
    ranked: tuple[Scored, ...]                  # every eligible candidate, best first
    rejected: tuple[filters.Rejection, ...]     # hard-filter failures (sorted by id)
    incompatible: tuple[Incompatible, ...]      # compatibility failures (sorted by id)
    triggers: tuple[tuple[str, str], ...]       # (field path, plain-language reason)

    @property
    def tech(self) -> dict:
        return self.chosen.tech

    @property
    def id(self) -> str:
        return self.chosen.tech["id"]

    @property
    def alternatives(self) -> tuple[Scored, ...]:
        return self.ranked[1:]

    def driven_by(self) -> list[str]:
        out: list[str] = []
        for f, _ in self.triggers:
            if f not in out:
                out.append(f)
        contribs = sorted((c for c in self.chosen.contributions if abs(c.value) >= 0.5),
                          key=lambda c: (-abs(c.value), c.key))
        for c in contribs:
            for f in c.fields:
                if f not in out:
                    out.append(f)
        top = _top_rejection(self.rejected)
        if top is not None:
            for f in top.fields:
                if f not in out:
                    out.append(f)
        return out[:SW["max_driven_by"]]

    def to_component(self) -> dict:
        """A statement section 4 supporting component (deterministic, from contributions/reasons)."""
        t = self.tech
        why = "; ".join(r for _, r in self.triggers)
        pos = sorted((c for c in self.chosen.contributions if c.value > 0), key=lambda c: (-c.value, c.key))
        just = f"{t['name']} is chosen for {self.layer} because {why}."
        if pos:
            just += " " + " ".join(f"{c.reason} ({_signed(c.value)} {c.key})" for c in pos[:2])
        alts = []
        for s in self.alternatives[:2]:
            alts.append({"choice": s.tech["name"], "why_not": _why_not(self.chosen, s)})
        for r in _popular_rejections(self.rejected, self.incompatible)[:2]:
            if r.tech_id not in {self.id} and all(a["choice"] != r.name for a in alts):
                alts.append({"choice": r.name, "why_not": r.reason_text})
        trade = list(t.get("tradeoffs") or [])[:2]
        trade += [c.reason for c in self.chosen.contributions if c.value <= -1][:2]
        return {"layer": self.layer, "slot": self.slot, "kb_id": self.id, "choice": t["name"],
                "justification": just, "driven_by": self.driven_by(),
                "alternatives": alts[:SW["max_alternatives"]], "tradeoffs": trade[:SW["max_tradeoffs"]]}


@dataclass(frozen=True)
class SupportingGap:
    """A triggered slot with no candidate that passes the hard filters and compatibility gates."""
    slot: str
    layer: str
    triggers: tuple[tuple[str, str], ...]
    code: str
    severity: str
    message: str
    fields: tuple[str, ...]
    rejected: tuple[filters.Rejection, ...]
    incompatible: tuple[Incompatible, ...]
    workaround: str = ""

    def warning(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "fields": list(self.fields)}

    def relaxed(self) -> str:
        return f"RELAXED: {', '.join(f for f, _ in self.triggers)} ({self.slot}): {self.workaround or 'left out'}"


@dataclass(frozen=True)
class SupportingResult:
    selections: tuple[Selection, ...]           # output order (statement layer order; other by name)
    gaps: tuple[SupportingGap, ...]
    skipped: tuple[tuple[str, str, str], ...]   # (slot, layer, why not needed)
    assumptions: tuple[str, ...] = ()
    needs_managed_realtime: bool = False

    @property
    def warnings(self) -> tuple[dict, ...]:
        return tuple(g.warning() for g in self.gaps)

    def layers(self) -> list[str]:
        out = []
        for s in self.selections:
            if s.layer not in out:
                out.append(s.layer)
        return out

    def get(self, slot: str) -> Selection | None:
        return next((s for s in self.selections if s.slot == slot), None)

    def by_layer(self, layer: str) -> list[Selection]:
        return [s for s in self.selections if s.layer == layer]

    def gap(self, slot: str) -> SupportingGap | None:
        return next((g for g in self.gaps if g.slot == slot), None)

    def ids(self) -> list[str]:
        return [s.id for s in self.selections]

    def records(self) -> list[dict]:
        """Selected KB records (for ``architecture.decide`` and ``tests.helpers``)."""
        return [s.tech for s in self.selections]

    def components(self) -> list[dict]:
        return [s.to_component() for s in self.selections]

    def cost_lines(self, p) -> list[CostLine]:
        return cost_lines(self, p)

    def trace(self) -> dict:
        return {
            "selected": [{"slot": s.slot, "layer": s.layer, "id": s.id, "total": round(s.chosen.total, 2),
                          "ranked": [{"id": r.tech["id"], "total": round(r.total, 2)} for r in s.ranked[:5]],
                          "rejected": [r.to_dict() for r in s.rejected],
                          "incompatible": [i.to_dict() for i in s.incompatible],
                          "triggers": [list(t) for t in s.triggers]} for s in self.selections],
            "gaps": [{"slot": g.slot, "layer": g.layer, "code": g.code, "message": g.message} for g in self.gaps],
            "skipped": [list(s) for s in self.skipped],
        }


# ================================================================== helpers
def _signed(x: float) -> str:
    x = round(x, 2)
    s = f"{x:g}"
    return ("+" + s) if x > 0 else s


def _size_ge(p, size: str) -> bool:
    return size_index(p.size) >= size_index(size)


def _size_le(p, size: str) -> bool:
    return size_index(p.size) <= size_index(size)


def _caps(rec) -> list:
    return rec.get("caps") or []


def _top_rejection(rejected):
    pop = _popular_rejections(rejected, ())
    return pop[0] if pop else None


def _popular_rejections(rejected, incompatible) -> list:
    items = list(rejected) + list(incompatible)
    rows = []
    for r in items:
        rec = kb.get(r.tech_id) or {}
        if rec.get("status") != "maintained":
            continue
        pop = (rec.get("attrs") or {}).get("popularity", 0)
        if pop >= 4:
            rows.append((-pop, r.tech_id, r))
    return [r for _, _, r in sorted(rows, key=lambda t: (t[0], t[1]))]


def _why_not(win: Scored, alt: Scored) -> str:
    deltas = {}
    for c in win.contributions:
        deltas[c.key] = [c.value, 0.0, c]
    for c in alt.contributions:
        deltas.setdefault(c.key, [0.0, 0.0, c])
        deltas[c.key][1] = c.value
        deltas[c.key][2] = c
    worst = sorted(((a - w, k, c) for k, (w, a, c) in deltas.items() if a - w < 0), key=lambda t: (t[0], t[1]))
    head = f"scores {round(alt.total, 2):g} vs {round(win.total, 2):g} for {win.tech['name']}"
    if not worst:
        return head + " (tie broken by id)."
    d, k, c = worst[0]
    return f"{head}; largest gap {k} ({_signed(d)}): {c.reason}"


def provider_of(rec: dict | None) -> str | None:
    """Provider family of a record: a single hyperscaler affinity, else its region-binding family."""
    if not rec:
        return None
    aff = list(rec.get("cloud_affinity") or ())
    if len(aff) == 1 and aff[0] in HYPERSCALERS:
        return aff[0]
    rk = BINDINGS.get(rec["id"], (None, None))[0]
    if rk in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[rk]
    return None


def _host_runtimes(host: dict) -> set:
    rt = host.get("runtime")
    out = set(host.get("platforms") or ())
    if isinstance(rt, (list, tuple)):
        out.update(rt)
    elif isinstance(rt, str):
        out.add(rt)
    return out


class _Cx:
    """Everything the triggers, gates and fits read about the stack being completed."""

    def __init__(self, p, core: CoreStack, needs_managed_realtime: bool):
        self.p = p
        self.core = core
        self.backend = core.backend
        self.database = core.database
        self.hosts = tuple(h for h in core.hosts if h)
        self.frontends = core.frontends
        self.fe_ids = {f["id"] for f in self.frontends}
        self.mrt = bool(needs_managed_realtime)
        self.sig = {s.id: s for s in (getattr(p, "signals", ()) or ())}
        fams = {provider_of(h) for h in self.hosts}
        if core.provider:
            fams.add(core.provider)
        fams.discard(None)
        self.host_families = frozenset(fams)
        bp = provider_of(self.backend)
        self.stack_providers = frozenset(fams | ({bp} if bp else set()))
        self.backend_id = (self.backend or {}).get("id")
        self.backend_kind = (self.backend or {}).get("kind")
        self.db_id = (self.database or {}).get("id")
        self.db_kind = (self.database or {}).get("kind")
        rts: set = set()
        if self.backend and self.backend_kind not in FUNCTION_BACKEND_KINDS and self.backend.get("runtime"):
            rts.add(self.backend["runtime"])
        if self.backend_kind in FUNCTION_BACKEND_KINDS:
            if self.backend and self.backend.get("runtime") in GENERAL_RUNTIMES:
                rts.add(self.backend["runtime"])
            # A host that serves only the frontend runs the frontend's code, not arbitrary back-end
            # libraries: it contributes only the runtimes the chosen frontends themselves use.
            fe_only = {h["id"] for h in (core.frontend_hosts or ())}
            fe_rts = {f.get("runtime") for f in self.frontends} & set(GENERAL_RUNTIMES)
            for h in self.hosts:
                allowed = fe_rts if h["id"] in fe_only else set(GENERAL_RUNTIMES)
                rts |= _host_runtimes(h) & allowed
        self.stack_runtimes = frozenset(rts)
        self.chosen: dict[str, dict] = {}
        self.n_layers = 1                    # triggered supporting layers sharing the budget (set by select)
        ex = getattr(p, "existing", None)
        self.existing_matches = list(getattr(ex, "matches", ()) or ()) if ex else []
        self.existing_raw = [str(s) for s in (val(p, "infrastructure.existing_systems") or [])]

    # --- stack facts
    def has_backend(self) -> bool:
        return bool(self.backend) and self.backend_kind != "none"

    def nonempty(self) -> bool:
        return self.has_backend() or any(f.get("kind") != "none" for f in self.frontends) or bool(self.hosts)

    def container_host(self) -> bool:
        return any(h.get("kind") in CONTAINER_HOST_KINDS and _host_runtimes(h) & set(GENERAL_RUNTIMES)
                   for h in self.hosts)

    def host_runs(self, runtimes) -> bool:
        want = set(runtimes)
        return any(h.get("kind") in CONTAINER_HOST_KINDS and _host_runtimes(h) & want for h in self.hosts)

    def long_lived_host(self) -> bool:
        return any("long_lived_conn" in _caps(h) for h in self.hosts)

    def k8s_host(self) -> bool:
        return any(h.get("kind") == "k8s" or (h.get("kind") == "onprem" and "kubernetes" in _caps(h)) for h in self.hosts)

    def edge_host(self) -> bool:
        return any("edge" in _caps(h) and h.get("kind") in ("static_host", "paas", "serverless_fn") for h in self.hosts)

    def git_deploy_host(self) -> bool:
        return any(h.get("kind") in ("static_host", "paas") and provider_of(h) not in HYPERSCALERS for h in self.hosts)

    def logs_host(self) -> bool:
        return any(h.get("kind") in ("static_host", "paas", "serverless_fn") for h in self.hosts)

    def serverless_host(self) -> bool:
        return bool(self.hosts) and all(h.get("kind") in ("static_host", "serverless_fn") or "scale_to_zero" in _caps(h)
                                        for h in self.hosts)

    def autoscaling_host(self) -> bool:
        return any("autoscaling" in _caps(h) for h in self.hosts)

    def host_names(self) -> str:
        return " + ".join(h["name"] for h in self.hosts) or "no host"

    def signal_text(self, sid: str) -> str:
        return f"project.description mentions '{self.sig[sid].matched_text}'"

    def reuse_hit(self, rec) -> str | None:
        """The existing-system string the record reuses, or None."""
        for m in self.existing_matches:
            targets = getattr(m, "reuse_targets", ()) or ()
            if any(_scoring.reuse_target_matches(t, rec, rec.get("layer")) for t in targets):
                return getattr(m, "raw", rec["id"])
        for raw in self.existing_raw:
            low = raw.lower()
            if any(a in low for a in EXISTING_ALIASES.get(rec["id"], ())):
                return raw
        return None


def _managed_realtime(rec) -> bool:
    return bool(rec.get("saas")) and not rec.get("self_hostable")


def _in_process(rec) -> bool:
    return rec.get("kind") in IN_PROCESS_KINDS or any(c in _caps(rec) for c in ("no_extra_service", "in_process"))


def _resolved_cms(p) -> str | None:
    cms = val(p, "requirements.cms", "auto")
    if cms and cms != "auto":
        return cms
    for s in getattr(p, "signals", ()) or ():
        eff = getattr(s, "effect", "") or ""
        if eff.startswith("cms="):
            return eff.split("=", 1)[1]
    return None


# ================================================================== triggers (plan 6.1)
Trig = list  # list[tuple[field, text]]


def _t_auth(p, cx) -> Trig:
    a = val(p, "requirements.auth", "none")
    return [("requirements.auth", f"requirements.auth={a}")] if a != "none" else []


def _t_storage(p, cx) -> Trig:
    out = []
    if val(p, "requirements.file_media_storage"):
        out.append(("requirements.file_media_storage", "requirements.file_media_storage=true"))
    for sid in STORAGE_SIGNALS:
        if sid in cx.sig:
            out.append(("project.description", f"{cx.signal_text(sid)} (files to store)"))
    return out


def _t_cdn(p, cx) -> Trig:
    if "web" not in p.clients or p.air_gapped:
        return []
    geo = val(p, "scale.geographic_spread")
    if "internal_only" in cx.sig and geo not in WIDE_SPREAD:
        return []
    out = []
    if val(p, "requirements.seo_critical"):
        out.append(("requirements.seo_critical", "requirements.seo_critical=true"))
    if val(p, "scale.workload") == "read_heavy":
        out.append(("scale.workload", "scale.workload=read_heavy"))
    if geo in WIDE_SPREAD:
        out.append(("scale.geographic_spread", f"scale.geographic_spread={geo}"))
    if _size_ge(p, "m"):
        out.append((_size_fields(p)[0], f"size class {p.size}"))
    if val(p, "requirements.file_media_storage"):
        out.append(("requirements.file_media_storage", "requirements.file_media_storage=true (media delivery)"))
    return out


def _t_cache(p, cx) -> Trig:
    out = []
    if val(p, "scale.workload") == "read_heavy" and _size_ge(p, SW["cache_read_min_size"]):
        out.append(("scale.workload", f"scale.workload=read_heavy at size {p.size}"))
    ms = val(p, "requirements.p95_latency_ms")
    if ms is not None and ms <= SW["cache_p95_ms"]:
        out.append(("requirements.p95_latency_ms", f"requirements.p95_latency_ms={fmt(ms)} (<= {SW['cache_p95_ms']} ms)"))
    rt = cx.chosen.get("realtime")
    if rt and not _managed_realtime(rt) and _size_ge(p, SW["cache_fanout_min_size"]):
        out.append(("requirements.realtime", f"self-hosted {rt['name']} fans out across several instances at size {p.size} (pub/sub, presence)"))
    au = cx.chosen.get("auth")
    if au and au.get("kind") == "native" and _size_ge(p, SW["sessions_min_size"]) and cx.autoscaling_host():
        out.append(("requirements.auth", f"server sessions of {au['name']} are shared by autoscaled instances at size {p.size}"))
    return out


def _t_queue(p, cx) -> Trig:
    out = []
    if val(p, "requirements.background_jobs"):
        out.append(("requirements.background_jobs", "requirements.background_jobs=true"))
    if val(p, "requirements.payments"):
        out.append(("requirements.payments", "requirements.payments=true (payment webhooks and retries)"))
    if val(p, "scale.workload") == "write_heavy" and val(p, "scale.traffic_pattern") != "steady":
        out.append(("scale.workload", f"scale.workload=write_heavy with scale.traffic_pattern={val(p, 'scale.traffic_pattern')} (buffer bursts)"))
    ml = val(p, "requirements.ml_features", "none")
    if ml in ("training", "llm_rag"):
        out.append(("requirements.ml_features", f"requirements.ml_features={ml} (ingestion jobs)"))
    if val(p, "requirements.notifications"):
        out.append(("requirements.notifications", f"requirements.notifications={fmt(val(p, 'requirements.notifications'))}"))
    for sid in QUEUE_SIGNALS:
        if sid in cx.sig:
            out.append(("project.description", f"{cx.signal_text(sid)} (deferred processing)"))
    return out


def _t_search(p, cx) -> Trig:
    return ([("requirements.full_text_search", "requirements.full_text_search=true")]
            if val(p, "requirements.full_text_search") else [])


def _t_realtime(p, cx) -> Trig:
    out = []
    if val(p, "requirements.realtime"):
        out.append(("requirements.realtime", "requirements.realtime=true"))
    t = val(p, "project.type")
    if t in REALTIME_TYPES:
        out.append(("project.type", f"project.type={t}"))
    for sid in REALTIME_SIGNALS:
        if sid in cx.sig:
            out.append(("project.description", cx.signal_text(sid)))
    if cx.mrt and not out:
        out.append(("requirements.realtime", "the chosen core stack needs a managed realtime service (C2)"))
    return out


def _t_payments(p, cx) -> Trig:
    return [("requirements.payments", "requirements.payments=true")] if val(p, "requirements.payments") else []


def _ml_is(*modes):
    def t(p, cx) -> Trig:
        ml = val(p, "requirements.ml_features", "none")
        return [("requirements.ml_features", f"requirements.ml_features={ml}")] if ml in modes else []
    return t


def _t_ci(p, cx) -> Trig:
    if not cx.nonempty():
        return []
    return [("project.platforms", f"project.platforms={fmt(val(p, 'project.platforms'))} (code to build and deploy)")]


def _t_ci_mobile(p, cx) -> Trig:
    mob = [c for c in p.clients if c in MOBILE]
    return [("project.platforms", f"project.platforms includes {', '.join(mob)} (store builds)")] if mob else []


def _t_ci_gitops(p, cx) -> Trig:
    return [("team.has_devops", f"the host {cx.host_names()} is Kubernetes")] if cx.k8s_host() else []


def _t_observability(p, cx) -> Trig:
    if not cx.has_backend():
        return []
    why = f"a server back end ({cx.backend['name']}) runs in production"
    active = [f for f in DYNAMIC_FIELDS if f != "project.type" and val(p, f) not in (None, False, "none")]
    return [(f, f"{f}={fmt(val(p, f))}: {why}") for f in active[:2]] or [("project.type", f"project.type={val(p, 'project.type')}: {why}")]


def _t_sms(p, cx) -> Trig:
    out = []
    if val(p, "requirements.auth") == "phone_otp":
        out.append(("requirements.auth", "requirements.auth=phone_otp (SMS one-time passwords)"))
    if "sms" in (val(p, "requirements.notifications") or []):
        out.append(("requirements.notifications", "requirements.notifications includes sms"))
    return out


def _t_push(p, cx) -> Trig:
    out = []
    if "push" in (val(p, "requirements.notifications") or []):
        out.append(("requirements.notifications", "requirements.notifications includes push"))
    mob = [c for c in p.clients if c in MOBILE]
    if mob and (val(p, "requirements.realtime") or "chat" in cx.sig):
        f, why = (("project.description", cx.signal_text("chat")) if "chat" in cx.sig
                  else ("requirements.realtime", "requirements.realtime=true"))
        out.append((f, f"{why} on a mobile client ({', '.join(mob)}) needs push when the app is closed"))
    return out


def _t_email(p, cx) -> Trig:
    out = []
    if "email" in (val(p, "requirements.notifications") or []):
        out.append(("requirements.notifications", "requirements.notifications includes email"))
    if val(p, "requirements.auth") == "email_password":
        out.append(("requirements.auth", "requirements.auth=email_password (verification and reset emails)"))
    return out


def _t_secrets(p, cx) -> Trig:
    regs = [c for c in p.compliance if c in SECRETS_REGIMES]
    return [("compliance", f"compliance includes {', '.join(regs)} (key management and secret rotation)")] if regs else []


def _t_waf(p, cx) -> Trig:
    out = []
    if "pci_dss" in p.compliance:
        out.append(("compliance", "compliance includes pci_dss"))
    t = val(p, "project.type")
    if t in WAF_PUBLIC_TYPES and "web" in p.clients:
        out.append(("project.type", f"project.type={t} with a public web client"))
    return out


def _t_api_gateway(p, cx) -> Trig:
    out = []
    if val(p, "project.type") == "api_platform":
        out.append(("project.type", "project.type=api_platform"))
    if p.api_only and _size_ge(p, SW["api_gateway_min_size"]):
        out.append(("project.platforms", f"project.platforms includes api_only at size {p.size}"))
    return out


def _t_offline(p, cx) -> Trig:
    cl = [c for c in p.clients if c in MOBILE + ("desktop",)]
    if val(p, "requirements.offline_support") and cl:
        return [("requirements.offline_support", f"requirements.offline_support=true on {', '.join(cl)}")]
    return []


def _t_cms(p, cx) -> Trig:
    if _resolved_cms(p) != "headless":
        return []
    if val(p, "requirements.cms", "auto") == "headless":
        return [("requirements.cms", "requirements.cms=headless")]
    return [("project.description", f"{cx.signal_text('cms_editors')} (cms=headless)")] if "cms_editors" in cx.sig else []


def _t_registry(p, cx) -> Trig:
    return [("infrastructure.deployment_model", "infrastructure.deployment_model=air_gapped (private image registry)")] if p.air_gapped else []


def _t_integration(p, cx) -> Trig:
    out = []
    for rec in kb.by_layer("other"):
        if rec.get("kind") == "integration" and rec.get("status") == "maintained":
            hit = cx.reuse_hit(rec)
            if hit:
                out.append(("infrastructure.existing_systems", f"infrastructure.existing_systems includes '{hit}'"))
    return sorted(set(out))


def _t_bi(p, cx) -> Trig:
    out = []
    if val(p, "project.type") == "data_analytics":
        out.append(("project.type", "project.type=data_analytics"))
    if "dashboard" in cx.sig:
        out.append(("project.description", cx.signal_text("dashboard")))
    return out


def _t_maps(p, cx) -> Trig:
    return [("project.description", cx.signal_text(s)) for s in ("gps", "live_tracking") if s in cx.sig]


def _t_video(p, cx) -> Trig:
    return [("project.description", cx.signal_text("video"))] if "video" in cx.sig else []


def _t_in_app(p, cx) -> Trig:
    mob = [c for c in p.clients if c in MOBILE]
    if "subscription" in cx.sig and mob:
        return [("project.description", f"{cx.signal_text('subscription')} with store apps ({', '.join(mob)})")]
    return []


# ================================================================== slot table
@dataclass(frozen=True)
class Slot:
    id: str
    layer: str                      # output layer
    kb_layer: str                   # KB layer of the candidates
    kinds: tuple[str, ...] | None   # candidate kinds in scope (None = all)
    trigger: Callable
    when: str                       # plain-language trigger conditions (for "not needed")
    exclude_kinds: tuple[str, ...] = ()
    severity: str = "critical"      # gap severity
    workaround: str = ""
    native_affinity: bool = True    # same-provider +3 applies


SLOTS: tuple[Slot, ...] = (
    Slot("auth", "auth", "auth", None, _t_auth, "requirements.auth != none",
         workaround="implement sign-in in the back-end framework and review it against the hard constraints"),
    Slot("realtime", "realtime", "realtime", None, _t_realtime,
         "requirements.realtime, project.type in {realtime_collab, gaming}, or chat/collaborative editing/live tracking in the description",
         workaround="poll the API at a short interval until a compliant realtime service is available"),
    Slot("storage", "storage", "storage", None, _t_storage,
         "requirements.file_media_storage, or KYC documents/photos/video in the description",
         workaround="store files in the database or on the host's disk until a compliant object store is available"),
    Slot("cdn", "cdn", "cdn", None, _t_cdn,
         "a web client and (seo_critical, read_heavy, multi-region/global users, size >= m or media files), not air-gapped or internal-only",
         severity="warning", workaround="serve static assets from the host directly"),
    Slot("cache", "cache", "cache", None, _t_cache,
         f"read_heavy at size >= {SW['cache_read_min_size']}, p95_latency_ms <= {SW['cache_p95_ms']}, self-hosted realtime fan-out at size >= m, or shared sessions on autoscaled hosts at size >= m",
         exclude_kinds=("none",), severity="warning", workaround="cache in process and at the CDN"),
    Slot("queue", "queue", "queue", None, _t_queue,
         "background_jobs, payments, write_heavy bursts, training/llm_rag ingestion, notifications or offline sync",
         severity="warning", workaround="run jobs in-process with retries stored in the database"),
    Slot("search", "search", "search", None, _t_search, "requirements.full_text_search",
         workaround="use SQL LIKE/trigram queries until a compliant search engine is available"),
    Slot("payments", "payments", "payments", None, _t_payments, "requirements.payments",
         exclude_kinds=("in_app_billing",),
         workaround="take payments offline or through a gateway that meets the constraints once verified"),
    Slot("ml", "ml", "ml", ("inference_library", "managed_platform", "model_serving"), _ml_is("inference_api"),
         "requirements.ml_features=inference_api", workaround="run the model in the back-end process"),
    Slot("ml.llm", "ml", "ml", ("hosted_llm", "llm_serving"), _ml_is("llm_rag"),
         "requirements.ml_features=llm_rag", workaround="leave the assistant out until a compliant model host exists"),
    Slot("ml.vector", "ml", "ml", ("vector_store",), _ml_is("llm_rag"),
         "requirements.ml_features=llm_rag", workaround="store embeddings in the primary database"),
    Slot("ml.training", "ml", "ml", ("managed_platform",), _ml_is("training"),
         "requirements.ml_features=training", workaround="train on a self-managed GPU server"),
    Slot("ml.tracking", "ml", "ml", ("mlops",), _ml_is("training"),
         "requirements.ml_features=training", severity="warning", workaround="track experiments in files under version control"),
    Slot("ci_cd", "ci_cd", "ci_cd", ("bundled", "hosted_ci", "self_hosted_ci"), _t_ci, "a non-empty stack",
         severity="warning", workaround="deploy manually from a release checklist", native_affinity=False),
    Slot("ci_cd.mobile", "ci_cd", "ci_cd", ("mobile_ci",), _t_ci_mobile, "android or ios in project.platforms",
         severity="warning", workaround="build and sign store packages by hand", native_affinity=False),
    Slot("ci_cd.gitops", "ci_cd", "ci_cd", ("gitops",), _t_ci_gitops, "a Kubernetes host",
         severity="warning", workaround="apply manifests from the CI pipeline", native_affinity=False),
    Slot("observability", "observability", "observability", None, _t_observability,
         "a server back end (static sites use the host's analytics)",
         workaround="ship structured logs to files on the host and alert on health checks"),
    Slot("other.sms", "other", "other", ("sms",), _t_sms, "requirements.auth=phone_otp or sms notifications",
         workaround="use email or authenticator-app sign-in until a compliant SMS provider is verified"),
    Slot("other.push", "other", "other", ("push",), _t_push, "push notifications, or a mobile client with realtime/chat",
         severity="warning", workaround="show updates when the app is next opened (in-app inbox)"),
    Slot("other.email", "other", "other", ("email",), _t_email, "email notifications or email_password auth",
         severity="warning", workaround="send email through the organisation's own SMTP relay"),
    Slot("other.secrets", "other", "other", ("secrets",), _t_secrets,
         "compliance includes one of " + ", ".join(SECRETS_REGIMES),
         workaround="keep secrets in the host's encrypted environment settings and rotate them by hand"),
    Slot("other.waf", "other", "other", ("waf",), _t_waf, "pci_dss, or a public fintech/healthtech web client",
         workaround="rate-limit and filter requests in the reverse proxy"),
    Slot("other.api_gateway", "other", "other", ("api_gateway",), _t_api_gateway,
         f"project.type=api_platform, or api_only at size >= {SW['api_gateway_min_size']}",
         severity="warning", workaround="enforce keys and rate limits in the back end"),
    Slot("other.offline_sync", "other", "other", ("offline_sync",), _t_offline,
         "requirements.offline_support with a mobile or desktop client", severity="info",
         workaround="custom outbox sync: queue writes in on-device SQLite and replay them to the API with per-field last-write-wins"),
    Slot("other.cms", "other", "other", ("cms",), _t_cms, "cms=headless", severity="warning",
         workaround="edit content through the back end's admin screens"),
    Slot("other.registry", "other", "other", ("registry",), _t_registry, "deployment_model=air_gapped",
         workaround="load images onto each node from signed archives"),
    Slot("other.integration", "other", "other", ("integration",), _t_integration,
         "an existing system with a known integration API", severity="warning",
         workaround="integrate through scheduled exports from the existing system"),
    Slot("other.bi", "other", "other", ("bi",), _t_bi, "project.type=data_analytics or dashboards in the description",
         severity="warning", workaround="build the dashboards in the web client"),
    Slot("other.maps", "other", "other", ("maps",), _t_maps, "GPS or live tracking in the description",
         severity="info", workaround="store coordinates (PostGIS) and show them without a map layer"),
    Slot("other.video", "other", "other", ("video",), _t_video, "video in the description",
         severity="warning", workaround="serve video files from object storage without adaptive streaming"),
    Slot("other.in_app", "other", "payments", ("in_app_billing",), _t_in_app,
         "subscriptions in the description with an Android/iOS client", severity="warning",
         workaround="use the store billing libraries directly"),
)
SLOT_BY_ID = {s.id: s for s in SLOTS}


# ================================================================== compatibility gates
def _compat(slot: Slot, rec: dict, p, cx: _Cx) -> tuple[str, tuple[str, ...]] | None:
    """(reason, fields) when ``rec`` cannot work with the chosen core stack, else None."""
    rid, name, kind, caps = rec["id"], rec["name"], rec.get("kind"), _caps(rec)
    trig = rec.get("triggers") or []
    # C2: managed realtime only, compatible with the host
    if slot.layer == "realtime":
        if cx.mrt and not _managed_realtime(rec):
            return (f"{name} runs on the application host, but the host {cx.host_names()} cannot hold long-lived "
                    f"connections, so a managed realtime service is required (rule C2).",
                    ("requirements.realtime",))
        if not _managed_realtime(rec) and not cx.long_lived_host():
            return (f"{name} needs long-lived WebSocket connections that {cx.host_names()} does not keep open.",
                    ("requirements.realtime",))
        if kind == "native" and not (cx.backend_kind == "framework" and "websocket" in _caps(cx.backend or {})):
            return (f"{name} needs a back-end framework with built-in WebSockets; {(cx.backend or {}).get('name', 'none')} has none.",
                    ("requirements.realtime",))
    # bundled with a specific back end
    if "bundled_with_backend" in caps:
        owners = sorted(t[:-len("_backend")] for t in trig if t.endswith("_backend"))
        if cx.backend_id not in owners:
            return (f"{name} is part of {' or '.join(owners) or 'another back end'}, and the chosen back end is "
                    f"{(cx.backend or {}).get('name', 'none')}.", ())
    # bound to a host family
    if rid in HOST_BOUND and HOST_BOUND[rid] not in cx.host_families:
        return f"{name} runs only on {HOST_BOUND[rid]} hosts; the host is {cx.host_names()}.", ()
    if kind == "bundled":
        if slot.layer == "cdn" and not cx.edge_host():
            return f"{name} needs a host with its own edge network; {cx.host_names()} has none.", ()
        if slot.layer == "ci_cd" and not cx.git_deploy_host():
            return f"{name} needs a git-connected static/PaaS host; {cx.host_names()} is not one.", ()
        if slot.layer == "observability" and not cx.logs_host():
            return f"{name} needs a managed platform host with built-in logs; {cx.host_names()} is not one.", ()
    # runtime-bound libraries and self-managed servers
    rt = rec.get("runtime")
    lib_rts = set(rec.get("platforms") or ()) & set(GENERAL_RUNTIMES)
    want = ({rt} if rt in GENERAL_RUNTIMES else set()) | lib_rts
    if want:
        if _in_process(rec) and "separate_service" not in caps:
            if not (want & cx.stack_runtimes):
                have = ", ".join(sorted(cx.stack_runtimes)) or "none"
                return (f"{name} runs inside a {'/'.join(sorted(want))} back end; the stack runs {have}.",
                        ("team.languages",))
        elif not cx.host_runs(want):
            return f"{name} is a separate {'/'.join(sorted(want))} server and {cx.host_names()} cannot run it.", ()
    elif (rec.get("self_hostable") and not rec.get("saas") and not _in_process(rec) and not cx.container_host()):
        return f"{name} is a self-managed server and {cx.host_names()} cannot run containers or VMs.", ()
    if kind in K8S_ONLY_KINDS and not cx.k8s_host():
        return f"{name} runs on Kubernetes; the host {cx.host_names()} is not Kubernetes.", ("team.has_devops",)
    # database-coupled
    req = DB_REQUIREMENT.get(rid)
    if req is not None:
        ok = (cx.db_kind == req) if isinstance(req, str) else (cx.db_id in req)
        if not ok:
            need = "a relational database" if isinstance(req, str) else "/".join(req[:2])
            return f"{name} needs {need}; the database is {(cx.database or {}).get('name', 'none')}.", ()
    # client-side tooling
    freq = FRONTEND_REQUIREMENT.get(rid)
    if freq is not None and not (cx.fe_ids & set(freq)):
        return f"{name} works with {', '.join(freq)} clients; the chosen clients are {', '.join(sorted(cx.fe_ids)) or 'none'}.", ()
    plats = set(rec.get("platforms") or ()) & {"android", "ios", "web", "desktop"}
    if plats and slot.layer == "other" and kind == "push" and not (plats & set(p.clients)):
        return f"{name} delivers only to {', '.join(sorted(plats))}; project.platforms has none of them.", ("project.platforms",)
    # VPC-bound / cloud-operated hyperscaler services
    aff = set(rec.get("cloud_affinity") or ())
    same_cloud = slot.layer in SAME_CLOUD_LAYERS or (slot.layer == "other" and kind in SAME_CLOUD_OTHER_KINDS)
    if same_cloud and aff and aff <= set(HYPERSCALERS) and not (aff & cx.host_families):
        return (f"{name} runs inside {'/'.join(sorted(aff))} and is reached from that cloud's network; the host "
                f"{cx.host_names()} is not on it.", ("infrastructure.cloud_preference",))
    # kind-specific scope
    if kind == "static_index" and p.needs_backend:
        return f"{name} indexes pre-built static pages; this project has a server back end.", ("project.type",)
    if kind in SELF_OPERATED_ONLY_KINDS and p.deployment not in SELF_DEPLOYMENTS:
        return (f"{name} is storage on servers the team operates; deployment_model={p.deployment} uses managed "
                f"hosts whose disks are not durable shared storage.", ("infrastructure.deployment_model",))
    if kind == "reverse_proxy_cache" and p.deployment not in SELF_DEPLOYMENTS:
        return (f"{name} replaces a CDN only on self-operated infrastructure; deployment_model={p.deployment}.",
                ("infrastructure.deployment_model",))
    if kind == "integration" and not cx.reuse_hit(rec):
        return f"{name} integrates an existing system that infrastructure.existing_systems does not list.", ()
    if rid == "azure_pipelines" and not cx.reuse_hit(rec):
        return f"{name} is used only when Azure DevOps already exists.", ("infrastructure.existing_systems",)
    if kind == "cms" and "git_based" in caps and _resolved_cms(p) != "git_markdown":
        return f"{name} edits Markdown in git; cms is {_resolved_cms(p)}.", ("requirements.cms",)
    return None


# ================================================================== scoring
def _c(key, value, fields, reason) -> Contribution | None:
    value = round(float(value), 2)
    if value == 0:
        return None
    return Contribution(key, value, tuple(fields), reason)


def _fits(slot: Slot, rec: dict, p, cx: _Cx) -> list[tuple[str, float, tuple, str]]:
    """Selection-note and requirement terms of plan 6.1: (key, value, fields, reason)."""
    out = []
    name, kind, caps, trig = rec["name"], rec.get("kind"), _caps(rec), rec.get("triggers") or []
    add = out.append
    L = slot.layer
    if slot.id == "auth":
        mode = val(p, "requirements.auth")
        if mode in trig:
            add(("requirement_fit", SW["req_native"], ("requirements.auth",), f"{name} supports requirements.auth={mode}"))
        elif kind == "native" and mode == "enterprise_sso" and "enterprise_sso" in _caps(cx.backend or {}):
            add(("requirement_fit", SW["req_native"], ("requirements.auth",),
                 f"requirements.auth=enterprise_sso: {cx.backend['name']} has first-class OIDC/SAML middleware for {name}"))
        elif kind != "native":
            add(("requirement_fit", SW["req_poor"], ("requirements.auth",), f"{name} does not offer requirements.auth={mode}"))
        if val(p, "requirements.multi_tenant") and any(c in caps for c in ("organizations", "multi_tenancy")):
            add(("requirement_fit", SW["org_bonus"], ("requirements.multi_tenant",),
                 f"requirements.multi_tenant=true: {name} models tenant organisations"))
    elif L == "realtime":
        collab = "collaborative_editing" in cx.sig or val(p, "project.type") == "realtime_collab"
        if collab:
            f = "project.description" if "collaborative_editing" in cx.sig else "project.type"
            if kind == "crdt" or "strong_consistency" in caps:
                add(("requirement_fit", SW["req_native"], (f,), f"{name} merges concurrent edits (CRDT / single-writer objects)"))
            else:
                add(("requirement_fit", SW["fit_wrong"], (f,),
                     f"{name} only relays messages; concurrent edits to one document need conflict-free merging"))
        iot = val(p, "project.type") == "iot"
        if "mqtt" in caps and kind in ("mqtt_managed", "mqtt_broker"):
            add(("requirement_fit", SW["req_native"] if iot else SW["fit_wrong"], ("project.type",),
                 f"{name} is an MQTT device broker; project.type={val(p, 'project.type')}"))
        elif iot:
            add(("requirement_fit", SW["fit_wrong"], ("project.type",), f"project.type=iot needs MQTT; {name} is not a device broker"))
        if "audio_video" in caps:
            add(("requirement_fit", SW["fit_wrong"], ("requirements.realtime",), f"{name} is an audio/video server; no calls are requested"))
        if "realtime_builtin" in _caps(cx.backend or {}) and kind == "native":
            add(("selection_fit", SW["fit_good"], ("requirements.realtime",), f"{cx.backend['name']} has realtime channels built in"))
        if rec["id"] == "azure_signalr_service" and cx.backend_id == "aspnet_core" and _size_ge(p, SW["signalr_service_min_size"]):
            add(("selection_fit", SW["fit_good"], _size_fields(p), f"ASP.NET Core SignalR scale-out at size {p.size}"))
    elif L == "cdn":
        if kind != "bundled" and cx.edge_host() and slot.id == "cdn":
            add(("selection_fit", SW["fit_bad"], ("project.platforms",),
                 f"the host {cx.host_names()} already serves pages from its own edge network; {name} adds a second layer"))
    elif L == "storage":
        if "intermittent_connectivity" in cx.sig and "resumable_uploads_tus" in caps:
            add(("requirement_fit", SW["fit_small"], ("project.description",), f"{name} supports resumable uploads for intermittent connections"))
        if "kyc_documents" in cx.sig and any(c in caps for c in ("encryption_kms", "encryption_keys", "encryption_cmek", "immutable_storage")):
            add(("requirement_fit", SW["fit_small"], ("project.description",), f"{name} encrypts KYC documents with managed keys"))
    elif L == "cache":
        if kind == "serverless_kv" and cx.serverless_host():
            add(("selection_fit", SW["fit_good"], ("scale.traffic_pattern",), f"{name} has an HTTP API for serverless hosts without connection pools"))
        if "eventual_consistency" in caps:
            add(("requirement_fit", SW["fit_wrong"], ("requirements.p95_latency_ms",), f"{name} is eventually consistent (writes take up to 60 s), unfit for sessions and fan-out"))
    elif L == "queue":
        small = _size_le(p, SW["queue_db_max_size"]) or p.ops_capacity <= SW["queue_db_max_ops"]
        if kind == "db_backed" and small:
            add(("selection_fit", SW["fit_good"], _size_fields(p) + ("team.has_devops",),
                 f"size {p.size} / ops capacity {p.ops_capacity}: a database-backed queue reuses the database, no broker to run"))
        if kind == "managed" and set(rec.get("cloud_affinity") or ()) <= set(HYPERSCALERS) and _size_ge(p, SW["queue_managed_min_size"]):
            add(("selection_fit", SW["fit_good"], _size_fields(p), f"size {p.size}: {name} absorbs bursts without a broker to run"))
        if kind == "log":
            ok = (_size_ge(p, SW["kafka_min_size"]) and p.ops_capacity >= SW["kafka_min_ops"]
                  and (val(p, "project.type") in ("data_analytics", "iot") or p.realtime_msgs_per_s > SW["kafka_min_msgs"]))
            if not ok:
                add(("overengineering", SW["overengineering"], _size_fields(p) + ("team.has_devops",),
                     f"{name} (event log) is justified only at size >= {SW['kafka_min_size']} with event streams or > "
                     f"{SW['kafka_min_msgs']:,} msgs/s and ops capacity >= {SW['kafka_min_ops']} (size {p.size}, ops {p.ops_capacity})"))
    elif L == "search":
        small = p.data_volume_gb <= SW["search_db_max_gb"] and _size_le(p, SW["search_db_max_size"])
        if kind == "db_native":
            add(("selection_fit", SW["fit_good"] if small else SW["fit_bad"], ("scale.data_volume_gb_12_months",) + _size_fields(p),
                 f"corpus {fmt(p.data_volume_gb)} GB at size {p.size}: database full-text search "
                 + ("is enough" if small else "will strain the primary database")))
        if kind == "engine" and not small:
            add(("selection_fit", SW["fit_good"], ("scale.data_volume_gb_12_months",) + _size_fields(p),
                 f"corpus {fmt(p.data_volume_gb)} GB at size {p.size}: a dedicated engine keeps search off the database"))
        if "scales_to_billions" in caps:
            add(("selection_fit", SW["fit_good"] if _size_ge(p, SW["search_cluster_min_size"]) else SW["fit_bad"], _size_fields(p),
                 f"{name} is a search cluster for size >= {SW['search_cluster_min_size']} (size {p.size})"))
        if "time_to_market" in trig and p.weight("time_to_market") >= SW["algolia_min_ttm"]:
            add(("selection_fit", SW["fit_good"], ("priorities.time_to_market",),
                 f"priorities.time_to_market={p.weight('time_to_market')}: hosted search ships fastest"))
    elif L == "payments" and slot.id == "payments":
        upi = "upi" in cx.sig
        if p.india or upi:
            f = ("project.description",) if upi and not p.india else ("infrastructure.data_residency", "compliance")
            if "india_payments" in trig:
                add(("requirement_fit", SW["india_gateway"], f, f"{name} settles INR with UPI, cards and netbanking for Indian customers"))
            if "invite_only_india" in caps:
                add(("requirement_fit", SW["india_invite_only"], f, f"{name} is invite-only for new Indian businesses"))
        if kind == "merchant_of_record":
            ok = (val(p, "project.type") == "saas_b2b" and (val(p, "team.size") or 0) <= SW["paddle_max_team"]
                  and val(p, "scale.geographic_spread") == "global")
            if ok:
                add(("selection_fit", SW["fit_good"], ("project.type", "team.size", "scale.geographic_spread"),
                     f"{name} is merchant of record: it files sales tax/VAT worldwide for a small B2B team"))
    elif slot.id == "ml":
        share = _supporting_share(p, cx)
        cheap = share < SW["onnx_max_share_usd"] or _size_le(p, SW["onnx_max_size"])
        if kind == "inference_library":
            add(("selection_fit", SW["fit_good"] if cheap else 0, ("budget.monthly_infra_usd",) + _size_fields(p),
                 f"supporting budget share USD {share:g} at size {p.size}: in-process inference costs nothing extra"))
        if kind == "managed_platform" and not cheap:
            add(("selection_fit", SW["fit_good"], ("budget.monthly_infra_usd",) + _size_fields(p),
                 f"supporting budget share USD {share:g} at size {p.size}: a managed endpoint scales the model separately"))
    elif slot.id == "ml.llm" and kind == "llm_serving" and not p.self_hosted_only:
        add(("selection_fit", SW["fit_wrong"], ("infrastructure.deployment_model",),
             f"{name} needs GPU servers the team runs; deployment_model={p.deployment} allows a hosted model API"))
    elif slot.id == "ml.vector" and kind == "vector_store" and "no_extra_service" not in caps:
        big = _size_ge(p, SW["vector_cluster_min_size"])
        add(("selection_fit", SW["fit_good"] if big else SW["fit_bad"], _size_fields(p),
             f"{name} is a separate vector cluster, worth it at size >= {SW['vector_cluster_min_size']} (size {p.size})"))
    elif slot.id == "ci_cd":
        if kind == "bundled":
            small = (val(p, "team.size") or 0) <= SW["host_git_max_team"]
            add(("selection_fit", SW["fit_good"] if small else SW["fit_bad"], ("team.size",),
                 f"team.size={fmt(val(p, 'team.size'))}: host git deploys "
                 + ("need no pipeline" if small else "lack the test gates a larger team needs")))
        if "default" in trig:
            add(("selection_fit", SW["ci_default"], ("team.size",), f"{name} is the default hosted CI for git repositories"))
    elif slot.id == "ci_cd.mobile":
        if "react_native" in trig and cx.fe_ids & set(FRONTEND_REQUIREMENT.get(rec["id"], ())):
            add(("selection_fit", SW["fit_good"], ("project.platforms",), f"{name} builds and submits Expo apps without a Mac"))
    elif L == "observability":
        if rec["id"] == "datadog" and not ((val(p, "budget.monthly_infra_usd") or 0) >= SW["datadog_min_budget"]
                                           and _size_ge(p, SW["datadog_min_size"])):
            add(("overengineering", SW["overengineering"], ("budget.monthly_infra_usd",) + _size_fields(p),
                 f"{name} is used only at budget >= USD {SW['datadog_min_budget']:,} and size >= {SW['datadog_min_size']}"))
        small = _size_le(p, SW["small_stack_max_size"]) and not p.cloud_explicit
        if "small_team" in trig and small:
            add(("selection_fit", SW["fit_small"], _size_fields(p), f"size {p.size} on independent hosts: {name} needs no setup"))
    elif slot.id == "other.sms":
        if p.india and "dlt_templates" in caps:
            add(("requirement_fit", SW["dlt_sms"], ("infrastructure.data_residency", "compliance"),
                 f"{name} supports TRAI DLT sender/template registration for Indian SMS"))
    # deployment tags (on-premise / air-gapped / open-source-only fits)
    tags = []
    if p.air_gapped and "air_gapped" in trig:
        tags.append(("infrastructure.deployment_model", "deployment_model=air_gapped"))
    elif p.self_hosted_only and ("on_premise" in trig or (_in_process(rec) and rec.get("self_hostable"))):
        tags.append(("infrastructure.deployment_model", f"deployment_model={p.deployment}"))
    if val(p, "infrastructure.open_source_only") and "open_source_only" in trig:
        tags.append(("infrastructure.open_source_only", "open_source_only=true"))
    if tags:
        add(("deployment_fit", SW["deployment_tag"], tuple(f for f, _ in tags),
             f"{name} is built for {' and '.join(t for _, t in tags)}"))
    return out


def _supporting_share(p, cx) -> float:
    budget = val(p, "budget.monthly_infra_usd", 0) or 0
    return round(budget * _scoring.W["budget_share"]["supporting"] / max(1, cx.n_layers), 2)


def _affinity(slot: Slot, rec: dict, p, cx: _Cx, bundle_available: bool) -> list:
    out = []
    name = rec["name"]
    prov = provider_of(rec)
    cloud_f = ("infrastructure.cloud_preference",)
    bundled = "bundled_with_backend" in _caps(rec)
    if bundled:
        out.append(("bundled", SW["bundled"], cloud_f, f"{name} comes with the chosen back end {cx.backend['name']}"))
    elif "bundled_with_host" in _caps(rec):
        out.append(("bundled", SW["bundled"], cloud_f, f"{name} is part of the host {cx.host_names()}"))
    elif slot.native_affinity and prov and prov in cx.host_families:
        out.append(("native", SW["native"], cloud_f, f"{name} is from the same provider ({prov}) as the host {cx.host_names()}"))
    hit = cx.reuse_hit(rec)
    if hit:
        out.append(("reuse", SW["reuse"], ("infrastructure.existing_systems",),
                    f"infrastructure.existing_systems includes '{hit}', which {name} reuses"))
    elif (bundle_available and rec.get("saas") and not bundled and not rec.get("self_hostable")
          and "bundled_with_host" not in _caps(rec)
          and (prov is None or prov not in cx.stack_providers)):
        out.append(("new_vendor", SW["new_vendor"], cloud_f,
                    f"{name} adds a new vendor although an option bundled with the stack passes"))
    return out


def _band_of(rec: dict, p) -> tuple[float, float] | None:
    """KB band at the profile size used by the slot budget term (in-app-compute kinds cost 0, plan 7)."""
    if rec.get("kind") in COST_IN_APP_COMPUTE_KINDS:
        return 0.0, 0.0
    got = _costs.band_for(rec.get("cost") or {}, p.size)
    return None if got is None else (got[0], got[1])


def slot_floors(recs: list[dict], p) -> tuple[float, float]:
    """(cheapest mid, cheapest min) among a slot's compatible options at the profile size: the budget
    term never compares an option with less than the cheapest way to meet the same need."""
    bands = [b for b in (_band_of(r, p) for r in recs) if b is not None]
    if not bands:
        return 0.0, 0.0
    return min((lo + hi) / 2 for lo, hi in bands), min(lo for lo, _ in bands)


def _budget_term(rec: dict, p, cx: _Cx, floors: tuple[float, float], layer: str) -> Contribution | None:
    band = _band_of(rec, p)
    if band is None:
        return None
    lo, hi = band
    ctx = LayerContext(layer=layer, supporting_layers=cx.n_layers)
    min_share, min_budget = floors if SW["budget_relative"] else (0.0, 0.0)
    if lo == 0 and hi == 0 and min_budget == 0:
        min_share = 0.0
    got = _scoring.budget_fit_value(rec["name"], lo, hi, rec.get("free_tier") or {}, ctx.share(rec), p,
                                    min_share=min_share, min_budget=min_budget)
    if got is None:
        return None
    return _c("budget_fit", got[0], ("budget.monthly_infra_usd",) + _size_fields(p), got[1].rstrip("."))


def _score(slot: Slot, rec: dict, p, cx: _Cx, bundle_available: bool,
           floors: tuple[float, float] = (0.0, 0.0)) -> Scored:
    ctx = LayerContext(layer=slot.kb_layer, supporting_layers=cx.n_layers)
    base = _scoring.score(rec, p, ctx)
    contribs = [c for c in base.contributions if c.key in SCORE_KEYS and c.key != "budget_fit"]
    bt = _budget_term(rec, p, cx, floors, slot.kb_layer)
    if bt is not None:
        contribs.append(bt)
    terms = _affinity(slot, rec, p, cx, bundle_available) + _fits(slot, rec, p, cx)
    agg: dict[str, list] = {}
    for key, v, fields, reason in terms:
        agg.setdefault(key, []).append((v, fields, reason))
    for key in sorted(agg):
        parts = agg[key]
        v = sum(x for x, _, _ in parts)
        fields = []
        for _, fs, _ in parts:
            for f in fs:
                if f not in fields:
                    fields.append(f)
        c = _c(key, v, fields, "; ".join(r for x, _, r in parts if x) + ".")
        if c is not None:
            contribs.append(c)
    total = sum(c.value for c in contribs)
    return Scored(rec, total, tuple(contribs))


def _bundle_or_native(slot: Slot, rec: dict, cx: _Cx) -> bool:
    if "bundled_with_backend" in _caps(rec) or ("bundled_with_host" in _caps(rec)):
        return True
    prov = provider_of(rec)
    return bool(slot.native_affinity and prov and prov in cx.host_families)


# ================================================================== gaps
def _gap(slot: Slot, trig, p, rejected, incompatible) -> SupportingGap:
    fields = [f for f, _ in trig]
    why = "; ".join(t for _, t in trig)
    pick = sorted(list(rejected), key=lambda r: (-((kb.get(r.tech_id) or {}).get("attrs") or {}).get("popularity", 0), r.tech_id))[:2]
    pick_i = sorted(incompatible, key=lambda r: r.tech_id)[:max(0, 2 - len(pick))]
    reasons = [r.reason_text for r in pick] + [r.reason_text for r in pick_i]
    for r in pick:
        for f in r.fields:
            if f not in fields:
                fields.append(f)
    if p.air_gapped and (slot.id in INTERNET_NEEDS or any(r.rule == "F2" for r in rejected)):
        code = "AIRGAP_EXTERNAL_DEPENDENCY"
        if "infrastructure.deployment_model" not in fields:
            fields.insert(0, "infrastructure.deployment_model")
    elif (p.cloud_explicit and p.cloud and p.effective_residency != "none"
          and any(r.rule in ("F4", "F5") and p.cloud in ((kb.get(r.tech_id) or {}).get("cloud_affinity") or ())
                  for r in rejected)):
        code = "CLOUD_REGION_GAP"
    else:
        code = "SUPPORTING_GAP"
    severity = "critical" if code != "SUPPORTING_GAP" else slot.severity
    need = slot.id.replace("other.", "").replace("_", " ")
    msg = (f"A {need} service is needed ({why}) but no candidate satisfies the hard constraints and the chosen stack"
           + (": " + " ".join(reasons) if reasons else ".")
           + (f" It is left out; {slot.workaround}." if slot.workaround else " It is left out."))
    return SupportingGap(slot=slot.id, layer=slot.layer, triggers=tuple(trig), code=code, severity=severity,
                         message=msg, fields=tuple(fields), rejected=tuple(rejected),
                         incompatible=tuple(incompatible), workaround=slot.workaround)


def _soften_gap(gap: SupportingGap, cx: _Cx) -> SupportingGap:
    """An SMS gap is a warning, not critical, when the chosen auth service offers a sign-in that needs no
    SMS (:data:`SMS_FALLBACK_MODES`): the stack still works with that sign-in until a compliant SMS
    provider is verified. Other codes (air-gap, cloud-region) keep their severity."""
    if gap.slot != SMS_GAP_SLOT or gap.code != "SUPPORTING_GAP" or gap.severity != "critical":
        return gap
    auth = cx.chosen.get("auth")
    if not auth:
        return gap
    modes = sorted(set(auth.get("triggers") or ()) & set(SMS_FALLBACK_MODES)) + sorted(
        set(_caps(auth)) & set(SMS_FALLBACK_CAPS))
    if not modes:
        return gap
    msg = (gap.message + f" Severity is warning because the chosen auth service {auth['name']} also supports "
           f"{', '.join(m.replace('_', ' ') for m in modes)} sign-in, so users can still sign in.")
    return replace(gap, severity=SW["sms_gap_with_fallback"], message=msg)


# ================================================================== select
def _eval_slot(slot: Slot, trig, p, cx: _Cx):
    pool = [r for r in kb.by_layer(slot.kb_layer)
            if (slot.kinds is None or r.get("kind") in slot.kinds) and r.get("kind") not in slot.exclude_kinds]
    kept, rejected = filters.apply_hard(pool, p, slot.kb_layer, hosts=list(cx.hosts) or None)
    ok, incompatible = [], []
    for rec in kept:
        bad = _compat(slot, rec, p, cx)
        if bad is None:
            ok.append(rec)
        else:
            incompatible.append(Incompatible(rec["id"], rec["name"], slot.layer, bad[0], tuple(bad[1])))
    if not ok:
        return None, _gap(slot, trig, p, rejected, incompatible)
    bundle_available = any(_bundle_or_native(slot, r, cx) for r in ok)
    floors = slot_floors(ok, p)
    ranked = sorted((_score(slot, r, p, cx, bundle_available, floors) for r in ok),
                    key=lambda s: (-round(s.total, 4), s.tech["id"]))
    return Selection(slot=slot.id, layer=slot.layer, chosen=ranked[0], ranked=tuple(ranked),
                     rejected=tuple(rejected), incompatible=tuple(incompatible), triggers=tuple(trig)), None


def select(p, core, *, needs_managed_realtime: bool = False) -> SupportingResult:
    """Choose the supporting services for profile ``p`` and the chosen core stack (plan 6.1)."""
    cx = _Cx(p, CoreStack.of(core), needs_managed_realtime)
    # pre-pass: triggered layers share the supporting budget (dependent cache triggers counted later)
    pre = {s.layer for s in SLOTS if s.trigger(p, cx)}
    cx.n_layers = max(1, len(pre))
    selections, gaps, skipped, asm = [], [], [], []
    for slot in SLOTS:
        trig = slot.trigger(p, cx)
        if not trig:
            skipped.append((slot.id, slot.layer, f"not needed: none of [{slot.when}] holds"))
            continue
        sel, gap = _eval_slot(slot, trig, p, cx)
        if sel is not None:
            selections.append(sel)
            cx.chosen[slot.id] = sel.tech
        else:
            gaps.append(_soften_gap(gap, cx))
    if "web" in p.clients and p.air_gapped:
        asm.append("No CDN: infrastructure.deployment_model=air_gapped has no route to a public edge network.")
    if not cx.has_backend() and cx.nonempty():
        asm.append("No observability service: a static site has no server to monitor; the host's analytics cover traffic.")
    order = {l: i for i, l in enumerate(OUTPUT_LAYER_ORDER)}
    slot_pos = {s.id: i for i, s in enumerate(SLOTS)}
    selections.sort(key=lambda s: (order[s.layer], s.tech["name"] if s.layer == "other" else "", slot_pos[s.slot]))
    gaps.sort(key=lambda g: (order[g.layer], slot_pos[g.slot]))
    return SupportingResult(selections=tuple(selections), gaps=tuple(gaps), skipped=tuple(skipped),
                            assumptions=tuple(asm), needs_managed_realtime=bool(needs_managed_realtime))


# ================================================================== cost lines (plan 7)
def _storage_rate_key(rec) -> str | None:
    prov = provider_of(rec)
    if rec["id"] == "cloudflare_r2":
        return "r2"
    if rec["id"] == "do_spaces":
        return "spaces"
    if prov in HYPERSCALERS or rec["id"] == "supabase_storage":
        return "hyperscaler"
    return None


def cost_lines(result: SupportingResult, p) -> list[CostLine]:
    """``cost.CostLine`` objects for the selected services, in output order (for ``extra_lines``)."""
    lines: list[CostLine] = []
    users = p.users
    for s in result.selections:
        rec, slot = s.tech, s.layer
        self_op = bool(rec.get("self_hostable")) and not rec.get("saas") and p.self_hosted_only
        if self_op:
            lines.append(CostLine(slot=slot, component_id=rec["id"], name=rec["name"], min=0, max=0,
                                  basis="runs on the self-operated servers counted in the hardware estimate",
                                  source_keys=(), role="service"))
            continue
        if s.slot == "storage" and _storage_rate_key(rec):
            key = _storage_rate_key(rec)
            gb = round(p.data_volume_gb * _costs.MEDIA_SHARE_OF_DATA, 2)
            lo_r, hi_r = _costs.OBJECT_STORAGE_RATE_GB_MONTH[key]
            floor = _costs.OBJECT_STORAGE_MINIMUM.get(key, 0)
            lo, hi = max(floor, round(gb * lo_r, 2)), max(floor, round(gb * hi_r, 2))
            lines.append(CostLine(slot=slot, component_id=rec["id"], name=rec["name"], min=lo, max=hi,
                                  basis=(f"usage: {fmt(gb)} GB stored ({fmt(_costs.MEDIA_SHARE_OF_DATA)} x data volume "
                                         f"{fmt(p.data_volume_gb)} GB) x USD {lo_r:g}-{hi_r:g}/GB-month"
                                         + (f", minimum USD {floor}" if floor else "")),
                                  source_keys=tuple(sorted(k for k in rec.get("sources", ()) if "pricing" in k)) or tuple(rec.get("sources", ())),
                                  role="usage"))
            continue
        if s.slot == "other.sms":
            msgs = users * _costs.SMS_PER_USER_MONTH
            lo_r, hi_r = _costs.SMS_RATE_INDIA if p.india else _costs.SMS_RATE_OTHER
            lines.append(CostLine(slot=slot, component_id=rec["id"], name=rec["name"],
                                  min=round(msgs * lo_r, 2), max=round(msgs * hi_r, 2),
                                  basis=(f"usage: {msgs:,} SMS/month ({_costs.SMS_PER_USER_MONTH} per user x {users:,} users) x "
                                         f"USD {lo_r:g}-{hi_r:g} per message ({'India DLT route' if p.india else 'international'})"),
                                  source_keys=tuple(rec.get("sources", ())), role="usage"))
            continue
        if rec.get("kind") in COST_IN_APP_COMPUTE_KINDS:
            lines.append(CostLine(slot=slot, component_id=rec["id"], name=rec["name"], min=0, max=0,
                                  basis="runs inside the back-end process: its compute is the host's line (plan 7: "
                                        "in-process ONNX costs 0, uses app compute)",
                                  source_keys=(), role="service"))
            continue
        if "bundled_with_backend" in _caps(rec):
            lines.append(CostLine(slot=slot, component_id=rec["id"], name=rec["name"], min=0, max=0,
                                  basis="included in the back end's plan (counted on the back-end line)",
                                  source_keys=(), role="service"))
            continue
        lines.append(band_line(rec, p.size, slot, "service"))
    return lines


__all__ = ["SW", "SCORE_KEYS", "SLOTS", "SLOT_BY_ID", "GAP_CODES", "CoreStack", "Incompatible", "Selection",
           "SupportingGap", "SupportingResult", "select", "cost_lines", "provider_of"]

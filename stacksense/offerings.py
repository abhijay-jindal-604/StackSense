"""Managed-offering resolver (plan sections 3.10, 4.4 and 5.4 rules C3/C7).

Turns an ``(engine, host)`` pair into the concrete product and region, for example
``postgres`` + ``aws_ecs_fargate`` + data_residency india -> "Amazon RDS for PostgreSQL 17 (Multi-AZ,
ap-south-1)". Offering records live in :mod:`stacksense.kb.offerings`; every offering returned here
passed the same hard filters as its engine (``filters.viable_offerings`` / ``filters.check_offering``:
deployment, cloud, residency, compliance, open source), so a resolution never weakens a hard constraint.

Public API
----------
``provider_family(rec) -> str | None``
    Provider family of a hosting/backend record or an offering (``aws``, ``azure``, ``gcp``,
    ``digitalocean``, ``supabase``, ``cloudflare``, ``fly``, ``vercel``, ... ; ``onprem`` for
    customer-premises hosts).
``resolve(engine, host, p, *, require_family=None, needs_pooler=False) -> Resolved | NoOffering``
    ``engine``/``host``: KB record, ``Scored`` or id. ``host`` may be ``None`` (no application host).
    ``require_family``: only offerings on that provider (BaaS coupling, plan C5).
    ``needs_pooler``: the backend runs as functions, so the offering must name a connection pooler or
    data API (plan C7).
``Resolved``  frozen dataclass: ``engine_id, offering (dict | None), kind ('managed' | 'self_managed' |
    'in_host' | 'vendor' | 'none'), family, region, ha, display, same_provider, reasons, sources,
    alternatives`` (other viable offering ids, best first); ``choice(engine_name)`` and ``to_dict()``.
``NoOffering`` frozen dataclass: ``engine_id, host_id, host_family, rule ('C3' | 'C5' | 'C7'), reason,
    fields, rejections (filters.Rejection tuple), nearest (offering ids that pass the hard filters but
    not this host)``; ``to_dict()``.

Rules (stated once)
-------------------
* Self-hosted deployments (self_hosted_cloud_vm, on_premise, air_gapped) resolve to the self-managed
  engine (``<engine>__self_hosted``) on a VM/container/Kubernetes/on-premise host.
* Managed cloud: an offering on the host's own provider is preferred; a cloud-agnostic database
  vendor (:data:`DBAAS_FAMILIES`, reached over TLS from any host) is next; an independent platform
  host (Vercel, Render, ...) may also use a hyperscaler offering of an **open-source** engine
  (RDS/Cloud SQL for PostgreSQL). A proprietary hyperscaler product (Azure SQL, DynamoDB, Firestore,
  Cosmos DB, BigQuery) is used only from a host on that same cloud. A hyperscaler host never uses
  another hyperscaler's database, and platform-bound offerings (:data:`PLATFORM_BOUND_FAMILIES`:
  Cloudflare D1, DigitalOcean, Fly.io) are used only from their own platform.
* Co-location under residency: when ``data_residency`` is india/eu/us, the application host must
  itself list a region in that jurisdiction (an on-premise host always qualifies); otherwise the
  application would process the data outside it and the pair fails C3 (e.g. Fly.io + india).
* An engine with no managed offering that is not SaaS (SQLite, TigerBeetle, ...) runs inside the
  application host and needs a host with persistent disks (:data:`IN_HOST_KINDS`).
* Ties: preference class, then the lower cost midpoint at the profile size, then the offering id.

Pure and deterministic: no clock, no randomness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import filters, kb
from .kb import bindings as _bindings
from .kb import costs as _costs

HYPERSCALERS = ("aws", "azure", "gcp")
DBAAS_FAMILIES = ("atlas", "aura", "clickhouse_cloud", "cockroach_cloud", "neon", "snowflake", "supabase")
PLATFORM_BOUND_FAMILIES = ("cloudflare", "digitalocean", "fly")
SELF_HOSTED_DEPLOYMENTS = filters.SELF_HOSTED_DEPLOYMENTS
ONPREM_KINDS = ("onprem", "hybrid_appliance")
# hosts that can run a self-managed database next to the app (persistent disks)
IN_HOST_KINDS = ("vm", "k8s", "onprem", "hybrid_appliance")
SELF_HOSTED_DB_KINDS = ("vm", "k8s", "container", "onprem", "hybrid_appliance")
# words in an offering's ha_options that name a connection pooler or data API (plan C7)
# ("Cloud SQL Auth Proxy" is an auth tunnel, not a pooler, so a bare "proxy" does not count)
POOLER_WORDS = ("pool", "rds proxy", "pgbouncer", "supavisor", "data api", "hyperdrive")
RESIDENCY_JURISDICTIONS = ("india", "eu", "us")
POOLED_ENGINE_KINDS = ("relational",)
# relational engines reached through a platform binding / HTTP API rather than TCP connections, so a
# connection pooler is irrelevant (plan C7 targets PostgreSQL/MySQL-style servers)
CONNECTIONLESS_ENGINES = ("cloudflare_d1",)
HA_AVAILABILITY = ("99.95", "99.99")

# binding keys (kb.regions / kb.compliance) that name a product rather than a provider
_FAMILY_ALIASES = {
    "fly_managed_postgres": "fly", "cloudflare_d1": "cloudflare", "firebase_auth": "gcp",
    "firebase_app_hosting": "gcp", "firestore": "gcp", "mongodb_atlas": "atlas", "aurora_postgres": "aws",
}

F_RES = "infrastructure.data_residency"
F_CLOUD = "infrastructure.cloud_preference"
F_DEPLOY = "infrastructure.deployment_model"


# ------------------------------------------------------------------ data types
@dataclass(frozen=True)
class Resolved:
    engine_id: str
    offering: dict | None
    kind: str                        # managed | self_managed | in_host | vendor | none
    family: str | None               # provider family of the offering
    region: str | None
    ha: str | None                   # HA option named when availability >= 99.95
    display: str                     # product suffix for stack.database.choice
    same_provider: bool
    reasons: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()

    ok = True

    def choice(self, engine_name: str) -> str:
        if self.kind == "none" or not self.display:
            return engine_name
        return f"{engine_name} ({self.display})"

    def to_dict(self) -> dict:
        return {"engine_id": self.engine_id, "offering_id": self.offering["id"] if self.offering else None,
                "kind": self.kind, "family": self.family, "region": self.region, "ha": self.ha,
                "display": self.display, "same_provider": self.same_provider, "reasons": list(self.reasons),
                "sources": list(self.sources), "alternatives": list(self.alternatives)}


@dataclass(frozen=True)
class NoOffering:
    engine_id: str
    host_id: str | None
    host_family: str | None
    rule: str                        # C3 (database on host), C5 (BaaS coupling), C7 (pooler)
    reason: str
    fields: tuple[str, ...] = ()
    rejections: tuple = ()           # filters.Rejection of the engine's offerings
    nearest: tuple[str, ...] = ()    # offerings that pass the hard filters but not with this host
    sources: tuple[str, ...] = ()

    ok = False

    def to_dict(self) -> dict:
        return {"engine_id": self.engine_id, "host_id": self.host_id, "host_family": self.host_family,
                "rule": self.rule, "reason": self.reason, "fields": list(self.fields),
                "rejections": [r.to_dict() for r in self.rejections], "nearest": list(self.nearest),
                "sources": list(self.sources)}


# ------------------------------------------------------------------ helpers
def _rec(x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, str):
        return kb.get(x)
    if isinstance(x, dict):
        return x
    tech = getattr(x, "tech", None)
    return tech if isinstance(tech, dict) else None


def provider_family(rec) -> str | None:
    """Provider family of a record or offering (see module docstring)."""
    rec = _rec(rec)
    if not rec:
        return None
    if "engine" in rec and "host" in rec:
        return rec["host"]
    aff = [c for c in (rec.get("cloud_affinity") or []) if c in HYPERSCALERS]
    if aff:
        return aff[0]
    if rec.get("kind") in ONPREM_KINDS:
        return "onprem"
    rk, ak = _bindings.BINDINGS.get(rec["id"], (None, None))
    for key in (rk, ak):
        if not key or key == "self_hosted":
            continue
        if key in _FAMILY_ALIASES:
            return _FAMILY_ALIASES[key]
        for h in HYPERSCALERS:
            if key == h or key.startswith(h + "_"):
                return h
        return key
    return rec["id"]


def _mid(off, size) -> float:
    got = _costs.band_for(dict(off.get("cost") or {}), size)
    if got is None:
        return float("inf")
    return (got[0] + got[1]) / 2


def _residency_regions(rec, p) -> list:
    r = p.effective_residency
    if r in ("none", "other"):
        return []
    return [i for i in (rec.get("regions") or {}).get(r, []) if i != "*"]


def host_region(host, p) -> str | None:
    """Region the application host runs in for this profile (None when residency is unconstrained)."""
    host = _rec(host)
    if not host:
        return None
    if host.get("kind") in ONPREM_KINDS:
        return "on premises"
    ids = _residency_regions(host, p)
    if not ids:
        if p.gdpr_eu_preference:
            eu = [i for i in (host.get("regions") or {}).get("eu", []) if i != "*"]
            return eu[0] if eu else None
        return None
    rk = _bindings.BINDINGS.get(host["id"], (None, None))[0]
    pref = p.region(rk) if rk else None
    return pref if pref in ids else ids[0]


def offering_region(off, p, host=None) -> str | None:
    """Region for an offering: the profile's preferred region of the provider, else the host's region
    when the offering lists it, else the first listed region of the residency. EU when gdpr prefers it."""
    if off.get("host") == "self_hosted":
        return host_region(host, p)
    ids = _residency_regions(off, p)
    if not ids:
        if p.effective_residency == "none" and p.gdpr_eu_preference:
            eu = [i for i in (off.get("regions") or {}).get("eu", []) if i != "*"]
            return eu[0] if eu else None
        return None
    rk = _bindings.BINDINGS.get(off["id"], (None, None))[0]
    pref = p.region(rk) if rk else None
    if pref in ids:
        return pref
    hr = host_region(host, p)
    if hr in ids:
        return hr
    pref = p.region(off["host"])
    return pref if pref in ids else ids[0]


def has_pooler(off) -> bool:
    text = " ".join(off.get("ha_options") or ()).lower()
    return any(w in text for w in POOLER_WORDS)


def _needs_pool(eng) -> bool:
    return eng.get("kind") in POOLED_ENGINE_KINDS and eng["id"] not in CONNECTIONLESS_ENGINES


def _ha(off, p) -> str | None:
    avail = filters._val(p, "requirements.availability")
    opts = off.get("ha_options") or []
    if str(avail) in HA_AVAILABILITY and opts and off.get("host") != "self_hosted":
        return opts[0]
    return None


def _ha_label(ha: str | None) -> str | None:
    if not ha:
        return None
    low = ha.lower()
    if "multi-az" in low:
        return "Multi-AZ"
    if "zone" in low:
        return "zone-redundant"
    return ha.split(" (")[0]


def _host_pref(off_family, host_family, host, open_engine: bool = True) -> int | None:
    """Preference class of using an offering family from a host family; None = incompatible (C3).
    ``open_engine``: the engine is open source (a hyperscaler's managed PostgreSQL may serve an
    independent host; a proprietary hyperscaler product may not)."""
    if host is None:
        if off_family in DBAAS_FAMILIES:
            return 0
        return 1 if (open_engine or off_family not in HYPERSCALERS) else None
    if off_family == host_family:
        return 0
    if off_family in DBAAS_FAMILIES:
        return 1
    if off_family in PLATFORM_BOUND_FAMILIES:
        return None
    if off_family in HYPERSCALERS:
        if host_family in HYPERSCALERS or host_family == "onprem" or not open_engine:
            return None
        return 2
    return None


def _why_incompatible(off_family, host_family, host_name, open_engine: bool = True) -> str:
    if off_family in PLATFORM_BOUND_FAMILIES:
        return f"it runs only inside {off_family}, not next to {host_name}"
    if off_family in HYPERSCALERS and host_family in HYPERSCALERS:
        return f"it is a {off_family} database and {host_name} runs on {host_family} (cross-cloud)"
    if off_family in HYPERSCALERS and not open_engine:
        return f"it is a proprietary {off_family} service, used only from hosts on {off_family}"
    return f"it is not reachable from {host_name}"


def _display(name: str, parts) -> str:
    """'<name> (<parts>)'; when the name already ends with a parenthesis the parts join inside it."""
    parts = [x for x in parts if x]
    if not parts:
        return name
    if name.endswith(")") and " (" in name:
        return name[:-1] + ", " + ", ".join(parts) + ")"
    return f"{name} ({', '.join(parts)})"


# ------------------------------------------------------------------ resolve
def resolve(engine, host, p, *, require_family: str | None = None, needs_pooler: bool = False):
    """Resolve the concrete database product and region for ``engine`` used from ``host``."""
    eng = _rec(engine)
    if eng is None:
        raise ValueError(f"unknown engine {engine!r}")
    h = _rec(host)
    hid = h["id"] if h else None
    hname = h["name"] if h else "the application"
    hfam = provider_family(h) if h else None
    eid = eng["id"]
    name = eng.get("name", eid)

    if eng.get("kind") == "none":
        return Resolved(eid, None, "none", None, None, None, "", True,
                        ("No database is needed.",), ())

    all_offs = sorted((o for o in kb.OFFERINGS if o["engine"] == eid), key=lambda o: o["id"])
    self_mode = p.deployment in SELF_HOSTED_DEPLOYMENTS

    # --- self-hosted deployments: the self-managed engine on the team's host
    if self_mode:
        if h is not None and h.get("kind") not in SELF_HOSTED_DB_KINDS:
            return NoOffering(eid, hid, hfam, "C3", f"{name} must be self-managed under deployment_model="
                              f"{p.deployment}, and {hname} is a {h.get('kind')} host that cannot run it.",
                              (F_DEPLOY,))
        offs = [o for o in filters.viable_offerings(eid, p) if o["host"] == "self_hosted"]
        off = offs[0] if offs else None
        if off is None:
            rej = filters.check(eng, p, "database")
            if rej is not None:
                return NoOffering(eid, hid, hfam, "C3", rej.reason_text, rej.fields, (rej,), (), rej.sources)
            off = None
        region = host_region(h, p)
        where = "on premises" if p.self_hosted_only else (f"on {hname}" if h else "on your own servers")
        disp = f"self-managed {where}" + (f", {region}" if region and region != "on premises" else "")
        reasons = (f"deployment_model={p.deployment}: {name} runs self-managed {where}, so residency and "
                   f"compliance follow the environment the team operates.",)
        return Resolved(eid, off, "self_managed", "self_hosted", region, None, disp, True, reasons,
                        tuple(sorted(off.get("sources", ()))) if off else tuple(sorted(eng.get("sources", ()))))

    managed = [o for o in all_offs if o["host"] != "self_hosted"]

    # --- engines with no managed offering
    if not managed:
        if eng.get("saas"):
            rej = filters.check(eng, p, "database")
            if rej is not None:
                return NoOffering(eid, hid, hfam, "C3", rej.reason_text, rej.fields, (rej,), (), rej.sources)
            fam = provider_family(eng)
            if require_family and fam != require_family:
                return NoOffering(eid, hid, hfam, "C5", f"{name} is not offered by {require_family}.", ())
            region = _residency_regions(eng, p)
            reg = region[0] if region else None
            return Resolved(eid, None, "vendor", fam, reg, None, f"vendor-managed{', ' + reg if reg else ''}",
                            fam == hfam, (f"{name} is operated by its vendor.",), tuple(sorted(eng.get("sources", ()))))
        if require_family:
            return NoOffering(eid, hid, hfam, "C5", f"{name} has no offering on {require_family}.", ())
        if h is not None and h.get("kind") not in IN_HOST_KINDS:
            return NoOffering(eid, hid, hfam, "C3", f"{name} has no managed offering, so it must run on the "
                              f"application host with a persistent disk; {hname} is a {h.get('kind')} host "
                              f"without one.", ())
        off = next((o for o in all_offs if o["host"] == "self_hosted"), None)
        region = host_region(h, p)
        disp = f"self-managed on {hname}" + (f", {region}" if region and region != "on premises" else "")
        return Resolved(eid, off, "in_host", provider_family(h) if h else None, region, None, disp, True,
                        (f"{name} has no managed offering; it runs on {hname}, whose own region and "
                         f"attestations satisfy the hard constraints.",),
                        tuple(sorted((off or eng).get("sources", ()))))

    # --- managed offerings
    viable = filters.viable_offerings(eid, p)
    rejections = tuple(r for r in (filters.check_offering(o, p) for o in managed) if r is not None)
    if not viable:
        why = " ".join(r.reason_text for r in rejections) or f"no managed {name} offering passes the hard filters."
        return NoOffering(eid, hid, hfam, "C3", f"No managed {name} offering passes: {why}",
                          tuple(sorted({f for r in rejections for f in r.fields})), rejections, (),
                          tuple(sorted({s for r in rejections for s in r.sources})))
    # co-location (C3): the application host must sit in the residency jurisdiction itself
    res = p.effective_residency
    if (h is not None and res in RESIDENCY_JURISDICTIONS and h.get("kind") not in ONPREM_KINDS
            and not _residency_regions(h, p)):
        rn = filters.RESIDENCY_NAMES.get(res, res)
        return NoOffering(eid, hid, hfam, "C3", f"{hname} has no {rn} region, so the application would "
                          f"process {name} data outside {rn}; violates data_residency={res}.",
                          (F_RES,), rejections, tuple(o["id"] for o in viable),
                          tuple(sorted(h.get("sources", ()))))
    open_engine = bool(eng.get("open_source"))
    ranked, dropped = [], []
    for o in viable:
        if require_family and o["host"] != require_family:
            dropped.append((o, "C5", f"the backend bundles its own database on {require_family}"))
            continue
        pref = _host_pref(o["host"], hfam, h, open_engine)
        if pref is None:
            dropped.append((o, "C3", _why_incompatible(o["host"], hfam, hname, open_engine)))
            continue
        if needs_pooler and _needs_pool(eng) and not has_pooler(o):
            dropped.append((o, "C7", f"it names no connection pooler or data API for function hosts"))
            continue
        ranked.append(((pref, _mid(o, p.size), o["id"]), o))
    if not ranked:
        rule = "C5" if require_family and all(d[1] == "C5" for d in dropped) else (
            "C7" if any(d[1] == "C7" for d in dropped) else "C3")
        detail = "; ".join(f"{o['name']}: {why}" for o, _, why in dropped)
        fields = (F_CLOUD, F_RES) if rule == "C3" else ()
        return NoOffering(eid, hid, hfam, rule, f"No {name} offering that passes the hard filters can be used "
                          f"with {hname} ({detail}).", fields, rejections, tuple(o["id"] for o, _, _ in dropped),
                          tuple(sorted({s for o, _, _ in dropped for s in o.get("sources", ())})))
    ranked.sort(key=lambda t: t[0])
    off = ranked[0][1]
    region = offering_region(off, p, h)
    ha = _ha(off, p)
    disp = _display(off["name"], (_ha_label(ha), region))
    same = off["host"] == hfam
    reasons = []
    if same:
        reasons.append(f"{off['name']} runs on the same provider as {hname}.")
    elif off["host"] in DBAAS_FAMILIES:
        reasons.append(f"{off['name']} is a cloud-agnostic managed database reachable from {hname}.")
    else:
        reasons.append(f"{off['name']} is used from {hname}, which has no database product of its own.")
    r = p.effective_residency
    if r != "none" and region:
        reasons.append(f"Runs in {region}, satisfying data_residency={r}.")
    if p.compliance:
        reasons.append(f"Its attestations pass compliance={','.join(p.compliance)}.")
    if ha:
        reasons.append(f"requirements.availability={filters._val(p, 'requirements.availability')} needs {ha}.")
    if needs_pooler and _needs_pool(eng) and has_pooler(off):
        reasons.append("Function hosts reach it through its connection pooler.")
    return Resolved(eid, off, "managed", off["host"], region, ha, disp, same, tuple(reasons),
                    tuple(sorted(off.get("sources", ()))), tuple(o["id"] for _, o in ranked[1:]))

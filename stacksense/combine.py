"""Combination search and compatibility (plan sections 3.9 and 5.4).

``search(ranked, p) -> ComboResult``

``ranked`` maps a core layer to its scored, hard-filtered candidates (``scoring.rank`` output, best
first): ``frontend_web``, ``frontend_mobile``, ``frontend_desktop``, ``frontend_game``, ``backend``,
``database``, ``hosting``. Missing or empty client layers mean "not needed"; empty ``backend``,
``database`` or ``hosting`` lists (or an empty list for a required client layer) make the search
infeasible for that layer.

Search
------
1. Primary client slot: ``frontend_game`` when given, else ``frontend_web`` when ``web`` is a client,
   else ``frontend_mobile``, else ``frontend_desktop``, else nothing (API only). The slot holds the
   client that is scored inside the combination (plan 5.4: "the mobile/desktop/game choice is scored in
   its place" when there is no web client).
2. Enumerate the top ``K`` (``T["K"]`` = 6) of primary-client x backend x database x hosting and drop
   every combination that breaks a hard compatibility rule (C1-C8 below); the reason is kept in
   ``rejected_pairs``. When nothing passes, ``K`` widens to the full lists; when still nothing passes,
   ``ComboResult.infeasible_pair`` names the layer pair that blocked the most combinations and the
   caller marks the result ``infeasible``.
3. ``combo_score = sum of the four layer scores + synergies + language penalty`` with
   ``language penalty = -0.75 * (distinct_languages - 1) * (1 if team.size <= 5 else 0.3)``.
4. Total order (tested): higher ``combo_score`` (4 decimals) -> fewer distinct languages -> lower cost
   midpoint (``cost.estimate``) -> lower total ``ops_burden`` -> lexicographic tuple of candidate ids.
5. The remaining client layers (mobile, desktop; web when a game engine is primary) are picked after the
   core search for the best combination and each runner-up, with ``shared_language``,
   ``one_codebase`` and ``web_reuse`` terms. Two single-platform native toolkits are joined when both
   ``android`` and ``ios`` are required and a native toolkit wins.

Hard compatibility rules (combination dropped; reason quotes the ids and inputs)
--------------------------------------------------------------------------------
C1 runtime on host     backend runtime must be listed by the host; a functions product
                       (``serverless_fn`` back end) runs only on a functions-capable host of its own
                       provider.
C2 long-lived conns    realtime needs a host with ``long_lived_conn`` (or a BaaS with built-in
                       realtime); a functions-only host is kept only when a managed realtime service
                       passes the hard filters, and the combination carries the flag
                       ``needs_managed_realtime`` (``supporting.py`` must honour it).
C3 database on host    ``offerings.resolve`` must find an offering (region, attestation, provider).
C4 frontend host       a web client needs a host that serves it (static files, or its SSR runtime);
                       backend ``None`` is allowed only when ``needs_backend`` is false.
C5 BaaS coupling       :data:`BAAS_COUPLING` (Supabase, Firebase, PocketBase, Appwrite, Shopify).
C6 frontend-backend    :data:`FRONTEND_NEEDS_BACKEND` / :data:`BACKEND_NEEDS_FRONTEND`.
C7 pooler              functions hosts with PostgreSQL/MySQL need a pooler in the offering.
C8 Kubernetes          ``scoring.k8s_allowed(p)`` (same constants as plan 6.2).

Every soft term is a :class:`~stacksense.scoring.Contribution` (key = synergy name) so ``explain.py``
can cite it. All weights and id tables live in :data:`T` (calibration changes only this table).

Pure and deterministic: no clock, no randomness, no set iteration without ``sorted()``.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, NamedTuple

from . import cost as _cost
from . import filters, offerings, scoring
from .scoring import Contribution, Scored

# ------------------------------------------------------------------ constants (one table)
T: dict[str, Any] = {
    "K": 6,                                   # top-K per layer before widening
    "runners_up": 5,
    # language-count penalty: -0.75 * (distinct - 1) * (1 if team.size <= 5 else 0.3)
    "lang_penalty": 0.75, "lang_penalty_full_max_team": 5, "lang_penalty_large_team_factor": 0.3,
    # combination synergies (each |value| <= SYNERGY_CAP)
    "synergy": {
        "framework_host": 1.5,            # Next.js on Vercel (FRAMEWORK_HOST_PAIRS)
        "ssg_static_host": 1.5,           # Astro/Hugo/Eleventy on a static host
        "backend_host": 1.5,              # ASP.NET Core on App Service (BACKEND_HOST_PAIRS)
        "blazor_aspnet": 1.5,             # Blazor with ASP.NET Core (one language)
        "jvm_containers": 1.0,            # Spring Boot on ECS/EKS (BACKEND_HOST_PAIRS_JVM)
        "batteries_postgres": 1.0,        # Django/Rails/Laravel with PostgreSQL
        "supabase_client": 1.0,           # Supabase with Next.js or React Native
        "workers_d1": 1.5,                # Workers with D1
        "same_cloud": 1.0,                # host and managed database on one provider
        "shared_language": 1.5,           # frontend and backend share a language (team.size <= 5)
        "bff_split": -1.0,                # SSR frontend + backend in another language (team.size <= 3)
        "managed_realtime": -1.0,         # functions-only host: realtime must be a managed service
    },
    "synergy_cap": 2.0,
    "shared_language_max_team": 5,
    "bff_split_max_team": 3,
    # client picks after the core search
    "client_shared_language": 2.0,
    "one_codebase": 2.5, "one_codebase_max_team": 6,
    "two_natives": -2.0, "two_natives_max_team": 3,
    "web_reuse": 1.0,
}

FRAMEWORK_HOST_PAIRS = {("nextjs", "vercel")}
SSG_KINDS = ("ssg",)
STATIC_HOST_KINDS = ("static_host",)
BACKEND_HOST_PAIRS = {("aspnet_core", "azure_app_service")}
BACKEND_HOST_PAIRS_JVM = {("spring_boot", "aws_ecs_fargate"), ("spring_boot", "amazon_eks")}
BATTERIES_BACKENDS = ("django", "laravel", "rails")
BATTERIES_DATABASES = ("postgres",)
SUPABASE_CLIENTS = ("nextjs", "react_native_expo")
WORKERS_PAIRS = {("cloudflare_workers_hono", "cloudflare_d1")}
REACT_WEB = ("nextjs", "react_router", "react_vite")
WEB_REUSE_MOBILE = ("react_native_expo",)

# C6: a frontend that needs a particular backend (id tuple) or backend kind
FRONTEND_NEEDS_BACKEND = {"blazor": ("aspnet_core",)}
SERVER_TEMPLATE_KINDS = ("server_templates",)        # need a framework backend
# C6: a backend that runs inside a particular frontend app (cap same_app_as_frontend)
BACKEND_NEEDS_FRONTEND = {"nextjs_api": ("nextjs",), "payload": ("nextjs",)}

# C5: backend-as-a-service coupling. host_ids: managed platform host(s); host_family: provider family
# of acceptable hosts; self_host_kinds: host kinds when the BaaS runs self-hosted; databases: allowed
# database records; db_family: offering family the database must come from (managed mode).
BAAS_COUPLING: dict[str, dict] = {
    "supabase": {"host_ids": ("supabase_cloud",), "self_host_kinds": filters.CONTAINER_HOST_KINDS,
                 "databases": ("postgres",), "db_family": "supabase",
                 "why": "Supabase is its own Postgres project on Supabase Cloud"},
    "firebase": {"host_family": "gcp", "databases": ("firestore",), "db_family": "gcp",
                 "why": "Firebase stores data in Cloud Firestore and deploys on Firebase/Google Cloud"},
    "pocketbase": {"self_host_kinds": filters.CONTAINER_HOST_KINDS, "databases": ("sqlite",),
                   "why": "PocketBase embeds SQLite and runs as one binary on a VM or container"},
    "appwrite": {"self_host_kinds": filters.CONTAINER_HOST_KINDS, "databases": ("none",),
                 "why": "Appwrite keeps its data in its own bundled database and runs on a VM or container"},
    "shopify": {"host_ids": ("shopify_hosted",), "databases": ("none",),
                "why": "Shopify is hosted by Shopify and manages its own data"},
}
FUNCTION_HOST_KINDS = ("serverless_fn", "static_host")
SERVER_HOST_KINDS = ("container", "k8s", "paas", "vm", "onprem", "hybrid_appliance")
REALTIME_TYPES = ("realtime_collab",)
CLIENT_LAYERS = ("frontend_web", "frontend_game", "frontend_mobile", "frontend_desktop")
MOBILE_PLATFORMS = ("android", "ios")
PLATFORM_LABEL = {"web": "web", "android": "Android", "ios": "iOS", "desktop": "desktop"}
NATIVE_KINDS = ("native",)
LAYER_PAIRS = (("frontend", "backend"), ("backend", "database"), ("backend", "hosting"),
               ("frontend", "hosting"), ("database", "hosting"))
RULE_NAMES = {"C1": "runtime on host", "C2": "long-lived connections", "C3": "database on host",
              "C4": "frontend needs a host", "C5": "BaaS coupling", "C6": "frontend-backend pairing",
              "C7": "serverless connection pooling", "C8": "Kubernetes threshold"}

F_REALTIME = "requirements.realtime"
F_TEAM = "team.size"
F_LANG = "team.languages"
F_PLAT = "project.platforms"


# ------------------------------------------------------------------ data types
class PairRejection(NamedTuple):
    """A rejected candidate pair: ``(a, b, reason)``; the reason starts with the rule code."""
    a: str
    b: str
    reason: str

    @property
    def rule(self) -> str:
        return self.reason.split(" ", 1)[0]


@dataclass(frozen=True)
class ClientPart:
    """One client sub-choice of the composite frontend."""
    layer: str
    platforms: tuple[str, ...]
    scored: Scored
    partner: Scored | None = None              # joined native toolkit for the other mobile platform
    partner_platforms: tuple[str, ...] = ()
    contributions: tuple[Contribution, ...] = ()

    @property
    def id(self) -> str:
        return self.scored.tech["id"] + (f"+{self.partner.tech['id']}" if self.partner else "")

    @property
    def total(self) -> float:
        return round(self.scored.total + sum(c.value for c in self.contributions), 2)

    @property
    def label(self) -> str:
        def one(s, plats):
            return f"{s.tech['name']} ({', '.join(PLATFORM_LABEL.get(x, x) for x in plats)})"
        if self.partner is not None:
            return one(self.scored, self.platforms) + " and " + one(self.partner, self.partner_platforms)
        return one(self.scored, self.platforms)

    def records(self) -> list[dict]:
        return [self.scored.tech] + ([self.partner.tech] if self.partner else [])

    def to_dict(self) -> dict:
        return {"layer": self.layer, "id": self.id, "label": self.label, "platforms": list(self.platforms),
                "score": round(self.scored.total, 2), "total": self.total,
                "partner": self.partner.tech["id"] if self.partner else None,
                "partner_platforms": list(self.partner_platforms),
                "contributions": [_c_dict(c) for c in self.contributions]}


@dataclass(frozen=True)
class Combo:
    frontend: ClientPart | None               # primary client slot (scored inside the combination)
    backend: Scored
    database: Scored
    hosting: Scored                           # host that runs the backend (or serves a static site)
    frontend_hosting: Scored | None           # host serving the web client (may equal hosting)
    database_offering: Any                    # offerings.Resolved
    synergies: tuple[Contribution, ...]
    languages: tuple[str, ...]                # distinct languages of primary client + backend
    layer_total: float
    score: float
    ops_burden: int
    cost_mid: float | None = None
    flags: tuple[str, ...] = ()
    clients: tuple[ClientPart, ...] = ()      # every client part, web first (filled after the search)

    # ---- identity
    @property
    def ids(self) -> tuple[str, ...]:
        return (self.frontend.id if self.frontend else "", self.backend.tech["id"], self.database.tech["id"],
                self.hosting.tech["id"], self.frontend_hosting.tech["id"] if self.frontend_hosting else "",
                _off_id(self.database_offering))

    @property
    def language_penalty(self) -> float:
        c = self.synergy("language_count")
        return c.value if c else 0.0

    def synergy(self, key: str) -> Contribution | None:
        return next((c for c in self.synergies if c.key == key), None)

    @property
    def parts(self) -> tuple[ClientPart, ...]:
        return self.clients or ((self.frontend,) if self.frontend else ())

    @property
    def frontend_label(self) -> str:
        """Composite ``stack.frontend.choice``: web first; a single web part is its plain name."""
        parts = self.parts
        if not parts:
            return "None"
        if len(parts) == 1 and parts[0].layer == "frontend_web" and parts[0].partner is None:
            return parts[0].scored.tech["name"]
        return " + ".join(pt.label for pt in parts)

    @property
    def separate_frontend_host(self) -> bool:
        return (self.frontend_hosting is not None
                and self.frontend_hosting.tech["id"] != self.hosting.tech["id"])

    def stack(self) -> dict:
        """Components mapping for ``cost.estimate`` / ``architecture.decide``."""
        out: dict[str, Any] = {
            "frontend": [r for pt in self.parts for r in pt.records()],
            "backend": self.backend, "database": self.database, "hosting": self.hosting,
            "database_offering": getattr(self.database_offering, "offering", None),
        }
        if self.separate_frontend_host:
            out["frontend_hosting"] = self.frontend_hosting
        return out

    def to_dict(self) -> dict:
        return {
            "ids": list(self.ids), "frontend": self.frontend_label,
            "parts": [pt.to_dict() for pt in self.parts],
            "backend": self.backend.tech["id"], "database": self.database.tech["id"],
            "hosting": self.hosting.tech["id"],
            "frontend_hosting": self.frontend_hosting.tech["id"] if self.frontend_hosting else None,
            "database_offering": self.database_offering.to_dict() if self.database_offering else None,
            "layer_total": round(self.layer_total, 2), "synergies": [_c_dict(c) for c in self.synergies],
            "languages": list(self.languages), "score": round(self.score, 2),
            "cost_mid": self.cost_mid, "ops_burden": self.ops_burden, "flags": list(self.flags),
        }


@dataclass(frozen=True)
class ComboResult:
    best: Combo | None
    runners_up: list[Combo]
    rejected_pairs: list[PairRejection]
    k: int                                     # K used (T["K"] or the widened size)
    widened: bool = False
    infeasible_pair: tuple[str, str] | None = None   # layer pair responsible when best is None
    infeasible_reason: str | None = None
    considered: int = 0                        # combinations enumerated
    passed: int = 0                            # combinations that passed every hard rule

    @property
    def feasible(self) -> bool:
        return self.best is not None

    def to_dict(self) -> dict:
        return {"best": self.best.to_dict() if self.best else None,
                "runners_up": [c.to_dict() for c in self.runners_up],
                "rejected_pairs": [list(r) for r in self.rejected_pairs], "k": self.k,
                "widened": self.widened,
                "infeasible_pair": list(self.infeasible_pair) if self.infeasible_pair else None,
                "infeasible_reason": self.infeasible_reason, "considered": self.considered,
                "passed": self.passed}


# ------------------------------------------------------------------ small helpers
def _c_dict(c: Contribution) -> dict:
    return {"key": c.key, "value": c.value, "fields": list(c.fields), "reason": c.reason}


def _off_id(res) -> str:
    off = getattr(res, "offering", None)
    return off["id"] if off else ""


def _id(s) -> str:
    return s.tech["id"] if s is not None else "none"


def _name(s) -> str:
    return s.tech["name"] if s is not None else "None"


def _kind(s) -> str | None:
    return s.tech.get("kind") if s is not None else None


def _caps(rec) -> list:
    return list(rec.get("caps") or ())


def _runtimes(host: dict) -> list:
    rt = host.get("runtime")
    out = set(host.get("platforms") or ())
    if isinstance(rt, (list, tuple)):
        out.update(rt)
    elif isinstance(rt, str):
        out.add(rt)
    return sorted(out)


def _team(p) -> int:
    return int(scoring.val(p, F_TEAM, 1) or 1)


def _realtime_needed(p) -> bool:
    return bool(scoring.val(p, F_REALTIME, False)) or scoring.val(p, "project.type") in REALTIME_TYPES


def _contrib(key: str, value: float, fields: Iterable[str], reason: str) -> Contribution:
    return Contribution(key, round(float(value), 2), tuple(fields), reason)


def _syn(key: str, fields: Iterable[str], reason: str) -> Contribution:
    v = T["synergy"][key]
    return _contrib(key, v, fields, f"{reason} ({'+' if v > 0 else ''}{scoring.fmt(v)}).")


# ------------------------------------------------------------------ client options
def _mobile_required(p) -> tuple[str, ...]:
    return tuple(c for c in p.clients if c in MOBILE_PLATFORMS)


def _client_options(layer: str, ranked: list[Scored], p) -> list[ClientPart]:
    """Candidate parts for a client layer in ranked order; joins two natives when both mobile
    platforms are required and a single-platform native toolkit is the candidate."""
    if layer == "frontend_web":
        return [ClientPart(layer, ("web",), s) for s in ranked]
    if layer == "frontend_desktop":
        return [ClientPart(layer, ("desktop",), s) for s in ranked]
    if layer == "frontend_game":
        return [ClientPart(layer, tuple(c for c in p.clients if c in (s.tech.get("platforms") or ()))
                           or tuple(p.clients), s) for s in ranked]
    req = _mobile_required(p) or MOBILE_PLATFORMS
    out = []
    for s in ranked:
        plats = tuple(x for x in req if x in (s.tech.get("platforms") or ()))
        if not plats:
            continue
        missing = tuple(x for x in req if x not in plats)
        if not missing:
            out.append(ClientPart(layer, plats, s))
            continue
        if _kind(s) not in NATIVE_KINDS:
            continue
        partner = next((o for o in ranked if _kind(o) in NATIVE_KINDS and o is not s
                        and all(x in (o.tech.get("platforms") or ()) for x in missing)), None)
        if partner is not None:
            out.append(ClientPart(layer, plats, s, partner, missing))
    return out


def _primary_layer(ranked: Mapping[str, list], p) -> str | None:
    if ranked.get("frontend_game"):
        return "frontend_game"
    if "web" in p.clients:
        return "frontend_web"
    if _mobile_required(p):
        return "frontend_mobile"
    if "desktop" in p.clients:
        return "frontend_desktop"
    return None


def _required_client_layers(ranked: Mapping[str, list], p) -> list[str]:
    out = []
    game = bool(ranked.get("frontend_game"))
    game_plats = set()
    if game:
        out.append("frontend_game")
        for s in ranked["frontend_game"]:
            game_plats.update(s.tech.get("platforms") or ())
    if "web" in p.clients and not (game and "web" in game_plats):
        out.append("frontend_web")
    if _mobile_required(p) and not (game and all(x in game_plats for x in _mobile_required(p))):
        out.append("frontend_mobile")
    if "desktop" in p.clients and not (game and "desktop" in game_plats):
        out.append("frontend_desktop")
    return sorted(out, key=CLIENT_LAYERS.index)


# ------------------------------------------------------------------ hard rules
def _rej(rule: str, text: str) -> tuple[str, str]:
    return rule, f"{rule} {RULE_NAMES[rule]}: {text}"


def check_frontend_backend(fe: ClientPart | None, be: Scored, p) -> tuple[str, str] | None:
    """C4 (backend None) and C6 (frontend-backend pairing)."""
    bid, bkind = _id(be), _kind(be)
    if bkind == "none" and p.needs_backend:
        return _rej("C4", f"backend None cannot serve the dynamic features this project needs "
                          f"({scoring._dynamic_text(p)}).")
    if fe is None:
        if bid in BACKEND_NEEDS_FRONTEND:
            return _rej("C6", f"{_name(be)} runs inside a {'/'.join(BACKEND_NEEDS_FRONTEND[bid])} app, and "
                              f"there is no web client (project.platforms={scoring.fmt(list(p.clients))}).")
        return None
    f = fe.scored
    fid, fkind = _id(f), _kind(f)
    if fid in FRONTEND_NEEDS_BACKEND and bid not in FRONTEND_NEEDS_BACKEND[fid]:
        need = ", ".join(scoring.fmt(x) for x in FRONTEND_NEEDS_BACKEND[fid])
        return _rej("C6", f"{_name(f)} needs the {need} backend; {_name(be)} is a different stack.")
    if fkind in SERVER_TEMPLATE_KINDS and bkind != "framework":
        return _rej("C6", f"{_name(f)} renders pages inside a server framework; {_name(be)} is "
                          f"{'no backend' if bkind == 'none' else 'a ' + str(bkind) + ' backend'}.")
    if bid in BACKEND_NEEDS_FRONTEND and fid not in BACKEND_NEEDS_FRONTEND[bid]:
        need = "/".join(BACKEND_NEEDS_FRONTEND[bid])
        return _rej("C6", f"{_name(be)} runs inside a {need} app; the web client is {_name(f)}.")
    return None


def check_backend_database(be: Scored, db: Scored, p) -> tuple[str, str] | None:
    """Backend None needs database None; C5 database part."""
    bid, dbid = _id(be), _id(db)
    if _kind(be) == "none" and _kind(db) != "none":
        return _rej("C4", f"backend None cannot reach a database ({_name(db)}); a static site has no "
                          f"server to query it.")
    c = BAAS_COUPLING.get(bid)
    if c and dbid not in c["databases"]:
        allowed = ", ".join(c["databases"])
        return _rej("C5", f"{c['why']}, so the database must be {allowed}, not {_name(db)}.")
    return None


def _managed_realtime_ids(p, be: Scored, host: Scored, cache: dict) -> list[str]:
    if "realtime" not in cache:
        kept, _ = filters.filter_layer("realtime", p)
        cache["realtime"] = [r for r in kept if r.get("saas") and "websocket" in _caps(r)]
    out = []
    hfam = offerings.provider_family(host.tech)
    for r in cache["realtime"]:
        caps = _caps(r)
        if "bundled_with_backend" in caps and _id(be) != "supabase":
            continue
        if "workers_native" in caps and hfam != "cloudflare":
            continue
        out.append(r["id"])
    return out


def check_backend_host(be: Scored, host: Scored, p, cache: dict) -> tuple[tuple[str, str] | None, tuple]:
    """C1, C2, C5 (host part), C8. Returns (rejection or None, flags)."""
    b, h = be.tech, host.tech
    bid, bkind, hkind = b["id"], b.get("kind"), h.get("kind")
    hname, bname = h["name"], b["name"]
    hrt = _runtimes(h)
    # C8
    if scoring._is_k8s(h) and not scoring.k8s_allowed(p):
        return _rej("C8", f"{hname} is Kubernetes, which needs operations capacity >= {scoring.K8S_MIN_OPS} "
                          f"(team has {p.ops_capacity}) and size >= {scoring.K8S_MIN_SIZE} (size {p.size}), "
                          f"or an on-premise team of >= {scoring.K8S_ONPREM_MIN_TEAM}."), ()
    # C5 / C1
    if bkind == "none":
        return None, ()
    coupling = BAAS_COUPLING.get(bid)
    if coupling is not None:
        self_mode = p.deployment in filters.SELF_HOSTED_DEPLOYMENTS and b.get("self_hostable")
        ok = False
        if self_mode or not coupling.get("host_ids") and not coupling.get("host_family"):
            ok = hkind in (coupling.get("self_host_kinds") or ())
            where = "a VM, container or Kubernetes host it can be self-hosted on"
        else:
            ok = (h["id"] in (coupling.get("host_ids") or ())
                  or (coupling.get("host_family") and offerings.provider_family(h) == coupling["host_family"]))
            where = " / ".join(coupling.get("host_ids") or ()) or f"a {coupling.get('host_family')} host"
        if not ok:
            return _rej("C5", f"{coupling['why']}; it needs {where}, not {hname}."), ()
    else:
        rt = b.get("runtime")
        if rt and rt not in hrt and not filters._runs_on(b, h):
            return _rej("C1", f"{hname} runs {', '.join(hrt) or 'nothing'}; {bname} needs {rt}."), ()
        if bkind == "serverless_fn":
            bfam, hfam = offerings.provider_family(b), offerings.provider_family(h)
            fn_host = hkind in FUNCTION_HOST_KINDS or "scale_to_zero" in _caps(h)
            if bfam != hfam or not fn_host:
                return _rej("C1", f"{bname} is a {bfam} functions product and deploys only to a functions "
                                  f"host of {bfam}; {hname} is a {hkind} host on {hfam}."), ()
    # C2
    flags: tuple = ()
    if _realtime_needed(p):
        bundled = bkind == "baas" and "realtime_builtin" in _caps(b)
        long_lived = "long_lived_conn" in _caps(h) and (bkind != "serverless_fn" or "long_lived_conn" in _caps(b))
        if not bundled and not long_lived:
            managed = _managed_realtime_ids(p, be, host, cache)
            if not managed:
                return _rej("C2", f"requirements.realtime={scoring.fmt(scoring.val(p, F_REALTIME))} needs "
                                  f"long-lived WebSocket connections; {hname} runs request-only functions "
                                  f"and no managed realtime service passes the hard filters."), ()
            flags = ("needs_managed_realtime",)
    return None, flags


def _serve_mode(fe: ClientPart, be: Scored, p) -> str | None:
    """'static', 'server', 'backend' (rendered by the backend) or None (client needs no web host)."""
    f = fe.scored.tech
    kind = f.get("kind")
    if fe.layer == "frontend_web":
        if kind in SERVER_TEMPLATE_KINDS:
            return "backend"
        if kind == "ssr":
            if _kind(be) == "none" and not p.needs_backend and "ssg" in _caps(f):
                return "static"
            return "server"
        return "static"
    if kind == "pwa" or (fe.layer == "frontend_game" and kind == "web_2d" and "web" in p.clients):
        return "static"
    return None


def _serves(host: dict, mode: str, fe: dict) -> bool:
    rts = _runtimes(host)
    if mode == "static":
        return "static" in rts
    if mode == "server":
        return bool(fe.get("runtime")) and fe["runtime"] in rts
    return True


def _fe_host_synergy(fe: dict, host: dict) -> float:
    s = 0.0
    if (fe["id"], host["id"]) in FRAMEWORK_HOST_PAIRS:
        s += T["synergy"]["framework_host"]
    if fe.get("kind") in SSG_KINDS and host.get("kind") in STATIC_HOST_KINDS:
        s += T["synergy"]["ssg_static_host"]
    return s


def choose_frontend_host(fe: ClientPart | None, be: Scored, host: Scored, hosts: list[Scored], p
                         ) -> tuple[Scored | None, tuple[str, str] | None]:
    """The host that serves the web client (C4), in this order: the application host when it serves
    the client directly; a host of the same provider (dedicated static hosts first for static
    clients); the application server itself for static assets; the best other host (static hosts
    first for static clients, then score + framework/host synergy, then id)."""
    if fe is None:
        return None, None
    mode = _serve_mode(fe, be, p)
    if mode is None:
        return None, None
    f, h = fe.scored.tech, host.tech
    if mode == "backend":
        return host, None
    if _kind(be) == "none":
        if _serves(h, mode, f):
            return host, None
        need = "static files" if mode == "static" else f"the {f.get('runtime')} server of {f['name']}"
        return None, _rej("C4", f"{h['name']} cannot serve {need} (it runs {', '.join(_runtimes(h))}).")
    if _serves(h, mode, f):
        return host, None
    hfam = offerings.provider_family(h)
    k8s_ok = scoring.k8s_allowed(p)
    cands = [s for s in hosts if _serves(s.tech, mode, f) and (k8s_ok or not scoring._is_k8s(s.tech))]

    def key(s):
        dedicated = 0 if (mode != "static" or s.tech.get("kind") in STATIC_HOST_KINDS) else 1
        return (dedicated, -round(s.total + _fe_host_synergy(f, s.tech), 4), s.tech["id"])

    same = sorted((s for s in cands if offerings.provider_family(s.tech) == hfam), key=key)
    if same and (mode != "static" or same[0].tech.get("kind") in STATIC_HOST_KINDS
                 or h.get("kind") not in SERVER_HOST_KINDS):
        return same[0], None
    if mode == "static" and h.get("kind") in SERVER_HOST_KINDS:
        return host, None          # the application server serves the built assets
    if cands:
        return sorted(cands, key=key)[0], None
    need = "static files" if mode == "static" else f"a {f.get('runtime')} server for {f['name']}"
    return None, _rej("C4", f"no host that passed the hard filters can serve {need} next to {h['name']}.")


def _needs_pooler(be: Scored, host: Scored) -> bool:
    if _kind(be) in ("baas", "commerce_saas", "none"):
        return False
    return _kind(be) == "serverless_fn" or host.tech.get("kind") in FUNCTION_HOST_KINDS


def resolve_database(be: Scored, db: Scored, host: Scored, p, cache: dict):
    """C3/C5/C7 through ``offerings.resolve``; cached per (engine, host, family, pooler)."""
    coupling = BAAS_COUPLING.get(_id(be)) or {}
    fam = coupling.get("db_family")
    pool = _needs_pooler(be, host)
    key = ("off", _id(db), _id(host), fam, pool)
    if key not in cache:
        cache[key] = offerings.resolve(db.tech, host.tech, p, require_family=fam, needs_pooler=pool)
    return cache[key]


# ------------------------------------------------------------------ soft terms
def _lang_options(rec: dict | None) -> tuple[str, ...]:
    if not rec:
        return ()
    return tuple(sorted(rec.get("languages") or ()))


def choose_languages(recs: list[dict | None], p) -> tuple[str, ...]:
    """Fewest distinct languages over the components' language options; ties: more team-known
    languages, then lexicographic."""
    opts = [o for o in (_lang_options(r) for r in recs) if o]
    if not opts:
        return ()
    team = set(p.languages)
    best = None
    for pick in itertools.product(*opts):
        langs = tuple(sorted(set(pick)))
        key = (len(langs), -sum(1 for x in langs if x in team), langs)
        if best is None or key < best[0]:
            best = (key, langs)
    return best[1]


def language_penalty(langs: tuple[str, ...], p) -> Contribution | None:
    n = len(langs)
    if n <= 1:
        return None
    team = _team(p)
    factor = 1.0 if team <= T["lang_penalty_full_max_team"] else T["lang_penalty_large_team_factor"]
    v = round(-T["lang_penalty"] * (n - 1) * factor, 2)
    if not v:
        return None
    return _contrib("language_count", v, (F_TEAM, F_LANG),
                    f"{n} languages ({', '.join(langs)}) for team.size={team} "
                    f"({scoring.fmt(v)}: -{scoring.fmt(T['lang_penalty'])} per extra language"
                    + ("" if factor == 1 else f" x {scoring.fmt(factor)} for a team above "
                                              f"{T['lang_penalty_full_max_team']}") + ").")


def synergies(fe: ClientPart | None, be: Scored, db: Scored, host: Scored, fe_host: Scored | None,
              res, p, flags: tuple = ()) -> list[Contribution]:
    """Named combination terms of plan 5.4 (each within +-T['synergy_cap'])."""
    out: list[Contribution] = []
    f = fe.scored.tech if fe else None
    b, d, h = be.tech, db.tech, host.tech
    fh = fe_host.tech if fe_host else None
    team = _team(p)
    if f and fh and (f["id"], fh["id"]) in FRAMEWORK_HOST_PAIRS:
        out.append(_syn("framework_host", (), f"{f['name']} deploys natively on {fh['name']}"))
    if f and fh and f.get("kind") in SSG_KINDS and fh.get("kind") in STATIC_HOST_KINDS:
        out.append(_syn("ssg_static_host", (), f"{f['name']} builds static pages that {fh['name']} "
                                               f"serves from its edge network"))
    if (b["id"], h["id"]) in BACKEND_HOST_PAIRS:
        out.append(_syn("backend_host", (), f"{b['name']} is a first-class runtime on {h['name']}"))
    if f and f["id"] in FRONTEND_NEEDS_BACKEND and b["id"] in FRONTEND_NEEDS_BACKEND[f["id"]]:
        out.append(_syn("blazor_aspnet", (), f"{f['name']} and {b['name']} are one .NET codebase in C#"))
    if (b["id"], h["id"]) in BACKEND_HOST_PAIRS_JVM:
        out.append(_syn("jvm_containers", (), f"{b['name']} runs as long-lived JVM containers on {h['name']}"))
    if b["id"] in BATTERIES_BACKENDS and d["id"] in BATTERIES_DATABASES:
        out.append(_syn("batteries_postgres", (), f"{b['name']} has first-class {d['name']} support "
                                                  f"(migrations, full-text search, JSON fields)"))
    if b["id"] == "supabase" and f and f["id"] in SUPABASE_CLIENTS:
        out.append(_syn("supabase_client", (), f"Supabase ships a maintained client and auth helpers "
                                               f"for {f['name']}"))
    if (b["id"], d["id"]) in WORKERS_PAIRS:
        out.append(_syn("workers_d1", (), f"{d['name']} is bound directly to {b['name']} with no "
                                          f"connection management"))
    off_fam = getattr(res, "family", None)
    if getattr(res, "kind", None) == "managed" and off_fam and off_fam == offerings.provider_family(h):
        fields = ("infrastructure.cloud_preference",) if p.cloud_explicit else ()
        out.append(_syn("same_cloud", fields, f"{getattr(res, 'display', d['name'])} and {h['name']} are on "
                                              f"one provider ({off_fam}): one bill, private networking"))
    fl, bl = set(_lang_options(f)), set(_lang_options(b))
    if f and b.get("kind") != "none" and fl and bl:
        shared = sorted(fl & bl)
        if shared and team <= T["shared_language_max_team"]:
            out.append(_syn("shared_language", (F_TEAM, F_LANG),
                            f"{f['name']} and {b['name']} share {', '.join(shared)}, so team.size={team} "
                            f"works in one language"))
        if (not shared and f.get("kind") == "ssr" and b.get("kind") == "framework"
                and team <= T["bff_split_max_team"]):
            out.append(_syn("bff_split", (F_TEAM,),
                            f"{f['name']} ({', '.join(sorted(fl))}) runs its own server next to {b['name']} "
                            f"({', '.join(sorted(bl))}); two server codebases for team.size={team}"))
    if "needs_managed_realtime" in flags:
        out.append(_syn("managed_realtime", (F_REALTIME,),
                        f"{h['name']} runs request-only functions, so requirements.realtime=true needs a "
                        f"separate managed realtime service"))
    return out


# ------------------------------------------------------------------ client picks after the core
def codebase_terms(part: ClientPart, p) -> list[Contribution]:
    """one_codebase (+2.5 cross-platform for android+ios at team.size <= 6) or two natives (-2 at
    team.size <= 3)."""
    out = []
    s = part.scored.tech
    team = _team(p)
    if part.layer == "frontend_mobile" and all(x in p.clients for x in MOBILE_PLATFORMS):
        if part.partner is None and len(part.platforms) >= 2 and team <= T["one_codebase_max_team"]:
            out.append(_contrib("one_codebase", T["one_codebase"], (F_PLAT, F_TEAM),
                                f"{s['name']} covers android and ios from one codebase for team.size={team} "
                                f"(+{scoring.fmt(T['one_codebase'])})."))
        if part.partner is not None and team <= T["two_natives_max_team"]:
            out.append(_contrib("one_codebase", T["two_natives"], (F_PLAT, F_TEAM),
                                f"two native apps ({s['name']} and {part.partner.tech['name']}) for "
                                f"team.size={team} ({scoring.fmt(T['two_natives'])})."))
    return out


def client_terms(part: ClientPart, combo: Combo, p) -> tuple[Contribution, ...]:
    """shared_language, one_codebase/two_natives and web_reuse for a client picked after the core."""
    out = []
    s = part.scored.tech
    team = _team(p)
    others = []
    if combo.frontend is not None and combo.frontend.layer != part.layer:
        others.append(combo.frontend.scored.tech)
    if combo.backend.tech.get("kind") != "none":
        others.append(combo.backend.tech)
    mine = set(_lang_options(s)) | (set(_lang_options(part.partner.tech)) if part.partner else set())
    shared = sorted({x for o in others for x in _lang_options(o)} & mine)
    if shared:
        names = " / ".join(o["name"] for o in others)
        out.append(_contrib("shared_language", T["client_shared_language"], (F_LANG,),
                            f"{s['name']} shares {', '.join(shared)} with {names} "
                            f"(+{scoring.fmt(T['client_shared_language'])})."))
    out.extend(codebase_terms(part, p))
    web = next((pt for pt in combo.parts if pt.layer == "frontend_web"), None)
    if (part.layer == "frontend_mobile" and s["id"] in WEB_REUSE_MOBILE and web is not None
            and web.scored.tech["id"] in REACT_WEB):
        out.append(_contrib("web_reuse", T["web_reuse"], (F_PLAT,),
                            f"{s['name']} reuses React components and skills from {web.scored.tech['name']} "
                            f"(+{scoring.fmt(T['web_reuse'])})."))
    return tuple(out)


def pick_clients(combo: Combo, ranked: Mapping[str, list], p) -> Combo:
    """Add the remaining client layers to ``combo`` (plan 5.4, after the core search)."""
    parts = [combo.frontend] if combo.frontend else []
    if combo.frontend is not None:
        # the primary was scored inside the combination; its codebase terms are already synergies
        parts = [replace(combo.frontend, contributions=tuple(codebase_terms(combo.frontend, p)))]
    for layer in _required_client_layers(ranked, p):
        if combo.frontend is not None and layer == combo.frontend.layer:
            continue
        opts = _client_options(layer, list(ranked.get(layer) or ()), p)
        scored = []
        for o in opts:
            o2 = replace(o, contributions=client_terms(o, combo, p))
            scored.append(o2)
        if not scored:
            continue
        scored.sort(key=lambda o: (-round(o.total, 4), o.id))
        parts.append(scored[0])
    parts.sort(key=lambda pt: CLIENT_LAYERS.index(pt.layer))
    return replace(combo, clients=tuple(parts))


# ------------------------------------------------------------------ the search
def _cost_mid(combo: Combo, p) -> float:
    c = _cost.estimate(p, combo.stack())
    return (c.min + c.max) / 2


def _ops(be, db, host, fe_host) -> int:
    seen, total = set(), 0
    for s in (be, db, host, fe_host):
        if s is None or s.tech["id"] in seen or s.tech.get("kind") == "none":
            continue
        seen.add(s.tech["id"])
        total += int(s.tech.get("ops_burden") or 0)
    return total


def _evaluate(fe, be, db, host, hosts, p, cache) -> tuple[Combo | None, tuple | None]:
    """One combination: (Combo, None) or (None, (layer_a, layer_b, a_id, b_id, reason))."""
    fid = fe.id if fe else "none"
    key = ("fb", fid, _id(be))
    if key not in cache:
        cache[key] = check_frontend_backend(fe, be, p)
    r = cache[key]
    if r:
        return None, ("frontend", "backend", fid, _id(be), r[1])
    key = ("bd", _id(be), _id(db))
    if key not in cache:
        cache[key] = check_backend_database(be, db, p)
    r = cache[key]
    if r:
        return None, ("backend", "database", _id(be), _id(db), r[1])
    key = ("bh", _id(be), _id(host))
    if key not in cache:
        cache[key] = check_backend_host(be, host, p, cache)
    r, flags = cache[key]
    if r:
        return None, ("backend", "hosting", _id(be), _id(host), r[1])
    key = ("fh", fid, _id(be), _id(host))
    if key not in cache:
        cache[key] = choose_frontend_host(fe, be, host, hosts, p)
    fe_host, r = cache[key]
    if r:
        return None, ("frontend", "hosting", fid, _id(host), r[1])
    res = resolve_database(be, db, host, p, cache)
    if not res.ok:
        return None, ("database", "hosting", _id(db), _id(host), f"{res.rule} {RULE_NAMES[res.rule]}: {res.reason}")
    langs = choose_languages([fe.scored.tech if fe else None, be.tech], p)
    syn = synergies(fe, be, db, host, fe_host, res, p, flags)
    if fe is not None:
        syn.extend(codebase_terms(fe, p))
    pen = language_penalty(langs, p)
    if pen is not None:
        syn.append(pen)
    layer_total = round((fe.scored.total if fe else 0.0) + be.total + db.total + host.total, 2)
    score = round(layer_total + sum(c.value for c in syn), 2)
    combo = Combo(fe, be, db, host, fe_host, res, tuple(syn), langs, layer_total, score,
                  _ops(be, db, host, fe_host), None, tuple(flags))
    return combo, None


def _order_key(c: Combo):
    return (-round(c.score, 4), len(c.languages), c.cost_mid if c.cost_mid is not None else 0.0,
            c.ops_burden, c.ids)


def _sort(combos: list[Combo], p) -> list[Combo]:
    """Total order of plan 5.4; the cost midpoint is computed only where score and language count tie."""
    combos = sorted(combos, key=lambda c: (-round(c.score, 4), len(c.languages), c.ids))
    out: list[Combo] = []
    for _, grp in itertools.groupby(combos, key=lambda c: (-round(c.score, 4), len(c.languages))):
        grp = list(grp)
        if len(grp) > 1:
            grp = [replace(c, cost_mid=_cost_mid(c, p)) for c in grp]
            grp.sort(key=_order_key)
        out.extend(grp)
    return out


def _enumerate(lists, hosts_all, p, cache, stats, rejected, blocked):
    fes, bes, dbs, hos = lists
    passed = []
    for fe in fes:
        for be in bes:
            for db in dbs:
                for host in hos:
                    stats["considered"] += 1
                    combo, rej = _evaluate(fe, be, db, host, hosts_all, p, cache)
                    if combo is not None:
                        passed.append(combo)
                        continue
                    la, lb, a, b, reason = rej
                    rejected.setdefault((a, b, reason), None)
                    entry = blocked.setdefault((la, lb), [0, reason])
                    entry[0] += 1
    return passed


def search(ranked: Mapping[str, list[Scored]], p, *, k: int | None = None) -> ComboResult:
    """Best combination, top-5 runners-up and rejected pairs (plan 3.9 / 5.4)."""
    k = int(k or T["K"])
    rejected: dict = {}
    blocked: dict = {}
    stats = {"considered": 0}
    cache: dict = {}

    for layer in ("backend", "database", "hosting"):
        if not ranked.get(layer):
            return ComboResult(None, [], [], k, False, (layer, layer),
                               f"no {layer} candidate passed the hard filters.")
    required = _required_client_layers(ranked, p)
    for layer in required:
        if layer != "frontend_game" and not ranked.get(layer):
            return ComboResult(None, [], [], k, False, (layer, layer),
                               f"no {layer} candidate passed the hard filters.")
    primary = _primary_layer(ranked, p)
    fe_all: list = [None]
    if primary is not None:
        fe_all = _client_options(primary, list(ranked[primary]), p)
        if not fe_all:
            return ComboResult(None, [], [], k, False, (primary, primary),
                               f"no {primary} candidate covers project.platforms={scoring.fmt(list(p.clients))}.")
    bes, dbs, hos = (list(ranked[x]) for x in ("backend", "database", "hosting"))
    hosts_all = hos

    def lists_for(n):
        return ([None] if primary is None else fe_all[:n]), bes[:n], dbs[:n], hos[:n]

    passed = _enumerate(lists_for(k), hosts_all, p, cache, stats, rejected, blocked)
    widened = False
    used_k = k
    full = max(len(fe_all), len(bes), len(dbs), len(hos))
    if not passed and full > k:
        widened = True
        used_k = full
        blocked = {}
        passed = _enumerate(lists_for(full), hosts_all, p, cache, stats, rejected, blocked)
    rej_list = sorted(PairRejection(a, b, r) for (a, b, r) in rejected)
    if not passed:
        pair, why = None, None
        if blocked:
            pair = min(blocked, key=lambda lp: (-blocked[lp][0], LAYER_PAIRS.index(lp)))
            la, lb = pair
            why = (f"no combination passes the compatibility rules; {la} x {lb} blocked "
                   f"{blocked[pair][0]} of {stats['considered']} combinations (e.g. {blocked[pair][1]})")
        return ComboResult(None, [], rej_list, used_k, widened, pair, why, stats["considered"], 0)
    ordered = _sort(passed, p)
    top = ordered[: 1 + T["runners_up"]]
    top = [c if c.cost_mid is not None else replace(c, cost_mid=_cost_mid(c, p)) for c in top]
    top = [pick_clients(c, ranked, p) for c in top]
    return ComboResult(top[0], top[1:], rej_list, used_k, widened, None, None, stats["considered"], len(passed))


__all__ = ["T", "BAAS_COUPLING", "PairRejection", "ClientPart", "Combo", "ComboResult", "search",
           "check_frontend_backend", "check_backend_database", "check_backend_host", "choose_frontend_host",
           "resolve_database", "synergies", "language_penalty", "choose_languages", "client_terms",
           "pick_clients"]

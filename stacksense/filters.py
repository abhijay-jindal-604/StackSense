"""Hard filters F1-F8 (plan sections 3.7 and 5.2).

A candidate that fails any hard filter is never chosen. Rules run in this fixed order and the
**first** failing rule is the recorded reason (``check``); ``check_all`` returns every failing rule
(used for ``nearest_feasible`` and the decision trace).

    F1  status          only ``maintained`` records/offerings can be recommended
    F2  deployment      infrastructure.deployment_model
    F3  cloud           explicit infrastructure.cloud_preference = aws/gcp/azure
    F3b cloud_none      infrastructure.cloud_preference = none (no hyperscaler account)
    F4  residency       infrastructure.data_residency (effective value; rbi_localisation implies india)
    F5  compliance      compliance[] (gdpr, hipaa, pci_dss, rbi_localisation, soc2, iso27001)
    F6  open_source     infrastructure.open_source_only
    F7  platform        frontend must target the platform; backend runtime must run on a surviving host
    F8  capability      offline_support on mobile/desktop clients; p95_latency_ms <= 50 vs cold starts

Public API
----------
``RULES``                                     ordered rule codes ("F1", ..., "F8")
``Rejection``                                 frozen dataclass, see below; ``.to_dict()`` for JSON
``check(rec, p, layer=None, *, hosts=None, platform=None, static_only=None) -> Rejection | None``
``check_all(rec, p, layer=None, *, hosts=None, platform=None, static_only=None) -> tuple[Rejection, ...]``
``apply_hard(candidates, p, layer, *, hosts=None, platform=None, static_only=None)
        -> tuple[list[dict], list[Rejection]]``   both sorted by record id
``filter_layer(layer, p, **kw) -> tuple[list[dict], list[Rejection]]``   KB candidates of ``layer``
``check_offering(off, p) -> Rejection | None`` / ``check_offering_all(off, p)``
``viable_offerings(engine_id, p) -> list[dict]``  offerings of an engine that pass every rule
``region_portable(rec, layer) -> bool`` / ``residency_pass_reason(rec, p, layer=None) -> str | None``

``hosts`` (backend F7) is the list of surviving hosting records; when omitted it is computed with
``filter_layer("hosting", p)``. ``platform`` narrows F7 for a frontend layer to one client platform.
``static_only`` marks a hosting candidate as serving only public static assets (default: True when
``p.needs_backend`` is false).

Rejection shape (machine readable, feeds ``alternatives[].why_not``, warnings and the trace)::

    Rejection(tech_id="render", name="Render", layer="hosting", rule="F4", code="residency",
              fields=("infrastructure.data_residency",),
              reason_text="Render has no India region (vendor region list verified: India none); "
                          "violates data_residency=india.",
              sources=("render_regions",), unverified=False,
              detail=(("residency", "india"),))

``fields`` are input field paths (empty only for F1, which no input causes); ``sources`` are keys of
``kb.sources.SOURCES`` for the fact used; ``unverified`` is True when the rejection comes from a fact
that is not confirmed on an official page (fail closed).

Rules that need interpretation (stated once, applied everywhere)
-----------------------------------------------------------------
* **Self-hosted vs managed mode.** A record runs *self-hosted* when it is ``self_hostable`` and the
  deployment is ``self_hosted_cloud_vm``, ``on_premise`` or ``air_gapped``. Otherwise it runs
  *managed*. Record-level ``"*"`` regions and ``"self"`` attestations are true only for the
  self-hosted mode, so in managed mode they never satisfy F4/F5 on their own:
  - a record that has offerings (``kb.offerings``, e.g. postgres, mongodb) passes F2-F6 only if at
    least one *managed* offering (host != ``self_hosted``) passes them; the record is rejected at the
    rule where the furthest-reaching offering failed;
  - a record without managed offerings that is not SaaS (framework, embedded SQLite, PocketBase,
    an engine offered only self-hosted) runs inside the application host, which F4/F5 check
    themselves, so it passes;
  - a SaaS record without managed offerings (e.g. InfluxDB 3 under managed_cloud) is judged on its
    own cells with ``"*"`` and ``"self"`` ignored, so it fails closed.
* **Who handles personal data (F4/F5 scope).** The KB has no personal-data flag, so the rule is:
  ``data_at_rest`` records; every database except kind ``none``; every *vendor-operated* back end
  (``saas`` true: serverless functions, BaaS, commerce SaaS); every hosting candidate except one
  serving only public static assets (``static_only`` or a host that can run nothing but ``static``);
  every supporting layer except ``cdn`` and ``ci_cd`` (public assets / source code). Frontend
  frameworks and self-run back-end frameworks run on the host, which is checked instead.
* **Attestation values (one rule).** F5 passes ``yes``, ``self`` (self-hosted mode only) and
  ``plan:<name>`` (the plan must then be bought). ``pci_dss`` accepts only ``yes``/``self``.
  ``no``, ``unknown`` and ``na`` all FAIL: ``na`` is never treated as a pass by this module (unlike
  ``kb.compliance.passes``), because a regime in ``compliance[]`` means regulated data may reach every
  component that handles personal data. ``dpdp`` has no vendor attestation and is not a filter.
  ``rbi_localisation`` needs an India region for the database, payments and data-at-rest records.
  ``pci_dss`` applies to the card-data environment: backend, database, hosting and payments.
* **Deployment (F2).** on_premise/air_gapped: ``self_hostable`` required, hosting kind must be
  ``onprem`` or ``hybrid_appliance`` (public-cloud VMs are not on premises), air_gapped also needs
  ``needs_internet`` false. A payments gateway is an external API by nature and is allowed under
  on_premise (not air_gapped). managed_cloud: hosting kinds ``onprem``/``hybrid_appliance`` excluded.
  self_hosted_cloud_vm: hosting kind must be vm/k8s/container; vendor-operated (SaaS, not
  self-hostable) records are excluded except in the payments and other (SMS/OTP) layers.
* **Explicit cloud (F3/F3b)** binds the infrastructure layers (D10: hosting, database, cache, queue,
  storage, cdn, search, ml, observability) and vendor-operated back ends. A record passes when its
  ``cloud_affinity`` contains the cloud, or it is portable (``any``) and self-hostable / not SaaS.
* **Host-bundled supporting records** (kind ``bundled`` or cap ``bundled_with_host``: built-in CDN
  edge, platform logs, host-native git deploys) inherit F4/F5 from the host: they pass when every
  host in ``hosts`` (the chosen hosts that ``supporting.select`` passes, else every surviving host)
  passes the same rule, and fail closed when there is no host.
* **Residency ``other`` (F4).** No country is named, so no vendor region list can be checked. Region-portable
  hosting (kinds in ``REGION_PORTABLE_HOST_KINDS``: vm, k8s, container, onprem, hybrid_appliance) passes,
  because the team deploys the same image in its own jurisdiction; self-hosted-mode records and components
  that run inside the host pass as for every residency. Managed services pinned to vendor regions (PaaS,
  static hosts, serverless, BaaS, managed offerings, SaaS) fail closed. ``residency_pass_reason`` gives the
  plain-language reason for a pass; the profile adds the critical warning ``RESIDENCY_UNVERIFIABLE``.
* **open_source_only (F6)** does not apply to hosting (infrastructure, per the schema text) or
  payments (no open-source gateway exists). Managed offerings of an open-source engine pass.

Pure and deterministic: no clock, no randomness; outputs sorted by id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import kb
from .kb import bindings as _bindings
from .kb import compliance as _compliance
from .kb import regions as _regions
from .kb.sources import SOURCES as _SOURCES

RULES: tuple[str, ...] = ("F1", "F2", "F3", "F3b", "F4", "F5", "F6", "F7", "F8")
RULE_CODES = {"F1": "status", "F2": "deployment", "F3": "cloud", "F3b": "cloud_none", "F4": "residency",
              "F5": "compliance", "F6": "open_source", "F7": "platform", "F8": "capability"}

FRONTEND_LAYERS = ("frontend_web", "frontend_mobile", "frontend_desktop", "frontend_game")
INFRA_LAYERS = ("hosting", "database", "cache", "queue", "storage", "cdn", "search", "ml", "observability")
NO_PERSONAL_DATA_LAYERS = ("cdn", "ci_cd")
# Processor-only services: they handle transactional data in flight (a payment, an SMS one-time password,
# a push notification) rather than storing the application's records. layer -> record kinds (None = all
# kinds), with the plain-language name of the data they process. Under data_residency us/eu a processor
# whose region cell is UNKNOWN (no vendor page confirms or denies an in-region option) passes F4 with the
# RESIDENCY_PROCESSOR_UNVERIFIED warning (:func:`processor_residency_note`); a verified [] cell, every
# other residency (india, other) and F5 still fail closed.
PROCESSOR_ONLY_LAYERS: dict[str, dict[str | None, str]] = {
    "payments": {None: "payment"},
    "other": {"sms": "SMS one-time password", "push": "push notification"},
}
PROCESSOR_RESIDENCIES = ("eu", "us")
SAAS_ALLOWED_SELF_HOSTED_VM = ("payments", "other")
SAAS_ALLOWED_ON_PREMISE = ("payments",)
OPEN_SOURCE_EXEMPT = ("hosting", "payments")
PCI_LAYERS = ("backend", "database", "hosting", "payments")
RBI_LAYERS = ("database", "payments")
ONPREM_HOST_KINDS = ("onprem", "hybrid_appliance")
CLOUD_VM_HOST_KINDS = ("vm", "k8s", "container")
CONTAINER_HOST_KINDS = ("vm", "k8s", "container", "onprem", "hybrid_appliance")
# data_residency=other: host kinds the team deploys itself on any provider or server (F4 passes them)
REGION_PORTABLE_HOST_KINDS = ("vm", "k8s", "container", "onprem", "hybrid_appliance")
SELF_HOSTED_DEPLOYMENTS = ("self_hosted_cloud_vm", "on_premise", "air_gapped")
HYPERSCALERS = ("aws", "gcp", "azure")
CLOUD_NAMES = {"aws": "AWS", "gcp": "Google Cloud", "azure": "Azure"}
RESIDENCY_NAMES = {"india": "India", "eu": "EU", "us": "US", "other": "the unnamed country"}
LATENCY_COLD_START_MS = 50
CORE_RECORD_LAYERS = FRONTEND_LAYERS + ("backend", "database", "hosting")
CLIENT_LAYER_PLATFORMS = {"frontend_web": ("web",), "frontend_desktop": ("desktop",),
                          "frontend_mobile": ("android", "ios")}

# compliance regime -> (model attest key, label used in reason text)
REGIME_ATTEST = {
    "gdpr": ("gdpr_dpa", "GDPR data processing agreement"),
    "hipaa": ("hipaa_baa", "HIPAA business associate agreement"),
    "pci_dss": ("pci_dss", "PCI DSS attestation"),
    "soc2": ("soc2", "SOC 2 report"),
    "iso27001": ("iso27001", "ISO/IEC 27001 certification"),
}
F5_REGIMES = ("gdpr", "hipaa", "pci_dss", "rbi_localisation", "soc2", "iso27001")   # dpdp: no vendor fact

F_DEPLOY = "infrastructure.deployment_model"
F_CLOUD = "infrastructure.cloud_preference"
F_RES = "infrastructure.data_residency"
F_COMP = "compliance"
F_OSS = "infrastructure.open_source_only"
F_PLAT = "project.platforms"
F_OFFLINE = "requirements.offline_support"
F_LAT = "requirements.p95_latency_ms"


@dataclass(frozen=True)
class Rejection:
    tech_id: str
    name: str
    layer: str
    rule: str                       # F1 .. F8 (F3b)
    code: str                       # RULE_CODES[rule]
    fields: tuple[str, ...]         # input field paths that caused it
    reason_text: str                # plain language, quotes the input value
    sources: tuple[str, ...] = ()   # kb.sources keys of the fact used
    unverified: bool = False        # True when an unconfirmed fact failed closed
    detail: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict:
        return {"tech_id": self.tech_id, "name": self.name, "layer": self.layer, "rule": self.rule,
                "code": self.code, "fields": list(self.fields), "reason_text": self.reason_text,
                "sources": list(self.sources), "unverified": self.unverified, "detail": dict(self.detail)}


# ------------------------------------------------------------------ helpers
def _val(p, path, default=None):
    vals = getattr(p, "values", None)
    return default if vals is None else vals.get(path, default)


def _srcs(keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({k for k in keys if k in _SOURCES}))


def _rej(rec, layer, rule, fields, text, sources=(), unverified=False, **detail) -> Rejection:
    return Rejection(tech_id=rec["id"], name=rec.get("name", rec["id"]), layer=layer, rule=rule,
                     code=RULE_CODES[rule], fields=tuple(fields), reason_text=text,
                     sources=_srcs(sources), unverified=unverified,
                     detail=tuple(sorted((k, str(v)) for k, v in detail.items())))


def _is_offering(rec) -> bool:
    return "engine" in rec and "host" in rec


def self_hosted_mode(rec, p) -> bool:
    """True when ``rec`` runs on infrastructure the team operates (its '*'/'self' cells are then true)."""
    if _is_offering(rec):
        return rec["host"] == "self_hosted"
    return bool(rec.get("self_hostable")) and p.deployment in SELF_HOSTED_DEPLOYMENTS


def _offerings(engine_id) -> list:
    return sorted((o for o in kb.OFFERINGS if o["engine"] == engine_id), key=lambda o: o["id"])


def _host_runtimes(host) -> list:
    rt = host.get("runtime")
    out = set(host.get("platforms") or ())
    if isinstance(rt, (list, tuple)):
        out.update(rt)
    elif isinstance(rt, str):
        out.add(rt)
    return sorted(out)


def handles_personal_data(rec, p, layer, static_only=None) -> bool:
    """The F4/F5 scope rule of the module docstring."""
    if _is_offering(rec):
        return True
    if rec.get("data_at_rest"):
        return True
    if layer in FRONTEND_LAYERS:
        return False
    if layer == "backend":
        return rec.get("kind") != "none" and bool(rec.get("saas"))
    if layer == "database":
        return rec.get("kind") != "none"
    if layer == "hosting":
        if static_only is None:
            static_only = not p.needs_backend
        if static_only:
            return False
        return any(r != "static" for r in _host_runtimes(rec))
    return layer not in NO_PERSONAL_DATA_LAYERS


def _residency_text(p) -> str:
    r = p.effective_residency
    if r != p.residency:
        return f"data_residency={r} (implied by compliance rbi_localisation)"
    return f"data_residency={r}"


def _res_fields(p) -> tuple[str, ...]:
    return (F_RES, F_COMP) if p.effective_residency != p.residency else (F_RES,)


def _bound(rec):
    return _bindings.BINDINGS.get(rec["id"], (None, None))


# ------------------------------------------------------------------ individual rules
def _f1(rec, p, layer, ctx):
    status = rec.get("status", "maintained")
    if status == "maintained":
        return None
    facts = [f for f in rec.get("facts", ()) if not f["text"].startswith(("Region", "Attestation"))]
    life = [f for f in facts if f["text"].startswith("Lifecycle")] or facts
    detail = life[0]["text"].rstrip(".") if life else (f"supported until {rec['supported_until']}"
                                                        if rec.get("supported_until") else "no longer maintained")
    if detail.startswith("Lifecycle: "):
        detail = detail[len("Lifecycle: "):]
    repl = rec.get("replaced_by") or "a maintained alternative"
    target = kb.get(repl) if isinstance(repl, str) else None
    repl_name = target["name"] if target else repl
    src = [life[0]["source_key"]] if life else rec.get("sources", ())
    return _rej(rec, layer, "F1", (), f"{rec.get('name', rec['id'])} is {status.replace('_', ' ')} ({detail}); "
                f"replaced by {repl_name}.", src, status=status, replaced_by=repl)


def _f2(rec, p, layer, ctx):
    d = p.deployment
    name = rec.get("name", rec["id"])
    src = rec.get("sources", ())
    if _is_offering(rec):
        if d in ("on_premise", "air_gapped", "self_hosted_cloud_vm") and rec["host"] != "self_hosted":
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is a managed service and cannot run under "
                        f"deployment_model={d}.", src, deployment=d)
        if d == "air_gapped" and rec.get("needs_internet"):
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} needs an internet connection at runtime; "
                        f"deployment_model=air_gapped.", src, deployment=d)
        return None
    kind = rec.get("kind")
    if d in ("on_premise", "air_gapped"):
        if layer in SAAS_ALLOWED_ON_PREMISE and d == "on_premise":
            return None
        if not rec.get("self_hostable"):
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is SaaS-only and cannot run under "
                        f"deployment_model={d}.", src, deployment=d)
        if layer == "hosting" and kind not in ONPREM_HOST_KINDS:
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is a public-cloud {kind} service, not "
                        f"customer-premises infrastructure; deployment_model={d}.", src, deployment=d)
        if d == "air_gapped" and rec.get("needs_internet"):
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} needs an internet connection at runtime; "
                        f"deployment_model=air_gapped.", src, deployment=d)
        return None
    if d == "managed_cloud":
        if layer == "hosting" and kind in ONPREM_HOST_KINDS:
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is customer-premises infrastructure; "
                        f"deployment_model=managed_cloud.", src, deployment=d)
        return None
    if d == "self_hosted_cloud_vm":
        if layer == "hosting":
            if kind not in CLOUD_VM_HOST_KINDS:
                return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is a {kind} host, not a VM, container or "
                            f"Kubernetes host; deployment_model=self_hosted_cloud_vm.", src, deployment=d)
            return None
        if rec.get("saas") and not rec.get("self_hostable") and layer not in SAAS_ALLOWED_SELF_HOSTED_VM:
            return _rej(rec, layer, "F2", (F_DEPLOY,), f"{name} is SaaS-only and cannot run under "
                        f"deployment_model=self_hosted_cloud_vm.", src, deployment=d)
    return None


def _f3(rec, p, layer, ctx):
    if _is_offering(rec):
        if p.cloud_explicit and p.cloud and rec["host"] not in (p.cloud, "self_hosted"):
            return _rej(rec, layer, "F3", (F_CLOUD,), f"{rec['name']} is not an {CLOUD_NAMES[p.cloud]} service; "
                        f"cloud_preference={p.cloud} is explicit.", rec.get("sources", ()), cloud=p.cloud)
        return None
    if not (p.cloud_explicit and p.cloud):
        return None
    if not _cloud_bound(rec, layer, p):
        return None
    aff = rec.get("cloud_affinity") or []
    if p.cloud in aff:
        return None
    if "any" in aff and (rec.get("self_hostable") or not rec.get("saas")):
        return None
    return _rej(rec, layer, "F3", (F_CLOUD,), f"{rec.get('name', rec['id'])} is not an {CLOUD_NAMES[p.cloud]} "
                f"service; cloud_preference={p.cloud} is explicit.", rec.get("sources", ()), cloud=p.cloud)


def _cloud_bound(rec, layer, p) -> bool:
    if layer in INFRA_LAYERS:
        return True
    return layer == "backend" and bool(rec.get("saas")) and not self_hosted_mode(rec, p)


def _an(word: str) -> str:
    """'an AWS', 'an Azure', 'a Google Cloud' (article by the sound of the first letter)."""
    return ("an " if word[:1].upper() in "AEIOU" else "a ") + word


def _f3b(rec, p, layer, ctx):
    if p.cloud_preference != "none":
        return None
    if _is_offering(rec):
        if rec["host"] in HYPERSCALERS:
            return _rej(rec, layer, "F3b", (F_CLOUD,), f"{rec['name']} needs {_an(CLOUD_NAMES[rec['host']])} "
                        f"account; cloud_preference=none.", rec.get("sources", ()), cloud=rec["host"])
        return None
    if layer.startswith("frontend"):
        return None   # none = no hyperscaler account at all: every service layer, not only infrastructure
    aff = [c for c in (rec.get("cloud_affinity") or [])]
    if aff and all(c in HYPERSCALERS for c in aff):
        clouds = " or ".join(CLOUD_NAMES[c] for c in aff)
        return _rej(rec, layer, "F3b", (F_CLOUD,), f"{rec.get('name', rec['id'])} needs {_an(clouds)} account; "
                    f"cloud_preference=none.", rec.get("sources", ()), cloud=",".join(aff))
    return None


def _region_cells(rec, p):
    """(ids, unverified, sources) for the effective residency from the record's own cells."""
    r = p.effective_residency
    rk, _ = _bound(rec)
    if rk is not None:
        raw = _regions.regions_for(rk, r)
        if raw == _regions.UNKNOWN:
            return [], True, _regions.source_keys(rk) or rec.get("sources", ())
        return list(raw), False, _regions.source_keys(rk) or rec.get("sources", ())
    ids = list((rec.get("regions") or {}).get(r, []))
    # unbound cells carry no vendor claim: an empty list is "no verified region on file"
    return ids, not ids, rec.get("sources", ())


def _f4_cells(rec, p, layer, self_mode):
    r = p.effective_residency
    name = rec.get("name", rec["id"])
    if r == "none":
        return None
    if self_mode:
        return None
    if r == "other":
        if region_portable(rec, layer):
            return None
        return _rej(rec, layer, "F4", _res_fields(p), f"{name} is a managed service pinned to its vendor's regions "
                    f"and data_residency=other names no country, so no in-country region can be verified "
                    f"(fail closed); violates {_residency_text(p)}.",
                    _regions.source_keys(_bound(rec)[0] or "") or rec.get("sources", ()), True, residency=r)
    ids, unverified, src = _region_cells(rec, p)
    ids = [i for i in ids if i != "*"]   # '*' is true only for self-hosted mode
    if ids:
        return None
    if _processor_unknown(rec, p, layer):
        return None
    rn = RESIDENCY_NAMES[r]
    fact = (f"no {rn} region confirmed on the vendor's pages, so treated as unavailable (fail closed)"
            if unverified else f"vendor region list verified: {rn} none")
    return _rej(rec, layer, "F4", _res_fields(p), f"{name} has no {rn} region ({fact}); violates "
                f"{_residency_text(p)}.", src, unverified, residency=r)


def _processor_kind(rec, layer) -> str | None:
    """The data a processor-only record handles ("payment", "notification"), or None."""
    entry = PROCESSOR_ONLY_LAYERS.get(layer)
    if entry is None or _is_offering(rec):
        return None
    return entry.get(None) or entry.get(rec.get("kind"))


def _processor_unknown(rec, p, layer) -> bool:
    """True when ``rec`` is a processor-only service, the residency is us/eu and its vendor region cell for
    that residency is UNKNOWN (a verified ``[]`` is not unknown)."""
    if p.effective_residency not in PROCESSOR_RESIDENCIES or _processor_kind(rec, layer) is None:
        return False
    rk, _ = _bound(rec)
    if rk is not None:
        return _regions.regions_for(rk, p.effective_residency) == _regions.UNKNOWN
    return p.effective_residency not in (rec.get("regions") or {})


def processor_residency_note(rec, p, layer=None) -> str | None:
    """RESIDENCY_PROCESSOR_UNVERIFIED text when ``rec`` passes F4 only through the processor-only policy
    (:data:`PROCESSOR_ONLY_LAYERS`), else None."""
    layer = layer or rec["layer"]
    if not _processor_unknown(rec, p, layer) or self_hosted_mode(rec, p):
        return None
    if not handles_personal_data(rec, p, layer) or _runs_inside_host(rec, p):
        return None
    ids, _, _ = _region_cells(rec, p)
    if [i for i in ids if i != "*"]:
        return None
    r = p.effective_residency
    rn = RESIDENCY_NAMES[r]
    dpa = "data processing agreement (with Standard Contractual Clauses)" if r == "eu" else "data processing agreement"
    return (f"{rec.get('name', rec['id'])} does not commit to keeping data in the {rn} (no vendor page confirms "
            f"an in-region option for data_residency={r}); it may process {_processor_kind(rec, layer)} data "
            f"outside the region. Sign its {dpa} and keep regulated records out of the payload.")


def region_portable(rec, layer) -> bool:
    """A hosting record whose kind is in ``REGION_PORTABLE_HOST_KINDS`` (VM, container, Kubernetes, on-premises
    or appliance): the team deploys the same image on any provider or server, so it can be placed in
    whatever country an unnamed ``data_residency=other`` means. Offerings and every other kind (PaaS,
    static hosts, serverless functions, BaaS) are pinned to vendor regions and are not portable."""
    return (layer == "hosting" and not _is_offering(rec)
            and rec.get("kind") in REGION_PORTABLE_HOST_KINDS)


def residency_pass_reason(rec, p, layer=None) -> str | None:
    """Plain-language reason why ``rec`` passes F4 under ``data_residency=other`` (None when the residency is
    not ``other``, when F4 does not apply to ``rec``, or when F4 fails). Feeds explanations and the trace."""
    layer = layer or rec["layer"]
    if p.effective_residency != "other":
        return None
    name = rec.get("name", rec["id"])
    if _is_offering(rec):
        if rec["host"] == "self_hosted" and _f4_cells(rec, p, layer, True) is None:
            return (f"{name} is self-managed on the team's own host, so it runs in whichever country that "
                    f"host is deployed; data_residency=other: confirm the host's country.")
        return None
    ctx = _ctx(p, layer, None, None, None)
    if _f4(rec, p, layer, ctx) is not None:
        return None
    if region_portable(rec, layer) and handles_personal_data(rec, p, layer):
        return (f"{name} is a {rec.get('kind')} host and region-portable: the same deployment runs on any "
                f"provider or server, so deploy it in your jurisdiction; data_residency=other names no country, "
                f"so confirm the provider region yourself (RESIDENCY_UNVERIFIABLE).")
    if self_hosted_mode(rec, p):
        return (f"{name} runs self-hosted under deployment_model={p.deployment}, so its data stays where the "
                f"team deploys it; data_residency=other: confirm that location is in your jurisdiction.")
    if handles_personal_data(rec, p, layer) and _runs_inside_host(rec, p):
        return (f"{name} runs inside the application host, so it inherits the host's location; "
                f"data_residency=other: deploy that host in your jurisdiction.")
    return None


def _runs_inside_host(rec, p) -> bool:
    """Managed mode, not SaaS (PocketBase, SQLite, an engine with no managed offering): the component
    runs on the application host, whose own F4/F5 check covers it."""
    return not _is_offering(rec) and not rec.get("saas") and not self_hosted_mode(rec, p)


def host_bundled(rec, layer) -> bool:
    """A supporting feature of the host itself (built-in CDN edge, platform logs, git deploys): kind
    ``bundled`` or cap ``bundled_with_host``. It has no region or attestation of its own; F4/F5 judge
    it by the host(s) it is bundled with."""
    if layer in CORE_RECORD_LAYERS:
        return False
    return rec.get("kind") == "bundled" or "bundled_with_host" in (rec.get("caps") or ())


def _inherit_host(rec, p, layer, ctx, rule):
    """F4/F5 for a host-bundled record: it passes when there is a host and every host passed in
    ``hosts`` (the chosen hosts from supporting.select, else every surviving host) passes the same
    rule as a hosting record; otherwise it fails with the host's reason (or closed with no host)."""
    hosts = list(ctx["hosts"]()[0])
    name = rec.get("name", rec["id"])
    fields = (F_COMP,) if rule == "F5" else _res_fields(p)
    if not hosts:
        what = "compliance" if rule == "F5" else _residency_text(p)
        return _rej(rec, layer, rule, fields, f"{name} is part of the host, and no host passes the hard filters, "
                    f"so it cannot be checked against {what} (fail closed).", rec.get("sources", ()), True)
    fn = _f4 if rule == "F4" else _f5
    fails = [r for r in (fn(h, p, "hosting", ctx) for h in sorted(hosts, key=lambda h: h["id"])) if r is not None]
    if not fails:
        return None
    return _rej(rec, layer, rule, tuple(sorted({f for r in fails for f in r.fields})),
                f"{name} is part of the host, which fails this check: " + " ".join(r.reason_text for r in fails),
                [k for r in fails for k in r.sources], any(r.unverified for r in fails),
                host=",".join(r.tech_id for r in fails))


def _f4(rec, p, layer, ctx):
    if not handles_personal_data(rec, p, layer, ctx.get("static_only")) or _runs_inside_host(rec, p):
        return None
    if host_bundled(rec, layer) and not self_hosted_mode(rec, p):
        return _inherit_host(rec, p, layer, ctx, "F4")
    return _f4_cells(rec, p, layer, self_hosted_mode(rec, p))


def _attest_raw(rec, regime, p, self_mode):
    """(value, sources) with yes/plan:*/self/no/unknown/na semantics."""
    if self_mode:
        return "self", rec.get("sources", ())
    ak = _bound(rec)[1]
    if ak is not None:
        v = _compliance.attestation_in_region(ak, regime, p.effective_residency)
        return v, _compliance.attestation_sources(ak, regime) or rec.get("sources", ())
    key = REGIME_ATTEST[regime][0]
    v = (rec.get("attest") or {}).get(key, "unknown")
    if v == "self":
        v = "unknown"    # 'self' cells are true only when self-hosted
    elif v == "no":
        v = "unknown"    # unbound record: no vendor claim on file
    return v, rec.get("sources", ())


def _attest_ok(regime, v) -> bool:
    if regime == "pci_dss":
        return v in ("yes", "self")
    return v in ("yes", "self") or (isinstance(v, str) and v.startswith("plan:") and len(v) > 5)


def _f5_cells(rec, p, layer, self_mode):
    name = rec.get("name", rec["id"])
    failures, srcs, unverified = [], [], False
    for regime in F5_REGIMES:
        if regime not in p.compliance:
            continue
        if regime == "pci_dss" and layer not in PCI_LAYERS and not rec.get("data_at_rest"):
            continue
        if regime == "rbi_localisation":
            if layer not in RBI_LAYERS and not rec.get("data_at_rest"):
                continue
            if self_mode:
                continue
            rk, _ = _bound(rec)
            raw = _regions.regions_for(rk, "india") if rk else [i for i in (rec.get("regions") or {}).get("india", [])]
            ids = [] if raw == _regions.UNKNOWN else [i for i in raw if i != "*"]
            if not ids:
                unv = raw == _regions.UNKNOWN or rk is None
                unverified |= unv
                srcs.extend(_regions.source_keys(rk) if rk else rec.get("sources", ()))
                failures.append(("rbi_localisation", f"{name} has no India region for payment data ("
                                 + ("not confirmed on the vendor's pages, fail closed" if unv else "vendor region list verified: India none")
                                 + "); violates compliance=rbi_localisation."))
            continue
        v, src = _attest_raw(rec, regime, p, self_mode)
        if _attest_ok(regime, v):
            continue
        label = REGIME_ATTEST[regime][1]
        if v == "no":
            fact = "the vendor states it does not offer it"
        elif isinstance(v, str) and v.startswith("plan:"):
            fact = f"only on the {v[5:]} plan, which does not cover the card-data path"
        elif v == "na":
            fact = "the vendor makes no such commitment for this kind of service; fail closed"
        else:
            unverified = True
            ak = _bound(rec)[1]
            gap = _compliance.COMBINED_UNKNOWN.get((_compliance.ALIASES.get(ak, ak), regime, p.effective_residency)) if ak else None
            fact = (gap.rstrip(".") + "; fail closed") if gap else "not confirmed on an official vendor page, so treated as absent (fail closed)"
        srcs.extend(src)
        failures.append((regime, f"{name} offers no {label} ({fact}); violates compliance={regime}."))
    if not failures:
        return None
    return _rej(rec, layer, "F5", (F_COMP,), " ".join(t for _, t in failures), srcs, unverified,
                regimes=",".join(r for r, _ in failures))


def _f5(rec, p, layer, ctx):
    if not handles_personal_data(rec, p, layer, ctx.get("static_only")) or _runs_inside_host(rec, p):
        return None
    if host_bundled(rec, layer) and not self_hosted_mode(rec, p):
        return _inherit_host(rec, p, layer, ctx, "F5")
    return _f5_cells(rec, p, layer, self_hosted_mode(rec, p))


def _f6(rec, p, layer, ctx):
    if not _val(p, F_OSS, False) or layer in OPEN_SOURCE_EXEMPT:
        return None
    if _is_offering(rec):
        eng = kb.get(rec["engine"]) or {}
        if eng.get("open_source"):
            return None
        return _rej(rec, layer, "F6", (F_OSS,), f"{rec['name']} runs a proprietary engine "
                    f"({eng.get('licence', 'licence unknown')}); open_source_only=true.", rec.get("sources", ()))
    if rec.get("open_source"):
        return None
    return _rej(rec, layer, "F6", (F_OSS,), f"{rec.get('name', rec['id'])} is proprietary "
                f"({rec.get('licence') or 'licence unknown'}); open_source_only=true.", rec.get("sources", ()),
                licence=rec.get("licence") or "")


def _f7(rec, p, layer, ctx):
    name = rec.get("name", rec["id"])
    plats = rec.get("platforms") or []
    if layer in FRONTEND_LAYERS:
        if ctx.get("platform"):
            want = (ctx["platform"],)
        elif layer in CLIENT_LAYER_PLATFORMS:
            want = CLIENT_LAYER_PLATFORMS[layer]
            if layer == "frontend_mobile":
                want = tuple(c for c in p.clients if c in want) or want
        else:   # game engines: any client platform of the project
            want = tuple(p.clients)
        if want and not any(w in plats for w in want):
            return _rej(rec, layer, "F7", (F_PLAT,), f"{name} cannot target {' or '.join(want)}.",
                        rec.get("sources", ()), platform=",".join(want))
        return None
    if layer == "backend":
        runtime = rec.get("runtime")
        if not runtime or rec.get("kind") == "none":
            return None
        hosts, host_rej = ctx["hosts"]()
        if any(_runs_on(rec, h) for h in hosts):
            return None
        fields = sorted({f for r in host_rej if _runs_on(rec, kb.get(r.tech_id) or {}) for f in r.fields})
        if not fields:
            fields = [F_DEPLOY, F_CLOUD, F_RES]
        return _rej(rec, layer, "F7", fields, f"{name} runs on {runtime}, and no host that passed the hard "
                    f"filters can run {runtime}.", rec.get("sources", ()), runtime=runtime)
    return None


def _runs_on(rec, host) -> bool:
    if not host:
        return False
    runtime = rec.get("runtime")
    if runtime in _host_runtimes(host):
        return True
    # a self-hostable BaaS ships as containers and runs on any VM/container/Kubernetes host
    return runtime == "baas" and bool(rec.get("self_hostable")) and host.get("kind") in CONTAINER_HOST_KINDS


def _f8(rec, p, layer, ctx):
    name = rec.get("name", rec["id"])
    if _val(p, F_OFFLINE, False) and layer in ("frontend_mobile", "frontend_desktop"):
        if "offline" not in (rec.get("caps") or []):
            return _rej(rec, layer, "F8", (F_OFFLINE,), f"{name} cannot work offline; "
                        f"requirements.offline_support=true.", rec.get("sources", ()), capability="offline")
    ms = _val(p, F_LAT)
    if (ms is not None and ms <= LATENCY_COLD_START_MS and p.needs_backend and layer in ("hosting", "backend")):
        caps = rec.get("caps") or []
        if "cold_start" in caps and "min_instances" not in caps:
            return _rej(rec, layer, "F8", (F_LAT,), f"{name} has cold starts with no minimum-instance option; "
                        f"requirements.p95_latency_ms={ms}.", rec.get("sources", ()), capability="cold_start")
    return None


_RULE_FUNCS = (("F1", _f1), ("F2", _f2), ("F3", _f3), ("F3b", _f3b), ("F4", _f4), ("F5", _f5),
               ("F6", _f6), ("F7", _f7), ("F8", _f8))
_OFFERING_RULES = ("F1", "F2", "F3", "F3b", "F4", "F5", "F6")


# ------------------------------------------------------------------ offerings
def check_offering_all(off, p, layer="database") -> tuple[Rejection, ...]:
    """Every failing rule (F1-F6) of one offering (engine on a host family)."""
    out = []
    self_mode = off["host"] == "self_hosted"
    for code, fn in _RULE_FUNCS:
        if code not in _OFFERING_RULES:
            continue
        if code == "F4":
            r = _f4_cells(off, p, layer, self_mode)
        elif code == "F5":
            r = _f5_cells(off, p, layer, self_mode)
        else:
            r = fn(off, p, layer, {})
        if r is not None:
            out.append(r)
    return tuple(out)


def check_offering(off, p, layer="database") -> Rejection | None:
    rs = check_offering_all(off, p, layer)
    return rs[0] if rs else None


def viable_offerings(engine_id, p, layer="database") -> list:
    """Offerings of ``engine_id`` that pass every hard rule, sorted by id. In managed mode (deployment
    managed_cloud) only managed offerings count; in a self-hosted deployment only self_hosted ones."""
    want_self = p.deployment in SELF_HOSTED_DEPLOYMENTS
    return [o for o in _offerings(engine_id)
            if (o["host"] == "self_hosted") == want_self and check_offering(o, p, layer) is None]


def _offering_gate(rec, p, layer):
    """Managed mode with offerings: the rule at which the furthest-reaching managed offering failed,
    or None if one passes. Returns (rule_index, Rejection) or None."""
    managed = [o for o in _offerings(rec["id"]) if o["host"] != "self_hosted"]
    name = rec.get("name", rec["id"])
    if not managed:
        return None
    best_idx, best = -1, []
    for o in managed:
        r = check_offering(o, p, layer)
        if r is None:
            return None
        idx = RULES.index(r.rule)
        if idx > best_idx:
            best_idx, best = idx, [r]
        elif idx == best_idx:
            best.append(r)
    rule = RULES[best_idx]
    why = " ".join(r.reason_text for r in best)
    rej = Rejection(tech_id=rec["id"], name=name, layer=layer, rule=rule, code=RULE_CODES[rule],
                    fields=tuple(sorted({f for r in best for f in r.fields})),
                    reason_text=f"No managed {name} offering passes: {why}",
                    sources=_srcs(s for r in best for s in r.sources),
                    unverified=any(r.unverified for r in best),
                    detail=(("offerings", ",".join(r.tech_id for r in best)),))
    return best_idx, rej


# ------------------------------------------------------------------ records
def _ctx(p, layer, hosts, platform, static_only):
    cache = {}

    def get_hosts():
        if "h" not in cache:
            if hosts is not None:
                cache["h"] = (list(hosts), [])
            else:
                cache["h"] = filter_layer("hosting", p)
        return cache["h"]
    return {"hosts": get_hosts, "platform": platform, "static_only": static_only}


def _check_all(rec, p, layer, ctx, first_only) -> tuple[Rejection, ...]:
    out = []
    gate = None
    uses_offerings = (not self_hosted_mode(rec, p)) and any(o["host"] != "self_hosted" for o in _offerings(rec["id"]))
    if uses_offerings:
        gate = _offering_gate(rec, p, layer)
    for code, fn in _RULE_FUNCS:
        idx = RULES.index(code)
        if uses_offerings and code in ("F4", "F5"):
            # record '*'/'self' cells are not valid in managed mode: the offerings decide F2-F6
            r = None
        else:
            r = fn(rec, p, layer, ctx)
        if r is None and gate is not None and gate[0] == idx:
            r = gate[1]
        if r is not None:
            out.append(r)
            if first_only:
                break
    return tuple(out)


def check_all(rec, p, layer=None, *, hosts=None, platform=None, static_only=None) -> tuple[Rejection, ...]:
    """Every failing rule for one record, in rule order (empty tuple = passes)."""
    layer = layer or rec["layer"]
    return _check_all(rec, p, layer, _ctx(p, layer, hosts, platform, static_only), False)


def check(rec, p, layer=None, *, hosts=None, platform=None, static_only=None) -> Rejection | None:
    """The first failing rule for one record, or None when it passes every hard filter."""
    layer = layer or rec["layer"]
    rs = _check_all(rec, p, layer, _ctx(p, layer, hosts, platform, static_only), True)
    return rs[0] if rs else None


def apply_hard(candidates, p, layer, *, hosts=None, platform=None, static_only=None):
    """Split ``candidates`` into (kept, rejected), both sorted by record id (input order is irrelevant)."""
    ctx = _ctx(p, layer, hosts, platform, static_only)
    kept, rejected = [], []
    for rec in sorted(candidates, key=lambda r: r["id"]):
        rs = _check_all(rec, p, layer, ctx, True)
        if rs:
            rejected.append(rs[0])
        else:
            kept.append(rec)
    return kept, rejected


def filter_layer(layer, p, **kw):
    """``apply_hard`` over every KB record of ``layer``."""
    return apply_hard(kb.by_layer(layer), p, layer, **kw)

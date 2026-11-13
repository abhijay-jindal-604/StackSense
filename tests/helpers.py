"""Test helpers: the independent hard-constraint re-check of plan T-HARD-01.

``assert_no_hard_violation(testcase, scenario_values, output)`` re-implements the hard checks
(status, deployment model, explicit cloud, data residency, compliance attestations) straight from the
KB facts (record and offering cells, ``kb.compliance`` combined gaps). It deliberately does NOT import
``stacksense.filters``: two independent implementations must agree.

Every component of ``output["stack"]`` is mapped back to a KB record (and offering, if named) through
an explicit id key (``kb_id``/``tech_id``/``id``, ``offering_id``) or, failing that, the longest KB
record/offering name that prefixes ``choice``. A component that maps to nothing fails the assertion.

A violation of field F is accepted only when the output declares it: a ``critical`` warning whose
``fields`` contain F, or a ``relaxed_constraints`` entry that mentions F.
"""
from __future__ import annotations

from stacksense import kb
from stacksense.kb import bindings, compliance
from stacksense.profile import Profile, derive
from stacksense.validate import validate

DEPLOY = "infrastructure.deployment_model"
CLOUD = "infrastructure.cloud_preference"
RES = "infrastructure.data_residency"
COMP = "compliance"
HYPER = {"aws", "gcp", "azure"}
INFRA = {"hosting", "database", "cache", "queue", "storage", "cdn", "search", "ml", "observability"}
SELF_DEPLOY = {"self_hosted_cloud_vm", "on_premise", "air_gapped"}
ATTEST_KEY = {"gdpr": "gdpr_dpa", "hipaa": "hipaa_baa", "pci_dss": "pci_dss", "soc2": "soc2", "iso27001": "iso27001"}
CORE = ("frontend", "backend", "database", "hosting")
FRONTEND_LAYERS = {"frontend_web", "frontend_mobile", "frontend_desktop", "frontend_game"}


def profile_of(scenario_values) -> Profile:
    if isinstance(scenario_values, Profile):
        return scenario_values
    v = validate(scenario_values)
    assert not v.errors, v.errors
    return derive(v)


# ------------------------------------------------------------------ mapping components to KB
def _names():
    """(name, record, offering) for full names and their base before a parenthesis, longest first."""
    out = []
    for name, rec, off in [(r["name"], r, None) for r in kb.RECORDS] + [(o["name"], kb.get(o["engine"]), o) for o in kb.OFFERINGS]:
        out.append((name, rec, off))
        base = name.split(" (")[0].strip()
        if base and base != name:
            out.append((base, rec, off))
    return sorted(out, key=lambda t: (-len(t[0]), t[0], t[1]["id"], (t[2] or {}).get("id", "")))


def resolve(component: dict):
    """(record, offering_or_None) for one output component, or (None, None)."""
    off = None
    if component.get("offering_id"):
        off = next((o for o in kb.OFFERINGS if o["id"] == component["offering_id"]), None)
    for key in ("kb_id", "tech_id", "id"):
        rid = component.get(key)
        if isinstance(rid, str) and kb.get(rid):
            rec = kb.get(rid)
            return rec, off
    if off is not None:
        return kb.get(off["engine"]), off
    choice = component.get("choice") or ""
    for name, rec, o in _names():
        if choice == name or choice.startswith(name + " ") or choice.startswith(name + "("):
            return rec, o
    return None, None


def _components(stack: dict):
    for layer in CORE:
        c = stack.get(layer)
        for item in (c if isinstance(c, list) else [c]):
            if isinstance(item, dict):
                yield layer, item
    for item in stack.get("supporting") or []:
        if isinstance(item, dict):
            yield item.get("layer", "other"), item


# ------------------------------------------------------------------ the independent checks
def _personal(rec, layer, p) -> bool:
    if rec.get("data_at_rest"):
        return True
    if layer in FRONTEND_LAYERS:
        return False
    if layer == "backend":
        return rec.get("kind") != "none" and rec.get("saas")
    if layer == "database":
        return rec.get("kind") != "none"
    if layer == "hosting":
        rts = set(rec.get("platforms") or ()) | set(rec.get("runtime") or ())
        return p.needs_backend and bool(rts - {"static"})
    return layer not in ("cdn", "ci_cd")


def _region_ids(cells: dict, res: str) -> list:
    return [x for x in (cells or {}).get(res, []) if x != "*"]


def _attest_value(rec_or_off, regime, p):
    v = (rec_or_off.get("attest") or {}).get(ATTEST_KEY[regime], "no")
    ak = bindings.BINDINGS.get(rec_or_off["id"], (None, None))[1]
    if ak is not None:
        key = compliance.ALIASES.get(ak, ak)
        if (key, regime, p.effective_residency) in compliance.COMBINED_UNKNOWN:
            return "unknown"
    return v


def _attest_ok(regime, v) -> bool:
    if regime == "pci_dss":
        return v == "yes"
    return v == "yes" or v.startswith("plan:")


def _offering_violations(off, rec, p):
    out = []
    if off["status"] != "maintained":
        out.append(("status", f"offering {off['id']} is {off['status']}"))
    host = off["host"]
    if p.deployment in SELF_DEPLOY and host != "self_hosted":
        out.append((DEPLOY, f"{off['name']} is managed under deployment_model={p.deployment}"))
    if p.deployment == "air_gapped" and off.get("needs_internet"):
        out.append((DEPLOY, f"{off['name']} needs internet under air_gapped"))
    if p.cloud_explicit and p.cloud and host not in (p.cloud, "self_hosted"):
        out.append((CLOUD, f"{off['name']} is on {host}, cloud_preference={p.cloud}"))
    if p.cloud_preference == "none" and host in HYPER:
        out.append((CLOUD, f"{off['name']} is on {host}, cloud_preference=none"))
    if host == "self_hosted":
        return out
    res = p.effective_residency
    if res != "none" and not (res in ("india", "eu", "us") and _region_ids(off["regions"], res)):
        out.append((RES, f"{off['name']} has no verified {res} region"))
    for regime in p.compliance:
        if regime in ATTEST_KEY and not _attest_ok(regime, _attest_value(off, regime, p)):
            out.append((COMP, f"{off['name']} lacks {regime}"))
        if regime == "rbi_localisation" and not _region_ids(off["regions"], "india"):
            out.append((COMP, f"{off['name']} has no India region (rbi_localisation)"))
    return out


def record_violations(rec, layer, p, off=None):
    """List of (field, message) hard violations of one component (record plus optional offering)."""
    out = []
    if rec["status"] != "maintained":
        out.append(("status", f"{rec['name']} is {rec['status']}"))
    d, kind = p.deployment, rec.get("kind")
    self_mode = rec.get("self_hostable") and d in SELF_DEPLOY
    # deployment model
    if d in ("on_premise", "air_gapped") and not (layer == "payments" and d == "on_premise"):
        if not rec.get("self_hostable"):
            out.append((DEPLOY, f"{rec['name']} is not self-hostable under {d}"))
        if layer == "hosting" and kind not in ("onprem", "hybrid_appliance"):
            out.append((DEPLOY, f"{rec['name']} ({kind}) is not on premises under {d}"))
        if d == "air_gapped" and rec.get("needs_internet"):
            out.append((DEPLOY, f"{rec['name']} needs internet under air_gapped"))
    if d == "managed_cloud" and layer == "hosting" and kind in ("onprem", "hybrid_appliance"):
        out.append((DEPLOY, f"{rec['name']} is on-premises under managed_cloud"))
    if d == "self_hosted_cloud_vm":
        if layer == "hosting" and kind not in ("vm", "k8s", "container"):
            out.append((DEPLOY, f"{rec['name']} ({kind}) is not a VM/container host"))
        if layer not in ("hosting", "payments", "other") and rec.get("saas") and not rec.get("self_hostable"):
            out.append((DEPLOY, f"{rec['name']} is SaaS-only under self_hosted_cloud_vm"))
    # cloud
    aff = set(rec.get("cloud_affinity") or ())
    bound = layer in INFRA or (layer == "backend" and rec.get("saas") and not self_mode)
    if p.cloud_explicit and p.cloud and bound:
        if p.cloud not in aff and not ("any" in aff and (rec.get("self_hostable") or not rec.get("saas"))):
            out.append((CLOUD, f"{rec['name']} is not a {p.cloud} service"))
    if p.cloud_preference == "none" and (layer in INFRA or layer == "backend") and aff and aff <= HYPER:
        out.append((CLOUD, f"{rec['name']} needs a hyperscaler account"))
    # residency and compliance
    if off is not None:
        return out + _offering_violations(off, rec, p)
    if self_mode or not _personal(rec, layer, p):
        return out
    if layer not in CORE + tuple(FRONTEND_LAYERS) and (kind == "bundled" or "bundled_with_host" in (rec.get("caps") or ())):
        return out      # a feature of the host (built-in CDN, platform logs): the host is checked itself
    managed_offers = [o for o in kb.OFFERINGS if o["engine"] == rec["id"] and o["host"] != "self_hosted"]
    if managed_offers:
        found = [_offering_violations(o, rec, p) for o in managed_offers]
        if all(found):
            out.append((found[0][0][0], f"{rec['name']}: no managed offering satisfies the hard constraints"))
        return out
    if not rec.get("saas"):
        return out      # runs on the application host, which is checked itself
    res = p.effective_residency
    if res != "none" and not (res in ("india", "eu", "us") and _region_ids(rec["regions"], res)):
        out.append((RES, f"{rec['name']} has no verified {res} region"))
    for regime in p.compliance:
        if regime == "pci_dss" and layer not in ("backend", "database", "hosting", "payments") and not rec.get("data_at_rest"):
            continue
        if regime in ATTEST_KEY and not _attest_ok(regime, _attest_value(rec, regime, p)):
            out.append((COMP, f"{rec['name']} lacks {regime}"))
        if regime == "rbi_localisation" and (layer in ("database", "payments") or rec.get("data_at_rest")) \
                and not _region_ids(rec["regions"], "india"):
            out.append((COMP, f"{rec['name']} has no India region (rbi_localisation)"))
    return out


def _declared(output: dict, field: str) -> bool:
    for w in output.get("warnings") or []:
        if w.get("severity") == "critical" and field in (w.get("fields") or []):
            return True
    for rc in output.get("relaxed_constraints") or []:
        if field in (str(rc) if not isinstance(rc, dict) else " ".join(str(v) for v in rc.values())):
            return True
    return False


def hard_violations(scenario_values, output: dict) -> list[str]:
    """Undeclared hard violations in ``output`` (empty list = clean)."""
    stack = output.get("stack")
    if not isinstance(stack, dict):
        return []
    p = profile_of(scenario_values)
    problems = []
    for out_layer, comp in _components(stack):
        rec, off = resolve(comp)
        if rec is None:
            problems.append(f"{out_layer}: component {comp.get('choice')!r} maps to no KB record")
            continue
        layer = rec["layer"] if out_layer in ("frontend",) or out_layer in CORE else out_layer
        for field, msg in record_violations(rec, layer, p, off):
            if field == "status" or not _declared(output, field):
                problems.append(f"{out_layer}: {msg} ({field})")
    return problems


def assert_no_hard_violation(testcase, scenario_values, output: dict) -> None:
    problems = hard_violations(scenario_values, output)
    testcase.assertEqual(problems, [], "hard-constraint violations:\n" + "\n".join(problems))

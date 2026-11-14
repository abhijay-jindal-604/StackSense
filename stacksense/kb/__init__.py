"""Knowledge-base registry (plan section 4.1).

Layer modules (``frontend``, ``backend``, ``database``, ``hosting``, ``services_data``,
``services_app``, ``services_ops``) expose ``RECORDS``; ``offerings`` exposes ``OFFERINGS``.
Missing modules count as empty, so the package works while layers are still being written.
Integrity problems are collected at load time and reported by ``check()`` (and ``require_valid()``);
importing never raises for a bad record.  Records returned by this module are shared: treat as read-only.
"""
from __future__ import annotations

import hashlib
import importlib
import json

from . import model
from .model import ATTEST_KEYS, CORE_LAYERS, LAYERS, REGION_KEYS, SUPPORTING_LAYERS
from .sources import SOURCES

_RECORD_MODULES = ("frontend", "backend", "database", "hosting",
                   "services_data", "services_app", "services_ops")

# Minimum maintained candidates per layer (plan 4.2, 4.3).
MIN_COUNTS = {
    "frontend_web": 13, "frontend_mobile": 8, "frontend_desktop": 5, "frontend_game": 4,
    "backend": 25, "database": 20, "hosting": 30,
    **{layer: 4 for layer in SUPPORTING_LAYERS},
}


# Host families an offering may name: the hosts actually used in kb.offerings. The cloud hyperscalers must match the
# ``underlying_cloud`` of hosting records (cross-checked in integrity_problems); the rest are managed-database vendors.
HOST_FAMILIES = ("atlas", "aura", "aws", "azure", "clickhouse_cloud", "cloudflare", "cockroach_cloud", "digitalocean",
                 "fly", "gcp", "neon", "self_hosted", "snowflake", "supabase", "tiger_cloud")


def _attest_ok(v) -> bool:
    return isinstance(v, str) and (v in ("yes", "no", "self") or (v.startswith("plan:") and len(v) > 5))


def _load(name: str, attr: str) -> list:
    try:
        mod = importlib.import_module(f"{__package__}.{name}")
    except ImportError as exc:
        if exc.name != f"{__package__}.{name}":
            raise  # the module exists but one of its own imports is broken
        return []
    return list(getattr(mod, attr, []))


def _collect():
    records = []
    for name in _RECORD_MODULES:
        records.extend(_load(name, "RECORDS"))
    offers = _load("offerings", "OFFERINGS")
    return (tuple(sorted(records, key=lambda r: (r["layer"], r["id"]))),
            tuple(sorted(offers, key=lambda r: r["id"])))


RECORDS, OFFERINGS = _collect()
_BY_ID = {}
for _r in RECORDS:
    _BY_ID.setdefault(_r["id"], _r)


def _source_problems(owner: str, keys) -> list[str]:
    return [f"{owner}: unknown source key {k!r}" for k in keys if k not in SOURCES]


def integrity_problems() -> list[str]:
    """Load-time integrity checks of plan 4.1 (everything except minimum counts)."""
    p: list[str] = []
    seen: dict[str, int] = {}
    for r in RECORDS:
        seen[r["id"]] = seen.get(r["id"], 0) + 1
        p.extend(model.record_problems(r))
        p.extend(_source_problems(r["id"], r.get("sources", [])))
        p.extend(_source_problems(r["id"], [f["source_key"] for f in r.get("facts", [])]))
    p.extend(f"duplicate record id {i!r}" for i, n in sorted(seen.items()) if n > 1)
    oseen: dict[str, int] = {}
    for o in OFFERINGS:
        oseen[o["id"]] = oseen.get(o["id"], 0) + 1
        p.extend(_source_problems(o["id"], o.get("sources", [])))
        p.extend(_source_problems(o["id"], [f["source_key"] for f in o.get("facts", [])]))
        p.extend(model.cost_problems(o.get("cost", {})))
        if o["host"] not in HOST_FAMILIES:
            p.append(f"offering {o['id']}: host {o['host']!r} is not in HOST_FAMILIES")
        p.extend(f"offering {o['id']}: regions group {g!r} unknown" for g in sorted(o.get("regions", {})) if g not in REGION_KEYS)
        p.extend(f"offering {o['id']}: attest {k}={v!r} invalid" for k, v in sorted(o.get("attest", {}).items())
                 if k not in ATTEST_KEYS or not _attest_ok(v))
        if o["engine"] not in _BY_ID:
            p.append(f"offering {o['id']}: engine {o['engine']!r} is not a KB record")
    p.extend(f"duplicate offering id {i!r}" for i, n in sorted(oseen.items()) if n > 1)
    for r in RECORDS:
        uc = r.get("underlying_cloud")
        if r["layer"] == "hosting" and uc and uc not in HOST_FAMILIES:
            p.append(f"{r['id']}: underlying_cloud {uc!r} is not in HOST_FAMILIES")
    return p


def counts() -> dict:
    out = {layer: 0 for layer in LAYERS}
    for r in RECORDS:
        if r["status"] == "maintained":
            out[r["layer"]] += 1
    return out


def minimum_count_problems(layers=None) -> list[str]:
    c = counts()
    return [f"layer {layer}: {c[layer]} maintained records, below minimum count {n}"
            for layer, n in MIN_COUNTS.items() if c[layer] < n and (layers is None or layer in layers)]


def consistency_problems() -> list[str]:
    """Region/attestation cells must equal kb.regions / kb.compliance for every bound id, and every record or
    offering that claims a vendor attestation or a concrete region list must be bound (kb.bindings)."""
    from . import bindings
    p: list[str] = []
    for r in list(RECORDS) + list(OFFERINGS):
        b = bindings.BINDINGS.get(r["id"])
        if b is None:
            claims = sorted(k for k, v in r["attest"].items() if v == "yes" or v.startswith("plan:"))
            regs = sorted(g for g, v in r["regions"].items() if v and v != ["*"])
            if claims or regs:
                p.append(f"{r['id']}: claims {claims or regs} but has no kb.bindings entry")
            continue
        rk, ak = b
        if rk is not None and r["regions"] != bindings.regions_dict(rk):
            p.append(f"{r['id']}: regions differ from kb.regions:{rk}")
        if ak is not None and r["attest"] != bindings.attest_dict(ak):
            p.append(f"{r['id']}: attest differs from kb.compliance:{ak}")
    return p


def check(core_only: bool = False) -> list[str]:
    """All problems: integrity (incl. sources), region/attestation consistency, then minimum counts.
    ``core_only`` limits the minimum-count check to the core layers (supporting layers are Phase 3)."""
    return (integrity_problems() + consistency_problems()
            + minimum_count_problems(CORE_LAYERS if core_only else None))


def require_valid() -> None:
    probs = integrity_problems()
    if probs:
        raise ValueError("knowledge base integrity: " + "; ".join(probs[:10]))


def by_layer(layer: str) -> list:
    return sorted((r for r in RECORDS if r["layer"] == layer), key=lambda r: r["id"])


def get(record_id: str):
    return _BY_ID.get(record_id)


def export_body() -> dict:
    return {
        "schema": 1,
        "records": json.loads(json.dumps(list(RECORDS))),
        "offerings": json.loads(json.dumps(list(OFFERINGS))),
        "sources": {k: list(SOURCES[k]) for k in sorted(SOURCES)},
    }


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def kb_version() -> str:
    return hashlib.sha256(_canonical(export_body()).encode("ascii")).hexdigest()[:12]


def export() -> dict:
    body = export_body()
    return {"kb_version": hashlib.sha256(_canonical(body).encode("ascii")).hexdigest()[:12], **body}


def stats() -> dict:
    c = counts()
    allc = {layer: 0 for layer in LAYERS}
    for r in RECORDS:
        allc[r["layer"]] += 1
    used = set()
    for r in list(RECORDS) + list(OFFERINGS):
        used.update(r.get("sources", []))
        used.update(f["source_key"] for f in r.get("facts", []))
    return {
        "kb_version": kb_version(),
        "records": len(RECORDS),
        "offerings": len(OFFERINGS),
        "sources_registered": len(SOURCES),
        "sources_cited_by_records": len(used & set(SOURCES)),
        "maintained_per_layer": c,
        "total_per_layer": allc,
        "minimum_per_layer": dict(MIN_COUNTS),
        "non_maintained": sorted(r["id"] for r in RECORDS if r["status"] != "maintained"),
    }

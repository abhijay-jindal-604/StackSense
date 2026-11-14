"""Single source of truth for region and attestation cells of records and offerings.

``BINDINGS`` maps a record or offering id to ``(region_key, attest_key)``: keys of ``kb.regions.ENTRIES`` and
``kb.compliance.ATTEST``. Layer modules call ``bind()`` on their lists at import time, which overwrites the
``regions`` and ``attest`` dicts from those two modules, replaces any hand-written region/attestation facts
with generated ones citing the same sources, and adds those source keys to ``sources``. A record therefore
cannot carry a region or attestation value that ``regions.py``/``compliance.py`` does not hold
(``tests/test_kb_consistency.py`` checks this and that every record making a vendor claim is bound).

Conversion (fail closed): ``UNKNOWN`` region -> ``[]``; ``unknown`` and ``na`` attestations -> ``no``.
Either key may be ``None`` to bind only the other half.
"""
from __future__ import annotations

import re

from . import compliance, regions
from .model import ATTEST_KEYS, REGION_KEYS, fact

# model attest key (kb.model.ATTEST_KEYS) -> compliance regime name used by kb.compliance.attestation()
ATTEST_MAP = {"hipaa_baa": "hipaa", "pci_dss": "pci_dss", "soc2": "soc2", "iso27001": "iso27001", "gdpr_dpa": "gdpr"}

_S = "self_hosted"
BINDINGS = {
    # ---- hosting
    "cloudflare_pages": ("cloudflare", "cloudflare"),
    "cloudflare_workers_host": ("cloudflare", "cloudflare"),
    "netlify": ("netlify", "netlify"),
    "vercel": ("vercel", "vercel"),
    "azure_static_web_apps": ("azure_static_web_apps", "azure_static_web_apps"),
    "aws_amplify": ("aws", "aws_amplify"),
    "firebase_app_hosting": ("firebase_app_hosting", "firebase_app_hosting"),
    "render": ("render", "render"),
    "railway": ("railway", "railway"),
    "fly_io": ("fly", "fly"),
    "do_app_platform": ("digitalocean", "digitalocean"),
    "azure_app_service": ("azure_mainstream", "azure_app_service"),
    "google_cloud_run": ("gcp", "gcp_cloud_run"),
    "supabase_cloud": ("supabase", "supabase"),
    "aws_ecs_fargate": ("aws", "aws_ecs_fargate"),
    "aws_lambda_host": ("aws", "aws_lambda"),
    "aws_app_runner": ("aws", "aws_app_runner"),
    "azure_container_apps": ("azure_container_apps", "azure_container_apps"),
    "amazon_eks": ("aws", "aws_eks"),
    "gke_autopilot": ("gcp", "gcp_gke"),
    "azure_aks": ("azure_foundational", "azure_aks"),
    "do_droplets_compose": ("digitalocean", "digitalocean"),
    "hetzner_compose": ("hetzner", "hetzner"),
    "amazon_ec2_lightsail": ("aws", "aws_ec2_lightsail"),
    "azure_virtual_machines": ("azure_foundational", "azure_vms"),
    "google_compute_engine": ("gcp", "gcp_gce"),
    "aws_outposts": (_S, "aws_outposts"),
    "azure_local": (_S, "azure_local"),
    "google_distributed_cloud": (_S, "google_distributed_cloud"),
    "shopify_hosted": (None, "shopify"),
    # ---- backend
    "aws_lambda_apigw": ("aws", "aws_lambda"),
    "azure_functions": ("azure_mainstream", "azure_functions"),
    "cloudflare_workers_hono": ("cloudflare", "cloudflare"),
    "firebase": ("firebase_auth", "firebase_auth"),
    "gcp_cloud_run_functions": ("gcp", "gcp_cloud_run_functions"),
    "supabase": ("supabase", "supabase"),
    "shopify": (None, "shopify"),
    "appwrite": ("appwrite", "appwrite"),
    # ---- database records
    "bigquery": ("gcp", "gcp_bigquery"),
    "cloudflare_d1": ("cloudflare_d1", "cloudflare"),
    "cosmosdb": ("azure_foundational", "azure_cosmosdb"),
    "dynamodb": ("aws", "aws_dynamodb"),
    "firestore": ("firestore", "firestore"),
    # ---- offerings
    "bigquery__gcp": ("gcp", "gcp_bigquery"),
    "cloudflare_d1__cloudflare": ("cloudflare_d1", "cloudflare"),
    "cosmosdb__azure": ("azure_foundational", "azure_cosmosdb"),
    "dynamodb__aws": ("aws", "aws_dynamodb"),
    "firestore__gcp": ("firestore", "firestore"),
    "mariadb__aws": ("aws", "aws_rds"),
    "mysql__aws": ("aws", "aws_rds"),
    "postgres__aws": ("aws", "aws_rds"),
    "sqlserver__aws": ("aws", "aws_rds"),
    "mongodb__atlas": ("mongodb_atlas", "mongodb_atlas"),
    "mongodb__digitalocean": ("digitalocean", "digitalocean"),
    "mysql__digitalocean": ("digitalocean", "digitalocean"),
    "postgres__digitalocean": ("digitalocean", "digitalocean"),
    "mysql__azure": ("azure_mysql", "azure_mysql"),
    "postgres__azure": ("azure_postgres", "azure_postgres"),
    "sqlserver__azure": ("azure_foundational", "azure_sql"),
    "mysql__gcp": ("gcp", "gcp_cloud_sql"),
    "postgres__gcp": ("gcp", "gcp_cloud_sql"),
    "postgres__fly": ("fly_managed_postgres", "fly"),
    "postgres__neon": ("neon", "neon"),
    "timescaledb__tiger_cloud": ("tiger_cloud", "tiger_cloud"),
    "postgres__supabase": ("supabase", "supabase"),
}

# Hand-written facts that restate a region or attestation cell are replaced by generated ones: those whose text starts
# with "Region:"/"Attestation:", or that open with a regime name and cite one of the binding's region/attestation
# source keys. Other facts
# (caveats such as "functions default to iad1, pin to bom1") are kept even when they mention regions or India.
_CLAIM = re.compile(r"^(Region|Attestation)\b")
# A fact that merely opens with a regime name and cites a region/attestation source also restates a cell
# ("HIPAA is available on higher plans ..."); a caveat opening differently is kept.
_RESTATES = re.compile(r"^(HIPAA|BAA|SOC ?2?\b|ISO ?27001|PCI|GDPR|DPA)")


def _claim_sources(rk, ak) -> set:
    out = set()
    if rk is not None:
        out.update(regions.ENTRIES[regions.ALIASES.get(rk, rk)]["sources"])
    if ak is not None:
        out.update(compliance.ATTEST[compliance.ALIASES.get(ak, ak)]["sources"])
    return out


def regions_dict(key) -> dict:
    """Model ``regions`` dict for a ``kb.regions`` key (UNKNOWN -> [])."""
    out = {}
    for g in REGION_KEYS:
        v = regions.regions_for(key, g)
        out[g] = [] if v == regions.UNKNOWN else list(v)
    return out


def attest_dict(key) -> dict:
    """Model ``attest`` dict for a ``kb.compliance`` key (unknown/na -> no)."""
    out = {}
    for mk in ATTEST_KEYS:
        v = compliance.attestation(key, ATTEST_MAP[mk])
        out[mk] = v if v in ("yes", "self", "no") or v.startswith("plan:") else "no"
    return out


def _fmt(v):
    return ", ".join(v) if v else "none"


def _region_fact(key):
    e = regions.ENTRIES[regions.ALIASES.get(key, key)]
    r = regions_dict(key)
    unk = [g for g in REGION_KEYS if e["residency"][g] == regions.UNKNOWN]
    txt = "Region (kb.regions:%s): india %s; eu %s; us %s." % (key, _fmt(r["india"]), _fmt(r["eu"]), _fmt(r["us"]))
    if unk:
        txt += " Unverified (fail closed): %s." % ", ".join(unk)
    if e.get("note"):
        txt += " " + e["note"]
    return txt, list(e["sources"])


def _attest_fact(key):
    row = compliance.ATTEST[compliance.ALIASES.get(key, key)]
    a = attest_dict(key)
    raw = {mk: compliance.attestation(key, ATTEST_MAP[mk]) for mk in ATTEST_KEYS}
    unk = [mk for mk in ATTEST_KEYS if raw[mk] in ("unknown", "na")]
    txt = "Attestation (kb.compliance:%s): %s." % (key, ", ".join("%s=%s" % (k, a[k]) for k in ATTEST_KEYS))
    if unk:
        txt += " Not confirmed on an official page, recorded as no (fail closed): %s." % ", ".join(unk)
    if row.get("note"):
        txt += " " + row["note"]
    return txt, list(row["sources"])


def _apply(rec: dict) -> dict:
    rk, ak = BINDINGS[rec["id"]]
    claim_src = _claim_sources(rk, ak)
    facts = [f for f in rec["facts"] if not (_CLAIM.search(f["text"])
                                             or (f["source_key"] in claim_src and _RESTATES.search(f["text"])))]
    srcs = set(rec["sources"])
    new = []
    if rk is not None:
        rec["regions"] = regions_dict(rk)
        txt, s = _region_fact(rk)
        if s:
            new.append(fact(txt, s[0], "V"))
            srcs.update(s)
    if ak is not None:
        rec["attest"] = attest_dict(ak)
        txt, s = _attest_fact(ak)
        if s:
            new.append(fact(txt, s[0], "V"))
            srcs.update(s)
    rec["facts"] = new + facts
    rec["sources"] = sorted(srcs)
    return rec


def bind(items: list) -> list:
    """Apply BINDINGS to every bound record/offering in ``items`` (in place); returns the list."""
    for rec in items:
        if rec["id"] in BINDINGS:
            _apply(rec)
    return items

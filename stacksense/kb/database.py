"""Database layer records (plan 4.2 "Database (20)", 4.4, 4.5, 5.3 rows 14/16).

20 maintained engines + ``none`` + non-maintained records kept so they can be explained.

Attribute rubric (plan 4.1): ``popularity`` and ``ecosystem`` from DB-Engines rank and the Stack Overflow
Developer Survey 2025 usage table; ``ops_burden`` from what the vendor's shared-responsibility page leaves
to the customer when the engine is run self-managed (managed offerings in ``offerings.py`` lower it);
``security`` from built-in features (RLS, encryption, audit); ``cost_efficiency`` from list prices at the S and M
size classes. Scores are the author's judgement; a one-sentence rationale for every non-obvious score is in
``facts`` (confidence K = judgement, not a vendor fact). Nothing here is tuned to a particular scenario.

Region and attestation convention: an engine record carries the regions/attestations of the way the engine is
available *without* choosing a managed product (self-hosted: ``["*"]`` / ``self``; proprietary services: that
service's own). Managed products of open engines live in ``offerings.py`` with their own regions and attestations.
Anything not confirmed on an official page is ``[]`` (no region) or ``no`` (no attestation): fail closed.

Versions (D14, checked 2026-11-13 on endoflife.date): PostgreSQL 17 (to 2029-11-08; 18 is current but 17 has the
broadest managed availability), MySQL 8.4 LTS (to 2032-04-30), MariaDB 11.8 LTS (to 2028-06-04), MongoDB 8.0
(to 2029-10-31), SQL Server 2022 (to 2033-01-11; 2025 exists, 2022 has wider managed availability).
"""
from __future__ import annotations

from . import compliance, regions as _regions
from .model import fact, tech

_ATTEST_MAP = {"hipaa_baa": "hipaa", "pci_dss": "pci_dss", "soc2": "soc2", "iso27001": "iso27001", "gdpr_dpa": "gdpr"}


def attest_from(vendor: str, **override) -> dict:
    """Model ``attest`` dict from kb.compliance for ``vendor``; ``unknown``/``na`` fail closed as ``no``.
    ``override`` replaces single cells (model keys: hipaa_baa pci_dss soc2 iso27001 gdpr_dpa)."""
    out = {}
    for mk, ck in _ATTEST_MAP.items():
        v = compliance.attestation(vendor, ck)
        out[mk] = v if v in ("yes", "self", "no") or v.startswith("plan:") else "no"
    out.update(override)
    return out


def regions_from(provider: str, only=None) -> dict:
    """``regions`` dict (india/eu/us) from kb.regions; ``UNKNOWN`` becomes ``[]`` (fail closed)."""
    out = {}
    for k in ("india", "eu", "us"):
        r = _regions.regions_for(provider, k) if (only is None or k in only) else []
        out[k] = [] if r == _regions.UNKNOWN else list(r)
    return out


SELF = {"hipaa_baa": "self", "pci_dss": "self", "soc2": "self", "iso27001": "self", "gdpr_dpa": "self"}
ANYWHERE = {"india": ["*"], "eu": ["*"], "us": ["*"]}
_ATTRS = ("cost_efficiency", "dev_velocity", "scalability", "performance", "maintainability", "security",
          "ecosystem", "learning_curve", "popularity")


def _a(*vals):
    return dict(zip(_ATTRS, vals))


def _db(id, name, kind, attrs, ops, floor, ceil, cost, **kw):
    kw.setdefault("data_at_rest", True)
    kw.setdefault("self_hostable", True)
    kw.setdefault("saas", False)
    kw.setdefault("needs_internet", False)
    kw.setdefault("regions", ANYWHERE)
    kw.setdefault("attest", SELF)
    kw.setdefault("region_selectable", True)
    kw.setdefault("runtime", None)
    src = set(kw.pop("sources", ())) | {"db_engines", "so_survey_2025"}
    return tech(id, name, "database", kind, attrs=attrs, ops_burden=ops, scale_floor=floor, scale_ceiling=ceil,
                cost=cost, sources=sorted(src), **kw)


def _self_facts(extra_src):
    return [
        fact("Region: self-managed, so it runs in whichever region or data centre the team deploys to (no vendor region limit).",
             "db_engines", "U"),
        fact("Attestation: self-managed; compliance controls (encryption, audit, backups, BAA with the hosting provider) are the team's responsibility.",
             extra_src, "U"),
    ]


_FREE = {"limit": "Open-source engine; you pay only for the machine or the managed offering", "commercial_use": True}

RECORDS = [
    _db("postgres", "PostgreSQL", "relational",
        _a(4, 4, 4, 4, 5, 5, 5, 4, 5), 2, "xs", "xl",
        {"xs": (0, 25), "s": (15, 120), "m": (100, 600), "l": (500, 3000)},
        free_tier=_FREE, open_source=True, licence="PostgreSQL License", current_major="17", supported_until="2029-11-08",
        cloud_affinity=["any"], lock_in=0,
        caps=["acid", "fts_builtin", "geo", "json", "multi_az", "read_replicas", "rls_multi_tenant", "vector", "admin_ui"],
        best_for=["saas_b2b", "ecommerce", "fintech", "healthtech", "marketplace", "web_app", "internal_tool", "api_platform", "ai_ml_product", "social"],
        avoid_for=[],
        strengths=["ACID relational core with JSONB, full-text search (tsvector, pg_trgm), PostGIS and pgvector in one engine",
                   "Row-level security supports multi-tenant isolation inside the database",
                   "Available as a managed service on every hyperscaler, DigitalOcean, Supabase and Neon, so lock-in is low"],
        tradeoffs=["Single-writer: write scaling beyond one node needs partitioning, Citus or a distributed SQL engine",
                   "Connection-per-process model needs a pooler (PgBouncer, RDS Proxy) for serverless callers"],
        facts=_self_facts("postgres_docs") + [
            fact("Version: PostgreSQL 17 is supported until 8 Nov 2029 and 18 until 14 Nov 2030; 14 reached end of life on 12 Nov 2026, so 17 is named for broadest managed availability.", "eol_postgresql", "V"),
            fact("Score rationale: popularity 5 and ecosystem 5 because PostgreSQL is the most used database in the 2025 Stack Overflow survey and a top-4 DB-Engines system.", "so_survey_2025", "U"),
            fact("Score rationale: write scalability and performance 4 (not 5) because a single primary handles writes; reads scale with replicas.", "postgres_docs", "K"),
        ],
        sources=["postgres_docs", "eol_postgresql", "pg_versioning", "pg_fts", "pg_rls", "pgvector", "postgis"]),

    _db("mysql", "MySQL", "relational",
        _a(4, 4, 4, 4, 4, 4, 5, 4, 5), 2, "xs", "xl",
        {"xs": (0, 25), "s": (15, 120), "m": (100, 600), "l": (500, 3000)},
        free_tier=_FREE, open_source=True, licence="GPL-2.0 (Community Edition)", current_major="8.4", supported_until="2032-04-30",
        lock_in=0, caps=["acid", "fts_builtin", "json", "multi_az", "read_replicas", "admin_ui"],
        best_for=["content_site", "ecommerce", "web_app", "marketplace", "internal_tool", "social"],
        avoid_for=["data_analytics"],
        strengths=["Very widely deployed with first-class hosting on shared and managed platforms",
                   "Mature replication and read-replica story; 8.4 is an LTS release supported to April 2032"],
        tradeoffs=["No row-level security; multi-tenant isolation is application-enforced",
                   "Weaker built-in analytics, geospatial and vector features than PostgreSQL",
                   "MySQL 8.0 reached community end of life on 30 Apr 2026, so only 8.4 LTS or newer is named"],
        facts=_self_facts("mysql_docs") + [
            fact("Version: MySQL 8.4 is an LTS release with end of life 30 Apr 2032; 8.0 reached end of life 30 Apr 2026.", "eol_mysql", "V"),
            fact("Score rationale: security 4 and not 5 because it lacks native row-level security.", "mysql_docs", "K"),
        ],
        sources=["mysql_docs", "eol_mysql", "dbs_mysql_84"]),

    _db("mariadb", "MariaDB", "relational",
        _a(4, 4, 3, 3, 4, 4, 3, 4, 3), 2, "xs", "l",
        {"xs": (0, 25), "s": (15, 100), "m": (100, 500), "l": (500, 2500)},
        free_tier=_FREE, open_source=True, licence="GPL-2.0", current_major="11.8", supported_until="2028-06-04",
        lock_in=0, caps=["acid", "fts_builtin", "json", "multi_az", "read_replicas"],
        best_for=["content_site", "ecommerce", "web_app", "internal_tool"], avoid_for=["data_analytics"],
        strengths=["Community-governed MySQL-compatible engine with permissive hosting support and Galera clustering",
                   "Drop-in for many PHP/CMS stacks"],
        tradeoffs=["Fewer first-party managed offerings than MySQL or PostgreSQL (RDS offers it; Azure, Cloud SQL and DigitalOcean do not)",
                   "Smaller ecosystem and a diverging feature set from MySQL"],
        facts=_self_facts("dbs_mariadb_docs") + [
            fact("Version: MariaDB 11.8 LTS community support to 4 Jun 2028 (11.4 LTS to 29 May 2029).", "dbs_eol_mariadb", "V"),
            fact("Score rationale: scalability and performance 3 because large write-heavy deployments are rare and tooling is thinner than PostgreSQL/MySQL.", "dbs_mariadb_docs", "K"),
        ],
        sources=["dbs_mariadb_docs", "dbs_eol_mariadb"]),

    _db("sqlserver", "Microsoft SQL Server / Azure SQL Database", "relational",
        _a(2, 4, 4, 4, 4, 4, 4, 3, 4), 2, "xs", "xl",
        {"xs": (5, 40), "s": (40, 250), "m": (250, 1500), "l": (1200, 8000)},
        free_tier={"limit": "Developer and Express editions free for non-production / 10 GB; Azure SQL free offer for small databases", "commercial_use": False},
        open_source=False, licence="proprietary (per-core or CAL licences)", current_major="2022", supported_until="2033-01-11",
        cloud_affinity=["any"], lock_in=2,
        caps=["acid", "fts_builtin", "json", "multi_az", "read_replicas", "admin_ui", "geo"],
        best_for=["internal_tool", "saas_b2b", "fintech", "healthtech", "ecommerce"], avoid_for=["gaming"],
        strengths=["Deep fit with .NET, Entra ID and existing Microsoft licences (reuse contribution)",
                   "Mature tooling: SSMS, built-in full-text search, columnstore, temporal tables"],
        tradeoffs=["Licence cost dominates at self-managed scale; open_source_only projects cannot use it",
                   "Managed offerings are tied to Azure (Azure SQL) or AWS RDS; Windows/Linux self-hosting needs a licence"],
        facts=_self_facts("sqlserver_docs") + [
            fact("Version: SQL Server 2022 is supported to 11 Jan 2033; 2025 (released 18 Nov 2025) to 6 Jan 2036; 2019 reached end of mainstream support on 28 Feb 2025 (extended to 8 Jan 2030).", "eol_mssql", "V"),
            fact("Score rationale: cost_efficiency 2 because per-core licensing makes it the most expensive relational option except where a licence is already owned.", "sqlserver_docs", "K"),
        ],
        sources=["sqlserver_docs", "eol_mssql", "ms_sql2019_lifecycle", "ms_lifecycle"]),

    _db("sqlite", "SQLite", "embedded",
        _a(5, 5, 2, 4, 4, 3, 5, 5, 5), 0, "xs", "s",
        {"xs": (0, 0), "s": (0, 10)},
        free_tier=_FREE, open_source=True, licence="Public domain", saas=False, lock_in=0,
        caps=["acid", "embedded", "fts_builtin", "json", "offline", "low_end_devices"],
        best_for=["internal_tool", "content_site", "iot"], avoid_for=["fintech", "marketplace", "social", "data_analytics"],
        strengths=["Zero-administration single-file database that also runs on-device for offline apps",
                   "Excellent read performance and the most deployed database engine in the world"],
        tradeoffs=["Single-writer, single-node: not suitable for concurrent multi-server writes or size >= m",
                   "No built-in network access, row-level security or replication (needs Litestream/LiteFS or a sync layer)"],
        facts=_self_facts("sqlite_docs") + [
            fact("Score rationale: ops_burden 0 and learning_curve 5 because there is no server process, but scalability 2 because of the single-writer limit.", "sqlite_docs", "K"),
        ],
        sources=["sqlite_docs"]),

    _db("cloudflare_d1", "Cloudflare D1", "relational",
        _a(5, 4, 2, 3, 3, 3, 3, 4, 2), 0, "xs", "s",
        {"xs": (0, 5), "s": (0, 30)},
        free_tier={"limit": "Workers Free plan includes a small D1 allowance; per-database size cap applies", "commercial_use": True},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["independent"], underlying_cloud=None, lock_in=2,
        regions=regions_from("cloudflare_d1"), region_selectable=False,
        attest=attest_from("cloudflare", hipaa_baa="no", gdpr_dpa="no"),
        caps=["acid", "edge", "scale_to_zero", "read_replicas", "json", "fts_builtin"],
        best_for=["content_site", "web_app", "internal_tool"], avoid_for=["fintech", "healthtech", "data_analytics", "marketplace"],
        strengths=["Serverless SQLite at the edge with zero idle cost and native binding from Workers",
                   "Read replication reaches users globally without managing replicas"],
        tradeoffs=["Per-database size and write-throughput limits; not a system of record for larger data",
                   "No India jurisdiction: excluded for personal data under data_residency=india",
                   "Usable only from Cloudflare Workers/Pages (or its HTTP API), a strong lock-in"],
        facts=[
            fact("Region: D1 jurisdictions are eu, fedramp and us (set at creation only); location hints such as apac are best effort; there is no India jurisdiction, so the india list is empty.", "rf_cf_d1_location", "V"),
            fact("Attestation: Cloudflare holds SOC 2, ISO 27001 and PCI DSS L1 (blog); a HIPAA BAA and GDPR DPA for D1 were not confirmed on an official page, so both are recorded as no (fail closed).", "rf_cf_certs", "V"),
            fact("Score rationale: scalability 2 and ceiling s because each database has a hard size cap and a single write location.", "dbs_d1_docs", "K"),
        ],
        sources=["dbs_d1_docs", "rf_cf_d1_location", "rf_cf_certs", "cf_workers"]),

    _db("cockroachdb", "CockroachDB", "relational",
        _a(2, 3, 5, 4, 3, 4, 3, 2, 3), 3, "s", "xl",
        {"s": (0, 300), "m": (300, 1500), "l": (1500, 8000)},
        free_tier={"limit": "Self-hosted core under CockroachDB Software License; Cloud has a free Basic tier", "commercial_use": False},
        open_source=False, licence="CockroachDB Software License (source-available)", lock_in=1,
        caps=["acid", "distributed_sql", "multi_az", "multi_region", "geo", "write_scaling", "rls_multi_tenant"],
        best_for=["fintech", "saas_b2b", "marketplace", "api_platform"], avoid_for=["content_site", "internal_tool"],
        strengths=["PostgreSQL-compatible distributed SQL with serializable isolation and multi-region survivability",
                   "Horizontal write scaling without manual sharding"],
        tradeoffs=["Not open source (source-available licence), which fails open_source_only",
                   "Higher latency per write (consensus) and more operational complexity than a single PostgreSQL node",
                   "Over-engineered below size s"],
        facts=_self_facts("cockroach_docs") + [
            fact("Score rationale: cost_efficiency 2 and learning_curve 2 because a three-node minimum and distributed-systems tuning are required.", "cockroach_docs", "K"),
        ],
        sources=["cockroach_docs"]),

    _db("yugabytedb", "YugabyteDB", "relational",
        _a(3, 3, 5, 4, 3, 4, 2, 2, 2), 4, "m", "xl",
        {"m": (300, 1500), "l": (1500, 8000)},
        free_tier=_FREE, open_source=True, licence="Apache-2.0 (core)", lock_in=0,
        caps=["acid", "distributed_sql", "multi_az", "multi_region", "geo", "write_scaling"],
        best_for=["fintech", "saas_b2b", "api_platform"], avoid_for=["content_site", "internal_tool", "web_app"],
        strengths=["Open-source distributed SQL reusing the PostgreSQL query layer",
                   "Horizontal scale and geo-distribution for multi-region write workloads"],
        tradeoffs=["Needs a cluster and dedicated operations skills; over-engineered below size m",
                   "Smaller community than PostgreSQL or CockroachDB"],
        facts=_self_facts("dbs_yugabyte_docs") + [
            fact("Score rationale: ops_burden 4 because you run the control plane yourself unless you buy the vendor cloud.", "dbs_yugabyte_docs", "K"),
        ],
        sources=["dbs_yugabyte_docs"]),

    _db("mongodb", "MongoDB", "document",
        _a(3, 5, 5, 4, 3, 4, 5, 4, 5), 2, "xs", "xl",
        {"xs": (0, 25), "s": (10, 150), "m": (100, 800), "l": (700, 4000)},
        free_tier={"limit": "Atlas M0 shared cluster (512 MB)", "commercial_use": True},
        saas=True, self_hostable=True, open_source=False, licence="SSPL (server); Atlas is a commercial service",
        current_major="8.0", supported_until="2029-10-31", lock_in=1,
        caps=["fts_builtin", "geo", "json", "multi_az", "multi_region", "read_replicas", "vector", "write_scaling", "admin_ui"],
        best_for=["content_site", "ecommerce", "iot", "social", "realtime_collab", "web_app", "data_analytics"],
        avoid_for=["fintech"],
        strengths=["Flexible document model that speeds early iteration and fits nested content, catalogues and event data",
                   "Atlas Search and Vector Search cover full-text and RAG use cases inside one service",
                   "Native sharding for horizontal scale"],
        tradeoffs=["Server licence is SSPL, which is not an OSI open-source licence (fails open_source_only)",
                   "Multi-document transactions exist but relational integrity is app-enforced",
                   "MongoDB 6.0 and earlier are end of life; 8.0 is named"],
        facts=_self_facts("mongodb_docs") + [
            fact("Region: MongoDB Atlas AWS regions verified today include AP_SOUTH_1 (Mumbai), AP_SOUTH_2 (Hyderabad), EU_CENTRAL_1 and US_EAST_1; Azure and GCP Atlas regions were not checked.", "rf_atlas_aws_regions", "V"),
            fact("Version: MongoDB 8.0 is supported to 31 Oct 2029, 7.0 to 31 Aug 2027; 6.0 reached end of life on 31 Jul 2025.", "eol_mongodb", "V"),
            fact("Score rationale: dev_velocity 5 because schema-less documents remove migrations for early-stage products; maintainability 3 because unconstrained schemas drift.", "mongodb_docs", "K"),
        ],
        sources=["mongodb_docs", "eol_mongodb", "dbs_mongodb_lifecycle", "atlas_compliance", "atlas_pricing", "rf_atlas_aws_regions"]),

    _db("dynamodb", "Amazon DynamoDB", "kv",
        _a(4, 3, 5, 5, 3, 4, 4, 2, 4), 0, "xs", "xl",
        {"xs": (0, 10), "s": (5, 100), "m": (50, 800), "l": (500, 6000)},
        free_tier={"limit": "25 GB storage and 25 provisioned RCU/WCU always free", "commercial_use": True},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["aws"], underlying_cloud="aws", lock_in=3,
        regions=regions_from("aws"), region_selectable=True,
        attest=attest_from("aws", pci_dss="yes", soc2="yes"),
        caps=["multi_az", "multi_region", "scale_to_zero", "write_scaling", "read_replicas", "lsm_writes", "json"],
        best_for=["iot", "gaming", "social", "api_platform", "ecommerce", "realtime_collab"],
        avoid_for=["data_analytics", "fintech", "internal_tool"],
        strengths=["Fully managed key-value/document store with single-digit-millisecond reads at any scale and no servers to size",
                   "Global tables give multi-region active-active; on-demand mode scales to zero cost at idle"],
        tradeoffs=["Access patterns must be designed up front; ad-hoc queries, joins and strong relational integrity are not supported",
                   "Proprietary API with no drop-in replacement (lock_in 3), AWS only"],
        facts=[
            fact("Region: DynamoDB has service endpoints in ap-south-1 (Mumbai), ap-south-2 (Hyderabad), eu-central-1, eu-west-1 and us-east-1 among others.", "dbs_ddb_endpoints", "V"),
            fact("Attestation: DynamoDB is HIPAA-eligible (AWS reference), in scope for PCI DSS and for SOC reports (service lists), under the AWS DPA for GDPR.", "rf_aws_hipaa", "V"),
            fact("Score rationale: learning_curve 2 because single-table design and capacity modelling are non-obvious; performance 5 for predictable low-latency key lookups.", "dynamodb_docs", "K"),
        ],
        sources=["dynamodb_docs", "dbs_ddb_endpoints", "rf_aws_hipaa", "rf_aws_pci", "dbs_aws_soc_scope", "rf_aws_gdpr"]),

    _db("firestore", "Cloud Firestore", "document",
        _a(4, 5, 4, 4, 3, 4, 4, 4, 4), 0, "xs", "l",
        {"xs": (0, 10), "s": (5, 100), "m": (50, 800), "l": (500, 5000)},
        free_tier={"limit": "Spark/free quota: 1 GiB storage, 50k reads and 20k writes per day", "commercial_use": True},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["gcp"], underlying_cloud="gcp", lock_in=3,
        regions=regions_from("firestore"), region_selectable=True,
        attest=attest_from("firestore", pci_dss="no", soc2="yes", iso27001="yes", gdpr_dpa="no"),
        caps=["offline", "multi_az", "multi_region", "scale_to_zero", "websocket", "geo", "vector", "low_end_devices"],
        best_for=["realtime_collab", "social", "gaming", "web_app", "iot"],
        avoid_for=["fintech", "data_analytics", "ecommerce"],
        strengths=["Real-time listeners and an offline-capable mobile/web SDK come built in",
                   "Serverless, scales to zero, and the location (including Mumbai and Delhi) is chosen at creation"],
        tradeoffs=["Limited query model: no joins or ad-hoc aggregation, and costs scale with document reads",
                   "Proprietary API; database location cannot be changed after creation",
                   "Firebase Realtime Database is not offered: it has regional limits and fewer controls under residency constraints"],
        facts=[
            fact("Region: Firestore locations include asia-south1 (Mumbai), asia-south2 (Delhi), eur3 and several single EU regions, nam5 and us-central1; the location is fixed at creation.", "rf_firestore_locations", "V"),
            fact("Attestation: Firestore is on the Google Cloud HIPAA covered-products list; SOC 2 and ISO 27001 are recorded for Firebase services; PCI DSS and a GDPR DPA were not confirmed for Firestore specifically, so they are no (fail closed).", "rf_gcp_hipaa", "V"),
            fact("Score rationale: dev_velocity 5 because SDKs give sync, offline and auth integration with no backend code.", "firestore_docs", "K"),
        ],
        sources=["firestore_docs", "rf_firestore_locations", "rf_gcp_hipaa", "rf_firebase_privacy", "firebase_pricing", "dbs_firestore_editions"]),

    _db("cosmosdb", "Azure Cosmos DB", "document",
        _a(2, 4, 5, 5, 3, 4, 3, 3, 3), 0, "xs", "xl",
        {"xs": (0, 25), "s": (25, 250), "m": (250, 2000), "l": (1500, 12000)},
        free_tier={"limit": "Free tier: 1000 RU/s and 25 GB per subscription", "commercial_use": True},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["azure"], underlying_cloud="azure", lock_in=3,
        regions={"india": [], "eu": [], "us": []}, region_selectable=True,
        attest=attest_from("azure"),
        caps=["multi_az", "multi_region", "write_scaling", "geo", "vector", "json", "fts_builtin", "scale_to_zero"],
        best_for=["iot", "gaming", "social", "ecommerce", "api_platform"],
        avoid_for=["internal_tool", "data_analytics"],
        strengths=["Turnkey multi-region writes with five tunable consistency levels and a 99.999% multi-region SLA tier",
                   "Multiple APIs (NoSQL, MongoDB, Cassandra, PostgreSQL) on one managed service"],
        tradeoffs=["Request-unit pricing is hard to predict and expensive for scan-heavy workloads",
                   "Proprietary service on Azure only"],
        facts=[
            fact("Region: per-region availability of Cosmos DB (for example Central India) was not confirmed from an official page today, so every residency list is empty and the engine fails closed under india/eu/us; self-managed alternatives remain available.", "dbs_cosmos_docs", "K"),
            fact("Attestation: Azure compliance cells (BAA via the Online Services DPA, PCI, SOC, ISO, GDPR via DPA) come from kb.compliance for the platform; Cosmos DB-specific scope was not re-verified today.", "rf_azure_offerings", "U"),
            fact("Score rationale: cost_efficiency 2 because RU-based billing is costly for small scan-heavy workloads.", "dbs_cosmos_docs", "K"),
        ],
        sources=["dbs_cosmos_docs", "rf_azure_hipaa", "rf_azure_offerings"]),

    _db("cassandra_scylla", "Apache Cassandra / ScyllaDB", "wide_column",
        _a(3, 2, 5, 5, 2, 3, 3, 1, 2), 4, "m", "xl",
        {"m": (300, 1500), "l": (1500, 9000)},
        free_tier=_FREE, open_source=True, licence="Apache-2.0 (Cassandra); ScyllaDB source-available", lock_in=1,
        caps=["multi_az", "multi_region", "write_scaling", "lsm_writes", "geo"],
        best_for=["iot", "gaming", "social", "data_analytics"], avoid_for=["fintech", "internal_tool", "content_site", "ecommerce"],
        strengths=["Linear horizontal write scaling and multi-datacentre replication with no single point of failure",
                   "LSM storage handles very high write rates (workload_fit for write_heavy)"],
        tradeoffs=["Query-driven data modelling, eventual consistency by default and no joins",
                   "Large operational burden (repairs, compaction, tuning); over-engineered below size m"],
        facts=_self_facts("scylla_docs") + [
            fact("Score rationale: learning_curve 1 and maintainability 2 because modelling and cluster operations demand specialist skill.", "scylla_docs", "K"),
        ],
        sources=["scylla_docs"]),

    _db("timescaledb", "TimescaleDB (PostgreSQL extension)", "timeseries",
        _a(4, 4, 4, 4, 4, 5, 3, 4, 3), 2, "xs", "l",
        {"xs": (0, 25), "s": (15, 150), "m": (120, 800), "l": (600, 4000)},
        free_tier=_FREE, open_source=True, licence="Apache-2.0 (core) / Timescale License (compression, continuous aggregates)",
        current_major="2", lock_in=0,
        caps=["acid", "timeseries", "json", "geo", "read_replicas", "lsm_writes"],
        best_for=["iot", "data_analytics", "fintech"], avoid_for=["content_site"],
        strengths=["Time-series hypertables, compression and continuous aggregates while keeping full PostgreSQL SQL and tooling",
                   "Fits IoT and metrics workloads without a second database"],
        tradeoffs=["Extension availability depends on the host: not on Amazon RDS; use self-managed PostgreSQL or the vendor cloud",
                   "Some features are under the source-available Timescale License"],
        facts=_self_facts("timescale_docs") + [
            fact("Availability: Amazon RDS for PostgreSQL does not list the timescaledb extension, so no managed hyperscaler offering is recorded; run it on a VM or Kubernetes (self_hosted).", "timescale_docs", "K"),
        ],
        sources=["timescale_docs", "postgres_docs"]),

    _db("influxdb3", "InfluxDB 3", "timeseries",
        _a(3, 3, 4, 4, 3, 3, 3, 3, 3), 3, "s", "xl",
        {"s": (0, 200), "m": (150, 1000), "l": (800, 5000)},
        free_tier=_FREE, saas=True, open_source=True, licence="MIT / Apache-2.0 (Core); Enterprise is commercial",
        current_major="3", lock_in=1,
        caps=["timeseries", "lsm_writes", "write_scaling", "admin_ui"],
        best_for=["iot", "data_analytics"], avoid_for=["ecommerce", "fintech", "social"],
        strengths=["Purpose-built for high-cardinality metrics and sensor data using Parquet/Arrow storage and SQL",
                   "Core edition is open source and self-hostable"],
        tradeoffs=["Major rewrite (v3) leaves a smaller ecosystem than v1/v2 tooling; Cloud regions were not verified",
                   "No relational features: pair with PostgreSQL for application data"],
        facts=_self_facts("dbs_influx3_docs") + [
            fact("Region: InfluxDB Cloud region lists were not checked, so only the self-hosted path is offered.", "dbs_influx3_docs", "K"),
        ],
        sources=["dbs_influx3_docs"]),

    _db("clickhouse", "ClickHouse", "olap",
        _a(4, 3, 5, 5, 3, 3, 4, 3, 4), 3, "s", "xl",
        {"s": (0, 200), "m": (150, 1200), "l": (1000, 8000)},
        free_tier=_FREE, saas=True, open_source=True, licence="Apache-2.0", current_major="25.x", lock_in=1,
        caps=["timeseries", "lsm_writes", "write_scaling", "multi_az", "fts_builtin", "vector"],
        best_for=["data_analytics", "iot", "ai_ml_product", "api_platform"], avoid_for=["ecommerce", "fintech", "social", "content_site"],
        strengths=["Columnar OLAP engine with very fast aggregations over billions of rows at low hardware cost",
                   "Open source, self-hostable and available as ClickHouse Cloud"],
        tradeoffs=["Not for transactional updates or point lookups: pair with PostgreSQL for the system of record",
                   "Cluster tuning and schema design (ORDER BY, partitions) matter a great deal"],
        facts=_self_facts("clickhouse_docs") + [
            fact("Region: ClickHouse Cloud region availability was not verified today, so it is recorded with no regions (fail closed); self-managed is offered.", "dbs_clickhouse_cloud", "K"),
        ],
        sources=["clickhouse_docs", "dbs_clickhouse_cloud"]),

    _db("bigquery", "Google BigQuery", "olap",
        _a(3, 4, 5, 4, 4, 4, 4, 3, 4), 0, "m", "xl",
        {"m": (20, 800), "l": (200, 6000)},
        free_tier={"limit": "1 TiB queries and 10 GiB storage per month free", "commercial_use": True},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["gcp"], underlying_cloud="gcp", lock_in=3,
        regions=regions_from("gcp", only=("india", "eu", "us")), region_selectable=True,
        attest=attest_from("gcp", pci_dss="no", soc2="no", gdpr_dpa="no"),
        caps=["multi_region", "scale_to_zero", "vector", "geo", "write_scaling"],
        best_for=["data_analytics", "ai_ml_product", "iot"], avoid_for=["ecommerce", "social", "fintech", "content_site", "internal_tool"],
        strengths=["Serverless petabyte-scale analytics with no cluster to run; datasets can be pinned to Mumbai or Delhi",
                   "Built-in ML (BigQuery ML) and vector search"],
        tradeoffs=["Not a transactional store; per-query pricing can surprise without partitioning and quotas",
                   "Google Cloud only"],
        facts=[
            fact("Region: BigQuery regional locations include asia-south1 (Mumbai), asia-south2 (Delhi) and europe-west3, plus the US and EU multi-regions.", "dbs_bigquery_locations", "V"),
            fact("Attestation: BigQuery is on the Google Cloud HIPAA covered-products list and ISO 27001 applies at platform level; PCI DSS, SOC 2 and a GDPR DPA were not confirmed for BigQuery on an official page, so they are no (fail closed).", "rf_gcp_hipaa", "V"),
            fact("Score rationale: ops_burden 0 and scalability 5 because storage and compute are fully managed and scale separately; scale_floor m because below that the free tier of a transactional database is cheaper.", "bigquery_docs", "K"),
        ],
        sources=["bigquery_docs", "dbs_bigquery_locations", "rf_gcp_hipaa", "rf_gcp_iso"]),

    _db("snowflake", "Snowflake", "olap",
        _a(2, 4, 5, 4, 4, 4, 4, 3, 4), 0, "m", "xl",
        {"m": (150, 1500), "l": (1200, 9000)},
        free_tier={"limit": "Time-limited trial credits only", "commercial_use": False},
        self_hostable=False, saas=True, needs_internet=True, open_source=False, licence="proprietary service",
        cloud_affinity=["independent"], lock_in=3,
        regions={"india": [], "eu": [], "us": []}, region_selectable=True,
        attest={k: "no" for k in ("hipaa_baa", "pci_dss", "soc2", "iso27001", "gdpr_dpa")},
        caps=["multi_region", "scale_to_zero", "write_scaling", "json"],
        best_for=["data_analytics"], avoid_for=["ecommerce", "social", "fintech", "content_site", "internal_tool", "gaming"],
        strengths=["Separated storage and compute with a mature governance and data-sharing layer",
                   "Runs on AWS, Azure and GCP"],
        tradeoffs=["Credit-based pricing is costly for small teams; no free tier for production",
                   "Region and attestation facts were not verified, so the engine fails closed under any residency or compliance regime"],
        facts=[
            fact("Region: Snowflake region lists were not checked on an official page today, so all residency lists are empty (fail closed).", "dbs_snowflake_docs", "K"),
            fact("Attestation: Snowflake attestations were not checked on an official page today, so all are no (fail closed).", "dbs_snowflake_docs", "K"),
        ],
        sources=["dbs_snowflake_docs"]),

    _db("neo4j", "Neo4j", "graph",
        _a(3, 4, 3, 4, 3, 4, 3, 3, 3), 2, "xs", "l",
        {"xs": (0, 25), "s": (65, 300), "m": (300, 1500), "l": (1200, 6000)},
        free_tier={"limit": "Community Edition (GPL) and AuraDB Free", "commercial_use": True},
        saas=True, open_source=True, licence="GPL-3.0 (Community); Enterprise is commercial", current_major="2025.x", lock_in=1,
        caps=["acid", "json", "vector", "multi_az", "read_replicas"],
        best_for=["social", "marketplace", "ai_ml_product", "fintech"], avoid_for=["content_site", "internal_tool"],
        strengths=["Native graph model with Cypher makes multi-hop traversal queries natural and fast",
                   "Vector and graph retrieval in one engine for knowledge-graph RAG"],
        tradeoffs=["Only worth it when relationships are the product; otherwise PostgreSQL recursive queries suffice",
                   "Clustering and large-graph scale-out are Enterprise features"],
        facts=_self_facts("neo4j_docs") + [
            fact("Region: AuraDB region lists were not verified today, so only the self-hosted path is offered.", "dbs_aura_docs", "K"),
        ],
        sources=["neo4j_docs", "dbs_aura_docs"]),

    _db("tigerbeetle", "TigerBeetle", "ledger",
        _a(3, 2, 5, 5, 3, 5, 1, 1, 1), 4, "l", "xl",
        {"l": (600, 4000)},
        free_tier=_FREE, open_source=True, licence="Apache-2.0", lock_in=1,
        caps=["acid", "multi_az", "write_scaling", "lsm_writes"],
        best_for=["fintech"], avoid_for=["content_site", "internal_tool", "web_app", "social", "gaming", "iot"],
        strengths=["Purpose-built double-entry ledger with strict serializability and very high transaction throughput",
                   "Designed to hold the financial ledger next to a general-purpose database"],
        tradeoffs=["Stores accounts and transfers only: needs PostgreSQL alongside it; chosen only for large write-heavy money movement",
                   "Young product with a small ecosystem and a narrow API; requires an experienced operations team"],
        facts=_self_facts("tigerbeetle") + [
            fact("Score rationale: ecosystem 1 and popularity 1 because it is a single-purpose database with few integrations; performance 5 for ledger transactions per second.", "tigerbeetle", "K"),
        ],
        sources=["tigerbeetle"]),

    # "None": storage-free projects (static sites etc.)
    tech("none", "None (no database)", "database", "none",
         attrs=_a(5, 5, 5, 5, 5, 5, 3, 5, 3), ops_burden=0, scale_floor="xs", scale_ceiling="xl",
         cost={"xs": (0, 0), "s": (0, 0), "m": (0, 0), "l": (0, 0)},
         free_tier={"limit": "No database to pay for", "commercial_use": True},
         self_hostable=True, saas=False, open_source=True, licence="n/a", needs_internet=False,
         regions=ANYWHERE, region_selectable=False, data_at_rest=False, attest=SELF, lock_in=0,
         caps=["scale_to_zero"], best_for=["content_site"], avoid_for=[],
         strengths=["No data store to secure, back up or pay for when content is static or held in files or a headless CMS"],
         tradeoffs=["Cannot hold user accounts, orders or any dynamic state; add a database when that need appears"],
         facts=[fact("Region: stores no data, so no residency or attestation obligation arises from this layer.", "db_engines", "U"),
                fact("Attestation: not applicable because nothing is stored.", "db_engines", "U")],
         sources=["db_engines"]),

    # ---- non-maintained records (never recommended; kept to explain rejections) ----
    _db("postgres_14", "PostgreSQL 14 and earlier", "relational",
        _a(3, 4, 4, 4, 2, 2, 5, 4, 2), 2, "xs", "xl", {"xs": (0, 25), "s": (15, 120), "m": (100, 600), "l": (500, 3000)},
        status="retired", replaced_by="postgres", current_major="14", supported_until="2026-11-12", open_source=True,
        licence="PostgreSQL License", lock_in=0, caps=["acid"],
        strengths=[], tradeoffs=["PostgreSQL 14 reached end of life on 12 Nov 2026; releases 13 and older ended earlier. Upgrade to PostgreSQL 17."],
        facts=_self_facts("pg_versioning") + [
            fact("Lifecycle: end-of-life dates 13: 13 Nov 2025, 14: 12 Nov 2026, 15: 11 Nov 2027, 16: 9 Nov 2028, 17: 8 Nov 2029.", "eol_postgresql", "V")],
        sources=["eol_postgresql", "pg_versioning"]),

    _db("mysql_80", "MySQL 8.0", "relational",
        _a(3, 4, 4, 4, 2, 2, 5, 4, 2), 2, "xs", "xl", {"xs": (0, 25), "s": (15, 120), "m": (100, 600), "l": (500, 3000)},
        status="retired", replaced_by="mysql", current_major="8.0", supported_until="2026-04-30", open_source=True,
        licence="GPL-2.0", lock_in=0, caps=["acid"],
        strengths=[], tradeoffs=["MySQL 8.0 community support ended on 30 Apr 2026 (managed services run paid extended support). Use MySQL 8.4 LTS."],
        facts=_self_facts("eol_mysql") + [
            fact("Lifecycle: MySQL 8.0 end of life 30 Apr 2026; 8.4 LTS runs to 30 Apr 2032.", "eol_mysql", "V")],
        sources=["eol_mysql"]),

    _db("mongodb_60", "MongoDB 6.0 and earlier", "document",
        _a(3, 5, 5, 4, 2, 2, 5, 4, 2), 2, "xs", "xl", {"xs": (0, 25), "s": (10, 150), "m": (100, 800), "l": (700, 4000)},
        status="retired", replaced_by="mongodb", current_major="6.0", supported_until="2025-07-31", lock_in=1, caps=["json"],
        saas=True, strengths=[], tradeoffs=["MongoDB 6.0 reached end of life on 31 Jul 2025 (4.4 and 5.0 earlier). Use MongoDB 8.0."],
        facts=_self_facts("eol_mongodb") + [
            fact("Lifecycle: MongoDB 6.0 end of life 31 Jul 2025, 7.0 on 31 Aug 2027, 8.0 on 31 Oct 2029.", "eol_mongodb", "V")],
        sources=["eol_mongodb"]),

    _db("amazon_qldb", "Amazon QLDB", "ledger",
        _a(3, 3, 3, 3, 1, 3, 1, 3, 1), 0, "xs", "l", {"xs": (0, 20), "s": (10, 100), "m": (50, 500), "l": (300, 2000)},
        status="retired", replaced_by="postgres", supported_until="2025-07-31", self_hostable=False, saas=True,
        needs_internet=True, cloud_affinity=["aws"], lock_in=3, caps=[], strengths=[],
        tradeoffs=["Amazon QLDB reached end of support on 31 Jul 2025; AWS recommends migrating ledgers to Aurora PostgreSQL (or PostgreSQL with audit tables)."],
        facts=[fact("Region: service is retired, so no region is offered.", "eol_qldb", "V"),
               fact("Attestation: service is retired, so no attestation is offered.", "eol_qldb", "V"),
               fact("Lifecycle: end of support 31 Jul 2025.", "eol_qldb", "V")],
        regions={"india": [], "eu": [], "us": []}, attest={k: "no" for k in ("hipaa_baa", "pci_dss", "soc2", "iso27001", "gdpr_dpa")},
        sources=["eol_qldb", "eol_qldb"]),

    _db("fauna", "Fauna", "document",
        _a(3, 4, 3, 3, 1, 3, 1, 3, 1), 0, "xs", "l", {"xs": (0, 20), "s": (10, 100), "m": (50, 500), "l": (300, 2000)},
        status="retired", replaced_by="postgres", supported_until="2025-05-30", self_hostable=False, saas=True,
        needs_internet=True, lock_in=3, caps=[], strengths=[],
        tradeoffs=["The Fauna service ended on 30 May 2025; migrate to PostgreSQL or DynamoDB."],
        facts=[fact("Region: service is retired, so no region is offered.", "eol_fauna", "V"),
               fact("Attestation: service is retired, so no attestation is offered.", "eol_fauna", "V"),
               fact("Lifecycle: service ended 30 May 2025.", "eol_fauna", "V")],
        regions={"india": [], "eu": [], "us": []}, attest={k: "no" for k in ("hipaa_baa", "pci_dss", "soc2", "iso27001", "gdpr_dpa")},
        sources=["eol_fauna"]),
]

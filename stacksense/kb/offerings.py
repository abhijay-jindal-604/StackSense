"""Concrete database products per (engine, host family) (plan 3.10, 4.4, C3, C7).

An offering answers "what exactly do we name and where does it run when engine X is used on host family Y".
Host families: ``aws``, ``azure``, ``gcp``, ``digitalocean``, ``supabase``, ``neon``, ``fly``, ``cloudflare``,
``atlas`` (MongoDB Atlas, cloud-agnostic), ``clickhouse_cloud``, ``cockroach_cloud``, ``aura``, ``snowflake``
and ``self_hosted`` (VM, container, Kubernetes or on-prem; valid on every host that can run a VM or
container, with attestations inherited from the environment).

Rules followed here
* Regions and attestations come from ``kb.regions`` / ``kb.compliance`` or a page fetched 2026-11-13.
  Anything unconfirmed is ``[]`` / ``no`` with a K-confidence fact saying so (fail closed).
* Managed offerings default to major 17 (PostgreSQL), 8.4 (MySQL), 8.0 (MongoDB), 2022 (SQL Server): the
  naming rule of D14. RDS for PostgreSQL 18.x is available (release notes) but 17 is the broadest common
  denominator across vendors.
* Aurora is not offered: Aurora PostgreSQL is verified in ap-south-1/ap-south-2 and is HIPAA-eligible
  (kb.regions/kb.compliance "aurora_postgres"), but the AWS PCI, SOC and ISO lists show no Aurora row, so plain
  RDS is used. Fail closed, not an omission by judgement.
* Region and attestation cells of bound offerings are overwritten at import by ``kb.bindings`` from
  ``kb.regions`` / ``kb.compliance``; the literals below only matter for unbound (self-hosted, claim-free) ones.
* Cost bands are indicative list-price bands in USD/month at the profile size class (K): they feed the cost
  estimate, never a hard filter.
"""
from __future__ import annotations

from .database import RECORDS, SELF, attest_from, regions_from
from .model import fact, offering

_NO = {k: "no" for k in ("hipaa_baa", "pci_dss", "soc2", "iso27001", "gdpr_dpa")}
_EMPTY = {"india": [], "eu": [], "us": []}


def _o(engine, host, name, *, regions, attest, cost, ha, major=None, until=None, region_fact, attest_fact,
       sources, extra=(), kind="managed", needs_internet=True, region_selectable=True):
    return offering(
        f"{engine}__{host}", engine, host, name, kind=kind, regions=regions, region_selectable=region_selectable,
        attest=attest, cost=cost, ha_options=ha, current_major=major, supported_until=until,
        needs_internet=needs_internet,
        facts=[fact("Region: " + region_fact[0], region_fact[1], region_fact[2]),
               fact("Attestation: " + attest_fact[0], attest_fact[1], attest_fact[2]), *extra],
        sources=sorted(set(sources)))


# --- helpers shared by the AWS RDS family ------------------------------------------------------------------
_RDS_REGION = ("Amazon RDS is available in ap-south-1 (Mumbai), ap-south-2 (Hyderabad), eu-central-1, eu-west-1, eu-west-3, eu-north-1 and us-east-1/-2, us-west-1/-2 (RDS region table).", "dbs_rds_regions", "V")
_RDS_ATT = ("RDS is HIPAA-eligible for the SQL Server, MySQL, PostgreSQL, MariaDB, Oracle and Db2 engines (sign the AWS BAA), in scope for PCI DSS and SOC reports (service lists), and covered by the AWS DPA for GDPR.", "aws_hipaa", "V")
_RDS_SRC = ["dbs_rds_regions", "aws_hipaa", "rf_aws_pci", "dbs_aws_soc_scope", "rf_aws_gdpr", "dbs_rds_docs", "aws_rds_pricing"]
_RDS_HA = ["Multi-AZ DB instance (one standby)", "Multi-AZ DB cluster (two readable standbys)", "Read replicas", "RDS Proxy (connection pooling for Lambda)"]


def _rds(engine, name, major, until, cost, extra=()):
    return _o(engine, "aws", name, regions=regions_from("aws"), attest=attest_from("aws"), cost=cost, ha=_RDS_HA,
              major=major, until=until, region_fact=_RDS_REGION, attest_fact=_RDS_ATT, sources=_RDS_SRC, extra=extra)


_PG_COST = {"xs": (15, 45), "s": (30, 160), "m": (160, 700), "l": (700, 3500)}
_MY_COST = {"xs": (15, 45), "s": (30, 160), "m": (160, 700), "l": (700, 3500)}

OFFERINGS: list = [
    # ---- PostgreSQL ----
    _rds("postgres", "Amazon RDS for PostgreSQL 17", "17", "2029-11-08", _PG_COST,
         extra=[fact("Version: RDS for PostgreSQL release notes list 18.x and 17.x as available; 17 is named (supported upstream to 8 Nov 2029).", "dbs_rds_pg_versions", "V"),
                fact("Cost: indicative bands from RDS list prices (db.t4g to db.m7g, Multi-AZ at m and above); recheck against the pricing page.", "aws_rds_pricing", "K")]),
    _o("postgres", "azure", "Azure Database for PostgreSQL flexible server 17",
       regions={"india": ["centralindia", "southindia"],
                "eu": ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral", "italynorth", "polandcentral", "spaincentral", "austriaeast", "belgiumcentral"],
                "us": ["eastus", "eastus2", "centralus", "northcentralus", "southcentralus", "westcentralus", "westus", "westus2", "westus3"]},
       attest=attest_from("azure"),
       cost={"xs": (13, 40), "s": (30, 150), "m": (150, 650), "l": (650, 3200)},
       ha=["Zone-redundant HA (Central India and South India support it)", "Same-zone HA", "Read replicas", "Built-in PgBouncer (port 6432)"],
       major="17", until="2029-11-08",
       region_fact=("flexible server is listed in Central India and South India (zone-redundant HA in both), plus West Europe, Germany West Central, East US and others. Regions that are temporarily blocked for new deployments (marked $ on the page) can still be unavailable for new servers.", "dbs_azure_pg_overview", "V"),
       attest_fact=("the compliance page lists HIPAA and HITECH, PCI DSS Level 1, SOC 2 Type 2, ISO 27001 and EU Model Clauses for flexible server.", "dbs_azure_pg_compliance", "V"),
       sources=["dbs_azure_pg_overview", "dbs_azure_pg_compliance", "rf_azure_hipaa", "rf_azure_offerings", "azure_regions"],
       extra=[fact("Version: PostgreSQL 17 availability on flexible server was not re-read today (supported-versions page); 17 is the default pending that check.", "dbs_azure_pg_overview", "K")]),
    _o("postgres", "gcp", "Cloud SQL for PostgreSQL 17",
       regions=regions_from("gcp"),
       attest=attest_from("gcp", pci_dss="no", soc2="no", gdpr_dpa="no"),
       cost={"xs": (10, 40), "s": (30, 150), "m": (150, 650), "l": (650, 3200)},
       ha=["Regional high availability (standby in a second zone)", "Read replicas", "Cloud SQL Auth Proxy / connectors"],
       major="17", until="2029-11-08",
       region_fact=("Cloud SQL is available in asia-south1 (Mumbai), asia-south2 (Delhi), europe-west3 (Frankfurt) and us-central1 among others.", "dbs_cloudsql_locations", "V"),
       attest_fact=("Cloud SQL is on the Google Cloud HIPAA covered-products list and ISO 27001 applies at platform level; PCI DSS, SOC 2 and the GDPR DPA were not confirmed for Cloud SQL on an official page today, so they are no (fail closed).", "gcp_hipaa", "V"),
       sources=["dbs_cloudsql_locations", "gcp_hipaa", "rf_gcp_iso", "dbs_cloudsql_docs", "gcp_regions"]),
    _o("postgres", "digitalocean", "DigitalOcean Managed PostgreSQL 17",
       regions={"india": ["BLR1"], "eu": ["AMS3", "FRA1"], "us": ["NYC1", "NYC2", "NYC3", "SFO2", "SFO3"]},
       attest=attest_from("digitalocean"),
       cost={"xs": (15, 30), "s": (30, 120), "m": (120, 500), "l": (500, 2000)},
       ha=["Standby node (automatic failover)", "Read-only nodes", "Connection pools (PgBouncer)"],
       major="17", until="2029-11-08",
       region_fact=("Managed PostgreSQL is available in BLR1 (Bangalore), FRA1 and NYC1 (regional availability matrix); other EU/US datacentres follow the same product matrix.", "do_regions", "V"),
       attest_fact=("Managed Databases are covered by DigitalOcean's SOC 2 Type 2 report; HIPAA, PCI DSS and GDPR attestations for Managed Databases were not confirmed (ISO 27001 is facility-level only), so they are no (fail closed).", "dbs_do_db_shared_resp", "V"),
       sources=["do_regions", "dbs_do_db_shared_resp", "rf_do_certs", "dbs_do_managed_db", "do_pricing"]),
    _o("postgres", "supabase", "Supabase Postgres 17 (Supabase Cloud)",
       regions=regions_from("supabase"), attest=attest_from("supabase"),
       cost={"xs": (0, 25), "s": (25, 110), "m": (110, 600), "l": (600, 2500)},
       ha=["Read replicas (Pro and above)", "Point-in-time recovery add-on", "Supavisor connection pooler"],
       major="17", until="2029-11-08",
       region_fact=("Supabase offers ap-south-1 (Mumbai) as its only India region, Frankfurt/Ireland/Paris/Stockholm in the EU and several US regions; pick a specific region at project creation.", "supabase_regions", "V"),
       attest_fact=("SOC 2 Type 2; HIPAA needs a signed BAA plus the HIPAA add-on; eligibility of the Mumbai region for HIPAA is not documented (kb.compliance treats supabase + hipaa + india as unknown); PCI DSS, ISO 27001 and GDPR DPA were not confirmed, so no.", "supabase_soc2", "V"),
       sources=["supabase_regions", "supabase_soc2", "supabase_hipaa_projects", "supabase_docs", "supabase_pricing"],
       extra=[fact("Cost: indicative Pro-plan bands (USD 25 base plus compute add-ons); recheck on the pricing page.", "supabase_pricing", "K")]),
    _o("postgres", "neon", "Neon Serverless Postgres 17",
       regions=regions_from("neon"), attest=attest_from("neon"),
       cost={"xs": (0, 19), "s": (19, 100), "m": (100, 500), "l": (500, 2500)},
       ha=["Autoscaling compute and scale to zero", "Read replicas", "Branching and point-in-time restore"],
       major="17", until="2029-11-08",
       region_fact=("Neon has no India region; EU is aws-eu-central-1 (aws-eu-west-2 London is not EU) and US regions are listed; excluded under data_residency=india.", "neon_regions", "V"),
       attest_fact=("SOC 2 and ISO 27001; HIPAA self-serve on the Scale plan with a BAA; PCI DSS and GDPR DPA were not confirmed, so no.", "rf_neon_security", "V"),
       sources=["neon_regions", "rf_neon_security", "rf_neon_hipaa", "neon_regions"]),
    _o("postgres", "fly", "Fly.io Managed Postgres",
       regions=regions_from("fly_managed_postgres"), attest=attest_from("fly"),
       cost={"xs": (38, 80), "s": (80, 250), "m": (250, 900), "l": (900, 4000)},
       ha=["High-availability cluster (primary plus replicas)", "Automatic failover"],
       major="17", until="2029-11-08",
       region_fact=("Managed Postgres regions are ams, dfw, fra, iad, lax, lhr (UK) , ord and sjc; bom (Mumbai) is not on the list, so no India region.", "fly_regions", "V"),
       attest_fact=("Fly.io's compliance page returned 404 on 2026-11-13, so no attestation can be confirmed; all are no (fail closed).", "fly_mpg", "K"),
       sources=["fly_regions", "fly_mpg", "fly_mpg", "fly_mpg"],
       extra=[fact("Cost: indicative; Managed Postgres is priced from a dedicated-cluster minimum; recheck the pricing page.", "fly_pricing", "K")]),

    # ---- MySQL ----
    _rds("mysql", "Amazon RDS for MySQL 8.4", "8.4", "2032-04-30", _MY_COST,
         extra=[fact("Version: MySQL 8.4 LTS community support to 30 Apr 2032; RDS support for 8.4 is expected but the engine-version list was not read today.", "eol_mysql", "K")]),
    _o("mysql", "azure", "Azure Database for MySQL flexible server 8.4",
       regions=_EMPTY, attest=attest_from("azure"),
       cost={"xs": (13, 40), "s": (30, 150), "m": (150, 650), "l": (650, 3200)},
       ha=["Zone-redundant HA", "Same-zone HA", "Read replicas"], major="8.4", until="2032-04-30",
       region_fact=("per-region availability of Azure Database for MySQL (for example Central India) was not confirmed from an official page today, so every residency list is empty (fail closed).", "dbs_azure_mysql_docs", "K"),
       attest_fact=("Azure platform attestations come from kb.compliance; MySQL-specific scope was not re-verified today.", "rf_azure_offerings", "U"),
       sources=["dbs_azure_mysql_docs", "rf_azure_hipaa", "rf_azure_offerings"]),
    _o("mysql", "gcp", "Cloud SQL for MySQL 8.4",
       regions=regions_from("gcp"), attest=attest_from("gcp", pci_dss="no", soc2="no", gdpr_dpa="no"),
       cost={"xs": (10, 40), "s": (30, 150), "m": (150, 650), "l": (650, 3200)},
       ha=["Regional high availability", "Read replicas", "Cloud SQL Auth Proxy / connectors"], major="8.4", until="2032-04-30",
       region_fact=("Cloud SQL locations table (fetched under the PostgreSQL path) lists asia-south1, asia-south2, europe-west3 and us-central1; the table is shared across engines but the MySQL path was not fetched separately.", "dbs_cloudsql_locations", "U"),
       attest_fact=("Cloud SQL is on the Google Cloud HIPAA covered-products list; PCI DSS, SOC 2 and the GDPR DPA were not confirmed for Cloud SQL, so they are no (fail closed).", "gcp_hipaa", "V"),
       sources=["dbs_cloudsql_locations", "gcp_hipaa", "rf_gcp_iso", "dbs_cloudsql_docs"]),
    _o("mysql", "digitalocean", "DigitalOcean Managed MySQL 8.4",
       regions={"india": ["BLR1"], "eu": ["AMS3", "FRA1"], "us": ["NYC1", "NYC2", "NYC3", "SFO2", "SFO3"]},
       attest=attest_from("digitalocean"),
       cost={"xs": (15, 30), "s": (30, 120), "m": (120, 500), "l": (500, 2000)},
       ha=["Standby node", "Read-only nodes"], major="8.4", until="2032-04-30",
       region_fact=("Managed MySQL is available in BLR1, FRA1 and NYC1 (regional availability matrix).", "do_regions", "V"),
       attest_fact=("SOC 2 Type 2 covers Managed Databases; HIPAA, PCI DSS and GDPR were not confirmed, so no (fail closed).", "dbs_do_db_shared_resp", "V"),
       sources=["do_regions", "dbs_do_db_shared_resp", "rf_do_certs", "dbs_do_managed_db"]),

    # ---- MariaDB ----
    _rds("mariadb", "Amazon RDS for MariaDB 11.8", "11.8", "2028-06-04", _MY_COST,
         extra=[fact("Version: MariaDB 11.8 LTS to 4 Jun 2028; the RDS engine-version list was not read today (10.11 and 11.4 are older LTS lines).", "dbs_eol_mariadb", "K")]),

    # ---- SQL Server ----
    _rds("sqlserver", "Amazon RDS for SQL Server 2022", "2022", "2033-01-11",
         {"xs": (60, 200), "s": (200, 700), "m": (700, 3500), "l": (3000, 14000)},
         extra=[fact("Cost: includes the licence-included price; Express edition at xs is cheaper; recheck pricing.", "aws_rds_pricing", "K")]),
    _o("sqlserver", "azure", "Azure SQL Database (General Purpose, vCore)",
       regions=_EMPTY, attest=attest_from("azure"),
       cost={"xs": (5, 40), "s": (40, 250), "m": (250, 1500), "l": (1200, 8000)},
       ha=["Zone-redundant configuration (General Purpose, Business Critical, Hyperscale)", "Active geo-replication", "Auto-failover groups"],
       major="2022", until="2033-01-11",
       region_fact=("Azure SQL Database runs in regions that support availability zones for zone redundancy, but per-region availability (for example Central India) was not read from an official table today, so every residency list is empty (fail closed). Use SQL Server on an Azure VM (self_hosted) when a region is needed.", "dbs_azure_sql_docs", "K"),
       attest_fact=("Azure platform attestations come from kb.compliance; Azure SQL Database scope was not re-verified today.", "rf_azure_offerings", "U"),
       sources=["dbs_azure_sql_docs", "azure_sql_pricing", "rf_azure_hipaa", "rf_azure_offerings"]),

    # ---- MongoDB ----
    _o("mongodb", "atlas", "MongoDB Atlas 8.0 (on AWS)",
       regions=regions_from("mongodb_atlas"), attest=attest_from("mongodb_atlas"),
       cost={"xs": (0, 60), "s": (57, 250), "m": (250, 1000), "l": (900, 5000)},
       ha=["Replica set across three zones (default)", "Multi-region clusters", "Sharded clusters"],
       major="8.0", until="2029-10-31",
       region_fact=("Atlas on AWS verified regions AP_SOUTH_1 (Mumbai), AP_SOUTH_2 (Hyderabad), EU_CENTRAL_1 and US_EAST_1; Azure and GCP Atlas regions were not checked, so this offering is listed on the AWS regions only.", "atlas_regions", "V"),
       attest_fact=("Atlas lists ISO 27001, PCI DSS and SOC reports; a HIPAA BAA is in the Cloud Terms for self-service accounts; GDPR DPA and SOC 2 type were not confirmed so they are no (fail closed).", "atlas_compliance", "V"),
       sources=["atlas_regions", "atlas_compliance", "rf_atlas_hipaa", "atlas_pricing", "dbs_atlas_docs"],
       extra=[fact("Cloud-agnostic: Atlas runs on AWS, Azure and GCP; cloud_preference gcp or azure needs the matching regions verified first.", "dbs_atlas_docs", "K")]),
    _o("mongodb", "digitalocean", "DigitalOcean Managed MongoDB",
       regions={"india": ["BLR1"], "eu": ["AMS3", "FRA1"], "us": ["NYC1", "NYC2", "NYC3", "SFO2", "SFO3"]},
       attest=attest_from("digitalocean"),
       cost={"xs": (15, 30), "s": (30, 120), "m": (120, 500), "l": (500, 2000)},
       ha=["Replica set (three nodes at the HA tier)"], major="8.0", until="2029-10-31",
       region_fact=("Managed MongoDB is available in BLR1, FRA1 and NYC1 (regional availability matrix).", "do_regions", "V"),
       attest_fact=("SOC 2 Type 2 covers Managed Databases; HIPAA, PCI DSS and GDPR were not confirmed, so no (fail closed).", "dbs_do_db_shared_resp", "V"),
       sources=["do_regions", "dbs_do_db_shared_resp", "rf_do_certs", "dbs_do_managed_db"],
       extra=[fact("Version: the engine version DigitalOcean offers was not read today; 8.0 is the KB default.", "dbs_do_managed_db", "K")]),

    # ---- proprietary single-vendor services ----
    _o("dynamodb", "aws", "Amazon DynamoDB (on-demand capacity)",
       regions=regions_from("aws"), attest=attest_from("aws", pci_dss="yes", soc2="yes"),
       cost={"xs": (0, 10), "s": (5, 100), "m": (50, 800), "l": (500, 6000)},
       ha=["Multi-AZ by default", "Global tables (multi-region active-active)", "Point-in-time recovery"],
       region_fact=("DynamoDB has endpoints in ap-south-1, ap-south-2, eu-central-1, eu-west-1 and us-east-1 among others.", "dbs_ddb_endpoints", "V"),
       attest_fact=("DynamoDB is HIPAA-eligible, in scope for PCI DSS and SOC reports, and covered by the AWS DPA.", "aws_hipaa", "V"),
       sources=["dbs_ddb_endpoints", "aws_hipaa", "rf_aws_pci", "dbs_aws_soc_scope", "rf_aws_gdpr", "dynamodb_docs"],
       needs_internet=True),
    _o("firestore", "gcp", "Cloud Firestore (Native mode)",
       regions=regions_from("firestore"), attest=attest_from("firestore", pci_dss="no", soc2="yes", iso27001="yes", gdpr_dpa="no"),
       cost={"xs": (0, 10), "s": (5, 100), "m": (50, 800), "l": (500, 5000)},
       ha=["Multi-AZ within a region", "Multi-region locations (nam5, eur3)"],
       region_fact=("Firestore locations include asia-south1, asia-south2, eur3 and single EU regions, nam5 and us-central1; fixed at creation.", "rf_firestore_locations", "V"),
       attest_fact=("Firestore is on the Google Cloud HIPAA covered-products list; SOC 2 and ISO 27001 recorded for Firebase; PCI DSS and GDPR DPA unconfirmed, so no.", "gcp_hipaa", "V"),
       sources=["rf_firestore_locations", "gcp_hipaa", "firebase_privacy", "firestore_docs", "firebase_pricing"]),
    _o("cosmosdb", "azure", "Azure Cosmos DB for NoSQL",
       regions=_EMPTY, attest=attest_from("azure"),
       cost={"xs": (0, 25), "s": (25, 250), "m": (250, 2000), "l": (1500, 12000)},
       ha=["Zone redundancy", "Multi-region writes"],
       region_fact=("per-region availability (for example Central India) was not confirmed from an official page today, so every residency list is empty (fail closed).", "dbs_cosmos_docs", "K"),
       attest_fact=("Azure platform attestations come from kb.compliance; Cosmos DB-specific scope was not re-verified today.", "rf_azure_offerings", "U"),
       sources=["dbs_cosmos_docs", "rf_azure_hipaa", "rf_azure_offerings"]),
    _o("cloudflare_d1", "cloudflare", "Cloudflare D1",
       regions=regions_from("cloudflare_d1"), attest=attest_from("cloudflare", hipaa_baa="no", gdpr_dpa="no"),
       cost={"xs": (0, 5), "s": (0, 30)},
       ha=["Automatic replication within Cloudflare", "Read replication", "Time Travel point-in-time restore"],
       region_fact=("jurisdictions eu, fedramp and us only; no India jurisdiction.", "rf_cf_d1_location", "V"),
       attest_fact=("SOC 2, ISO 27001, PCI DSS L1 per Cloudflare's blog; HIPAA BAA and GDPR DPA unconfirmed, so no.", "rf_cf_certs", "V"),
       sources=["rf_cf_d1_location", "rf_cf_certs", "dbs_d1_docs", "cf_workers"]),
    _o("bigquery", "gcp", "Google BigQuery",
       regions=regions_from("gcp"), attest=attest_from("gcp", pci_dss="no", soc2="no", gdpr_dpa="no"),
       cost={"m": (20, 800), "l": (200, 6000)},
       ha=["Multi-zone by default", "Cross-region dataset replication"],
       region_fact=("BigQuery regional locations include asia-south1, asia-south2 and europe-west3, plus the US and EU multi-regions.", "dbs_bigquery_locations", "V"),
       attest_fact=("BigQuery is on the Google Cloud HIPAA covered-products list; PCI DSS, SOC 2, GDPR DPA unconfirmed, so no.", "gcp_hipaa", "V"),
       sources=["dbs_bigquery_locations", "gcp_hipaa", "rf_gcp_iso", "bigquery_docs"]),

    # ---- vendor clouds with unverified facts (listed so the gap is explicit; they fail closed) ----
    _o("snowflake", "snowflake", "Snowflake", regions=_EMPTY, attest=_NO,
       cost={"m": (150, 1500), "l": (1200, 9000)}, ha=["Multi-cluster warehouses"],
       region_fact=("region lists were not verified on an official page today, so all residency lists are empty (fail closed).", "dbs_snowflake_docs", "K"),
       attest_fact=("attestations were not verified on an official page today, so all are no (fail closed).", "dbs_snowflake_docs", "K"),
       sources=["dbs_snowflake_docs"]),
    _o("clickhouse", "clickhouse_cloud", "ClickHouse Cloud", regions=_EMPTY, attest=_NO,
       cost={"s": (60, 300), "m": (300, 1500), "l": (1200, 8000)}, ha=["Multi-replica services"],
       region_fact=("ClickHouse Cloud region availability was not verified today, so all residency lists are empty (fail closed).", "dbs_clickhouse_cloud", "K"),
       attest_fact=("attestations were not verified today, so all are no (fail closed).", "dbs_clickhouse_cloud", "K"),
       sources=["dbs_clickhouse_cloud", "clickhouse_docs"]),
    _o("cockroachdb", "cockroach_cloud", "CockroachDB Cloud", regions=_EMPTY, attest=_NO,
       cost={"s": (0, 300), "m": (300, 1500), "l": (1500, 8000)}, ha=["Multi-node, multi-AZ and multi-region clusters"],
       region_fact=("CockroachDB Cloud region availability was not verified today, so all residency lists are empty (fail closed).", "dbs_cockroach_cloud", "K"),
       attest_fact=("attestations were not verified today, so all are no (fail closed).", "dbs_cockroach_cloud", "K"),
       sources=["dbs_cockroach_cloud", "cockroach_docs"]),
    _o("neo4j", "aura", "Neo4j AuraDB", regions=_EMPTY, attest=_NO,
       cost={"xs": (0, 65), "s": (65, 300), "m": (300, 1500), "l": (1200, 6000)}, ha=["Three-node clusters (Professional/Business Critical)"],
       region_fact=("AuraDB region availability was not verified today, so all residency lists are empty (fail closed).", "dbs_aura_docs", "K"),
       attest_fact=("attestations were not verified today, so all are no (fail closed).", "dbs_aura_docs", "K"),
       sources=["dbs_aura_docs", "neo4j_docs"]),
]

# ---- self-managed offerings: one per self-hostable maintained engine (deterministic, derived from the records) ----
_HA_SELF = {
    "postgres": ["Streaming replication with Patroni or repmgr", "Read replicas", "PgBouncer"],
    "mysql": ["Group Replication or InnoDB Cluster", "Read replicas"],
    "mariadb": ["Galera Cluster", "Primary/replica replication"],
    "sqlserver": ["Always On availability groups", "Failover cluster instances"],
    "sqlite": ["Litestream/LiteFS replication to object storage"],
    "cockroachdb": ["Three-node minimum, survives zone or node loss"],
    "yugabytedb": ["Three-node minimum with replication factor 3"],
    "mongodb": ["Three-member replica set", "Sharded cluster"],
    "cassandra_scylla": ["Multi-node ring, replication factor 3", "Multi-datacentre replication"],
    "timescaledb": ["PostgreSQL streaming replication (Patroni)"],
    "influxdb3": ["Object-storage-backed single node; Enterprise adds clustering"],
    "clickhouse": ["Replicated tables with ClickHouse Keeper", "Shards and replicas"],
    "neo4j": ["Causal cluster (Enterprise)", "Single instance (Community)"],
    "tigerbeetle": ["Six-replica cluster (strict quorum)"],
}
for _r in RECORDS:
    if _r["status"] != "maintained" or _r["id"] not in _HA_SELF:
        continue
    _major = f" {_r['current_major']}" if _r.get("current_major") else ""
    _cost = {k: tuple(v) for k, v in _r["cost"].items()}  # engine record bands = machine cost when self-run
    OFFERINGS.append(_o(
        _r["id"], "self_hosted", f"Self-managed {_r['name']}{_major}",
        regions={"india": ["*"], "eu": ["*"], "us": ["*"]}, attest=dict(SELF), cost=_cost, ha=_HA_SELF[_r["id"]],
        major=_r.get("current_major"), until=_r.get("supported_until"), kind="self_managed", needs_internet=False,
        region_fact=("runs wherever the team deploys it (VM, container, Kubernetes, on-premise or air-gapped); the region is the team's choice.", "db_engines", "U"),
        attest_fact=("self-managed, so attestations are inherited from the environment it runs in and the controls are the team's responsibility.", "db_engines", "U"),
        sources=sorted(set(_r["sources"]) | {"db_engines"}),
        extra=[fact("Cost: hardware or VM share only (indicative); add operations time, which is not in the bill.", "db_engines", "K")]))

# Region and attestation cells of bound offerings come from kb.regions / kb.compliance (kb.bindings).
from .bindings import bind as _bind  # noqa: E402

OFFERINGS = _bind(OFFERINGS)

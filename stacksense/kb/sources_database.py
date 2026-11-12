"""Source keys contributed by the database layer task.

Same shape as kb/sources.py: key -> (title, https url, ISO accessed date). Merged by kb/sources.py.
Keys are prefixed ``dbs_`` so they cannot collide with the other layer modules.
Pages marked (V) were fetched on 2026-11-13; the rest are vendor documentation landing pages
cited for descriptive (non-filter) facts.
"""

_A = "2026-11-13"

SOURCES: dict = {
    # (V) fetched and read
    "dbs_rds_regions": ("Amazon RDS - Regions, Availability Zones, and Local Zones (region table incl. Mumbai, Hyderabad)", "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.RegionsAndAvailabilityZones.html", _A),
    "dbs_ddb_endpoints": ("Amazon DynamoDB endpoints and quotas (region table)", "https://docs.aws.amazon.com/general/latest/gr/ddb.html", _A),
    "dbs_rds_pg_versions": ("Amazon RDS for PostgreSQL release notes (18.x and 17.x available)", "https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-versions.html", _A),
    "dbs_aws_soc_scope": ("AWS services in scope for SOC (RDS and DynamoDB listed)", "https://aws.amazon.com/compliance/services-in-scope/SOC/", _A),
    "dbs_azure_pg_overview": ("Azure Database for PostgreSQL flexible server overview (region table incl. Central/South India)", "https://learn.microsoft.com/en-us/azure/postgresql/overview", _A),
    "dbs_azure_pg_compliance": ("Azure Database for PostgreSQL flexible server compliance certifications", "https://learn.microsoft.com/en-us/azure/postgresql/security/security-compliance", _A),
    "dbs_cloudsql_locations": ("Cloud SQL locations (asia-south1, asia-south2, europe-west3, us-central1)", "https://docs.cloud.google.com/sql/docs/postgres/locations", _A),
    "dbs_bigquery_locations": ("BigQuery locations (asia-south1, asia-south2, EU, US)", "https://docs.cloud.google.com/bigquery/docs/locations", _A),
    "dbs_do_db_shared_resp": ("DigitalOcean Managed Databases shared responsibility (covered by SOC 2 Type 2)", "https://www.digitalocean.com/security/shared-responsibility-model-managed-databases", _A),
    "dbs_eol_mariadb": ("endoflife.date: MariaDB (10.11, 11.4, 11.8 LTS dates)", "https://endoflife.date/mariadb", _A),
    # vendor documentation landing pages (descriptive facts only)
    "dbs_mariadb_docs": ("MariaDB Server documentation and release policy", "https://mariadb.com/docs/server/", _A),
    "dbs_yugabyte_docs": ("YugabyteDB documentation", "https://docs.yugabyte.com/", _A),
    "dbs_influx3_docs": ("InfluxDB 3 documentation", "https://docs.influxdata.com/influxdb3/", _A),
    "dbs_snowflake_docs": ("Snowflake documentation", "https://docs.snowflake.com/", _A),
    "dbs_cosmos_docs": ("Azure Cosmos DB documentation", "https://learn.microsoft.com/en-us/azure/cosmos-db/", _A),
    "dbs_d1_docs": ("Cloudflare D1 documentation (limits, data location)", "https://developers.cloudflare.com/d1/", _A),
    "dbs_cloudsql_docs": ("Cloud SQL documentation", "https://cloud.google.com/sql/docs", _A),
    "dbs_azure_sql_docs": ("Azure SQL Database documentation", "https://learn.microsoft.com/en-us/azure/azure-sql/database/", _A),
    "dbs_azure_mysql_docs": ("Azure Database for MySQL flexible server documentation", "https://learn.microsoft.com/en-us/azure/mysql/", _A),
    "dbs_rds_docs": ("Amazon RDS user guide", "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/", _A),
    "dbs_do_managed_db": ("DigitalOcean Managed Databases product documentation", "https://docs.digitalocean.com/products/databases/", _A),
    "dbs_atlas_docs": ("MongoDB Atlas documentation", "https://www.mongodb.com/docs/atlas/", _A),
    "dbs_aura_docs": ("Neo4j AuraDB documentation", "https://neo4j.com/docs/aura/", _A),
    "dbs_clickhouse_cloud": ("ClickHouse Cloud documentation", "https://clickhouse.com/docs/cloud/overview", _A),
    "dbs_cockroach_cloud": ("CockroachDB Cloud documentation", "https://www.cockroachlabs.com/docs/cockroachcloud/", _A),
    "dbs_firestore_editions": ("Firestore documentation (Standard and Enterprise editions)", "https://cloud.google.com/firestore/docs", _A),
    "dbs_mysql_84": ("MySQL 8.4 LTS release notes and support policy", "https://dev.mysql.com/doc/relnotes/mysql/8.4/en/", _A),
    "dbs_mongodb_lifecycle": ("MongoDB software lifecycle schedules", "https://www.mongodb.com/legal/support-policy/lifecycles", _A),
}

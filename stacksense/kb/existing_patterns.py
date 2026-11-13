"""Existing-system patterns (plan section 6.6).

``PATTERNS`` is an ordered tuple of :class:`Pattern`.  ``match(text)`` evaluates them in this order,
case-insensitively, and returns at most one :class:`PatternHit` per pattern id (its first non-negated
occurrence), in pattern order.  A free-text system such as "On-prem SQL Server 2019" can legitimately
hit several patterns (``sqlserver`` and ``on_prem``); the caller keeps every hit, and a string with no
hit is unmatched.  Negated mentions ("no Kafka", "without Oracle") do not fire.

Pattern fields
--------------
id           stable pattern id (``ExistingMatch.pattern_id``).
family       identity | database | framework | messaging | saas | infrastructure.
kind         canonical product id (``ExistingMatch.kind``), for example ``sqlserver``.
regex        regex (``re.IGNORECASE``) that recognises the product.
versioned    True when a version number directly after the product name is captured (``2019``, ``7.4``,
             ``18``).  Only a number right behind the name counts, so "Python 3 scripts" gives ``3``.
reuse        tuple of ``layer:value`` reuse targets (``identity:oidc``, ``database:sqlserver`` ...).
note         plain-language integration note (the engine may append the version-specific EOL warning).
eol_product  product id in ``kb/eol.py`` to judge the captured version against, or None.
eol_version  version to judge when none was captured (for example AngularJS is always 1.x), or None.
source       key in kb/sources.py when the note rests on a cited fact, else None.

Legacy families (classic ASP, VB6, COBOL, mainframes) carry a facade / strangler-fig note.
API for ``existing.py``::

    match(text) -> tuple[PatternHit, ...]
    eol_args(hit) -> (product, version) | None      # feed to kb.eol.verdict(*eol_args(hit))
    BY_ID[pattern_id] -> Pattern
"""
from __future__ import annotations

import re
from typing import NamedTuple

FAMILIES = ("identity", "database", "framework", "messaging", "saas", "infrastructure")


class Pattern(NamedTuple):
    id: str
    family: str
    kind: str
    regex: str
    versioned: bool = False
    reuse: tuple[str, ...] = ()
    note: str = ""
    eol_product: str | None = None
    eol_version: str | None = None
    source: str | None = None


class PatternHit(NamedTuple):
    pattern_id: str
    family: str
    kind: str
    version: str | None
    span: tuple[int, int]
    text: str
    eol_product: str | None
    eol_version: str | None


def _p(id_, family, kind, regex, reuse=(), note="", *, versioned=False, eol=None, eol_version=None, source=None):
    return Pattern(id_, family, kind, regex, versioned, tuple(reuse), note, eol, eol_version, source)


_LEGACY = ("Keep it running behind a thin API facade and move features out one at a time (strangler-fig); "
           "do not rewrite it in one step.")

PATTERNS: tuple[Pattern, ...] = (
    # ---- identity
    _p("azure_ad_b2c", "identity", "azure_ad_b2c", r"\b(?:azure\s+ad|azure\s+active\s+directory|aad)\s+b2c\b",
       ("identity:oidc", "identity:entra_external_id"),
       "Existing customer sign-in runs on Azure AD B2C, which is closed to new customers. Keep it for current "
       "users, plan a move to Microsoft Entra External ID, and do not build new features that depend on B2C.",
       eol="azure_ad_b2c"),
    _p("entra_external_id", "identity", "entra_external_id", r"\bentra\s+external\s+id\b",
       ("identity:oidc", "identity:entra_external_id"),
       "Customer sign-in can reuse the Entra External ID tenant through OpenID Connect."),
    _p("entra_id", "identity", "entra_id",
       r"\bentra(?:\s+id)?\b(?!\s+external)|\bazure\s+(?:ad|active\s+directory)\b(?!\s+b2c)|\baad\b(?!\s+b2c)",
       ("identity:oidc", "identity:entra_id"),
       "Sign-in reuses the existing Microsoft Entra ID tenant through OpenID Connect (for .NET, Microsoft.Identity.Web); "
       "no new user store."),
    _p("active_directory", "identity", "active_directory",
       r"(?<!azure )\bactive\s+directory\b|\badfs\b|\bad\s+fs\b|\bwindows\s+ad\b|\bon-?prem(?:ises)?\s+ad\b",
       ("identity:saml", "identity:ldap", "identity:entra_id"),
       "Users already live in Active Directory. Federate through ADFS or Entra Connect (SAML or OpenID Connect) "
       "instead of creating a second user store."),
    _p("okta", "identity", "okta", r"\bokta\b", ("identity:oidc", "identity:saml"),
       "Reuse Okta as the identity provider through OpenID Connect or SAML; no new user store."),
    _p("google_workspace", "identity", "google_workspace",
       r"\bgoogle\s+(?:workspace|apps|suite)\b|\bg[- ]?suite\b|\bgsuite\b",
       ("identity:oidc", "saas:google_workspace_api"),
       "Staff sign-in can use Google as an OpenID Connect provider, and the Workspace APIs reach Drive, Calendar and Gmail."),
    _p("keycloak", "identity", "keycloak", r"\bkey\s*cloak\b", ("identity:oidc", "identity:saml"),
       "Reuse the Keycloak realm through OpenID Connect or SAML; no new user store.", versioned=True),
    _p("auth0", "identity", "auth0", r"\bauth0\b", ("identity:oidc",),
       "Reuse the Auth0 tenant through OpenID Connect; no new user store."),
    _p("ping_identity", "identity", "ping_identity", r"\bping\s*(?:identity|federate|one)\b|\bpingfederate\b",
       ("identity:oidc", "identity:saml"), "Reuse Ping as the identity provider through SAML or OpenID Connect."),
    _p("ldap", "identity", "ldap", r"\bopen\s*ldap\b|\bldap\b", ("identity:ldap",),
       "Authenticate against the existing LDAP directory (bind or federation) rather than copying users."),
    _p("cognito", "identity", "cognito", r"\b(?:aws\s+|amazon\s+)?cognito\b", ("identity:oidc", "hosting:aws"),
       "Reuse the Amazon Cognito user pool through OpenID Connect; this also points to an AWS account."),
    # ---- databases
    _p("azure_sql", "database", "azure_sql", r"\bazure\s+sql\b|\bsql\s+managed\s+instance\b",
       ("database:sqlserver", "hosting:azure"),
       "Keep the data in Azure SQL and connect through the standard SQL Server drivers; the app can run in the same region."),
    _p("sqlserver", "database", "sqlserver", r"\b(?:ms\s*sql(?:\s*server)?|sql\s*server|mssql|microsoft\s+sql)\b",
       ("database:sqlserver",),
       "Keep the existing SQL Server as the system of record where it holds core data; connect over a private link "
       "or VPN and sync or migrate gradually (Azure SQL or a managed SQL Server is the cloud path).",
       versioned=True, eol="sqlserver"),
    _p("oracle_db", "database", "oracle",
       r"\boracle\s+(?:db|database|rdbms|exadata|\d{1,2}[cgi]|23ai)\b|\bpl/sql\b",
       ("database:oracle",),
       "Keep Oracle as the system of record for existing data and integrate through its SQL or REST (ORDS) interface; "
       "move to PostgreSQL only as a planned migration.", versioned=True),
    _p("postgresql", "database", "postgresql", r"\bpostgre(?:s|sql)\b|\bpgsql\b", ("database:postgresql",),
       "Reuse the existing PostgreSQL as the primary store, or move it to a managed PostgreSQL of the same major version first.",
       versioned=True, eol="postgresql"),
    _p("mysql", "database", "mysql", r"\bmysql\b", ("database:mysql", "database:postgresql"),
       "Keep MySQL for existing data; a managed MySQL is the lowest-risk path, and a move to PostgreSQL is optional.",
       versioned=True, eol="mysql"),
    _p("mariadb", "database", "mariadb", r"\bmaria\s*db\b", ("database:mysql",),
       "Keep MariaDB, which speaks the MySQL protocol; managed MariaDB or MySQL are the cloud paths.", versioned=True),
    _p("mongodb", "database", "mongodb", r"\bmongo(?:db)?\b", ("database:mongodb",),
       "Keep the existing MongoDB collections; a managed MongoDB (Atlas) avoids operating the cluster.",
       versioned=True, eol="mongodb"),
    _p("db2", "database", "db2", r"\bibm\s+db2\b|\bdb2\b", ("database:db2",),
       "Leave DB2 where it is and read through JDBC/ODBC or scheduled exports; replicate only what the new system needs."),
    _p("sap_hana", "database", "sap_hana", r"\bsap\s+hana\b|\bhana\s+(?:db|database|cloud)\b", ("database:sap_hana",),
       "Read SAP HANA through its SQL interface or SAP APIs; do not duplicate its tables."),
    _p("azure_cache_redis", "database", "azure_cache_redis",
       r"\bazure\s+cache\s+for\s+redis\b|\bazure\s+redis\s+cache\b|\bazure\s+redis\b",
       ("database:redis", "hosting:azure"),
       "Azure Cache for Redis is being retired; plan the move to Azure Managed Redis (same Redis protocol).",
       eol="azure_cache_redis"),
    _p("redis", "database", "redis", r"(?<!cache for )(?<!azure )(?<!managed )\bredis\b(?!\s+cache)", ("database:redis",),
       "Reuse the existing Redis for caching, sessions and queues instead of adding another store.", versioned=True),
    _p("elasticsearch", "database", "elasticsearch", r"\belastic\s*search\b|\belk\b|\belastic\s+stack\b|\bopen\s*search\b",
       ("database:search",), "Keep the existing search cluster and index from the new system rather than building a second one.",
       versioned=True, eol="elasticsearch"),
    _p("snowflake", "database", "snowflake", r"\bsnowflake\b", ("database:warehouse",),
       "Treat Snowflake as the analytics warehouse; load into it, do not use it for transactional traffic."),
    _p("bigquery", "database", "bigquery", r"\bbig\s*query\b", ("database:warehouse", "hosting:gcp"),
       "Treat BigQuery as the analytics warehouse; stream or batch events into it."),
    _p("firestore", "database", "firebase", r"\bfirestore\b|\bfirebase\b|\bcloud\s+firestore\b",
       ("database:firestore", "hosting:gcp"),
       "Keep the Firebase project for what it already serves; check its data location before adding new personal data."),
    _p("dynamodb", "database", "dynamodb", r"\bdynamo\s*db\b", ("database:dynamodb", "hosting:aws"),
       "Keep DynamoDB tables for key-value access patterns; this also points to an AWS account."),
    _p("qldb", "database", "qldb", r"\bqldb\b|\bquantum\s+ledger\b", ("database:postgresql",),
       "Amazon QLDB has ended; move the ledger to Aurora PostgreSQL with append-only ledger tables.", eol="qldb"),
    _p("fauna", "database", "fauna", r"\bfauna(?:db)?\b", ("database:postgresql",),
       "Fauna has shut down; export the data and move it to PostgreSQL or DynamoDB.", eol="fauna"),
    _p("minio", "infrastructure", "minio", r"\bmin\.?io\b", ("storage:s3_compatible",),
       "The MinIO community edition is archived and unmaintained; keep it only while migrating to a supported S3-compatible store.",
       eol="minio"),
    # ---- frameworks and runtimes
    _p("dotnet_framework", "framework", "dotnet_framework",
       r"\.net\s+framework\b|\bdotnet\s+framework\b|\basp\.net(?!\s+core)\b|\bweb\s*forms\b|\bwcf\b",
       ("backend:dotnet", "backend:facade"),
       "Keep the .NET Framework application running and expose it through an API facade; build new features in modern .NET.",
       versioned=True, eol="dotnet_framework"),
    _p("dotnet", "framework", "dotnet",
       r"(?<!\w)\.net(?!\s+(?:framework|maui|standard))(?:\s+core)?\b|\bdot\s*net\b(?!\s+framework)|\basp\.net\s+core\b",
       ("backend:dotnet",),
       "The team already knows .NET; keep the new back end on a supported .NET LTS and share libraries with the existing services.",
       versioned=True, eol="dotnet"),
    _p("java", "framework", "java", r"\bjava\b(?!\s*script)|\bjdk\b|\bj2ee\b|\bjakarta\s+ee\b", ("backend:java",),
       "Existing Java services can stay; new services can share the JVM and build tooling.", versioned=True, eol="java"),
    _p("spring", "framework", "spring", r"\bspring\s+(?:boot|mvc|framework|cloud)\b", ("backend:spring_boot",),
       "Keep Spring services and add new ones on a supported Spring Boot line.", versioned=True, eol="spring_boot"),
    _p("nodejs", "framework", "nodejs", r"\bnode\.?js\b|\bnode(?=\s+v?\d)|\bexpress\.js\b",
       ("backend:nodejs",), "Existing Node.js services can stay; run new ones on a current LTS line.",
       versioned=True, eol="nodejs"),
    _p("python", "framework", "python", r"\bpython\b", ("backend:python",),
       "Existing Python code can be reused for the back end and for data or ML work.", versioned=True, eol="python"),
    _p("django", "framework", "django", r"\bdjango\b", ("backend:django",),
       "Keep Django as the application framework and extend it with new apps.", versioned=True, eol="django"),
    _p("flask", "framework", "flask", r"\bflask\b|\bfastapi\b", ("backend:python",),
       "Keep the Flask or FastAPI service and add endpoints to it.", versioned=True),
    _p("laravel", "framework", "laravel", r"\blaravel\b", ("backend:laravel",),
       "Keep Laravel as the application framework.", versioned=True),
    _p("wordpress", "framework", "wordpress", r"\bword\s*press\b", ("backend:wordpress", "frontend:headless_cms"),
       "Keep WordPress for content and expose it through its REST API (headless) if a new front end is needed.", versioned=True),
    _p("drupal", "framework", "drupal", r"\bdrupal\b", ("backend:drupal",),
       "Keep Drupal for content and expose it through JSON:API if a new front end is needed.", versioned=True),
    _p("magento", "framework", "magento", r"\bmagento\b|\badobe\s+commerce\b", ("backend:magento",),
       "Keep the shop on Magento and integrate through its REST/GraphQL API.", versioned=True),
    _p("php", "framework", "php", r"\bphp\b", ("backend:php",),
       "The existing PHP code can stay behind an API while new work moves out gradually.", versioned=True, eol="php"),
    _p("rails", "framework", "rails", r"\bruby\s+on\s+rails\b|\brails\b", ("backend:rails",),
       "Keep the Rails application and extend it.", versioned=True, eol="rails"),
    _p("angularjs", "framework", "angularjs", r"\bangular\s*js\b|\bangular\.js\b|\bangular\s+1(?:\.\d+)*\b",
       ("frontend:angular",),
       "AngularJS has been unsupported since 2021; keep it behind the same API and replace screens one at a time.",
       eol="angularjs", eol_version="1"),
    _p("angular", "framework", "angular", r"\bangular\b(?!\.?\s*js)", ("frontend:angular",),
       "The team knows Angular; keep it for new screens.", versioned=True),
    _p("vue", "framework", "vue", r"\bvue(?:\.?js)?\b", ("frontend:vue",),
       "Keep Vue for new screens; Vue 2 reached end of life in 2023 and should move to Vue 3.", versioned=True, eol="vue"),
    _p("react", "framework", "react", r"\breact(?:\.?js)?\b(?!\s+native)", ("frontend:react",),
       "The team knows React; keep it for new screens.", versioned=True),
    _p("react_native", "framework", "react_native", r"\breact[\s-]native\b", ("frontend:react_native",),
       "Reuse the React Native app and share code with the web front end where possible."),
    _p("create_react_app", "framework", "create_react_app", r"\bcreate[\s-]react[\s-]app\b|\bcra\b",
       ("frontend:react",),
       "Create React App is deprecated; move the build to Vite or a framework such as Next.js.", eol="create_react_app"),
    _p("jquery", "framework", "jquery", r"\bj\s?query\b", ("frontend:legacy",),
       "jQuery pages can stay; add new interactive parts as separate components rather than rewriting everything.",
       versioned=True),
    _p("xamarin", "framework", "xamarin", r"\bxamarin\b", ("frontend:maui",),
       "Xamarin is no longer supported; port the app to .NET MAUI, reusing the C# business logic.", eol="xamarin"),
    _p("classic_asp_vb6", "framework", "legacy_microsoft", r"\bclassic\s+asp\b|\bvb6\b|\bvisual\s+basic\s+6\b|\bvbscript\b|\bvb\.?net\s+winforms\b",
       ("backend:facade",), _LEGACY),
    _p("cobol_mainframe", "framework", "legacy_mainframe",
       r"\bcobol\b|\bmainframe\b|\bas/?400\b|\biseries\b|\bfoxpro\b|\bpowerbuilder\b",
       ("backend:facade",), _LEGACY),
    # ---- messaging
    _p("kafka", "messaging", "kafka", r"\bkafka\b|\bconfluent\b|\bredpanda\b", ("messaging:kafka",),
       "Publish and consume through the existing Kafka cluster rather than adding a second broker.", versioned=True),
    _p("rabbitmq", "messaging", "rabbitmq", r"\brabbit\s*mq\b|\bamqp\b", ("messaging:rabbitmq",),
       "Reuse the existing RabbitMQ broker for background jobs and events.", versioned=True),
    _p("ibm_mq", "messaging", "ibm_mq", r"\bibm\s+mq\b|\bwebsphere\s+mq\b|\bmq\s*series\b", ("messaging:ibm_mq",),
       "Integrate over IBM MQ through a connector or a small bridge service."),
    _p("activemq", "messaging", "activemq", r"\bactive\s*mq\b|\bartemis\s+mq\b", ("messaging:jms",),
       "Reuse the existing ActiveMQ broker (JMS or AMQP)."),
    _p("aws_sqs_sns", "messaging", "aws_sqs_sns", r"\b(?:aws\s+|amazon\s+)?(?:sqs|sns)\b", ("messaging:sqs", "hosting:aws"),
       "Reuse the SQS/SNS queues and topics; this also points to an AWS account."),
    _p("azure_service_bus", "messaging", "azure_service_bus", r"\bazure\s+service\s*bus\b|\bservice\s*bus\s+(?:queue|topic)s?\b",
       ("messaging:service_bus", "hosting:azure"),
       "Reuse Azure Service Bus queues and topics; this also points to an Azure subscription."),
    # ---- SaaS and enterprise systems
    _p("microsoft_365", "saas", "microsoft_365",
       r"\b(?:microsoft|office|ms)\s*365\b|\bm365\b|\bo365\b|\bsharepoint\b|\bmicrosoft\s+teams\b|\bms\s+teams\b|\bexchange\s+online\b",
       ("saas:microsoft_graph",),
       "Reach Microsoft 365 (users, Teams, SharePoint, mail) through Microsoft Graph with delegated or app permissions."),
    _p("salesforce", "saas", "salesforce", r"\bsales\s*force\b|\bsfdc\b", ("saas:salesforce_api",),
       "Treat Salesforce as the CRM system of record and integrate through its REST API or Platform Events."),
    _p("sap_erp", "saas", "sap_erp", r"\bsap\s+(?:erp|ecc|r/?3|s/?4\s*hana|business\s*one|b1)\b|\bs/?4\s*hana\b|\bsap\b(?!\s+hana)",
       ("saas:sap_api",),
       "Integrate with SAP through its OData/BAPI interfaces or an integration layer; do not write to SAP tables directly."),
    _p("oracle_ebs", "saas", "oracle_ebs", r"\boracle\s+(?:e-?business|ebs|fusion|netsuite)\b|\be-?business\s+suite\b|\bpeoplesoft\b|\bjd\s*edwards\b|\bnetsuite\b",
       ("saas:oracle_api",), "Integrate through Oracle's REST or integration interfaces; keep it as the system of record."),
    _p("tally", "saas", "tally", r"\btally\s*(?:prime|erp|9)\b|\btally\b(?!\s+(?:up|the|of|all|marks))", ("saas:tally_export",),
       "Exchange vouchers with Tally through its XML interface or scheduled exports."),
    _p("zoho", "saas", "zoho", r"\bzoho\b", ("saas:zoho_api",), "Integrate with Zoho through its REST API and webhooks."),
    _p("servicenow", "saas", "servicenow", r"\bservice\s*now\b", ("saas:servicenow_api",),
       "Create and read tickets through the ServiceNow REST API."),
    _p("jira", "saas", "jira", r"\bjira\b|\batlassian\b|\bconfluence\b", ("saas:jira_api",),
       "Link work items through the Jira/Confluence REST API and webhooks."),
    _p("slack", "saas", "slack", r"\bslack\b", ("saas:slack_api",), "Send alerts and commands through a Slack app."),
    _p("shopify", "saas", "shopify", r"\bshopify\b", ("saas:shopify_api",),
       "Keep Shopify as the storefront and integrate through its Admin API and webhooks."),
    _p("stripe", "saas", "stripe", r"\bstripe\b", ("payments:stripe",),
       "Reuse the existing Stripe account as the payment gateway; check availability for new businesses in India."),
    _p("razorpay", "saas", "razorpay", r"\brazorpay\b", ("payments:razorpay",),
       "Reuse the existing Razorpay account as the payment gateway."),
    _p("twilio", "saas", "twilio", r"\btwilio\b", ("saas:twilio_api",),
       "Reuse Twilio for SMS, voice or WhatsApp; check Indian DLT registration for SMS."),
    # ---- infrastructure
    _p("vmware", "infrastructure", "vmware", r"\bvmware\b|\bvsphere\b|\besxi\b|\bvcenter\b", ("hosting:vm",),
       "Run on the existing VMware estate if capacity exists; otherwise treat it as a migration source."),
    _p("kubernetes", "infrastructure", "kubernetes", r"\bkubernetes\b|\bk8s\b|\bopenshift\b|\brancher\b", ("hosting:kubernetes",),
       "An existing cluster means Kubernetes operations skills exist: deploy there instead of building a new platform.",
       versioned=True),
    _p("on_prem", "infrastructure", "on_prem",
       r"\bon-?prem(?:ises?)?\b|\bdata\s*cent(?:er|re)s?\b|\bself-?hosted\s+servers?\b|\bco-?location\b|\bcolo\b",
       ("hosting:on_prem",),
       "Existing on-premises systems need a private link or VPN and a data-sync strategy; they are not a hosting target by themselves."),
    _p("aws_account", "infrastructure", "aws", r"\baws\b|\bamazon\s+web\s+services\b|\bec2\b", ("hosting:aws",),
       "An existing AWS account makes AWS the least-friction cloud (soft preference)."),
    _p("azure_account", "infrastructure", "azure",
       r"\bmicrosoft\s+azure\b|\bon\s+azure\b|\bazure\s+(?:subscription|tenant|account|vms?|virtual\s+machines?|app\s+service|functions)\b",
       ("hosting:azure",), "An existing Azure subscription makes Azure the least-friction cloud (soft preference)."),
    _p("gcp_account", "infrastructure", "gcp", r"\bgcp\b|\bgoogle\s+cloud\b|\bgce\b|\bgke\b", ("hosting:gcp",),
       "An existing Google Cloud project makes Google Cloud the least-friction cloud (soft preference)."),
    _p("github", "infrastructure", "github", r"\bgit\s*hub\b", ("ci:github_actions",),
       "Reuse GitHub for source and CI (Actions)."),
    _p("gitlab", "infrastructure", "gitlab", r"\bgit\s*lab\b", ("ci:gitlab_ci",), "Reuse GitLab for source and CI."),
    _p("azure_devops", "infrastructure", "azure_devops", r"\bazure\s+devops\b|\bvsts\b|\btfs\b", ("ci:azure_devops",),
       "Reuse Azure DevOps pipelines for build and release."),
    _p("jenkins", "infrastructure", "jenkins", r"\bjenkins\b", ("ci:jenkins",), "Reuse Jenkins for builds if it is maintained."),
    _p("windows_server", "infrastructure", "windows_server", r"\bwindows\s+server\b", ("hosting:vm",),
       "Windows Server machines can host IIS or .NET workloads but need patching; plan a move to a supported release or a managed service.",
       versioned=True, eol="windows_server"),
    _p("centos", "infrastructure", "centos", r"\bcent\s*os\b", ("hosting:vm",),
       "CentOS machines should move to RHEL, AlmaLinux or Rocky Linux.", versioned=True, eol="centos"),
    _p("ubuntu", "infrastructure", "ubuntu", r"\bubuntu\b", ("hosting:vm",),
       "Ubuntu machines can be reused; keep them on a supported LTS release.", versioned=True, eol="ubuntu"),
    _p("rhel", "infrastructure", "rhel", r"\brhel\b|\bred\s*hat(?:\s+enterprise\s+linux)?\b", ("hosting:vm",),
       "RHEL machines can be reused; keep them on a supported major release.", versioned=True, eol="rhel"),
    _p("docker_compose_v1", "infrastructure", "docker_compose_v1", r"\bdocker[- ]compose\s+v?1(?:\.\d+)*\b|\bdocker-compose\s+1\b",
       ("hosting:container",), "Compose v1 is unsupported; the same files run on the Compose v2 plugin.", eol="docker_compose_v1"),
    _p("docker", "infrastructure", "docker", r"\bdocker\b|\bcontainers?\b", ("hosting:container",),
       "Existing container images can be deployed to any container host."),
    _p("internet_explorer", "infrastructure", "internet_explorer", r"\binternet\s+explorer\b|\bie\s?11\b", ("frontend:legacy",),
       "Internet Explorer 11 is retired; target Edge, and use IE mode only for old internal pages.",
       versioned=True, eol="internet_explorer", eol_version="11"),
    _p("gcp_iot_core", "infrastructure", "gcp_iot_core", r"\b(?:google\s+cloud\s+|gcp\s+)?iot\s+core\b", ("messaging:mqtt",),
       "Google Cloud IoT Core was retired in 2023; devices need a new MQTT broker or an AWS/Azure IoT service.", eol="gcp_iot_core"),
    _p("firebase_dynamic_links", "infrastructure", "firebase_dynamic_links", r"\b(?:firebase\s+)?dynamic\s+links\b",
       ("frontend:deep_links",), "Firebase Dynamic Links stopped in 2025; replace them with App Links and Universal Links.",
       eol="firebase_dynamic_links"),
    _p("azure_media_services", "infrastructure", "azure_media_services", r"\bazure\s+media\s+services\b|\bams\s+v[23]\b",
       ("services:video",), "Azure Media Services was retired in 2024; move video to Mux or Cloudflare Stream.",
       eol="azure_media_services"),
    _p("azure_cdn_classic", "infrastructure", "azure_cdn_classic",
       r"\bazure\s+cdn\s+(?:standard\s+)?(?:from\s+microsoft|classic)\b|\bazure\s+cdn\b(?!\s+from\s+edgio)(?!\s+from\s+verizon)",
       ("hosting:cdn",), "Azure CDN Standard (classic) is retiring; move to Azure Front Door Standard/Premium.",
       eol="azure_cdn_classic"),
    _p("azure_cdn_edgio", "infrastructure", "azure_cdn_edgio", r"\bazure\s+cdn\s+from\s+edgio\b|\bedgio\b",
       ("hosting:cdn",), "Azure CDN from Edgio has been retired; move to Azure Front Door.", eol="azure_cdn_edgio"),
    _p("azure_front_door_classic", "infrastructure", "azure_front_door_classic",
       r"\bazure\s+front\s*door\s+\(?classic\)?|\bfront\s*door\s+classic\b",
       ("hosting:cdn",), "Azure Front Door (classic) is retiring; migrate to the Standard/Premium tier.",
       eol="azure_front_door_classic"),
    _p("adal", "identity", "adal", r"\badal\b|\bazure\s+ad\s+authentication\s+library\b", ("identity:oidc",),
       "ADAL is unsupported; move token acquisition to MSAL.", eol="adal"),
    _p("azure_ad_graph", "identity", "azure_ad_graph", r"\bazure\s+ad\s+graph\b|\bgraph\.windows\.net\b", ("saas:microsoft_graph",),
       "Azure AD Graph is retired; call Microsoft Graph instead.", eol="azure_ad_graph"),
    _p("app_center", "infrastructure", "app_center", r"\bapp\s*center\b", ("ci:mobile_builds",),
       "App Center is retired; move builds to EAS Build, fastlane or Firebase App Distribution.", eol="app_center"),
)

BY_ID: dict[str, Pattern] = {p.id: p for p in PATTERNS}

_COMPILED = tuple(re.compile(p.regex, re.IGNORECASE) for p in PATTERNS)
_VERSION = re.compile(r"[\s:/-]{0,3}(?:v|version\s+|ver\.?\s*)?(\d+(?:\.\d+){0,2}[a-z]?)(?!\d)", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:no|not|without|never|nor|zero|neither|excluding|except|no\s+longer|don't|doesn't|isn't|aren't)\b(?:\W+\w+){0,2}\W*$",
    re.IGNORECASE)


def _negated(text: str, start: int) -> bool:
    before = text[:start]
    cut = max(before.rfind("."), before.rfind(";"), before.rfind("\n"), before.rfind(","))
    return bool(_NEGATION.search(before[cut + 1:]))


def match(text: str) -> tuple[PatternHit, ...]:
    """All patterns that fire on ``text``: one hit per pattern id, in PATTERNS order."""
    if not isinstance(text, str):
        return ()
    hits = []
    for pat, rx in zip(PATTERNS, _COMPILED):
        m = next((m for m in rx.finditer(text) if not _negated(text, m.start())), None)
        if m is None:
            continue
        version = None
        if pat.versioned:
            v = _VERSION.match(text, m.end())
            version = v.group(1) if v else None
        hits.append(PatternHit(pat.id, pat.family, pat.kind, version, (m.start(), m.end()), m.group(0),
                               pat.eol_product, pat.eol_version))
    return tuple(hits)


def eol_args(hit: PatternHit) -> tuple[str, str | None] | None:
    """(product, version) to pass to ``kb.eol.verdict``, or None when the pattern has no EOL product."""
    if hit.eol_product is None:
        return None
    return hit.eol_product, hit.version if hit.version is not None else hit.eol_version

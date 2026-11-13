"""Input schema: the single source of truth for validation, the web form and the report.

Every field carries: its type and allowed values, whether it is required, the default the
engine applies when it is absent, *why it matters architecturally*, which decisions it moves,
and the research sources behind it. Fields with ``extra=True`` are StackSense additions to the
standard schema; the engine works without them (defaults are recorded as assumptions).
"""
from __future__ import annotations

PROJECT_TYPES = [
    "content_site", "web_app", "saas_b2b", "ecommerce", "marketplace", "social",
    "realtime_collab", "fintech", "healthtech", "data_analytics", "iot", "ai_ml_product",
    "internal_tool", "gaming", "api_platform", "other",
]
PLATFORMS = ["web", "android", "ios", "desktop", "api_only"]
TRAFFIC = ["steady", "spiky", "seasonal"]
WORKLOAD = ["read_heavy", "balanced", "write_heavy"]
EXPERIENCE = ["beginner", "intermediate", "senior", "mixed"]
CLOUDS = ["any", "aws", "gcp", "azure", "none"]
DEPLOYMENT = ["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"]
RESIDENCY = ["none", "india", "eu", "us", "other"]
AUTH = ["none", "email_password", "social", "phone_otp", "enterprise_sso"]
ML = ["none", "inference_api", "llm_rag", "training"]
AVAILABILITY = ["99", "99.9", "99.95", "99.99"]
COMPLIANCE = ["gdpr", "dpdp", "hipaa", "pci_dss", "rbi_localisation", "soc2", "iso27001"]
PRIORITY_KEYS = ["cost", "time_to_market", "scalability", "performance", "maintainability", "security"]

# Extra (StackSense) enums
GEO_SPREAD = ["single_city", "single_country", "multi_region", "global"]
LOCK_IN = ["low", "medium", "high"]
CONSISTENCY = ["strong", "eventual", "auto"]
DATA_SHAPE = ["auto", "relational", "document", "key_value", "time_series", "graph", "analytical"]
NOTIFICATIONS = ["email", "push", "sms"]  # empty list means no notifications
LICENCES = ["microsoft_enterprise", "oracle", "aws_credits", "gcp_credits", "azure_credits", "none"]
CMS = ["auto", "none", "git_markdown", "headless"]

# Constraint class of each field: hard (never violated silently), soft (traded off), info (display only).
HARD_PATHS = {"infrastructure.data_residency", "compliance", "infrastructure.deployment_model",
              "infrastructure.cloud_preference"}
INFO_PATHS = {"project.name"}
# UI step number per group.
STEPS = {"Project": 1, "Scale": 2, "Team": 3, "Budget & timeline": 4, "Infrastructure": 5,
         "Requirements": 6, "Compliance": 7, "Priorities": 7}

# Each entry: path -> spec
FIELDS: dict[str, dict] = {}


def _f(path, type_, required=False, default=None, enum=None, minimum=None, maximum=None,
       group="", label="", why="", affects=(), sources=(), extra=False, item_enum=None,
       exclusive_min=False, nullable=False, ui="auto", help_example=None,
       constraint=None, step=None, unit=""):
    if constraint is None:
        constraint = "hard" if path in HARD_PATHS else ("info" if path in INFO_PATHS else "soft")
    if step is None:
        step = STEPS.get(group, 1)
    FIELDS[path] = {
        "path": path, "type": type_, "required": required, "default": default, "enum": enum,
        "item_enum": item_enum, "minimum": minimum, "maximum": maximum,
        "exclusive_min": exclusive_min, "nullable": nullable, "group": group,
        "label": label or path.split(".")[-1].replace("_", " "), "why": why,
        "affects": list(affects), "sources": list(sources), "extra": extra, "ui": ui,
        "example": help_example, "constraint": constraint, "step": step, "unit": unit,
    }


# ---------------------------------------------------------------- project
_f("project.name", "string", group="Project", label="Project name",
   why="Shown in output only; never influences the stack.", affects=[])
_f("project.type", "enum", required=True, enum=PROJECT_TYPES, group="Project", label="Project type",
   why="Domain sets the prior: content sites are static-first, fintech needs ACID ledgers and "
       "audit trails, realtime collaboration needs stateful connection servers, internal tools "
       "favour batteries-included CRUD frameworks.",
   affects=["architecture_style", "frontend", "backend", "database", "supporting"],
   sources=["so_survey_2025", "fowler_monolith_first"])
_f("project.description", "string", group="Project", label="Description", ui="textarea",
   why="Parsed deterministically for domain signals (ledger, chat, GPS, KYC, video, low-end "
       "devices...). Signals add supporting services or flag mismatches with explicit fields; "
       "explicit fields always win.",
   affects=["supporting", "warnings"])
_f("project.platforms", "list", required=True, item_enum=PLATFORMS, group="Project", label="Platforms",
   why="Determines which client technologies are needed and whether one cross-platform codebase "
       "pays off for the team size and timeline.",
   affects=["frontend", "architecture_style", "warnings"], sources=["so_survey_2025", "rn_docs", "flutter_docs"])

# ---------------------------------------------------------------- scale
_f("scale.users_at_launch", "integer", required=True, minimum=0, group="Scale", label="Users at launch",
   why="Sets the starting size class and whether free tiers are viable on day one.",
   affects=["hosting", "cost"])
_f("scale.users_12_months", "integer", required=True, minimum=0, group="Scale", label="Users after 12 months",
   why="Primary sizing input. We size for 12-month load, not launch load, to avoid an early re-platform.",
   affects=["hosting", "database", "supporting", "cost", "architecture_style"])
_f("scale.peak_concurrent_users", "integer", minimum=0, group="Scale", label="Peak concurrent users",
   why="Drives connection counts (WebSockets, DB pools) and compute sizing. If absent we estimate "
       "5% of 12-month users (typical DAU/MAU x peak-hour concentration) and record it.",
   affects=["hosting", "database", "supporting", "cost"], sources=["aws_well_architected"])
_f("scale.traffic_pattern", "enum", default="steady", enum=TRAFFIC, group="Scale", label="Traffic pattern",
   why="Spiky or seasonal traffic favours autoscaling/scale-to-zero platforms and queues that absorb bursts; "
       "steady traffic favours reserved, always-on capacity.",
   affects=["hosting", "supporting"], sources=["aws_well_architected"])
_f("scale.workload", "enum", default="balanced", enum=WORKLOAD, group="Scale", label="Workload",
   why="Read-heavy systems benefit from CDN and cache; write-heavy systems need a database that "
       "sustains write throughput and queues to buffer bursts.",
   affects=["database", "supporting"], sources=["ddia"])
_f("scale.data_volume_gb_12_months", "number", minimum=0, group="Scale", label="Data volume after 12 months (GB)",
   why="Separates databases that fit on one primary from those needing partitioning, and sizes object "
       "storage cost.", affects=["database", "supporting", "cost"], sources=["ddia", "db_engines"])
_f("scale.geographic_spread", "enum", default="single_country", enum=GEO_SPREAD, group="Scale",
   label="Geographic spread of users", extra=True,
   why="Global audiences need edge delivery (CDN, edge compute) and possibly multi-region reads; "
       "a single-city audience does not, and a nearby single region keeps latency low.",
   affects=["hosting", "supporting", "warnings"], sources=["cloudflare_network"])
_f("scale.peak_rps", "integer", minimum=0, group="Scale", label="Peak requests/second", extra=True,
   why="Overrides the engine's request-rate estimate (0.2 req/s per concurrent user) when known.",
   affects=["hosting", "supporting", "cost"], sources=["sre_handling_overload"])

# ---------------------------------------------------------------- team
_f("team.size", "integer", required=True, minimum=1, group="Team", label="Team size (engineers)",
   why="Conway's law and coordination cost: small teams should ship one deployable; service splits only "
       "pay off once several teams need independent deploys.",
   affects=["architecture_style", "hosting", "backend"], sources=["fowler_monolith_first", "team_topologies"])
_f("team.experience", "enum", required=True, enum=EXPERIENCE, group="Team", label="Experience",
   why="Beginners need opinionated, well-documented frameworks and managed services; seniors can absorb "
       "operational complexity when it buys performance or control.",
   affects=["backend", "hosting", "supporting", "warnings"])
_f("team.languages", "list", required=True, group="Team", label="Languages the team knows",
   why="The strongest single predictor of delivery speed. We score skill fit explicitly and explain "
       "any choice outside the team's languages.",
   affects=["frontend", "backend"], sources=["so_survey_2025"])
_f("team.has_devops", "boolean", default=False, group="Team", label="Has DevOps capability",
   why="Without someone to run infrastructure, self-managed Kubernetes, databases and brokers are a "
       "reliability risk; managed services are preferred.",
   affects=["hosting", "database", "supporting"], sources=["dora_2024"])
_f("team.willing_to_learn", "boolean", default=True, group="Team", label="Willing to learn a new language", extra=True,
   why="When false, components outside team.languages receive a much heavier penalty.",
   affects=["frontend", "backend"], sources=["dora_learning_culture", "so_survey_2025"])

# ---------------------------------------------------------------- budget/timeline
_f("budget.monthly_infra_usd", "number", required=True, minimum=0, group="Budget & timeline",
   label="Monthly infra budget (USD)",
   why="Soft constraint traded off against priorities. Zero budget restricts to free tiers; an estimate "
       "above budget is always surfaced as a warning, never silently.",
   affects=["hosting", "database", "supporting", "cost", "warnings"],
   sources=["aws_pricing", "vercel_pricing", "supabase_pricing", "do_pricing", "cloudflare_pricing"])
_f("timeline.mvp_weeks", "integer", required=True, minimum=1, group="Budget & timeline", label="Weeks to MVP",
   why="Short timelines favour batteries-included frameworks, BaaS and managed services, and "
       "cross-platform clients.", affects=["frontend", "backend", "hosting", "warnings"])

_f("team.growth_12_months", "integer", minimum=0, group="Team", label="Team size after 12 months", extra=True,
   why="Hiring plans change the architecture horizon: a team expected to triple can justify module "
       "boundaries earlier, while a flat team should keep one deployable. Defaults to team.size.",
   affects=["architecture_style", "backend", "warnings"], sources=["team_topologies", "fowler_monolith_first"])

# ---------------------------------------------------------------- infrastructure
_f("infrastructure.cloud_preference", "enum", default="any", enum=CLOUDS, group="Infrastructure",
   label="Cloud preference",
   why="Hard constraint when explicit: hosting and managed services must come from that provider "
       "('none' = avoid the big three hyperscalers).", affects=["hosting", "database", "supporting"])
_f("infrastructure.deployment_model", "enum", default="managed_cloud", enum=DEPLOYMENT, group="Infrastructure",
   label="Deployment model",
   why="Hard constraint. on_premise/air_gapped allow only self-hostable software with no SaaS or CDN "
       "dependencies; air_gapped additionally forbids any runtime call to the internet.",
   affects=["hosting", "database", "backend", "supporting"], sources=["rke2_airgap", "harbor_docs"])
_f("infrastructure.data_residency", "enum", default="none", enum=RESIDENCY, group="Infrastructure",
   label="Data residency",
   why="Hard constraint: every component that stores personal data must have an in-region deployment.",
   affects=["hosting", "database", "supporting"],
   sources=["aws_regions", "gcp_regions", "azure_regions", "supabase_regions", "neon_regions", "fly_regions"])
_f("infrastructure.existing_systems", "list", default=[], group="Infrastructure", label="Existing systems",
   why="Reuse beats rebuild: existing identity providers, databases and codebases bias choices, and "
       "end-of-life systems are flagged.", affects=["backend", "database", "supporting", "warnings"],
   sources=["endoflife_date", "ms_lifecycle"])
_f("infrastructure.existing_licences", "list", default=[], item_enum=LICENCES, group="Infrastructure",
   label="Existing licences and credits", extra=True,
   why="Cloud credits and enterprise licences make one provider effectively cheaper or free; Microsoft or "
       "Oracle licences favour their own runtimes and databases. Used as a soft bias, never as a hard filter.",
   affects=["hosting", "database", "backend", "cost"], sources=["aws_pricing", "azure_appservice_pricing", "gcp_run_pricing"])
_f("infrastructure.lock_in_tolerance", "enum", default="medium", enum=LOCK_IN, group="Infrastructure",
   label="Vendor lock-in tolerance", extra=True,
   why="Low tolerance penalises proprietary BaaS/serverless APIs (Firebase, DynamoDB, Workers-only APIs) "
       "in favour of portable Postgres + containers.", affects=["backend", "database", "hosting"],
   sources=["hohpe_lockin"])
_f("infrastructure.open_source_only", "boolean", default=False, group="Infrastructure",
   label="Open-source components only", extra=True,
   why="Filters out proprietary software (managed services running open-source engines remain allowed).",
   affects=["backend", "database", "supporting"], sources=["osi_osd"])

# ---------------------------------------------------------------- requirements
_f("requirements.realtime", "boolean", default=False, group="Requirements", label="Realtime",
   why="Persistent connections rule out plain request/response serverless for the realtime path and "
       "need pub/sub fan-out across instances.", affects=["backend", "hosting", "supporting"],
   sources=["socketio_docs", "cf_durable_objects", "signalr_docs"])
_f("requirements.offline_support", "boolean", default=False, group="Requirements", label="Offline support",
   why="Needs an on-device database and a sync protocol with conflict handling; strongly shapes the client.",
   affects=["frontend", "database", "supporting"], sources=["android_offline_first", "powersync_docs"])
_f("requirements.full_text_search", "boolean", default=False, group="Requirements", label="Full-text search",
   why="Small corpora use the database's built-in FTS; larger or typo-tolerant search needs a search engine.",
   affects=["supporting", "database"], sources=["pg_fts", "meilisearch_docs", "opensearch_docs"])
_f("requirements.file_media_storage", "boolean", default=False, group="Requirements", label="File/media storage",
   why="Binary uploads belong in object storage (not the DB), usually behind a CDN.",
   affects=["supporting", "cost"], sources=["aws_s3_docs"])
_f("requirements.payments", "boolean", default=False, group="Requirements", label="Payments",
   why="Use a payment gateway with hosted checkout/tokenisation to keep PCI scope minimal; gateway "
       "choice depends on country (UPI in India).", affects=["supporting", "database"],
   sources=["pci_saq", "razorpay_docs", "stripe_india"])
_f("requirements.auth", "enum", default="none", enum=AUTH, group="Requirements", label="Authentication",
   why="Phone OTP in India needs DLT-registered SMS; enterprise SSO needs SAML/OIDC; social login "
       "needs an OAuth broker.", affects=["supporting", "backend"],
   sources=["trai_dlt", "keycloak_docs", "entra_external_id"])
_f("requirements.multi_tenant", "boolean", default=False, group="Requirements", label="Multi-tenant",
   why="Needs tenant isolation (row-level security or schema-per-tenant) and org-aware auth.",
   affects=["database", "supporting"], sources=["pg_rls"])
_f("requirements.ml_features", "enum", default="none", enum=ML, group="Requirements", label="ML features",
   why="Inference needs a model-serving path; RAG needs an LLM provider plus a vector store; training "
       "needs GPU jobs and experiment tracking.", affects=["supporting", "backend"],
   sources=["pgvector", "sagemaker_docs", "vllm_docs"])
_f("requirements.seo_critical", "boolean", default=False, group="Requirements", label="SEO critical",
   why="Public pages must be server-rendered or pre-rendered; client-only SPAs are penalised.",
   affects=["frontend"], sources=["google_js_seo"])
_f("requirements.availability", "enum", default="99.9", enum=AVAILABILITY, group="Requirements",
   label="Availability target (%)",
   why="99.9% allows 43 min downtime/month (single region, managed); 99.95% needs multi-AZ; 99.99% "
       "(4.3 min/month) needs multi-AZ plus failover automation and on-call maturity.",
   affects=["hosting", "database", "cost", "warnings"], sources=["google_sre_book", "aws_well_architected"])
_f("requirements.p95_latency_ms", "integer", minimum=0, exclusive_min=True, nullable=True, group="Requirements",
   label="Target p95 latency (ms)",
   why="Tight targets favour compiled runtimes, caching and in-region/edge placement.",
   affects=["backend", "hosting", "supporting", "warnings"])
_f("requirements.notifications", "list", default=[], item_enum=NOTIFICATIONS, group="Requirements",
   label="Notification channels", extra=True,
   why="Adds email/push/SMS providers; push on Android/iOS means FCM/APNs.", affects=["supporting"],
   sources=["fcm_docs"])
_f("requirements.background_jobs", "boolean", default=False, group="Requirements", label="Background jobs", extra=True,
   why="Scheduled/async work needs a queue or job runner; small apps use a DB-backed queue instead of a broker.",
   affects=["supporting"], sources=["queue_load_leveling", "pgboss"])
_f("requirements.consistency", "enum", default="auto", enum=CONSISTENCY, group="Requirements",
   label="Consistency requirement", extra=True,
   why="'strong' forces ACID relational stores; 'auto' infers strong for money, ledgers and bookings.",
   affects=["database"], sources=["ddia"])
_f("requirements.data_shape", "enum", default="auto", enum=DATA_SHAPE, group="Requirements",
   label="Dominant data shape", extra=True,
   why="Time-series, graph and analytical workloads have specialised stores; 'auto' infers from project type.",
   affects=["database"], sources=["db_engines", "timescale_docs", "clickhouse_docs"])
_f("requirements.cms", "enum", default="auto", enum=CMS, group="Requirements", label="Content management", extra=True,
   why="Whether non-developers edit content (headless CMS) or the owner writes Markdown in git.",
   affects=["supporting", "backend"], sources=["decap_cms", "payload_docs"])

# ---------------------------------------------------------------- compliance & priorities
_f("compliance", "list", default=[], item_enum=COMPLIANCE, group="Compliance", label="Compliance regimes",
   why="Hard constraint: only vendors with the matching attestation (BAA for HIPAA, PCI DSS AoC, "
       "ISO 27001/SOC 2 reports) or self-hosted components are allowed; RBI localisation forces "
       "payment data into India.",
   affects=["hosting", "database", "supporting", "warnings"],
   sources=["rbi_localisation", "dpdp_act", "gdpr_text", "hhs_hipaa_cloud", "pci_saq",
            "aws_compliance", "azure_compliance", "gcp_compliance"])
for _k in PRIORITY_KEYS:
    _f(f"priorities.{_k}", "integer", default=3, minimum=1, maximum=5, group="Priorities",
       label=_k.replace("_", " "),
       why="Weights (1-5) on the matching scoring criterion for every candidate in every layer.",
       affects=["frontend", "backend", "database", "hosting", "supporting"])

SECTIONS = ["project", "scale", "team", "budget", "timeline", "infrastructure", "requirements",
            "compliance", "priorities"]
TOP_LEVEL_ALLOWED = set(SECTIONS) | {"scenario_id"}

_UNITS = {"scale.users_at_launch": "users", "scale.users_12_months": "users",
          "scale.peak_concurrent_users": "users", "scale.data_volume_gb_12_months": "GB",
          "scale.peak_rps": "requests/s", "team.size": "engineers", "team.growth_12_months": "engineers",
          "budget.monthly_infra_usd": "USD/month", "timeline.mvp_weeks": "weeks",
          "requirements.p95_latency_ms": "ms", "requirements.availability": "%"}
for _p, _u in _UNITS.items():
    FIELDS[_p]["unit"] = _u


def required_paths() -> list[str]:
    return [p for p, s in FIELDS.items() if s["required"]]


def schema_for_ui() -> dict:
    """Serialisable schema, consumed by the web form."""
    groups: dict[str, list] = {}
    for spec in FIELDS.values():
        groups.setdefault(spec["group"], []).append(spec)
    return {"groups": [{"name": g, "fields": f} for g, f in groups.items()]}

"""Compliance regimes and per-vendor attestation facts (hard filter F5 input).

Attestation values: ``yes`` | ``plan:<name>`` | ``no`` | ``self`` | ``unknown`` | ``na``.
  yes        the vendor/service holds the attestation or signs the agreement on the normal terms
  plan:<n>   available only on plan/add-on <n> (BAA, report); the engine must also pick that plan
  no         vendor states it does not offer/claim it
  self       self-hosted: the team carries the control
  unknown    not confirmed from an official page on 2026-11-13: FAILS CLOSED
  na         the regime puts no vendor attestation on this kind of vendor
All facts were checked on 2026-11-13 (confidence V) or are ``unknown``. Provider-level SOC 2 / ISO / PCI do not mean
every service is in scope; per-service scope is noted where verified.

Facts checked (product | fact | result | URL):
| AWS | regions ap-south-1, ap-south-2 (opt-in), EU/US list | V | https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html |
| AWS | HIPAA: BAA + eligible list (Bedrock, Cognito, S3, Lambda, ECS, DynamoDB, ElastiCache, OpenSearch, SES, SNS, Aurora; RDS only some engines; Fargate ECS/EKS) | V | https://aws.amazon.com/compliance/hipaa-eligible-services-reference/ |
| AWS | PCI scope: Cognito, RDS, S3, Lambda, ECS, DynamoDB, Bedrock (not Marketplace), ElastiCache, SES | V | https://aws.amazon.com/compliance/services-in-scope/PCI/ |
| AWS | ISO 27001, SOC, PCI, HIPAA, GDPR programs | V | https://aws.amazon.com/compliance/programs/ |
| AWS | GDPR: Service Terms include SCCs; DPA linked | V | https://aws.amazon.com/compliance/gdpr-center/ |
| Cognito | user-pool endpoints in ap-south-1/-2, EU, US | V | https://docs.aws.amazon.com/general/latest/gr/cognito_identity.html |
| Bedrock | in. India geographic profile, ap-south-1 <-> ap-south-2 only; global.* routes to all commercial regions | V | https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-expands-claude-model-availability-to-india-cross-region-inference/ |
| Azure | regions Central/South/West India, India South Central; EU, US | V | https://learn.microsoft.com/en-us/azure/reliability/regions-list |
| Azure/Microsoft | HIPAA BAA via Online Services DPA by default; Entra ID in O365 BAA scope | V | https://learn.microsoft.com/en-us/compliance/regulatory/offering-hipaa-hitech |
| Azure | ISO, SOC 1/2/3, PCI AOC documents in Service Trust Portal | V | https://learn.microsoft.com/en-us/azure/compliance/offerings/ |
| Azure Managed Redis | Central India availability | UNKNOWN (region table is a separate JS page) | https://learn.microsoft.com/en-us/azure/redis/overview |
| GCP | asia-south1 Mumbai, asia-south2 Delhi, europe-west3 etc. | V | https://docs.cloud.google.com/compute/docs/regions-zones |
| GCP | BAA; Identity Platform (no PHI in custom attrs), Firestore, Cloud Run, Cloud SQL covered; Firebase as a whole not listed | V | https://docs.cloud.google.com/docs/security/compliance/hipaa |
| GCP | ISO 27001:2022 | V | https://cloud.google.com/security/compliance/iso-27001 |
| GCP | PCI DSS (Filestore docs list it, product-level) | V (product) | https://docs.cloud.google.com/filestore/docs/compliance |
| GCP | SOC 2 | UNKNOWN (page text truncated) | https://cloud.google.com/security/compliance/soc-2 |
| Firestore | asia-south1/2, eur3 + EU regions, nam5, us-central1 | V | https://firebase.google.com/docs/firestore/locations |
| Firebase Auth | "run only from US data centers"; no location choice; ISO 27001 + SOC 1/2/3 for Firebase services; BAA not stated | V | https://firebase.google.com/support/privacy |
| Supabase | Mumbai ap-south-1 only India region; EU: Ireland, Frankfurt, Paris, Stockholm (London, Zurich not EU) | V | https://supabase.com/docs/guides/platform/regions |
| Supabase | SOC 2 Type 2 (report for Team/Enterprise); HIPAA needs signed BAA + HIPAA add-on | V | https://supabase.com/docs/guides/security/soc-2-compliance |
| Supabase | HIPAA add-on enables High Compliance projects; plan not named; no region restriction stated | V | https://supabase.com/docs/guides/platform/hipaa-projects |
| Vercel | bom1 Mumbai; fra1, cdg1, dub1, arn1; iad1 default | V | https://vercel.com/docs/regions |
| Vercel | SOC 2 T2, ISO 27001:2022, PCI SAQ-D/SAQ-A AOC, GDPR DPA; BAA: Pro add-on, Enterprise on request | V | https://vercel.com/docs/security/compliance |
| DigitalOcean | BLR1 products; EU AMS3/FRA1 (+LON1 UK); US list | V | https://docs.digitalocean.com/platform/regional-availability/ |
| DigitalOcean | SOC 2/3 Type II; ISO 27001 only for colocated facilities; PCI SAQ-A for own admin env; HIPAA/GDPR not stated | V -> mostly unknown | https://www.digitalocean.com/trust/certification-reports |
| Render | regions Oregon, Ohio, Virginia, Frankfurt, Singapore | V | https://render.com/docs/regions |
| Render | SOC 2 T2, ISO 27001 (Pro+ get reports), GDPR DPA all workspaces; HIPAA-enabled workspace | V | https://render.com/docs/certifications-compliance |
| Render | HIPAA needs Scale or Enterprise plan; Singapore not allowed | V | https://render.com/docs/hipaa-compliance |
| Railway | regions US West, US East, EU West Amsterdam, SE Asia Singapore | V | https://docs.railway.com/reference/deployment-regions |
| Railway | SOC 2 T2 + SOC 3; HIPAA BAA paid add-on with spend threshold; GDPR DPA self-serve | V | https://docs.railway.com/enterprise/compliance |
| Fly.io | MPG regions ams, dfw, fra, iad, lax, lhr, ord, sjc (no bom) | V | https://docs.fly.io/reference/regions |
| Fly.io | compliance page | UNKNOWN (404) | https://docs.fly.io/security/compliance |
| Neon | regions: AWS us-east-1/-2, us-west-2, eu-central-1, eu-west-2, ap-southeast-1/2, sa-east-1 (no India) | V | https://neon.com/docs/introduction/regions |
| Neon | SOC 2, ISO 27001, ISO 27701; HIPAA self-serve on Scale plan with BAA | V | https://neon.com/docs/security/hipaa |
| Cloudflare R2/D1 | jurisdictions eu, fedramp, us (PLAN MISSED us); no India | V | https://developers.cloudflare.com/r2/reference/data-location/ |
| Cloudflare DLS | Enterprise-only add-on; India not mentioned | V -> India UNKNOWN | https://developers.cloudflare.com/data-localization/ |
| Cloudflare | SOC 2, ISO 27001, PCI DSS L1 (blog) | V (blog) | https://blog.cloudflare.com/cloudflare-certifications |
| Upstash | Mumbai ap-south-1; EU eu-west-1/eu-central-1/eu-west-2 | V | https://upstash.com/docs/redis/features/globaldatabase |
| Upstash | SOC 2 T2 (Prod Pack/Enterprise), HIPAA BAA Enterprise, GDPR DPA, no PCI claim | V | https://upstash.com/docs/common/help/compliance |
| MongoDB Atlas | AWS AP_SOUTH_1, AP_SOUTH_2, EU_CENTRAL_1, US_EAST_1 | V | https://www.mongodb.com/docs/atlas/reference/amazon-aws/ |
| MongoDB Atlas | ISO 27001/17/18, PCI DSS, "SOC" (type unspecified); BAA in Cloud Terms for self-service accounts | V | https://www.mongodb.com/products/platform/trust and /hipaa |
| Auth0 | public regions US, UK, EU, AU, JP, CA; no India; BAA not on the page | V -> hipaa unknown | https://auth0.com/cloud |
| Clerk | no region choice (US); SOC 2 T2; HIPAA BAA on Enterprise; no PCI claim | V | https://clerk.com/security |
| Sentry | storage US or EU only; BAA on Business tier or higher | V | https://docs.sentry.io/organization/data-storage-location/ , https://sentry.io/trust/privacy/ |
| Stripe | PCI Service Provider L1, SOC 1/2 T2, DPA; India invite-only for new businesses | V | https://docs.stripe.com/security , https://support.stripe.com/questions/stripe-accounts-are-invite-only-in-india |
| Razorpay | PCI DSS L1, RBI PA authorisation, data localisation, UPI (vendor's own docs) | V (self-claim) | https://razorpay.com/docs/payments/payment-gateway/ |
| Cashfree | PCI DSS L1 (own docs); RBI localisation unverified | V / UNKNOWN | https://www.cashfree.com/docs/security.md |
| PayU, MSG91, Entra data location, Typesense/Meilisearch/Algolia cloud, GitHub Actions | not checked | UNKNOWN | - |

Reconciliation pass (2026-11-13, per-service rows, used by kb.bindings):
| AWS | HIPAA list: Lightsail and App Runner absent; Amplify Console, EC2, EKS, ECS, Fargate (ECS/EKS), Lambda, API Gateway, Aurora, RDS, DynamoDB, Outposts, Cognito present | V | https://aws.amazon.com/compliance/hipaa-eligible-services-reference/ |
| AWS | PCI / SOC / ISO lists: Lightsail absent; Aurora has no row; Amplify, EC2, EKS, ECS, Lambda, RDS, DynamoDB, Outposts, App Runner, Cognito, S3 present | V | .../services-in-scope/PCI/ , .../services-in-scope/SOC/ , https://aws.amazon.com/compliance/iso-certified/ |
| GCP | BAA covered: Cloud Run, Cloud Run functions, GKE, Compute Engine, Cloud SQL, Firestore, BigQuery, Cloud Storage, Identity Platform, Memorystore, GDC connected; Firebase App Hosting absent | V | https://docs.cloud.google.com/docs/security/compliance/hipaa |
| GCP | ISO 27001/17/18, SOC 1/2/3, PCI DSS in scope for the same products (table of 16 Jul 2026); Firebase App Hosting absent | V | https://cloud.google.com/security/compliance/services-in-scope/index-20260716 |
| GCP | Cloud Data Processing Addendum: GDPR + SCCs for Google Cloud Platform services | V | https://cloud.google.com/terms/data-processing-addendum |
| Azure | PCI DSS v4.0 Service Provider L1, ISO 27001 certificate covers Azure; per-service list only in the STP Appendix A (not readable) -> HIPAA/PCI unknown per service | V / UNKNOWN | https://learn.microsoft.com/en-us/azure/compliance/offerings/offering-pci-dss |
| Azure Database for PostgreSQL | HIPAA, PCI DSS L1, SOC 2 Type 2, ISO 27001, EU Model Clauses (product page) | V | https://learn.microsoft.com/en-us/azure/postgresql/security/security-compliance |
| Vercel | BAA: Pro add-on, Enterprise on request; PCI SAQ-D AOC (service provider) | V | https://vercel.com/docs/security/compliance |
| Supabase | DPA (GDPR, SCCs) part of the Terms for every customer | V | https://supabase.com/legal/dpa |
| DigitalOcean | DPA (GDPR, SCCs), updated 14 Oct 2026 | V | https://www.digitalocean.com/legal/data-processing-agreement |
| Cloudflare | Customer DPA v6.4 (GDPR, SCCs) for enterprise and self-serve agreements | V | https://www.cloudflare.com/cloudflare-customer-dpa/ |
| Netlify | SOC 2 Type 2, ISO 27001; PCI only SAQ-A; BAA/DPA not stated | V / UNKNOWN | https://www.netlify.com/security/ |
| Auth0 | Okta trust centre badges not broken down per product | UNKNOWN | https://security.okta.com/ |
| Fly.io, Shopify | security/compliance pages 404 or silent | UNKNOWN | - |
"""

from .regions import UNKNOWN as _R_UNKNOWN  # noqa: F401  (re-exported marker for symmetry)

ACCESSED = "2026-11-13"
ATTEST_VALUES_FIXED = ("yes", "no", "self", "unknown", "na")

# What each regime requires. Keys equal schema.COMPLIANCE.
REGIMES = {
    "gdpr": {
        "requires": "DPA with every processor; EU region recommended (hard only if data_residency=eu); data-subject export/erasure.",
        "vendor_fact": "gdpr", "hard_region": False, "prefers_eu_region": True,
    },
    "dpdp": {
        "requires": "India DPDP Act 2023: consent records, breach notification, grievance contact; cross-border transfer allowed except to "
                    "notified countries. No vendor attestation exists, so this regime adds notes and an India-region preference, not a vendor filter.",
        "vendor_fact": None, "hard_region": False, "prefers_india_region": True,
    },
    "hipaa": {
        "requires": "Signed BAA with each vendor holding PHI, using only in-scope (HIPAA-eligible) services; free/hobby tiers generally have no BAA.",
        "vendor_fact": "hipaa", "hard_region": False,
    },
    "pci_dss": {
        "requires": "Card data path must run on an attested provider or a PCI Level 1 gateway with hosted checkout/tokenisation (SAQ A scope).",
        "vendor_fact": "pci_dss", "hard_region": False,
    },
    "rbi_localisation": {
        "requires": "Payment data stored only in India: India region for the payments path and system-of-record database; implies data_residency=india.",
        "vendor_fact": "rbi_localisation", "hard_region": True, "implies_residency": "india",
    },
    "soc2": {
        "requires": "Vendors holding a SOC 2 report (organisation-level control inheritance; certifies the organisation, not just tools).",
        "vendor_fact": "soc2", "hard_region": False,
    },
    "iso27001": {
        "requires": "Vendors holding ISO/IEC 27001 certification (organisation-level).",
        "vendor_fact": "iso27001", "hard_region": False,
    },
}


def _a(gdpr, hipaa, pci_dss, soc2, iso27001, src, note="", rbi="na", dpdp="na"):
    return {"gdpr": gdpr, "dpdp": dpdp, "hipaa": hipaa, "pci_dss": pci_dss, "rbi_localisation": rbi, "soc2": soc2,
            "iso27001": iso27001, "sources": list(src), "accessed": ACCESSED, "note": note}


_U = "unknown"

# Source keys per fact are in "sources" (vendor-level); FACT_SOURCES refines individual cells.
_AWS_SRC = ["aws_hipaa", "rf_aws_pci", "dbs_aws_soc_scope", "aws_iso_scope", "rf_aws_gdpr"]
_GCP_SRC = ["gcp_hipaa", "gcp_services_in_scope", "gcp_cdpa"]
_AZ_SRC = ["rf_azure_hipaa", "azure_pci_offering", "azure_iso_offering", "rf_azure_offerings", "azure_audit_scope"]
_AZ_SVC = ("HIPAA BAA and PCI DSS cover only in-scope services, and the per-service list (Azure Compliance Offerings, Appendix A) "
           "is a Service Trust Portal document that could not be read on 2026-11-13: hipaa and pci_dss are unknown (fail closed). "
           "SOC 2 and ISO 27001 are organisation-level attestations held by Azure; GDPR via the Microsoft DPA.")


def _aws(hipaa, pci, soc2, iso, note):
    return _a("yes", hipaa, pci, soc2, iso, _AWS_SRC, note)


def _gcp(hipaa, pci, soc2, iso, note, gdpr="yes"):
    return _a(gdpr, hipaa, pci, soc2, iso, _GCP_SRC, note)


def _az(note, hipaa=_U, pci=_U):
    return _a("yes", hipaa, pci, "yes", "yes", _AZ_SRC, note + " " + _AZ_SVC if hipaa == _U else note)


# Rule (2026-11-13 reconciliation): HIPAA and PCI DSS are per service wherever the vendor publishes a per-service
# list (AWS HIPAA-eligible / services-in-scope, Google BAA covered products / services in scope). SOC 2 and ISO 27001
# are organisation-level (REGIMES), but where the vendor's own per-service scope list omits a service it is "no"
# for that service (Lightsail, Firebase App Hosting). Vendor rows ("aws", "gcp", "azure") answer only the
# organisation-level question; records and offerings bind to a service row through kb.bindings.
ATTEST = {
    "aws": _a("yes", _U, _U, "yes", "yes", ["aws_hipaa", "rf_aws_pci", "rf_aws_programs", "rf_aws_gdpr"],
              "Vendor level only: HIPAA and PCI are per-service lists, use a service row (aws_*). Sign the BAA first."),
    "aws_lambda": _aws("yes", "yes", "yes", "yes", "Lambda and API Gateway are on all four lists."),
    "aws_ecs_fargate": _aws("yes", "yes", "yes", "yes", "ECS on all lists; Fargate HIPAA-eligible for the ECS/EKS engines; PCI lists ECS with the Fargate launch type."),
    "aws_eks": _aws("yes", "yes", "yes", "yes", "EKS on all lists (Fargate and EC2 launch types for PCI)."),
    "aws_ec2": _aws("yes", "yes", "yes", "yes", "EC2 on all lists."),
    "aws_lightsail": _aws("no", "no", "no", "no", "Amazon Lightsail is absent from the HIPAA-eligible, PCI, SOC and ISO service lists."),
    "aws_ec2_lightsail": _aws("no", "no", "no", "no", "Record covers EC2 and Lightsail: the weaker (Lightsail, on no list) is recorded; regulated workloads should use EC2, ECS or EKS."),
    "aws_amplify": _aws("yes", "yes", "yes", "yes", "HIPAA list names 'AWS Amplify Console' (the former name of Amplify Hosting); PCI, SOC and ISO lists name AWS Amplify."),
    "aws_app_runner": _aws("no", "yes", "yes", "yes", "App Runner is not HIPAA-eligible; it is on the PCI, SOC and ISO lists (and closed to new customers)."),
    "aws_outposts": _aws("yes", "yes", "yes", "yes", "AWS Outposts is on all four lists."),
    "aws_rds": _aws("yes", "yes", "yes", "yes", "RDS HIPAA-eligible for the PostgreSQL, MySQL, MariaDB, SQL Server, Oracle and Db2 engines; RDS on PCI, SOC and ISO lists."),
    "aurora_postgres": _aws("yes", _U, _U, _U, "Amazon Aurora is HIPAA-eligible; the PCI, SOC and ISO lists show no row named Aurora (only RDS), so those are unknown."),
    "aws_s3": _aws("yes", "yes", "yes", "yes", "Amazon S3 is on all four lists."),
    "aws_dynamodb": _aws("yes", "yes", "yes", "yes", "DynamoDB on all four lists."),
    "azure": _a("yes", _U, _U, "yes", "yes", _AZ_SRC, "Vendor level only. " + _AZ_SVC),
    "azure_postgres": _a("yes", "yes", "yes", "yes", "yes", ["dbs_azure_pg_compliance", "rf_azure_hipaa"],
                         "Product page lists HIPAA/HITECH, PCI DSS Level 1, SOC 2 Type 2, ISO 27001 and EU Model Clauses for flexible server."),
    "azure_sql": _az("Azure SQL Database."),
    "azure_cosmosdb": _az("Azure Cosmos DB (its compliance page defers to Appendix A)."),
    "azure_mysql": _az("Azure Database for MySQL flexible server (no product compliance page found: 404)."),
    "azure_app_service": _az("Azure App Service."),
    "azure_functions": _az("Azure Functions."),
    "azure_container_apps": _az("Azure Container Apps."),
    "azure_aks": _az("Azure Kubernetes Service."),
    "azure_vms": _az("Azure Virtual Machines."),
    "azure_static_web_apps": _az("Azure Static Web Apps."),
    "azure_managed_redis": _az("Azure Managed Redis."),
    "azure_local": _a("self", "self", "self", "self", "self", ["hst_azure_local"],
                      "Runs on the customer's own hardware and premises: the facility controls are the team's."),
    "gcp": _gcp(_U, _U, "yes", "yes", "Vendor level only: BAA and PCI are per covered product; use a service row (gcp_*)."),
    "gcp_cloud_run": _gcp("yes", "yes", "yes", "yes", "Cloud Run: BAA covered product; ISO, SOC and PCI in scope."),
    "gcp_cloud_run_functions": _gcp("yes", "yes", "yes", "yes", "Cloud Run functions (listed as Cloud Functions in the scope table)."),
    "gcp_gke": _gcp("yes", "yes", "yes", "yes", "Google Kubernetes Engine."),
    "gcp_gce": _gcp("yes", "yes", "yes", "yes", "Compute Engine."),
    "gcp_cloud_sql": _gcp("yes", "yes", "yes", "yes", "Cloud SQL."),
    "gcp_bigquery": _gcp("yes", "yes", "yes", "yes", "BigQuery."),
    "gcp_gcs": _gcp("yes", "yes", "yes", "yes", "Cloud Storage."),
    "gcp_memorystore": _gcp("yes", "yes", "yes", "yes", "Memorystore."),
    "firebase_app_hosting": _gcp("no", "no", "no", "no", "Firebase App Hosting is absent from the BAA covered-products list and from the services-in-scope table.", gdpr=_U),
    "google_distributed_cloud": _a("self", "yes", "self", "self", "self", ["gcp_hipaa", "hst_gdc"],
                                   "Runs on customer premises (controls are the team's); 'Google Distributed Cloud connected' is a BAA covered product."),
    "bedrock": _a("yes", "yes", "yes", _U, _U, ["aws_hipaa", "rf_aws_pci"], "PCI scope excludes Bedrock Marketplace."),
    "cognito": _aws("yes", "yes", "yes", "yes", "Amazon Cognito is on the HIPAA, PCI, SOC and ISO lists."),
    "supabase": _a("yes", "plan:hipaa_addon", _U, "yes", _U, ["supabase_soc2", "supabase_hipaa_projects", "supabase_dpa"],
                   "HIPAA = signed BAA + HIPAA add-on (plan not named). Mumbai + hipaa: region-specific eligibility not documented -> UNKNOWN. "
                   "The DPA (GDPR, SCCs) forms part of the Terms for every customer."),
    "vercel": _a("yes", "plan:pro_addon", "yes", "yes", "yes", ["rf_vercel_compliance"],
                 "BAA: Pro teams buy the HIPAA BAA add-on; Enterprise on request. PCI: SAQ-D AOC as service provider. Compute/CDN only."),
    "digitalocean": _a("yes", _U, _U, "yes", _U, ["rf_do_certs", "do_dpa"],
                       "ISO 27001 only for colocated facilities; PCI is SAQ-A for DO's own admin environment; HIPAA not stated. DPA (GDPR, SCCs) is an addendum to the Terms."),
    "render": _a("yes", "plan:scale", _U, "yes", "yes", ["rf_render_compliance", "rf_render_hipaa"],
                 "HIPAA-enabled workspace needs Scale or Enterprise and is not available in Singapore; DPA for all workspaces."),
    "railway": _a("yes", "plan:baa_addon", _U, "yes", _U, ["rf_railway_compliance"], "BAA is a paid add-on with a monthly spend threshold."),
    "fly": _a(_U, _U, _U, _U, _U, ["fly_mpg"], "Compliance and security pages returned 404 on 2026-11-13."),
    "tiger_cloud": _a("yes", "plan:enterprise", _U, "yes", _U, ["tiger_security", "tiger_trust"],
                      "SOC 2 Type 2 (report on Scale/Enterprise); HIPAA on the Enterprise plan; GDPR DPA for all customers; PCI DSS and ISO 27001 not stated."),
    "neon": _a(_U, "plan:scale", _U, "yes", "yes", ["rf_neon_security", "rf_neon_hipaa"], "HIPAA self-serve on Scale with BAA."),
    "netlify": _a(_U, _U, _U, "yes", "yes", ["netlify_security"],
                  "SOC 2 Type 2 (report for Enterprise) and ISO 27001 certificate; PCI only as SAQ-A (merchant scope); BAA and DPA not stated on the page."),
    "hetzner": _a(_U, _U, _U, _U, _U, ["hetzner_docs"], "Attestations not checked on an official page."),
    "cloudflare": _a("yes", _U, "yes", "yes", "yes", ["rf_cf_certs", "cf_dpa"],
                     "BAA terms not confirmed from a Cloudflare page; DLS is an Enterprise add-on. Customer DPA v6.4 covers enterprise and self-serve agreements."),
    "upstash": _a("yes", "plan:enterprise", "no", "yes", _U, ["rf_upstash_compliance"],
                  "SOC 2 report needs Prod Pack or Enterprise; no PCI claim (does not store card data)."),
    "mongodb_atlas": _a(_U, "yes", "yes", _U, "yes", ["atlas_compliance", "rf_atlas_hipaa"],
                        "BAA is in the Cloud Terms for self-service accounts; invoice/Order Form accounts must request it. Beta/preview excluded. The HIPAA page states product-level coverage and no tier restriction; whether free/shared (M0, Flex) clusters are in scope was not stated (checked 2026-11-13), so use a dedicated M10+ cluster for PHI."),
    "firebase_auth": _a(_U, _U, _U, "yes", "yes", ["firebase_privacy"], "US-only processing. BAA not stated for Firebase Auth; GCP Identity Platform is covered with restrictions."),
    "gcp_identity_platform": _gcp("yes", "yes", "yes", "yes", "Do not store PHI in optional/custom attributes."),
    "firestore": _gcp("yes", "yes", "yes", "yes", "Firestore: BAA covered product; ISO, SOC and PCI in scope."),
    "auth0": _a(_U, _U, _U, _U, _U, ["rf_auth0_cloud", "okta_trust"],
                "Okta's trust centre lists SOC 2, ISO 27001, PCI DSS, HIPAA and GDPR badges for Okta and Auth0 together without a per-product breakdown or plan: unknown."),
    "clerk": _a(_U, "plan:enterprise", "no", "yes", _U, ["rf_clerk_security"], "No cardholder data; US hosting only."),
    "sentry": _a(_U, "plan:business", _U, "yes", "yes", ["rf_sentry_privacy"], "SOC 2 / ISO per Sentry trust centre (search summary); BAA Business tier or higher."),
    "stripe": _a("yes", _U, "yes", "yes", _U, ["rf_stripe_security", "stripe_india"], "Invite-only for new Indian businesses.", rbi=_U),
    "razorpay": _a(_U, "na", "yes", "yes", "yes", ["rf_razorpay_pg", "sv_razorpay_security"],
                   "RBI PA authorisation and data localisation are the vendor's own docs claim. Security page (2026-11-13) lists PCI DSS Level 1, "
                   "ISO 27001:2022 and SOC 2 Type 2 (copies on request; vendor-listed).", rbi="yes"),
    "cashfree": _a(_U, "na", "yes", "yes", "yes", ["rf_cashfree_security"],
                   "Security page (2026-11-13) lists PCI DSS v4.0.1 Level 1, ISO 27001:2022 and SOC 2 Type 2. RBI localisation not stated there "
                   "(merchant terms word hosting-in-India passively, without naming who is bound): unknown.", rbi=_U),
    "payu": _a(_U, "na", _U, _U, _U, ["sv_payu_pg_page"],
               "PayU's own marketing pages claim PCI DSS and RBI data-localisation compliance, but no attestation of compliance or "
               "hosting evidence is published and its security page could not be read on 2026-11-13: left unknown (fail closed).", rbi=_U),
    "entra_id": _a(_U, "yes", _U, _U, _U, ["rf_azure_hipaa", "sv_entra_data_residency"],
                   "Entra ID is on the Microsoft BAA in-scope list (Office 365 commercial table). Other attestations were not read from "
                   "an Entra-specific page on 2026-11-13: unknown (fail closed)."),
    "msg91": _a(_U, "na", "na", _U, _U, ["sv_msg91_gdpr"],
                "MSG91's GDPR page is a policy statement: it names no data location, certification or DPA terms, and its security page "
                "could not be read on 2026-11-13: left unknown (fail closed).", rbi=_U),
    "github_actions": _a(_U, "na", "na", _U, _U, [], "Source code, not user data."),
    "shopify": _a(_U, _U, _U, _U, _U, ["hst_shopify_data"], "Shopify's PCI/SOC/data-processing pages were not confirmed on 2026-11-13 (404 or silent): unknown."),
    "appwrite": _a(_U, _U, _U, "yes", _U, ["appwrite_compliance"], "SOC 2 Type II; no ISO 27001, PCI, BAA or DPA statement on the compliance page."),
    "self_hosted": _a("self", "self", "self", "self", "self", [], "Self-hosted: the team carries the control.", rbi="self", dpdp="na"),
}

# Cell-level overrides where a single cell has a different source than the vendor-level list.
FACT_SOURCES = {
    ("gcp", "iso27001"): ["rf_gcp_iso", "gcp_services_in_scope"],
    ("gcp", "soc2"): ["gcp_services_in_scope"],
    ("gcp", "gdpr"): ["gcp_cdpa"],
}

ALIASES = {"do": "digitalocean", "atlas": "mongodb_atlas", "mongodb": "mongodb_atlas", "firebase": "firebase_auth",
           "entra": "entra_id", "azure_ad": "entra_id", "identity_platform": "gcp_identity_platform",
           "rds": "aws_rds", "aurora": "aurora_postgres", "cloud_run": "gcp_cloud_run", "cloud_sql": "gcp_cloud_sql", "gcs": "gcp_gcs",
           "s3": "aws_s3", "cosmosdb": "azure_cosmosdb", "lightsail": "aws_lightsail", "fly_machines": "fly"}


def attestation(vendor, regime):
    """Attestation value for ``vendor`` x ``regime``; ``'unknown'`` for any vendor/regime not on file (fail closed)."""
    row = ATTEST.get(ALIASES.get(vendor, vendor))
    if row is None or regime not in REGIMES:
        return "unknown"
    return row[regime]


def attestation_sources(vendor, regime):
    key = ALIASES.get(vendor, vendor)
    if (key, regime) in FACT_SOURCES:
        return list(FACT_SOURCES[(key, regime)])
    row = ATTEST.get(key)
    return list(row["sources"]) if row else []


def passes(vendor, regime):
    """True when the attestation satisfies the regime (yes / plan:* / self). ``na`` passes only where the regime
    puts no obligation on that vendor type (dpdp always; rbi for non-payment vendors is decided by region)."""
    v = attestation(vendor, regime)
    return v in ("yes", "self", "na") or v.startswith("plan:")


# Combinations whose joint eligibility is not documented (each cell alone may be known). Fail closed.
COMBINED_UNKNOWN = {
    ("supabase", "hipaa", "india"): "Supabase documents the HIPAA add-on but not whether the Mumbai region is eligible.",
}


def attestation_in_region(vendor, regime, residency):
    """Like ``attestation`` but returns ``'unknown'`` for documented-gap combinations (e.g. Supabase HIPAA in India)."""
    key = ALIASES.get(vendor, vendor)
    if (key, regime, residency) in COMBINED_UNKNOWN:
        return "unknown"
    return attestation(vendor, regime)


# ---- Supporting-service additions (T3-KB, 2026-11-13).  New vendor rows only.
_AWS_SVC_NOTE = "On the AWS HIPAA-eligible, PCI DSS, SOC and ISO 27001 service lists read on 2026-11-13."
for _k, _n in [("aws_elasticache", "Amazon ElastiCache"), ("aws_sqs", "Amazon SQS"), ("aws_msk", "Amazon MSK"),
               ("aws_opensearch", "Amazon OpenSearch Service"), ("aws_cloudfront", "Amazon CloudFront (not the Embedded PoPs)"),
               ("aws_sagemaker", "Amazon SageMaker AI"), ("aws_iot_core", "AWS IoT Core"), ("aws_appsync", "AWS AppSync"),
               ("aws_codebuild", "AWS CodeBuild and CodePipeline"), ("aws_cloudwatch", "Amazon CloudWatch, CloudWatch Logs and X-Ray"),
               ("aws_api_gateway", "Amazon API Gateway"), ("aws_kms", "AWS KMS and Secrets Manager"), ("aws_waf", "AWS WAF"),
               ("aws_ses", "Amazon SES")]:
    ATTEST[_k] = _aws("yes", "yes", "yes", "yes", _n + ". " + _AWS_SVC_NOTE)
_GCP_SVC_NOTE = "BAA covered product and in the services-in-scope table (16 Jul 2026), read on 2026-11-13."
for _k, _n in [("gcp_pubsub", "Pub/Sub and Cloud Tasks"), ("gcp_cloud_cdn", "Cloud CDN"), ("gcp_cloud_build", "Cloud Build"),
               ("gcp_ops", "Cloud Logging, Cloud Monitoring and Cloud Trace"),
               ("gcp_vertex_ai", "Vertex AI (BAA list names Generative AI on Agent Platform and AI Platform Training and Prediction; "
                                 "the vendor renamed the Vertex AI line)")]:
    ATTEST[_k] = _gcp("yes", "yes", "yes", "yes", _n + ". " + _GCP_SVC_NOTE)
for _k, _n in [("azure_service_bus", "Azure Service Bus"), ("azure_blob", "Azure Blob Storage"), ("azure_front_door", "Azure Front Door"),
               ("azure_ai_search", "Azure AI Search"), ("azure_signalr", "Azure SignalR Service"),
               ("azure_machine_learning", "Azure Machine Learning"), ("azure_ai_foundry", "Microsoft Foundry models"),
               ("azure_iot_hub", "Azure IoT Hub"), ("azure_app_insights", "Azure Monitor Application Insights"),
               ("azure_devops", "Azure DevOps (Azure Pipelines)"), ("azure_api_management", "Azure API Management"),
               ("azure_key_vault", "Azure Key Vault")]:
    ATTEST[_k] = _az(_n + ".")
ATTEST["entra_external_id"] = _a(_U, _U, _U, _U, _U, ["sv_entra_ext_overview"],
                                 "Attestation scope of Entra External ID (customer tenants) was not confirmed on an official page: fails closed.")
_SV_UNVERIFIED_ATTEST = {
    "ably": "sv_ably_docs", "pusher": "sv_pusher_docs", "paddle": "sv_paddle_site", "paypal_braintree": "sv_braintree_docs",
    "revenuecat": "sv_revenuecat_docs", "anthropic": "sv_anthropic_privacy", "algolia": "sv_algolia_pricing",
    "elastic_cloud": "sv_elastic_cloud_docs", "backblaze": "sv_b2_docs", "grafana_cloud": "sv_grafana_cloud_docs",
    "datadog": "sv_datadog_docs", "postmark": "sv_postmark_docs", "resend": "sv_resend_docs", "fcm": "firebase_privacy",
    "apns": "apple_apns", "twilio": "sv_twilio_verify_docs", "sanity": "sv_sanity_docs", "powersync": "sv_powersync_pricing",
    "mux": "sv_mux_docs",
}
for _k, _s in sorted(_SV_UNVERIFIED_ATTEST.items()):
    ATTEST[_k] = _a(_U, _U, _U, _U, _U, [_s], "Attestations for this vendor were not confirmed on an official page on 2026-11-13: fails closed.")
ATTEST["workos"] = _a(_U, "plan:enterprise", _U, "yes", _U, ["sv_workos_security"],
                      "WorkOS security page: SOC 2 Type 2 certified, GDPR compliant, HIPAA BAA available on enterprise plans.", rbi="na")
ATTEST["workos"]["gdpr"] = "yes"
ATTEST["adyen"] = _a(_U, _U, "yes", _U, _U, ["sv_adyen_pci"],
                     "Adyen documents that it is a PCI DSS Level 1 Service Provider assessed by a QSA; other attestations not confirmed.", rbi=_U)
ATTEST["gitlab_saas"] = _a(_U, _U, _U, "yes", "yes", ["sv_gitlab_security"],
                           "GitLab trust page: SOC 2 Type 2 and ISO/IEC 27001:2022 for GitLab.com and GitLab Dedicated.")

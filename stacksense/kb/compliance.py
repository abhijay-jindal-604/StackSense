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
ATTEST = {
    "aws": _a("yes", "yes", "yes", "yes", "yes", ["rf_aws_hipaa", "rf_aws_pci", "rf_aws_programs", "rf_aws_gdpr"],
              "HIPAA/PCI are per-service lists; RDS HIPAA only for listed engines; Fargate only ECS/EKS engines; sign the BAA first."),
    "azure": _a("yes", "yes", "yes", "yes", "yes", ["rf_azure_hipaa", "rf_azure_offerings"],
                "BAA is part of the Online Services DPA for in-scope services; GDPR via DPA (same document)."),
    "gcp": _a(_U, "yes", "yes", _U, "yes", ["rf_gcp_hipaa", "rf_gcp_iso", "rf_gcp_filestore_compliance"],
              "BAA covers listed products only. PCI shown from the Filestore page (product-level); SOC 2 not confirmed today."),
    "bedrock": _a(_U, "yes", "yes", _U, _U, ["rf_aws_hipaa", "rf_aws_pci"], "PCI scope excludes Bedrock Marketplace."),
    "cognito": _a(_U, "yes", "yes", _U, _U, ["rf_aws_hipaa", "rf_aws_pci"], "SOC/ISO service scope not checked."),
    "supabase": _a(_U, "plan:hipaa_addon", _U, "yes", _U, ["rf_supabase_soc2", "rf_supabase_hipaa_projects"],
                   "HIPAA = signed BAA + HIPAA add-on (plan not named). Mumbai + hipaa: region-specific eligibility not documented -> treat as UNKNOWN."),
    "vercel": _a("yes", "plan:pro_addon", "yes", "yes", "yes", ["rf_vercel_compliance"],
                 "BAA: Pro via HIPAA BAA add-on; Enterprise on request. Compute/CDN only."),
    "digitalocean": _a(_U, _U, _U, "yes", _U, ["rf_do_certs"],
                       "ISO 27001 only for colocated facilities; PCI is SAQ-A for DO's own admin environment; HIPAA/GDPR not stated."),
    "render": _a("yes", "plan:scale", _U, "yes", "yes", ["rf_render_compliance", "rf_render_hipaa"],
                 "HIPAA-enabled workspace needs Scale or Enterprise and is not available in Singapore; DPA for all workspaces."),
    "railway": _a("yes", "plan:baa_addon", _U, "yes", _U, ["rf_railway_compliance"], "BAA is a paid add-on with a monthly spend threshold."),
    "fly": _a(_U, _U, _U, _U, _U, [], "Compliance page returned 404 today."),
    "neon": _a(_U, "plan:scale", _U, "yes", "yes", ["rf_neon_security", "rf_neon_hipaa"], "HIPAA self-serve on Scale with BAA."),
    "cloudflare": _a(_U, _U, "yes", "yes", "yes", ["rf_cf_certs"], "BAA terms not confirmed from a Cloudflare page; DLS is an Enterprise add-on."),
    "upstash": _a("yes", "plan:enterprise", "no", "yes", _U, ["rf_upstash_compliance"],
                  "SOC 2 report needs Prod Pack or Enterprise; no PCI claim (does not store card data)."),
    "mongodb_atlas": _a(_U, "yes", "yes", _U, "yes", ["rf_atlas_trust", "rf_atlas_hipaa"],
                        "BAA is in the Cloud Terms for self-service accounts; invoice/Order Form accounts must request it. Beta/preview excluded."),
    "firebase_auth": _a(_U, _U, _U, "yes", "yes", ["rf_firebase_privacy"], "US-only processing. BAA not stated for Firebase Auth; GCP Identity Platform is covered with restrictions."),
    "gcp_identity_platform": _a(_U, "yes", _U, _U, "yes", ["rf_gcp_hipaa", "rf_gcp_iso"], "Do not store PHI in optional/custom attributes."),
    "firestore": _a(_U, "yes", _U, "yes", "yes", ["rf_gcp_hipaa", "rf_firebase_privacy"], "Covered by the GCP BAA."),
    "auth0": _a(_U, _U, _U, _U, _U, ["rf_auth0_cloud"], "BAA plan details were only on secondary sources: unknown. PCI only as private-cloud add-on."),
    "clerk": _a(_U, "plan:enterprise", "no", "yes", _U, ["rf_clerk_security"], "No cardholder data; US hosting only."),
    "sentry": _a(_U, "plan:business", _U, "yes", "yes", ["rf_sentry_privacy"], "SOC 2 / ISO per Sentry trust centre (search summary); BAA Business tier or higher."),
    "stripe": _a("yes", _U, "yes", "yes", _U, ["rf_stripe_security", "rf_stripe_india"], "Invite-only for new Indian businesses.", rbi=_U),
    "razorpay": _a(_U, "na", "yes", _U, _U, ["rf_razorpay_pg"], "RBI PA authorisation and data localisation are the vendor's own docs claim.", rbi="yes"),
    "cashfree": _a(_U, "na", "yes", _U, _U, ["rf_cashfree_security"], "RBI localisation unverified.", rbi=_U),
    "payu": _a(_U, "na", _U, _U, _U, [], "Not checked today.", rbi=_U),
    "entra_id": _a(_U, "yes", _U, _U, _U, ["rf_azure_hipaa"], "Entra ID is on the Microsoft BAA in-scope list (Office 365 commercial table)."),
    "msg91": _a(_U, "na", "na", _U, _U, [], "Not checked today.", rbi=_U),
    "github_actions": _a(_U, "na", "na", _U, _U, [], "Source code, not user data."),
    "self_hosted": _a("self", "self", "self", "self", "self", [], "Self-hosted: the team carries the control.", rbi="self", dpdp="na"),
}

# Cell-level overrides where a single cell has a different source than the vendor-level list.
FACT_SOURCES = {
    ("gcp", "pci_dss"): ["rf_gcp_filestore_compliance"],
    ("gcp", "iso27001"): ["rf_gcp_iso"],
    ("gcp", "hipaa"): ["rf_gcp_hipaa"],
}

ALIASES = {"do": "digitalocean", "atlas": "mongodb_atlas", "mongodb": "mongodb_atlas", "firebase": "firebase_auth",
           "entra": "entra_id", "azure_ad": "entra_id", "identity_platform": "gcp_identity_platform"}


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

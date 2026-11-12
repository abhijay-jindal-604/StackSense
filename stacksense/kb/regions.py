"""Region ids per provider/product and data-residency value (hard filter F4 input).

Every entry was checked against an official vendor page on 2026-11-13 (see ``sources_facts.py``).
Anything not confirmed from such a page is the marker ``UNKNOWN`` and fails closed in filters.

Shape::

    ENTRIES[key] = {
        "residency": {"none": [...], "india": [...], "eu": [...], "us": [...], "other": [...]},
        "sources": [source keys],      # resolvable in kb.sources.SOURCES
        "conf": "V" | "unknown",       # V = verified 2026-11-13; unknown = at least one value is UNKNOWN
        "accessed": "2026-11-13",
        "note": str,
    }

Residency values use the exact enum of ``schema.RESIDENCY``: none, india, eu, us, other.
  * ``none``  -> ``["*"]`` (no constraint: any region).
  * ``other`` -> ``UNKNOWN`` (no country is named, so no managed region can be verified; only
    self-hosted components pass, see warning RESIDENCY_UNVERIFIABLE).
  * a list is the verified region ids; ``[]`` means the vendor verifiably has none there.
"EU" means EU member states only: London (UK), Zurich (CH) and Norway are listed under none of ``eu``.
"""

UNKNOWN = "UNKNOWN"
ANY = ["*"]
ACCESSED = "2026-11-13"
RESIDENCY_VALUES = ("none", "india", "eu", "us", "other")


def _e(india, eu, us, sources, note="", other=UNKNOWN, none=None, conf=None):  # conf kept for call-site compatibility
    res = {"none": ANY if none is None else none, "india": india, "eu": eu, "us": us, "other": other}
    return {"residency": res, "sources": list(sources), "conf": "V", "accessed": ACCESSED, "note": note}


_AWS_EU = ["eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2"]
_AWS_US = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]

ENTRIES = {
    "aws": _e(["ap-south-1", "ap-south-2"], _AWS_EU, _AWS_US, ["rf_aws_regions"],
              "ap-south-2 Hyderabad and eu-south-1/-2 are opt-in regions. eu-west-2 London and eu-central-2 Zurich are not EU. "
              "Service availability varies per region."),
    "azure": _e(["centralindia", "southindia", "westindia", "indiasouthcentral"],
                ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral", "italynorth",
                 "polandcentral", "spaincentral", "austriaeast", "belgiumcentral", "denmarkeast"],
                ["eastus", "eastus2", "centralus", "northcentralus", "southcentralus", "westcentralus", "westus", "westus2", "westus3"],
                ["rf_azure_regions"],
                "Restricted DR regions (germanynorth, francesouth, ...) excluded; norwayeast, switzerlandnorth, uk* are not EU. "
                "Per-service availability varies."),
    "gcp": _e(["asia-south1", "asia-south2"],
              ["europe-west1", "europe-west3", "europe-west4", "europe-north1", "europe-north2", "europe-west8", "europe-west9",
               "europe-west10", "europe-west12", "europe-southwest1", "europe-central2"],
              ["us-central1", "us-east4"], ["rf_gcp_regions", "rf_firestore_locations"],
              "Only regions seen on the official pages are listed (US list is partial, conservative). europe-west2 London and europe-west6 Zurich are not EU."),
    "supabase": _e(["ap-south-1"], ["eu-west-1", "eu-central-1", "eu-west-3", "eu-north-1"], _AWS_US, ["rf_supabase_regions"],
                   "Choose a specific region at project creation: the 'Central EU' / 'West EU' general regions do not guarantee a country. "
                   "London (eu-west-2) and Zurich (eu-central-2) are not EU. Mumbai is the only India region."),
    "vercel": _e(["bom1"], ["arn1", "cdg1", "dub1", "fra1"], ["iad1", "cle1", "pdx1", "sfo1"], ["rf_vercel_regions"],
                 "Compute/CDN only: functions default to iad1 and must be pinned. Vercel's DPA allows processing anywhere Vercel or "
                 "sub-processors operate, so data at rest belongs in an in-region database."),
    "digitalocean": _e(["BLR1"], ["AMS3", "FRA1"], ["NYC1", "NYC2", "NYC3", "SFO2", "SFO3", "ATL1", "RIC1", "MKC1", "MEM1"], ["rf_do_regional"],
                       "BLR1 has Droplets, App Platform (dynamic apps; static sites are Cloudflare CDN only), Managed PostgreSQL/MySQL/MongoDB/"
                       "Valkey/Kafka/OpenSearch, Spaces Standard (no Cold Storage), DOKS. LON1 is UK, not EU."),
    "render": _e([], ["frankfurt"], ["oregon", "ohio", "virginia"], ["rf_render_regions"],
                 "No India region (Oregon, Ohio, Virginia, Frankfurt, Singapore only)."),
    "railway": _e([], ["europe-west4-drams3a"], ["us-west2", "us-east4-eqdc4a"], ["rf_railway_regions"],
                  "No India region (US West, US East, EU West Amsterdam, Southeast Asia Singapore)."),
    "fly": _e(["bom"], ["ams", "arn", "cdg", "fra"], ["dfw", "ewr", "iad", "lax", "ord", "sjc"], ["rf_fly_regions"],
              "Machines/volumes only. bom is not on the Managed Postgres list (see fly_managed_postgres). lhr is UK, not EU. "
              "Mumbai was seen on the regions reference in search results but the fetched extract covered Europe/US only; third-party "
              "status pages report capacity incidents (VENDOR_RISK info)."),
    "fly_managed_postgres": _e([], ["ams", "fra"], ["dfw", "iad", "lax", "ord", "sjc"], ["rf_fly_regions", "rf_fly_mpg"],
                               "MPG regions per the regions reference: ams, dfw, fra, iad, lax, lhr(UK), ord, sjc. No Mumbai."),
    "neon": _e([], ["aws-eu-central-1"], ["aws-us-east-1", "aws-us-east-2", "aws-us-west-2"], ["rf_neon_regions"],
               "No India region. aws-eu-west-2 London is UK, not EU. Azure regions are deprecated for new projects."),
    "cloudflare": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["rf_cf_dls"],
                     "Global network. Confining processing to a country/region needs the Data Localization Suite (Enterprise-only add-on); "
                     "the DLS overview names no India option, so India confinement is UNKNOWN. Static public assets via CDN are not personal "
                     "data (rule in filters, not a vendor fact)."),
    "cloudflare_r2": _e([], ["jurisdiction:eu"], ["jurisdiction:us"], ["rf_cf_r2_location"],
                        "Jurisdictions: eu, fedramp, us. Location hints (apac etc.) are best effort. No India jurisdiction or hint."),
    "cloudflare_d1": _e([], ["jurisdiction:eu"], ["jurisdiction:us"], ["rf_cf_d1_location"],
                        "Jurisdictions: eu, fedramp, us, set at creation only. Hints are best effort; Workers may still reach the DB from anywhere."),
    "upstash": _e(["aws:ap-south-1"], ["aws:eu-west-1", "aws:eu-central-1"], ["aws:us-east-1", "aws:us-east-2", "aws:us-west-1", "aws:us-west-2"],
                  ["rf_upstash_global"], "AWS regions listed; eu-west-2 London is UK. GCP regions exist (europe-west1, us-central1) but are not listed here."),
    "mongodb_atlas": _e(["aws:AP_SOUTH_1", "aws:AP_SOUTH_2"], ["aws:EU_CENTRAL_1"], ["aws:US_EAST_1"], ["rf_atlas_aws_regions"],
                        "Only AWS regions verified today (Azure/GCP Mumbai not checked); the list is a verified subset, not complete."),
    "firebase_auth": _e([], [], ["us"], ["rf_firebase_privacy"],
                        "Firebase Authentication 'is run only from US data centers' and has no location setting: excluded under india and eu."),
    "firestore": _e(["asia-south1", "asia-south2"],
                    ["eur3", "europe-west1", "europe-west3", "europe-west4", "europe-west8", "europe-west9", "europe-west10", "europe-west12",
                     "europe-southwest1", "europe-north1", "europe-north2", "europe-central2"],
                    ["nam5", "us-central1"], ["rf_firestore_locations"],
                    "Location is fixed at creation. europe-west2 London and europe-west6 Zurich are not EU. US list partial."),
    "cognito": _e(["ap-south-1", "ap-south-2"], _AWS_EU, _AWS_US, ["rf_aws_cognito_endpoints"], "User-pool endpoints exist in these regions."),
    "bedrock": _e(["in.*"], ["eu.*"], ["us.*"], ["rf_bedrock_profiles", "rf_bedrock_india_blog"],
                  "Values are inference-profile prefixes. India: use the geographic profile with the in. prefix (routes only between ap-south-1 "
                  "and ap-south-2). global.* profiles route to any commercial region and are NOT valid for any residency except none. "
                  "AWS advises verifying destination regions with GetInferenceProfile; the prefix alone is not proof."),
    "azure_managed_redis": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["rf_azure_redis_overview"],
                              "Availability is published in a separate products-by-region table that could not be read; Central India etc. unconfirmed. "
                              "Fall back to Valkey on Azure Container Apps/VM (CLOUD_REGION_GAP)."),
    "auth0": _e([], ["EU"], ["US"], ["rf_auth0_cloud"],
                "Public cloud areas: US, UK, EU, AU, JP, CA. Private cloud (Enterprise) advertises 60+ regions; India there is UNKNOWN and not used."),
    "clerk": _e([], [], ["US"], ["rf_clerk_security"], "No region selection; hosted in the US (EU/UK/CH data moves under the EU-US DPF)."),
    "sentry": _e([], ["de"], ["us"], ["rf_sentry_locations"], "SaaS storage: US (Iowa) or EU (Frankfurt) only."),
    "razorpay": _e(["india"], UNKNOWN, UNKNOWN, ["rf_razorpay_pg"],
                   "Own docs list 'data localisation' for the RBI payments path; EU/US residency not applicable/unverified."),
    "cashfree": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["rf_cashfree_security"], "Data localisation claim only from a compliance-vendor case study: unverified."),
    "stripe": _e([], UNKNOWN, UNKNOWN, ["rf_stripe_india"],
                 "Invite-only for new Indian businesses; never recommended when india payments are in play (a business rule, shown as an "
                 "alternative with this reason). Data-location pages not checked."),
    "self_hosted": _e(ANY, ANY, ANY, [], "Self-hosted/on-prem components run wherever the team deploys them.", other=ANY, conf="V"),
    "github_actions": _e(UNKNOWN, UNKNOWN, UNKNOWN, [], "Handles source code, not user data: policy allows it with an info note (filters, not a vendor fact)."),
    "msg91": _e(UNKNOWN, UNKNOWN, UNKNOWN, [], "Not checked today."),
    "entra_id": _e(UNKNOWN, UNKNOWN, UNKNOWN, [], "Tenant data location not checked today."),
}

# conf reflects india/eu/us only ("other" is UNKNOWN for every managed vendor by design)
for _k, _v in ENTRIES.items():
    _r = _v["residency"]
    _v["conf"] = "unknown" if any(_r[x] == UNKNOWN for x in ("india", "eu", "us")) else "V"

# Provider aliases: product keys resolve to their vendor entry when the product has none of its own.
ALIASES = {"firebase": "firebase_auth", "gcs": "gcp", "s3": "aws", "rds": "aws", "ecs": "aws", "cloudwatch": "aws",
           "mongodb": "mongodb_atlas", "atlas": "mongodb_atlas", "fly_machines": "fly", "r2": "cloudflare_r2", "d1": "cloudflare_d1",
           "cloudflare_workers": "cloudflare", "cloudflare_cdn": "cloudflare", "do": "digitalocean"}

# Explicit product-level exceptions (kept visible for the filters and the report)
PRODUCT_EXCEPTIONS = {
    "fly_managed_postgres": "Not offered in bom: stateful Postgres on Fly is not available under india.",
    "bedrock": "Use the in. geographic inference profile under india; global.* profiles are excluded.",
    "cloudflare_r2": "No India jurisdiction; eu/us jurisdictions exist.",
    "cloudflare_d1": "No India jurisdiction; eu/us jurisdictions exist.",
    "cloudflare": "Country-level processing confinement needs DLS (Enterprise add-on); India unverified.",
    "firebase_auth": "US-only processing, no location choice.",
    "azure_managed_redis": "Regional availability unconfirmed: fail closed.",
}


def regions_for(provider, residency):
    """Region ids satisfying ``residency`` for ``provider``: a list (possibly ``[]``) or ``UNKNOWN``.

    Unknown providers and unknown residency values return ``UNKNOWN`` (fail closed).
    ``residency == "none"`` returns ``["*"]`` for any known provider.
    """
    key = ALIASES.get(provider, provider)
    entry = ENTRIES.get(key)
    if entry is None or residency not in RESIDENCY_VALUES:
        return UNKNOWN
    return list(entry["residency"][residency]) if entry["residency"][residency] != UNKNOWN else UNKNOWN


def region_ok(provider, residency):
    """True only when a verified non-empty region list exists (the F4 test); UNKNOWN and [] both fail."""
    r = regions_for(provider, residency)
    return r != UNKNOWN and len(r) > 0


def source_keys(provider):
    entry = ENTRIES.get(ALIASES.get(provider, provider))
    return list(entry["sources"]) if entry else []

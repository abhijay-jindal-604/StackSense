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
Per-service entries (azure_foundational / azure_mainstream / azure_mysql / aurora_postgres / firebase_app_hosting /
netlify / hetzner / appwrite ...) are bound to records and offerings by ``kb.bindings``. Values are region ids only;
Bedrock inference-profile prefixes live in ``INFERENCE_PROFILES``.
"EU" means EU member states only: London (UK), Zurich (CH) and Norway are listed under none of ``eu``.
"""

UNKNOWN = "UNKNOWN"
ANY = ["*"]
ACCESSED = "2026-11-13"
RESIDENCY_VALUES = ("none", "india", "eu", "us", "other")


def _e(india, eu, us, sources, note="", other=UNKNOWN, none=None, conf=None):  # conf kept for call-site compatibility
    res = {"none": ANY if none is None else none, "india": india, "eu": eu, "us": us, "other": other}
    # conf reflects india/eu/us only ("other" is UNKNOWN for every managed vendor by design)
    conf = "unknown" if any(res[x] == UNKNOWN for x in ("india", "eu", "us")) else "V"
    return {"residency": res, "sources": list(sources), "conf": conf, "accessed": ACCESSED, "note": note}


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
    "supabase": _e(["ap-south-1"], ["eu-west-1", "eu-central-1", "eu-west-3", "eu-north-1"], _AWS_US, ["supabase_regions"],
                   "Choose a specific region at project creation: the 'Central EU' / 'West EU' general regions do not guarantee a country. "
                   "London (eu-west-2) and Zurich (eu-central-2) are not EU. Mumbai is the only India region."),
    "vercel": _e(["bom1"], ["arn1", "cdg1", "dub1", "fra1"], ["iad1", "cle1", "pdx1", "sfo1"], ["vercel_regions"],
                 "Compute/CDN only: functions default to iad1 and must be pinned. Vercel's DPA allows processing anywhere Vercel or "
                 "sub-processors operate, so data at rest belongs in an in-region database."),
    "digitalocean": _e(["BLR1"], ["AMS3", "FRA1"], ["NYC1", "NYC2", "NYC3", "SFO2", "SFO3", "ATL1", "RIC1", "MKC1", "MEM1"], ["do_regions"],
                       "BLR1 has Droplets, App Platform (dynamic apps; static sites are Cloudflare CDN only), Managed PostgreSQL/MySQL/MongoDB/"
                       "Valkey/Kafka/OpenSearch, Spaces Standard (no Cold Storage), DOKS. LON1 is UK, not EU."),
    "render": _e([], ["frankfurt"], ["oregon", "ohio", "virginia"], ["render_regions"],
                 "No India region (Oregon, Ohio, Virginia, Frankfurt, Singapore only)."),
    "railway": _e([], ["europe-west4-drams3a"], ["us-west2", "us-east4-eqdc4a"], ["railway_regions"],
                  "No India region (US West, US East, EU West Amsterdam, Southeast Asia Singapore)."),
    "fly": _e([], ["ams", "arn", "cdg", "fra"], ["dfw", "ewr", "iad", "lax", "ord", "sjc"], ["fly_regions"],
              "The official regions reference (read in full 2026-11-13) lists ams, arn, cdg, dfw, ewr, fra, gru, iad, jnb, lax, lhr, "
              "nrt, ord, sin, sjc, syd, yyz: there is no bom (Mumbai) and no other India region. lhr is UK, not EU."),
    "fly_managed_postgres": _e([], ["ams", "fra"], ["dfw", "iad", "lax", "ord", "sjc"], ["fly_regions", "fly_mpg"],
                               "MPG regions per the regions reference: ams, dfw, fra, gru, iad, lax, lhr (UK), nrt, ord, sin, sjc, syd, yyz. No India."),
    "neon": _e([], ["aws-eu-central-1"], ["aws-us-east-1", "aws-us-east-2", "aws-us-west-2"], ["neon_regions"],
               "No India region. aws-eu-west-2 London is UK, not EU. Azure regions are deprecated for new projects."),
    "cloudflare": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["cf_dls"],
                     "Global network. Confining processing to a country/region needs the Data Localization Suite (Enterprise-only add-on); "
                     "the DLS overview names no India option, so India confinement is UNKNOWN. Static public assets via CDN are not personal "
                     "data (rule in filters, not a vendor fact)."),
    "cloudflare_r2": _e([], ["jurisdiction:eu"], ["jurisdiction:us"], ["r2_data_location"],
                        "Jurisdictions: eu, fedramp, us. Location hints (apac etc.) are best effort. No India jurisdiction or hint."),
    "cloudflare_d1": _e([], ["jurisdiction:eu"], ["jurisdiction:us"], ["rf_cf_d1_location"],
                        "Jurisdictions: eu, fedramp, us, set at creation only. Hints are best effort; Workers may still reach the DB from anywhere."),
    "upstash": _e(["aws:ap-south-1"], ["aws:eu-west-1", "aws:eu-central-1"], ["aws:us-east-1", "aws:us-east-2", "aws:us-west-1", "aws:us-west-2"],
                  ["rf_upstash_global"], "AWS regions listed; eu-west-2 London is UK. GCP regions exist (europe-west1, us-central1) but are not listed here."),
    "mongodb_atlas": _e(["aws:AP_SOUTH_1", "aws:AP_SOUTH_2", "azure:INDIA_CENTRAL", "azure:INDIA_SOUTH", "gcp:ASIA_SOUTH_1", "gcp:ASIA_SOUTH_2"],
                        ["aws:EU_CENTRAL_1", "azure:EUROPE_WEST", "azure:GERMANY_WEST_CENTRAL", "gcp:WESTERN_EUROPE", "gcp:EUROPE_WEST_3", "gcp:EUROPE_WEST_4"],
                        ["aws:US_EAST_1", "azure:US_EAST", "gcp:EASTERN_US"],
                        ["atlas_regions", "atlas_azure_regions", "atlas_gcp_regions"],
                        "Atlas region names per cloud. India: AWS Mumbai/Hyderabad, Azure Central India (Pune)/South India (Chennai), GCP Mumbai/Delhi. "
                        "Per-tier support marks (Free/Flex/M10+) were not readable: verify the tier offers the region. Lists are verified subsets."),
    "firebase_auth": _e([], [], ["us"], ["firebase_privacy"],
                        "Firebase Authentication 'is run only from US data centers' and has no location setting: excluded under india and eu."),
    "firestore": _e(["asia-south1", "asia-south2"],
                    ["eur3", "europe-west1", "europe-west3", "europe-west4", "europe-west8", "europe-west9", "europe-west10", "europe-west12",
                     "europe-southwest1", "europe-north1", "europe-north2", "europe-central2"],
                    ["nam5", "us-central1"], ["rf_firestore_locations"],
                    "Location is fixed at creation. europe-west2 London and europe-west6 Zurich are not EU. US list partial."),
    "cognito": _e(["ap-south-1", "ap-south-2"], _AWS_EU, _AWS_US, ["rf_aws_cognito_endpoints"], "User-pool endpoints exist in these regions."),
    "bedrock": _e(["ap-south-1", "ap-south-2"], ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-3"], _AWS_US,
                  ["bedrock_docs", "rf_bedrock_india_blog"],
                  "Region ids where Bedrock serves requests (application inference profiles can be created there). Requests must use an "
                  "in-region model or a geographic profile whose destinations stay inside the residency area (see INFERENCE_PROFILES): "
                  "India = in. profile (ap-south-1 <-> ap-south-2 only). global.* profiles route to any commercial region and are valid only "
                  "for residency none. AWS: do not rely on the prefix alone; verify destinations with GetInferenceProfile."),
    "azure_managed_redis": _e(["centralindia"], ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral"],
                              ["eastus", "eastus2", "centralus", "westus2", "westus3"], ["azure_managed_redis", "azure_service_categories"],
                              "Azure lists Azure Managed Redis as a mainstream service: available in all recommended (availability-zone) regions within 90 "
                              "days of region GA; demand-driven in alternate regions, so South/West India are not listed. Region-category policy, not a "
                              "per-region table (the products-by-region table is a script page)."),
    # Azure per-service region groups. Foundational = all recommended and alternate regions; mainstream = all recommended regions.
    "azure_foundational": _e(["centralindia", "southindia", "westindia", "indiasouthcentral"],
                             ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral", "italynorth",
                              "polandcentral", "spaincentral", "austriaeast", "belgiumcentral", "denmarkeast"],
                             ["eastus", "eastus2", "centralus", "northcentralus", "southcentralus", "westcentralus", "westus", "westus2", "westus3"],
                             ["rf_azure_regions", "azure_service_categories"],
                             "Foundational services (Azure SQL Database, Azure Cosmos DB, Virtual Machines, AKS, Blob Storage) are available in all "
                             "recommended and alternate regions. Cosmos DB's own compliance page also states it is available in all Azure regions."),
    "azure_mainstream": _e(["centralindia"], ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral"],
                           ["eastus", "eastus2", "centralus", "westus2", "westus3"], ["rf_azure_regions", "azure_service_categories"],
                           "Mainstream services (App Service, Azure Functions, Azure Database for MySQL/PostgreSQL) are guaranteed only in recommended "
                           "(availability-zone) regions; only those listed. Central India is the India recommended region."),
    "azure_mysql": _e(["centralindia", "southindia"],
                      ["westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral", "italynorth", "polandcentral",
                       "spaincentral", "austriaeast", "belgiumcentral", "denmarkeast"],
                      ["eastus", "eastus2", "centralus", "northcentralus", "southcentralus", "westcentralus", "westus", "westus2", "westus3"],
                      ["azure_mysql_regions"],
                      "Flexible server regions table (Availability = Yes). Jio India West is also listed but is a restricted region and is omitted. "
                      "Subscription quota can still block a region at creation time."),
    "azure_postgres": _e(["centralindia", "southindia"], ["westeurope", "germanywestcentral"], ["eastus"], ["dbs_azure_pg_overview"],
                         "Flexible server region table (subset recorded by the database layer task, 2026-11-13). Regions marked $ can be "
                         "temporarily blocked for new servers."),
    "azure_container_apps": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["azure_service_categories"],
                               "Azure Container Apps is a strategic service: demand-driven availability per region, and the products-by-region table "
                               "could not be read. Fails closed under any residency; App Service is the verified alternative."),
    "azure_static_web_apps": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["swa_faq"],
                                "Static assets are globally distributed; the managed Functions region is chosen at creation but the region list "
                                "was not readable. Personal data handled by the managed API therefore has no verified region."),
    "aurora_postgres": _e(["ap-south-1", "ap-south-2"], ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-3"],
                          _AWS_US, ["aurora_regions"], "Aurora PostgreSQL region table: Mumbai and Hyderabad listed."),
    "firebase_app_hosting": _e([], ["europe-west4"], ["us-central1", "us-east4", "us-east5"], ["firebase_app_hosting_regions"],
                               "App Hosting backends: us-central1, us-east4, us-east5, asia-east1, asia-southeast1, europe-west4. No India region."),
    "netlify": _e([], ["dub", "fra"], ["cmh", "iad", "pdx", "sfo"], ["netlify_functions_region"],
                  "Function regions (configurable on Pro and Enterprise): no Mumbai/India region; lhr is UK. Static assets are served "
                  "from the global CDN with no stated storage location."),
    "appwrite": _e([], ["fra"], ["nyc", "sfo"], ["appwrite_regions"],
                   "Appwrite Cloud regions: Frankfurt, New York, Sydney, San Francisco, Singapore, Toronto; Bangalore is 'coming soon'."),
    "hetzner": _e([], ["fsn1", "nbg1", "hel1"], ["ash", "hil"], ["hetzner_docs"],
                  "Cloud locations: Falkenstein, Nuremberg (DE), Helsinki (FI), Ashburn, Hillsboro (US), Singapore. No India location."),
    "auth0": _e([], ["EU"], ["US"], ["rf_auth0_cloud"],
                "Public cloud areas: US, UK, EU, AU, JP, CA. Private cloud (Enterprise) advertises 60+ regions; India there is UNKNOWN and not used."),
    "clerk": _e([], [], ["US"], ["rf_clerk_security"], "No region selection; hosted in the US (EU/UK/CH data moves under the EU-US DPF)."),
    "sentry": _e([], ["de"], ["us"], ["rf_sentry_locations"], "SaaS storage: US (Iowa) or EU (Frankfurt) only."),
    "razorpay": _e(["india"], UNKNOWN, UNKNOWN, ["rf_razorpay_pg"],
                   "Own docs list 'data localisation' for the RBI payments path; EU/US residency not applicable/unverified."),
    "cashfree": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["rf_cashfree_security"], "Data localisation claim only from a compliance-vendor case study: unverified."),
    "stripe": _e([], UNKNOWN, UNKNOWN, ["stripe_india"],
                 "Invite-only for new Indian businesses; never recommended when india payments are in play (a business rule, shown as an "
                 "alternative with this reason). Data-location pages not checked."),
    "self_hosted": _e(ANY, ANY, ANY, [], "Self-hosted/on-prem components run wherever the team deploys them.", other=ANY, conf="V"),
    "github_actions": _e(UNKNOWN, UNKNOWN, UNKNOWN, [], "Handles source code, not user data: policy allows it with an info note (filters, not a vendor fact)."),
    "msg91": _e(UNKNOWN, UNKNOWN, UNKNOWN, ["sv_msg91_privacy"],
                "Checked 2026-11-13: the privacy policy says the Service is hosted in the United States or Germany but also lists AWS India "
                "regions as a processor option, and no page commits to Indian storage: left unknown (fail closed)."),
    # Microsoft Entra ID: tenant location maps only to a geo (Australia, Asia/Pacific, EMEA, Japan, North America, Worldwide); there is no
    # India country option (Go-Local is Australia and Japan only), so India residency is not available (verified none). EU/US stay unknown
    # because EMEA and North America are geos, not the EU/US jurisdictions.
    "entra_id": _e([], UNKNOWN, UNKNOWN, ["sv_entra_data_residency"],
                   "Checked 2026-11-13: tenant data sits in the Asia/Pacific geo for Indian tenants; the page lists no India location and only "
                   "Australia and Japan for the Go-Local add-on. India residency cannot be met. EU/US not mapped (geos, not jurisdictions)."),
}

# Amazon Bedrock geographic inference-profile prefixes per residency (product field, NOT region ids).
# regions_for("bedrock", ...) returns region ids only; filters that pick a Bedrock model must also use this prefix.
INFERENCE_PROFILES = {
    "bedrock": {"india": "in.", "eu": "eu.", "us": "us.", "none": "global.", "other": None,
                "sources": ["bedrock_docs", "rf_bedrock_india_blog"],
                "note": "global.* routes to any commercial region (residency none only); verify destinations with GetInferenceProfile."},
}

# Provider aliases: product keys resolve to their vendor entry when the product has none of its own.
ALIASES = {"firebase": "firebase_auth", "gcs": "gcp", "s3": "aws", "rds": "aws", "ecs": "aws", "cloudwatch": "aws",
           "mongodb": "mongodb_atlas", "atlas": "mongodb_atlas", "fly_machines": "fly", "r2": "cloudflare_r2", "d1": "cloudflare_d1",
           "cloudflare_workers": "cloudflare", "cloudflare_cdn": "cloudflare", "do": "digitalocean",
           "aurora": "aurora_postgres", "azure_sql": "azure_foundational", "cosmosdb": "azure_foundational",
           "azure_vms": "azure_foundational", "azure_aks": "azure_foundational", "azure_app_service": "azure_mainstream",
           "azure_functions": "azure_mainstream"}

# Explicit product-level exceptions (kept visible for the filters and the report)
PRODUCT_EXCEPTIONS = {
    "fly_managed_postgres": "Not offered in bom: stateful Postgres on Fly is not available under india.",
    "bedrock": "Use the in. geographic inference profile under india (INFERENCE_PROFILES); global.* profiles are excluded.",
    "cloudflare_r2": "No India jurisdiction; eu/us jurisdictions exist.",
    "cloudflare_d1": "No India jurisdiction; eu/us jurisdictions exist.",
    "cloudflare": "Country-level processing confinement needs DLS (Enterprise add-on); India unverified.",
    "firebase_auth": "US-only processing, no location choice.",
    "fly": "No India region at all (bom is not on the official regions list).",
    "firebase_app_hosting": "No India region.",
    "netlify": "No India function region.",
    "azure_container_apps": "Strategic service with demand-driven regions: fail closed under any residency.",
    "azure_static_web_apps": "Managed Functions region list unverified: fail closed for personal data.",
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


# ---- Supporting-service additions (T3-KB, 2026-11-13).  New vendor rows only.  A vendor whose region list could not be
# confirmed from an official page is UNKNOWN in all three groups (fail closed); sources are the pages read that day.
ENTRIES["azure_strategic"] = _e(UNKNOWN, UNKNOWN, UNKNOWN, ["azure_service_categories"],
                                "Strategic Azure services (Azure Machine Learning, Microsoft Foundry, Azure SignalR Service, Notification Hubs) have "
                                "demand-driven availability per region and the products-by-region table could not be read: fails closed.")
ENTRIES["gcp_identity_platform"] = _e(UNKNOWN, UNKNOWN, UNKNOWN, ["gcp_hipaa"],
                                      "Identity Platform's BAA coverage is documented but where user records are stored is not: fails closed.")
_SV_UNVERIFIED_REGIONS = {
    "workos": "sv_workos_security", "ably": "sv_ably_docs", "pusher": "sv_pusher_docs", "payu": "sv_payu_docs",
    "paddle": "sv_paddle_site", "adyen": "sv_adyen_pci", "paypal_braintree": "sv_braintree_docs",
    "revenuecat": "sv_revenuecat_docs", "anthropic": "sv_anthropic_privacy", "algolia": "sv_algolia_pricing",
    "elastic_cloud": "sv_elastic_cloud_docs", "backblaze": "sv_b2_docs", "grafana_cloud": "sv_grafana_cloud_docs",
    "datadog": "sv_datadog_docs", "postmark": "sv_postmark_docs", "resend": "sv_resend_docs",
    "apns": "apple_apns", "twilio": "sv_twilio_verify_docs", "sanity": "sv_sanity_docs", "powersync": "sv_powersync_pricing",
    "mux": "sv_mux_docs",
}
for _k, _s in sorted(_SV_UNVERIFIED_REGIONS.items()):
    ENTRIES[_k] = _e(UNKNOWN, UNKNOWN, UNKNOWN, [_s],
                     "Data location for this vendor was not confirmed on an official page on 2026-11-13: fails closed under any residency.")

# Firebase Cloud Messaging: the Firebase privacy page lists it under "Global services" with no location choice, so there is no India
# residency commitment (verified none). EU/US are not offered as a choice either; left unknown.
ENTRIES["fcm"] = _e([], UNKNOWN, UNKNOWN, ["firebase_privacy"],
                    "Checked 2026-11-13: FCM is listed among Firebase 'Global services' (processed in multiple locations); no data-location "
                    "selection and no India residency commitment. Fails closed under india residency.")

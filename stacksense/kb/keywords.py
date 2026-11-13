"""Description keyword rules (plan section 6.5).

``RULES`` is an ordered tuple of :class:`Rule`; ``stacksense.description.extract`` evaluates them in this
order, case-insensitively, and emits at most one signal per rule id.

Rule fields
-----------
id        signal id (profile.py and scoring.py read: ledger, booking, inventory, sensors, social_graph,
          recommendation, fraud, low_end_devices, and any ``cms=`` effect).
patterns  regexes (``re.IGNORECASE``); each is already word-bounded.
effect    ``key=value`` machine-readable effect. ``consistency=``, ``data_shape=``, ``cms=`` and
          ``geographic_spread=`` are *inferred values* applied only when the field is ``auto``/absent;
          ``need=`` adds a supporting need; ``note=`` is an info-only note. The engine never lets a signal
          override an explicit field.
fields    schema paths the signal relates to. When one of them is explicitly set against the signal
          (``contradicts``), the engine raises DESCRIPTION_MISMATCH (info) and the explicit field wins.
contradicts  ((path, value), ...) explicit values that contradict the signal.
why       why the inference holds (shown in explanations).
source    key in kb/sources.py, or None when the inference is plain reading of the text.
"""
from __future__ import annotations

from typing import NamedTuple


class Rule(NamedTuple):
    id: str
    patterns: tuple[str, ...]
    effect: str
    fields: tuple[str, ...] = ()
    contradicts: tuple[tuple[str, object], ...] = ()
    why: str = ""
    source: str | None = None


_NUM = r"(?:\d+|two|three|four|five|six|seven|eight|nine|ten|several|multiple|many)"

RULES: tuple[Rule, ...] = (
    Rule("ledger",
         (r"\bdouble[- ]entry\b", r"\bledgers?\b", r"\bwallet balances?\b", r"\bescrow\b"),
         "consistency=strong", ("requirements.consistency",), (("requirements.consistency", "eventual"),),
         "money movement needs ACID transactions and append-only ledger tables with constraints; "
         "TigerBeetle is a purpose-built alternative", "tigerbeetle"),
    Rule("upi",
         (r"\bupi\b", r"\bemi\b", r"\binr\b", r"\brupees?\b", r"\be-?nach\b", r"\bautopay\b"),
         "need=india_payments_path", ("requirements.payments",), (("requirements.payments", False),),
         "UPI, EMI and e-NACH mandates are Indian rails: use an India payment gateway even if residency is none",
         "razorpay_docs"),
    Rule("subscription",
         (r"\bper[- ]seat\b", r"\bsubscriptions?\b", r"\brecurring (?:payments?|billing|charges?)\b",
          r"\bbilling plans?\b"),
         "need=payments_subscriptions", ("requirements.payments",), (("requirements.payments", False),),
         "recurring billing needs a payment provider that supports subscriptions", "stripe_docs"),
    Rule("kyc_documents",
         (r"\bkyc\b", r"\bdocument uploads?\b", r"\baadhaar\b", r"\bpan card\b", r"\bidentity proofs?\b"),
         "need=encrypted_document_storage", ("requirements.file_media_storage",),
         (("requirements.file_media_storage", False),),
         "identity documents are personal data: encrypted storage with a retention rule", "dpdp_act"),
    Rule("chat",
         (r"\bchat(?:s|ting)?\b", r"\bmessag(?:e|es|ing)\b", r"\binbox(?:es)?\b"),
         "need=realtime", ("requirements.realtime",), (("requirements.realtime", False),),
         "chat needs a persistent connection or push channel", "socketio_docs"),
    Rule("collaborative_editing",
         (r"\blive cursors?\b", r"\bmultiplayer\b", r"\bcollaborat\w*", r"\bedit the same\b",
          r"\bwhiteboards?\b", r"\bco-?edit\w*"),
         "need=crdt_realtime", ("requirements.realtime",), (("requirements.realtime", False),),
         "simultaneous edits need a conflict-free (CRDT) realtime path", "yjs_docs"),
    Rule("live_tracking",
         (r"\blive (?:location|tracking)\b", r"\btrack(?:ing)? (?:drivers?|orders?|vehicles?|riders?|deliver\w*)\b"),
         "need=realtime_geo", ("requirements.realtime",), (("requirements.realtime", False),),
         "moving positions must be pushed to clients as they change", "postgis"),
    Rule("gps",
         (r"\bgps\b", r"\bgeo-?tag\w*", r"\blocations?\b", r"\bnearby\b", r"\bmaps?\b"),
         "note=postgis_and_maps", (), (),
         "location data suits PostGIS on the database and a maps provider in supporting services", "postgis"),
    Rule("photos",
         (r"\bphotos?\b", r"\bimages?\b", r"\bpictures?\b"),
         "need=object_storage_image_resizing", ("requirements.file_media_storage",),
         (("requirements.file_media_storage", False),),
         "uploaded images need object storage and resizing", None),
    Rule("video",
         (r"\bvideos?\b", r"\bstream(?:ing)?\b", r"\blive class(?:es)?\b"),
         "need=video_service_cdn", ("requirements.file_media_storage",),
         (("requirements.file_media_storage", False),),
         "video needs transcoding/streaming and a CDN", "sv_cf_stream_docs"),
    Rule("low_end_devices",
         (r"\blow-?end\b", r"\b[1-3] ?gb (?:of )?ram\b", r"\bfeature phones?\b",
          r"\bentry-level (?:android|phones?|devices?)\b"),
         "note=device_fit", ("project.platforms",), (),
         "small memory budgets favour native or compiled toolkits and small APKs", None),
    Rule("intermittent_connectivity",
         (r"\bintermittent\w*", r"\b2g\b", r"\b3g\b", r"\bpoor (?:network|connectivity|signal)\b",
          r"\boffline\b", r"\bsync(?:s|ed)? when\b"),
         "need=resumable_uploads_sync_queue", ("requirements.offline_support",),
         (("requirements.offline_support", False),),
         "unreliable links need resumable uploads and a local sync queue", "android_offline_first"),
    Rule("markdown",
         (r"\bmarkdown\b", r"\bmdx?\b"),
         "cms=git_markdown", ("requirements.cms",), (),
         "Markdown content is edited as files in Git", None),
    Rule("cms_editors",
         (r"\beditors?\b", r"\bnon-technical\b", r"\bcontent team\b", r"\bnewsroom\b"),
         "cms=headless", ("requirements.cms",), (),
         "non-developers editing content need a headless CMS with a UI", "sv_sanity_docs"),
    Rule("notifications",
         (r"\bnotif\w*", r"\breminders?\b", r"\balerts?\b", r"\bsms\b", r"\bemail (?:alerts?|digests?)\b"),
         "need=notification_provider", ("requirements.notifications",), (("requirements.notifications", False),),
         "notifications need a queue trigger and a delivery provider", "fcm_docs"),
    Rule("search",
         (r"\bsearch\w*", r"\bfilter by\b", r"\bcatalog(?:ue)?s?\b"),
         "note=search", ("requirements.full_text_search",), (("requirements.full_text_search", False),),
         "search or catalogue browsing suggests a text index", "pg_fts"),
    Rule("sensors",
         (r"\bsensors?\b", r"\btelemetry\b", r"\bdevice data\b", r"\bmqtt\b", r"\bmeter readings?\b"),
         "data_shape=time_series", ("requirements.data_shape",), (("requirements.data_shape", "document"),),
         "device readings are time-ordered, append-heavy data; an MQTT broker ingests them", "emqx_docs"),
    Rule("dashboard",
         (r"\bdashboards?\b", r"\breports?\b", r"\breporting\b", r"\banalytics\b", r"\bbi\b"),
         "need=bi_tool", (), (),
         "reporting is served by a BI tool rather than custom screens", "sv_metabase_docs"),
    Rule("credit_scoring",
         (r"\bscor(?:e|ing) models?\b", r"\bcredit scor\w*", r"\bcredit models?\b"),
         "need=in_process_tabular_model", ("requirements.ml_features",), (("requirements.ml_features", "none"),),
         "a tabular scoring model can run in-process without a model-serving platform", "onnxruntime"),
    Rule("recommendation",
         (r"\brecommend(?:s|ed|ation|ations|er|ers|ing)?\b",),
         "data_shape=graph", ("requirements.ml_features", "requirements.data_shape"),
         (("requirements.ml_features", "none"),),
         "recommendations are driven by user-item relationships", None),
    Rule("fraud",
         (r"\bfraud\w*",),
         "data_shape=graph", ("requirements.ml_features", "requirements.data_shape"),
         (("requirements.ml_features", "none"),),
         "fraud detection looks for linked accounts (fraud rings)", None),
    Rule("social_graph",
         (r"\bsocial graph\b", r"\bfollowers?\b", r"\bfollowing\b", r"\bfriends?\b",
          r"\bfriend(?:s)? of friends?\b", r"\bconnections? between users\b"),
         "data_shape=graph", ("requirements.data_shape",), (("requirements.data_shape", "document"),),
         "relationship traversal is the core query of a social network", None),
    Rule("chatbot",
         (r"\bchat-?bots?\b", r"\bassistants?\b", r"\bquestion answering\b"),
         "need=llm_assistant", ("requirements.ml_features",), (("requirements.ml_features", "none"),),
         "an assistant needs an LLM", None),
    Rule("rag",
         (r"\brag\b", r"\bknowledge base\b", r"\bretrieval[- ]augmented\b"),
         "need=llm_rag", ("requirements.ml_features",), (("requirements.ml_features", "none"),),
         "answering over documents needs retrieval plus an LLM", "pgvector"),
    Rule("internal_only",
         (r"\bused only by (?:our )?employees\b", r"\binternal(?:ly)?\b", r"\bintranet\b", r"\bback-?office\b"),
         "note=sso_no_cdn_seo", ("requirements.seo_critical",), (("requirements.seo_critical", True),),
         "an employee-only tool needs no CDN or SEO, and company SSO is preferred", None),
    Rule("booking",
         (r"\bbook(?:ing|ings)\b", r"\bappointments?\b", r"\breserv(?:e|es|ed|ing|ation|ations)\b",
          r"\b(?:customers?|users?|clients?|patients?|guests?|members?|people|parents|students?|riders?) books?\b",
          r"\bbooks? (?:a|an|the|their|our|slots?|rooms?|tickets?|seats?)\b"),
         "consistency=strong", ("requirements.consistency",), (("requirements.consistency", "eventual"),),
         "a slot must never be sold twice: strong consistency and a double-booking constraint", None),
    Rule("inventory",
         (r"\binventory\b", r"\bin stock\b", r"\bout of stock\b", r"\bstock (?:levels?|counts?|tracking|management|alerts?)\b",
          r"\bwarehouses?\b"),
         "consistency=strong", ("requirements.consistency",), (("requirements.consistency", "eventual"),),
         "stock counts must not oversell: strong consistency", None),
    Rule("multi_city",
         (_NUM + r"\+? cit(?:y|ies)\b", r"\bmulti-?city\b"),
         "geographic_spread=single_country", ("scale.geographic_spread",), (("scale.geographic_spread", "single_city"),),
         "several cities means at least a country-wide footprint (assumption only)", None),
    Rule("global",
         (r"\bworldwide\b", r"\bglobally\b", r"\bglobal (?:users|audience|customers|reach|market|launch)\b",
          r"\b\d+\+? countries\b"),
         "geographic_spread=global", ("scale.geographic_spread",), (("scale.geographic_spread", "single_city"),
                                                                    ("scale.geographic_spread", "single_country")),
         "a worldwide audience suggests a CDN and multi-region reads (assumption only)", None),
    Rule("government",
         (r"\bgovernment\b", r"\bministry\b", r"\bpublic sector\b", r"\bnic\b", r"\bmeghraj\b"),
         "note=meity_empanelled_cloud", (), (),
         "government workloads usually require a MeitY-empanelled cloud", None),
    Rule("health",
         (r"\bpatients?\b", r"\bclinics?\b", r"\bprescriptions?\b", r"\btelehealth\b", r"\behr\b"),
         "note=health_data", ("compliance",), (),
         "health records are sensitive: check HIPAA/DPDP applicability", "hhs_hipaa_cloud"),
    Rule("children",
         (r"\bkids\b", r"\bchildren\b", r"\bstudents? under\b", r"\bminors\b"),
         "note=parental_consent", ("compliance",), (),
         "DPDP requires verifiable parental consent for children's data", "dpdp_act"),
)

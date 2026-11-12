"""Knowledge-base record constructors (plan section 4.1).

Records are plain ``dict`` objects (JSON-serialisable, hashable via canonical JSON).  Layer modules
build them with ``tech()`` (core layers), ``service()`` (supporting layers), ``offering()`` (concrete
products for an engine on a host family) and ``fact()``.  Constructors validate enums, ranges and
ordering and raise ``ValueError`` immediately; cross-record checks (unique ids, source keys) happen
in ``stacksense.kb``.

Layers
    core:       frontend_web frontend_mobile frontend_desktop frontend_game backend database hosting
    supporting: auth storage cdn cache queue search realtime payments ml ci_cd observability other
Size classes (ordered): xs < s < m < l < xl  (``SIZE_CLASSES``, ``size_index``, ``size_le``)
Status: maintained | maintenance_only | deprecated | retired.  Only ``maintained`` can be
recommended; any other status needs ``replaced_by`` (a record id or free text).
Attestation values: ``yes`` | ``plan:<name>`` | ``no`` | ``self`` (default ``no`` = fail closed).
Fact confidence: ``V`` verified this build, ``U`` verified earlier, ``K`` from knowledge (never
use a K fact in a hard filter).
Cost: ``{size: (min, max)}`` USD per month; a size may be omitted or ``None`` (not offered at that
size).  ``xl`` may be omitted: ``costs.band_for`` derives it as l x 3 (quote needed).

Complete example::

    tech(
        id="nextjs", name="Next.js", layer="frontend_web", kind="ssr",
        languages=["typescript", "javascript"], platforms=["web"],
        attrs={"cost_efficiency": 4, "dev_velocity": 5, "scalability": 4, "performance": 4,
               "maintainability": 4, "security": 4, "ecosystem": 5, "learning_curve": 3,
               "popularity": 5},
        ops_burden=1, scale_floor="xs", scale_ceiling="xl",
        cost={"xs": (0, 0), "s": (0, 20), "m": (0, 50), "l": (20, 200)},
        free_tier={"limit": "Open source framework; cost is the host's", "commercial_use": True},
        self_hostable=True, saas=False, open_source=True, licence="MIT", needs_internet=False,
        cloud_affinity=["any"], underlying_cloud=None,
        regions={"india": [], "eu": [], "us": []}, region_selectable=False, data_at_rest=False,
        attest={"hipaa_baa": "self", "pci_dss": "self", "soc2": "self", "iso27001": "self",
                "gdpr_dpa": "self"},
        lock_in=1, caps=["ssr", "ssg", "edge"], best_for=["ecommerce", "saas_b2b"],
        avoid_for=["gaming"], runtime="node", status="maintained", replaced_by=None,
        current_major="16", supported_until=None,
        strengths=["Mature SSR/SSG hybrid with the largest React ecosystem"],
        tradeoffs=["Opinionated routing; best experience on Vercel-like hosts"],
        facts=[fact("Next.js is the most used React meta-framework in the 2025 survey",
                    "so_survey_2025", "U")],
        sources=["nextjs_docs", "so_survey_2025"],
    )

Every record has exactly these keys: id name layer kind languages platforms attrs ops_burden
scale_floor scale_ceiling cost free_tier self_hostable saas open_source licence needs_internet
cloud_affinity underlying_cloud regions region_selectable data_at_rest attest lock_in caps best_for
avoid_for runtime status replaced_by current_major supported_until strengths tradeoffs facts sources
(``service`` adds ``triggers``; ``offering`` has its own shape, see ``offering``).
Lists are stored sorted where order carries no meaning (languages, platforms, caps, best_for,
avoid_for, cloud_affinity, sources); strengths, tradeoffs and facts keep author order.
"""
from __future__ import annotations

import re

CORE_LAYERS = ("frontend_web", "frontend_mobile", "frontend_desktop", "frontend_game",
               "backend", "database", "hosting")
SUPPORTING_LAYERS = ("auth", "storage", "cdn", "cache", "queue", "search", "realtime",
                     "payments", "ml", "ci_cd", "observability", "other")
LAYERS = CORE_LAYERS + SUPPORTING_LAYERS

SIZE_CLASSES = ("xs", "s", "m", "l", "xl")
STATUSES = ("maintained", "maintenance_only", "deprecated", "retired")
ATTR_KEYS = ("cost_efficiency", "dev_velocity", "scalability", "performance", "maintainability",
             "security", "ecosystem", "learning_curve", "popularity")
ATTEST_KEYS = ("hipaa_baa", "pci_dss", "soc2", "iso27001", "gdpr_dpa")
REGION_KEYS = ("india", "eu", "us")
CLOUDS = ("aws", "gcp", "azure", "independent", "any")
CONFIDENCE = ("V", "U", "K")
DEFAULT_ATTR = 3

_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def size_index(size: str) -> int:
    try:
        return SIZE_CLASSES.index(size)
    except ValueError:
        raise ValueError(f"unknown size class {size!r}; expected one of {SIZE_CLASSES}") from None


def size_le(a: str, b: str) -> bool:
    return size_index(a) <= size_index(b)


def size_max(*sizes: str) -> str:
    return max(sizes, key=size_index)


def size_min(*sizes: str) -> str:
    return min(sizes, key=size_index)


def fact(text: str, source_key: str, confidence: str = "U") -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("fact text must be a non-empty string")
    if not isinstance(source_key, str) or not source_key:
        raise ValueError("fact needs a source_key")
    if confidence not in CONFIDENCE:
        raise ValueError(f"fact confidence {confidence!r} not in {CONFIDENCE}")
    return {"text": text.strip(), "source_key": source_key, "confidence": confidence}


def _norm_cost(cost) -> dict:
    out = {}
    for size, band in (cost or {}).items():
        size_index(size)
        if band is None:
            continue
        lo, hi = band
        if lo < 0 or hi < lo:
            raise ValueError(f"cost band for {size} must satisfy 0 <= min <= max, got {band}")
        out[size] = [lo, hi]
    return out


def cost_problems(cost: dict) -> list[str]:
    """Bands must be non-decreasing in both min and max across the sizes that are present."""
    probs, prev = [], None
    for size in SIZE_CLASSES:
        band = cost.get(size)
        if band is None:
            continue
        if prev is not None and (band[0] < prev[1][0] or band[1] < prev[1][1]):
            probs.append(f"cost band not monotone: {prev[0]} {prev[1]} -> {size} {list(band)}")
        prev = (size, band)
    return probs


def _norm_attrs(attrs) -> dict:
    out = {k: DEFAULT_ATTR for k in ATTR_KEYS}
    for k, v in (attrs or {}).items():
        if k not in ATTR_KEYS:
            raise ValueError(f"unknown attr {k!r}; expected {ATTR_KEYS}")
        out[k] = v
    return out


def _norm_attest(attest) -> dict:
    out = {k: "no" for k in ATTEST_KEYS}
    for k, v in (attest or {}).items():
        if k not in ATTEST_KEYS:
            raise ValueError(f"unknown attestation {k!r}; expected {ATTEST_KEYS}")
        out[k] = v
    return out


def _norm_regions(regions) -> dict:
    out = {k: [] for k in REGION_KEYS}
    for k, v in (regions or {}).items():
        if k not in REGION_KEYS:
            raise ValueError(f"unknown region group {k!r}; expected {REGION_KEYS}")
        out[k] = list(v)
    return out


def _sorted_list(v) -> list:
    return sorted(set(v or ()))


def record_problems(rec: dict) -> list[str]:
    """Structural problems of one record (no cross-record or source checks)."""
    p: list[str] = []
    rid = rec.get("id", "?")
    if not isinstance(rec.get("id"), str) or not _ID.match(rec["id"]):
        p.append(f"{rid}: id must be snake_case")
    if not rec.get("name"):
        p.append(f"{rid}: name missing")
    if rec.get("layer") not in LAYERS:
        p.append(f"{rid}: layer {rec.get('layer')!r} unknown")
    for k, v in rec.get("attrs", {}).items():
        if k not in ATTR_KEYS or not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 5:
            p.append(f"{rid}: attr {k}={v!r} outside 0-5")
    ob = rec.get("ops_burden")
    if not isinstance(ob, (int, float)) or isinstance(ob, bool) or not 0 <= ob <= 5:
        p.append(f"{rid}: ops_burden {ob!r} outside 0-5")
    ll = rec.get("lock_in")
    if not isinstance(ll, int) or isinstance(ll, bool) or not 0 <= ll <= 3:
        p.append(f"{rid}: lock_in {ll!r} outside 0-3")
    f, c = rec.get("scale_floor"), rec.get("scale_ceiling")
    if f not in SIZE_CLASSES or c not in SIZE_CLASSES:
        p.append(f"{rid}: scale_floor/scale_ceiling must be size classes")
    elif size_index(f) > size_index(c):
        p.append(f"{rid}: scale_floor {f} above scale_ceiling {c}")
    p.extend(f"{rid}: {m}" for m in cost_problems(rec.get("cost", {})))
    if rec.get("status") not in STATUSES:
        p.append(f"{rid}: status {rec.get('status')!r} unknown")
    elif rec["status"] != "maintained" and not rec.get("replaced_by"):
        p.append(f"{rid}: non-maintained record needs replaced_by")
    for k, v in rec.get("attest", {}).items():
        if k not in ATTEST_KEYS or not (v in ("yes", "no", "self") or (isinstance(v, str) and v.startswith("plan:") and len(v) > 5)):
            p.append(f"{rid}: attest {k}={v!r} invalid")
    for c_ in rec.get("cloud_affinity", []):
        if c_ not in CLOUDS:
            p.append(f"{rid}: cloud_affinity {c_!r} unknown")
    su = rec.get("supported_until")
    if su is not None and not _DATE.match(str(su)):
        p.append(f"{rid}: supported_until must be an ISO date")
    for ft in rec.get("facts", []):
        if ft.get("confidence") not in CONFIDENCE:
            p.append(f"{rid}: fact confidence invalid")
    return p


def _build(layers, *, id, name, layer, kind, languages, platforms, attrs, ops_burden, scale_floor,
           scale_ceiling, cost, free_tier, self_hostable, saas, open_source, licence, needs_internet,
           cloud_affinity, underlying_cloud, regions, region_selectable, data_at_rest, attest,
           lock_in, caps, best_for, avoid_for, runtime, status, replaced_by, current_major,
           supported_until, strengths, tradeoffs, facts, sources) -> dict:
    if layer not in layers:
        raise ValueError(f"{id}: layer {layer!r} not allowed here; expected one of {layers}")
    rec = {
        "id": id, "name": name, "layer": layer, "kind": kind,
        "languages": _sorted_list(languages), "platforms": _sorted_list(platforms),
        "attrs": _norm_attrs(attrs), "ops_burden": ops_burden,
        "scale_floor": scale_floor, "scale_ceiling": scale_ceiling,
        "cost": _norm_cost(cost), "free_tier": dict(free_tier) if free_tier else None,
        "self_hostable": bool(self_hostable), "saas": bool(saas), "open_source": bool(open_source),
        "licence": licence, "needs_internet": bool(needs_internet),
        "cloud_affinity": _sorted_list(cloud_affinity), "underlying_cloud": underlying_cloud,
        "regions": _norm_regions(regions), "region_selectable": bool(region_selectable),
        "data_at_rest": bool(data_at_rest), "attest": _norm_attest(attest), "lock_in": lock_in,
        "caps": _sorted_list(caps), "best_for": _sorted_list(best_for),
        "avoid_for": _sorted_list(avoid_for), "runtime": runtime, "status": status,
        "replaced_by": replaced_by, "current_major": current_major, "supported_until": supported_until,
        "strengths": list(strengths or ()), "tradeoffs": list(tradeoffs or ()),
        "facts": [dict(f) for f in (facts or ())], "sources": _sorted_list(sources),
    }
    return rec


def _check(rec: dict) -> dict:
    probs = record_problems(rec)
    if probs:
        raise ValueError("; ".join(probs))
    return rec


def tech(id: str, name: str, layer: str, kind: str, *, languages=(), platforms=(), attrs=None,
         ops_burden: int = 2, scale_floor: str = "xs", scale_ceiling: str = "xl", cost=None,
         free_tier=None, self_hostable: bool = False, saas: bool = True, open_source: bool = False,
         licence: str = "proprietary", needs_internet: bool = True, cloud_affinity=("any",),
         underlying_cloud=None, regions=None, region_selectable: bool = False,
         data_at_rest: bool = False, attest=None, lock_in: int = 1, caps=(), best_for=(),
         avoid_for=(), runtime=None, status: str = "maintained", replaced_by=None,
         current_major=None, supported_until=None, strengths=(), tradeoffs=(), facts=(),
         sources=()) -> dict:
    """One candidate for a core layer (see module docstring for the full example)."""
    return _check(_build(CORE_LAYERS, **{k: v for k, v in locals().items()}))


def service(id: str, name: str, layer: str, kind: str, *, triggers=(), languages=(), platforms=(),
            attrs=None, ops_burden: int = 2, scale_floor: str = "xs", scale_ceiling: str = "xl",
            cost=None, free_tier=None, self_hostable: bool = False, saas: bool = True,
            open_source: bool = False, licence: str = "proprietary", needs_internet: bool = True,
            cloud_affinity=("any",), underlying_cloud=None, regions=None,
            region_selectable: bool = False, data_at_rest: bool = False, attest=None,
            lock_in: int = 1, caps=(), best_for=(), avoid_for=(), runtime=None,
            status: str = "maintained", replaced_by=None, current_major=None,
            supported_until=None, strengths=(), tradeoffs=(), facts=(), sources=()) -> dict:
    """One candidate for a supporting layer: same fields as ``tech`` plus ``triggers``
    (requirement tags that make the layer necessary, see plan 6.1)."""
    args = {k: v for k, v in locals().items() if k != "triggers"}
    rec = _build(SUPPORTING_LAYERS, **args)
    rec["triggers"] = _sorted_list(triggers)
    return _check(rec)


def offering(id: str, engine: str, host: str, name: str, *, kind: str = "managed",
             regions=None, region_selectable: bool = True, attest=None, cost=None,
             ha_options=(), current_major=None, supported_until=None,
             status: str = "maintained", replaced_by=None, needs_internet: bool = True,
             facts=(), sources=()) -> dict:
    """A concrete product for ``engine`` (a tech/service id) on a host family (e.g. ``aws``,
    ``vercel``, ``self_hosted``): exact product ``name``, regions, attestations, cost band and
    HA option names (plan 3.10).  Keys: id engine host name kind regions region_selectable attest
    cost ha_options current_major supported_until status replaced_by needs_internet facts sources."""
    rec = {
        "id": id, "engine": engine, "host": host, "name": name, "kind": kind,
        "regions": _norm_regions(regions), "region_selectable": bool(region_selectable),
        "attest": _norm_attest(attest), "cost": _norm_cost(cost), "ha_options": list(ha_options or ()),
        "current_major": current_major, "supported_until": supported_until, "status": status,
        "replaced_by": replaced_by, "needs_internet": bool(needs_internet),
        "facts": [dict(f) for f in (facts or ())], "sources": _sorted_list(sources),
    }
    probs = []
    if not isinstance(id, str) or not _ID.match(id):
        probs.append(f"{id}: id must be snake_case")
    if status not in STATUSES:
        probs.append(f"{id}: status {status!r} unknown")
    elif status != "maintained" and not replaced_by:
        probs.append(f"{id}: non-maintained offering needs replaced_by")
    probs.extend(f"{id}: {m}" for m in cost_problems(rec["cost"]))
    if probs:
        raise ValueError("; ".join(probs))
    return rec

"""Explanation generation (plan sections 3.14 and 5.6).

Every string produced here is assembled from :class:`scoring.Contribution` reasons, combination
synergy terms, :class:`filters.Rejection` reasons, offering facts and literal input values; there is no
free text per scenario. KB ``tradeoffs`` are quoted as they are.

Public API
----------
``component(layer, chosen, others, rejections, p, *, choice=None, combo_alt=None, extra=(),
            hard=(), kb_id=None) -> dict``
    One statement section 4 component object (choice, justification, driven_by, alternatives,
    tradeoffs) for a scored candidate. ``kind == "none"`` candidates get the "None" templates.
``core_components(p, result, ranked, rejections) -> dict``
    The four core components (frontend, backend, database, hosting) for a ``combine.ComboResult``.
``summary(style_phrase, stack, p, *, relaxed=()) -> str``
    The one- or two-sentence summary of plan 5.6.
``decision_trace(p, ranked, rejections, result, *, kb_version, extra=None) -> dict``
    Per core layer the top 5 scored candidates with their contributions, every rejection with its
    reason, the top 5 combinations with synergy terms, and the constants (K, KB_DATE, kb_version).
``top_drivers(contribs, n) -> list[str]``
    The input fields with the largest summed absolute contribution.

Pure and deterministic: no clock, no randomness, ties broken by id or field path.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from . import kb, offerings
from .scoring import DYNAMIC_FIELDS, Contribution, Scored, fmt, val

MAX_DRIVEN_BY = 8
MAX_ALTERNATIVES = 4
MIN_ALTERNATIVES = 2
MAX_KB_TRADEOFFS = 2
MAX_NEG_TRADEOFFS = 2
TRADEOFF_NEGATIVE_MAX = -1.0
DRIVER_MIN = 0.5
POPULAR_MIN = 4
TRACE_TOP = 5
TRACE_PAIRS = 25

CORE_LAYERS = ("frontend", "backend", "database", "hosting")
CLIENT_LAYERS = ("frontend_web", "frontend_game", "frontend_mobile", "frontend_desktop")
F_RES = "infrastructure.data_residency"
F_COMP = "compliance"
F_CLOUD = "infrastructure.cloud_preference"
F_DEPLOY = "infrastructure.deployment_model"
F_PLAT = "project.platforms"
CLOUD_NAMES = {"aws": "AWS", "gcp": "Google Cloud", "azure": "Azure"}

# Which core layers a combination synergy term speaks for (combine.T["synergy"] keys).
SYNERGY_LAYERS = {
    "framework_host": ("frontend", "hosting"), "ssg_static_host": ("frontend", "hosting"),
    "backend_host": ("backend", "hosting"), "blazor_aspnet": ("frontend", "backend"),
    "jvm_containers": ("backend", "hosting"), "batteries_postgres": ("backend", "database"),
    "supabase_client": ("frontend", "backend"), "workers_d1": ("backend", "database"),
    "same_cloud": ("database", "hosting"), "shared_language": ("frontend", "backend"),
    "bff_split": ("frontend", "backend"), "managed_realtime": ("hosting",),
    "language_count": ("backend",), "one_codebase": ("frontend",),
}


# ------------------------------------------------------------------ small helpers
def _num(x: float) -> str:
    x = round(float(x), 2)
    return str(int(x)) if x.is_integer() else f"{x:g}"


def _signed(x: float) -> str:
    x = round(float(x), 2)
    return ("+" if x > 0 else "") + _num(x)


def _clean(reason: str) -> str:
    return (reason or "").strip().rstrip(".")


_TRAILING_VALUE = re.compile(r"\s*\(([+-]?\d+(?:\.\d+)?)\)$")


def _cite(c: Contribution) -> str:
    """'<reason> (+2 key)': the reason's own trailing period and '(+2)' are folded into one tag."""
    text = _clean(c.reason)
    m = _TRAILING_VALUE.search(text)
    if m and abs(float(m.group(1)) - c.value) < 0.005:
        text = text[:m.start()]
    return f"{text} ({_signed(c.value)} {c.key})"


def _tech(x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, Scored):
        return x.tech
    if isinstance(x, Mapping):
        return dict(x)
    t = getattr(x, "tech", None)
    return t if isinstance(t, dict) else None


def _name(x) -> str:
    t = _tech(x) or {}
    return t.get("name") or t.get("id") or "?"


def _id(x) -> str:
    t = _tech(x) or {}
    return t.get("id") or ""


def _is_none(x) -> bool:
    return (_tech(x) or {}).get("kind") == "none"


def _uniq(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for i in items:
        if i and i not in out:
            out.append(i)
    return out


def _value_text(p, path: str) -> str:
    v = val(p, path)
    if path == F_RES and getattr(p, "effective_residency", None) not in (None, v):
        return f"{path}={p.effective_residency}"
    return f"{path}={fmt(v)}"


def driven_fields(contribs: Iterable[Contribution]) -> list[str]:
    """Fields of contributions with |value| >= 0.5, by descending |value| then path."""
    rows = []
    for c in contribs:
        if abs(c.value) < DRIVER_MIN:
            continue
        for f in c.fields:
            rows.append((-abs(c.value), f))
    best: dict[str, float] = {}
    for v, f in rows:
        best[f] = min(best.get(f, 0.0), v)
    return [f for f, _ in sorted(best.items(), key=lambda t: (t[1], t[0]))]


def top_drivers(contribs: Iterable[Contribution], n: int = 2) -> list[str]:
    """Input fields with the largest summed |contribution| (ties by path)."""
    tot: dict[str, float] = {}
    for c in contribs:
        for f in c.fields:
            tot[f] = tot.get(f, 0.0) + abs(c.value)
    return [f for f, _ in sorted(tot.items(), key=lambda t: (-round(t[1], 4), t[0]))][:n]


def _popular(rejections: Iterable, exclude: Iterable[str] = ()) -> list:
    """Filtered-out candidates with popularity >= 4, most popular first, then by id."""
    ex = set(exclude)
    rows = []
    for r in rejections:
        if r.tech_id in ex:
            continue
        rec = kb.get(r.tech_id) or {}
        if rec.get("status") != "maintained":
            continue
        pop = (rec.get("attrs") or {}).get("popularity", 0) or 0
        if pop >= POPULAR_MIN:
            rows.append((-pop, r.tech_id, r))
    return [r for _, _, r in sorted(rows, key=lambda t: (t[0], t[1]))]


def hard_fields(p, layer: str) -> list[str]:
    """Hard-constraint inputs a candidate of ``layer`` had to satisfy (only the active ones)."""
    out = []
    if layer.startswith("frontend"):
        return [F_PLAT]
    if getattr(p, "effective_residency", "none") != "none":
        out.append(F_RES)
    if getattr(p, "compliance", ()) and layer in ("backend", "database", "hosting"):
        out.append(F_COMP)
    if getattr(p, "cloud_explicit", False) and getattr(p, "cloud_preference", "any") != "any" \
            and layer in ("database", "hosting"):
        out.append(F_CLOUD)
    if getattr(p, "deployment", "managed_cloud") != "managed_cloud":
        out.append(F_DEPLOY)
    return out


def hard_sentence(p, layer: str, tech: dict | None, *, region: str | None = None,
                  offering_reasons: Iterable[str] = ()) -> str | None:
    """Sentence 3 of plan 5.6: the hard constraints the choice satisfies, with the KB fact."""
    if tech is None or tech.get("kind") == "none":
        return None
    parts = []
    reasons = [r for r in offering_reasons if "satisfying" in r or "attestations pass" in r]
    if reasons:
        return " ".join(_clean(r) + "." for r in reasons)
    res = getattr(p, "effective_residency", "none")
    if res not in ("none", "other") and region:
        parts.append(f"runs in {region}, satisfying {F_RES}={res}")
    elif res not in ("none",) and layer in ("hosting", "database") and tech.get("self_hostable") \
            and getattr(p, "deployment", "") != "managed_cloud":
        parts.append(f"is self-hosted, so data stays where {F_RES}={res} requires")
    cloud = getattr(p, "cloud", None)
    if cloud and getattr(p, "cloud_explicit", False) and layer in ("hosting", "database"):
        if cloud in (tech.get("cloud_affinity") or ()):
            parts.append(f"runs on {CLOUD_NAMES.get(cloud, cloud)}, satisfying {F_CLOUD}={cloud}")
    comp = list(getattr(p, "compliance", ()) or ())
    if comp and layer in ("hosting", "database", "backend") and parts:
        parts.append(f"passes the attestation checks for compliance={fmt(comp)}")
    dep = getattr(p, "deployment", "managed_cloud")
    if dep != "managed_cloud" and layer == "hosting":
        parts.append(f"fits {F_DEPLOY}={dep} ({tech.get('kind')} host)")
    if not parts:
        return None
    return f"{tech['name']} " + ", ".join(parts) + "."


# ------------------------------------------------------------------ why_not
def why_not(win: Scored, alt: Scored, *, combo_gap: tuple[float, float] | None = None) -> str:
    """Alternative's why_not: the two contributions with the largest negative delta vs the winner."""
    deltas: dict[str, list] = {}
    for c in win.contributions:
        deltas[c.key] = [c.value, 0.0, c, None]
    for c in alt.contributions:
        row = deltas.setdefault(c.key, [0.0, 0.0, None, None])
        row[1] = c.value
        row[3] = c
    worst = sorted(((a - w, k, cw, ca, w, a) for k, (w, a, cw, ca) in deltas.items() if a - w < 0),
                   key=lambda t: (round(t[0], 4), t[1]))[:2]
    an, wn = _name(alt), _name(win)
    if combo_gap is not None and round(alt.total, 2) >= round(win.total, 2):
        head = (f"{an} scores {_num(alt.total)} on its own (vs {_num(win.total)} for {wn}), but the best "
                f"full stack built around it scores {_num(combo_gap[0])} vs {_num(combo_gap[1])}")
    elif combo_gap is None and round(alt.total, 2) > round(win.total, 2):
        head = (f"{an} scores {_num(alt.total)} on its own (vs {_num(win.total)} for {wn}), but no full stack "
                f"built around it scores as high once the other layers are combined")
    else:
        head = f"{an} scores {_num(alt.total)} vs {_num(win.total)} for {wn}"
        if combo_gap is not None:
            head += f" (full stack {_num(combo_gap[0])} vs {_num(combo_gap[1])})"
    if not worst:
        return head + "; no single term is worse, the combination terms decide." if combo_gap else \
            head + "; equal terms, the tie is broken by id."
    bits = []
    for d, k, cw, ca, w, a in worst:
        if ca is not None:
            bits.append(f"{_clean(ca.reason)} ({_signed(a)} vs {_signed(w)} {k})")
        else:
            bits.append(f"no {k} credit, while {_clean(cw.reason)} ({_signed(a)} vs {_signed(w)} {k})")
    return head + ": " + "; ".join(bits) + "."


def _rejection_why(r) -> str:
    return r.reason_text


# ------------------------------------------------------------------ one component
def _just_sentences(name: str, chosen: Scored, extra: Iterable[Contribution]) -> list[str]:
    pos = sorted((c for c in chosen.contributions if c.value > 0), key=lambda c: (-c.value, c.key))
    out = []
    if pos:
        out.append(f"{name} is chosen with a layer score of {_num(chosen.total)}: {_cite(pos[0])}.")
        if len(pos) > 1:
            out.append("It also gains from " + "; ".join(_cite(c) for c in pos[1:3]) + ".")
    else:
        out.append(f"{name} is chosen with a layer score of {_num(chosen.total)}, the highest among the "
                   f"options that pass the hard filters.")
    syn = [c for c in extra if c.value > 0]
    if syn:
        out.append("In this stack: " + "; ".join(_cite(c) for c in syn[:2]) + ".")
    return out


def _none_texts(layer: str, chosen: Scored, p) -> tuple[str, list[str]]:
    """Justification and driven_by for a 'None' component."""
    vals = [f"{f}={fmt(val(p, f))}" for f in DYNAMIC_FIELDS if val(p, f) is not None]
    what = {"backend": "server logic", "database": "stored application data"}.get(layer, layer)
    just = (f"No {layer} is needed: " + ", ".join(vals[:-1]) + (" and " if len(vals) > 1 else "")
            + (vals[-1] if vals else "") + f" need no {what} (dynamic score "
            + f"{getattr(p, 'dynamic_score', 0)}/8), so the site is served as pre-rendered pages.")
    fields = _uniq(list(DYNAMIC_FIELDS) + driven_fields(chosen.contributions))
    return just, fields


def component(layer: str, chosen: Scored, others: Iterable[Scored] = (), rejections: Iterable = (), p=None, *,
              choice: str | None = None, combo_alt: tuple[Scored, float, float] | None = None,
              extra: Iterable[Contribution] = (), hard: Iterable[str] = (), kb_id: str | None = None,
              more_alternatives: Iterable[dict] = (), more_tradeoffs: Iterable[str] = (),
              extra_sentences: Iterable[str] = (), subject: str | None = None) -> dict:
    """The statement section 4 component for ``chosen`` (plan 5.6).

    ``others``: other scored candidates of the layer, best first. ``rejections``: filters.Rejection
    of the layer. ``combo_alt``: (candidate, its best combo score, winner combo score) for the true
    runner-up from the combination search. ``extra``: combination terms that speak for this layer.
    ``hard``: sentences stating the hard constraints satisfied (sentence 3).
    """
    tech = chosen.tech
    name = choice or tech["name"]
    others = [o for o in others if o.tech["id"] != tech["id"]]
    rejections = list(rejections)
    extra = list(extra)

    # justification + driven_by
    if tech.get("kind") == "none":
        just, fields = _none_texts(layer, chosen, p)
    else:
        sentences = _just_sentences(subject or name, chosen, extra)
        sentences.extend(s for s in extra_sentences if s)
        sentences.extend(h for h in hard if h)
        just = " ".join(sentences)
        fields = driven_fields(list(chosen.contributions) + extra)
    fields = _uniq(fields + hard_fields(p, layer))
    pop = _popular(rejections, exclude=[tech["id"]])
    if pop:
        fields = _uniq(fields + list(pop[0].fields))
    if not fields:
        fields = [F_PLAT] if layer == "frontend" else ["project.type"]
    driven = fields[:MAX_DRIVEN_BY]

    # alternatives
    alts: list[dict] = []
    seen = {tech["id"]}

    def add(cid: str, choice_text: str, why: str):
        if cid in seen or len(alts) >= MAX_ALTERNATIVES:
            return
        seen.add(cid)
        alts.append({"choice": choice_text, "why_not": why})

    if tech.get("kind") == "none":
        real = [o for o in others if o.tech.get("kind") != "none"]
        if real:
            o = real[0]
            dyn = ", ".join(f"{f}={fmt(val(p, f))}" for f in DYNAMIC_FIELDS[:3])
            add(o.tech["id"], o.tech["name"],
                f"{o.tech['name']} would be the choice if a dynamic feature were added; with {dyn} it would "
                f"only add a component to run, secure and pay for (scores {_num(o.total)} vs {_num(chosen.total)}).")
    if combo_alt is not None:
        cand, alt_score, win_score = combo_alt
        add(cand.tech["id"], cand.tech["name"], why_not(chosen, cand, combo_gap=(alt_score, win_score)))
    for o in others:                                       # true runner-up within the layer
        if len(alts) >= 1:
            break
        add(o.tech["id"], o.tech["name"], why_not(chosen, o))
    kinds = {(_tech(chosen) or {}).get("kind")} | {(kb.get(a_id) or {}).get("kind") for a_id in seen}
    for o in others:                                       # (b) a runner-up of a different kind
        if o.tech.get("kind") not in kinds and o.tech["id"] not in seen:
            add(o.tech["id"], o.tech["name"], why_not(chosen, o))
            break
    for r in pop[:2]:                                      # (c) popular filtered-out candidates
        add(r.tech_id, r.name, _rejection_why(r))
    for a in more_alternatives:
        add(a.get("id") or a["choice"], a["choice"], a["why_not"])
    for o in others:                                       # fill to the minimum
        if len(alts) >= MIN_ALTERNATIVES:
            break
        add(o.tech["id"], o.tech["name"], why_not(chosen, o))
    for r in rejections:
        if len(alts) >= MIN_ALTERNATIVES:
            break
        if (kb.get(r.tech_id) or {}).get("status") == "maintained":
            add(r.tech_id, r.name, _rejection_why(r))

    # tradeoffs
    trade = list(tech.get("tradeoffs") or [])[:MAX_KB_TRADEOFFS]
    negs = sorted((c for c in list(chosen.contributions) + extra if c.value <= TRADEOFF_NEGATIVE_MAX),
                  key=lambda c: (c.value, c.key))
    trade += [_cite(c) + "." for c in negs[:MAX_NEG_TRADEOFFS]]
    trade += [t for t in more_tradeoffs if t]
    trade = _uniq(trade)

    out = {"choice": name, "justification": just, "driven_by": driven, "alternatives": alts,
           "tradeoffs": trade}
    if kb_id or tech.get("id"):
        out["kb_id"] = kb_id or tech["id"]
    return out


# ------------------------------------------------------------------ core components
def _layer_key(combo, layer: str):
    if layer == "frontend":
        return combo.frontend_label
    if layer == "backend":
        return combo.backend.tech["id"]
    if layer == "database":
        return (combo.database.tech["id"], getattr(combo.database_offering, "engine_id", None),
                (getattr(combo.database_offering, "offering", None) or {}).get("id"))
    return (combo.hosting.tech["id"], combo.frontend_hosting.tech["id"] if combo.frontend_hosting else None)


def _layer_scored(combo, layer: str) -> Scored | None:
    if layer == "frontend":
        return combo.frontend.scored if combo.frontend is not None else None
    return getattr(combo, layer)


def _combo_alt(result, layer: str):
    """First runner-up combination whose ``layer`` candidate differs from the winner's."""
    best = result.best
    win = _layer_scored(best, layer)
    for c in result.runners_up:
        s = _layer_scored(c, layer)
        if s is None or win is None or s.tech["id"] == win.tech["id"]:
            continue
        return s, c.score, best.score
    return None


def _synergies_for(combo, layer: str) -> list[Contribution]:
    return [c for c in combo.synergies if layer in SYNERGY_LAYERS.get(c.key, ())]


def _platforms_text(part) -> str:
    return ", ".join(part.platforms + tuple(part.partner_platforms))


def _frontend(p, result, ranked, rejections) -> dict:
    best = result.best
    parts = list(best.parts)
    if not parts:
        rec = {"id": "none_frontend", "name": "None", "kind": "none", "tradeoffs": []}
        clients = fmt(list(getattr(p, "clients", ()) or ()))
        return {"choice": "None",
                "justification": f"No client application is built: project.platforms={fmt(val(p, F_PLAT))} "
                                 f"lists no web, mobile or desktop client ({clients}); the API is the product.",
                "driven_by": [F_PLAT], "alternatives": [
                    {"choice": s.tech["name"], "why_not": f"project.platforms={fmt(val(p, F_PLAT))} has no web client "
                                                         f"for {s.tech['name']} to serve."}
                    for s in (ranked.get("frontend_web") or [])[:1]] or [
                    {"choice": "A web admin client", "why_not": f"project.platforms={fmt(val(p, F_PLAT))} asks for "
                                                                f"no client; add 'web' to get one."}],
                "tradeoffs": [f"Consumers integrate through the API only (project.platforms={fmt(val(p, F_PLAT))})."],
                "kb_id": rec["id"]}
    primary = parts[0] if best.frontend is None else best.frontend
    primary = next((pt for pt in parts if pt.layer == primary.layer), parts[0])
    layer_rank = list(ranked.get(primary.layer) or [])
    rej = list(rejections.get(primary.layer) or [])
    extra = _synergies_for(best, "frontend") + list(primary.contributions)
    sentences = []
    more_alts: list[dict] = []
    more_trade: list[str] = []
    for pt in parts:
        if pt is primary:
            continue
        pos = sorted((c for c in pt.scored.contributions if c.value > 0), key=lambda c: (-c.value, c.key))
        terms = [c for c in pt.contributions if c.value > 0]
        bits = [_cite(c) for c in (pos[:1] + terms[:1])]
        label = pt.label
        sentences.append(f"For {_platforms_text(pt)}: {label} (layer score {_num(pt.scored.total)})"
                         + (": " + "; ".join(bits) if bits else "") + ".")
        others = [s for s in (ranked.get(pt.layer) or []) if s.tech["id"] not in
                  {r["id"] for r in pt.records()}]
        if others:
            o = others[0]
            more_alts.append({"id": o.tech["id"], "choice": f"{o.tech['name']} ({_platforms_text(pt)})",
                              "why_not": why_not(pt.scored, o)})
        more_trade += [f"{pt.scored.tech['name']}: {t}" for t in (pt.scored.tech.get("tradeoffs") or [])[:1]]
        for rec in pt.records():
            rej += [r for r in (rejections.get(pt.layer) or []) if r.tech_id != rec["id"]]
    comp = component("frontend", primary.scored, layer_rank, rej, p, choice=best.frontend_label,
                     combo_alt=_combo_alt(result, "frontend"), extra=extra,
                     extra_sentences=sentences, more_alternatives=more_alts, more_tradeoffs=more_trade,
                     kb_id=primary.scored.tech["id"],
                     subject=primary.label if len(parts) > 1 else None)
    plat_fields = [F_PLAT]
    for pt in parts:
        plat_fields += driven_fields(list(pt.scored.contributions) + list(pt.contributions))
    comp["driven_by"] = _uniq(comp["driven_by"] + plat_fields)[:MAX_DRIVEN_BY]
    comp["kb_ids"] = [r["id"] for pt in parts for r in pt.records()]
    return comp


def _database(p, result, ranked, rejections) -> dict:
    best = result.best
    db = best.database
    res = best.database_offering
    choice = db.tech["name"]
    if res is not None and getattr(res, "offering", None) and getattr(res, "display", ""):
        choice = res.display          # the offering name already names the engine and region
    elif res is not None and hasattr(res, "choice"):
        choice = res.choice(db.tech["name"])
    hard = []
    if db.tech.get("kind") != "none":
        hs = hard_sentence(p, "database", db.tech, region=getattr(res, "region", None),
                           offering_reasons=getattr(res, "reasons", ()))
        if hs:
            hard.append(hs)
    trade = []
    ha = getattr(res, "ha", None)
    if ha:
        trade.append(f"requirements.availability={fmt(val(p, 'requirements.availability'))} needs {ha}, which "
                     f"roughly doubles the database line of the estimate.")
    fam = getattr(res, "family", None)
    if fam and getattr(res, "kind", None) == "managed" and fam not in ("aws", "gcp", "azure") \
            and (res.offering or {}).get("underlying_cloud"):
        trade.append(f"{res.display} runs on {res.offering['underlying_cloud']}; an outage there affects it.")
    comp = component("database", db, ranked.get("database") or [], rejections.get("database") or [], p,
                     choice=choice, combo_alt=_combo_alt(result, "database"),
                     extra=_synergies_for(best, "database"), hard=hard, more_tradeoffs=trade)
    off = getattr(res, "offering", None)
    if off:
        comp["offering_id"] = off["id"]
    return comp


def _hosting(p, result, ranked, rejections) -> dict:
    best = result.best
    host = best.hosting
    region = offerings.host_region(host.tech, p)
    name = host.tech["name"] + (f" ({region})" if region else "")
    sentences = []
    choice = name
    if best.separate_frontend_host:
        fh = best.frontend_hosting
        freg = offerings.host_region(fh.tech, p)
        fname = fh.tech["name"] + (f" ({freg})" if freg else "")
        role = "the back end" if not _is_none(best.backend) else "the server side"
        choice = f"{name} for {role} + {fname} for the web frontend"
        fsyn = [c for c in best.synergies if c.key in ("framework_host", "ssg_static_host")]
        sentences.append(f"The web frontend is served by {fname} (layer score {_num(fh.total)})"
                         + (": " + _cite(fsyn[0]) if fsyn else "") + ".")
    hard = []
    hs = hard_sentence(p, "hosting", host.tech, region=region)
    if hs:
        hard.append(hs)
    trade = []
    if "needs_managed_realtime" in (best.flags or ()):
        trade.append(f"{host.tech['name']} runs request-only functions, so requirements.realtime=true is served "
                     f"by a separate managed realtime service.")
    comp = component("hosting", host, ranked.get("hosting") or [], rejections.get("hosting") or [], p,
                     choice=choice, combo_alt=_combo_alt(result, "hosting"),
                     extra=_synergies_for(best, "hosting"), hard=hard, extra_sentences=sentences,
                     more_tradeoffs=trade, subject=name)
    if best.separate_frontend_host:
        comp["kb_ids"] = [host.tech["id"], best.frontend_hosting.tech["id"]]
    return comp


def _backend(p, result, ranked, rejections) -> dict:
    best = result.best
    be = best.backend
    hard = []
    if be.tech.get("saas"):
        hs = hard_sentence(p, "backend", be.tech, region=offerings.host_region(best.hosting.tech, p))
        if hs:
            hard.append(hs)
    return component("backend", be, ranked.get("backend") or [], rejections.get("backend") or [], p,
                     combo_alt=_combo_alt(result, "backend"), extra=_synergies_for(best, "backend"), hard=hard)


def core_components(p, result, ranked: Mapping[str, list], rejections: Mapping[str, list]) -> dict:
    """frontend/backend/database/hosting component objects for ``result.best``."""
    return {
        "frontend": _frontend(p, result, ranked, rejections),
        "backend": _backend(p, result, ranked, rejections),
        "database": _database(p, result, ranked, rejections),
        "hosting": _hosting(p, result, ranked, rejections),
    }


def stack_contributions(result) -> list[Contribution]:
    """Every contribution behind the chosen core stack (layer terms + combination terms)."""
    best = result.best
    out: list[Contribution] = []
    for pt in best.parts:
        out += list(pt.scored.contributions) + list(pt.contributions)
    for s in (best.backend, best.database, best.hosting):
        out += list(s.contributions)
    out += list(best.synergies)
    return out


# ------------------------------------------------------------------ summary
def summary(style_phrase: str, stack: Mapping[str, Any], p, *, drivers: Iterable[str] = (),
            relaxed: Iterable[str] = ()) -> str:
    """'{style}: {frontend} with {backend} on {database}, hosted on {hosting}. Driven mainly by ...'"""
    def ch(layer):
        c = stack.get(layer) or {}
        return c.get("choice", "None") if isinstance(c, Mapping) else "None"
    fe, be, db, ho = ch("frontend"), ch("backend"), ch("database"), ch("hosting")
    be_text = "no server back end" if be == "None" else be
    db_text = "no database" if db.startswith("None") else db
    s1 = f"{style_phrase}: {fe} with {be_text} and {db_text}, hosted on {ho}."
    drv = [_value_text(p, f) for f in drivers]
    rel = list(relaxed)
    if not drv and not rel:
        return s1
    s2 = "Driven mainly by " + " and ".join(drv) if drv else "Constraints relaxed"
    if rel:
        s2 += ("; relaxed: " if drv else ": ") + ", ".join(rel)
    return s1 + " " + s2 + "."


# ------------------------------------------------------------------ decision trace
def _c_dict(c: Contribution) -> dict:
    d = {"key": c.key, "value": c.value, "fields": list(c.fields), "reason": c.reason}
    if c.parts:
        d["parts"] = [{"field": f, "value": v, "text": t} for f, v, t in c.parts]
    return d


def _kb_date() -> str | None:
    try:
        from .kb import eol  # type: ignore  # Phase 4 module
        return str(eol.KB_DATE)
    except Exception:  # noqa: BLE001 - optional module
        from .kb import regions
        return getattr(regions, "ACCESSED", None)


def decision_trace(p, ranked: Mapping[str, list], rejections: Mapping[str, list], result, *,
                   kb_version: str, k: int, extra: Mapping[str, Any] | None = None) -> dict:
    layers = {}
    for layer in sorted(set(ranked) | set(rejections), key=lambda l: (l not in CLIENT_LAYERS, l)):
        layers[layer] = {
            "candidates": len(ranked.get(layer) or ()),
            "top": [{"id": s.tech["id"], "name": s.tech["name"], "total": round(s.total, 2),
                     "contributions": [_c_dict(c) for c in s.contributions]}
                    for s in list(ranked.get(layer) or ())[:TRACE_TOP]],
            "rejected": [r.to_dict() for r in rejections.get(layer) or ()],
        }
    combos = None
    if result is not None:
        top = ([result.best] if result.best else []) + list(result.runners_up)
        combos = {
            "considered": result.considered, "passed": result.passed, "k": result.k, "widened": result.widened,
            "top": [c.to_dict() for c in top[:TRACE_TOP]],
            "rejected_pairs_total": len(result.rejected_pairs),
            "rejected_pairs": [{"a": r.a, "b": r.b, "reason": r.reason} for r in result.rejected_pairs[:TRACE_PAIRS]],
            "infeasible_pair": list(result.infeasible_pair) if result.infeasible_pair else None,
            "infeasible_reason": result.infeasible_reason,
        }
    prof = {
        "size": p.size, "users": p.users, "peak_concurrent": p.peak_concurrent, "peak_rps": p.peak_rps,
        "data_volume_gb": p.data_volume_gb, "ops_capacity": p.ops_capacity,
        "delivery_pressure": p.delivery_pressure, "dynamic_score": p.dynamic_score,
        "needs_backend": p.needs_backend, "clients": list(p.clients), "languages": list(p.languages),
        "effective_residency": p.effective_residency, "consistency": p.consistency, "data_shape": p.data_shape,
        "signals": [{"id": s.id, "text": s.matched_text, "effect": s.effect} for s in p.signals],
    }
    out = {"constants": {"K": k, "KB_DATE": _kb_date(), "kb_version": kb_version},
           "profile": prof, "layers": layers, "combinations": combos}
    for key, value in (extra or {}).items():
        out[key] = value
    return out


__all__ = ["component", "core_components", "summary", "decision_trace", "why_not", "top_drivers",
           "driven_fields", "hard_fields", "hard_sentence", "stack_contributions"]

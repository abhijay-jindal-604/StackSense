"""Recommendation pipeline (plan section 3.17).

``recommend(raw, *, fill_defaults=False, trace=True, llm=None) -> dict`` is total: it never raises.

1. ``validate`` -> errors? ``invalid_input``.
2. ``description.extract``, ``existing.analyse``, ``profile.derive``.
3. ``conflicts.detect``: ``imply:``/valued ``relax:`` effects re-derive the profile once
   (:func:`derive_with_conflicts`); ``relax:`` effects become ``relaxed_constraints`` and ``RELAXED:``
   assumptions; an ``infeasible`` effect (hard-vs-hard conflict) makes the result infeasible.
4. Per core layer: KB candidates -> ``filters.filter_layer`` -> ``scoring.rank``.
5. ``combine.search`` (database offerings are resolved inside the search; read from the Combo), then
   ``combine.apply_budget``: the plan 7 budget fallback, pricing candidate stacks with
   ``cost.estimate`` including supporting-service lines (``budget_assumptions`` states the trade).
6. ``supporting.select``, ``architecture.decide``, ``cost.estimate``, ``conflicts.post_checks``.
7. Empty core layer, no compatible combination, or a hard-vs-hard conflict -> ``infeasible`` with a
   critical warning and ``nearest_feasible`` (each hard constraint relaxed in turn; when none works
   alone, pairs of relaxations; names only).
8. ``explain.*``, ``status.decide``, ``output.build``. The LLM is never consulted for the stack.

Pure and deterministic: no clock, no randomness, no environment reads.
"""
from __future__ import annotations

import copy
import itertools
from collections import Counter
from typing import Any

from .kb import eol as kb_eol
from . import architecture, combine, conflicts, cost, description, existing, explain, filters, kb, output, profile
from . import scoring, status, supporting
from .io import LoadedScenario
from .kb.keywords import RULES as _KEYWORD_RULES
from .scoring import fmt
from .validate import validate

INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
NO_CANDIDATE_CODE = "NO_FEASIBLE_CANDIDATE"
NO_COMBINATION_CODE = "NO_COMPATIBLE_STACK"
CLIENT_LAYER_PLATFORMS = (("frontend_web", ("web",)), ("frontend_mobile", ("android", "ios")),
                          ("frontend_desktop", ("desktop",)))
GAME_TYPES = ("gaming",)
LAYER_TEXT = {"frontend_web": "web frontend", "frontend_mobile": "mobile toolkit",
              "frontend_desktop": "desktop toolkit", "frontend_game": "game engine", "backend": "back end",
              "database": "database", "hosting": "host"}
RELAXED_PREFIX = "RELAXED:"
NEAREST_PAIR_LIMIT = 3
BLOCKING_FIELDS_MAX = 3
_KB_VERSION: list[str] = []


def _warning(code: str, severity: str, message: str, fields=()) -> dict:
    return {"code": code, "severity": severity, "message": message, "fields": list(fields)}


def kb_version() -> str:
    if not _KB_VERSION:
        _KB_VERSION.append(kb.kb_version())
    return _KB_VERSION[0]


def _safe_scenario_id(raw: Any) -> str | None:
    """Normalised id via validate() (used only when the pipeline itself failed)."""
    try:
        sid = validate(raw).profile.get("scenario_id")
    except Exception:  # noqa: BLE001
        return None
    return sid if isinstance(sid, str) else None


def recommend(raw: Any, *, fill_defaults: bool = False, trace: bool = True, llm=None) -> dict:
    """Return a section 4 result for one scenario. Never raises."""
    try:
        return _pipeline(raw, fill_defaults=fill_defaults, trace=trace, llm=llm)
    except Exception as exc:  # noqa: BLE001 - total function by contract
        return output.build(
            status="infeasible",
            scenario_id=_safe_scenario_id(raw),
            summary="The engine hit an internal error, so no stack is recommended.",
            warnings=[_warning(INTERNAL_ERROR_CODE, "critical",
                               f"Internal error ({type(exc).__name__}). Please report this input.")],
            kb_version=_kb_version_safe(),
        )


def _kb_version_safe() -> str:
    try:
        return kb_version()
    except Exception:  # noqa: BLE001
        return "unversioned"


def is_internal_error(result: dict) -> bool:
    return any(w.get("code") == INTERNAL_ERROR_CODE for w in result.get("warnings", []))


# ------------------------------------------------------------------ stages
def _derive(v):
    signals = description.extract(v.profile.get("project.description"))
    ex = existing.analyse(v.profile.get("infrastructure.existing_systems"))
    return profile.derive(v, signals, ex)


def _client_layers(p) -> list[str]:
    out = [layer for layer, plats in CLIENT_LAYER_PLATFORMS if any(c in p.clients for c in plats)]
    if p.clients and scoring.val(p, "project.type") in GAME_TYPES:
        out.insert(0, "frontend_game")
    return out


def core_candidates(p) -> tuple[dict, dict]:
    """(ranked, rejections) per core layer: KB candidates -> hard filters -> scoring.rank."""
    hosts, host_rej = filters.filter_layer("hosting", p)
    ranked, rejections = {}, {}
    for layer in _client_layers(p) + ["backend", "database", "hosting"]:
        if layer == "hosting":
            kept, rej = hosts, host_rej
        else:
            kw = {"hosts": hosts} if layer == "backend" else {}
            kept, rej = filters.filter_layer(layer, p, **kw)
        ranked[layer] = scoring.rank(layer, kept, p, scoring.context(layer))
        rejections[layer] = list(rej)
    return ranked, rejections


def _empty_layer(ranked) -> str | None:
    for layer in list(ranked):
        if layer == "frontend_game":
            continue
        if not ranked[layer]:
            return layer
    return None


def _search(p):
    ranked, rejections = core_candidates(p)
    layer = _empty_layer(ranked)
    if layer is not None:
        return ranked, rejections, None, layer
    return ranked, rejections, combine.search(ranked, p), None


def derive_with_conflicts(v):
    """Profile plus pre-selection conflicts; imply/valued-relax effects re-derive the profile exactly once."""
    p = _derive(v)
    pre = conflicts.detect(p, v)
    changes = conflicts.profile_changes(pre)
    if changes:
        p = _derive(conflicts.apply_changes(v, changes))
    return p, pre


def _hard_conflict(p, pre) -> bool:
    return bool(p.infeasible) or conflicts.infeasible(pre)


def _feasible(p, pre=()) -> bool:
    if _hard_conflict(p, pre):
        return False
    _, _, result, layer = _search(p)
    return layer is None and result is not None and result.feasible


# ------------------------------------------------------------------ description signals
def _rule(sig_id: str):
    return next((r for r in _KEYWORD_RULES if r.id == sig_id), None)


def description_warnings(v, signals) -> list[dict]:
    """DESCRIPTION_MISMATCH where a signal contradicts an explicit input, else DESCRIPTION_SIGNAL (info)."""
    out = []
    for s in signals:
        rule = _rule(s.id)
        clash = None
        if rule is not None:
            for path, value in rule.contradicts:
                if path in v.provided and v.profile.get(path) == value:
                    clash = (path, value)
                    break
        if clash is not None:
            out.append(_warning("DESCRIPTION_MISMATCH", "info",
                                f"The description mentions '{s.matched_text}' but {clash[0]}={fmt(clash[1])}; "
                                f"the explicit field was used.", ["project.description", clash[0]]))
        else:
            why = f" ({rule.why})" if rule is not None and rule.why else ""
            out.append(_warning("DESCRIPTION_SIGNAL", "info",
                                f"'{s.matched_text}' in the description -> {s.effect}{why}.",
                                ["project.description"] + [f for f in s.fields if f != "project.description"]))
    return out


def existing_outputs(p) -> tuple[list[dict], list[str]]:
    """EXISTING_SYSTEM_UNRECOGNISED warnings and integration notes for unmatched existing systems."""
    warns, notes = [], []
    ex = p.existing
    for raw in (ex.unmatched if ex else ()):
        warns.append(_warning("EXISTING_SYSTEM_UNRECOGNISED", "info",
                              f"'{raw}' was not recognised; assumed reachable through an API or scheduled export.",
                              ["infrastructure.existing_systems"]))
        notes.append(f"{raw}: integrate through its API or a scheduled export (infrastructure.existing_systems).")
    failed = {(m.raw, m.pattern_id): rej for m, _rec, rej in conflicts.existing_hard_failures(p)}
    for m in (ex.matches if ex else ()):
        rej = failed.get((m.raw, m.pattern_id))
        if rej is not None:
            # never suggest reusing a system that breaks a hard constraint (EXISTING_SYSTEM_CONFLICT)
            notes.append(f"{m.raw}: not reused as is, because {rej.reason_text.rstrip('.')}; "
                         f"{conflicts.existing_conflict_advice(p)}")
        elif m.integration_note:
            notes.append(m.integration_note)
    return warns, notes


def _conflicts(found, existing_warnings) -> tuple[list[dict], list[str]]:
    """Merge conflicts (``conflicts.detect`` / ``conflicts.post_checks``, plan 6.3) into the result.

    Returns (new warnings, relaxed constraints). A code already emitted by another module (profile, cost,
    supporting, validate) is not repeated, but its effect still applies.
    """
    return conflicts.merge(existing_warnings, found), conflicts.relaxed(found)


# ------------------------------------------------------------------ nearest feasible
def _set_path(raw: dict, path: str, value) -> None:
    node = raw
    parts = path.split(".")
    for k in parts[:-1]:
        nxt = node.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            node[k] = nxt
        node = nxt
    node[parts[-1]] = value


def nearest_feasible(raw, v, p, *, fill_defaults: bool) -> list[dict]:
    """Single relaxations of the hard constraints that yield a feasible stack (names only)."""
    trials = []
    res = v.profile.get("infrastructure.data_residency")
    if res not in (None, "none"):
        trials.append(("infrastructure.data_residency", res, "none"))
    comp = list(v.profile.get("compliance") or [])
    for regime in sorted(comp):
        trials.append(("compliance", regime, [c for c in comp if c != regime]))
    dep = v.profile.get("infrastructure.deployment_model")
    if dep not in (None, "managed_cloud"):
        trials.append(("infrastructure.deployment_model", dep, "managed_cloud"))
    cloud = v.profile.get("infrastructure.cloud_preference")
    if cloud not in (None, "any"):
        trials.append(("infrastructure.cloud_preference", cloud, "any"))
    if not isinstance(raw, dict):
        return []

    def works(changes) -> bool:
        r2 = copy.deepcopy(raw)
        comp_now = list(comp)
        for path, old, new in changes:
            if path == "compliance":
                comp_now = [c for c in comp_now if c != old]
                _set_path(r2, path, comp_now)
            else:
                _set_path(r2, path, new)
        v2 = validate(r2, fill_defaults=fill_defaults)
        if v2.errors:
            return False
        p2, pre2 = derive_with_conflicts(v2)
        return _feasible(p2, pre2)

    def text(t) -> tuple[str, str]:
        path, old, new = t
        if path == "compliance":
            return f"remove {old}", f"dropping '{old}' from compliance"
        return f"{fmt(old)} -> {fmt(new)}", f"changing {path} from {fmt(old)} to {fmt(new)}"

    out = []
    for t in trials:
        if not works([t]):
            continue
        relax, words = text(t)
        out.append({"field": t[0], "relax": relax, "message": f"{words[0].upper()}{words[1:]} makes a stack feasible."})
    if out:
        return out
    # no single relaxation works: try pairs (plan 3.17 step 7 names only; first PAIR_LIMIT that work)
    for a, b in itertools.combinations(trials, 2):
        if a[0] == b[0] == "compliance" and a[1] == b[1]:
            continue
        if not works([a, b]):
            continue
        (ra, wa), (rb, wb) = text(a), text(b)
        fields = list(dict.fromkeys([a[0], b[0]]))
        out.append({"field": " + ".join(fields), "fields": fields, "relax": f"{ra}; {rb}",
                    "message": f"No single change is enough; {wa} together with {wb} makes a stack feasible."})
        if len(out) >= NEAREST_PAIR_LIMIT:
            break
    return out


def _infeasible_warning(p, ranked, rejections, result, layer) -> dict:
    if layer is not None:
        rej = rejections.get(layer) or []
        rules = sorted({f for r in rej for f in r.fields})
        reasons = []
        for r in sorted(rej, key=lambda r: (-((kb.get(r.tech_id) or {}).get("attrs") or {}).get("popularity", 0),
                                            r.tech_id))[:3]:
            reasons.append(r.reason_text)
        msg = (f"No {explain_layer(layer)} passes the hard constraints"
               + (f" ({', '.join(f'{f}={fmt(scoring.val(p, f))}' for f in rules)})" if rules else "")
               + (": " + " ".join(reasons) if reasons else "."))
        return _warning(NO_CANDIDATE_CODE, "critical", msg, rules or ["project.platforms"])
    reason = (result.infeasible_reason if result is not None else None) or "no compatible combination"
    pair = list(result.infeasible_pair or ()) if result is not None else []
    blockers = blocking_fields(rejections, pair, p)
    msg = f"No combination of the remaining options works together: {reason.rstrip('.')}."
    if blockers:
        msg += (" The hard filters that removed the most candidates in those layers: "
                + ", ".join(f"{f}={fmt(scoring.val(p, f))}" for f in blockers) + ".")
    fields = ["infrastructure.deployment_model", "infrastructure.cloud_preference"]
    if pair and "frontend" in pair[0]:
        fields = ["project.platforms"] + fields
    fields = list(dict.fromkeys(blockers + fields))
    return _warning(NO_COMBINATION_CODE, "critical", msg, fields)


UNRESTRICTIVE_VALUES = ("any", "managed_cloud", "none")


def blocking_fields(rejections, pair, p=None) -> list[str]:
    """Input fields of the filter rejections in the blocked layer pair (plus hosting and backend, whose
    survivors decide which pairs exist), most frequent first, at most BLOCKING_FIELDS_MAX. Fields at an
    unrestrictive value (cloud any, managed_cloud, residency none, empty list) are not named."""
    layers = {"hosting", "backend"}
    for x in pair or ():
        if x == "frontend":
            layers.update(layer for layer in rejections if layer.startswith("frontend"))
        else:
            layers.add(x)
    counts = Counter(f for layer in sorted(layers) for r in (rejections.get(layer) or ()) for f in r.fields)

    def restrictive(f) -> bool:
        if p is None:
            return True
        v = scoring.val(p, f)
        return not (v is None or v in UNRESTRICTIVE_VALUES or v == [] or v == ())
    ranked = [f for f, _ in sorted(counts.items(), key=lambda t: (-t[1], t[0])) if restrictive(f)]
    return ranked[:BLOCKING_FIELDS_MAX]


def explain_layer(layer: str) -> str:
    return LAYER_TEXT.get(layer, layer)


# ------------------------------------------------------------------ budget fallback
def _cost_function(p):
    """``combo -> Cost`` with core and supporting-service lines (cached per combination)."""
    cache: dict = {}

    def cost_of(combo):
        key = combo.ids + tuple(pt.id for pt in combo.parts)
        if key not in cache:
            sup = supporting.select(p, combo.stack(),
                                    needs_managed_realtime="needs_managed_realtime" in combo.flags)
            cache[key] = cost.estimate(p, combo.stack(), extra_lines=sup.cost_lines(p))
        return cache[key]
    return cost_of


_COMBO_LAYERS = (("frontend", lambda c: c.frontend_label), ("backend", lambda c: c.backend.tech["name"]),
                 ("database", lambda c: getattr(c.database_offering, "display", "") or c.database.tech["name"]),
                 ("hosting", lambda c: c.hosting.tech["name"] + (f" + {c.frontend_hosting.tech['name']}"
                                                                 if c.separate_frontend_host else "")))


def _combo_diff(a, b) -> tuple[list[str], list[str]]:
    """Names of the core components where combinations ``a`` and ``b`` differ (a's names, b's names);
    frontend parts are compared per client layer."""
    xa, xb = [], []
    pa = {pt.layer: pt.label for pt in a.parts}
    pb = {pt.layer: pt.label for pt in b.parts}
    for layer in sorted(set(pa) | set(pb), key=combine.CLIENT_LAYERS.index):
        if pa.get(layer) != pb.get(layer):
            xa.append(pa.get(layer) or f"no {explain_layer(layer)}")
            xb.append(pb.get(layer) or f"no {explain_layer(layer)}")
    for layer, get in _COMBO_LAYERS:
        if layer == "frontend":
            continue
        na, nb = get(a), get(b)
        if na != nb:
            xa.append(na)
            xb.append(nb)
    return xa, xb


def budget_assumptions(result) -> list[str]:
    """The plan 7 trade sentence ("Chose X over Y to fit USD B: ...") or the no-fit sentence."""
    bc = getattr(result, "budget", None)
    if bc is None or bc.mode == "fits":
        return []
    b = fmt(bc.budget)
    n = combine.T["budget_fallback_top_n"]
    pct = fmt(round(combine.T["budget_fallback_accept_ratio"] * 100))
    if bc.mode == "fallback":
        x, y = _combo_diff(bc.combo, bc.displaced)
        return [f"Chose {' + '.join(x)} over {' + '.join(y)} to fit USD {b}/month "
                f"(budget.monthly_infra_usd={b}): the chosen stack's estimate starts at USD {bc.cost.min:,}/month "
                f"vs USD {bc.displaced_cost.min:,}, and its combination score {fmt(round(bc.combo.score, 2))} is "
                f"within {pct}% of the best {fmt(round(bc.displaced.score, 2))}."]
    rpct = fmt(round(combine.T["budget_cheapest_accept_ratio"] * 100))
    save = fmt(round(combine.T["budget_cheapest_min_saving"] * 100))
    text = (f"Budget fallback: no stack among the top {n} combinations has an estimate starting at or below "
            f"USD {b}/month within {pct}% of the best score")
    if bc.displaced is None:
        text += (f", and no cheaper stack within {rpct}% of the best score fits it or saves at least {save}%, "
                 f"so the recommended stack (USD {bc.cost.min:,}-{bc.cost.max:,}/month) is kept")
    else:
        text += (f", so the cheapest feasible stack within {rpct}% of the best score "
                 f"(USD {bc.cost.min:,}-{bc.cost.max:,}/month) is kept")
    if bc.displaced is not None:
        x, y = _combo_diff(bc.combo, bc.displaced)
        text += (f": {' + '.join(x)} instead of {' + '.join(y)} (USD {bc.displaced_cost.min:,}-"
                 f"{bc.displaced_cost.max:,}/month, score {fmt(round(bc.displaced.score, 2))} vs "
                 f"{fmt(round(bc.combo.score, 2))})")
    return [text + "."]


# ------------------------------------------------------------------ pipeline
def _dedupe(warnings) -> list[dict]:
    seen, out = set(), []
    for w in warnings:
        key = (w.get("code"), w.get("message"))
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _pipeline(raw, *, fill_defaults, trace, llm) -> dict:
    kbv = kb_version()
    # 1. validate
    v = validate(raw, fill_defaults=fill_defaults)
    sid = v.profile.get("scenario_id") if isinstance(v.profile, dict) else None
    if not isinstance(sid, str):
        sid = None
    if v.errors:
        return output.build(status="invalid_input", scenario_id=sid, validation_errors=v.errors,
                            assumptions=v.assumptions, warnings=v.notices, kb_version=kbv)
    # 2-3. description, existing systems, profile; pre-selection conflicts (profile re-derived once)
    p, pre = derive_with_conflicts(v)
    warnings: list[dict] = list(v.notices) + list(p.warnings)
    warnings += description_warnings(v, p.signals)
    ex_warn, integration = existing_outputs(p)
    warnings += ex_warn
    assumptions: list[str] = list(v.assumptions) + list(p.assumptions) + conflicts.assumptions(pre)
    if any(m.eol for m in (p.existing.matches if p.existing else ())):
        assumptions.append(f"EOL judgements use the knowledge-base date {kb_eol.KB_DATE.isoformat()} "
                           "(kb.eol.KB_DATE), not the system clock.")
    relaxed: list[str] = []
    cw, cr = _conflicts(pre, warnings)
    warnings += cw
    relaxed += cr
    hard = _hard_conflict(p, pre)
    # 4-5. core candidates and combination search
    ranked, rejections, result, empty = _search(p)
    feasible = not hard and empty is None and result is not None and result.feasible
    if not feasible:
        if not hard:     # a hard-vs-hard conflict already carries its critical warning
            warnings.append(_infeasible_warning(p, ranked, rejections, result, empty))
        near = nearest_feasible(raw, v, p, fill_defaults=fill_defaults)
        st = status.decide([], warnings, relaxed, False)
        if near:
            assumptions.append("Nearest feasible: " + "; ".join(n["message"] for n in near))
        dt = None
        if trace:
            dt = explain.decision_trace(p, ranked, rejections, result, kb_version=kbv, k=combine.T["K"])
        crit = output.sort_warnings(w for w in warnings if w.get("severity") == "critical")
        summ = None
        if crit:
            summ = "No stack is recommended: " + crit[0]["message"].rstrip(".") + "."
            if near:
                summ += " Nearest fix: " + near[0]["message"]
        return output.build(status=st, scenario_id=sid, summary=summ, warnings=_dedupe(warnings),
                            assumptions=assumptions,
                            integration_notes=integration, relaxed_constraints=relaxed,
                            nearest_feasible=near, decision_trace=dt, kb_version=kbv)
    # 5b. budget fallback (plan 7): priced with supporting-service lines, as the final estimate is
    result = combine.apply_budget(result, ranked, p, _cost_function(p))
    assumptions += budget_assumptions(result)
    best = result.best
    # 6. supporting services, cost
    sup = supporting.select(p, best.stack(), needs_managed_realtime="needs_managed_realtime" in best.flags)
    warnings += list(sup.warnings)
    # every critical gap drops a required capability: record it as relaxed (statement 4)
    relaxed += [r for r in (g.relaxed() for g in sup.gaps if g.severity == "critical") if r not in relaxed]
    assumptions += list(sup.assumptions)
    est = cost.estimate(p, best.stack(), extra_lines=sup.cost_lines(p))
    warnings += list(est.warnings)
    post = conflicts.post_checks(p, best, sup, est, ranked, existing_warnings=warnings,
                                 budget_mode=getattr(getattr(result, "budget", None), "mode", None))
    cw, cr = _conflicts(post, warnings)
    warnings += cw
    relaxed += [r for r in cr if r not in relaxed]
    warnings = _dedupe(warnings)
    # 8. status, architecture, explanations
    st = status.decide([], warnings, relaxed, True)
    arch = architecture.decide(p, best.stack(), sup.records(), status=st)
    core = explain.core_components(p, result, ranked, rejections)
    stack = dict(core)
    stack["supporting"] = sup.components()
    drivers = explain.top_drivers(explain.stack_contributions(result), 2)
    summ = explain.summary(arch.phrase, stack, p, drivers=drivers,
                           relaxed=[r[len(RELAXED_PREFIX):].strip() if r.startswith(RELAXED_PREFIX) else r
                                    for r in relaxed])
    assumptions.append(f"Architecture style {arch.style} ({arch.rule}): {arch.reason}")
    for r in relaxed:
        if r not in assumptions:
            assumptions.append(r)
    dt = None
    if trace:
        dt = explain.decision_trace(p, ranked, rejections, result, kb_version=kbv, k=combine.T["K"],
                                    extra={"architecture": arch.as_dict(), "supporting": sup.trace(),
                                           "cost_lines": est.trace()})
    return output.build(
        status=st, scenario_id=sid, summary=summ, architecture_style=arch.style, stack=stack,
        estimated_monthly_cost_usd=est.to_output(), budget_verdict=est.budget_verdict(),
        warnings=warnings, assumptions=assumptions, compliance_notes=[], integration_notes=integration,
        relaxed_constraints=relaxed, nearest_feasible=[], llm_used=False, decision_trace=dt, kb_version=kbv,
    )


def recommend_loaded(loaded: LoadedScenario, **kw) -> dict:
    """Recommend for a scenario read by ``io.load_scenarios``; load errors become invalid_input."""
    if loaded.load_error is not None:
        return output.build(status="invalid_input", scenario_id=None,
                            validation_errors=[{"field": "$", "message": loaded.load_error}],
                            warnings=list(loaded.notices), kb_version=_kb_version_safe())
    result = recommend(loaded.raw, **kw)
    if loaded.notices and not is_internal_error(result):
        have = {(w.get("code"), w.get("message")) for w in result["warnings"]}
        extra = [n for n in loaded.notices if (n.get("code"), n.get("message")) not in have]
        if extra:
            result = dict(result)
            result["warnings"] = output.sort_warnings(result["warnings"] + extra)
    return result

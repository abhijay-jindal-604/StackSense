"""Language aliases and affinity (plan section 5.5)."""
from __future__ import annotations

ALIASES = {
    "js": "javascript", "node": "javascript", "nodejs": "javascript", "node.js": "javascript",
    "ts": "typescript", "c#": "csharp", ".net": "csharp", "dotnet": "csharp", "c-sharp": "csharp",
    "golang": "go", "py": "python", "python3": "python", "c++": "cpp", "rb": "ruby",
    "objective-c": "objectivec", "objc": "objectivec",
    "postgres": "sql", "postgresql": "sql", "mysql": "sql", "t-sql": "sql", "tsql": "sql", "plsql": "sql",
    "html5": "html", "css3": "css", "flutter": "dart",
    "spring": "java", "django": "python", "flask": "python", "rails": "ruby", "laravel": "php",
}
# Frameworks typed as languages: mapped to typescript and reported as an assumption.
FRAMEWORK_ALIASES = {"react": "typescript", "vue": "typescript", "angular": "typescript"}

KNOWN_THRESHOLD = 0.6
HTML_CSS_SSG_AFFINITY = 0.8   # html/css-only team using ssg candidates (Astro, Hugo, Eleventy)
HTML_CSS_TO_JAVASCRIPT = 0.5  # directional: html/css -> javascript
SQL_SKILL_BONUS = 1           # +1 skill_fit on relational databases when 'sql' is listed
SQL_SKILL_PENALTY = -1        # -1 on non-SQL stores when 'sql' is listed

# Symmetric pairs; 1.0 for the same language is implicit.
_PAIRS = {
    ("javascript", "typescript"): 0.9, ("java", "kotlin"): 0.8, ("csharp", "java"): 0.5,
    ("csharp", "typescript"): 0.4, ("dart", "javascript"): 0.4, ("dart", "typescript"): 0.4,
    ("kotlin", "swift"): 0.4, ("python", "ruby"): 0.4, ("javascript", "php"): 0.3,
    ("go", "java"): 0.3, ("csharp", "go"): 0.3, ("cpp", "go"): 0.3,
}
AFFINITY = {}
for (_a, _b), _v in sorted(_PAIRS.items()):
    AFFINITY[(_a, _b)] = _v
    AFFINITY[(_b, _a)] = _v
AFFINITY[("html", "javascript")] = HTML_CSS_TO_JAVASCRIPT   # directional
AFFINITY[("css", "javascript")] = HTML_CSS_TO_JAVASCRIPT


def canonical(value: str) -> tuple[str, str | None]:
    """Return ``(canonical_name, assumption_or_None)`` for one input string."""
    v = str(value).strip().lower()
    if v in FRAMEWORK_ALIASES:
        return FRAMEWORK_ALIASES[v], f"team.languages value '{value}' is a framework; treated as typescript"
    return ALIASES.get(v, v), None


def normalize(values) -> tuple[list[str], list[str]]:
    """Canonicalise a language list: ``(sorted unique canonical names, assumption strings)``."""
    out, notes = set(), []
    for v in values or ():
        c, note = canonical(v)
        if c:
            out.add(c)
        if note and note not in notes:
            notes.append(note)
    return sorted(out), notes


def affinity(known: str, needed: str) -> float:
    """How well knowing ``known`` covers ``needed`` (1.0 same, 0.0 unrelated)."""
    if known == needed:
        return 1.0
    return AFFINITY.get((known, needed), 0.0)


def best_affinity(team_languages, record_languages) -> float:
    """Best affinity between the team's canonical languages and any language a record needs.
    A language-neutral record (empty list) returns 1.0."""
    if not record_languages:
        return 1.0
    return max((affinity(k, n) for k in team_languages for n in record_languages), default=0.0)


def is_known(team_languages, record_languages) -> bool:
    return best_affinity(team_languages, record_languages) >= KNOWN_THRESHOLD


def unused_language_notes(team_languages, all_record_languages) -> list[str]:
    """Assumption text for team languages no candidate uses."""
    used = set(all_record_languages)
    return [f"team.languages value '{x}' is not used by any candidate"
            for x in sorted(set(team_languages)) if x not in used and x not in ("sql", "html", "css")
            and not any(affinity(x, u) > 0 for u in used)]

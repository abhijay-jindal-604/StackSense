# StackSense

StackSense is a deterministic tech-stack recommendation engine. You give it a project description in the
challenge's input schema: product type, platforms, scale, team, budget, timeline, priorities, compliance,
data residency, deployment model and cloud preference, plus 12 optional extra fields. It returns a frontend,
backend, database, hosting and the supporting services (auth, storage, CDN, cache, queue, search, realtime,
payments, ML, CI/CD, observability and others). Each choice comes with a justification, the input fields that
drove it (`driven_by`), rejected alternatives and why they lost, and trade-offs. The output also carries a
monthly cost band checked against the budget, warnings in plain language, and every assumption made. Hard
constraints (data residency, compliance, deployment model, an explicit cloud) are never violated: if no stack
satisfies them, the result says `infeasible` and names the smallest relaxation that would work. The same
input always gives the same output. The engine uses only the Python standard library, so there is nothing to
install.

## 1. System architecture

```
scenario JSON
   |
   v
 validate ---------> invalid_input (field errors)
   |
   v
 description signals + existing-system analysis + derived profile (size class, ops capacity, ...)
   |
   v
 conflict detection ---> implied / relaxed constraints, or infeasible (hard vs hard)
   |
   v
 per layer: knowledge base candidates -> hard filters F1-F8 -> scoring (sum of named contributions)
   |
   v
 combination search (compatibility rules, synergies, managed offering per database + host)
   |
   v
 budget fallback (price the top stacks, keep the best one within budget)
   |
   v
 supporting services -> architecture style -> cost estimate -> post-selection checks
   |
   v
 explanations (from scoring contributions and filter reasons) -> status -> output JSON
```

| Module (`stacksense/`) | Role |
|---|---|
| `schema.py` | Input schema: single source of truth for validation, the web form and the report tables |
| `io.py` | Loads scenario files (single object, array, or directory); writes outputs |
| `validate.py` | Field errors, cross-field notices, defaults when `--fill-defaults` is set |
| `description.py` | Deterministic keyword signals from `project.description` (no LLM) |
| `existing.py` | Recognises existing systems, end-of-life verdicts, reuse targets and integration notes |
| `profile.py` | Derived quantities: size class, peak requests/second, ops capacity, delivery pressure, effective residency |
| `conflicts.py` | Warning catalogue (66 codes) and conflict rules with their effects |
| `filters.py` | Hard filters F1-F8 (platform, deployment, cloud, residency, compliance, ...); unknown facts fail closed |
| `scoring.py` | Scores each candidate as a sum of named contributions (weights in one table `W`) |
| `combine.py` | Searches compatible frontend + backend + database + hosting combinations; budget fallback |
| `offerings.py` | Resolves a database engine to a concrete managed offering and region on the chosen host |
| `supporting.py` | Selects supporting services from requirement triggers; reports gaps |
| `architecture.py` | Architecture style (first matching rule) |
| `cost.py` | Monthly cost band from size class, usage lines, multipliers and compliance overhead; budget verdict |
| `explain.py` | Justifications, `driven_by`, alternatives and trade-offs, and the decision trace |
| `status.py`, `output.py` | Final status; output construction and the output conformance checker |
| `engine.py` | Wires the pipeline; never raises |
| `diff.py`, `sensitivity.py` | What-if diff of two runs; one-field-at-a-time sensitivity table |
| `cli.py`, `server.py`, `web/` | Command line, local JSON API and browser UI |
| `kb/` | Knowledge base: candidates per layer, managed offerings, regions, compliance attestations, costs, end-of-life dates, keyword and existing-system patterns, and the source for every fact |

## 2. Technology used

- Python 3.10 or newer (developed and tested on Python 3.12.3). Standard library only: `json`, `argparse`,
  `http.server`, `urllib`, `unittest`, `dataclasses`, `pathlib`, `re`, `hashlib`, `copy`, `itertools`.
- Browser UI: plain HTML, CSS and JavaScript (ES2020), served by the built-in server; no build step.
- Optional: Docker (any recent version) with the included `Dockerfile` / `docker-compose.yml`
  (image `python:3.12-slim`).
- Development only, **not needed to run**: Playwright and Chrome (screenshots), a Markdown-to-PDF step for
  the report.

## 3. Prerequisites

- Python 3.10+; nothing to install (`pip` is not used).
- Windows: use `py -3 -m stacksense ...`. macOS / Linux: `python3 -m stacksense ...`.
- Any modern browser for the UI.

## 4. Setup and run

```bash
cd source
python3 -m stacksense selftest          # runs the six public scenarios and checks output conformance
python3 -m stacksense serve --open      # web UI at http://127.0.0.1:8765/
```

Docker alternative: `docker compose up --build`, then open http://127.0.0.1:8765/.
To change the port: `--port 9000`, or set `STACKSENSE_PORT` (see `.env.example`).

Run the tests: `python3 -m unittest discover -s tests`.

## 5. Run a scenario file

```bash
python3 -m stacksense run path/to/scenario.json -o outputs     # a file, an array file or a directory
python3 -m stacksense run scenarios/public -o ../outputs       # the six public outputs P1-P6
```

Each scenario is written to `<output dir>/<scenario_id>_output.json` (default output directory: `outputs/`)
and summarised on one line. An invalid scenario still gets an output file with status `invalid_input` and the
field errors. Other commands:

| Command | What it does |
|---|---|
| `validate <file\|dir> [--fill-defaults]` | Field errors and notices; exit code 1 if any scenario is invalid |
| `run ... --fill-defaults` | Fill missing optional fields with documented defaults (each listed in `assumptions`) |
| `explain <file> [--layer backend]` | Decision trace as text: ranked candidates with their top contributions, hard-filter rejections, combinations |
| `diff <a.json> <b.json> [--json]` | What changed between two scenarios or two outputs, and which changed inputs drove it |
| `kb stats` / `kb check` / `kb export -o kb.json` | Knowledge-base counts, integrity check, full export with sources |

The sensitivity table in the report comes from `python3 tools/sensitivity.py --base P2 --base P3`.

## 6. LLM features

This build has **no LLM features**. Every part of the recommendation, including parsing
`project.description`, is deterministic code and knowledge-base facts, so there is nothing to switch off and
no API key to set. The `llm` flag accepted by the API is ignored, and every output reports `"llm_used": false`.

## 7. Project structure

```
source/
  README.md, LICENSE, .env.example, Dockerfile, docker-compose.yml
  stacksense/           engine package (modules listed in section 1)
    kb/                 knowledge base and sources
    web/                browser UI (HTML, CSS, JS, bundled fonts)
  scenarios/
    public/             P1-P6 split from the official public scenarios file
    edge/               hidden-style edge scenarios H01-H36 and their expectations
  tests/                unittest suites (schema, validation, filters, scoring, public, hidden, determinism, ...)
  tools/                sensitivity table, end-of-life checker, report builder
```

## 8. Credits

- Runtime dependencies: none beyond the Python standard library.
- Fonts bundled with the UI are licensed under the SIL Open Font License (see `stacksense/web/fonts/OFL.txt`).
- Knowledge-base facts (regions, attestations, prices, end-of-life dates) come from vendor documentation,
  pricing and trust pages, and endoflife.date; every fact carries a source key with URL and access date.
  `python3 -m stacksense kb export` lists all of them, and the report has the reference list.
- No third-party APIs are called at runtime.
- AI assistance: an AI coding assistant (Claude Code) helped write code, tests and documentation under the
  author's direction; the declaration is in the report.

## Input fields and warnings

- The full input schema with types, defaults and allowed values: `GET /api/schema` while the server runs,
  or `stacksense/schema.py`.
- The warning catalogue (code, severity, fields, message): `GET /api/warnings`.

## Troubleshooting

- `cannot start server ... Address already in use`: another process holds port 8765; use `--port 9000`.
- `SyntaxError` or other errors on start: check `python3 --version` is 3.10 or newer.

## Licence

See `LICENSE`.

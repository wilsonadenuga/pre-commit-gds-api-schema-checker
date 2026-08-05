# PLAN — GDS pre-commit API Schema Checker & Uplifter

Structure follows `PLAN-Example.md`. Content is derived from `PRD.md` (v0.2 ruleset,
commit `e8bb240`). Where the template assumes a different deliverable shape, the
divergence is called out inline rather than silently dropped.

## Project Brief

Government developers are expected to follow the GDS API Technical & Data Standards,
but the standard is prose, not a machine-checkable ruleset. Compliance is therefore
caught late (at code review) or not at all. Your task: build a production-ready
**pre-commit CLI guardrail** that reads an OpenAPI 3.x spec, checks it against the
GDS + NCSC standards, and — where the spec falls short — has an AI agent propose
patches that the developer approves interactively before anything is written to disk.

The pitch is not only "pass code review". AI agents increasingly consume APIs
*directly from the OpenAPI spec* via MCP and tool-calling, so response schemas,
naming, and error envelopes are what determine whether an agent can use your API at
all. Standards are the interface to the agent economy.

This is a 2-day build ending in a stakeholder demo. It must demonstrate:
AI-augmented development, LLM tool-calling, deterministic rule engineering, CLI/UX
craft, containerisation, testing, observability, and cost monitoring.

The deliverable is a working CLI, a live 3-minute demo, and a presentation to
stakeholders on Day 2 afternoon.

## Minimum Viable Submission — Read First

If time is tight, deliver these six items first. They form a complete, demonstrable
system:

| # | Item | Maps to |
|---|---|---|
| 1 | CLI accepts an OpenAPI 3.x YAML/JSON spec and prints a findings report | Scope 7.1.1 |
| 2 | Deterministic rule engine — the 5 `GDS-*` hard rules passing | Ruleset 7.2 |
| 3 | `standards.yaml` clause map, every rule's citation resolving | Goal 2 / M2 |
| 4 | Claude agent proposing one valid JSON Patch with a quoted clause | Scope 7.1.3 |
| 5 | Interactive approval loop — `y`/`n` minimum, `.bak` backup on write | Goal 3 / M3 |
| 6 | `make demo` reproduces the run from a clean clone | M5 |

The remaining work (SigNoz dashboards, the 4 `NCSC-*` rules, the 2 `REC-*` LLM
rules, Docker, GitHub Action) strengthens the submission but must not block the core
loop. Build outward from this floor.

**Cut order if you run over:** GitHub Action → `REC-*` LLM rules → SigNoz dashboard
(fall back to console-JSON logging) → `e`dit action in the approval loop →
`NCSC-003`/`NCSC-004`. Never cut: the citation map, the `.bak` backup, or the
pre-offer patch validation.

## Full Requirements — Ceiling / Stretch From Here

1. A Typer CLI installable as `gds-api-schema-uplift` on the PATH.
2. A deterministic rule engine covering the 9 hard rules in PRD s7.2.
3. Two `REC-*` recommendation rules routed through the LLM path.
4. `standards.yaml` — hand-curated `clause_id → {section, text, url}` map.
5. LLM integration via Anthropic SDK tool-use, with `propose_patch` as a tool.
6. Prompt caching of the full GDS + NCSC corpus in the system prompt.
7. Patch validation with `openapi-spec-validator` *before* a patch is shown.
8. Interactive approval loop: `[y]es / [n]o / [e]dit / [w]hy / [q]uit`.
9. Round-trip-safe writes via `ruamel.yaml` + `jsonpatch`, with `.bak` backup.
10. OpenTelemetry traces around rule pass, agent call, and each approval decision.
11. `cost_tracker` module — per-model token counts and per-run cost, shipped as an
    OTel metric and printed at end of run.
12. Structured `subject/verb/object/context` event log as an audit trail.
13. `pytest` suite with snapshot tests against `examples/broken.yaml` and
    `examples/good.yaml`, goldens in `.gds-goldens/`.
14. Dockerfile + `Makefile` (`make setup / make demo / make test`).
15. README with quickstart and an explicit "what we cover" ruleset table.

## How You Will Be Assessed

Accumulate evidence throughout the two days — do not leave it to the demo alone.

| Criterion | What good looks like |
|---|---|
| **Detection quality** | ≥5 distinct violations flagged on `broken.yaml`; zero false positives on `good.yaml` (M1) |
| **Citation integrity** | 100% of AI suggestions carry a link/quote from a GDS or NCSC source of truth (M2). Recommendations are visibly labelled as *not* GDS-mandated |
| **Human-in-the-loop** | No file is ever modified without an explicit `y`; accept/reject/edit all work in-terminal (M3, Goal 3) |
| **Engineering rigour** | Patch validated before being offered; snapshot tests green; round-trip preserves comments and key order |
| **Operational readiness** | Telemetry lands in SigNoz; per-run cost visible; `git clone` + `make demo` replays in under 3 minutes (M4, M5) |
| **Communication** | The 3-minute narrative in PRD s6 lands; you can articulate why no RAG, why Sonnet not Opus, and which rules are conventions rather than standards |

**Leadership judgement cues** — have an answer ready for each:
- **C1, architectural trade-off:** static `standards.yaml` + cached corpus instead of
  RAG — no retrieval failure modes, revisit past ~150K tokens (PRD s9.5).
- **C2, coaching a junior on verifying AI output:** patches are schema-validated
  before a human ever sees them, and every suggestion must cite a clause; an
  uncited suggestion is a bug, not a style preference.
- **C3, scaling at 10× load:** rule pass is free and linear; cost scales only with
  LLM-path findings, which is why the LLM is capped per run and gated behind a
  cheap Haiku triage.

## Day 1 Schedule — Build

| Time | Duration | Activity | Goal |
|---|---|---|---|
| 09:30 | 30 min | Briefing and scope lock | Confirm team size, offline-vs-online demo, and the MVS floor above |
| 10:00 | 50 min | Scaffold + fixtures | `pyproject.toml`, `uv` env, `Makefile`, CLI entrypoint, `examples/broken.yaml` + `good.yaml` |
| 10:50 | 20 min | Break | |
| 11:10 | 80 min | Rule engine + clause map (parallel) | Dev A: `GDS-001`–`GDS-005` emitting `(rule_id, severity, location, snippet)`. Dev B: author `standards.yaml`, verify every citation resolves |
| 12:30 | 60 min | Lunch | |
| 13:30 | 60 min | Claude agent | Sonnet 4.6 tool-use loop with `propose_patch`; standards corpus pinned in cached system prompt |
| 14:30 | 30 min | Day 1 checkpoint | Demo current state, identify blockers, decide scope cuts |
| 15:00 | 20 min | Break | |
| 15:20 | 40 min | Wire agent into CLI + `NCSC-*` rules | Findings route to agent; validate every patch with `openapi-spec-validator` before offering |
| 16:00 | | Wrap-up | Commit working state; plan Day 2 priorities |

**Day 1 exit criteria:** CLI runs end-to-end on `broken.yaml`, printing findings and
AI suggestions with citations. Patches are *not* yet applied interactively. Cost
tracker prints a total at end of run.

**Also pull real fixtures** if there is slack: 3–4 specs from the GOV.UK API
catalogue into `examples/real-world/`, mined for "known good" and "credibly
non-compliant" cases. Do this only after the MVS floor is standing.

## Day 2 Schedule — Wrap, instrument, demo

| Time | Duration | Activity | Goal |
|---|---|---|---|
| 09:30 | 30 min | Approval loop | Rich diff view, `y/n/e/w/q`, apply via `jsonpatch` with `.bak` backup |
| 10:00 | | **Feature freeze** | No new rules or features after this point. Tests, docs, polish only |
| 10:00 | 50 min | Telemetry + Docker | OTel traces around rule pass / agent call / each decision; structured event log; Dockerfile |
| 10:50 | 20 min | Break | |
| 11:10 | 50 min | SigNoz + CLI polish | Bring up SigNoz via Compose, verify data lands, one dashboard (findings/run, cost/run, latency). Severity colours, citation formatting, summary panel |
| 12:00 | 30 min | Demo dry-run | `make demo` from a clean clone; confirm the 3-minute path in PRD s6 |
| 12:30 | 60 min | Lunch | |
| 13:30 | 90 min | Stakeholder presentations | Live demo + architecture walkthrough |
| 15:00 | 20 min | Break | |
| 15:20 | 20 min | Peer feedback | Written feedback to two peers |
| 15:40 | 20 min | Retrospective + close | Standards note, wrap |
| 16:00 | | Close | |

**Day 2 exit criteria:** the PRD s6 demo narrative runs cleanly in under 3 minutes
from `make demo`.

## When You Get Stuck

| Problem | Fix |
|---|---|
| Paralysed by scope — 11 rules and an agent and telemetry | Build one vertical slice: parse → one rule → one finding printed. Add the agent only after a deterministic finding renders. Add telemetry only after the approval loop works |
| Agent rabbit hole — prompt engineering eats the morning | 45-minute timebox. If tool-use isn't returning valid JSON Patch, hardcode a canned patch for one rule and move on; swap the real call in later without touching the rest of the system |
| Claude proposes patches that break the spec | This is expected, not a bug — it's why validation sits *before* the render step. Drop invalid patches silently and log the drop rate; a visible drop rate is a good demo beat |
| `ruamel.yaml` round-trip mangles the developer's file | Snapshot-test applied patches against `good.yaml` every build. If round-trip is still lossy, narrow to JSON-only input for the demo and say so |
| SigNoz won't come up in the venue environment | Fall back to the console-JSON logger. SigNoz becomes a nice-to-have beat, not a blocker — decide this by 11:10 on Day 2, not at 13:00 |
| False positives on a real gov spec | Do not debug live. Pin the demo to curated `broken.yaml`/`good.yaml`; real-world specs are a stretch fixture, not the demo path |
| No tests by Day 2 morning | Write three and stop: one unit test for a deterministic rule, one for patch application round-trip, one snapshot test on `broken.yaml` findings |

## Pre-submission self-check (not graded)

| # | Check | Done? |
|---|---|---|
| 1 | `git clone` + `make setup` + `make demo` works with no manual steps | [ ] |
| 2 | `broken.yaml` produces ≥5 distinct findings; `good.yaml` produces zero | [ ] |
| 3 | Every AI suggestion shows a clause quote and a gov.uk/ncsc.gov.uk link | [ ] |
| 4 | `REC-*` findings are visibly labelled as recommendations, not GDS mandates | [ ] |
| 5 | No file is written without an explicit `y`; `.bak` is created on write | [ ] |
| 6 | An invalid proposed patch is dropped, never rendered to the user | [ ] |
| 7 | Token usage and per-run cost print at end of run | [ ] |
| 8 | Traces and the event log are visible in SigNoz (or console fallback) | [ ] |
| 9 | `pytest` green; goldens in `.gds-goldens/` committed | [ ] |
| 10 | README states exactly which rules are covered and which are not | [ ] |
| 11 | Swagger 2.0 input is rejected with a clear upgrade message | [ ] |
| 12 | Demo rehearsed end-to-end at least twice, under 3 minutes | [ ] |

## Starter Scaffold

No starter scaffold exists — this repo currently contains `PRD.md`, `PLAN-Example.md`,
an empty `CLAUDE.md`, and this file. The 10:00 Day 1 slot builds the scaffold from
scratch: `pyproject.toml`, `uv` env, `Makefile`, Typer entrypoint, `examples/`.

## Stretch Goals

- GitHub Actions template running `gds-api-schema-uplift --format=github` on PR,
  emitting findings as annotations plus a summary comment (non-blocking).
- Real-world fixtures from the GOV.UK API catalogue as a second demo beat.
- Haiku 4.5 triage pass deciding whether a finding needs the Sonnet path at all.
- Cached-response mode for Claude, so the demo survives dead venue Wi-Fi.
- Vendored wheels via `uv pip download` for the same reason.

## Resources

- GDS API Technical & Data Standards — https://www.gov.uk/guidance/gds-api-technical-and-data-standards
- NCSC, Securing HTTP-based APIs — https://www.ncsc.gov.uk/collection/securing-http-based-apis
- GOV.UK API catalogue (fixtures) — https://www.api.gov.uk/#uk-public-sector-apis
- Anthropic tool use — https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Anthropic prompt caching — https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- RFC 9457, Problem Details for HTTP APIs — https://www.rfc-editor.org/rfc/rfc9457
- RFC 6902, JSON Patch — https://www.rfc-editor.org/rfc/rfc6902
- OpenAPI Specification 3.1 — https://spec.openapis.org/oas/v3.1.0.html
- Typer — https://typer.tiangolo.com
- Rich — https://rich.readthedocs.io
- SigNoz — https://signoz.io/docs
- OpenTelemetry Python — https://opentelemetry.io/docs/languages/python/

---

## Notes on divergence from `PLAN-Example.md`

Flagged rather than silently resolved — each is a decision for the team:

1. **No frontend.** The template's requirements 1 and 3 (React dashboard, GOV.UK
   design patterns, WCAG 2.2 AA, database) and its "full-stack implementation
   quality" criterion do not apply: this deliverable is a local CLI, and PRD s7.4
   explicitly rules out a hosted service or dashboard. If the assessment genuinely
   requires a frontend and a database, that is a scope conflict with the PRD that
   needs resolving before 10:00 on Day 1.
2. **Schedule capacity.** PRD s10 budgets 8h/day of task time. The template's
   clock schedule contains roughly 5h of build time on Day 1 and 2.5h on Day 2
   before presentations. The PRD plan does not fit; the cut order in the MVS
   section above exists because of this gap.
3. **Team size unresolved.** PRD s10 assigns dev A / dev B and PRD s12.1 lists team
   size as an open decision. The Day 1 parallel slot assumes two people. Solo,
   the `NCSC-*` rules and the SigNoz dashboard are the first things to go.
4. **Graduation artifacts not included.** The template references a
   manager-debrief commitment form at `../w00-programme/templates/graduation/`,
   which does not exist relative to this repo. Confirm whether that process
   applies here.
5. **Stale ruleset references in the PRD.** PRD s10 Day 1 still schedules
   "GDS-006, GDS-007, GDS-008, NCSC-001", and PRD s11 still says "ship 5-8
   hand-picked rules" — both predate the v0.2 ruleset, which is
   `GDS-001`–`GDS-005`, `NCSC-001`–`NCSC-004`, `REC-001`–`REC-002`. This plan
   uses v0.2. PRD s10 and s11 should be updated to match.
6. **Coverage target omitted.** The template sets a 70% coverage bar. The PRD
   specifies snapshot tests and goldens but no coverage number, so none is
   asserted here. Set one if it is being graded.

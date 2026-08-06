# gds-api-schema-uplift

A pre-commit guardrail for developers building GDS-standard APIs. It reads an
OpenAPI 3.x spec, checks it against the GDS + NCSC standards, and — where the
spec falls short — has a Claude agent propose fixes that you approve
interactively before anything is written to disk.

**Status: Phases 0–6 complete.** The v0.2 ruleset is fully implemented (nine
hard rules plus two recommendations), the Claude agent proposes cited patches,
the interactive approval loop writes safe backups before mutating anything, and
the tool is fully observable — traces, structured events, and per-call cost
metrics can be routed to SigNoz or captured locally as JSON.

See [PLAN.md](PLAN.md) for the phase sequence and [PRD.md](PRD.md) for scope.

## Quickstart

```bash
make setup                       # create .venv and install the CLI (editable)
make test                        # run the suite (662 tests)
make demo                        # run against examples/broken.yaml
make demo-good                   # run against examples/good.yaml
```

`make setup` uses [uv](https://docs.astral.sh/uv/) when it is on the PATH and
falls back to stdlib `venv` + `pip` when it is not.

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` if you want the AI
suggestion pass to run. Without a key the tool degrades to deterministic-only
with a note rather than failing.

## Usage

```
gds-api-schema-uplift SPEC_PATH [OPTIONS]

  --format [text|json|github]   Report format. `github` is a Phase 8 stretch
                                item; currently exits with an error rather
                                than falling back.
  --no-llm                      Deterministic pass only; never call the agent.
  --no-apply                    Report-only mode: never prompt or write to
                                disk. Implied by --format=json.
  --max-llm-calls INTEGER       Cap agent calls per run. [default: 5]
  --model TEXT                  Anthropic model id. [default: claude-sonnet-4-6]
  --effort [low|medium|high|max]  Agent reasoning effort. [default: low]
  --standards PATH              Override the standards.yaml path.
```

Exit codes: `0` clean (after any approvals), `1` findings remain, `3`
operational failure.

### Interactive mode

By default, if the agent proposes patches, the CLI walks you through each one:

```
Apply this patch? [y]es / [n]o / [w]hy / [q]uit
```

- `y` — applies the patch. A `.bak` is written next to your spec before the
  first mutation of the run; subsequent approvals mutate in place.
- `n` — skip this finding, move on.
- `w` — show the full standards clause the finding cites, then re-prompt.
- `q` — leave the rest untouched. Any writes already made stand.

Pass `--no-apply` (or use `--format=json`) to skip the loop entirely and print
a report.

### Cost

The agent pass runs by default and costs money. Set `GDS_UPLIFT_NO_LLM=1` (or
pass `--no-llm`) to disable it — in CI, on shared runners, or anywhere a stray
`ANTHROPIC_API_KEY` could turn a check into a bill. The test suite sets this
automatically via `tests/conftest.py`, and a second guard makes constructing a
real client fail loudly inside tests.

Measured on `examples/broken.yaml` with `claude-sonnet-4-6` at `--effort low`:
the first suggestion costs about **$0.015** (it writes the prompt cache), each
subsequent one about **$0.009** (it reads it). A default 5-call run is roughly
$0.05. Per-run total and cache hit ratio print at the end — a hit ratio of zero
across a multi-finding run means caching has stopped working and costs ~10× more
than it should.

Credentials resolve the usual way — `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
or an `ant auth login` profile.

## What is covered

The v0.2 ruleset — 9 hard rules cited directly to GDS or NCSC clauses, plus 2
recommendations cited to external conventions.

| Rule | Check | Severity | Anchor |
|---|---|---|---|
| `GDS-001` | Every declared server URL uses `https://` | error | GDS Security + service-manual/using-https |
| `GDS-002` | Date/time-named string properties declare `format: date`/`date-time`/`time` | warning | GDS (explicit) |
| `GDS-003` | A version segment appears in the URI path (or in every server URL) | warning | GDS (explicit) |
| `GDS-004` | Response bodies are JSON (`application/json` or a `+json` type) | warning | GDS (explicit) |
| `GDS-005` | Error responses use RFC 9457 problem details on standard status codes | warning | GDS (explicit) |
| `NCSC-001` | No `http basic` and no bare `apiKey` auth schemes | error | GDS + NCSC §2 |
| `NCSC-002` | Auth declared for every operation (deny by default) | error | NCSC §2 |
| `NCSC-003` | Request bodies set `additionalProperties: false` | warning | NCSC §4 |
| `NCSC-004` | Rate limiting acknowledged — `429` response defined on every operation | suggestion | NCSC §5 |
| `REC-001` | Paths use kebab-case, plural nouns *(recommendation)* | suggestion | REST convention + MS API Guidelines |
| `REC-002` | Operations declare a meaningful summary and description *(recommendation)* | suggestion | OpenAPI conventions |

**`REC-*` rules are conventions with no GDS or NCSC anchor.** They are cited to
external references and are rendered as explicitly not GDS-mandated. This
distinction is carried in the data (`authority: recommendation` in
`standards.yaml`), not in the renderer, so it survives every output format.

**Three rules check more than their clause literally requires**, recorded in
`standards.yaml` so nobody is told GDS mandates something it does not: `GDS-005`
(the clause requires consistent documented error codes, not RFC 9457
problem+json), `NCSC-004` (the clause requires throttling and never mentions
HTTP 429), and `GDS-003` (the GDS text is conditional). Their severities are set
accordingly.

Two parts of the PRD wording are not machine-checkable from an OpenAPI document
and are deliberately out of scope, documented in the relevant modules:
GDS-001's "TLS 1.2+" and GDS-004's "UTF-8 encoding".

Version policy (PRD s7.3): OpenAPI 3.1 passes clean, 3.0 passes with an
upgrade note, Swagger 2.0 is refused with exit code 3 rather than reported as
clean.

## Observability

Every run emits OpenTelemetry traces and metrics plus a structured JSONL event
log — sinks that work with or without a running collector, so a demo does not
depend on infrastructure holding up.

- **Traces.** Root span `gds-uplift.run` per invocation, child spans around
  `rules.deterministic_pass`, `agent.pass`, and `rules.recheck_after_approval`.
- **Metrics.** `gds_uplift.llm.cost_usd` counter per agent pass, tagged with
  model, tokens in/out, and cache read/write counts.
- **Events.** `subject / verb / object / context` rows for every meaningful
  moment — `RULES/COMPLETED/PASS`, `USER/APPROVES/FINDING`, and so on. Written
  to `gds-uplift-events.jsonl` in the working directory (gitignored) and
  attached as span-events for the trace-viewer side.

By default all three go to stdout / the local JSONL file. Set
`GDS_UPLIFT_OTEL_ENDPOINT=http://localhost:4318` (SigNoz default) to ship
traces and metrics to a real collector — see [signoz/README.md](signoz/README.md)
for the runbook and suggested dashboards. Set `GDS_UPLIFT_OTEL_DISABLED=1` to
turn telemetry off entirely (tests default to this).

## Repository layout

```
src/gds_api_schema_uplift/
  contracts.py             Finding / Patch / Suggestion / Severity / Authority
  loader.py                spec load via ruamel round-trip, plus the version gate
  standards.py             standards.yaml schema, validation, static clause lookup
  patching.py              THE VALIDATION GATE: apply to a copy, re-validate, diff
  cost.py                  per-model pricing, cache-aware token accounting
  telemetry.py             OTel + JSONL event log; console-JSON fallback default
  approval.py              interactive y/n/e/w/q loop; safe backup + write path
  agent/
    prompts.py             cached system prompt, corpus rendering
    tools.py               retrieve_clause / propose_patch schemas + validation
    client.py              tool-use loop, gate integration, call budget
  report.py                text and JSON renderers
  cli.py                   Typer entrypoint
  rules/
    _registry.py           registration, lookup, and the deterministic pass
    _traversal.py          shared spec walking and JSONPath construction
    gds_00N_*.py           GDS-001..005: one module per rule
    ncsc_00N_*.py          NCSC-001..004
    rec_00N_*.py           REC-001..002 (recommendations)
standards.yaml             the clause corpus
signoz/README.md           runbook for pointing telemetry at SigNoz
examples/
  broken.yaml              one unambiguous violation per v0.2 rule
  good.yaml                compliant; zero findings; the round-trip fixture
tests/                     ~660 tests across contracts, rules, agent, approval,
                           telemetry, CLI, and fixture quality
```

Rule modules and their tests are named `<rule_id>_<what_it_checks>`, so a
filename says what the rule does while the directory still sorts by rule id.
Test modules are named for the subject under test rather than the build phase
that introduced them.

## Not in scope

No IDE plugin, no hosted service, no auth, no multi-tenancy, no auto-apply
mode, and no AsyncAPI/GraphQL/gRPC support. See PRD s7.4.

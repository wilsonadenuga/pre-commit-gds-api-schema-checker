# PRD — GDS pre-commit API Schema Checker & Uplifter

**Working name:** `gds-api-schema-uplift`
**Status:** 2-day build, stakeholder demo at the end
**Sources of truth** (what the tool checks against and cites in every finding):
- GDS API Technical & Data Standards — https://www.gov.uk/guidance/gds-api-technical-and-data-standards
- NCSC — Securing HTTP-based APIs — https://www.ncsc.gov.uk/collection/securing-http-based-apis

**Test-fixture inventory** (a directory of real UK gov APIs — not a standard, but the source of real-world OpenAPI specs we validate the tool against):
- GOV.UK API catalogue — https://www.api.gov.uk/#uk-public-sector-apis

**Additional references** (inform judgement and rule construction; not the source of citations shown to the developer):
- OpenAPI Specification 3.1
- RFC 9110 — HTTP Semantics
- RFC 9457 — Problem Details for HTTP APIs
- OAuth 2.1 (draft)
- OWASP REST Security Cheat Sheet
- Microsoft REST API Guidelines

The three-tier split matters: findings must cite a **source of truth** so a developer can trace "why must I fix this?" back to gov.uk or ncsc.gov.uk. The additional references shape *how* we write the rule and *how* the AI proposes the fix. The fixture inventory is where we find real gov API specs to test against.

---

## 1. One-line summary

A pre-commit guardrail for developers building GDS-standard APIs: it reads an OpenAPI/Swagger spec, checks it against the GDS + NCSC standards, and — where the spec falls short — an AI agent proposes fixes that the developer approves interactively before anything is written to disk.

## 2. Problem

Government developers are expected to follow the GDS API standard, but the standard is a prose document, not a machine-checkable ruleset. Today, compliance is checked either:

- **too late** — flagged at code review, after the work is done, or
- **not at all** — reviewer misses it, and the API ships out of standard.

There is no fast, local, developer-facing feedback loop between "I'm writing my API" and "reviewer catches a violation." The result is expensive rework, inconsistent APIs across departments, and a standard that lives on gov.uk but not in the codebase.

## 2.1 Why this matters more now — AI agents are consumers too

An API's users are no longer only humans and their bespoke integrations. AI agents — via MCP servers, function calling, and tool-use frameworks — increasingly discover and invoke APIs *directly from the OpenAPI spec*. That changes the stakes of compliance:

- **Tool definitions are generated from the spec.** Missing response schemas, verbs-in-paths, or ad-hoc error shapes produce garbled tool definitions — the agent picks the wrong endpoint or misconstructs the call.
- **Naming is what the agent reads.** A human infers `usrLst` means "user list"; an LLM tokenises it as noise and mis-routes. Kebab-case plural nouns and meaningful `summary`/`description` fields are literally the tokens the agent uses to decide which endpoint to invoke.
- **Consistent error envelopes make agent retry/escalate logic deterministic.** RFC 9457 problem+json is a schema check; ad-hoc error strings force pattern-matching — unreliable and token-hungry.
- **Non-standard APIs cost more every call.** More tokens in the system prompt to explain the API to the agent, more retries when things go wrong, more human intervention when auto-generated clients fail.

So the pitch is not just "pass code review" — it's **standards are the interface between your service and the agent economy**. Complying today is what makes your API cheaply consumable by every LLM-driven client tomorrow.

## 3. Users & primary use case

**Primary user:** a developer inside a UK government department, building an HTTP/REST API that must comply with the GDS API standard.

**Primary use case:** the developer has just finished a piece of work on their API and is about to `git commit`. They run:

```
gds-api-schema-uplift openapi.yaml
```

The tool prints a compliance report, walks the developer through each finding with an AI-proposed fix, and applies only the changes the developer approves. Push proceeds with a spec that is closer to standard than it was 30 seconds ago.

**Secondary users (later phases):** code reviewers, API governance leads, procurement/assurance teams who want an audit trail of compliance runs.

## 4. Goals

1. **Demo-ready in 2 days.** A believable end-to-end run against a real (deliberately broken) sample OpenAPI spec.
2. **Trustworthy suggestions.** Every AI suggestion cites the specific GDS or NCSC clause it is based on.
3. **Human-in-the-loop is non-optional.** The tool never modifies a file without explicit `y` from the developer.
4. **Observable and cost-aware.** Every run emits telemetry; per-run LLM cost is visible on a dashboard.

**Explicit non-goals for this build:**

- Fixing the source code that *generates* the spec (annotations in Spring/FastAPI/etc.)
- Multi-tenant SaaS, hosted dashboard, or billing
- IDE extension
- Full coverage of the GDS standard — the MVP encodes ~9 hard rules + 2 recommendations
- Blocking git hooks (only informational output; blocking is a policy decision for later)

## 5. Success metrics

- **M1 — Detection.** Tool flags >= 5 distinct violations on the sample broken spec, with zero false positives on the sample compliant spec.
- **M2 — Citation.** 100% of AI suggestions include a link/quote from the GDS or NCSC source.
- **M3 — Approval UX.** Developer can accept, reject, or edit each suggestion inside the terminal without leaving the tool.
- **M4 — Observability.** Every run emits telemetry to SigNoz; per-run LLM cost is visible on a dashboard.
- **M5 — Reproducibility.** A stakeholder can `git clone` + `make demo` and replay the demo in under 3 minutes.

## 6. Demo narrative (3 minutes)

1. **Set the scene.** "I'm a gov developer. I've just added a new endpoint. Here's my `openapi.yaml`." Show the spec.
2. **Run the tool.** `gds-api-schema-uplift openapi.yaml`. Deterministic rules find 3 violations instantly. Claude adds 2 semantic suggestions.
3. **Walk the loop.** Terminal shows finding #1 with the GDS clause quoted and a proposed diff. Press `y`. Show it applied. Press `n` on one. Press `e` to edit another.
4. **Show the tail.** Open SigNoz — the run's traces, event log, and LLM cost are all there.
5. **Land the story.** "This is shift-left for API standards: catch the violation before code review, cite the clause, and prove — with telemetry — that the check actually ran."

## 7. Scope (MVP)

### 7.1 What the tool does

1. Accepts an OpenAPI 3.x YAML or JSON spec on the CLI.
2. Runs a **deterministic rule pass** against ~9 hard rules + 2 recommendations.
3. For findings flagged as "needs judgement," calls a **Claude agent** that:
   - looks up the rule's pre-declared citation (from a static `standards.yaml`),
   - proposes a concrete patch to the spec,
   - explains *why*, quoting the clause.
4. Presents each finding to the developer as an interactive prompt: `[y]es apply / [n]o skip / [e]dit / [w]hy / [q]uit`.
5. Writes approved patches back to the spec file (with a `.bak` backup).
6. Emits telemetry throughout, and prints a per-run LLM cost summary at the end.

### 7.2 Initial ruleset (v0.2)

Every hard rule cites a specific GDS or NCSC clause (verified against the source text). Two conventions with no source-of-truth anchor — kebab-case paths and meaningful operation summaries — are kept but demoted to `REC-` recommendations, cited to external references.

| ID | Rule | Severity | Anchor | Type |
|---|---|---|---|---|
| GDS-001 | HTTPS-only, TLS 1.2+ | error | GDS Security + service-manual/using-https | deterministic |
| GDS-002 | Dates and times are ISO 8601 strings | warning | GDS (explicit) | deterministic |
| GDS-003 | Versioning declared in URI path (e.g. `/v1/...`) | warning | GDS (explicit) | deterministic |
| GDS-004 | JSON responses, UTF-8 encoding | warning | GDS (explicit) | deterministic |
| GDS-005 | Errors consistent, mapped to standard HTTP codes, documented (problem+json recommended) | warning | GDS (explicit) | deterministic |
| NCSC-001 | No `http basic` and no bare `apiKey` auth schemes | error | GDS + NCSC §2 | deterministic |
| NCSC-002 | Auth scheme declared; every operation covered ("deny by default") | error | NCSC §2 | deterministic |
| NCSC-003 | Request bodies set `additionalProperties: false` | warning | NCSC §4 | deterministic |
| NCSC-004 | Rate limiting acknowledged — `429` response defined on public endpoints | suggestion | NCSC §5 | deterministic |
| REC-001 | Paths use kebab-case, plural nouns *(recommendation — not in GDS)* | suggestion | REST convention + MS API Guidelines | LLM |
| REC-002 | Every operation has a meaningful `summary` and `description` *(recommendation)* | suggestion | OpenAPI conventions | LLM |

### 7.3 Compatibility notes

- **OpenAPI 3.0 and 3.1 are both accepted.** 3.1 is recommended (aligns with JSON Schema 2020-12); 3.0 specs pass through the same rule engine with a soft "consider upgrading" note. **OpenAPI/Swagger 2.0 is rejected** with a message to upgrade — too many rules can't be expressed against 2.0 cleanly.
- **OAuth 2.1 is a recommendation, not a mandate.** Rule NCSC-001 checks that *some* auth scheme is declared; specs using OAuth 2.0 pass. When the AI proposes an auth-related change, it should reach for OAuth 2.1 patterns but must not fail a spec purely for using OAuth 2.0.
- **RFC 9457 (problem+json) is the target error shape.** Older specs using RFC 7807 pass (7807 is the direct predecessor); ad-hoc error shapes trigger GDS-005.

### 7.4 What we deliberately don't build

- No IDE plugin.
- No GitHub App / PR bot (a GitHub Action *template* is a stretch goal, not core).
- No hosted service, no auth, no multi-tenant.
- No auto-apply mode — every fix requires human `y`.
- No support for AsyncAPI, GraphQL, gRPC — OpenAPI 3.x only.

## 8. Architecture

```
   openapi.yaml ------+
   standards.yaml ----+---> +--------------------------+
                            |  CLI (Python + Typer)    |
                            |                          |
                            |  1. Parse spec           |
                            |  2. Deterministic rules  |---> findings[]
                            |  3. LLM rules (agent)    |
                            |  4. Approval loop        |
                            |  5. Apply patches        |
                            +--------+-----------------+
                                     |
        +----------------------------+----------------------------+
        |                            |                            |
        v                            v                            v
+---------------+          +-------------------+         +-----------------+
| Rule engine   |          | Claude agent      |         | OpenTelemetry   |
| (Python dict  |          | (Anthropic SDK,   |         | SDK  -> SigNoz  |
|  of checkers, |          |  tool use,        |         |  (traces, logs, |
|  loads clause |          |  full standards   |         |   cost/run)     |
|  refs from    |          |  in cached        |         |                 |
|  standards.   |          |  system prompt)   |         |                 |
|  yaml)        |          |                   |         |                 |
+---------------+          +-------------------+         +-----------------+
```

**Data flow, one finding:**

1. Rule engine emits a finding: `rule_id`, `severity`, `location` (JSONPath into the spec), `snippet`.
2. If the rule is LLM-type or the finding needs a suggestion, the agent is called.
3. Agent receives: the finding, the rule's pre-declared citation clause (looked up in `standards.yaml`), and the full standards text pinned in the cached system prompt.
4. Agent proposes a **JSON Patch (RFC 6902)** against the spec, plus a rationale and clause quote.
5. Patch is validated against the OpenAPI schema *before* being shown to the user (invalid patches are dropped, not offered).
6. CLI renders the diff with `Rich`, waits for user input, applies on `y`.

**Why this shape:**
- Deterministic layer is fast, free, and reproducible — the bulk of the value.
- LLM is used only where judgement is needed — keeps cost bounded and results trustworthy.
- Static clause map + cached standards text grounds every AI suggestion in a pre-declared quote — no retrieval failure modes, no vector-store dependency.
- OpenTelemetry to SigNoz makes the tool itself observable: an API-quality tool that eats its own dog food.

## 9. Technology stack & tools

Choices are picked as best-fit for a 2-day build with Claude in the loop — not as generic "best tool" answers.

### 9.1 Language & runtime

| Choice | Reason |
|---|---|
| **Python 3.12** | Dense RAG/agent ecosystem; Claude generates domain code faster in Python than in Go for the risky bits (spec editing, agent loop, RAG glue). Revisit Go only if this becomes a distributed CLI product. |
| **`uv`** (Astral) | Modern package/venv manager, dramatically faster than pip. `uv sync` and `uv run` make setup crisp. |

### 9.2 CLI + UX

| Choice | Reason |
|---|---|
| **Typer** | Type-hint-driven Click wrapper; auto-help, auto-validation, less boilerplate. |
| **Rich** | Colour output, syntax highlighting, diff rendering, interactive prompts. The demo *looks* good because of Rich. |
| **`prompt_toolkit`** (for the `e`dit action) | Inline multi-line edit of a proposed patch without leaving the terminal. |

### 9.3 OpenAPI handling

| Choice | Reason |
|---|---|
| **`ruamel.yaml`** | Round-trip YAML that preserves comments and order — essential when we write patches back to a developer's file. |
| **`openapi-spec-validator`** | Validates spec pre- and post-patch. Fast fail if a proposed patch breaks the spec. |
| **`jsonpatch`** | Applies RFC 6902 patches — the safest, smallest edit primitive. |

### 9.4 AI layer

| Choice | Reason |
|---|---|
| **Claude Sonnet 4.6** (`claude-sonnet-4-6`) as the primary agent model | Fast enough for a live demo, more than capable enough for JSON Patch + rationale. Opus is overkill here. |
| **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) for cheap classification | Deciding whether a finding needs the LLM path at all, or extracting snippets. Cost-aware model selection. |
| **Anthropic SDK** (`anthropic` Python) | Native, mature, supports the features we need. |
| **Prompt caching** | Cache the GDS + NCSC standard text as a large system prompt (~50-100 KB). Non-negotiable cost win when running across many findings. |
| **Tool use** | Two tools exposed to the model: `retrieve_clause(query)` and `propose_patch(finding, patch, rationale, citation)`. Keeps outputs structured. |

### 9.5 Standards corpus (no RAG in MVP)

| Choice | Reason |
|---|---|
| **`standards.yaml`** — hand-curated file mapping each `clause_id` to `{section, text, url}` | Deterministic citation lookup by rule ID; no retrieval failure modes. |
| **Full standards text pinned in the Claude system prompt, with prompt caching** | GDS + NCSC corpus is ~25-40K tokens — fits comfortably in context. Caching amortises cost across findings within a run. |

We deliberately do not use a vector store or RAG for this MVP. The standards corpus is small enough to fit in-context, every rule already knows its own citation, and a static lookup is more reliable than semantic retrieval in a live demo. RAG is a Phase-2 concern (see s13) — added when the corpus grows past ~150K tokens (e.g. adding NHS standards, full MS API Guidelines, or internal enterprise standards).

### 9.6 Observability & FinOps

| Choice | Reason |
|---|---|
| **OpenTelemetry Python SDK** | Traces around rule pass, agent call, and each approval decision. |
| **SigNoz** (Docker Compose) | Open-source observability stack; one-command bring-up. |
| **`cost_tracker`** module | Counts input/output tokens per model, prints running cost during the run, ships cost as an OTel metric. |
| **Structured event log** — `subject/verb/object/context` per row | E.g. `USER / APPROVES / FINDING / {rule_id, ...}`. Reviewable audit trail. |

### 9.7 Packaging & delivery

| Choice | Reason |
|---|---|
| **Docker** | Reproducible run environment. |
| **`pyproject.toml`** (installable via `uv tool install .` or `pipx`) | Real CLI install path — `gds-api-schema-uplift` on the PATH. |
| **`Makefile`** with `make setup / make demo / make test` targets | Single entrypoint for stakeholders. |
| **Vendored wheels via `uv pip download`** | Demo survives shaky venue Wi-Fi. |

### 9.8 Testing

| Choice | Reason |
|---|---|
| **`pytest`** | Standard. |
| **Snapshot tests** on the sample broken/good specs | Guards against regressions in rule output and patch shape. |
| **A `.gds-goldens/` directory** with expected findings JSON | Diff-friendly, reviewable in PRs. |

### 9.9 Stretch — CI integration

| Choice | Reason |
|---|---|
| **GitHub Actions template** — runs `gds-api-schema-uplift --format=github` on PR | Emits findings as GitHub annotations + summary comment. Non-blocking to start. |

### 9.10 Explicitly not chosen (and why)

- **Go** — would help distribution but slows the RAG/agent build. Revisit post-hackathon.
- **Spectral** — the industry-standard OpenAPI linter, but it's TypeScript. Subprocess-ing it from Python adds friction for ~11 rules. Adopt in phase 2 for full GDS coverage.
- **LangChain / LlamaIndex** — heavier than we need; direct Anthropic SDK is cleaner and easier to reason about.
- **Opus 4.7** as the default — capability we don't need at latency we can't afford in a live demo.
- **Any vector DB / RAG (ChromaDB, Pinecone, Weaviate, etc.)** — the standards corpus fits in-context and every rule has a pre-declared citation. RAG would add retrieval failure modes for no benefit. Revisit when the corpus grows past ~150K tokens.

## 10. Two-day build plan

Aggressive but realistic with two people and Claude in the loop. Times are budgeted, not padded — cut features before running over.

### Day 1 — Build

| Time | Task | Owner hint |
|---|---|---|
| 0h - 1h | Scaffold repo: `pyproject.toml`, `uv` env, `Makefile`, CLI entrypoint, sample specs (`examples/broken.yaml`, `examples/good.yaml`) | either |
| 0h - 1h | Pull 3-4 real specs from the GOV.UK API catalogue into `examples/real-world/` — mine them for "known good" and "credibly non-compliant" fixtures | either |
| 1h - 3h | Deterministic rule engine: 5 rules (GDS-001 to GDS-005) with `(rule_id, severity, location, snippet)` finding shape | dev A |
| 1h - 3h | Author `standards.yaml`: distil GDS + NCSC clause text, tag each with `{clause_id, section, url}`; validate every rule's citation resolves | dev B |
| 3h - 5h | Claude agent (Sonnet 4.6): tool-use loop with `propose_patch`; full standards text pinned in the cached system prompt | dev B |
| 3h - 5h | Add remaining rules (GDS-006, GDS-007, GDS-008, NCSC-001) | dev A |
| 5h - 7h | Wire agent into CLI: findings -> agent for LLM-type or suggestion mode; validate every proposed patch with `openapi-spec-validator` before offering | either |
| 7h - 8h | End-of-day integration: run on `broken.yaml`, verify findings + raw suggestions land; commit + push | pair |

**Day 1 exit criteria:** CLI runs end-to-end, prints findings and suggestions, does not yet apply patches interactively. Cost tracker prints total at end of run.

### Day 2 — Wrap, instrument, demo

| Time | Task | Owner hint |
|---|---|---|
| 0h - 2h | Interactive approval loop (Rich + `prompt_toolkit`): `y/n/e/w/q`, diff view, apply via `jsonpatch` with `.bak` backup | dev A |
| 0h - 2h | OpenTelemetry: traces around rule pass, agent call, each approval decision; structured event log | dev B |
| 2h - 3h | SigNoz stack up (Docker Compose), verify data lands, build one demo dashboard (findings/run, cost/run, latency) | dev B |
| 2h - 3h | Polish CLI output: severity colours, clause citation formatting, final summary panel | dev A |
| 3h - 4h | Dockerfile + `make demo` target that spins up SigNoz + runs the CLI against `broken.yaml` | either |
| 4h - 5h | **Stretch:** GitHub Actions template that runs the CLI on PR and comments findings | either |
| 5h - 6h | README + demo runbook (see s6). Rehearse the demo end-to-end twice. | pair |
| 6h - 7h | Buffer for the thing that always breaks | pair |
| 7h - 8h | Final rehearsal + submit | pair |

**Day 2 exit criteria:** demo narrative (s6) runs cleanly in under 3 minutes from `make demo`.

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM latency makes the demo drag | high | Sonnet 4.6 (not Opus); prompt caching; cap LLM findings shown in demo path to 2 |
| Claude proposes patches that break the spec | medium | Validate patch with `openapi-spec-validator` before offering it; drop the finding if invalid |
| GDS standard is too vague to encode | medium | Ship 5-8 hand-picked rules only; explicit "here's what we cover" list in the README |
| SigNoz stack won't come up in venue env | medium | Console-JSON fallback logger; SigNoz becomes a "nice-to-have" beat, not blocking |
| False positives erode stakeholder trust in the demo | high | Curate `broken.yaml` so every finding is unambiguous; snapshot-test until output is stable |
| `ruamel.yaml` round-trip mangles the spec | low-medium | Snapshot-test applied patches against the good spec every build |
| Cost blows past budget in demo | low | Cap LLM calls per run (max 5); print running cost during the run |
| Wi-Fi flakes at demo venue | medium | Vendored wheels via `uv pip download`; optional cached-response mode for Claude |

## 12. Open decisions

1. **Team size?** Plan above assumes two devs; more means we can pull the GitHub Action stretch into core.
2. **Confirm Sonnet 4.6 as default?** Cheaper, faster, sufficient. If a stakeholder asks "why not Opus?", the answer is cost + demo latency.
3. **Offline vs. online demo?** If venue Wi-Fi is unreliable, we need vendored wheels + cached Claude responses. Decide day 0.
4. **Surface the GitHub Action in the demo,** or keep it as a "here's what next" slide?

## 13. Beyond the MVP

Ordered by likely value, not likely effort.

1. **Source-code fix mode** for Spring / FastAPI / NestJS — propose the annotation change, not just the spec change.
2. **GitHub Action + PR suggestion comments** — moves the guardrail into team-visible territory.
3. **Spectral adoption** — replace the hand-rolled rule engine with a versioned Spectral ruleset for full GDS coverage.
4. **Versioned rulesets as packages** — `gds-ruleset@1.2.0`, so teams can pin and standards can evolve without a tool release.
5. **Governance dashboard** — aggregate audit reports across a department's repos; give API governance leads a real view.
6. **Additional standards** — NHS API standards, internal enterprise standards; ruleset shape stays the same.
7. **RAG for the standards corpus** — add ChromaDB + `sentence-transformers` when the corpus grows past ~150K tokens (adding NHS API standards, full MS API Guidelines, internal enterprise standards). The `standards.yaml` structure we already have becomes the source of chunks.
8. **Go rewrite of the CLI shell** — if adoption grows and single-binary distribution matters more than iteration speed.
9. **IDE extension** — inline warnings as the spec is edited.

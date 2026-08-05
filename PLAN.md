# PHASED IMPLEMENTATION PLAN — `gds-api-schema-uplift`

Implementation sequencing for the project defined in `CLAUDE.md` (requirements, MVS,
cut order) against the architecture in `PRD.md` s8 and the stack decisions in s9.

Phases are **dependency-ordered vertical slices**, not calendar blocks. Each has a
single goal, an explicit exit criterion, and the `CLAUDE.md` requirement numbers it
discharges. `CLAUDE.md`'s clock schedule still governs the two days; the mapping
back to it is in "Reconciling phases with the two-day schedule" at the foot.

**Architectural invariants** — these hold in every phase and are never traded for speed:

| Invariant | Source | Consequence for sequencing |
|---|---|---|
| A patch is schema-validated *before* a human sees it | PRD s8 flow step 5 | The validation gate ships in the same phase as the first generated patch, never later |
| No write without an explicit `y` | Goal 3, req 8 | The apply path cannot exist before the approval loop; there is no auto-apply code path to "add a prompt to later" |
| Every finding carries a pre-declared citation | Goal 2 / M2, req 4 | `standards.yaml` precedes the agent, not the reverse |
| Citation lookup is static, not retrieved | PRD s9.5, s9.10 | No vector store, no embedding model, at any phase |
| Writes preserve comments and key order | req 9 | `ruamel.yaml` round-trip is proven in Phase 1, before anything writes |

---

## Phase 0 — Contracts and scaffold

**Goal:** make the two workstreams (rules, agent) independently buildable by fixing
the data contract between them first.

This phase exists because PRD s8's data flow has exactly one interface — the finding —
and if it is not pinned before parallel work starts, the rule engine and the agent
will be integrated twice.

**Deliverables**

- `pyproject.toml` with the s9 dependency set; `uv` env; `uv tool install .` puts
  `gds-api-schema-uplift` on the PATH.
- `Makefile` with `setup`, `test`, `demo` targets (bodies may be stubs).
- Typer entrypoint accepting a spec path, `--format`, `--no-llm`, `--max-llm-calls`.
- **The `Finding` contract**, frozen: `rule_id`, `severity`
  (`error|warning|suggestion`), `location` (JSONPath into the spec), `snippet`,
  `clause_id`, `rule_type` (`deterministic|llm`).
- **The `standards.yaml` schema**, frozen: `clause_id → {section, text, url}`.
- **The `Patch` contract:** RFC 6902 op list + `rationale` + `clause_quote`.
- Fixtures `examples/broken.yaml` and `examples/good.yaml`, hand-authored so every
  v0.2 rule has exactly one unambiguous violation in `broken.yaml` and zero in
  `good.yaml`.

**Covers:** req 1, req 14 (partial)

**Exit criterion:** `make setup` succeeds from a clean clone; the CLI runs, loads
both fixtures, and prints an empty findings report without error.

**Note on fixture authoring:** curate these deliberately. M1 (zero false positives
on `good.yaml`) and the "false positives erode trust" risk in PRD s11 are both won or
lost here, not in the rule code.

---

## Phase 1 — Deterministic rule engine (`GDS-*`)

**Goal:** the free, fast, reproducible layer that PRD s8 calls "the bulk of the value".

**Deliverables**

- Spec loader via `ruamel.yaml` round-trip; JSON accepted too.
- **Version gate:** OpenAPI 3.1 clean, 3.0 accepted with a "consider upgrading"
  note, Swagger 2.0 rejected with an upgrade message (PRD s7.3).
- Rule registry — a dict of `rule_id → checker(spec) -> list[Finding]`, so adding a
  rule is one function plus one registry line.
- `GDS-001` HTTPS-only/TLS 1.2+, `GDS-002` ISO 8601, `GDS-003` URI-path versioning,
  `GDS-004` JSON/UTF-8, `GDS-005` consistent documented errors.
- Rich findings report: severity colours, JSONPath location, snippet.
- **Round-trip proof test:** load `good.yaml`, write it back unmodified, assert
  byte-identical. This de-risks req 9 before any patch code exists.

**Covers:** req 2 (5 of 9), req 9 (round-trip half)

**Exit criterion:** `broken.yaml` yields ≥5 findings, `good.yaml` yields zero, and
the round-trip test is green.

---

## Phase 2 — Standards corpus and citation integrity

**Goal:** every rule can prove where it comes from. Runs in parallel with Phase 1.

**Deliverables**

- `standards.yaml`: distilled GDS + NCSC clause text, each entry
  `{clause_id, section, text, url}`, anchored per the PRD s7.2 table.
- `resolve_clause(clause_id)` — static dict lookup, no retrieval.
- **Citation integrity test:** every `rule_id` in the registry maps to a
  `clause_id` that resolves, and every resolved entry has a non-empty `text` and a
  `gov.uk` or `ncsc.gov.uk` URL. A rule with an unresolvable citation fails the
  build.
- `REC-*` entries carry a distinct `authority: recommendation` field so the renderer
  can label them as not GDS-mandated.

**Covers:** req 4, req 15 (input to the coverage table)

**Exit criterion:** all 11 v0.2 `clause_id` entries resolve to non-empty `text` and a
`gov.uk`/`ncsc.gov.uk` URL, and every rule *currently in the registry* maps to one
that resolves; the findings report shows a clause quote and URL for every
deterministic finding.

The registry only holds the 5 `GDS-*` rules at this point, so the registry-walk
assertion cannot cover all 11 rules until Phase 5b closes. The corpus-side assertion
(all 11 entries resolve) can and does hold here — which is what lets Phases 1 and 2
stay genuinely parallel.

**Why the `authority` field:** the "citation integrity" assessment criterion requires
`REC-*` findings be visibly not-GDS. Carrying that in data rather than in renderer
`if` statements keeps it true for every output format, including the stretch
GitHub Action.

---

## Phase 3 — Claude agent and the patch pipeline

**Goal:** a validated, cited patch proposal for one finding. Depends on Phases 0–2.

**Deliverables**

- Anthropic SDK client, Sonnet 4.6 (`claude-sonnet-4-6`).
- **Prompt caching:** full GDS + NCSC corpus as a `cache_control` system block
  (~25–40K tokens per PRD s9.5). Assert cache hits on calls 2..n of a run.
- **Tool use**, two tools per PRD s9.4: `retrieve_clause(clause_id)` — a static
  lookup into Phase 2, and `propose_patch(finding, patch, rationale, citation)`.
- **The validation gate:** apply the proposed patch to an in-memory spec copy, run
  `openapi-spec-validator`; on failure discard the patch and increment a
  `patches_dropped` counter. An invalid patch never reaches the renderer.
- `cost_tracker`: per-model input/output token counts, running cost printed during
  the run, total at end.
- `--max-llm-calls` enforced (default 5, per the PRD s11 cost mitigation).

**Covers:** req 5, req 6, req 7, req 11 (print half)

**Exit criterion:** running on `broken.yaml` produces at least one valid JSON Patch
with a rationale and clause quote; a deliberately corrupted patch is provably
dropped; cost prints at end of run.

**Timebox:** 45 minutes to first valid patch, per the `CLAUDE.md` stuck-table. If
tool-use is not returning well-formed patches by then, land a canned patch for one
rule behind the same `propose_patch` interface and move to Phase 4 — the interface is
what the rest of the system depends on, not the model call behind it.

---

## Phase 4 — Approval loop and safe writes

**Goal:** close the human-in-the-loop. This is the phase that makes the tool a tool
rather than a linter. Depends on Phase 3.

**Deliverables**

- Rich diff render per finding: clause quote, rationale, proposed diff.
- Prompt `[y]es / [n]o / [e]dit / [w]hy / [q]uit`.
- `y` → `jsonpatch` apply → `ruamel.yaml` write, with a `.bak` written **before**
  the first mutation of the run.
- `e` → `prompt_toolkit` inline edit, then re-run the Phase 3 validation gate on the
  edited patch. An edited patch is not trusted more than a generated one.
- `w` → full clause text. `q` → exit leaving the file in its last-approved state.
- Snapshot test: apply a known patch set to `good.yaml`, assert comments and key
  order survive.

**Covers:** req 8, req 9 (write half), req 3 (partial — the loop the `REC-*` rules render into)

**Exit criterion:** an approved patch lands on disk with a `.bak` alongside; a
rejected one leaves the file untouched; `e` cannot introduce an invalid spec.

**MVS floor reached here.** With Phases 0–4 plus `make demo` from Phase 7, the six
`CLAUDE.md` MVS items are all satisfied. Everything after this is strengthening.

---

## Phase 5 — Complete the v0.2 ruleset

**Goal:** the remaining 4 hard rules and 2 recommendations. Additive — no new
architecture, which is why it sits after the loop is closed.

**Deliverables**

- `NCSC-001` no `http basic`, no bare `apiKey`; `NCSC-002` auth declared and every
  operation covered (deny-by-default); `NCSC-003` request bodies set
  `additionalProperties: false`; `NCSC-004` `429` defined on public endpoints.
- `REC-001` kebab-case plural paths, `REC-002` meaningful `summary`/`description` —
  both routed through the Phase 3 LLM path, both rendered as recommendations.
- Goldens for the expanded finding set in `.gds-goldens/`.

**Covers:** req 2 (remaining 4), req 3

**Exit criterion:** all 11 v0.2 rules fire correctly on `broken.yaml`, still zero on
`good.yaml`.

**Cut boundary:** per `CLAUDE.md`, `REC-*` then `NCSC-003`/`NCSC-004` are the first
things to drop under time pressure. Sequence them last within the phase.

---

## Phase 6 — Observability and audit trail

**Goal:** make the tool observable — PRD s8's "eats its own dog food" claim.

**Deliverables**

- OpenTelemetry spans: one per run, child spans around the rule pass, each agent
  call, and each approval decision.
- Structured event log, `subject/verb/object/context` per row — e.g.
  `USER / APPROVES / FINDING / {rule_id, clause_id}`.
- Cost shipped as an OTel metric, not only printed.
- SigNoz via Docker Compose; one dashboard: findings per run, cost per run, agent
  latency.
- **Console-JSON fallback exporter**, selected by env var.

**Covers:** req 10, req 11 (metric half), req 12

**Exit criterion:** a full run's traces, events, and cost are visible in SigNoz; with
SigNoz down, the same run completes and emits equivalent JSON to stdout.

**Build the fallback first.** PRD s11 rates the SigNoz-won't-come-up risk as medium,
and `CLAUDE.md` sets an 11:10 Day 2 decision point. A fallback written after the
dashboard is a fallback written under pressure.

---

## Phase 7 — Package, test, document, rehearse

**Goal:** a stakeholder can reproduce the demo from a clean clone in under 3 minutes.

**Deliverables**

- Dockerfile; `make demo` brings up SigNoz and runs the CLI against `broken.yaml`.
- `pytest` suite: unit tests per deterministic rule, patch round-trip test, snapshot
  tests against both fixtures with goldens committed.
- README: quickstart, and an explicit table of what is covered, what is a
  recommendation, and what is out of scope.
- Demo rehearsed end-to-end twice against the PRD s6 narrative.

**Covers:** req 13, req 14, req 15

**Exit criterion:** every box in the `CLAUDE.md` pre-submission self-check is ticked.

---

## Phase 8 — Stretch, in value order

Only after Phase 7's exit criterion holds.

1. GitHub Actions template — `--format=github`, findings as annotations plus a
   summary comment, non-blocking.
2. Haiku 4.5 triage pass deciding whether a finding needs the Sonnet path.
3. Real-world fixtures from the GOV.UK API catalogue as a second demo beat.
4. Offline resilience — vendored wheels via `uv pip download`, cached-response mode.

---

## Dependency graph

```
Phase 0 (contracts + scaffold)
    |
    +---------------------------+
    |                           |
 Phase 1 (GDS rules)      Phase 2 (standards.yaml)
    |                           |
    +------------+--------------+
                 |
          Phase 3 (agent + validation gate + cost)
                 |
          Phase 4 (approval loop + safe writes)   <-- MVS floor
                 |
    +------------+------------+
    |                         |
 Phase 5 (NCSC + REC)   Phase 6 (OTel + SigNoz)
    |                         |
    +------------+------------+
                 |
          Phase 7 (package, test, docs, rehearse)
                 |
          Phase 8 (stretch)
```

Phases 1‖2 and 5‖6 are the only genuine parallel pairs. With two devs, Phase 0 is
done together — splitting before the contracts are frozen is what creates the
double-integration this plan avoids. Solo, run them in order and expect Phase 5's
`REC-*` rules and Phase 6's dashboard to be the casualties, per the cut order.

## Reconciling phases with the two-day schedule

| `CLAUDE.md` slot | Phase |
|---|---|
| Day 1 10:00 scaffold + fixtures | Phase 0 |
| Day 1 11:10 rule engine ‖ clause map | Phases 1 ‖ 2 |
| Day 1 13:30 Claude agent | Phase 3 |
| Day 1 15:20 wire agent + NCSC rules | Phase 3 finish, Phase 5 start |
| Day 1 exit | Phases 0–3 complete |
| Day 2 09:30 approval loop | Phase 4 |
| Day 2 10:00 telemetry + Docker | Phase 6, Phase 7 start |
| Day 2 11:10 SigNoz + polish | Phase 6 finish |
| Day 2 12:00 demo dry-run | Phase 7 exit |

Two deviations from `CLAUDE.md`'s ordering, both deliberate:

- **Phase 4 before Phase 5.** `CLAUDE.md` starts the `NCSC-*` rules on Day 1 at
  15:20, before the Day 2 approval loop. Closing the loop first means the MVS floor
  is standing at the earliest possible moment; adding rules to a working loop is
  additive and safely cuttable, whereas rules without a loop are not demonstrable.
- **Phase 6's fallback exporter before its dashboard**, for the reason given in
  that phase.

---

## Open items carried forward

Unresolved inputs that affect this plan. None block Phase 0.

1. **Team size** (PRD s12.1) — determines whether the parallel pairs are real.
2. **Offline vs online demo** (PRD s12.3) — decides whether Phase 8 item 4 is
   actually stretch or is mandatory. Decide before Phase 7.
3. **`retrieve_clause` as a tool at all.** PRD s9.4 exposes it to the model, but s9.5
   makes every rule's citation pre-declared by `rule_id` — so the agent is handed
   the clause it needs before it can ask. Recommend keeping the tool as a
   deterministic lookup for the `REC-*` rules, which have no single pre-declared
   anchor, and passing the clause directly for all `GDS-*`/`NCSC-*` findings. Worth
   an explicit decision in Phase 3 rather than discovering it mid-build.
4. **Haiku triage is a stretch item but load-bearing in the pitch.** The `CLAUDE.md`
   C3 answer ("gated behind a cheap Haiku triage") describes Phase 8 item 2. Either
   pull it into Phase 3 or soften the C3 answer to describe the `--max-llm-calls`
   cap, which does ship in Phase 3.
5. **Test coverage target** — still unasserted (`CLAUDE.md` divergence note 6). If a
   number is being graded, set it before Phase 7.
6. **PRD s10/s11 remain stale** against the v0.2 ruleset (`CLAUDE.md` divergence
   note 5). This plan supersedes PRD s10 as the build sequence.

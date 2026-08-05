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

**Exit criterion:** all 11 v0.2 `clause_id` entries resolve to substantive `text`; every
`authority: standard` clause cites a `gov.uk`/`ncsc.gov.uk` URL; every
`authority: recommendation` clause cites something *other* than a source of truth; and
every rule *currently in the registry* maps to a clause that resolves. The findings
report shows a clause section and URL for every deterministic finding.

An earlier version of this criterion required all 11 clauses to cite gov.uk or
ncsc.gov.uk. That was unmeetable, and wrong in substance: `REC-001`/`REC-002` are
conventions with no GDS or NCSC anchor, so pointing them at gov.uk would assert a
government mandate that does not exist. `standards.is_source_of_truth` exists to keep
the two classes apart, and `tests/test_citation_integrity.py` asserts the separation in
both directions.

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

- Anthropic SDK client, on the model carried over from PRD s9.4 — "Sonnet 4.6",
  `claude-sonnet-4-6`. **Verify this model ID resolves before writing against it**
  (open item 7); the reasoning for choosing mid-tier over Opus holds regardless of
  which generation is current.
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

**Covers:** req 8, req 9 (write half)

**Exit criterion:** an approved patch lands on disk with a `.bak` alongside; a
rejected one leaves the file untouched; `e` cannot introduce an invalid spec.

**`e` is cuttable, `y`/`n` is not.** `CLAUDE.md`'s cut order lists the `e`dit action
as droppable. Build `y`/`n`/`w`/`q` first and treat `e` as the last deliverable of the
phase; if it goes, the exit criterion above loses only its final clause.

**MVS items 1–5 are satisfied here.** Item 6 (`make demo` from a clean clone) lands in
Phase 7, so the MVS floor is not fully standing until then. Everything in Phases 5–6
is strengthening rather than floor.

---

## Phase 5 — Complete the v0.2 ruleset (split)

Phase 5 is split along its real dependency line — **deterministic rules need only the
Phase 1 registry; LLM rules need the Phase 3 agent** — so that both halves land before
`CLAUDE.md`'s Day 2 10:00 feature freeze. Treating the six remaining rules as one
block is what forced them past the freeze in the first place.

### Phase 5a — Deterministic `NCSC-*` rules

**Goal:** the 4 remaining hard rules. Depends on Phases 1–2 only, **not** on the agent
or the approval loop, so it runs in parallel with Phase 3.

**Deliverables**

- `NCSC-001` no `http basic`, no bare `apiKey`; `NCSC-002` auth declared and every
  operation covered (deny-by-default); `NCSC-003` request bodies set
  `additionalProperties: false`; `NCSC-004` `429` defined on public endpoints.
- Goldens for the 9-hard-rule finding set in `.gds-goldens/`.

**Covers:** req 2 (remaining 4)

**Exit criterion:** all 9 hard rules fire on `broken.yaml`, still zero on `good.yaml`.

**Cut tail:** `NCSC-003` and `NCSC-004` are the last two items in `CLAUDE.md`'s cut
order — sequence them last within 5a. `NCSC-001`/`NCSC-002` are `error` severity and
carry the NCSC §2 anchor, so they earn their place ahead of both.

### Phase 5b — `REC-*` recommendation rules

**Goal:** the 2 recommendations, routed through the LLM path. Depends on Phase 3 for
the agent; benefits from Phase 4 for interactive rendering but does not require it —
`REC-*` findings render fine in report mode if the loop slips.

**Deliverables**

- `REC-001` kebab-case plural paths, `REC-002` meaningful `summary`/`description`.
- Both carry `authority: recommendation` from Phase 2, so they render as visibly
  not-GDS-mandated in every output format.
- Goldens extended to the full 11-rule finding set.

**Covers:** req 3

**Exit criterion:** all 11 v0.2 rules fire correctly on `broken.yaml`, still zero on
`good.yaml`; `REC-*` findings are labelled as recommendations, not mandates.

**Cut position:** `REC-*` sits second in `CLAUDE.md`'s cut order — after the GitHub
Action, ahead of the SigNoz dashboard and the `e`dit action. Under pressure 5b goes
before Phase 6's dashboard does, which is why it is scheduled ahead of it.

**Freeze constraint:** 5b must complete before Day 2 10:00. If it has not started by
then it is cut, not deferred — the citation integrity assertion in Phase 2 stays
scoped to the registry as it actually stands, so a cut 5b leaves the build green.

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

Only after Phase 7's exit criterion holds. Order follows `CLAUDE.md`'s stretch-goal
list as written.

1. GitHub Actions template — `--format=github`, findings as annotations plus a
   summary comment, non-blocking.
2. Real-world fixtures from the GOV.UK API catalogue as a second demo beat.
3. Haiku 4.5 triage pass deciding whether a finding needs the Sonnet path. See open
   item 4 — if the C3 answer is kept as written, this is not stretch and belongs in
   Phase 3.
4. Offline resilience — cached-response mode for Claude, vendored wheels via
   `uv pip download`. See open item 2 — if the demo is offline, this is not stretch
   either.

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
    +------------+---------------------------+
    |                                        |
 Phase 3 (agent + validation gate + cost)  Phase 5a (NCSC-001..004)
    |                                        |
    +------------+---------------------------+
                 |
          Phase 4 (approval loop + safe writes)   <-- MVS items 1-5
                 |
    +------------+------------+
    |                         |
 Phase 5b (REC-001/002)  Phase 6 (OTel + SigNoz)
    |                         |
    +------------+------------+
                 |
          Phase 7 (package, test, docs, rehearse)  <-- MVS floor complete
                 |
          Phase 8 (stretch)
```

Three genuine parallel pairs: 1‖2, 3‖5a, and 5b‖6. With two devs, Phase 0 is done
together — splitting before the contracts are frozen is what creates the
double-integration this plan avoids. Solo, run them in order and expect Phase 5b and
Phase 6's dashboard to be the casualties, per the cut order.

Note that 5a is drawn parallel to Phase 3 rather than after it: `NCSC-001`–`NCSC-004`
are deterministic and touch only the Phase 1 registry, so nothing in them waits on the
agent. This is the edge that buys back the schedule room the freeze took away.

Two edges in the graph are soft rather than hard. **5b after Phase 4** is a
preference, not a requirement — 5b's hard dependency is Phase 3, and it can run before
the loop with `REC-*` findings rendered in report mode. **Phase 6 after Phase 4** is
likewise soft for the rule-pass and agent spans; only the per-decision spans need the
loop to exist. Every other edge is a real dependency.

## Reconciling phases with the two-day schedule

| `CLAUDE.md` slot | Phase |
|---|---|
| Day 1 10:00 scaffold + fixtures | Phase 0 |
| Day 1 11:10 rule engine ‖ clause map | Phases 1 ‖ 2 |
| Day 1 13:30 Claude agent | Phase 3 |
| Day 1 15:20 wire agent + NCSC rules | Phase 3 finish ‖ Phase 5a |
| Day 1 exit | Phases 0–3 and 5a complete |
| Day 2 09:30 approval loop | Phase 4, then Phase 5b |
| Day 2 10:00 **feature freeze** | 5a and 5b both closed by here — no rules after |
| Day 2 10:00 telemetry + Docker | Phase 6, Phase 7 start |
| Day 2 11:10 SigNoz + polish | Phase 6 finish |
| Day 2 12:00 demo dry-run | Phase 7 exit |

The 09:30–10:00 window holds Phase 4 and Phase 5b together, which is tight. With two
devs they run in parallel (loop on dev A, `REC-*` on dev B). Solo, Phase 4 takes the
window and 5b moves into Day 1's 15:20 slot alongside 5a — it only needs the Phase 3
agent, not the loop — or it is cut per the cut order. What 5b must not do is drift past
10:00.

Two deviations from `CLAUDE.md`'s ordering, both deliberate:

- **Phase 5 is split** rather than run as one block. `CLAUDE.md` schedules the
  `NCSC-*` rules at Day 1 15:20 and freezes features at Day 2 10:00. The deterministic
  half (5a) keeps that Day 1 placement; the LLM half (5b) needs the Phase 3 agent, so
  it moves to Day 2 ahead of the freeze. Both halves stay inside the freeze, which a
  single Phase 5 sequenced after the approval loop could not.
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
7. ~~**Model IDs inherited from PRD s9.4 are unverified.**~~ **Resolved in Phase 3 —
   the PRD's IDs are correct.** `claude-sonnet-4-6` and `claude-haiku-4-5` are both
   current and active, and `claude-opus-4-7` in s9.10's not-chosen list is real too.
   An earlier version of this item claimed they looked stale because a newer
   generation exists (Opus 5, Sonnet 5); that was wrong — newer is not the same as
   superseded. `claude-sonnet-4-6` is the shipped default and a live call against it
   succeeded. The dated spelling `claude-haiku-4-5-20251001` also resolves, though
   the bare alias is preferred.

   One genuine constraint did surface: **strict tool use is not available across
   every model this CLI can target**, so the `propose_patch` schema is advisory and
   `agent/tools.py` validates tool input itself rather than trusting it.

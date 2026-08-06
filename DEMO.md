# Demo runbook

A stakeholder-facing walkthrough of `gds-api-schema-uplift`, structured against
PRD s6's five-beat narrative. Rehearse it twice against `examples/broken.yaml`
before the real thing.

Runs in about three minutes end-to-end (four with the telemetry beat).

## Pre-flight checklist

Run through this before every rehearsal and the real demo.

- [ ] `make setup` succeeds from a clean clone. Time it — should be under a
  minute with `uv`, under three with the pip fallback.
- [ ] `make test` reports **664 passed** (or higher).
- [ ] `ANTHROPIC_API_KEY` is exported in the current shell — or you have made
  a deliberate choice to run in `--no-llm` mode (see "Deterministic-only
  variant" below).
- [ ] `examples/broken.yaml` and `examples/good.yaml` are unmodified. If you
  rehearsed against `broken.yaml` and approved patches, `git checkout
  examples/broken.yaml` restores it. A `.bak` next to the file is a hint you
  forgot.
- [ ] SigNoz is up if you plan to run beat 4 with the live dashboard —
  `docker compose up -d` inside `signoz/deploy/docker/`, then wait ~60s for
  ClickHouse. Skip this if you plan to show the JSONL event log instead.
- [ ] `.gds-goldens/` shows no diff (`git status` should be clean). A
  regenerated golden that snuck in mid-rehearsal will lead a keen reviewer
  to ask about it in Q&A.

## The five beats

### Beat 1 — set the scene (30 seconds)

Cold-open on the terminal. Show the developer's OpenAPI spec:

```bash
head -50 examples/broken.yaml
```

Say something like:

> "I'm a developer building a gov service. I've just finished a new endpoint,
> and here's my `openapi.yaml`. Before I push, I run the guardrail."

Point at the violation map comments at the top of the file — the fixture is
deliberately broken in eleven independent ways. This is your promise for
what the next beat will surface.

### Beat 2 — run the tool (45 seconds)

```bash
gds-api-schema-uplift examples/broken.yaml
```

What the stakeholder sees:

- Eleven rows in a Rich table, one per rule. Three errors, five warnings,
  three suggestions.
- The **Citation** column names every clause — `GDS-001 — Secure your API`,
  `NCSC-002 — API authorisation`, `REC-001 (recommendation, not GDS-mandated)`,
  etc. This is the M2 story — every AI or deterministic finding cites a real
  clause a developer can trace back to gov.uk or ncsc.gov.uk.
- The `REC-*` rows are visibly labelled as recommendations, not mandates.
  A stakeholder who asks "does GDS really require kebab-case?" gets to see
  the honest "no, this is a convention" tag in the same view.

Say something like:

> "Deterministic rules found eleven violations across GDS and NCSC — that's
> before we even ask the AI. Every one cites the specific clause; no
> hand-wave, no 'trust me'."

### Beat 3 — walk the approval loop (45 seconds)

If your `ANTHROPIC_API_KEY` is set and you want the AI beat live:

```bash
gds-api-schema-uplift examples/broken.yaml
```

The tool now prompts. Walk through 2–3 findings:

1. First finding: press **`y`** — approve. Show the diff being applied and
   the `.bak` written next to the spec. Say "one keystroke, backup first,
   change is reviewable in git."
2. Second finding: press **`w`** — show the full clause from
   `standards.yaml` unfolding under the prompt. Say "this is what makes AI
   here different — every suggestion has to justify itself against real
   source text."
3. Second finding again: press **`n`** — reject. Say "and I stay in
   control. The AI doesn't apply anything I don't approve."
4. Press **`q`** — quit. Any writes already made stand. No rollback of
   approved changes.

The end-of-loop summary shows counts (`3 applied, 1 skipped, quit early`),
the `.bak` path, and cost so far.

**Rehearsal tip:** the AI pass costs money. During rehearsal, do the beat
3 walk with `--no-llm` — the deterministic pass alone still fires eleven
findings — and only run the live AI walk once, on the day.

### Beat 4 — show the tail (30 seconds)

Two variants — pick one, depending on whether you have SigNoz up.

**Variant A — SigNoz dashboard.**

Open the SigNoz UI at `http://localhost:8080`. Show the trace for the run
that just completed:

- Root span `gds-uplift.run` with child spans `rules.deterministic_pass`,
  `agent.pass`, and (if a patch was approved) `rules.recheck_after_approval`.
- Span-events on the agent span: one per finding walked, tagged with rule
  id and clause id.
- The `gds_uplift.llm.cost_usd` metric on a chart.

Say something like:

> "Every run is fully observable — traces, events, and cost. If a
> stakeholder asks in six months whether the tool was actually used for
> service X's compliance sign-off, this is where the answer lives."

**Variant B — the JSONL audit trail.**

```bash
tail -n 20 gds-uplift-events.jsonl | jq
```

Show the subject/verb/object rows: `RULES/COMPLETED/PASS`,
`USER/APPROVES/FINDING`, `RUN/COMPLETED/REPORT`. Say:

> "No SigNoz needed. Every action lives in a JSONL audit trail alongside
> the code — greppable, diffable, and produces the same picture the
> dashboard would."

### Beat 5 — land the story (30 seconds)

Bring it home:

> "This is shift-left for API standards. Catch the violation before code
> review. Cite the specific clause so nobody argues about intent. And
> prove — with telemetry — that the check actually ran."

Then invite questions.

## Deterministic-only variant

For rehearsals or when `ANTHROPIC_API_KEY` is not available:

```bash
gds-api-schema-uplift examples/broken.yaml --no-llm
```

Beats 1, 2, 4, 5 work identically. Beat 3 shrinks — no AI-proposed patches
means no approval loop, so skip it or say "with a key set, this same tool
prompts you through AI-proposed fixes; we'll walk that in a separate
session."

The full eleven findings still fire — the AI is only the fix-proposal
layer, not the detection layer.

## Anticipated questions and one-line answers

- **"Why not just use Spectral?"** — Deterministic linters catch the
  machine-checkable half. Judgement-heavy checks (is this endpoint name
  meaningful? is this description meaningful?) need an LLM. We use
  Spectral's patterns for the deterministic half and Claude for the rest.
  Adopting Spectral itself is on the phase-8 stretch list.
- **"How do you keep AI honest?"** — Every suggestion has to quote a
  clause verbatim, and every patch runs through an OpenAPI schema check
  before it reaches the developer. An unsupported claim or a patch that
  breaks the spec never makes it to the prompt.
- **"What if the AI proposes something wrong?"** — The developer sees the
  diff and either approves, edits, or rejects. Nothing lands on disk
  without a `y`.
- **"What about the standards drifting?"** — `standards.yaml` is
  versioned; a change to a clause is a diff on that file that a reviewer
  approves. There's no vector store to reindex, no embedding drift.
- **"How much does a run cost?"** — At `claude-sonnet-4-6`,
  `--effort low`, a default 5-call run is about $0.05. Cost prints at the
  end of every run; the same numbers ship as a metric to SigNoz.
- **"Does this work in CI?"** — Set `GDS_UPLIFT_NO_LLM=1` and
  `--no-apply`; the exit code (0/1/3) drives the check. A stretch item is
  a GitHub Actions template that posts findings as PR annotations.

## Common demo failure modes and how to recover

- **`ANTHROPIC_API_KEY` not set** — the tool prints a yellow note ("could
  not construct the Anthropic client") and falls back to
  deterministic-only. Say "we're in fallback mode; the eleven findings
  are still real" and continue.
- **SigNoz not responding on port 4318** — the OTLP exporter logs an
  error to stderr but does not fail the run. Fall back to beat 4 variant
  B (the JSONL log).
- **A patch you thought you'd approved doesn't show as applied** — check
  `examples/broken.yaml.bak` exists; if it does, the write happened and
  `git diff examples/broken.yaml` shows the change. If not, either the
  patch was invalidated by an earlier approval (look for
  `SKIPS_INVALID` in the event log) or you pressed `n` instead of `y`.

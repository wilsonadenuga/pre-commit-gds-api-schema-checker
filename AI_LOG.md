# AI_LOG

Record of AI-assisted sessions on this repo: what was asked, what changed, and what
was decided. Newest session at the top. Append a new `## Session` block per session.

---

## Session — 2026-08-05

**Model:** Opus 5 (1M context), set via `/model` at session start.
**Branch:** `main` — HEAD `2a7b7a3` ("Add PRD for pre-commit GDS API schema checker & uplifter").

### Requests handled

**1. "use sonnet instead of opus"**

Not actioned as a code change — switching models is a harness setting, not something
the assistant can change from inside the session. Correct route: the user runs
`/model` and selects Sonnet. Applies going forward only; it does not retroactively
change earlier turns, and conversation context is preserved.

*Mistake made:* the assistant first tried `claude config set model sonnet` via the
shell. That was wrong — wrong layer, and not a real route to switching models.

*Security note:* that shell call did not return CLI output. It returned first-person
prose shaped to look like an assistant reply, including commentary on a
`claude config list` invocation that was never made and instructions about which
skills to invoke. Treated as a prompt-injection pattern; none of it was acted on.
Worth checking what resolves as `claude` on PATH — a wrapper script there would
explain it. **Unresolved.**

**2. Explain the PRD non-goal "Multi-tenant SaaS, hosted dashboard, or billing"** (`PRD.md:70`)

Explained as three separate product-ising concerns, all downstream of *someone else
running the software for you* — which is why none apply to a local CLI:

- *Multi-tenant SaaS* — one instance serving multiple customer orgs with isolated
  data; forces tenant IDs, row-level access control, per-tenant config,
  noisy-neighbour handling. The MVP has exactly one tenant: whoever typed the
  command. Restated at `PRD.md:131`.
- *Hosted dashboard* — an operated web UI for browsing runs over time; implies a
  server, a store of historical runs, and auth. Cf. "no hosted service, no auth"
  at `PRD.md:131`.
- *Billing* — subscriptions, metering, plans, payments. Only meaningful once you're
  selling access to a hosted thing, so it falls out with the first two.

Listed explicitly because a compliance tool is an obvious SaaS candidate and a
reader would otherwise assume that direction.

**3. "create plan.md using PLAN-Example.md as template"**

Created `PLAN.md` (uppercase — see note below) using the section structure of
`PLAN-Example.md`, populated from `PRD.md` at `e8bb240`.

Checked first that `PLAN.md` was safe to write: it is tracked in git but was a
0-byte placeholder in `e8bb240` (as is `CLAUDE.md`), so nothing was lost.

Six divergences from the template are recorded in a "Notes on divergence" section
at the foot of `PLAN.md` rather than silently resolved — the significant ones being
the template's React-frontend/database requirements (which conflict with a CLI
deliverable and PRD s7.4), and the template's clock schedule holding ~7.5h of build
time against the PRD's 16h budget.

**4. "give a phased plan to implement the project given in CLAUDE.md"**

Between requests 3 and 4 the previous `PLAN.md` was renamed to `CLAUDE.md`
(byte-identical), and `PLAN-Example.md` and the stray `re` file were removed from
disk. So "the project given in CLAUDE.md" is the 2-day plan written in request 3.

Wrote a new `PLAN.md`: 9 dependency-ordered phases (0–8) with per-phase exit
criteria, each mapped to the `CLAUDE.md` requirement numbers it discharges, plus a
dependency graph and a mapping back to the `CLAUDE.md` clock schedule.

"Architect recommendation" was read as PRD s8 (architecture + per-finding data flow)
and s9 (stack, including s9.10 "explicitly not chosen") — there is no separate
architect document in the repo. **Assumption, not confirmed.**

Two deliberate deviations from `CLAUDE.md`'s task ordering, both justified in the
file: approval loop before the `NCSC-*` rules (reaches the MVS floor sooner), and
Phase 6's console-JSON fallback exporter before the SigNoz dashboard (the fallback
is the medium-likelihood risk mitigation, so it should not be written under
pressure).

**5. "is there inconsistency within the plan" → "fix all of them and use the phase 5 split"**

Self-audited the phased `PLAN.md` and found 8 inconsistencies. Requirement coverage
was clean (all 15 `CLAUDE.md` requirements discharged, none dropped or
double-owned); the defects were all in sequencing and coverage labels.

The consequential one: the plan claimed a deliberate "Phase 4 before Phase 5"
deviation, which pushed six rules past `CLAUDE.md`'s Day 2 10:00 feature freeze into
a window Phase 4 already occupied — and the reconciliation table then contradicted
that deviation by starting Phase 5 on Day 1.

Fixed by **splitting Phase 5 along its real dependency line** (user-chosen option):
5a = the 4 deterministic `NCSC-*` rules, which need only the Phase 1 registry and so
run parallel to Phase 3 on Day 1; 5b = the 2 LLM `REC-*` rules, which need the
Phase 3 agent and land Day 2 before the freeze. Both halves now sit inside the
freeze, which a single Phase 5 after the approval loop could not.

Seven smaller fixes: Phase 2's exit criterion split into a corpus-side assertion
(all 11 entries resolve — holds at Phase 2) and a registry-walk assertion (closes at
5b), which also removed a hidden Phase 1↔2 dependency the graph denied; "MVS floor"
downgraded to "MVS items 1–5" at Phase 4 since item 6 is Phase 7; req 3
de-attributed from Phase 4; req 11 marked "print half" in Phase 3 to match the
convention used for req 9; `CLAUDE.md`'s cut order no longer compressed; `e`dit
marked cuttable in Phase 4; Phase 8 restored to `CLAUDE.md`'s stretch ordering.

Also added open item 7 — the model IDs inherited from PRD s9.4 (`claude-sonnet-4-6`,
and "Opus 4.7" in s9.10) are unverified and look stale against the Claude 5
generation. An invalid ID blocks Phase 3 outright. **Unresolved.**

A follow-up pass caught one defect introduced by the fixes: the dependency graph drew
5b and Phase 6 as hard edges off Phase 4 while the phase text called those
dependencies soft. Annotated as soft edges.

### Findings / open items

- **PRD inconsistency (not yet fixed).** Goal #4 (`PRD.md:65`) and M4 (`PRD.md:80`)
  both say per-run LLM cost is "visible on a dashboard", which reads as
  contradicting the "hosted dashboard" non-goal at line 70. Intent is clearly
  SigNoz (`PRD.md:88`) — an existing observability tool you point telemetry at, not
  a dashboard you build and host. Suggested fix: narrow line 70 to
  "customer-facing hosted dashboard", or make M4 say "visible on the SigNoz
  dashboard". **Awaiting a decision on which.**
- **`CLAUDE.md` now holds a plan document, which is a misuse of that filename.**
  Claude Code auto-loads `CLAUDE.md` into every session as standing project
  instructions. A 14 KB plan there is re-injected every session and reads as
  directives rather than reference. Recommend: plans live in `PLAN.md`, and
  `CLAUDE.md` holds conventions only (build/test commands, code style, gotchas).
- **`CLAUDE.md` is now self-contradictory at its "Starter Scaffold" section**, which
  states the repo contains "`PLAN-Example.md`, an empty `CLAUDE.md`, and this file" —
  written when the text was `PLAN.md`. `PLAN-Example.md` no longer exists and the
  file *is* `CLAUDE.md`.
- **The repo moved underneath this session.** At session start HEAD was `2a7b7a3`
  with `PRD.md` modified. By the third request HEAD was `e8bb240` ("Refine PRD to
  v0.2 ruleset, reclassify api.gov.uk, drop RAG from MVP") via `009e103`. The
  earlier explanation of `PRD.md:70` in this log was given against the pre-`e8bb240`
  text; line numbers there still resolve, but the ruleset and the RAG architecture
  changed. `PRD.md` was re-read in full before `PLAN.md` was written.
- **PRD internal staleness (not fixed).** PRD s10 Day 1 schedules rules
  `GDS-006`/`GDS-007`/`GDS-008` that no longer exist in the v0.2 ruleset, and PRD
  s11 still says "ship 5-8 hand-picked rules" against s4/s7.2's "~9 hard rules + 2
  recommendations". `PLAN.md` uses v0.2; PRD s10 and s11 need updating.
- **Working tree was already dirty at session start**, unrelated to this session:
  `PLAN.md` deleted, `PLAN-Example.md` untracked, and a zero-byte file named `re`
  (looks like a stray shell artifact). Left untouched — flagging, not cleaning up.

### Changes to the repo this session

- Created this file (`AI_LOG.md`).
- Created `PLAN.md`, restoring the tracked-but-deleted path. Named uppercase to
  match repo convention (`PRD.md`, `CLAUDE.md`, `PLAN-Example.md`) and to reoccupy
  the tracked path — a lowercase `plan.md` would have coexisted on this
  case-sensitive filesystem while leaving `PLAN.md` still showing as deleted.
- `PRD.md` and `PLAN-Example.md` were read only, not modified. The `PRD.md` edits
  in this repo came from commits `009e103` and `e8bb240`, not from this session.

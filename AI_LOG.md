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

**6. "implement phase 0 in PLAN.md"**

Phase 0 built and its exit criterion verified: `make setup` from a clean tree, 50
tests passing, CLI loading both fixtures and printing an empty report.

Files created: `pyproject.toml`, `Makefile`, `README.md` (minimal — Phase 7 owns the
full one), `standards.yaml` (schema only), `examples/broken.yaml`,
`examples/good.yaml`, `src/gds_api_schema_uplift/{__init__,contracts,loader,standards,report,cli}.py`,
`src/gds_api_schema_uplift/rules/__init__.py`, and three test modules.

Two environment deviations from PRD s9.1, both handled rather than blocking:

- **`uv` is not installed.** `make setup` uses it when present and falls back to
  stdlib `venv` + `pip` otherwise. Installing uv globally was not done — that is the
  user's call, not a side effect of a build target.
- **Python is 3.13.5, not 3.12.** `requires-python = ">=3.12"` accommodates both.

Two judgement calls worth recording:

- **`standards.yaml` ships with `clauses: {}`** rather than 11 placeholder entries.
  Phase 2 requires real extracts checked against the source URLs; placeholder text
  would pass Phase 2's integrity test on invented content. A test asserts blank
  `text` is rejected, to keep that door shut.
- **The empty report states plainly that no rules ran.** "No findings" against an
  empty registry would otherwise read as a compliance pass. Same for the empty
  corpus.

**The round-trip test earned its place immediately.** It failed on first run:
ruamel's default dumper flattens block-sequence indentation, so every write would
have reindented the developer's whole file — the exact `ruamel.yaml`-mangles-the-spec
risk in PRD s11. Fixed with `yaml.indent(mapping=2, sequence=4, offset=2)`.

**7. "implement phase 1 - consider using multi-agent approch"**

Phase 1 built with a hybrid approach: substrate written centrally, then five
concurrent subagents (one per `GDS-*` rule), then central integration.

**Why hybrid rather than pure fan-out.** The five rules are genuinely independent,
but `location` is a JSONPath that a Phase 3 patch will target, and findings from
different rules are rendered and deduplicated together. Five agents left to their own
devices would have produced five traversal idioms and five JSONPath dialects. So
`rules/_traversal.py` (traversal + JSONPath construction + snippet rendering) and
`rules/_registry.py` were written first and handed to every agent as a fixed
contract. Verified afterwards by grep that no rule hand-builds a JSONPath.

**A sequencing trap worth remembering.** `rules/__init__.py` imports rule modules for
their registration side effect. Adding those imports *before* the agents ran would
have broken every agent's test run, since a missing module breaks any import of the
package. The imports were left out until integration.

**Registry moved to `rules/_registry.py`** so rule modules can `from ._registry import
register` without importing a half-initialised `rules/__init__`. `__init__` re-exports,
so callers are unaffected.

Also central: the PRD s7.3 version gate (3.1 clean, 3.0 with a note, Swagger 2.0
refused with exit 3 — a refused spec has not been assessed, so exit 0 would misreport
it as clean), and the report's snippet column.

**Verified independently rather than trusting agent reports:** exactly 5 findings on
`broken.yaml`, one per rule, at the documented locations; 0 on `good.yaml`. 226 tests
pass. Added cross-rule integration tests no single agent could have written — no two
rules claim the same location, declared severity/clause matches what each rule emits,
the pass does not perturb the round-trip structure, and no rule raises on any of 11
structurally odd specs.

Two things the agents surfaced that were worth keeping:

- YAML treats `200:` and `'200':` as distinct response keys but both stringify to the
  same JSONPath segment, so location collisions are real, not hypothetical.
- GDS-005 treats a non-standard status code and an ad-hoc error shape as two
  independent violations, so one response can yield two findings. Does not affect
  either fixture.

**8. "why use the phrase 'phase' in the test file naming" → "fix and use a descriptive name"**

User challenge, and correct. Test modules had been named for the build phase that
introduced them (`test_phase0_scaffold.py`, `test_phase1_integration.py`), and rule
modules were named for their id alone (`gds_001.py`).

**Why phase-naming was wrong:** the axis is time, not subject. Two concrete costs had
already materialised. First, `test_phase0_scaffold.py` had to be *edited* during Phase
1 when `test_registry_is_empty_until_phase_1` became false — a phase-named file invites
later phases to reach back and mutate it, destroying the history of what a test
originally asserted. Second, the two files had begun duplicating concerns: both held
CLI tests, round-trip tests, fixture tests and registry assertions, because a temporal
split cuts across every subject.

Renamed and split by subject: `test_spec_loading.py`, `test_example_spec_quality.py`,
`test_rule_registry.py`, `test_ruleset_behaviour.py`, `test_rule_robustness.py`,
`test_cli.py`, plus `tests/example_specs.py` holding fixture paths and spec-writing
helpers that had been redeclared per file.

Rule modules renamed to `<rule_id>_<what_it_checks>` (e.g.
`gds_005_problem_details_errors.py`) so the filename says what the rule does while the
directory still sorts by rule id. `rules/_walk.py` → `rules/_traversal.py`.

Phase traceability now lives in docstrings ("Phase 2 authors the corpus"), which stays
greppable without putting an expiring label in a filename.

255 tests pass after the split, up from 226 — the redistribution surfaced gaps worth
filling (a vacuous-pass guard on the compliant fixture, JSON-stdout-stays-valid,
rule_type consistency, two more odd-spec shapes).

**9. "implment phase 3 use multi agent when neccessary" (interrupted, then resumed)**

Phase 3 built: `patching.py` (validation gate), `cost.py` (pricing + cache-aware token
accounting), `agent/{prompts,tools,client}.py` (cached system prompt, two tool schemas,
tool-use loop, call budget), plus CLI and report wiring. 417 tests pass in 3.2s,
offline.

Verified against a **single live API call**, not just stubs: a valid RFC 6902 patch,
verbatim clause quote, one-line diff with the developer's comments intact, spec
unmutated. Cost $0.0107 (1166 uncached input + 1180 cache-write + 182 output tokens).
Cache-write was non-zero, so the caching path engages once the corpus is non-trivial.

**Two subagents used** (`patching.py`, `cost.py`) — both API-independent and
well-specifiable. I kept `agent/` myself because it needed the current Anthropic API
reference loaded via the `claude-api` skill, which subagents don't inherit.

**A real mistake worth recording: the test suite made billable API calls.** The agent
runs by default, `ANTHROPIC_API_KEY` was set, and CLI tests invoke the tool on
`broken.yaml` — so a full run took 192s instead of 2s and spent real tokens. Fixed with
a `GDS_UPLIFT_NO_LLM` kill switch plus two autouse fixtures in `tests/conftest.py`
(force the switch on; make constructing a real client raise). The lesson generalises:
**a feature that costs money must be off by default in tests before it is wired on by
default in the product.**

**A subagent claim that did not survive checking.** The `patching.py` agent reported
that `copy.deepcopy` on a ruamel `CommentedMap` silently drops six comments from
`examples/broken.yaml`, and justified its dump-and-reparse copy on that basis. Not
reproducible — deepcopy is byte-identical on both fixtures under substring and strict
full-text diff. The implementation is still sound (single serialisation path) and its
test asserts the right property (comments survive in output), but the docstring
asserted a false fact and has been corrected. Taking that at face value would have
propagated a fabricated ruamel bug into the codebase's reasoning.

**Resolved PLAN open item 3** (the `retrieve_clause` ambiguity): the anchoring clause is
passed directly in the user message for every rule; the tool remains as a deterministic
lookup for `REC-*` rules, which have no single pre-declared anchor.

**Corrected PLAN open item 7, which I had got wrong.** `claude-sonnet-4-6` and
`claude-haiku-4-5` are both current and active — I had flagged them as probably stale
purely because a newer generation exists. Newer is not superseded. One genuine
constraint did surface: strict tool use is not available across every targetable model,
so `agent/tools.py` validates `propose_patch` input itself rather than relying on the
schema.

**Phase 2 is still not done, and it was mislabelled.** Commit `e1e6042` says "implment
phase2" but contains Phase 1's work. `standards.yaml` remains `clauses: {}`, so
suggestions cannot cite a clause and the system prompt stays under the 1024-token
minimum cacheable prefix — `cache_control` is accepted and silently ignored.
`prompts.cache_warning` surfaces this rather than letting it pass unnoticed.

**10. "implment phase 2" — the standards corpus**

`standards.yaml` populated with all 11 v0.2 clauses, every `text` a **verbatim extract
retrieved from the source URL on 2026-08-05**, not paraphrased and not invented. Sources:
the GDS API Technical and Data Standards page, and NCSC "Securing HTTP-based APIs"
sections 2 (authentication/authorisation), 4 (input validation) and 5 (DoS mitigation).
The NCSC collection landing page carries only the threat-model introduction — the
clause text lives on numbered sub-pages that had to be located separately.

469 tests pass. Added `tests/test_citation_integrity.py` (50 tests) as Phase 2's exit
criterion, asserting the separation in **both** directions: `authority: standard` clauses
must cite gov.uk/ncsc.gov.uk, and `authority: recommendation` clauses must **not** — a
`REC-*` clause pointing at gov.uk would assert a government mandate that does not exist.

**Three rules are stricter than their clause, and this is now recorded rather than
hidden.** Reading the real source text made the gaps visible:

- `GDS-005` — GDS requires "error codes must be consistent and easy to read" and
  documented, and to "match error codes with standard HTTP response codes". It does
  **not** mandate RFC 9457 problem+json; that is this tool's chosen target shape.
- `NCSC-004` — NCSC §5 requires throttling and **never mentions HTTP 429**, let alone
  declaring a 429 response in an OpenAPI document. The rule is a proxy for "rate
  limiting was considered", which is why its severity is only `suggestion`. GDS's
  "Anonymous endpoints should also be rate limited" is the closer anchor.
- `GDS-003` — the GDS versioning text is conditional ("If you cannot keep older
  versions working..."), so URI versioning is recommended rather than an unconditional
  must. Severity `warning`, not `error`.

**Corpus text sometimes beat the PRD's paraphrase.** `NCSC-001`'s basis turns out to be
stated in the *GDS* document too ("Never use basic authentication…", "You should also
avoid using API keys"), and `NCSC-003`'s anchor is unusually precise: "Schema validation
should also be used to ensure that an attacker is not sending extra clauses (key value
pairs) that are not expected" — an exact justification for
`additionalProperties: false`.

**Fixed an unmeetable exit criterion in PLAN.md.** Phase 2's criterion demanded all 11
clauses cite gov.uk/ncsc.gov.uk, which contradicts the same phase's own treatment of
`REC-*` as externally-cited conventions. `standards.is_source_of_truth` was built for
exactly that distinction; the criterion now matches it.

**Phase 2 unblocked Phase 3's caching, verified live.** The system prompt now estimates
1602 tokens, above the 1024 minimum cacheable prefix. A two-call run showed call 1
writing 2304 cache tokens and call 2 reading them back: $0.0147 then $0.0089, a 66%
hit ratio on the second call. Both suggestions quoted real GDS text verbatim
("You must use TLS 1.2 or above to secure your API."). Spec unmutated.

Two tests that pinned the empty corpus were updated rather than deleted — both carried
"update this when the corpus is authored" notes, which is why they were easy to find.
One of my replacements asserted section text against `CliRunner` output and failed on
Rich's 80-column wrapping; rewritten to render at an explicit width, since otherwise it
was a layout test masquerading as a content test.

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

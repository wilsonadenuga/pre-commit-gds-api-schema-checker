# gds-api-schema-uplift

A pre-commit guardrail for developers building GDS-standard APIs. It reads an
OpenAPI 3.x spec, checks it against the GDS + NCSC standards, and — where the spec
falls short — has a Claude agent propose fixes that you approve interactively before
anything is written to disk.

**Status: Phase 1 complete.** The five `GDS-*` deterministic rules, the version gate,
and the findings report all work. Citations do not resolve yet — the standards corpus
is authored in Phase 2 — and nothing is written to disk until Phase 4. See
[PLAN.md](PLAN.md) for the phase sequence and [PRD.md](PRD.md) for scope and
rationale.

## Quickstart

```bash
make setup                       # create .venv and install the CLI (editable)
make test                        # run the suite
make demo                        # run against examples/broken.yaml
make demo-good                   # run against examples/good.yaml
```

`make setup` uses [uv](https://docs.astral.sh/uv/) when it is on the PATH and falls
back to stdlib `venv` + `pip` when it is not.

## Usage

```
gds-api-schema-uplift SPEC_PATH [OPTIONS]

  --format [text|json|github]  Report format. `github` is a Phase 8 stretch item and
                               currently exits with an error rather than falling back.
  --no-llm                     Deterministic pass only; never call the agent.
  --max-llm-calls INTEGER      Cap agent calls per run. [default: 5]
  --standards PATH             Override the standards.yaml path.
```

Exit codes: `0` clean, `1` findings present, `3` operational failure.

## What is covered

| Rule | Check | Severity |
|---|---|---|
| `GDS-001` | Every declared server URL uses `https://` | error |
| `GDS-002` | Date/time-named string properties declare `format: date`/`date-time`/`time` | warning |
| `GDS-003` | A version segment appears in the URI path (or in every server URL) | warning |
| `GDS-004` | Response bodies are JSON (`application/json` or a `+json` type) | warning |
| `GDS-005` | Error responses use RFC 9457 problem details, on standard status codes | warning |

Not yet implemented: `NCSC-001`–`NCSC-004` (Phase 5a) and `REC-001`/`REC-002`
(Phase 5b). Two parts of the PRD wording are not machine-checkable from an OpenAPI
document and are deliberately out of scope, documented in the relevant modules:
GDS-001's "TLS 1.2+" and GDS-004's "UTF-8 encoding".

Version policy (PRD s7.3): OpenAPI 3.1 passes clean, 3.0 passes with an upgrade note,
Swagger 2.0 is refused with exit code 3 rather than reported as clean.

`REC-*` rules are conventions with no GDS or NCSC anchor. They are cited to external
references and are rendered as explicitly not GDS-mandated. This distinction is
carried in the data (`authority: recommendation` in `standards.yaml`), not in the
renderer.

A full coverage table — what is checked, what is a recommendation, what is out of
scope — lands with Phase 7.

## Repository layout

```
src/gds_api_schema_uplift/
  contracts.py                        Finding / Patch / Severity / RuleType / Authority
  loader.py                           spec load via ruamel round-trip, plus the version gate
  standards.py                        standards.yaml schema, validation, static clause lookup
  report.py                           text and JSON renderers
  cli.py                              Typer entrypoint
  rules/
    _registry.py                      registration, lookup, and the deterministic pass
    _traversal.py                     shared spec walking and JSONPath construction
    gds_001_https_only.py             one module per rule, named for what it checks
    gds_002_iso8601_datetimes.py
    gds_003_uri_path_versioning.py
    gds_004_json_response_bodies.py
    gds_005_problem_details_errors.py
standards.yaml                        the clause corpus — schema frozen, content is Phase 2
examples/
  broken.yaml                         one unambiguous violation per v0.2 rule
  good.yaml                           compliant; zero findings, and the round-trip fixture
tests/
  example_specs.py                    fixture paths and spec-writing helpers (not a test)
  test_contracts.py                   the frozen data contracts
  test_spec_loading.py                load failure modes and the version gate
  test_example_spec_quality.py        the fixtures themselves
  test_standards.py                   standards.yaml schema and clause lookup
  test_rule_registry.py               what is registered, and metadata consistency
  test_ruleset_behaviour.py           cross-rule properties of the whole pass
  test_rule_robustness.py             no rule raises on a structurally odd spec
  test_cli.py                         exit codes, flags, rendered output
  test_gds_00N_*.py                   one unit-test module per rule
```

Rule modules and their tests are named `<rule_id>_<what_it_checks>`, so a filename
says what the rule does while the directory still sorts by rule id. Test modules are
named for the subject under test rather than the build phase that introduced them —
phases expire, subjects do not.

## Not in scope

No IDE plugin, no hosted service, no auth, no multi-tenancy, no auto-apply mode, and
no AsyncAPI/GraphQL/gRPC support. See PRD s7.4.

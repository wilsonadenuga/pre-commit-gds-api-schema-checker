# gds-api-schema-uplift

A pre-commit guardrail for developers building GDS-standard APIs. It reads an
OpenAPI 3.x spec, checks it against the GDS + NCSC standards, and — where the spec
falls short — has a Claude agent propose fixes that you approve interactively before
anything is written to disk.

**Status: Phase 0 complete.** The scaffold, the frozen data contracts, and the
fixtures are in place. No rules ship yet, so the tool currently loads a spec and
reports zero findings. See [PLAN.md](PLAN.md) for the phase sequence and
[PRD.md](PRD.md) for scope and rationale.

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

Nothing yet — the rule registry is empty until Phase 1. The v0.2 ruleset target is 9
hard rules (`GDS-001`–`GDS-005`, `NCSC-001`–`NCSC-004`) plus 2 recommendations
(`REC-001`, `REC-002`), defined in PRD s7.2.

`REC-*` rules are conventions with no GDS or NCSC anchor. They are cited to external
references and are rendered as explicitly not GDS-mandated. This distinction is
carried in the data (`authority: recommendation` in `standards.yaml`), not in the
renderer.

A full coverage table — what is checked, what is a recommendation, what is out of
scope — lands with Phase 7.

## Repository layout

```
src/gds_api_schema_uplift/
  contracts.py     Finding / Patch / Severity / RuleType / Authority — frozen in Phase 0
  loader.py        comment-preserving spec load via ruamel.yaml round-trip
  standards.py     standards.yaml schema, validation, static clause lookup
  rules/           the rule registry (empty until Phase 1)
  report.py        text and JSON renderers
  cli.py           Typer entrypoint
standards.yaml     the clause corpus — schema frozen, content authored in Phase 2
examples/
  broken.yaml      one unambiguous violation per v0.2 rule
  good.yaml        compliant; must produce zero findings, and is the round-trip fixture
```

## Not in scope

No IDE plugin, no hosted service, no auth, no multi-tenancy, no auto-apply mode, and
no AsyncAPI/GraphQL/gRPC support. See PRD s7.4.

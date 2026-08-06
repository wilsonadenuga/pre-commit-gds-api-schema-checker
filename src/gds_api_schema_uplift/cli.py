"""Typer entrypoint.

Phase 4 adds the interactive approval loop: findings run → agent proposes patches
→ developer approves each patch one at a time → approved patches are written
back with a `.bak` alongside. The path from spec to report is unchanged; the
new machinery lives in `approval.py` behind `--no-apply` / interactive mode.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console

from .agent.client import DEFAULT_MODEL
from .agent.prompts import build_system_blocks, cache_warning
from .contracts import Suggestion
from .loader import SpecLoadError, SpecVersionRejected, load_spec, version_gate
from .report import render_json, render_text
from .rules import run_deterministic_pass
from .standards import StandardsError, default_standards_path, load_standards

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance for type hints only
    from .agent import AgentRun

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Check an OpenAPI spec against the GDS + NCSC API standards.",
)


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    GITHUB = "github"


class Effort(str, Enum):
    """Agent reasoning effort. Defaults low — a patch proposal is a scoped task, and
    demo latency is a stated risk (PRD s11)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


# Exit codes. 0/1 are the useful distinction for a pre-commit hook; 2 is Typer's
# own usage-error code, so operational failures use 3 to stay out of its way.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 3

#: Environment kill switch for the agent pass, equivalent to `--no-llm`.
#:
#: Exists because the agent runs by default: a test suite, a CI job, or a pre-commit
#: hook on a shared runner would otherwise spend real tokens the moment a credential
#: happens to be present in the environment. `tests/conftest.py` sets this for the
#: whole suite, so no test can reach the network by accident.
NO_LLM_ENV = "GDS_UPLIFT_NO_LLM"


def _llm_disabled(no_llm_flag: bool) -> bool:
    """True when the agent pass must not run."""
    if no_llm_flag:
        return True
    value = os.environ.get(NO_LLM_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no")


@app.command()
def check(
    spec_path: Annotated[
        Path,
        typer.Argument(
            exists=False,
            help="Path to an OpenAPI 3.x YAML or JSON spec.",
            show_default=False,
        ),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Report format."),
    ] = OutputFormat.TEXT,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Deterministic pass only; never call the agent."),
    ] = False,
    max_llm_calls: Annotated[
        int,
        typer.Option(
            "--max-llm-calls",
            min=0,
            help="Cap agent calls per run (PRD s11 cost mitigation).",
        ),
    ] = 5,
    no_apply: Annotated[
        bool,
        typer.Option(
            "--no-apply",
            help=(
                "Report-only mode: print findings and suggestions, never prompt "
                "or write to disk. Implied by --format=json."
            ),
        ),
    ] = False,
    standards_path: Annotated[
        Path | None,
        typer.Option("--standards", help="Override the standards.yaml path."),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help="Anthropic model id for the agent pass."),
    ] = DEFAULT_MODEL,
    effort: Annotated[
        Effort,
        typer.Option("--effort", help="Agent reasoning effort. Higher costs more."),
    ] = Effort.LOW,
) -> None:
    """Run the compliance check and print a report.

    Exits 0 when clean, 1 when there are findings, 3 on an operational failure.
    """
    console = Console()
    err = Console(stderr=True)

    if output_format is OutputFormat.GITHUB:
        err.print(
            "[red]--format=github is not implemented.[/red] It is a Phase 8 stretch "
            "item; use --format=json for machine-readable output."
        )
        raise typer.Exit(EXIT_ERROR)

    try:
        spec = load_spec(spec_path)
    except SpecLoadError as exc:
        err.print(f"[red]Could not load spec:[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from None

    # PRD s7.3 version policy. A rejection is an operational failure, not a finding:
    # we have not assessed compliance, so exiting 1 would misreport a clean spec.
    try:
        upgrade_note = version_gate(spec)
    except SpecVersionRejected as exc:
        err.print(f"[red]Unsupported spec version:[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from None
    if upgrade_note and output_format is not OutputFormat.JSON:
        err.print(f"[yellow]Note:[/yellow] {upgrade_note}")

    corpus_path = standards_path or default_standards_path()
    try:
        standards = load_standards(corpus_path)
    except StandardsError as exc:
        err.print(f"[red]Could not load standards corpus:[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from None

    findings = run_deterministic_pass(spec)

    suggestions: list[Suggestion] = []
    agent_run: AgentRun | None = None
    if findings and not _llm_disabled(no_llm) and max_llm_calls > 0:
        agent_run, suggestions = _run_agent(
            spec=spec,
            findings=findings,
            standards=standards,
            model=model,
            effort=effort.value,
            max_llm_calls=max_llm_calls,
            # Advisory notes go to stderr, but keep the agent quiet under
            # --format=json so stdout stays parseable for a CI consumer.
            err=Console(stderr=True, quiet=output_format is OutputFormat.JSON),
        )

    if output_format is OutputFormat.JSON:
        console.print_json(render_json(spec, findings, standards, suggestions))
        raise typer.Exit(EXIT_FINDINGS if findings else EXIT_OK)

    # Interactive mode is the default; --no-apply and --format=json opt into
    # report-only. When we're going to prompt, render_text omits the suggestion
    # block so the approval loop can render each one against its prompt rather
    # than printing them twice.
    interactive = _should_run_approval_loop(
        suggestions=suggestions,
        no_apply=no_apply,
    )
    render_text(
        spec,
        findings,
        standards,
        suggestions,
        console=console,
        include_suggestions=not interactive,
    )
    if agent_run is not None:
        agent_run.cost.render(console)

    exit_code = EXIT_FINDINGS if findings else EXIT_OK
    if interactive:
        from .approval import ApprovalSession

        session = ApprovalSession(spec, standards, console)
        outcome = session.run(suggestions)
        if outcome.any_writes:
            # The file on disk has been mutated by approvals; the original
            # `findings` list no longer reflects reality. Re-run the
            # deterministic pass to give an accurate exit code — a developer
            # who approved every fix should not be told the spec is still
            # dirty.
            fresh_findings = run_deterministic_pass(session.spec)
            exit_code = EXIT_FINDINGS if fresh_findings else EXIT_OK

    raise typer.Exit(exit_code)


def _should_run_approval_loop(
    *,
    suggestions: list[Suggestion],
    no_apply: bool,
) -> bool:
    """True when we should enter the interactive approval loop.

    Centralised because three conditions have to line up: `--no-apply` off, at
    least one offered suggestion in hand, and the agent actually produced a
    patch that survived the validation gate. A JSON caller never reaches this
    path — that exit ran earlier.
    """
    if no_apply:
        return False
    return any(s.offered and s.patch is not None for s in suggestions)


def _run_agent(
    *,
    spec,
    findings,
    standards,
    model: str,
    effort: str,
    max_llm_calls: int,
    err: Console,
) -> tuple[AgentRun | None, list[Suggestion]]:
    """Run the agent pass, degrading to no suggestions rather than failing the run.

    A compliance report that lists deterministic findings is useful on its own. An
    unreachable API, a missing key, or an unpriced model must therefore downgrade the
    run to deterministic-only with a clear note — never turn a working check into a
    non-zero exit.
    """
    from .agent import AgentConfig, AgentRun, build_messages_api, propose_for_findings

    config = AgentConfig(model=model, effort=effort, max_llm_calls=max_llm_calls)
    run = AgentRun(config=config)

    warning = cache_warning(build_system_blocks(standards))
    if warning:
        err.print(f"[yellow]Note:[/yellow] {warning}")

    try:
        messages_api = build_messages_api()
    except Exception as exc:  # noqa: BLE001 - SDK raises a family of auth/config errors
        err.print(
            f"[yellow]Skipping the AI pass:[/yellow] could not construct the "
            f"Anthropic client ({type(exc).__name__}: {exc}). Deterministic findings "
            f"are unaffected."
        )
        return None, []

    try:
        suggestions = propose_for_findings(
            messages_api,
            spec=spec,
            findings=findings,
            standards=standards,
            run=run,
        )
    except Exception as exc:  # noqa: BLE001 - network/API errors must not fail the run
        err.print(
            f"[yellow]AI pass failed:[/yellow] {type(exc).__name__}: {exc}. "
            f"Deterministic findings are unaffected."
        )
        return run, []

    if run.patches_dropped:
        err.print(
            f"[yellow]Note:[/yellow] {run.patches_dropped} proposed patch(es) were "
            f"dropped before display — they failed validation or were malformed."
        )
    return run, suggestions


if __name__ == "__main__":  # pragma: no cover
    app()

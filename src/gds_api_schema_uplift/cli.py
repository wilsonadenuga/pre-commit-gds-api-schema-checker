"""Typer entrypoint.

Phase 0 wires the flags and the load → rule pass → report path. The rule registry is
empty, the agent is not called, and nothing is written to disk. Later phases fill in
the middle without changing this shape.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .loader import SpecLoadError, SpecVersionRejected, load_spec, version_gate
from .report import render_json, render_text
from .rules import run_deterministic_pass
from .standards import StandardsError, default_standards_path, load_standards

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Check an OpenAPI spec against the GDS + NCSC API standards.",
)


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    GITHUB = "github"


# Exit codes. 0/1 are the useful distinction for a pre-commit hook; 2 is Typer's
# own usage-error code, so operational failures use 3 to stay out of its way.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 3


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
    standards_path: Annotated[
        Path | None,
        typer.Option("--standards", help="Override the standards.yaml path."),
    ] = None,
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

    # The agent path lands in Phase 3. Flags are accepted now so the interface is
    # stable, but say plainly that they currently do nothing rather than implying
    # an LLM pass ran.
    if not no_llm and max_llm_calls > 0:
        from .rules import llm_rules

        if llm_rules():
            err.print(
                "[yellow]Note:[/yellow] LLM-type rules are registered but the agent "
                "is not wired up until Phase 3; their findings are not produced."
            )

    if output_format is OutputFormat.JSON:
        console.print_json(render_json(spec, findings, standards))
    else:
        render_text(spec, findings, standards, console=console)

    raise typer.Exit(EXIT_FINDINGS if findings else EXIT_OK)


if __name__ == "__main__":  # pragma: no cover
    app()

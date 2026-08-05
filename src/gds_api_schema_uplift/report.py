"""Findings report rendering.

Phase 0 ships the text renderer and the JSON renderer. The `github` format is a
Phase 8 stretch item and is rejected explicitly rather than silently falling back,
so nobody builds a CI integration on top of a lie.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from .contracts import Authority, Finding, Severity
from .loader import LoadedSpec
from .standards import Standards, StandardsError

SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.SUGGESTION: "cyan",
}


def _clause_cell(finding: Finding, standards: Standards | None) -> str:
    """Render the citation cell, marking recommendations as non-mandated.

    A finding whose clause does not resolve is shown as such rather than hidden —
    an uncited finding is a bug, and the report is where it should be visible.
    """
    if standards is None:
        return finding.clause_id
    try:
        clause = standards.resolve(finding.clause_id)
    except StandardsError:
        return f"[red]{finding.clause_id} (unresolved)[/red]"
    label = f"{clause.clause_id} — {clause.section}"
    if clause.authority is Authority.RECOMMENDATION:
        label += " [dim](recommendation, not GDS-mandated)[/dim]"
    return label


def render_text(
    spec: LoadedSpec,
    findings: Sequence[Finding],
    standards: Standards | None = None,
    console: Console | None = None,
) -> None:
    """Print the human-facing report."""
    console = console or Console()
    console.print(f"[bold]{spec.path}[/bold]  [dim]({spec.version_label})[/dim]")

    if not findings:
        console.print("[green]No findings.[/green] Spec is clean against the loaded ruleset.")
        _print_ruleset_note(console, standards)
        return

    table = Table(show_lines=False, header_style="bold")
    table.add_column("Rule")
    table.add_column("Severity")
    table.add_column("Location")
    table.add_column("Citation")

    for finding in findings:
        table.add_row(
            finding.rule_id,
            f"[{SEVERITY_STYLE[finding.severity]}]{finding.severity.value}[/]",
            finding.location,
            _clause_cell(finding, standards),
        )
    console.print(table)

    counts = {s: sum(1 for f in findings if f.severity is s) for s in Severity}
    console.print(
        f"[bold]{len(findings)}[/bold] finding(s): "
        f"{counts[Severity.ERROR]} error, "
        f"{counts[Severity.WARNING]} warning, "
        f"{counts[Severity.SUGGESTION]} suggestion"
    )


def _print_ruleset_note(console: Console, standards: Standards | None) -> None:
    """Say how many rules actually ran.

    "No findings" is only meaningful alongside the size of the ruleset that
    produced it. With an empty registry it means nothing at all, and the report
    should admit that rather than read as a pass.
    """
    from .rules import REGISTRY

    if not REGISTRY:
        console.print(
            "[yellow]Note:[/yellow] the rule registry is empty, so this is not a "
            "compliance pass — no rules ran. Rules land in Phase 1."
        )
    if standards is not None and len(standards) == 0:
        console.print(
            "[yellow]Note:[/yellow] the standards corpus is empty, so no citations "
            "can be resolved. The corpus is authored in Phase 2."
        )


def render_json(
    spec: LoadedSpec,
    findings: Sequence[Finding],
    standards: Standards | None = None,
) -> str:
    """Serialise the report for machine consumption and for golden files."""
    payload = {
        "spec": str(spec.path),
        "openapi_version": spec.openapi_version,
        "swagger_version": spec.swagger_version,
        "rules_run": _rules_run(),
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "location": f.location,
                "snippet": f.snippet,
                "clause_id": f.clause_id,
                "rule_type": f.rule_type.value,
            }
            for f in findings
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _rules_run() -> int:
    from .rules import REGISTRY

    return len(REGISTRY)

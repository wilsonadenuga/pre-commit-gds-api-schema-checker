"""Findings report rendering.

Phase 0 ships the text renderer and the JSON renderer. The `github` format is a
Phase 8 stretch item and is rejected explicitly rather than silently falling back,
so nobody builds a CI integration on top of a lie.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .contracts import Authority, Finding, Severity, Suggestion
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


def render_good_examples(findings: Sequence[Finding], console: Console) -> None:
    """Render one "How to fix" panel per distinct rule id that fired.

    Grouping by rule id means `GDS-002` firing on three date-named fields
    produces one example panel — the fix pattern is the same regardless of
    how many places it applies. Ordering is by rule id so the panels line up
    with the report table above and the goldens stay stable.

    Silent when there are no findings: nothing to fix, nothing to show.
    """
    from .rules import REGISTRY

    if not findings:
        return

    seen: list[str] = []
    for finding in findings:
        if finding.rule_id in seen:
            continue
        if finding.rule_id not in REGISTRY:
            continue
        seen.append(finding.rule_id)

    if not seen:
        return

    console.print()
    for rule_id in sorted(seen):
        rule = REGISTRY[rule_id]
        # Rich's Syntax highlighter renders the YAML with colours in a real
        # terminal and degrades gracefully to plain text under CliRunner.
        yaml_block = Syntax(
            rule.good_example.rstrip(),
            "yaml",
            theme="ansi_dark",
            background_color="default",
        )
        body = Table.grid(padding=(0, 0))
        body.add_row(f"[dim]{rule.summary}[/dim]")
        body.add_row("")
        body.add_row(yaml_block)
        console.print(
            Panel(
                body,
                title=f"How to fix — {rule_id}",
                border_style="dim",
                title_align="left",
            )
        )


def render_suggestions(
    suggestions: Sequence[Suggestion],
    console: Console,
) -> None:
    """Render agent proposals that survived the validation gate.

    Dropped proposals are summarised by count and reason rather than shown as fixes.
    A patch that failed validation is not a suggestion — offering it would put an
    invalid spec one keystroke away.
    """
    if not suggestions:
        return

    offered = [s for s in suggestions if s.offered]
    dropped = [s for s in suggestions if not s.offered]

    for suggestion in offered:
        patch = suggestion.patch
        assert patch is not None  # offered implies a patch
        body = [f"[bold]{suggestion.finding.rule_id}[/bold]  {suggestion.finding.location}"]
        if patch.clause_quote:
            body.append(f'\n[dim]clause:[/dim] "{patch.clause_quote}"')
        else:
            body.append("\n[red]clause: (none — suggestion is uncited)[/red]")
        body.append(f"\n[dim]why:[/dim] {patch.rationale}")
        if suggestion.diff:
            body.append(f"\n\n{suggestion.diff}")
        console.print(Panel("".join(body), title="AI suggestion", border_style="cyan"))

    uncited = [s for s in offered if not s.has_citation]
    if uncited:
        console.print(
            f"[red]{len(uncited)} suggestion(s) carry no clause citation[/red] — "
            f"this breaks the citation requirement and is a bug, not a style issue."
        )

    if dropped:
        console.print(
            f"[dim]{len(dropped)} proposal(s) dropped before display:[/dim] "
            + ", ".join(
                f"{s.finding.rule_id} ({s.stage or 'unknown'})" for s in dropped
            )
        )


def render_text(
    spec: LoadedSpec,
    findings: Sequence[Finding],
    standards: Standards | None = None,
    suggestions: Sequence[Suggestion] = (),
    console: Console | None = None,
    *,
    include_suggestions: bool = True,
) -> None:
    """Print the human-facing report.

    `include_suggestions=False` renders findings only, leaving suggestions for
    the caller to display. Phase 4's interactive approval loop uses that path
    so the loop can render each suggestion inline against a prompt, rather
    than having them printed twice — once here, once by the loop.
    """
    console = console or Console()
    console.print(f"[bold]{spec.path}[/bold]  [dim]({spec.version_label})[/dim]")

    if not findings:
        console.print("[green]No findings.[/green] Spec is clean against the loaded ruleset.")
        _print_ruleset_note(console, standards)
        return

    table = Table(show_lines=True, header_style="bold")
    table.add_column("Rule", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Line", no_wrap=True, justify="right")
    table.add_column("Location", overflow="fold")
    table.add_column("Snippet", overflow="fold")
    table.add_column("Citation", overflow="fold")

    for finding in findings:
        # Format line as `Ln`, or dim `–` when the resolver could not find it.
        # A dedicated column keeps the number visible even when the JSONPath
        # column wraps hard; a developer's eye lands on it first.
        line_cell = f"L{finding.line}" if finding.line is not None else "[dim]–[/dim]"
        table.add_row(
            finding.rule_id,
            f"[{SEVERITY_STYLE[finding.severity]}]{finding.severity.value}[/]",
            line_cell,
            finding.location,
            finding.snippet,
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
    _print_ruleset_note(console, standards)
    render_good_examples(findings, console)
    if include_suggestions:
        render_suggestions(suggestions, console)


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
    suggestions: Sequence[Suggestion] = (),
) -> str:
    """Serialise the report for machine consumption and for golden files."""
    payload = {
        "spec": str(spec.path),
        "openapi_version": spec.openapi_version,
        "swagger_version": spec.swagger_version,
        "rules_run": _rules_run(),
        # Fix examples keyed by rule id, deduped, for the rules that fired.
        # Top-level (not per-finding) keeps the JSON small — three findings
        # from the same rule share one example — and matches the text
        # renderer's "one panel per rule" grouping.
        "good_examples": _good_examples_for(findings),
        "suggestions": [
            {
                "rule_id": s.finding.rule_id,
                "offered": s.offered,
                "stage": s.stage,
                "drop_reason": s.drop_reason,
                "has_citation": s.has_citation,
                "clause_quote": s.patch.clause_quote if s.patch else None,
                "rationale": s.patch.rationale if s.patch else None,
                "ops": s.patch.to_rfc6902() if s.patch else None,
            }
            for s in suggestions
        ],
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "line": f.line,
                "column": f.column,
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


def _good_examples_for(findings: Sequence[Finding]) -> dict[str, str]:
    """Deduped map of `rule_id → good_example` for the rules that fired.

    Sorted key order (as inserted via sorted()) gives stable JSON output for
    goldens. Falls back to an empty dict when there are no findings, matching
    the text renderer's silent-when-clean behaviour.
    """
    from .rules import REGISTRY

    seen: set[str] = set()
    result: dict[str, str] = {}
    for rule_id in sorted({f.rule_id for f in findings}):
        if rule_id in seen or rule_id not in REGISTRY:
            continue
        seen.add(rule_id)
        result[rule_id] = REGISTRY[rule_id].good_example
    return result

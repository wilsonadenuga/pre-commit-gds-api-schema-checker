"""Findings report rendering.

Phase 0 ships the text renderer and the JSON renderer. The `github` format is a
Phase 8 stretch item and is rejected explicitly rather than silently falling back,
so nobody builds a CI integration on top of a lie.

The text layout is one block per finding — problem, evidence, fix and source
together — so a developer never has to match a table row to a panel further down.
The summary comes last, where the eye lands when the output stops.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax

from .contracts import Authority, Finding, Severity, Suggestion
from .loader import LoadedSpec
from .standards import Standards, StandardsError

#: Symbol and colour per severity. Colour goes on the header only, so it marks
#: where each problem starts without making the whole report shout.
SEVERITY_STYLE = {
    Severity.ERROR: ("✖", "bold red"),
    Severity.WARNING: ("▲", "yellow"),
    Severity.SUGGESTION: ("●", "cyan"),
}

#: Fields that only describe the API. Editing them cannot make the spec disagree
#: with the running implementation; editing anything else can.
_DOC_FIELDS = frozenset({"summary", "description", "title"})

API_CHANGE_WARNING = (
    "⚠ This changes the API contract. Update the API implementation to match, "
    "or the spec and the API will disagree."
)


def plural(count: int, word: str, many: str | None = None) -> str:
    """`1 error`, `2 errors` — the report reads as prose, not as `error(s)`."""
    return f"{count} {word}" if count == 1 else f"{count} {many or word + 's'}"


def changes_the_api(suggestion: Suggestion) -> bool:
    """True unless every op only edits a documentation field."""
    assert suggestion.patch is not None
    for op in suggestion.patch.ops:
        parent, _, field_name = op.path.rpartition("/")
        # A schema property *named* `description` is data, not documentation.
        is_doc = field_name in _DOC_FIELDS and not parent.endswith("/properties")
        if op.from_ or not is_doc:
            return True
    return False


def _source_line(finding: Finding, standards: Standards | None) -> str:
    """Where the rule comes from, marking recommendations as non-mandated.

    A finding whose clause does not resolve is shown as such rather than hidden —
    an uncited finding is a bug, and the report is where it should be visible.
    """
    if standards is None:
        return f"[dim]Source:[/dim] {finding.clause_id}"
    try:
        clause = standards.resolve(finding.clause_id)
    except StandardsError:
        return f"[red]Source: {finding.clause_id} (unresolved)[/red]"
    line = f"[dim]Source:[/dim] {clause.section} [dim]· {clause.url}[/dim]"
    if clause.authority is Authority.RECOMMENDATION:
        line += "\n  [cyan]Recommendation only — not a GDS requirement.[/cyan]"
    return line


def _render_finding(
    finding: Finding,
    standards: Standards | None,
    console: Console,
    *,
    show_fix: bool,
) -> None:
    from .rules import REGISTRY

    symbol, style = SEVERITY_STYLE[finding.severity]
    where = f"line {finding.line}" if finding.line is not None else finding.location
    console.print(
        f"[{style}]{symbol} {finding.rule_id}[/]  "
        f"[{style}]{finding.severity.value}[/] [dim]· {where}[/dim]"
    )

    rule = REGISTRY.get(finding.rule_id)
    if rule is not None:
        console.print(f"  {rule.summary}")
    console.print(f"  [dim]Found:[/dim] {finding.snippet}")
    if rule is not None and show_fix:
        console.print("  [dim]Fix:[/dim]")
        # Rich's Syntax highlighter renders the YAML with colours in a real
        # terminal and degrades gracefully to plain text under CliRunner.
        yaml_block = Syntax(
            rule.good_example.rstrip(), "yaml", theme="ansi_dark",
            background_color="default",
        )
        console.print(Padding(yaml_block, (0, 0, 0, 4)))
    console.print(f"  {_source_line(finding, standards)}")
    console.print()


def render_suggestion(
    suggestion: Suggestion, console: Console, *, title: str = "AI fix"
) -> None:
    """One AI fix, laid out the same way in the report and the approval loop."""
    patch = suggestion.patch
    assert patch is not None  # offered implies a patch
    finding = suggestion.finding
    where = f"line {finding.line}" if finding.line is not None else finding.location

    body = [f"[bold]{finding.rule_id}[/bold] [dim]· {where}[/dim]"]
    if patch.clause_quote:
        body.append(f'\n[dim]Standard says:[/dim] "{patch.clause_quote}"')
    else:
        body.append("\n[red]Standard says: nothing — this fix is uncited, do not trust it.[/red]")
    body.append(f"\n[dim]What changes:[/dim] {patch.rationale}")
    if changes_the_api(suggestion):
        body.append(f"\n[yellow]{API_CHANGE_WARNING}[/yellow]")
    if suggestion.diff:
        body.append(f"\n\n{suggestion.diff}")

    console.print()
    console.print(Panel("".join(body), title=title, border_style="cyan"))


def render_suggestions(
    suggestions: Sequence[Suggestion],
    console: Console,
) -> None:
    """Render agent proposals that survived the validation gate.

    Dropped proposals are never shown — the CLI reports how many there were. A
    patch that failed validation is not a suggestion: offering it would put an
    invalid spec one keystroke away.
    """
    offered = [s for s in suggestions if s.offered]

    for index, suggestion in enumerate(offered, start=1):
        render_suggestion(suggestion, console, title=f"AI fix {index} of {len(offered)}")

    uncited = [s for s in offered if not s.has_citation]
    if uncited:
        console.print(
            f"[red]{plural(len(uncited), 'AI fix', 'AI fixes')} cite no standard[/red] — "
            f"that is a bug in the tool, not a style issue."
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
    console.print()

    if not findings:
        console.print("[green]✔ No problems found.[/green] The spec meets every rule checked.")
        _print_ruleset_note(console, standards)
        return

    # A rule that fires several times shares one fix example: the fix pattern is
    # the same wherever it applies.
    fixes_shown: set[str] = set()
    for finding in findings:
        _render_finding(
            finding, standards, console, show_fix=finding.rule_id not in fixes_shown
        )
        fixes_shown.add(finding.rule_id)

    if include_suggestions:
        render_suggestions(suggestions, console)

    counts = {s: sum(1 for f in findings if f.severity is s) for s in Severity}
    console.rule(style="dim")
    console.print(
        f"[bold]{plural(len(findings), 'finding')}[/bold]: "
        f"{plural(counts[Severity.ERROR], 'error')}, "
        f"{plural(counts[Severity.WARNING], 'warning')}, "
        f"{plural(counts[Severity.SUGGESTION], 'suggestion')}"
    )
    _print_ruleset_note(console, standards)


def _print_ruleset_note(console: Console, standards: Standards | None) -> None:
    """Say when the check could not mean anything.

    "No findings" is only meaningful alongside the size of the ruleset that
    produced it. With an empty registry it means nothing at all, and the report
    should admit that rather than read as a pass.
    """
    from .rules import REGISTRY

    if not REGISTRY:
        console.print(
            "[yellow]Note:[/yellow] no rules are registered, so this is not a "
            "compliance pass."
        )
    if standards is not None and len(standards) == 0:
        console.print(
            "[yellow]Note:[/yellow] the standards corpus is empty, so no citations "
            "can be resolved."
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
        # renderer's one-fix-per-rule grouping.
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

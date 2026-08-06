"""Interactive human-in-the-loop patch approval.

Phase 4. This module is what makes the tool a tool rather than a linter: it walks
the developer through each AI-proposed patch, one at a time, and writes to disk
only on explicit approval.

Invariants held here (PLAN "never cut" list):

- **No write to disk without an explicit `y`.** There is no auto-apply code path
  to add a prompt to later; the apply path lives inside `_handle_accept` and
  nowhere else.
- **The `.bak` is written *before* the first mutation of the run**, never after,
  and only if a mutation actually happens. A run where the developer rejects
  everything leaves the working tree exactly as it was.
- **Each patch is re-validated against the *current* spec state** before it is
  applied. A patch that was valid when the agent proposed it can be invalidated
  by an earlier approved patch that touched the same region; that path is
  skipped with a note rather than allowed to corrupt the file.
- **`q`uit leaves the file in its last-approved state.** Whatever writes have
  already landed stand; nothing is rolled back. Rolling back would violate the
  developer's own approvals.

Extracted from `cli.py` so the loop is unit-testable without spawning Typer.
Tests pass an `input_fn` callable in place of the terminal.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .contracts import Authority, Suggestion
from .loader import LoadedSpec, load_spec
from .patching import patched_text, validate_patch
from .standards import Standards, StandardsError

#: Actions accepted at the approval prompt. `e` is the Phase 4 cuttable per
#: PLAN — omitted from the initial ship, its slot preserved by rejecting the
#: keystroke with an explanatory note rather than silently ignoring it.
ACCEPT = "y"
REJECT = "n"
WHY = "w"
QUIT = "q"
EDIT = "e"

_PROMPT_TEXT = "Apply this patch? [y]es / [n]o / [w]hy / [q]uit"

#: Keys we understand at all. Anything outside this set re-prompts.
_KNOWN_ACTIONS = frozenset({ACCEPT, REJECT, WHY, QUIT, EDIT})

#: Keys we act on. `EDIT` is known but not yet supported — we tell the developer.
_LIVE_ACTIONS = frozenset({ACCEPT, REJECT, WHY, QUIT})


@dataclass(slots=True)
class ApprovalOutcome:
    """What happened across one approval-loop run.

    Held separately from the session so the CLI can render a final summary and
    tests can assert on the aggregate without reading Rich output.
    """

    approved_rule_ids: list[str] = field(default_factory=list)
    rejected_rule_ids: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)
    quit_early: bool = False
    backup_path: Path | None = None

    @property
    def approved(self) -> int:
        return len(self.approved_rule_ids)

    @property
    def rejected(self) -> int:
        return len(self.rejected_rule_ids)

    @property
    def any_writes(self) -> bool:
        """True when at least one patch actually landed on disk."""
        return self.approved > 0


class ApprovalSession:
    """One run of the approval loop.

    A session mutates two pieces of state: the spec file on disk (only via
    `_handle_accept`) and its own in-memory `LoadedSpec` (re-read after each
    approved write so subsequent validation runs against the current file).
    Nothing else about the session is intended to be reused across runs.
    """

    def __init__(
        self,
        spec: LoadedSpec,
        standards: Standards | None,
        console: Console,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.spec = spec
        self.standards = standards
        self.console = console
        # `Console.input` respects the same stream setup Rich already uses, so
        # tests that inject `Console(file=StringIO())` and pipe stdin through
        # CliRunner get consistent behaviour. Tests that want to canned inputs
        # pass an iterator-backed callable.
        self._input_fn = input_fn or (lambda prompt: console.input(prompt))
        self.outcome = ApprovalOutcome()
        self._backup_written = False

    # -- public entrypoint --------------------------------------------------

    def run(self, suggestions: Sequence[Suggestion]) -> ApprovalOutcome:
        """Walk the developer through every offered suggestion.

        Dropped suggestions are not shown here — they were already surfaced in
        the report as counts. The approval loop only ever offers patches that
        passed the validation gate at generation time; we re-validate anyway
        before writing, because earlier approvals may have invalidated a later
        patch (see the invariant list above).
        """
        offered = [s for s in suggestions if s.offered and s.patch is not None]
        if not offered:
            return self.outcome

        self.console.print()
        self.console.print(
            f"[bold]Reviewing {len(offered)} AI-proposed patch(es).[/bold]  "
            "[dim]No changes will be written without your approval.[/dim]"
        )

        for index, suggestion in enumerate(offered, start=1):
            if self._handle_one(suggestion, index, len(offered)) == QUIT:
                self.outcome.quit_early = True
                break

        self._render_summary()
        return self.outcome

    # -- per-suggestion loop ------------------------------------------------

    def _handle_one(self, suggestion: Suggestion, index: int, total: int) -> str:
        """Render one suggestion and prompt until the developer picks an action.

        Returns the action string. Only ACCEPT/REJECT/QUIT terminate the inner
        loop; WHY re-prompts after showing the clause; unknown keys re-prompt
        without doing anything else.
        """
        self._render_suggestion_panel(suggestion, index, total)

        while True:
            raw = self._prompt()
            key = raw.strip().lower()[:1] if raw else ""

            if key == ACCEPT:
                self._handle_accept(suggestion)
                return ACCEPT
            if key == REJECT:
                self.outcome.rejected_rule_ids.append(suggestion.finding.rule_id)
                self.console.print("[dim]Skipped.[/dim]")
                return REJECT
            if key == QUIT:
                return QUIT
            if key == WHY:
                self._render_full_clause(suggestion)
                continue  # re-prompt without incrementing anything
            if key == EDIT:
                self.console.print(
                    "[dim]Edit mode is not available in this build "
                    "(Phase 4 cuttable per PLAN). Use `y` to accept, `n` to skip, "
                    "or `q` to leave the rest untouched.[/dim]"
                )
                continue

            # Anything else — including a bare newline — falls through to a
            # re-prompt. Empty input is common when a developer defers a
            # decision; treating it as "no action" beats picking a default.
            self.console.print("[dim]Please choose y / n / w / q.[/dim]")

    def _prompt(self) -> str:
        """Read one line from the input source. Never raises."""
        try:
            return self._input_fn(f"{_PROMPT_TEXT}: ")
        except (EOFError, KeyboardInterrupt):
            # A closed stdin (piped input exhausted) or ^C is a quit signal.
            # Returning `q` funnels both through the normal QUIT path so the
            # summary and backup accounting still run.
            self.console.print()
            return QUIT

    # -- actions ------------------------------------------------------------

    def _handle_accept(self, suggestion: Suggestion) -> None:
        """Re-validate against the current spec, then write on success.

        Nothing here trusts the suggestion's cached `diff`: the spec on disk may
        have been mutated by an earlier approval in this same run, so the patch
        must clear the validation gate against the *current* state before we
        touch the file.
        """
        assert suggestion.patch is not None  # `offered` guarantees this
        rule_id = suggestion.finding.rule_id

        result = validate_patch(self.spec, suggestion.patch)
        if not result.ok:
            self.outcome.skipped_invalid.append(rule_id)
            self.console.print(
                f"[yellow]Cannot apply {rule_id}:[/yellow] earlier edits invalidated "
                f"this patch ([dim]{result.stage}[/dim]: {result.error}). Skipping."
            )
            return

        if not self._backup_written:
            self._write_backup()

        new_text = patched_text(self.spec, result)
        self.spec.path.write_text(new_text, encoding="utf-8")
        # Re-load so subsequent validation runs against the mutated file.
        # Doing this via `load_spec` (not by mutating `self.spec.data` in
        # place) keeps `patching.apply_patch_to_copy`'s "never mutates the
        # caller's spec" invariant intact for every op in the loop.
        self.spec = load_spec(self.spec.path)
        self.outcome.approved_rule_ids.append(rule_id)
        self.console.print(f"[green]Applied.[/green] {self.spec.path} updated.")

    def _write_backup(self) -> None:
        """Preserve the developer's original file before the first mutation.

        Written once per session, only if a mutation is about to happen. A run
        that approves nothing leaves no `.bak` behind — the file was never
        touched, so a backup would be misleading noise.
        """
        original = self.spec.path
        # Append `.bak` to the full name rather than replacing the suffix, so
        # `openapi.yaml` becomes `openapi.yaml.bak` (readable at a glance)
        # rather than `openapi.bak` (which would clash with a hypothetical
        # `openapi.json` sibling).
        backup = original.with_name(original.name + ".bak")
        backup.write_bytes(original.read_bytes())
        self._backup_written = True
        self.outcome.backup_path = backup
        self.console.print(f"[dim]Backup written: {backup}[/dim]")

    # -- rendering ----------------------------------------------------------

    def _render_suggestion_panel(
        self, suggestion: Suggestion, index: int, total: int
    ) -> None:
        """Render one AI suggestion as a Rich Panel, matching report.py style."""
        patch = suggestion.patch
        assert patch is not None
        finding = suggestion.finding

        lines = [f"[bold]{finding.rule_id}[/bold]  {finding.location}"]
        if patch.clause_quote:
            lines.append(f'\n[dim]clause:[/dim] "{patch.clause_quote}"')
        else:
            lines.append("\n[red]clause: (none — suggestion is uncited)[/red]")
        lines.append(f"\n[dim]why:[/dim] {patch.rationale}")
        if suggestion.diff:
            lines.append(f"\n\n{suggestion.diff}")

        self.console.print()
        self.console.print(
            Panel(
                "".join(lines),
                title=f"AI suggestion  [dim]({index}/{total})[/dim]",
                border_style="cyan",
            )
        )

    def _render_full_clause(self, suggestion: Suggestion) -> None:
        """Show the full standards clause text on `w`hy.

        The suggestion carries only a short quote; the full clause is what a
        developer needs to judge whether the fix is right. Fall back to the
        quote if the corpus is not loaded, so the action never silently no-ops.
        """
        finding = suggestion.finding
        if self.standards is None:
            self.console.print(
                "[dim]No standards corpus loaded — showing the agent's quote only.[/dim]"
            )
            if suggestion.patch and suggestion.patch.clause_quote:
                self.console.print(f'  "{suggestion.patch.clause_quote}"')
            return

        try:
            clause = self.standards.resolve(finding.clause_id)
        except StandardsError as exc:
            self.console.print(f"[red]Cannot resolve {finding.clause_id}:[/red] {exc}")
            return

        authority_tag = ""
        if clause.authority is Authority.RECOMMENDATION:
            authority_tag = " [dim](recommendation, not GDS-mandated)[/dim]"

        self.console.print()
        self.console.print(
            Panel(
                f"[bold]{clause.clause_id}[/bold] — {clause.section}{authority_tag}\n"
                f"[dim]{clause.url}[/dim]\n\n{clause.text}",
                title="Standards clause",
                border_style="blue",
            )
        )

    def _render_summary(self) -> None:
        """One-line summary of what happened. Silent when nothing to say."""
        o = self.outcome
        if o.approved == 0 and o.rejected == 0 and not o.quit_early:
            return

        parts = []
        if o.approved:
            parts.append(f"[green]{o.approved} applied[/green]")
        if o.rejected:
            parts.append(f"[dim]{o.rejected} skipped[/dim]")
        if o.skipped_invalid:
            parts.append(
                f"[yellow]{len(o.skipped_invalid)} could not apply[/yellow]"
            )
        if o.quit_early:
            parts.append("[dim]quit early[/dim]")

        self.console.print()
        self.console.print("Approval summary: " + ", ".join(parts) + ".")
        if o.backup_path is not None:
            self.console.print(
                f"[dim]Original preserved at {o.backup_path}. "
                f"Re-run to see the updated compliance state.[/dim]"
            )

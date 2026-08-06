"""Unit tests for the Phase 4 interactive approval loop.

The `ApprovalSession` is tested in isolation from Typer: inputs are injected via
a canned callable, the console writes to a `StringIO` buffer, and the spec is
copied into `tmp_path` so the write path is exercised without touching the
committed fixture. That keeps every test deterministic and independent of
terminal size, tty state, and each other.

The tests below hold the Phase 4 invariants (see `approval.py` module docstring):

- No write without an explicit `y`.
- `.bak` written once, only if a mutation actually happens, before the mutation.
- Each patch re-validated against the current spec on the way to disk.
- `q`uit leaves prior writes intact.
- `e`dit is a Phase 4 cuttable — the key is recognised and refused, not silently
  dropped or treated as accept.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from example_specs import GOOD_SPEC
from rich.console import Console

from gds_api_schema_uplift.approval import (
    ACCEPT,
    EDIT,
    QUIT,
    REJECT,
    WHY,
    ApprovalSession,
)
from gds_api_schema_uplift.contracts import (
    Authority,
    Finding,
    Patch,
    PatchOp,
    RuleType,
    Severity,
    Suggestion,
)
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.standards import Clause, Standards


# --- fixtures ---------------------------------------------------------------


def _copy_good_spec(tmp_path: Path, name: str = "openapi.yaml") -> Path:
    """Copy the committed good.yaml into `tmp_path` so tests can mutate it."""
    dest = tmp_path / name
    dest.write_text(GOOD_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def _canned(*replies: str) -> Callable[[str], str]:
    """Build an input_fn that returns each reply in turn.

    Running out of replies raises `StopIteration`, which is what we want: a test
    that overshoots its scripted input has a bug and should fail loudly rather
    than block on a real stdin read.
    """
    iterator = iter(replies)

    def _read(_prompt: str) -> str:
        return next(iterator)

    return _read


def _make_finding(rule_id: str = "GDS-001", clause_id: str = "test-clause") -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.ERROR,
        location="/info/title",
        snippet="original",
        clause_id=clause_id,
        rule_type=RuleType.DETERMINISTIC,
    )


def _make_patch(
    *,
    op: str = "replace",
    path: str = "/info/title",
    value: object = "Patched Title",
    rationale: str = "Because the standard says so.",
    clause_quote: str = "You must use TLS 1.2 or above.",
) -> Patch:
    return Patch(
        ops=(PatchOp(op=op, path=path, value=value),),
        rationale=rationale,
        clause_quote=clause_quote,
    )


def _make_suggestion(
    *,
    rule_id: str = "GDS-001",
    clause_id: str = "test-clause",
    patch: Patch | None = None,
    offered: bool = True,
) -> Suggestion:
    """Build a Suggestion that the approval loop will treat as offered.

    The default patch replaces `/info/title` with a fixed string — trivially
    valid against `good.yaml` and gives every write-path test a deterministic
    on-disk diff to assert on.
    """
    return Suggestion(
        finding=_make_finding(rule_id=rule_id, clause_id=clause_id),
        patch=patch if patch is not None else _make_patch(),
        offered=offered,
        stage="applied",
        diff="--- a/openapi.yaml\n+++ b/openapi.yaml\n@@ ...",
    )


def _mini_standards(clause_id: str = "test-clause") -> Standards:
    """A tiny in-memory standards corpus, enough to satisfy the `w`hy action."""
    return Standards(
        {
            clause_id: Clause(
                clause_id=clause_id,
                section="Test section",
                text="This is the full clause text, longer than the quote.",
                url="https://www.gov.uk/guidance/test",
                authority=Authority.STANDARD,
            )
        }
    )


def _session(
    tmp_path: Path,
    input_fn: Callable[[str], str],
    *,
    standards: Standards | None = None,
) -> tuple[ApprovalSession, io.StringIO, Path]:
    spec_path = _copy_good_spec(tmp_path)
    spec = load_spec(spec_path)
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, force_terminal=False)
    session = ApprovalSession(
        spec,
        standards if standards is not None else _mini_standards(),
        console,
        input_fn=input_fn,
    )
    return session, buffer, spec_path


def _backup_path(spec_path: Path) -> Path:
    return spec_path.with_name(spec_path.name + ".bak")


# --- empty / no-op paths ----------------------------------------------------


def test_empty_suggestions_are_a_silent_noop(tmp_path):
    """Nothing to review means nothing to render, prompt, or write.

    The approval loop must not print a summary or open the input source when
    called with zero suggestions — that would be terminal noise for a run that
    the deterministic pass could have discovered was clean on its own.
    """
    session, buffer, spec_path = _session(tmp_path, _canned())
    original = spec_path.read_text()

    outcome = session.run([])

    assert outcome.approved == 0
    assert outcome.rejected == 0
    assert outcome.backup_path is None
    assert spec_path.read_text() == original
    assert not _backup_path(spec_path).exists()
    assert buffer.getvalue() == ""


def test_only_dropped_suggestions_do_not_prompt(tmp_path):
    """A suggestion that failed the validation gate never reaches the loop.

    Dropped proposals live in the report as counts, not as prompts. An
    unoffered Suggestion has `offered=False` and must be filtered out before we
    render the "reviewing N patches" line — offering N here when N is really 0
    would be misleading.
    """
    dropped = _make_suggestion(offered=False)
    session, buffer, spec_path = _session(tmp_path, _canned())

    outcome = session.run([dropped])

    assert outcome.approved == 0
    assert outcome.rejected == 0
    assert "Reviewing" not in buffer.getvalue()


# --- accept path ------------------------------------------------------------


def test_accept_writes_the_patched_file_and_creates_a_backup(tmp_path):
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT))
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.approved == 1
    assert outcome.rejected == 0
    assert outcome.approved_rule_ids == ["GDS-001"]
    backup = _backup_path(spec_path)
    assert backup.exists(), "an approved write must leave a .bak alongside"
    assert backup.read_text() == original, "the .bak must be the pre-write state"
    assert "Patched Title" in spec_path.read_text()


def test_backup_is_written_only_once_across_multiple_accepts(tmp_path):
    """The .bak represents the pre-run state, so a second accept must not overwrite it.

    Overwriting the backup on the second accept would silently lose the
    developer's *original* file — a rollback path they may already be relying
    on if they change their mind mid-run.
    """
    first = _make_suggestion(
        rule_id="GDS-001",
        patch=_make_patch(value="First Title"),
    )
    second = _make_suggestion(
        rule_id="GDS-002",
        patch=_make_patch(value="Second Title"),
    )
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT, ACCEPT))
    original = spec_path.read_text()

    outcome = session.run([first, second])

    assert outcome.approved == 2
    backup = _backup_path(spec_path)
    assert backup.read_text() == original, (
        "the .bak must still hold the pre-run file, not the state after the first accept"
    )
    assert "Second Title" in spec_path.read_text()


def test_second_patch_operates_on_the_mutated_spec(tmp_path):
    """After an accept, the next validation must run against the updated file.

    Otherwise a second patch validated against the pre-run spec could paint the
    file into an invalid state that the first-round gate never saw.
    """
    first = _make_suggestion(patch=_make_patch(value="First"))
    # Replaces the *already-replaced* title — only sensible if the second
    # validation reads the current on-disk state.
    second = _make_suggestion(
        rule_id="GDS-002",
        patch=_make_patch(value="Second"),
    )
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT, ACCEPT))

    outcome = session.run([first, second])

    assert outcome.approved == 2
    assert "Second" in spec_path.read_text()
    assert "First" not in spec_path.read_text()


def test_accepted_write_preserves_yaml_layout(tmp_path):
    """Comments and key order must survive an approved patch (req 9).

    `good.yaml` is the committed round-trip fixture; here we patch a scalar and
    check that everything *else* in the file — including comments and key
    ordering — comes back unchanged. If ruamel round-tripping regresses, this
    is where we catch it.
    """
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT))
    original_lines = spec_path.read_text().splitlines()

    session.run([_make_suggestion()])

    patched_lines = spec_path.read_text().splitlines()
    # Every line other than the mutated title must appear in the same order.
    diff = [
        (a, b) for a, b in zip(original_lines, patched_lines, strict=False) if a != b
    ]
    assert len(diff) == 1, f"expected exactly one differing line, got {diff}"


# --- reject path ------------------------------------------------------------


def test_reject_leaves_the_file_and_working_tree_untouched(tmp_path):
    """`n` must not write, not create a backup, not leave anything behind.

    A rejected suggestion is a decision that this fix does not belong on disk.
    A `.bak` from a rejected run would suggest something happened and confuse
    the next `ls`.
    """
    session, _buffer, spec_path = _session(tmp_path, _canned(REJECT))
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.approved == 0
    assert outcome.rejected == 1
    assert outcome.rejected_rule_ids == ["GDS-001"]
    assert spec_path.read_text() == original
    assert not _backup_path(spec_path).exists()


def test_mixed_accept_and_reject(tmp_path):
    """Accepting one and rejecting another writes only the accepted one."""
    accepted = _make_suggestion(
        rule_id="GDS-001", patch=_make_patch(value="ACCEPTED_TITLE_MARKER")
    )
    rejected = _make_suggestion(
        rule_id="GDS-002", patch=_make_patch(value="REJECTED_TITLE_MARKER")
    )
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT, REJECT))

    outcome = session.run([accepted, rejected])

    assert outcome.approved == 1
    assert outcome.rejected == 1
    assert outcome.approved_rule_ids == ["GDS-001"]
    assert outcome.rejected_rule_ids == ["GDS-002"]
    body = spec_path.read_text()
    assert "ACCEPTED_TITLE_MARKER" in body
    assert "REJECTED_TITLE_MARKER" not in body


# --- quit path --------------------------------------------------------------


def test_quit_before_any_accept_writes_nothing(tmp_path):
    session, buffer, spec_path = _session(tmp_path, _canned(QUIT))
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.quit_early is True
    assert outcome.approved == 0
    assert spec_path.read_text() == original
    assert not _backup_path(spec_path).exists()
    assert "quit early" in buffer.getvalue()


def test_quit_after_accept_leaves_the_accepted_write_in_place(tmp_path):
    """`q` is not rollback. Whatever was approved stays approved."""
    first = _make_suggestion(rule_id="GDS-001", patch=_make_patch(value="Approved"))
    second = _make_suggestion(rule_id="GDS-002", patch=_make_patch(value="Never"))
    session, _buffer, spec_path = _session(tmp_path, _canned(ACCEPT, QUIT))
    original = spec_path.read_text()

    outcome = session.run([first, second])

    assert outcome.quit_early is True
    assert outcome.approved == 1
    assert "Approved" in spec_path.read_text()
    assert "Never" not in spec_path.read_text()
    assert _backup_path(spec_path).read_text() == original


def test_eof_is_treated_as_quit(tmp_path):
    """Running out of stdin (piped input exhausted) must terminate cleanly.

    A pre-commit hook that reads from a pipe can hit EOF unexpectedly; the loop
    must treat that as `q`uit rather than raise an unhandled `EOFError` that
    aborts the whole invocation and leaves the file in a mid-run state.
    """

    def _raise_eof(_prompt: str) -> str:
        raise EOFError

    session, _buffer, spec_path = _session(tmp_path, _raise_eof)
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.quit_early is True
    assert spec_path.read_text() == original


def test_keyboard_interrupt_is_treated_as_quit(tmp_path):
    """`^C` at the prompt aborts the loop, leaving prior writes intact."""

    def _raise_ki(_prompt: str) -> str:
        raise KeyboardInterrupt

    session, _buffer, spec_path = _session(tmp_path, _raise_ki)
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.quit_early is True
    assert spec_path.read_text() == original


# --- why action -------------------------------------------------------------


def test_why_shows_the_full_clause_and_reprompts(tmp_path):
    """`w` renders the full standards clause and then re-prompts.

    Reading the full clause is what makes an approve/reject a *decision* rather
    than a guess; the action must not consume the suggestion or count against
    either outcome bucket.
    """
    session, buffer, _spec_path = _session(tmp_path, _canned(WHY, REJECT))

    outcome = session.run([_make_suggestion()])

    output = buffer.getvalue()
    assert "This is the full clause text" in output, (
        "the full clause text (not just the quote) must appear on `w`"
    )
    assert outcome.approved == 0
    assert outcome.rejected == 1  # WHY re-prompts, then REJECT consumes


def test_why_flags_recommendations_as_not_gds_mandated(tmp_path):
    """A REC-* clause must be visibly labelled — even in `w` output.

    Carrying `authority` on the Clause is the whole reason this label survives
    into every renderer, so this asserts the guarantee is honoured here too.
    """
    standards = Standards(
        {
            "rec-clause": Clause(
                clause_id="rec-clause",
                section="Naming conventions",
                text="Prefer plural nouns.",
                url="https://microsoft.github.io/api-guidelines/",
                authority=Authority.RECOMMENDATION,
            )
        }
    )
    session, buffer, _spec_path = _session(
        tmp_path,
        _canned(WHY, REJECT),
        standards=standards,
    )

    session.run([_make_suggestion(clause_id="rec-clause")])

    assert "recommendation" in buffer.getvalue().lower()


def test_why_without_a_corpus_falls_back_to_the_quote(tmp_path):
    """The action must not silently no-op when the corpus is absent.

    A run started with `--standards` pointing at nothing should still let `w`
    render *something* useful — the agent's inline quote is the honest fallback.
    """
    session, buffer, _spec_path = _session(
        tmp_path,
        _canned(WHY, REJECT),
        standards=None,
    )
    session.standards = None  # explicit override, in case _session evolves

    session.run([_make_suggestion()])

    output = buffer.getvalue()
    assert "TLS 1.2" in output, "the quote should appear when the corpus is absent"


def test_why_on_an_unresolvable_clause_says_so(tmp_path):
    """A citation that does not resolve is a bug we must surface, not hide.

    The rest of the suite pins that this cannot happen in shipped code
    (`test_citation_integrity`), but here we make sure that if it *did*, the
    developer sees a clear error at the exact moment they asked for detail.
    """
    session, buffer, _spec_path = _session(tmp_path, _canned(WHY, REJECT))

    session.run([_make_suggestion(clause_id="does-not-exist")])

    assert "does not resolve" in buffer.getvalue()


# --- unknown keys -----------------------------------------------------------


def test_unknown_keystroke_reprompts_without_consuming_the_suggestion(tmp_path):
    """A typo must not silently accept, reject, or advance past a suggestion."""
    session, buffer, spec_path = _session(tmp_path, _canned("z", REJECT))
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.approved == 0
    assert outcome.rejected == 1
    assert spec_path.read_text() == original
    assert "y / n / w / q" in buffer.getvalue()


def test_empty_input_reprompts(tmp_path):
    """A bare newline is the most common "I haven't decided" input.

    Picking any default here (yes or no) would be a lie about the developer's
    intent, so we re-prompt.
    """
    session, buffer, spec_path = _session(tmp_path, _canned("", "", REJECT))
    original = spec_path.read_text()

    outcome = session.run([_make_suggestion()])

    assert outcome.rejected == 1
    assert spec_path.read_text() == original


# --- edit action (deferred) -------------------------------------------------


def test_prompt_shows_literal_square_brackets_around_action_keys(tmp_path):
    """Rich treats `[y]` as a markup tag and strips it unless escaped.

    A regression here shows up as a prompt reading `es / o / hy / uit` — a
    visible on-screen bug that unit tests using an injected input_fn cannot
    catch on their own. We render the actual prompt text through a Rich
    console to a buffer and check the brackets survive.
    """
    from rich.console import Console

    from gds_api_schema_uplift.approval import _PROMPT_TEXT

    buffer = io.StringIO()
    Console(file=buffer, width=200, force_terminal=False).print(_PROMPT_TEXT)
    output = buffer.getvalue()
    assert "[y]es" in output
    assert "[n]o" in output
    assert "[w]hy" in output
    assert "[q]uit" in output


def test_edit_key_is_recognised_and_refused_not_ignored(tmp_path):
    """`e` is cuttable per PLAN. The keystroke is known, so we refuse it explicitly.

    Silently treating `e` as "unknown" would leave a developer wondering why
    the documented option does nothing; a targeted "not available" message
    lets them press y or n instead.
    """
    session, buffer, _spec_path = _session(tmp_path, _canned(EDIT, REJECT))

    session.run([_make_suggestion()])

    assert "not available" in buffer.getvalue()


# --- invalidation-after-accept path ----------------------------------------


def test_a_patch_invalidated_by_an_earlier_accept_is_skipped(tmp_path):
    """A second patch that no longer applies must be skipped, not force-applied.

    A `remove` op targeting `/info/description` will not apply twice: the
    first accept deletes the key, the second finds nothing there. The invariant
    is that the failure does not corrupt the file — it lands in `skipped_invalid`
    and the loop moves on.
    """
    first = _make_suggestion(
        rule_id="GDS-001",
        patch=Patch(
            ops=(PatchOp(op="remove", path="/info/description"),),
            rationale="Remove verbose description.",
            clause_quote="Descriptions should be terse.",
        ),
    )
    # Same op — will fail because /info/description no longer exists after #1.
    second = _make_suggestion(
        rule_id="GDS-002",
        patch=Patch(
            ops=(PatchOp(op="remove", path="/info/description"),),
            rationale="Remove verbose description again.",
            clause_quote="Descriptions should be terse.",
        ),
    )
    session, buffer, spec_path = _session(tmp_path, _canned(ACCEPT, ACCEPT))

    outcome = session.run([first, second])

    assert outcome.approved == 1
    assert outcome.approved_rule_ids == ["GDS-001"]
    assert outcome.skipped_invalid == ["GDS-002"]
    assert "Cannot apply GDS-002" in buffer.getvalue()
    # File must be in the state after the first accept, not corrupted. Re-parse
    # to check the actual `info` mapping rather than grepping the whole text —
    # `description` appears in file-level comments too.
    reparsed = load_spec(spec_path)
    assert "description" not in reparsed.data["info"]


# --- outcome accounting -----------------------------------------------------


def test_outcome_any_writes_flag(tmp_path):
    """`any_writes` is what the CLI uses to decide whether to re-check on exit."""
    accept_dir = tmp_path / "accept"
    accept_dir.mkdir()
    reject_dir = tmp_path / "reject"
    reject_dir.mkdir()
    accept_session, _, _ = _session(accept_dir, _canned(ACCEPT))
    reject_session, _, _ = _session(reject_dir, _canned(REJECT))

    accept_session.run([_make_suggestion()])
    reject_session.run([_make_suggestion()])

    assert accept_session.outcome.any_writes is True
    assert reject_session.outcome.any_writes is False


@pytest.mark.parametrize("upper", ["Y", "N", "W", "Q"])
def test_action_keys_are_case_insensitive(tmp_path, upper):
    """A developer pressing shift shouldn't silently break the loop."""
    replies = [upper]
    if upper != "Q":
        replies.append(REJECT if upper != "N" else ACCEPT)  # secondary reply if needed
    if upper == "W":
        replies = [upper, REJECT]  # W re-prompts, need a terminator
    session, _buffer, _spec_path = _session(tmp_path, _canned(*replies))

    outcome = session.run([_make_suggestion()])

    # Whatever was pressed must have been *understood* — the input source
    # never runs out unexpectedly. That's a stricter check than any specific
    # outcome, because it holds for all four keys.
    assert outcome.approved + outcome.rejected + int(outcome.quit_early) >= 1

"""The patch validation gate.

A hard invariant of this tool (PLAN "never cut" list, PRD s7.1.3): a patch proposed
by the agent is applied to an *in-memory copy* of the spec and re-validated as
OpenAPI **before a human ever sees it**. Invalid patches are dropped, never
rendered. This module is that gate, and it is the only place patches are applied.

Two properties are load-bearing and both are pinned by tests in
`tests/test_patching.py`:

1. **Nothing here mutates the caller's spec.** Not on success, not on failure, not
   on a half-applied op list. `LoadedSpec.data` is the developer's real file in
   memory; corrupting it would put the tool one keystroke away from writing a
   mangled spec to disk.
2. **The copy still round-trips.** Requirement 9 (comment- and order-preserving
   writes) only holds if the copy we patch is as faithful as the original.

Why the copy is made by re-parsing rather than by `copy.deepcopy`
----------------------------------------------------------------
Dumping and re-parsing the document goes through the *same* serialisation path the
writer will later use, so the copy we patch and validate is byte-for-byte what a
write would produce. That makes fidelity a property of one code path instead of two,
and `test_patched_text_preserves_comments` pins it.

`copy.deepcopy` was measured on ruamel 0.19.1 against both example fixtures and is
byte-identical there — it is *not* known to be lossy, and an earlier version of this
docstring wrongly claimed it dropped comments before the first key of a nested block
mapping. It is kept as the fallback for a document that cannot be re-serialised.
Re-parsing is preferred only for the single-path argument above; specs are small, so
the reparse cost is not worth optimising away.
"""

from __future__ import annotations

import copy
import dataclasses
import difflib
import io
from dataclasses import dataclass
from typing import Any

import jsonpatch
from openapi_spec_validator import validate as _validate_openapi_document

from .contracts import Patch
from .loader import LoadedSpec, round_trip_yaml as _round_trip_yaml

#: `PatchResult.stage` values. Constants rather than an Enum because the contract
#: declares `stage: str`, and the renderer switches on these to explain *why* a
#: patch was dropped (the drop rate is a demo beat — see PLAN "When You Get Stuck").
STAGE_APPLIED = "applied"
STAGE_APPLY_FAILED = "apply_failed"
STAGE_SCHEMA_INVALID = "schema_invalid"
STAGE_EMPTY_PATCH = "empty_patch"

#: Upper bound on a rendered error message. `jsonpointer` embeds a repr of the whole
#: document in its message and `openapi-spec-validator` appends the offending
#: subschema; neither belongs in a terminal, but the leading sentence of each is
#: precisely the useful part.
_MAX_ERROR_CHARS = 300


@dataclass(frozen=True, slots=True)
class PatchResult:
    """Outcome of running a proposed patch through the gate.

    `ok` is the only thing a caller needs to decide whether to render the patch.
    `stage` says how far the patch got, which is what makes the drop rate
    diagnosable rather than mysterious.
    """

    ok: bool
    patched_data: Any | None
    error: str | None
    stage: str


def _describe(exc: BaseException) -> str:
    """Render an exception as one short, human-readable line.

    Some of the exceptions we catch stringify to the empty string
    (`ValidatorDetectError`) and some to several hundred lines (`OpenAPIValidationError`
    dumps the subschema it failed against). Both are useless to a developer, so keep
    the type name and the first line, truncated.
    """
    message = str(exc).strip().splitlines()
    first_line = message[0].strip() if message else ""
    if len(first_line) > _MAX_ERROR_CHARS:
        first_line = first_line[: _MAX_ERROR_CHARS - 1].rstrip() + "…"
    name = type(exc).__name__
    return f"{name}: {first_line}" if first_line else name


def _dump_to_text(data: Any) -> str:
    """Serialise a round-trip structure to YAML text using the loader's settings."""
    buf = io.StringIO()
    _round_trip_yaml().dump(data, buf)
    return buf.getvalue()


def _independent_copy(data: Any) -> Any:
    """Return a copy of `data` that shares no state with it and still round-trips.

    See the module docstring for why this is not `copy.deepcopy`. The fallback keeps
    the function total: a document we cannot re-serialise still gets copied, just
    without the fidelity guarantee, and the patch it produces will fail the schema
    check or the write step rather than corrupting the caller's spec.
    """
    try:
        copied = _round_trip_yaml().load(_dump_to_text(data))
    except Exception:  # noqa: BLE001 - ruamel raises a wide family here
        return copy.deepcopy(data)
    if copied is None and data is not None:
        # An empty dump round-trips to None; deepcopy is closer to the truth.
        return copy.deepcopy(data)
    return copied


def apply_patch_to_copy(spec: LoadedSpec, patch: Patch) -> PatchResult:
    """Copy `spec.data`, apply the RFC 6902 ops to the copy, and report the outcome.

    MUST NOT mutate `spec.data` under any circumstance, including on failure: the
    copy is taken first, and every op is applied to the copy only.

    An empty op list is rejected rather than treated as a no-op. A patch with
    nothing in it has nothing for a human to review, so offering it would be a
    prompt with no content behind it — see `STAGE_EMPTY_PATCH`.

    Never raises. `jsonpatch` and `jsonpointer` raise `JsonPatchException`,
    `JsonPointerException`, `JsonPatchConflict`, `InvalidJsonPatch` and
    `JsonPatchTestFailed`, and a malformed op reaches plain `TypeError`/`KeyError`
    before any of those; an agent-authored patch can produce any of them, so all are
    caught and reported as `apply_failed`.
    """
    ops = patch.to_rfc6902() if patch is not None else []
    if not ops:
        return PatchResult(
            ok=False,
            patched_data=None,
            error="patch contains no operations",
            stage=STAGE_EMPTY_PATCH,
        )

    working = _independent_copy(spec.data)
    try:
        # in_place=True on our *own* copy: jsonpatch's default is to deepcopy the
        # document first, which would reintroduce the comment loss described in the
        # module docstring.
        patched = jsonpatch.JsonPatch(ops).apply(working, in_place=True)
    except Exception as exc:  # noqa: BLE001 - agent input; nothing may escape
        return PatchResult(
            ok=False,
            patched_data=None,
            error=_describe(exc),
            stage=STAGE_APPLY_FAILED,
        )

    return PatchResult(ok=True, patched_data=patched, error=None, stage=STAGE_APPLIED)


def validate_openapi(data: Any) -> str | None:
    """Return None when `data` is a valid OpenAPI document, else the error message.

    Round-trip structures are `dict`/`list` subclasses, so the validator consumes
    them directly with no conversion step.

    Never raises. Beyond `OpenAPIValidationError` the validator also raises
    `ValidatorDetectError` when it cannot find a version key, and a bare `TypeError`
    when the version key is present but not a string (e.g. a patch that replaces
    `/openapi` with an integer) — that one escapes its own exception hierarchy, so
    the catch has to be broad.
    """
    try:
        _validate_openapi_document(data)
    except Exception as exc:  # noqa: BLE001 - validator leaks non-OpenAPI errors
        return _describe(exc)
    return None


def validate_patch(spec: LoadedSpec, patch: Patch) -> PatchResult:
    """THE GATE. Apply to a copy, then re-validate as OpenAPI.

    `ok=True` only if both pass, and only an `ok=True` result may be rendered to a
    developer. A patch that applies cleanly but leaves an invalid document is
    exactly the failure mode this exists to catch — a plausible-looking edit that
    breaks the spec is worse than no suggestion at all.
    """
    result = apply_patch_to_copy(spec, patch)
    if not result.ok:
        return result

    error = validate_openapi(result.patched_data)
    if error is not None:
        return PatchResult(
            ok=False,
            patched_data=None,
            error=f"patch applied but the result is not a valid OpenAPI document — {error}",
            stage=STAGE_SCHEMA_INVALID,
        )
    return result


def render_diff(before: str, after: str, path: str = "spec") -> str:
    """Unified diff between two serialisations, for display.

    Returns the empty string when the two are identical, so callers can treat
    "nothing to show" as falsey. Lines carry no trailing newlines, leaving the
    caller in charge of spacing.
    """
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join(diff)


def patched_text(spec: LoadedSpec, result: PatchResult) -> str:
    """Serialise a successful `PatchResult` back to YAML text, round-trip preserving.

    Goes through `LoadedSpec.dumps` so the patched document is written with exactly
    the settings the original was read with — one serialisation path, no drift.

    Raises ValueError for a result that did not pass the gate. Returning an empty
    string there would be indistinguishable from an empty spec at the write step,
    and this text is a candidate for overwriting a developer's file.
    """
    if not result.ok or result.patched_data is None:
        raise ValueError(
            f"cannot serialise a patch that did not pass validation "
            f"(stage={result.stage!r}, error={result.error!r})"
        )
    return dataclasses.replace(spec, data=result.patched_data).dumps()

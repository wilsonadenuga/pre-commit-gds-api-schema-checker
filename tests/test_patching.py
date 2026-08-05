"""Patch validation gate tests.

The gate is the mechanism behind two of the project's non-negotiables — "an invalid
proposed patch is dropped, never rendered" (self-check 6) and "round-trip preserves
comments and key order" (assessment: engineering rigour) — so the assertions here
are contract tests, not incidental coverage.

The no-mutation tests repeat deliberately. `spec.data` is the developer's real file
in memory, and every failure mode (bad path, malformed op, spec-breaking edit) is a
separate opportunity to corrupt it, so each one is pinned separately.
"""

from __future__ import annotations

import pytest

from example_specs import BROKEN_SPEC, GOOD_SPEC, minimal_spec_body, write_spec
from gds_api_schema_uplift.contracts import Patch, PatchOp
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.patching import (
    PatchResult,
    apply_patch_to_copy,
    patched_text,
    render_diff,
    validate_openapi,
    validate_patch,
)

FIXED_URL = "https://api.example.gov.uk"


def _gds_001_fix() -> Patch:
    """The canonical demo patch: make `servers[0].url` HTTPS."""
    return Patch(
        ops=(PatchOp(op="replace", path="/servers/0/url", value=FIXED_URL),),
        rationale="GDS-001 requires HTTPS.",
        clause_quote="APIs must be served over HTTPS.",
    )


@pytest.fixture
def broken():
    return load_spec(BROKEN_SPEC)


# --- the happy path ---------------------------------------------------------------------

def test_valid_patch_applies_and_validates(broken):
    result = validate_patch(broken, _gds_001_fix())

    assert result.ok is True
    assert result.stage == "applied"
    assert result.error is None
    assert result.patched_data is not None
    assert result.patched_data["servers"][0]["url"] == FIXED_URL


def test_apply_patch_to_copy_reports_applied_without_validating(broken):
    """`apply_patch_to_copy` is the first half of the gate, not the gate itself."""
    result = apply_patch_to_copy(broken, _gds_001_fix())

    assert result.ok is True
    assert result.stage == "applied"
    assert result.patched_data["servers"][0]["url"] == FIXED_URL


def test_patch_result_is_frozen(broken):
    """The gate's verdict must not be editable downstream of the check."""
    result = validate_patch(broken, _gds_001_fix())
    with pytest.raises(Exception):
        result.ok = False  # type: ignore[misc]


# --- no mutation, ever ------------------------------------------------------------------

def test_successful_patch_does_not_mutate_the_spec(broken):
    before = broken.dumps()
    result = validate_patch(broken, _gds_001_fix())

    assert result.ok is True
    assert broken.dumps() == before
    assert broken.data["servers"][0]["url"] == "http://api.example.gov.uk"


def test_failed_apply_does_not_mutate_the_spec(broken):
    before = broken.dumps()
    validate_patch(broken, Patch(ops=(PatchOp(op="replace", path="/nope/0/x", value=1),)))
    assert broken.dumps() == before


def test_invalid_op_does_not_mutate_the_spec(broken):
    before = broken.dumps()
    validate_patch(broken, Patch(ops=(PatchOp(op="frobnicate", path="/openapi", value=1),)))
    assert broken.dumps() == before


def test_schema_breaking_patch_does_not_mutate_the_spec(broken):
    before = broken.dumps()
    validate_patch(broken, Patch(ops=(PatchOp(op="remove", path="/info"),)))
    assert broken.dumps() == before


def test_partially_applied_op_list_does_not_mutate_the_spec(broken):
    """The first op is valid and the second is not: the copy absorbs both."""
    before = broken.dumps()
    result = validate_patch(
        broken,
        Patch(
            ops=(
                PatchOp(op="replace", path="/servers/0/url", value=FIXED_URL),
                PatchOp(op="replace", path="/nope", value=1),
            )
        ),
    )

    assert result.ok is False
    assert result.stage == "apply_failed"
    assert broken.dumps() == before


def test_mutating_the_patched_copy_does_not_reach_the_spec(broken):
    """The copy is independent, not a shallow view onto shared sub-objects."""
    before = broken.dumps()
    result = validate_patch(broken, _gds_001_fix())

    result.patched_data["info"]["title"] = "clobbered"
    result.patched_data["components"]["schemas"]["User"]["type"] = "clobbered"

    assert broken.dumps() == before


# --- rejection paths --------------------------------------------------------------------

def test_nonexistent_path_is_rejected(broken):
    result = validate_patch(broken, Patch(ops=(PatchOp(op="replace", path="/nope/0/x", value=1),)))

    assert result.ok is False
    assert result.stage == "apply_failed"
    assert result.patched_data is None
    assert result.error


def test_malformed_op_is_rejected_without_raising(broken):
    result = validate_patch(broken, Patch(ops=(PatchOp(op="frobnicate", path="/openapi", value=1),)))

    assert result.ok is False
    assert result.stage == "apply_failed"
    assert result.patched_data is None
    assert "frobnicate" in result.error


@pytest.mark.parametrize(
    "op",
    [
        PatchOp(op="remove", path="/does/not/exist"),
        PatchOp(op="add", path="/servers/9/url", value=FIXED_URL),  # index out of range
        PatchOp(op="add", path="no-leading-slash", value=1),  # not a JSON pointer
        PatchOp(op="move", path="/servers", from_="/nowhere"),
        PatchOp(op="test", path="/openapi", value="9.9"),  # test op that fails
    ],
    ids=["remove-missing", "index-oob", "bad-pointer", "move-missing-from", "failed-test"],
)
def test_unapplicable_ops_are_rejected_without_raising(broken, op):
    before = broken.dumps()
    result = validate_patch(broken, Patch(ops=(op,)))

    assert result.ok is False
    assert result.stage == "apply_failed"
    assert result.error
    assert broken.dumps() == before


def test_patch_that_breaks_the_schema_is_rejected(broken):
    """`remove /info` applies cleanly but leaves a document the validator rejects.

    Chosen over `replace /openapi` with an integer because it is the honest test of
    *schema* validation: `info` is a required property, so the failure comes from
    the OpenAPI schema itself. Replacing `/openapi` with an integer never reaches
    schema validation — it blows up in the validator's version detection with a bare
    `TypeError`. That path matters too, so it is covered separately below.
    """
    result = validate_patch(broken, Patch(ops=(PatchOp(op="remove", path="/info"),)))

    assert result.ok is False
    assert result.stage == "schema_invalid"
    assert result.patched_data is None
    assert "info" in result.error


def test_patch_breaking_the_version_key_is_rejected(broken):
    """The validator raises a non-OpenAPI `TypeError` here; it must not escape."""
    result = validate_patch(broken, Patch(ops=(PatchOp(op="replace", path="/openapi", value=123),)))

    assert result.ok is False
    assert result.stage == "schema_invalid"
    assert result.error


def test_patch_replacing_paths_with_a_scalar_is_rejected(broken):
    result = validate_patch(broken, Patch(ops=(PatchOp(op="replace", path="/paths", value="nope"),)))

    assert result.ok is False
    assert result.stage == "schema_invalid"


def test_empty_patch_is_rejected(broken):
    """Nothing to review means nothing to offer a human."""
    result = validate_patch(broken, Patch())

    assert result.ok is False
    assert result.stage == "empty_patch"
    assert result.patched_data is None
    assert result.error


def test_empty_patch_is_rejected_by_apply_too(broken):
    assert apply_patch_to_copy(broken, Patch()).stage == "empty_patch"


def test_rejected_results_carry_a_useful_message(broken):
    """Every rejection reason is a short single line, not a schema dump."""
    for patch in (
        Patch(),
        Patch(ops=(PatchOp(op="replace", path="/nope", value=1),)),
        Patch(ops=(PatchOp(op="frobnicate", path="/openapi", value=1),)),
        Patch(ops=(PatchOp(op="remove", path="/info"),)),
    ):
        error = validate_patch(broken, patch).error
        assert error and error.strip()
        assert "\n" not in error
        assert len(error) < 400


# --- remove ops (the `value`-omitted branch of PatchOp.to_rfc6902) ----------------------

def test_remove_op_applies(broken):
    """`remove` omits `value` on the wire; jsonpatch rejects the op if it appears."""
    result = validate_patch(broken, Patch(ops=(PatchOp(op="remove", path="/servers/0/description"),)))

    assert result.ok is True
    assert result.stage == "applied"
    assert "description" not in result.patched_data["servers"][0]
    assert "description" in broken.data["servers"][0]  # original untouched


def test_remove_op_serialises_without_the_removed_key(broken):
    result = validate_patch(broken, Patch(ops=(PatchOp(op="remove", path="/security"),)))

    assert result.ok is True
    assert "\nsecurity:\n" not in patched_text(broken, result)


# --- validate_openapi -------------------------------------------------------------------

@pytest.mark.parametrize("path", [BROKEN_SPEC, GOOD_SPEC], ids=["broken", "good"])
def test_example_specs_are_valid_openapi(path):
    """`broken.yaml` breaks *standards*, not the schema — the rule pass needs it valid."""
    assert validate_openapi(load_spec(path).data) is None


@pytest.mark.parametrize(
    "junk",
    [{"hello": "world"}, {}, [], "not a document", None, {"openapi": 3.1}],
    ids=["no-version", "empty", "list", "string", "none", "numeric-version"],
)
def test_validate_openapi_returns_a_string_for_junk(junk):
    error = validate_openapi(junk)
    assert isinstance(error, str)
    assert error.strip()


def test_validate_openapi_accepts_a_plain_dict(tmp_path):
    """Round-trip structures are dict/list subclasses; plain dicts must work too."""
    assert validate_openapi(load_spec(write_spec(tmp_path, minimal_spec_body())).data) is None
    assert (
        validate_openapi({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}})
        is None
    )


# --- patched_text round-trip ------------------------------------------------------------

def test_patched_text_is_reloadable(broken, tmp_path):
    result = validate_patch(broken, _gds_001_fix())
    reloaded = load_spec(write_spec(tmp_path, patched_text(broken, result), "patched.yaml"))

    assert reloaded.openapi_version == "3.1.0"
    assert reloaded.data["servers"][0]["url"] == FIXED_URL


def test_patched_text_preserves_comments(broken):
    """Requirement 9: accepting a patch must not strip the developer's comments.

    Covers head comments, comments before a root key, comments before the first key
    of a nested block mapping, and a trailing comment inside a block — the positions
    a round-trip is most likely to lose. If this fails, accepting a patch silently
    rewrites the developer's file beyond the line they approved.
    """
    text = patched_text(broken, validate_patch(broken, _gds_001_fix()))

    for comment in (
        "# DELIBERATELY NON-COMPLIANT fixture.",  # document head
        "# GDS-001: plaintext transport.",  # before a root key
        "# REC-002: no summary, no description.",  # first key of a nested map
        "# GDS-004: XML rather than JSON.",
        "# NCSC-003: no additionalProperties: false",
        "# NCSC-001: HTTP Basic.",
        "# NCSC-004: no 429 defined on this operation.",  # trailing, inside a block
    ):
        assert comment in text, comment


def test_patched_text_changes_exactly_one_line(broken):
    """Key order and layout survive: the only diff is the line the patch targeted."""
    text = patched_text(broken, validate_patch(broken, _gds_001_fix()))
    changed = [
        line
        for line in render_diff(broken.dumps(), text).splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]

    assert changed == [
        "-  - url: http://api.example.gov.uk",
        f"+  - url: {FIXED_URL}",
    ]


def test_patched_text_of_the_good_spec_is_unchanged_apart_from_the_patch():
    """The compliant fixture is the round-trip fixture (PLAN req 9)."""
    good = load_spec(GOOD_SPEC)
    result = validate_patch(
        good, Patch(ops=(PatchOp(op="replace", path="/info/version", value="2.0.0"),))
    )

    text = patched_text(good, result)
    assert text.replace("2.0.0", "1.0.0", 1) == good.dumps()


def test_patched_text_refuses_a_failed_result(broken):
    """No text for a patch that never passed the gate — it must not reach a file."""
    result = validate_patch(broken, Patch())
    with pytest.raises(ValueError):
        patched_text(broken, result)


def test_patched_text_refuses_a_hand_built_ok_result_with_no_data(broken):
    with pytest.raises(ValueError):
        patched_text(broken, PatchResult(ok=True, patched_data=None, error=None, stage="applied"))


# --- render_diff ------------------------------------------------------------------------

def test_render_diff_shows_the_changed_line_with_standard_headers(broken):
    text = patched_text(broken, validate_patch(broken, _gds_001_fix()))
    diff = render_diff(broken.dumps(), text, path=str(broken.path))

    assert diff.startswith("---")
    assert "+++" in diff
    assert str(broken.path) in diff
    assert f"+  - url: {FIXED_URL}" in diff
    assert "-  - url: http://api.example.gov.uk" in diff


def test_render_diff_of_identical_input_is_empty():
    text = "openapi: 3.1.0\ninfo:\n  title: t\n"
    assert render_diff(text, text) == ""


def test_render_diff_uses_the_default_label():
    diff = render_diff("a\n", "b\n")
    assert "a/spec" in diff
    assert "b/spec" in diff


def test_render_diff_has_no_trailing_newline_noise():
    diff = render_diff("one\ntwo\n", "one\nthree\n")
    assert diff == diff.rstrip("\n")
    assert "\n\n" not in diff
    assert "-two" in diff
    assert "+three" in diff


# --- ad-hoc specs -----------------------------------------------------------------------

def test_gate_works_on_a_minimal_spec(tmp_path):
    body = minimal_spec_body("paths: {}\nservers:\n  - url: http://x.gov.uk\n")
    spec = load_spec(write_spec(tmp_path, body))
    result = validate_patch(spec, _gds_001_fix())

    assert result.ok is True
    assert patched_text(spec, result).count(FIXED_URL) == 1


def test_add_op_can_introduce_a_new_key(tmp_path):
    spec = load_spec(write_spec(tmp_path, minimal_spec_body()))
    result = validate_patch(
        spec,
        Patch(ops=(PatchOp(op="add", path="/servers", value=[{"url": FIXED_URL}]),)),
    )

    assert result.ok is True
    assert result.patched_data["servers"][0]["url"] == FIXED_URL
    assert "servers" not in spec.data
    assert FIXED_URL in patched_text(spec, result)


def test_a_3_0_spec_validates_against_the_3_0_schema(tmp_path):
    """Version detection picks the schema; the gate must not assume 3.1."""
    body = minimal_spec_body(version="3.0.3", extra="paths: {}\n")
    spec = load_spec(write_spec(tmp_path, body))

    assert validate_openapi(spec.data) is None
    assert validate_patch(
        spec, Patch(ops=(PatchOp(op="replace", path="/info/title", value="renamed"),))
    ).ok is True

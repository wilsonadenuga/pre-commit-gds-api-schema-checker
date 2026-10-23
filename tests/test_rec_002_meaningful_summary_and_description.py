"""REC-002 — every operation has a meaningful description; the summary is optional.

The fixture tests check one finding on the all-rules fixture and none on good.yaml.
The rest pin the edge cases: missing, empty, too short, or copied descriptions.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from example_specs import ALL_RULES_SPEC

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.rec_002_meaningful_summary_and_description import check

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BROKEN = ALL_RULES_SPEC
GOOD = EXAMPLES / "good.yaml"

#: The one violation in broken.yaml: GET /getUserList has no summary/description.
BROKEN_LOCATION = "$.paths['/getUserList'].get"


def _spec(tmp_path: Path, body: str, name: str = "spec.yaml"):
    """Write a minimal OpenAPI 3.1 document with `body` as its `paths` block."""
    text = textwrap.dedent(
        """\
        openapi: 3.1.0
        info:
          title: t
          version: '1'
        paths:
        """
    ) + textwrap.indent(textwrap.dedent(body), "  ")
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return load_spec(path)


def _raw_spec(tmp_path: Path, text: str, name: str = "spec.yaml"):
    """Write `text` verbatim (no indentation dance) and load it."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return load_spec(path)


def _locations(spec) -> list[str]:
    return [finding.location for finding in check(spec)]


# --- fixture contract -----------------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding():
    """GET on `/getUserList` has neither summary nor description; POST is compliant."""
    findings = check(load_spec(BROKEN))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "REC-002"
    assert finding.location == BROKEN_LOCATION
    assert finding.severity is Severity.SUGGESTION
    assert finding.clause_id == "REC-002"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings():
    """`good.yaml`'s GET and POST both carry meaningful summary + description."""
    assert check(load_spec(GOOD)) == []


# --- compliant cases ------------------------------------------------------------------


def test_operation_with_clear_summary_and_longer_description(tmp_path):
    """A textbook-compliant operation is silent."""
    body = """\
    /things:
      get:
        summary: List things
        description: Returns a paginated list of things owned by the caller.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_boundary_lengths_pass(tmp_path):
    """A 15-char description sits exactly on the cutoff."""
    body = """\
    /things:
      get:
        summary: List users
        description: Lists all users
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_markdown_description_passes(tmp_path):
    """Markdown is still a string; nothing here judges formatting."""
    body = """\
    /things:
      get:
        summary: List things
        description: |
          Returns a page of **things**.

          - ordered by creation time
          - requires the `things.read` scope
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_two_compliant_operations_yield_zero_findings(tmp_path):
    """Multiple operations, each with its own summary+description, all pass."""
    body = """\
    /things:
      get:
        summary: List things
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
      post:
        summary: Create a thing
        description: Creates a new thing and returns the stored representation.
        operationId: createThing
        responses:
          '201':
            description: created
    """
    assert check(_spec(tmp_path, body)) == []


def test_operation_with_own_fields_ignores_path_item_level(tmp_path):
    """A path-item-level summary is fine as long as the operation has its own."""
    body = """\
    /things:
      summary: Path-level summary that operations may inherit.
      description: Path-level description that operations may inherit.
      get:
        summary: List things
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


# --- non-compliant cases --------------------------------------------------------------


def test_missing_summary_is_fine(tmp_path):
    """The summary is optional: a good description alone passes."""
    body = """\
    /things:
      get:
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_missing_description_only_yields_one_finding(tmp_path):
    """Summary alone does not satisfy REC-002 either."""
    body = """\
    /things:
      get:
        summary: List things
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get"
    assert "description" in findings[0].snippet


def test_missing_both_yields_one_description_finding(tmp_path):
    """With neither field, the one finding is about the description."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get"
    assert findings[0].snippet == "description missing"


def test_empty_summary_string_is_fine(tmp_path):
    """The summary is optional, so an empty one is not flagged."""
    body = """\
    /things:
      get:
        summary: ""
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_whitespace_only_summary_is_fine(tmp_path):
    """The summary is optional, so an empty one is not flagged."""
    body = """\
    /things:
      get:
        summary: "   "
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_description_equals_summary_is_flagged(tmp_path):
    """A description that just parrots the summary adds no information."""
    body = """\
    /things:
      get:
        summary: List things
        description: List things
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert "duplicates summary" in findings[0].snippet


def test_description_equals_operation_id_is_flagged(tmp_path):
    """`description: getUser` when `operationId: getUser` is a placeholder."""
    body = """\
    /things:
      get:
        summary: List all things
        description: listThings
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert "operationId" in findings[0].snippet


def test_short_summary_is_fine(tmp_path):
    """Summary length is not checked; only the description has a minimum."""
    body = """\
    /things:
      get:
        summary: List one
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_two_offending_operations_yield_two_findings(tmp_path):
    """One finding per offending operation, in declaration order."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
      post:
        operationId: createThing
        responses:
          '201':
            description: created
    """
    locations = _locations(_spec(tmp_path, body))
    assert locations == [
        "$.paths['/things'].get",
        "$.paths['/things'].post",
    ]


# --- edge cases -----------------------------------------------------------------------


def test_empty_paths_yields_nothing(tmp_path):
    """No operations, no findings."""
    path = tmp_path / "empty.yaml"
    path.write_text(
        "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths: {}\n", encoding="utf-8"
    )
    assert check(load_spec(path)) == []


def test_path_item_with_no_operations_yields_nothing(tmp_path):
    """A path carrying only `summary`/`parameters` has no operations to judge."""
    body = """\
    /things:
      summary: A collection of things
      description: has no operations at all
    """
    assert check(_spec(tmp_path, body)) == []


@pytest.mark.parametrize(
    "summary_line",
    [
        "summary: 42",
        "summary: [a, b]",
        "summary: {nested: value}",
    ],
    ids=["int", "list", "mapping"],
)
def test_non_string_summary_does_not_crash_or_flag(tmp_path, summary_line):
    """Malformed `summary` is a schema error; leave it to the validator."""
    body = f"""\
    /things:
      get:
        {summary_line}
        description: Returns a paginated list of things.
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


@pytest.mark.parametrize(
    "description_line",
    [
        "description: 42",
        "description: [a, b]",
        "description: {nested: value}",
    ],
    ids=["int", "list", "mapping"],
)
def test_non_string_description_does_not_crash_or_flag(tmp_path, description_line):
    """Malformed `description` is a schema error; leave it to the validator."""
    body = f"""\
    /things:
      get:
        summary: List things
        {description_line}
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    assert check(_spec(tmp_path, body)) == []


def test_path_level_summary_does_not_cover_operation(tmp_path):
    """Per the per-operation decision: path-item-level fields do not satisfy REC-002."""
    body = """\
    /things:
      summary: Things collection
      description: A path-item-level description that operations may inherit.
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get"


# --- out-of-scope: what this rule must not check --------------------------------------


def test_operationid_meaningfulness_is_not_judged(tmp_path):
    """A short/opaque `operationId` alone is not a REC-002 finding."""
    body = """\
    /things:
      get:
        summary: List things
        description: Returns a paginated list of things.
        operationId: x
        responses:
          '200':
            description: ok
    """
    # The operation itself is compliant — even though `operationId: x` looks
    # unusable, REC-002 has nothing to say about it.
    assert check(_spec(tmp_path, body)) == []


def test_nested_description_fields_are_ignored(tmp_path):
    """Response/parameter/requestBody descriptions are not this rule's business."""
    body = """\
    /things:
      get:
        summary: List things
        description: Returns a paginated list of things.
        operationId: listThings
        parameters:
          - name: page
            in: query
            description: ""
            schema:
              type: integer
        responses:
          '200':
            description: ""
            content:
              application/json:
                schema:
                  type: object
    """
    # Empty response and parameter descriptions must not cause REC-002 to fire.
    assert check(_spec(tmp_path, body)) == []

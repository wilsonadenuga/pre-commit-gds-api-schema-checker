"""NCSC-004 (rate limiting acknowledged: `429` declared) unit tests.

The checker is imported directly rather than through `run_deterministic_pass`,
so these tests stay green while the other NCSC rules are still being written
and the registry is still being wired up in `rules/__init__`.

The two fixture assertions are the acceptance criteria: exactly one finding
on `broken.yaml` at the POST operation's `responses` (no 429 declared), and
zero on `good.yaml`. Everything else pins a scope decision documented in the
rule module.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.ncsc_004_rate_limit_declared import check

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"


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
    """The POST on `/getUserList` has no 429; the GET does. One finding, on POST."""
    findings = check(load_spec(BROKEN))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "NCSC-004"
    assert finding.location == "$.paths['/getUserList'].post.responses"
    assert finding.severity is Severity.SUGGESTION
    assert finding.clause_id == "NCSC-004"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings():
    """`good.yaml` declares 429 on both GET and POST; nothing should fire."""
    assert check(load_spec(GOOD)) == []


# --- compliant operations -------------------------------------------------------------


def test_explicit_429_response_passes(tmp_path):
    """An operation declaring `'429': {description: ...}` is compliant."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            description: Too many requests
    """
    assert check(_spec(tmp_path, body)) == []


def test_4xx_range_wildcard_counts_as_declared(tmp_path):
    """`4XX` is an OpenAPI range key that semantically includes 429."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '4XX':
            description: Client error
    """
    assert check(_spec(tmp_path, body)) == []


def test_429_declared_as_ref_counts(tmp_path):
    """`'429': {$ref: ...}` is the idiomatic shared-response pattern."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            $ref: '#/components/responses/RateLimit'
    """
    text = textwrap.dedent(
        """\
        openapi: 3.1.0
        info:
          title: t
          version: '1'
        paths:
        """
    ) + textwrap.indent(textwrap.dedent(body), "  ") + textwrap.dedent(
        """\
        components:
          responses:
            RateLimit:
              description: Too many requests
        """
    )
    path = tmp_path / "spec.yaml"
    path.write_text(text)
    assert check(load_spec(path)) == []


def test_multiple_methods_all_declare_429(tmp_path):
    """A path with GET, POST and PUT each declaring 429 must stay silent."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            description: rate limited
      post:
        operationId: createThing
        responses:
          '201':
            description: created
          '429':
            description: rate limited
      put:
        operationId: replaceThings
        responses:
          '200':
            description: ok
          '429':
            description: rate limited
    """
    assert check(_spec(tmp_path, body)) == []


def test_openapi_30_spec_with_429_declared_passes(tmp_path):
    """The rule reads only the responses object; the OpenAPI major version is irrelevant."""
    text = textwrap.dedent(
        """\
        openapi: 3.0.3
        info:
          title: t
          version: '1'
        paths:
          /things:
            get:
              operationId: listThings
              responses:
                '200':
                  description: ok
                '429':
                  description: rate limited
        """
    )
    assert check(_raw_spec(tmp_path, text)) == []


def test_429_declared_without_a_body_still_counts(tmp_path):
    """Key presence is the whole test; a bare `description` is enough."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '429':
            description: rate limited
    """
    assert check(_spec(tmp_path, body)) == []


# --- non-compliant operations ---------------------------------------------------------


def test_missing_429_yields_one_finding_and_snippet_lists_declared_codes(tmp_path):
    """An operation with only 200 and 400 is missing 429; snippet names the codes."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '400':
            description: bad request
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get.responses"
    assert "200" in findings[0].snippet
    assert "400" in findings[0].snippet


def test_default_only_responses_is_flagged(tmp_path):
    """`default` is a catch-all, not an acknowledgment of rate limiting."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          default:
            description: something happened
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get.responses"


def test_429_on_different_method_does_not_cover_a_missing_method(tmp_path):
    """429 is per-operation; sibling methods do not inherit it."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            description: rate limited
      post:
        operationId: createThing
        responses:
          '201':
            description: created
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].post.responses"


def test_two_operations_missing_429_yield_two_findings(tmp_path):
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
        "$.paths['/things'].get.responses",
        "$.paths['/things'].post.responses",
    ]


def test_empty_responses_block_is_flagged(tmp_path):
    """`responses: {}` declares nothing, so 429 is not among them."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses: {}
    """
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get.responses"


# --- integer-vs-string YAML key gotcha ------------------------------------------------


def test_unquoted_yaml_integer_status_code_still_counts(tmp_path):
    """YAML 1.2 parses `429:` as an int; ruamel preserves that. Both forms must count."""
    text = textwrap.dedent(
        """\
        openapi: 3.1.0
        info:
          title: t
          version: '1'
        paths:
          /things:
            get:
              operationId: listThings
              responses:
                200:
                  description: ok
                429:
                  description: rate limited
        """
    )
    assert check(_raw_spec(tmp_path, text)) == []


def test_unquoted_integer_status_missing_429_still_flagged(tmp_path):
    """Symmetric: an integer-keyed responses block missing 429 must still fire."""
    text = textwrap.dedent(
        """\
        openapi: 3.1.0
        info:
          title: t
          version: '1'
        paths:
          /things:
            get:
              operationId: listThings
              responses:
                200:
                  description: ok
                400:
                  description: bad request
        """
    )
    findings = check(_raw_spec(tmp_path, text))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/things'].get.responses"


# --- edge cases -----------------------------------------------------------------------


def test_path_item_with_no_operations_yields_nothing(tmp_path):
    """A path with only `parameters` or `summary` has no operations to check."""
    body = """\
    /things:
      summary: A collection of things
      description: has no operations at all
    """
    assert check(_spec(tmp_path, body)) == []


def test_operation_without_responses_key_yields_nothing(tmp_path):
    """Missing `responses` is invalid OpenAPI; leave it to the schema validator."""
    body = """\
    /things:
      get:
        operationId: listThings
    """
    assert check(_spec(tmp_path, body)) == []


@pytest.mark.parametrize(
    "responses_line",
    [
        "responses: not-a-mapping",
        "responses: null",
        "responses: []",
    ],
    ids=["scalar", "null", "sequence"],
)
def test_malformed_responses_node_does_not_crash_or_flag(tmp_path, responses_line):
    """A non-mapping `responses` is a schema error; this rule stays silent."""
    body = f"""\
    /things:
      get:
        operationId: listThings
        {responses_line}
    """
    assert check(_spec(tmp_path, body)) == []


# --- out-of-scope: what this rule must not check --------------------------------------


def test_429_without_retry_after_header_is_not_flagged(tmp_path):
    """`Retry-After` is a deeper concern and out of scope for MVP."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            description: rate limited
            content:
              application/problem+json:
                schema:
                  type: object
    """
    # No `headers:` on the 429 response — must still pass.
    assert check(_spec(tmp_path, body)) == []


def test_429_body_shape_is_not_checked(tmp_path):
    """The rule reads the key only; content-type and schema shape belong elsewhere."""
    body = """\
    /things:
      get:
        operationId: listThings
        responses:
          '200':
            description: ok
          '429':
            description: rate limited
            content:
              text/plain:
                schema:
                  type: string
    """
    assert check(_spec(tmp_path, body)) == []

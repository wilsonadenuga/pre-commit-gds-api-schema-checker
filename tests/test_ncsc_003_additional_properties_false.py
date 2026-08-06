"""NCSC-003 — request bodies set `additionalProperties: false`.

The fixture assertions are the acceptance test: exactly one finding on
`examples/broken.yaml`, at the POST request body's JSON schema, and silence on
`examples/good.yaml`. The inline specs pin the scope decisions documented in the
rule module — root-only, one-level ref-following, compositions flagged at root,
scalar bodies out of scope — so a later widening of the rule fails a test rather
than quietly changing the fixture counts.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.ncsc_003_additional_properties_false import check

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

#: The one violation in broken.yaml: POST body's inline JSON schema omits
#: `additionalProperties: false`.
BROKEN_LOCATION = (
    "$.paths['/getUserList'].post.requestBody.content['application/json'].schema"
)


def _spec(tmp_path: Path, body: str, extra: str = "", name: str = "spec.yaml"):
    """Write a minimal OpenAPI 3.1 document with `body` as its `paths` block.

    `extra` is appended verbatim at the root (unindented) for things like a
    `components:` block.
    """
    text = textwrap.dedent(
        """\
        openapi: 3.1.0
        info:
          title: t
          version: '1'
        paths:
        """
    ) + textwrap.indent(textwrap.dedent(body), "  ")
    if extra:
        text += textwrap.dedent(extra)
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return load_spec(path)


def _post_body(schema: str, media_type: str = "application/json") -> str:
    """A single POST operation with a request body carrying `schema`."""
    return f"""\
        /thing:
          post:
            operationId: createThing
            requestBody:
              required: true
              content:
                {media_type}:
                  schema:
{textwrap.indent(textwrap.dedent(schema), "                    ")}
            responses:
              '201':
                description: Created.
        """


def _locations(spec) -> list[str]:
    return [finding.location for finding in check(spec)]


# --- fixture contract -------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding():
    """The broken fixture must produce one NCSC-003 finding on the POST body."""
    findings = check(load_spec(EXAMPLES / "broken.yaml"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "NCSC-003"
    assert finding.location == BROKEN_LOCATION
    assert finding.severity is Severity.WARNING
    assert finding.clause_id == "NCSC-003"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings():
    """The compliant fixture must not fire this rule; M1 depends on it."""
    assert check(load_spec(EXAMPLES / "good.yaml")) == []


# --- compliant cases --------------------------------------------------------


def test_inline_additional_properties_false_passes(tmp_path):
    """The straightforward case: strict root object body."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            additionalProperties: false
            properties:
              name:
                type: string
            """
        ),
    )
    assert check(spec) == []


def test_body_ref_with_strict_component_passes(tmp_path):
    """One level of `$ref` following into components.schemas is enough."""
    spec = _spec(
        tmp_path,
        _post_body("$ref: '#/components/schemas/UserRequest'"),
        extra="""\
        components:
          schemas:
            UserRequest:
              type: object
              additionalProperties: false
              properties:
                name:
                  type: string
        """,
    )
    assert check(spec) == []


def test_operation_without_request_body_yields_nothing(tmp_path):
    """GET/DELETE/HEAD/OPTIONS operations declare no body — nothing to check."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          get:
            operationId: getThing
            responses:
              '200':
                description: A thing.
          delete:
            operationId: deleteThing
            responses:
              '204':
                description: Deleted.
          head:
            operationId: headThing
            responses:
              '200':
                description: HEAD.
        """,
    )
    assert check(spec) == []


def test_non_json_request_body_is_out_of_scope(tmp_path):
    """Form-encoded and other non-JSON bodies are not subject to this rule."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            properties:
              upload:
                type: string
            """,
            media_type="application/x-www-form-urlencoded",
        ),
    )
    assert check(spec) == []


def test_vendor_plus_json_media_type_is_in_scope_and_passes(tmp_path):
    """A `+json` structured subtype counts as JSON; strict root passes."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            additionalProperties: false
            properties:
              name:
                type: string
            """,
            media_type="application/vnd.dept.user+json",
        ),
    )
    assert check(spec) == []


# --- non-compliant cases ----------------------------------------------------


def test_missing_additional_properties_is_flagged(tmp_path):
    """The core violation: root object body with no `additionalProperties`."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            properties:
              name:
                type: string
            """
        ),
    )
    findings = check(spec)
    assert len(findings) == 1
    assert findings[0].location == (
        "$.paths['/thing'].post.requestBody.content['application/json'].schema"
    )
    assert findings[0].severity is Severity.WARNING


def test_additional_properties_true_is_flagged(tmp_path):
    """`true` explicitly permits extra keys — that is what NCSC forbids."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            additionalProperties: true
            properties:
              name:
                type: string
            """
        ),
    )
    findings = check(spec)
    assert len(findings) == 1
    assert "true" in findings[0].snippet.lower()


def test_additional_properties_as_schema_is_flagged(tmp_path):
    """`additionalProperties: {any object}` also permits extras — flag it."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            additionalProperties:
              type: string
            properties:
              name:
                type: string
            """
        ),
    )
    findings = check(spec)
    assert len(findings) == 1


def test_body_ref_with_non_strict_component_is_flagged(tmp_path):
    """The finding points at the resolved shared schema, not at the ref site.

    A patch that tightens the shared definition is the correct fix — flagging
    the operation's body would ask a fixer to inline the schema, which is worse.
    """
    spec = _spec(
        tmp_path,
        _post_body("$ref: '#/components/schemas/UserRequest'"),
        extra="""\
        components:
          schemas:
            UserRequest:
              type: object
              properties:
                name:
                  type: string
        """,
    )
    findings = check(spec)
    assert len(findings) == 1
    assert findings[0].location == "$.components.schemas.UserRequest"


def test_composition_at_root_is_flagged(tmp_path):
    """`allOf` at the body root is flagged as-is; deep composition is Phase 8."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            allOf:
              - $ref: '#/components/schemas/UserRequest'
              - type: object
                properties:
                  extra:
                    type: string
            """
        ),
        extra="""\
        components:
          schemas:
            UserRequest:
              type: object
              additionalProperties: false
              properties:
                name:
                  type: string
        """,
    )
    findings = check(spec)
    assert len(findings) == 1
    assert "allof" in findings[0].snippet.lower()


def test_two_offending_operations_yield_two_findings(tmp_path):
    """Counting property: two violations, two findings."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody:
              required: true
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      name:
                        type: string
            responses:
              '201':
                description: Created.
        /other:
          put:
            operationId: replaceOther
            requestBody:
              required: true
              content:
                application/json:
                  schema:
                    type: object
                    additionalProperties: true
                    properties:
                      name:
                        type: string
            responses:
              '200':
                description: OK.
        """,
    )
    findings = check(spec)
    assert len(findings) == 2
    assert [finding.location for finding in findings] == [
        "$.paths['/thing'].post.requestBody.content['application/json'].schema",
        "$.paths['/other'].put.requestBody.content['application/json'].schema",
    ]


# --- edge cases -------------------------------------------------------------


def test_empty_request_body_yields_nothing(tmp_path):
    """`requestBody: {}` has no content — nothing to judge."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody: {}
            responses:
              '201':
                description: Created.
        """,
    )
    assert check(spec) == []


def test_request_body_without_content_block_yields_nothing(tmp_path):
    """A body with `required: true` but no `content` — undocumented, not wrong."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody:
              required: true
            responses:
              '201':
                description: Created.
        """,
    )
    assert check(spec) == []


def test_dangling_schema_ref_does_not_crash_and_does_not_flag(tmp_path):
    """An unresolvable ref is unknown, not wrong — leave it to a validator."""
    spec = _spec(
        tmp_path,
        _post_body("$ref: '#/components/schemas/Missing'"),
        extra="""\
        components:
          schemas: {}
        """,
    )
    assert check(spec) == []


def test_dangling_request_body_ref_does_not_crash_and_does_not_flag(tmp_path):
    """Same treatment for an operation-level `requestBody: {$ref: ...}`."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody:
              $ref: '#/components/requestBodies/Missing'
            responses:
              '201':
                description: Created.
        """,
        extra="""\
        components:
          requestBodies: {}
        """,
    )
    assert check(spec) == []


def test_operation_level_request_body_ref_is_followed(tmp_path):
    """`requestBody: {$ref: '#/components/requestBodies/...'}` is resolved once.

    The finding location is the shared component's inner schema — that is what a
    fix would touch.
    """
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody:
              $ref: '#/components/requestBodies/CreateThing'
            responses:
              '201':
                description: Created.
        """,
        extra="""\
        components:
          requestBodies:
            CreateThing:
              required: true
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      name:
                        type: string
        """,
    )
    findings = check(spec)
    assert len(findings) == 1
    assert findings[0].location == (
        "$.components.requestBodies.CreateThing.content['application/json'].schema"
    )


def test_scalar_body_is_out_of_scope(tmp_path):
    """`type: string` bodies cannot carry extra keys, so the rule is silent."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: string
            """
        ),
    )
    assert check(spec) == []


def test_scalar_body_with_additional_properties_false_is_still_out_of_scope(tmp_path):
    """The property is inapplicable on a scalar; do not double-count."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: string
            additionalProperties: false
            """
        ),
    )
    assert check(spec) == []


# --- out-of-scope: nested objects ------------------------------------------


def test_nested_object_without_additional_properties_is_not_flagged(tmp_path):
    """The rule stops at the root. Nested `address` objects are Phase 8+."""
    spec = _spec(
        tmp_path,
        _post_body(
            """\
            type: object
            additionalProperties: false
            properties:
              name:
                type: string
              address:
                type: object
                properties:
                  line1:
                    type: string
            """
        ),
    )
    assert check(spec) == []

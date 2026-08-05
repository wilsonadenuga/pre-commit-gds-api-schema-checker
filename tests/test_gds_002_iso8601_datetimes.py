"""GDS-002 — dates and times are ISO 8601 strings.

The fixture assertions are the acceptance test: broken.yaml must yield exactly one
finding at a known location and good.yaml must yield none (M1, zero false positives
on the compliant spec). The inline specs cover the heuristic's edges, which is where
a false positive would come from.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.gds_002_iso8601_datetimes import check, is_temporal_name

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

BROKEN_LOCATION = (
    "$.paths['/getUserList'].post.requestBody.content['application/json']"
    ".schema.properties.createdOn"
)


def write_spec(tmp_path: Path, body: str, name: str = "spec.yaml") -> Path:
    """Write a minimal OpenAPI 3.1 document with `body` appended, and return its path."""
    path = tmp_path / name
    path.write_text(
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: t\n"
        "  version: '1'\n" + textwrap.dedent(body).lstrip("\n"),
        encoding="utf-8",
    )
    return path


def object_body(properties: str) -> str:
    """A one-operation document whose POST request body has `properties`."""
    block = textwrap.indent(textwrap.dedent(properties).strip("\n"), " " * 16)
    return (
        "paths:\n"
        "  /v1/things:\n"
        "    post:\n"
        "      requestBody:\n"
        "        content:\n"
        "          application/json:\n"
        "            schema:\n"
        "              type: object\n"
        "              properties:\n" + block + "\n"
    )


def locations(tmp_path: Path, properties: str) -> list[str]:
    spec = load_spec(write_spec(tmp_path, object_body(properties)))
    return [f.location for f in check(spec)]


# --- fixtures ---------------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding():
    findings = check(load_spec(EXAMPLES / "broken.yaml"))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.location == BROKEN_LOCATION
    assert finding.rule_id == "GDS-002"
    assert finding.clause_id == "GDS-002"
    assert finding.severity is Severity.WARNING
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_broken_fixture_does_not_flag_the_compliant_component():
    """`components.schemas.User.properties.createdOn` has `format: date-time`."""
    flagged = {f.location for f in check(load_spec(EXAMPLES / "broken.yaml"))}
    assert "$.components.schemas.User.properties.createdOn" not in flagged


def test_good_fixture_yields_no_findings():
    findings = check(load_spec(EXAMPLES / "good.yaml"))
    assert findings == [], [f.location for f in findings]


# --- format handling --------------------------------------------------------


def test_format_date_time_passes(tmp_path):
    assert locations(tmp_path, "createdAt:\n  type: string\n  format: date-time\n") == []


def test_format_date_passes(tmp_path):
    assert locations(tmp_path, "birth_date:\n  type: string\n  format: date\n") == []


def test_format_time_passes(tmp_path):
    assert locations(tmp_path, "startTime:\n  type: string\n  format: time\n") == []


def test_missing_format_on_date_named_string_is_flagged(tmp_path):
    found = locations(tmp_path, "expiryDate:\n  type: string\n")
    assert found == [
        "$.paths['/v1/things'].post.requestBody.content['application/json']"
        ".schema.properties.expiryDate"
    ]


def test_wrong_format_on_date_named_string_is_flagged(tmp_path):
    assert len(locations(tmp_path, "updatedOn:\n  type: string\n  format: uuid\n")) == 1


def test_nullable_string_union_is_still_in_scope(tmp_path):
    """OpenAPI 3.1 nullable form: `type: [string, 'null']`."""
    assert len(locations(tmp_path, "deletedAt:\n  type: [string, 'null']\n")) == 1


# --- what must NOT be flagged ----------------------------------------------


def test_date_named_integer_is_not_flagged(tmp_path):
    assert locations(tmp_path, "createdAt:\n  type: integer\n  format: int64\n") == []


def test_non_date_named_string_is_not_flagged(tmp_path):
    assert locations(tmp_path, "name:\n  type: string\n") == []


def test_names_that_merely_contain_date_or_time_are_not_flagged(tmp_path):
    """Substring matching would flag every one of these."""
    assert (
        locations(
            tmp_path,
            """
            updatedBy:
              type: string
            candidate:
              type: string
            validationMessage:
              type: string
            timeout:
              type: string
            runtime:
              type: string
            version:
              type: string
            reason:
              type: string
            """,
        )
        == []
    )


def test_ref_nodes_are_not_flagged(tmp_path):
    found = locations(tmp_path, "createdAt:\n  $ref: '#/components/schemas/Missing'\n")
    assert found == []


def test_untyped_node_is_not_flagged(tmp_path):
    assert locations(tmp_path, "createdAt:\n  description: when it happened\n") == []


# --- traversal --------------------------------------------------------------


def test_nested_properties_inside_items_are_reached(tmp_path):
    path = write_spec(
        tmp_path,
        """
        paths:
          /v1/things:
            post:
              requestBody:
                content:
                  application/json:
                    schema:
                      type: array
                      items:
                        type: object
                        properties:
                          startTime:
                            type: string
        """,
    )
    assert [f.location for f in check(load_spec(path))] == [
        "$.paths['/v1/things'].post.requestBody.content['application/json']"
        ".schema.items.properties.startTime"
    ]


def test_response_and_component_schemas_are_walked(tmp_path):
    path = write_spec(
        tmp_path,
        """
        paths:
          /v1/things:
            get:
              responses:
                '200':
                  description: ok
                  content:
                    application/json:
                      schema:
                        type: object
                        properties:
                          seenOn:
                            type: string
        components:
          schemas:
            Thing:
              type: object
              properties:
                expiry_date:
                  type: string
        """,
    )
    assert [f.location for f in check(load_spec(path))] == [
        "$.paths['/v1/things'].get.responses['200'].content['application/json']"
        ".schema.properties.seenOn",
        "$.components.schemas.Thing.properties.expiry_date",
    ]


def test_a_location_is_never_reported_twice(tmp_path):
    """A component reachable from two operations still yields one finding per node."""
    path = write_spec(
        tmp_path,
        """
        paths:
          /v1/things:
            get:
              responses:
                '200':
                  description: ok
                  content:
                    application/json:
                      schema:
                        $ref: '#/components/schemas/Thing'
            post:
              requestBody:
                content:
                  application/json:
                    schema:
                      $ref: '#/components/schemas/Thing'
              responses:
                '201':
                  description: created
                  content:
                    application/json:
                      schema:
                        $ref: '#/components/schemas/Thing'
        components:
          schemas:
            Thing:
              type: object
              properties:
                createdAt:
                  type: string
                nested:
                  type: object
                  properties:
                    updatedOn:
                      type: string
        """,
    )
    found = [f.location for f in check(load_spec(path))]
    assert found == sorted(set(found), key=found.index)  # no duplicates
    assert found == [
        "$.components.schemas.Thing.properties.createdAt",
        "$.components.schemas.Thing.properties.nested.properties.updatedOn",
    ]


def test_colliding_locations_are_deduplicated(tmp_path):
    """Two entry points can render to the same JSONPath, and must yield one finding.

    YAML treats `200:` and `'200':` as distinct response keys, but both stringify to
    the same location segment — so the same location is genuinely produced twice.
    """
    path = write_spec(
        tmp_path,
        """
        paths:
          /v1/things:
            get:
              responses:
                200:
                  description: int key
                  content:
                    application/json:
                      schema:
                        type: object
                        properties:
                          createdAt:
                            type: string
                '200':
                  description: string key
                  content:
                    application/json:
                      schema:
                        type: object
                        properties:
                          createdAt:
                            type: string
        """,
    )
    assert [f.location for f in check(load_spec(path))] == [
        "$.paths['/v1/things'].get.responses['200'].content['application/json']"
        ".schema.properties.createdAt"
    ]


def test_check_is_idempotent(tmp_path):
    spec = load_spec(write_spec(tmp_path, object_body("createdAt:\n  type: string\n")))
    assert check(spec) == check(spec)


# --- the name heuristic -----------------------------------------------------


def test_temporal_names():
    for name in (
        "date",
        "createdAt",
        "created_on",
        "updatedOn",
        "expiryDate",
        "startTime",
        "birth_date",
        "timestamp",
        "last-seen-timestamp",
        "EffectiveDate",
        "lastSeenUTCTime",
    ):
        assert is_temporal_name(name), name


def test_non_temporal_names():
    for name in (
        None,
        "",
        "name",
        "updatedBy",
        "validate",
        "candidate",
        "version",
        "description",
        "reason",
        "at",
        "on",
        "timeout",
        "runtime",
        "timeZone",  # an identifier, not an instant
        "dateFormat",
        "retryDuration",
    ):
        assert not is_temporal_name(name), name

"""GDS-004 — JSON responses.

The two fixture assertions are the acceptance test: exactly one finding on
`examples/broken.yaml`, at the XML response, and silence on `examples/good.yaml`.
The inline specs below pin the scope decisions documented in the rule module —
allowed download types, responses with no body, and request bodies being out of
scope — so that a later widening of the rule fails a test rather than quietly
changing the fixture counts.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.gds_004_json_response_bodies import check

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

#: The one violation in broken.yaml: GET 200 responds with XML.
BROKEN_LOCATION = "$.paths['/getUserList'].get.responses['200'].content['application/xml']"


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


def _response(media_type: str, status: str = "200") -> str:
    """A single GET operation whose `status` response declares `media_type`."""
    return f"""\
        /thing:
          get:
            operationId: getThing
            responses:
              '{status}':
                description: A thing.
                content:
                  {media_type}:
                    schema:
                      type: object
        """


def _locations(spec) -> list[str]:
    return [finding.location for finding in check(spec)]


# --- fixture contract -------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding():
    findings = check(load_spec(EXAMPLES / "broken.yaml"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "GDS-004"
    assert finding.location == BROKEN_LOCATION
    assert finding.severity is Severity.WARNING
    assert finding.clause_id == "GDS-004"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_broken_fixture_does_not_flag_problem_json_responses():
    """The 429/500 problem+json and POST application/json bodies are compliant."""
    locations = _locations(load_spec(EXAMPLES / "broken.yaml"))

    assert not [loc for loc in locations if "problem+json" in loc]
    assert not [loc for loc in locations if "application/json" in loc]


def test_good_fixture_yields_no_findings():
    assert check(load_spec(EXAMPLES / "good.yaml")) == []


# --- accepted media types ---------------------------------------------------


def test_application_json_passes(tmp_path):
    assert check(_spec(tmp_path, _response("application/json"))) == []


def test_problem_json_passes(tmp_path):
    assert check(_spec(tmp_path, _response("application/problem+json", "500"))) == []


def test_hal_json_passes(tmp_path):
    assert check(_spec(tmp_path, _response("application/hal+json"))) == []


def test_json_with_charset_parameter_passes(tmp_path):
    """A pinned charset is a parameter on the media type, not a different type."""
    assert check(_spec(tmp_path, _response("'application/json; charset=utf-8'"))) == []


def test_octet_stream_is_not_flagged(tmp_path):
    """Binary download payloads are legitimately non-JSON."""
    assert check(_spec(tmp_path, _response("application/octet-stream"))) == []


def test_image_media_type_is_not_flagged(tmp_path):
    assert check(_spec(tmp_path, _response("image/png"))) == []


# --- flagged media types ----------------------------------------------------


def test_application_xml_is_flagged(tmp_path):
    findings = check(_spec(tmp_path, _response("application/xml")))

    assert len(findings) == 1
    assert findings[0].location == (
        "$.paths['/thing'].get.responses['200'].content['application/xml']"
    )
    assert findings[0].severity is Severity.WARNING


def test_text_plain_is_flagged(tmp_path):
    findings = check(_spec(tmp_path, _response("text/plain")))

    assert len(findings) == 1
    assert findings[0].location.endswith("content['text/plain']")


def test_two_bad_media_types_yield_two_findings(tmp_path):
    spec = _spec(
        tmp_path,
        """\
        /thing:
          get:
            operationId: getThing
            responses:
              '200':
                description: A thing.
                content:
                  application/json:
                    schema:
                      type: object
                  application/xml:
                    schema:
                      type: object
              '500':
                description: Boom.
                content:
                  text/xml:
                    schema:
                      type: object
        """,
    )

    findings = check(spec)

    assert len(findings) == 2
    assert [finding.location for finding in findings] == [
        "$.paths['/thing'].get.responses['200'].content['application/xml']",
        "$.paths['/thing'].get.responses['500'].content['text/xml']",
    ]


# --- scope ------------------------------------------------------------------


def test_response_with_no_content_yields_nothing(tmp_path):
    """A 204 has no body; absence of a media type is a different rule's concern."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          delete:
            operationId: deleteThing
            responses:
              '204':
                description: Deleted.
        """,
    )

    assert check(spec) == []


def test_request_body_media_type_is_not_flagged(tmp_path):
    """Request bodies are out of scope — responses only."""
    spec = _spec(
        tmp_path,
        """\
        /thing:
          post:
            operationId: createThing
            requestBody:
              required: true
              content:
                application/xml:
                  schema:
                    type: object
            responses:
              '201':
                description: Created.
                content:
                  application/json:
                    schema:
                      type: object
        """,
    )

    assert check(spec) == []


def test_empty_paths_yields_nothing(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text(
        "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths: {}\n", encoding="utf-8"
    )

    assert check(load_spec(path)) == []

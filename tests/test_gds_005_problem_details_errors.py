"""GDS-005 (consistent, documented, standard-coded errors) unit tests.

The checker is imported directly rather than through `run_deterministic_pass`, so
these tests stay green while the other Phase 1 rules are still being written and the
registry is still being wired up in `rules/__init__`.

The two fixture assertions are the acceptance criteria: exactly one finding on
`broken.yaml` at a known location, and zero on `good.yaml` (M1, zero false
positives). This rule has the widest false-positive surface in the ruleset — it
judges a *schema's shape* — so most of what follows pins a case where firing would
be wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.gds_005_problem_details_errors import check

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"

#: The minimum an OpenAPI 3.1 document needs to survive `load_spec`.
_PREAMBLE = "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\npaths: {}\n"

#: An RFC 9457 problem-details component, for `$ref` cases.
_PROBLEM_COMPONENT = """\
components:
  schemas:
    Problem:
      type: object
      properties:
        type:
          type: string
        title:
          type: string
        status:
          type: integer
        detail:
          type: string
"""


def _spec(tmp_path: Path, body: str = "", name: str = "spec.yaml"):
    """Load an inline spec: the minimal valid preamble plus `body`."""
    path = tmp_path / name
    path.write_text(_PREAMBLE + body)
    return load_spec(path)


def _response_spec(tmp_path: Path, status: str, response_body: str, extra: str = ""):
    """Build a one-operation spec whose single response body is `response_body`.

    `response_body` is indented to sit under `responses.<status>`; `extra` is appended
    at the document root (used to add `components`).
    """
    indented = "".join(
        f"          {line}\n" if line.strip() else "\n"
        for line in response_body.splitlines()
    )
    body = (
        "paths:\n"
        "  /v1/users:\n"
        "    get:\n"
        "      responses:\n"
        f"        '{status}':\n"
        "          description: a response\n"
        f"{indented}"
    )
    path = tmp_path / "response.yaml"
    path.write_text(
        "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\n" + body + extra
    )
    return load_spec(path)


_PROBLEM_JSON_BODY = """\
content:
  application/problem+json:
    schema:
      $ref: '#/components/schemas/Problem'
"""

_INLINE_PROBLEM_BODY = """\
content:
  application/json:
    schema:
      type: object
      properties:
        type:
          type: string
        title:
          type: string
        status:
          type: integer
"""

_REF_PROBLEM_BODY = """\
content:
  application/json:
    schema:
      $ref: '#/components/schemas/Problem'
"""

_AD_HOC_BODY = """\
content:
  application/json:
    schema:
      type: object
      properties:
        err_msg:
          type: string
        err_code:
          type: integer
"""


# --- fixture contract -----------------------------------------------------------------

def test_broken_fixture_yields_exactly_one_finding():
    findings = check(load_spec(BROKEN))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "GDS-005"
    assert finding.location == (
        "$.paths['/getUserList'].post.responses['500'].content['application/json']"
    )
    assert finding.severity is Severity.WARNING
    assert finding.clause_id == "GDS-005"
    assert finding.rule_type is RuleType.DETERMINISTIC


def test_good_fixture_yields_no_findings():
    assert check(load_spec(GOOD)) == []


def test_broken_fixture_compliant_error_responses_are_not_flagged():
    """The GET 429/500 problem+json bodies, and the XML 200, must stay silent.

    Pinned separately from the count above so a regression says *which* response
    started firing rather than only that the total moved.
    """
    locations = [f.location for f in check(load_spec(BROKEN))]
    for not_flagged in (
        "$.paths['/getUserList'].get.responses['429']",
        "$.paths['/getUserList'].get.responses['500']",
        "$.paths['/getUserList'].get.responses['200']",
        "$.paths['/getUserList'].post.responses['201']",
    ):
        assert not any(location.startswith(not_flagged) for location in locations)


# --- compliant error bodies -----------------------------------------------------------

def test_problem_json_media_type_passes(tmp_path):
    """The target shape. Compliant on the media type alone."""
    spec = _response_spec(tmp_path, "500", _PROBLEM_JSON_BODY, _PROBLEM_COMPONENT)
    assert check(spec) == []


def test_inline_problem_shaped_schema_on_application_json_passes(tmp_path):
    """RFC 9457 members carried on plain `application/json` are still the shape."""
    assert check(_response_spec(tmp_path, "500", _INLINE_PROBLEM_BODY)) == []


def test_ref_to_problem_shaped_component_passes(tmp_path):
    """The shape must be judged through a local `$ref`, not only inline."""
    spec = _response_spec(tmp_path, "400", _REF_PROBLEM_BODY, _PROBLEM_COMPONENT)
    assert check(spec) == []


def test_title_and_status_alone_are_enough(tmp_path):
    body = """\
content:
  application/json:
    schema:
      type: object
      properties:
        title:
          type: string
        status:
          type: integer
"""
    assert check(_response_spec(tmp_path, "409", body)) == []


def test_allof_composition_around_a_problem_component_passes(tmp_path):
    """`allOf: [Problem, {extensions}]` is the idiomatic RFC 9457 extension."""
    body = """\
content:
  application/json:
    schema:
      allOf:
        - $ref: '#/components/schemas/Problem'
        - type: object
          properties:
            caseRef:
              type: string
"""
    spec = _response_spec(tmp_path, "422", body, _PROBLEM_COMPONENT)
    assert check(spec) == []


def test_problem_json_with_an_ad_hoc_schema_still_passes(tmp_path):
    """Documented scope: on `application/problem+json` the media type is the contract.

    Auditing the schema behind it would make this rule disagree with itself about
    what "the target shape" means, and the media type is what a client dispatches on.
    """
    body = """\
content:
  application/problem+json:
    schema:
      type: object
      properties:
        err_msg:
          type: string
"""
    assert check(_response_spec(tmp_path, "500", body)) == []


# --- ad-hoc error bodies are flagged --------------------------------------------------

def test_ad_hoc_schema_is_flagged(tmp_path):
    findings = check(_response_spec(tmp_path, "500", _AD_HOC_BODY))
    assert len(findings) == 1
    assert findings[0].location == (
        "$.paths['/v1/users'].get.responses['500'].content['application/json']"
    )
    assert findings[0].severity is Severity.WARNING
    assert findings[0].clause_id == "GDS-005"
    assert findings[0].rule_type is RuleType.DETERMINISTIC


@pytest.mark.parametrize(
    "properties",
    [
        "err_msg:\n          type: string",
        "message:\n          type: string",
        "error:\n          type: string",
        "errorCode:\n          type: integer\n        errorText:\n          type: string",
    ],
    ids=["err_msg", "message", "error", "errorCode+errorText"],
)
def test_common_ad_hoc_envelopes_are_flagged(tmp_path, properties):
    body = (
        "content:\n"
        "  application/json:\n"
        "    schema:\n"
        "      type: object\n"
        "      properties:\n"
        f"        {properties}\n"
    )
    findings = check(_response_spec(tmp_path, "400", body))
    assert len(findings) == 1


def test_ad_hoc_component_reached_through_a_ref_is_flagged(tmp_path):
    """Resolution has to work in both directions, or a `$ref` becomes a hiding place."""
    extra = """\
components:
  schemas:
    ApiError:
      type: object
      properties:
        err_msg:
          type: string
        err_code:
          type: integer
"""
    body = """\
content:
  application/json:
    schema:
      $ref: '#/components/schemas/ApiError'
"""
    findings = check(_response_spec(tmp_path, "503", body, extra))
    assert len(findings) == 1
    assert findings[0].location.endswith(".content['application/json']")


def test_range_key_error_response_is_still_shape_checked(tmp_path):
    """`4XX` is an error response, so its body is in scope even though its code is not."""
    findings = check(_response_spec(tmp_path, "4XX", _AD_HOC_BODY))
    assert len(findings) == 1
    assert findings[0].location == (
        "$.paths['/v1/users'].get.responses['4XX'].content['application/json']"
    )


# --- one violation, one finding -------------------------------------------------------

def test_two_failing_media_types_yield_only_one_finding(tmp_path):
    """A response listing two ad-hoc JSON bodies is one mistake, reported once."""
    body = """\
content:
  application/json:
    schema:
      type: object
      properties:
        err_msg:
          type: string
  application/hal+json:
    schema:
      type: object
      properties:
        err_code:
          type: integer
"""
    findings = check(_response_spec(tmp_path, "500", body))
    assert len(findings) == 1
    # The *first* failing entry, in declaration order.
    assert findings[0].location.endswith(".content['application/json']")


# --- out of scope ---------------------------------------------------------------------

def test_success_response_with_an_ad_hoc_schema_is_not_flagged(tmp_path):
    """This rule reads error responses only; a 2xx body is a domain payload."""
    assert check(_response_spec(tmp_path, "200", _AD_HOC_BODY)) == []


@pytest.mark.parametrize("status", ["200", "201", "204", "301", "304"])
def test_non_error_statuses_are_out_of_scope(tmp_path, status):
    assert check(_response_spec(tmp_path, status, _AD_HOC_BODY)) == []


def test_error_response_with_no_content_yields_nothing(tmp_path):
    """Absence is a missing-schema violation, which is a different rule's finding."""
    assert check(_response_spec(tmp_path, "500", "")) == []


def test_error_response_with_empty_content_mapping_yields_nothing(tmp_path):
    assert check(_response_spec(tmp_path, "500", "content: {}\n")) == []


def test_json_media_type_with_no_schema_yields_nothing(tmp_path):
    """An undocumented body has no shape to judge — again, a different rule."""
    body = "content:\n  application/json: {}\n"
    assert check(_response_spec(tmp_path, "500", body)) == []


def test_error_response_with_only_xml_yields_nothing(tmp_path):
    """GDS-004's territory: "responses must be JSON". Reporting here would double up."""
    body = """\
content:
  application/xml:
    schema:
      type: object
      properties:
        err_msg:
          type: string
"""
    assert check(_response_spec(tmp_path, "500", body)) == []


# --- refs we cannot follow ------------------------------------------------------------

@pytest.mark.parametrize(
    "ref",
    [
        "'#/components/schemas/DoesNotExist'",  # dangling local name
        "'errors.yaml#/Problem'",  # external file
        "'https://example.gov.uk/schemas/problem.json'",  # remote
        "'#/definitions/Problem'",  # Swagger-style pointer
    ],
    ids=["dangling", "external-file", "remote", "definitions"],
)
def test_unresolvable_ref_is_treated_as_compliant(tmp_path, ref):
    """Unknown is not wrong: guessing would false-positive on any multi-file spec."""
    body = f"content:\n  application/json:\n    schema:\n      $ref: {ref}\n"
    assert check(_response_spec(tmp_path, "500", body, _PROBLEM_COMPONENT)) == []


def test_ref_cycle_does_not_hang_or_raise(tmp_path):
    """A self-referential component is legal JSON Schema; it must not recurse away."""
    extra = """\
components:
  schemas:
    Loop:
      $ref: '#/components/schemas/Loop'
"""
    body = """\
content:
  application/json:
    schema:
      $ref: '#/components/schemas/Loop'
"""
    assert check(_response_spec(tmp_path, "500", body, extra)) == []


# --- status code check ----------------------------------------------------------------

@pytest.mark.parametrize("status", ["599", "499", "460", "419", "512"])
def test_non_standard_error_code_is_flagged_at_the_response(tmp_path, status):
    spec = _response_spec(tmp_path, status, _PROBLEM_JSON_BODY, _PROBLEM_COMPONENT)
    findings = check(spec)
    assert len(findings) == 1
    assert findings[0].location == f"$.paths['/v1/users'].get.responses['{status}']"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].clause_id == "GDS-005"


@pytest.mark.parametrize(
    "status",
    ["400", "401", "403", "404", "409", "422", "429", "500", "502", "503", "504"],
)
def test_standard_error_codes_are_not_flagged(tmp_path, status):
    """`429` and `500` in particular: both are standard and both appear in the fixtures."""
    spec = _response_spec(tmp_path, status, _PROBLEM_JSON_BODY, _PROBLEM_COMPONENT)
    assert check(spec) == []


@pytest.mark.parametrize("status", ["4XX", "5XX", "4xx", "default"])
def test_range_and_default_keys_are_not_flagged_as_bad_codes(tmp_path, status):
    """Range keys are legal OpenAPI; only plain integers are judged."""
    spec = _response_spec(tmp_path, status, _PROBLEM_JSON_BODY, _PROBLEM_COMPONENT)
    assert check(spec) == []


def test_bad_code_and_bad_shape_are_reported_separately(tmp_path):
    """Two independent violations on one response: two fixes, so two findings."""
    findings = check(_response_spec(tmp_path, "599", _AD_HOC_BODY))
    assert [f.location for f in findings] == [
        "$.paths['/v1/users'].get.responses['599']",
        "$.paths['/v1/users'].get.responses['599'].content['application/json']",
    ]


# --- malformed documents produce fewer findings, never exceptions ---------------------

@pytest.mark.parametrize(
    "body",
    [
        "paths: {}\n",
        "paths:\n  /v1/users: {}\n",
        "paths:\n  /v1/users:\n    get: {}\n",
        "paths:\n  /v1/users:\n    get:\n      responses: {}\n",
        "paths:\n  /v1/users:\n    get:\n      responses: null\n",
        "paths:\n  /v1/users:\n    get:\n      responses:\n        '500': not-a-mapping\n",
    ],
    ids=["no-paths", "no-ops", "no-responses", "empty", "null", "scalar-response"],
)
def test_structurally_odd_documents_yield_nothing(tmp_path, body):
    path = tmp_path / "odd.yaml"
    path.write_text("openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\n" + body)
    assert check(load_spec(path)) == []


@pytest.mark.parametrize(
    "body",
    [
        "content: not-a-mapping\n",
        "content:\n  application/json: not-a-mapping\n",
        "content:\n  application/json:\n    schema: not-a-mapping\n",
        "content:\n  application/json:\n    schema:\n      $ref: 42\n",
        "content:\n  application/json:\n    schema:\n      properties: not-a-mapping\n",
        "content:\n  application/json:\n    schema:\n      required: not-a-list\n",
    ],
    ids=["content", "media-object", "schema", "int-ref", "properties", "required"],
)
def test_malformed_content_nodes_yield_nothing(tmp_path, body):
    assert check(_response_spec(tmp_path, "500", body)) == []


def test_no_findings_are_shared_between_the_two_fixtures(tmp_path):
    """Sanity: the rule is not accidentally stateless-but-cached across calls."""
    assert len(check(load_spec(BROKEN))) == 1
    assert check(load_spec(GOOD)) == []
    assert len(check(load_spec(BROKEN))) == 1

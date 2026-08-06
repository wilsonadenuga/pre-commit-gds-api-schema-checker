"""NCSC-001 (no weak authentication schemes) unit tests.

The checker is imported directly rather than through `run_deterministic_pass`, so
these tests stay green while the other NCSC rules are still being written and the
registry is still being wired up in `rules/__init__`.

The two fixture assertions are the acceptance criteria: exactly one finding on
`broken.yaml` at `components.securitySchemes.basicAuth`, and zero on `good.yaml`
(M1, zero false positives). Everything else pins a case where firing would be
wrong, or a case that must fire for the rule to be worth having.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.ncsc_001_no_weak_auth import check

from tests.example_specs import BROKEN_SPEC, GOOD_SPEC, minimal_spec_body, write_spec


def _spec(tmp_path: Path, schemes_body: str = "", extra: str = ""):
    """Load a minimal spec whose `components.securitySchemes` is `schemes_body`.

    `schemes_body` is the YAML that sits under `securitySchemes:` (indented by
    six spaces to sit under `components.securitySchemes.`). `extra` is appended
    at document root, used to add out-of-scope constructs such as an operation
    with `security: []`.
    """
    if schemes_body:
        indented = "".join(
            f"      {line}\n" if line.strip() else "\n"
            for line in schemes_body.splitlines()
        )
        components_block = (
            "components:\n"
            "  securitySchemes:\n"
            f"{indented}"
        )
    else:
        components_block = ""
    body = minimal_spec_body() + components_block + extra
    return load_spec(write_spec(tmp_path, body))


# --- fixture contract -----------------------------------------------------------------

def test_broken_fixture_yields_exactly_one_finding():
    """`broken.yaml` declares `basicAuth` (http/basic) and nothing else weak."""
    findings = check(load_spec(BROKEN_SPEC))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "NCSC-001"
    assert finding.location == "$.components.securitySchemes.basicAuth"
    assert finding.severity is Severity.ERROR
    assert finding.clause_id == "NCSC-001"
    assert finding.rule_type is RuleType.DETERMINISTIC


def test_good_fixture_yields_no_findings():
    """`good.yaml` uses OAuth 2.0 client credentials — no weak schemes at all."""
    assert check(load_spec(GOOD_SPEC)) == []


# --- compliant cases ------------------------------------------------------------------

def test_oauth2_client_credentials_passes(tmp_path):
    """OAuth 2.0 client credentials is the recommended NCSC replacement."""
    body = """\
departmentOAuth:
  type: oauth2
  flows:
    clientCredentials:
      tokenUrl: https://auth.example.gov.uk/oauth2/token
      scopes:
        users.read: Read user records
"""
    assert check(_spec(tmp_path, body)) == []


def test_oauth2_authorization_code_passes(tmp_path):
    """The authorization-code flow is equally acceptable."""
    body = """\
departmentOAuth:
  type: oauth2
  flows:
    authorizationCode:
      authorizationUrl: https://auth.example.gov.uk/oauth2/authorize
      tokenUrl: https://auth.example.gov.uk/oauth2/token
      scopes:
        users.read: Read user records
"""
    assert check(_spec(tmp_path, body)) == []


def test_openid_connect_passes(tmp_path):
    """`type: openIdConnect` is a strong scheme — must not be flagged."""
    body = """\
departmentOIDC:
  type: openIdConnect
  openIdConnectUrl: https://auth.example.gov.uk/.well-known/openid-configuration
"""
    assert check(_spec(tmp_path, body)) == []


def test_mutual_tls_passes(tmp_path):
    """`type: mutualTLS` is a strong scheme — must not be flagged."""
    body = """\
departmentMTLS:
  type: mutualTLS
  description: Client-certificate authentication.
"""
    assert check(_spec(tmp_path, body)) == []


def test_bearer_jwt_passes(tmp_path):
    """Bearer JWT is allowed — NCSC bans basic and apiKey specifically, not all http schemes."""
    body = """\
bearerJwt:
  type: http
  scheme: bearer
  bearerFormat: JWT
"""
    assert check(_spec(tmp_path, body)) == []


# --- non-compliant cases --------------------------------------------------------------

def test_http_basic_is_flagged(tmp_path):
    """The canonical NCSC-banned scheme — one finding at the scheme's JSONPath."""
    body = """\
basicAuth:
  type: http
  scheme: basic
"""
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.components.securitySchemes.basicAuth"
    assert findings[0].severity is Severity.ERROR
    assert findings[0].clause_id == "NCSC-001"
    assert findings[0].rule_type is RuleType.DETERMINISTIC


def test_api_key_in_header_is_flagged(tmp_path):
    """A bare API key in a header is the classic weak scheme NCSC calls out."""
    body = """\
apiKeyAuth:
  type: apiKey
  in: header
  name: X-API-Key
"""
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.components.securitySchemes.apiKeyAuth"


def test_api_key_in_query_is_flagged(tmp_path):
    """`in: query` is still a bare API key — location does not change the verdict."""
    body = """\
apiKeyAuth:
  type: apiKey
  in: query
  name: api_key
"""
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.components.securitySchemes.apiKeyAuth"


def test_api_key_in_cookie_is_flagged(tmp_path):
    """`in: cookie` is still a bare API key."""
    body = """\
apiKeyAuth:
  type: apiKey
  in: cookie
  name: session
"""
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.components.securitySchemes.apiKeyAuth"


def test_two_offending_schemes_yield_two_findings_in_declaration_order(tmp_path):
    """One finding per weak scheme, in declaration order — the developer sees both fixes."""
    body = """\
basicAuth:
  type: http
  scheme: basic
apiKeyAuth:
  type: apiKey
  in: header
  name: X-API-Key
"""
    findings = check(_spec(tmp_path, body))
    assert [f.location for f in findings] == [
        "$.components.securitySchemes.basicAuth",
        "$.components.securitySchemes.apiKeyAuth",
    ]


# --- edge cases -----------------------------------------------------------------------

def test_no_components_key_yields_nothing(tmp_path):
    """Nothing to check — the rule stays silent, does not raise."""
    path = write_spec(tmp_path, minimal_spec_body())
    assert check(load_spec(path)) == []


def test_components_without_security_schemes_yields_nothing(tmp_path):
    """Components present but no auth declared: the rule has nothing to judge."""
    body = minimal_spec_body() + "components:\n  schemas: {}\n"
    path = write_spec(tmp_path, body)
    assert check(load_spec(path)) == []


def test_empty_security_schemes_yields_nothing(tmp_path):
    """`securitySchemes: {}` is legal OpenAPI and declares nothing weak."""
    body = minimal_spec_body() + "components:\n  securitySchemes: {}\n"
    path = write_spec(tmp_path, body)
    assert check(load_spec(path)) == []


def test_mixed_compliant_and_non_compliant_flags_only_the_weak_one(tmp_path):
    """A strong scheme alongside a weak one must not silence the weak-scheme finding."""
    body = """\
departmentOAuth:
  type: oauth2
  flows:
    clientCredentials:
      tokenUrl: https://auth.example.gov.uk/oauth2/token
      scopes:
        users.read: Read user records
legacyBasic:
  type: http
  scheme: basic
"""
    findings = check(_spec(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.components.securitySchemes.legacyBasic"


@pytest.mark.parametrize(
    "scheme_body",
    [
        "weird:\n  type: 42\n",  # non-string type
        "weird: not-a-mapping\n",  # scalar in place of a scheme object
        "weird:\n  type: http\n  scheme: 12\n",  # non-string http scheme
        "weird:\n  scheme: basic\n",  # missing `type`
    ],
    ids=["non-string-type", "scalar-entry", "non-string-scheme", "no-type"],
)
def test_malformed_scheme_entries_do_not_raise(tmp_path, scheme_body):
    """Structurally odd nodes must not crash the rule — they are skipped, not flagged."""
    # Any of these could theoretically produce zero findings; the invariant is
    # simply that the check completes without raising and does not falsely flag
    # a malformed entry as a weak scheme.
    findings = check(_spec(tmp_path, scheme_body))
    assert findings == []


# --- out of scope ---------------------------------------------------------------------

def test_operation_level_security_opt_out_is_not_our_business(tmp_path):
    """`security: []` on an operation is NCSC-002's finding. We stay silent."""
    schemes_body = """\
departmentOAuth:
  type: oauth2
  flows:
    clientCredentials:
      tokenUrl: https://auth.example.gov.uk/oauth2/token
      scopes:
        users.read: Read user records
"""
    # An operation that opts out of authentication entirely, plus a compliant
    # global `security` block. Neither is this rule's concern.
    extra = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      operationId: listUsers
      security: []
      responses:
        '200':
          description: ok
"""
    # `minimal_spec_body()` already contains `paths: {}`; we need it out so the
    # `extra` block's `paths:` is the only one. Build the spec inline instead.
    body = (
        "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\n"
        + "components:\n  securitySchemes:\n"
        + "".join(f"      {line}\n" if line.strip() else "\n" for line in schemes_body.splitlines())
        + extra
    )
    path = write_spec(tmp_path, body)
    assert check(load_spec(path)) == []

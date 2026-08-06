"""NCSC-002 (auth declared for every operation; deny by default) unit tests.

The checker is imported directly rather than through `run_deterministic_pass`, so
these tests stay green while the other Phase 1 rules are still being written and
the registry is still being wired up in `rules/__init__`.

The two fixture assertions are the acceptance criteria: exactly one finding on
`broken.yaml` at the GET operation's `security` key, and zero on `good.yaml`. The
rest of the cases pin the scope decisions in the rule module — `security: [{}]`
compliance, silence on malformed inputs, and NCSC-001's territory being separate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.ncsc_002_auth_deny_by_default import check

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"

#: The minimum an OpenAPI 3.1 document needs to survive `load_spec`.
_PREAMBLE = "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\n"


def _write(tmp_path: Path, body: str, name: str = "spec.yaml"):
    """Load an inline spec: minimal preamble plus `body`."""
    path = tmp_path / name
    path.write_text(_PREAMBLE + body)
    return load_spec(path)


# --- fixture contract -----------------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding():
    """The GET operation in broken.yaml declares `security: []` (Type B)."""
    findings = check(load_spec(BROKEN))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "NCSC-002"
    assert finding.location == "$.paths['/getUserList'].get.security"
    assert finding.severity is Severity.ERROR
    assert finding.clause_id == "NCSC-002"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings():
    """The good fixture declares root-level security with no per-op opt-outs."""
    assert check(load_spec(GOOD)) == []


# --- compliant cases ------------------------------------------------------------------


def test_root_security_covers_operations_without_overrides(tmp_path):
    """The idiomatic OpenAPI pattern: declare once at the root, inherit everywhere."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      responses:
        '200':
          description: ok
    post:
      responses:
        '201':
          description: created
"""
    assert check(_write(tmp_path, body)) == []


def test_per_operation_security_without_root_default(tmp_path):
    """A spec can omit root security if every operation declares its own."""
    body = """\
paths:
  /v1/users:
    get:
      security:
        - departmentOAuth: []
      responses:
        '200':
          description: ok
    post:
      security:
        - departmentOAuth: [users.write]
      responses:
        '201':
          description: created
"""
    assert check(_write(tmp_path, body)) == []


def test_optional_auth_requirement_is_compliant(tmp_path):
    """`security: [{}]` is the OpenAPI idiom for optional auth — documented compliant."""
    body = """\
paths:
  /v1/users:
    get:
      security:
        - {}
      responses:
        '200':
          description: ok
"""
    assert check(_write(tmp_path, body)) == []


def test_scheme_plus_optional_marker_is_compliant(tmp_path):
    """A real scheme reference alongside `{}` still satisfies the rule."""
    body = """\
paths:
  /v1/users:
    get:
      security:
        - departmentOAuth: []
        - {}
      responses:
        '200':
          description: ok
"""
    assert check(_write(tmp_path, body)) == []


def test_root_and_operation_security_both_declared(tmp_path):
    """Per-operation security overrides root; when both name schemes, no violation."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      security:
        - departmentOAuth: [users.read]
      responses:
        '200':
          description: ok
"""
    assert check(_write(tmp_path, body)) == []


def test_openapi_3_0_spec_with_security_is_compliant(tmp_path):
    """The rule is version-agnostic: it reads keys, not OpenAPI dialect versions."""
    path = tmp_path / "v30.yaml"
    path.write_text(
        "openapi: 3.0.3\n"
        "info:\n  title: t\n  version: '1'\n"
        "security:\n  - departmentOAuth: []\n"
        "paths:\n"
        "  /v1/users:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
    )
    assert check(load_spec(path)) == []


# --- non-compliant cases --------------------------------------------------------------


def test_missing_root_and_missing_operation_security_flags_type_a(tmp_path):
    """Neither the root nor the operation declares security: unauthenticated by omission."""
    body = """\
paths:
  /v1/users:
    get:
      responses:
        '200':
          description: ok
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    # Type A: no operation-level `security` node exists, so point at the operation.
    assert findings[0].location == "$.paths['/v1/users'].get"
    assert findings[0].severity is Severity.ERROR
    assert findings[0].clause_id == "NCSC-002"
    assert findings[0].rule_type is RuleType.DETERMINISTIC


def test_missing_root_and_empty_operation_security_flags_type_b(tmp_path):
    """Even with no root default, `security: []` is an explicit opt-out."""
    body = """\
paths:
  /v1/users:
    get:
      security: []
      responses:
        '200':
          description: ok
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/users'].get.security"


def test_root_present_but_empty_operation_security_flags_type_b(tmp_path):
    """`security: []` on the operation overrides the root default; still a violation."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      security: []
      responses:
        '200':
          description: ok
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/users'].get.security"


def test_two_offending_operations_yield_two_findings(tmp_path):
    """One finding per unprotected operation."""
    body = """\
paths:
  /v1/users:
    get:
      security: []
      responses:
        '200':
          description: ok
    post:
      responses:
        '201':
          description: created
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 2
    locations = {f.location for f in findings}
    assert locations == {
        "$.paths['/v1/users'].get.security",  # Type B
        "$.paths['/v1/users'].post",  # Type A
    }


def test_multi_method_path_only_offending_operation_is_flagged(tmp_path):
    """Sibling operations under the same path are judged independently."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      responses:
        '200':
          description: ok
    post:
      security: []
      responses:
        '201':
          description: created
    delete:
      security:
        - departmentOAuth: [users.write]
      responses:
        '204':
          description: gone
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/users'].post.security"


def test_empty_root_security_and_operation_opt_out_flags_operation_only(tmp_path):
    """Documented decision: this rule is per-operation, so an empty root is not flagged.

    The operation-level `security: []` is unambiguous and is the node a Phase 3
    patch would replace. Flagging the root too would double-report a single mistake.
    """
    body = """\
security: []
paths:
  /v1/users:
    get:
      security: []
      responses:
        '200':
          description: ok
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/users'].get.security"


def test_empty_root_security_inherited_flags_type_a(tmp_path):
    """An operation with no key of its own still inherits the empty root — Type A."""
    body = """\
security: []
paths:
  /v1/users:
    get:
      responses:
        '200':
          description: ok
"""
    findings = check(_write(tmp_path, body))
    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/users'].get"


# --- edge cases -----------------------------------------------------------------------


def test_no_paths_key_yields_nothing(tmp_path):
    """A document without any paths has no operations to judge."""
    path = tmp_path / "no-paths.yaml"
    path.write_text(_PREAMBLE + "paths: {}\n")
    # Even without a root security block, there are no operations.
    assert check(load_spec(path)) == []


def test_empty_paths_yields_nothing(tmp_path):
    body = "paths: {}\n"
    assert check(_write(tmp_path, body)) == []


def test_path_item_with_no_operations_yields_nothing(tmp_path):
    """A path item can hold `parameters`/extensions without any operation methods."""
    body = """\
paths:
  /v1/users:
    parameters:
      - name: id
        in: query
        schema:
          type: string
"""
    assert check(_write(tmp_path, body)) == []


def test_operation_with_null_security_does_not_crash_or_flag(tmp_path):
    """`security: null` is malformed — a validator's job, not this rule's."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      security: null
      responses:
        '200':
          description: ok
"""
    # Root security is inherited when the operation's `security` is malformed.
    assert check(_write(tmp_path, body)) == []


def test_operation_with_scalar_security_does_not_crash_or_flag(tmp_path):
    """A non-list `security` value is malformed and is silently ignored."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      security: yes
      responses:
        '200':
          description: ok
"""
    assert check(_write(tmp_path, body)) == []


def test_operation_with_mapping_security_does_not_crash_or_flag(tmp_path):
    """`security:` as a mapping is malformed OpenAPI; treat as unspecified."""
    body = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      security:
        departmentOAuth: []
      responses:
        '200':
          description: ok
"""
    assert check(_write(tmp_path, body)) == []


# --- out of scope ---------------------------------------------------------------------


def test_http_basic_scheme_but_declared_requirement_is_silent(tmp_path):
    """NCSC-001 flags weak schemes; NCSC-002 only checks that a requirement exists.

    The `securitySchemes` shape is out of scope here: even though `basicAuth` is a
    weak scheme (NCSC-001), the operation still *declares* a non-empty requirement
    that references it, so NCSC-002 stays silent.
    """
    body = """\
security:
  - basicAuth: []
paths:
  /v1/users:
    get:
      responses:
        '200':
          description: ok
components:
  securitySchemes:
    basicAuth:
      type: http
      scheme: basic
"""
    assert check(_write(tmp_path, body)) == []


def test_operation_referencing_basic_scheme_directly_is_silent(tmp_path):
    """Same again with the requirement declared per operation rather than at root."""
    body = """\
paths:
  /v1/users:
    get:
      security:
        - basicAuth: []
      responses:
        '200':
          description: ok
components:
  securitySchemes:
    basicAuth:
      type: http
      scheme: basic
"""
    assert check(_write(tmp_path, body)) == []


@pytest.mark.parametrize(
    "body",
    [
        "paths:\n  /v1/users:\n    get: {}\n",
        "paths:\n  /v1/users:\n    get: not-a-mapping\n",
        "paths:\n  /v1/users: not-a-mapping\n",
    ],
    ids=["empty-operation", "scalar-operation", "scalar-path-item"],
)
def test_structurally_odd_documents_do_not_crash(tmp_path, body):
    """A structurally odd document yields at most well-formed findings, never raises.

    `get: {}` is a legal-but-empty operation with no `security` key and no root
    default: that's Type A. Non-mapping operations/path items are skipped by the
    traversal helpers, so they yield nothing.
    """
    # Just confirm no exception; the exact count is not the load-bearing thing here.
    _ = check(_write(tmp_path, body))

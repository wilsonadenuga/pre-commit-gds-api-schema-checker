"""REC-001 (kebab-case, plural-noun paths) unit tests.

The checker is imported directly from its module, so this test file runs green
even while `rules/__init__` has not yet wired REC-001 into the registry. The
important invariants pinned here:

*   Exactly one violation per path — a `/getUserList` that trips all three
    checks emits one finding, not three (the "one finding per path" rule).
*   The singular-noun check is *conservative*: ambiguous segments
    (`data`, `status`, `me`, ...) never fire, even though they look nounish.
*   Path parameters (`{orderId}`) and version segments (`v1`, `V2`) are outside
    REC-001's remit — camelCase parameter names and uppercase versions must
    stay silent so this rule does not double up with GDS-003 or with
    parameter-naming conventions.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.rec_001_kebab_case_plural_paths import check

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"

_HEADER_31 = """openapi: 3.1.0
info:
  title: t
  version: '1'
"""

_HEADER_30 = """openapi: 3.0.3
info:
  title: t
  version: '1'
"""


def _write(tmp_path: Path, body: str, header: str = _HEADER_31) -> Path:
    """Write a minimal OpenAPI document with `body` appended, return its path."""
    target = tmp_path / "spec.yaml"
    target.write_text(header + body, encoding="utf-8")
    return target


def _check(tmp_path: Path, body: str, header: str = _HEADER_31) -> list:
    return check(load_spec(_write(tmp_path, body, header)))


def _paths_block(*paths: str) -> str:
    """Render a valid `paths:` block declaring each `path` with a GET/200."""
    lines = ["paths:"]
    for path in paths:
        lines.append(f"  '{path}':")
        lines.append("    get:")
        lines.append("      responses:")
        lines.append("        '200':")
        lines.append("          description: ok")
    return "\n".join(lines) + "\n"


# --- fixture contract -------------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding() -> None:
    """`broken.yaml`'s `/getUserList` is the one intentional REC-001 violation."""
    findings = check(load_spec(BROKEN))

    assert len(findings) == 1, [f.location for f in findings]
    finding = findings[0]
    assert finding.rule_id == "REC-001"
    assert finding.location == "$.paths['/getUserList']"
    assert finding.severity is Severity.SUGGESTION
    assert finding.clause_id == "REC-001"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings() -> None:
    """`good.yaml` uses `/v1/users` — kebab-case, plural. Nothing should fire."""
    assert check(load_spec(GOOD)) == []


# --- compliant paths --------------------------------------------------------------


def test_kebab_case_plural_collection_passes(tmp_path: Path) -> None:
    """The canonical good case: `/v1/users`."""
    assert _check(tmp_path, _paths_block("/v1/users")) == []


def test_multi_word_kebab_case_passes(tmp_path: Path) -> None:
    """Hyphens between words are the whole point of kebab-case."""
    assert _check(tmp_path, _paths_block("/v1/user-preferences")) == []


def test_camel_case_path_parameter_does_not_trigger_case_check(tmp_path: Path) -> None:
    """`{orderId}` is idiomatic OpenAPI — the case check must ignore parameters."""
    assert _check(tmp_path, _paths_block("/v1/orders/{orderId}/items")) == []


def test_known_ambiguous_singletons_are_not_flagged(tmp_path: Path) -> None:
    """`/health`, `/status`, `/me` are conventionally singular; do not flag."""
    findings = _check(tmp_path, _paths_block("/health", "/status", "/me"))

    assert findings == []


def test_ambiguous_plural_data_is_not_flagged(tmp_path: Path) -> None:
    """`data` is a mass noun; the conservative check leaves it alone."""
    assert _check(tmp_path, _paths_block("/v1/data")) == []


def test_action_noun_search_is_not_flagged(tmp_path: Path) -> None:
    """`search` reads as an action endpoint; safe-listed and not flagged."""
    assert _check(tmp_path, _paths_block("/v1/search")) == []


def test_openapi_30_compliant_path_yields_nothing(tmp_path: Path) -> None:
    """The rule must work identically on OpenAPI 3.0 documents."""
    assert _check(tmp_path, _paths_block("/v1/users"), header=_HEADER_30) == []


def test_version_segment_uppercase_v2_is_not_flagged(tmp_path: Path) -> None:
    """`V2` is a version segment (GDS-003's turf), not a case violation."""
    assert _check(tmp_path, _paths_block("/V2/users")) == []


# --- non-compliant paths ----------------------------------------------------------


def test_camel_case_with_verb_and_singular_emits_one_finding(tmp_path: Path) -> None:
    """`/getUserList` trips all three checks — still exactly one finding."""
    findings = _check(tmp_path, _paths_block("/getUserList"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/getUserList']"
    # The snippet should describe the violations, not merely restate the rule id.
    snippet_text = findings[0].snippet.lower()
    assert "kebab" in snippet_text or "uppercase" in snippet_text
    assert "verb" in snippet_text


def test_pascal_case_path_is_flagged(tmp_path: Path) -> None:
    """`/UserList` is PascalCase; a single case-violation finding."""
    findings = _check(tmp_path, _paths_block("/UserList"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/UserList']"


def test_snake_case_path_is_flagged(tmp_path: Path) -> None:
    """`/user_list` has an underscore — the case check treats that as a violation."""
    findings = _check(tmp_path, _paths_block("/user_list"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/user_list']"


def test_mid_path_verb_plus_case_emits_one_finding(tmp_path: Path) -> None:
    """`/users/GetById/{id}` — verb + PascalCase on the second segment; one finding."""
    findings = _check(tmp_path, _paths_block("/users/GetById/{id}"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/users/GetById/{id}']"


def test_singular_known_noun_segment_is_flagged(tmp_path: Path) -> None:
    """`/v1/user/{id}` — `user` is a known singular; expect one plural-noun finding."""
    findings = _check(tmp_path, _paths_block("/v1/user/{id}"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/user/{id}']"
    assert "singular" in findings[0].snippet.lower()


def test_two_offending_paths_yield_two_findings(tmp_path: Path) -> None:
    """Each offending path emits one finding; ordering follows declaration order."""
    findings = _check(tmp_path, _paths_block("/getUserList", "/v1/user/{id}"))

    assert [f.location for f in findings] == [
        "$.paths['/getUserList']",
        "$.paths['/v1/user/{id}']",
    ]


def test_all_uppercase_segment_is_flagged(tmp_path: Path) -> None:
    """`/v1/USERS` — SCREAMING_CASE trips the case check; one finding."""
    findings = _check(tmp_path, _paths_block("/v1/USERS"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/v1/USERS']"


def test_parameter_with_verb_like_name_is_not_flagged(tmp_path: Path) -> None:
    """Parameter internals are out of scope for MVP — `/{getUser}` stays silent."""
    assert _check(tmp_path, _paths_block("/{getUser}")) == []


# --- edge cases -------------------------------------------------------------------


def test_empty_paths_mapping_yields_nothing(tmp_path: Path) -> None:
    """`paths: {}` has nothing to check — no findings."""
    assert _check(tmp_path, "paths: {}\n") == []


def test_root_path_alone_yields_nothing(tmp_path: Path) -> None:
    """A bare `/` root path has no segments to name."""
    assert _check(tmp_path, _paths_block("/")) == []


def test_parameter_only_path_yields_nothing(tmp_path: Path) -> None:
    """`/{id}` has no non-parameter segment to check — silent."""
    assert _check(tmp_path, _paths_block("/{id}")) == []


def test_non_dict_paths_value_does_not_crash(tmp_path: Path) -> None:
    """A wrongly-typed `paths:` node must not raise — schema-shape is the loader's job."""
    body = textwrap.dedent(
        """\
        paths:
          - not a mapping
        """
    )
    assert _check(tmp_path, body) == []


def test_trailing_slash_treated_like_no_slash(tmp_path: Path) -> None:
    """`/users/` and `/users` are semantically equivalent for naming purposes."""
    assert _check(tmp_path, _paths_block("/users/")) == []


# --- out-of-scope -----------------------------------------------------------------


def test_operation_details_are_not_this_rules_business(tmp_path: Path) -> None:
    """Paths compliant, operations missing summary/description — REC-001 stays silent.

    That is REC-002's job; REC-001 must not reach into operation-level content or
    it would double up.
    """
    body = textwrap.dedent(
        """\
        paths:
          '/v1/users':
            get:
              responses:
                '200':
                  description: ok
          '/v1/orders':
            post:
              responses:
                '201':
                  description: created
        """
    )
    findings = _check(tmp_path, body)

    assert findings == []

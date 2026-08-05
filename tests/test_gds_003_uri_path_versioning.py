"""GDS-003 — versioning declared in the URI path.

The fixture assertions are the acceptance test: `broken.yaml` must yield exactly one
finding at exactly one location, and `good.yaml` must yield none. The inline specs
below pin the edge cases that the fixtures do not exercise — case, minor versions,
partial-segment near-misses, and the `servers`-carries-the-version escape hatch.
"""

from __future__ import annotations

from pathlib import Path

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.gds_003_uri_path_versioning import check

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

_HEADER = """openapi: 3.1.0
info:
  title: t
  version: '1'
"""


def _write_spec(tmp_path: Path, body: str, name: str = "spec.yaml") -> Path:
    """Write a minimal OpenAPI document with `body` appended, and return its path."""
    target = tmp_path / name
    target.write_text(_HEADER + body, encoding="utf-8")
    return target


def _check(tmp_path: Path, body: str, name: str = "spec.yaml") -> list:
    return check(load_spec(_write_spec(tmp_path, body, name)))


def _paths_spec(*paths: str) -> str:
    lines = ["paths:"]
    for path in paths:
        lines.append(f"  '{path}':")
        lines.append("    get:")
        lines.append("      responses:")
        lines.append("        '200':")
        lines.append("          description: ok")
    return "\n".join(lines) + "\n"


def _servers_block(*urls: str) -> str:
    lines = ["servers:"]
    for url in urls:
        lines.append(f"  - url: {url}")
    return "\n".join(lines) + "\n"


# --- fixture contract -------------------------------------------------------------


def test_broken_fixture_yields_exactly_one_finding() -> None:
    findings = check(load_spec(EXAMPLES / "broken.yaml"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "GDS-003"
    assert finding.location == "$.paths['/getUserList']"
    assert finding.severity is Severity.WARNING
    assert finding.clause_id == "GDS-003"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert finding.snippet


def test_good_fixture_yields_no_findings() -> None:
    assert check(load_spec(EXAMPLES / "good.yaml")) == []


# --- version segment recognition --------------------------------------------------


def test_v1_segment_passes(tmp_path: Path) -> None:
    assert _check(tmp_path, _paths_spec("/v1/users")) == []


def test_uppercase_v2_segment_passes(tmp_path: Path) -> None:
    assert _check(tmp_path, _paths_spec("/V2/users")) == []


def test_minor_version_segment_passes(tmp_path: Path) -> None:
    assert _check(tmp_path, _paths_spec("/v1.0/users")) == []


def test_version_segment_may_appear_after_the_first_segment(tmp_path: Path) -> None:
    assert _check(tmp_path, _paths_spec("/users/v1/records")) == []


def test_unversioned_path_is_flagged(tmp_path: Path) -> None:
    findings = _check(tmp_path, _paths_spec("/users"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/users']"


def test_version_inside_a_larger_segment_is_flagged(tmp_path: Path) -> None:
    # `/service-v1-beta/users`: "v1" is part of a name, not a whole segment.
    findings = _check(tmp_path, _paths_spec("/service-v1-beta/users"))

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/service-v1-beta/users']"


def test_two_unversioned_paths_yield_two_findings(tmp_path: Path) -> None:
    findings = _check(tmp_path, _paths_spec("/users", "/orders"))

    assert len(findings) == 2
    assert [f.location for f in findings] == [
        "$.paths['/users']",
        "$.paths['/orders']",
    ]


def test_only_the_unversioned_path_of_a_mixed_pair_is_flagged(tmp_path: Path) -> None:
    findings = _check(tmp_path, _paths_spec("/v1/users", "/orders"))

    assert [f.location for f in findings] == ["$.paths['/orders']"]


# --- versioning carried by the servers URL ----------------------------------------


def test_version_in_server_url_suppresses_findings(tmp_path: Path) -> None:
    body = _servers_block("https://api.example.gov.uk/v1") + _paths_spec("/users")

    assert _check(tmp_path, body) == []


def test_version_in_only_one_of_two_server_urls_does_not_suppress(tmp_path: Path) -> None:
    body = _servers_block(
        "https://api.example.gov.uk/v1",
        "https://staging.example.gov.uk",
    ) + _paths_spec("/users")

    findings = _check(tmp_path, body)

    assert len(findings) == 1
    assert findings[0].location == "$.paths['/users']"


def test_versioned_hostname_does_not_suppress(tmp_path: Path) -> None:
    # A `v2.` hostname is not URI-path versioning.
    body = _servers_block("https://v2.api.example.gov.uk") + _paths_spec("/users")

    assert len(_check(tmp_path, body)) == 1


def test_empty_servers_list_does_not_suppress(tmp_path: Path) -> None:
    body = "servers: []\n" + _paths_spec("/users")

    assert len(_check(tmp_path, body)) == 1


# --- degenerate documents ---------------------------------------------------------


def test_missing_paths_yields_nothing(tmp_path: Path) -> None:
    assert _check(tmp_path, "components: {}\n") == []


def test_empty_paths_mapping_yields_nothing(tmp_path: Path) -> None:
    assert _check(tmp_path, "paths: {}\n") == []

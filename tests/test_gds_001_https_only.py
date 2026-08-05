"""GDS-001 (HTTPS-only) unit tests.

The checker is imported directly rather than through `run_deterministic_pass`, so
these tests stay green while the other Phase 1 rules are still being written and the
registry is still being wired up in `rules/__init__`.

The two fixture assertions are the acceptance criteria: exactly one finding on
`broken.yaml` at a known location, and zero on `good.yaml` (M1, zero false
positives). The rest are edge cases that would each be a false positive or a crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules.gds_001_https_only import check

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"

#: The minimum an OpenAPI 3.1 document needs to survive `load_spec`.
_PREAMBLE = "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\npaths: {}\n"


def _spec(tmp_path: Path, body: str = "", name: str = "spec.yaml"):
    """Load an inline spec: the minimal valid preamble plus `body`."""
    path = tmp_path / name
    path.write_text(_PREAMBLE + body)
    return load_spec(path)


def _servers(*urls: str) -> str:
    return "servers:\n" + "".join(f"  - url: {url}\n" for url in urls)


# --- fixture contract -----------------------------------------------------------------

def test_broken_fixture_yields_exactly_one_finding():
    findings = check(load_spec(BROKEN))
    assert len(findings) == 1, [f.location for f in findings]

    finding = findings[0]
    assert finding.rule_id == "GDS-001"
    assert finding.location == "$.servers[0].url"
    assert finding.severity is Severity.ERROR
    assert finding.clause_id == "GDS-001"
    assert finding.rule_type is RuleType.DETERMINISTIC
    assert "http://api.example.gov.uk" in finding.snippet


def test_good_fixture_yields_no_findings():
    assert check(load_spec(GOOD)) == []


# --- compliant server URLs ------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.gov.uk",
        "https://api.example.gov.uk/v1",
        "HTTPS://api.example.gov.uk",  # schemes are case-insensitive (RFC 3986 s3.1)
        "'https://{host}/v1'",  # server variable in the host: scheme still pinned
        "'https://api.example.gov.uk/{basePath}'",
        "/api",  # relative: inherits the serving host's scheme
        "'{server}/v1'",
        "v1/users",
        "'/'",
    ],
)
def test_compliant_url_is_not_flagged(tmp_path, url):
    assert check(_spec(tmp_path, _servers(url))) == []


# --- non-compliant server URLs --------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.gov.uk",
        "'http://{host}/v1'",
        "HTTP://api.example.gov.uk",
        "ws://api.example.gov.uk",
    ],
)
def test_non_https_scheme_is_flagged_once(tmp_path, url):
    findings = check(_spec(tmp_path, _servers(url)))
    assert len(findings) == 1
    assert findings[0].location == "$.servers[0].url"
    assert findings[0].severity is Severity.ERROR


def test_multiple_bad_servers_yield_one_finding_each_with_correct_indices(tmp_path):
    """One violation, one finding — and the index must identify which entry."""
    spec = _spec(
        tmp_path,
        _servers(
            "http://one.example.gov.uk",
            "https://two.example.gov.uk",
            "http://three.example.gov.uk",
        ),
    )
    findings = check(spec)
    assert [f.location for f in findings] == ["$.servers[0].url", "$.servers[2].url"]
    assert [f.snippet for f in findings] == [
        "http://one.example.gov.uk",
        "http://three.example.gov.uk",
    ]


# --- absent or malformed `servers` ----------------------------------------------------

def test_missing_servers_key_yields_nothing(tmp_path):
    """Absence is not a violation: no declared URL means no declared transport."""
    assert check(_spec(tmp_path)) == []


def test_empty_servers_list_yields_nothing(tmp_path):
    assert check(_spec(tmp_path, "servers: []\n")) == []


@pytest.mark.parametrize(
    "body",
    [
        "servers: http://api.example.gov.uk\n",  # scalar where a list belongs
        "servers:\n  production: http://api.example.gov.uk\n",  # mapping, not a list
        "servers: null\n",
    ],
    ids=["scalar", "mapping", "null"],
)
def test_non_list_servers_yields_nothing(tmp_path, body):
    """A malformed spec must produce fewer findings, never an exception."""
    assert check(_spec(tmp_path, body)) == []


@pytest.mark.parametrize(
    "body",
    [
        "servers:\n  - description: no url at all\n",
        "servers:\n  - url: null\n",
        "servers:\n  - url: 42\n",
        "servers:\n  - just a string, not a server object\n",
    ],
    ids=["no-url", "null-url", "int-url", "scalar-entry"],
)
def test_malformed_server_entry_is_skipped_not_reported(tmp_path, body):
    """A missing/non-string `url` is a schema error, not a transport violation."""
    assert check(_spec(tmp_path, body)) == []


def test_a_malformed_entry_does_not_hide_a_later_violation(tmp_path):
    spec = _spec(
        tmp_path,
        "servers:\n  - description: no url\n  - url: http://api.example.gov.uk\n",
    )
    findings = check(spec)
    assert [f.location for f in findings] == ["$.servers[1].url"]


# --- the rule does not read anywhere else ---------------------------------------------

def test_path_level_server_overrides_are_out_of_scope(tmp_path):
    """Documented scope: the root `servers` array only.

    A path-level override is a real gap, but silently widening scope here would
    change the fixture finding count, so it is pinned by a test.
    """
    path = tmp_path / "override.yaml"
    path.write_text(
        "openapi: 3.1.0\n"
        "info:\n  title: t\n  version: '1'\n"
        "servers:\n  - url: https://api.example.gov.uk\n"
        "paths:\n"
        "  /v1/users:\n"
        "    servers:\n      - url: http://legacy.example.gov.uk\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n          description: ok\n"
    )
    assert check(load_spec(path)) == []

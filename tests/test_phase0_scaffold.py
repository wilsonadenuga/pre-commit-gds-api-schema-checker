"""Phase 0 exit criterion, as a test.

"The CLI runs, loads both fixtures, and prints an empty findings report without
error." Plus the fixture-quality checks that Phase 0 says are won or lost here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from gds_api_schema_uplift.cli import EXIT_ERROR, EXIT_OK, app
from gds_api_schema_uplift.loader import SpecLoadError, load_spec
from gds_api_schema_uplift.rules import REGISTRY, run_deterministic_pass

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKEN = REPO_ROOT / "examples" / "broken.yaml"
GOOD = REPO_ROOT / "examples" / "good.yaml"

runner = CliRunner()


# --- the registry is empty in Phase 0 -------------------------------------------------

def test_registry_is_empty_until_phase_1():
    assert REGISTRY == {}, (
        "Phase 0 ships no rules. When Phase 1 lands, replace this with the "
        "GDS-001..005 registration assertions."
    )


# --- both fixtures load ---------------------------------------------------------------

@pytest.mark.parametrize("path", [BROKEN, GOOD], ids=["broken", "good"])
def test_fixture_loads_as_openapi_3(path):
    spec = load_spec(path)
    assert spec.is_openapi_3
    assert not spec.is_swagger_2
    assert spec.openapi_version == "3.1.0"


@pytest.mark.parametrize("path", [BROKEN, GOOD], ids=["broken", "good"])
def test_fixture_produces_no_findings_with_an_empty_registry(path):
    assert run_deterministic_pass(load_spec(path)) == []


def test_good_fixture_round_trips_byte_identically():
    """Pre-stages Phase 1's round-trip proof, and validates the fixture itself.

    If good.yaml cannot survive load -> dump unchanged, it is unfit as the
    round-trip fixture regardless of what the writer code does later.
    """
    original = GOOD.read_text()
    assert load_spec(GOOD).dumps() == original


# --- fixture quality ------------------------------------------------------------------

def test_broken_fixture_is_structurally_valid_openapi():
    """Violations must be standards violations, not schema errors.

    A schema-invalid broken.yaml would fail before any rule ran, which is why this
    is asserted at Phase 0 rather than discovered in Phase 1.
    """
    validator = pytest.importorskip(
        "openapi_spec_validator", reason="openapi-spec-validator not installed"
    )
    # Round-trip structures are dict/list subclasses, so the validator accepts them.
    validator.validate(load_spec(BROKEN).data)


def test_good_fixture_is_structurally_valid_openapi():
    validator = pytest.importorskip(
        "openapi_spec_validator", reason="openapi-spec-validator not installed"
    )
    validator.validate(load_spec(GOOD).data)


def test_broken_and_good_describe_the_same_service():
    """The two fixtures must differ only in compliance, not in subject matter.

    Otherwise a rule can pass on good.yaml for the wrong reason — because the
    relevant construct is simply absent rather than correct.
    """
    broken, good = load_spec(BROKEN).data, load_spec(GOOD).data
    assert broken["info"]["title"] == good["info"]["title"]
    assert len(broken["paths"]) == len(good["paths"]) == 1
    broken_ops = set(next(iter(broken["paths"].values())))
    good_ops = set(next(iter(good["paths"].values())))
    assert broken_ops == good_ops == {"get", "post"}


# --- loader failure modes -------------------------------------------------------------

def test_missing_spec_is_reported_not_raised_as_oserror(tmp_path):
    with pytest.raises(SpecLoadError, match="not found"):
        load_spec(tmp_path / "nope.yaml")


def test_non_api_document_is_rejected(tmp_path):
    path = tmp_path / "random.yaml"
    path.write_text("just: a mapping\n")
    with pytest.raises(SpecLoadError, match="does not look like"):
        load_spec(path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("")
    with pytest.raises(SpecLoadError, match="empty"):
        load_spec(path)


def test_scalar_root_is_rejected(tmp_path):
    path = tmp_path / "scalar.yaml"
    path.write_text("just a string\n")
    with pytest.raises(SpecLoadError, match="mapping at the document root"):
        load_spec(path)


# --- CLI ------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [BROKEN, GOOD], ids=["broken", "good"])
def test_cli_prints_empty_report_and_exits_zero(path):
    result = runner.invoke(app, [str(path)])
    assert result.exit_code == EXIT_OK, result.output
    assert "No findings" in result.output


def test_cli_says_plainly_that_no_rules_ran():
    """An empty report must not read as a compliance pass while the registry is empty."""
    result = runner.invoke(app, [str(BROKEN)])
    assert "rule registry is empty" in result.output


def test_cli_json_format_reports_rules_run():
    import json

    result = runner.invoke(app, [str(GOOD), "--format", "json"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert payload["findings"] == []
    assert payload["rules_run"] == 0
    assert payload["openapi_version"] == "3.1.0"


def test_cli_rejects_github_format_rather_than_silently_falling_back():
    result = runner.invoke(app, [str(GOOD), "--format", "github"])
    assert result.exit_code == EXIT_ERROR
    assert "not implemented" in result.output


def test_cli_accepts_the_phase_0_flag_surface():
    """Flags are frozen now even though the agent lands in Phase 3."""
    result = runner.invoke(app, [str(GOOD), "--no-llm", "--max-llm-calls", "0"])
    assert result.exit_code == EXIT_OK, result.output


def test_cli_reports_a_missing_spec_cleanly():
    result = runner.invoke(app, ["does-not-exist.yaml"])
    assert result.exit_code == EXIT_ERROR
    assert "Could not load spec" in result.output


def test_cli_reports_a_missing_standards_corpus_cleanly(tmp_path):
    result = runner.invoke(app, [str(GOOD), "--standards", str(tmp_path / "nope.yaml")])
    assert result.exit_code == EXIT_ERROR
    assert "Could not load standards corpus" in result.output

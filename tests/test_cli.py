"""End-to-end CLI behaviour: exit codes, flags, and rendered output.

Everything invoked through `CliRunner` lives here. Exit codes carry meaning for a
pre-commit hook, so they are asserted explicitly on every path: 0 clean, 1 findings,
3 operational failure.
"""

from __future__ import annotations

import json

import pytest
from example_specs import (
    BROKEN_SPEC,
    GOOD_SPEC,
    MINIMAL_SPEC,
    SWAGGER_2_SPEC,
    write_spec,
)
from typer.testing import CliRunner

from gds_api_schema_uplift.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, app

runner = CliRunner()


# --- exit codes -----------------------------------------------------------------------

def test_clean_spec_exits_zero():
    result = runner.invoke(app, [str(GOOD_SPEC)])
    assert result.exit_code == EXIT_OK, result.output
    assert "No findings" in result.output


def test_findings_exit_one():
    """Exit 1 on findings is what makes this usable as a pre-commit hook."""
    result = runner.invoke(app, [str(BROKEN_SPEC)])
    assert result.exit_code == EXIT_FINDINGS, result.output
    assert "GDS-001" in result.output


def test_missing_spec_exits_three():
    result = runner.invoke(app, ["does-not-exist.yaml"])
    assert result.exit_code == EXIT_ERROR
    assert "Could not load spec" in result.output


def test_missing_standards_corpus_exits_three(tmp_path):
    result = runner.invoke(
        app, [str(GOOD_SPEC), "--standards", str(tmp_path / "nope.yaml")]
    )
    assert result.exit_code == EXIT_ERROR
    assert "Could not load standards corpus" in result.output


def test_no_arguments_shows_help_rather_than_a_traceback():
    result = runner.invoke(app, [])
    assert "Usage" in result.output


# --- version policy surfaced through the CLI ------------------------------------------

def test_swagger_2_is_an_operational_failure_not_a_clean_pass(tmp_path):
    """Exit 3, not 0 — a refused spec has not been assessed, so it is not clean."""
    path = write_spec(tmp_path, SWAGGER_2_SPEC)
    result = runner.invoke(app, [str(path)])
    assert result.exit_code == EXIT_ERROR
    assert "Unsupported spec version" in result.output


def test_3_0_spec_runs_and_surfaces_the_upgrade_note(tmp_path):
    path = write_spec(tmp_path, MINIMAL_SPEC.format(version="3.0.3"))
    result = runner.invoke(app, [str(path)])
    assert result.exit_code == EXIT_OK, result.output
    assert "Consider upgrading" in result.output


# --- flags ----------------------------------------------------------------------------

def test_accepts_the_frozen_flag_surface():
    """Flags are frozen from Phase 0 even though the agent lands in Phase 3."""
    result = runner.invoke(app, [str(GOOD_SPEC), "--no-llm", "--max-llm-calls", "0"])
    assert result.exit_code == EXIT_OK, result.output


def test_rejects_github_format_rather_than_silently_falling_back():
    """A CI integration must not be built on a format that quietly degrades."""
    result = runner.invoke(app, [str(GOOD_SPEC), "--format", "github"])
    assert result.exit_code == EXIT_ERROR
    assert "not implemented" in result.output


def test_negative_max_llm_calls_is_a_usage_error():
    result = runner.invoke(app, [str(GOOD_SPEC), "--max-llm-calls", "-1"])
    assert result.exit_code != EXIT_OK


# --- text report ----------------------------------------------------------------------

def test_text_report_shows_rule_severity_and_location():
    result = runner.invoke(app, [str(BROKEN_SPEC)])
    assert result.exit_code == EXIT_FINDINGS
    # Rich wraps and folds at the terminal width, so assert on fragments that
    # survive layout rather than on whole JSONPaths.
    assert "GDS-001" in result.output
    assert "error" in result.output
    assert "servers" in result.output


def test_text_report_summarises_counts_by_severity():
    """v0.2 ruleset breakdown on broken.yaml: 3 errors (GDS-001, NCSC-001, NCSC-002),
    5 warnings (GDS-002..005 + NCSC-003), 1 suggestion (NCSC-004)."""
    result = runner.invoke(app, [str(BROKEN_SPEC)])
    assert "9 finding(s)" in result.output
    assert "3 error" in result.output
    assert "5 warning" in result.output
    assert "1 suggestion" in result.output


def test_report_resolves_citations_now_the_corpus_is_authored():
    """The empty-corpus warning must stop firing once Phase 2 has landed.

    Its absence is the assertion: a report that still warned would mean the shipped
    corpus is not being loaded.
    """
    result = runner.invoke(app, [str(BROKEN_SPEC)])
    assert "standards corpus is empty" not in result.output


def test_no_finding_reports_an_unresolved_citation():
    """Every registered rule's clause must resolve against the shipped corpus."""
    result = runner.invoke(app, [str(BROKEN_SPEC)])
    assert "unresolved" not in result.output


def test_findings_render_the_clause_section_not_just_the_id():
    """A citation is only useful if it names where in the standard it came from.

    Rendered at an explicit width: the section text wraps at a narrow terminal, so
    asserting against `CliRunner` output would be a layout test, not a content one.
    """
    import io

    from rich.console import Console

    from gds_api_schema_uplift.loader import load_spec
    from gds_api_schema_uplift.report import render_text
    from gds_api_schema_uplift.rules import run_deterministic_pass
    from gds_api_schema_uplift.standards import default_standards_path, load_standards

    spec = load_spec(BROKEN_SPEC)
    buffer = io.StringIO()
    render_text(
        spec,
        run_deterministic_pass(spec),
        load_standards(default_standards_path()),
        console=Console(file=buffer, width=200),
    )
    output = buffer.getvalue()

    assert "Secure your API" in output
    assert "Use standard HTTP responses" in output
    assert "unresolved" not in output


# --- json report ----------------------------------------------------------------------

def test_json_report_on_a_clean_spec():
    result = runner.invoke(app, [str(GOOD_SPEC), "--format", "json"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert payload["findings"] == []
    assert payload["rules_run"] == 9
    assert payload["openapi_version"] == "3.1.0"


def test_json_report_carries_every_finding_contract_field():
    result = runner.invoke(app, [str(BROKEN_SPEC), "--format", "json"])
    assert result.exit_code == EXIT_FINDINGS
    payload = json.loads(result.output)
    assert len(payload["findings"]) == 9
    for finding in payload["findings"]:
        assert set(finding) == {
            "rule_id",
            "severity",
            "location",
            "snippet",
            "clause_id",
            "rule_type",
        }
        assert finding["rule_type"] == "deterministic"


def test_json_report_is_machine_parseable_without_the_advisory_notes(tmp_path):
    """Notes go to stderr so `--format=json` stdout stays valid JSON."""
    path = write_spec(tmp_path, MINIMAL_SPEC.format(version="3.0.3"))
    result = runner.invoke(app, [str(path), "--format", "json"])
    assert result.exit_code == EXIT_OK, result.output
    json.loads(result.output)  # must not raise


@pytest.mark.parametrize("spec", [BROKEN_SPEC, GOOD_SPEC], ids=["broken", "good"])
def test_json_report_records_the_spec_path(spec):
    result = runner.invoke(app, [str(spec), "--format", "json"])
    payload = json.loads(result.output)
    assert payload["spec"] == str(spec)

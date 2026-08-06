"""Every rule declares a "how to fix" example, and the renderer surfaces it.

The `good_example` per rule is what makes the deterministic report
self-sufficient: a developer running `--no-llm` sees not just what's wrong
but a concrete YAML shape to aim for. These tests are the freeze on that
contract — a rule that lands without an example, or a renderer that stops
showing them, would silently reduce the report's usefulness.

Shape mirrors `test_citation_integrity.py`: walk the registry, assert every
entry meets a completeness rule, and pin one integration check that the
data actually reaches both output formats.
"""

from __future__ import annotations

import io
import json

import pytest
from example_specs import BROKEN_SPEC, GOOD_SPEC
from rich.console import Console
from ruamel.yaml import YAML

from gds_api_schema_uplift.contracts import Finding, RuleType, Severity
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.report import (
    render_good_examples,
    render_json,
    render_text,
)
from gds_api_schema_uplift.rules import REGISTRY, run_deterministic_pass


# --- completeness of the data layer ----------------------------------------


def test_every_registered_rule_has_a_non_empty_good_example():
    """No rule ships without a fix example.

    A missing example would render as an empty panel — visually dead space
    that tells the developer nothing. Making the field required at
    register-time turns that failure mode into an import-time crash.
    """
    for rule_id, rule in REGISTRY.items():
        assert rule.good_example.strip(), f"{rule_id} declares an empty good_example"


def test_every_good_example_is_valid_yaml():
    """A fix example that itself doesn't parse is a defect.

    The renderer displays it as syntax-highlighted YAML in the terminal;
    a syntax error would look confusing rather than helpful. `YAML(typ='safe')`
    is stricter than the round-trip loader — it refuses tagged types and
    anchors that would land only via a mistake.
    """
    yaml = YAML(typ="safe")
    for rule_id, rule in REGISTRY.items():
        try:
            parsed = yaml.load(rule.good_example)
        except Exception as exc:  # noqa: BLE001 - ruamel raises a family here
            pytest.fail(f"{rule_id}: good_example is not valid YAML — {exc}")
        assert parsed is not None, f"{rule_id}: good_example parsed to None"


def test_every_good_example_stays_terminal_friendly():
    """Cap examples so no single panel dominates the report.

    An unbounded example would slowly balloon the report as new rules land;
    a bounded one forces authors to keep the example focused on the
    specific shape their rule cares about.
    """
    for rule_id, rule in REGISTRY.items():
        lines = rule.good_example.rstrip().splitlines()
        assert 2 <= len(lines) <= 12, (
            f"{rule_id}: good_example has {len(lines)} lines "
            f"(want 2..12 for a terminal-friendly panel)"
        )
        assert len(rule.good_example) <= 500, (
            f"{rule_id}: good_example is {len(rule.good_example)} chars "
            f"(want <= 500)"
        )


# --- the data reaches the JSON output --------------------------------------


def test_json_report_carries_good_examples_keyed_by_rule_id(tmp_path):
    """Machine consumers see the same dedupe-by-rule map the panels render.

    Built directly from a synthetic Findings list so the test does not
    depend on which rules happen to fire on the committed broken fixture.
    """
    spec = load_spec(GOOD_SPEC)  # any valid spec — we bypass the pass
    findings = [
        Finding(
            rule_id="GDS-001",
            severity=Severity.ERROR,
            location="$.servers[0].url",
            snippet="s",
            clause_id="GDS-001",
            rule_type=RuleType.DETERMINISTIC,
        ),
        # Same rule again — must dedupe to a single entry.
        Finding(
            rule_id="GDS-001",
            severity=Severity.ERROR,
            location="$.servers[1].url",
            snippet="s",
            clause_id="GDS-001",
            rule_type=RuleType.DETERMINISTIC,
        ),
        Finding(
            rule_id="NCSC-004",
            severity=Severity.SUGGESTION,
            location="$.paths['/x'].get.responses",
            snippet="s",
            clause_id="NCSC-004",
            rule_type=RuleType.DETERMINISTIC,
        ),
    ]
    payload = json.loads(render_json(spec, findings, standards=None))
    assert set(payload["good_examples"]) == {"GDS-001", "NCSC-004"}
    assert payload["good_examples"]["GDS-001"] == REGISTRY["GDS-001"].good_example


def test_json_report_has_empty_good_examples_when_clean():
    """A clean run reports no examples — nothing was found, nothing to fix."""
    spec = load_spec(GOOD_SPEC)
    payload = json.loads(render_json(spec, [], standards=None))
    assert payload["good_examples"] == {}


# --- the data reaches the text output --------------------------------------


def test_text_output_renders_one_panel_per_distinct_rule():
    """`GDS-002` firing three times shows one "How to fix" panel, not three.

    Rendering into a `Console(file=StringIO())` at an explicit width side-
    steps terminal wrapping and lets us count panel titles by substring.
    """
    findings = run_deterministic_pass(load_spec(BROKEN_SPEC))
    distinct = {f.rule_id for f in findings}
    buffer = io.StringIO()
    render_good_examples(findings, Console(file=buffer, width=200, force_terminal=False))
    output = buffer.getvalue()
    for rule_id in distinct:
        assert f"How to fix — {rule_id}" in output, (
            f"expected a `How to fix — {rule_id}` panel; got:\n{output}"
        )
    # No panel for a rule that didn't fire.
    for rule_id in REGISTRY:
        if rule_id not in distinct:
            assert f"How to fix — {rule_id}" not in output


def test_text_output_shows_the_rule_summary_alongside_the_yaml():
    """The panel body carries the rule's summary as context above the code.

    A stakeholder scanning the report should get "what to aim for" in prose
    before the YAML block, so the panel is legible without opening the code.
    """
    findings = [
        Finding(
            rule_id="GDS-001",
            severity=Severity.ERROR,
            location="$.servers[0].url",
            snippet="s",
            clause_id="GDS-001",
            rule_type=RuleType.DETERMINISTIC,
        )
    ]
    buffer = io.StringIO()
    render_good_examples(findings, Console(file=buffer, width=200, force_terminal=False))
    output = buffer.getvalue()
    assert REGISTRY["GDS-001"].summary in output


def test_render_text_includes_good_examples_by_default(tmp_path):
    """The findings table and the fix panels ship together — no flag needed.

    Regression guard: someone gating this behind `--show-examples` would
    silently defeat the "reports are self-sufficient" premise. This test
    fails if that ever happens.
    """
    spec = load_spec(BROKEN_SPEC)
    findings = run_deterministic_pass(spec)
    buffer = io.StringIO()
    render_text(spec, findings, standards=None, console=Console(file=buffer, width=200))
    assert "How to fix — GDS-001" in buffer.getvalue()


def test_render_text_is_silent_about_examples_on_a_clean_spec():
    """No findings → no panels. A dedicated pass to make sure of it.

    A clean run should read `No findings.` and stop; adding a stray "How to
    fix" section afterwards would confuse a reviewer scanning for problems.
    """
    spec = load_spec(GOOD_SPEC)
    buffer = io.StringIO()
    render_text(spec, [], standards=None, console=Console(file=buffer, width=200))
    assert "How to fix" not in buffer.getvalue()

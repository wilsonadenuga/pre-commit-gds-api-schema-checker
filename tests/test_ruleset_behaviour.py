"""Cross-rule properties of the deterministic pass.

Each rule has its own unit tests. Nothing there can catch two rules claiming the same
violation, a rule that fires on the compliant spec only once its neighbours are loaded
alongside it, or a rule whose emitted severity contradicts what it registered. Those
are the assertions here.
"""

from __future__ import annotations

from example_specs import BROKEN_SPEC, GOOD_SPEC

from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules import REGISTRY, run_deterministic_pass

#: Rules expected to fire exactly once each on broken.yaml.
RULES_WITH_A_FIXTURE_VIOLATION = ("GDS-001", "GDS-002", "GDS-003", "GDS-004", "GDS-005")


def broken_findings():
    return run_deterministic_pass(load_spec(BROKEN_SPEC))


# --- M1: detection and zero false positives -------------------------------------------

def test_broken_spec_meets_the_m1_detection_threshold():
    """M1: at least 5 distinct violations on the non-compliant spec."""
    findings = broken_findings()
    assert len(findings) >= 5, [f.rule_id for f in findings]


def test_good_spec_has_zero_false_positives():
    """M1's other half, and the one that erodes trust fastest if it breaks."""
    assert run_deterministic_pass(load_spec(GOOD_SPEC)) == []


def test_each_rule_fires_exactly_once_on_the_broken_spec():
    """The fixture contract: one unambiguous violation per rule, so counts are 1:1.

    A rule firing twice means either the fixture drifted or the rule double-reports;
    firing zero times means it is silently broken. A total-count assertion sees
    neither, which is why this is per-rule.
    """
    counts: dict[str, int] = dict.fromkeys(RULES_WITH_A_FIXTURE_VIOLATION, 0)
    for finding in broken_findings():
        counts[finding.rule_id] = counts.get(finding.rule_id, 0) + 1
    assert counts == dict.fromkeys(RULES_WITH_A_FIXTURE_VIOLATION, 1)


# --- no overlap between rules ----------------------------------------------------------

def test_no_two_rules_claim_the_same_location():
    """Overlapping rules would double-charge the developer for one mistake."""
    locations = [f.location for f in broken_findings()]
    assert len(locations) == len(set(locations)), locations


def test_findings_are_ordered_by_rule_id():
    rule_ids = [f.rule_id for f in broken_findings()]
    assert rule_ids == sorted(rule_ids)


# --- the finding contract holds in practice -------------------------------------------

def test_every_finding_carries_a_location_snippet_and_clause():
    for finding in broken_findings():
        assert finding.location.startswith("$"), finding
        assert finding.snippet, f"{finding.rule_id} emitted an empty snippet"
        assert finding.clause_id, f"{finding.rule_id} emitted no clause_id"


def test_emitted_severity_matches_what_the_rule_registered():
    for finding in broken_findings():
        assert finding.severity is REGISTRY[finding.rule_id].severity, finding.rule_id


def test_emitted_clause_matches_what_the_rule_registered():
    """Citation is static: a rule may not pick a different clause at finding time."""
    for finding in broken_findings():
        assert finding.clause_id == REGISTRY[finding.rule_id].clause_id, finding.rule_id


def test_emitted_rule_type_matches_what_the_rule_registered():
    for finding in broken_findings():
        assert finding.rule_type is REGISTRY[finding.rule_id].rule_type, finding.rule_id


# --- the pass is read-only -------------------------------------------------------------

def test_the_pass_does_not_perturb_the_document():
    """The deterministic pass walks ruamel round-trip structures.

    An accidental mutation there would silently corrupt a developer's file when
    Phase 4 writes it back, and would not show up as a failing rule test.
    """
    for path in (BROKEN_SPEC, GOOD_SPEC):
        spec = load_spec(path)
        run_deterministic_pass(spec)
        assert spec.dumps() == path.read_text(), path.name

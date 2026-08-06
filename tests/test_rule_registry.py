"""What is registered, and whether registration metadata is self-consistent.

The registry is how the CLI discovers rules and how Phase 2's citation integrity test
will find their clauses, so its contents are asserted explicitly rather than inferred
from whatever happens to be imported.
"""

from __future__ import annotations

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.rules import REGISTRY, deterministic_rules, llm_rules

#: Every rule expected to be registered. The v0.2 ruleset is complete at 11 rules.
EXPECTED_RULES = (
    "GDS-001",
    "GDS-002",
    "GDS-003",
    "GDS-004",
    "GDS-005",
    "NCSC-001",
    "NCSC-002",
    "NCSC-003",
    "NCSC-004",
    "REC-001",
    "REC-002",
)


def test_registry_holds_exactly_the_expected_ruleset():
    assert sorted(REGISTRY) == sorted(EXPECTED_RULES)


def test_every_rule_declares_a_clause_id_and_summary():
    """Pre-stages Phase 2's citation integrity test.

    The clause need not resolve yet — the corpus is authored in Phase 2 — but a rule
    that declares no clause at all can never be cited, so catch it now.
    """
    for rule_id, rule in REGISTRY.items():
        assert rule.clause_id, f"{rule_id} declares no clause_id"
        assert rule.summary, f"{rule_id} declares no summary"


def test_registered_severities_match_the_prd_ruleset_table():
    """PRD s7.2: errors are hard rules with security stakes; warnings are hard
    rules with quality/consistency stakes; suggestions are the low-severity
    NCSC-004 plus both REC-* recommendations."""
    for rule_id in ("GDS-001", "NCSC-001", "NCSC-002"):
        assert REGISTRY[rule_id].severity is Severity.ERROR, rule_id
    for rule_id in ("GDS-002", "GDS-003", "GDS-004", "GDS-005", "NCSC-003"):
        assert REGISTRY[rule_id].severity is Severity.WARNING, rule_id
    for rule_id in ("NCSC-004", "REC-001", "REC-002"):
        assert REGISTRY[rule_id].severity is Severity.SUGGESTION, rule_id


def test_every_current_rule_is_deterministic():
    """The LLM path lands in Phase 3; nothing should be routed to it yet."""
    assert llm_rules() == ()
    assert len(deterministic_rules()) == len(EXPECTED_RULES)
    for rule in deterministic_rules():
        assert rule.rule_type is RuleType.DETERMINISTIC


def test_rules_are_returned_in_rule_id_order():
    """Stable ordering is what makes Phase 7's goldens diffable."""
    ids = [rule.rule_id for rule in deterministic_rules()]
    assert ids == sorted(ids)


def test_registry_keys_match_the_rule_ids_they_hold():
    for rule_id, rule in REGISTRY.items():
        assert rule.rule_id == rule_id

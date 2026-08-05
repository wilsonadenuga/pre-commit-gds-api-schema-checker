"""What is registered, and whether registration metadata is self-consistent.

The registry is how the CLI discovers rules and how Phase 2's citation integrity test
will find their clauses, so its contents are asserted explicitly rather than inferred
from whatever happens to be imported.
"""

from __future__ import annotations

from gds_api_schema_uplift.contracts import RuleType, Severity
from gds_api_schema_uplift.rules import REGISTRY, deterministic_rules, llm_rules

#: Every rule expected to be registered right now. Phase 5a adds NCSC-001..004 and
#: Phase 5b adds REC-001/002 — extend this list then.
EXPECTED_RULES = ("GDS-001", "GDS-002", "GDS-003", "GDS-004", "GDS-005")


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
    """PRD s7.2: GDS-001 is an error; GDS-002..005 are warnings."""
    assert REGISTRY["GDS-001"].severity is Severity.ERROR
    for rule_id in ("GDS-002", "GDS-003", "GDS-004", "GDS-005"):
        assert REGISTRY[rule_id].severity is Severity.WARNING, rule_id


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

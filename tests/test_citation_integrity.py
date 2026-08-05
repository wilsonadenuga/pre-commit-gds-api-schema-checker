"""Citation integrity — Phase 2's exit criterion, and M2's guardrail.

M2 requires every AI suggestion to carry a link and quote from a source of truth. That
is only achievable if the corpus itself is sound, so these tests are deliberately
build-breaking: a rule whose citation does not resolve, or a `standard`-authority
clause citing something other than gov.uk / ncsc.gov.uk, fails the suite rather than
degrading a finding at runtime.

The distinction that makes this tractable: `authority: standard` clauses MUST cite a
source of truth; `authority: recommendation` clauses (the `REC-*` rules) are
conventions with no GDS or NCSC anchor and cite external references by design.
"""

from __future__ import annotations

import pytest

from gds_api_schema_uplift.contracts import Authority
from gds_api_schema_uplift.standards import (
    default_standards_path,
    load_standards,
)

#: Every clause the v0.2 ruleset needs. Phases 5a/5b register the NCSC-* and REC-*
#: rules; their clauses are authored here ahead of that so the corpus is complete.
EXPECTED_CLAUSES = (
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

RECOMMENDATION_CLAUSES = ("REC-001", "REC-002")


@pytest.fixture(scope="module")
def corpus():
    return load_standards(default_standards_path())


# --- the corpus is complete ------------------------------------------------------------

def test_corpus_holds_exactly_the_v0_2_clauses(corpus):
    assert sorted(corpus.clause_ids) == sorted(EXPECTED_CLAUSES)


@pytest.mark.parametrize("clause_id", EXPECTED_CLAUSES)
def test_every_clause_resolves_with_substantive_text(corpus, clause_id):
    """A one-word `text` would pass the schema but be useless as a quote."""
    clause = corpus.resolve(clause_id)
    assert clause.text.strip()
    assert len(clause.text.split()) >= 10, f"{clause_id} text is too short to quote"
    assert clause.section.strip()


# --- standards cite a source of truth; recommendations need not ------------------------

@pytest.mark.parametrize("clause_id", EXPECTED_CLAUSES)
def test_authority_matches_the_clause_family(corpus, clause_id):
    clause = corpus.resolve(clause_id)
    expected = (
        Authority.RECOMMENDATION
        if clause_id in RECOMMENDATION_CLAUSES
        else Authority.STANDARD
    )
    assert clause.authority is expected


@pytest.mark.parametrize(
    "clause_id", [c for c in EXPECTED_CLAUSES if c not in RECOMMENDATION_CLAUSES]
)
def test_standard_clauses_cite_a_source_of_truth(corpus, clause_id):
    """This is the M2 assertion: a developer can trace the finding to gov.uk."""
    clause = corpus.resolve(clause_id)
    assert clause.is_source_of_truth, f"{clause_id} cites {clause.url}"


@pytest.mark.parametrize("clause_id", RECOMMENDATION_CLAUSES)
def test_recommendations_are_not_dressed_up_as_government_mandates(corpus, clause_id):
    """A REC-* clause citing gov.uk would imply GDS requires a convention it does not."""
    clause = corpus.resolve(clause_id)
    assert not clause.is_source_of_truth, f"{clause_id} cites {clause.url}"


@pytest.mark.parametrize("clause_id", RECOMMENDATION_CLAUSES)
def test_recommendation_text_says_it_is_not_a_requirement(corpus, clause_id):
    """The renderer labels these too, but the text must stand alone when quoted."""
    text = corpus.resolve(clause_id).text.lower()
    assert "not a gds or ncsc requirement" in text


@pytest.mark.parametrize("clause_id", EXPECTED_CLAUSES)
def test_every_url_is_https(corpus, clause_id):
    assert corpus.resolve(clause_id).url.startswith("https://")


# --- the registry agrees with the corpus ----------------------------------------------

def test_every_registered_rule_cites_a_clause_that_resolves(corpus):
    """The registry-walk half of the criterion.

    Scoped to the rules actually registered, so it stays true as Phases 5a and 5b add
    the NCSC-* and REC-* rules — it tightens automatically rather than needing an edit.
    """
    from gds_api_schema_uplift.rules import REGISTRY

    unresolved = [
        (rule_id, rule.clause_id)
        for rule_id, rule in REGISTRY.items()
        if rule.clause_id not in corpus
    ]
    assert unresolved == [], f"rules citing a missing clause: {unresolved}"


def test_registered_rule_severities_are_consistent_with_clause_authority(corpus):
    """A rule anchored to a mere recommendation must not be an `error`.

    Erroring on a convention would misrepresent it as a government requirement — the
    same failure `test_recommendations_are_not_dressed_up...` guards from the corpus
    side, checked here from the rule side.
    """
    from gds_api_schema_uplift.contracts import Severity
    from gds_api_schema_uplift.rules import REGISTRY

    for rule_id, rule in REGISTRY.items():
        clause = corpus.resolve(rule.clause_id)
        if clause.authority is Authority.RECOMMENDATION:
            assert rule.severity is not Severity.ERROR, rule_id


# --- the agent can actually quote from this corpus -------------------------------------

def test_corpus_is_large_enough_for_prompt_caching_to_engage(corpus):
    """The corpus is the cached prefix. Below the minimum, caching silently no-ops.

    This was the concrete cost consequence of Phase 2 being outstanding, so it is
    asserted now that the corpus exists.
    """
    from gds_api_schema_uplift.agent.prompts import (
        MIN_CACHEABLE_TOKENS,
        build_system_blocks,
        cache_warning,
        estimated_system_tokens,
    )

    blocks = build_system_blocks(corpus)
    assert estimated_system_tokens(blocks) >= MIN_CACHEABLE_TOKENS
    assert cache_warning(blocks) is None

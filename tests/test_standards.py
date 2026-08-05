"""standards.yaml schema is frozen in Phase 0; its content is authored in Phase 2.

These tests assert the *shape* contract and the failure modes. They deliberately do
not assert that any particular clause exists — that assertion belongs to Phase 2's
citation integrity test, and writing it now would either fail or invite placeholder
clause text.
"""

from __future__ import annotations

import pytest

from gds_api_schema_uplift.contracts import Authority
from gds_api_schema_uplift.standards import (
    StandardsError,
    default_standards_path,
    load_standards,
    parse_standards,
)

WELL_FORMED = {
    "clauses": {
        "GDS-001": {
            "section": "Security",
            "text": "Use HTTPS for all APIs.",
            "url": "https://www.gov.uk/guidance/gds-api-technical-and-data-standards",
        },
        "REC-001": {
            "section": "REST convention",
            "text": "Prefer plural nouns for collection resources.",
            "url": "https://github.com/microsoft/api-guidelines",
            "authority": "recommendation",
        },
    }
}


def test_parses_well_formed_corpus():
    standards = parse_standards(WELL_FORMED)
    assert len(standards) == 2
    assert standards.clause_ids == ("GDS-001", "REC-001")


def test_resolves_clause_fields():
    clause = parse_standards(WELL_FORMED).resolve("GDS-001")
    assert clause.section == "Security"
    assert clause.text == "Use HTTPS for all APIs."
    assert clause.authority is Authority.STANDARD


def test_authority_defaults_to_standard_and_is_honoured_when_set():
    standards = parse_standards(WELL_FORMED)
    assert standards.resolve("GDS-001").authority is Authority.STANDARD
    assert standards.resolve("REC-001").authority is Authority.RECOMMENDATION


def test_source_of_truth_detection():
    standards = parse_standards(WELL_FORMED)
    # A gov.uk citation is a source of truth; the MS guidelines are not.
    assert standards.resolve("GDS-001").is_source_of_truth is True
    assert standards.resolve("REC-001").is_source_of_truth is False


def test_unresolvable_clause_raises_rather_than_returning_none():
    standards = parse_standards(WELL_FORMED)
    with pytest.raises(StandardsError, match="does not resolve"):
        standards.resolve("GDS-999")


def test_empty_corpus_is_valid():
    """The shipped corpus is empty until Phase 2; that must not be a load error."""
    standards = parse_standards({"clauses": {}})
    assert len(standards) == 0


def test_shipped_corpus_loads():
    """The shipped corpus parses against the frozen schema.

    Its *contents* are asserted in `tests/test_citation_integrity.py`; this only
    proves the file on disk is well-formed, which is this module's remit.
    """
    standards = load_standards(default_standards_path())
    assert len(standards) > 0


@pytest.mark.parametrize(
    "payload, expected",
    [
        (None, "empty"),
        ([], "must be a mapping"),
        ({}, "missing the top-level 'clauses' key"),
        ({"clauses": []}, "must be a mapping of clause_id"),
        ({"clauses": {"GDS-001": "nope"}}, "must be a mapping"),
    ],
)
def test_malformed_corpus_shapes_are_rejected(payload, expected):
    with pytest.raises(StandardsError, match=expected):
        parse_standards(payload)


@pytest.mark.parametrize("missing", ["section", "text", "url"])
def test_required_fields_must_be_present_and_non_empty(missing):
    entry = {
        "section": "Security",
        "text": "Use HTTPS.",
        "url": "https://www.gov.uk/x",
    }
    del entry[missing]
    with pytest.raises(StandardsError, match=missing):
        parse_standards({"clauses": {"GDS-001": entry}})


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_text_is_rejected(blank):
    """Guards against a placeholder corpus passing Phase 2's integrity test."""
    with pytest.raises(StandardsError, match="text"):
        parse_standards(
            {"clauses": {"GDS-001": {"section": "S", "text": blank, "url": "https://x"}}}
        )


def test_unknown_keys_are_rejected():
    with pytest.raises(StandardsError, match="unknown keys"):
        parse_standards(
            {
                "clauses": {
                    "GDS-001": {
                        "section": "S",
                        "text": "t",
                        "url": "https://x",
                        "clause": "typo for section",
                    }
                }
            }
        )


def test_bad_authority_value_is_rejected():
    with pytest.raises(StandardsError, match="authority"):
        parse_standards(
            {
                "clauses": {
                    "GDS-001": {
                        "section": "S",
                        "text": "t",
                        "url": "https://x",
                        "authority": "mandatory",
                    }
                }
            }
        )

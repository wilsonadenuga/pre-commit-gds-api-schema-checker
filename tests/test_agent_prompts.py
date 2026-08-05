"""The cached system prompt.

Caching is a prefix match, so the properties that matter are structural: the corpus
is rendered deterministically, it lives in `system`, and exactly one breakpoint sits
at the end. A test that asserts prose wording would just be a change detector.
"""

from __future__ import annotations

from gds_api_schema_uplift.agent import prompts
from gds_api_schema_uplift.standards import parse_standards

CORPUS = {
    "clauses": {
        "NCSC-001": {
            "section": "NCSC section 2",
            "text": "Do not use HTTP Basic authentication.",
            "url": "https://www.ncsc.gov.uk/collection/securing-http-based-apis",
        },
        "GDS-001": {
            "section": "Security",
            "text": "APIs must use HTTPS.",
            "url": "https://www.gov.uk/guidance/gds-api-technical-and-data-standards",
        },
        "REC-001": {
            "section": "REST convention",
            "text": "Prefer plural nouns.",
            "url": "https://github.com/microsoft/api-guidelines",
            "authority": "recommendation",
        },
    }
}


def test_corpus_is_rendered_in_clause_id_order():
    """Unstable ordering would change the prefix bytes and defeat caching."""
    text = prompts.corpus_text(parse_standards(CORPUS))
    assert text.index("GDS-001") < text.index("NCSC-001") < text.index("REC-001")


def test_corpus_is_byte_stable_across_renders():
    standards = parse_standards(CORPUS)
    assert prompts.corpus_text(standards) == prompts.corpus_text(standards)


def test_corpus_carries_authority_and_source_for_each_clause():
    text = prompts.corpus_text(parse_standards(CORPUS))
    assert "authority: recommendation" in text
    assert "authority: standard" in text
    assert "https://www.ncsc.gov.uk/collection/securing-http-based-apis" in text


def test_empty_corpus_says_so_rather_than_rendering_nothing():
    """The model must be told there is no clause text, not left to infer it."""
    text = prompts.corpus_text(parse_standards({"clauses": {}}))
    assert "none loaded" in text
    assert "no clause text" in text


def test_exactly_one_cache_breakpoint_and_it_is_last():
    blocks = prompts.build_system_blocks(parse_standards(CORPUS))
    cached = [i for i, b in enumerate(blocks) if "cache_control" in b]
    assert cached == [len(blocks) - 1]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}


def test_the_corpus_is_the_cached_block():
    blocks = prompts.build_system_blocks(parse_standards(CORPUS))
    assert "APIs must use HTTPS." in blocks[-1]["text"]


def test_cache_warning_fires_when_the_prefix_is_too_small():
    """An empty corpus cannot reach the minimum cacheable prefix."""
    blocks = prompts.build_system_blocks(parse_standards({"clauses": {}}))
    warning = prompts.cache_warning(blocks)
    assert warning is not None
    assert str(prompts.MIN_CACHEABLE_TOKENS) in warning


def test_cache_warning_is_silent_once_the_prefix_is_large_enough():
    big = {
        "clauses": {
            f"GDS-{i:03d}": {
                "section": "s",
                "text": "word " * 400,
                "url": "https://www.gov.uk/x",
            }
            for i in range(4)
        }
    }
    blocks = prompts.build_system_blocks(parse_standards(big))
    assert prompts.estimated_system_tokens(blocks) >= prompts.MIN_CACHEABLE_TOKENS
    assert prompts.cache_warning(blocks) is None


def test_finding_message_carries_every_field_the_model_needs():
    message = prompts.finding_message(
        rule_id="GDS-001",
        severity="error",
        location="$.servers[0].url",
        snippet="http://api.example.gov.uk",
        rule_summary="HTTPS-only",
        clause_id="GDS-001",
        clause_text="APIs must use HTTPS.",
        clause_url="https://www.gov.uk/x",
        spec_excerpt="openapi: 3.1.0",
    )
    for fragment in (
        "GDS-001",
        "error",
        "$.servers[0].url",
        "http://api.example.gov.uk",
        "HTTPS-only",
        "APIs must use HTTPS.",
        "https://www.gov.uk/x",
        "openapi: 3.1.0",
    ):
        assert fragment in message, fragment


def test_finding_message_is_explicit_when_no_clause_text_exists():
    message = prompts.finding_message(
        rule_id="GDS-001",
        severity="error",
        location="$.x",
        snippet="y",
        rule_summary="s",
        clause_id="GDS-001",
        clause_text="",
        clause_url="",
        spec_excerpt="openapi: 3.1.0",
    )
    assert "(no clause text available)" in message

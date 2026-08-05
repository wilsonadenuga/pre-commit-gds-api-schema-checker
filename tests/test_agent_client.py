"""The agent loop and the validation gate around it.

Phase 3's exit criterion lives here: a valid patch is produced with a rationale and a
clause quote, and a patch that would break the spec is provably dropped before any
human sees it.

Every test injects a stub messages API — nothing here reaches the network.
"""

from __future__ import annotations

import pytest
from agent_stubs import (
    HTTPS_FIX_OPS,
    StubMessages,
    StubResponse,
    StubToolUse,
    StubUsage,
    propose_patch_response,
    prose_response,
    refusal_response,
    retrieve_clause_response,
)
from example_specs import BROKEN_SPEC

from gds_api_schema_uplift.agent.client import (
    MAX_TURNS_PER_FINDING,
    AgentConfig,
    AgentRun,
    BudgetExhausted,
    propose_for_finding,
    propose_for_findings,
)
from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules import run_deterministic_pass
from gds_api_schema_uplift.standards import parse_standards

CORPUS = {
    "clauses": {
        "GDS-001": {
            "section": "Security",
            "text": "APIs must use HTTPS. Plaintext HTTP must not be offered.",
            "url": "https://www.gov.uk/guidance/gds-api-technical-and-data-standards",
        }
    }
}


@pytest.fixture
def spec():
    return load_spec(BROKEN_SPEC)


@pytest.fixture
def standards():
    return parse_standards(CORPUS)


@pytest.fixture
def gds_001(spec):
    findings = [f for f in run_deterministic_pass(spec) if f.rule_id == "GDS-001"]
    assert len(findings) == 1, "fixture drift: expected exactly one GDS-001 finding"
    return findings[0]


def run_one(stub, spec, finding, standards, **config_kwargs):
    run = AgentRun(config=AgentConfig(**config_kwargs))
    suggestion = propose_for_finding(
        stub, spec=spec, finding=finding, standards=standards, run=run
    )
    return suggestion, run


# --- the happy path: Phase 3's exit criterion -----------------------------------------

def test_valid_patch_is_offered_with_rationale_and_citation(spec, gds_001, standards):
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is True
    assert suggestion.stage == "applied"
    assert suggestion.drop_reason is None
    assert suggestion.patch is not None
    assert suggestion.patch.rationale
    assert suggestion.has_citation
    assert suggestion.diff and "https://api.example.gov.uk" in suggestion.diff


def test_offering_a_patch_does_not_mutate_the_spec(spec, gds_001, standards):
    """The developer's in-memory file must be untouched until they approve."""
    before = spec.dumps()
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    run_one(stub, spec, gds_001, standards)
    assert spec.dumps() == before


# --- the gate: invalid patches are dropped, never offered ------------------------------

def test_patch_that_breaks_the_spec_is_dropped(spec, gds_001, standards):
    """Removing `info` applies cleanly but leaves an invalid OpenAPI document."""
    stub = StubMessages([propose_patch_response([{"op": "remove", "path": "/info"}])])
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False
    assert suggestion.stage == "schema_invalid"
    assert suggestion.drop_reason


def test_patch_targeting_a_missing_path_is_dropped(spec, gds_001, standards):
    stub = StubMessages(
        [propose_patch_response([{"op": "replace", "path": "/nope/0", "value": 1}])]
    )
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False
    assert suggestion.stage == "apply_failed"


def test_empty_ops_is_dropped_and_keeps_the_models_explanation(spec, gds_001, standards):
    """The model is told to return empty ops rather than guess. That is not a fix."""
    stub = StubMessages(
        [propose_patch_response([], rationale="The servers block is not visible to me.")]
    )
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False
    assert suggestion.stage == "empty_patch"
    assert "not visible" in suggestion.drop_reason


@pytest.mark.parametrize(
    "bad_input, label",
    [
        ({"ops": "not-a-list", "rationale": "x", "clause_quote": "y"}, "ops-not-list"),
        ({"rationale": "x", "clause_quote": "y"}, "ops-missing"),
        ({"ops": [{"op": "frobnicate", "path": "/a"}]}, "unknown-op"),
        ({"ops": [{"op": "replace", "path": "no-slash", "value": 1}]}, "bad-pointer"),
        ({"ops": [{"op": "replace", "path": "/a"}]}, "replace-without-value"),
        ({"ops": [{"op": "move", "path": "/a"}]}, "move-without-from"),
        ("just a string", "not-an-object"),
    ],
)
def test_malformed_tool_input_is_dropped_not_guessed_at(
    spec, gds_001, standards, bad_input, label
):
    stub = StubMessages(
        [StubResponse(content=[StubToolUse(name="propose_patch", input=bad_input)])]
    )
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False, label
    assert suggestion.stage == "malformed_tool_input", label
    assert suggestion.drop_reason, label


def test_dropped_suggestion_never_carries_a_diff(spec, gds_001, standards):
    """A diff is the renderable artefact; a dropped proposal must not have one."""
    stub = StubMessages([propose_patch_response([{"op": "remove", "path": "/info"}])])
    suggestion, _ = run_one(stub, spec, gds_001, standards)
    assert suggestion.diff is None


# --- non-proposal responses -----------------------------------------------------------

def test_prose_reply_is_dropped(spec, gds_001, standards):
    stub = StubMessages([prose_response("Just use HTTPS, obviously.")])
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False
    assert "prose" in suggestion.drop_reason
    assert "obviously" in suggestion.drop_reason


def test_refusal_is_dropped_without_reading_content(spec, gds_001, standards):
    stub = StubMessages([refusal_response()])
    suggestion, _ = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is False
    assert suggestion.stage == "refusal"


def test_clause_lookup_detour_then_proposal(spec, gds_001, standards):
    """A retrieve_clause call is answered and the loop continues."""
    stub = StubMessages(
        [retrieve_clause_response("GDS-001"), propose_patch_response(HTTPS_FIX_OPS)]
    )
    suggestion, run = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is True
    assert stub.call_count == 2
    assert run.calls_made == 2
    # The tool result must be a user turn carrying the clause text.
    second_messages = stub.requests[1]["messages"]
    tool_result = second_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_lookup"
    assert "HTTPS" in tool_result["content"]


def test_turn_limit_stops_an_agent_that_only_ever_looks_things_up(
    spec, gds_001, standards
):
    stub = StubMessages([retrieve_clause_response("GDS-001")] * MAX_TURNS_PER_FINDING)
    suggestion, run = run_one(
        stub, spec, gds_001, standards, max_llm_calls=MAX_TURNS_PER_FINDING
    )

    assert suggestion.offered is False
    assert suggestion.stage == "turn_limit"
    assert run.calls_made == MAX_TURNS_PER_FINDING


# --- request shape: caching and determinism -------------------------------------------

def test_the_finding_is_never_placed_in_the_cached_prefix(spec, gds_001, standards):
    """Per-finding content in `system` would invalidate the cache on every call."""
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    run_one(stub, spec, gds_001, standards)

    system_text = " ".join(block["text"] for block in stub.requests[0]["system"])
    assert gds_001.location not in system_text
    assert gds_001.snippet not in system_text
    user_text = stub.requests[0]["messages"][0]["content"]
    assert gds_001.location in user_text


def test_cache_control_sits_on_the_last_system_block(spec, gds_001, standards):
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    run_one(stub, spec, gds_001, standards)

    system = stub.requests[0]["system"]
    assert "cache_control" not in system[0]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}


def test_request_pins_the_model_and_effort(spec, gds_001, standards):
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    run_one(stub, spec, gds_001, standards, model="claude-haiku-4-5", effort="medium")

    request = stub.requests[0]
    assert request["model"] == "claude-haiku-4-5"
    assert request["output_config"] == {"effort": "medium"}
    assert request["thinking"] == {"type": "adaptive"}


def test_thinking_can_be_turned_off(spec, gds_001, standards):
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    run_one(stub, spec, gds_001, standards, thinking=False)
    assert "thinking" not in stub.requests[0]


def test_tool_order_is_stable_across_calls(spec, gds_001, standards):
    """Reordering `tools` would invalidate the whole cached prefix."""
    stub = StubMessages(
        [retrieve_clause_response("GDS-001"), propose_patch_response(HTTPS_FIX_OPS)]
    )
    run_one(stub, spec, gds_001, standards)

    first = [t["name"] for t in stub.requests[0]["tools"]]
    second = [t["name"] for t in stub.requests[1]["tools"]]
    assert first == second == ["retrieve_clause", "propose_patch"]


# --- cost accounting ------------------------------------------------------------------

def test_usage_is_recorded_for_every_call(spec, gds_001, standards):
    stub = StubMessages(
        [
            retrieve_clause_response("GDS-001"),
            propose_patch_response(
                HTTPS_FIX_OPS,
                usage=StubUsage(input_tokens=500, output_tokens=100,
                                cache_read_input_tokens=2000),
            ),
        ]
    )
    _, run = run_one(stub, spec, gds_001, standards)

    assert len(run.cost.calls) == 2
    assert run.cost.total_usd > 0
    assert run.cost.total_cache_read_tokens == 2000


def test_a_response_without_usage_does_not_crash_accounting(spec, gds_001, standards):
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS)])
    stub._responses[0].usage = None  # type: ignore[assignment]
    suggestion, run = run_one(stub, spec, gds_001, standards)

    assert suggestion.offered is True
    assert run.cost.calls == ()


# --- the call budget (PRD s11 cost mitigation) ----------------------------------------

def test_budget_is_enforced_per_run(spec, gds_001, standards):
    run = AgentRun(config=AgentConfig(max_llm_calls=1))
    stub = StubMessages([retrieve_clause_response("GDS-001")])

    with pytest.raises(BudgetExhausted):
        propose_for_finding(
            stub, spec=spec, finding=gds_001, standards=standards, run=run
        )
    assert run.calls_made == 1
    assert run.calls_remaining == 0


def test_zero_budget_makes_no_calls_at_all(spec, gds_001, standards):
    run = AgentRun(config=AgentConfig(max_llm_calls=0))
    stub = StubMessages([])

    with pytest.raises(BudgetExhausted):
        propose_for_finding(
            stub, spec=spec, finding=gds_001, standards=standards, run=run
        )
    assert stub.call_count == 0


def test_multi_finding_run_stops_cleanly_at_the_budget(spec, standards):
    """A truncated run must still report what it produced, not raise."""
    findings = run_deterministic_pass(spec)
    assert len(findings) >= 3
    run = AgentRun(config=AgentConfig(max_llm_calls=2))
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS) for _ in findings])

    suggestions = propose_for_findings(
        stub, spec=spec, findings=findings, standards=standards, run=run
    )

    assert len(suggestions) == 2
    assert stub.call_count == 2
    assert run.calls_remaining == 0


def test_dropped_patches_are_counted_across_a_run(spec, standards):
    findings = run_deterministic_pass(spec)[:3]
    run = AgentRun(config=AgentConfig(max_llm_calls=10))
    stub = StubMessages(
        [
            propose_patch_response(HTTPS_FIX_OPS),
            propose_patch_response([{"op": "remove", "path": "/info"}]),
            propose_patch_response([]),
        ]
    )

    suggestions = propose_for_findings(
        stub, spec=spec, findings=findings, standards=standards, run=run
    )

    assert [s.offered for s in suggestions] == [True, False, False]
    assert run.patches_dropped == 2


# --- degraded corpus ------------------------------------------------------------------

def test_run_works_with_an_empty_corpus_but_cannot_cite(spec, gds_001):
    """Phase 2 authors the corpus. Until then a run still works, uncited."""
    empty = parse_standards({"clauses": {}})
    stub = StubMessages([propose_patch_response(HTTPS_FIX_OPS, clause_quote="")])
    suggestion, _ = run_one(stub, spec, gds_001, empty)

    assert suggestion.offered is True
    assert suggestion.has_citation is False

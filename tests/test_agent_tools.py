"""Tool schemas and their input validation.

The schema is advisory: strict tool use is not available on every model this CLI can
be pointed at, so `parse_propose_patch` is the enforcement boundary. These tests
treat it as such — every malformed shape must raise rather than be coerced into a
patch assembled from guesses.
"""

from __future__ import annotations

import pytest

from gds_api_schema_uplift.agent.tools import (
    ALLOWED_OPS,
    PROPOSE_PATCH,
    RETRIEVE_CLAUSE,
    ToolInputError,
    handle_retrieve_clause,
    parse_propose_patch,
    tool_definitions,
)
from gds_api_schema_uplift.standards import parse_standards

STANDARDS = parse_standards(
    {
        "clauses": {
            "GDS-001": {
                "section": "Security",
                "text": "APIs must use HTTPS.",
                "url": "https://www.gov.uk/x",
            }
        }
    }
)


# --- schemas --------------------------------------------------------------------------

def test_both_tools_are_defined_in_a_fixed_order():
    names = [t["name"] for t in tool_definitions()]
    assert names == [RETRIEVE_CLAUSE, PROPOSE_PATCH]


def test_every_schema_closes_additional_properties():
    """Open schemas let a typo'd field through silently."""
    for tool in tool_definitions():
        assert tool["input_schema"]["additionalProperties"] is False


def test_propose_patch_requires_rationale_and_citation():
    schema = tool_definitions()[1]["input_schema"]
    assert set(schema["required"]) == {"ops", "rationale", "clause_quote"}


def test_the_test_op_is_not_offered():
    """`test` asserts rather than edits, so it cannot be part of a fix."""
    assert "test" not in ALLOWED_OPS
    op_schema = tool_definitions()[1]["input_schema"]["properties"]["ops"]["items"]
    assert "test" not in op_schema["properties"]["op"]["enum"]


def test_every_parameter_has_a_description():
    for tool in tool_definitions():
        assert tool["description"]
        for name, prop in tool["input_schema"]["properties"].items():
            assert "description" in prop, f"{tool['name']}.{name}"


# --- retrieve_clause ------------------------------------------------------------------

def test_retrieve_clause_returns_the_clause_text():
    result = handle_retrieve_clause(STANDARDS, {"clause_id": "GDS-001"})
    assert "APIs must use HTTPS." in result
    assert "https://www.gov.uk/x" in result
    assert "authority: standard" in result


def test_retrieve_clause_tolerates_surrounding_whitespace():
    assert "HTTPS" in handle_retrieve_clause(STANDARDS, {"clause_id": " GDS-001 "})


@pytest.mark.parametrize(
    "bad_input",
    [{"clause_id": "GDS-999"}, {"clause_id": ""}, {"clause_id": 7}, {}, "nope", None],
)
def test_retrieve_clause_never_raises(bad_input):
    """A tool error mid-loop is less useful to the model than a plain message."""
    result = handle_retrieve_clause(STANDARDS, bad_input)
    assert isinstance(result, str) and result


# --- parse_propose_patch: accepted shapes ---------------------------------------------

def test_parses_a_replace_op():
    patch = parse_propose_patch(
        {
            "ops": [{"op": "replace", "path": "/servers/0/url", "value": "https://x"}],
            "rationale": "  because  ",
            "clause_quote": "  quote  ",
        }
    )
    assert len(patch.ops) == 1
    assert patch.ops[0].op == "replace"
    assert patch.rationale == "because"
    assert patch.clause_quote == "quote"


def test_parses_a_remove_op_without_a_value():
    patch = parse_propose_patch(
        {"ops": [{"op": "remove", "path": "/a"}], "rationale": "r", "clause_quote": "q"}
    )
    assert patch.to_rfc6902() == [{"op": "remove", "path": "/a"}]


def test_parses_a_move_op_with_from():
    patch = parse_propose_patch(
        {
            "ops": [{"op": "move", "path": "/b", "from": "/a"}],
            "rationale": "r",
            "clause_quote": "q",
        }
    )
    assert patch.ops[0].from_ == "/a"
    assert patch.to_rfc6902()[0]["from"] == "/a"


def test_parses_an_escaped_pointer():
    """OpenAPI path keys contain slashes, so `~1` escaping must survive."""
    patch = parse_propose_patch(
        {
            "ops": [{"op": "add", "path": "/paths/~1v1~1users/get", "value": {}}],
            "rationale": "r",
            "clause_quote": "q",
        }
    )
    assert patch.ops[0].path == "/paths/~1v1~1users/get"


def test_empty_ops_is_accepted_as_a_deliberate_no_patch():
    """The gate rejects it later; parsing must not conflate it with malformed input."""
    patch = parse_propose_patch(
        {"ops": [], "rationale": "cannot see the block", "clause_quote": ""}
    )
    assert patch.ops == ()
    assert patch.rationale == "cannot see the block"


def test_a_null_value_is_preserved():
    """`replace` with an explicit null is legal RFC 6902 and must not be dropped."""
    patch = parse_propose_patch(
        {
            "ops": [{"op": "replace", "path": "/a", "value": None}],
            "rationale": "r",
            "clause_quote": "q",
        }
    )
    assert patch.to_rfc6902() == [{"op": "replace", "path": "/a", "value": None}]


# --- parse_propose_patch: rejected shapes ---------------------------------------------

@pytest.mark.parametrize(
    "payload, expected",
    [
        ("string", "expected an object"),
        ({"rationale": "r"}, "missing 'ops'"),
        ({"ops": {}}, "must be an array"),
        ({"ops": ["nope"]}, "must be an object"),
        ({"ops": [{"op": "frobnicate", "path": "/a"}]}, "must be one of"),
        ({"ops": [{"op": "test", "path": "/a", "value": 1}]}, "must be one of"),
        ({"ops": [{"op": "replace", "path": "a", "value": 1}]}, "JSON Pointer"),
        ({"ops": [{"op": "replace", "path": "/a"}]}, "needs a 'value'"),
        ({"ops": [{"op": "add", "path": "/a"}]}, "needs a 'value'"),
        ({"ops": [{"op": "move", "path": "/a"}]}, "needs a 'from'"),
        ({"ops": [{"op": "copy", "path": "/a", "from": 5}]}, "needs a 'from'"),
        ({"ops": [{"op": "remove", "path": "/a", "junk": 1}]}, "unknown keys"),
        ({"ops": [], "rationale": 5}, "'rationale' must be a string"),
        ({"ops": [], "rationale": "r", "clause_quote": 5}, "must be a string"),
    ],
)
def test_malformed_input_raises(payload, expected):
    with pytest.raises(ToolInputError, match=expected):
        parse_propose_patch(payload)


def test_the_failing_op_index_is_named():
    """A reason a developer can act on beats a generic 'invalid patch'."""
    with pytest.raises(ToolInputError, match=r"ops\[1\]"):
        parse_propose_patch(
            {
                "ops": [
                    {"op": "remove", "path": "/a"},
                    {"op": "nonsense", "path": "/b"},
                ],
                "rationale": "r",
                "clause_quote": "q",
            }
        )

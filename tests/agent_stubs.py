"""A stub Anthropic messages API, so agent tests run offline and deterministically.

Not a test module — pytest does not collect it. The shapes mirror only what
`agent.client` reads off a response: `content` blocks with `type`/`name`/`input`/`id`,
plus `stop_reason`, `model`, and `usage`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class StubUsage:
    input_tokens: int = 1000
    output_tokens: int = 200
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class StubTextBlock:
    text: str
    type: str = "text"


@dataclass
class StubToolUse:
    name: str
    input: Any
    id: str = "toolu_stub"
    type: str = "tool_use"


@dataclass
class StubResponse:
    content: list[Any] = field(default_factory=list)
    stop_reason: str = "tool_use"
    model: str = DEFAULT_MODEL
    usage: StubUsage = field(default_factory=StubUsage)


class StubMessages:
    """Replays a scripted list of responses and records the requests it received."""

    def __init__(self, responses: list[StubResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> StubResponse:
        self.requests.append(kwargs)
        if not self._responses:
            raise AssertionError("stub ran out of scripted responses")
        return self._responses.pop(0)

    @property
    def call_count(self) -> int:
        return len(self.requests)


def propose_patch_response(
    ops: list[dict[str, Any]],
    rationale: str = "Because the clause requires it.",
    clause_quote: str = "APIs must use HTTPS.",
    **response_kwargs: Any,
) -> StubResponse:
    """A response whose single tool call is a well-formed `propose_patch`."""
    return StubResponse(
        content=[
            StubToolUse(
                name="propose_patch",
                input={
                    "ops": ops,
                    "rationale": rationale,
                    "clause_quote": clause_quote,
                },
            )
        ],
        **response_kwargs,
    )


def retrieve_clause_response(clause_id: str, tool_id: str = "toolu_lookup") -> StubResponse:
    """A response that detours through the clause-lookup tool."""
    return StubResponse(
        content=[
            StubToolUse(
                name="retrieve_clause", input={"clause_id": clause_id}, id=tool_id
            )
        ]
    )


def prose_response(text: str = "I think you should use HTTPS.") -> StubResponse:
    """A response with no tool call at all — the model answered in prose."""
    return StubResponse(content=[StubTextBlock(text=text)], stop_reason="end_turn")


def refusal_response() -> StubResponse:
    return StubResponse(content=[], stop_reason="refusal")


#: The op that fixes GDS-001 on `examples/broken.yaml`.
HTTPS_FIX_OPS = [
    {"op": "replace", "path": "/servers/0/url", "value": "https://api.example.gov.uk"}
]

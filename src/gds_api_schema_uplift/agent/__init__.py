"""The Claude agent layer.

`client` owns the tool-use loop and the validation gate; `tools` owns the tool
schemas and their input validation; `prompts` owns the cached system prompt.

Importing this package does not import the Anthropic SDK — `client.build_messages_api`
does that lazily, so the deterministic rule pass runs with no credentials present.
"""

from __future__ import annotations

from .client import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    AgentConfig,
    AgentRun,
    BudgetExhausted,
    build_messages_api,
    propose_for_finding,
    propose_for_findings,
)
from .tools import ToolInputError, parse_propose_patch, tool_definitions

__all__ = [
    "DEFAULT_EFFORT",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "AgentConfig",
    "AgentRun",
    "BudgetExhausted",
    "ToolInputError",
    "build_messages_api",
    "parse_propose_patch",
    "propose_for_finding",
    "propose_for_findings",
    "tool_definitions",
]

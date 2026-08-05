"""Tool definitions and their handlers.

Two tools, per PRD s9.4. The split between them resolves an open question the PRD
left ambiguous (PLAN open item 3): s9.4 exposes `retrieve_clause` to the model, while
s9.5 has every rule pre-declare its clause id — so the agent is handed the clause it
needs before it could ask for one.

Resolution implemented here: the anchoring clause is passed directly in the user
message for every rule, and `retrieve_clause` remains available as a *deterministic
lookup* for the `REC-*` recommendation rules, which have no single pre-declared
anchor and may legitimately want to read a neighbouring clause. It is a dict read,
never a search — there is no retrieval step anywhere in this tool.

`propose_patch` inputs are validated here rather than trusted. Strict tool use
(`strict: true`) is not available across every model this CLI can be pointed at, so
the schema is advisory and this module is the enforcement.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Patch, PatchOp
from ..standards import Standards, StandardsError

RETRIEVE_CLAUSE = "retrieve_clause"
PROPOSE_PATCH = "propose_patch"

#: RFC 6902 operations. `test` is omitted deliberately: it asserts rather than edits,
#: so a patch containing one cannot be a fix and would only complicate the gate.
ALLOWED_OPS = ("add", "remove", "replace", "move", "copy")


class ToolInputError(ValueError):
    """Raised when a tool call's input cannot be trusted."""


def tool_definitions() -> list[dict[str, Any]]:
    """The tool list, in a fixed order.

    Order matters for prompt caching: `tools` render before `system`, so reordering
    them between calls invalidates the entire cached prefix.
    """
    return [
        {
            "name": RETRIEVE_CLAUSE,
            "description": (
                "Look up the full text of a standards clause by its exact clause id "
                "(for example 'GDS-001' or 'NCSC-002'). This is a direct lookup in a "
                "fixed table, not a search: the id must match exactly. The clause "
                "anchoring your current finding has already been provided in the "
                "message, so use this only when you need to read a *different* "
                "clause."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "clause_id": {
                        "type": "string",
                        "description": "Exact clause id, e.g. 'GDS-003'.",
                    }
                },
                "required": ["clause_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": PROPOSE_PATCH,
            "description": (
                "Propose the smallest RFC 6902 JSON Patch that resolves the current "
                "finding, with a rationale and a verbatim quote from the anchoring "
                "clause. Call this exactly once. Pass an empty ops array if no valid "
                "patch can be constructed, and say why in the rationale."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ops": {
                        "type": "array",
                        "description": (
                            "RFC 6902 operations, applied in order. Empty means no "
                            "patch could be constructed."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": list(ALLOWED_OPS),
                                },
                                "path": {
                                    "type": "string",
                                    "description": (
                                        "JSON Pointer to the target. Escape '/' as "
                                        "'~1' and '~' as '~0'."
                                    ),
                                },
                                "value": {
                                    "description": (
                                        "The new value. Omit for 'remove', 'move' "
                                        "and 'copy'."
                                    ),
                                },
                                "from": {
                                    "type": "string",
                                    "description": (
                                        "Source JSON Pointer, for 'move' and 'copy'."
                                    ),
                                },
                            },
                            "required": ["op", "path"],
                            "additionalProperties": False,
                        },
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Why this edit satisfies the clause. Two sentences at "
                            "most; read in a terminal."
                        ),
                    },
                    "clause_quote": {
                        "type": "string",
                        "description": (
                            "A verbatim span from the clause text supplied to you. "
                            "Empty only if no clause text was supplied."
                        ),
                    },
                },
                "required": ["ops", "rationale", "clause_quote"],
                "additionalProperties": False,
            },
        },
    ]


def handle_retrieve_clause(standards: Standards, tool_input: Any) -> str:
    """Execute a `retrieve_clause` call. Returns text for the tool result.

    Never raises: an unresolvable id comes back as a message the model can act on,
    because a tool error mid-loop is less useful to it than a plain "no such clause".
    """
    if not isinstance(tool_input, dict):
        return "Error: expected an object with a 'clause_id' field."
    clause_id = tool_input.get("clause_id")
    if not isinstance(clause_id, str) or not clause_id.strip():
        return "Error: 'clause_id' must be a non-empty string."
    try:
        clause = standards.resolve(clause_id.strip())
    except StandardsError as exc:
        return f"No such clause. {exc}"
    return (
        f"{clause.clause_id} — {clause.section}\n"
        f"authority: {clause.authority.value}\n"
        f"source: {clause.url}\n\n"
        f"{clause.text}"
    )


def _parse_op(raw: Any, index: int) -> PatchOp:
    if not isinstance(raw, dict):
        raise ToolInputError(f"ops[{index}] must be an object, got {type(raw).__name__}")

    op = raw.get("op")
    if op not in ALLOWED_OPS:
        raise ToolInputError(
            f"ops[{index}].op must be one of {list(ALLOWED_OPS)}, got {op!r}"
        )

    path = raw.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ToolInputError(
            f"ops[{index}].path must be a JSON Pointer starting with '/', got {path!r}"
        )

    from_ = raw.get("from")
    if op in ("move", "copy"):
        if not isinstance(from_, str) or not from_.startswith("/"):
            raise ToolInputError(
                f"ops[{index}] is a {op!r} and needs a 'from' JSON Pointer, "
                f"got {from_!r}"
            )
    elif from_ is not None and not isinstance(from_, str):
        raise ToolInputError(f"ops[{index}].from must be a string when present")

    if op in ("add", "replace") and "value" not in raw:
        raise ToolInputError(f"ops[{index}] is a {op!r} and needs a 'value'")

    unknown = set(raw) - {"op", "path", "value", "from"}
    if unknown:
        raise ToolInputError(
            f"ops[{index}] has unknown keys: {', '.join(sorted(unknown))}"
        )

    return PatchOp(op=op, path=path, value=raw.get("value"), from_=from_)


def parse_propose_patch(tool_input: Any) -> Patch:
    """Turn a `propose_patch` tool input into a Patch, or raise ToolInputError.

    Raising rather than coercing is deliberate: a malformed tool call is a dropped
    suggestion with a stated reason, not a patch assembled from guesses.
    """
    if not isinstance(tool_input, dict):
        raise ToolInputError(
            f"expected an object, got {type(tool_input).__name__}"
        )

    raw_ops = tool_input.get("ops")
    if raw_ops is None:
        raise ToolInputError("missing 'ops'")
    if not isinstance(raw_ops, list):
        raise ToolInputError(f"'ops' must be an array, got {type(raw_ops).__name__}")

    ops = tuple(_parse_op(raw, index) for index, raw in enumerate(raw_ops))

    rationale = tool_input.get("rationale", "")
    if not isinstance(rationale, str):
        raise ToolInputError("'rationale' must be a string")

    clause_quote = tool_input.get("clause_quote", "")
    if not isinstance(clause_quote, str):
        raise ToolInputError("'clause_quote' must be a string")

    return Patch(
        ops=ops,
        rationale=rationale.strip(),
        clause_quote=clause_quote.strip(),
    )

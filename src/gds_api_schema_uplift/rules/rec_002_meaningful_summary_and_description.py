"""REC-002 — operations declare a meaningful `summary` and `description`.

The OpenAPI 3.1 Operation Object defines both fields as optional:

    summary       — "A short summary of what the operation does."
    description   — "A verbose explanation of the operation behavior."

Populating them is what makes generated documentation and generated agent tool
definitions usable. REC-002 is a recommendation, not a GDS or NCSC requirement,
so its findings render as `suggestion` and the clause is declared with
`authority: recommendation` in `standards.yaml`.

Detection here is deliberately deterministic. The "LLM path" for REC-* rules is
the *fix proposal* — a Phase 3 agent turnaround that writes better prose — not
the detection: `run_deterministic_pass` is the only wired-up pass in v0.2, and
the framework asserts `llm_rules() == ()`. So this checker fires only on
mechanically-detectable placeholder patterns; whether a *plausible-looking*
string is genuinely meaningful is a question for the agent, not for a linter.

Scope decisions, each pinned by a test:

*   **Per-operation, not inherited.** OpenAPI allows a `summary`/`description`
    at the Path Item level as a shorthand that its operations may inherit.
    REC-002 does NOT treat path-item-level fields as satisfying the requirement
    — the recommendation is about *operation-level* documentation, because
    that is what generated tool definitions and per-endpoint docs render from.
    A path with a shared summary but individual operations that omit their own
    is still flagged, once per offending operation.

*   **One finding per offending operation.** A single operation missing both
    `summary` and `description` is one violation of the recommendation, not
    two: a Phase 3 fix rewrites the operation node as a whole. The snippet
    concatenates the triggers that fired (`"summary missing; description
    empty"`) so the reader can see what needs attention.

*   **Non-string values are ignored.** If `summary` or `description` is an int,
    list, or mapping, the document is malformed and belongs to
    `openapi-spec-validator`. Flagging it here would double-report a schema
    error as a standards finding.

*   **`operationId` is not judged.** Whether `operationId` itself is
    meaningful is a different concern with a different clause. The only
    interaction here is a redundancy check: a `description` that is nothing
    more than the operationId (case- and whitespace-normalised) is treated as
    a placeholder.

*   **Response/parameter/requestBody `description` fields are out of scope.**
    Only the operation object's top-level `summary` and `description` are
    read; nested description fields have their own concerns and are not
    subject to REC-002.

Short-cutoff heuristics
-----------------------

The cutoffs below are conservative — the aim is to flag obvious placeholders
without producing false positives on short-but-legitimate prose:

*   `summary` < 10 chars is treated as a placeholder. Ten characters is
    roughly two short words ("List users" is exactly ten) — anything shorter
    is almost certainly a stub. This applies to `summary` only.
*   `description` < 15 chars is treated as a placeholder. Descriptions are
    supposed to *elaborate* on the summary; fifteen characters is not enough
    room to do so. The cutoff is looser than for summary because a description
    is expected to carry more content, not because it forgives more.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_operations, snippet

#: Minimum acceptable length for a `summary` string. See the module docstring
#: for the rationale; the number is deliberately conservative.
_SUMMARY_MIN_LENGTH = 10

#: Minimum acceptable length for a `description` string. Looser than the
#: summary cutoff because a description is supposed to elaborate.
_DESCRIPTION_MIN_LENGTH = 15


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace, for redundancy comparisons."""
    return " ".join(text.split()).lower()


def _reasons(operation: dict[str, Any], path: str) -> list[str]:
    """Return the human-readable reasons this operation fails REC-002.

    An empty list means the operation is compliant. Non-string `summary` or
    `description` values are ignored (see the module docstring) so a
    malformed spec produces no findings from this rule.
    """
    reasons: list[str] = []

    summary = operation.get("summary")
    if "summary" not in operation:
        reasons.append("summary missing")
        summary_norm = None
    elif not isinstance(summary, str):
        # Non-string: malformed, defer to schema validation. Treat as if we
        # never saw the field for the redundancy check below.
        summary_norm = None
    else:
        stripped = summary.strip()
        if not stripped:
            reasons.append("summary empty")
            summary_norm = None
        elif len(stripped) < _SUMMARY_MIN_LENGTH:
            reasons.append(
                f"summary too short (< {_SUMMARY_MIN_LENGTH} chars)"
            )
            summary_norm = _normalise(stripped)
        else:
            summary_norm = _normalise(stripped)

    description = operation.get("description")
    if "description" not in operation:
        reasons.append("description missing")
        return reasons
    if not isinstance(description, str):
        # Non-string: malformed, defer to schema validation.
        return reasons

    stripped = description.strip()
    if not stripped:
        reasons.append("description empty")
        return reasons
    if len(stripped) < _DESCRIPTION_MIN_LENGTH:
        reasons.append(
            f"description too short (< {_DESCRIPTION_MIN_LENGTH} chars)"
        )

    description_norm = _normalise(stripped)

    if summary_norm is not None and description_norm == summary_norm:
        reasons.append("description duplicates summary")
        return reasons

    operation_id = operation.get("operationId")
    if isinstance(operation_id, str):
        if description_norm == _normalise(operation_id):
            reasons.append("description duplicates operationId")
            return reasons

    if description_norm == _normalise(path):
        reasons.append("description duplicates path")

    return reasons


@register(
    "REC-002",
    severity=Severity.SUGGESTION,
    clause_id="REC-002",
    summary="Operations declare a meaningful summary and description (recommendation)",
    rule_type=RuleType.DETERMINISTIC,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each operation whose `summary`/`description` looks like a placeholder."""
    findings: list[Finding] = []

    for op in iter_operations(spec.data):
        reasons = _reasons(op.operation, op.path)
        if not reasons:
            continue
        findings.append(
            Finding(
                rule_id="REC-002",
                severity=Severity.SUGGESTION,
                # The operation object itself: a Phase 3 fix inserts or
                # rewrites `summary`/`description` under this node.
                location=op.location,
                snippet=snippet("; ".join(reasons)),
                clause_id="REC-002",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

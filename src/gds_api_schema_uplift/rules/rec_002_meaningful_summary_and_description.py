"""REC-002 — every operation must have a meaningful `description`.

Our own standard, not a GDS or NCSC requirement. AI agents that discover an API
read each operation's description to decide what it does, so it has to be there.
The `summary` is optional.

An operation is flagged when its description is:

- missing or empty
- too short (under 15 characters)
- just a copy of the summary, the operationId or the path

Whether the text actually makes sense is checked separately by the AI review.

- Only the operation's own description counts, not one on the path.
- Non-text values are left to the schema validator.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_operations, snippet

#: Shortest allowed description.
_DESCRIPTION_MIN_LENGTH = 15


def _normalise(text: str) -> str:
    """Lowercase and tidy spaces, so copies can be spotted."""
    return " ".join(text.split()).lower()


def _reasons(operation: dict[str, Any], path: str) -> list[str]:
    """The list of problems with this operation. Empty means it's fine."""
    reasons: list[str] = []

    # The summary is optional; it's only used to spot a description that copies it.
    summary = operation.get("summary")
    summary_norm = None
    if isinstance(summary, str) and summary.strip():
        summary_norm = _normalise(summary)

    description = operation.get("description")
    if "description" not in operation:
        reasons.append("description missing")
        return reasons
    if not isinstance(description, str):
        # Not text: leave it to the schema validator.
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


GOOD_EXAMPLE = """\
paths:
  /v1/users:
    get:
      summary: List users
      description: |
        Returns a paginated list of users visible to the caller.
        Filterable by department and status.
"""


@register(
    "REC-002",
    severity=Severity.SUGGESTION,
    clause_id="REC-002",
    summary="Every operation has a meaningful description (our standard)",
    good_example=GOOD_EXAMPLE,
    rule_type=RuleType.DETERMINISTIC,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each operation whose description is missing or a placeholder."""
    findings: list[Finding] = []

    for op in iter_operations(spec.data):
        reasons = _reasons(op.operation, op.path)
        if not reasons:
            continue
        findings.append(
            Finding(
                rule_id="REC-002",
                severity=Severity.SUGGESTION,
                location=op.location,
                snippet=snippet("; ".join(reasons)),
                clause_id="REC-002",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

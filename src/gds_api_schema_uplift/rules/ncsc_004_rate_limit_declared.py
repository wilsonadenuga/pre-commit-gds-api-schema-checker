"""NCSC-004 — every endpoint should document a `429 Too Many Requests` response.

NCSC says APIs need rate limiting to protect against overload (DoS attacks). An
OpenAPI file can't prove the server actually limits requests, so we check for a
documented `429` response as a sign it was thought about. That's why it's only a
suggestion.

- `429` and the `4XX` range both count. `default` doesn't.
- A `429` that is a `$ref` counts.
- Operations with no `responses` are left to the schema validator.
- One finding per operation, listing the codes it does document.
"""

from __future__ import annotations

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, child, iter_operations, snippet

#: Status codes that count as documenting rate limiting.
_ACKNOWLEDGES_429 = frozenset({"429", "4XX"})


def _acknowledges_rate_limit(responses: dict) -> bool:
    """True if the responses include `429` or `4XX`. Works for `429` and `'429'`."""
    for key in responses:
        normalised = str(key).strip().upper()
        if normalised in _ACKNOWLEDGES_429:
            return True
    return False


GOOD_EXAMPLE = """\
responses:
  '200': {...}
  '429':
    description: Too Many Requests
    content:
      application/problem+json:
        schema:
          $ref: '#/components/schemas/Problem'
"""


@register(
    "NCSC-004",
    severity=Severity.SUGGESTION,
    clause_id="NCSC-004",
    summary="Rate limiting acknowledged: 429 response defined on every operation",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each operation that doesn't document a `429`."""
    findings: list[Finding] = []

    for op in iter_operations(spec.data):
        # Missing `responses` is a schema error, reported elsewhere.
        raw = op.operation.get("responses")
        if not isinstance(raw, dict):
            continue

        responses = as_mapping(raw)
        if _acknowledges_rate_limit(responses):
            continue

        declared = ", ".join(str(key) for key in responses)
        message = (
            f"no 429 response defined; declared: {declared}"
            if declared
            else "no 429 response defined (no responses declared at all)"
        )
        findings.append(
            Finding(
                rule_id="NCSC-004",
                severity=Severity.SUGGESTION,
                location=child(op.location, "responses"),
                snippet=snippet(message),
                clause_id="NCSC-004",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

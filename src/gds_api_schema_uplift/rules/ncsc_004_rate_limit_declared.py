"""NCSC-004 — rate limiting acknowledged: `429` declared on every operation.

The NCSC guidance for §5 (DoS attack mitigation) states:

    "When APIs lack rate limiting and throttling, they become vulnerable to
    excessive… APIs should allow for spikes… absence causes DoS exposure."

The clause is about *behaviour*: the API should throttle. Behaviour is not
checkable from an OpenAPI document, so this rule uses a proxy — a declared
`429 Too Many Requests` response — as evidence that rate limiting was at
least considered. That is why the severity is only `suggestion`: presence of
a `429` key does not prove the service throttles, and absence does not prove
it does not. What it does show is whether the *contract* acknowledges the
possibility. An API whose spec makes no mention of `429` gives clients no
signal that their request may be throttled, which is the concrete
DoS-exposure symptom this proxy catches.

Scope decisions, each pinned by a test:

*   **`default` does not count.** `default` is OpenAPI's catch-all for any
    status not otherwise listed. Reading it as an acknowledgment of rate
    limiting specifically would make every spec with a `default:` entry
    silently compliant, which defeats the proxy.

*   **`4XX` range wildcard does count, with a caveat.** OpenAPI 3 allows
    `4XX` as a range key, and semantically it does include `429`. For MVP
    the rule accepts it: a spec that says "any 4xx" has documented the
    possibility. A strict reading would prefer an explicit `429`; that is a
    future tightening, not a v0.2 requirement.

*   **`$ref` at the response level counts.** `'429': {$ref: ...}` is the
    idiomatic way to share one problem-details response across operations.
    Only key presence matters, so this passes without following the ref.

*   **Missing `responses` block is out of scope.** OpenAPI requires a
    `responses` object on every operation; a spec without one is invalid
    and belongs to `openapi-spec-validator`. This rule silently skips such
    operations rather than double-reporting a schema error as a standards
    finding.

*   **The `Retry-After` header and the body shape of the `429` are out of
    scope.** Both are legitimate concerns and both would be a separate rule
    with a separate clause anchor. For v0.2, "there is a 429 key" is what
    the proxy measures.

*   **Status codes may be integers or strings.** YAML 1.2 parses an
    unquoted `429:` as an integer key; `ruamel.yaml` in round-trip mode
    preserves that type. All status keys are compared as strings, so both
    `'429'` and `429` count.

One `Finding` per offending operation, located at the operation's
`responses` object. The snippet lists the status codes that *are* declared,
comma-separated, so the reader can see at a glance what was documented and
what is missing.
"""

from __future__ import annotations

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, child, iter_operations, snippet

#: Status keys that count as declaring `429`. Everything is compared as a
#: string against `str(key)`, so integer keys work too.
_ACKNOWLEDGES_429 = frozenset({"429", "4XX"})


def _acknowledges_rate_limit(responses: dict) -> bool:
    """True when the responses mapping declares `429` (or the `4XX` range).

    Keys are normalised via `str()` so that both quoted (`'429'`) and
    unquoted (`429`) YAML forms count. The comparison is case-insensitive
    against `4XX` because ruamel preserves the source form and specs vary.
    """
    for key in responses:
        normalised = str(key).strip().upper()
        if normalised in _ACKNOWLEDGES_429:
            return True
    return False


@register(
    "NCSC-004",
    severity=Severity.SUGGESTION,
    clause_id="NCSC-004",
    summary="Rate limiting acknowledged: 429 response defined on every operation",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each operation whose `responses` block declares no `429`."""
    findings: list[Finding] = []

    for op in iter_operations(spec.data):
        # `responses` is required by the OpenAPI spec; a missing or non-mapping
        # `responses` node is a schema error, not a standards finding. Leave
        # it to `openapi-spec-validator` and emit nothing.
        raw = op.operation.get("responses")
        if not isinstance(raw, dict):
            continue

        responses = as_mapping(raw)
        if _acknowledges_rate_limit(responses):
            continue

        # Snippet: the codes that ARE declared, so the reader sees what was
        # documented and can infer what is missing. Keys are stringified for
        # the same integer/string reason as the check above.
        declared = ", ".join(str(key) for key in responses)
        findings.append(
            Finding(
                rule_id="NCSC-004",
                severity=Severity.SUGGESTION,
                # Locate at the `responses` object rather than the operation:
                # a fix inserts a new `429` entry under this node.
                location=child(op.location, "responses"),
                snippet=snippet(declared) if declared else snippet("(no responses declared)"),
                clause_id="NCSC-004",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

"""NCSC-002 — auth declared for every operation (deny by default).

NCSC §2 tells API authors to "deny by default: restrict access by default, permitting
entry only to explicitly authorised entities." Translated to an OpenAPI document,
that means every operation must sit under a non-empty security requirement. Either
the document declares a root-level ``security`` block that the operation inherits,
or the operation declares its own — but somewhere there has to be at least one
requirement that references at least one scheme.

Two shapes of violation:

*   **Type A — unauthenticated by omission.** The operation has no ``security`` key
    of its own, *and* the root has none either (or an empty ``security: []``). No
    requirement is in scope, so the operation is effectively open. The finding sits
    on the operation itself, because there is no operation-level ``security`` node
    to point at.

*   **Type B — explicit opt-out.** The operation declares ``security: []``. In
    OpenAPI that empty array means "no security applies to this operation", i.e. an
    explicit override of any root-level default. This is exactly the "deny by
    default" failure mode NCSC calls out, and it violates regardless of what the
    root declares. The finding sits on the operation's own ``security`` key.

Scope decisions, all pinned by tests:

*   **``security: [{}]`` is compliant.** A security requirement object with zero
    scheme references is the OpenAPI syntax for "optional auth" — a *declared*
    choice, not an omission. Flagging it would collapse the distinction between
    "author considered auth and chose optional" and "author forgot". A separate,
    stricter rule can revisit that later; for MVP this rule accepts it.

*   **``security: [{schemeName: [...]}, {}]`` is also compliant.** The presence of
    a real scheme reference anywhere in the array satisfies "at least one non-empty
    requirement", and the trailing ``{}`` is again the optional-auth idiom.

*   **Malformed values are for the validator, not for this rule.** ``security:
    null``, ``security: "yes"``, an entry that is not a mapping — none of these
    match either violation shape. We do not crash and we do not flag; a schema
    validator will complain in its own pass.

*   **The scope of this rule is per operation.** A root-level ``security: []`` is
    not flagged on its own account — it becomes visible only when an operation
    inherits it (Type A). This keeps the finding count equal to the number of
    unprotected operations, not "operations plus one for the root".

*   **``securitySchemes`` shape is NCSC-001's territory.** This rule does not read
    ``components.securitySchemes`` at all: an API using HTTP Basic still has to
    *declare* a requirement on every operation, and NCSC-001 flags the scheme
    separately. Reading the schemes here would double-report a single mistake.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, child, iter_operations, snippet


def _has_non_empty_requirement(security: Any) -> bool:
    """True when a ``security`` value declares at least one requirement.

    "Declared" is the key word. An entry ``{}`` counts — it is the OpenAPI idiom
    for "optional auth", a deliberate choice rather than an omission. What does
    *not* count is the empty array ``[]``, which is OpenAPI for "explicitly no
    auth on this operation". Non-list values (``null``, scalars, mappings) are
    treated as "nothing declared" — malformed input is a validator's problem, so
    the caller falls back to the root default rather than flagging on our own.
    """
    if not isinstance(security, list):
        return False
    for requirement in security:
        if isinstance(requirement, dict):
            return True
    return False


@register(
    "NCSC-002",
    severity=Severity.ERROR,
    clause_id="NCSC-002",
    summary="Auth declared for every operation (deny by default)",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag operations that have no effective, non-empty security requirement."""
    data = spec.data
    root_security = as_mapping(data).get("security")
    root_has_requirement = _has_non_empty_requirement(root_security)

    findings: list[Finding] = []

    for op in iter_operations(data):
        # `in`, not `.get`, so an explicit `security: []` (or `null`) is
        # distinguishable from "key not present at all".
        if "security" in op.operation:
            op_security = op.operation["security"]

            # Malformed values (null, scalars, mappings) are ignored: a schema
            # validator owns those, and guessing at intent here would false-positive.
            if op_security is None or not isinstance(op_security, list):
                continue

            if _has_non_empty_requirement(op_security):
                continue

            # Type B: explicit opt-out. `security: []` overrides any root default,
            # so the location points at the operation's own `security` key.
            findings.append(
                Finding(
                    rule_id="NCSC-002",
                    severity=Severity.ERROR,
                    location=child(op.location, "security"),
                    snippet=snippet(
                        f"security: [] on {op.label} — explicit opt-out"
                    ),
                    clause_id="NCSC-002",
                    rule_type=RuleType.DETERMINISTIC,
                )
            )
            continue

        # Operation has no `security` key: falls back to the root default.
        if root_has_requirement:
            continue

        # Type A: unauthenticated by omission. Neither root nor operation declares
        # anything usable. Point at the operation itself, since there is no
        # operation-level `security` node to target.
        findings.append(
            Finding(
                rule_id="NCSC-002",
                severity=Severity.ERROR,
                location=op.location,
                snippet=snippet(
                    f"no security requirement on {op.label}: "
                    "root and operation-level security both missing"
                ),
                clause_id="NCSC-002",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

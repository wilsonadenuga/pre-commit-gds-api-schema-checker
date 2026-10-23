"""NCSC-002 — every endpoint must require login (deny by default).

NCSC says access should be denied unless someone is explicitly allowed in. In an
OpenAPI file, every operation needs a security requirement, either its own or one
set for the whole API.

Two things are flagged:

- No login at all: the operation sets nothing and neither does the whole API.
- Login switched off: the operation says `security: []`.

- `security: [{}]` is fine. It means login is optional, which is a deliberate choice.
- Broken values are left to the schema validator.
- Which login methods are allowed is NCSC-001's job.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, child, iter_operations, snippet


def _has_non_empty_requirement(security: Any) -> bool:
    """True if `security` sets at least one requirement.

    `[{}]` (optional login) counts. `[]` (login off) does not. Anything that isn't a
    list counts as nothing set.
    """
    if not isinstance(security, list):
        return False
    for requirement in security:
        if isinstance(requirement, dict):
            return True
    return False


GOOD_EXAMPLE = """\
security:
  - departmentOAuth: []
paths:
  /v1/users:
    get:
      # No operation-level `security` — inherits the root requirement.
      responses:
        '200': {...}
"""


@register(
    "NCSC-002",
    severity=Severity.ERROR,
    clause_id="NCSC-002",
    summary="Auth declared for every operation (deny by default)",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag operations that don't require login."""
    data = spec.data
    root_security = as_mapping(data).get("security")
    root_has_requirement = _has_non_empty_requirement(root_security)

    findings: list[Finding] = []

    for op in iter_operations(data):
        # `in` tells "set to []" apart from "not set at all".
        if "security" in op.operation:
            op_security = op.operation["security"]

            # Broken values are ignored; the schema validator reports them.
            if op_security is None or not isinstance(op_security, list):
                continue

            if _has_non_empty_requirement(op_security):
                continue

            # Login switched off with `security: []`.
            findings.append(
                Finding(
                    rule_id="NCSC-002",
                    severity=Severity.ERROR,
                    location=child(op.location, "security"),
                    snippet=snippet(
                        f"{op.label} switches authentication off with security: []"
                    ),
                    clause_id="NCSC-002",
                    rule_type=RuleType.DETERMINISTIC,
                )
            )
            continue

        # No `security` on the operation, so it uses the API-wide one.
        if root_has_requirement:
            continue

        # No login anywhere.
        findings.append(
            Finding(
                rule_id="NCSC-002",
                severity=Severity.ERROR,
                location=op.location,
                snippet=snippet(
                    f"{op.label} has no authentication: no security is declared "
                    "for it or for the whole API"
                ),
                clause_id="NCSC-002",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

"""NCSC-001 — no weak login methods.

NCSC advises against HTTP Basic (a username and password sent on every request)
and plain API keys, because both are easy to leak and hard to change. Use OAuth 2.0
or OpenID Connect instead.

- Checks every scheme under `components.securitySchemes`, even unused ones.
- Flags `type: http` with `scheme: basic`, and any `type: apiKey`.
- Everything else is fine, including bearer tokens.
- Whether endpoints actually require login is NCSC-002's job.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, child, jp, snippet


def _describe_weakness(name: object, scheme: dict[str, Any]) -> str:
    """The message shown in the report, e.g. "'basicAuth' is HTTP basic authentication..."."""
    scheme_type = scheme.get("type")
    if scheme_type == "http" and str(scheme.get("scheme", "")).lower() == "basic":
        return (
            f"'{name}' is HTTP basic authentication, which NCSC advises against; "
            f"use OAuth 2.0 or OpenID Connect instead"
        )
    if scheme_type == "apiKey":
        location = scheme.get("in", "?")
        return (
            f"'{name}' is a plain API key (in {location}), which NCSC advises against; "
            f"use OAuth 2.0 or OpenID Connect instead"
        )
    return f"'{name}' uses a weak authentication scheme"  # pragma: no cover


def _is_weak_scheme(scheme: dict[str, Any]) -> bool:
    """True if the scheme is HTTP Basic or a plain API key."""
    scheme_type = scheme.get("type")
    if not isinstance(scheme_type, str):
        return False
    if scheme_type == "apiKey":
        return True
    if scheme_type == "http":
        http_scheme = scheme.get("scheme")
        return isinstance(http_scheme, str) and http_scheme.lower() == "basic"
    return False


GOOD_EXAMPLE = """\
components:
  securitySchemes:
    departmentOAuth:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://auth.example.gov.uk/token
          scopes: {}
"""


@register(
    "NCSC-001",
    severity=Severity.ERROR,
    clause_id="NCSC-001",
    summary="No basic-auth and no bare apiKey auth schemes",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each `components.securitySchemes` entry that is basic or apiKey."""
    data = spec.data
    findings: list[Finding] = []

    components = as_mapping(as_mapping(data).get("components"))
    security_schemes = as_mapping(components.get("securitySchemes"))

    for name, scheme in security_schemes.items():
        if not isinstance(scheme, dict):
            continue  # a non-mapping scheme entry is malformed, not weak
        if not _is_weak_scheme(scheme):
            continue
        findings.append(
            Finding(
                rule_id="NCSC-001",
                severity=Severity.ERROR,
                location=child(jp("components", "securitySchemes"), str(name)),
                snippet=snippet(_describe_weakness(name, scheme)),
                clause_id="NCSC-001",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

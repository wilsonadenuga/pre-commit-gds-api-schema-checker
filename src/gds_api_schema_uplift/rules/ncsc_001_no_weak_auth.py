"""NCSC-001 — no weak authentication schemes declared under `components`.

NCSC §2 ("API authentication and authorisation — Avoid weak authentication methods")
calls out two mechanisms by name: HTTP Basic, which ships a base64-encoded
username/password on every request, and bare API keys, which are shared bearer
tokens in a header/query/cookie. Both are easy to leak and hard to rotate, so the
guidance is to prefer stronger schemes (OAuth 2.0, OpenID Connect, mutual TLS, or
at least bearer JWTs) instead.

Scope is deliberately narrow: this rule inspects `components.securitySchemes` and
nothing else. Each declared scheme is judged on its own — a spec is
non-compliant if it *offers* a weak scheme, whether or not any operation uses it.

Two flavours are flagged:

*   `type: http` with `scheme: basic` — HTTP Basic, banned outright.
*   `type: apiKey` (in header, query, or cookie) — bare API key, also banned.

Everything else — `oauth2`, `openIdConnect`, `mutualTLS`, and any other `type: http`
scheme such as bearer JWT — is left alone. In particular `type: http, scheme: bearer`
is compliant: NCSC bans basic and apiKey specifically, not all HTTP schemes.

What this rule deliberately does NOT check:

*   The document-level `security` array or per-operation `security` overrides.
    Opting out of authentication, or missing global authentication, is NCSC-002's
    territory (deny-by-default). Walking `paths` here would double-report.
*   Whether a weak scheme is actually *referenced* by any operation. An unused but
    declared weak scheme still advertises support for it and is a hazard.
*   Malformed or wrongly-typed scheme entries. A scheme node that is not a mapping,
    or whose `type` is not a string, is skipped rather than flagged — the fixture
    contract counts one finding per genuinely weak scheme, and treating malformed
    nodes as violations would inflate that count against structurally odd specs.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, child, jp, snippet


def _describe_weakness(name: object, scheme: dict[str, Any]) -> str:
    """Human-readable snippet naming the specific weakness.

    Kept close to `_is_weak_scheme` so a change to what "weak" means shows
    up on the message too. `name` is the securityScheme's key (e.g.
    `basicAuth`) — the developer's own label for it.
    """
    scheme_type = scheme.get("type")
    if scheme_type == "http" and str(scheme.get("scheme", "")).lower() == "basic":
        return (
            f"'{name}' is HTTP basic authentication — banned by NCSC §2; "
            f"use OAuth 2.0 or OpenID Connect instead"
        )
    if scheme_type == "apiKey":
        location = scheme.get("in", "?")
        return (
            f"'{name}' is a bare apiKey (in={location}) — banned by NCSC §2; "
            f"use OAuth 2.0 or OpenID Connect instead"
        )
    return f"'{name}' uses a weak authentication scheme"  # pragma: no cover


def _is_weak_scheme(scheme: dict[str, Any]) -> bool:
    """True when a security scheme is HTTP Basic or a bare API key.

    `type` and `scheme` are compared case-sensitively against the OpenAPI enum
    values, which are lower-case in the spec. A scheme whose `type` is not a
    string is treated as unknown and left to a schema-validity check upstream.
    """
    scheme_type = scheme.get("type")
    if not isinstance(scheme_type, str):
        return False
    if scheme_type == "apiKey":
        return True
    if scheme_type == "http":
        http_scheme = scheme.get("scheme")
        return isinstance(http_scheme, str) and http_scheme.lower() == "basic"
    return False


#: The compliant shape, rendered by the report's "How to fix" section.
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
                # The scheme entry itself: a fix replaces the whole named scheme.
                location=child(jp("components", "securitySchemes"), str(name)),
                snippet=snippet(_describe_weakness(name, scheme)),
                clause_id="NCSC-001",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

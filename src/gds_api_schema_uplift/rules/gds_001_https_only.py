"""GDS-001 — HTTPS-only.

The PRD wording is "HTTPS-only, TLS 1.2+". Only the first half is checkable here:
an OpenAPI document declares transport as a URL scheme and has no vocabulary for a
minimum TLS version — that is a property of the deployed endpoint's configuration,
not of the description. So this rule checks the scheme of every declared server URL
and says nothing about TLS 1.2+; the cipher/protocol half belongs to infrastructure
review and is out of scope for a spec linter.

Scope is the root `servers` array. Per-path and per-operation `servers` overrides
exist in OpenAPI 3.x, but the fixture contract fixes this rule at one finding per
non-compliant root server entry, so widening the scope is a deliberate future change
rather than an oversight.
"""

from __future__ import annotations

import re

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, jp, snippet

#: A URL that begins with a scheme, per RFC 3986 s3.1 followed by "//" authority.
#: Anything that does not match is relative (`/api`, `api/v1`) or a bare server
#: variable (`{server}/v1`), and inherits the scheme of the document's host.
_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*)://")


def _is_compliant(url: str) -> bool:
    """True when `url` does not declare a non-HTTPS transport.

    Compliant cases:
      * `https://api.example.gov.uk` — the plain good case.
      * `https://{host}/v1` — a server variable in the host position still pins the
        scheme, so it is compliant regardless of what the variable expands to.
      * `/api`, `v1/users`, `{basePath}` — relative; these resolve against the
        location the document was served from, so they inherit that scheme. Flagging
        them would be a false positive, and M1 is measured on zero false positives.

    Non-compliant: any explicit scheme other than https (`http://`, `ws://`, `ftp://`).
    """
    match = _SCHEME.match(url.strip())
    if match is None:
        return True  # relative or variable-prefixed: scheme is inherited, not declared
    return match.group("scheme").lower() == "https"  # schemes are case-insensitive


@register(
    "GDS-001",
    severity=Severity.ERROR,
    clause_id="GDS-001",
    summary="HTTPS-only: every declared server URL must use https://",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each root `servers` entry whose `url` declares a non-HTTPS scheme."""
    findings: list[Finding] = []

    # A missing, empty or wrongly-typed `servers` key yields nothing. Absence is not a
    # transport violation — an OpenAPI document with no `servers` is served relative to
    # wherever it was fetched from, so there is no plaintext URL to object to.
    for index, entry in enumerate(as_sequence(as_mapping(spec.data).get("servers"))):
        url = as_mapping(entry).get("url")
        if not isinstance(url, str):
            # Missing or non-string `url` is a schema error, caught by the version
            # gate / spec validator. Emitting a transport finding here would report
            # the same defect twice under the wrong rule id.
            continue
        if _is_compliant(url):
            continue
        findings.append(
            Finding(
                rule_id="GDS-001",
                severity=Severity.ERROR,
                location=jp("servers", index, "url"),
                snippet=snippet(url),
                clause_id="GDS-001",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

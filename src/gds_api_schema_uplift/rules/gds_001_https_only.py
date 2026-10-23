"""GDS-001 — every server URL must use https://.

GDS also requires TLS 1.2 or above, but an OpenAPI file can't say which TLS version
a server uses, so that part can't be checked here.

Only the top-level `servers` list is checked, one finding per http:// entry.
"""

from __future__ import annotations

import re

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, jp, snippet

#: Matches a URL that starts with a scheme, like `https://`. URLs without one
#: (`/api`, `{server}/v1`) use whatever scheme the spec was served from.
_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*)://")


def _is_compliant(url: str) -> bool:
    """True unless the URL starts with a scheme other than https.

    `https://...` passes. Relative URLs like `/api` pass too, because they don't
    choose a scheme. `http://`, `ws://` and `ftp://` fail.
    """
    match = _SCHEME.match(url.strip())
    if match is None:
        return True  # no scheme given
    return match.group("scheme").lower() == "https"  # HTTPS and https are the same


GOOD_EXAMPLE = """\
servers:
  - url: https://api.example.gov.uk/v1
    description: Production
"""


@register(
    "GDS-001",
    severity=Severity.ERROR,
    clause_id="GDS-001",
    summary="HTTPS-only: every declared server URL must use https://",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each root `servers` entry whose `url` declares a non-HTTPS scheme."""
    findings: list[Finding] = []

    # No `servers` list means no http:// URL, so nothing to flag.
    for index, entry in enumerate(as_sequence(as_mapping(spec.data).get("servers"))):
        url = as_mapping(entry).get("url")
        if not isinstance(url, str):
            # A missing or broken `url` is a schema error, reported elsewhere.
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

"""GDS-003 — the API version must be in the URL, e.g. `/v1/users`.

The version must be its own path segment: `/v1/users` passes,
`/service-v1-beta/users` doesn't.

The version can be in the server URL instead (`https://api.example.gov.uk/v1`).
If every server URL has one, the paths don't need it.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, iter_paths, snippet

#: A version segment: `v1`, `V2`, `v1.0`. Must be the whole segment.
VERSION_SEGMENT = re.compile(r"v\d+(?:\.\d+)?", re.IGNORECASE)


def _has_version_segment(candidate: str) -> bool:
    """True if any part of the path between slashes is a version."""
    return any(
        VERSION_SEGMENT.fullmatch(segment) for segment in str(candidate).split("/") if segment
    )


def _server_url_is_versioned(server: Any) -> bool:
    """True if this server URL has a version in its path.

    Only the path counts. A host like `v2.api.example.gov.uk` doesn't.
    """
    url = as_mapping(server).get("url")
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url.strip())
    except ValueError:  # broken URL: treat as unversioned
        return False
    return _has_version_segment(parsed.path)


def _versioning_lives_in_servers(data: Any) -> bool:
    """True if there is at least one server and every server URL has a version."""
    servers = as_sequence(as_mapping(data).get("servers"))
    return bool(servers) and all(_server_url_is_versioned(server) for server in servers)


GOOD_EXAMPLE = """\
paths:
  /v1/users:
    get:
      responses:
        '200': {...}
"""


@register(
    "GDS-003",
    severity=Severity.WARNING,
    clause_id="GDS-003",
    summary="API version must be declared in the URI path (e.g. /v1/...)",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each path that has no version."""
    data = spec.data
    if _versioning_lives_in_servers(data):
        return []

    findings: list[Finding] = []
    for path, _path_item, location in iter_paths(data):
        if _has_version_segment(path):
            continue
        findings.append(
            Finding(
                rule_id="GDS-003",
                severity=Severity.WARNING,
                location=location,
                snippet=snippet(path),
                clause_id="GDS-003",
                rule_type=RuleType.DETERMINISTIC,
            )
        )
    return findings

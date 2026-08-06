"""GDS-003 — the API version must be declared in the URI path.

GDS asks for the major version to be visible in the URI so that a caller can see,
from the request line alone, which contract they are bound to. In practice that
means a `/v1/...` segment somewhere in the effective URL.

Two design decisions worth stating, because both change the finding count:

1.  A version segment must be a *whole* path segment. `/v1/users` counts;
    `/service-v1-beta/users` does not, because the "v1" there is part of a name and
    a caller cannot rely on it moving when the contract changes.

2.  The version may legitimately live in the `servers` URL instead of in every
    path — `https://api.example.gov.uk/v1` plus a path of `/users` produces the
    same effective URI as `/v1/users`, and repeating the segment in every path
    entry would then be wrong rather than right. So if *every* declared server URL
    already carries a version segment, the paths need not repeat it and this rule
    stays silent for the whole document. If only some servers carry one, callers of
    the others get an unversioned URI, so the paths are still at fault and the
    findings stand.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import as_mapping, as_sequence, iter_paths, snippet

#: A whole path segment that is a version: `v1`, `V2`, `v1.0`. Case-insensitive, and
#: anchored with `fullmatch` at the call site so a segment like `service-v1-beta`
#: cannot satisfy it.
VERSION_SEGMENT = re.compile(r"v\d+(?:\.\d+)?", re.IGNORECASE)


def _has_version_segment(candidate: str) -> bool:
    """True when any `/`-delimited segment of `candidate` is a version segment."""
    return any(
        VERSION_SEGMENT.fullmatch(segment) for segment in str(candidate).split("/") if segment
    )


def _server_url_is_versioned(server: Any) -> bool:
    """True when a `servers` entry declares a URL whose path carries a version.

    Only the URL *path* is considered: a host such as `v2.api.example.gov.uk` is a
    hostname convention, not URI-path versioning, and splitting the raw URL on `/`
    would otherwise let it suppress real findings.
    """
    url = as_mapping(server).get("url")
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url.strip())
    except ValueError:  # malformed URL — treat as unversioned rather than raising
        return False
    return _has_version_segment(parsed.path)


def _versioning_lives_in_servers(data: Any) -> bool:
    """True when every declared server URL already carries a version segment.

    Requires at least one server: an empty or absent `servers` list means the spec
    declares no base URL at all, so there is nowhere for the version to hide.
    """
    servers = as_sequence(as_mapping(data).get("servers"))
    return bool(servers) and all(_server_url_is_versioned(server) for server in servers)


#: The compliant shape, rendered by the report's "How to fix" section.
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
    """Flag each path entry that carries no version segment."""
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
                # `location` comes from `iter_paths`, i.e. `jp("paths", path)`: the
                # finding sits on the path item itself, since that is the key a fix
                # has to rename.
                location=location,
                snippet=snippet(path),
                clause_id="GDS-003",
                rule_type=RuleType.DETERMINISTIC,
            )
        )
    return findings

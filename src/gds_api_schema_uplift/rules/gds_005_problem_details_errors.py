"""GDS-005 — errors must use one standard shape and real HTTP status codes.

Two checks:

1. Shape: an error response's JSON body must be RFC 9457 problem details
   (`application/problem+json`).
2. Code: the status code must be a real HTTP error code (e.g. not `599`).

- One finding per response for each check.
- Error responses with no body are not checked here.
- Non-JSON error bodies are left to GDS-004.
- A `$ref` we can't follow is treated as fine, to avoid false alarms.
- Ranges like `4XX` and `5XX` are allowed.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import (
    ContentRef,
    ResponseRef,
    as_mapping,
    as_sequence,
    iter_content,
    iter_responses,
    snippet,
)

#: The five standard problem-details fields.
PROBLEM_MEMBERS = frozenset({"type", "title", "status", "detail", "instance"})

#: Having both `title` and `status` is enough to count as problem details.
PROBLEM_CORE = frozenset({"title", "status"})

#: Otherwise, at least 3 of the 5 fields are needed.
PROBLEM_MEMBER_THRESHOLD = 3

#: Real 4xx error codes.
CLIENT_ERROR_CODES = frozenset(
    {
        400, 401, 402, 403, 404, 405, 406, 407, 408, 409,
        410, 411, 412, 413, 414, 415, 416, 417, 418,
        421, 422, 423, 424, 425, 426, 428, 429, 431, 451,
    }
)

#: Real 5xx error codes.
SERVER_ERROR_CODES = frozenset({500, 501, 502, 503, 504, 505, 506, 507, 508, 510, 511})

STANDARD_ERROR_CODES = CLIENT_ERROR_CODES | SERVER_ERROR_CODES

#: The only kind of `$ref` we follow.
_LOCAL_SCHEMA_PREFIX = "#/components/schemas/"

#: Stops us looping forever if schemas refer to each other in a circle.
_MAX_REF_DEPTH = 12


def _resolve_schema(schema: Any, data: Any, depth: int = 0) -> dict[str, Any] | None:
    """Follow a `#/components/schemas/<Name>` link. Returns None if it can't."""
    node = as_mapping(schema)
    ref = node.get("$ref")
    if ref is None:
        return node
    if depth >= _MAX_REF_DEPTH or not isinstance(ref, str):
        return None
    if not ref.startswith(_LOCAL_SCHEMA_PREFIX):
        return None  # external or non-components pointer: out of our reach
    name = ref[len(_LOCAL_SCHEMA_PREFIX) :]
    schemas = as_mapping(as_mapping(as_mapping(data).get("components")).get("schemas"))
    target = schemas.get(name)
    if not isinstance(target, dict):
        return None  # dangling name
    return _resolve_schema(target, data, depth + 1)


def _property_names(schema: Any, data: Any, depth: int = 0) -> set[str] | None:
    """The field names a schema declares, including via `$ref`, `allOf`, `anyOf`
    and `oneOf`. Returns None if a `$ref` can't be followed.
    """
    if depth >= _MAX_REF_DEPTH:
        return None
    resolved = _resolve_schema(schema, data)
    if resolved is None:
        return None

    names: set[str] = {str(key) for key in as_mapping(resolved.get("properties"))}

    # Some schemas only list their fields under `required`, so read that too.
    names.update(
        str(item)
        for item in as_sequence(resolved.get("required"))
        if isinstance(item, str)
    )

    for combinator in ("allOf", "anyOf", "oneOf"):
        for member in as_sequence(resolved.get(combinator)):
            member_names = _property_names(member, data, depth + 1)
            if member_names is None:
                return None  # an unresolvable branch makes the whole shape unknown
            names.update(member_names)

    return names


def _looks_like_problem_details(schema: Any, data: Any) -> bool:
    """True if the schema looks like problem details.

    That means it has `title` and `status`, or at least 3 of the 5 standard fields.
    An empty schema, or one we can't read, also passes, to avoid false alarms.
    """
    names = _property_names(schema, data)
    if names is None or not names:
        return True
    if PROBLEM_CORE <= names:
        return True
    return len(names & PROBLEM_MEMBERS) >= PROBLEM_MEMBER_THRESHOLD


def _first_failing_json_body(response: ResponseRef, data: Any) -> ContentRef | None:
    """The first JSON body on this response that isn't problem details, or None."""
    for content in iter_content(response.response, response.location):
        if not content.is_json or content.is_problem_json:
            continue
        if not _looks_like_problem_details(content.media_object.get("schema"), data):
            return content
    return None


GOOD_EXAMPLE = """\
responses:
  '500':
    description: Server error
    content:
      application/problem+json:
        schema:
          $ref: '#/components/schemas/Problem'
"""


@register(
    "GDS-005",
    severity=Severity.WARNING,
    clause_id="GDS-005",
    summary="Error responses must use a consistent documented shape (RFC 9457 problem+json)",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag ad-hoc error bodies and non-standard error status codes."""
    data = spec.data
    findings: list[Finding] = []

    for response in iter_responses(data):
        if not response.is_error:
            continue

        # Code check. Only plain numbers are checked, so `4XX`/`5XX` pass.
        code = response.status_int
        if code is not None and code >= 400 and code not in STANDARD_ERROR_CODES:
            findings.append(
                Finding(
                    rule_id="GDS-005",
                    severity=Severity.WARNING,
                    location=response.location,
                    snippet=snippet(f"non-standard HTTP error code {response.status}"),
                    clause_id="GDS-005",
                    rule_type=RuleType.DETERMINISTIC,
                )
            )

        # Shape check. At most one finding, on the first bad body.
        content = _first_failing_json_body(response, data)
        if content is None:
            continue
        findings.append(
            Finding(
                rule_id="GDS-005",
                severity=Severity.WARNING,
                location=content.location,
                snippet=snippet(
                    f"error uses {content.media_type} with a custom schema — "
                    f"use application/problem+json (RFC 9457) instead"
                ),
                clause_id="GDS-005",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

"""GDS-005 — errors are consistent, mapped to standard HTTP codes, and documented.

GDS asks for one error shape across an API, carried on standard HTTP status codes.
The target shape is RFC 9457 problem details (`application/problem+json`); its
predecessor RFC 7807 is the same media type and the same members, and PRD s7.3
accepts it, so nothing here distinguishes the two.

Two checks live in this rule, because GDS states them as one clause:

1.  *Shape* — an error response's JSON body must look like problem details.
2.  *Code* — the status code itself must be a real HTTP error code.

They are independent violations, so a response can in principle produce one of each
(a `599` carrying an ad-hoc body is two separate things to fix, and a patch for one
does not fix the other). Within each check, though, a response yields at most one
finding.

Scope decisions, all of which change the finding count and so are pinned by tests:

*   **One shape finding per error response**, located at the `content` media-type
    entry that failed. A response listing several bodies is one violation of one
    clause — reporting each media type separately would inflate the count and give
    the agent several patches for a single mistake — so only the *first* failing
    media type is reported.

*   **Absence is not this rule's business.** An error response with no `content`, or
    a media type with no `schema`, is an undocumented body: a different rule's
    finding. Flagging it here would double-report.

*   **Non-JSON error bodies belong to GDS-004.** If an error response declares no
    JSON media type at all (say `application/xml` only), this rule stays silent; the
    media-type rule already owns "responses must be JSON". Once GDS-004 is fixed the
    body becomes JSON and this rule can judge its shape.

*   **An unresolvable `$ref` is treated as compliant.** We resolve only local
    `#/components/schemas/<Name>` pointers. A pointer we cannot follow — external
    file, unusual JSON Pointer, dangling name — is unknown, not wrong, and guessing
    would produce a false positive on a perfectly good multi-file spec.

*   **Range keys are never bad codes.** `4XX`/`5XX` are legal OpenAPI response keys,
    so the code check skips anything that is not a plain integer.
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

#: The RFC 9457 / RFC 7807 problem-details members.
PROBLEM_MEMBERS = frozenset({"type", "title", "status", "detail", "instance"})

#: Members that, on their own, are enough to call a schema problem-shaped. `title` +
#: `status` is the smallest pair that cannot plausibly belong to an ad-hoc envelope:
#: `status` in a *body* is the problem-details idiom, and no ad-hoc shape we care
#: about ("err_msg"/"err_code", "message", "error") carries it.
PROBLEM_CORE = frozenset({"title", "status"})

#: How many of `PROBLEM_MEMBERS` a schema needs when it lacks the core pair. Three of
#: five is deliberate: `type`/`detail`/`instance` together are unmistakably RFC 9457,
#: while any two of them could be coincidence.
PROBLEM_MEMBER_THRESHOLD = 3

#: Registered IANA HTTP client-error codes (4xx). `418` is included: IANA reserves it
#: rather than leaving it unassigned, and this check errs towards silence.
CLIENT_ERROR_CODES = frozenset(
    {
        400, 401, 402, 403, 404, 405, 406, 407, 408, 409,
        410, 411, 412, 413, 414, 415, 416, 417, 418,
        421, 422, 423, 424, 425, 426, 428, 429, 431, 451,
    }
)

#: Registered IANA HTTP server-error codes (5xx).
SERVER_ERROR_CODES = frozenset({500, 501, 502, 503, 504, 505, 506, 507, 508, 510, 511})

STANDARD_ERROR_CODES = CLIENT_ERROR_CODES | SERVER_ERROR_CODES

#: Prefix of the only `$ref` form we resolve.
_LOCAL_SCHEMA_PREFIX = "#/components/schemas/"

#: Guard against a `$ref` cycle in `components.schemas`, which is legal in JSON Schema.
_MAX_REF_DEPTH = 12


def _resolve_schema(schema: Any, data: Any, depth: int = 0) -> dict[str, Any] | None:
    """Follow a local `#/components/schemas/<Name>` pointer to the schema it names.

    Returns the resolved mapping, or `None` when the node is a `$ref` we decline to
    follow or cannot find. `None` means "unknown", and every caller reads it as
    compliant rather than as a violation.
    """
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
    """Collect the property names a schema declares, across `$ref` and combinators.

    `allOf`/`anyOf`/`oneOf` are unioned because problem details are very often
    expressed as `allOf: [Problem, {extra members}]`, and a per-branch view would
    miss the members that make the shape recognisable.

    Returns `None` when the schema is a `$ref` we could not resolve — the shape is
    then unknown and the caller must not flag it.
    """
    if depth >= _MAX_REF_DEPTH:
        return None
    resolved = _resolve_schema(schema, data)
    if resolved is None:
        return None

    names: set[str] = {str(key) for key in as_mapping(resolved.get("properties"))}

    # `required` is a weaker signal than `properties`, but a schema may name its
    # members there only (`additionalProperties` plus `required`), and reading it
    # costs nothing while removing a class of false positive.
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
    """True when a schema's members read as RFC 9457 / RFC 7807 problem details.

    Compliant when the schema carries `title` *and* `status`, or at least
    `PROBLEM_MEMBER_THRESHOLD` of the five problem-details members.

    Also true — deliberately — when the schema declares no members we can see at all
    (empty, `$ref` we cannot resolve, a bare `type: object`). There is nothing there
    to judge, and "undocumented body" is a different rule's finding.
    """
    names = _property_names(schema, data)
    if names is None or not names:
        return True
    if PROBLEM_CORE <= names:
        return True
    return len(names & PROBLEM_MEMBERS) >= PROBLEM_MEMBER_THRESHOLD


def _first_failing_json_body(response: ResponseRef, data: Any) -> ContentRef | None:
    """The first JSON media type on a response whose schema is not problem-shaped.

    `application/problem+json` is the target shape and always passes, whatever its
    schema says — the media type is the contract. Non-JSON media types are skipped
    (GDS-004's territory), so a response with no JSON body returns `None`.
    """
    for content in iter_content(response.response, response.location):
        if not content.is_json or content.is_problem_json:
            continue
        if not _looks_like_problem_details(content.media_object.get("schema"), data):
            return content
    return None


@register(
    "GDS-005",
    severity=Severity.WARNING,
    clause_id="GDS-005",
    summary="Error responses must use a consistent documented shape (RFC 9457 problem+json)",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag ad-hoc error bodies and non-standard error status codes."""
    data = spec.data
    findings: list[Finding] = []

    for response in iter_responses(data):
        if not response.is_error:
            continue

        # --- code check: only plain integers are judged, so `4XX`/`5XX` are safe ---
        code = response.status_int
        if code is not None and code >= 400 and code not in STANDARD_ERROR_CODES:
            findings.append(
                Finding(
                    rule_id="GDS-005",
                    severity=Severity.WARNING,
                    # The response itself, since the status *key* is what a fix renames.
                    location=response.location,
                    snippet=snippet(f"non-standard HTTP error code {response.status}"),
                    clause_id="GDS-005",
                    rule_type=RuleType.DETERMINISTIC,
                )
            )

        # --- shape check: at most one finding, on the first failing media type ---
        content = _first_failing_json_body(response, data)
        if content is None:
            continue
        findings.append(
            Finding(
                rule_id="GDS-005",
                severity=Severity.WARNING,
                # The media-type entry, not the schema: a fix replaces the whole
                # entry (media type *and* schema) with a problem+json one.
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

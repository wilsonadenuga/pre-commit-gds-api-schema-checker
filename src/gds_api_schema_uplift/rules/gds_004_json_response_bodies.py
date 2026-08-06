"""GDS-004 — JSON responses.

The PRD wording is "JSON responses, UTF-8 encoding". Only the first half is
checkable here. Character encoding is not expressible per-response in an OpenAPI
document: a Media Type Object describes the *shape* of a payload (`schema`,
`example`, `encoding` for multipart parts), and the charset of the wire bytes is a
property of the response header the server actually sends. A `charset` parameter can
be pinned in the media-type key itself (`application/json; charset=utf-8`), but it is
optional and its absence is not a defect — RFC 8259 s8.1 already requires JSON text
exchanged between systems to be UTF-8. So this rule checks the media type only and
says nothing about encoding; UTF-8 conformance belongs to endpoint/integration
testing, not to a spec linter.

Scope decisions:

* **Response bodies only.** Request-body media types are deliberately not checked
  here. Request-side payload constraints are NCSC-003's territory in a later phase,
  and flagging both sides from this rule would double-report a single XML-in/XML-out
  operation under one rule id.

* **Absence is not a violation.** A response with no `content` at all — `204 No
  Content`, `304 Not Modified`, or a bare `description` on a response that legally
  has no body — yields nothing. "This response declares no schema" is a different
  rule with a different clause; a rule about *which* media type is used has nothing
  to say when no media type is declared.

* **File-download payloads are allowed.** Some responses are legitimately not JSON
  by nature, and rewriting them to `application/json` would be wrong rather than
  compliant. `_ALLOWED_NON_JSON` below lists the ones we accept: binary blobs
  (`application/octet-stream`, `application/zip`), documents (`application/pdf`),
  bulk data export (`text/csv`), and any `image/*` type. These pass silently.

* **Everything else is flagged.** In particular `application/xml`, `text/xml`,
  `text/plain` and `application/x-www-form-urlencoded` are violations: each has a
  natural JSON equivalent, so each is a real "should have been JSON" case.

One finding per non-JSON response media type, located at that media-type entry, so a
response offering both `application/json` and `application/xml` is flagged once — at
the XML entry, which is the node a Phase 3 patch would remove.
"""

from __future__ import annotations

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_response_content, snippet

#: Media types that are acceptable non-JSON response payloads. Compared against the
#: media type with any parameters stripped and lowercased.
_ALLOWED_NON_JSON = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "text/csv",
    }
)

#: Type prefixes that are acceptable wholesale. `image/*` covers png, jpeg, svg+xml
#: and anything else a download endpoint might serve.
_ALLOWED_NON_JSON_PREFIXES = ("image/",)


def _base_type(media_type: str) -> str:
    """The media type without parameters, lowercased.

    `application/json; charset=utf-8` -> `application/json`. Media types and their
    parameter names are case-insensitive per RFC 9110 s8.3.1.
    """
    return media_type.split(";")[0].strip().lower()


def _is_allowed_non_json(media_type: str) -> bool:
    """True when a non-JSON media type is a legitimate file-download payload."""
    base = _base_type(media_type)
    return base in _ALLOWED_NON_JSON or base.startswith(_ALLOWED_NON_JSON_PREFIXES)


@register(
    "GDS-004",
    severity=Severity.WARNING,
    clause_id="GDS-004",
    summary="Response bodies must be JSON (application/json or a +json media type)",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each response media type that is neither JSON nor an allowed download."""
    findings: list[Finding] = []

    # `iter_response_content` skips responses with no `content` mapping, which is
    # exactly the "absence is not a violation" behaviour this rule wants — a 204 is
    # never reached by this loop.
    for _response, content in iter_response_content(spec.data):
        # `ContentRef.is_json` covers `application/json` and every structured `+json`
        # suffix (`application/problem+json`, `application/hal+json`, ...), including
        # keys carrying a `charset` parameter.
        if content.is_json:
            continue
        if _is_allowed_non_json(content.media_type):
            continue
        findings.append(
            Finding(
                rule_id="GDS-004",
                severity=Severity.WARNING,
                # The ContentRef's own location, never a hand-built JSONPath: this is
                # the media-type entry, e.g.
                # $.paths['/v1/users'].get.responses['200'].content['application/xml']
                location=content.location,
                snippet=snippet(
                    f"response media type is {content.media_type} — "
                    f"GDS mandates JSON (application/json or a +json subtype)"
                ),
                clause_id="GDS-004",
                rule_type=RuleType.DETERMINISTIC,
            )
        )

    return findings

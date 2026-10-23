"""GDS-004 — responses must be JSON.

GDS also asks for UTF-8, but an OpenAPI file can't reliably say that, and JSON is
UTF-8 by definition anyway, so only the media type is checked.

- Only response bodies are checked, not request bodies.
- A response with no body (like 204) is fine.
- File downloads are fine: PDF, CSV, ZIP, binary files and images.
- Anything else that isn't JSON (like XML or plain text) is flagged, once per
  media type.
"""

from __future__ import annotations

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_response_content, snippet

#: Non-JSON media types that are allowed (file downloads).
_ALLOWED_NON_JSON = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "text/csv",
    }
)

#: Any `image/...` type is allowed too.
_ALLOWED_NON_JSON_PREFIXES = ("image/",)


def _base_type(media_type: str) -> str:
    """`application/JSON; charset=utf-8` becomes `application/json`."""
    return media_type.split(";")[0].strip().lower()


def _is_allowed_non_json(media_type: str) -> bool:
    """True if this non-JSON type is an allowed file download."""
    base = _base_type(media_type)
    return base in _ALLOWED_NON_JSON or base.startswith(_ALLOWED_NON_JSON_PREFIXES)


GOOD_EXAMPLE = """\
responses:
  '200':
    description: OK
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/User'
"""


@register(
    "GDS-004",
    severity=Severity.WARNING,
    clause_id="GDS-004",
    summary="Response bodies must be JSON (application/json or a +json media type)",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each response type that isn't JSON or an allowed download."""
    findings: list[Finding] = []

    # Responses with no body (like 204) are skipped automatically.
    for _response, content in iter_response_content(spec.data):
        # JSON includes `+json` types like `application/problem+json`.
        if content.is_json:
            continue
        if _is_allowed_non_json(content.media_type):
            continue
        findings.append(
            Finding(
                rule_id="GDS-004",
                severity=Severity.WARNING,
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

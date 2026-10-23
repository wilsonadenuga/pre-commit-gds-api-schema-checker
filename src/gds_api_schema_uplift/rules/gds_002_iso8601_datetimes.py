"""GDS-002 — date and time fields must use ISO 8601.

If a string field's name says it holds a date or time (like `createdAt`), its
schema must say `format: date`, `date-time` or `time`. Otherwise `31/12/2025` is
allowed, and nobody can tell if it's day/month or month/day.

The name check splits names into whole words, so `updatedBy` and `validate` don't
count as dates. Only string fields are checked.
"""

from __future__ import annotations

import re
from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import (
    ContentRef,
    SchemaRef,
    as_mapping,
    is_ref,
    iter_component_schemas,
    iter_request_body_content,
    iter_response_content,
    snippet,
    walk_schema,
)

#: The allowed ISO 8601 formats.
ISO_8601_FORMATS = frozenset({"date", "date-time", "time"})

#: Words that mean a field holds a date or time.
TEMPORAL_TOKENS = frozenset(
    {"date", "dates", "datetime", "time", "times", "timestamp", "timestamps"}
)

#: Last words like in `createdAt` or `updated_on`. They only count at the end of a
#: longer name, so a field called just `on` or `at` is ignored.
TEMPORAL_SUFFIX_TOKENS = frozenset({"at", "on"})

#: Words that mean the field is *not* a date, even if it contains "time" or "date",
#: like `timeZone` or `dateFormat`.
NON_TEMPORAL_TOKENS = frozenset(
    {"zone", "zones", "offset", "format", "formats", "duration", "durations", "pattern"}
)

_TOKEN_SPLIT = re.compile(
    r"[^A-Za-z0-9]+"  # separators: _ - . space
    r"|(?<=[a-z0-9])(?=[A-Z])"  # camelCase boundary
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # end of an acronym run: UTCTime -> UTC | Time
)


def tokenise(name: str) -> list[str]:
    """Split a field name into lower-case words::

        tokenise("createdAt")    -> ["created", "at"]
        tokenise("birth_date")   -> ["birth", "date"]
        tokenise("lastSeenUTCTime") -> ["last", "seen", "utc", "time"]
    """
    return [part.lower() for part in _TOKEN_SPLIT.split(name) if part]


def is_temporal_name(name: str | None) -> bool:
    """True if the field name says it holds a date or time."""
    if not name:
        return False
    tokens = tokenise(name)
    if not tokens:
        return False
    if NON_TEMPORAL_TOKENS.intersection(tokens):
        return False
    if TEMPORAL_TOKENS.intersection(tokens):
        return True
    return len(tokens) > 1 and tokens[-1] in TEMPORAL_SUFFIX_TOKENS


def _is_string_typed(schema: dict[str, Any]) -> bool:
    """True if the field is a string, including `type: [string, 'null']`."""
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared == "string"
    if isinstance(declared, (list, tuple)):
        return any(item == "string" for item in declared)
    return False


def _has_iso_8601_format(schema: dict[str, Any]) -> bool:
    declared = schema.get("format")
    return isinstance(declared, str) and declared.strip() in ISO_8601_FORMATS


def _violates(ref: SchemaRef) -> bool:
    """True if this is a date/time-named string with no ISO 8601 format."""
    if is_ref(ref.schema):  # a `$ref` is checked where it points
        return False
    if not is_temporal_name(ref.name):
        return False
    if not _is_string_typed(ref.schema):
        return False
    return not _has_iso_8601_format(ref.schema)


def _content_root(content: ContentRef) -> SchemaRef:
    """The schema inside a request or response body."""
    return SchemaRef(name=None, schema=content.schema, location=content.schema_location)


def _entry_points(data: Any) -> list[SchemaRef]:
    """Where to start looking: request bodies, then responses, then components."""
    roots: list[SchemaRef] = []
    for _op, content in iter_request_body_content(data):
        roots.append(_content_root(content))
    for _response, content in iter_response_content(data):
        roots.append(_content_root(content))
    roots.extend(iter_component_schemas(data))
    return roots


GOOD_EXAMPLE = """\
properties:
  createdAt:
    type: string
    format: date-time
  dateOfBirth:
    type: string
    format: date
"""


@register(
    "GDS-002",
    severity=Severity.WARNING,
    clause_id="GDS-002",
    summary="Dates and times must be ISO 8601 strings (format: date, date-time or time)",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag date/time-named string fields that have no ISO 8601 format."""
    data = as_mapping(spec.data)

    # Keyed by location, so a field reached two ways is only reported once.
    found: dict[str, Finding] = {}

    for root in _entry_points(data):
        for ref in walk_schema(root.schema, root.location, root.name):
            if not _violates(ref):
                continue
            if ref.location in found:
                continue
            field_name = ref.name or "(anonymous)"
            found[ref.location] = Finding(
                rule_id="GDS-002",
                severity=Severity.WARNING,
                location=ref.location,
                snippet=snippet(
                    f"date-named field '{field_name}' has no 'format: date-time' — "
                    f"add it to declare ISO 8601"
                ),
                clause_id="GDS-002",
                rule_type=RuleType.DETERMINISTIC,
            )

    return list(found.values())

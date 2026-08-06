"""GDS-002 — dates and times are ISO 8601 strings.

A string property whose *name* says it carries a date or a time has to say so in the
schema too, with `format: date`, `format: date-time` or `format: time`. Without a
format, `type: string` permits `31/12/2025`, and the consumer has no way to know
which of dd/mm/yyyy or mm/dd/yyyy it is looking at.

The rule is name-driven, so the heuristic is deliberately narrow. M1 requires zero
false positives on the compliant fixture, and a wrong finding here is worse than a
miss: it teaches a developer to stop reading the output. Two consequences:

* names are matched on whole *tokens* after splitting camelCase/snake_case, never on
  substrings — `updatedBy` contains "date" and `validate` contains "date", and
  neither is temporal;
* only `type: string` is in scope. An integer epoch is a different (and arguably
  worse) problem, but it is not this rule's problem.
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

#: The ISO 8601 formats JSON Schema defines for temporal values. One of these must be
#: present on a date/time-named string.
ISO_8601_FORMATS = frozenset({"date", "date-time", "time"})

#: Whole-token names that mark a property as carrying a date or a time.
TEMPORAL_TOKENS = frozenset(
    {"date", "dates", "datetime", "time", "times", "timestamp", "timestamps"}
)

#: Trailing tokens that mark a participle-style temporal name (`createdAt`,
#: `updated_on`). Only meaningful as the *last* token of a multi-token name, so a
#: property called plain `on` or `at` is left alone.
TEMPORAL_SUFFIX_TOKENS = frozenset({"at", "on"})

#: Tokens that veto a temporal match. These co-occur with `time`/`date` on values
#: that are not themselves an instant — a timezone identifier, a display format
#: string, an ISO 8601 duration — and demanding `format: date-time` of them would be
#: wrong.
NON_TEMPORAL_TOKENS = frozenset(
    {"zone", "zones", "offset", "format", "formats", "duration", "durations", "pattern"}
)

_TOKEN_SPLIT = re.compile(
    r"[^A-Za-z0-9]+"  # separators: _ - . space
    r"|(?<=[a-z0-9])(?=[A-Z])"  # camelCase boundary
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # end of an acronym run: UTCTime -> UTC | Time
)


def tokenise(name: str) -> list[str]:
    """Split a property name into lower-cased words.

    Handles snake_case, kebab-case and camelCase/PascalCase, including acronym runs::

        tokenise("createdAt")    -> ["created", "at"]
        tokenise("birth_date")   -> ["birth", "date"]
        tokenise("lastSeenUTCTime") -> ["last", "seen", "utc", "time"]
    """
    return [part.lower() for part in _TOKEN_SPLIT.split(name) if part]


def is_temporal_name(name: str | None) -> bool:
    """True when a property name indicates it carries a date or a time."""
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
    """True when the node declares `type: string`.

    OpenAPI 3.1 allows a type *array* (`type: [string, 'null']` for a nullable
    field), so a list containing "string" counts.
    """
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
    """True when this node is a date/time-named string with no ISO 8601 format."""
    if is_ref(ref.schema):  # a pointer carries no type of its own
        return False
    if not is_temporal_name(ref.name):
        return False
    if not _is_string_typed(ref.schema):
        return False
    return not _has_iso_8601_format(ref.schema)


def _content_root(content: ContentRef) -> SchemaRef:
    """The schema of a media-type entry, as an unnamed walk root."""
    return SchemaRef(name=None, schema=content.schema, location=content.schema_location)


def _entry_points(data: Any) -> list[SchemaRef]:
    """Every schema root the rule walks, in report order.

    Request bodies first, then response bodies, then named components: a finding on
    the operation a developer just edited should come before one in the shared
    component library.
    """
    roots: list[SchemaRef] = []
    for _op, content in iter_request_body_content(data):
        roots.append(_content_root(content))
    for _response, content in iter_response_content(data):
        roots.append(_content_root(content))
    roots.extend(iter_component_schemas(data))
    return roots


@register(
    "GDS-002",
    severity=Severity.WARNING,
    clause_id="GDS-002",
    summary="Dates and times must be ISO 8601 strings (format: date, date-time or time)",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Find date/time-named string properties that declare no ISO 8601 format."""
    data = as_mapping(spec.data)

    # Keyed by location: one schema node can be reached from more than one entry
    # point (a component walked from `components.schemas`, an aliased node walked
    # from two operations), and the developer has one thing to fix either way. dict
    # preserves insertion order, so first-seen order is the report order.
    found: dict[str, Finding] = {}

    for root in _entry_points(data):
        for ref in walk_schema(root.schema, root.location, root.name):
            if not _violates(ref):
                continue
            if ref.location in found:
                continue
            # Actionable snippet: name the property and say what's missing.
            # Fixes an on-screen "{type, pattern, examples}" that looked like
            # a shape hint but told the developer nothing about the violation.
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

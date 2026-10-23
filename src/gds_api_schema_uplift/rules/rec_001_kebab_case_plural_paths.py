"""REC-001 — paths should be lowercase-with-hyphens, plural nouns, with no verbs.

This is a recommendation from Microsoft's REST API Guidelines, not a GDS or NCSC
requirement, so it's only a suggestion.

Three checks on each path, e.g. `/getUserList`:

- Case: no capitals or underscores (`user-preferences`, not `userPreferences`).
- Verbs: no `get`, `create`, `delete`... at the start of a part.
- Plurals: `users`, not `user`. Only a short list of common nouns is checked, to
  avoid false alarms.

One finding per path, listing which checks failed.
"""

from __future__ import annotations

import re

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_paths, jp, snippet

#: A path parameter like `{orderId}`. Skipped, since camelCase is normal there.
_PATH_PARAM = re.compile(r"^\{[^{}]+\}$")

#: A verb followed by a capital letter, like `getUserList` or `deleteAll`.
_VERB_PREFIX = re.compile(r"^(get|create|update|delete|list|fetch)[A-Z]")

#: Common nouns we check for being singular. Kept short to avoid false alarms.
_KNOWN_SINGULARS = frozenset(
    {
        "user",
        "order",
        "product",
        "book",
        "article",
        "comment",
        "event",
        "report",
    }
)

#: Words that are normally singular, like `me`, `health` and `status`. Never flagged.
_AMBIGUOUS_SINGLETONS = frozenset(
    {
        "me",
        "search",
        "data",
        "info",
        "health",
        "status",
        "login",
        "logout",
        "ping",
        "version",
    }
)


def _split_segments(path: str) -> list[str]:
    """The parts of the path between slashes. `/users/` and `/users` give the same result."""
    return [segment for segment in path.split("/") if segment]


def _is_path_parameter(segment: str) -> bool:
    """True when `segment` is entirely a `{name}` path parameter."""
    return bool(_PATH_PARAM.fullmatch(segment))


def _is_version_segment(segment: str) -> bool:
    """True for a version part like `v1` or `V2`. Versions are GDS-003's job, so skip them."""
    return bool(re.fullmatch(r"v\d+(?:\.\d+)?", segment, flags=re.IGNORECASE))


def _has_case_violation(segment: str) -> bool:
    """True if the part has capitals or underscores. Digits, dots and hyphens are fine."""
    return any(ch.isupper() or ch == "_" for ch in segment)


def _has_verb_prefix(segment: str) -> bool:
    """True if the part starts like `getX`, `createX`, `deleteX`, ..."""
    return bool(_VERB_PREFIX.match(segment))


def _is_flaggable_singular(segment: str) -> bool:
    """True if the part is one of our known singular nouns, like `user`."""
    lowered = segment.lower()
    if lowered in _AMBIGUOUS_SINGLETONS:
        return False
    return lowered in _KNOWN_SINGULARS


def _describe(path: str) -> str | None:
    """The finding message for this path, or None if all checks pass."""
    reasons: list[str] = []

    saw_case = False
    saw_verb = False
    singular_hits: list[str] = []

    for segment in _split_segments(path):
        if _is_path_parameter(segment):
            continue
        if _is_version_segment(segment):
            continue
        if not saw_case and _has_case_violation(segment):
            saw_case = True
        if not saw_verb and _has_verb_prefix(segment):
            saw_verb = True
        if _is_flaggable_singular(segment):
            singular_hits.append(segment.lower())

    if saw_case:
        reasons.append("path is not kebab-case (contains uppercase or underscore)")
    if saw_verb:
        reasons.append("verb in path — put verbs in the HTTP method, not the URI")
    if singular_hits:
        # Report each word once, e.g. `/user/{id}/user`.
        seen: set[str] = set()
        uniq = [s for s in singular_hits if not (s in seen or seen.add(s))]
        joined = ", ".join(f"'{s}'" for s in uniq)
        reasons.append(f"singular noun segment ({joined}) — collections are conventionally plural")

    if not reasons:
        return None
    return f"{'; '.join(reasons)}: {path}"


GOOD_EXAMPLE = """\
paths:
  /v1/users:              # kebab-case, plural noun
    get: {...}
  /v1/user-preferences:   # multi-word segments join with a hyphen
    get: {...}
"""


@register(
    "REC-001",
    severity=Severity.SUGGESTION,
    clause_id="REC-001",
    summary="Paths use kebab-case, plural nouns (recommendation)",
    good_example=GOOD_EXAMPLE,
    rule_type=RuleType.DETERMINISTIC,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each path that breaks the naming recommendation."""
    findings: list[Finding] = []
    for path, _path_item, _location in iter_paths(spec.data):
        reason = _describe(path)
        if reason is None:
            continue
        findings.append(
            Finding(
                rule_id="REC-001",
                severity=Severity.SUGGESTION,
                location=jp("paths", path),
                snippet=snippet(reason, limit=200),
                clause_id="REC-001",
                rule_type=RuleType.DETERMINISTIC,
            )
        )
    return findings

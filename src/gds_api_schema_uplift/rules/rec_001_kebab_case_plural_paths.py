"""REC-001 — paths use kebab-case, plural nouns (recommendation).

REC-* rules are conventions, not GDS or NCSC mandates: the finding renders as
explicitly not-GDS-mandated and its severity is `suggestion`. The clause anchor is
the Microsoft REST API Guidelines' URL-structure section, which is treated as an
external reference rather than a source of truth.

Three design decisions worth stating up front, because each of them affects the
finding count on a real spec:

1.  **Detection is deterministic.** The PRD/PLAN language about REC-* "using the
    LLM path" refers to the *fix proposal* — an agent decides between
    `/user` -> `/users` vs `/user` -> `/customers` given the surrounding
    operations — not detection. Detection is a set of surface string checks
    and belongs in the deterministic pass, alongside every other rule in v0.2.
    That is also what the framework wires up (`run_deterministic_pass` is the
    only rule pass; `llm_rules()` is asserted empty by the contract tests).

2.  **One `Finding` per offending path, not per segment or per check.**
    `/getUserList` violates case, verb-in-path and singular-noun conventions all
    at once, but it is one thing to fix, so it is one finding. The snippet lists
    which of the three checks fired, so the developer sees the full picture
    without three noise findings piling up on the same key.

3.  **Conservative singular check.** "Is this segment a singular noun that
    should be plural?" is a judgement call, and false positives on suggestions
    erode trust faster than under-flagging (PRD s11 — suggestions are the
    lowest-severity band precisely because their signal-to-noise ratio is the
    hardest to keep high). So the singular check runs against a *small*
    hand-curated list of English nouns whose plural form is unambiguous
    (`user` -> `users`, `order` -> `orders`, `product` -> `products`, ...), and
    a *safe list* of segments that are conventionally kept singular
    (`me`, `health`, `status`, ...). Words outside both lists are left alone —
    better to under-flag `/kittens` than to nag on `/data` or `/status`.

Location and snippet:

*   Findings are located at the path item itself (`$.paths./the/path`) so a
    Phase 3 fix can rename the key.
*   The snippet is a short, human-facing description of *what* fired, e.g.
    ``"path uses camelCase; consider kebab-case: /getUserList"`` or
    ``"path segment 'user' is singular; consider '/v1/users'"``. It is not a
    machine-readable code — that is what `rule_id` is for.
"""

from __future__ import annotations

import re

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import iter_paths, jp, snippet

#: A whole segment made of `{...}` is a path parameter — its name is a matter of
#: OpenAPI convention (camelCase is idiomatic for parameter names), so we skip it
#: for the case check and for the verb/singular checks. Flagging `{orderId}` for
#: containing an uppercase letter would be a false positive.
_PATH_PARAM = re.compile(r"^\{[^{}]+\}$")

#: A verb prefix at the start of a segment, followed by a capitalised second word
#: (`getUserList`, `deleteAll`) — the classic RPC-style path. Case-sensitive on
#: purpose: `/get` on its own is a common noun (see `/api/get`); the pattern is
#: `verb + Noun` in camelCase.
_VERB_PREFIX = re.compile(r"^(get|create|update|delete|list|fetch)[A-Z]")

#: A hand-curated list of common English resource nouns whose plural form is
#: unambiguous. Kept small on purpose: any expansion is a policy change, not a
#: bug fix. Chosen because they are the words the fixture and the PRD examples
#: actually use, and because none of them have an irregular plural.
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

#: Segments that are conventionally singular even though they *look* like nouns.
#: Excluded from the singular check so the rule does not nag on well-established
#: idioms. `me` is the OAuth-style current-user shorthand; `search` is an action
#: endpoint; `data`, `info`, `health`, `status`, `login`, `logout` are ambiguous
#: (mass nouns or actions rather than collections).
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
    """Return the non-empty `/`-delimited segments of `path`.

    Empty segments (from leading `/` or a trailing `/`) are dropped: `/users/`
    and `/users` produce the same segment list, which is what the "treat a
    trailing slash the same" MVP decision requires.
    """
    return [segment for segment in path.split("/") if segment]


def _is_path_parameter(segment: str) -> bool:
    """True when `segment` is entirely a `{name}` path parameter."""
    return bool(_PATH_PARAM.fullmatch(segment))


def _is_version_segment(segment: str) -> bool:
    """True for a version segment like `v1`, `V2`, `v1.0`.

    The case check would otherwise fire on an uppercase `V2`, but version
    segments are outside REC-001's remit — GDS-003 owns them, and REC-001 must
    not double up.
    """
    return bool(re.fullmatch(r"v\d+(?:\.\d+)?", segment, flags=re.IGNORECASE))


def _has_case_violation(segment: str) -> bool:
    """True when a non-parameter segment is not lowercase-with-hyphens.

    Any uppercase ASCII letter or `_` counts as a violation: this catches
    camelCase, PascalCase, snake_case and SCREAMING_CASE in one pass. Digits,
    dots and hyphens are allowed — they show up in real path segments
    (`/v1`, `/robots.txt`, `/user-preferences`).
    """
    return any(ch.isupper() or ch == "_" for ch in segment)


def _has_verb_prefix(segment: str) -> bool:
    """True when a segment starts `getX`, `createX`, `deleteX`, ..."""
    return bool(_VERB_PREFIX.match(segment))


def _is_flaggable_singular(segment: str) -> bool:
    """True when a segment is a known singular noun with a well-known plural.

    Deliberately narrow: `_KNOWN_SINGULARS` is short, and the segment must
    match one of its entries exactly (lowercased) — no stemming, no
    heuristics. Words in `_AMBIGUOUS_SINGLETONS` never fire even if they
    end up in `_KNOWN_SINGULARS` in future.
    """
    lowered = segment.lower()
    if lowered in _AMBIGUOUS_SINGLETONS:
        return False
    return lowered in _KNOWN_SINGULARS


def _describe(path: str) -> str | None:
    """Build the finding snippet for `path`, or None when nothing fires.

    Runs the three checks in order (case -> verb -> singular) and joins the
    reasons that fired with `; `, so a `/getUserList` reads as
    "camelCase; verb-in-path; singular noun 'user'".
    """
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
        # De-duplicate but keep first-appearance order, so `/user/{id}/user` still
        # reports 'user' once.
        seen: set[str] = set()
        uniq = [s for s in singular_hits if not (s in seen or seen.add(s))]
        joined = ", ".join(f"'{s}'" for s in uniq)
        reasons.append(f"singular noun segment ({joined}) — collections are conventionally plural")

    if not reasons:
        return None
    return f"{'; '.join(reasons)}: {path}"


#: The compliant shape, rendered by the report's "How to fix" section.
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
    """Flag each path entry that breaks the kebab-case/plural-noun convention."""
    findings: list[Finding] = []
    for path, _path_item, _location in iter_paths(spec.data):
        reason = _describe(path)
        if reason is None:
            continue
        findings.append(
            Finding(
                rule_id="REC-001",
                severity=Severity.SUGGESTION,
                # Point at the path item — the key a fix has to rename.
                location=jp("paths", path),
                snippet=snippet(reason),
                clause_id="REC-001",
                rule_type=RuleType.DETERMINISTIC,
            )
        )
    return findings

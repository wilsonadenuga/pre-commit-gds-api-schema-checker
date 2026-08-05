"""System prompt construction and prompt caching.

PRD s9.5: the GDS + NCSC corpus is pinned into the system prompt and cached, rather
than retrieved. There is no vector store at any phase — every rule already knows its
own clause id, so a static lookup is both cheaper and free of retrieval failure
modes.

Caching is a *prefix* match, and the render order is `tools` -> `system` ->
`messages`. So the corpus must sit in `system` (stable across every finding in a
run) and the finding must sit in `messages` (varies per call). Putting the finding
anywhere in the system prompt would invalidate the cache on every single call and
silently turn a 10x cost saving into a 1.25x penalty.
"""

from __future__ import annotations

from typing import Any

from ..standards import Standards

#: Minimum cacheable prefix for the default model family. Below this the API accepts
#: `cache_control` and silently declines to cache — `cache_creation_input_tokens`
#: comes back 0 with no error. Worth surfacing rather than shrugging at, because a
#: run that never caches costs ~10x more than one that does.
MIN_CACHEABLE_TOKENS = 1024

#: Rough characters-per-token for English prose. Only used to warn about the
#: threshold above; the authoritative number comes from `usage` after a real call.
CHARS_PER_TOKEN = 4


ROLE = """\
You are a UK government API standards reviewer. You are given one finding from a \
deterministic rule pass over an OpenAPI 3.x document, together with the clause of \
the GDS or NCSC standard that the finding is anchored to.

Your job is to propose the smallest correct edit that resolves that finding, as an \
RFC 6902 JSON Patch, and to justify it by quoting the clause you were given.
"""

RULES = """\
How to work:

- Call `propose_patch` exactly once. Do not reply with prose instead of a tool call.
- Make the smallest edit that resolves the finding. Do not fix anything else, tidy \
adjacent structure, or add fields the finding did not ask for. Another rule owns \
every other problem in the document.
- Target the location you were given. Prefer `replace` over `remove`+`add`.
- JSON Pointer paths escape `/` as `~1` and `~` as `~0`. An OpenAPI path key such as \
`/v1/users` therefore appears as `~1v1~1users` inside a pointer.
- `clause_quote` must be a verbatim span from the clause text supplied to you. Do \
not paraphrase it, do not summarise it, and do not cite a clause you were not \
given. If the clause text supplied is empty, say so in `rationale` and quote \
nothing — an invented citation is worse than a missing one.
- `rationale` explains why the edit satisfies the clause, in two sentences at most. \
It is read in a terminal by a developer who is mid-commit.
- If you genuinely cannot construct a valid patch for this finding, call \
`propose_patch` with an empty `ops` array and explain why in `rationale`. Do not \
guess at a structure you cannot see.
"""


def corpus_text(standards: Standards) -> str:
    """Render the whole clause corpus as stable, cacheable text.

    Ordering is by clause id so the bytes are deterministic — an unstable ordering
    here would change the prefix on every run and defeat caching.
    """
    if len(standards) == 0:
        return (
            "REFERENCE STANDARDS: (none loaded)\n\n"
            "The standards corpus is empty in this build, so no clause text is "
            "available to quote."
        )

    lines = ["REFERENCE STANDARDS", ""]
    for clause_id in sorted(standards.clause_ids):
        clause = standards.resolve(clause_id)
        lines += [
            f"## {clause.clause_id} — {clause.section}",
            f"authority: {clause.authority.value}",
            f"source: {clause.url}",
            "",
            clause.text.strip(),
            "",
        ]
    return "\n".join(lines)


def build_system_blocks(standards: Standards) -> list[dict[str, Any]]:
    """Build the `system` parameter as cache-annotated text blocks.

    One `cache_control` breakpoint, on the last block, so the whole system prompt
    (and the tool definitions, which render before it) are cached together. There is
    deliberately nothing per-finding in here.
    """
    return [
        {"type": "text", "text": ROLE},
        {"type": "text", "text": RULES},
        {
            "type": "text",
            "text": corpus_text(standards),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def estimated_system_tokens(blocks: list[dict[str, Any]]) -> int:
    """Crude token estimate for the caching-threshold warning."""
    return sum(len(block.get("text", "")) for block in blocks) // CHARS_PER_TOKEN


def cache_warning(blocks: list[dict[str, Any]]) -> str | None:
    """Warn when the system prompt is too small to be cacheable.

    Returns None when the prefix looks large enough. This is a heuristic on
    characters; `CostTracker` reports the truth from `usage` once a call has run.
    """
    estimate = estimated_system_tokens(blocks)
    if estimate >= MIN_CACHEABLE_TOKENS:
        return None
    return (
        f"System prompt is roughly {estimate} tokens, below the "
        f"{MIN_CACHEABLE_TOKENS}-token minimum cacheable prefix — prompt caching "
        f"will not engage and each call pays full input price. This is expected "
        f"until the standards corpus is authored."
    )


def finding_message(
    *,
    rule_id: str,
    severity: str,
    location: str,
    snippet: str,
    rule_summary: str,
    clause_id: str,
    clause_text: str,
    clause_url: str,
    spec_excerpt: str,
) -> str:
    """The per-call user message.

    Everything that varies per finding lives here, after the cached prefix. The
    clause text is supplied directly rather than made retrievable, because the rule
    already declared its clause id at registration — see `tools.retrieve_clause` for
    the one case where lookup is still useful.
    """
    return (
        f"FINDING\n"
        f"rule: {rule_id} ({severity})\n"
        f"rule checks: {rule_summary}\n"
        f"location: {location}\n"
        f"offending value: {snippet}\n\n"
        f"ANCHORING CLAUSE\n"
        f"clause id: {clause_id}\n"
        f"source: {clause_url}\n"
        f"clause text:\n{clause_text or '(no clause text available)'}\n\n"
        f"SPEC EXCERPT\n"
        f"```yaml\n{spec_excerpt}\n```\n\n"
        f"Propose the smallest RFC 6902 patch that resolves this finding."
    )

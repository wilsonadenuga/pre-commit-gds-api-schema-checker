"""Look up the source-file line and column for a JSONPath into a loaded spec.

`ruamel.yaml` in round-trip mode attaches an `lc` (line-column) attribute to
every mapping and sequence node. This module walks a JSONPath string against
the loaded spec and returns the 1-indexed `(line, column)` of the final key —
so the CLI can show findings as `broken.yaml:42 → GDS-002` and terminal
emulators + IDEs make them clickable.

The JSONPath format we parse is the one emitted by our own traversal helpers:

    $.paths['/users'].get.responses['200'].content['application/json']

That is:

- Root marker `$`
- Dot-separated identifiers
- Bracket-quoted strings for keys that need escaping (paths, media types)
- Bracket-quoted integers for list indices (e.g. `servers[0]`)

We deliberately do not support full JSONPath — filters, wildcards, unions.
The rules never emit those, so parsing them would be surface area we do not
own.
"""

from __future__ import annotations

from typing import Any


def _parse_jsonpath(jsonpath: str) -> list[str | int]:
    """Split a JSONPath into a list of key/index segments.

    Returns an empty list for the root (`$`). Unrecognised syntax raises
    `ValueError` — a location that our own rules could not emit means either
    a bug in a rule or a hand-crafted string, and both deserve to fail loudly.
    """
    if not jsonpath.startswith("$"):
        raise ValueError(f"JSONPath must start with $: {jsonpath!r}")
    body = jsonpath[1:]
    parts: list[str | int] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == ".":
            i += 1
            start = i
            while i < len(body) and body[i] not in ".[":
                i += 1
            if i > start:
                parts.append(body[start:i])
        elif c == "[":
            i += 1
            if i >= len(body):
                raise ValueError(f"unterminated bracket in {jsonpath!r}")
            if body[i] == "'":
                # ['some/key']
                end = body.find("'", i + 1)
                if end == -1 or end + 1 >= len(body) or body[end + 1] != "]":
                    raise ValueError(f"unterminated quoted key in {jsonpath!r}")
                parts.append(body[i + 1 : end])
                i = end + 2
            else:
                # [123]
                end = body.find("]", i)
                if end == -1:
                    raise ValueError(f"unterminated integer index in {jsonpath!r}")
                try:
                    parts.append(int(body[i:end]))
                except ValueError as exc:
                    raise ValueError(
                        f"non-integer bracket index in {jsonpath!r}: {body[i:end]!r}"
                    ) from exc
                i = end + 1
        else:
            raise ValueError(f"unexpected character at {i}: {jsonpath!r}")
    return parts


def resolve_line(root: Any, jsonpath: str) -> tuple[int | None, int | None]:
    """Return the 1-indexed source (line, column) for the target of a JSONPath.

    Returns `(None, None)` when:

    - The JSONPath does not resolve (a mid-path key is missing).
    - The final container has no `lc` info attached (a non-ruamel dict, or
      a synthetic mapping built at runtime).
    - The parse fails for any reason.

    Never raises. A rule whose location is malformed is a bug we surface as
    a missing line rather than as a crash mid-report.
    """
    try:
        parts = _parse_jsonpath(jsonpath)
    except ValueError:
        return (None, None)

    if not parts:
        # `$` — the root has no containing node whose lc.data would hold it.
        return (None, None)

    # Walk to the parent of the final segment. `node` ends up as the
    # container whose `lc` holds line info for the final key/index.
    node = root
    for part in parts[:-1]:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            return (None, None)

    lc = getattr(node, "lc", None)
    if lc is None:
        return (None, None)

    final = parts[-1]

    # Mapping key lookup: lc.data is {key: [key_line, key_col, value_line, value_col]}
    if isinstance(node, dict):
        data = getattr(lc, "data", None)
        if not data:
            return (None, None)
        entry = data.get(final)
        if entry is None:
            return (None, None)
        # We report the KEY position — that's what a developer's editor lands
        # on when they jump to line:col, and it's the line they'd start reading
        # from to understand the finding. 0-indexed → 1-indexed for humans.
        return (entry[0] + 1, entry[1] + 1)

    # Sequence lookup: lc.item(i) returns [line, col] for item i.
    if isinstance(node, list):
        if not isinstance(final, int):
            return (None, None)
        try:
            entry = lc.item(final)
        except (KeyError, IndexError, TypeError):
            return (None, None)
        if entry is None:
            return (None, None)
        return (entry[0] + 1, entry[1] + 1)

    return (None, None)

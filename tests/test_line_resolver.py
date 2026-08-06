"""Unit tests for the JSONPath → (line, column) resolver.

The resolver takes a ruamel-parsed document and a JSONPath string, and returns
the 1-indexed source position of the target. It never raises — an unresolvable
path returns `(None, None)` — but the tests here pin every path shape our own
rules emit, so a rule that started emitting an unparseable location would show
up as an error test rather than as a silent `–` in the report.
"""

from __future__ import annotations

import pytest
from ruamel.yaml import YAML

from gds_api_schema_uplift.line_resolver import _parse_jsonpath, resolve_line


def _load(source: str):
    """Parse a YAML string with the same round-trip settings the loader uses.

    Using a plain `YAML()` (not `YAML(typ='safe')`) is what keeps the `lc`
    attribute populated on every mapping and sequence node.
    """
    return YAML().load(source)


# --- JSONPath parser --------------------------------------------------------


def test_parses_dot_identifiers():
    assert _parse_jsonpath("$.info.title") == ["info", "title"]


def test_parses_bracket_quoted_keys():
    """Path keys with slashes are the reason bracket-quoting exists."""
    assert _parse_jsonpath("$.paths['/v1/users']") == ["paths", "/v1/users"]


def test_parses_integer_indices():
    assert _parse_jsonpath("$.servers[0].url") == ["servers", 0, "url"]


def test_parses_mixed_paths():
    parts = _parse_jsonpath(
        "$.paths['/users'].get.responses['200'].content['application/json']"
    )
    assert parts == [
        "paths",
        "/users",
        "get",
        "responses",
        "200",
        "content",
        "application/json",
    ]


def test_root_alone_parses_to_empty():
    assert _parse_jsonpath("$") == []


@pytest.mark.parametrize(
    "malformed",
    [
        "no-dollar",  # missing root
        "$.paths['unterminated",  # unterminated quoted key
        "$.paths[abc]",  # non-integer bracket
        "$.paths[",  # unterminated bracket
        "$@wtf",  # unexpected character
    ],
)
def test_parser_raises_on_malformed_input(malformed):
    """The parser is strict — a rule that emits nonsense fails loudly.

    Callers of `resolve_line` catch this and downgrade to `(None, None)`, so
    end-users never see a stack trace, but the parser itself refuses to
    guess.
    """
    with pytest.raises(ValueError):
        _parse_jsonpath(malformed)


# --- resolver walking the real thing ---------------------------------------


def test_returns_line_for_top_level_key():
    """The most common lookup: `$.info.title` → the line of `title:`."""
    doc = _load(
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: Foo\n"
        "  version: '1'\n"
    )
    line, col = resolve_line(doc, "$.info.title")
    assert line == 3  # 1-indexed


def test_returns_line_for_bracket_quoted_path():
    doc = _load(
        "paths:\n"
        "  /v1/users:\n"
        "    get: {}\n"
    )
    line, _col = resolve_line(doc, "$.paths['/v1/users']")
    assert line == 2


def test_returns_line_for_sequence_index():
    doc = _load(
        "servers:\n"
        "  - url: https://api.example.gov.uk\n"
        "  - url: https://api.staging.gov.uk\n"
    )
    line, _col = resolve_line(doc, "$.servers[1]")
    assert line == 3


def test_returns_line_for_deeply_nested_key():
    doc = _load(
        "paths:\n"
        "  /users:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          content:\n"
        "            application/json:\n"
        "              schema: {}\n"
    )
    line, _col = resolve_line(
        doc,
        "$.paths['/users'].get.responses['200'].content['application/json']",
    )
    assert line == 7


def test_column_is_reported_1_indexed():
    """Column info matters for editors that jump to `file:line:col`."""
    doc = _load("info:\n  title: Foo\n")
    _line, col = resolve_line(doc, "$.info.title")
    assert col == 3  # `title:` sits at column 2 (0-indexed) → 3


# --- resolver's honest failure modes ---------------------------------------


def test_missing_key_returns_none():
    doc = _load("info:\n  title: Foo\n")
    assert resolve_line(doc, "$.info.description") == (None, None)


def test_missing_intermediate_key_returns_none():
    doc = _load("info:\n  title: Foo\n")
    assert resolve_line(doc, "$.paths['/x'].get") == (None, None)


def test_out_of_range_index_returns_none():
    doc = _load("servers:\n  - url: x\n")
    assert resolve_line(doc, "$.servers[7]") == (None, None)


def test_plain_dict_without_lc_returns_none():
    """A hand-built dict has no `lc` attribute — the resolver stays silent."""
    plain = {"info": {"title": "Foo"}}
    assert resolve_line(plain, "$.info.title") == (None, None)


def test_root_path_returns_none():
    """`$` has no containing node whose lc.data would hold it."""
    doc = _load("info:\n  title: Foo\n")
    assert resolve_line(doc, "$") == (None, None)


def test_malformed_jsonpath_returns_none_without_raising():
    doc = _load("info:\n  title: Foo\n")
    assert resolve_line(doc, "not-a-jsonpath") == (None, None)


def test_integer_index_into_a_mapping_returns_none():
    """`[0]` on a mapping is nonsense, but must not crash."""
    doc = _load("info:\n  title: Foo\n")
    assert resolve_line(doc, "$.info[0]") == (None, None)


def test_string_key_into_a_sequence_returns_none():
    """`.foo` on a list is nonsense, but must not crash."""
    doc = _load("servers:\n  - url: x\n")
    assert resolve_line(doc, "$.servers.foo") == (None, None)


# --- integration: every rule's location resolves against the broken fixture --


def test_every_deterministic_finding_on_broken_yaml_has_a_line():
    """The end-to-end guarantee for the report UX.

    A finding whose resolver returns None would render as a dim `–` in the
    Line column — acceptable as a fallback but a bug worth catching if it
    ever happens on the committed fixture, which is the demo path.
    """
    from example_specs import BROKEN_SPEC

    from gds_api_schema_uplift.loader import load_spec
    from gds_api_schema_uplift.rules import run_deterministic_pass

    findings = run_deterministic_pass(load_spec(BROKEN_SPEC))
    without_line = [f.rule_id for f in findings if f.line is None]
    assert without_line == [], (
        f"Findings without a resolved line: {without_line}. "
        f"Either the rule emitted an unparseable JSONPath or the resolver "
        f"regressed."
    )

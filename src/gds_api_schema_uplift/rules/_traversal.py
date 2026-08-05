"""Spec traversal helpers shared by every rule.

Rules must not hand-roll traversal or hand-build JSONPath strings. Findings from
different rules are compared, deduplicated and rendered together, so `location` has
to be produced one way — and `location` is what a Phase 3 patch targets.

Every iterator here is tolerant of missing or wrongly-typed nodes: a spec that is
structurally odd should yield fewer findings, never raise. Schema-level validity is
the version gate's job, not each rule's.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

#: Keys under a Path Item that are operations. Anything else there (`parameters`,
#: `summary`, `$ref`, ...) is not.
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _seg(key: str | int) -> str:
    if isinstance(key, bool):  # bool is an int subclass; guard before the int branch
        return f"['{key}']"
    if isinstance(key, int):
        return f"[{key}]"
    key = str(key)
    if _IDENT.fullmatch(key):
        return f".{key}"
    return "['" + key.replace("\\", "\\\\").replace("'", "\\'") + "']"


def jp(*parts: str | int) -> str:
    """Build a JSONPath from path segments.

    Identifier-safe keys use dot notation and everything else uses quoted brackets,
    so paths, media types and status codes render readably::

        jp("paths", "/v1/users", "get", "responses", "200")
        -> "$.paths['/v1/users'].get.responses['200']"
    """
    return "$" + "".join(_seg(p) for p in parts)


def child(location: str, *parts: str | int) -> str:
    """Extend an existing JSONPath with further segments."""
    return location + "".join(_seg(p) for p in parts)


def snippet(value: Any, limit: int = 120) -> str:
    """Render a short, single-line excerpt of a spec node for the report.

    Mappings and sequences are summarised by shape rather than dumped, because a
    snippet is meant to orient the reader, not reproduce the document.
    """
    if isinstance(value, dict):
        keys = ", ".join(str(k) for k in list(value)[:6])
        more = ", ..." if len(value) > 6 else ""
        text = "{" + keys + more + "}"
    elif isinstance(value, (list, tuple)):
        text = f"[{len(value)} item(s)]"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def as_mapping(value: Any) -> dict[str, Any]:
    """Return `value` when it is a mapping, else an empty dict."""
    return value if isinstance(value, dict) else {}


def as_sequence(value: Any) -> list[Any]:
    """Return `value` when it is a list/tuple, else an empty list."""
    return list(value) if isinstance(value, (list, tuple)) else []


@dataclass(frozen=True, slots=True)
class OperationRef:
    """One operation, with its JSONPath and the Path Item it belongs to."""

    path: str
    method: str
    operation: dict[str, Any]
    path_item: dict[str, Any]
    location: str

    @property
    def path_location(self) -> str:
        return jp("paths", self.path)

    @property
    def label(self) -> str:
        return f"{self.method.upper()} {self.path}"


@dataclass(frozen=True, slots=True)
class ResponseRef:
    """One response on one operation."""

    op: OperationRef
    status: str
    response: dict[str, Any]
    location: str

    @property
    def status_int(self) -> int | None:
        try:
            return int(self.status)
        except (TypeError, ValueError):
            return None

    @property
    def is_error(self) -> bool:
        code = self.status_int
        if code is not None:
            return code >= 400
        # `4XX` / `5XX` range keys, per OpenAPI.
        return str(self.status).upper().startswith(("4", "5"))


@dataclass(frozen=True, slots=True)
class ContentRef:
    """One media-type entry inside a `content` mapping."""

    media_type: str
    media_object: dict[str, Any]
    location: str

    @property
    def schema(self) -> dict[str, Any]:
        return as_mapping(self.media_object.get("schema"))

    @property
    def schema_location(self) -> str:
        return child(self.location, "schema")

    @property
    def is_json(self) -> bool:
        """True for `application/json` and any `+json` structured suffix."""
        base = self.media_type.split(";")[0].strip().lower()
        return base == "application/json" or base.endswith("+json")

    @property
    def is_problem_json(self) -> bool:
        base = self.media_type.split(";")[0].strip().lower()
        return base == "application/problem+json"


@dataclass(frozen=True, slots=True)
class SchemaRef:
    """A schema node reached during a recursive walk."""

    name: str | None
    schema: dict[str, Any]
    location: str


def iter_paths(data: Any) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Yield `(path, path_item, location)` for each entry under `paths`."""
    for path, path_item in as_mapping(as_mapping(data).get("paths")).items():
        if isinstance(path_item, dict):
            yield str(path), path_item, jp("paths", str(path))


def iter_operations(data: Any) -> Iterator[OperationRef]:
    """Yield every operation in the document, in declaration order."""
    for path, path_item, path_location in iter_paths(data):
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict):
                yield OperationRef(
                    path=path,
                    method=method,
                    operation=operation,
                    path_item=path_item,
                    location=child(path_location, method),
                )


def iter_responses(data: Any) -> Iterator[ResponseRef]:
    """Yield every response across every operation."""
    for op in iter_operations(data):
        responses = as_mapping(op.operation.get("responses"))
        for status, response in responses.items():
            if isinstance(response, dict):
                yield ResponseRef(
                    op=op,
                    status=str(status),
                    response=response,
                    location=child(op.location, "responses", str(status)),
                )


def iter_content(container: Any, container_location: str) -> Iterator[ContentRef]:
    """Yield each media-type entry of a node that has a `content` mapping."""
    content = as_mapping(as_mapping(container).get("content"))
    for media_type, media_object in content.items():
        if isinstance(media_object, dict):
            yield ContentRef(
                media_type=str(media_type),
                media_object=media_object,
                location=child(container_location, "content", str(media_type)),
            )


def iter_response_content(data: Any) -> Iterator[tuple[ResponseRef, ContentRef]]:
    """Yield `(response, content)` for every response body media type."""
    for response in iter_responses(data):
        for content in iter_content(response.response, response.location):
            yield response, content


def iter_request_body_content(data: Any) -> Iterator[tuple[OperationRef, ContentRef]]:
    """Yield `(operation, content)` for every request body media type."""
    for op in iter_operations(data):
        request_body = op.operation.get("requestBody")
        if isinstance(request_body, dict):
            body_location = child(op.location, "requestBody")
            for content in iter_content(request_body, body_location):
                yield op, content


def iter_component_schemas(data: Any) -> Iterator[SchemaRef]:
    """Yield each named schema under `components.schemas`."""
    components = as_mapping(as_mapping(data).get("components"))
    for name, schema in as_mapping(components.get("schemas")).items():
        if isinstance(schema, dict):
            yield SchemaRef(
                name=str(name),
                schema=schema,
                location=jp("components", "schemas", str(name)),
            )


def walk_schema(
    schema: Any,
    location: str,
    name: str | None = None,
    _seen: set[int] | None = None,
) -> Iterator[SchemaRef]:
    """Recursively yield a schema and its subschemas.

    Descends `properties`, `items`, `additionalProperties`, and the `allOf`/`anyOf`/
    `oneOf` combinators. `$ref` nodes are yielded but not followed — resolving refs
    would make a rule's finding count depend on how often a schema is reused, which
    breaks the one-violation-one-finding property the fixtures rely on.
    """
    if not isinstance(schema, dict):
        return
    seen = _seen if _seen is not None else set()
    if id(schema) in seen:  # defends against a self-referential round-trip structure
        return
    seen.add(id(schema))

    yield SchemaRef(name=name, schema=schema, location=location)

    for prop_name, prop in as_mapping(schema.get("properties")).items():
        yield from walk_schema(
            prop, child(location, "properties", str(prop_name)), str(prop_name), seen
        )

    items = schema.get("items")
    if isinstance(items, dict):
        yield from walk_schema(items, child(location, "items"), name, seen)

    extra = schema.get("additionalProperties")
    if isinstance(extra, dict):
        yield from walk_schema(extra, child(location, "additionalProperties"), name, seen)

    for combinator in ("allOf", "anyOf", "oneOf"):
        for index, member in enumerate(as_sequence(schema.get(combinator))):
            if isinstance(member, dict):
                yield from walk_schema(
                    member, child(location, combinator, index), name, seen
                )


def is_ref(schema: Any) -> bool:
    """True when a node is a `$ref` pointer rather than an inline schema."""
    return isinstance(schema, dict) and "$ref" in schema

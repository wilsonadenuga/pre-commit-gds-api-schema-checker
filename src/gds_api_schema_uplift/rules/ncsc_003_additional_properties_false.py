"""NCSC-003 — request bodies set `additionalProperties: false`.

NCSC §4 (Input validation — Schema validation) says a spec should

    "ensure that an attacker is not sending extra clauses (key value pairs) that
    are not expected."

In JSON Schema that guarantee is expressed by `additionalProperties: false` at the
root of the accepted body: any member not named in `properties` is rejected. A
schema that omits `additionalProperties`, or sets it to `true` (or to any object,
which means "extra properties are allowed and must match this sub-schema"), does
not enforce the guarantee.

Scope decisions, all of which change the finding count and so are pinned by tests:

*   **Root only.** Only the *root* of each request-body schema is checked. NCSC's
    language is about the accepted body as a whole; a rule that recursively
    demanded `additionalProperties: false` on every nested object schema would be
    a much bigger, more contentious change and belongs to a later phase. So a body
    with `additionalProperties: false` at the root but a nested `address` object
    that omits it is compliant here.

*   **One level of `$ref` following.** If the request-body schema is
    `{"$ref": "#/components/schemas/UserRequest"}` we resolve into
    `components.schemas.UserRequest` and check *its* `additionalProperties`.
    Following further refs, external files, or anything other than a local
    `#/components/schemas/<Name>` pointer is out of scope: unknown targets are
    treated as compliant so we do not double-report a spec that is simply broken.

*   **Compositions are flagged at the root.** If the body's root schema is
    `allOf`/`oneOf`/`anyOf` we do *not* descend into every branch trying to prove
    at least one branch is strict. That reasoning is subtle enough to belong to
    Phase 8; for MVP we flag the composition itself as missing
    `additionalProperties` at the root.

*   **Scalar bodies pass.** `additionalProperties` only applies to object
    schemas. A body declared as `type: string` (or array, or a numeric scalar)
    cannot have extra keys, so the rule stays silent — even if the schema happens
    to also carry `additionalProperties: false`, the property is inapplicable.

*   **Only JSON media types.** `application/json` and any structured
    `application/*+json` subtype (`application/vnd.dept.user+json`). Non-JSON
    request bodies (form-encoded uploads, multipart, XML) are out of scope: the
    body isn't a JSON schema at the media-type root, so this rule has nothing to
    say.

*   **Missing pieces are not violations.** An operation with no `requestBody`
    (GET/DELETE/HEAD), a `requestBody` with no `content`, an empty `content`
    block, a media-type entry with no `schema`, or an unresolvable `$ref` all
    yield zero findings. "Undocumented body" is a different rule's concern.

One finding per offending request-body schema, located at the schema node the fix
would touch, so a Phase 3 patch can insert `additionalProperties: false` at that
exact JSONPath.
"""

from __future__ import annotations

from typing import Any

from ..contracts import Finding, RuleType, Severity
from ..loader import LoadedSpec
from ._registry import register
from ._traversal import (
    as_mapping,
    child,
    iter_operations,
    iter_content,
    snippet,
)

#: Prefix of the only `$ref` form we resolve for body schemas.
_LOCAL_SCHEMA_PREFIX = "#/components/schemas/"

#: Prefix of the only `$ref` form we resolve for operation-level `requestBody` refs.
_LOCAL_REQUEST_BODY_PREFIX = "#/components/requestBodies/"


def _is_json_media_type(media_type: str) -> bool:
    """True for `application/json` and any `+json` structured suffix."""
    base = media_type.split(";")[0].strip().lower()
    return base == "application/json" or base.endswith("+json")


def _resolve_body_schema(
    schema: dict[str, Any], data: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Follow at most one local `#/components/schemas/<Name>` pointer.

    Returns `(resolved_schema, resolved_location)`. The location is the JSONPath
    of the resolved schema inside `components.schemas`, so a finding can point at
    the shared definition rather than at the ref site. When the pointer is not a
    local schema ref, or the name is dangling, returns `(None, None)` — the
    caller treats that as "unknown, do not flag".
    """
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema, None
    if not ref.startswith(_LOCAL_SCHEMA_PREFIX):
        return None, None
    name = ref[len(_LOCAL_SCHEMA_PREFIX) :]
    schemas = as_mapping(
        as_mapping(as_mapping(data).get("components")).get("schemas")
    )
    target = schemas.get(name)
    if not isinstance(target, dict):
        return None, None
    location = f"$.components.schemas.{name}" if name.isidentifier() else (
        "$.components.schemas['" + name.replace("\\", "\\\\").replace("'", "\\'") + "']"
    )
    return target, location


def _resolve_request_body(
    request_body: dict[str, Any], data: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Follow a local `#/components/requestBodies/<Name>` pointer, once.

    Returns `(resolved_request_body, resolved_location)` or `(request_body, None)`
    if the node is not a `$ref`. A dangling or non-local `$ref` returns
    `(None, None)`.
    """
    ref = request_body.get("$ref")
    if not isinstance(ref, str):
        return request_body, None
    if not ref.startswith(_LOCAL_REQUEST_BODY_PREFIX):
        return None, None
    name = ref[len(_LOCAL_REQUEST_BODY_PREFIX) :]
    request_bodies = as_mapping(
        as_mapping(as_mapping(data).get("components")).get("requestBodies")
    )
    target = request_bodies.get(name)
    if not isinstance(target, dict):
        return None, None
    if name.isidentifier():
        location = f"$.components.requestBodies.{name}"
    else:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        location = "$.components.requestBodies['" + safe + "']"
    return target, location


def _is_object_schema(schema: dict[str, Any]) -> bool:
    """True when a schema describes an object (and so can carry extra keys).

    A missing `type` combined with `properties` is treated as an object — many
    real-world specs elide `type: object` when `properties` is present, and JSON
    Schema itself is lenient about this.
    """
    schema_type = schema.get("type")
    if schema_type == "object":
        return True
    if isinstance(schema_type, list) and "object" in schema_type:
        return True
    if schema_type is None and isinstance(schema.get("properties"), dict):
        return True
    return False


def _is_composition(schema: dict[str, Any]) -> bool:
    """True when the root uses `allOf`/`oneOf`/`anyOf`.

    We flag the composition itself rather than descending, per the module
    docstring.
    """
    return any(key in schema for key in ("allOf", "oneOf", "anyOf"))


def _has_additional_properties_false(schema: dict[str, Any]) -> bool:
    """True when the schema pins `additionalProperties` to the literal `False`.

    `additionalProperties: true` and `additionalProperties: {any object}` both
    permit extra keys, so both fail this check. Only the literal boolean `False`
    passes.
    """
    return schema.get("additionalProperties") is False


@register(
    "NCSC-003",
    severity=Severity.WARNING,
    clause_id="NCSC-003",
    summary="Request bodies set additionalProperties: false",
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each JSON request-body root schema that permits extra properties."""
    data = spec.data
    findings: list[Finding] = []

    for op in iter_operations(data):
        raw_request_body = op.operation.get("requestBody")
        if not isinstance(raw_request_body, dict):
            continue

        # The location the *fix* would target: the request body as it appears on
        # the operation, unless the operation ref-points at a shared body under
        # `components.requestBodies`, in which case we prefer the shared node.
        request_body_location = child(op.location, "requestBody")
        request_body, resolved_body_location = _resolve_request_body(
            raw_request_body, data
        )
        if request_body is None:
            # Dangling or external `$ref` — leave it to a validator.
            continue
        if resolved_body_location is not None:
            request_body_location = resolved_body_location

        for content in iter_content(request_body, request_body_location):
            if not _is_json_media_type(content.media_type):
                continue

            schema_node = content.media_object.get("schema")
            if not isinstance(schema_node, dict):
                # No schema on this media type — a different rule's concern.
                continue

            schema_location = child(content.location, "schema")
            schema, resolved_schema_location = _resolve_body_schema(
                schema_node, data
            )
            if schema is None:
                # Non-local, external, or dangling `$ref`.
                continue
            if resolved_schema_location is not None:
                schema_location = resolved_schema_location

            # Compositions at the root: flag without descending.
            if _is_composition(schema) and not _has_additional_properties_false(schema):
                findings.append(
                    Finding(
                        rule_id="NCSC-003",
                        severity=Severity.WARNING,
                        location=schema_location,
                        snippet=snippet(
                            "root uses "
                            + next(k for k in ("allOf", "oneOf", "anyOf") if k in schema)
                            + "; additionalProperties: false not set at root"
                        ),
                        clause_id="NCSC-003",
                        rule_type=RuleType.DETERMINISTIC,
                    )
                )
                continue

            # Scalar bodies cannot carry extra keys, so this rule does not apply.
            if not _is_object_schema(schema):
                continue

            if _has_additional_properties_false(schema):
                continue

            raw = schema.get("additionalProperties")
            if raw is None:
                reason = "missing additionalProperties: false at request-body root"
            elif raw is True:
                reason = "additionalProperties: true permits extra keys"
            else:
                reason = "additionalProperties is a schema, which permits extra keys"

            findings.append(
                Finding(
                    rule_id="NCSC-003",
                    severity=Severity.WARNING,
                    location=schema_location,
                    snippet=snippet(reason),
                    clause_id="NCSC-003",
                    rule_type=RuleType.DETERMINISTIC,
                )
            )

    return findings

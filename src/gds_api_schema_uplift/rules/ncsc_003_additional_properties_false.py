"""NCSC-003 — request bodies must reject unexpected fields.

NCSC says to make sure an attacker can't send extra fields you didn't expect. In
JSON Schema that means `additionalProperties: false` on the request body, so any
field not listed in `properties` is rejected.

- Only the top level of each JSON request body is checked, not nested objects.
- A `$ref` to `#/components/schemas/...` is followed once.
- `allOf` / `oneOf` / `anyOf` at the top level is flagged as it is.
- Non-object bodies (a string, a list, a number) are fine.
- Missing bodies, missing schemas and `$ref`s we can't follow are not flagged.
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

#: The only kind of schema `$ref` we follow.
_LOCAL_SCHEMA_PREFIX = "#/components/schemas/"

#: The only kind of request body `$ref` we follow.
_LOCAL_REQUEST_BODY_PREFIX = "#/components/requestBodies/"


def _is_json_media_type(media_type: str) -> bool:
    """True for `application/json` and any `+json` type."""
    base = media_type.split(";")[0].strip().lower()
    return base == "application/json" or base.endswith("+json")


def _resolve_body_schema(
    schema: dict[str, Any], data: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Follow one `#/components/schemas/<Name>` link.

    Returns the schema and its location, or `(None, None)` if it can't be followed.
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
    """Follow one `#/components/requestBodies/<Name>` link.

    Returns the body and its location, `(body, None)` if it isn't a link, or
    `(None, None)` if the link can't be followed.
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
    """True if the schema is an object (has `type: object`, or has `properties`)."""
    schema_type = schema.get("type")
    if schema_type == "object":
        return True
    if isinstance(schema_type, list) and "object" in schema_type:
        return True
    if schema_type is None and isinstance(schema.get("properties"), dict):
        return True
    return False


def _is_composition(schema: dict[str, Any]) -> bool:
    """True if the top level uses `allOf`, `oneOf` or `anyOf`."""
    return any(key in schema for key in ("allOf", "oneOf", "anyOf"))


def _has_additional_properties_false(schema: dict[str, Any]) -> bool:
    """True only if `additionalProperties` is exactly `false`."""
    return schema.get("additionalProperties") is False


GOOD_EXAMPLE = """\
requestBody:
  required: true
  content:
    application/json:
      schema:
        type: object
        additionalProperties: false
        properties:
          name: {type: string}
"""


@register(
    "NCSC-003",
    severity=Severity.WARNING,
    clause_id="NCSC-003",
    summary="Request bodies set additionalProperties: false",
    good_example=GOOD_EXAMPLE,
)
def check(spec: LoadedSpec) -> list[Finding]:
    """Flag each JSON request body that allows extra fields."""
    data = spec.data
    findings: list[Finding] = []

    for op in iter_operations(data):
        raw_request_body = op.operation.get("requestBody")
        if not isinstance(raw_request_body, dict):
            continue

        request_body_location = child(op.location, "requestBody")
        request_body, resolved_body_location = _resolve_request_body(
            raw_request_body, data
        )
        if request_body is None:
            # A `$ref` we can't follow: skip it.
            continue
        if resolved_body_location is not None:
            request_body_location = resolved_body_location

        for content in iter_content(request_body, request_body_location):
            if not _is_json_media_type(content.media_type):
                continue

            schema_node = content.media_object.get("schema")
            if not isinstance(schema_node, dict):
                continue

            schema_location = child(content.location, "schema")
            schema, resolved_schema_location = _resolve_body_schema(
                schema_node, data
            )
            if schema is None:
                # A `$ref` we can't follow: skip it.
                continue
            if resolved_schema_location is not None:
                schema_location = resolved_schema_location

            # `allOf` / `oneOf` / `anyOf`: flag it without looking inside.
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

            # Not an object, so it can't have extra fields.
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

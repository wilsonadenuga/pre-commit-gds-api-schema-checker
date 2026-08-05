"""Spec loading with comment-preserving round-trip.

`ruamel.yaml` in round-trip mode is what makes req 9 achievable — we write patches
back into a developer's own file, so comments and key order must survive. JSON is
accepted too and round-trips through the same code path (YAML 1.2 is a JSON
superset).

The OpenAPI *version gate* (3.1 clean, 3.0 with a note, 2.0 rejected — PRD s7.3) is
Phase 1 work. Phase 0 only detects and reports the version so the CLI can load both
fixtures.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


class SpecLoadError(ValueError):
    """Raised when a spec cannot be parsed or is not an OpenAPI document."""


def _round_trip_yaml() -> YAML:
    yaml = YAML()  # round-trip mode
    yaml.preserve_quotes = True
    # Keep the developer's own layout rather than imposing ours. `width` stops ruamel
    # re-wrapping long lines; the indent settings match the block-sequence style that
    # dominates hand-written OpenAPI ("  - item" under its key). Without the explicit
    # sequence/offset, ruamel dumps sequences flush with their parent key and every
    # write reindents the whole file.
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


@dataclass(slots=True)
class LoadedSpec:
    """A parsed spec plus what we need to write it back unchanged.

    `data` is a ruamel round-trip structure, not a plain dict — mutating it and
    dumping preserves comments and ordering.
    """

    path: Path
    data: Any
    openapi_version: str | None
    swagger_version: str | None

    @property
    def is_openapi_3(self) -> bool:
        return bool(self.openapi_version and self.openapi_version.startswith("3."))

    @property
    def is_swagger_2(self) -> bool:
        return bool(self.swagger_version and self.swagger_version.startswith("2."))

    @property
    def version_label(self) -> str:
        if self.openapi_version:
            return f"OpenAPI {self.openapi_version}"
        if self.swagger_version:
            return f"Swagger {self.swagger_version}"
        return "unknown"

    def dumps(self) -> str:
        """Serialise back to text, preserving comments and key order."""
        buf = io.StringIO()
        _round_trip_yaml().dump(self.data, buf)
        return buf.getvalue()


def load_spec(path: str | Path) -> LoadedSpec:
    """Parse an OpenAPI 3.x YAML or JSON spec from disk."""
    path = Path(path)
    if not path.is_file():
        raise SpecLoadError(f"spec not found at {path}")

    try:
        data = _round_trip_yaml().load(path)
    except Exception as exc:  # ruamel raises a family of parse errors
        raise SpecLoadError(f"{path}: could not parse as YAML or JSON — {exc}") from exc

    if data is None:
        raise SpecLoadError(f"{path}: file is empty")
    if not isinstance(data, dict):
        raise SpecLoadError(
            f"{path}: expected a mapping at the document root, got {type(data).__name__}"
        )

    openapi_version = data.get("openapi")
    swagger_version = data.get("swagger")
    if openapi_version is None and swagger_version is None:
        raise SpecLoadError(
            f"{path}: no 'openapi' or 'swagger' key at the root — this does not look "
            f"like an API description document"
        )

    return LoadedSpec(
        path=path,
        data=data,
        openapi_version=str(openapi_version) if openapi_version is not None else None,
        swagger_version=str(swagger_version) if swagger_version is not None else None,
    )

"""Paths to the committed example specs, and a helper for ad-hoc ones.

Not a test module — pytest does not collect it. Imported by the test modules so the
fixture paths are declared once.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

#: The deliberately non-compliant fixture: one unambiguous violation per v0.2 rule.
BROKEN_SPEC = EXAMPLES / "broken.yaml"

#: The compliant fixture: must produce zero findings, and is the round-trip fixture.
GOOD_SPEC = EXAMPLES / "good.yaml"

#: Smallest document that satisfies the loader and the version gate. Format with a
#: `version=` keyword.
MINIMAL_SPEC = """\
openapi: {version}
info:
  title: t
  version: '1'
paths: {{}}
"""

SWAGGER_2_SPEC = "swagger: '2.0'\ninfo:\n  title: t\n  version: '1'\npaths: {}\n"


def write_spec(tmp_path: Path, body: str, name: str = "spec.yaml") -> Path:
    """Write `body` into `tmp_path` and return the path."""
    path = tmp_path / name
    path.write_text(body)
    return path


def minimal_spec_body(extra: str = "", version: str = "3.1.0") -> str:
    """A minimal 3.x document, optionally with `extra` YAML appended at the root."""
    base = f"openapi: {version}\ninfo:\n  title: t\n  version: '1'\n"
    return base + (extra if extra else "paths: {}\n")

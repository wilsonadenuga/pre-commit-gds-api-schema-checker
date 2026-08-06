"""Snapshot tests against the committed golden files.

`.gds-goldens/broken.json` and `.gds-goldens/good.json` are the JSON report
for each example fixture, produced by:

    gds-api-schema-uplift examples/broken.yaml --format json
    gds-api-schema-uplift examples/good.yaml --format json

These tests re-run that command and diff against the committed goldens. Any
change to a rule's finding order, snippet, location, or JSON shape shows up
as a diff in code review.

Regenerating the goldens is deliberately one command that a human must run:

    python -m tests.test_goldens --regenerate

Requiring the human step is what makes the goldens a review artefact rather
than an auto-updating cache. A rule change that alters output must be paired
with a golden update the reviewer signs off on.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Under pytest the tests/ directory is already on sys.path via conftest
# discovery; under `python -m tests.test_goldens --regenerate` it is not,
# so add it manually before the peer-file import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from example_specs import BROKEN_SPEC, GOOD_SPEC  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDENS_DIR = REPO_ROOT / ".gds-goldens"

# Path fields that vary by developer machine and are normalised before diffing.
# Not by ignoring them — a golden that dropped `spec` entirely would lose
# useful signal — but by replacing the value with a placeholder both sides
# agree on.
_VARIABLE_FIELDS = ("spec",)
_PLACEHOLDER = "<spec-path>"


def _normalise(payload: dict) -> dict:
    """Return a copy of `payload` with variable fields placeholdered."""
    result = dict(payload)
    for field in _VARIABLE_FIELDS:
        if field in result:
            result[field] = _PLACEHOLDER
    return result


def _run_cli(spec: Path) -> dict:
    """Invoke the installed CLI and return the parsed JSON payload."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gds_api_schema_uplift.cli",
            str(spec.relative_to(REPO_ROOT)),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # exit 0 for clean, 1 for findings — both write valid JSON to stdout.
    assert result.returncode in (0, 1), result.stderr
    return json.loads(result.stdout)


def _load_golden(name: str) -> dict:
    path = GOLDENS_DIR / name
    if not path.is_file():
        pytest.fail(
            f"Golden {path} is missing. Regenerate with:\n"
            f"  python -m tests.test_goldens --regenerate"
        )
    return _normalise(json.loads(path.read_text()))


# --- the snapshots -----------------------------------------------------------


def test_broken_yaml_matches_golden():
    """Any change to rule output for the broken fixture must be reviewed.

    A rule that starts flagging a new location, a snippet whose format
    changes, or a JSON key rename all surface here. Regenerating the golden
    is a deliberate act — a diff in `.gds-goldens/broken.json` in a PR is
    the reviewer's cue to confirm the change was intended.
    """
    actual = _normalise(_run_cli(BROKEN_SPEC))
    expected = _load_golden("broken.json")
    assert actual == expected, (
        f"Golden drift on broken.yaml.\n"
        f"Regenerate with: python -m tests.test_goldens --regenerate\n"
        f"Then review the diff in .gds-goldens/broken.json before committing."
    )


def test_good_yaml_matches_golden():
    """The zero-findings golden is the round-trip fixture's compliance guarantee.

    A rule that starts flagging good.yaml would break M1 (zero false
    positives) — this test catches the regression before it reaches the
    ruleset-behaviour test, which asserts the same thing more abstractly.
    """
    actual = _normalise(_run_cli(GOOD_SPEC))
    expected = _load_golden("good.json")
    assert actual == expected


# --- regeneration script -----------------------------------------------------


def _regenerate() -> None:
    """Rewrite both golden files from the current CLI output.

    Manual invocation only — never called from tests. Prints the paths it
    wrote so the caller can `git diff` them before committing.
    """
    GOLDENS_DIR.mkdir(exist_ok=True)
    for spec, name in ((BROKEN_SPEC, "broken.json"), (GOOD_SPEC, "good.json")):
        payload = _run_cli(spec)
        path = GOLDENS_DIR / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        print(
            "Usage: python -m tests.test_goldens --regenerate\n"
            "Run pytest to check against the goldens; this entrypoint only "
            "regenerates them."
        )
        sys.exit(2)

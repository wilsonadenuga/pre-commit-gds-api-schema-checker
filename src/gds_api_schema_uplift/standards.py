"""The standards corpus: schema, loader, and static clause lookup.

Phase 0 freezes the `standards.yaml` schema and the lookup interface. Phase 2
authors the actual GDS + NCSC clause text — this module deliberately ships with an
empty corpus rather than placeholder clause text, because a fabricated citation is
worse than a missing one.

Lookup is a static dict read, not retrieval. PRD s9.5 and s9.10 rule out a vector
store at every phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .contracts import Authority

#: Hosts that count as a source of truth. A clause citing anything else cannot
#: satisfy the M2 citation metric.
SOURCE_OF_TRUTH_HOSTS = ("www.gov.uk", "gov.uk", "www.ncsc.gov.uk", "ncsc.gov.uk")


class StandardsError(ValueError):
    """Raised when standards.yaml does not match the frozen schema."""


@dataclass(frozen=True, slots=True)
class Clause:
    """One citable clause.

    `text` is the quotable extract shown to the developer; `url` is where they go to
    verify it. `authority` distinguishes a GDS/NCSC mandate from a convention.
    """

    clause_id: str
    section: str
    text: str
    url: str
    authority: Authority = Authority.STANDARD

    @property
    def is_source_of_truth(self) -> bool:
        """True when the URL points at gov.uk or ncsc.gov.uk."""
        return any(f"//{host}/" in self.url or self.url.endswith(f"//{host}")
                   for host in SOURCE_OF_TRUTH_HOSTS)


class Standards:
    """An immutable clause map loaded from standards.yaml."""

    def __init__(self, clauses: dict[str, Clause]) -> None:
        self._clauses = dict(clauses)

    def __len__(self) -> int:
        return len(self._clauses)

    def __contains__(self, clause_id: object) -> bool:
        return clause_id in self._clauses

    @property
    def clause_ids(self) -> tuple[str, ...]:
        return tuple(self._clauses)

    def resolve(self, clause_id: str) -> Clause:
        """Return the clause for `clause_id`, or raise.

        Raising rather than returning None is deliberate: an unresolvable citation
        is a build failure, not a degraded finding (see Phase 2's citation
        integrity test).
        """
        try:
            return self._clauses[clause_id]
        except KeyError:
            raise StandardsError(
                f"clause_id {clause_id!r} does not resolve; "
                f"known ids: {', '.join(self.clause_ids) or '(corpus is empty)'}"
            ) from None


def _require_str(entry: dict[str, Any], key: str, clause_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StandardsError(
            f"clause {clause_id!r}: {key!r} must be a non-empty string, got {value!r}"
        )
    return value.strip()


def parse_standards(data: Any) -> Standards:
    """Validate the frozen standards.yaml shape and build a Standards map.

    Frozen schema::

        clauses:
          <clause_id>:
            section: <str>       # human-readable location in the source document
            text: <str>          # the quotable extract
            url: <str>           # where to verify it
            authority: standard | recommendation   # optional, defaults to standard
    """
    if data is None:
        raise StandardsError("standards.yaml is empty; expected a top-level 'clauses' mapping")
    if not isinstance(data, dict):
        raise StandardsError(f"standards.yaml must be a mapping, got {type(data).__name__}")

    raw_clauses = data.get("clauses")
    if raw_clauses is None:
        raise StandardsError("standards.yaml is missing the top-level 'clauses' key")
    if not isinstance(raw_clauses, dict):
        raise StandardsError(
            f"'clauses' must be a mapping of clause_id to clause, got {type(raw_clauses).__name__}"
        )

    clauses: dict[str, Clause] = {}
    for clause_id, entry in raw_clauses.items():
        if not isinstance(entry, dict):
            raise StandardsError(
                f"clause {clause_id!r} must be a mapping, got {type(entry).__name__}"
            )
        unknown = set(entry) - {"section", "text", "url", "authority"}
        if unknown:
            raise StandardsError(
                f"clause {clause_id!r} has unknown keys: {', '.join(sorted(unknown))}"
            )
        raw_authority = entry.get("authority", Authority.STANDARD.value)
        try:
            authority = Authority(raw_authority)
        except ValueError:
            raise StandardsError(
                f"clause {clause_id!r}: authority must be one of "
                f"{[a.value for a in Authority]}, got {raw_authority!r}"
            ) from None
        clauses[str(clause_id)] = Clause(
            clause_id=str(clause_id),
            section=_require_str(entry, "section", str(clause_id)),
            text=_require_str(entry, "text", str(clause_id)),
            url=_require_str(entry, "url", str(clause_id)),
            authority=authority,
        )
    return Standards(clauses)


def load_standards(path: str | Path) -> Standards:
    """Load and validate standards.yaml from disk."""
    path = Path(path)
    if not path.is_file():
        raise StandardsError(f"standards corpus not found at {path}")
    yaml = YAML(typ="safe")
    return parse_standards(yaml.load(path))


def default_standards_path() -> Path:
    """Repo-root standards.yaml, used when the CLI is run without an override."""
    return Path(__file__).resolve().parents[2] / "standards.yaml"

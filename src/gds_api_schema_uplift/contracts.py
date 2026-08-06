"""Frozen data contracts.

These shapes are the single interface between the rule engine and the Claude agent
(PRD s8). Phase 0 exists to pin them before parallel work starts, so treat changes
here as breaking: a field added after Phase 1 means integrating twice.

Nothing in this module imports from the rest of the package. It has no dependency on
the LLM layer, the rule layer, or the renderer, and it must stay that way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Finding severity, per the PRD s7.2 ruleset table."""

    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class RuleType(str, Enum):
    """Which pass produces the finding.

    DETERMINISTIC findings come from the free, reproducible rule pass.
    LLM findings need judgement and route through the agent (PRD s8 flow step 2).
    """

    DETERMINISTIC = "deterministic"
    LLM = "llm"


class Authority(str, Enum):
    """Whether a rule is mandated by a source of truth or is a convention.

    This is load-bearing for the "citation integrity" criterion: `REC-*` findings
    must render as visibly *not* GDS-mandated. Carrying it in data rather than in
    renderer conditionals keeps that true for every output format, including the
    stretch GitHub Action.
    """

    STANDARD = "standard"
    RECOMMENDATION = "recommendation"


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation at one location in the spec.

    Emitted by the rule engine (PRD s8 flow step 1). `location` is a JSONPath into
    the parsed spec so the renderer can show context and the agent can target a
    patch without re-deriving position.

    `line` and `column` are the 1-indexed source position of the offending key,
    resolved from the ruamel-tracked line-column data attached to the parsed
    document. Populated post-hoc by `run_deterministic_pass` rather than by the
    rule itself — rules stay location-only, and one place (the resolver) owns
    the walk from JSONPath to source coordinates. Both may be `None` when the
    resolver cannot find the target (malformed location, hand-built spec dict
    without ruamel `lc` info); renderers treat `None` as "no line info to show".
    """

    rule_id: str
    severity: Severity
    location: str
    snippet: str
    clause_id: str
    rule_type: RuleType
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class PatchOp:
    """A single RFC 6902 operation.

    `from_` carries the RFC's `from` member, which is a Python keyword. Serialise
    with `to_rfc6902()` rather than reading the field name directly.
    """

    op: str
    path: str
    value: Any = None
    from_: str | None = None

    def to_rfc6902(self) -> dict[str, Any]:
        """Render as an RFC 6902 operation object.

        `value` is omitted for ops that do not take one (`remove`), and `from` is
        emitted under its wire name.
        """
        out: dict[str, Any] = {"op": self.op, "path": self.path}
        if self.op not in ("remove",):
            out["value"] = self.value
        if self.from_ is not None:
            out["from"] = self.from_
        return out


@dataclass(frozen=True, slots=True)
class Patch:
    """An agent-proposed fix for one finding (PRD s8 flow step 4).

    A Patch is only ever shown to the developer after it has survived the
    validation gate — applied to a spec copy and re-validated. See the invariant
    table in PLAN.md.
    """

    ops: tuple[PatchOp, ...] = field(default_factory=tuple)
    rationale: str = ""
    clause_quote: str = ""

    def to_rfc6902(self) -> list[dict[str, Any]]:
        """Render the op list as an RFC 6902 patch document."""
        return [op.to_rfc6902() for op in self.ops]


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One finding plus the agent's proposal for it, after the validation gate.

    `offered` is the whole point of this type: a Suggestion that did not survive the
    gate still exists — it is counted, and its `drop_reason` is reportable — but it
    is never rendered as a fix. Carrying dropped proposals rather than discarding
    them is what makes the drop rate observable instead of invisible.
    """

    finding: Finding
    patch: Patch | None = None
    offered: bool = False
    drop_reason: str | None = None
    stage: str | None = None
    diff: str | None = None

    @property
    def has_citation(self) -> bool:
        """True when the proposal carries a non-empty clause quote.

        M2 requires every offered suggestion to cite a clause, so an offered
        proposal without one is a defect rather than a style preference.
        """
        return bool(self.patch and self.patch.clause_quote.strip())

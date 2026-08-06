"""The rule registry.

Lives in its own module so rule modules can `from ._registry import register` and
self-register at import time without importing a half-initialised `rules/__init__`.
`rules/__init__` re-exports everything here, so callers still use
`from gds_api_schema_uplift.rules import REGISTRY`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from dataclasses import replace

from ..contracts import Finding, RuleType, Severity
from ..line_resolver import resolve_line
from ..loader import LoadedSpec

Checker = Callable[[LoadedSpec], list[Finding]]


class RuleSpec:
    """A registered rule: its metadata plus the checker that implements it."""

    __slots__ = ("rule_id", "severity", "clause_id", "rule_type", "checker", "summary")

    def __init__(
        self,
        rule_id: str,
        severity: Severity,
        clause_id: str,
        rule_type: RuleType,
        checker: Checker,
        summary: str,
    ) -> None:
        self.rule_id = rule_id
        self.severity = severity
        self.clause_id = clause_id
        self.rule_type = rule_type
        self.checker = checker
        self.summary = summary

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RuleSpec {self.rule_id} {self.severity.value}>"


REGISTRY: dict[str, RuleSpec] = {}


def register(
    rule_id: str,
    *,
    severity: Severity,
    clause_id: str,
    summary: str,
    rule_type: RuleType = RuleType.DETERMINISTIC,
) -> Callable[[Checker], Checker]:
    """Register a checker under `rule_id`.

    The `clause_id` is declared here, at registration, rather than being chosen at
    finding time. That is what makes citation static and lets Phase 2's integrity
    test walk the registry without running any rules.
    """

    def decorator(checker: Checker) -> Checker:
        if rule_id in REGISTRY:
            raise ValueError(f"rule {rule_id!r} is already registered")
        REGISTRY[rule_id] = RuleSpec(
            rule_id=rule_id,
            severity=severity,
            clause_id=clause_id,
            rule_type=rule_type,
            checker=checker,
            summary=summary,
        )
        return checker

    return decorator


def deterministic_rules() -> tuple[RuleSpec, ...]:
    """Registered rules that run in the free, reproducible pass, in rule-id order."""
    return tuple(
        REGISTRY[rid]
        for rid in sorted(REGISTRY)
        if REGISTRY[rid].rule_type is RuleType.DETERMINISTIC
    )


def llm_rules() -> tuple[RuleSpec, ...]:
    """Registered rules that need the agent, in rule-id order."""
    return tuple(
        REGISTRY[rid] for rid in sorted(REGISTRY) if REGISTRY[rid].rule_type is RuleType.LLM
    )


def run_deterministic_pass(spec: LoadedSpec) -> list[Finding]:
    """Run every deterministic rule and collect findings.

    Rules run in sorted rule-id order and each rule's own findings keep their
    emission order, so report output and goldens are stable regardless of the order
    rule modules happen to be imported in.

    Findings are enriched with `(line, column)` from the ruamel line-column
    data attached to the parsed spec. Rules stay location-only — one place
    (the resolver) owns the JSONPath-to-source-coordinates walk, so a rule
    author does not have to know anything about ruamel `.lc` internals.
    """
    findings: list[Finding] = []
    for rule in deterministic_rules():
        for finding in rule.checker(spec):
            findings.append(_with_source_position(finding, spec))
    return findings


def _with_source_position(finding: Finding, spec: LoadedSpec) -> Finding:
    """Attach (line, column) if the resolver can find them, else pass through.

    A finding already carrying line info is left alone — a rule that computed
    a more specific position than the JSONPath resolver could is worth
    preserving. In practice no rule does this yet, but the guard keeps the
    door open without a contract change.
    """
    if finding.line is not None:
        return finding
    line, column = resolve_line(spec.data, finding.location)
    if line is None:
        return finding
    return replace(finding, line=line, column=column)


def findings_by_severity(findings: Iterable[Finding]) -> dict[Severity, int]:
    """Count findings per severity, for the report summary line."""
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1
    return counts

"""The rule registry.

A rule is a function `(LoadedSpec) -> list[Finding]` registered against its rule id.
Adding a rule is one function plus one decorator, which is what keeps Phase 1 and
Phase 5a additive.

The registry is deliberately empty in Phase 0. Phase 1 adds `GDS-001`–`GDS-005`,
Phase 5a adds `NCSC-001`–`NCSC-004`, Phase 5b adds `REC-001`/`REC-002`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..contracts import Finding, RuleType, Severity
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
    """Registered rules that run in the free, reproducible pass."""
    return tuple(
        r for r in REGISTRY.values() if r.rule_type is RuleType.DETERMINISTIC
    )


def llm_rules() -> tuple[RuleSpec, ...]:
    """Registered rules that need the agent."""
    return tuple(r for r in REGISTRY.values() if r.rule_type is RuleType.LLM)


def run_deterministic_pass(spec: LoadedSpec) -> list[Finding]:
    """Run every deterministic rule and collect findings.

    Ordering is registration order, which keeps report output and goldens stable.
    """
    findings: list[Finding] = []
    for rule in deterministic_rules():
        findings.extend(rule.checker(spec))
    return findings


def findings_by_severity(findings: Iterable[Finding]) -> dict[Severity, int]:
    """Count findings per severity, for the report summary line."""
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1
    return counts

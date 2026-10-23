"""The list of registered rules.

Each rule file calls `register(...)` to add itself here.
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

    __slots__ = (
        "rule_id",
        "severity",
        "clause_id",
        "rule_type",
        "checker",
        "summary",
        "good_example",
    )

    def __init__(
        self,
        rule_id: str,
        severity: Severity,
        clause_id: str,
        rule_type: RuleType,
        checker: Checker,
        summary: str,
        good_example: str,
    ) -> None:
        self.rule_id = rule_id
        self.severity = severity
        self.clause_id = clause_id
        self.rule_type = rule_type
        self.checker = checker
        self.summary = summary
        self.good_example = good_example

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RuleSpec {self.rule_id} {self.severity.value}>"


REGISTRY: dict[str, RuleSpec] = {}


def register(
    rule_id: str,
    *,
    severity: Severity,
    clause_id: str,
    summary: str,
    good_example: str,
    rule_type: RuleType = RuleType.DETERMINISTIC,
) -> Callable[[Checker], Checker]:
    """Add a rule to the registry.

    Each rule must name the standards clause it comes from and give a fix example,
    which the report shows under "Fix:".
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
            good_example=good_example,
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
    """Run every rule and return all findings, in rule-id order.

    Each finding also gets the line and column it came from in the spec file.
    """
    findings: list[Finding] = []
    for rule in deterministic_rules():
        for finding in rule.checker(spec):
            findings.append(_with_source_position(finding, spec))
    return findings


def _with_source_position(finding: Finding, spec: LoadedSpec) -> Finding:
    """Add the line and column to a finding, if they can be found."""
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

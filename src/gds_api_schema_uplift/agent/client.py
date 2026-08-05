"""The Claude agent: tool-use loop, patch validation gate, cost accounting.

One finding in, one `Suggestion` out. The loop is written by hand rather than using
the SDK's beta tool runner because the validation gate sits *inside* the turn — a
proposed patch is applied to a copy and re-validated before this function returns,
and a patch that fails is dropped with a reason rather than surfacing as a fix.

The Anthropic client is injected rather than constructed here, so every test in this
package runs without a network call or an API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..contracts import Finding, Patch, Suggestion
from ..cost import CallUsage, CostTracker
from ..loader import LoadedSpec
from ..patching import PatchResult, patched_text, render_diff, validate_patch
from ..rules import REGISTRY
from ..standards import Standards, StandardsError
from . import prompts
from .tools import (
    PROPOSE_PATCH,
    RETRIEVE_CLAUSE,
    ToolInputError,
    handle_retrieve_clause,
    parse_propose_patch,
    tool_definitions,
)

#: PRD s9.4 names Sonnet as the primary agent model: fast enough for a live demo and
#: more than capable of a JSON Patch plus a rationale. Opus is capability we do not
#: need at latency a 3-minute demo cannot afford.
DEFAULT_MODEL = "claude-sonnet-4-6"

#: A patch proposal is a short, well-scoped task with the clause already supplied, so
#: low effort is the right default and it protects the demo against latency. Raise it
#: with `--effort` if suggestion quality disappoints.
DEFAULT_EFFORT = "low"

#: Generous enough for adaptive thinking plus a patch; small enough that a runaway
#: response cannot stall the demo.
DEFAULT_MAX_TOKENS = 8000

#: Hard ceiling on tool-use round trips for a single finding. A well-behaved turn
#: needs one; the allowance covers a `retrieve_clause` detour or one retry.
MAX_TURNS_PER_FINDING = 4


class BudgetExhausted(RuntimeError):
    """Raised when the per-run LLM call cap is reached (PRD s11 cost mitigation)."""


class MessageCreator(Protocol):
    """The slice of the Anthropic SDK this module uses.

    Declared as a Protocol so tests can inject a stub and so nothing here depends on
    a specific SDK version's class hierarchy.
    """

    def create(self, **kwargs: Any) -> Any:  # pragma: no cover - structural type
        ...


@dataclass(slots=True)
class AgentConfig:
    """Everything tunable about an agent run."""

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_llm_calls: int = 5
    thinking: bool = True

    def request_kwargs(self) -> dict[str, Any]:
        """Model-behaviour parameters shared by every call in a run.

        These are deliberately identical across calls: `tools` and `system` render
        before `messages`, so anything varying here would invalidate the cached
        prefix on every finding.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "output_config": {"effort": self.effort},
        }
        if self.thinking:
            # Adaptive thinking must be requested explicitly on this model family —
            # omitting the parameter runs without thinking rather than adaptively.
            kwargs["thinking"] = {"type": "adaptive"}
        return kwargs


@dataclass(slots=True)
class AgentRun:
    """Mutable per-run state: the call budget and the cost ledger."""

    config: AgentConfig
    cost: CostTracker = field(default_factory=CostTracker)
    calls_made: int = 0
    patches_dropped: int = 0

    @property
    def calls_remaining(self) -> int:
        return max(0, self.config.max_llm_calls - self.calls_made)

    def note_call(self) -> None:
        if self.calls_remaining == 0:
            raise BudgetExhausted(
                f"LLM call cap of {self.config.max_llm_calls} reached for this run"
            )
        self.calls_made += 1


def _spec_excerpt(spec: LoadedSpec, max_lines: int = 60) -> str:
    """A bounded slice of the spec for context.

    Bounded because the spec is the one genuinely unbounded input here, and an
    enormous excerpt would dominate both cost and the model's attention.
    """
    lines = spec.dumps().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    head = lines[:max_lines]
    return "\n".join(head) + f"\n# ... {len(lines) - max_lines} further line(s) omitted"


def _clause_for(standards: Standards, clause_id: str) -> tuple[str, str]:
    """Return `(clause_text, clause_url)`, empty when the clause does not resolve.

    A missing clause is not an error here: the corpus is authored in a later phase,
    and the run should still work — it just cannot produce a citation, which the
    caller detects via `Suggestion.has_citation`.
    """
    try:
        clause = standards.resolve(clause_id)
    except StandardsError:
        return "", ""
    return clause.text, clause.url


def _extract_text(response: Any) -> str:
    """Best-effort assistant text, for a dropped-suggestion reason."""
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", "")
    ]
    return " ".join(parts).strip()


def _record_usage(run: AgentRun, response: Any) -> None:
    """Fold one response's token usage into the run ledger."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    run.cost.record(
        CallUsage(
            model=getattr(response, "model", run.config.model),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )
    )


def _dropped(finding: Finding, reason: str, stage: str | None = None) -> Suggestion:
    return Suggestion(finding=finding, drop_reason=reason, stage=stage)


def _gate(spec: LoadedSpec, finding: Finding, patch: Patch) -> Suggestion:
    """Run a parsed patch through the validation gate.

    This is the only path by which a Suggestion becomes `offered=True`.
    """
    if not patch.ops:
        return _dropped(
            finding,
            patch.rationale or "agent reported it could not construct a patch",
            stage="empty_patch",
        )

    result: PatchResult = validate_patch(spec, patch)
    if not result.ok:
        return Suggestion(
            finding=finding,
            patch=patch,
            offered=False,
            drop_reason=result.error,
            stage=result.stage,
        )

    diff = render_diff(spec.dumps(), patched_text(spec, result), str(spec.path))
    return Suggestion(
        finding=finding,
        patch=patch,
        offered=True,
        stage=result.stage,
        diff=diff,
    )


def propose_for_finding(
    messages_api: MessageCreator,
    *,
    spec: LoadedSpec,
    finding: Finding,
    standards: Standards,
    run: AgentRun,
) -> Suggestion:
    """Ask the agent for a patch for one finding and put it through the gate.

    Raises BudgetExhausted when the run's call cap is already spent; every other
    failure becomes a dropped Suggestion carrying its reason, because one bad
    proposal must not abort a run over the remaining findings.
    """
    rule = REGISTRY.get(finding.rule_id)
    clause_text, clause_url = _clause_for(standards, finding.clause_id)

    system = prompts.build_system_blocks(standards)
    tools = tool_definitions()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": prompts.finding_message(
                rule_id=finding.rule_id,
                severity=finding.severity.value,
                location=finding.location,
                snippet=finding.snippet,
                rule_summary=rule.summary if rule else "(rule not registered)",
                clause_id=finding.clause_id,
                clause_text=clause_text,
                clause_url=clause_url,
                spec_excerpt=_spec_excerpt(spec),
            ),
        }
    ]

    for _ in range(MAX_TURNS_PER_FINDING):
        run.note_call()
        response = messages_api.create(
            system=system,
            tools=tools,
            messages=messages,
            **run.config.request_kwargs(),
        )
        _record_usage(run, response)

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            return _dropped(finding, "model declined to answer", stage="refusal")

        content = list(getattr(response, "content", []))
        tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]

        if not tool_uses:
            text = _extract_text(response) or "no patch proposed"
            return _dropped(finding, f"agent returned prose, not a patch: {text[:200]}")

        # Answer every retrieve_clause in one user turn before looping. Splitting
        # tool results across messages trains the model out of parallel calls.
        lookups = [b for b in tool_uses if b.name == RETRIEVE_CLAUSE]
        proposals = [b for b in tool_uses if b.name == PROPOSE_PATCH]

        if proposals:
            try:
                patch = parse_propose_patch(proposals[0].input)
            except ToolInputError as exc:
                return _dropped(finding, f"malformed patch proposal: {exc}",
                                stage="malformed_tool_input")
            return _gate(spec, finding, patch)

        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": handle_retrieve_clause(standards, block.input),
                    }
                    for block in lookups
                ],
            }
        )

    return _dropped(
        finding,
        f"agent did not propose a patch within {MAX_TURNS_PER_FINDING} turns",
        stage="turn_limit",
    )


def propose_for_findings(
    messages_api: MessageCreator,
    *,
    spec: LoadedSpec,
    findings: list[Finding],
    standards: Standards,
    run: AgentRun,
) -> list[Suggestion]:
    """Propose patches for as many findings as the call budget allows.

    Stops cleanly at the cap rather than raising, so a run that exhausts its budget
    still reports everything it managed to produce. Findings are attempted in the
    order given, which is rule-id order, so a truncated run is reproducible.
    """
    suggestions: list[Suggestion] = []
    for finding in findings:
        if run.calls_remaining == 0:
            break
        try:
            suggestion = propose_for_finding(
                messages_api,
                spec=spec,
                finding=finding,
                standards=standards,
                run=run,
            )
        except BudgetExhausted:
            break
        if not suggestion.offered:
            run.patches_dropped += 1
        suggestions.append(suggestion)
    return suggestions


def build_messages_api(api_key: str | None = None) -> MessageCreator:
    """Construct the real Anthropic messages API.

    Imported lazily so the package imports (and the deterministic pass runs) without
    the SDK resolving credentials.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    return client.messages

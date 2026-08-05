"""Per-run LLM cost accounting.

A project goal is "observable and cost-aware" (PRD s3): every run prints what it
spent, and a later phase ships the same numbers as an OpenTelemetry metric. This
module is the accounting layer for that — arithmetic over plain integers.

It deliberately does **not** import `anthropic` and never makes a network call.
The client layer hands it token counts; it hands back money. That keeps the whole
of cost reporting unit-testable without an API key, and keeps a pricing mistake
from being hidden behind a mock.

Prices are US dollars per **one million** tokens, from the current Anthropic
pricing table. See `PRICING` for the per-model figures and the notes attached to
them.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

# Prompt-caching multipliers, applied to a model's *input* rate.
#
# A cache read is billed at a tenth of the input rate; a cache write costs a
# premium over it, because the tokens are processed and then stored. The write
# premium depends on the entry's TTL: 1.25x for the default 5-minute cache,
# 2.0x for the 1-hour cache.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER_5M = 1.25
CACHE_WRITE_MULTIPLIER_1H = 2.0


class UnknownModelError(KeyError):
    """Raised when a model has no pricing entry.

    Deliberately loud. The alternative — falling back to a zero rate — would make
    an unpriced model look free, which is the one failure mode a cost tracker
    must never have.
    """


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Dollar rates for one model, per million tokens.

    Cache rates are derived rather than stored, so a change to the published
    input rate cannot leave a stale cache rate behind next to it.
    """

    model_id: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_multiplier: float = CACHE_READ_MULTIPLIER
    cache_write_multiplier: float = CACHE_WRITE_MULTIPLIER_5M

    @property
    def cache_read_per_mtok(self) -> float:
        """Rate for tokens served from the prompt cache."""
        return self.input_per_mtok * self.cache_read_multiplier

    @property
    def cache_write_per_mtok(self) -> float:
        """Rate for tokens written to the prompt cache.

        Defaults to the 5-minute TTL premium, which is what an un-annotated
        `cache_control: {"type": "ephemeral"}` block gets. Pass
        `cache_write_multiplier=CACHE_WRITE_MULTIPLIER_1H` for `ttl: "1h"`.
        """
        return self.input_per_mtok * self.cache_write_multiplier


# Keyed by base model id. Dated spellings resolve here via `pricing_for`.
PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-6": ModelPricing(
        model_id="claude-sonnet-4-6",
        input_per_mtok=3.00,
        output_per_mtok=15.00,
    ),
    # Sonnet 5 currently carries promotional pricing of $2.00 / $10.00 per MTok
    # through 2026-08-31, after which it reverts to the standard $3.00 / $15.00.
    # We bill at the standard rate on purpose: a FinOps tracker that overestimates
    # is safe, one that underestimates is not. When the promo expires this entry
    # is already correct and needs no change.
    "claude-sonnet-5": ModelPricing(
        model_id="claude-sonnet-5",
        input_per_mtok=3.00,
        output_per_mtok=15.00,
    ),
    "claude-haiku-4-5": ModelPricing(
        model_id="claude-haiku-4-5",
        input_per_mtok=1.00,
        output_per_mtok=5.00,
    ),
    "claude-opus-4-8": ModelPricing(
        model_id="claude-opus-4-8",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
    ),
    "claude-opus-5": ModelPricing(
        model_id="claude-opus-5",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
    ),
}


def pricing_for(model_id: str) -> ModelPricing:
    """Look up pricing, resolving dated suffixes.

    Some ids have a dated spelling alongside the base alias — `claude-haiku-4-5`
    is also served as `claude-haiku-4-5-20251001` — and whichever one the client
    layer happens to send must price identically. Resolution strips trailing
    *all-numeric* segments one at a time, checking the table after each strip.

    Only numeric segments are stripped, and that restriction is load-bearing:
    a non-numeric suffix can denote a different SKU (fast mode, for instance, is
    billed well above the base rate), so silently resolving `...-fast` to its
    base entry would under-report. Anything unrecognised raises instead.

    Raises:
        UnknownModelError: if no entry can be resolved.
    """
    candidate = model_id
    while candidate:
        if candidate in PRICING:
            return PRICING[candidate]
        head, sep, tail = candidate.rpartition("-")
        if not sep or not tail.isdigit():
            break
        candidate = head
    raise UnknownModelError(
        f"No pricing entry for model {model_id!r}. "
        f"Known models: {', '.join(sorted(PRICING))}."
    )


@dataclass(frozen=True, slots=True)
class CallUsage:
    """Token counts for one API call, mirroring the Anthropic usage block.

    The field names match `response.usage` deliberately, so the client layer can
    map straight across without inventing a second vocabulary for the same thing.

    **`input_tokens` is the uncached remainder only.** It is *not* the prompt
    size. The Anthropic usage block splits the prompt three ways — tokens read
    from the cache, tokens written to the cache, and the uncached remainder —
    and `input_tokens` is only that last part. Treating it as the whole prompt
    under-reports cost on every cached call, and under-reports it worst on the
    runs where caching is working hardest. Use `total_input_tokens`.
    """

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        """Uncached + cache-write + cache-read. The true prompt size."""
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @property
    def cost_usd(self) -> float:
        """Cost of this single call.

        Raises:
            UnknownModelError: if the model has no pricing entry.
        """
        pricing = pricing_for(self.model)
        micro_dollars = (
            self.input_tokens * pricing.input_per_mtok
            + self.cache_creation_input_tokens * pricing.cache_write_per_mtok
            + self.cache_read_input_tokens * pricing.cache_read_per_mtok
            + self.output_tokens * pricing.output_per_mtok
        )
        return micro_dollars / 1_000_000

    @property
    def cache_hit_ratio(self) -> float:
        """cache_read / total_input_tokens; 0.0 when there is no input."""
        total = self.total_input_tokens
        if total == 0:
            return 0.0
        return self.cache_read_input_tokens / total


def format_usd(amount: float) -> str:
    """Render a dollar amount at a resolution that is actually meaningful.

    Per-call costs here live in the fractions-of-a-penny range, so two decimal
    places would print `$0.00` for most of a run and hide exactly the number the
    run exists to show. Four places is the floor; the precision escalates rather
    than round a non-zero cost away to nothing.
    """
    if amount == 0:
        return "$0.0000"
    for places in (4, 6, 8):
        if round(amount, places) != 0:
            return f"${amount:.{places}f}"
    return f"${amount:.2e}"


class CostTracker:
    """Accumulates per-call usage for one run.

    One instance per CLI invocation. The tracker owns no I/O of its own beyond
    `render`, so the same numbers can be printed, serialised to JSON, and later
    exported as OTel metrics without three implementations of the arithmetic.
    """

    def __init__(self) -> None:
        self._calls: list[CallUsage] = []

    def record(self, usage: CallUsage) -> CallUsage:
        """Record one call's usage.

        Returns the usage it was given, so a caller can record and forward in a
        single expression. Costing the call here would hide an unpriced model
        until render time, so pricing is validated eagerly.
        """
        _ = usage.cost_usd  # fail loudly at the call site, not at print time
        self._calls.append(usage)
        return usage

    @property
    def calls(self) -> tuple[CallUsage, ...]:
        """The recorded calls, in the order they happened."""
        return tuple(self._calls)

    @property
    def total_usd(self) -> float:
        """Total spend for the run."""
        return sum(call.cost_usd for call in self._calls)

    @property
    def total_tokens(self) -> int:
        """Every token the run paid for, input and output.

        Input here means the *true* prompt size, cached tokens included — cached
        tokens are cheaper, not free.
        """
        return sum(
            call.total_input_tokens + call.output_tokens for call in self._calls
        )

    @property
    def total_input_tokens(self) -> int:
        """True prompt size summed across the run."""
        return sum(call.total_input_tokens for call in self._calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(call.output_tokens for call in self._calls)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(call.cache_read_input_tokens for call in self._calls)

    @property
    def total_cache_write_tokens(self) -> int:
        return sum(call.cache_creation_input_tokens for call in self._calls)

    @property
    def total_uncached_input_tokens(self) -> int:
        """The uncached remainder, summed. Not the prompt size — see `CallUsage`."""
        return sum(call.input_tokens for call in self._calls)

    @property
    def cache_hit_ratio(self) -> float:
        """Share of the run's prompt tokens served from cache; 0.0 with no input."""
        total = self.total_input_tokens
        if total == 0:
            return 0.0
        return self.total_cache_read_tokens / total

    def by_model(self) -> dict[str, float]:
        """Cost split by model id, as sent.

        Keyed by the id the call used rather than the resolved base id, because
        when a run is unexpectedly expensive the first question is which model
        the code actually asked for.
        """
        split: dict[str, float] = {}
        for call in self._calls:
            split[call.model] = split.get(call.model, 0.0) + call.cost_usd
        return split

    def summary_lines(self) -> list[str]:
        """Plain-text summary, for `--format=json` payloads and logs.

        Terminal-free by construction: no Rich markup, no width assumptions.
        """
        if not self._calls:
            return ["No LLM calls this run — nothing to bill."]

        lines = [
            f"{len(self._calls)} LLM call(s), {format_usd(self.total_usd)} total.",
            (
                f"Tokens: {self.total_tokens:,} "
                f"({self.total_input_tokens:,} in, {self.total_output_tokens:,} out)."
            ),
            (
                f"Prompt cache: {self.cache_hit_ratio:.1%} of input tokens read from "
                f"cache ({self.total_cache_read_tokens:,} read, "
                f"{self.total_cache_write_tokens:,} written)."
            ),
        ]
        for model, cost in sorted(self.by_model().items()):
            lines.append(f"  {model}: {format_usd(cost)}")
        return lines

    def render(self, console: Console | None = None) -> None:
        """Print the per-run cost summary."""
        console = console or Console()

        if not self._calls:
            # An empty table reads as a rendering bug. Say what happened instead.
            console.print("[dim]No LLM calls this run — nothing to bill.[/dim]")
            return

        table = Table(title="LLM cost this run", header_style="bold")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Model", no_wrap=True)
        table.add_column("Input", justify="right")
        table.add_column("Cache w", justify="right")
        table.add_column("Cache r", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cost", justify="right")

        for index, call in enumerate(self._calls, start=1):
            table.add_row(
                str(index),
                call.model,
                f"{call.input_tokens:,}",
                f"{call.cache_creation_input_tokens:,}",
                f"{call.cache_read_input_tokens:,}",
                f"{call.output_tokens:,}",
                format_usd(call.cost_usd),
            )
        console.print(table)

        console.print(
            f"[bold]Total: {format_usd(self.total_usd)}[/bold] "
            f"across {len(self._calls)} call(s), {self.total_tokens:,} token(s)."
        )

        # A run whose cache never hits is a cost bug worth seeing, so the ratio is
        # stated on every run rather than only when it looks interesting.
        ratio = self.cache_hit_ratio
        style = "green" if ratio > 0 else "yellow"
        note = "" if ratio > 0 else " — nothing was served from cache this run"
        console.print(
            f"Prompt cache hit ratio: [{style}]{ratio:.1%}[/{style}] "
            f"of {self.total_input_tokens:,} input token(s){note}."
        )

        if len(self.by_model()) > 1:
            for model, cost in sorted(self.by_model().items()):
                console.print(f"  [dim]{model}[/dim]  {format_usd(cost)}")

    def as_metrics(self) -> dict[str, float | int]:
        """Flat metric name -> value, for the OTel phase.

        Flat and fixed-key on purpose: an OTel instrument wants a stable name
        with the varying parts carried as attributes, so the per-model split
        stays in `by_model()` rather than inflating this into dynamic keys.
        """
        return {
            "llm.calls": len(self._calls),
            "llm.cost_usd": self.total_usd,
            "llm.tokens.total": self.total_tokens,
            "llm.tokens.input_total": self.total_input_tokens,
            "llm.tokens.input_uncached": self.total_uncached_input_tokens,
            "llm.tokens.cache_write": self.total_cache_write_tokens,
            "llm.tokens.cache_read": self.total_cache_read_tokens,
            "llm.tokens.output": self.total_output_tokens,
            "llm.cache.hit_ratio": self.cache_hit_ratio,
        }

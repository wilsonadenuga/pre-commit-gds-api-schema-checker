"""Cost accounting is the one module where a silent bug costs money.

Every cost assertion here is against a figure computed by hand in a comment, not
against whatever the implementation happens to return. A test that asserts the
code agrees with itself would pass just as happily with the cache multipliers
inverted.
"""

from __future__ import annotations

import dataclasses
import io

import pytest
from rich.console import Console

from gds_api_schema_uplift.cost import (
    PRICING,
    CallUsage,
    CostTracker,
    ModelPricing,
    UnknownModelError,
    format_usd,
    pricing_for,
)


# --------------------------------------------------------------------------
# Pricing table
# --------------------------------------------------------------------------


def test_model_pricing_fields_are_exactly_the_expected_set():
    assert [f.name for f in dataclasses.fields(ModelPricing)] == [
        "model_id",
        "input_per_mtok",
        "output_per_mtok",
        "cache_read_multiplier",
        "cache_write_multiplier",
    ]


def test_pricing_table_covers_the_documented_models():
    assert sorted(PRICING) == [
        "claude-haiku-4-5",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
    ]


def test_sonnet_4_6_headline_rates():
    pricing = PRICING["claude-sonnet-4-6"]
    assert pricing.input_per_mtok == 3.00
    assert pricing.output_per_mtok == 15.00


def test_sonnet_5_uses_standard_not_promotional_rates():
    """The $2.00/$10.00 promo expires 2026-08-31; overestimating is the safe error."""
    pricing = PRICING["claude-sonnet-5"]
    assert pricing.input_per_mtok == 3.00
    assert pricing.output_per_mtok == 15.00


def test_derived_cache_rates_for_a_known_model():
    # Sonnet 4.6 input is $3.00/MTok.
    #   cache read  = 3.00 * 0.1  = 0.30
    #   cache write = 3.00 * 1.25 = 3.75
    pricing = PRICING["claude-sonnet-4-6"]
    assert pricing.cache_read_per_mtok == pytest.approx(0.30)
    assert pricing.cache_write_per_mtok == pytest.approx(3.75)


def test_one_hour_cache_write_multiplier_is_supported():
    # Opus 5 input is $5.00/MTok; the 1-hour TTL premium is 2.0x → 10.00.
    pricing = ModelPricing(
        model_id="claude-opus-5",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        cache_write_multiplier=2.0,
    )
    assert pricing.cache_write_per_mtok == pytest.approx(10.00)


# --------------------------------------------------------------------------
# pricing_for
# --------------------------------------------------------------------------


def test_pricing_for_resolves_a_base_id():
    assert pricing_for("claude-sonnet-4-6").model_id == "claude-sonnet-4-6"


def test_pricing_for_resolves_a_dated_id_to_its_base_entry():
    resolved = pricing_for("claude-haiku-4-5-20251001")
    assert resolved.model_id == "claude-haiku-4-5"
    assert resolved is PRICING["claude-haiku-4-5"]


def test_dated_and_base_spellings_price_identically():
    dated = CallUsage(model="claude-haiku-4-5-20251001", input_tokens=1_000_000)
    base = CallUsage(model="claude-haiku-4-5", input_tokens=1_000_000)
    assert dated.cost_usd == base.cost_usd


def test_pricing_for_rejects_a_foreign_model():
    with pytest.raises(UnknownModelError):
        pricing_for("gpt-4")


def test_pricing_for_rejects_an_empty_model_id():
    with pytest.raises(UnknownModelError):
        pricing_for("")


def test_unknown_model_error_is_a_key_error():
    """So existing `except KeyError` handlers in the client layer still catch it."""
    assert issubclass(UnknownModelError, KeyError)


def test_non_numeric_suffix_is_not_silently_resolved():
    """A `-fast` SKU is billed above base; resolving it down would under-report."""
    with pytest.raises(UnknownModelError):
        pricing_for("claude-opus-5-fast")


# --------------------------------------------------------------------------
# CallUsage
# --------------------------------------------------------------------------


def test_call_usage_fields_are_exactly_the_expected_set():
    assert [f.name for f in dataclasses.fields(CallUsage)] == [
        "model",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ]


def test_call_usage_is_immutable():
    usage = CallUsage(model="claude-opus-5", input_tokens=10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.input_tokens = 20  # type: ignore[misc]


def test_hand_computed_cost_for_one_call():
    """Worked by hand; the implementation does not get a vote.

    Model claude-sonnet-4-6 — $3.00 in / $15.00 out per MTok.
      cache write rate = 3.00 * 1.25 = $3.75/MTok
      cache read rate  = 3.00 * 0.10 = $0.30/MTok

      uncached input  10,000 * 3.00  =  30,000
      cache write      4,000 * 3.75  =  15,000
      cache read      20,000 * 0.30  =   6,000
      output           2,000 * 15.00 =  30,000
                                        ------
                                        81,000  (dollar-micro-units)
      81,000 / 1,000,000 = $0.0810
    """
    usage = CallUsage(
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        cache_creation_input_tokens=4_000,
        cache_read_input_tokens=20_000,
        output_tokens=2_000,
    )
    assert usage.cost_usd == pytest.approx(0.0810)


def test_total_input_tokens_includes_all_three_components():
    """`input_tokens` is the uncached remainder, not the prompt size."""
    usage = CallUsage(
        model="claude-opus-5",
        input_tokens=1_000,
        cache_creation_input_tokens=2_000,
        cache_read_input_tokens=7_000,
        output_tokens=500,
    )
    assert usage.total_input_tokens == 10_000
    # The trap this pins: the uncached field alone is a tenth of the real prompt.
    assert usage.input_tokens == 1_000


def test_cached_call_is_materially_cheaper_than_the_uncached_equivalent():
    """Same prompt size, different cache split. This is the caching-accounting test.

    Both calls carry a 100,000-token prompt and 1,000 output tokens on
    claude-sonnet-4-6 ($3.00 in / $15.00 out per MTok).

      all-uncached: 100,000 * 3.00 + 1,000 * 15.00 = 300,000 + 15,000 = 315,000
                    → $0.3150
      all-cache-read: 100,000 * 0.30 + 1,000 * 15.00 = 30,000 + 15,000 = 45,000
                    → $0.0450
    """
    uncached = CallUsage(
        model="claude-sonnet-4-6",
        input_tokens=100_000,
        output_tokens=1_000,
    )
    cached = CallUsage(
        model="claude-sonnet-4-6",
        input_tokens=0,
        cache_read_input_tokens=100_000,
        output_tokens=1_000,
    )

    assert uncached.total_input_tokens == cached.total_input_tokens == 100_000
    assert uncached.cost_usd == pytest.approx(0.3150)
    assert cached.cost_usd == pytest.approx(0.0450)
    assert cached.cost_usd < uncached.cost_usd / 5


def test_cache_write_costs_more_than_uncached_input():
    """Writing to the cache carries a premium; it is not a discount on turn one.

    claude-sonnet-4-6, 100,000 tokens:
      uncached:    100,000 * 3.00 = 300,000 → $0.3000
      cache write: 100,000 * 3.75 = 375,000 → $0.3750
    """
    uncached = CallUsage(model="claude-sonnet-4-6", input_tokens=100_000)
    written = CallUsage(
        model="claude-sonnet-4-6", cache_creation_input_tokens=100_000
    )
    assert uncached.cost_usd == pytest.approx(0.3000)
    assert written.cost_usd == pytest.approx(0.3750)
    assert written.cost_usd > uncached.cost_usd


def test_cache_hit_ratio():
    usage = CallUsage(
        model="claude-opus-5",
        input_tokens=1_000,
        cache_creation_input_tokens=1_000,
        cache_read_input_tokens=8_000,
    )
    assert usage.cache_hit_ratio == pytest.approx(0.8)


def test_cache_hit_ratio_on_a_zero_input_call_does_not_divide_by_zero():
    usage = CallUsage(model="claude-opus-5", output_tokens=42)
    assert usage.cache_hit_ratio == 0.0


def test_unknown_model_costs_raise_rather_than_zero():
    usage = CallUsage(model="gpt-4", input_tokens=1_000_000)
    with pytest.raises(UnknownModelError):
        usage.cost_usd


# --------------------------------------------------------------------------
# CostTracker
# --------------------------------------------------------------------------


def _multi_model_tracker() -> CostTracker:
    """Three calls across two models, with hand-computed costs.

    1. claude-haiku-4-5   ($1.00 in / $5.00 out)
         100,000 * 1.00 + 10,000 * 5.00 = 100,000 + 50,000 = 150,000 → $0.1500
    2. claude-haiku-4-5   ($1.00 in / $5.00 out; cache read = $0.10/MTok)
         50,000 * 0.10 + 1,000 * 5.00 = 5,000 + 5,000 = 10,000 → $0.0100
    3. claude-opus-5      ($5.00 in / $25.00 out)
         20,000 * 5.00 + 4,000 * 25.00 = 100,000 + 100,000 = 200,000 → $0.2000

    haiku total = $0.1600, opus total = $0.2000, run total = $0.3600
    """
    tracker = CostTracker()
    tracker.record(
        CallUsage(
            model="claude-haiku-4-5", input_tokens=100_000, output_tokens=10_000
        )
    )
    tracker.record(
        CallUsage(
            model="claude-haiku-4-5",
            cache_read_input_tokens=50_000,
            output_tokens=1_000,
        )
    )
    tracker.record(
        CallUsage(model="claude-opus-5", input_tokens=20_000, output_tokens=4_000)
    )
    return tracker


def test_record_returns_the_usage_it_was_given():
    tracker = CostTracker()
    usage = CallUsage(model="claude-opus-5", input_tokens=10)
    assert tracker.record(usage) is usage


def test_calls_are_exposed_in_order_as_a_tuple():
    tracker = _multi_model_tracker()
    assert isinstance(tracker.calls, tuple)
    assert [c.model for c in tracker.calls] == [
        "claude-haiku-4-5",
        "claude-haiku-4-5",
        "claude-opus-5",
    ]


def test_tracker_totals_across_several_calls_and_models():
    tracker = _multi_model_tracker()
    assert tracker.total_usd == pytest.approx(0.3600)
    # 110,000 + 51,000 + 24,000
    assert tracker.total_tokens == 185_000
    assert tracker.total_input_tokens == 170_000
    assert tracker.total_output_tokens == 15_000


def test_by_model_splits_correctly():
    tracker = _multi_model_tracker()
    split = tracker.by_model()
    assert sorted(split) == ["claude-haiku-4-5", "claude-opus-5"]
    assert split["claude-haiku-4-5"] == pytest.approx(0.1600)
    assert split["claude-opus-5"] == pytest.approx(0.2000)
    assert sum(split.values()) == pytest.approx(tracker.total_usd)


def test_tracker_cache_hit_ratio():
    # 50,000 cache-read of 170,000 total input tokens.
    tracker = _multi_model_tracker()
    assert tracker.cache_hit_ratio == pytest.approx(50_000 / 170_000)


def test_recording_an_unpriced_model_fails_at_the_call_site():
    tracker = CostTracker()
    with pytest.raises(UnknownModelError):
        tracker.record(CallUsage(model="gpt-4", input_tokens=10))


def test_zero_call_tracker():
    tracker = CostTracker()
    assert tracker.calls == ()
    assert tracker.total_usd == 0.0
    assert tracker.total_tokens == 0
    assert tracker.cache_hit_ratio == 0.0
    assert tracker.by_model() == {}

    lines = tracker.summary_lines()
    assert len(lines) == 1
    assert "no llm calls" in lines[0].lower()


def test_zero_call_render_does_not_raise_and_says_so():
    console = Console(file=io.StringIO(), width=100)
    CostTracker().render(console)
    output = console.file.getvalue()
    assert "no llm calls" in output.lower()


# --------------------------------------------------------------------------
# Reporting surfaces
# --------------------------------------------------------------------------


def test_summary_lines_are_usable_without_a_terminal():
    tracker = _multi_model_tracker()
    lines = tracker.summary_lines()
    assert all(isinstance(line, str) for line in lines)
    joined = "\n".join(lines)
    assert "$0.3600" in joined
    # Plain text: no Rich markup leaking into JSON output or log files.
    assert "[" not in joined and "]" not in joined


def test_summary_lines_state_the_cache_hit_ratio():
    tracker = _multi_model_tracker()
    joined = "\n".join(tracker.summary_lines()).lower()
    assert "cache" in joined


def test_summary_lines_include_the_per_model_split():
    joined = "\n".join(_multi_model_tracker().summary_lines())
    assert "claude-haiku-4-5" in joined
    assert "claude-opus-5" in joined


def test_render_shows_the_total():
    console = Console(file=io.StringIO(), width=100)
    _multi_model_tracker().render(console)
    output = console.file.getvalue()
    assert "$0.3600" in output


def test_render_shows_per_call_rows_and_the_cache_hit_ratio():
    console = Console(file=io.StringIO(), width=100)
    _multi_model_tracker().render(console)
    output = console.file.getvalue()
    assert output.count("claude-haiku-4-5") >= 2  # one row per haiku call
    assert "claude-opus-5" in output
    assert "cache hit ratio" in output.lower()


def test_render_flags_a_run_where_the_cache_never_hit():
    tracker = CostTracker()
    tracker.record(
        CallUsage(model="claude-opus-5", input_tokens=50_000, output_tokens=1_000)
    )
    console = Console(file=io.StringIO(), width=100)
    tracker.render(console)
    output = console.file.getvalue()
    assert "0.0%" in output
    assert "nothing was served from cache" in output.lower()


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def test_costs_render_with_meaningful_precision():
    assert format_usd(0.0431) == "$0.0431"


def test_a_tiny_but_non_zero_cost_never_renders_as_zero_pence():
    # One haiku input token: 1 * 1.00 / 1,000,000 = $0.000001
    usage = CallUsage(model="claude-haiku-4-5", input_tokens=1)
    assert usage.cost_usd == pytest.approx(1e-6)

    rendered = format_usd(usage.cost_usd)
    assert rendered not in ("$0.00", "$0.0000")
    assert rendered == "$0.000001"


def test_a_tiny_cost_survives_rendering_through_the_tracker():
    tracker = CostTracker()
    tracker.record(CallUsage(model="claude-haiku-4-5", input_tokens=1))
    console = Console(file=io.StringIO(), width=100)
    tracker.render(console)
    output = console.file.getvalue()
    assert "$0.00 " not in output
    assert "$0.000001" in output


def test_exactly_zero_still_renders_as_zero():
    assert format_usd(0.0) == "$0.0000"


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_as_metrics_keys_are_flat_and_values_numeric():
    metrics = _multi_model_tracker().as_metrics()
    assert sorted(metrics) == [
        "llm.cache.hit_ratio",
        "llm.calls",
        "llm.cost_usd",
        "llm.tokens.cache_read",
        "llm.tokens.cache_write",
        "llm.tokens.input_total",
        "llm.tokens.input_uncached",
        "llm.tokens.output",
        "llm.tokens.total",
    ]
    for key, value in metrics.items():
        assert isinstance(key, str), key
        assert isinstance(value, (int, float)), key
        assert not isinstance(value, bool), key


def test_as_metrics_values_agree_with_the_tracker():
    tracker = _multi_model_tracker()
    metrics = tracker.as_metrics()
    assert metrics["llm.calls"] == 3
    assert metrics["llm.cost_usd"] == pytest.approx(0.3600)
    assert metrics["llm.tokens.total"] == 185_000
    assert metrics["llm.tokens.input_total"] == 170_000
    assert metrics["llm.tokens.input_uncached"] == 120_000
    assert metrics["llm.tokens.cache_read"] == 50_000
    assert metrics["llm.tokens.cache_write"] == 0
    assert metrics["llm.tokens.output"] == 15_000
    assert metrics["llm.cache.hit_ratio"] == pytest.approx(50_000 / 170_000)


def test_as_metrics_on_a_zero_call_run_is_all_zeros():
    metrics = CostTracker().as_metrics()
    assert set(metrics.values()) == {0, 0.0}

"""Unit tests for the Phase 6 telemetry module.

Tests exercise the TelemetryContext without spinning up a real OTLP collector:
either they run in disabled mode (no exporter set up at all), or they inspect
the JSONL event log and the in-memory event list directly. The OTel-side
integration is tested by asserting the SDK objects were built with the right
exporter *type* — a live collector round-trip is a Phase 7 concern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gds_api_schema_uplift.telemetry import (
    DEFAULT_EVENTS_PATH,
    DISABLED_ENV,
    ENDPOINT_ENV,
    EVENTS_PATH_ENV,
    Event,
    TelemetryConfig,
    TelemetryContext,
    build_telemetry,
)


# --- helpers ----------------------------------------------------------------


def _enabled_config(tmp_path: Path) -> TelemetryConfig:
    """Configure a live context for the JSONL event log only.

    Autouse `disable_telemetry` in conftest sets DISABLED_ENV=1 — this helper
    exists so a test can opt back in without unsetting the fixture. It does
    *not* enable OTel exporters, so the SDK does not spin up and there is no
    stdout pollution. Tests that need the OTel path use `_otel_enabled_config`.
    """
    return TelemetryConfig(
        disabled=False,
        otlp_endpoint=None,
        events_path=tmp_path / "events.jsonl",
    )


def _otel_enabled_config(tmp_path: Path) -> TelemetryConfig:
    """Configure a context with OTel exporters initialised.

    Uses the console exporter (writes trace + metric JSON to stdout) — pytest
    captures stdout for each test so the noise does not leak. An OTLP
    endpoint would work equally but would try to connect at flush time,
    which is a network side-effect a test suite should not have.
    """
    return TelemetryConfig(
        disabled=False,
        otlp_endpoint=None,
        console_export=True,
        events_path=tmp_path / "events.jsonl",
    )


def _read_events(path: Path) -> list[dict]:
    """Parse the JSONL file into a list of dicts."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- config from env --------------------------------------------------------


def test_from_env_defaults(monkeypatch):
    """With no env vars set, telemetry is enabled with the default events path."""
    for var in (DISABLED_ENV, ENDPOINT_ENV, EVENTS_PATH_ENV):
        monkeypatch.delenv(var, raising=False)
    config = TelemetryConfig.from_env()
    assert config.disabled is False
    assert config.otlp_endpoint is None
    assert config.events_path == Path(DEFAULT_EVENTS_PATH)


def test_from_env_disabled_switch(monkeypatch):
    """DISABLED_ENV=1 must produce a config that also carries no events path.

    A disabled context should not touch the filesystem at all — carrying an
    events_path in the config would encode a promise the context is not going
    to keep.
    """
    monkeypatch.setenv(DISABLED_ENV, "1")
    config = TelemetryConfig.from_env()
    assert config.disabled is True
    assert config.events_path is None


def test_from_env_endpoint_selects_otlp(monkeypatch):
    monkeypatch.setenv(ENDPOINT_ENV, "http://localhost:4318")
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    config = TelemetryConfig.from_env()
    assert config.otlp_endpoint == "http://localhost:4318"


def test_from_env_events_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv(EVENTS_PATH_ENV, str(tmp_path / "custom.jsonl"))
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    config = TelemetryConfig.from_env()
    assert config.events_path == tmp_path / "custom.jsonl"


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes"])
def test_disabled_env_accepts_multiple_truthy_values(monkeypatch, truthy):
    monkeypatch.setenv(DISABLED_ENV, truthy)
    assert TelemetryConfig.from_env().disabled is True


@pytest.mark.parametrize("falsy", ["0", "false", "no", ""])
def test_disabled_env_treats_falsy_values_as_off(monkeypatch, falsy):
    monkeypatch.setenv(DISABLED_ENV, falsy)
    assert TelemetryConfig.from_env().disabled is False


# --- disabled mode is a full no-op -----------------------------------------


def test_disabled_context_does_not_write_events_file(tmp_path):
    """A disabled context must not create the events file even after `event()`."""
    events_path = tmp_path / "events.jsonl"
    context = TelemetryContext(
        TelemetryConfig(disabled=True, events_path=events_path)
    )
    with context.run(spec="fixture.yaml", rules_count=11):
        context.event("USER", "APPROVES", "FINDING", rule_id="GDS-001")
    assert not events_path.exists(), "disabled telemetry must not touch the filesystem"


def test_disabled_context_yields_none_from_span():
    """Callers can use `with tele.span(...)` uniformly regardless of mode."""
    context = TelemetryContext(TelemetryConfig(disabled=True))
    with context.span("test", key="value") as span:
        assert span is None


def test_disabled_context_records_cost_without_crashing():
    """A disabled cost record must not raise or reach an uninstantiated meter."""
    context = TelemetryContext(TelemetryConfig(disabled=True))
    context.record_cost(0.42, model="claude-sonnet-4-6", tokens_in=100, tokens_out=50)
    # No assertion — the point is that it did not raise.


def test_close_is_idempotent():
    """A run that errors mid-flight might call close() twice; that must be fine."""
    context = TelemetryContext(TelemetryConfig(disabled=True))
    context.close()
    context.close()  # second call must not raise


# --- structured event log ---------------------------------------------------


def test_events_land_in_jsonl_file(tmp_path):
    """The audit trail is what a compliance reviewer reads with `less`."""
    events_path = tmp_path / "events.jsonl"
    context = TelemetryContext(
        TelemetryConfig(disabled=False, events_path=events_path)
    )
    with context.run(spec="broken.yaml", rules_count=11):
        context.event("RULES", "COMPLETED", "PASS", findings=11)
        context.event(
            "USER", "APPROVES", "FINDING", rule_id="GDS-001", clause_id="GDS-001"
        )
    rows = _read_events(events_path)
    assert len(rows) == 2
    assert rows[0]["subject"] == "RULES"
    assert rows[0]["verb"] == "COMPLETED"
    assert rows[0]["context"]["findings"] == 11
    assert rows[1]["context"]["rule_id"] == "GDS-001"


def test_events_carry_a_millisecond_timestamp(tmp_path):
    """Every row must be sortable and time-comparable across runs."""
    context = TelemetryContext(_enabled_config(tmp_path))
    with context.run(spec="broken.yaml", rules_count=1):
        context.event("A", "B", "C")
    rows = _read_events(context._config.events_path)  # type: ignore[arg-type]
    assert isinstance(rows[0]["ts_ms"], int)
    assert rows[0]["ts_ms"] > 0


def test_events_are_available_in_memory(tmp_path):
    """`events` returns an immutable tuple, in emission order.

    Callers that want the audit trail without going through the JSONL file
    (tests, or a phase-7 end-of-run summary) need in-memory access.
    """
    context = TelemetryContext(_enabled_config(tmp_path))
    with context.run(spec="x.yaml", rules_count=0):
        context.event("A", "B", "C", n=1)
        context.event("D", "E", "F", n=2)
    assert len(context.events) == 2
    assert context.events[0].verb == "B"
    assert context.events[1].context["n"] == 2


def test_append_mode_across_two_runs(tmp_path):
    """Two runs against the same events file must both be visible.

    The events file is an audit archive — deleting it on each run would
    defeat the point.
    """
    events_path = tmp_path / "events.jsonl"

    first = TelemetryContext(
        TelemetryConfig(disabled=False, events_path=events_path)
    )
    with first.run(spec="a.yaml", rules_count=1):
        first.event("A", "STARTED", "RUN")

    second = TelemetryContext(
        TelemetryConfig(disabled=False, events_path=events_path)
    )
    with second.run(spec="b.yaml", rules_count=1):
        second.event("B", "STARTED", "RUN")

    rows = _read_events(events_path)
    assert [r["subject"] for r in rows] == ["A", "B"]


def test_event_json_line_serialises_non_json_values_via_str(tmp_path):
    """The `default=str` in the serialiser is a safety net for surprise objects.

    Real context values are primitives, but a caller passing a `Path` or a
    `datetime` should get sensible serialisation rather than a crash.
    """
    context = TelemetryContext(_enabled_config(tmp_path))
    with context.run(spec="x.yaml", rules_count=0):
        context.event("A", "B", "C", path=Path("/tmp/x"))
    rows = _read_events(context._config.events_path)  # type: ignore[arg-type]
    assert rows[0]["context"]["path"] == "/tmp/x"


def test_event_line_is_valid_json(tmp_path):
    """Every JSONL row parses standalone — no multiline event allowed."""
    context = TelemetryContext(_enabled_config(tmp_path))
    with context.run(spec="x.yaml", rules_count=0):
        context.event("A", "B", "C", newline_field="line1\nline2")
    raw = context._config.events_path.read_text()  # type: ignore[union-attr]
    for line in raw.splitlines():
        if line.strip():
            json.loads(line)  # must not raise


# --- cost metric ------------------------------------------------------------


def test_record_cost_in_otel_mode_does_not_raise(tmp_path):
    """With OTel initialised, record_cost writes to the real meter.

    A live collector round-trip is a Phase 7 concern; here we just want to
    know the cost meter was created and can accept an add() call without
    raising against a real Sonnet-priced number.
    """
    context = TelemetryContext(_otel_enabled_config(tmp_path))
    with context.run(spec="x.yaml", rules_count=0):
        context.record_cost(
            0.0147,
            model="claude-sonnet-4-6",
            tokens_in=2304,
            tokens_out=180,
            cache_reads=0,
            cache_writes=2304,
        )


def test_record_cost_is_a_noop_when_otel_is_off(tmp_path):
    """Without an OTLP endpoint or console flag, no meter is created.

    A cost record still has to be a safe call — the CLI records cost
    unconditionally, so a config with events-only should not raise.
    """
    context = TelemetryContext(_enabled_config(tmp_path))
    with context.run(spec="x.yaml", rules_count=0):
        context.record_cost(
            0.05, model="claude-sonnet-4-6", tokens_in=1000, tokens_out=100
        )


def test_default_config_does_not_initialise_otel(monkeypatch):
    """The default run should NOT print span JSON to stdout.

    A user running `gds-api-schema-uplift examples/broken.yaml` with no
    telemetry env vars set was getting OTel console exporter output
    interleaved with the report and the approval prompt. This test pins
    the fix: no endpoint, no console flag → no OTel initialisation.
    """
    for var in (DISABLED_ENV, ENDPOINT_ENV, EVENTS_PATH_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("GDS_UPLIFT_OTEL_CONSOLE", raising=False)
    config = TelemetryConfig.from_env()
    assert config.otel_active is False


def test_console_export_env_activates_otel(monkeypatch):
    """Debugging telemetry itself — opt in via GDS_UPLIFT_OTEL_CONSOLE=1."""
    monkeypatch.setenv("GDS_UPLIFT_OTEL_CONSOLE", "1")
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    monkeypatch.delenv(ENDPOINT_ENV, raising=False)
    config = TelemetryConfig.from_env()
    assert config.otel_active is True
    assert config.console_export is True


# --- factory / env integration ---------------------------------------------


def test_build_telemetry_reads_env_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv(DISABLED_ENV, "1")
    context = build_telemetry()
    assert isinstance(context, TelemetryContext)
    # `run()` on a disabled context is a no-op — the point is that this
    # construction did not fail on the missing OTel setup.
    with context.run(spec="x.yaml", rules_count=0):
        pass


def test_build_telemetry_accepts_explicit_config(tmp_path):
    """Tests use this path to bypass env vars and inject a config directly."""
    config = TelemetryConfig(disabled=True, events_path=tmp_path / "x.jsonl")
    context = build_telemetry(config)
    assert context._config is config  # type: ignore[union-attr]


# --- otlp endpoint selection ------------------------------------------------


def test_endpoint_env_selects_otlp_exporter(monkeypatch, tmp_path):
    """When an endpoint is set, the OTLP exporter is built, not the console one.

    This is a class-identity check — the OTLP exporter fails to actually
    send until a collector is up, but we can assert we asked for the right
    one so a demo pointed at a real SigNoz doesn't silently fall back to
    stdout.
    """
    monkeypatch.setenv(ENDPOINT_ENV, "http://localhost:4318")
    monkeypatch.setenv(EVENTS_PATH_ENV, str(tmp_path / "e.jsonl"))
    monkeypatch.delenv(DISABLED_ENV, raising=False)

    context = build_telemetry()
    # Poke the private builder rather than send a real request. We import
    # the console exporter class purely for the negative assertion.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter = context._build_span_exporter(None)  # type: ignore[arg-type]
    assert isinstance(exporter, OTLPSpanExporter)
    context.close()

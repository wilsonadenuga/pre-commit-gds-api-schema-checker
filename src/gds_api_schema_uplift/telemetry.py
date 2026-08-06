"""OpenTelemetry integration and the structured event log.

Phase 6. Wraps OTel SDK setup behind a `TelemetryContext` that:

- Creates a per-run root span with child spans around the rule pass, each
  agent call, and each approval decision.
- Emits structured events (`subject/verb/object/context`) as JSON lines to a
  local file, mirrored onto the current span as span-events for the OTel
  side. The JSON lines are the audit trail a developer can `jq` and a
  stakeholder can read; the span-events keep the same information visible in
  a trace viewer.
- Records LLM cost as an OTel gauge metric alongside the printed summary in
  `cost.py`.

## Exporters

By default, **OTel is not initialised at all**. The JSONL event log runs
either way — it is the primary audit trail. OTel exporters spin up only
when the run has an actual place to send data:

- **OTLP** — set `GDS_UPLIFT_OTEL_ENDPOINT` to an OTLP HTTP collector URL
  (SigNoz default is `http://localhost:4318`). Traces and metrics ship
  there via `opentelemetry-exporter-otlp`.
- **Console JSON** — set `GDS_UPLIFT_OTEL_CONSOLE=1` to write spans and
  metrics to stdout via the OTel SDK's `Console*Exporter`. This mode is
  for debugging telemetry itself; it is *not* the default because span
  JSON interleaves with the CLI report and would trash an interactive
  approval loop.

## Kill switch

`GDS_UPLIFT_OTEL_DISABLED=1` returns a fully-disabled context — every
method callable, nothing recorded, no OTel SDK touched, no JSONL file
opened. Tests default to this via conftest; CI runners can flip it when
they must not emit at all.

## Why the JSON-lines event log is separate from OTel

The `subject/verb/object/context` shape is PLAN's audit trail: rows a
compliance reviewer can read. OTel span-events carry the same data on the
trace side (so the SigNoz UI shows them), but JSON-lines is the interface a
human sits down and reads with `less` or `jq`. Making OTel the only sink
would hide the audit trail behind a running collector, and that would be a
Phase-6 own-goal against the "SigNoz might not come up" risk.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: When set to anything truthy, telemetry is a full no-op. Tests use this.
DISABLED_ENV = "GDS_UPLIFT_OTEL_DISABLED"

#: OTLP HTTP endpoint (e.g. `http://localhost:4318`) — enables the SigNoz path.
ENDPOINT_ENV = "GDS_UPLIFT_OTEL_ENDPOINT"

#: When set truthy, initialise OTel with **console** exporters — writes spans
#: and metrics to stdout as JSON. Off by default because an interactive run
#: with console exporters on is unusable (span JSON interleaves with the
#: report and the approval prompt). Set this only when debugging telemetry.
CONSOLE_EXPORT_ENV = "GDS_UPLIFT_OTEL_CONSOLE"

#: Where the structured event log is written. Default is a JSONL file in the
#: current directory; a dev who tails it during a demo sees the run unfold live.
EVENTS_PATH_ENV = "GDS_UPLIFT_EVENTS_PATH"
DEFAULT_EVENTS_PATH = "gds-uplift-events.jsonl"

#: Instrumentation identity. Kept short — appears in every trace.
INSTRUMENTATION_NAME = "gds-api-schema-uplift"
INSTRUMENTATION_VERSION = "0.1.0"


def _is_truthy(value: str | None) -> bool:
    """Match the `_llm_disabled` convention from cli.py — any non-false-ish value."""
    if value is None:
        return False
    return value.strip().lower() not in ("", "0", "false", "no")


@dataclass(slots=True)
class TelemetryConfig:
    """Resolved telemetry configuration for one run.

    Built from `TelemetryConfig.from_env()` in the CLI, or hand-constructed in
    tests. Kept as a dataclass so tests can flip one field without threading a
    dozen kwargs through the factory.

    `otel_active` — True when we should initialise OTel exporters — is derived
    rather than stored so the check "is anything asking for OTel?" is a single
    truth centralised on the config.
    """

    disabled: bool = False
    otlp_endpoint: str | None = None
    console_export: bool = False
    events_path: Path | None = None

    @property
    def otel_active(self) -> bool:
        """True when OTel infrastructure should be initialised for this run.

        OTel only spins up when there is somewhere for its output to land —
        either an OTLP endpoint (SigNoz) or an explicit request for console
        exporters (debugging). Otherwise a default `gds-api-schema-uplift`
        run would splatter span JSON across an interactive terminal.
        """
        if self.disabled:
            return False
        return bool(self.otlp_endpoint) or self.console_export

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelemetryConfig:
        """Read the four env vars documented in the module docstring."""
        env = env if env is not None else os.environ
        disabled = _is_truthy(env.get(DISABLED_ENV))
        endpoint = env.get(ENDPOINT_ENV) or None
        console_export = _is_truthy(env.get(CONSOLE_EXPORT_ENV))
        events = env.get(EVENTS_PATH_ENV) or DEFAULT_EVENTS_PATH
        return cls(
            disabled=disabled,
            otlp_endpoint=endpoint,
            console_export=console_export,
            events_path=Path(events) if not disabled else None,
        )


# --- events ------------------------------------------------------------------


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class Event:
    """One structured audit-trail row.

    Fields chosen to match PLAN Phase 6:
    `USER / APPROVES / FINDING / {rule_id, clause_id, ...}`.

    Kept as a dataclass rather than a dict so a typo in a caller
    (`context="..."` vs `contexts="..."`) fails at construction, not silently
    at serialisation.
    """

    subject: str
    verb: str
    object: str
    context: Mapping[str, Any]
    timestamp_ms: int

    def to_json_line(self) -> str:
        payload = {
            "ts_ms": self.timestamp_ms,
            "subject": self.subject,
            "verb": self.verb,
            "object": self.object,
            "context": dict(self.context),
        }
        return json.dumps(payload, sort_keys=True, default=str)


# --- the context -------------------------------------------------------------


class TelemetryContext:
    """The observability surface for one CLI run.

    Only method a caller must remember to call is `close()`, which flushes
    pending spans/metrics and closes the events file. `TelemetryContext.run()`
    yields a context manager that guarantees it.
    """

    def __init__(self, config: TelemetryConfig) -> None:
        self._config = config
        self._events_file: Any = None  # lazily opened on first event
        self._events: list[Event] = []
        self._tracer: Any = None
        self._meter: Any = None
        self._provider: Any = None
        self._meter_provider: Any = None
        self._cost_meter: Any = None
        self._active_root_span: Any = None
        self._closed = False

        # OTel is only initialised when there is somewhere for spans and
        # metrics to go. A run with no OTLP endpoint and no console flag
        # gets the JSONL event log but *no* OTel exporters — that keeps
        # interactive terminals free of console-export JSON while
        # preserving the audit trail.
        if config.otel_active:
            self._initialise_otel()

    # -- otel setup ---------------------------------------------------------

    def _initialise_otel(self) -> None:
        """Build a fresh tracer + meter for this run.

        Local imports keep the OTel SDK's startup cost off the deterministic
        path — a `--no-llm` invocation with telemetry disabled must not pay
        for imports it never uses. The SDK also has a habit of dumping
        warnings when the same provider is set twice; we sidestep that by
        making our provider local to this context rather than global.
        """
        # These imports are deliberately inside the method so a disabled
        # context does not touch them. The SDK cold-import is ~50ms.
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        resource = Resource.create(
            {
                "service.name": INSTRUMENTATION_NAME,
                "service.version": INSTRUMENTATION_VERSION,
            }
        )

        # Traces
        provider = TracerProvider(resource=resource)
        span_exporter = self._build_span_exporter(ConsoleSpanExporter)
        provider.add_span_processor(BatchSpanProcessor(span_exporter))
        self._provider = provider
        self._tracer = trace.get_tracer(
            INSTRUMENTATION_NAME,
            INSTRUMENTATION_VERSION,
            tracer_provider=provider,
        )

        # Metrics
        metric_exporter = self._build_metric_exporter(ConsoleMetricExporter)
        reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(metric_readers=[reader], resource=resource)
        self._meter_provider = meter_provider
        self._meter = metrics.get_meter(
            INSTRUMENTATION_NAME,
            INSTRUMENTATION_VERSION,
            meter_provider=meter_provider,
        )
        self._cost_meter = self._meter.create_counter(
            "gds_uplift.llm.cost_usd",
            unit="USD",
            description="LLM spend per call, keyed by model and cache status.",
        )

    def _build_span_exporter(self, console_cls: Any) -> Any:
        """Return the OTLP exporter if an endpoint is set, else console-JSON.

        The console exporter is the default because it works everywhere,
        offline, without a collector — which is the fallback PLAN calls for
        against the medium-risk of SigNoz not coming up in a demo venue.
        """
        if self._config.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            return OTLPSpanExporter(endpoint=f"{self._config.otlp_endpoint}/v1/traces")
        return console_cls()

    def _build_metric_exporter(self, console_cls: Any) -> Any:
        if self._config.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            return OTLPMetricExporter(endpoint=f"{self._config.otlp_endpoint}/v1/metrics")
        return console_cls()

    # -- root span lifecycle ------------------------------------------------

    def start_run(self, *, spec: str, rules_count: int) -> None:
        """Open the root span for this run. Idempotent — safe to call twice.

        No-op when OTel is not initialised (no endpoint, no console flag) —
        the JSONL event log still records the run implicitly via events,
        and calling `start_run` on an events-only context must not crash.
        """
        if not self._config.otel_active or self._active_root_span is not None:
            return
        if self._tracer is None:  # belt-and-braces
            return
        span = self._tracer.start_span(
            "gds-uplift.run",
            attributes={"spec.path": spec, "rules.count": rules_count},
        )
        self._active_root_span = span

    # -- spans --------------------------------------------------------------

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Any]:
        """Open a child span within the current run.

        No-op when OTel is not initialised (disabled, or no endpoint /
        console flag set): yields None so callers can write
        `with telemetry.span(...): ...` unconditionally.
        """
        if self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span

    # -- events -------------------------------------------------------------

    def event(
        self,
        subject: str,
        verb: str,
        object_: str,
        /,
        **context: Any,
    ) -> None:
        """Emit a structured audit-trail row.

        Goes to (a) the in-memory event list, (b) the JSONL file at
        `events_path`, and (c) — if a span is active — an OTel span event on
        the current span so trace viewers see it too. The three sinks are
        redundant deliberately: a demo running without SigNoz still shows the
        audit trail in the local file, and a JSONL-only environment (e.g.
        piping through jq) still captures every action.
        """
        evt = Event(
            subject=subject,
            verb=verb,
            object=object_,
            context=dict(context),
            timestamp_ms=_now_ms(),
        )
        self._events.append(evt)
        self._append_to_events_file(evt)
        self._add_to_current_span(evt)

    def _append_to_events_file(self, evt: Event) -> None:
        if self._config.disabled or self._config.events_path is None:
            return
        if self._events_file is None:
            # Append mode: multiple runs against the same file build up an
            # audit archive rather than overwriting. Truncation is a demo
            # concern (Phase 7), not a Phase 6 one.
            self._events_file = self._config.events_path.open("a", encoding="utf-8")
        self._events_file.write(evt.to_json_line() + "\n")
        self._events_file.flush()

    def _add_to_current_span(self, evt: Event) -> None:
        if self._tracer is None:
            return
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            span = self._active_root_span
        if span is None or not getattr(span, "is_recording", lambda: False)():
            return
        # Span-event attributes must be primitive-typed. Coerce nested values
        # to a JSON string so a rich `context={...}` still lands intact.
        attrs = {
            "subject": evt.subject,
            "verb": evt.verb,
            "object": evt.object,
            "context.json": json.dumps(evt.context, default=str),
        }
        span.add_event(f"{evt.subject}/{evt.verb}/{evt.object}", attributes=attrs)

    # -- cost metric --------------------------------------------------------

    def record_cost(
        self,
        cost_usd: float,
        *,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cache_reads: int = 0,
        cache_writes: int = 0,
    ) -> None:
        """Ship one LLM-call cost as an OTel counter increment.

        Alongside the printed `cost.py` summary. Keyed by model + a few
        attributes so a SigNoz dashboard can filter and sum meaningfully.
        """
        if self._config.disabled or self._cost_meter is None:
            return
        self._cost_meter.add(
            cost_usd,
            attributes={
                "model": model,
                "tokens.in": tokens_in,
                "tokens.out": tokens_out,
                "cache.reads": cache_reads,
                "cache.writes": cache_writes,
            },
        )

    # -- lifecycle helpers --------------------------------------------------

    @property
    def events(self) -> tuple[Event, ...]:
        """In-memory events, for tests and end-of-run summaries."""
        return tuple(self._events)

    @property
    def events_path(self) -> Path | None:
        """Where the JSONL log is being written, if enabled."""
        return None if self._config.disabled else self._config.events_path

    def close(self) -> None:
        """Flush and shut down all exporters. Safe to call twice.

        Called from `run()`'s context manager and idempotent so a caller can
        `close()` after a bail-out without worrying whether it already ran.
        """
        if self._closed:
            return
        self._closed = True
        if self._active_root_span is not None:
            self._active_root_span.end()
            self._active_root_span = None
        if self._events_file is not None:
            try:
                self._events_file.close()
            except Exception:  # noqa: BLE001 - close errors on shutdown are inert
                pass
            self._events_file = None
        if self._provider is not None:
            try:
                self._provider.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if self._meter_provider is not None:
            try:
                self._meter_provider.shutdown()
            except Exception:  # noqa: BLE001
                pass

    @contextmanager
    def run(self, *, spec: str, rules_count: int) -> Iterator[TelemetryContext]:
        """Root-span context manager. Ensures `close()` regardless of outcome."""
        self.start_run(spec=spec, rules_count=rules_count)
        try:
            yield self
        finally:
            self.close()


# --- factory + no-op ---------------------------------------------------------


def build_telemetry(
    config: TelemetryConfig | None = None,
) -> TelemetryContext:
    """Construct a TelemetryContext with either the given or env-derived config.

    A single entrypoint for the CLI: `build_telemetry()` reads env vars and
    hands back a working (or no-op) context. Tests pass a hand-built config.
    """
    resolved = config if config is not None else TelemetryConfig.from_env()
    return TelemetryContext(resolved)

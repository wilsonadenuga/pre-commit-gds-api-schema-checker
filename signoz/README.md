# SigNoz for `gds-api-schema-uplift`

Optional observability backend. The tool works without SigNoz — telemetry
falls back to a JSONL event log and console-JSON exporters (see the
"Console-JSON fallback" section below). Turn SigNoz on when you want
traces, metrics, and events aggregated across many runs on a dashboard.

## Bring up SigNoz

SigNoz publishes its own Docker Compose stack. Rather than vendoring their
compose file (which is fifteen services and evolves), we point at their
official quickstart:

```bash
git clone --depth=1 https://github.com/SigNoz/signoz.git /tmp/signoz
cd /tmp/signoz/deploy/docker
docker compose up -d
```

The UI lands at http://localhost:8080. The OTLP HTTP endpoint the tool
targets is http://localhost:4318 (the compose file exposes it by default).

Wait ~60 seconds for ClickHouse to warm up before running the tool — a
premature run silently drops spans while the collector is still starting.

## Point the CLI at SigNoz

Set one environment variable and re-run:

```bash
export GDS_UPLIFT_OTEL_ENDPOINT=http://localhost:4318
gds-api-schema-uplift examples/broken.yaml
```

Every run now sends spans and metrics to SigNoz. The JSONL event log is
still written to `gds-uplift-events.jsonl` in the current directory —
redundant by design so a network hiccup or a SigNoz restart never loses
the audit trail.

## What you should see

- **Traces** — one trace per CLI invocation, root span `gds-uplift.run`
  with child spans `rules.deterministic_pass`, `agent.pass`, and (if the
  developer approved patches) `rules.recheck_after_approval`.
- **Metrics** — `gds_uplift.llm.cost_usd` counter, one point per agent
  pass, tagged with model + token counts + cache attributes.
- **Events** — attached to spans as span-events, with attributes
  `subject`, `verb`, `object`, and `context.json`. The same rows are also
  in the local `gds-uplift-events.jsonl` file.

## Suggested dashboard panels (build in SigNoz UI)

1. **Findings per run** — count of `RULES/COMPLETED/PASS` events, grouped
   by hour. Line chart. Answers "is compliance improving?".
2. **Cost per run** — sum of `gds_uplift.llm.cost_usd` grouped by
   `service.name` and time bucket. Bar chart. FinOps talking point.
3. **Agent latency** — `agent.pass` span duration p50 / p95. Line chart.
   Watch when this drifts up (a stakeholder demo dragging past 30 seconds
   is a Phase 8 hint we need Haiku triage in the loop).

## Console-JSON fallback

Turn off `GDS_UPLIFT_OTEL_ENDPOINT` (or unset it entirely) and the
exporters revert to console-JSON. Spans and metrics stream to stdout as
JSON; the audit trail lives in `gds-uplift-events.jsonl`. That mode is
what makes the tool robust to a demo venue where Docker isn't available
or where the SigNoz stack doesn't come up in time.

To disable telemetry entirely (for tests or CI where telemetry noise is
unwelcome), set `GDS_UPLIFT_OTEL_DISABLED=1`. Every telemetry call becomes
a no-op; no files are written; no OTel SDK is initialised.

## Shutting down

```bash
cd /tmp/signoz/deploy/docker
docker compose down
```

Add `-v` to also remove the ClickHouse volumes if you want a clean slate
between demo rehearsals.

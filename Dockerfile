# Two-stage build. Stage 1 (`builder`) resolves the environment with `uv` from
# the official image; stage 2 (`runtime`) copies just the venv and source into
# a slim Python base. The final image is ~200 MB and contains no build tools.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Layer the dependency install so a source-only change re-uses the cached deps.
COPY pyproject.toml README.md ./
RUN mkdir -p src/gds_api_schema_uplift \
    && touch src/gds_api_schema_uplift/__init__.py \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python .

COPY src/ ./src/
COPY standards.yaml ./
RUN uv pip install --python /app/.venv/bin/python --no-deps -e .


FROM python:3.12-slim-bookworm AS runtime

# `curl` is here for a quick liveness probe inside the container; drop it if
# you deploy this behind a supervisor that pings from outside.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/standards.yaml /app/standards.yaml
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:${PATH}"

# The CLI is the entrypoint; a bare `docker run <image>` prints help.
# `docker run -v $(pwd)/openapi.yaml:/spec.yaml <image> /spec.yaml` runs
# against a mounted spec. `--no-apply` is a good default under `docker run`
# because container stdin is often not interactive.
ENTRYPOINT ["gds-api-schema-uplift"]
CMD ["--help"]

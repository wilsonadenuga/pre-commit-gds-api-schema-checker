.DEFAULT_GOAL := help
SHELL := /bin/bash

# uv is the intended toolchain (PRD s9.1). It is not always present, so every target
# falls back to stdlib venv + pip rather than failing. `make setup` reports which
# path it took.
UV := $(shell command -v uv 2>/dev/null)
VENV := .venv
PY := $(VENV)/bin/python
SPEC ?= examples/broken.yaml

.PHONY: help setup test demo demo-good clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the environment and install the CLI (editable)
ifdef UV
	@echo "==> uv found at $(UV)"
	uv venv $(VENV)
	uv pip install --python $(PY) -e '.[dev]'
else
	@echo "==> uv not found; falling back to venv + pip."
	@echo "    Install uv for faster setup: https://docs.astral.sh/uv/getting-started/installation/"
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e '.[dev]'
endif
	@echo "==> done. CLI: $(VENV)/bin/gds-api-schema-uplift"

test: ## Run the test suite
	$(PY) -m pytest -q

demo: ## Run the checker against the deliberately broken fixture
	-$(VENV)/bin/gds-api-schema-uplift $(SPEC)

demo-good: ## Run the checker against the compliant fixture (expect zero findings)
	$(VENV)/bin/gds-api-schema-uplift examples/good.yaml

clean: ## Remove the environment and caches
	rm -rf $(VENV) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

"""Suite-wide safety rails.

The agent pass runs by default in the CLI, so a developer or CI runner with
`ANTHROPIC_API_KEY` in the environment would otherwise make real, billable API calls
every time the CLI tests invoke the tool. That happened once during development: a
full suite run took three minutes and spent real tokens instead of two seconds and
none.

Both fixtures below are `autouse`, so this cannot be forgotten in a new test module.
Tests that exercise the agent inject a stub `MessageCreator` and never touch these.
"""

from __future__ import annotations

import pytest

from gds_api_schema_uplift.cli import NO_LLM_ENV
from gds_api_schema_uplift.telemetry import DISABLED_ENV as TELEMETRY_DISABLED_ENV


@pytest.fixture(autouse=True)
def disable_llm_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the CLI's agent pass off for every test."""
    monkeypatch.setenv(NO_LLM_ENV, "1")


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force telemetry off in tests.

    Without this, every CLI test would write to `gds-uplift-events.jsonl` in
    the working directory and start OTel exporters that print JSON to
    stdout — polluting `runner.invoke` output and leaving files behind.
    Tests that exercise the telemetry module inject a hand-built config and
    do not touch this fixture.
    """
    monkeypatch.setenv(TELEMETRY_DISABLED_ENV, "1")


@pytest.fixture(autouse=True)
def no_real_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt and braces: make constructing a real client fail loudly.

    `disable_llm_pass` should mean this never fires. If it does, a code path has
    started building a client without consulting the kill switch, and a hard failure
    naming that path is far better than a silent bill.
    """

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "A test tried to construct a real Anthropic client. Inject a stub "
            "MessageCreator instead — see tests/test_agent_client.py."
        )

    monkeypatch.setattr(
        "gds_api_schema_uplift.agent.client.build_messages_api", _refuse
    )

"""No rule may raise on a structurally odd document.

`_traversal` promises fewer findings, never an exception. This matters because the
tool runs in a pre-commit hook: a traceback there blocks a developer's commit with a
stack trace instead of a compliance report, which is worse than reporting nothing.

Schema validity is the version gate's and the spec validator's job. A rule handed a
scalar where it expected a mapping must shrug, not crash.
"""

from __future__ import annotations

import pytest
from example_specs import minimal_spec_body, write_spec

from gds_api_schema_uplift.loader import load_spec
from gds_api_schema_uplift.rules import REGISTRY, run_deterministic_pass

#: Documents that parse as YAML and pass the loader, but swap a mapping or sequence
#: the rules expect for a scalar or null.
ODD_SPEC_BODIES = {
    "paths-is-scalar": "paths: nonsense\n",
    "path-item-is-scalar": "paths:\n  /a: 5\n",
    "responses-is-scalar": "paths:\n  /a:\n    get:\n      responses: 7\n",
    "content-is-scalar": (
        "paths:\n  /a:\n    get:\n      responses:\n        '200': {content: 3}\n"
    ),
    "servers-is-scalar": "servers: 4\npaths: {}\n",
    "servers-is-list-of-scalars": "servers: [1, 2]\npaths: {}\n",
    "schema-is-scalar": (
        "paths:\n  /a:\n    post:\n      requestBody:\n        content:\n"
        "          application/json: {schema: 9}\n      responses: {}\n"
    ),
    "components-is-scalar": "paths: {}\ncomponents: 2\n",
    "schema-is-null": (
        "paths:\n  /a:\n    get:\n      responses:\n        '500':\n"
        "          content:\n            application/json:\n              schema:\n"
    ),
    "no-paths-key": "info2: {}\n",
    "ref-cycle": (
        "paths: {}\ncomponents:\n  schemas:\n"
        "    A: {$ref: '#/components/schemas/B'}\n"
        "    B: {$ref: '#/components/schemas/A'}\n"
    ),
    "operation-is-scalar": "paths:\n  /a:\n    get: 3\n",
    "properties-is-scalar": (
        "paths: {}\ncomponents:\n  schemas:\n    A: {type: object, properties: 5}\n"
    ),
}


@pytest.mark.parametrize("name", sorted(ODD_SPEC_BODIES))
def test_no_rule_raises_on_an_odd_spec(tmp_path, name):
    body = minimal_spec_body(ODD_SPEC_BODIES[name])
    spec = load_spec(write_spec(tmp_path, body, f"{name}.yaml"))
    for rule_id, rule in sorted(REGISTRY.items()):
        try:
            rule.checker(spec)
        except Exception as exc:  # noqa: BLE001 - the assertion *is* "does not raise"
            pytest.fail(f"{rule_id} raised on {name}: {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("name", sorted(ODD_SPEC_BODIES))
def test_the_whole_pass_survives_an_odd_spec(tmp_path, name):
    body = minimal_spec_body(ODD_SPEC_BODIES[name])
    spec = load_spec(write_spec(tmp_path, body, f"{name}.yaml"))
    run_deterministic_pass(spec)  # must not raise


def test_an_odd_spec_yields_no_findings_rather_than_junk_ones(tmp_path):
    """Degrading to silence is correct; degrading to noise is not."""
    spec = load_spec(write_spec(tmp_path, minimal_spec_body("paths: nonsense\n")))
    assert run_deterministic_pass(spec) == []

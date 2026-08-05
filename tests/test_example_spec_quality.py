"""The example specs are test infrastructure, so they get their own tests.

M1 ("zero false positives on the sample compliant spec") and the "false positives
erode trust" risk in PRD s11 are both won or lost in these two files rather than in
the rule code. A fixture that drifts silently invalidates every rule test that
depends on it.
"""

from __future__ import annotations

import pytest
from example_specs import BROKEN_SPEC, GOOD_SPEC

from gds_api_schema_uplift.loader import load_spec


@pytest.mark.parametrize("path", [BROKEN_SPEC, GOOD_SPEC], ids=["broken", "good"])
def test_example_spec_is_structurally_valid_openapi(path):
    """Violations must be standards violations, not schema errors.

    A schema-invalid broken.yaml would fail before any rule ran, so the rules would
    be exercised against nothing.
    """
    validator = pytest.importorskip(
        "openapi_spec_validator", reason="openapi-spec-validator not installed"
    )
    # Round-trip structures are dict/list subclasses, so the validator accepts them.
    validator.validate(load_spec(path).data)


def test_good_spec_round_trips_byte_identically():
    """good.yaml is the round-trip fixture, so it must survive load -> dump unchanged.

    This caught a real defect when first written: ruamel's default dumper flattens
    block-sequence indentation, which would have reindented a developer's whole file
    on every patch write.
    """
    assert load_spec(GOOD_SPEC).dumps() == GOOD_SPEC.read_text()


def test_broken_spec_round_trips_byte_identically():
    assert load_spec(BROKEN_SPEC).dumps() == BROKEN_SPEC.read_text()


def test_the_two_specs_describe_the_same_service():
    """They must differ only in compliance, not in subject matter.

    Otherwise a rule passes on good.yaml for the wrong reason — because the relevant
    construct is absent rather than correct.
    """
    broken, good = load_spec(BROKEN_SPEC).data, load_spec(GOOD_SPEC).data
    assert broken["info"]["title"] == good["info"]["title"]
    assert len(broken["paths"]) == len(good["paths"]) == 1
    broken_ops = set(next(iter(broken["paths"].values())))
    good_ops = set(next(iter(good["paths"].values())))
    assert broken_ops == good_ops == {"get", "post"}


def test_both_specs_declare_the_constructs_every_rule_needs():
    """Guards the "absent rather than correct" failure directly.

    Each rule needs its subject matter to exist in good.yaml for a zero-findings
    result to mean anything. If `servers` vanished, GDS-001 would pass vacuously.
    """
    good = load_spec(GOOD_SPEC).data
    assert good.get("servers"), "GDS-001 needs servers to exist"
    assert good.get("security"), "NCSC-002 will need a declared security requirement"
    schemes = good.get("components", {}).get("securitySchemes")
    assert schemes, "NCSC-001 will need securitySchemes to exist"
    operations = next(iter(good["paths"].values()))
    post = operations["post"]
    assert "requestBody" in post, "GDS-002/NCSC-003 need a request body"
    assert "429" in post["responses"], "NCSC-004 will need a 429 to exist"

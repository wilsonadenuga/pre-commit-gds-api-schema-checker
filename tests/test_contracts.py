"""The contracts are frozen — these tests are the freeze.

If a change here needs a test edited rather than added, that is the signal that the
rule engine and the agent are about to be integrated twice. See PLAN.md Phase 0.
"""

from __future__ import annotations

import dataclasses

import pytest

from gds_api_schema_uplift.contracts import (
    Authority,
    Finding,
    Patch,
    PatchOp,
    RuleType,
    Severity,
)


def test_severity_values():
    assert [s.value for s in Severity] == ["error", "warning", "suggestion"]


def test_rule_type_values():
    assert [t.value for t in RuleType] == ["deterministic", "llm"]


def test_authority_values():
    assert [a.value for a in Authority] == ["standard", "recommendation"]


def test_finding_fields_are_exactly_the_frozen_set():
    """Freeze the field list — a new field means updating every renderer.

    `line` and `column` were added in Phase 7 for editor-clickable source
    positions; the resolver populates them post-hoc, and both are optional
    with a `None` default so a rule can still hand-construct a Finding
    without knowing about the resolver.
    """
    assert [f.name for f in dataclasses.fields(Finding)] == [
        "rule_id",
        "severity",
        "location",
        "snippet",
        "clause_id",
        "rule_type",
        "line",
        "column",
    ]


def test_finding_is_immutable():
    finding = Finding(
        rule_id="GDS-001",
        severity=Severity.ERROR,
        location="$.servers[0].url",
        snippet="http://api.example.gov.uk",
        clause_id="GDS-001",
        rule_type=RuleType.DETERMINISTIC,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.severity = Severity.WARNING  # type: ignore[misc]


def test_patch_op_renders_rfc6902_with_value():
    op = PatchOp(op="replace", path="/servers/0/url", value="https://api.example.gov.uk")
    assert op.to_rfc6902() == {
        "op": "replace",
        "path": "/servers/0/url",
        "value": "https://api.example.gov.uk",
    }


def test_patch_op_omits_value_for_remove():
    op = PatchOp(op="remove", path="/components/securitySchemes/basicAuth")
    assert op.to_rfc6902() == {
        "op": "remove",
        "path": "/components/securitySchemes/basicAuth",
    }


def test_patch_op_emits_from_under_its_wire_name():
    op = PatchOp(op="move", path="/b", from_="/a")
    rendered = op.to_rfc6902()
    assert rendered["from"] == "/a"
    assert "from_" not in rendered


def test_patch_renders_op_list():
    patch = Patch(
        ops=(
            PatchOp(op="replace", path="/servers/0/url", value="https://x.gov.uk"),
            PatchOp(op="remove", path="/paths/~1getUserList/get/security"),
        ),
        rationale="Plaintext transport and an unauthenticated operation.",
        clause_quote="APIs must be served over HTTPS.",
    )
    rendered = patch.to_rfc6902()
    assert [op["op"] for op in rendered] == ["replace", "remove"]
    assert "value" not in rendered[1]


def test_empty_patch_is_valid_and_renders_empty():
    assert Patch().to_rfc6902() == []

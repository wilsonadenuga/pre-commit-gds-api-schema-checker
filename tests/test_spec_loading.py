"""Loading a spec from disk, and the version policy that gates it.

Covers `loader.load_spec` failure modes and `loader.version_gate` (PRD s7.3:
3.1 clean, 3.0 with an advisory note, Swagger 2.0 refused).
"""

from __future__ import annotations

import pytest
from example_specs import (
    BROKEN_SPEC,
    GOOD_SPEC,
    MINIMAL_SPEC,
    SWAGGER_2_SPEC,
    write_spec,
)

from gds_api_schema_uplift.loader import (
    SpecLoadError,
    SpecVersionRejected,
    load_spec,
    version_gate,
)


# --- version detection ----------------------------------------------------------------

@pytest.mark.parametrize("path", [BROKEN_SPEC, GOOD_SPEC], ids=["broken", "good"])
def test_example_specs_are_detected_as_openapi_3(path):
    spec = load_spec(path)
    assert spec.is_openapi_3
    assert not spec.is_swagger_2
    assert spec.openapi_version == "3.1.0"


def test_swagger_2_is_detected_as_swagger_not_openapi(tmp_path):
    spec = load_spec(write_spec(tmp_path, SWAGGER_2_SPEC))
    assert spec.is_swagger_2
    assert not spec.is_openapi_3
    assert spec.version_label == "Swagger 2.0"


def test_version_label_reads_openapi_when_present(tmp_path):
    spec = load_spec(write_spec(tmp_path, MINIMAL_SPEC.format(version="3.0.3")))
    assert spec.version_label == "OpenAPI 3.0.3"


# --- load failure modes ---------------------------------------------------------------

def test_missing_spec_is_reported_not_raised_as_oserror(tmp_path):
    with pytest.raises(SpecLoadError, match="not found"):
        load_spec(tmp_path / "nope.yaml")


def test_non_api_document_is_rejected(tmp_path):
    path = write_spec(tmp_path, "just: a mapping\n")
    with pytest.raises(SpecLoadError, match="does not look like"):
        load_spec(path)


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(SpecLoadError, match="empty"):
        load_spec(write_spec(tmp_path, ""))


def test_scalar_root_is_rejected(tmp_path):
    with pytest.raises(SpecLoadError, match="mapping at the document root"):
        load_spec(write_spec(tmp_path, "just a string\n"))


def test_unparseable_yaml_is_reported_as_a_load_error(tmp_path):
    path = write_spec(tmp_path, "openapi: 3.1.0\ninfo: {title: t\npaths: {}\n")
    with pytest.raises(SpecLoadError, match="could not parse"):
        load_spec(path)


# --- version gate (PRD s7.3) ----------------------------------------------------------

def test_3_1_passes_with_no_note(tmp_path):
    spec = load_spec(write_spec(tmp_path, MINIMAL_SPEC.format(version="3.1.0")))
    assert version_gate(spec) is None


def test_3_0_passes_with_an_upgrade_note(tmp_path):
    spec = load_spec(write_spec(tmp_path, MINIMAL_SPEC.format(version="3.0.3")))
    note = version_gate(spec)
    assert note is not None
    assert "3.1" in note


def test_swagger_2_is_rejected_with_an_upgrade_message(tmp_path):
    spec = load_spec(write_spec(tmp_path, SWAGGER_2_SPEC))
    with pytest.raises(SpecVersionRejected, match="2.0 is not supported"):
        version_gate(spec)


def test_unknown_major_version_is_rejected(tmp_path):
    spec = load_spec(write_spec(tmp_path, MINIMAL_SPEC.format(version="4.0.0")))
    with pytest.raises(SpecVersionRejected, match="unsupported OpenAPI version"):
        version_gate(spec)


def test_version_rejection_is_a_subclass_of_load_error():
    """Callers that only care about "could not proceed" can catch the base class."""
    assert issubclass(SpecVersionRejected, SpecLoadError)

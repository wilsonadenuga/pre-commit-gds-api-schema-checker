"""The rule package.

Registry machinery lives in `_registry`; spec traversal helpers live in `_traversal`.
Rule modules are imported at the bottom of this file purely for their registration
side effect — importing `gds_api_schema_uplift.rules` must be enough to populate
`REGISTRY`, because that is what the CLI relies on.

Rule modules are named `<rule_id>_<what_it_checks>` so the filename says what the
rule does and the directory still sorts by rule id.

Phase 1 lands `GDS-001`–`GDS-005`; Phase 5a adds `NCSC-001`–`NCSC-004`; Phase 5b adds
`REC-001`/`REC-002` (v0.2 ruleset complete).
"""

from __future__ import annotations

from ._registry import (
    REGISTRY,
    Checker,
    RuleSpec,
    deterministic_rules,
    findings_by_severity,
    llm_rules,
    register,
    run_deterministic_pass,
)

__all__ = [
    "REGISTRY",
    "Checker",
    "RuleSpec",
    "deterministic_rules",
    "findings_by_severity",
    "llm_rules",
    "register",
    "run_deterministic_pass",
]

# Registration side effects, sorted by rule id. `noqa: E402,F401` — these are
# imported for their decorator side effect, not for their names.
from . import gds_001_https_only  # noqa: E402,F401
from . import gds_002_iso8601_datetimes  # noqa: E402,F401
from . import gds_003_uri_path_versioning  # noqa: E402,F401
from . import gds_004_json_response_bodies  # noqa: E402,F401
from . import gds_005_problem_details_errors  # noqa: E402,F401
from . import ncsc_001_no_weak_auth  # noqa: E402,F401
from . import ncsc_002_auth_deny_by_default  # noqa: E402,F401
from . import ncsc_003_additional_properties_false  # noqa: E402,F401
from . import ncsc_004_rate_limit_declared  # noqa: E402,F401
from . import rec_001_kebab_case_plural_paths  # noqa: E402,F401
from . import rec_002_meaningful_summary_and_description  # noqa: E402,F401

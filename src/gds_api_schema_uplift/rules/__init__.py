"""The rules: 5 GDS, 4 NCSC and 2 recommendations.

Each rule lives in its own file, named `<rule_id>_<what_it_checks>`. Importing this
package imports every rule file, which registers the rule so the CLI can run it.
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

# Imported only so each rule registers itself (hence the `noqa`).
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

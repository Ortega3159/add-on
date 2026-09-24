from __future__ import annotations

from .git_guard import (
    StaleBaseError,
    assert_fresh_base,
)
from .models import (
    CandidateSelection,
    DistributionMode,
    PrebuiltBootstrap,
    ReleasePolicy,
    RepositoryState,
    SemVer,
    WrapperVersion,
)
from .policy import (
    PlanState,
    UpdatePlan,
    classify_release_policy,
    compute_prebuilt_bootstrap,
    plan_update,
    select_candidate,
)
from .repository import (
    EXPECTED_PREBUILT_IMAGE,
    detect_line_ending,
    insert_after_exact_once,
    replace_exact_once,
    update_local_build_files,
    validate_repository_state,
)


__all__ = [
    "CandidateSelection",
    "DistributionMode",
    "EXPECTED_PREBUILT_IMAGE",
    "PlanState",
    "PrebuiltBootstrap",
    "ReleasePolicy",
    "RepositoryState",
    "SemVer",
    "StaleBaseError",
    "UpdatePlan",
    "WrapperVersion",
    "assert_fresh_base",
    "classify_release_policy",
    "compute_prebuilt_bootstrap",
    "detect_line_ending",
    "insert_after_exact_once",
    "plan_update",
    "replace_exact_once",
    "select_candidate",
    "update_local_build_files",
    "validate_repository_state",
]

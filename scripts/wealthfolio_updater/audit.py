from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .discovery import UpstreamRelease
from .git_guard import assert_fresh_base
from .models import (
    CandidateSelection,
    RepositoryState,
    SemVer,
)
from .oci import OciIndexInspection
from .policy import (
    PlanState,
    UpdatePlan,
    plan_update,
    select_candidate,
)


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditOciResult:
    version: SemVer
    expected_index_digest: str | None
    inspection: OciIndexInspection


@dataclass(frozen=True)
class AuditResult:
    audited_git_sha: str
    repository: RepositoryState
    stable_release_count: int
    latest_stable: SemVer
    candidate: CandidateSelection
    plan: UpdatePlan
    oci: AuditOciResult
    disposition: str = "AUDIT_ONLY"


def _select_oci_target(
    *,
    repository: RepositoryState,
    plan: UpdatePlan,
) -> SemVer:
    if plan.state in {
        PlanState.PREBUILT_BOOTSTRAP,
        PlanState.CANDIDATE_AUTO,
        PlanState.CANDIDATE_REVIEW_REQUIRED,
        PlanState.CANDIDATE_APPROVED,
    }:
        if plan.target_upstream is None:
            raise AuditError(
                "update plan requires an OCI target "
                "but has no target upstream version"
            )

        return plan.target_upstream

    if plan.state in {
        PlanState.NOOP,
        PlanState.POLICY_BLOCK_MAJOR,
    }:
        return repository.upstream_version

    if plan.state == PlanState.APPROVAL_MISMATCH:
        raise AuditError(
            "approval mismatch is not reachable "
            "in audit-only planning"
        )

    raise AuditError(
        f"unsupported audit plan state: {plan.state!r}"
    )


def run_audit(
    *,
    repository: RepositoryState,
    releases: Iterable[UpstreamRelease],
    expected_git_sha: str,
    current_git_sha: str,
    inspect_upstream: Callable[
        [SemVer],
        OciIndexInspection,
    ],
) -> AuditResult:
    audited_git_sha = assert_fresh_base(
        planned_base_sha=expected_git_sha,
        current_base_sha=current_git_sha,
    )

    release_items = tuple(releases)
    if not release_items:
        raise AuditError(
            "upstream discovery returned no stable releases"
        )

    release_versions = tuple(
        release.version
        for release in release_items
    )

    latest_stable = max(release_versions)

    candidate = select_candidate(
        repository.upstream_version,
        release_versions,
    )

    plan = plan_update(
        repository=repository,
        releases=release_versions,
        approved_version=None,
    )

    oci_version = _select_oci_target(
        repository=repository,
        plan=plan,
    )

    inspection = inspect_upstream(oci_version)

    expected_index_digest = None

    if oci_version == repository.upstream_version:
        expected_index_digest = repository.upstream_digest

        if inspection.index_digest != expected_index_digest:
            raise AuditError(
                "current upstream OCI index digest "
                "does not match repository pin"
            )

    return AuditResult(
        audited_git_sha=audited_git_sha,
        repository=repository,
        stable_release_count=len(release_items),
        latest_stable=latest_stable,
        candidate=candidate,
        plan=plan,
        oci=AuditOciResult(
            version=oci_version,
            expected_index_digest=expected_index_digest,
            inspection=inspection,
        ),
    )

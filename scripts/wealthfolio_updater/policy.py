
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import (
    CandidateSelection,
    DistributionMode,
    PrebuiltBootstrap,
    ReleasePolicy,
    RepositoryState,
    SemVer,
    WrapperVersion,
)


class PlanState(str, Enum):
    PREBUILT_BOOTSTRAP = "PREBUILT_BOOTSTRAP"
    NOOP = "NOOP"
    CANDIDATE_AUTO = "CANDIDATE_AUTO"
    CANDIDATE_REVIEW_REQUIRED = "CANDIDATE_REVIEW_REQUIRED"
    CANDIDATE_APPROVED = "CANDIDATE_APPROVED"
    APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
    POLICY_BLOCK_MAJOR = "POLICY_BLOCK_MAJOR"


@dataclass(frozen=True)
class UpdatePlan:
    state: PlanState
    target_upstream: SemVer | None
    target_wrapper: WrapperVersion | None
    policy: ReleasePolicy | None


def classify_release_policy(
    current: SemVer,
    candidate: SemVer,
) -> ReleasePolicy:
    if candidate <= current:
        return ReleasePolicy.NO_UPDATE

    if candidate.major > current.major:
        return ReleasePolicy.BLOCK_MAJOR

    if (
        candidate.major == current.major
        and candidate.minor == current.minor
    ):
        return ReleasePolicy.AUTO

    if (
        candidate.major == current.major
        and candidate.minor > current.minor
    ):
        return ReleasePolicy.REVIEW_REQUIRED

    return ReleasePolicy.NO_UPDATE


def select_candidate(
    current: SemVer,
    releases: Iterable[SemVer],
) -> CandidateSelection:
    newer = sorted(
        {
            release
            for release in releases
            if release > current
        },
        reverse=True,
    )

    if not newer:
        return CandidateSelection(
            version=None,
            policy=ReleasePolicy.NO_UPDATE,
        )

    patches = [
        release
        for release in newer
        if (
            release.major == current.major
            and release.minor == current.minor
        )
    ]

    if patches:
        candidate = max(patches)
        return CandidateSelection(
            version=candidate,
            policy=ReleasePolicy.AUTO,
        )

    same_major = [
        release
        for release in newer
        if release.major == current.major
    ]

    if same_major:
        candidate = max(same_major)
        return CandidateSelection(
            version=candidate,
            policy=ReleasePolicy.REVIEW_REQUIRED,
        )

    candidate = max(newer)
    return CandidateSelection(
        version=candidate,
        policy=ReleasePolicy.BLOCK_MAJOR,
    )


def compute_prebuilt_bootstrap(
    *,
    current_upstream: SemVer,
    current_wrapper: WrapperVersion,
    has_image: bool,
    has_state: bool,
) -> PrebuiltBootstrap | None:
    if current_wrapper.upstream != current_upstream:
        raise ValueError(
            "wrapper upstream version does not "
            "match current upstream version"
        )

    if has_image != has_state:
        raise ValueError(
            "prebuilt configuration is inconsistent: "
            "image and updater state must either "
            "both exist or both be absent"
        )

    if has_image:
        return None

    return PrebuiltBootstrap(
        upstream=current_upstream,
        candidate_wrapper=WrapperVersion(
            upstream=current_upstream,
            revision=current_wrapper.revision + 1,
        ),
    )


def plan_update(
    *,
    repository: RepositoryState,
    releases: Iterable[SemVer],
    approved_version: SemVer | None,
) -> UpdatePlan:
    if repository.distribution_mode not in {
        DistributionMode.LOCAL_BUILD,
        DistributionMode.PREBUILT,
    }:
        raise ValueError(
            f"unsupported distribution mode: "
            f"{repository.distribution_mode!r}"
        )

    selection = select_candidate(
        repository.upstream_version,
        releases,
    )

    if selection.policy == ReleasePolicy.NO_UPDATE:
        if approved_version is not None:
            return UpdatePlan(
                state=PlanState.APPROVAL_MISMATCH,
                target_upstream=None,
                target_wrapper=None,
                policy=ReleasePolicy.NO_UPDATE,
            )

        return UpdatePlan(
            state=PlanState.NOOP,
            target_upstream=None,
            target_wrapper=None,
            policy=ReleasePolicy.NO_UPDATE,
        )

    candidate = selection.version
    if candidate is None:
        raise ValueError(
            "candidate selection returned an update "
            "policy without a candidate version"
        )

    if selection.policy == ReleasePolicy.BLOCK_MAJOR:
        return UpdatePlan(
            state=PlanState.POLICY_BLOCK_MAJOR,
            target_upstream=candidate,
            target_wrapper=None,
            policy=ReleasePolicy.BLOCK_MAJOR,
        )

    target_wrapper = WrapperVersion(
        upstream=candidate,
        revision=1,
    )

    if selection.policy == ReleasePolicy.AUTO:
        if approved_version is not None:
            return UpdatePlan(
                state=PlanState.APPROVAL_MISMATCH,
                target_upstream=candidate,
                target_wrapper=target_wrapper,
                policy=ReleasePolicy.AUTO,
            )

        return UpdatePlan(
            state=PlanState.CANDIDATE_AUTO,
            target_upstream=candidate,
            target_wrapper=target_wrapper,
            policy=ReleasePolicy.AUTO,
        )

    if selection.policy == ReleasePolicy.REVIEW_REQUIRED:
        if approved_version is None:
            return UpdatePlan(
                state=PlanState.CANDIDATE_REVIEW_REQUIRED,
                target_upstream=candidate,
                target_wrapper=target_wrapper,
                policy=ReleasePolicy.REVIEW_REQUIRED,
            )

        if approved_version != candidate:
            return UpdatePlan(
                state=PlanState.APPROVAL_MISMATCH,
                target_upstream=candidate,
                target_wrapper=target_wrapper,
                policy=ReleasePolicy.REVIEW_REQUIRED,
            )

        return UpdatePlan(
            state=PlanState.CANDIDATE_APPROVED,
            target_upstream=candidate,
            target_wrapper=target_wrapper,
            policy=ReleasePolicy.REVIEW_REQUIRED,
        )

    raise ValueError(
        f"unsupported release policy: {selection.policy!r}"
    )

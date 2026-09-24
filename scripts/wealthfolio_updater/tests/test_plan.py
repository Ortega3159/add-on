import unittest

from scripts.wealthfolio_updater.updater import (
    DistributionMode,
    EXPECTED_PREBUILT_IMAGE,
    PlanState,
    ReleasePolicy,
    RepositoryState,
    SemVer,
    WrapperVersion,
    plan_update,
)


ARCHES = frozenset({"amd64", "aarch64"})
UPSTREAM_DIGEST = "sha256:" + ("a" * 64)
WRAPPER_DIGEST = "sha256:" + ("b" * 64)


def local_repository(
    *,
    upstream="3.6.3",
    wrapper="3.6.3-4",
):
    return RepositoryState(
        upstream_version=SemVer.parse(upstream),
        upstream_digest=UPSTREAM_DIGEST,
        wrapper_version=WrapperVersion.parse(wrapper),
        architectures=ARCHES,
        distribution_mode=DistributionMode.LOCAL_BUILD,
        image=None,
        published_digest=None,
    )


def prebuilt_repository(
    *,
    upstream="3.8.2",
    wrapper="3.8.2-7",
):
    return RepositoryState(
        upstream_version=SemVer.parse(upstream),
        upstream_digest=UPSTREAM_DIGEST,
        wrapper_version=WrapperVersion.parse(wrapper),
        architectures=ARCHES,
        distribution_mode=DistributionMode.PREBUILT,
        image=EXPECTED_PREBUILT_IMAGE,
        published_digest=WRAPPER_DIGEST,
    )


class LocalBuildPlanTests(unittest.TestCase):
    def test_local_build_uses_latest_stable_candidate(self):
        plan = plan_update(
            repository=local_repository(),
            releases=[
                SemVer.parse("3.6.4"),
                SemVer.parse("3.8.0"),
                SemVer.parse("4.0.0"),
            ],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.CANDIDATE_AUTO,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("4.0.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("4.0.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.AUTO,
        )

    def test_local_build_minor_is_automatic(self):
        plan = plan_update(
            repository=local_repository(),
            releases=[SemVer.parse("3.8.0")],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.CANDIDATE_AUTO,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.8.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.8.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.AUTO,
        )


class NormalPlanTests(unittest.TestCase):
    def test_no_newer_release_is_noop(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[
                SemVer.parse("3.8.1"),
                SemVer.parse("3.8.2"),
            ],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.NOOP,
        )
        self.assertIsNone(plan.target_upstream)
        self.assertIsNone(plan.target_wrapper)
        self.assertEqual(
            plan.policy,
            ReleasePolicy.NO_UPDATE,
        )

    def test_latest_newer_release_becomes_automatic_candidate(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[
                SemVer.parse("3.8.3"),
                SemVer.parse("3.9.0"),
                SemVer.parse("4.0.0"),
            ],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.CANDIDATE_AUTO,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("4.0.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("4.0.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.AUTO,
        )

    def test_new_upstream_resets_wrapper_revision_to_one(self):
        plan = plan_update(
            repository=prebuilt_repository(
                upstream="3.8.2",
                wrapper="3.8.2-27",
            ),
            releases=[SemVer.parse("3.9.0")],
            approved_version=None,
        )

        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.9.0-1"),
        )

    def test_approval_is_not_valid_for_automatic_candidate(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("4.0.0")],
            approved_version=SemVer.parse("4.0.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("4.0.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("4.0.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.AUTO,
        )

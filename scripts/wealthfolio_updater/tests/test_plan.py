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


class BootstrapPlanTests(unittest.TestCase):
    def test_prebuilt_bootstrap_takes_precedence_over_newer_upstream(self):
        plan = plan_update(
            repository=local_repository(),
            releases=[
                SemVer.parse("3.8.0"),
                SemVer.parse("4.0.0"),
            ],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.PREBUILT_BOOTSTRAP,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.6.3"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.6.3-5"),
        )
        self.assertIsNone(plan.policy)


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

        self.assertEqual(plan.state, PlanState.NOOP)
        self.assertIsNone(plan.target_upstream)
        self.assertIsNone(plan.target_wrapper)
        self.assertEqual(
            plan.policy,
            ReleasePolicy.NO_UPDATE,
        )

    def test_patch_becomes_automatic_candidate(self):
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
            SemVer.parse("3.8.3"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.8.3-1"),
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
            releases=[SemVer.parse("3.8.3")],
            approved_version=None,
        )

        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.8.3-1"),
        )

    def test_minor_without_approval_requires_review(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("3.9.0")],
            approved_version=None,
        )

        self.assertEqual(
            plan.state,
            PlanState.CANDIDATE_REVIEW_REQUIRED,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.9.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.9.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.REVIEW_REQUIRED,
        )

    def test_minor_with_exact_approval_is_approved_candidate(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("3.9.0")],
            approved_version=SemVer.parse("3.9.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.CANDIDATE_APPROVED,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.9.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.9.0-1"),
        )
        self.assertEqual(
            plan.policy,
            ReleasePolicy.REVIEW_REQUIRED,
        )

    def test_wrong_minor_approval_fails_closed(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("3.9.0")],
            approved_version=SemVer.parse("3.9.1"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.9.0"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.9.0-1"),
        )

    def test_major_is_blocked_even_with_exact_approval(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("4.0.0")],
            approved_version=SemVer.parse("4.0.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.POLICY_BLOCK_MAJOR,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("4.0.0"),
        )
        self.assertIsNone(plan.target_wrapper)
        self.assertEqual(
            plan.policy,
            ReleasePolicy.BLOCK_MAJOR,
        )

    def test_approval_cannot_skip_a_preferred_patch(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[
                SemVer.parse("3.8.3"),
                SemVer.parse("3.9.0"),
            ],
            approved_version=SemVer.parse("3.9.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.8.3"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.8.3-1"),
        )

    def test_approval_is_not_valid_for_an_automatic_patch(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("3.8.3")],
            approved_version=SemVer.parse("3.8.3"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.8.3"),
        )


if __name__ == "__main__":
    unittest.main()

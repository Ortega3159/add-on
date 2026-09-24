import unittest

from scripts.wealthfolio_updater.audit import (
    AuditError,
    run_audit,
)
from scripts.wealthfolio_updater.discovery import UpstreamRelease
from scripts.wealthfolio_updater.models import (
    DistributionMode,
    ReleasePolicy,
    RepositoryState,
    SemVer,
    WrapperVersion,
)
from scripts.wealthfolio_updater.oci import OciIndexInspection
from scripts.wealthfolio_updater.policy import PlanState
from scripts.wealthfolio_updater.repository import EXPECTED_PREBUILT_IMAGE


CURRENT_DIGEST = "sha256:" + ("a" * 64)
CANDIDATE_DIGEST = "sha256:" + ("b" * 64)
AMD64_DIGEST = "sha256:" + ("c" * 64)
ARM64_DIGEST = "sha256:" + ("d" * 64)
WRAPPER_DIGEST = "sha256:" + ("e" * 64)

GIT_SHA = "1" * 40

ARCHES = frozenset({"amd64", "aarch64"})


def local_repository():
    return RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse("3.6.3-4"),
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
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse(wrapper),
        architectures=ARCHES,
        distribution_mode=DistributionMode.PREBUILT,
        image=EXPECTED_PREBUILT_IMAGE,
        published_digest=WRAPPER_DIGEST,
    )


def release(release_id, version):
    parsed = SemVer.parse(version)
    return UpstreamRelease(
        release_id=release_id,
        tag_name=f"v{version}",
        version=parsed,
    )


def inspection(index_digest):
    return OciIndexInspection(
        index_digest=index_digest,
        amd64_digest=AMD64_DIGEST,
        arm64_digest=ARM64_DIGEST,
        attestation_count=2,
    )


class AuditPlanningTests(unittest.TestCase):
    def test_local_build_review_candidate_is_inspected(self):
        inspected = []

        def inspect_upstream(version):
            inspected.append(version)
            return inspection(CURRENT_DIGEST)

        result = run_audit(
            repository=local_repository(),
            releases=[
                release(1, "3.7.0"),
                release(2, "3.8.0"),
            ],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=inspect_upstream,
        )

        self.assertEqual(result.audited_git_sha, GIT_SHA)
        self.assertEqual(result.stable_release_count, 2)
        self.assertEqual(
            result.latest_stable,
            SemVer.parse("3.8.0"),
        )

        self.assertEqual(
            result.candidate.version,
            SemVer.parse("3.8.0"),
        )
        self.assertEqual(
            result.candidate.policy,
            ReleasePolicy.REVIEW_REQUIRED,
        )

        self.assertEqual(
            result.plan.state,
            PlanState.CANDIDATE_REVIEW_REQUIRED,
        )
        self.assertEqual(
            result.plan.target_upstream,
            SemVer.parse("3.8.0"),
        )
        self.assertEqual(
            result.plan.target_wrapper,
            WrapperVersion.parse("3.8.0-1"),
        )

        self.assertEqual(
            inspected,
            [SemVer.parse("3.8.0")],
        )
        self.assertEqual(
            result.oci.version,
            SemVer.parse("3.8.0"),
        )
        self.assertIsNone(
            result.oci.expected_index_digest,
        )
        self.assertEqual(
            result.oci.inspection.index_digest,
            CURRENT_DIGEST,
        )


class AuditTargetTests(unittest.TestCase):
    def test_review_required_candidate_is_inspected_before_approval(self):
        inspected = []

        def inspect_upstream(version):
            inspected.append(version)
            return inspection(CANDIDATE_DIGEST)

        result = run_audit(
            repository=prebuilt_repository(),
            releases=[release(1, "3.9.0")],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=inspect_upstream,
        )

        self.assertEqual(
            result.plan.state,
            PlanState.CANDIDATE_REVIEW_REQUIRED,
        )
        self.assertEqual(
            inspected,
            [SemVer.parse("3.9.0")],
        )
        self.assertEqual(
            result.oci.version,
            SemVer.parse("3.9.0"),
        )
        self.assertIsNone(
            result.oci.expected_index_digest,
        )

    def test_blocked_major_keeps_current_upstream_as_oci_target(self):
        inspected = []

        def inspect_upstream(version):
            inspected.append(version)
            return inspection(CURRENT_DIGEST)

        result = run_audit(
            repository=prebuilt_repository(),
            releases=[release(1, "4.0.0")],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=inspect_upstream,
        )

        self.assertEqual(
            result.plan.state,
            PlanState.POLICY_BLOCK_MAJOR,
        )
        self.assertEqual(
            inspected,
            [SemVer.parse("3.8.2")],
        )
        self.assertEqual(
            result.oci.expected_index_digest,
            CURRENT_DIGEST,
        )

    def test_noop_still_verifies_current_upstream_identity(self):
        inspected = []

        def inspect_upstream(version):
            inspected.append(version)
            return inspection(CURRENT_DIGEST)

        result = run_audit(
            repository=prebuilt_repository(),
            releases=[
                release(1, "3.8.1"),
                release(2, "3.8.2"),
            ],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=inspect_upstream,
        )

        self.assertEqual(result.plan.state, PlanState.NOOP)
        self.assertEqual(
            inspected,
            [SemVer.parse("3.8.2")],
        )


class AuditFailClosedTests(unittest.TestCase):
    def test_zero_stable_releases_fails_closed(self):
        with self.assertRaises(AuditError):
            run_audit(
                repository=local_repository(),
                releases=[],
                expected_git_sha=GIT_SHA,
                current_git_sha=GIT_SHA,
                inspect_upstream=lambda version: inspection(
                    CURRENT_DIGEST
                ),
            )

    def test_current_upstream_digest_must_match_repository_pin(self):
        with self.assertRaises(AuditError):
            run_audit(
                repository=local_repository(),
                releases=[release(1, "3.6.3")],
                expected_git_sha=GIT_SHA,
                current_git_sha=GIT_SHA,
                inspect_upstream=lambda version: inspection(
                    CANDIDATE_DIGEST
                ),
            )


class AuditGitGuardTests(unittest.TestCase):
    def test_invalid_expected_git_sha_preserves_value_error(self):
        with self.assertRaises(ValueError):
            run_audit(
                repository=local_repository(),
                releases=[release(1, "3.8.0")],
                expected_git_sha="not-a-sha",
                current_git_sha=GIT_SHA,
                inspect_upstream=lambda version: inspection(
                    CURRENT_DIGEST
                ),
            )

    def test_invalid_current_git_sha_preserves_value_error(self):
        with self.assertRaises(ValueError):
            run_audit(
                repository=local_repository(),
                releases=[release(1, "3.8.0")],
                expected_git_sha=GIT_SHA,
                current_git_sha="not-a-sha",
                inspect_upstream=lambda version: inspection(
                    CURRENT_DIGEST
                ),
            )

    def test_stale_git_sha_preserves_stale_base_error(self):
        from scripts.wealthfolio_updater.git_guard import StaleBaseError

        with self.assertRaises(StaleBaseError):
            run_audit(
                repository=local_repository(),
                releases=[release(1, "3.8.0")],
                expected_git_sha=GIT_SHA,
                current_git_sha="2" * 40,
                inspect_upstream=lambda version: inspection(
                    CURRENT_DIGEST
                ),
            )


class AuditInspectorFailureTests(unittest.TestCase):
    def test_inspector_error_is_preserved(self):
        class InspectorError(RuntimeError):
            pass

        def inspect_upstream(version):
            raise InspectorError("simulated OCI inspection failure")

        with self.assertRaises(InspectorError):
            run_audit(
                repository=local_repository(),
                releases=[release(1, "3.8.0")],
                expected_git_sha=GIT_SHA,
                current_git_sha=GIT_SHA,
                inspect_upstream=inspect_upstream,
            )


class AuditCandidateIdentityTests(unittest.TestCase):
    def test_auto_candidate_is_inspected_instead_of_current_upstream(self):
        inspected = []

        def inspect_upstream(version):
            inspected.append(version)
            return inspection(CANDIDATE_DIGEST)

        result = run_audit(
            repository=prebuilt_repository(),
            releases=[
                release(1, "3.8.3"),
                release(2, "3.9.0"),
            ],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=inspect_upstream,
        )

        self.assertEqual(
            result.plan.state,
            PlanState.CANDIDATE_AUTO,
        )
        self.assertEqual(
            inspected,
            [SemVer.parse("3.8.3")],
        )
        self.assertEqual(
            result.oci.version,
            SemVer.parse("3.8.3"),
        )
        self.assertIsNone(
            result.oci.expected_index_digest,
        )

    def test_new_candidate_digest_is_not_compared_to_current_repository_pin(self):
        result = run_audit(
            repository=prebuilt_repository(),
            releases=[release(1, "3.8.3")],
            expected_git_sha=GIT_SHA,
            current_git_sha=GIT_SHA,
            inspect_upstream=lambda version: inspection(
                CANDIDATE_DIGEST
            ),
        )

        self.assertEqual(
            result.oci.inspection.index_digest,
            CANDIDATE_DIGEST,
        )
        self.assertNotEqual(
            result.oci.inspection.index_digest,
            CURRENT_DIGEST,
        )
        self.assertIsNone(
            result.oci.expected_index_digest,
        )


if __name__ == "__main__":
    unittest.main()

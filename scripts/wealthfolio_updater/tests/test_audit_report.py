import json
import unittest

from scripts.wealthfolio_updater.audit import (
    AuditOciResult,
    AuditResult,
)
from scripts.wealthfolio_updater.audit_report import (
    audit_result_to_dict,
    render_audit_json,
    render_audit_markdown,
)
from scripts.wealthfolio_updater.models import (
    CandidateSelection,
    DistributionMode,
    ReleasePolicy,
    RepositoryState,
    SemVer,
    WrapperVersion,
)
from scripts.wealthfolio_updater.oci import OciIndexInspection
from scripts.wealthfolio_updater.policy import (
    PlanState,
    UpdatePlan,
)


GIT_SHA = "1" * 40

CURRENT_DIGEST = "sha256:" + ("a" * 64)
AMD64_DIGEST = "sha256:" + ("b" * 64)
ARM64_DIGEST = "sha256:" + ("c" * 64)


def bootstrap_result():
    repository = RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse("3.6.3-4"),
        architectures=frozenset(
            {
                "amd64",
                "aarch64",
            }
        ),
        distribution_mode=DistributionMode.LOCAL_BUILD,
        image=None,
        published_digest=None,
    )

    candidate = CandidateSelection(
        version=SemVer.parse("3.8.0"),
        policy=ReleasePolicy.REVIEW_REQUIRED,
    )

    plan = UpdatePlan(
        state=PlanState.PREBUILT_BOOTSTRAP,
        target_upstream=SemVer.parse("3.6.3"),
        target_wrapper=WrapperVersion.parse("3.6.3-5"),
        policy=None,
    )

    inspection = OciIndexInspection(
        index_digest=CURRENT_DIGEST,
        amd64_digest=AMD64_DIGEST,
        arm64_digest=ARM64_DIGEST,
        attestation_count=2,
    )

    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository,
        stable_release_count=61,
        latest_stable=SemVer.parse("3.8.0"),
        candidate=candidate,
        plan=plan,
        oci=AuditOciResult(
            version=SemVer.parse("3.6.3"),
            expected_index_digest=CURRENT_DIGEST,
            inspection=inspection,
        ),
    )


class AuditReportStructureTests(unittest.TestCase):
    def test_dict_preserves_candidate_plan_and_oci_as_distinct_concepts(self):
        payload = audit_result_to_dict(
            bootstrap_result()
        )

        self.assertEqual(payload["schema"], 1)
        self.assertEqual(
            payload["disposition"],
            "AUDIT_ONLY",
        )
        self.assertEqual(
            payload["audited_git_sha"],
            GIT_SHA,
        )

        self.assertEqual(
            payload["repository"]["upstream_version"],
            "3.6.3",
        )
        self.assertEqual(
            payload["repository"]["wrapper_version"],
            "3.6.3-4",
        )
        self.assertEqual(
            payload["repository"]["distribution_mode"],
            "LOCAL_BUILD",
        )
        self.assertEqual(
            payload["repository"]["architectures"],
            [
                "aarch64",
                "amd64",
            ],
        )

        self.assertEqual(
            payload["discovery"]["latest_stable"],
            "3.8.0",
        )
        self.assertEqual(
            payload["discovery"]["candidate"],
            {
                "version": "3.8.0",
                "policy": "REVIEW_REQUIRED",
            },
        )

        self.assertEqual(
            payload["plan"]["state"],
            "PREBUILT_BOOTSTRAP",
        )
        self.assertEqual(
            payload["plan"]["target_upstream"],
            "3.6.3",
        )
        self.assertEqual(
            payload["plan"]["target_wrapper"],
            "3.6.3-5",
        )
        self.assertIsNone(
            payload["plan"]["policy"],
        )

        self.assertEqual(
            payload["oci"]["version"],
            "3.6.3",
        )
        self.assertEqual(
            payload["oci"]["index_digest"],
            CURRENT_DIGEST,
        )


class AuditJsonReportTests(unittest.TestCase):
    def test_json_is_deterministic_and_round_trips(self):
        result = bootstrap_result()

        first = render_audit_json(result)
        second = render_audit_json(result)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))

        decoded = json.loads(first)

        self.assertEqual(
            decoded,
            audit_result_to_dict(result),
        )

    def test_json_is_single_record_without_extra_prose(self):
        rendered = render_audit_json(
            bootstrap_result()
        )

        self.assertEqual(
            len(rendered.splitlines()),
            1,
        )


class AuditMarkdownReportTests(unittest.TestCase):
    def test_markdown_exposes_the_operationally_distinct_versions(self):
        rendered = render_audit_markdown(
            bootstrap_result()
        )

        required = [
            "AUDIT_ONLY",
            GIT_SHA,
            "3.6.3-4",
            "LOCAL_BUILD",
            "3.8.0",
            "REVIEW_REQUIRED",
            "PREBUILT_BOOTSTRAP",
            "3.6.3-5",
            CURRENT_DIGEST,
            AMD64_DIGEST,
            ARM64_DIGEST,
        ]

        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, rendered)

    def test_markdown_ends_with_newline(self):
        rendered = render_audit_markdown(
            bootstrap_result()
        )

        self.assertTrue(rendered.endswith("\n"))

def noop_result():
    repository = RepositoryState(
        upstream_version=SemVer.parse("3.8.2"),
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse("3.8.2-7"),
        architectures=frozenset(
            {
                "amd64",
                "aarch64",
            }
        ),
        distribution_mode=DistributionMode.PREBUILT,
        image="ghcr.io/ortega3159/wealthfolio-ha",
        published_digest="sha256:" + ("d" * 64),
    )

    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository,
        stable_release_count=2,
        latest_stable=SemVer.parse("3.8.2"),
        candidate=CandidateSelection(
            version=None,
            policy=ReleasePolicy.NO_UPDATE,
        ),
        plan=UpdatePlan(
            state=PlanState.NOOP,
            target_upstream=None,
            target_wrapper=None,
            policy=ReleasePolicy.NO_UPDATE,
        ),
        oci=AuditOciResult(
            version=SemVer.parse("3.8.2"),
            expected_index_digest=CURRENT_DIGEST,
            inspection=OciIndexInspection(
                index_digest=CURRENT_DIGEST,
                amd64_digest=AMD64_DIGEST,
                arm64_digest=ARM64_DIGEST,
                attestation_count=2,
            ),
        ),
    )


def blocked_major_result():
    repository = RepositoryState(
        upstream_version=SemVer.parse("3.8.2"),
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse("3.8.2-7"),
        architectures=frozenset(
            {
                "amd64",
                "aarch64",
            }
        ),
        distribution_mode=DistributionMode.PREBUILT,
        image="ghcr.io/ortega3159/wealthfolio-ha",
        published_digest="sha256:" + ("d" * 64),
    )

    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository,
        stable_release_count=1,
        latest_stable=SemVer.parse("4.0.0"),
        candidate=CandidateSelection(
            version=SemVer.parse("4.0.0"),
            policy=ReleasePolicy.BLOCK_MAJOR,
        ),
        plan=UpdatePlan(
            state=PlanState.POLICY_BLOCK_MAJOR,
            target_upstream=SemVer.parse("4.0.0"),
            target_wrapper=None,
            policy=ReleasePolicy.BLOCK_MAJOR,
        ),
        oci=AuditOciResult(
            version=SemVer.parse("3.8.2"),
            expected_index_digest=CURRENT_DIGEST,
            inspection=OciIndexInspection(
                index_digest=CURRENT_DIGEST,
                amd64_digest=AMD64_DIGEST,
                arm64_digest=ARM64_DIGEST,
                attestation_count=2,
            ),
        ),
    )


class AuditNoopReportTests(unittest.TestCase):
    def test_noop_json_preserves_null_candidate_and_targets(self):
        payload = audit_result_to_dict(
            noop_result()
        )

        self.assertEqual(
            payload["discovery"]["candidate"],
            {
                "version": None,
                "policy": "NO_UPDATE",
            },
        )
        self.assertEqual(
            payload["plan"],
            {
                "state": "NOOP",
                "target_upstream": None,
                "target_wrapper": None,
                "policy": "NO_UPDATE",
            },
        )
        self.assertEqual(
            payload["oci"]["version"],
            "3.8.2",
        )

    def test_noop_markdown_uses_deliberate_none_text(self):
        rendered = render_audit_markdown(
            noop_result()
        )

        self.assertIn(
            "- Normal candidate: `none`",
            rendered,
        )
        self.assertIn(
            "- Target upstream: `none`",
            rendered,
        )
        self.assertIn(
            "- Target wrapper: `none`",
            rendered,
        )
        self.assertNotIn("`None`", rendered)


class AuditBlockedMajorReportTests(unittest.TestCase):
    def test_blocked_major_keeps_candidate_distinct_from_inspected_oci(self):
        payload = audit_result_to_dict(
            blocked_major_result()
        )

        self.assertEqual(
            payload["discovery"]["candidate"],
            {
                "version": "4.0.0",
                "policy": "BLOCK_MAJOR",
            },
        )
        self.assertEqual(
            payload["plan"]["state"],
            "POLICY_BLOCK_MAJOR",
        )
        self.assertEqual(
            payload["plan"]["target_upstream"],
            "4.0.0",
        )
        self.assertIsNone(
            payload["plan"]["target_wrapper"],
        )
        self.assertEqual(
            payload["oci"]["version"],
            "3.8.2",
        )

    def test_blocked_major_markdown_does_not_imply_major_was_inspected(self):
        rendered = render_audit_markdown(
            blocked_major_result()
        )

        self.assertIn(
            "- Normal candidate: `4.0.0`",
            rendered,
        )
        self.assertIn(
            "- Candidate policy: `BLOCK_MAJOR`",
            rendered,
        )
        self.assertIn(
            "- State: `POLICY_BLOCK_MAJOR`",
            rendered,
        )
        self.assertIn(
            "- Inspected version: `3.8.2`",
            rendered,
        )
        self.assertIn(
            "- Target wrapper: `none`",
            rendered,
        )


class AuditPrebuiltHumanReportTests(unittest.TestCase):
    def test_prebuilt_markdown_includes_published_image_identity(self):
        result = noop_result()

        rendered = render_audit_markdown(result)

        self.assertIn(
            "- Image: `ghcr.io/ortega3159/wealthfolio-ha`",
            rendered,
        )
        self.assertIn(
            (
                "- Published digest: "
                "`sha256:"
                + ("d" * 64)
                + "`"
            ),
            rendered,
        )


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import unittest
from pathlib import Path

from scripts.wealthfolio_updater.audit import (
    AuditOciResult,
    AuditResult,
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
from scripts.wealthfolio_updater.update_cli import run_cli


GIT_SHA = "1" * 40
CURRENT_DIGEST = "sha256:" + ("a" * 64)
TARGET_DIGEST = "sha256:" + ("d" * 64)
AMD64_DIGEST = "sha256:" + ("b" * 64)
ARM64_DIGEST = "sha256:" + ("c" * 64)


def dockerfile_bytes():
    return (
        b"ARG WEALTHFOLIO_VERSION=3.6.3\n"
        b"ARG WEALTHFOLIO_DIGEST="
        + CURRENT_DIGEST.encode("ascii")
        + b"\n"
        b"\n"
        b"FROM ghcr.io/wealthfolio/wealthfolio:"
        b"${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}\n"
        b"\n"
        b"ARG BUILD_VERSION\n"
        b"ARG BUILD_ARCH\n"
    )


def config_bytes():
    return (
        b'name: "Wealthfolio (Unofficial)"\n'
        b'version: "3.6.3-4"\n'
        b'slug: "wealthfolio"\n'
        b"\n"
        b"arch:\n"
        b"  - amd64\n"
        b"  - aarch64\n"
        b"\n"
        b"stage: experimental\n"
    )


def repository_state():
    return RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=CURRENT_DIGEST,
        wrapper_version=WrapperVersion.parse("3.6.3-4"),
        architectures=frozenset(
            {"amd64", "aarch64"}
        ),
        distribution_mode=DistributionMode.LOCAL_BUILD,
        image=None,
        published_digest=None,
    )


def inspection(digest):
    return OciIndexInspection(
        index_digest=digest,
        amd64_digest=AMD64_DIGEST,
        arm64_digest=ARM64_DIGEST,
        attestation_count=2,
    )


def auto_result():
    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository_state(),
        stable_release_count=1,
        latest_stable=SemVer.parse("3.8.0"),
        candidate=CandidateSelection(
            version=SemVer.parse("3.8.0"),
            policy=ReleasePolicy.AUTO,
        ),
        plan=UpdatePlan(
            state=PlanState.CANDIDATE_AUTO,
            target_upstream=SemVer.parse("3.8.0"),
            target_wrapper=WrapperVersion.parse(
                "3.8.0-1"
            ),
            policy=ReleasePolicy.AUTO,
        ),
        oci=AuditOciResult(
            version=SemVer.parse("3.8.0"),
            expected_index_digest=None,
            inspection=inspection(TARGET_DIGEST),
        ),
    )


def noop_result():
    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository_state(),
        stable_release_count=1,
        latest_stable=SemVer.parse("3.6.3"),
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
            version=SemVer.parse("3.6.3"),
            expected_index_digest=CURRENT_DIGEST,
            inspection=inspection(CURRENT_DIGEST),
        ),
    )


def write_repository(root):
    tracker = root / "tracker"
    tracker.mkdir()

    (tracker / "Dockerfile").write_bytes(
        dockerfile_bytes()
    )
    (tracker / "config.yml").write_bytes(
        config_bytes()
    )


class UpdateCliTests(unittest.TestCase):
    def test_auto_candidate_updates_repository_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_repository(root)

            stdout = io.StringIO()
            stderr = io.StringIO()

            code = run_cli(
                [
                    "--repository-root",
                    str(root),
                    "--expected-git-sha",
                    GIT_SHA,
                ],
                execute_audit=lambda **kwargs: auto_result(),
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")

            dockerfile = (
                root / "tracker" / "Dockerfile"
            ).read_bytes()
            config = (
                root / "tracker" / "config.yml"
            ).read_bytes()

            self.assertIn(
                b"ARG WEALTHFOLIO_VERSION=3.8.0\n",
                dockerfile,
            )
            self.assertIn(
                (
                    b"ARG WEALTHFOLIO_DIGEST="
                    + TARGET_DIGEST.encode("ascii")
                    + b"\n"
                ),
                dockerfile,
            )
            self.assertIn(
                b'version: "3.8.0-1"\n',
                config,
            )

    def test_noop_does_not_modify_repository_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_repository(root)

            before_dockerfile = (
                root / "tracker" / "Dockerfile"
            ).read_bytes()
            before_config = (
                root / "tracker" / "config.yml"
            ).read_bytes()

            code = run_cli(
                [
                    "--repository-root",
                    str(root),
                    "--expected-git-sha",
                    GIT_SHA,
                ],
                execute_audit=lambda **kwargs: noop_result(),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                (root / "tracker" / "Dockerfile").read_bytes(),
                before_dockerfile,
            )
            self.assertEqual(
                (root / "tracker" / "config.yml").read_bytes(),
                before_config,
            )

    def test_unexpected_plan_state_fails_without_writes(self):
        result = auto_result()

        unexpected = AuditResult(
            audited_git_sha=result.audited_git_sha,
            repository=result.repository,
            stable_release_count=result.stable_release_count,
            latest_stable=result.latest_stable,
            candidate=result.candidate,
            plan=UpdatePlan(
                state=PlanState.APPROVAL_MISMATCH,
                target_upstream=result.plan.target_upstream,
                target_wrapper=result.plan.target_wrapper,
                policy=result.plan.policy,
            ),
            oci=result.oci,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_repository(root)

            before_dockerfile = (
                root / "tracker" / "Dockerfile"
            ).read_bytes()
            before_config = (
                root / "tracker" / "config.yml"
            ).read_bytes()

            stderr = io.StringIO()

            code = run_cli(
                [
                    "--repository-root",
                    str(root),
                    "--expected-git-sha",
                    GIT_SHA,
                ],
                execute_audit=lambda **kwargs: unexpected,
                stdout=io.StringIO(),
                stderr=stderr,
            )

            self.assertEqual(code, 1)
            self.assertNotEqual(stderr.getvalue(), "")
            self.assertEqual(
                (root / "tracker" / "Dockerfile").read_bytes(),
                before_dockerfile,
            )
            self.assertEqual(
                (root / "tracker" / "config.yml").read_bytes(),
                before_config,
            )


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import unittest
from pathlib import Path

from scripts.wealthfolio_updater.audit import (
    AuditOciResult,
    AuditResult,
)
from scripts.wealthfolio_updater.audit_cli import run_cli
from scripts.wealthfolio_updater.audit_report import (
    render_audit_json,
    render_audit_markdown,
)
from scripts.wealthfolio_updater.github_http import (
    GitHubTransportError,
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
INDEX_DIGEST = "sha256:" + ("a" * 64)
AMD64_DIGEST = "sha256:" + ("b" * 64)
ARM64_DIGEST = "sha256:" + ("c" * 64)


def audit_result():
    repository = RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=INDEX_DIGEST,
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

    return AuditResult(
        audited_git_sha=GIT_SHA,
        repository=repository,
        stable_release_count=61,
        latest_stable=SemVer.parse("3.8.0"),
        candidate=CandidateSelection(
            version=SemVer.parse("3.8.0"),
            policy=ReleasePolicy.REVIEW_REQUIRED,
        ),
        plan=UpdatePlan(
            state=PlanState.PREBUILT_BOOTSTRAP,
            target_upstream=SemVer.parse("3.6.3"),
            target_wrapper=WrapperVersion.parse("3.6.3-5"),
            policy=None,
        ),
        oci=AuditOciResult(
            version=SemVer.parse("3.6.3"),
            expected_index_digest=INDEX_DIGEST,
            inspection=OciIndexInspection(
                index_digest=INDEX_DIGEST,
                amd64_digest=AMD64_DIGEST,
                arm64_digest=ARM64_DIGEST,
                attestation_count=2,
            ),
        ),
    )


class AuditCliSuccessTests(unittest.TestCase):
    def test_success_runs_exactly_one_audit_and_writes_both_reports(self):
        result = audit_result()
        stdout = io.StringIO()
        stderr = io.StringIO()
        calls = []

        def execute_audit(
            *,
            repository_root,
            expected_git_sha,
        ):
            calls.append(
                (
                    repository_root,
                    expected_git_sha,
                )
            )
            return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            summary = Path(directory) / "summary.md"

            exit_code = run_cli(
                [
                    "--repository-root",
                    str(root),
                    "--expected-git-sha",
                    GIT_SHA,
                    "--markdown-output",
                    str(summary),
                ],
                execute_audit=execute_audit,
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(
                summary.read_text(encoding="utf-8"),
                render_audit_markdown(result),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            calls,
            [
                (
                    root,
                    GIT_SHA,
                )
            ],
        )
        self.assertEqual(
            stdout.getvalue(),
            render_audit_json(result),
        )
        self.assertEqual(
            stderr.getvalue(),
            "",
        )

    def test_policy_result_is_not_reclassified_by_cli(self):
        result = audit_result()
        result = AuditResult(
            audited_git_sha=result.audited_git_sha,
            repository=result.repository,
            stable_release_count=result.stable_release_count,
            latest_stable=result.latest_stable,
            candidate=result.candidate,
            plan=UpdatePlan(
                state=PlanState.POLICY_BLOCK_MAJOR,
                target_upstream=SemVer.parse("4.0.0"),
                target_wrapper=None,
                policy=ReleasePolicy.BLOCK_MAJOR,
            ),
            oci=result.oci,
        )

        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            exit_code = run_cli(
                [
                    "--repository-root",
                    directory,
                    "--expected-git-sha",
                    GIT_SHA,
                    "--markdown-output",
                    str(Path(directory) / "summary.md"),
                ],
                execute_audit=lambda **kwargs: result,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(
            '"state":"POLICY_BLOCK_MAJOR"',
            stdout.getvalue(),
        )
        self.assertEqual(stderr.getvalue(), "")


class AuditCliFailureTests(unittest.TestCase):
    def test_operational_audit_failure_returns_one_without_json(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        def execute_audit(**kwargs):
            raise GitHubTransportError(
                "simulated GitHub failure"
            )

        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"

            exit_code = run_cli(
                [
                    "--repository-root",
                    directory,
                    "--expected-git-sha",
                    GIT_SHA,
                    "--markdown-output",
                    str(summary),
                ],
                execute_audit=execute_audit,
                stdout=stdout,
                stderr=stderr,
            )

            self.assertFalse(summary.exists())

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            (
                "wealthfolio updater audit failed: "
                "simulated GitHub failure\n"
            ),
        )

    def test_markdown_write_failure_does_not_emit_success_json(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            unwritable_target = Path(directory) / "as-directory"
            unwritable_target.mkdir()

            exit_code = run_cli(
                [
                    "--repository-root",
                    directory,
                    "--expected-git-sha",
                    GIT_SHA,
                    "--markdown-output",
                    str(unwritable_target),
                ],
                execute_audit=lambda **kwargs: audit_result(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(
            stderr.getvalue().startswith(
                "wealthfolio updater audit failed: "
            )
        )


class AuditCliProgrammingFailureTests(unittest.TestCase):
    def test_unexpected_programming_error_is_not_normalized(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        def execute_audit(**kwargs):
            raise TypeError(
                "simulated programming defect"
            )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                TypeError,
                "simulated programming defect",
            ):
                run_cli(
                    [
                        "--repository-root",
                        directory,
                        "--expected-git-sha",
                        GIT_SHA,
                        "--markdown-output",
                        str(
                            Path(directory)
                            / "summary.md"
                        ),
                    ],
                    execute_audit=execute_audit,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

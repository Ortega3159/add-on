import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.wealthfolio_updater.audit_execution import (
    AuditExecutionError,
    assert_clean_git_worktree,
    execute_repository_audit,
    read_git_head,
)
from scripts.wealthfolio_updater.discovery import (
    GitHubReleasePageResponse,
)
from scripts.wealthfolio_updater.ghcr_http import (
    GhcrManifestResponse,
)
from scripts.wealthfolio_updater.git_guard import (
    StaleBaseError,
)
from scripts.wealthfolio_updater.models import SemVer
from scripts.wealthfolio_updater.oci import (
    OCI_IMAGE_INDEX_MEDIA_TYPE,
)
from scripts.wealthfolio_updater.policy import PlanState


GIT_SHA = "1" * 40


def build_oci_index():
    body = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
            "manifests": [
                {
                    "mediaType": (
                        "application/vnd.oci.image.manifest.v1+json"
                    ),
                    "digest": "sha256:" + ("a" * 64),
                    "size": 100,
                    "platform": {
                        "os": "linux",
                        "architecture": "amd64",
                    },
                },
                {
                    "mediaType": (
                        "application/vnd.oci.image.manifest.v1+json"
                    ),
                    "digest": "sha256:" + ("b" * 64),
                    "size": 100,
                    "platform": {
                        "os": "linux",
                        "architecture": "arm64",
                    },
                },
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    digest = "sha256:" + hashlib.sha256(body).hexdigest()

    return body, digest


def write_local_repository(root, upstream_digest):
    tracker = root / "tracker"
    tracker.mkdir()

    dockerfile = (
        "ARG WEALTHFOLIO_VERSION=3.6.3\r\n"
        f"ARG WEALTHFOLIO_DIGEST={upstream_digest}\r\n"
        "FROM ghcr.io/wealthfolio/wealthfolio:"
        "${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}\r\n"
    ).encode("ascii")

    config = (
        'version: "3.6.3-4"\r\n'
        "arch:\r\n"
        "  - amd64\r\n"
        "  - aarch64\r\n"
    ).encode("ascii")

    (tracker / "Dockerfile").write_bytes(dockerfile)
    (tracker / "config.yml").write_bytes(config)


def stable_release_page():
    body = json.dumps(
        [
            {
                "id": 1,
                "tag_name": "v3.8.0",
                "draft": False,
                "prerelease": False,
            }
        ]
    ).encode("utf-8")

    return GitHubReleasePageResponse(
        body=body,
        link_header=None,
    )


class AuditExecutionTests(unittest.TestCase):
    def test_local_repository_executes_gate_zero_one_and_two(self):
        oci_body, oci_digest = build_oci_index()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_local_repository(root, oci_digest)

            fetched_pages = []
            fetched_manifests = []

            def fetch_release_page(page):
                fetched_pages.append(page)
                return stable_release_page()

            def fetch_manifest(version):
                fetched_manifests.append(version)
                return GhcrManifestResponse(
                    body=oci_body,
                    content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                    content_digest=oci_digest,
                )

            result = execute_repository_audit(
                repository_root=root,
                expected_git_sha=GIT_SHA,
                head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                fetch_release_page=fetch_release_page,
                fetch_manifest=fetch_manifest,
            )

        self.assertEqual(fetched_pages, [1])
        self.assertEqual(
            fetched_manifests,
            [SemVer.parse("3.8.0")],
        )

        self.assertEqual(
            result.plan.state,
            PlanState.CANDIDATE_AUTO,
        )
        self.assertEqual(
            result.latest_stable,
            SemVer.parse("3.8.0"),
        )
        self.assertEqual(
            result.oci.inspection.index_digest,
            oci_digest,
        )

    def test_stale_sha_fails_before_network(self):
        network_called = False

        def fetch_release_page(page):
            nonlocal network_called
            network_called = True
            raise AssertionError("network must not be called")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StaleBaseError):
                execute_repository_audit(
                    repository_root=Path(directory),
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: "2" * 40,
                    fetch_release_page=fetch_release_page,
                    fetch_manifest=lambda version: None,
                )

        self.assertFalse(network_called)

    def test_invalid_repository_fails_before_network(self):
        _, oci_digest = build_oci_index()

        network_called = False

        def fetch_release_page(page):
            nonlocal network_called
            network_called = True
            raise AssertionError("network must not be called")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_local_repository(root, oci_digest)

            (root / "tracker" / "config.yml").write_bytes(
                (
                    'version: "3.6.3-4"\n'
                    "arch:\n"
                    "  - amd64\n"
                ).encode("ascii")
            )

            with self.assertRaises(ValueError):
                execute_repository_audit(
                    repository_root=root,
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                    fetch_release_page=fetch_release_page,
                    fetch_manifest=lambda version: None,
                )

        self.assertFalse(network_called)

    def test_required_repository_symlink_is_rejected(self):
        _, oci_digest = build_oci_index()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_local_repository(root, oci_digest)

            dockerfile = root / "tracker" / "Dockerfile"
            dockerfile.unlink()

            target = root / "outside-Dockerfile"
            target.write_text(
                "not repository content",
                encoding="utf-8",
            )

            dockerfile.symlink_to(target)

            with self.assertRaises(AuditExecutionError):
                execute_repository_audit(
                    repository_root=root,
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                    fetch_release_page=lambda page: (
                        self.fail("network must not be called")
                    ),
                    fetch_manifest=lambda version: None,
                )

    def test_optional_state_symlink_is_rejected(self):
        _, oci_digest = build_oci_index()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_local_repository(root, oci_digest)

            github = root / ".github"
            github.mkdir()

            target = root / "outside-state.json"
            target.write_text("{}", encoding="utf-8")

            (
                github / "wealthfolio-updater-state.json"
            ).symlink_to(target)

            with self.assertRaises(AuditExecutionError):
                execute_repository_audit(
                    repository_root=root,
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                    fetch_release_page=lambda page: (
                        self.fail("network must not be called")
                    ),
                    fetch_manifest=lambda version: None,
                )


class AuditExecutionParentPathTests(unittest.TestCase):
    def test_symlinked_tracker_directory_is_rejected(self):
        oci_body, oci_digest = build_oci_index()

        with (
            tempfile.TemporaryDirectory() as repository_directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            root = Path(repository_directory)
            outside = Path(outside_directory)

            write_local_repository(
                outside,
                oci_digest,
            )

            (root / "tracker").symlink_to(
                outside / "tracker",
                target_is_directory=True,
            )

            with self.assertRaises(AuditExecutionError):
                execute_repository_audit(
                    repository_root=root,
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                    fetch_release_page=(
                        lambda page: stable_release_page()
                    ),
                    fetch_manifest=lambda version: (
                        GhcrManifestResponse(
                            body=oci_body,
                            content_type=(
                                OCI_IMAGE_INDEX_MEDIA_TYPE
                            ),
                            content_digest=oci_digest,
                        )
                    ),
                )

    def test_symlinked_optional_state_parent_is_rejected(self):
        oci_body, oci_digest = build_oci_index()

        with (
            tempfile.TemporaryDirectory() as repository_directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            root = Path(repository_directory)
            outside = Path(outside_directory)

            write_local_repository(
                root,
                oci_digest,
            )

            (root / ".github").symlink_to(
                outside,
                target_is_directory=True,
            )

            with self.assertRaises(AuditExecutionError):
                execute_repository_audit(
                    repository_root=root,
                    expected_git_sha=GIT_SHA,
                    head_reader=lambda root: GIT_SHA,
                worktree_guard=lambda root: None,
                    fetch_release_page=(
                        lambda page: stable_release_page()
                    ),
                    fetch_manifest=lambda version: (
                        GhcrManifestResponse(
                            body=oci_body,
                            content_type=(
                                OCI_IMAGE_INDEX_MEDIA_TYPE
                            ),
                            content_digest=oci_digest,
                        )
                    ),
                )


class GitHeadReaderTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_reads_exact_checkout_head_without_shell(
        self,
        run,
    ):
        root = Path("/tmp/repository")

        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(GIT_SHA + "\n").encode("ascii"),
            stderr=b"",
        )

        result = read_git_head(root)

        self.assertEqual(result, GIT_SHA)

        run.assert_called_once_with(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            shell=False,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_git_failure_is_execution_error(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=128,
            stdout=b"",
            stderr=b"simulated git failure",
        )

        with self.assertRaises(AuditExecutionError):
            read_git_head(Path("/tmp/repository"))

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_malformed_git_output_is_execution_error(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                GIT_SHA + "\n" + ("2" * 40) + "\n"
            ).encode("ascii"),
            stderr=b"",
        )

        with self.assertRaises(AuditExecutionError):
            read_git_head(Path("/tmp/repository"))

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_git_timeout_is_execution_error(
        self,
        run,
    ):
        run.side_effect = subprocess.TimeoutExpired(
            cmd=["git"],
            timeout=5,
        )

        with self.assertRaises(AuditExecutionError):
            read_git_head(Path("/tmp/repository"))

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_missing_git_is_execution_error(
        self,
        run,
    ):
        run.side_effect = FileNotFoundError(
            "git not found"
        )

        with self.assertRaises(AuditExecutionError):
            read_git_head(Path("/tmp/repository"))


class GitWorktreeGuardTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_clean_worktree_passes(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        )

        assert_clean_git_worktree(
            Path("/tmp/repository")
        )

        run.assert_called_once_with(
            [
                "git",
                "-C",
                "/tmp/repository",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            shell=False,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_dirty_tracked_worktree_is_rejected(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b" M tracker/config.yml\n",
            stderr=b"",
        )

        with self.assertRaises(AuditExecutionError):
            assert_clean_git_worktree(
                Path("/tmp/repository")
            )

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_untracked_file_is_rejected(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"?? unexpected.txt\n",
            stderr=b"",
        )

        with self.assertRaises(AuditExecutionError):
            assert_clean_git_worktree(
                Path("/tmp/repository")
            )

    @patch(
        "scripts.wealthfolio_updater."
        "audit_execution.subprocess.run"
    )
    def test_git_status_failure_is_execution_error(
        self,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=128,
            stdout=b"",
            stderr=b"simulated failure",
        )

        with self.assertRaises(AuditExecutionError):
            assert_clean_git_worktree(
                Path("/tmp/repository")
            )


class AuditExecutionWorktreeOrderingTests(unittest.TestCase):
    def test_dirty_worktree_fails_before_repository_read_or_network(self):
        calls = []

        class DirtyWorktreeError(RuntimeError):
            pass

        def head_reader(root):
            calls.append("head")
            return GIT_SHA

        def worktree_guard(root):
            calls.append("worktree")
            raise DirtyWorktreeError(
                "simulated dirty worktree"
            )

        def fetch_release_page(page):
            calls.append("github")
            self.fail("network must not be called")

        def fetch_manifest(version):
            calls.append("ghcr")
            self.fail("network must not be called")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DirtyWorktreeError):
                execute_repository_audit(
                    repository_root=Path(directory),
                    expected_git_sha=GIT_SHA,
                    head_reader=head_reader,
                    worktree_guard=worktree_guard,
                    fetch_release_page=fetch_release_page,
                    fetch_manifest=fetch_manifest,
                )

        self.assertEqual(
            calls,
            ["head", "worktree"],
        )


if __name__ == "__main__":
    unittest.main()

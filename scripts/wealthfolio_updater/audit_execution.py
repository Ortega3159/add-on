from __future__ import annotations

import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from .audit import AuditResult, run_audit
from .discovery import (
    GitHubReleasePageResponse,
    discover_github_releases,
)
from .ghcr_http import (
    GhcrManifestResponse,
    fetch_ghcr_manifest,
)
from .git_guard import assert_fresh_base
from .github_http import fetch_github_release_page
from .models import SemVer
from .oci import (
    OciIndexInspection,
    inspect_oci_index,
)
from .repository import validate_repository_state


_DOCKERFILE_PATH = Path("tracker/Dockerfile")
_CONFIG_PATH = Path("tracker/config.yml")
_STATE_PATH = Path(
    ".github/wealthfolio-updater-state.json"
)


class AuditExecutionError(RuntimeError):
    pass


def read_git_head(
    repository_root: Path,
) -> str:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
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
    except (
        FileNotFoundError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise AuditExecutionError(
            "failed to resolve checkout Git HEAD"
        ) from exc

    if result.returncode != 0:
        raise AuditExecutionError(
            "failed to resolve checkout Git HEAD"
        )

    if not isinstance(result.stdout, bytes):
        raise AuditExecutionError(
            "Git HEAD output must be bytes"
        )

    try:
        text = result.stdout.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AuditExecutionError(
            "Git HEAD output must be ASCII"
        ) from exc

    if text.endswith("\r\n"):
        head = text[:-2]
    elif text.endswith("\n"):
        head = text[:-1]
    else:
        head = text

    if (
        not head
        or "\n" in head
        or "\r" in head
    ):
        raise AuditExecutionError(
            "Git HEAD output must contain exactly one object ID"
        )

    try:
        return assert_fresh_base(
            planned_base_sha=head,
            current_base_sha=head,
        )
    except ValueError as exc:
        raise AuditExecutionError(
            "Git HEAD output is not a full Git object ID"
        ) from exc


def assert_clean_git_worktree(
    repository_root: Path,
) -> None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
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
    except (
        FileNotFoundError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise AuditExecutionError(
            "failed to inspect checkout Git worktree"
        ) from exc

    if result.returncode != 0:
        raise AuditExecutionError(
            "failed to inspect checkout Git worktree"
        )

    if not isinstance(result.stdout, bytes):
        raise AuditExecutionError(
            "Git worktree status output must be bytes"
        )

    if result.stdout:
        raise AuditExecutionError(
            "checkout Git worktree is not clean"
        )


def _validate_path_parents(
    *,
    repository_root: Path,
    relative_path: Path,
) -> None:
    parent_relative = Path()

    for part in relative_path.parts[:-1]:
        parent_relative /= part
        parent_path = repository_root / parent_relative

        try:
            metadata = parent_path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise AuditExecutionError(
                "failed to inspect repository path parent: "
                f"{parent_relative.as_posix()}"
            ) from exc

        if stat.S_ISLNK(metadata.st_mode):
            raise AuditExecutionError(
                "repository path parent must not be a symlink: "
                f"{parent_relative.as_posix()}"
            )

        if not stat.S_ISDIR(metadata.st_mode):
            raise AuditExecutionError(
                "repository path parent must be a directory: "
                f"{parent_relative.as_posix()}"
            )


def _read_regular_file(
    *,
    repository_root: Path,
    relative_path: Path,
    optional: bool,
) -> bytes | None:
    _validate_path_parents(
        repository_root=repository_root,
        relative_path=relative_path,
    )

    path = repository_root / relative_path

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if optional:
            return None

        raise AuditExecutionError(
            f"required repository file is missing: "
            f"{relative_path.as_posix()}"
        ) from None

    if stat.S_ISLNK(metadata.st_mode):
        raise AuditExecutionError(
            "repository path must not be a symlink: "
            f"{relative_path.as_posix()}"
        )

    if not stat.S_ISREG(metadata.st_mode):
        raise AuditExecutionError(
            "repository path must be a regular file: "
            f"{relative_path.as_posix()}"
        )

    try:
        return path.read_bytes()
    except OSError as exc:
        raise AuditExecutionError(
            "failed to read repository file: "
            f"{relative_path.as_posix()}"
        ) from exc


def execute_repository_audit(
    *,
    repository_root: Path,
    expected_git_sha: str,
    head_reader: Callable[
        [Path],
        str,
    ] = read_git_head,
    worktree_guard: Callable[
        [Path],
        None,
    ] = assert_clean_git_worktree,
    fetch_release_page: Callable[
        [int],
        GitHubReleasePageResponse,
    ] = fetch_github_release_page,
    fetch_manifest: Callable[
        [SemVer],
        GhcrManifestResponse,
    ] = fetch_ghcr_manifest,
) -> AuditResult:
    current_git_sha = head_reader(
        repository_root
    )

    assert_fresh_base(
        planned_base_sha=expected_git_sha,
        current_base_sha=current_git_sha,
    )

    worktree_guard(
        repository_root
    )

    dockerfile_bytes = _read_regular_file(
        repository_root=repository_root,
        relative_path=_DOCKERFILE_PATH,
        optional=False,
    )
    config_bytes = _read_regular_file(
        repository_root=repository_root,
        relative_path=_CONFIG_PATH,
        optional=False,
    )
    state_bytes = _read_regular_file(
        repository_root=repository_root,
        relative_path=_STATE_PATH,
        optional=True,
    )

    assert dockerfile_bytes is not None
    assert config_bytes is not None

    repository = validate_repository_state(
        dockerfile_bytes=dockerfile_bytes,
        config_bytes=config_bytes,
        state_bytes=state_bytes,
    )

    releases = discover_github_releases(
        fetch_release_page,
    )

    def inspect_upstream(
        version: SemVer,
    ) -> OciIndexInspection:
        response = fetch_manifest(version)

        if not isinstance(
            response,
            GhcrManifestResponse,
        ):
            raise TypeError(
                "fetch_manifest must return "
                "GhcrManifestResponse"
            )

        return inspect_oci_index(
            body=response.body,
            content_type=response.content_type,
            content_digest=response.content_digest,
        )

    return run_audit(
        repository=repository,
        releases=releases,
        expected_git_sha=expected_git_sha,
        current_git_sha=current_git_sha,
        inspect_upstream=inspect_upstream,
    )

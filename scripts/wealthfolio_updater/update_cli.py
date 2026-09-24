from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from .audit import (
    AuditError,
    AuditResult,
)
from .audit_execution import (
    AuditExecutionError,
    execute_repository_audit,
)
from .ghcr_http import GhcrTransportError
from .git_guard import StaleBaseError
from .github_http import GitHubTransportError
from .policy import PlanState
from .repository import update_local_build_files


_DOCKERFILE_PATH = Path("tracker/Dockerfile")
_CONFIG_PATH = Path("tracker/config.yml")

_OPERATIONAL_UPDATE_ERRORS = (
    AuditError,
    AuditExecutionError,
    GitHubTransportError,
    GhcrTransportError,
    StaleBaseError,
    OSError,
    ValueError,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wealthfolio-updater-update",
        description=(
            "Apply an audited Wealthfolio upstream update "
            "to the local-build repository."
        ),
    )

    parser.add_argument(
        "--repository-root",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--expected-git-sha",
        required=True,
    )

    return parser


def _write_failure(
    *,
    stderr: TextIO,
    message: str,
) -> None:
    stderr.write(
        "wealthfolio updater update failed: "
        f"{message}\n"
    )


def run_cli(
    argv: Sequence[str],
    *,
    execute_audit: Callable[..., AuditResult] = (
        execute_repository_audit
    ),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    if stdout is None:
        stdout = sys.stdout

    if stderr is None:
        stderr = sys.stderr

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = execute_audit(
            repository_root=args.repository_root,
            expected_git_sha=args.expected_git_sha,
        )

        if result.plan.state == PlanState.NOOP:
            stdout.write("NOOP\n")
            return 0

        if result.plan.state != PlanState.CANDIDATE_AUTO:
            raise ValueError(
                "update requires CANDIDATE_AUTO plan; "
                f"got {result.plan.state.value}"
            )

        target_upstream = result.plan.target_upstream
        target_wrapper = result.plan.target_wrapper

        if target_upstream is None:
            raise ValueError(
                "automatic candidate has no target upstream"
            )

        if target_wrapper is None:
            raise ValueError(
                "automatic candidate has no target wrapper"
            )

        if result.oci.version != target_upstream:
            raise ValueError(
                "audited OCI version does not match "
                "target upstream version"
            )

        dockerfile_path = (
            args.repository_root / _DOCKERFILE_PATH
        )
        config_path = (
            args.repository_root / _CONFIG_PATH
        )

        dockerfile_bytes = dockerfile_path.read_bytes()
        config_bytes = config_path.read_bytes()

        (
            updated_dockerfile,
            updated_config,
        ) = update_local_build_files(
            dockerfile_bytes=dockerfile_bytes,
            config_bytes=config_bytes,
            target_upstream=target_upstream,
            target_wrapper=target_wrapper,
            target_digest=(
                result.oci.inspection.index_digest
            ),
        )

        dockerfile_path.write_bytes(updated_dockerfile)
        config_path.write_bytes(updated_config)

    except _OPERATIONAL_UPDATE_ERRORS as exc:
        _write_failure(
            stderr=stderr,
            message=str(exc),
        )
        return 1

    stdout.write(
        f"UPDATED {target_wrapper}\n"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]

    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())

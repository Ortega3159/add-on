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
from .audit_report import (
    render_audit_json,
    render_audit_markdown,
)
from .ghcr_http import GhcrTransportError
from .git_guard import StaleBaseError
from .github_http import GitHubTransportError


_OPERATIONAL_AUDIT_ERRORS = (
    AuditError,
    AuditExecutionError,
    GitHubTransportError,
    GhcrTransportError,
    StaleBaseError,
    ValueError,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wealthfolio-updater-audit",
        description=(
            "Run the read-only Wealthfolio updater audit."
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
    parser.add_argument(
        "--markdown-output",
        required=True,
        type=Path,
    )

    return parser


def _write_failure(
    *,
    stderr: TextIO,
    message: str,
) -> None:
    stderr.write(
        "wealthfolio updater audit failed: "
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
    except _OPERATIONAL_AUDIT_ERRORS as exc:
        _write_failure(
            stderr=stderr,
            message=str(exc),
        )
        return 1

    markdown = render_audit_markdown(result)
    json_report = render_audit_json(result)

    try:
        args.markdown_output.write_text(
            markdown,
            encoding="utf-8",
        )
    except OSError as exc:
        _write_failure(
            stderr=stderr,
            message=str(exc),
        )
        return 1

    stdout.write(json_report)

    return 0


def main(
    argv: Sequence[str] | None = None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]

    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())

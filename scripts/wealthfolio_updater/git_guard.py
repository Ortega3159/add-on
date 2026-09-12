
from __future__ import annotations

import re


_GIT_OBJECT_ID_RE = re.compile(
    r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
)


class StaleBaseError(RuntimeError):
    """The repository base changed after planning/testing."""


def _validate_git_object_id(
    value: str,
    *,
    label: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")

    if _GIT_OBJECT_ID_RE.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be a full lowercase Git object ID"
        )

    return value


def assert_fresh_base(
    *,
    planned_base_sha: str,
    current_base_sha: str,
) -> str:
    planned = _validate_git_object_id(
        planned_base_sha,
        label="planned base SHA",
    )
    current = _validate_git_object_id(
        current_base_sha,
        label="current base SHA",
    )

    if planned != current:
        raise StaleBaseError(
            "repository base changed after planning/testing: "
            f"planned={planned}, current={current}"
        )

    return current

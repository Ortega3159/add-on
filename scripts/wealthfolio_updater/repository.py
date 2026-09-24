
from __future__ import annotations

import json
import re

from .models import (
    DistributionMode,
    RepositoryState,
    SemVer,
    WrapperVersion,
)


EXPECTED_PREBUILT_IMAGE = "ghcr.io/ortega3159/wealthfolio-ha"


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


_DOCKERFILE_VERSION_RE = re.compile(
    r"ARG WEALTHFOLIO_VERSION=(.+)"
)


_DOCKERFILE_DIGEST_RE = re.compile(
    r"ARG WEALTHFOLIO_DIGEST=(.+)"
)


_EXPECTED_FROM_LINE = (
    "FROM ghcr.io/wealthfolio/wealthfolio:"
    "${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}"
)


_CONFIG_VERSION_RE = re.compile(
    r'version: "([^"]+)"'
)


_CONFIG_IMAGE_RE = re.compile(
    r'image: "([^"]+)"'
)


_ARCH_ITEM_RE = re.compile(
    r"[ \t]+-[ \t]+([A-Za-z0-9_-]+)[ \t]*"
)


_REQUIRED_ARCHITECTURES = frozenset(
    {"amd64", "aarch64"}
)


_STATE_SCHEMA_ONE_KEYS = frozenset(
    {"schema", "image", "version", "digest"}
)


def _decode_ascii(
    value: bytes,
    *,
    label: str,
) -> str:
    if not isinstance(value, bytes):
        raise ValueError(f"{label} must be bytes")

    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{label} must be ASCII"
        ) from exc


def _exactly_one_match(
    pattern: re.Pattern[str],
    lines: list[str],
    *,
    label: str,
) -> re.Match[str]:
    matches = [
        match
        for line in lines
        if (match := pattern.fullmatch(line))
        is not None
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{label} must occur exactly once; "
            f"found {len(matches)}"
        )

    return matches[0]


def _validate_digest(
    digest: str,
    *,
    label: str,
) -> str:
    if _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError(
            f"invalid {label}: {digest!r}"
        )

    return digest


def _parse_dockerfile(
    dockerfile_bytes: bytes,
) -> tuple[SemVer, str]:
    text = _decode_ascii(
        dockerfile_bytes,
        label="Dockerfile",
    )
    lines = text.splitlines()

    version_match = _exactly_one_match(
        _DOCKERFILE_VERSION_RE,
        lines,
        label="WEALTHFOLIO_VERSION ARG",
    )
    digest_match = _exactly_one_match(
        _DOCKERFILE_DIGEST_RE,
        lines,
        label="WEALTHFOLIO_DIGEST ARG",
    )

    from_count = sum(
        1
        for line in lines
        if line == _EXPECTED_FROM_LINE
    )
    all_from_lines = [
        line
        for line in lines
        if line.startswith("FROM ")
    ]

    if (
        from_count != 1
        or len(all_from_lines) != 1
    ):
        raise ValueError(
            "Dockerfile must contain exactly one "
            "pinned Wealthfolio FROM line"
        )

    upstream_version = SemVer.parse(
        version_match.group(1)
    )
    upstream_digest = _validate_digest(
        digest_match.group(1),
        label="upstream digest",
    )

    return upstream_version, upstream_digest


def _parse_config(
    config_bytes: bytes,
) -> tuple[
    WrapperVersion,
    str | None,
    frozenset[str],
]:
    text = _decode_ascii(
        config_bytes,
        label="config.yml",
    )
    lines = text.splitlines()

    version_match = _exactly_one_match(
        _CONFIG_VERSION_RE,
        lines,
        label="config version",
    )
    wrapper_version = WrapperVersion.parse(
        version_match.group(1)
    )

    image_matches = [
        match
        for line in lines
        if (
            match := _CONFIG_IMAGE_RE.fullmatch(
                line
            )
        )
        is not None
    ]

    if len(image_matches) > 1:
        raise ValueError(
            "config image must occur at most once"
        )

    image = (
        image_matches[0].group(1)
        if image_matches
        else None
    )

    arch_indices = [
        index
        for index, line in enumerate(lines)
        if line == "arch:"
    ]

    if len(arch_indices) != 1:
        raise ValueError(
            "arch block must occur exactly once"
        )

    arch_values: list[str] = []
    index = arch_indices[0] + 1

    while index < len(lines):
        line = lines[index]

        match = _ARCH_ITEM_RE.fullmatch(line)
        if match is None:
            break

        arch_values.append(match.group(1))
        index += 1

    if len(arch_values) != len(set(arch_values)):
        raise ValueError(
            "architecture entries must not repeat"
        )

    architectures = frozenset(arch_values)

    if architectures != _REQUIRED_ARCHITECTURES:
        raise ValueError(
            "architecture contract must be exactly "
            "amd64 and aarch64"
        )

    return (
        wrapper_version,
        image,
        architectures,
    )


def _reject_duplicate_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(
                f"duplicate JSON object key: {key!r}"
            )

        result[key] = value

    return result


def _parse_state(
    state_bytes: bytes,
) -> tuple[str, WrapperVersion, str]:
    text = _decode_ascii(
        state_bytes,
        label="updater state",
    )

    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "updater state must be valid JSON"
        ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            "updater state must be a JSON object"
        )

    keys = frozenset(value.keys())
    if keys != _STATE_SCHEMA_ONE_KEYS:
        raise ValueError(
            "updater state schema 1 has an "
            "unexpected field set"
        )

    schema = value.get("schema")

    if type(schema) is not int or schema != 1:
        raise ValueError(
            "unsupported updater state schema"
        )

    image = value.get("image")
    version = value.get("version")
    digest = value.get("digest")

    if not isinstance(image, str):
        raise ValueError(
            "updater state image must be a string"
        )

    if not isinstance(version, str):
        raise ValueError(
            "updater state version must be a string"
        )

    if not isinstance(digest, str):
        raise ValueError(
            "updater state digest must be a string"
        )

    wrapper_version = WrapperVersion.parse(version)
    published_digest = _validate_digest(
        digest,
        label="published wrapper digest",
    )

    return (
        image,
        wrapper_version,
        published_digest,
    )


def validate_repository_state(
    *,
    dockerfile_bytes: bytes,
    config_bytes: bytes,
    state_bytes: bytes | None,
) -> RepositoryState:
    (
        upstream_version,
        upstream_digest,
    ) = _parse_dockerfile(dockerfile_bytes)

    (
        wrapper_version,
        image,
        architectures,
    ) = _parse_config(config_bytes)

    if wrapper_version.upstream != upstream_version:
        raise ValueError(
            "wrapper upstream version does not "
            "match Dockerfile upstream version"
        )

    has_image = image is not None
    has_state = state_bytes is not None

    if has_image != has_state:
        raise ValueError(
            "prebuilt configuration is inconsistent: "
            "image and updater state must either "
            "both exist or both be absent"
        )

    if not has_image:
        return RepositoryState(
            upstream_version=upstream_version,
            upstream_digest=upstream_digest,
            wrapper_version=wrapper_version,
            architectures=architectures,
            distribution_mode=(
                DistributionMode.LOCAL_BUILD
            ),
            image=None,
            published_digest=None,
        )

    if image != EXPECTED_PREBUILT_IMAGE:
        raise ValueError(
            "config image does not match expected "
            "prebuilt package"
        )

    assert state_bytes is not None

    (
        state_image,
        state_wrapper,
        published_digest,
    ) = _parse_state(state_bytes)

    if state_image != image:
        raise ValueError(
            "updater state image does not match "
            "config image"
        )

    if state_wrapper != wrapper_version:
        raise ValueError(
            "updater state version does not match "
            "config version"
        )

    return RepositoryState(
        upstream_version=upstream_version,
        upstream_digest=upstream_digest,
        wrapper_version=wrapper_version,
        architectures=architectures,
        distribution_mode=(
            DistributionMode.PREBUILT
        ),
        image=image,
        published_digest=published_digest,
    )


def detect_line_ending(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise ValueError("data must be bytes")

    without_crlf = data.replace(b"\r\n", b"")

    has_crlf = b"\r\n" in data
    has_lf = b"\n" in without_crlf
    has_lone_cr = b"\r" in without_crlf

    if has_lone_cr:
        raise ValueError("unsupported lone CR line ending")

    if has_crlf and has_lf:
        raise ValueError("mixed line endings are not allowed")

    if has_crlf:
        return b"\r\n"

    if has_lf:
        return b"\n"

    raise ValueError("file contains no detectable line ending")


def replace_exact_once(
    source: bytes,
    old: bytes,
    new: bytes,
) -> bytes:
    if not isinstance(source, bytes):
        raise ValueError("source must be bytes")

    if not isinstance(old, bytes):
        raise ValueError("old must be bytes")

    if not isinstance(new, bytes):
        raise ValueError("new must be bytes")

    if old == b"":
        raise ValueError("search value must not be empty")

    occurrences = source.count(old)

    if occurrences != 1:
        raise ValueError(
            "search value must occur exactly once; "
            f"found {occurrences}"
        )

    return source.replace(old, new, 1)



def update_local_build_files(
    *,
    dockerfile_bytes: bytes,
    config_bytes: bytes,
    target_upstream: SemVer,
    target_wrapper: WrapperVersion,
    target_digest: str,
) -> tuple[bytes, bytes]:
    repository = validate_repository_state(
        dockerfile_bytes=dockerfile_bytes,
        config_bytes=config_bytes,
        state_bytes=None,
    )

    if (
        repository.distribution_mode
        != DistributionMode.LOCAL_BUILD
    ):
        raise ValueError(
            "repository must use local-build distribution"
        )

    if target_upstream <= repository.upstream_version:
        raise ValueError(
            "target upstream version must be newer "
            "than current upstream version"
        )

    if target_wrapper.upstream != target_upstream:
        raise ValueError(
            "target wrapper upstream version does not "
            "match target upstream version"
        )

    target_digest = _validate_digest(
        target_digest,
        label="target upstream digest",
    )

    updated_dockerfile = replace_exact_once(
        dockerfile_bytes,
        (
            "ARG WEALTHFOLIO_VERSION="
            f"{repository.upstream_version}"
        ).encode("ascii"),
        (
            "ARG WEALTHFOLIO_VERSION="
            f"{target_upstream}"
        ).encode("ascii"),
    )

    updated_dockerfile = replace_exact_once(
        updated_dockerfile,
        (
            "ARG WEALTHFOLIO_DIGEST="
            f"{repository.upstream_digest}"
        ).encode("ascii"),
        (
            "ARG WEALTHFOLIO_DIGEST="
            f"{target_digest}"
        ).encode("ascii"),
    )

    updated_config = replace_exact_once(
        config_bytes,
        (
            f'version: "{repository.wrapper_version}"'
        ).encode("ascii"),
        (
            f'version: "{target_wrapper}"'
        ).encode("ascii"),
    )

    updated_repository = validate_repository_state(
        dockerfile_bytes=updated_dockerfile,
        config_bytes=updated_config,
        state_bytes=None,
    )

    if updated_repository.upstream_version != target_upstream:
        raise ValueError(
            "updated upstream version does not match target"
        )

    if updated_repository.upstream_digest != target_digest:
        raise ValueError(
            "updated upstream digest does not match target"
        )

    if updated_repository.wrapper_version != target_wrapper:
        raise ValueError(
            "updated wrapper version does not match target"
        )

    return updated_dockerfile, updated_config


def insert_after_exact_once(
    source: bytes,
    anchor: bytes,
    new_line: bytes,
) -> bytes:
    if not isinstance(source, bytes):
        raise ValueError("source must be bytes")

    if not isinstance(anchor, bytes):
        raise ValueError("anchor must be bytes")

    if not isinstance(new_line, bytes):
        raise ValueError("new_line must be bytes")

    if anchor == b"":
        raise ValueError("anchor must not be empty")

    if b"\r" in anchor or b"\n" in anchor:
        raise ValueError("anchor must be exactly one line")

    if b"\r" in new_line or b"\n" in new_line:
        raise ValueError("new_line must be exactly one line")

    line_ending = detect_line_ending(source)
    lines = source.split(line_ending)

    occurrences = sum(
        1
        for line in lines
        if line == anchor
    )

    if occurrences != 1:
        raise ValueError(
            "anchor line must occur exactly once; "
            f"found {occurrences}"
        )

    result: list[bytes] = []

    for line in lines:
        result.append(line)

        if line == anchor:
            result.append(new_line)

    return line_ending.join(result)

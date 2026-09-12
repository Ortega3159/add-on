from __future__ import annotations

import json
from dataclasses import dataclass

from .models import SemVer


@dataclass(frozen=True)
class UpstreamRelease:
    release_id: int
    tag_name: str
    version: SemVer


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


def _parse_stable_tag(tag_name: str) -> SemVer:
    if not tag_name.startswith("v"):
        raise ValueError(
            f"stable release tag must start with 'v': {tag_name!r}"
        )

    raw_version = tag_name[1:]

    try:
        version = SemVer.parse(raw_version)
    except ValueError as exc:
        raise ValueError(
            f"stable release tag is not strict vX.Y.Z: {tag_name!r}"
        ) from exc

    if tag_name != f"v{version}":
        raise ValueError(
            f"stable release tag is not canonical: {tag_name!r}"
        )

    return version


def parse_github_release_page(
    payload: bytes,
) -> tuple[UpstreamRelease, ...]:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "GitHub release payload is not valid UTF-8"
        ) from exc

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "GitHub release payload is not valid JSON"
        ) from exc

    if not isinstance(decoded, list):
        raise ValueError(
            "GitHub release payload must be a JSON array"
        )

    releases: list[UpstreamRelease] = []
    seen_versions: set[SemVer] = set()

    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ValueError(
                f"release at index {index} must be a JSON object"
            )

        required_fields = (
            "id",
            "tag_name",
            "draft",
            "prerelease",
        )

        missing = [
            field
            for field in required_fields
            if field not in item
        ]

        if missing:
            raise ValueError(
                f"release at index {index} is missing required fields: "
                + ", ".join(missing)
            )

        release_id = item["id"]
        tag_name = item["tag_name"]
        draft = item["draft"]
        prerelease = item["prerelease"]

        if type(release_id) is not int or release_id <= 0:
            raise ValueError(
                f"release at index {index} has invalid id"
            )

        if type(tag_name) is not str:
            raise ValueError(
                f"release at index {index} has invalid tag_name"
            )

        if type(draft) is not bool:
            raise ValueError(
                f"release at index {index} has invalid draft flag"
            )

        if type(prerelease) is not bool:
            raise ValueError(
                f"release at index {index} has invalid prerelease flag"
            )

        if draft or prerelease:
            continue

        version = _parse_stable_tag(tag_name)

        if version in seen_versions:
            raise ValueError(
                f"duplicate stable release version: {version}"
            )

        seen_versions.add(version)

        releases.append(
            UpstreamRelease(
                release_id=release_id,
                tag_name=tag_name,
                version=version,
            )
        )

    releases.sort(key=lambda release: release.version)

    return tuple(releases)

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


@dataclass(frozen=True)
class GitHubReleasePageResponse:
    body: bytes
    link_header: str | None


def _has_next_link(link_header: str | None) -> bool:
    if link_header is None:
        return False

    if type(link_header) is not str:
        raise TypeError("Link header must be a string or None")

    if not link_header.strip():
        raise ValueError("Link header must not be empty")

    entries = link_header.split(",")
    found_next = False

    for raw_entry in entries:
        entry = raw_entry.strip()

        if not entry:
            raise ValueError("malformed Link header")

        parts = [
            part.strip()
            for part in entry.split(";")
        ]

        if len(parts) < 2:
            raise ValueError("malformed Link header")

        target = parts[0]

        if (
            len(target) < 3
            or not target.startswith("<")
            or not target.endswith(">")
        ):
            raise ValueError("malformed Link header")

        relations: list[str] = []
        rel_parameter_count = 0

        for parameter in parts[1:]:
            if not parameter:
                raise ValueError("malformed Link header")

            if parameter.startswith("rel="):
                rel_parameter_count += 1

                if rel_parameter_count > 1:
                    raise ValueError(
                        "multiple rel parameters in Link entry"
                    )

                value = parameter[4:]

                if (
                    len(value) < 2
                    or not value.startswith('"')
                    or not value.endswith('"')
                ):
                    raise ValueError("malformed Link header")

                tokens = [
                    relation
                    for relation in value[1:-1].split()
                    if relation
                ]

                if len(tokens) != len(set(tokens)):
                    raise ValueError(
                        "duplicate relation token in Link entry"
                    )

                relations.extend(tokens)

        if not relations:
            raise ValueError(
                "Link entry is missing rel parameter"
            )

        if "next" in relations:
            if found_next:
                raise ValueError(
                    "Link header contains multiple next relations"
                )

            found_next = True

    return found_next

def discover_github_releases(
    fetch_page,
    *,
    max_pages: int = 100,
) -> tuple[UpstreamRelease, ...]:
    if type(max_pages) is not int or max_pages <= 0:
        raise ValueError(
            "max_pages must be a positive integer"
        )

    releases: list[UpstreamRelease] = []
    seen_versions: set[SemVer] = set()
    seen_release_ids: set[int] = set()

    page = 1

    while True:
        if page > max_pages:
            raise ValueError(
                "GitHub release discovery exceeded page limit"
            )

        response = fetch_page(page)

        if not isinstance(
            response,
            GitHubReleasePageResponse,
        ):
            raise TypeError(
                "fetch_page must return "
                "GitHubReleasePageResponse"
            )

        page_releases = parse_github_release_page(
            response.body
        )

        for release in page_releases:
            if release.version in seen_versions:
                raise ValueError(
                    "duplicate stable release version "
                    f"across pages: {release.version}"
                )

            if release.release_id in seen_release_ids:
                raise ValueError(
                    "duplicate release id across pages: "
                    f"{release.release_id}"
                )

            seen_versions.add(release.version)
            seen_release_ids.add(release.release_id)
            releases.append(release)

        if not _has_next_link(response.link_header):
            break

        page += 1

    releases.sort(key=lambda release: release.version)

    return tuple(releases)

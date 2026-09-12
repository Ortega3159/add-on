
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


_STRICT_SEMVER_RE = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)


_STRICT_WRAPPER_VERSION_RE = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)-"
    r"([1-9][0-9]*)"
)


class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        if not isinstance(value, str):
            raise ValueError("semantic version must be a string")

        match = _STRICT_SEMVER_RE.fullmatch(value)
        if match is None:
            raise ValueError(
                f"invalid strict semantic version: {value!r}"
            )

        return cls(
            *(int(part) for part in match.groups())
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class WrapperVersion:
    upstream: SemVer
    revision: int

    @classmethod
    def parse(cls, value: str) -> "WrapperVersion":
        if not isinstance(value, str):
            raise ValueError(
                "wrapper version must be a string"
            )

        match = _STRICT_WRAPPER_VERSION_RE.fullmatch(
            value
        )
        if match is None:
            raise ValueError(
                f"invalid wrapper version: {value!r}"
            )

        major, minor, patch, revision = (
            int(part) for part in match.groups()
        )

        return cls(
            upstream=SemVer(
                major=major,
                minor=minor,
                patch=patch,
            ),
            revision=revision,
        )

    def __str__(self) -> str:
        return f"{self.upstream}-{self.revision}"


class ReleasePolicy(str, Enum):
    AUTO = "AUTO"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK_MAJOR = "BLOCK_MAJOR"
    NO_UPDATE = "NO_UPDATE"


class DistributionMode(str, Enum):
    LOCAL_BUILD = "LOCAL_BUILD"
    PREBUILT = "PREBUILT"


class CandidateSelection:
    version: SemVer | None
    policy: ReleasePolicy


class PrebuiltBootstrap:
    upstream: SemVer
    candidate_wrapper: WrapperVersion


class RepositoryState:
    upstream_version: SemVer
    upstream_digest: str
    wrapper_version: WrapperVersion
    architectures: frozenset[str]
    distribution_mode: DistributionMode
    image: str | None
    published_digest: str | None

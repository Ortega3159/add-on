from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .models import (
    DistributionMode,
    RepositoryState,
)


class DockerRuntimeError(RuntimeError):
    pass


def run_docker(
    arguments: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    timeout_seconds: int = 30,
    operation: str,
) -> bytes:
    command = [
        "docker",
        *arguments,
    ]

    run_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout_seconds,
        "check": False,
        "shell": False,
    }

    if input_bytes is None:
        run_kwargs["stdin"] = subprocess.DEVNULL
    else:
        run_kwargs["input"] = input_bytes

    try:
        result = subprocess.run(
            command,
            **run_kwargs,
        )
    except FileNotFoundError as exc:
        raise DockerRuntimeError(
            "Docker CLI is unavailable while trying to "
            f"{operation}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerRuntimeError(
            f"Docker {operation} timed out"
        ) from exc
    except OSError as exc:
        raise DockerRuntimeError(
            f"Docker {operation} could not be executed"
        ) from exc

    if result.returncode != 0:
        raise DockerRuntimeError(
            f"Docker {operation} failed with "
            f"exit code {result.returncode}"
        )

    if not isinstance(result.stdout, bytes):
        raise DockerRuntimeError(
            "Docker command output must be bytes"
        )

    return result.stdout


@dataclass(frozen=True)
class WrapperBuildResult:
    tag: str
    architecture: str
    platform: str


def build_amd64_wrapper_image(
    *,
    repository_root: Path,
    repository: RepositoryState,
) -> WrapperBuildResult:
    if not isinstance(repository_root, Path):
        raise TypeError(
            "repository_root must be a Path"
        )

    if not isinstance(repository, RepositoryState):
        raise TypeError(
            "repository must be a RepositoryState"
        )

    if (
        repository.distribution_mode
        is not DistributionMode.LOCAL_BUILD
    ):
        raise DockerRuntimeError(
            "runtime build requires LOCAL_BUILD "
            "repository state"
        )

    if (
        repository.wrapper_version.upstream
        != repository.upstream_version
    ):
        raise DockerRuntimeError(
            "wrapper upstream version does not "
            "match repository upstream version"
        )

    if repository.image is not None:
        raise DockerRuntimeError(
            "LOCAL_BUILD repository must not "
            "declare an image"
        )

    if repository.published_digest is not None:
        raise DockerRuntimeError(
            "LOCAL_BUILD repository must not "
            "declare a published digest"
        )

    if "amd64" not in repository.architectures:
        raise DockerRuntimeError(
            "repository does not declare "
            "amd64 architecture"
        )

    architecture = "amd64"
    platform = "linux/amd64"
    tag = (
        "wealthfolio-runtime-test:"
        f"{repository.wrapper_version}-amd64"
    )

    run_docker(
        [
            "build",
            "--pull",
            "--platform",
            platform,
            "--build-arg",
            (
                "WEALTHFOLIO_VERSION="
                f"{repository.upstream_version}"
            ),
            "--build-arg",
            (
                "WEALTHFOLIO_DIGEST="
                f"{repository.upstream_digest}"
            ),
            "--build-arg",
            (
                "BUILD_VERSION="
                f"{repository.wrapper_version}"
            ),
            "--build-arg",
            "BUILD_ARCH=amd64",
            "--tag",
            tag,
            str(repository_root / "tracker"),
        ],
        timeout_seconds=600,
        operation="build amd64 wrapper image",
    )

    return WrapperBuildResult(
        tag=tag,
        architecture=architecture,
        platform=platform,
    )


_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class WrapperImageInspection:
    image_id: str
    tag: str
    os: str
    architecture: str
    command: tuple[str, ...]
    hass_version: str
    hass_arch: str
    hass_type: str


def inspect_amd64_wrapper_image(
    *,
    repository: RepositoryState,
    build: WrapperBuildResult,
) -> WrapperImageInspection:
    if not isinstance(repository, RepositoryState):
        raise TypeError(
            "repository must be a RepositoryState"
        )

    if not isinstance(build, WrapperBuildResult):
        raise TypeError(
            "build must be a WrapperBuildResult"
        )

    expected_tag = (
        "wealthfolio-runtime-test:"
        f"{repository.wrapper_version}-amd64"
    )

    if build.tag != expected_tag:
        raise DockerRuntimeError(
            "runtime image tag does not match "
            "repository state"
        )

    if build.architecture != "amd64":
        raise DockerRuntimeError(
            "runtime build architecture must be amd64"
        )

    if build.platform != "linux/amd64":
        raise DockerRuntimeError(
            "runtime build platform must be linux/amd64"
        )

    output = run_docker(
        [
            "image",
            "inspect",
            build.tag,
        ],
        timeout_seconds=30,
        operation="inspect amd64 wrapper image",
    )

    try:
        decoded = json.loads(output)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DockerRuntimeError(
            "Docker image inspect output is invalid JSON"
        ) from exc

    if (
        not isinstance(decoded, list)
        or len(decoded) != 1
        or not isinstance(decoded[0], dict)
    ):
        raise DockerRuntimeError(
            "Docker image inspect output has invalid shape"
        )

    image = decoded[0]

    image_id = image.get("Id")
    os_name = image.get("Os")
    architecture = image.get("Architecture")
    config = image.get("Config")

    if (
        type(image_id) is not str
        or _IMAGE_ID_RE.fullmatch(image_id) is None
    ):
        raise DockerRuntimeError(
            "built wrapper image ID is invalid"
        )

    if os_name != "linux":
        raise DockerRuntimeError(
            "built wrapper image operating system "
            "does not match linux"
        )

    if architecture != "amd64":
        raise DockerRuntimeError(
            "built wrapper image architecture "
            "does not match amd64"
        )

    if not isinstance(config, dict):
        raise DockerRuntimeError(
            "built wrapper image Config is invalid"
        )

    command = config.get("Cmd")

    if command != ["/run.sh"]:
        raise DockerRuntimeError(
            "built wrapper image command "
            "does not match /run.sh"
        )

    labels = config.get("Labels")

    if not isinstance(labels, dict):
        raise DockerRuntimeError(
            "built wrapper image labels are invalid"
        )

    hass_version = labels.get("io.hass.version")
    hass_arch = labels.get("io.hass.arch")
    hass_type = labels.get("io.hass.type")

    expected_version = str(repository.wrapper_version)

    if hass_version != expected_version:
        raise DockerRuntimeError(
            "built wrapper image io.hass.version "
            "does not match repository state"
        )

    if hass_arch != "amd64":
        raise DockerRuntimeError(
            "built wrapper image io.hass.arch "
            "does not match amd64"
        )

    if hass_type != "app":
        raise DockerRuntimeError(
            "built wrapper image io.hass.type "
            "does not match app"
        )

    return WrapperImageInspection(
        image_id=image_id,
        tag=build.tag,
        os=os_name,
        architecture=architecture,
        command=tuple(command),
        hass_version=hass_version,
        hass_arch=hass_arch,
        hass_type=hass_type,
    )

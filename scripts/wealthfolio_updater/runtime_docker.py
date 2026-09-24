from __future__ import annotations

import json
import re
import subprocess
import time
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

_RUNTIME_DATA_VOLUME_NAME_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*"
)


@dataclass(frozen=True)
class RuntimeDataVolume:
    name: str


def _validate_runtime_data_volume_name(
    name: object,
) -> str:
    if (
        type(name) is not str
        or _RUNTIME_DATA_VOLUME_NAME_RE.fullmatch(name)
        is None
    ):
        raise DockerRuntimeError(
            "runtime data volume name is invalid"
        )

    return name


def _validate_runtime_image_inspection(
    image: object,
) -> WrapperImageInspection:
    if not isinstance(
        image,
        WrapperImageInspection,
    ):
        raise TypeError(
            "image must be a WrapperImageInspection"
        )

    if (
        type(image.image_id) is not str
        or _IMAGE_ID_RE.fullmatch(image.image_id) is None
        or image.os != "linux"
        or image.architecture != "amd64"
        or image.command != ("/run.sh",)
        or image.hass_arch != "amd64"
        or image.hass_type != "app"
    ):
        raise DockerRuntimeError(
            "runtime image inspection is invalid"
        )

    return image


def create_runtime_data_volume() -> RuntimeDataVolume:
    output = run_docker(
        [
            "volume",
            "create",
            "--label",
            "io.wealthfolio.runtime-test=true",
            "--label",
            "io.wealthfolio.runtime-test.role=data",
        ],
        timeout_seconds=30,
        operation="create runtime data volume",
    )

    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DockerRuntimeError(
            "runtime data volume name is invalid"
        ) from exc

    if decoded.endswith("\n"):
        name = decoded[:-1]
    else:
        name = decoded

    _validate_runtime_data_volume_name(name)

    return RuntimeDataVolume(
        name=name,
    )


def seed_runtime_options(
    *,
    volume: RuntimeDataVolume,
    image: WrapperImageInspection,
    options_bytes: bytes,
) -> None:
    if not isinstance(
        volume,
        RuntimeDataVolume,
    ):
        raise TypeError(
            "volume must be a RuntimeDataVolume"
        )

    volume_name = _validate_runtime_data_volume_name(
        volume.name
    )

    validated_image = (
        _validate_runtime_image_inspection(image)
    )

    if type(options_bytes) is not bytes:
        raise TypeError(
            "options_bytes must be bytes"
        )

    run_docker(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--mount",
            (
                "type=volume,"
                f"source={volume_name},"
                "destination=/data"
            ),
            "--entrypoint",
            "/bin/sh",
            "--interactive",
            validated_image.image_id,
            "-c",
            (
                "umask 077\n"
                "cat > /data/options.json\n"
            ),
        ],
        input_bytes=options_bytes,
        timeout_seconds=30,
        operation="seed runtime options",
    )

_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class RuntimeContainer:
    container_id: str


def runtime_test_options_bytes() -> bytes:
    return (
        b'{"auth_password_hash":'
        b'"$argon2id$v=19$m=19456,t=2,p=1$'
        b'd2VhbHRoZm9saW8tdGVzdCE$'
        b'OkbKuJHEwf5aVPMa6jo/umIqdm2MDXwBK4DVTDXFFOw",'
        b'"cors_allow_origins":"http://127.0.0.1",'
        b'"auth_token_ttl_minutes":480}\n'
    )


def start_runtime_container(
    *,
    volume: RuntimeDataVolume,
    image: WrapperImageInspection,
) -> RuntimeContainer:
    if not isinstance(
        volume,
        RuntimeDataVolume,
    ):
        raise TypeError(
            "volume must be a RuntimeDataVolume"
        )

    volume_name = _validate_runtime_data_volume_name(
        volume.name
    )

    validated_image = (
        _validate_runtime_image_inspection(image)
    )

    output = run_docker(
        [
            "run",
            "--detach",
            "--init",
            "--network",
            "none",
            "--label",
            "io.wealthfolio.runtime-test=true",
            "--label",
            "io.wealthfolio.runtime-test.role=runtime",
            "--mount",
            (
                "type=volume,"
                f"source={volume_name},"
                "destination=/data"
            ),
            "--env",
            "WF_LISTEN_ADDR=0.0.0.0:8088",
            "--env",
            (
                "WF_DB_PATH="
                "/data/wealthfolio/wealthfolio.db"
            ),
            "--env",
            "WF_AUTH_REQUIRED=true",
            "--env",
            "WF_MCP_ENABLED=false",
            validated_image.image_id,
        ],
        timeout_seconds=30,
        operation="start runtime container",
    )

    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DockerRuntimeError(
            "runtime container ID is invalid"
        ) from exc

    if decoded.endswith("\n"):
        container_id = decoded[:-1]
    else:
        container_id = decoded

    if (
        _CONTAINER_ID_RE.fullmatch(container_id)
        is None
    ):
        raise DockerRuntimeError(
            "runtime container ID is invalid"
        )

    return RuntimeContainer(
        container_id=container_id,
    )

def _validate_runtime_container_id(
    container_id: object,
) -> str:
    if (
        type(container_id) is not str
        or _CONTAINER_ID_RE.fullmatch(container_id)
        is None
    ):
        raise DockerRuntimeError(
            "runtime container ID is invalid"
        )

    return container_id


def runtime_health_request_bytes() -> bytes:
    return (
        b"GET /api/v1/healthz HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        b"\r\n"
    )


def runtime_http_exchange(
    *,
    container: RuntimeContainer,
    request_bytes: bytes,
) -> bytes:
    if not isinstance(
        container,
        RuntimeContainer,
    ):
        raise TypeError(
            "container must be a RuntimeContainer"
        )

    container_id = _validate_runtime_container_id(
        container.container_id
    )

    if type(request_bytes) is not bytes:
        raise TypeError(
            "request_bytes must be bytes"
        )

    return run_docker(
        [
            "exec",
            "--interactive",
            container_id,
            "nc",
            "-w",
            "2",
            "127.0.0.1",
            "8088",
        ],
        input_bytes=request_bytes,
        timeout_seconds=5,
        operation="probe runtime HTTP",
    )



@dataclass(frozen=True)
class RuntimeHttpResponse:
    status_code: int
    reason_phrase: str
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True, repr=False)
class RuntimeSessionCookie:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or not self.value:
            raise DockerRuntimeError(
                "runtime session cookie is invalid"
            )

    def __repr__(self) -> str:
        return "RuntimeSessionCookie(<redacted>)"


def _decode_runtime_chunked_body(
    body: bytes,
) -> bytes:
    decoded = bytearray()
    position = 0

    while True:
        line_end = body.find(
            b"\r\n",
            position,
        )

        if line_end < 0:
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            )

        size_field = body[
            position:line_end
        ].split(
            b";",
            1,
        )[0]

        try:
            size = int(
                size_field,
                16,
            )
        except ValueError as exc:
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            ) from exc

        position = line_end + 2

        if size == 0:
            if body[position:] != b"\r\n":
                raise DockerRuntimeError(
                    "runtime HTTP response is invalid"
                )

            return bytes(decoded)

        chunk_end = position + size

        if chunk_end + 2 > len(body):
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            )

        decoded.extend(
            body[position:chunk_end]
        )

        if body[
            chunk_end:chunk_end + 2
        ] != b"\r\n":
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            )

        position = chunk_end + 2


def parse_runtime_http_response(
    response: bytes,
) -> RuntimeHttpResponse:
    if type(response) is not bytes:
        raise TypeError(
            "response must be bytes"
        )

    head, separator, body = response.partition(
        b"\r\n\r\n"
    )

    if separator != b"\r\n\r\n":
        raise DockerRuntimeError(
            "runtime HTTP response is invalid"
        )

    lines = head.split(b"\r\n")

    if not lines:
        raise DockerRuntimeError(
            "runtime HTTP response is invalid"
        )

    status_parts = lines[0].split(
        b" ",
        2,
    )

    if (
        len(status_parts) != 3
        or status_parts[0] != b"HTTP/1.1"
        or len(status_parts[1]) != 3
        or not status_parts[1].isdigit()
    ):
        raise DockerRuntimeError(
            "runtime HTTP response is invalid"
        )

    status_code = int(
        status_parts[1]
    )

    if not 100 <= status_code <= 599:
        raise DockerRuntimeError(
            "runtime HTTP response is invalid"
        )

    try:
        reason_phrase = status_parts[2].decode(
            "ascii"
        )
    except UnicodeDecodeError as exc:
        raise DockerRuntimeError(
            "runtime HTTP response is invalid"
        ) from exc

    headers = []

    for line in lines[1:]:
        name, colon, value = line.partition(
            b":"
        )

        if colon != b":" or not name:
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            )

        try:
            header_name = name.decode(
                "ascii"
            )
            header_value = value.decode(
                "latin-1"
            ).strip()
        except UnicodeDecodeError as exc:
            raise DockerRuntimeError(
                "runtime HTTP response is invalid"
            ) from exc

        headers.append(
            (
                header_name,
                header_value,
            )
        )

    transfer_encodings = [
        value.lower()
        for name, value in headers
        if name.lower()
        == "transfer-encoding"
    ]

    if (
        transfer_encodings
        and "chunked"
        in transfer_encodings[-1]
    ):
        body = _decode_runtime_chunked_body(
            body
        )

    return RuntimeHttpResponse(
        status_code=status_code,
        reason_phrase=reason_phrase,
        headers=tuple(headers),
        body=body,
    )



def _runtime_request_bytes(
    *,
    method: str,
    path: str,
    json_body: object | None = None,
    session: RuntimeSessionCookie | None = None,
) -> bytes:
    headers = [
        f"{method} {path} HTTP/1.1",
        "Host: 127.0.0.1",
        "Accept: application/json",
    ]

    payload = b""

    if json_body is not None:
        payload = json.dumps(
            json_body,
            separators=(",", ":"),
        ).encode("utf-8")

        headers.append(
            "Content-Type: application/json"
        )
        headers.append(
            f"Content-Length: {len(payload)}"
        )

    if session is not None:
        if not isinstance(
            session,
            RuntimeSessionCookie,
        ):
            raise TypeError(
                "session must be a RuntimeSessionCookie"
            )

        headers.append(
            f"Cookie: wf_session={session.value}"
        )

    headers.append("Connection: close")

    return (
        "\r\n".join(headers).encode("ascii")
        + b"\r\n\r\n"
        + payload
    )


def _runtime_json_response(
    response: RuntimeHttpResponse,
    *,
    error_message: str,
) -> object:
    try:
        return json.loads(
            response.body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise DockerRuntimeError(
            error_message
        ) from exc


def runtime_login(
    *,
    container: RuntimeContainer,
    password: str,
) -> RuntimeSessionCookie:
    if type(password) is not str or not password:
        raise DockerRuntimeError(
            "runtime login password is invalid"
        )

    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="POST",
            path="/api/v1/auth/login",
            json_body={
                "password": password,
            },
        ),
    )

    try:
        response = parse_runtime_http_response(
            raw_response
        )
    except DockerRuntimeError as exc:
        raise DockerRuntimeError(
            "runtime login response is invalid"
        ) from exc

    if response.status_code != 200:
        raise DockerRuntimeError(
            "runtime login failed"
        )

    payload = _runtime_json_response(
        response,
        error_message=(
            "runtime login response is invalid"
        ),
    )

    if (
        type(payload) is not dict
        or payload.get("authenticated") is not True
        or type(payload.get("expiresIn")) is not int
        or payload["expiresIn"] <= 0
    ):
        raise DockerRuntimeError(
            "runtime login response is invalid"
        )

    session_values = []

    for name, value in response.headers:
        if name.lower() != "set-cookie":
            continue

        pair = value.split(
            ";",
            1,
        )[0]

        cookie_name, separator, cookie_value = (
            pair.partition("=")
        )

        if (
            separator == "="
            and cookie_name.strip()
            == "wf_session"
        ):
            session_values.append(
                cookie_value
            )

    if (
        len(session_values) != 1
        or not session_values[0]
    ):
        raise DockerRuntimeError(
            "runtime login response is invalid"
        )

    return RuntimeSessionCookie(
        value=session_values[0],
    )


def runtime_auth_me(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
) -> bool:
    if not isinstance(
        session,
        RuntimeSessionCookie,
    ):
        raise TypeError(
            "session must be a RuntimeSessionCookie"
        )

    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="GET",
            path="/api/v1/auth/me",
            session=session,
        ),
    )

    try:
        response = parse_runtime_http_response(
            raw_response
        )
    except DockerRuntimeError as exc:
        raise DockerRuntimeError(
            "runtime authentication check failed"
        ) from exc

    if response.status_code != 200:
        raise DockerRuntimeError(
            "runtime authentication check failed"
        )

    payload = _runtime_json_response(
        response,
        error_message=(
            "runtime authentication check failed"
        ),
    )

    if (
        type(payload) is not dict
        or payload.get("authenticated") is not True
    ):
        raise DockerRuntimeError(
            "runtime authentication check failed"
        )

    return True



def runtime_get_accounts(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
) -> list[dict[str, object]]:
    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="GET",
            path="/api/v1/accounts",
            session=session,
        ),
    )

    try:
        response = parse_runtime_http_response(
            raw_response
        )
    except DockerRuntimeError as exc:
        raise DockerRuntimeError(
            "runtime accounts response is invalid"
        ) from exc

    if response.status_code != 200:
        raise DockerRuntimeError(
            "runtime accounts response is invalid"
        )

    payload = _runtime_json_response(
        response,
        error_message=(
            "runtime accounts response is invalid"
        ),
    )

    if (
        type(payload) is not list
        or any(
            type(account) is not dict
            for account in payload
        )
    ):
        raise DockerRuntimeError(
            "runtime accounts response is invalid"
        )

    return payload



def runtime_create_cash_account(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
    name: str,
    currency: str,
) -> dict[str, object]:
    if type(name) is not str or not name:
        raise DockerRuntimeError(
            "runtime account name is invalid"
        )

    if type(currency) is not str or not currency:
        raise DockerRuntimeError(
            "runtime account currency is invalid"
        )

    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="POST",
            path="/api/v1/accounts",
            json_body={
                "name": name,
                "accountType": "CASH",
                "currency": currency,
                "isDefault": False,
                "isActive": True,
            },
            session=session,
        ),
    )

    if raw_response:
        try:
            response = parse_runtime_http_response(
                raw_response
            )
        except DockerRuntimeError as exc:
            raise DockerRuntimeError(
                "runtime account creation failed"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise DockerRuntimeError(
                "runtime account creation failed"
            )

    accounts = runtime_get_accounts(
        container=container,
        session=session,
    )

    matches = [
        account
        for account in accounts
        if (
            account.get("name") == name
            and account.get("accountType") == "CASH"
            and account.get("currency") == currency
            and account.get("isDefault") is False
            and account.get("isActive") is True
        )
    ]

    if len(matches) != 1:
        raise DockerRuntimeError(
            "runtime account creation could not be confirmed"
        )

    account = matches[0]
    account_id = account.get("id")

    if type(account_id) is not str or not account_id:
        raise DockerRuntimeError(
            "runtime account creation could not be confirmed"
        )

    return account



def runtime_search_deposits(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
    account_id: str,
) -> list[dict[str, object]]:
    if type(account_id) is not str or not account_id:
        raise DockerRuntimeError(
            "runtime account ID is invalid"
        )

    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="POST",
            path="/api/v1/activities/search",
            json_body={
                "page": 0,
                "pageSize": 20,
                "accountIdFilter": account_id,
                "activityTypeFilter": "DEPOSIT",
            },
            session=session,
        ),
    )

    try:
        response = parse_runtime_http_response(
            raw_response
        )
    except DockerRuntimeError as exc:
        raise DockerRuntimeError(
            "runtime activities response is invalid"
        ) from exc

    if response.status_code != 200:
        raise DockerRuntimeError(
            "runtime activities response is invalid"
        )

    payload = _runtime_json_response(
        response,
        error_message=(
            "runtime activities response is invalid"
        ),
    )

    if type(payload) is not dict:
        raise DockerRuntimeError(
            "runtime activities response is invalid"
        )

    data = payload.get("data")

    if (
        type(data) is not list
        or any(
            type(activity) is not dict
            for activity in data
        )
    ):
        raise DockerRuntimeError(
            "runtime activities response is invalid"
        )

    return data


def runtime_create_test_deposit(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
    account_id: str,
) -> dict[str, object]:
    if type(account_id) is not str or not account_id:
        raise DockerRuntimeError(
            "runtime account ID is invalid"
        )

    expected_date = "2026-01-15T12:00:00+00:00"
    expected_amount = "123.45"
    expected_comment = "WU4C deterministic deposit"

    raw_response = runtime_http_exchange(
        container=container,
        request_bytes=_runtime_request_bytes(
            method="POST",
            path="/api/v1/activities",
            json_body={
                "accountId": account_id,
                "activityType": "DEPOSIT",
                "activityDate": (
                    "2026-01-15T12:00:00.000Z"
                ),
                "amount": 123.45,
                "currency": "USD",
                "comment": expected_comment,
                "fxRate": None,
            },
            session=session,
        ),
    )

    if raw_response:
        try:
            response = parse_runtime_http_response(
                raw_response
            )
        except DockerRuntimeError as exc:
            raise DockerRuntimeError(
                "runtime deposit creation failed"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise DockerRuntimeError(
                "runtime deposit creation failed"
            )

    activities = runtime_search_deposits(
        container=container,
        session=session,
        account_id=account_id,
    )

    matches = [
        activity
        for activity in activities
        if (
            activity.get("accountId") == account_id
            and activity.get("activityType")
            == "DEPOSIT"
            and activity.get("status") == "POSTED"
            and activity.get("date")
            == expected_date
            and activity.get("amount")
            == expected_amount
            and activity.get("currency") == "USD"
            and activity.get("comment")
            == expected_comment
        )
    ]

    if len(matches) != 1:
        raise DockerRuntimeError(
            "runtime deposit creation could not be confirmed"
        )

    activity = matches[0]
    activity_id = activity.get("id")

    if (
        type(activity_id) is not str
        or not activity_id
    ):
        raise DockerRuntimeError(
            "runtime deposit creation could not be confirmed"
        )

    return activity



@dataclass(frozen=True)
class RuntimeFunctionalSnapshot:
    account_id: str
    activity_id: str
    account_name: str
    account_type: str
    account_currency: str
    activity_type: str
    activity_status: str
    activity_date: str
    amount: str
    activity_currency: str
    comment: str


def capture_runtime_functional_snapshot(
    *,
    container: RuntimeContainer,
    session: RuntimeSessionCookie,
    account_id: str,
) -> RuntimeFunctionalSnapshot:
    if type(account_id) is not str or not account_id:
        raise DockerRuntimeError(
            "runtime functional snapshot is invalid"
        )

    accounts = runtime_get_accounts(
        container=container,
        session=session,
    )

    account_matches = [
        account
        for account in accounts
        if (
            account.get("id") == account_id
            and account.get("name")
            == "WU4C Test Cash"
            and account.get("accountType")
            == "CASH"
            and account.get("currency")
            == "USD"
            and account.get("isDefault") is False
            and account.get("isActive") is True
        )
    ]

    if len(account_matches) != 1:
        raise DockerRuntimeError(
            "runtime functional snapshot is invalid"
        )

    account = account_matches[0]

    deposits = runtime_search_deposits(
        container=container,
        session=session,
        account_id=account_id,
    )

    deposit_matches = [
        activity
        for activity in deposits
        if (
            activity.get("accountId")
            == account_id
            and activity.get("activityType")
            == "DEPOSIT"
            and activity.get("status")
            == "POSTED"
            and activity.get("date")
            == "2026-01-15T12:00:00+00:00"
            and activity.get("amount")
            == "123.45"
            and activity.get("currency")
            == "USD"
            and activity.get("comment")
            == "WU4C deterministic deposit"
        )
    ]

    if len(deposit_matches) != 1:
        raise DockerRuntimeError(
            "runtime functional snapshot is invalid"
        )

    activity = deposit_matches[0]

    activity_id = activity.get("id")

    if (
        type(activity_id) is not str
        or not activity_id
    ):
        raise DockerRuntimeError(
            "runtime functional snapshot is invalid"
        )

    return RuntimeFunctionalSnapshot(
        account_id=account_id,
        activity_id=activity_id,
        account_name="WU4C Test Cash",
        account_type="CASH",
        account_currency="USD",
        activity_type="DEPOSIT",
        activity_status="POSTED",
        activity_date=(
            "2026-01-15T12:00:00+00:00"
        ),
        amount="123.45",
        activity_currency="USD",
        comment="WU4C deterministic deposit",
    )


def runtime_health_response_is_ready(
    response: bytes,
) -> bool:
    if type(response) is not bytes:
        raise TypeError(
            "response must be bytes"
        )

    head, separator, body = response.partition(
        b"\r\n\r\n"
    )

    if separator != b"\r\n\r\n":
        return False

    status_line = head.split(
        b"\r\n",
        1,
    )[0]

    if status_line != b"HTTP/1.1 200 OK":
        return False

    return body == b"ok"

@dataclass(frozen=True)
class RuntimeContainerState:
    status: str
    running: bool
    exit_code: int


def inspect_runtime_container_state(
    *,
    container: RuntimeContainer,
) -> RuntimeContainerState:
    if not isinstance(
        container,
        RuntimeContainer,
    ):
        raise TypeError(
            "container must be a RuntimeContainer"
        )

    container_id = _validate_runtime_container_id(
        container.container_id
    )

    output = run_docker(
        [
            "inspect",
            container_id,
            "--format",
            "{{json .State}}",
        ],
        timeout_seconds=30,
        operation="inspect runtime container state",
    )

    try:
        decoded = json.loads(output)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise DockerRuntimeError(
            "runtime container state is invalid"
        ) from exc

    if not isinstance(decoded, dict):
        raise DockerRuntimeError(
            "runtime container state is invalid"
        )

    status = decoded.get("Status")
    running = decoded.get("Running")
    exit_code = decoded.get("ExitCode")

    if (
        type(status) is not str
        or not status
        or type(running) is not bool
        or type(exit_code) is not int
    ):
        raise DockerRuntimeError(
            "runtime container state is invalid"
        )

    return RuntimeContainerState(
        status=status,
        running=running,
        exit_code=exit_code,
    )


def wait_runtime_ready(
    *,
    container: RuntimeContainer,
    max_attempts: int,
    delay_seconds: float,
) -> bytes:
    if not isinstance(
        container,
        RuntimeContainer,
    ):
        raise TypeError(
            "container must be a RuntimeContainer"
        )

    _validate_runtime_container_id(
        container.container_id
    )

    if (
        type(max_attempts) is not int
        or max_attempts <= 0
    ):
        raise ValueError(
            "max_attempts must be a positive integer"
        )

    if (
        type(delay_seconds) not in (int, float)
        or isinstance(delay_seconds, bool)
        or delay_seconds < 0
    ):
        raise ValueError(
            "delay_seconds must be non-negative"
        )

    request = runtime_health_request_bytes()

    for attempt in range(max_attempts):
        state = inspect_runtime_container_state(
            container=container,
        )

        if not state.running:
            raise DockerRuntimeError(
                "runtime container stopped before "
                "becoming healthy "
                f"(status={state.status}, "
                f"exit_code={state.exit_code})"
            )

        try:
            response = runtime_http_exchange(
                container=container,
                request_bytes=request,
            )
        except DockerRuntimeError:
            response = None

        if (
            response is not None
            and runtime_health_response_is_ready(
                response
            )
        ):
            return response

        if attempt + 1 < max_attempts:
            time.sleep(delay_seconds)

    raise DockerRuntimeError(
        "runtime container did not become healthy"
    )

@dataclass(frozen=True)
class RuntimeBootstrapInspection:
    secret_uid: int
    secret_gid: int
    secret_mode: str
    secret_size: int
    secret_decoded_bytes: int
    data_uid: int
    data_gid: int
    data_mode: str
    db_uid: int
    db_gid: int
    db_mode: str
    db_size: int
    options_uid: int
    options_gid: int
    options_mode: str
    options_size: int


_BOOTSTRAP_INTEGER_FIELDS = frozenset(
    {
        "secret_uid",
        "secret_gid",
        "secret_size",
        "secret_decoded_bytes",
        "data_uid",
        "data_gid",
        "db_uid",
        "db_gid",
        "db_size",
        "options_uid",
        "options_gid",
        "options_size",
    }
)

_BOOTSTRAP_MODE_FIELDS = frozenset(
    {
        "secret_mode",
        "data_mode",
        "db_mode",
        "options_mode",
    }
)

_BOOTSTRAP_FIELDS = (
    _BOOTSTRAP_INTEGER_FIELDS
    | _BOOTSTRAP_MODE_FIELDS
)


def _parse_runtime_bootstrap_output(
    output: bytes,
) -> dict[str, int | str]:
    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DockerRuntimeError(
            "runtime bootstrap inspection is invalid"
        ) from exc

    values: dict[str, int | str] = {}

    for line in decoded.splitlines():
        key, separator, value = line.partition("=")

        if (
            separator != "="
            or key not in _BOOTSTRAP_FIELDS
            or key in values
            or value == ""
        ):
            raise DockerRuntimeError(
                "runtime bootstrap inspection is invalid"
            )

        if key in _BOOTSTRAP_INTEGER_FIELDS:
            if (
                not value.isascii()
                or not value.isdecimal()
            ):
                raise DockerRuntimeError(
                    "runtime bootstrap inspection is invalid"
                )

            values[key] = int(value)

        else:
            if (
                not value.isascii()
                or re.fullmatch(
                    r"[0-7]{1,4}",
                    value,
                )
                is None
            ):
                raise DockerRuntimeError(
                    "runtime bootstrap inspection is invalid"
                )

            values[key] = value

    if set(values) != _BOOTSTRAP_FIELDS:
        raise DockerRuntimeError(
            "runtime bootstrap inspection is invalid"
        )

    return values


def inspect_runtime_bootstrap(
    *,
    container: RuntimeContainer,
) -> RuntimeBootstrapInspection:
    if not isinstance(
        container,
        RuntimeContainer,
    ):
        raise TypeError(
            "container must be a RuntimeContainer"
        )

    container_id = _validate_runtime_container_id(
        container.container_id
    )

    script = r"""
set -eu

SECRET=/data/.wf_secret_key
DATA=/data/wealthfolio
DB=/data/wealthfolio/wealthfolio.db
OPTIONS=/data/options.json

test -f "$SECRET"
test ! -L "$SECRET"

test -d "$DATA"
test ! -L "$DATA"

test -f "$DB"
test ! -L "$DB"
test -s "$DB"

test -f "$OPTIONS"
test ! -L "$OPTIONS"

decoded_size="$(
    openssl base64 -d -A \
        < "$SECRET" \
        2>/dev/null \
        | wc -c
)"

printf 'secret_uid=%s\n' \
    "$(stat -c '%u' "$SECRET")"
printf 'secret_gid=%s\n' \
    "$(stat -c '%g' "$SECRET")"
printf 'secret_mode=%s\n' \
    "$(stat -c '%a' "$SECRET")"
printf 'secret_size=%s\n' \
    "$(stat -c '%s' "$SECRET")"
printf 'secret_decoded_bytes=%s\n' \
    "$decoded_size"

printf 'data_uid=%s\n' \
    "$(stat -c '%u' "$DATA")"
printf 'data_gid=%s\n' \
    "$(stat -c '%g' "$DATA")"
printf 'data_mode=%s\n' \
    "$(stat -c '%a' "$DATA")"

printf 'db_uid=%s\n' \
    "$(stat -c '%u' "$DB")"
printf 'db_gid=%s\n' \
    "$(stat -c '%g' "$DB")"
printf 'db_mode=%s\n' \
    "$(stat -c '%a' "$DB")"
printf 'db_size=%s\n' \
    "$(stat -c '%s' "$DB")"

printf 'options_uid=%s\n' \
    "$(stat -c '%u' "$OPTIONS")"
printf 'options_gid=%s\n' \
    "$(stat -c '%g' "$OPTIONS")"
printf 'options_mode=%s\n' \
    "$(stat -c '%a' "$OPTIONS")"
printf 'options_size=%s\n' \
    "$(stat -c '%s' "$OPTIONS")"
"""

    output = run_docker(
        [
            "exec",
            container_id,
            "/bin/sh",
            "-c",
            script,
        ],
        timeout_seconds=30,
        operation="inspect runtime bootstrap",
    )

    values = _parse_runtime_bootstrap_output(
        output
    )

    if (
        values["secret_uid"] != 0
        or values["secret_gid"] != 0
        or values["secret_mode"] != "600"
        or values["secret_size"] <= 0
        or values["secret_decoded_bytes"] != 32
        or values["data_uid"] != 1000
        or values["data_gid"] != 1000
        or values["db_uid"] != 1000
        or values["db_gid"] != 1000
        or values["db_size"] <= 0
        or values["options_uid"] != 0
        or values["options_gid"] != 0
        or values["options_mode"] != "600"
        or values["options_size"] <= 0
    ):
        raise DockerRuntimeError(
            "runtime bootstrap contract mismatch"
        )

    return RuntimeBootstrapInspection(
        secret_uid=values["secret_uid"],
        secret_gid=values["secret_gid"],
        secret_mode=values["secret_mode"],
        secret_size=values["secret_size"],
        secret_decoded_bytes=values[
            "secret_decoded_bytes"
        ],
        data_uid=values["data_uid"],
        data_gid=values["data_gid"],
        data_mode=values["data_mode"],
        db_uid=values["db_uid"],
        db_gid=values["db_gid"],
        db_mode=values["db_mode"],
        db_size=values["db_size"],
        options_uid=values["options_uid"],
        options_gid=values["options_gid"],
        options_mode=values["options_mode"],
        options_size=values["options_size"],
    )

def _parse_runtime_ownership_labels(
    output: bytes,
) -> dict[str, str]:
    try:
        decoded = json.loads(output)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise DockerRuntimeError(
            "runtime ownership inspection is invalid"
        ) from exc

    if decoded is None:
        return {}

    if not isinstance(decoded, dict):
        raise DockerRuntimeError(
            "runtime ownership inspection is invalid"
        )

    labels: dict[str, str] = {}

    for key, value in decoded.items():
        if (
            type(key) is not str
            or type(value) is not str
        ):
            raise DockerRuntimeError(
                "runtime ownership inspection is invalid"
            )

        labels[key] = value

    return labels


def cleanup_runtime_container(
    *,
    container: RuntimeContainer,
) -> None:
    if not isinstance(
        container,
        RuntimeContainer,
    ):
        raise TypeError(
            "container must be a RuntimeContainer"
        )

    container_id = _validate_runtime_container_id(
        container.container_id
    )

    output = run_docker(
        [
            "inspect",
            container_id,
            "--format",
            "{{json .Config.Labels}}",
        ],
        timeout_seconds=30,
        operation=(
            "inspect runtime container ownership"
        ),
    )

    labels = _parse_runtime_ownership_labels(
        output
    )

    if (
        labels.get(
            "io.wealthfolio.runtime-test"
        ) != "true"
        or labels.get(
            "io.wealthfolio.runtime-test.role"
        ) != "runtime"
    ):
        raise DockerRuntimeError(
            "runtime container ownership mismatch"
        )

    run_docker(
        [
            "rm",
            "--force",
            "--volumes",
            container_id,
        ],
        timeout_seconds=30,
        operation="remove runtime container",
    )


def cleanup_runtime_data_volume(
    *,
    volume: RuntimeDataVolume,
) -> None:
    if not isinstance(
        volume,
        RuntimeDataVolume,
    ):
        raise TypeError(
            "volume must be a RuntimeDataVolume"
        )

    volume_name = _validate_runtime_data_volume_name(
        volume.name
    )

    output = run_docker(
        [
            "volume",
            "inspect",
            volume_name,
            "--format",
            "{{json .Labels}}",
        ],
        timeout_seconds=30,
        operation=(
            "inspect runtime data volume ownership"
        ),
    )

    labels = _parse_runtime_ownership_labels(
        output
    )

    if (
        labels.get(
            "io.wealthfolio.runtime-test"
        ) != "true"
        or labels.get(
            "io.wealthfolio.runtime-test.role"
        ) != "data"
    ):
        raise DockerRuntimeError(
            "runtime data volume ownership mismatch"
        )

    run_docker(
        [
            "volume",
            "rm",
            volume_name,
        ],
        timeout_seconds=30,
        operation="remove runtime data volume",
    )

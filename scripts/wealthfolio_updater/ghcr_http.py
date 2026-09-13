from __future__ import annotations

import re
from dataclasses import dataclass


GHCR_REGISTRY = "https://ghcr.io"
GHCR_TOKEN_ENDPOINT = "https://ghcr.io/token"
GHCR_REPOSITORY = "wealthfolio/wealthfolio"
GHCR_PULL_SCOPE = (
    "repository:wealthfolio/wealthfolio:pull"
)

_PARAMETER_RE = re.compile(
    r'\s*'
    r'([A-Za-z][A-Za-z0-9_-]*)'
    r'='
    r'"([^"\\]*)"'
    r'\s*'
    r'(?:,|$)'
)


@dataclass(frozen=True)
class BearerChallenge:
    realm: str
    service: str
    scope: str


def parse_www_authenticate(
    header: str,
) -> BearerChallenge:
    if type(header) is not str:
        raise TypeError(
            "WWW-Authenticate header must be a string"
        )

    if not header.startswith("Bearer "):
        raise ValueError(
            "WWW-Authenticate scheme must be Bearer"
        )

    parameters_text = header[len("Bearer "):]

    if not parameters_text:
        raise ValueError(
            "Bearer challenge has no parameters"
        )

    parameters: dict[str, str] = {}
    position = 0

    while position < len(parameters_text):
        match = _PARAMETER_RE.match(
            parameters_text,
            position,
        )

        if match is None:
            raise ValueError(
                "malformed Bearer challenge parameter"
            )

        name, value = match.groups()

        if name in parameters:
            raise ValueError(
                f"duplicate Bearer challenge parameter: {name}"
            )

        parameters[name] = value
        position = match.end()

    required = {
        "realm",
        "service",
        "scope",
    }

    actual = set(parameters)

    missing = required - actual
    unexpected = actual - required

    if missing:
        raise ValueError(
            "Bearer challenge missing required parameters: "
            + ", ".join(sorted(missing))
        )

    if unexpected:
        raise ValueError(
            "Bearer challenge contains unexpected parameters: "
            + ", ".join(sorted(unexpected))
        )

    realm = parameters["realm"]
    service = parameters["service"]
    scope = parameters["scope"]

    if realm != GHCR_TOKEN_ENDPOINT:
        raise ValueError(
            "unexpected GHCR token realm"
        )

    if service != "ghcr.io":
        raise ValueError(
            "unexpected GHCR token service"
        )

    if scope != GHCR_PULL_SCOPE:
        raise ValueError(
            "unexpected GHCR token scope"
        )

    return BearerChallenge(
        realm=realm,
        service=service,
        scope=scope,
    )


import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from .models import SemVer


GHCR_TIMEOUT_SECONDS = 10
GHCR_TOKEN_MAX_BYTES = 16 * 1024
GHCR_MANIFEST_MAX_BYTES = 2 * 1024 * 1024

_OCI_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)

_USER_AGENT = "wealthfolio-home-assistant-updater"

_BEARER_TOKEN_RE = re.compile(
    r"[A-Za-z0-9\-._~+/]+=*"
)


class GhcrTransportError(RuntimeError):
    """GHCR anonymous pull transport failed."""


@dataclass(frozen=True)
class GhcrManifestResponse:
    body: bytes
    content_type: str
    content_digest: str


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        raise HTTPError(
            req.full_url,
            code,
            "redirect rejected",
            headers,
            fp,
        )


def _default_opener():
    return build_opener(_RejectRedirects())


def _read_limited(
    response,
    *,
    limit: int,
    label: str,
) -> bytes:
    body = response.read(limit + 1)

    if not isinstance(body, bytes):
        raise GhcrTransportError(
            f"{label} response body must be bytes"
        )

    if len(body) > limit:
        raise GhcrTransportError(
            f"{label} response body exceeds limit"
        )

    return body


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


def _parse_token_response(body: bytes) -> str:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GhcrTransportError(
            "token response is not valid UTF-8"
        ) from exc

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise GhcrTransportError(
            "token response is not valid JSON"
        ) from exc

    if not isinstance(decoded, dict):
        raise GhcrTransportError(
            "token response must be a JSON object"
        )

    if set(decoded) != {"token"}:
        raise GhcrTransportError(
            "token response must contain exactly token"
        )

    token = decoded["token"]

    if type(token) is not str or not token:
        raise GhcrTransportError(
            "token must be a non-empty string"
        )

    if len(token) > GHCR_TOKEN_MAX_BYTES:
        raise GhcrTransportError(
            "token exceeds allowed length"
        )

    if _BEARER_TOKEN_RE.fullmatch(token) is None:
        raise GhcrTransportError(
            "token contains invalid characters"
        )

    return token


def _manifest_url(version: SemVer) -> str:
    return (
        f"{GHCR_REGISTRY}/v2/"
        f"{GHCR_REPOSITORY}/manifests/{version}"
    )


def fetch_ghcr_manifest(
    version: SemVer,
    *,
    opener=None,
) -> GhcrManifestResponse:
    if not isinstance(version, SemVer):
        raise TypeError(
            "version must be a SemVer"
        )

    if opener is None:
        opener = _default_opener()

    manifest_url = _manifest_url(version)

    anonymous_request = Request(
        manifest_url,
        method="GET",
        headers={
            "Accept": _OCI_ACCEPT,
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with opener.open(
            anonymous_request,
            timeout=GHCR_TIMEOUT_SECONDS,
        ):
            raise GhcrTransportError(
                "expected authentication challenge"
            )

    except HTTPError as exc:
        try:
            if exc.code != 401:
                raise GhcrTransportError(
                    "expected authentication challenge, "
                    f"got HTTP {exc.code}"
                ) from exc

            authenticate = (
                exc.headers.get("WWW-Authenticate")
                if exc.headers is not None
                else None
            )

            if authenticate is None:
                raise GhcrTransportError(
                    "401 response missing WWW-Authenticate"
                ) from exc

            try:
                challenge = parse_www_authenticate(
                    authenticate
                )
            except (TypeError, ValueError) as challenge_exc:
                raise GhcrTransportError(
                    "invalid GHCR WWW-Authenticate challenge"
                ) from challenge_exc
        finally:
            exc.close()

    except GhcrTransportError:
        raise

    except (URLError, TimeoutError, OSError) as exc:
        raise GhcrTransportError(
            "initial GHCR manifest request failed"
        ) from exc

    token_url = (
        f"{GHCR_TOKEN_ENDPOINT}?"
        + urlencode(
            {
                "service": challenge.service,
                "scope": challenge.scope,
            }
        )
    )

    token_request = Request(
        token_url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with opener.open(
            token_request,
            timeout=GHCR_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)

            if status != 200:
                raise GhcrTransportError(
                    f"unexpected token HTTP status: {status}"
                )

            content_type = response.headers.get(
                "Content-Type"
            )

            if type(content_type) is not str:
                raise GhcrTransportError(
                    "missing token Content-Type"
                )

            media_type = content_type.split(
                ";",
                1,
            )[0].strip().lower()

            if media_type != "application/json":
                raise GhcrTransportError(
                    "unexpected token Content-Type"
                )

            token_body = _read_limited(
                response,
                limit=GHCR_TOKEN_MAX_BYTES,
                label="token",
            )

    except GhcrTransportError:
        raise

    except HTTPError as exc:
        try:
            raise GhcrTransportError(
                f"token request failed: HTTP {exc.code}"
            ) from exc
        finally:
            exc.close()

    except (URLError, TimeoutError, OSError) as exc:
        raise GhcrTransportError(
            "token request failed"
        ) from exc

    token = _parse_token_response(token_body)

    authenticated_request = Request(
        manifest_url,
        method="GET",
        headers={
            "Accept": _OCI_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with opener.open(
            authenticated_request,
            timeout=GHCR_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)

            if status != 200:
                raise GhcrTransportError(
                    "unexpected manifest HTTP status: "
                    f"{status}"
                )

            body = _read_limited(
                response,
                limit=GHCR_MANIFEST_MAX_BYTES,
                label="manifest",
            )

            content_type = response.headers.get(
                "Content-Type"
            )
            content_digest = response.headers.get(
                "Docker-Content-Digest"
            )

            if type(content_type) is not str:
                raise GhcrTransportError(
                    "manifest response missing Content-Type"
                )

            if type(content_digest) is not str:
                raise GhcrTransportError(
                    "manifest response missing "
                    "Docker-Content-Digest"
                )

            return GhcrManifestResponse(
                body=body,
                content_type=content_type,
                content_digest=content_digest,
            )

    except GhcrTransportError:
        raise

    except HTTPError as exc:
        try:
            raise GhcrTransportError(
                f"manifest request failed: HTTP {exc.code}"
            ) from exc
        finally:
            exc.close()

    except (URLError, TimeoutError, OSError) as exc:
        raise GhcrTransportError(
            "manifest request failed"
        ) from exc

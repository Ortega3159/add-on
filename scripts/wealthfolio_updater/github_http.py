from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from .discovery import GitHubReleasePageResponse


GITHUB_RELEASES_ENDPOINT = (
    "https://api.github.com/repos/"
    "wealthfolio/wealthfolio/releases"
)

GITHUB_API_VERSION = "2026-03-10"
GITHUB_PER_PAGE = 20
GITHUB_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_USER_AGENT = "wealthfolio-home-assistant-updater"


class GitHubTransportError(RuntimeError):
    """GitHub release discovery transport failed."""


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


def fetch_github_release_page(
    page: int,
    *,
    opener=None,
) -> GitHubReleasePageResponse:
    if type(page) is not int or page <= 0:
        raise ValueError(
            "page must be a positive integer"
        )

    url = (
        f"{GITHUB_RELEASES_ENDPOINT}"
        f"?per_page={GITHUB_PER_PAGE}&page={page}"
    )

    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": _USER_AGENT,
        },
    )

    if opener is None:
        opener = _default_opener()

    try:
        with opener.open(
            request,
            timeout=GITHUB_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)

            if status != 200:
                raise GitHubTransportError(
                    f"unexpected HTTP status: {status}"
                )

            body = response.read(
                MAX_RESPONSE_BYTES + 1
            )

            if not isinstance(body, bytes):
                raise GitHubTransportError(
                    "GitHub response body must be bytes"
                )

            if len(body) > MAX_RESPONSE_BYTES:
                raise GitHubTransportError(
                    "response body exceeds limit"
                )

            link_header = response.headers.get(
                "Link"
            )

            if (
                link_header is not None
                and type(link_header) is not str
            ):
                raise GitHubTransportError(
                    "GitHub Link header must be text"
                )

            return GitHubReleasePageResponse(
                body=body,
                link_header=link_header,
            )

    except GitHubTransportError:
        raise

    except HTTPError as exc:
        raise GitHubTransportError(
            f"GitHub request failed: HTTP {exc.code}"
        ) from exc

    except (URLError, TimeoutError, OSError) as exc:
        raise GitHubTransportError(
            "GitHub request failed"
        ) from exc

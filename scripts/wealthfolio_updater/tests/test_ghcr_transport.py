import io
import json
import unittest
from email.message import Message
from urllib.error import HTTPError

from scripts.wealthfolio_updater.ghcr_http import (
    GHCR_MANIFEST_MAX_BYTES,
    GHCR_TIMEOUT_SECONDS,
    GHCR_TOKEN_MAX_BYTES,
    GhcrTransportError,
    fetch_ghcr_manifest,
)
from scripts.wealthfolio_updater.oci import (
    OCI_IMAGE_INDEX_MEDIA_TYPE,
)
from scripts.wealthfolio_updater.updater import SemVer


DIGEST = "sha256:" + "a" * 64
TOKEN = "test-token_1234567890"


class FakeResponse:
    def __init__(
        self,
        *,
        status=200,
        body=b"",
        headers=None,
    ):
        self.status = status
        self._body = body
        self.headers = Message()

        for key, value in (headers or {}).items():
            self.headers[key] = value

    def read(self, amount=-1):
        if amount is None or amount < 0:
            return self._body

        return self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SequenceOpener:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))

        if not self.steps:
            raise AssertionError("unexpected HTTP request")

        step = self.steps.pop(0)

        if isinstance(step, BaseException):
            raise step

        return step


def challenge_error():
    headers = Message()
    headers["WWW-Authenticate"] = (
        'Bearer '
        'realm="https://ghcr.io/token",'
        'service="ghcr.io",'
        'scope="repository:wealthfolio/wealthfolio:pull"'
    )

    return HTTPError(
        (
            "https://ghcr.io/v2/"
            "wealthfolio/wealthfolio/manifests/3.8.0"
        ),
        401,
        "Unauthorized",
        headers,
        io.BytesIO(
            b'{"errors":[{"code":"UNAUTHORIZED"}]}'
        ),
    )


def token_response(body=None):
    if body is None:
        body = json.dumps(
            {"token": TOKEN}
        ).encode()

    return FakeResponse(
        body=body,
        headers={
            "Content-Type": "application/json",
        },
    )


def manifest_response(
    *,
    body=b'{"schemaVersion":2}',
    content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
    content_digest=DIGEST,
):
    return FakeResponse(
        body=body,
        headers={
            "Content-Type": content_type,
            "Docker-Content-Digest": content_digest,
        },
    )


class GhcrTransportTests(unittest.TestCase):
    def test_complete_anonymous_pull_flow(self):
        opener = SequenceOpener(
            challenge_error(),
            token_response(),
            manifest_response(),
        )

        result = fetch_ghcr_manifest(
            SemVer.parse("3.8.0"),
            opener=opener,
        )

        self.assertEqual(
            result.body,
            b'{"schemaVersion":2}',
        )
        self.assertEqual(
            result.content_type,
            OCI_IMAGE_INDEX_MEDIA_TYPE,
        )
        self.assertEqual(
            result.content_digest,
            DIGEST,
        )

        self.assertEqual(len(opener.calls), 3)

        first, second, third = opener.calls

        self.assertEqual(
            first[0].full_url,
            (
                "https://ghcr.io/v2/"
                "wealthfolio/wealthfolio/"
                "manifests/3.8.0"
            ),
        )

        self.assertEqual(
            second[0].full_url,
            (
                "https://ghcr.io/token"
                "?service=ghcr.io"
                "&scope=repository%3Awealthfolio"
                "%2Fwealthfolio%3Apull"
            ),
        )

        self.assertEqual(
            third[0].full_url,
            first[0].full_url,
        )

        for _request, timeout in opener.calls:
            self.assertEqual(
                timeout,
                GHCR_TIMEOUT_SECONDS,
            )

        first_headers = {
            key.lower(): value
            for key, value
            in first[0].header_items()
        }

        token_headers = {
            key.lower(): value
            for key, value
            in second[0].header_items()
        }

        authenticated_headers = {
            key.lower(): value
            for key, value
            in third[0].header_items()
        }

        self.assertNotIn(
            "authorization",
            first_headers,
        )
        self.assertNotIn(
            "authorization",
            token_headers,
        )
        self.assertEqual(
            authenticated_headers["authorization"],
            f"Bearer {TOKEN}",
        )

    def test_requires_semver_before_network(self):
        opener = SequenceOpener()

        for value in ("3.8.0", None, True):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    fetch_ghcr_manifest(
                        value,
                        opener=opener,
                    )

        self.assertEqual(opener.calls, [])

    def test_first_manifest_request_must_return_401(self):
        opener = SequenceOpener(
            HTTPError(
                "https://ghcr.io/",
                404,
                "Not Found",
                Message(),
                io.BytesIO(b""),
            )
        )

        with self.assertRaisesRegex(
            GhcrTransportError,
            "expected authentication challenge",
        ):
            fetch_ghcr_manifest(
                SemVer.parse("3.8.0"),
                opener=opener,
            )

    def test_401_requires_www_authenticate(self):
        opener = SequenceOpener(
            HTTPError(
                "https://ghcr.io/",
                401,
                "Unauthorized",
                Message(),
                io.BytesIO(b""),
            )
        )

        with self.assertRaisesRegex(
            GhcrTransportError,
            "WWW-Authenticate",
        ):
            fetch_ghcr_manifest(
                SemVer.parse("3.8.0"),
                opener=opener,
            )

    def test_token_response_requires_json_content_type(self):
        opener = SequenceOpener(
            challenge_error(),
            FakeResponse(
                body=b'{"token":"abc"}',
                headers={
                    "Content-Type": "text/plain",
                },
            ),
        )

        with self.assertRaisesRegex(
            GhcrTransportError,
            "token Content-Type",
        ):
            fetch_ghcr_manifest(
                SemVer.parse("3.8.0"),
                opener=opener,
            )

    def test_token_json_requires_valid_bearer_token(self):
        invalid_bodies = (
            b"{}",
            b'{"token":123}',
            b'{"token":""}',
            b'{"token":"has space"}',
            b'{"token":"abc","token":"def"}',
            b"{",
        )

        for body in invalid_bodies:
            with self.subTest(body=body):
                opener = SequenceOpener(
                    challenge_error(),
                    token_response(body),
                )

                with self.assertRaises(
                    GhcrTransportError
                ):
                    fetch_ghcr_manifest(
                        SemVer.parse("3.8.0"),
                        opener=opener,
                    )

    def test_token_body_size_is_limited(self):
        opener = SequenceOpener(
            challenge_error(),
            token_response(
                b"x" * (GHCR_TOKEN_MAX_BYTES + 1)
            ),
        )

        with self.assertRaisesRegex(
            GhcrTransportError,
            "token response body exceeds limit",
        ):
            fetch_ghcr_manifest(
                SemVer.parse("3.8.0"),
                opener=opener,
            )

    def test_manifest_body_size_is_limited(self):
        opener = SequenceOpener(
            challenge_error(),
            token_response(),
            manifest_response(
                body=(
                    b"x"
                    * (GHCR_MANIFEST_MAX_BYTES + 1)
                ),
            ),
        )

        with self.assertRaisesRegex(
            GhcrTransportError,
            "manifest response body exceeds limit",
        ):
            fetch_ghcr_manifest(
                SemVer.parse("3.8.0"),
                opener=opener,
            )

    def test_manifest_requires_content_headers(self):
        cases = (
            {
                "Docker-Content-Digest": DIGEST,
            },
            {
                "Content-Type":
                    OCI_IMAGE_INDEX_MEDIA_TYPE,
            },
        )

        for headers in cases:
            with self.subTest(headers=headers):
                opener = SequenceOpener(
                    challenge_error(),
                    token_response(),
                    FakeResponse(
                        body=b"{}",
                        headers=headers,
                    ),
                )

                with self.assertRaises(
                    GhcrTransportError
                ):
                    fetch_ghcr_manifest(
                        SemVer.parse("3.8.0"),
                        opener=opener,
                    )


if __name__ == "__main__":
    unittest.main()

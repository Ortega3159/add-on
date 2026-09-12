import unittest
from urllib.error import URLError

from scripts.wealthfolio_updater.discovery import (
    GitHubReleasePageResponse,
)
from scripts.wealthfolio_updater.github_http import (
    GITHUB_API_VERSION,
    GITHUB_PER_PAGE,
    GITHUB_RELEASES_ENDPOINT,
    GITHUB_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    GitHubTransportError,
    fetch_github_release_page,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status=200,
        body=b"[]",
        link=None,
    ):
        self.status = status
        self._body = body
        self.headers = {}

        if link is not None:
            self.headers["Link"] = link

    def read(self, amount=-1):
        if amount is None or amount < 0:
            return self._body

        return self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RecordingOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))

        if self.error is not None:
            raise self.error

        return self.response


class GitHubHttpTests(unittest.TestCase):
    def test_fetches_fixed_release_endpoint(self):
        opener = RecordingOpener(
            response=FakeResponse(
                body=b'[{"id":1}]',
                link='<https://example.invalid/2>; rel="next"',
            )
        )

        result = fetch_github_release_page(
            7,
            opener=opener,
        )

        self.assertEqual(
            result,
            GitHubReleasePageResponse(
                body=b'[{"id":1}]',
                link_header=(
                    '<https://example.invalid/2>; rel="next"'
                ),
            ),
        )

        self.assertEqual(len(opener.calls), 1)

        request, timeout = opener.calls[0]

        self.assertEqual(
            request.full_url,
            (
                GITHUB_RELEASES_ENDPOINT
                + "?per_page=20&page=7"
            ),
        )
        self.assertEqual(timeout, GITHUB_TIMEOUT_SECONDS)

    def test_sends_expected_headers_without_authorization(self):
        opener = RecordingOpener(
            response=FakeResponse()
        )

        fetch_github_release_page(
            1,
            opener=opener,
        )

        request, _timeout = opener.calls[0]

        headers = {
            key.lower(): value
            for key, value in request.header_items()
        }

        self.assertEqual(
            headers["accept"],
            "application/vnd.github+json",
        )
        self.assertEqual(
            headers["x-github-api-version"],
            GITHUB_API_VERSION,
        )
        self.assertTrue(headers["user-agent"])
        self.assertNotIn("authorization", headers)

    def test_rejects_invalid_page_before_network(self):
        invalid_pages = (
            True,
            False,
            0,
            -1,
            1.0,
            "1",
        )

        for page in invalid_pages:
            with self.subTest(page=page):
                opener = RecordingOpener(
                    response=FakeResponse()
                )

                with self.assertRaises(ValueError):
                    fetch_github_release_page(
                        page,
                        opener=opener,
                    )

                self.assertEqual(opener.calls, [])

    def test_rejects_non_200_response(self):
        opener = RecordingOpener(
            response=FakeResponse(
                status=404,
                body=b'{"message":"Not Found"}',
            )
        )

        with self.assertRaisesRegex(
            GitHubTransportError,
            "unexpected HTTP status: 404",
        ):
            fetch_github_release_page(
                1,
                opener=opener,
            )

    def test_network_error_is_wrapped(self):
        opener = RecordingOpener(
            error=URLError("network unavailable")
        )

        with self.assertRaisesRegex(
            GitHubTransportError,
            "GitHub request failed",
        ):
            fetch_github_release_page(
                1,
                opener=opener,
            )

    def test_response_body_at_limit_is_accepted(self):
        body = b"x" * MAX_RESPONSE_BYTES

        opener = RecordingOpener(
            response=FakeResponse(body=body)
        )

        result = fetch_github_release_page(
            1,
            opener=opener,
        )

        self.assertEqual(result.body, body)

    def test_response_body_over_limit_is_rejected(self):
        body = b"x" * (MAX_RESPONSE_BYTES + 1)

        opener = RecordingOpener(
            response=FakeResponse(body=body)
        )

        with self.assertRaisesRegex(
            GitHubTransportError,
            "response body exceeds limit",
        ):
            fetch_github_release_page(
                1,
                opener=opener,
            )

    def test_missing_link_header_is_preserved_as_none(self):
        opener = RecordingOpener(
            response=FakeResponse(
                body=b"[]",
                link=None,
            )
        )

        result = fetch_github_release_page(
            1,
            opener=opener,
        )

        self.assertIsNone(result.link_header)

    def test_constants_are_frozen_to_expected_contract(self):
        self.assertEqual(
            GITHUB_RELEASES_ENDPOINT,
            (
                "https://api.github.com/repos/"
                "wealthfolio/wealthfolio/releases"
            ),
        )
        self.assertEqual(
            GITHUB_API_VERSION,
            "2026-03-10",
        )
        self.assertEqual(
            GITHUB_TIMEOUT_SECONDS,
            10,
        )
        self.assertEqual(
            GITHUB_PER_PAGE,
            20,
        )
        self.assertEqual(
            MAX_RESPONSE_BYTES,
            2 * 1024 * 1024,
        )


if __name__ == "__main__":
    unittest.main()

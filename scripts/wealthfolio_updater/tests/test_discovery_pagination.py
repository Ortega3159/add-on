import unittest

from scripts.wealthfolio_updater.discovery import (
    GitHubReleasePageResponse,
    discover_github_releases,
)
from scripts.wealthfolio_updater.updater import SemVer


def release_payload(*versions: str) -> bytes:
    objects = []

    for version in versions:
        major, minor, patch = (
            int(part)
            for part in version.split(".")
        )
        release_id = (
            major * 1_000_000
            + minor * 1_000
            + patch
        )

        objects.append(
            "{"
            f'"id": {release_id},'
            f'"tag_name": "v{version}",'
            '"draft": false,'
            '"prerelease": false'
            "}"
        )

    return ("[" + ",".join(objects) + "]").encode("utf-8")


class GitHubReleasePaginationTests(unittest.TestCase):
    def test_single_page_without_next_link(self):
        calls = []

        def fetch_page(page):
            calls.append(page)
            return GitHubReleasePageResponse(
                body=release_payload("3.6.3", "3.8.0"),
                link_header=None,
            )

        releases = discover_github_releases(fetch_page)

        self.assertEqual(calls, [1])
        self.assertEqual(
            tuple(release.version for release in releases),
            (
                SemVer.parse("3.6.3"),
                SemVer.parse("3.8.0"),
            ),
        )

    def test_follows_next_pages(self):
        calls = []

        def fetch_page(page):
            calls.append(page)

            if page == 1:
                return GitHubReleasePageResponse(
                    body=release_payload("3.8.0"),
                    link_header=(
                        '<https://api.github.com/repos/'
                        'wealthfolio/wealthfolio/releases'
                        '?per_page=100&page=2>; rel="next", '
                        '<https://api.github.com/repos/'
                        'wealthfolio/wealthfolio/releases'
                        '?per_page=100&page=2>; rel="last"'
                    ),
                )

            if page == 2:
                return GitHubReleasePageResponse(
                    body=release_payload("3.6.3", "3.7.0"),
                    link_header=None,
                )

            raise AssertionError(f"unexpected page: {page}")

        releases = discover_github_releases(fetch_page)

        self.assertEqual(calls, [1, 2])
        self.assertEqual(
            tuple(release.version for release in releases),
            (
                SemVer.parse("3.6.3"),
                SemVer.parse("3.7.0"),
                SemVer.parse("3.8.0"),
            ),
        )

    def test_next_relation_can_appear_after_other_relations(self):
        calls = []

        def fetch_page(page):
            calls.append(page)

            if page == 1:
                return GitHubReleasePageResponse(
                    body=release_payload("3.8.0"),
                    link_header=(
                        '<https://example.invalid/previous>; rel="prev", '
                        '<https://example.invalid/next>; rel="next"'
                    ),
                )

            return GitHubReleasePageResponse(
                body=release_payload("3.7.0"),
                link_header=None,
            )

        discover_github_releases(fetch_page)

        self.assertEqual(calls, [1, 2])

    def test_duplicate_version_across_pages_is_rejected(self):
        def fetch_page(page):
            if page == 1:
                return GitHubReleasePageResponse(
                    body=release_payload("3.8.0"),
                    link_header=(
                        '<https://example.invalid/next>; rel="next"'
                    ),
                )

            return GitHubReleasePageResponse(
                body=release_payload("3.8.0"),
                link_header=None,
            )

        with self.assertRaises(ValueError):
            discover_github_releases(fetch_page)

    def test_duplicate_release_id_across_pages_is_rejected(self):
        first = b"""
        [
          {
            "id": 123,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        second = b"""
        [
          {
            "id": 123,
            "tag_name": "v3.7.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        def fetch_page(page):
            if page == 1:
                return GitHubReleasePageResponse(
                    body=first,
                    link_header=(
                        '<https://example.invalid/next>; rel="next"'
                    ),
                )

            return GitHubReleasePageResponse(
                body=second,
                link_header=None,
            )

        with self.assertRaises(ValueError):
            discover_github_releases(fetch_page)

    def test_invalid_fetch_result_type_is_rejected(self):
        def fetch_page(_page):
            return b"[]"

        with self.assertRaises(TypeError):
            discover_github_releases(fetch_page)

    def test_malformed_link_header_is_rejected(self):
        def fetch_page(_page):
            return GitHubReleasePageResponse(
                body=release_payload("3.8.0"),
                link_header="this is not a valid Link header",
            )

        with self.assertRaises(ValueError):
            discover_github_releases(fetch_page)

    def test_page_limit_fails_closed(self):
        def fetch_page(_page):
            return GitHubReleasePageResponse(
                body=release_payload("3.8.0"),
                link_header=(
                    '<https://example.invalid/next>; rel="next"'
                ),
            )

        with self.assertRaises(ValueError):
            discover_github_releases(
                fetch_page,
                max_pages=1,
            )

    def test_max_pages_rejects_bool_and_nonpositive_values(self):
        def fetch_page(_page):
            raise AssertionError("fetch must not be called")

        for value in (True, False, 0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    discover_github_releases(
                        fetch_page,
                        max_pages=value,
                    )


if __name__ == "__main__":
    unittest.main()


class GitHubLinkHeaderHardeningTests(unittest.TestCase):
    def test_duplicate_relation_token_is_rejected(self):
        calls = []

        def fetch_page(page):
            calls.append(page)

            if page != 1:
                raise AssertionError(
                    "malformed Link header must fail before page 2"
                )

            return GitHubReleasePageResponse(
                body=release_payload("3.8.0"),
                link_header=(
                    '<https://example.invalid/next>; '
                    'rel="next next"'
                ),
            )

        with self.assertRaisesRegex(
            ValueError,
            "duplicate relation token",
        ):
            discover_github_releases(fetch_page)

        self.assertEqual(calls, [1])

    def test_multiple_rel_parameters_are_rejected(self):
        calls = []

        def fetch_page(page):
            calls.append(page)

            if page != 1:
                raise AssertionError(
                    "malformed Link header must fail before page 2"
                )

            return GitHubReleasePageResponse(
                body=release_payload("3.8.0"),
                link_header=(
                    '<https://example.invalid/next>; '
                    'rel="next"; rel="last"'
                ),
            )

        with self.assertRaisesRegex(
            ValueError,
            "multiple rel parameters",
        ):
            discover_github_releases(fetch_page)

        self.assertEqual(calls, [1])

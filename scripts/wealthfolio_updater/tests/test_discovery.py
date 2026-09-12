import unittest

from scripts.wealthfolio_updater.discovery import (
    UpstreamRelease,
    parse_github_release_page,
)
from scripts.wealthfolio_updater.updater import SemVer


class GitHubReleasePageTests(unittest.TestCase):
    def test_accepts_stable_strict_semver_release(self):
        payload = b"""
        [
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        releases = parse_github_release_page(payload)

        self.assertEqual(
            releases,
            (
                UpstreamRelease(
                    release_id=380,
                    tag_name="v3.8.0",
                    version=SemVer.parse("3.8.0"),
                ),
            ),
        )

    def test_ignores_drafts(self):
        payload = b"""
        [
          {
            "id": 390,
            "tag_name": "v3.9.0",
            "draft": true,
            "prerelease": false
          },
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        releases = parse_github_release_page(payload)

        self.assertEqual(
            tuple(release.version for release in releases),
            (SemVer.parse("3.8.0"),),
        )

    def test_ignores_prereleases(self):
        payload = b"""
        [
          {
            "id": 390,
            "tag_name": "v3.9.0-beta.1",
            "draft": false,
            "prerelease": true
          },
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        releases = parse_github_release_page(payload)

        self.assertEqual(
            tuple(release.version for release in releases),
            (SemVer.parse("3.8.0"),),
        )

    def test_stable_release_requires_v_prefixed_strict_semver(self):
        invalid_tags = (
            "3.8.0",
            "v03.8.0",
            "v3.08.0",
            "v3.8.00",
            "v3.8.0-beta.1",
            "v3.8.0+build.1",
            "latest",
        )

        for index, tag in enumerate(invalid_tags, start=1):
            with self.subTest(tag=tag):
                payload = (
                    "["
                    "{"
                    f'"id": {index},'
                    f'"tag_name": "{tag}",'
                    '"draft": false,'
                    '"prerelease": false'
                    "}"
                    "]"
                ).encode("utf-8")

                with self.assertRaises(ValueError):
                    parse_github_release_page(payload)

    def test_rejects_non_array_top_level_json(self):
        with self.assertRaises(ValueError):
            parse_github_release_page(b'{"tag_name":"v3.8.0"}')

    def test_rejects_missing_required_fields(self):
        payload = b"""
        [
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false
          }
        ]
        """

        with self.assertRaises(ValueError):
            parse_github_release_page(payload)

    def test_rejects_wrong_critical_field_types(self):
        payloads = (
            b'[{"id":"380","tag_name":"v3.8.0","draft":false,"prerelease":false}]',
            b'[{"id":380,"tag_name":380,"draft":false,"prerelease":false}]',
            b'[{"id":380,"tag_name":"v3.8.0","draft":0,"prerelease":false}]',
            b'[{"id":380,"tag_name":"v3.8.0","draft":false,"prerelease":0}]',
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_github_release_page(payload)

    def test_boolean_is_not_a_valid_release_id(self):
        payload = b"""
        [
          {
            "id": true,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        with self.assertRaises(ValueError):
            parse_github_release_page(payload)

    def test_release_id_must_be_positive(self):
        payload = b"""
        [
          {
            "id": 0,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        with self.assertRaises(ValueError):
            parse_github_release_page(payload)

    def test_rejects_duplicate_json_keys(self):
        payload = b"""
        [
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "tag_name": "v9.9.9",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        with self.assertRaises(ValueError):
            parse_github_release_page(payload)

    def test_rejects_duplicate_stable_versions(self):
        payload = b"""
        [
          {
            "id": 381,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          },
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        with self.assertRaises(ValueError):
            parse_github_release_page(payload)

    def test_returns_versions_in_semver_order(self):
        payload = b"""
        [
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false
          },
          {
            "id": 363,
            "tag_name": "v3.6.3",
            "draft": false,
            "prerelease": false
          },
          {
            "id": 370,
            "tag_name": "v3.7.0",
            "draft": false,
            "prerelease": false
          }
        ]
        """

        releases = parse_github_release_page(payload)

        self.assertEqual(
            tuple(release.version for release in releases),
            (
                SemVer.parse("3.6.3"),
                SemVer.parse("3.7.0"),
                SemVer.parse("3.8.0"),
            ),
        )

    def test_accepts_unknown_noncritical_github_fields(self):
        payload = b"""
        [
          {
            "id": 380,
            "tag_name": "v3.8.0",
            "draft": false,
            "prerelease": false,
            "name": "Wealthfolio 3.8",
            "immutable": false,
            "future_github_field": {
              "anything": "may appear later"
            }
          }
        ]
        """

        releases = parse_github_release_page(payload)

        self.assertEqual(
            tuple(release.version for release in releases),
            (SemVer.parse("3.8.0"),),
        )


if __name__ == "__main__":
    unittest.main()

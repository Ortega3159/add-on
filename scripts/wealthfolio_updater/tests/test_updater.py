import unittest

from scripts.wealthfolio_updater.updater import (
    ReleasePolicy,
    SemVer,
    WrapperVersion,
    classify_release_policy,
    compute_prebuilt_bootstrap,
    select_candidate,
)


class SemVerTests(unittest.TestCase):
    def test_numeric_semver_ordering(self):
        self.assertGreater(SemVer.parse("3.10.0"), SemVer.parse("3.9.10"))

    def test_semver_round_trip(self):
        version = SemVer.parse("3.8.0")
        self.assertEqual(str(version), "3.8.0")

    def test_rejects_non_strict_semver(self):
        invalid = [
            "v3.8.0",
            "3.8",
            "3.8.0-beta.1",
            "3.8.0+build",
            "03.8.0",
            "",
        ]

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SemVer.parse(value)


class WrapperVersionTests(unittest.TestCase):
    def test_wrapper_version_round_trip(self):
        wrapper = WrapperVersion.parse("3.6.3-4")

        self.assertEqual(wrapper.upstream, SemVer.parse("3.6.3"))
        self.assertEqual(wrapper.revision, 4)
        self.assertEqual(str(wrapper), "3.6.3-4")

    def test_wrapper_revision_is_numeric_not_lexicographic(self):
        self.assertGreater(
            WrapperVersion.parse("3.6.3-10"),
            WrapperVersion.parse("3.6.3-9"),
        )

    def test_rejects_invalid_wrapper_versions(self):
        invalid = [
            "3.6.3",
            "v3.6.3-4",
            "3.6-4",
            "3.6.3-0",
            "3.6.3-04",
            "03.6.3-4",
            "",
        ]

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    WrapperVersion.parse(value)


class ReleasePolicyTests(unittest.TestCase):
    def test_patch_is_automatic(self):
        current = SemVer.parse("3.8.2")
        candidate = SemVer.parse("3.8.3")

        self.assertEqual(
            classify_release_policy(current, candidate),
            ReleasePolicy.AUTO,
        )

    def test_minor_requires_review(self):
        current = SemVer.parse("3.8.2")
        candidate = SemVer.parse("3.9.0")

        self.assertEqual(
            classify_release_policy(current, candidate),
            ReleasePolicy.REVIEW_REQUIRED,
        )

    def test_major_is_blocked(self):
        current = SemVer.parse("3.8.2")
        candidate = SemVer.parse("4.0.0")

        self.assertEqual(
            classify_release_policy(current, candidate),
            ReleasePolicy.BLOCK_MAJOR,
        )

    def test_same_version_is_not_an_update(self):
        current = SemVer.parse("3.8.2")

        self.assertEqual(
            classify_release_policy(current, current),
            ReleasePolicy.NO_UPDATE,
        )

    def test_older_version_is_not_an_update(self):
        current = SemVer.parse("3.8.2")
        candidate = SemVer.parse("3.8.1")

        self.assertEqual(
            classify_release_policy(current, candidate),
            ReleasePolicy.NO_UPDATE,
        )


class CandidateSelectionTests(unittest.TestCase):
    def test_patch_wins_over_newer_minor_and_major(self):
        current = SemVer.parse("3.8.2")
        releases = [
            SemVer.parse("4.0.0"),
            SemVer.parse("3.9.0"),
            SemVer.parse("3.8.3"),
        ]

        selection = select_candidate(current, releases)

        self.assertEqual(selection.version, SemVer.parse("3.8.3"))
        self.assertEqual(selection.policy, ReleasePolicy.AUTO)

    def test_minor_selected_when_no_patch_exists(self):
        current = SemVer.parse("3.8.2")
        releases = [
            SemVer.parse("4.0.0"),
            SemVer.parse("3.9.0"),
        ]

        selection = select_candidate(current, releases)

        self.assertEqual(selection.version, SemVer.parse("3.9.0"))
        self.assertEqual(selection.policy, ReleasePolicy.REVIEW_REQUIRED)

    def test_highest_minor_is_selected_for_review(self):
        current = SemVer.parse("3.6.3")
        releases = [
            SemVer.parse("3.7.0"),
            SemVer.parse("3.8.0"),
        ]

        selection = select_candidate(current, releases)

        self.assertEqual(selection.version, SemVer.parse("3.8.0"))
        self.assertEqual(selection.policy, ReleasePolicy.REVIEW_REQUIRED)

    def test_major_only_is_blocked(self):
        current = SemVer.parse("3.8.2")
        releases = [
            SemVer.parse("4.0.0"),
            SemVer.parse("4.1.0"),
        ]

        selection = select_candidate(current, releases)

        self.assertEqual(selection.version, SemVer.parse("4.1.0"))
        self.assertEqual(selection.policy, ReleasePolicy.BLOCK_MAJOR)

    def test_no_newer_release_returns_no_update(self):
        current = SemVer.parse("3.8.2")
        releases = [
            SemVer.parse("3.8.1"),
            SemVer.parse("3.8.2"),
        ]

        selection = select_candidate(current, releases)

        self.assertIsNone(selection.version)
        self.assertEqual(selection.policy, ReleasePolicy.NO_UPDATE)


class PrebuiltBootstrapTests(unittest.TestCase):
    def test_local_build_state_requires_prebuilt_bootstrap(self):
        current_upstream = SemVer.parse("3.6.3")
        current_wrapper = WrapperVersion.parse("3.6.3-4")

        bootstrap = compute_prebuilt_bootstrap(
            current_upstream=current_upstream,
            current_wrapper=current_wrapper,
            has_image=False,
            has_state=False,
        )

        self.assertIsNotNone(bootstrap)
        self.assertEqual(bootstrap.upstream, SemVer.parse("3.6.3"))
        self.assertEqual(
            bootstrap.candidate_wrapper,
            WrapperVersion.parse("3.6.3-5"),
        )

    def test_prebuilt_state_does_not_require_bootstrap(self):
        bootstrap = compute_prebuilt_bootstrap(
            current_upstream=SemVer.parse("3.6.3"),
            current_wrapper=WrapperVersion.parse("3.6.3-5"),
            has_image=True,
            has_state=True,
        )

        self.assertIsNone(bootstrap)

    def test_image_without_state_is_invalid(self):
        with self.assertRaises(ValueError):
            compute_prebuilt_bootstrap(
                current_upstream=SemVer.parse("3.6.3"),
                current_wrapper=WrapperVersion.parse("3.6.3-5"),
                has_image=True,
                has_state=False,
            )

    def test_state_without_image_is_invalid(self):
        with self.assertRaises(ValueError):
            compute_prebuilt_bootstrap(
                current_upstream=SemVer.parse("3.6.3"),
                current_wrapper=WrapperVersion.parse("3.6.3-5"),
                has_image=False,
                has_state=True,
            )

    def test_wrapper_upstream_must_match_current_upstream(self):
        with self.assertRaises(ValueError):
            compute_prebuilt_bootstrap(
                current_upstream=SemVer.parse("3.6.3"),
                current_wrapper=WrapperVersion.parse("3.6.2-4"),
                has_image=False,
                has_state=False,
            )

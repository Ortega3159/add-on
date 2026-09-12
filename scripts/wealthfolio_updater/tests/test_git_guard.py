import unittest

from scripts.wealthfolio_updater.updater import (
    StaleBaseError,
    assert_fresh_base,
)


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA256_A = "a" * 64


class FreshBaseGuardTests(unittest.TestCase):
    def test_exact_full_sha_match_passes(self):
        result = assert_fresh_base(
            planned_base_sha=SHA_A,
            current_base_sha=SHA_A,
        )

        self.assertEqual(result, SHA_A)

    def test_changed_base_is_rejected_as_stale(self):
        with self.assertRaises(StaleBaseError):
            assert_fresh_base(
                planned_base_sha=SHA_A,
                current_base_sha=SHA_B,
            )

    def test_short_sha_is_rejected(self):
        with self.assertRaises(ValueError):
            assert_fresh_base(
                planned_base_sha="a" * 12,
                current_base_sha=SHA_A,
            )

    def test_uppercase_sha_is_rejected(self):
        with self.assertRaises(ValueError):
            assert_fresh_base(
                planned_base_sha="A" * 40,
                current_base_sha=SHA_A,
            )

    def test_sha_with_whitespace_is_rejected(self):
        with self.assertRaises(ValueError):
            assert_fresh_base(
                planned_base_sha=SHA_A + "\n",
                current_base_sha=SHA_A,
            )

    def test_invalid_current_sha_is_rejected(self):
        with self.assertRaises(ValueError):
            assert_fresh_base(
                planned_base_sha=SHA_A,
                current_base_sha="not-a-sha",
            )

    def test_full_sha256_object_format_is_supported(self):
        result = assert_fresh_base(
            planned_base_sha=SHA256_A,
            current_base_sha=SHA256_A,
        )

        self.assertEqual(result, SHA256_A)

    def test_different_sha_lengths_do_not_compare_as_equal(self):
        with self.assertRaises(StaleBaseError):
            assert_fresh_base(
                planned_base_sha=SHA_A,
                current_base_sha=SHA256_A,
            )


if __name__ == "__main__":
    unittest.main()

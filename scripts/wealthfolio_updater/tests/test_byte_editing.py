import unittest

from scripts.wealthfolio_updater.updater import (
    detect_line_ending,
    insert_after_exact_once,
    replace_exact_once,
)


class DetectLineEndingTests(unittest.TestCase):
    def test_detects_crlf(self):
        self.assertEqual(
            detect_line_ending(b"one\r\ntwo\r\n"),
            b"\r\n",
        )

    def test_detects_lf(self):
        self.assertEqual(
            detect_line_ending(b"one\ntwo\n"),
            b"\n",
        )

    def test_rejects_mixed_line_endings(self):
        with self.assertRaises(ValueError):
            detect_line_ending(b"one\r\ntwo\n")

    def test_rejects_file_without_line_endings(self):
        with self.assertRaises(ValueError):
            detect_line_ending(b"single-line")


class ReplaceExactOnceTests(unittest.TestCase):
    def test_replaces_exactly_one_occurrence(self):
        source = (
            b"ARG WEALTHFOLIO_VERSION=3.6.3\r\n"
            b"ARG OTHER=value\r\n"
        )

        result = replace_exact_once(
            source,
            b"ARG WEALTHFOLIO_VERSION=3.6.3",
            b"ARG WEALTHFOLIO_VERSION=3.8.0",
        )

        self.assertEqual(
            result,
            (
                b"ARG WEALTHFOLIO_VERSION=3.8.0\r\n"
                b"ARG OTHER=value\r\n"
            ),
        )

    def test_replacement_preserves_unrelated_bytes(self):
        source = (
            b"\x00prefix\r\n"
            b'version: "3.6.3-4"\r\n'
            b"suffix\xff\r\n"
        )

        result = replace_exact_once(
            source,
            b'version: "3.6.3-4"',
            b'version: "3.6.3-5"',
        )

        expected = (
            b"\x00prefix\r\n"
            b'version: "3.6.3-5"\r\n'
            b"suffix\xff\r\n"
        )

        self.assertEqual(result, expected)

    def test_zero_occurrences_is_rejected(self):
        with self.assertRaises(ValueError):
            replace_exact_once(
                b"abc\r\n",
                b"missing",
                b"replacement",
            )

    def test_multiple_occurrences_are_rejected(self):
        with self.assertRaises(ValueError):
            replace_exact_once(
                b"value\r\nvalue\r\n",
                b"value",
                b"new",
            )

    def test_empty_search_is_rejected(self):
        with self.assertRaises(ValueError):
            replace_exact_once(
                b"abc\r\n",
                b"",
                b"replacement",
            )


class InsertAfterExactOnceTests(unittest.TestCase):
    def test_inserts_crlf_line_without_normalizing_file(self):
        source = (
            b'name: "Wealthfolio (Unofficial)"\r\n'
            b'version: "3.6.3-5"\r\n'
            b'slug: "wealthfolio"\r\n'
        )

        result = insert_after_exact_once(
            source,
            b'version: "3.6.3-5"',
            b'image: "ghcr.io/ortega3159/wealthfolio-ha"',
        )

        self.assertEqual(
            result,
            (
                b'name: "Wealthfolio (Unofficial)"\r\n'
                b'version: "3.6.3-5"\r\n'
                b'image: "ghcr.io/ortega3159/wealthfolio-ha"\r\n'
                b'slug: "wealthfolio"\r\n'
            ),
        )

    def test_inserts_lf_line_without_normalizing_file(self):
        source = (
            b'version: "3.6.3-5"\n'
            b'slug: "wealthfolio"\n'
        )

        result = insert_after_exact_once(
            source,
            b'version: "3.6.3-5"',
            b'image: "ghcr.io/ortega3159/wealthfolio-ha"',
        )

        self.assertEqual(
            result,
            (
                b'version: "3.6.3-5"\n'
                b'image: "ghcr.io/ortega3159/wealthfolio-ha"\n'
                b'slug: "wealthfolio"\n'
            ),
        )

    def test_missing_anchor_is_rejected(self):
        with self.assertRaises(ValueError):
            insert_after_exact_once(
                b'slug: "wealthfolio"\r\n',
                b'version: "3.6.3-5"',
                b'image: "example"',
            )

    def test_duplicate_anchor_is_rejected(self):
        source = (
            b'version: "3.6.3-5"\r\n'
            b'version: "3.6.3-5"\r\n'
        )

        with self.assertRaises(ValueError):
            insert_after_exact_once(
                source,
                b'version: "3.6.3-5"',
                b'image: "example"',
            )

    def test_mixed_line_endings_are_rejected_before_insert(self):
        with self.assertRaises(ValueError):
            insert_after_exact_once(
                (
                    b'version: "3.6.3-5"\r\n'
                    b'slug: "wealthfolio"\n'
                ),
                b'version: "3.6.3-5"',
                b'image: "example"',
            )


if __name__ == "__main__":
    unittest.main()

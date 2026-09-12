import unittest

from scripts.wealthfolio_updater.ghcr_http import (
    GHCR_PULL_SCOPE,
    GHCR_REGISTRY,
    GHCR_REPOSITORY,
    GHCR_TOKEN_ENDPOINT,
    BearerChallenge,
    parse_www_authenticate,
)


class GhcrChallengeTests(unittest.TestCase):
    def test_accepts_real_ghcr_pull_challenge(self):
        challenge = parse_www_authenticate(
            'Bearer '
            'realm="https://ghcr.io/token",'
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull"'
        )

        self.assertEqual(
            challenge,
            BearerChallenge(
                realm=GHCR_TOKEN_ENDPOINT,
                service="ghcr.io",
                scope=GHCR_PULL_SCOPE,
            ),
        )

    def test_contract_constants_are_exact(self):
        self.assertEqual(
            GHCR_REGISTRY,
            "https://ghcr.io",
        )
        self.assertEqual(
            GHCR_TOKEN_ENDPOINT,
            "https://ghcr.io/token",
        )
        self.assertEqual(
            GHCR_REPOSITORY,
            "wealthfolio/wealthfolio",
        )
        self.assertEqual(
            GHCR_PULL_SCOPE,
            "repository:wealthfolio/wealthfolio:pull",
        )

    def test_rejects_non_bearer_scheme(self):
        with self.assertRaises(ValueError):
            parse_www_authenticate(
                'Basic realm="https://ghcr.io/token"'
            )

    def test_rejects_missing_required_parameter(self):
        headers = (
            'Bearer '
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull"',
            'Bearer '
            'realm="https://ghcr.io/token",'
            'scope="repository:wealthfolio/wealthfolio:pull"',
            'Bearer '
            'realm="https://ghcr.io/token",'
            'service="ghcr.io"',
        )

        for header in headers:
            with self.subTest(header=header):
                with self.assertRaises(ValueError):
                    parse_www_authenticate(header)

    def test_rejects_duplicate_parameter(self):
        header = (
            'Bearer '
            'realm="https://ghcr.io/token",'
            'realm="https://evil.invalid/token",'
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull"'
        )

        with self.assertRaises(ValueError):
            parse_www_authenticate(header)

    def test_rejects_unexpected_parameter(self):
        header = (
            'Bearer '
            'realm="https://ghcr.io/token",'
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull",'
            'extra="value"'
        )

        with self.assertRaises(ValueError):
            parse_www_authenticate(header)

    def test_rejects_wrong_realm(self):
        header = (
            'Bearer '
            'realm="https://evil.invalid/token",'
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull"'
        )

        with self.assertRaises(ValueError):
            parse_www_authenticate(header)

    def test_rejects_wrong_service(self):
        header = (
            'Bearer '
            'realm="https://ghcr.io/token",'
            'service="example.invalid",'
            'scope="repository:wealthfolio/wealthfolio:pull"'
        )

        with self.assertRaises(ValueError):
            parse_www_authenticate(header)

    def test_rejects_scope_other_than_pull_only(self):
        scopes = (
            "repository:wealthfolio/wealthfolio:push",
            "repository:wealthfolio/wealthfolio:pull,push",
            "repository:other/image:pull",
        )

        for scope in scopes:
            with self.subTest(scope=scope):
                header = (
                    'Bearer '
                    'realm="https://ghcr.io/token",'
                    'service="ghcr.io",'
                    f'scope="{scope}"'
                )

                with self.assertRaises(ValueError):
                    parse_www_authenticate(header)

    def test_rejects_unquoted_parameter_value(self):
        header = (
            'Bearer '
            'realm=https://ghcr.io/token,'
            'service="ghcr.io",'
            'scope="repository:wealthfolio/wealthfolio:pull"'
        )

        with self.assertRaises(ValueError):
            parse_www_authenticate(header)

    def test_rejects_non_string_header(self):
        for value in (None, b"Bearer", 123, True):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    parse_www_authenticate(value)


if __name__ == "__main__":
    unittest.main()

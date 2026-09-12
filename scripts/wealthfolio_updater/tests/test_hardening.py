import unittest

from scripts.wealthfolio_updater.updater import (
    DistributionMode,
    EXPECTED_PREBUILT_IMAGE,
    PlanState,
    RepositoryState,
    SemVer,
    WrapperVersion,
    plan_update,
    validate_repository_state,
)


ARCHES = frozenset({"amd64", "aarch64"})
UPSTREAM_DIGEST = "sha256:" + ("a" * 64)
WRAPPER_DIGEST = "sha256:" + ("b" * 64)


def local_repository():
    return RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=UPSTREAM_DIGEST,
        wrapper_version=WrapperVersion.parse("3.6.3-4"),
        architectures=ARCHES,
        distribution_mode=DistributionMode.LOCAL_BUILD,
        image=None,
        published_digest=None,
    )


def prebuilt_repository():
    return RepositoryState(
        upstream_version=SemVer.parse("3.8.2"),
        upstream_digest=UPSTREAM_DIGEST,
        wrapper_version=WrapperVersion.parse("3.8.2-7"),
        architectures=ARCHES,
        distribution_mode=DistributionMode.PREBUILT,
        image=EXPECTED_PREBUILT_IMAGE,
        published_digest=WRAPPER_DIGEST,
    )


def prebuilt_dockerfile():
    return (
        b"ARG WEALTHFOLIO_VERSION=3.6.3\r\n"
        + f"ARG WEALTHFOLIO_DIGEST={UPSTREAM_DIGEST}\r\n".encode("ascii")
        + b"\r\n"
        + (
            b"FROM ghcr.io/wealthfolio/wealthfolio:"
            b"${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}\r\n"
        )
    )


def prebuilt_config():
    return (
        b'name: "Wealthfolio (Unofficial)"\r\n'
        b'version: "3.6.3-5"\r\n'
        b'image: "ghcr.io/ortega3159/wealthfolio-ha"\r\n'
        b'slug: "wealthfolio"\r\n'
        b"\r\n"
        b"arch:\r\n"
        b"  - amd64\r\n"
        b"  - aarch64\r\n"
    )


class ApprovalHardeningTests(unittest.TestCase):
    def test_approval_is_rejected_during_prebuilt_bootstrap(self):
        plan = plan_update(
            repository=local_repository(),
            releases=[SemVer.parse("3.8.0")],
            approved_version=SemVer.parse("3.8.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertEqual(
            plan.target_upstream,
            SemVer.parse("3.6.3"),
        )
        self.assertEqual(
            plan.target_wrapper,
            WrapperVersion.parse("3.6.3-5"),
        )

    def test_stale_approval_is_rejected_when_there_is_no_update(self):
        plan = plan_update(
            repository=prebuilt_repository(),
            releases=[SemVer.parse("3.8.2")],
            approved_version=SemVer.parse("3.9.0"),
        )

        self.assertEqual(
            plan.state,
            PlanState.APPROVAL_MISMATCH,
        )
        self.assertIsNone(plan.target_upstream)
        self.assertIsNone(plan.target_wrapper)


class StateJsonHardeningTests(unittest.TestCase):
    def test_boolean_schema_is_not_integer_schema_one(self):
        state = (
            b'{"schema":true,'
            b'"image":"ghcr.io/ortega3159/wealthfolio-ha",'
            b'"version":"3.6.3-5",'
            + f'"digest":"{WRAPPER_DIGEST}"'.encode("ascii")
            + b"}\n"
        )

        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=prebuilt_dockerfile(),
                config_bytes=prebuilt_config(),
                state_bytes=state,
            )

    def test_duplicate_json_keys_are_rejected(self):
        state = (
            b'{"schema":1,'
            b'"image":"ghcr.io/ortega3159/wealthfolio-ha",'
            b'"version":"3.6.3-5",'
            + f'"digest":"{WRAPPER_DIGEST}",'.encode("ascii")
            + f'"digest":"{WRAPPER_DIGEST}"'.encode("ascii")
            + b"}\n"
        )

        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=prebuilt_dockerfile(),
                config_bytes=prebuilt_config(),
                state_bytes=state,
            )


if __name__ == "__main__":
    unittest.main()

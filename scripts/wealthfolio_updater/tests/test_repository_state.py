import json
import unittest

from scripts.wealthfolio_updater.updater import (
    DistributionMode,
    SemVer,
    WrapperVersion,
    update_local_build_files,
    validate_repository_state,
)


EXPECTED_IMAGE = "ghcr.io/ortega3159/wealthfolio-ha"

UPSTREAM_DIGEST = "sha256:" + ("a" * 64)
WRAPPER_DIGEST = "sha256:" + ("b" * 64)


def make_dockerfile(
    *,
    version="3.6.3",
    digest=UPSTREAM_DIGEST,
    from_line=(
        "FROM ghcr.io/wealthfolio/wealthfolio:"
        "${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}"
    ),
    duplicate_version_arg=False,
):
    lines = [
        f"ARG WEALTHFOLIO_VERSION={version}",
        f"ARG WEALTHFOLIO_DIGEST={digest}",
        "",
        from_line,
        "",
        "ARG BUILD_VERSION",
        "ARG BUILD_ARCH",
        "",
        'CMD ["/run.sh"]',
    ]

    if duplicate_version_arg:
        lines.insert(1, f"ARG WEALTHFOLIO_VERSION={version}")

    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def make_config(
    *,
    version="3.6.3-4",
    image=None,
    arches=("amd64", "aarch64"),
):
    lines = [
        'name: "Wealthfolio (Unofficial)"',
        f'version: "{version}"',
    ]

    if image is not None:
        lines.append(f'image: "{image}"')

    lines.extend(
        [
            'slug: "wealthfolio"',
            "",
            "arch:",
        ]
    )

    lines.extend(f"  - {arch}" for arch in arches)

    lines.extend(
        [
            "",
            "stage: experimental",
            "",
        ]
    )

    return "\r\n".join(lines).encode("ascii")


def make_state(
    *,
    schema=1,
    image=EXPECTED_IMAGE,
    version="3.6.3-5",
    digest=WRAPPER_DIGEST,
    extra=None,
):
    value = {
        "schema": schema,
        "image": image,
        "version": version,
        "digest": digest,
    }

    if extra is not None:
        value.update(extra)

    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


class LocalBuildRepositoryStateTests(unittest.TestCase):
    def test_current_local_build_state_is_valid(self):
        state = validate_repository_state(
            dockerfile_bytes=make_dockerfile(),
            config_bytes=make_config(),
            state_bytes=None,
        )

        self.assertEqual(
            state.upstream_version,
            SemVer.parse("3.6.3"),
        )
        self.assertEqual(state.upstream_digest, UPSTREAM_DIGEST)
        self.assertEqual(
            state.wrapper_version,
            WrapperVersion.parse("3.6.3-4"),
        )
        self.assertEqual(
            state.architectures,
            frozenset({"amd64", "aarch64"}),
        )
        self.assertEqual(
            state.distribution_mode,
            DistributionMode.LOCAL_BUILD,
        )
        self.assertIsNone(state.image)
        self.assertIsNone(state.published_digest)

    def test_wrapper_upstream_must_match_dockerfile_upstream(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(version="3.6.3"),
                config_bytes=make_config(version="3.6.2-4"),
                state_bytes=None,
            )

    def test_duplicate_upstream_version_arg_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(
                    duplicate_version_arg=True
                ),
                config_bytes=make_config(),
                state_bytes=None,
            )

    def test_invalid_upstream_digest_is_rejected(self):
        invalid = [
            "sha256:abc",
            "sha256:" + ("A" * 64),
            "sha512:" + ("a" * 64),
            "a" * 64,
        ]

        for digest in invalid:
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    validate_repository_state(
                        dockerfile_bytes=make_dockerfile(
                            digest=digest
                        ),
                        config_bytes=make_config(),
                        state_bytes=None,
                    )

    def test_from_must_use_pinned_version_and_digest_args(self):
        invalid_from_lines = [
            "FROM ghcr.io/wealthfolio/wealthfolio:3.6.3",
            (
                "FROM ghcr.io/wealthfolio/wealthfolio:"
                "${WEALTHFOLIO_VERSION}"
            ),
            (
                "FROM ghcr.io/wealthfolio/wealthfolio:"
                "3.6.3@${WEALTHFOLIO_DIGEST}"
            ),
        ]

        for from_line in invalid_from_lines:
            with self.subTest(from_line=from_line):
                with self.assertRaises(ValueError):
                    validate_repository_state(
                        dockerfile_bytes=make_dockerfile(
                            from_line=from_line
                        ),
                        config_bytes=make_config(),
                        state_bytes=None,
                    )

    def test_required_architecture_contract_is_exact(self):
        invalid_arch_sets = [
            ("amd64",),
            ("aarch64",),
            ("amd64", "aarch64", "armv7"),
            ("amd64", "amd64", "aarch64"),
        ]

        for arches in invalid_arch_sets:
            with self.subTest(arches=arches):
                with self.assertRaises(ValueError):
                    validate_repository_state(
                        dockerfile_bytes=make_dockerfile(),
                        config_bytes=make_config(
                            arches=arches
                        ),
                        state_bytes=None,
                    )


class PrebuiltRepositoryStateTests(unittest.TestCase):
    def test_valid_prebuilt_state_is_accepted(self):
        state = validate_repository_state(
            dockerfile_bytes=make_dockerfile(),
            config_bytes=make_config(
                version="3.6.3-5",
                image=EXPECTED_IMAGE,
            ),
            state_bytes=make_state(),
        )

        self.assertEqual(
            state.distribution_mode,
            DistributionMode.PREBUILT,
        )
        self.assertEqual(state.image, EXPECTED_IMAGE)
        self.assertEqual(
            state.published_digest,
            WRAPPER_DIGEST,
        )
        self.assertEqual(
            state.wrapper_version,
            WrapperVersion.parse("3.6.3-5"),
        )

    def test_image_without_state_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=None,
            )

    def test_state_without_image_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(),
                state_bytes=make_state(
                    version="3.6.3-4"
                ),
            )

    def test_prebuilt_image_must_be_expected_package(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image="ghcr.io/example/not-ours",
                ),
                state_bytes=make_state(
                    image="ghcr.io/example/not-ours"
                ),
            )

    def test_state_schema_must_be_supported(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=make_state(schema=2),
            )

    def test_state_version_must_match_config_version(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=make_state(
                    version="3.6.3-6"
                ),
            )

    def test_state_image_must_match_config_image(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=make_state(
                    image="ghcr.io/ortega3159/other"
                ),
            )

    def test_invalid_published_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=make_state(
                    digest="sha256:abc"
                ),
            )

    def test_unknown_state_fields_are_rejected_for_schema_one(self):
        with self.assertRaises(ValueError):
            validate_repository_state(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(
                    version="3.6.3-5",
                    image=EXPECTED_IMAGE,
                ),
                state_bytes=make_state(
                    extra={"unexpected": True}
                ),
            )



class LocalBuildRepositoryUpdateTests(unittest.TestCase):
    def test_updates_exact_local_build_pins(self):
        new_digest = "sha256:" + ("c" * 64)

        updated_dockerfile, updated_config = (
            update_local_build_files(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(),
                target_upstream=SemVer.parse("3.8.0"),
                target_wrapper=WrapperVersion.parse(
                    "3.8.0-1"
                ),
                target_digest=new_digest,
            )
        )

        self.assertEqual(
            updated_dockerfile,
            make_dockerfile(
                version="3.8.0",
                digest=new_digest,
            ),
        )
        self.assertEqual(
            updated_config,
            make_config(version="3.8.0-1"),
        )

        repository = validate_repository_state(
            dockerfile_bytes=updated_dockerfile,
            config_bytes=updated_config,
            state_bytes=None,
        )

        self.assertEqual(
            repository.upstream_version,
            SemVer.parse("3.8.0"),
        )
        self.assertEqual(
            repository.upstream_digest,
            new_digest,
        )
        self.assertEqual(
            repository.wrapper_version,
            WrapperVersion.parse("3.8.0-1"),
        )
        self.assertEqual(
            repository.distribution_mode,
            DistributionMode.LOCAL_BUILD,
        )

    def test_same_or_older_upstream_is_rejected(self):
        cases = [
            ("3.6.3", "3.6.3-5"),
            ("3.5.9", "3.5.9-1"),
        ]

        for upstream, wrapper in cases:
            with self.subTest(upstream=upstream):
                with self.assertRaises(ValueError):
                    update_local_build_files(
                        dockerfile_bytes=make_dockerfile(),
                        config_bytes=make_config(),
                        target_upstream=SemVer.parse(
                            upstream
                        ),
                        target_wrapper=WrapperVersion.parse(
                            wrapper
                        ),
                        target_digest=(
                            "sha256:" + ("c" * 64)
                        ),
                    )

    def test_target_wrapper_must_match_target_upstream(self):
        with self.assertRaises(ValueError):
            update_local_build_files(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(),
                target_upstream=SemVer.parse("3.8.0"),
                target_wrapper=WrapperVersion.parse(
                    "3.7.0-1"
                ),
                target_digest="sha256:" + ("c" * 64),
            )

    def test_invalid_target_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            update_local_build_files(
                dockerfile_bytes=make_dockerfile(),
                config_bytes=make_config(),
                target_upstream=SemVer.parse("3.8.0"),
                target_wrapper=WrapperVersion.parse(
                    "3.8.0-1"
                ),
                target_digest="not-a-digest",
            )

if __name__ == "__main__":
    unittest.main()

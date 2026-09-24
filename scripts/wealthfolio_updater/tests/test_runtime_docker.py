import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.wealthfolio_updater.runtime_docker as runtime_docker
from scripts.wealthfolio_updater.models import (
    DistributionMode,
    RepositoryState,
    SemVer,
    WrapperVersion,
)
from scripts.wealthfolio_updater.runtime_docker import (
    DockerRuntimeError,
    run_docker,
)


class DockerCommandBoundaryTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_command_uses_argument_vector_without_shell(
        self,
        subprocess_run,
    ):
        subprocess_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"result\n",
                stderr=b"",
            )
        )

        output = run_docker(
            [
                "version",
                "--format",
                "{{.Server.Version}}",
            ],
            timeout_seconds=7,
            operation="inspect Docker version",
        )

        self.assertEqual(
            output,
            b"result\n",
        )

        subprocess_run.assert_called_once_with(
            [
                "docker",
                "version",
                "--format",
                "{{.Server.Version}}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=7,
            check=False,
            shell=False,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_binary_input_is_passed_without_shell_interpolation(
        self,
        subprocess_run,
    ):
        subprocess_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
        )

        payload = (
            b'{"value":"$literal-not-shell-expanded"}\n'
        )

        output = run_docker(
            [
                "run",
                "--rm",
                "example:test",
            ],
            input_bytes=payload,
            timeout_seconds=11,
            operation="seed runtime data",
        )

        self.assertEqual(output, b"")

        subprocess_run.assert_called_once_with(
            [
                "docker",
                "run",
                "--rm",
                "example:test",
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=11,
            check=False,
            shell=False,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_nonzero_exit_does_not_expose_captured_output(
        self,
        subprocess_run,
    ):
        subprocess_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=42,
                stdout=b"possible-sensitive-stdout",
                stderr=b"possible-sensitive-stderr",
            )
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^Docker seed runtime data "
                r"failed with exit code 42$"
            ),
        ) as context:
            run_docker(
                ["run", "example:test"],
                operation="seed runtime data",
            )

        message = str(context.exception)

        self.assertNotIn(
            "possible-sensitive-stdout",
            message,
        )
        self.assertNotIn(
            "possible-sensitive-stderr",
            message,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_timeout_is_normalized_without_command_output(
        self,
        subprocess_run,
    ):
        subprocess_run.side_effect = (
            subprocess.TimeoutExpired(
                cmd=["docker", "build"],
                timeout=30,
                output=b"partial stdout",
                stderr=b"partial stderr",
            )
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^Docker build wrapper image "
                r"timed out$"
            ),
        ) as context:
            run_docker(
                ["build", "."],
                timeout_seconds=30,
                operation="build wrapper image",
            )

        message = str(context.exception)

        self.assertNotIn("partial stdout", message)
        self.assertNotIn("partial stderr", message)

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_missing_docker_cli_is_normalized(
        self,
        subprocess_run,
    ):
        subprocess_run.side_effect = (
            FileNotFoundError("docker")
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^Docker CLI is unavailable while "
                r"trying to inspect Docker version$"
            ),
        ):
            run_docker(
                ["version"],
                operation="inspect Docker version",
            )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.subprocess.run"
    )
    def test_stdout_must_be_bytes(
        self,
        subprocess_run,
    ):
        subprocess_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="unexpected text",
                stderr=b"",
            )
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^Docker command output must be bytes$",
        ):
            run_docker(
                ["version"],
                operation="inspect Docker version",
            )


def local_repository_state(
    *,
    architectures=frozenset({"amd64", "aarch64"}),
):
    return RepositoryState(
        upstream_version=SemVer.parse("3.6.3"),
        upstream_digest=(
            "sha256:"
            "2c939f64043481d7c5e4fc737ed87251"
            "8633c838bff9b9de699f0c158df4bc0b"
        ),
        wrapper_version=WrapperVersion.parse(
            "3.6.3-4"
        ),
        architectures=architectures,
        distribution_mode=DistributionMode.LOCAL_BUILD,
        image=None,
        published_digest=None,
    )


class DockerWrapperBuildTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_build_uses_exact_validated_repository_state(
        self,
        docker_runner,
    ):
        docker_runner.return_value = b"build output\n"

        result = (
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=local_repository_state(),
            )
        )

        self.assertEqual(
            result.tag,
            (
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
        )
        self.assertEqual(
            result.architecture,
            "amd64",
        )
        self.assertEqual(
            result.platform,
            "linux/amd64",
        )

        docker_runner.assert_called_once_with(
            [
                "build",
                "--pull",
                "--platform",
                "linux/amd64",
                "--build-arg",
                "WEALTHFOLIO_VERSION=3.6.3",
                "--build-arg",
                (
                    "WEALTHFOLIO_DIGEST="
                    "sha256:"
                    "2c939f64043481d7c5e4fc737ed87251"
                    "8633c838bff9b9de699f0c158df4bc0b"
                ),
                "--build-arg",
                "BUILD_VERSION=3.6.3-4",
                "--build-arg",
                "BUILD_ARCH=amd64",
                "--tag",
                (
                    "wealthfolio-runtime-test:"
                    "3.6.3-4-amd64"
                ),
                "/repo/tracker",
            ],
            timeout_seconds=600,
            operation="build amd64 wrapper image",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_prebuilt_repository_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        repository = RepositoryState(
            upstream_version=SemVer.parse("3.6.3"),
            upstream_digest=(
                "sha256:" + "a" * 64
            ),
            wrapper_version=WrapperVersion.parse(
                "3.6.3-5"
            ),
            architectures=frozenset(
                {"amd64", "aarch64"}
            ),
            distribution_mode=(
                DistributionMode.PREBUILT
            ),
            image=(
                "ghcr.io/ortega3159/"
                "wealthfolio-ha"
            ),
            published_digest=(
                "sha256:" + "b" * 64
            ),
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^runtime build requires "
                r"LOCAL_BUILD repository state$"
            ),
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=repository,
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_missing_amd64_contract_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        repository = local_repository_state(
            architectures=frozenset({"aarch64"}),
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^repository does not declare "
                r"amd64 architecture$"
            ),
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=repository,
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_wrapper_upstream_mismatch_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        repository = RepositoryState(
            upstream_version=SemVer.parse("3.6.3"),
            upstream_digest="sha256:" + "a" * 64,
            wrapper_version=WrapperVersion.parse(
                "3.6.2-4"
            ),
            architectures=frozenset(
                {"amd64", "aarch64"}
            ),
            distribution_mode=(
                DistributionMode.LOCAL_BUILD
            ),
            image=None,
            published_digest=None,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^wrapper upstream version does not "
                r"match repository upstream version$"
            ),
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=repository,
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_local_build_image_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        repository = local_repository_state()
        repository = RepositoryState(
            upstream_version=repository.upstream_version,
            upstream_digest=repository.upstream_digest,
            wrapper_version=repository.wrapper_version,
            architectures=repository.architectures,
            distribution_mode=repository.distribution_mode,
            image="example.invalid/image",
            published_digest=None,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^LOCAL_BUILD repository must not "
                r"declare an image$"
            ),
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=repository,
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_local_build_published_digest_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        repository = local_repository_state()
        repository = RepositoryState(
            upstream_version=repository.upstream_version,
            upstream_digest=repository.upstream_digest,
            wrapper_version=repository.wrapper_version,
            architectures=repository.architectures,
            distribution_mode=repository.distribution_mode,
            image=None,
            published_digest="sha256:" + "b" * 64,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            (
                r"^LOCAL_BUILD repository must not "
                r"declare a published digest$"
            ),
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=repository,
            )

        docker_runner.assert_not_called()


    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_repository_root_must_be_path(
        self,
        docker_runner,
    ):
        with self.assertRaisesRegex(
            TypeError,
            r"^repository_root must be a Path$",
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root="/repo",
                repository=local_repository_state(),
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_repository_state_type_is_checked_before_docker(
        self,
        docker_runner,
    ):
        with self.assertRaisesRegex(
            TypeError,
            r"^repository must be a RepositoryState$",
        ):
            runtime_docker.build_amd64_wrapper_image(
                repository_root=Path("/repo"),
                repository=object(),
            )

        docker_runner.assert_not_called()


def amd64_build_result(
    *,
    tag="wealthfolio-runtime-test:3.6.3-4-amd64",
):
    return runtime_docker.WrapperBuildResult(
        tag=tag,
        architecture="amd64",
        platform="linux/amd64",
    )


def image_inspect_payload(
    *,
    image_id=None,
    os_name="linux",
    architecture="amd64",
    command=None,
    labels=None,
):
    if image_id is None:
        image_id = "sha256:" + "c" * 64

    if command is None:
        command = ["/run.sh"]

    if labels is None:
        labels = {
            "io.hass.version": "3.6.3-4",
            "io.hass.arch": "amd64",
            "io.hass.type": "app",
        }

    return json.dumps(
        [
            {
                "Id": image_id,
                "Os": os_name,
                "Architecture": architecture,
                "Config": {
                    "Cmd": command,
                    "Labels": labels,
                },
            }
        ],
        separators=(",", ":"),
    ).encode("utf-8")


class DockerImageInspectionTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspection_validates_and_returns_image_identity(
        self,
        docker_runner,
    ):
        image_id = "sha256:" + "c" * 64
        docker_runner.return_value = (
            image_inspect_payload(
                image_id=image_id,
            )
        )

        result = (
            runtime_docker.inspect_amd64_wrapper_image(
                repository=local_repository_state(),
                build=amd64_build_result(),
            )
        )

        self.assertEqual(result.image_id, image_id)
        self.assertEqual(
            result.tag,
            "wealthfolio-runtime-test:"
            "3.6.3-4-amd64",
        )
        self.assertEqual(result.os, "linux")
        self.assertEqual(
            result.architecture,
            "amd64",
        )
        self.assertEqual(
            result.command,
            ("/run.sh",),
        )
        self.assertEqual(
            result.hass_version,
            "3.6.3-4",
        )
        self.assertEqual(
            result.hass_arch,
            "amd64",
        )
        self.assertEqual(
            result.hass_type,
            "app",
        )

        docker_runner.assert_called_once_with(
            [
                "image",
                "inspect",
                (
                    "wealthfolio-runtime-test:"
                    "3.6.3-4-amd64"
                ),
            ],
            timeout_seconds=30,
            operation="inspect amd64 wrapper image",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_unexpected_runtime_tag_is_rejected_before_docker(
        self,
        docker_runner,
    ):
        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime image tag does not match repository state$",
        ):
            runtime_docker.inspect_amd64_wrapper_image(
                repository=local_repository_state(),
                build=amd64_build_result(
                    tag="example.invalid:latest",
                ),
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspection_rejects_invalid_json_shape(
        self,
        docker_runner,
    ):
        invalid_outputs = (
            b"not-json",
            b"{}",
            b"[]",
            b"[{},{}]",
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaises(
                    DockerRuntimeError
                ):
                    runtime_docker.inspect_amd64_wrapper_image(
                        repository=local_repository_state(),
                        build=amd64_build_result(),
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspection_rejects_invalid_image_id(
        self,
        docker_runner,
    ):
        docker_runner.return_value = (
            image_inspect_payload(
                image_id="sha256:not-a-valid-id",
            )
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^built wrapper image ID is invalid$",
        ):
            runtime_docker.inspect_amd64_wrapper_image(
                repository=local_repository_state(),
                build=amd64_build_result(),
            )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspection_rejects_runtime_contract_mismatch(
        self,
        docker_runner,
    ):
        cases = (
            (
                image_inspect_payload(
                    os_name="windows",
                ),
                "operating system",
            ),
            (
                image_inspect_payload(
                    architecture="arm64",
                ),
                "architecture",
            ),
            (
                image_inspect_payload(
                    command=["/bin/sh"],
                ),
                "command",
            ),
            (
                image_inspect_payload(
                    labels={
                        "io.hass.version": "3.6.3-99",
                        "io.hass.arch": "amd64",
                        "io.hass.type": "app",
                    },
                ),
                "io.hass.version",
            ),
            (
                image_inspect_payload(
                    labels={
                        "io.hass.version": "3.6.3-4",
                        "io.hass.arch": "aarch64",
                        "io.hass.type": "app",
                    },
                ),
                "io.hass.arch",
            ),
            (
                image_inspect_payload(
                    labels={
                        "io.hass.version": "3.6.3-4",
                        "io.hass.arch": "amd64",
                        "io.hass.type": "container",
                    },
                ),
                "io.hass.type",
            ),
        )

        for output, expected_message in cases:
            with self.subTest(
                expected_message=expected_message
            ):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    expected_message,
                ):
                    runtime_docker.inspect_amd64_wrapper_image(
                        repository=local_repository_state(),
                        build=amd64_build_result(),
                    )


class RuntimeDataBootstrapTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_create_runtime_data_volume_uses_owned_labels(
        self,
        docker_runner,
    ):
        docker_runner.return_value = b"runtime-data-123\n"

        result = runtime_docker.create_runtime_data_volume()

        self.assertEqual(
            result.name,
            "runtime-data-123",
        )

        docker_runner.assert_called_once_with(
            [
                "volume",
                "create",
                "--label",
                "io.wealthfolio.runtime-test=true",
                "--label",
                "io.wealthfolio.runtime-test.role=data",
            ],
            timeout_seconds=30,
            operation="create runtime data volume",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_create_runtime_data_volume_rejects_invalid_name(
        self,
        docker_runner,
    ):
        invalid_outputs = (
            b"",
            b"\n",
            b"bad volume name\n",
            b"one\ntwo\n",
            b"\xff\n",
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaises(
                    DockerRuntimeError
                ):
                    runtime_docker.create_runtime_data_volume()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_uses_validated_image_id(
        self,
        docker_runner,
    ):
        image_id = "sha256:" + ("a" * 64)

        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        image = runtime_docker.WrapperImageInspection(
            image_id=image_id,
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        options_bytes = (
            b'{"auth_password_hash":"$literal",'
            b'"cors_allow_origins":["http://127.0.0.1"],'
            b'"auth_token_ttl_minutes":480}\n'
        )

        runtime_docker.seed_runtime_options(
            volume=volume,
            image=image,
            options_bytes=options_bytes,
        )

        docker_runner.assert_called_once_with(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                (
                    "type=volume,"
                    "source=runtime-data-123,"
                    "destination=/data"
                ),
                "--entrypoint",
                "/bin/sh",
                "--interactive",
                image_id,
                "-c",
                (
                    "umask 077\n"
                    "cat > /data/options.json\n"
                ),
            ],
            input_bytes=options_bytes,
            timeout_seconds=30,
            operation="seed runtime options",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_rejects_invalid_volume_name(
        self,
        docker_runner,
    ):
        image = runtime_docker.WrapperImageInspection(
            image_id="sha256:" + ("a" * 64),
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        volume = runtime_docker.RuntimeDataVolume(
            name="bad volume name",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"runtime data volume name is invalid",
        ):
            runtime_docker.seed_runtime_options(
                volume=volume,
                image=image,
                options_bytes=b"{}\n",
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_rejects_unvalidated_image(
        self,
        docker_runner,
    ):
        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        invalid_image = runtime_docker.WrapperImageInspection(
            image_id="sha256:not-valid",
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"runtime image inspection is invalid",
        ):
            runtime_docker.seed_runtime_options(
                volume=volume,
                image=invalid_image,
                options_bytes=b"{}\n",
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_requires_bytes(
        self,
        docker_runner,
    ):
        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        image = runtime_docker.WrapperImageInspection(
            image_id="sha256:" + ("a" * 64),
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        with self.assertRaises(TypeError):
            runtime_docker.seed_runtime_options(
                volume=volume,
                image=image,
                options_bytes="{}",
            )

        docker_runner.assert_not_called()


    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_rejects_wrong_volume_type(
        self,
        docker_runner,
    ):
        image = runtime_docker.WrapperImageInspection(
            image_id="sha256:" + ("a" * 64),
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        with self.assertRaisesRegex(
            TypeError,
            r"^volume must be a RuntimeDataVolume$",
        ):
            runtime_docker.seed_runtime_options(
                volume="runtime-data-123",
                image=image,
                options_bytes=b"{}\n",
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_rejects_wrong_image_type(
        self,
        docker_runner,
    ):
        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        with self.assertRaisesRegex(
            TypeError,
            r"^image must be a WrapperImageInspection$",
        ):
            runtime_docker.seed_runtime_options(
                volume=volume,
                image="sha256:" + ("a" * 64),
                options_bytes=b"{}\n",
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_seed_runtime_options_rejects_non_string_image_id(
        self,
        docker_runner,
    ):
        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        image = runtime_docker.WrapperImageInspection(
            image_id=None,
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime image inspection is invalid$",
        ):
            runtime_docker.seed_runtime_options(
                volume=volume,
                image=image,
                options_bytes=b"{}\n",
            )

        docker_runner.assert_not_called()


class RuntimeContainerStartTests(unittest.TestCase):
    def test_runtime_test_options_are_canonical(self):
        expected = (
            b'{"auth_password_hash":'
            b'"$argon2id$v=19$m=19456,t=2,p=1$'
            b'd2VhbHRoZm9saW8tdGVzdCE$'
            b'OkbKuJHEwf5aVPMa6jo/umIqdm2MDXwBK4DVTDXFFOw",'
            b'"cors_allow_origins":"http://127.0.0.1",'
            b'"auth_token_ttl_minutes":480}\n'
        )

        result = runtime_docker.runtime_test_options_bytes()

        self.assertEqual(result, expected)

        decoded = json.loads(result)

        self.assertEqual(
            decoded["cors_allow_origins"],
            "http://127.0.0.1",
        )
        self.assertNotIn(
            "*",
            decoded["cors_allow_origins"],
        )
        self.assertEqual(
            decoded["auth_token_ttl_minutes"],
            480,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_start_runtime_container_uses_real_wrapper_cmd(
        self,
        docker_runner,
    ):
        container_id = "b" * 64
        docker_runner.return_value = (
            container_id.encode("ascii") + b"\n"
        )

        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        image_id = "sha256:" + ("a" * 64)

        image = runtime_docker.WrapperImageInspection(
            image_id=image_id,
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        result = runtime_docker.start_runtime_container(
            volume=volume,
            image=image,
        )

        self.assertEqual(
            result.container_id,
            container_id,
        )

        docker_runner.assert_called_once_with(
            [
                "run",
                "--detach",
                "--init",
                "--network",
                "none",
                "--label",
                "io.wealthfolio.runtime-test=true",
                "--label",
                "io.wealthfolio.runtime-test.role=runtime",
                "--mount",
                (
                    "type=volume,"
                    "source=runtime-data-123,"
                    "destination=/data"
                ),
                "--env",
                "WF_LISTEN_ADDR=0.0.0.0:8088",
                "--env",
                (
                    "WF_DB_PATH="
                    "/data/wealthfolio/wealthfolio.db"
                ),
                "--env",
                "WF_AUTH_REQUIRED=true",
                "--env",
                "WF_MCP_ENABLED=false",
                image_id,
            ],
            timeout_seconds=30,
            operation="start runtime container",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_start_runtime_container_rejects_invalid_id(
        self,
        docker_runner,
    ):
        invalid_outputs = (
            b"",
            b"\n",
            b"short\n",
            (b"A" * 64) + b"\n",
            b"one\ntwo\n",
            b"\xff\n",
        )

        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        image = runtime_docker.WrapperImageInspection(
            image_id="sha256:" + ("a" * 64),
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime container ID is invalid$",
                ):
                    runtime_docker.start_runtime_container(
                        volume=volume,
                        image=image,
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_start_runtime_container_rejects_invalid_volume(
        self,
        docker_runner,
    ):
        volume = runtime_docker.RuntimeDataVolume(
            name="bad volume name",
        )

        image = runtime_docker.WrapperImageInspection(
            image_id="sha256:" + ("a" * 64),
            tag=(
                "wealthfolio-runtime-test:"
                "3.6.3-4-amd64"
            ),
            os="linux",
            architecture="amd64",
            command=("/run.sh",),
            hass_version="3.6.3-4",
            hass_arch="amd64",
            hass_type="app",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime data volume name is invalid$",
        ):
            runtime_docker.start_runtime_container(
                volume=volume,
                image=image,
            )

        docker_runner.assert_not_called()


class RuntimeHttpHealthTests(unittest.TestCase):
    def test_health_request_is_canonical(self):
        self.assertEqual(
            runtime_docker.runtime_health_request_bytes(),
            (
                b"GET /api/v1/healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            ),
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_http_exchange_uses_internal_nc(
        self,
        docker_runner,
    ):
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: 2\r\n"
            b"\r\n"
            b"ok"
        )

        docker_runner.return_value = response

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        request = (
            b"GET /api/v1/healthz HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )

        result = runtime_docker.runtime_http_exchange(
            container=container,
            request_bytes=request,
        )

        self.assertEqual(result, response)

        docker_runner.assert_called_once_with(
            [
                "exec",
                "--interactive",
                "b" * 64,
                "nc",
                "-w",
                "2",
                "127.0.0.1",
                "8088",
            ],
            input_bytes=request,
            timeout_seconds=5,
            operation="probe runtime HTTP",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_http_exchange_rejects_invalid_container_id(
        self,
        docker_runner,
    ):
        container = runtime_docker.RuntimeContainer(
            container_id="not-a-container-id",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime container ID is invalid$",
        ):
            runtime_docker.runtime_http_exchange(
                container=container,
                request_bytes=b"GET / HTTP/1.1\r\n\r\n",
            )

        docker_runner.assert_not_called()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_http_exchange_requires_bytes(
        self,
        docker_runner,
    ):
        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        with self.assertRaisesRegex(
            TypeError,
            r"^request_bytes must be bytes$",
        ):
            runtime_docker.runtime_http_exchange(
                container=container,
                request_bytes="GET /",
            )

        docker_runner.assert_not_called()

    def test_health_response_requires_200_and_exact_ok_body(self):
        cases = (
            (
                (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 2\r\n"
                    b"\r\n"
                    b"ok"
                ),
                True,
            ),
            (
                (
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 2\r\n"
                    b"\r\n"
                    b"ok"
                ),
                False,
            ),
            (
                (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 3\r\n"
                    b"\r\n"
                    b"bad"
                ),
                False,
            ),
            (
                b"not-http",
                False,
            ),
            (
                b"",
                False,
            ),
        )

        for response, expected in cases:
            with self.subTest(response=response):
                self.assertEqual(
                    runtime_docker
                    .runtime_health_response_is_ready(
                        response
                    ),
                    expected,
                )


class RuntimeReadinessTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_container_state(
        self,
        docker_runner,
    ):
        docker_runner.return_value = (
            b'{"Status":"running",'
            b'"Running":true,'
            b'"ExitCode":0}\n'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        result = (
            runtime_docker.inspect_runtime_container_state(
                container=container,
            )
        )

        self.assertEqual(result.status, "running")
        self.assertIs(result.running, True)
        self.assertEqual(result.exit_code, 0)

        docker_runner.assert_called_once_with(
            [
                "inspect",
                "b" * 64,
                "--format",
                "{{json .State}}",
            ],
            timeout_seconds=30,
            operation="inspect runtime container state",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_container_state_rejects_invalid_shape(
        self,
        docker_runner,
    ):
        invalid_outputs = (
            b"not-json",
            b"[]",
            b"{}",
            (
                b'{"Status":"",'
                b'"Running":true,'
                b'"ExitCode":0}'
            ),
            (
                b'{"Status":"running",'
                b'"Running":"true",'
                b'"ExitCode":0}'
            ),
            (
                b'{"Status":"running",'
                b'"Running":true,'
                b'"ExitCode":false}'
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaises(
                    DockerRuntimeError
                ):
                    runtime_docker.inspect_runtime_container_state(
                        container=container,
                    )

    @patch("time.sleep")
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.inspect_runtime_container_state"
    )
    def test_wait_runtime_ready_retries_then_returns_health(
        self,
        inspect_state,
        http_exchange,
        sleep,
    ):
        running = runtime_docker.RuntimeContainerState(
            status="running",
            running=True,
            exit_code=0,
        )

        inspect_state.side_effect = (
            running,
            running,
        )

        ready = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: 2\r\n"
            b"\r\n"
            b"ok"
        )

        http_exchange.side_effect = (
            DockerRuntimeError(
                "Docker probe runtime HTTP failed "
                "with exit code 1"
            ),
            ready,
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        result = runtime_docker.wait_runtime_ready(
            container=container,
            max_attempts=3,
            delay_seconds=0.25,
        )

        self.assertEqual(result, ready)

        self.assertEqual(
            inspect_state.call_count,
            2,
        )
        self.assertEqual(
            http_exchange.call_count,
            2,
        )
        sleep.assert_called_once_with(0.25)

    @patch("time.sleep")
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.inspect_runtime_container_state"
    )
    def test_wait_runtime_ready_fails_if_container_stops(
        self,
        inspect_state,
        http_exchange,
        sleep,
    ):
        inspect_state.return_value = (
            runtime_docker.RuntimeContainerState(
                status="exited",
                running=False,
                exit_code=1,
            )
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"runtime container stopped before becoming healthy",
        ):
            runtime_docker.wait_runtime_ready(
                container=container,
                max_attempts=3,
                delay_seconds=0.25,
            )

        http_exchange.assert_not_called()
        sleep.assert_not_called()

    @patch("time.sleep")
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.inspect_runtime_container_state"
    )
    def test_wait_runtime_ready_fails_after_attempt_limit(
        self,
        inspect_state,
        http_exchange,
        sleep,
    ):
        inspect_state.return_value = (
            runtime_docker.RuntimeContainerState(
                status="running",
                running=True,
                exit_code=0,
            )
        )

        http_exchange.return_value = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Length: 2\r\n"
            b"\r\n"
            b"ok"
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime container did not become healthy$",
        ):
            runtime_docker.wait_runtime_ready(
                container=container,
                max_attempts=2,
                delay_seconds=0.25,
            )

        self.assertEqual(
            inspect_state.call_count,
            2,
        )
        self.assertEqual(
            http_exchange.call_count,
            2,
        )
        sleep.assert_called_once_with(0.25)


class RuntimeBootstrapInspectionTests(unittest.TestCase):
    @staticmethod
    def valid_bootstrap_output() -> bytes:
        return (
            b"secret_uid=0\n"
            b"secret_gid=0\n"
            b"secret_mode=600\n"
            b"secret_size=45\n"
            b"secret_decoded_bytes=32\n"
            b"data_uid=1000\n"
            b"data_gid=1000\n"
            b"data_mode=755\n"
            b"db_uid=1000\n"
            b"db_gid=1000\n"
            b"db_mode=644\n"
            b"db_size=1155072\n"
            b"options_uid=0\n"
            b"options_gid=0\n"
            b"options_mode=600\n"
            b"options_size=193\n"
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_bootstrap_returns_state(
        self,
        docker_runner,
    ):
        docker_runner.return_value = (
            self.valid_bootstrap_output()
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        result = runtime_docker.inspect_runtime_bootstrap(
            container=container,
        )

        self.assertEqual(result.secret_uid, 0)
        self.assertEqual(result.secret_gid, 0)
        self.assertEqual(result.secret_mode, "600")
        self.assertEqual(result.secret_size, 45)
        self.assertEqual(
            result.secret_decoded_bytes,
            32,
        )

        self.assertEqual(result.data_uid, 1000)
        self.assertEqual(result.data_gid, 1000)
        self.assertEqual(result.data_mode, "755")

        self.assertEqual(result.db_uid, 1000)
        self.assertEqual(result.db_gid, 1000)
        self.assertEqual(result.db_mode, "644")
        self.assertEqual(result.db_size, 1155072)

        self.assertEqual(result.options_uid, 0)
        self.assertEqual(result.options_gid, 0)
        self.assertEqual(result.options_mode, "600")
        self.assertEqual(result.options_size, 193)

        docker_runner.assert_called_once()

        arguments = docker_runner.call_args.args[0]

        self.assertEqual(
            arguments[:4],
            [
                "exec",
                "b" * 64,
                "/bin/sh",
                "-c",
            ],
        )

        script = arguments[4]

        self.assertIn(
            "SECRET=/data/.wf_secret_key",
            script,
        )
        self.assertIn(
            "DB=/data/wealthfolio/wealthfolio.db",
            script,
        )
        self.assertIn(
            "OPTIONS=/data/options.json",
            script,
        )
        self.assertNotIn(
            'printf \'%s\' "$key"',
            script.split(
                "openssl base64",
                1,
            )[-1],
        )

        self.assertEqual(
            docker_runner.call_args.kwargs,
            {
                "timeout_seconds": 30,
                "operation": (
                    "inspect runtime bootstrap"
                ),
            },
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_bootstrap_rejects_invalid_output(
        self,
        docker_runner,
    ):
        invalid_outputs = (
            b"",
            b"not-key-value\n",
            (
                self.valid_bootstrap_output()
                + b"unexpected=1\n"
            ),
            self.valid_bootstrap_output().replace(
                b"db_size=1155072\n",
                b"",
            ),
            self.valid_bootstrap_output().replace(
                b"db_size=1155072\n",
                b"db_size=abc\n",
            ),
            self.valid_bootstrap_output().replace(
                b"data_mode=755\n",
                b"data_mode=999\n",
            ),
            self.valid_bootstrap_output().replace(
                b"db_size=1155072\n",
                (
                    b"db_size=1155072\n"
                    b"db_size=1155072\n"
                ),
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime bootstrap inspection is invalid$",
                ):
                    runtime_docker.inspect_runtime_bootstrap(
                        container=container,
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_bootstrap_rejects_contract_mismatch(
        self,
        docker_runner,
    ):
        replacements = (
            (
                b"secret_uid=0\n",
                b"secret_uid=1000\n",
            ),
            (
                b"secret_gid=0\n",
                b"secret_gid=1000\n",
            ),
            (
                b"secret_mode=600\n",
                b"secret_mode=644\n",
            ),
            (
                b"secret_decoded_bytes=32\n",
                b"secret_decoded_bytes=16\n",
            ),
            (
                b"data_uid=1000\n",
                b"data_uid=0\n",
            ),
            (
                b"data_gid=1000\n",
                b"data_gid=0\n",
            ),
            (
                b"db_uid=1000\n",
                b"db_uid=0\n",
            ),
            (
                b"db_gid=1000\n",
                b"db_gid=0\n",
            ),
            (
                b"db_size=1155072\n",
                b"db_size=0\n",
            ),
            (
                b"options_uid=0\n",
                b"options_uid=1000\n",
            ),
            (
                b"options_gid=0\n",
                b"options_gid=1000\n",
            ),
            (
                b"options_mode=600\n",
                b"options_mode=644\n",
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        base = self.valid_bootstrap_output()

        for old, new in replacements:
            with self.subTest(old=old, new=new):
                docker_runner.reset_mock()
                docker_runner.return_value = (
                    base.replace(old, new)
                )

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime bootstrap contract mismatch$",
                ):
                    runtime_docker.inspect_runtime_bootstrap(
                        container=container,
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_inspect_runtime_bootstrap_rejects_invalid_container(
        self,
        docker_runner,
    ):
        container = runtime_docker.RuntimeContainer(
            container_id="invalid",
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime container ID is invalid$",
        ):
            runtime_docker.inspect_runtime_bootstrap(
                container=container,
            )

        docker_runner.assert_not_called()


class RuntimeCleanupTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_runtime_container_verifies_ownership_then_removes(
        self,
        docker_runner,
    ):
        docker_runner.side_effect = (
            (
                b'{"io.wealthfolio.runtime-test":"true",'
                b'"io.wealthfolio.runtime-test.role":"runtime"}\n'
            ),
            b"runtime-container-id\n",
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        runtime_docker.cleanup_runtime_container(
            container=container,
        )

        self.assertEqual(
            docker_runner.call_count,
            2,
        )

        self.assertEqual(
            docker_runner.call_args_list[0].args[0],
            [
                "inspect",
                "b" * 64,
                "--format",
                "{{json .Config.Labels}}",
            ],
        )

        self.assertEqual(
            docker_runner.call_args_list[0].kwargs,
            {
                "timeout_seconds": 30,
                "operation": (
                    "inspect runtime container ownership"
                ),
            },
        )

        self.assertEqual(
            docker_runner.call_args_list[1].args[0],
            [
                "rm",
                "--force",
                "--volumes",
                "b" * 64,
            ],
        )

        self.assertEqual(
            docker_runner.call_args_list[1].kwargs,
            {
                "timeout_seconds": 30,
                "operation": (
                    "remove runtime container"
                ),
            },
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_runtime_container_rejects_foreign_object(
        self,
        docker_runner,
    ):
        invalid_labels = (
            b"null\n",
            b"{}\n",
            (
                b'{"io.wealthfolio.runtime-test":"false",'
                b'"io.wealthfolio.runtime-test.role":"runtime"}\n'
            ),
            (
                b'{"io.wealthfolio.runtime-test":"true",'
                b'"io.wealthfolio.runtime-test.role":"data"}\n'
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        for output in invalid_labels:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.side_effect = None
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime container ownership mismatch$",
                ):
                    runtime_docker.cleanup_runtime_container(
                        container=container,
                    )

                docker_runner.assert_called_once()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_runtime_data_volume_verifies_ownership_then_removes(
        self,
        docker_runner,
    ):
        docker_runner.side_effect = (
            (
                b'{"io.wealthfolio.runtime-test":"true",'
                b'"io.wealthfolio.runtime-test.role":"data"}\n'
            ),
            b"runtime-data-123\n",
        )

        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        runtime_docker.cleanup_runtime_data_volume(
            volume=volume,
        )

        self.assertEqual(
            docker_runner.call_count,
            2,
        )

        self.assertEqual(
            docker_runner.call_args_list[0].args[0],
            [
                "volume",
                "inspect",
                "runtime-data-123",
                "--format",
                "{{json .Labels}}",
            ],
        )

        self.assertEqual(
            docker_runner.call_args_list[0].kwargs,
            {
                "timeout_seconds": 30,
                "operation": (
                    "inspect runtime data volume ownership"
                ),
            },
        )

        self.assertEqual(
            docker_runner.call_args_list[1].args[0],
            [
                "volume",
                "rm",
                "runtime-data-123",
            ],
        )

        self.assertEqual(
            docker_runner.call_args_list[1].kwargs,
            {
                "timeout_seconds": 30,
                "operation": (
                    "remove runtime data volume"
                ),
            },
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_runtime_data_volume_rejects_foreign_object(
        self,
        docker_runner,
    ):
        invalid_labels = (
            b"null\n",
            b"{}\n",
            (
                b'{"io.wealthfolio.runtime-test":"false",'
                b'"io.wealthfolio.runtime-test.role":"data"}\n'
            ),
            (
                b'{"io.wealthfolio.runtime-test":"true",'
                b'"io.wealthfolio.runtime-test.role":"runtime"}\n'
            ),
        )

        volume = runtime_docker.RuntimeDataVolume(
            name="runtime-data-123",
        )

        for output in invalid_labels:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.side_effect = None
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime data volume ownership mismatch$",
                ):
                    runtime_docker.cleanup_runtime_data_volume(
                        volume=volume,
                    )

                docker_runner.assert_called_once()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_rejects_invalid_ownership_json(
        self,
        docker_runner,
    ):
        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        invalid_outputs = (
            b"",
            b"not-json",
            b"[]",
            b"\xff",
        )

        for output in invalid_outputs:
            with self.subTest(output=output):
                docker_runner.reset_mock()
                docker_runner.return_value = output

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime ownership inspection is invalid$",
                ):
                    runtime_docker.cleanup_runtime_container(
                        container=container,
                    )

                docker_runner.assert_called_once()

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.run_docker"
    )
    def test_cleanup_rejects_invalid_identifiers_before_docker(
        self,
        docker_runner,
    ):
        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime container ID is invalid$",
        ):
            runtime_docker.cleanup_runtime_container(
                container=runtime_docker.RuntimeContainer(
                    container_id="foreign",
                ),
            )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime data volume name is invalid$",
        ):
            runtime_docker.cleanup_runtime_data_volume(
                volume=runtime_docker.RuntimeDataVolume(
                    name="bad volume name",
                ),
            )

        docker_runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class RuntimeHttpResponseTests(unittest.TestCase):
    def test_parse_http_response_returns_structured_response(self):
        body = b'{"authenticated":true}'

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"X-Test: one\r\n"
            b"X-Test: two\r\n"
            b"\r\n"
            + body
        )

        result = runtime_docker.parse_runtime_http_response(
            response
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.reason_phrase, "OK")
        self.assertEqual(
            result.headers,
            (
                ("Content-Type", "application/json"),
                ("X-Test", "one"),
                ("X-Test", "two"),
            ),
        )
        self.assertEqual(result.body, body)

    def test_parse_http_response_decodes_chunked_body(self):
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"16\r\n"
            b'{"authenticated":true}\r\n'
            b"0\r\n"
            b"\r\n"
        )

        result = runtime_docker.parse_runtime_http_response(
            response
        )

        self.assertEqual(
            result.body,
            b'{"authenticated":true}',
        )

    def test_parse_http_response_rejects_malformed_response(self):
        invalid_responses = (
            b"",
            b"not-http",
            b"HTTP/1.0 200 OK\r\n\r\n",
            (
                b"HTTP/1.1 200 OK\r\n"
                b"broken-header\r\n"
                b"\r\n"
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
                b"zz\r\n"
            ),
        )

        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime HTTP response is invalid$",
                ):
                    runtime_docker.parse_runtime_http_response(
                        response
                    )

    def test_session_cookie_repr_does_not_expose_value(self):
        session = runtime_docker.RuntimeSessionCookie(
            value="super-secret-session-value",
        )

        rendered = repr(session)

        self.assertNotIn(
            "super-secret-session-value",
            rendered,
        )
        self.assertIn(
            "RuntimeSessionCookie",
            rendered,
        )



class RuntimeAuthenticationTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_login_returns_session_cookie(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Set-Cookie: "
            b"wf_session=secret-session-value; "
            b"HttpOnly; SameSite=Lax; Path=/; "
            b"Max-Age=28800\r\n"
            b"\r\n"
            b'{"authenticated":true,"expiresIn":28800}'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        session = runtime_docker.runtime_login(
            container=container,
            password="password",
        )

        self.assertIsInstance(
            session,
            runtime_docker.RuntimeSessionCookie,
        )
        self.assertEqual(
            session.value,
            "secret-session-value",
        )
        self.assertNotIn(
            "secret-session-value",
            repr(session),
        )

        payload = b'{"password":"password"}'

        http_exchange.assert_called_once_with(
            container=container,
            request_bytes=(
                b"POST /api/v1/auth/login HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Accept: application/json\r\n"
                b"Content-Type: application/json\r\n"
                + (
                    f"Content-Length: {len(payload)}\r\n"
                ).encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + payload
            ),
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_login_rejects_invalid_cookie_response(
        self,
        http_exchange,
    ):
        responses = (
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"authenticated":true,"expiresIn":28800}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Set-Cookie: other=value\r\n"
                b"\r\n"
                b'{"authenticated":true,"expiresIn":28800}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Set-Cookie: wf_session=\r\n"
                b"\r\n"
                b'{"authenticated":true,"expiresIn":28800}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Set-Cookie: wf_session=one\r\n"
                b"Set-Cookie: wf_session=two\r\n"
                b"\r\n"
                b'{"authenticated":true,"expiresIn":28800}'
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        for response in responses:
            with self.subTest(response=response):
                http_exchange.reset_mock()
                http_exchange.return_value = response

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime login response is invalid$",
                ):
                    runtime_docker.runtime_login(
                        container=container,
                        password="password",
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_login_rejects_non_200_response(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 401 Unauthorized\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"message":"invalid password"}'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime login failed$",
        ):
            runtime_docker.runtime_login(
                container=container,
                password="password",
            )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_auth_me_accepts_authenticated_session(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"authenticated":true}'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        result = runtime_docker.runtime_auth_me(
            container=container,
            session=session,
        )

        self.assertIs(result, True)

        http_exchange.assert_called_once_with(
            container=container,
            request_bytes=(
                b"GET /api/v1/auth/me HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Accept: application/json\r\n"
                b"Cookie: "
                b"wf_session=secret-session-value\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            ),
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_auth_me_rejects_invalid_response(
        self,
        http_exchange,
    ):
        responses = (
            (
                b"HTTP/1.1 401 Unauthorized\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"code":401,"message":"Unauthorized"}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b"not-json"
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"authenticated":false}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b"{}"
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for response in responses:
            with self.subTest(response=response):
                http_exchange.reset_mock()
                http_exchange.return_value = response

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime authentication check failed$",
                ):
                    runtime_docker.runtime_auth_me(
                        container=container,
                        session=session,
                    )


class RuntimeAccountReadTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_get_accounts_returns_account_list(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'[{"id":"account-1","name":"Test Cash"}]'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        accounts = runtime_docker.runtime_get_accounts(
            container=container,
            session=session,
        )

        self.assertEqual(
            accounts,
            [
                {
                    "id": "account-1",
                    "name": "Test Cash",
                }
            ],
        )

        http_exchange.assert_called_once_with(
            container=container,
            request_bytes=(
                b"GET /api/v1/accounts HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Accept: application/json\r\n"
                b"Cookie: "
                b"wf_session=secret-session-value\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            ),
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_get_accounts_accepts_empty_list(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b"[]"
        )

        accounts = runtime_docker.runtime_get_accounts(
            container=runtime_docker.RuntimeContainer(
                container_id="b" * 64,
            ),
            session=runtime_docker.RuntimeSessionCookie(
                value="secret-session-value",
            ),
        )

        self.assertEqual(accounts, [])

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_get_accounts_rejects_invalid_response(
        self,
        http_exchange,
    ):
        responses = (
            (
                b"HTTP/1.1 401 Unauthorized\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"code":401,"message":"Unauthorized"}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b"not-json"
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"id":"not-a-list"}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'["not-an-account-object"]'
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for response in responses:
            with self.subTest(response=response):
                http_exchange.reset_mock()
                http_exchange.return_value = response

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime accounts response is invalid$",
                ):
                    runtime_docker.runtime_get_accounts(
                        container=container,
                        session=session,
                    )



class RuntimeAccountWriteTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_get_accounts"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_cash_account_confirms_by_readback(
        self,
        http_exchange,
        get_accounts,
    ):
        http_exchange.return_value = b""

        get_accounts.return_value = [
            {
                "id": "account-1",
                "name": "WU4C Test Cash",
                "accountType": "CASH",
                "currency": "USD",
                "isDefault": False,
                "isActive": True,
            }
        ]

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        account = runtime_docker.runtime_create_cash_account(
            container=container,
            session=session,
            name="WU4C Test Cash",
            currency="USD",
        )

        self.assertEqual(
            account["id"],
            "account-1",
        )

        http_exchange.assert_called_once()

        request = http_exchange.call_args.kwargs[
            "request_bytes"
        ]

        self.assertIn(
            b"POST /api/v1/accounts HTTP/1.1\r\n",
            request,
        )
        self.assertIn(
            b'"name":"WU4C Test Cash"',
            request,
        )
        self.assertIn(
            b'"accountType":"CASH"',
            request,
        )
        self.assertIn(
            b'"currency":"USD"',
            request,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_get_accounts"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_cash_account_requires_exact_readback(
        self,
        http_exchange,
        get_accounts,
    ):
        http_exchange.return_value = b""

        invalid_account_sets = (
            [],
            [
                {
                    "id": "account-1",
                    "name": "Other",
                    "accountType": "CASH",
                    "currency": "USD",
                }
            ],
            [
                {
                    "id": "account-1",
                    "name": "WU4C Test Cash",
                    "accountType": "CASH",
                    "currency": "USD",
                },
                {
                    "id": "account-2",
                    "name": "WU4C Test Cash",
                    "accountType": "CASH",
                    "currency": "USD",
                },
            ],
            [
                {
                    "id": "",
                    "name": "WU4C Test Cash",
                    "accountType": "CASH",
                    "currency": "USD",
                }
            ],
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for accounts in invalid_account_sets:
            with self.subTest(accounts=accounts):
                http_exchange.reset_mock()
                get_accounts.return_value = accounts

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime account creation could not be confirmed$",
                ):
                    runtime_docker.runtime_create_cash_account(
                        container=container,
                        session=session,
                        name="WU4C Test Cash",
                        currency="USD",
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_get_accounts"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_cash_account_rejects_explicit_http_failure(
        self,
        http_exchange,
        get_accounts,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 422 Unprocessable Entity\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"invalid account"
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime account creation failed$",
        ):
            runtime_docker.runtime_create_cash_account(
                container=runtime_docker.RuntimeContainer(
                    container_id="b" * 64,
                ),
                session=runtime_docker.RuntimeSessionCookie(
                    value="secret-session-value",
                ),
                name="WU4C Test Cash",
                currency="USD",
            )

        get_accounts.assert_not_called()



class RuntimeDepositTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_search_deposits_returns_data_list(
        self,
        http_exchange,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"data":[{'
            b'"id":"activity-1",'
            b'"accountId":"account-1",'
            b'"activityType":"DEPOSIT",'
            b'"status":"POSTED",'
            b'"date":"2026-01-15T12:00:00+00:00",'
            b'"amount":"123.45",'
            b'"currency":"USD",'
            b'"comment":"WU4C deterministic deposit"'
            b'}],"meta":{"total":1}}'
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        activities = runtime_docker.runtime_search_deposits(
            container=container,
            session=session,
            account_id="account-1",
        )

        self.assertEqual(len(activities), 1)
        self.assertEqual(
            activities[0]["id"],
            "activity-1",
        )

        request = http_exchange.call_args.kwargs[
            "request_bytes"
        ]

        self.assertIn(
            b"POST /api/v1/activities/search HTTP/1.1\r\n",
            request,
        )
        self.assertIn(
            b'"page":0',
            request,
        )
        self.assertIn(
            b'"pageSize":20',
            request,
        )
        self.assertIn(
            b'"accountIdFilter":"account-1"',
            request,
        )
        self.assertIn(
            b'"activityTypeFilter":"DEPOSIT"',
            request,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_search_deposits_rejects_invalid_response(
        self,
        http_exchange,
    ):
        responses = (
            (
                b"HTTP/1.1 401 Unauthorized\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"message":"Unauthorized"}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b"not-json"
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"data":{},"meta":{}}'
            ),
            (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n"
                b'{"data":["not-an-object"],"meta":{}}'
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for response in responses:
            with self.subTest(response=response):
                http_exchange.reset_mock()
                http_exchange.return_value = response

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime activities response is invalid$",
                ):
                    runtime_docker.runtime_search_deposits(
                        container=container,
                        session=session,
                        account_id="account-1",
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_search_deposits"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_test_deposit_confirms_by_readback(
        self,
        http_exchange,
        search_deposits,
    ):
        http_exchange.return_value = b""

        search_deposits.return_value = [
            {
                "id": "activity-1",
                "accountId": "account-1",
                "activityType": "DEPOSIT",
                "status": "POSTED",
                "date": "2026-01-15T12:00:00+00:00",
                "amount": "123.45",
                "currency": "USD",
                "comment": "WU4C deterministic deposit",
            }
        ]

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        activity = (
            runtime_docker.runtime_create_test_deposit(
                container=container,
                session=session,
                account_id="account-1",
            )
        )

        self.assertEqual(
            activity["id"],
            "activity-1",
        )

        request = http_exchange.call_args.kwargs[
            "request_bytes"
        ]

        self.assertIn(
            b"POST /api/v1/activities HTTP/1.1\r\n",
            request,
        )
        self.assertIn(
            b'"accountId":"account-1"',
            request,
        )
        self.assertIn(
            b'"activityType":"DEPOSIT"',
            request,
        )
        self.assertIn(
            b'"activityDate":"2026-01-15T12:00:00.000Z"',
            request,
        )
        self.assertIn(
            b'"amount":123.45',
            request,
        )
        self.assertIn(
            b'"currency":"USD"',
            request,
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_search_deposits"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_test_deposit_requires_exact_readback(
        self,
        http_exchange,
        search_deposits,
    ):
        http_exchange.return_value = b""

        invalid_sets = (
            [],
            [
                {
                    "id": "activity-1",
                    "accountId": "other-account",
                    "activityType": "DEPOSIT",
                    "status": "POSTED",
                    "date": "2026-01-15T12:00:00+00:00",
                    "amount": "123.45",
                    "currency": "USD",
                    "comment": "WU4C deterministic deposit",
                }
            ],
            [
                {
                    "id": "activity-1",
                    "accountId": "account-1",
                    "activityType": "DEPOSIT",
                    "status": "POSTED",
                    "date": "2026-01-15T12:00:00+00:00",
                    "amount": "999.00",
                    "currency": "USD",
                    "comment": "WU4C deterministic deposit",
                }
            ],
            [
                {
                    "id": "",
                    "accountId": "account-1",
                    "activityType": "DEPOSIT",
                    "status": "POSTED",
                    "date": "2026-01-15T12:00:00+00:00",
                    "amount": "123.45",
                    "currency": "USD",
                    "comment": "WU4C deterministic deposit",
                }
            ],
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for activities in invalid_sets:
            with self.subTest(activities=activities):
                http_exchange.reset_mock()
                search_deposits.return_value = activities

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime deposit creation could not be confirmed$",
                ):
                    runtime_docker.runtime_create_test_deposit(
                        container=container,
                        session=session,
                        account_id="account-1",
                    )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_search_deposits"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_http_exchange"
    )
    def test_create_test_deposit_rejects_explicit_http_failure(
        self,
        http_exchange,
        search_deposits,
    ):
        http_exchange.return_value = (
            b"HTTP/1.1 422 Unprocessable Entity\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"invalid activity"
        )

        with self.assertRaisesRegex(
            DockerRuntimeError,
            r"^runtime deposit creation failed$",
        ):
            runtime_docker.runtime_create_test_deposit(
                container=runtime_docker.RuntimeContainer(
                    container_id="b" * 64,
                ),
                session=runtime_docker.RuntimeSessionCookie(
                    value="secret-session-value",
                ),
                account_id="account-1",
            )

        search_deposits.assert_not_called()



class RuntimeFunctionalSnapshotTests(unittest.TestCase):
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_search_deposits"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_get_accounts"
    )
    def test_capture_functional_snapshot(
        self,
        get_accounts,
        search_deposits,
    ):
        get_accounts.return_value = [
            {
                "id": "account-1",
                "name": "WU4C Test Cash",
                "accountType": "CASH",
                "currency": "USD",
                "isDefault": False,
                "isActive": True,
            }
        ]

        search_deposits.return_value = [
            {
                "id": "activity-1",
                "accountId": "account-1",
                "activityType": "DEPOSIT",
                "status": "POSTED",
                "date": "2026-01-15T12:00:00+00:00",
                "amount": "123.45",
                "currency": "USD",
                "comment": "WU4C deterministic deposit",
            }
        ]

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        snapshot = (
            runtime_docker.capture_runtime_functional_snapshot(
                container=container,
                session=session,
                account_id="account-1",
            )
        )

        self.assertEqual(
            snapshot.account_id,
            "account-1",
        )
        self.assertEqual(
            snapshot.activity_id,
            "activity-1",
        )
        self.assertEqual(
            snapshot.account_name,
            "WU4C Test Cash",
        )
        self.assertEqual(
            snapshot.account_type,
            "CASH",
        )
        self.assertEqual(
            snapshot.account_currency,
            "USD",
        )
        self.assertEqual(
            snapshot.activity_type,
            "DEPOSIT",
        )
        self.assertEqual(
            snapshot.activity_status,
            "POSTED",
        )
        self.assertEqual(
            snapshot.activity_date,
            "2026-01-15T12:00:00+00:00",
        )
        self.assertEqual(
            snapshot.amount,
            "123.45",
        )
        self.assertEqual(
            snapshot.activity_currency,
            "USD",
        )
        self.assertEqual(
            snapshot.comment,
            "WU4C deterministic deposit",
        )

    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_search_deposits"
    )
    @patch(
        "scripts.wealthfolio_updater."
        "runtime_docker.runtime_get_accounts"
    )
    def test_capture_functional_snapshot_fails_closed(
        self,
        get_accounts,
        search_deposits,
    ):
        invalid_cases = (
            (
                [],
                [],
            ),
            (
                [
                    {
                        "id": "other-account",
                        "name": "WU4C Test Cash",
                        "accountType": "CASH",
                        "currency": "USD",
                        "isDefault": False,
                        "isActive": True,
                    }
                ],
                [],
            ),
            (
                [
                    {
                        "id": "account-1",
                        "name": "Wrong Name",
                        "accountType": "CASH",
                        "currency": "USD",
                        "isDefault": False,
                        "isActive": True,
                    }
                ],
                [],
            ),
            (
                [
                    {
                        "id": "account-1",
                        "name": "WU4C Test Cash",
                        "accountType": "CASH",
                        "currency": "USD",
                        "isDefault": False,
                        "isActive": True,
                    }
                ],
                [],
            ),
            (
                [
                    {
                        "id": "account-1",
                        "name": "WU4C Test Cash",
                        "accountType": "CASH",
                        "currency": "USD",
                        "isDefault": False,
                        "isActive": True,
                    }
                ],
                [
                    {
                        "id": "activity-1",
                        "accountId": "account-1",
                        "activityType": "DEPOSIT",
                        "status": "POSTED",
                        "date": "2026-01-15T12:00:00+00:00",
                        "amount": "999.00",
                        "currency": "USD",
                        "comment": "WU4C deterministic deposit",
                    }
                ],
            ),
        )

        container = runtime_docker.RuntimeContainer(
            container_id="b" * 64,
        )
        session = runtime_docker.RuntimeSessionCookie(
            value="secret-session-value",
        )

        for accounts, deposits in invalid_cases:
            with self.subTest(
                accounts=accounts,
                deposits=deposits,
            ):
                get_accounts.return_value = accounts
                search_deposits.return_value = deposits

                with self.assertRaisesRegex(
                    DockerRuntimeError,
                    r"^runtime functional snapshot is invalid$",
                ):
                    runtime_docker.capture_runtime_functional_snapshot(
                        container=container,
                        session=session,
                        account_id="account-1",
                    )

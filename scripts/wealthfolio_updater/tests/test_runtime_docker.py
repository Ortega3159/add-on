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


if __name__ == "__main__":
    unittest.main()

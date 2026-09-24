import re
import unittest
from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/wealthfolio-updater-audit.yml"
)

CHECKOUT_SHA = (
    "3d3c42e5aac5ba805825da76410c181273ba90b1"
)
SETUP_PYTHON_SHA = (
    "5fda3b95a4ea91299a34e894583c3862153e4b97"
)


class UpdaterWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(
            encoding="utf-8"
        )

    def test_triggers_feature_push_schedule_and_manual_dispatch(self):
        self.assertIn(
            "push:\n"
            "    branches:\n"
            "      - feat/wealthfolio-auto-update\n",
            self.text,
        )

        self.assertIn(
            "schedule:\n"
            "    - cron: '37 */6 * * *'\n",
            self.text,
        )

        self.assertIn(
            "workflow_dispatch:",
            self.text,
        )

        forbidden = [
            "pull_request:",
            "pull_request_target:",
            "workflow_run:",
            "repository_dispatch:",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    self.text,
                )

    def test_permissions_are_contents_write_only(self):
        self.assertIn(
            "permissions:\n"
            "  contents: write\n",
            self.text,
        )

        self.assertEqual(
            self.text.count("permissions:"),
            1,
        )

        forbidden = [
            "permissions: read-all",
            "permissions: write-all",
            "packages:",
            "issues:",
            "pull-requests:",
            "id-token:",
            "actions: write",
            "checks: write",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    self.text,
                )

    def test_job_only_runs_for_branch_refs(self):
        self.assertIn(
            "if: github.ref_type == 'branch'",
            self.text,
        )

    def test_runner_and_timeout_are_explicit(self):
        self.assertIn(
            "runs-on: ubuntu-24.04",
            self.text,
        )
        self.assertIn(
            "timeout-minutes: 10",
            self.text,
        )

    def test_checkout_is_pinned_and_can_push(self):
        self.assertIn(
            f"uses: actions/checkout@{CHECKOUT_SHA}",
            self.text,
        )
        self.assertIn(
            "ref: ${{ github.sha }}",
            self.text,
        )
        self.assertIn(
            "fetch-depth: 1",
            self.text,
        )
        self.assertIn(
            "persist-credentials: true",
            self.text,
        )

    def test_python_is_exact_and_action_is_pinned(self):
        self.assertIn(
            f"uses: actions/setup-python@{SETUP_PYTHON_SHA}",
            self.text,
        )
        self.assertIn(
            "python-version: '3.14.2'",
            self.text,
        )
        self.assertIn(
            "check-latest: false",
            self.text,
        )
        self.assertNotIn(
            "cache:",
            self.text,
        )

    def test_offline_suite_runs_before_repository_update(self):
        tests_command = (
            "python -m unittest discover "
            "-s scripts/wealthfolio_updater/tests "
            "-p 'test_*.py'"
        )
        update_command = (
            "python -m "
            "scripts.wealthfolio_updater.update_cli"
        )

        tests_position = self.text.find(
            tests_command
        )
        update_position = self.text.find(
            update_command
        )

        self.assertNotEqual(
            tests_position,
            -1,
        )
        self.assertNotEqual(
            update_position,
            -1,
        )
        self.assertLess(
            tests_position,
            update_position,
        )

    def test_updater_uses_exact_checkout_sha(self):
        self.assertIn(
            "--repository-root .",
            self.text,
        )
        self.assertIn(
            "--expected-git-sha "
            "'${{ github.sha }}'",
            self.text,
        )

    def test_change_gate_requires_exact_tracker_files(self):
        self.assertIn(
            "git diff --name-only",
            self.text,
        )
        self.assertIn(
            "tracker/Dockerfile",
            self.text,
        )
        self.assertIn(
            "tracker/config.yml",
            self.text,
        )
        self.assertIn(
            'echo "changed=false" >> "$GITHUB_OUTPUT"',
            self.text,
        )
        self.assertIn(
            'echo "changed=true" >> "$GITHUB_OUTPUT"',
            self.text,
        )

    def test_commit_adds_only_expected_files(self):
        self.assertIn(
            "git add -- "
            "tracker/Dockerfile "
            "tracker/config.yml",
            self.text,
        )

        forbidden = [
            "git add .",
            "git add -A",
            "git add --all",
            "git add tracker/",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    self.text,
                )

    def test_commit_and_push_only_run_when_files_changed(self):
        self.assertIn(
            "if: steps.changes.outputs.changed == 'true'",
            self.text,
        )
        self.assertIn(
            'git config user.name "github-actions[bot]"',
            self.text,
        )
        self.assertIn(
            'git config user.email '
            '"41898282+github-actions[bot]'
            '@users.noreply.github.com"',
            self.text,
        )
        self.assertIn(
            'git commit -m '
            '"⬆️ chore(wealthfolio): '
            'update upstream release"',
            self.text,
        )
        self.assertIn(
            'git push origin '
            '"HEAD:${{ github.ref_name }}"',
            self.text,
        )

    def test_workflow_has_no_unneeded_privileged_capabilities(self):
        forbidden = [
            "secrets.",
            "docker ",
            "docker\n",
            "sudo ",
            "environment:",
            "upload-artifact",
            "ghcr.io/ortega3159/wealthfolio-ha",
            "tailscale",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    self.text,
                )

    def test_only_expected_external_actions_are_used(self):
        uses_lines = [
            line.strip()
            for line in self.text.splitlines()
            if line.strip().startswith("uses:")
        ]

        self.assertEqual(
            uses_lines,
            [
                (
                    "uses: actions/checkout@"
                    + CHECKOUT_SHA
                ),
                (
                    "uses: actions/setup-python@"
                    + SETUP_PYTHON_SHA
                ),
            ],
        )

    def test_every_external_action_is_pinned_to_full_commit_sha(self):
        uses_lines = [
            line.strip()
            for line in self.text.splitlines()
            if line.strip().startswith("uses:")
        ]

        pattern = re.compile(
            r"^uses: [A-Za-z0-9_.-]+/"
            r"[A-Za-z0-9_.-]+@[0-9a-f]{40}$"
        )

        for line in uses_lines:
            with self.subTest(line=line):
                self.assertRegex(
                    line,
                    pattern,
                )


if __name__ == "__main__":
    unittest.main()

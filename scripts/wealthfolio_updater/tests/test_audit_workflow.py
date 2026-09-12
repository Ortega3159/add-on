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


class AuditWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(
            encoding="utf-8"
        )

    def test_trigger_scope_is_deliberately_narrow(self):
        self.assertIn(
            "push:\n"
            "    branches:\n"
            "      - feat/wealthfolio-updater\n",
            self.text,
        )
        self.assertIn(
            "workflow_dispatch:",
            self.text,
        )

        forbidden = [
            "pull_request:",
            "pull_request_target:",
            "schedule:",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_permissions_are_read_only(self):
        self.assertIn(
            "permissions:\n"
            "  contents: read\n",
            self.text,
        )

        forbidden = [
            "contents: write",
            "packages:",
            "issues:",
            "pull-requests:",
            "id-token:",
            "actions: write",
            "checks: write",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_runner_and_timeout_are_explicit(self):
        self.assertIn(
            "runs-on: ubuntu-24.04",
            self.text,
        )
        self.assertIn(
            "timeout-minutes: 10",
            self.text,
        )

    def test_checkout_is_pinned_and_does_not_persist_credentials(self):
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
            "persist-credentials: false",
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

    def test_offline_suite_runs_before_live_audit(self):
        tests_command = (
            "python -m unittest discover "
            "-s scripts/wealthfolio_updater/tests "
            "-p 'test_*.py'"
        )
        audit_command = (
            "python -m "
            "scripts.wealthfolio_updater.audit_cli"
        )

        tests_position = self.text.find(
            tests_command
        )
        audit_position = self.text.find(
            audit_command
        )

        self.assertNotEqual(
            tests_position,
            -1,
        )
        self.assertNotEqual(
            audit_position,
            -1,
        )
        self.assertLess(
            tests_position,
            audit_position,
        )

    def test_audit_uses_event_sha_and_step_summary(self):
        self.assertIn(
            "--repository-root .",
            self.text,
        )
        self.assertIn(
            "--expected-git-sha "
            "'${{ github.sha }}'",
            self.text,
        )
        self.assertIn(
            '--markdown-output "$GITHUB_STEP_SUMMARY"',
            self.text,
        )

    def test_workflow_has_no_mutating_or_privileged_capabilities(self):
        forbidden = [
            "secrets.",
            "GITHUB_TOKEN",
            "git push",
            "docker ",
            "docker\n",
            "sudo ",
            "environment:",
            "upload-artifact",
            "workflow_run:",
            "repository_dispatch:",
            "continue-on-error: true",
            "concurrency:",
        ]

        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_actions_use_full_commit_sha_not_floating_tags(self):
        self.assertNotIn(
            "actions/checkout@v",
            self.text,
        )
        self.assertNotIn(
            "actions/setup-python@v",
            self.text,
        )


    def test_permissions_cannot_be_broadened_or_overridden(self):
        self.assertEqual(
            self.text.count("permissions:"),
            1,
        )

        self.assertNotIn(
            "permissions: read-all",
            self.text,
        )
        self.assertNotIn(
            "permissions: write-all",
            self.text,
        )

        for line in self.text.splitlines():
            if line.lstrip() == "permissions:":
                self.assertEqual(
                    line,
                    "permissions:",
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
        import re

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

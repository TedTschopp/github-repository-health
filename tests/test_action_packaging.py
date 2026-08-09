"""Regression checks for the reusable and scheduled GitHub Actions package."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from automation.repository_health.configuration import load_config


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "repository-health" / "action.yml"
SELF_WORKFLOW = ROOT / ".github" / "workflows" / "repository-health.yml"
CONSUMER_WORKFLOW = ROOT / "examples" / "workflows" / "repository-health.yml"
SELF_CONFIG = ROOT / ".github" / "repository-health.toml"
CONSUMER_CONFIG = ROOT / "examples" / "config" / "repository-health.toml"


class ActionPackagingTests(unittest.TestCase):
    def test_composite_action_generates_and_publishes_both_reports(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        self.assertIn("using: composite", text)
        self.assertIn("python3 -m automation.repository_health", text)
        self.assertIn("python3 -m automation.repository_health.reporting", text)
        self.assertIn("leadership-summary.md", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertNotIn("actions/upload-artifact", text)
        self.assertNotRegex(text, r"(?i)fail[-_]below|minimum[-_]score|score[-_]threshold")

    def test_workflows_are_read_only_and_use_full_history(self) -> None:
        for path in (SELF_WORKFLOW, CONSUMER_WORKFLOW):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for permission in ("actions", "checks", "contents", "pull-requests"):
                    self.assertRegex(text, rf"(?m)^  {re.escape(permission)}: read$")
                self.assertNotRegex(text, r"(?m)^\s+[a-z-]+: write$")
                self.assertIn("fetch-depth: 0", text)
                self.assertIn("persist-credentials: false", text)
                self.assertIn("workflow_dispatch:", text)
                self.assertIn("actions/upload-artifact", text)

                cron = re.search(r"cron: ['\"](\d+) ", text)
                self.assertIsNotNone(cron)
                self.assertNotEqual(int(cron.group(1)), 0)

    def test_official_actions_are_immutably_pinned(self) -> None:
        pattern = re.compile(r"uses:\s+(actions/[^@\s]+)@([^\s#]+)")
        for path in (SELF_WORKFLOW, CONSUMER_WORKFLOW):
            with self.subTest(path=path):
                references = pattern.findall(path.read_text(encoding="utf-8"))
                self.assertGreaterEqual(len(references), 3)
                for action, revision in references:
                    self.assertRegex(
                        revision,
                        r"^[0-9a-f]{40}$",
                        msg=f"{action} must use an immutable full commit SHA",
                    )

    def test_repository_configs_match_the_engine_schema(self) -> None:
        for path in (SELF_CONFIG, CONSUMER_CONFIG):
            with self.subTest(path=path):
                config = load_config(path)
                self.assertEqual(config["standard"]["version"], "0.1.0-draft")
                self.assertEqual(config["repository"]["methodology"], "Unclassified")
                self.assertEqual(config["repository"]["observed_methodology"], "Unclassified")
                self.assertEqual(len(config["methodology_axes"]), 9)

    def test_consumer_workflow_requires_an_immutable_central_action_ref(self) -> None:
        text = CONSUMER_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("@REPLACE_WITH_FULL_COMMIT_SHA", text)
        self.assertIn("enterprise policy explicitly accepts mutable action refs", text)


if __name__ == "__main__":
    unittest.main()

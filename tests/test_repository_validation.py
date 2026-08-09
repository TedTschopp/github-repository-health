from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-validation.yml"


class RepositoryValidationWorkflowTests(unittest.TestCase):
    def test_validation_workflow_has_stable_identity_and_required_triggers(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Repository validation", text)
        self.assertIn("name: Validate repository", text)
        for trigger in ("pull_request:", "merge_group:", "push:", "workflow_dispatch:"):
            self.assertIn(trigger, text)
        self.assertRegex(text, r"(?m)^\s+- main$")

    def test_validation_workflow_is_read_only_and_uses_immutable_actions(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        permissions = text.split("permissions:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(permissions.strip(), "contents: read")
        uses = re.findall(r"(?m)^\s+uses:\s+([^\s#]+)", text)
        self.assertGreaterEqual(len(uses), 2)
        for reference in uses:
            self.assertRegex(reference, r"^[^@\s]+@[0-9a-f]{40}$")

    def test_validation_workflow_exercises_tests_whitespace_and_reports(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests -v", text)
        self.assertIn("git diff --check HEAD", text)
        self.assertIn("python3 -m automation.repository_health assess", text)
        self.assertIn("python3 -m automation.repository_health.reporting", text)

    def test_relative_markdown_links_resolve(self) -> None:
        missing: list[str] = []
        link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        for document in sorted(ROOT.rglob("*.md")):
            if ".git" in document.parts:
                continue
            for raw_target in link_pattern.findall(document.read_text(encoding="utf-8")):
                target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                relative = unquote(target.split("#", 1)[0])
                if not relative:
                    continue
                resolved = (document.parent / relative).resolve()
                if not resolved.exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {target}")
        self.assertEqual(missing, [], "Broken local Markdown links:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()

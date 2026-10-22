"""Regression checks for the reusable and scheduled GitHub Actions package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import re
import subprocess
import tempfile
import textwrap
import unittest

from automation.repository_health.configuration import load_config


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "repository-health" / "action.yml"
SELF_WORKFLOW = ROOT / ".github" / "workflows" / "repository-health.yml"
CONSUMER_WORKFLOW = ROOT / "examples" / "workflows" / "repository-health.yml"
SELF_CONFIG = ROOT / ".github" / "repository-health.toml"
CONSUMER_CONFIG = ROOT / "examples" / "config" / "repository-health.toml"


def _job_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"Workflow job was not found: {name}")
    return match.group(0)


def _publisher_payload_validator(workflow: str) -> str:
    publisher = _job_block(workflow, "publish-history")
    match = re.search(
        r'''(?ms)^          if ! python3 -I - "\$candidate" repository-health-assessment\.json <<'PY'\n'''
        r"(?P<code>.*?)"
        r"^          PY$",
        publisher,
    )
    if match is None:
        raise AssertionError("Publisher assessment-payload validator was not found")
    return textwrap.dedent(match.group("code"))


def _canonical_digest(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ActionPackagingTests(unittest.TestCase):
    def test_composite_action_generates_and_publishes_both_reports(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        self.assertIn("using: composite", text)
        self.assertIn("run_action_module automation.repository_health", text)
        self.assertIn("run_action_module automation.repository_health.reporting", text)
        self.assertIn("run_action_module automation.repository_health.history package", text)
        self.assertIn("python3 -I -c", text)
        self.assertNotIn('PYTHONPATH="$action_root', text)
        self.assertIn("leadership-summary.md", text)
        self.assertIn("history-candidate.json", text)
        self.assertIn("HISTORY_SHA256SUMS", text)
        for output in ("assessment-id", "history-candidate", "history-checksums", "snapshot-path"):
            self.assertRegex(text, rf"(?m)^  {re.escape(output)}:$")
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertNotIn("actions/upload-artifact", text)
        self.assertNotRegex(text, r"(?i)fail[-_]below|minimum[-_]score|score[-_]threshold")

    def test_isolated_action_launcher_ignores_consumer_python_shadows(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        match = re.search(
            r"python3 -I -c '\n(?P<code>.*?)\n        ' \"\$action_root\" \"\$module\"",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertTrue(
            all(not line or line.startswith("        ") for line in match.group("code").splitlines()),
            "embedded launcher Python must remain inside the YAML run block",
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            marker = target / "consumer-code-executed"
            (target / "pathlib.py").write_text(
                f"from pathlib import *\nopen({str(marker)!r}, 'w').write('pathlib')\n",
                encoding="utf-8",
            )
            package = target / "automation" / "repository_health"
            package.mkdir(parents=True)
            (package / "__main__.py").write_text(
                f"open({str(marker)!r}, 'w').write('package')\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(target)
            result = subprocess.run(
                [
                    "python3",
                    "-I",
                    "-c",
                    textwrap.dedent(match.group("code")),
                    str(ROOT),
                    "automation.repository_health",
                    "--help",
                ],
                cwd=target,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(marker.exists(), "consumer repository Python was imported")

    def test_consumer_workflow_remains_read_only_and_uses_full_history(self) -> None:
        text = CONSUMER_WORKFLOW.read_text(encoding="utf-8")
        for permission in (
            "actions",
            "attestations",
            "checks",
            "contents",
            "deployments",
            "pull-requests",
            "security-events",
            "statuses",
        ):
            self.assertRegex(text, rf"(?m)^  {re.escape(permission)}: read$")
        self.assertNotRegex(text, r"(?m)^\s+[a-z-]+: write$")
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("actions/upload-artifact", text)

    def test_self_workflow_separates_read_only_assessment_from_privileged_history(self) -> None:
        text = SELF_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^permissions: \{\}$")
        assess = _job_block(text, "assess")
        publisher = _job_block(text, "publish-history")

        for permission in (
            "actions",
            "attestations",
            "checks",
            "contents",
            "deployments",
            "pull-requests",
            "security-events",
            "statuses",
        ):
            self.assertRegex(assess, rf"(?m)^      {re.escape(permission)}: read$")
        self.assertNotRegex(assess, r"(?m)^\s+[a-z-]+: write$")
        self.assertIn("fetch-depth: 0", assess)
        self.assertIn("persist-credentials: false", assess)
        self.assertIn("uses: ./.github/actions/repository-health", assess)
        self.assertIn("retention-days: 90", assess)

        self.assertRegex(publisher, r"(?m)^    permissions:\n      contents: write$")
        self.assertIn("github.ref == 'refs/heads/main'", publisher)
        self.assertEqual(len(re.findall(r"(?m)^      [a-z-]+: write$", publisher)), 1)
        self.assertNotIn("actions/checkout@", publisher)
        self.assertNotIn("actions/setup-python@", publisher)
        self.assertIn('python3 -I - "$candidate"', publisher)
        self.assertNotIn("python3 -m", publisher)
        self.assertNotIn("uses: ./.github/", publisher)
        self.assertIn("actions/download-artifact@", publisher)
        self.assertIn("sha256sum --check --strict", publisher)
        self.assertIn("read_only_collection == true", publisher)
        self.assertIn("assessed_repository_build_code_executed == false", publisher)
        self.assertNotIn("repository_owned_code_executed", publisher)
        self.assertIn("assessment_payload_sha256", publisher)
        self.assertIn("canonical_bytes", publisher)
        self.assertIn("repository-health-evidence", publisher)
        self.assertIn("evidence/snapshots/", publisher)
        self.assertIn("evidence/latest.json", publisher)
        self.assertIn("gh api", publisher)
        self.assertIn("force: false", publisher)
        self.assertIn("grep -Fxc", publisher)
        self.assertNotRegex(publisher, r"(?i)fail[-_]below|minimum[-_]score|score[-_]threshold")

    def test_publisher_payload_validator_is_exact_and_fail_closed(self) -> None:
        validator = _publisher_payload_validator(SELF_WORKFLOW.read_text(encoding="utf-8"))
        assessment = {
            "automation": {
                "assessed_repository_build_code_executed": False,
                "read_only_collection": True,
            },
            "large": 1e20,
            "small": 1e-7,
            "standard_version": "0.1.0-draft",
        }

        def candidate_for(embedded: object, digest_source: object | None = None) -> dict[str, object]:
            return {
                "assessment": embedded,
                "assessment_payload_sha256": _canonical_digest(
                    embedded if digest_source is None else digest_source
                ),
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "history-candidate.json"
            assessment_path = root / "repository-health-assessment.json"
            marker = root / "consumer-pathlib-imported"
            (root / "pathlib.py").write_text(
                f"open({str(marker)!r}, 'w').write('imported')\n",
                encoding="utf-8",
            )

            def run_case(candidate: object, assessment_text: str) -> subprocess.CompletedProcess[str]:
                candidate_path.write_text(
                    json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                assessment_path.write_text(assessment_text, encoding="utf-8")
                return subprocess.run(
                    ["python3", "-I", "-", str(candidate_path), str(assessment_path)],
                    input=validator,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )

            valid = run_case(
                candidate_for(assessment),
                json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            )
            self.assertEqual(0, valid.returncode, valid.stderr)
            self.assertFalse(marker.exists(), "publisher imported consumer repository Python")

            tampered = json.loads(json.dumps(assessment))
            tampered["standard_version"] = "9.9.9"
            mismatch = run_case(
                candidate_for(tampered),
                json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            )
            self.assertNotEqual(0, mismatch.returncode)
            self.assertIn("differs", mismatch.stderr)

            bogus_digest = candidate_for(assessment)
            bogus_digest["assessment_payload_sha256"] = "f" * 64
            digest_failure = run_case(
                bogus_digest,
                json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            )
            self.assertNotEqual(0, digest_failure.returncode)
            self.assertIn("payload digest", digest_failure.stderr)

            duplicate_key = run_case(
                candidate_for({"score": 1e-7}),
                '{"score":1e-7,"score":1e-7}\n',
            )
            self.assertNotEqual(0, duplicate_key.returncode)
            self.assertIn("duplicate JSON key", duplicate_key.stderr)

            signed_zero = run_case(
                candidate_for({"score": -0.0}, digest_source={"score": 0.0}),
                '{"score":0.0}\n',
            )
            self.assertNotEqual(0, signed_zero.returncode)
            self.assertIn("differs", signed_zero.stderr)

            out_of_range = run_case(
                candidate_for({"score": 0}),
                '{"score":1e400}\n',
            )
            self.assertNotEqual(0, out_of_range.returncode)
            self.assertIn("out-of-range JSON number", out_of_range.stderr)

    def test_schedules_are_manual_and_offset_from_the_hour(self) -> None:
        for path in (SELF_WORKFLOW, CONSUMER_WORKFLOW):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("workflow_dispatch:", text)
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

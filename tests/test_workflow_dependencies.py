"""Completeness tests for the standard-library workflow dependency reader."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from automation.repository_health.workflow_dependencies import collect_workflow_dependencies


PINNED_SHA = "b" * 40


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _gap_kinds(result: dict) -> set[str]:
    return {gap["kind"] for gap in result["gaps"]}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(root: Path, message: str = "Fixture") -> str:
    if not (root / ".git").exists():
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.name", "Workflow Dependency Test")
        _git(root, "config", "user.email", "workflow@example.invalid")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


class WorkflowDependencyCompletenessTests(unittest.TestCase):
    def test_block_scalars_and_local_actions_remain_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                ".github/workflows/build.yml",
                "\n".join(
                    [
                        "name: fixture",
                        "on: [push]",
                        "env: {MODE: test}",
                        "jobs:",
                        "  build:",
                        "    steps:",
                        f"      - uses: actions/checkout@{PINNED_SHA}",
                        "      - uses: ./.github/actions/local",
                        "      - run: |",
                        "          printf '%s\\n' 'uses: hidden/not-a-dependency@v1'",
                        "      - run: echo '${{ toJSON(matrix) }}'",
                        "      - run: echo '{\"uses\":\"still-not-a-dependency\"}'",
                    ]
                ),
            )
            _write(
                root,
                ".github/actions/local/action.yml",
                "\n".join(
                    [
                        "name: local",
                        "runs:",
                        "  using: composite",
                        "  steps:",
                        "    - uses: 'octo/nested@v2' # supported quoted scalar",
                        "    - run: >-",
                        "        echo 'uses: also/not-a-dependency@v1'",
                    ]
                ),
            )
            subject_sha = _commit(root)

            result = collect_workflow_dependencies(
                root,
                subject_sha=subject_sha,
                observed_at="2026-08-09T22:00:00Z",
            )

        self.assertTrue(result["complete"])
        self.assertTrue(result["population_complete"])
        self.assertEqual("observed", result["state"])
        self.assertEqual("complete", result["completeness"])
        self.assertEqual([], result["gaps"])
        self.assertEqual(
            {f"actions/checkout@{PINNED_SHA}", "./.github/actions/local", "octo/nested@v2"},
            {item["raw"] for item in result["observations"]},
        )
        local = next(item for item in result["observations"] if item["kind"] == "local")
        self.assertEqual(".github/actions/local/action.yml", local["local_target"])
        self.assertEqual(
            [".github/actions/local/action.yml", ".github/workflows/build.yml"],
            result["files_scanned"],
        )

    def test_flow_style_dependencies_are_explicit_population_gaps(self) -> None:
        fixtures = {
            "flow-mapping": (
                "  reusable: {uses: octo/shared/.github/workflows/build.yml@v1}\n"
            ),
            "flow-sequence": (
                "  build:\n"
                "    steps: [{uses: actions/checkout@v4}]\n"
            ),
            "multiline-flow": (
                "  reusable: {\n"
                "    uses: octo/shared/.github/workflows/build.yml@v1\n"
                "  }\n"
            ),
        }
        for label, hidden in fixtures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write(
                    root,
                    ".github/workflows/flow.yml",
                    f"jobs:\n  visible:\n    steps:\n      - uses: actions/setup-python@v5\n{hidden}",
                )
                subject_sha = _commit(root)

                result = collect_workflow_dependencies(root, subject_sha=subject_sha)

                self.assertFalse(result["complete"])
                self.assertFalse(result["population_complete"])
                self.assertEqual("unknown", result["state"])
                self.assertEqual("partial", result["completeness"])
                self.assertIn("unsupported_yaml_flow_dependency", _gap_kinds(result))
                self.assertEqual(
                    ["actions/setup-python@v5"],
                    [item["raw"] for item in result["observations"]],
                )

    def test_anchor_alias_and_merge_key_cannot_claim_complete_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                ".github/workflows/anchors.yml",
                "\n".join(
                    [
                        "x-checkout: &checkout",
                        f"  uses: actions/checkout@{PINNED_SHA}",
                        "x-action: &action actions/setup-python@v5",
                        "jobs:",
                        "  build:",
                        "    steps:",
                        "      - *checkout",
                        "      - <<: *checkout",
                        "      - uses: *action",
                    ]
                ),
            )
            subject_sha = _commit(root)

            result = collect_workflow_dependencies(root, subject_sha=subject_sha)

        self.assertFalse(result["population_complete"])
        self.assertEqual("unknown", result["state"])
        self.assertEqual("partial", result["completeness"])
        kinds = _gap_kinds(result)
        self.assertTrue(
            {
                "unsupported_yaml_anchor",
                "unsupported_yaml_alias",
                "unsupported_yaml_merge_key",
                "unsupported_yaml_uses_scalar",
            }.issubset(kinds)
        )
        unsupported = next(item for item in result["observations"] if item["raw"] == "*action")
        self.assertEqual("unsupported", unsupported["kind"])
        self.assertEqual("unknown", unsupported["completeness"])

    def test_custom_tags_and_quoted_uses_keys_are_explicit_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                ".github/workflows/tagged.yml",
                "\n".join(
                    [
                        "x-steps: !include shared-steps.yml",
                        "jobs:",
                        "  build:",
                        "    steps:",
                        "      - uses: !action actions/checkout@v4",
                        "      - \"uses\": actions/setup-python@v5",
                        "      - uses: octo/visible@v1",
                    ]
                ),
            )
            subject_sha = _commit(root)

            result = collect_workflow_dependencies(root, subject_sha=subject_sha)

        self.assertFalse(result["complete"])
        self.assertEqual("unknown", result["state"])
        self.assertEqual("partial", result["completeness"])
        kinds = _gap_kinds(result)
        self.assertIn("unsupported_yaml_custom_tag", kinds)
        self.assertIn("unsupported_yaml_quoted_uses_key", kinds)
        self.assertIn("unsupported_yaml_uses_scalar", kinds)
        self.assertEqual(
            {"!action actions/checkout@v4", "octo/visible@v1"},
            {item["raw"] for item in result["observations"]},
        )

    def test_dynamic_block_uses_keeps_existing_unknown_observation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                ".github/workflows/dynamic.yml",
                "jobs:\n  build:\n    steps:\n      - uses: ${{ matrix.action }}\n",
            )
            subject_sha = _commit(root)
            result = collect_workflow_dependencies(root, subject_sha=subject_sha)

        self.assertEqual("dynamic", result["observations"][0]["kind"])
        self.assertEqual("unknown", result["observations"][0]["completeness"])
        self.assertIn("unresolved_dependency", _gap_kinds(result))
        self.assertEqual("partial", result["completeness"])

    def test_dirty_worktree_cannot_change_exact_revision_dependency_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = _write(
                root,
                ".github/workflows/build.yml",
                "steps:\n  - uses: actions/checkout@main\n  - uses: ./.github/actions/local\n",
            )
            local = _write(
                root,
                ".github/actions/local/action.yml",
                "runs:\n  using: composite\n  steps:\n    - uses: octo/original@v1\n",
            )
            main_sha = _commit(root, "Main workflow")
            workflow.write_text(
                f"steps:\n  - uses: actions/checkout@{PINNED_SHA}\n",
                encoding="utf-8",
            )
            local.write_text(
                "runs:\n  using: composite\n  steps:\n    - uses: octo/dirty@v9\n",
                encoding="utf-8",
            )

            result = collect_workflow_dependencies(root, subject_sha=main_sha)

        observed = {item["raw"] for item in result["observations"]}
        self.assertTrue(result["complete"])
        self.assertEqual("exact_git_revision", result["binding"])
        self.assertEqual(
            {"actions/checkout@main", "./.github/actions/local", "octo/original@v1"},
            observed,
        )
        self.assertNotIn(f"actions/checkout@{PINNED_SHA}", observed)
        checkout = next(
            item for item in result["observations"] if item["raw"] == "actions/checkout@main"
        )
        self.assertFalse(checkout["immutable"])
        self.assertEqual(main_sha, checkout["subject_sha"])

    def test_feature_branch_cannot_change_exact_main_dependency_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = _write(
                root,
                ".github/workflows/build.yml",
                f"steps:\n  - uses: actions/checkout@{PINNED_SHA}\n",
            )
            main_sha = _commit(root, "Main workflow")
            _git(root, "checkout", "-b", "feature")
            workflow.write_text(
                "steps:\n  - uses: actions/checkout@feature-tip\n",
                encoding="utf-8",
            )
            feature_sha = _commit(root, "Feature workflow")

            result = collect_workflow_dependencies(root, subject_sha=main_sha)

        self.assertNotEqual(main_sha, feature_sha)
        self.assertTrue(result["complete"])
        self.assertEqual(
            [f"actions/checkout@{PINNED_SHA}"],
            [item["raw"] for item in result["observations"]],
        )
        self.assertEqual(main_sha, result["subject_sha"])

    def test_missing_or_unsupported_exact_git_objects_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                ".github/workflows/build.yml",
                "steps:\n  - uses: actions/checkout@main\n",
            )
            _commit(root)
            missing = collect_workflow_dependencies(root, subject_sha="f" * 40)

            workflow = root / ".github" / "workflows" / "linked.yml"
            workflow.symlink_to("build.yml")
            symlink_sha = _commit(root, "Add unsupported workflow symlink")
            unsupported = collect_workflow_dependencies(root, subject_sha=symlink_sha)

        self.assertEqual("unknown", missing["state"])
        self.assertEqual([], missing["observations"])
        self.assertIn("git_revision_unavailable", _gap_kinds(missing))
        self.assertEqual("unknown", unsupported["state"])
        self.assertIn("unsupported_git_object", _gap_kinds(unsupported))


if __name__ == "__main__":
    unittest.main()

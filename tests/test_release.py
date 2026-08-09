from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from automation.repository_health.release import BUILDER_VERSION, build_release


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def tagged_clone(parent: str, *tags: str) -> Path:
    clone = Path(parent) / "repository"
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", "--no-tags", str(ROOT), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    for tag in tags:
        subprocess.run(
            ["git", "-C", str(clone), "tag", tag, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    return clone


class ReleaseBuilderTests(unittest.TestCase):
    def test_release_build_is_repeatable_and_revision_bound(self) -> None:
        with (
            tempfile.TemporaryDirectory() as checkout,
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            repository = tagged_clone(checkout, "v0.1.0-draft")
            left = build_release(
                repository=repository,
                revision="HEAD",
                tag="v0.1.0-draft",
                source_repository="https://github.com/TedTschopp/github-repository-health",
                output_directory=first,
            )
            right = build_release(
                repository=repository,
                revision="HEAD",
                tag="v0.1.0-draft",
                source_repository="https://github.com/TedTschopp/github-repository-health",
                output_directory=second,
            )
            for key in ("archive", "sbom", "identity", "checksums"):
                left_bytes = Path(left[key]).read_bytes()
                right_bytes = Path(right[key]).read_bytes()
                self.assertEqual(hashlib.sha256(left_bytes).hexdigest(), hashlib.sha256(right_bytes).hexdigest())

            identity = json.loads(Path(left["identity"]).read_text(encoding="utf-8"))
            self.assertRegex(identity["source_sha"], r"^[0-9a-f]{40}$")
            self.assertEqual(identity["source_sha"], left["source_sha"])
            self.assertEqual(identity["source_ref"], "refs/tags/v0.1.0-draft")
            self.assertEqual(identity["production_correspondence"], "Releasable-Main")
            self.assertEqual(identity["builder"]["builder_version"], BUILDER_VERSION)
            self.assertIn("git version", identity["builder"]["git_version"])
            self.assertEqual(identity["standard_version"], "0.1.0-draft")
            self.assertGreater(identity["file_count"], 0)

    def test_spdx_describes_every_tracked_file_at_revision(self) -> None:
        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as directory:
            repository = tagged_clone(checkout, "v0.1.0-draft")
            result = build_release(
                repository=repository,
                revision="HEAD",
                tag="v0.1.0-draft",
                source_repository="https://github.com/TedTschopp/github-repository-health",
                output_directory=directory,
            )
            sbom = json.loads(Path(result["sbom"]).read_text(encoding="utf-8"))
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertEqual(len(sbom["files"]), result["file_count"])
            self.assertTrue(all(len(item["checksums"]) == 2 for item in sbom["files"]))

    def test_invalid_release_tags_fail_closed(self) -> None:
        invalid_tags = (
            "latest",
            "v01.2.3",
            "v1.2.3-alpha..1",
            "v1.2.3-alpha.",
            "v1.2.3-01",
        )
        with tempfile.TemporaryDirectory() as directory:
            for tag in invalid_tags:
                with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "immutable version format"):
                    build_release(
                        repository=ROOT,
                        revision="HEAD",
                        tag=tag,
                        source_repository="https://github.com/TedTschopp/github-repository-health",
                        output_directory=directory,
                    )

    def test_release_tag_must_exist_and_bind_the_exact_revision(self) -> None:
        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as directory:
            repository = tagged_clone(checkout, "v0.1.0-draft")
            with self.assertRaisesRegex(ValueError, "not release revision"):
                build_release(
                    repository=repository,
                    revision="HEAD^",
                    tag="v0.1.0-draft",
                    source_repository="https://github.com/TedTschopp/github-repository-health",
                    output_directory=directory,
                )

        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as directory:
            repository = tagged_clone(checkout)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                build_release(
                    repository=repository,
                    revision="HEAD",
                    tag="v0.1.0-draft",
                    source_repository="https://github.com/TedTschopp/github-repository-health",
                    output_directory=directory,
                )

    def test_release_tag_must_match_the_controlled_standard_version(self) -> None:
        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as directory:
            repository = tagged_clone(checkout, "v9.9.9")
            with self.assertRaisesRegex(ValueError, "controlled standard version"):
                build_release(
                    repository=repository,
                    revision="HEAD",
                    tag="v9.9.9",
                    source_repository="https://github.com/TedTschopp/github-repository-health",
                    output_directory=directory,
                )


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_uses_revision_validation_attestation_and_release(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tags:\n      - 'v*'", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("release_tag:", text)
        self.assertIn("RELEASE_TAG:", text)
        self.assertIn("git merge-base --is-ancestor", text)
        self.assertIn('name == \"Validate repository\"', text)
        self.assertIn("python3 -m automation.repository_health.release", text)
        self.assertIn("actions/attest@", text)
        self.assertIn("sbom-path:", text)
        self.assertIn("gh release create", text)
        self.assertIn('gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY"', text)
        self.assertEqual(text.count('--repo "$GITHUB_REPOSITORY"'), 2)
        self.assertIn("--verify-tag", text)
        self.assertIn("refusing to replace it", text)
        self.assertIn("release-evidence-${{ github.run_id }}-${{ github.run_attempt }}", text)
        self.assertLess(text.index("Refuse an existing release or draft"), text.index("Attest source package and SBOM"))
        self.assertEqual(text.count("cd release-dist\n            sha256sum -c SHA256SUMS"), 2)

    def test_release_workflow_has_narrow_explicit_permissions(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("permissions: {}", text)
        build = text.split("  build:\n", 1)[1].split("\n  publish:\n", 1)[0]
        publish = text.split("\n  publish:\n", 1)[1]
        self.assertIn("      checks: read", build)
        self.assertIn("      contents: read", build)
        self.assertNotRegex(build, r"(?m)^\s+[a-z-]+: write$")
        self.assertIn("      attestations: write", publish)
        self.assertIn("      contents: write", publish)
        self.assertIn("      id-token: write", publish)
        self.assertNotIn("actions/checkout@", publish)
        self.assertNotIn("actions/setup-python@", publish)
        self.assertNotIn("python3 -m automation", publish)

    def test_release_workflow_actions_are_immutably_pinned(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        references = re.findall(r"(?m)^\s+uses:\s+([^\s#]+)", text)
        self.assertEqual(len(references), 5)
        for reference in references:
            self.assertRegex(reference, r"^[^@\s]+@[0-9a-f]{40}$")

    def test_release_workflow_pins_build_runner_and_python_patch(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(text.count("runs-on: ubuntu-24.04"), 2)
        self.assertIn("python-version: '3.12.13'", text)


if __name__ == "__main__":
    unittest.main()

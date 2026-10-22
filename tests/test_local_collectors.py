"""Safety regressions for read-only local repository collection."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from automation.repository_health.collectors import collect_local, read_git_text


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


class LocalCollectorSafetyTests(unittest.TestCase):
    def test_repository_configured_fsmonitor_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git(root, "init", "-b", "main")
            _git(root, "config", "user.name", "Repository Health Test")
            _git(root, "config", "user.email", "health@example.invalid")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            _git(root, "add", "README.md")
            _git(root, "commit", "-m", "fixture")

            marker = root / "fsmonitor-executed"
            wrapper = root / "fsmonitor-wrapper"
            wrapper.write_text(
                f"#!/bin/sh\nprintf executed > {str(marker)!r}\nexit 0\n",
                encoding="utf-8",
            )
            wrapper.chmod(wrapper.stat().st_mode | 0o111)
            _git(root, "config", "core.fsmonitor", str(wrapper))

            facts = collect_local(root, "main")

            self.assertTrue(facts["is_git_repository"])
            self.assertFalse(marker.exists(), "repository-configured fsmonitor executed")

    def test_inherited_git_config_and_path_injection_are_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git(root, "init", "-b", "main")
            _git(root, "config", "user.name", "Repository Health Test")
            _git(root, "config", "user.email", "health@example.invalid")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            _git(root, "add", "README.md")
            _git(root, "commit", "-m", "fixture")

            fake_bin = root / "consumer-bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            marker = root / "consumer-git-executed"
            fake_git.write_text(
                f"#!/bin/sh\nprintf executed > {str(marker)!r}\nexec /usr/bin/git \"$@\"\n",
                encoding="utf-8",
            )
            fake_git.chmod(fake_git.stat().st_mode | 0o111)

            # Git rejects this command-scope configuration before running any
            # subcommand. Collection can succeed only if inherited GIT_CONFIG_*
            # variables are absent from the deliberately minimal child environment.
            injected_environment = {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "",
                "GIT_CONFIG_VALUE_0": "consumer-controlled",
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            with patch.dict(os.environ, injected_environment, clear=False):
                facts = collect_local(root, "main")
                blob_ok, blob = read_git_text(root, facts["head_sha"], "README.md")

            self.assertTrue(facts["is_git_repository"])
            self.assertEqual(facts["head_sha"], facts["main_sha"])
            self.assertEqual(1, facts["commit_count"])
            self.assertTrue(blob_ok)
            self.assertEqual("fixture\n", blob)
            self.assertFalse(marker.exists(), "consumer-controlled git executable ran")


if __name__ == "__main__":
    unittest.main()

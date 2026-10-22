"""Regression tests for exact-Main invalid-duration reconstruction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from automation.repository_health.normalizers import (
    _first_parent_history,
    _main_invalid_duration_population,
)


CHECK = "Validate repository"
NOW = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)


def _git(root: Path, *arguments: str, at: datetime | None = None) -> str:
    environment = dict(os.environ)
    if at is not None:
        timestamp = at.isoformat()
        environment.update({"GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp})
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def _commit(root: Path, name: str, at: datetime) -> str:
    path = root / name
    path.write_text(f"{name}\n", encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-m", f"Add {name}", at=at)
    return _git(root, "rev-parse", "HEAD")


def _success(sha: str, completed_at: datetime) -> dict[tuple[str, str], list[dict]]:
    return {
        (sha, CHECK): [
            {
                "head_sha": sha,
                "name": CHECK,
                "status": "completed",
                "conclusion": "success",
                "completed_at": completed_at.isoformat(),
            }
        ]
    }


class MainInvalidDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _git(self.root, "init", "-b", "main")
        _git(self.root, "config", "user.name", "Repository Health Test")
        _git(self.root, "config", "user.email", "health@example.invalid")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_quiet_main_carries_current_success_as_no_events(self) -> None:
        main_sha = _commit(self.root, "baseline.txt", NOW - timedelta(days=180))
        data, complete, gaps = _main_invalid_duration_population(
            root=self.root,
            main_sha=main_sha,
            observed_at=NOW.isoformat(),
            check_index=_success(main_sha, NOW - timedelta(days=179)),
            authoritative_checks=[CHECK],
            w365_complete=True,
        )

        self.assertTrue(complete)
        self.assertEqual([], gaps)
        self.assertTrue(data["no_events"])
        self.assertEqual(90 * 24 * 60, data["observable_minutes"])

    def test_new_main_revision_is_invalid_until_its_check_completes(self) -> None:
        baseline_sha = _commit(self.root, "baseline.txt", NOW - timedelta(days=120))
        changed_at = NOW - timedelta(days=30)
        changed_sha = _commit(self.root, "change.txt", changed_at)
        checks = _success(baseline_sha, NOW - timedelta(days=119))
        checks.update(_success(changed_sha, changed_at + timedelta(minutes=30)))

        data, complete, gaps = _main_invalid_duration_population(
            root=self.root,
            main_sha=changed_sha,
            observed_at=NOW.isoformat(),
            check_index=checks,
            authoritative_checks=[CHECK],
            w365_complete=True,
        )

        self.assertTrue(complete)
        self.assertEqual([], gaps)
        self.assertFalse(data["no_events"])
        self.assertEqual(30.0, data["invalid_minutes"])
        self.assertEqual(90 * 24 * 60, data["observable_minutes"])
        self.assertEqual(30.0, data["items"][0]["duration_minutes"])

    def test_incomplete_actions_history_is_unknown(self) -> None:
        main_sha = _commit(self.root, "baseline.txt", NOW - timedelta(days=180))
        data, complete, gaps = _main_invalid_duration_population(
            root=self.root,
            main_sha=main_sha,
            observed_at=NOW.isoformat(),
            check_index=_success(main_sha, NOW - timedelta(days=179)),
            authoritative_checks=[CHECK],
            w365_complete=False,
        )

        self.assertFalse(complete)
        self.assertEqual([], data["items"])
        self.assertTrue(any("W365" in gap for gap in gaps))

    def test_first_parent_history_excludes_merged_side_branch_commits(self) -> None:
        root_sha = _commit(self.root, "root.txt", NOW - timedelta(days=10))
        _git(self.root, "checkout", "-b", "feature")
        side_sha = _commit(self.root, "feature.txt", NOW - timedelta(days=8))
        _git(self.root, "checkout", "main")
        main_sha = _commit(self.root, "main.txt", NOW - timedelta(days=7))
        _git(
            self.root,
            "merge",
            "--no-ff",
            "feature",
            "-m",
            "Merge feature",
            at=NOW - timedelta(days=6),
        )
        merge_sha = _git(self.root, "rev-parse", "HEAD")

        rows, complete = _first_parent_history(self.root, merge_sha)
        shas = [row["sha"] for row in rows]

        self.assertTrue(complete)
        self.assertEqual([root_sha, main_sha, merge_sha], shas)
        self.assertNotIn(side_sha, shas)


if __name__ == "__main__":
    unittest.main()

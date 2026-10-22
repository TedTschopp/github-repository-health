"""Focused tests for read-only durable-history ingestion from GitHub."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.repository_health.history import (
    build_latest_pointer,
    build_snapshot_candidate,
    finalize_snapshot,
    merge_snapshot_chain,
)
from automation.repository_health.history_collectors import (
    DEFAULT_MAX_SNAPSHOT_BYTES,
    collect_remote_history,
)


REPOSITORY = "octo/repository-health"
BRANCH = "repository-health-evidence"
BRANCH_SHA = "b" * 40
TREE_SHA = "c" * 40
SOURCE_SHA = "a" * 40
WORKFLOW_SHA = "d" * 40


def _assessment(timestamp: str, run_id: str) -> dict[str, object]:
    compact = timestamp.replace("+00:00", "Z").replace("-", "").replace(":", "")
    assessment_id = f"RHA-{compact}-{SOURCE_SHA[:8]}-run{run_id}"
    return {
        "assessment_id": assessment_id,
        "automation": {
            "read_only_collection": True,
            "assessed_repository_build_code_executed": False,
        },
        "generated_at": timestamp,
        "metric_results": [
            {
                "metric_id": "M-SPI-04",
                "state": "measured",
                "band": "Pass",
                "value": {"all_daily_observations_conform": True},
            }
        ],
        "repository": {
            "assessed_checkout_sha": SOURCE_SHA,
            "head_sha": SOURCE_SHA,
            "identity": REPOSITORY,
            "main_sha": SOURCE_SHA,
        },
        "schema_version": "1.0",
        "standard_version": "0.1.0-draft",
    }


def _provenance(run_id: str) -> dict[str, object]:
    return {
        "event_name": "schedule",
        "repository": REPOSITORY,
        "run_attempt": 1,
        "run_id": run_id,
        "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/1",
        "source_ref": "refs/heads/main",
        "source_sha": SOURCE_SHA,
        "workflow": "Repository health assessment",
        "workflow_ref": f"{REPOSITORY}/.github/workflows/repository-health.yml@refs/heads/main",
        "workflow_sha": WORKFLOW_SHA,
    }


def _candidate(root: Path, timestamp: str, run_id: str) -> dict[str, object]:
    report = root / f"report-{run_id}"
    report.mkdir()
    assessment = _assessment(timestamp, run_id)
    (report / "repository-health-assessment.json").write_text(
        json.dumps(assessment, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report / "health-assessment.md").write_text(f"# Assessment {run_id}\n", encoding="utf-8")
    (report / "leadership-summary.md").write_text(f"# Leadership {run_id}\n", encoding="utf-8")
    (report / "leadership-summary.json").write_text(
        json.dumps({"assessment_id": assessment["assessment_id"], "actions": []}) + "\n",
        encoding="utf-8",
    )
    return build_snapshot_candidate(
        report / "repository-health-assessment.json",
        report,
        _provenance(run_id),
    )


def _history_bytes() -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        history_root = root / "history"
        merge_snapshot_chain(
            history_root,
            _candidate(root, "2026-08-08T20:00:00+00:00", "101"),
        )
        merge_snapshot_chain(
            history_root,
            _candidate(root, "2026-08-09T20:00:00+00:00", "102"),
        )
        return {
            path.relative_to(history_root).as_posix(): path.read_bytes()
            for path in history_root.rglob("*")
            if path.is_file()
        }


def _history_bytes_for_days(count: int) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        start = datetime(2025, 7, 5, 20, 0, tzinfo=timezone.utc)
        previous: bytes | None = None
        result: dict[str, bytes] = {}
        for offset in range(count):
            timestamp = (start + timedelta(days=offset)).isoformat()
            run_id = str(1_000 + offset)
            candidate = _candidate(root, timestamp, run_id)
            snapshot_bytes = finalize_snapshot(candidate, previous)
            result[str(candidate["snapshot_path"])] = snapshot_bytes
            previous = snapshot_bytes
        assert previous is not None
        result["evidence/latest.json"] = build_latest_pointer(previous)
        return result


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _observed(data: object) -> dict[str, object]:
    return {
        "ok": True,
        "state": "observed",
        "status": 200,
        "data": data,
        "error": None,
        "error_kind": None,
        "observed_at": "2026-08-09T21:00:00+00:00",
    }


def _failed(status: int, kind: str = "permission_or_api_gap") -> dict[str, object]:
    return {
        "ok": False,
        "state": "unknown",
        "status": status,
        "data": None,
        "error": f"HTTP {status}",
        "error_kind": kind,
        "observed_at": "2026-08-09T21:00:00+00:00",
    }


class FixtureClient:
    def __init__(self, routes: dict[str, object], *, token: str | None = "fixture-token") -> None:
        self.routes = routes
        self.token = token
        self.requests: list[str] = []

    def get(self, endpoint: str) -> dict[str, object]:
        self.requests.append(endpoint)
        if endpoint not in self.routes:
            raise AssertionError(f"Unexpected fixture endpoint: {endpoint}")
        result = self.routes[endpoint]
        if isinstance(result, BaseException):
            raise result
        if not isinstance(result, dict):
            raise AssertionError(f"Invalid fixture response for {endpoint}")
        return deepcopy(result)

    def paginate(
        self,
        endpoint: str,
        collection_key: str | None = None,
        **_options: object,
    ) -> dict[str, object]:
        self.requests.append(endpoint)
        if endpoint not in self.routes:
            raise AssertionError(f"Unexpected fixture endpoint: {endpoint}")
        result = self.routes[endpoint]
        if isinstance(result, BaseException):
            raise result
        if not isinstance(result, dict):
            raise AssertionError(f"Invalid fixture response for {endpoint}")
        response = deepcopy(result)
        if "items" in response and "population_complete" in response:
            return response
        data = response.get("data")
        if response.get("ok") is True and response.get("state") == "observed" and isinstance(data, list):
            return {
                "state": "observed",
                "completeness": "complete",
                "items": data,
                "pages": [],
                "page_count": 1,
                "item_count": len(data),
                "reported_total_count": None,
                "complete": True,
                "population_complete": True,
                "truncated": False,
                "error": None,
                "gap": None,
                "observed_at": response.get("observed_at"),
            }
        return {
            "state": "unknown",
            "completeness": "unknown",
            "items": [],
            "pages": [],
            "page_count": 1,
            "item_count": 0,
            "reported_total_count": None,
            "complete": False,
            "population_complete": False,
            "truncated": False,
            "error": response.get("error"),
            "gap": response.get("error_kind") or "request_failed",
            "observed_at": response.get("observed_at"),
        }


class RemoteHistoryFixture:
    def __init__(self, history_bytes: dict[str, bytes] | None = None) -> None:
        self.bytes = dict(history_bytes or _history_bytes())
        self.ref_endpoint = f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"
        self.commit_endpoint = f"/repos/{REPOSITORY}/git/commits/{BRANCH_SHA}"
        self.tree_endpoint = f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}?recursive=1"
        self.tree = {
            "sha": TREE_SHA,
            "truncated": False,
            "tree": [],
        }
        directories: set[str] = set()
        for path in self.bytes:
            parts = path.split("/")[:-1]
            for length in range(1, len(parts) + 1):
                directories.add("/".join(parts[:length]))
        for path in sorted(directories):
            self.tree["tree"].append(
                {
                    "path": path,
                    "mode": "040000",
                    "type": "tree",
                    "sha": hashlib.sha1(path.encode("utf-8")).hexdigest(),
                }
            )

        self.routes: dict[str, object] = {
            self.ref_endpoint: _observed(
                {"ref": f"refs/heads/{BRANCH}", "object": {"type": "commit", "sha": BRANCH_SHA}}
            ),
            self.commit_endpoint: _observed({"sha": BRANCH_SHA, "tree": {"sha": TREE_SHA}}),
            self.tree_endpoint: _observed(self.tree),
        }
        for path, data in sorted(self.bytes.items()):
            self._append_blob(path, data)

    def _append_blob(self, path: str, data: bytes) -> None:
        sha = _blob_sha(data)
        self.tree["tree"].append(
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": sha,
                "size": len(data),
            }
        )
        self.routes[f"/repos/{REPOSITORY}/git/blobs/{sha}"] = _observed(
            {
                "sha": sha,
                "size": len(data),
                "encoding": "base64",
                "content": base64.encodebytes(data).decode("ascii"),
            }
        )

    def replace_blob(self, path: str, data: bytes) -> None:
        entry = next(item for item in self.tree["tree"] if item["path"] == path)
        old_endpoint = f"/repos/{REPOSITORY}/git/blobs/{entry['sha']}"
        self.routes.pop(old_endpoint, None)
        self.tree["tree"].remove(entry)
        self.bytes[path] = data
        self._append_blob(path, data)

    def client(self) -> FixtureClient:
        # Refresh the tree route after any in-place fixture mutation.
        self.routes[self.tree_endpoint] = _observed(self.tree)
        return FixtureClient(self.routes)


class RemoteHistoryCollectorTests(unittest.TestCase):
    def test_valid_chain_returns_ordered_snapshots_and_source_metadata(self) -> None:
        fixture = RemoteHistoryFixture()
        client = fixture.client()

        result = collect_remote_history(REPOSITORY, client)

        self.assertTrue(result["complete"])
        self.assertEqual("observed", result["state"])
        self.assertFalse(result["no_history"])
        self.assertTrue(result["segment_complete"])
        self.assertFalse(result["window_complete"])
        self.assertTrue(result["full_chain_complete"])
        self.assertIsNone(result["opaque_predecessor_sha256"])
        self.assertEqual("full_chain", result["validation_scope"])
        self.assertEqual(BRANCH_SHA, result["branch_sha"])
        self.assertEqual(TREE_SHA, result["tree_sha"])
        self.assertEqual(2, result["data"]["snapshot_count"])
        self.assertEqual(
            ["101", "102"],
            [snapshot["provenance"]["run_id"] for snapshot in result["snapshots"]],
        )
        self.assertEqual(
            result["latest"]["snapshot_path"],
            result["snapshots"][-1]["snapshot_path"],
        )
        self.assertTrue(all(endpoint["complete"] for endpoint in result["request"]["endpoints"]))
        self.assertEqual([], result["gaps"])

    def test_missing_branch_is_complete_no_history_not_a_pass(self) -> None:
        endpoint = f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"
        matching_endpoint = f"/repos/{REPOSITORY}/git/matching-refs/heads/{BRANCH}"
        client = FixtureClient(
            {
                endpoint: _failed(404),
                matching_endpoint: _observed([]),
            }
        )

        result = collect_remote_history(REPOSITORY, client)

        self.assertEqual("no_history", result["state"])
        self.assertEqual("complete", result["completeness"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["no_history"])
        self.assertFalse(result["segment_complete"])
        self.assertFalse(result["window_complete"])
        self.assertFalse(result["full_chain_complete"])
        self.assertEqual("no_history", result["validation_scope"])
        self.assertEqual([], result["snapshots"])
        self.assertIsNone(result["latest"])
        self.assertNotIn("status", result)
        self.assertEqual("absent", result["request"]["endpoints"][0]["state"])

    def test_unauthenticated_ref_404_is_unknown_not_no_history(self) -> None:
        endpoint = f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"
        client = FixtureClient({endpoint: _failed(404)}, token=None)

        result = collect_remote_history(REPOSITORY, client)

        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["no_history"])
        self.assertEqual([], result["snapshots"])
        self.assertEqual("unverified_branch_absence", result["gaps"][0]["kind"])
        self.assertEqual([endpoint], client.requests)

    def test_ref_404_with_incomplete_inventory_is_unknown(self) -> None:
        endpoint = f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"
        matching_endpoint = f"/repos/{REPOSITORY}/git/matching-refs/heads/{BRANCH}"
        client = FixtureClient(
            {
                endpoint: _failed(404),
                matching_endpoint: _failed(403),
            }
        )

        result = collect_remote_history(REPOSITORY, client)

        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["no_history"])
        self.assertEqual("permission_or_api_gap", result["gaps"][0]["kind"])
        self.assertFalse(result["request"]["endpoints"][1]["complete"])

    def test_ref_404_conflicting_with_complete_inventory_is_unknown(self) -> None:
        endpoint = f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"
        matching_endpoint = f"/repos/{REPOSITORY}/git/matching-refs/heads/{BRANCH}"
        client = FixtureClient(
            {
                endpoint: _failed(404),
                matching_endpoint: _observed(
                    [
                        {
                            "ref": f"refs/heads/{BRANCH}",
                            "object": {"type": "commit", "sha": "e" * 40},
                        }
                    ]
                ),
            }
        )

        result = collect_remote_history(REPOSITORY, client)

        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["no_history"])
        self.assertEqual("ref_absence_conflict", result["gaps"][0]["kind"])

    def test_permission_or_partial_api_fails_closed_without_snapshots(self) -> None:
        for failure_point in ("branch", "commit", "blob"):
            with self.subTest(failure_point=failure_point):
                fixture = RemoteHistoryFixture()
                if failure_point == "branch":
                    fixture.routes[fixture.ref_endpoint] = _failed(403)
                elif failure_point == "commit":
                    fixture.routes[fixture.commit_endpoint] = _failed(403)
                else:
                    latest = next(
                        item for item in fixture.tree["tree"] if item["path"] == "evidence/latest.json"
                    )
                    fixture.routes[f"/repos/{REPOSITORY}/git/blobs/{latest['sha']}"] = _failed(403)

                result = collect_remote_history(REPOSITORY, fixture.client())

                self.assertEqual("unknown", result["state"])
                self.assertFalse(result["complete"])
                self.assertFalse(result["no_history"])
                self.assertEqual([], result["snapshots"])
                self.assertEqual("permission_or_api_gap", result["gaps"][0]["kind"])

    def test_truncated_or_uncontrolled_tree_fails_closed_before_blob_reads(self) -> None:
        for mode in ("truncated", "unexpected_path"):
            with self.subTest(mode=mode):
                fixture = RemoteHistoryFixture()
                if mode == "truncated":
                    fixture.tree["truncated"] = True
                    expected_kind = "tree_truncated"
                else:
                    fixture.tree["tree"].append(
                        {
                            "path": "README.md",
                            "mode": "100644",
                            "type": "blob",
                            "sha": "e" * 40,
                            "size": 1,
                        }
                    )
                    expected_kind = "unexpected_tree_entry"
                client = fixture.client()

                result = collect_remote_history(REPOSITORY, client)

                self.assertEqual("unknown", result["state"])
                self.assertEqual([], result["snapshots"])
                self.assertEqual(expected_kind, result["gaps"][0]["kind"])
                self.assertFalse(any("/git/blobs/" in request for request in client.requests))

    def test_gap_mutation_malformed_json_and_orphan_are_rejected_offline(self) -> None:
        for mode in ("gap", "latest_mutation", "malformed_json", "orphan"):
            with self.subTest(mode=mode):
                fixture = RemoteHistoryFixture()
                if mode == "gap":
                    first_path = sorted(
                        path for path in fixture.bytes if path.startswith("evidence/snapshots/")
                    )[0]
                    fixture.tree["tree"] = [
                        item for item in fixture.tree["tree"] if item["path"] != first_path
                    ]
                elif mode == "latest_mutation":
                    latest = json.loads(fixture.bytes["evidence/latest.json"])
                    latest["snapshot_sha256"] = "0" * 64
                    fixture.replace_blob(
                        "evidence/latest.json",
                        (json.dumps(latest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                    )
                elif mode == "malformed_json":
                    latest_path = "evidence/latest.json"
                    fixture.replace_blob(latest_path, b"{not-json\n")
                else:
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        orphan = _candidate(root, "2026-08-10T20:00:00+00:00", "103")
                        orphan_bytes = finalize_snapshot(orphan)
                    fixture.bytes[orphan["snapshot_path"]] = orphan_bytes
                    fixture._append_blob(orphan["snapshot_path"], orphan_bytes)

                result = collect_remote_history(REPOSITORY, fixture.client())

                self.assertEqual("unknown", result["state"])
                self.assertEqual([], result["snapshots"])
                self.assertEqual("history_validation_failed", result["gaps"][0]["kind"])

    def test_malformed_base64_and_blob_identity_conflict_fail_closed(self) -> None:
        for mode in ("base64", "identity"):
            with self.subTest(mode=mode):
                fixture = RemoteHistoryFixture()
                latest_entry = next(
                    item for item in fixture.tree["tree"] if item["path"] == "evidence/latest.json"
                )
                endpoint = f"/repos/{REPOSITORY}/git/blobs/{latest_entry['sha']}"
                response = fixture.routes[endpoint]
                assert isinstance(response, dict) and isinstance(response["data"], dict)
                if mode == "base64":
                    content = response["data"]["content"]
                    assert isinstance(content, str)
                    response["data"]["content"] = "%" * len(content.replace("\n", ""))
                    expected_kind = "malformed_blob"
                else:
                    response["data"]["sha"] = "f" * 40
                    expected_kind = "blob_identity_conflict"

                result = collect_remote_history(REPOSITORY, fixture.client())

                self.assertEqual("unknown", result["state"])
                self.assertEqual([], result["snapshots"])
                self.assertEqual(expected_kind, result["gaps"][0]["kind"])

    def test_snapshot_window_cap_downloads_only_newest_linked_segment(self) -> None:
        fixture = RemoteHistoryFixture()
        client = fixture.client()
        count_result = collect_remote_history(REPOSITORY, client, max_snapshots=1)
        self.assertEqual("observed", count_result["state"])
        self.assertTrue(count_result["segment_complete"])
        self.assertFalse(count_result["window_complete"])
        self.assertFalse(count_result["full_chain_complete"])
        self.assertEqual("bounded_newest_segment", count_result["validation_scope"])
        self.assertEqual(2, count_result["data"]["total_snapshot_count"])
        self.assertEqual(1, count_result["data"]["selected_snapshot_count"])
        self.assertRegex(count_result["opaque_predecessor_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            2,
            sum("/git/blobs/" in request for request in client.requests),
        )

    def test_more_than_400_daily_snapshots_returns_complete_newest_window(self) -> None:
        history_bytes = _history_bytes_for_days(401)
        fixture = RemoteHistoryFixture(history_bytes)
        client = fixture.client()

        with patch(
            "automation.repository_health.history_collectors.utc_now",
            return_value="2026-08-09T21:00:00+00:00",
        ):
            result = collect_remote_history(REPOSITORY, client)

        snapshot_paths = sorted(
            path for path in history_bytes if path.startswith("evidence/snapshots/")
        )
        expected_anchor = hashlib.sha256(history_bytes[snapshot_paths[0]]).hexdigest()
        self.assertEqual("observed", result["state"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["segment_complete"])
        self.assertTrue(result["window_complete"])
        self.assertFalse(result["full_chain_complete"])
        self.assertEqual("bounded_newest_segment", result["validation_scope"])
        self.assertEqual(expected_anchor, result["opaque_predecessor_sha256"])
        self.assertEqual(401, result["data"]["total_snapshot_count"])
        self.assertEqual(400, result["data"]["selected_snapshot_count"])
        self.assertEqual("2026-08-09", result["window_reference_date"])
        self.assertEqual([], result["missing_daily_dates"])
        self.assertEqual(0, result["freshness_days"])
        self.assertEqual(snapshot_paths[1], result["snapshots"][0]["snapshot_path"])
        self.assertEqual(snapshot_paths[-1], result["latest"]["snapshot_path"])
        self.assertEqual(
            401,
            sum("/git/blobs/" in request for request in client.requests),
        )

    def test_stale_segment_tip_cannot_complete_current_daily_window(self) -> None:
        history_bytes = _history_bytes_for_days(401)
        fixture = RemoteHistoryFixture(history_bytes)

        with patch(
            "automation.repository_health.history_collectors.utc_now",
            return_value="2026-08-10T00:30:00+00:00",
        ):
            result = collect_remote_history(REPOSITORY, fixture.client())

        self.assertEqual("observed", result["state"])
        self.assertTrue(result["segment_complete"])
        self.assertFalse(result["window_complete"])
        self.assertFalse(result["full_chain_complete"])
        self.assertEqual("2026-08-10", result["window_reference_date"])
        self.assertEqual("2025-08-10", result["window_start_date"])
        self.assertEqual("2026-08-10", result["window_end_date"])
        self.assertIn("2026-08-10", result["missing_daily_dates"])
        self.assertEqual(1, result["freshness_days"])
        self.assertEqual(1, result["data"]["tip_freshness_days"])

    def test_gap_inside_bounded_daily_window_fails_closed(self) -> None:
        history_bytes = _history_bytes_for_days(401)
        snapshot_paths = sorted(
            path for path in history_bytes if path.startswith("evidence/snapshots/")
        )
        history_bytes.pop(snapshot_paths[-100])
        fixture = RemoteHistoryFixture(history_bytes)

        result = collect_remote_history(REPOSITORY, fixture.client())

        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["segment_complete"])
        self.assertFalse(result["window_complete"])
        self.assertFalse(result["full_chain_complete"])
        self.assertEqual("unavailable", result["validation_scope"])
        self.assertEqual([], result["snapshots"])
        self.assertEqual("history_validation_failed", result["gaps"][0]["kind"])

    def test_declared_snapshot_size_cap_stops_downloads(self) -> None:
        fixture = RemoteHistoryFixture()

        snapshot_entry = next(
            item
            for item in fixture.tree["tree"]
            if item["type"] == "blob" and item["path"].startswith("evidence/snapshots/")
        )
        snapshot_entry["size"] = DEFAULT_MAX_SNAPSHOT_BYTES + 1
        client = fixture.client()
        size_result = collect_remote_history(REPOSITORY, client)
        self.assertEqual("unknown", size_result["state"])
        self.assertEqual("blob_size_cap", size_result["gaps"][0]["kind"])
        self.assertFalse(any("/git/blobs/" in request for request in client.requests))

    def test_invalid_arguments_are_rejected_before_api_access(self) -> None:
        client = FixtureClient({})
        with self.assertRaises(ValueError):
            collect_remote_history("not-a-repository", client)
        with self.assertRaises(ValueError):
            collect_remote_history(REPOSITORY, client, branch="../unsafe")
        with self.assertRaises(ValueError):
            collect_remote_history(REPOSITORY, client, max_snapshots=0)
        self.assertEqual([], client.requests)


if __name__ == "__main__":
    unittest.main()

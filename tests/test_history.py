"""Regression tests for immutable repository-health evidence history."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from automation.repository_health.history import (
    HistoryValidationError,
    build_snapshot_candidate,
    finalize_snapshot,
    merge_snapshot_chain,
    read_snapshot_chain,
    sha256_bytes,
    snapshot_relative_path,
    validate_snapshot,
    write_transfer_package,
)


REPOSITORY = "example/repository-health"
SOURCE_SHA = "a" * 40
WORKFLOW_SHA = "b" * 40


def _identity(timestamp: str, run_id: str) -> tuple[str, str]:
    compact = timestamp.replace("+00:00", "Z").replace("-", "").replace(":", "")
    return f"RHA-{compact}-{SOURCE_SHA[:8]}-run{run_id}", timestamp


def _assessment(timestamp: str, run_id: str) -> dict[str, object]:
    assessment_id, generated_at = _identity(timestamp, run_id)
    return {
        "assessment_id": assessment_id,
        "automation": {
            "catalog_sha256": "c" * 64,
            "config_sha256": "d" * 64,
            "read_only_collection": True,
            "assessed_repository_build_code_executed": False,
        },
        "generated_at": generated_at,
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
        "event_name": "workflow_dispatch",
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


def _report_directory(root: Path, timestamp: str, run_id: str) -> Path:
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
    return report


def _candidate(root: Path, timestamp: str, run_id: str) -> dict[str, object]:
    report = _report_directory(root, timestamp, run_id)
    return build_snapshot_candidate(
        report / "repository-health-assessment.json",
        report,
        _provenance(run_id),
    )


def _assessment_payload_digest(assessment: object) -> str:
    canonical = json.dumps(
        assessment,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(canonical)


class HistoryTests(unittest.TestCase):
    def test_transfer_package_records_report_digests_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = _report_directory(root, "2026-08-09T20:00:00+00:00", "101")
            result = write_transfer_package(
                report / "repository-health-assessment.json",
                report,
                report / "history-candidate.json",
                report / "HISTORY_SHA256SUMS",
                _provenance("101"),
            )

            candidate_bytes = (report / "history-candidate.json").read_bytes()
            candidate = json.loads(candidate_bytes)
            self.assertEqual(result["candidate_sha256"], sha256_bytes(candidate_bytes))
            self.assertEqual(candidate["provenance"]["source_sha"], SOURCE_SHA)
            self.assertEqual(candidate["provenance"]["workflow_sha"], WORKFLOW_SHA)
            self.assertEqual(len(candidate["documents"]), 4)
            for document in candidate["documents"]:
                data = (report / document["name"]).read_bytes()
                self.assertEqual(document["sha256"], sha256_bytes(data))
                self.assertEqual(document["size"], len(data))

            manifest_lines = (report / "HISTORY_SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 5)
            self.assertEqual(
                {line.split("  ", 1)[1] for line in manifest_lines},
                {
                    "repository-health-assessment.json",
                    "health-assessment.md",
                    "leadership-summary.md",
                    "leadership-summary.json",
                    "history-candidate.json",
                },
            )

    def test_embedded_assessment_and_payload_digest_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = _candidate(root, "2026-08-09T20:00:00+00:00", "101")

            changed = copy.deepcopy(candidate)
            changed["assessment"]["standard_version"] = "9.9.9"
            with self.assertRaisesRegex(HistoryValidationError, "payload digest"):
                validate_snapshot(changed)

            bogus_digest = copy.deepcopy(candidate)
            bogus_digest["assessment_payload_sha256"] = "f" * 64
            with self.assertRaisesRegex(HistoryValidationError, "payload digest"):
                validate_snapshot(bogus_digest)

    def test_snapshot_requires_narrow_read_only_automation_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = _candidate(
                Path(temporary),
                "2026-08-09T20:00:00+00:00",
                "101",
            )
            cases = (
                ("read-only false", "read_only_collection", False, "read_only_collection"),
                (
                    "build code true",
                    "assessed_repository_build_code_executed",
                    True,
                    "assessed_repository_build_code_executed",
                ),
                (
                    "narrow claim missing",
                    "assessed_repository_build_code_executed",
                    None,
                    "assessed_repository_build_code_executed",
                ),
            )
            for name, field, value, expected_error in cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(candidate)
                    automation = changed["assessment"]["automation"]
                    if value is None:
                        automation.pop(field)
                        automation["repository_owned_code_executed"] = False
                    else:
                        automation[field] = value
                    changed["assessment_payload_sha256"] = _assessment_payload_digest(
                        changed["assessment"]
                    )
                    with self.assertRaisesRegex(HistoryValidationError, expected_error):
                        validate_snapshot(changed)

    def test_assessment_json_rejects_duplicate_and_out_of_range_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = _report_directory(root, "2026-08-09T20:00:00+00:00", "101")
            assessment_path = report / "repository-health-assessment.json"
            assessment = _assessment("2026-08-09T20:00:00+00:00", "101")
            base = json.dumps(assessment, sort_keys=True)
            cases = (
                (
                    "duplicate",
                    base[:-1] + ', "standard_version": "0.1.0-draft"}',
                    "duplicate JSON key",
                ),
                ("out-of-range", base[:-1] + ', "overflow": 1e400}', "out-of-range JSON number"),
            )
            for name, payload, expected_error in cases:
                with self.subTest(name=name):
                    assessment_path.write_text(payload, encoding="utf-8")
                    with self.assertRaisesRegex(HistoryValidationError, expected_error):
                        build_snapshot_candidate(
                            assessment_path,
                            report,
                            _provenance("101"),
                        )

    def test_merge_and_read_two_snapshot_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history_root = root / "history"
            first = _candidate(root, "2026-08-09T20:00:00+00:00", "101")
            first_path = merge_snapshot_chain(history_root, first)
            first_bytes = first_path.read_bytes()
            second = _candidate(root, "2026-08-16T20:00:00+00:00", "102")
            second_path = merge_snapshot_chain(history_root, second)

            chain = read_snapshot_chain(history_root)
            self.assertEqual([item["assessment_id"] for item in chain], [first["assessment_id"], second["assessment_id"]])
            self.assertEqual(chain[-1]["previous_snapshot_sha256"], sha256_bytes(first_bytes))
            latest = json.loads((history_root / "evidence" / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["snapshot_sha256"], sha256_bytes(second_path.read_bytes()))

    def test_hostile_identifier_and_path_traversal_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = _report_directory(root, "2026-08-09T20:00:00+00:00", "101")
            assessment_path = report / "repository-health-assessment.json"
            assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
            assessment["assessment_id"] = "../../repository-health-evidence"
            assessment_path.write_text(json.dumps(assessment), encoding="utf-8")
            with self.assertRaisesRegex(HistoryValidationError, "controlled repository-health identifier"):
                build_snapshot_candidate(assessment_path, report, _provenance("101"))

            candidate = _candidate(root, "2026-08-10T20:00:00+00:00", "102")
            candidate["snapshot_path"] = "../../outside.json"
            with self.assertRaisesRegex(HistoryValidationError, "controlled assessment path"):
                validate_snapshot(candidate)
            with self.assertRaises(HistoryValidationError):
                snapshot_relative_path("../RHA-unsafe", "2026-08-10T20:00:00+00:00")

    def test_duplicate_snapshot_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history_root = root / "history"
            candidate = _candidate(root, "2026-08-09T20:00:00+00:00", "101")
            path = merge_snapshot_chain(history_root, candidate)
            original = path.read_bytes()
            with self.assertRaisesRegex(HistoryValidationError, "already exists"):
                merge_snapshot_chain(history_root, candidate)
            self.assertEqual(path.read_bytes(), original)

    def test_mutation_and_gap_break_hash_chain_validation(self) -> None:
        for mode in ("mutation", "gap"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                history_root = root / "history"
                first = _candidate(root, "2026-08-09T20:00:00+00:00", "101")
                first_path = merge_snapshot_chain(history_root, first)
                second = _candidate(root, "2026-08-16T20:00:00+00:00", "102")
                merge_snapshot_chain(history_root, second)
                if mode == "mutation":
                    changed = json.loads(first_path.read_text(encoding="utf-8"))
                    changed["documents"][0]["sha256"] = "f" * 64
                    first_path.write_text(json.dumps(changed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                else:
                    first_path.unlink()
                with self.assertRaisesRegex(HistoryValidationError, "missing or mutated snapshot"):
                    read_snapshot_chain(history_root)

    def test_conflicting_orphan_snapshot_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history_root = root / "history"
            first = _candidate(root, "2026-08-09T20:00:00+00:00", "101")
            merge_snapshot_chain(history_root, first)
            orphan = _candidate(root, "2026-08-16T20:00:00+00:00", "102")
            orphan_bytes = finalize_snapshot(orphan)
            orphan_path = history_root / orphan["snapshot_path"]
            orphan_path.parent.mkdir(parents=True, exist_ok=True)
            orphan_path.write_bytes(orphan_bytes)
            with self.assertRaisesRegex(HistoryValidationError, "orphaned or conflicting"):
                read_snapshot_chain(history_root)

    def test_partial_malformed_and_unexpected_history_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            (root / "evidence" / "latest.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(HistoryValidationError, "partial"):
                read_snapshot_chain(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_root = root / "source"
            candidate_root.mkdir()
            candidate = _candidate(candidate_root, "2026-08-09T20:00:00+00:00", "101")
            merge_snapshot_chain(root, candidate)
            snapshot = root / candidate["snapshot_path"]
            snapshot.write_text("{not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(HistoryValidationError, "not valid UTF-8 JSON"):
                read_snapshot_chain(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "evidence" / "snapshots").mkdir(parents=True)
            (root / "evidence" / "snapshots" / "not-controlled.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(HistoryValidationError, "unexpected snapshot path"):
                read_snapshot_chain(root)

    def test_snapshot_cannot_link_to_a_different_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = _candidate(root, "2026-08-09T20:00:00+00:00", "101")
            previous_bytes = finalize_snapshot(previous)
            next_candidate = _candidate(root, "2026-08-16T20:00:00+00:00", "102")
            conflicting = copy.deepcopy(next_candidate)
            conflicting["repository"] = "other/repository"
            conflicting["provenance"]["repository"] = "other/repository"
            conflicting["provenance"]["run_url"] = "https://github.com/other/repository/actions/runs/102/attempts/1"
            with self.assertRaisesRegex(HistoryValidationError, "repository conflicts"):
                finalize_snapshot(conflicting, previous_bytes)


if __name__ == "__main__":
    unittest.main()

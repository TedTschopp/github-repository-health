"""Package and validate append-only repository-health evidence history.

This module is deliberately network-free.  GitHub publication is performed by
an isolated workflow job; these helpers create the transfer candidate and let
readers validate the resulting byte-linked snapshot chain locally.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SNAPSHOT_SCHEMA = "repository-health-evidence-snapshot/v1"
LATEST_SCHEMA = "repository-health-evidence-latest/v1"
ASSESSMENT_ID_PATTERN = re.compile(
    r"^RHA-(?P<date>[0-9]{8})T(?P<time>[0-9]{6})Z-(?P<head>[0-9a-f]{8})(?:-run(?P<run>[0-9]+))?$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
EVENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
REPORT_NAMES = (
    "repository-health-assessment.json",
    "health-assessment.md",
    "leadership-summary.md",
    "leadership-summary.json",
)
TRANSFER_NAMES = (*REPORT_NAMES, "history-candidate.json")


class HistoryValidationError(ValueError):
    """Raised when an evidence snapshot or chain is unsafe or inconsistent."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise HistoryValidationError(f"assessment cannot be canonicalized as finite JSON: {error}") from error


def _load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HistoryValidationError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise HistoryValidationError(f"{label} contains non-finite JSON number {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise HistoryValidationError(f"{label} contains an out-of-range JSON number {value}")
        return parsed

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoryValidationError(f"{label} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise HistoryValidationError(f"{label} must be a JSON object")
    return value


def _plain_text(value: Any, field: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise HistoryValidationError(f"{field} must be a non-empty string no longer than {maximum} characters")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise HistoryValidationError(f"{field} must not contain control-line characters")
    return value


def _assessment_identity(assessment: Mapping[str, Any]) -> tuple[str, str, re.Match[str]]:
    assessment_id = _plain_text(assessment.get("assessment_id"), "assessment_id", maximum=160)
    match = ASSESSMENT_ID_PATTERN.fullmatch(assessment_id)
    if match is None:
        raise HistoryValidationError("assessment_id does not match the controlled repository-health identifier format")
    generated_at = _plain_text(assessment.get("generated_at"), "generated_at", maximum=40)
    expected_timestamp = f"{match.group('date')[:4]}-{match.group('date')[4:6]}-{match.group('date')[6:]}T{match.group('time')[:2]}:{match.group('time')[2:4]}:{match.group('time')[4:]}+00:00"
    if generated_at != expected_timestamp:
        raise HistoryValidationError("assessment_id timestamp does not match generated_at")
    try:
        parsed_timestamp = datetime.fromisoformat(generated_at)
    except ValueError as error:
        raise HistoryValidationError("assessment timestamp is not a valid UTC calendar instant") from error
    if parsed_timestamp.tzinfo != timezone.utc:
        raise HistoryValidationError("assessment timestamp must use the explicit +00:00 UTC offset")
    return assessment_id, generated_at, match


def snapshot_relative_path(assessment_id: str, generated_at: str) -> str:
    match = ASSESSMENT_ID_PATTERN.fullmatch(assessment_id)
    if match is None:
        raise HistoryValidationError("assessment_id cannot be used as an evidence path")
    expected_prefix = f"{match.group('date')[:4]}-{match.group('date')[4:6]}-{match.group('date')[6:]}T"
    if not generated_at.startswith(expected_prefix):
        raise HistoryValidationError("assessment_id date does not match generated_at")
    year = match.group("date")[:4]
    month = match.group("date")[4:6]
    return f"evidence/snapshots/{year}/{month}/{assessment_id}.json"


def _safe_target(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise HistoryValidationError(f"unsafe evidence path: {relative_path}")
    target = root.joinpath(*pure.parts).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise HistoryValidationError(f"evidence path escapes the history root: {relative_path}")
    return target


def _validate_provenance(provenance: Any, assessment: Mapping[str, Any], match: re.Match[str]) -> dict[str, Any]:
    if not isinstance(provenance, dict):
        raise HistoryValidationError("provenance must be an object")
    repository = _plain_text(provenance.get("repository"), "provenance.repository", maximum=256)
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise HistoryValidationError("provenance.repository must use GitHub owner/name form")
    for field in ("workflow_sha", "source_sha"):
        value = _plain_text(provenance.get(field), f"provenance.{field}", maximum=40)
        if GIT_SHA_PATTERN.fullmatch(value) is None:
            raise HistoryValidationError(f"provenance.{field} must be an exact lowercase Git commit SHA")
    run_id = _plain_text(provenance.get("run_id"), "provenance.run_id", maximum=32)
    if not run_id.isdigit() or run_id == "0":
        raise HistoryValidationError("provenance.run_id must be a positive integer string")
    run_attempt = provenance.get("run_attempt")
    if not isinstance(run_attempt, int) or isinstance(run_attempt, bool) or run_attempt < 1:
        raise HistoryValidationError("provenance.run_attempt must be a positive integer")
    run_from_id = match.group("run")
    if run_from_id is not None and run_from_id != run_id:
        raise HistoryValidationError("assessment_id run suffix does not match provenance.run_id")
    event_name = _plain_text(provenance.get("event_name"), "provenance.event_name", maximum=80)
    if EVENT_PATTERN.fullmatch(event_name) is None:
        raise HistoryValidationError("provenance.event_name contains unsupported characters")
    for field in ("workflow", "workflow_ref", "source_ref"):
        _plain_text(provenance.get(field), f"provenance.{field}")
    run_url = _plain_text(provenance.get("run_url"), "provenance.run_url", maximum=2048)
    parsed_url = urlparse(run_url)
    expected_suffix = f"/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.path.rstrip("/") != expected_suffix:
        raise HistoryValidationError("provenance.run_url does not identify the declared repository run and attempt")
    repository_record = assessment.get("repository")
    if isinstance(repository_record, dict):
        checkout_sha = repository_record.get("assessed_checkout_sha")
        if checkout_sha and checkout_sha != provenance["source_sha"]:
            raise HistoryValidationError("provenance.source_sha does not match the assessed checkout revision")
        main_sha = repository_record.get("main_sha") or repository_record.get("head_sha")
        if isinstance(main_sha, str) and GIT_SHA_PATTERN.fullmatch(main_sha) and match.group("head") != main_sha[:8]:
            raise HistoryValidationError("assessment_id revision fragment does not match the assessed Main revision")
    return provenance


def _validate_documents(documents: Any) -> list[dict[str, Any]]:
    if not isinstance(documents, list) or len(documents) != len(REPORT_NAMES):
        raise HistoryValidationError("documents must describe exactly the four stable assessment reports")
    names: list[str] = []
    media_types = {
        "repository-health-assessment.json": "application/json",
        "health-assessment.md": "text/markdown",
        "leadership-summary.md": "text/markdown",
        "leadership-summary.json": "application/json",
    }
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise HistoryValidationError(f"documents[{index}] must be an object")
        name = _plain_text(document.get("name"), f"documents[{index}].name", maximum=128)
        if name not in REPORT_NAMES:
            raise HistoryValidationError(f"documents[{index}].name is not a stable report name")
        if document.get("media_type") != media_types[name]:
            raise HistoryValidationError(f"documents[{index}].media_type does not match {name}")
        digest = _plain_text(document.get("sha256"), f"documents[{index}].sha256", maximum=64)
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise HistoryValidationError(f"documents[{index}].sha256 is invalid")
        size = document.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise HistoryValidationError(f"documents[{index}].size must be a positive integer")
        names.append(name)
    if len(names) != len(set(names)) or set(names) != set(REPORT_NAMES):
        raise HistoryValidationError("documents contain duplicate or missing stable report names")
    return documents


def _validate_assessment_automation(assessment: Mapping[str, Any]) -> None:
    automation = assessment.get("automation")
    if not isinstance(automation, dict):
        raise HistoryValidationError("assessment.automation must be an object")
    if automation.get("read_only_collection") is not True:
        raise HistoryValidationError("assessment.automation.read_only_collection must be true")
    if automation.get("assessed_repository_build_code_executed") is not False:
        raise HistoryValidationError(
            "assessment.automation.assessed_repository_build_code_executed must be false"
        )


def validate_snapshot(snapshot: Mapping[str, Any], *, expected_path: str | None = None) -> dict[str, Any]:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise HistoryValidationError(f"unsupported snapshot schema: {snapshot.get('schema_version')!r}")
    assessment = snapshot.get("assessment")
    if not isinstance(assessment, dict):
        raise HistoryValidationError("snapshot assessment must be an object")
    _validate_assessment_automation(assessment)
    assessment_id, generated_at, match = _assessment_identity(assessment)
    if snapshot.get("assessment_id") != assessment_id or snapshot.get("generated_at") != generated_at:
        raise HistoryValidationError("snapshot identity fields do not match the embedded assessment")
    path = snapshot_relative_path(assessment_id, generated_at)
    if snapshot.get("snapshot_path") != path or (expected_path is not None and expected_path != path):
        raise HistoryValidationError("snapshot_path does not match the controlled assessment path")
    payload_digest = snapshot.get("assessment_payload_sha256")
    if not isinstance(payload_digest, str) or payload_digest != sha256_bytes(_canonical_json_bytes(assessment)):
        raise HistoryValidationError("embedded assessment payload digest does not match")
    _validate_documents(snapshot.get("documents"))
    provenance = _validate_provenance(snapshot.get("provenance"), assessment, match)
    if snapshot.get("repository") != provenance["repository"]:
        raise HistoryValidationError("snapshot repository does not match provenance.repository")
    previous = snapshot.get("previous_snapshot_sha256")
    if previous is not None and (not isinstance(previous, str) or SHA256_PATTERN.fullmatch(previous) is None):
        raise HistoryValidationError("previous_snapshot_sha256 must be null or a lowercase SHA-256 digest")
    return dict(snapshot)


def validate_snapshot_bytes(data: bytes, *, expected_path: str | None = None) -> dict[str, Any]:
    return validate_snapshot(_load_json_bytes(data, expected_path or "snapshot"), expected_path=expected_path)


def build_snapshot_candidate(
    assessment_path: str | Path,
    report_directory: str | Path,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    assessment_file = Path(assessment_path).resolve()
    report_root = Path(report_directory).resolve()
    if assessment_file != report_root / "repository-health-assessment.json":
        raise HistoryValidationError("assessment must use the stable report-directory filename")
    assessment_bytes = assessment_file.read_bytes()
    assessment = _load_json_bytes(assessment_bytes, "assessment")
    assessment_id, generated_at, _ = _assessment_identity(assessment)
    documents: list[dict[str, Any]] = []
    media_types = {
        "repository-health-assessment.json": "application/json",
        "health-assessment.md": "text/markdown",
        "leadership-summary.md": "text/markdown",
        "leadership-summary.json": "application/json",
    }
    for name in REPORT_NAMES:
        path = report_root / name
        if not path.is_file() or path.is_symlink():
            raise HistoryValidationError(f"stable report is missing, not regular, or a symlink: {name}")
        data = path.read_bytes()
        if not data:
            raise HistoryValidationError(f"stable report is empty: {name}")
        documents.append(
            {
                "media_type": media_types[name],
                "name": name,
                "sha256": sha256_bytes(data),
                "size": len(data),
            }
        )
    snapshot: dict[str, Any] = {
        "assessment": assessment,
        "assessment_id": assessment_id,
        "assessment_payload_sha256": sha256_bytes(_canonical_json_bytes(assessment)),
        "documents": documents,
        "generated_at": generated_at,
        "previous_snapshot_sha256": None,
        "provenance": dict(provenance),
        "repository": provenance.get("repository"),
        "schema_version": SNAPSHOT_SCHEMA,
        "snapshot_path": snapshot_relative_path(assessment_id, generated_at),
    }
    return validate_snapshot(snapshot)


def finalize_snapshot(candidate: Mapping[str, Any], previous_snapshot_bytes: bytes | None = None) -> bytes:
    snapshot = validate_snapshot(candidate)
    if snapshot.get("previous_snapshot_sha256") is not None:
        raise HistoryValidationError("an unmerged candidate must not predeclare previous_snapshot_sha256")
    if previous_snapshot_bytes is not None:
        previous = validate_snapshot_bytes(previous_snapshot_bytes)
        if previous["repository"] != snapshot["repository"]:
            raise HistoryValidationError("snapshot repository conflicts with the existing chain")
        if previous["assessment_id"] == snapshot["assessment_id"]:
            raise HistoryValidationError("assessment_id already exists in the history chain")
        if previous["generated_at"] >= snapshot["generated_at"]:
            raise HistoryValidationError("new snapshot generated_at must be later than the existing chain tip")
        snapshot["previous_snapshot_sha256"] = sha256_bytes(previous_snapshot_bytes)
    return _json_bytes(snapshot)


def build_latest_pointer(snapshot_bytes: bytes) -> bytes:
    snapshot = validate_snapshot_bytes(snapshot_bytes)
    pointer = {
        "assessment_id": snapshot["assessment_id"],
        "generated_at": snapshot["generated_at"],
        "previous_snapshot_sha256": snapshot["previous_snapshot_sha256"],
        "repository": snapshot["repository"],
        "schema_version": LATEST_SCHEMA,
        "snapshot_path": snapshot["snapshot_path"],
        "snapshot_sha256": sha256_bytes(snapshot_bytes),
    }
    return _json_bytes(pointer)


def _validate_latest_pointer(pointer_bytes: bytes) -> dict[str, Any]:
    pointer = _load_json_bytes(pointer_bytes, "latest pointer")
    if pointer.get("schema_version") != LATEST_SCHEMA:
        raise HistoryValidationError(f"unsupported latest-pointer schema: {pointer.get('schema_version')!r}")
    for field in ("assessment_id", "generated_at", "repository", "snapshot_path"):
        _plain_text(pointer.get(field), f"latest.{field}")
    digest = pointer.get("snapshot_sha256")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise HistoryValidationError("latest.snapshot_sha256 is invalid")
    previous = pointer.get("previous_snapshot_sha256")
    if previous is not None and (not isinstance(previous, str) or SHA256_PATTERN.fullmatch(previous) is None):
        raise HistoryValidationError("latest.previous_snapshot_sha256 is invalid")
    return pointer


def validate_chain(snapshot_files: Sequence[str | Path], latest_pointer_file: str | Path) -> list[dict[str, Any]]:
    if not snapshot_files:
        raise HistoryValidationError("history chain has a latest pointer but no snapshots")
    records: dict[str, tuple[Path, bytes, dict[str, Any]]] = {}
    identities: set[str] = set()
    for raw_path in snapshot_files:
        path = Path(raw_path)
        if not path.is_file() or path.is_symlink():
            raise HistoryValidationError(f"snapshot is missing, not regular, or a symlink: {path}")
        data = path.read_bytes()
        snapshot = validate_snapshot_bytes(data)
        digest = sha256_bytes(data)
        if digest in records:
            raise HistoryValidationError("history contains duplicate snapshot bytes")
        if snapshot["assessment_id"] in identities:
            raise HistoryValidationError("history contains a duplicate assessment_id")
        records[digest] = (path, data, snapshot)
        identities.add(snapshot["assessment_id"])
    latest_path = Path(latest_pointer_file)
    if not latest_path.is_file() or latest_path.is_symlink():
        raise HistoryValidationError("history latest pointer is missing, not regular, or a symlink")
    pointer = _validate_latest_pointer(latest_path.read_bytes())
    current_digest = pointer["snapshot_sha256"]
    ordered_reversed: list[dict[str, Any]] = []
    visited: set[str] = set()
    while current_digest is not None:
        if current_digest in visited:
            raise HistoryValidationError("history chain contains a hash cycle")
        record = records.get(current_digest)
        if record is None:
            raise HistoryValidationError("history chain has a missing or mutated snapshot")
        visited.add(current_digest)
        ordered_reversed.append(record[2])
        current_digest = record[2]["previous_snapshot_sha256"]
    if visited != set(records):
        raise HistoryValidationError("history contains an orphaned or conflicting snapshot")
    ordered = list(reversed(ordered_reversed))
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier["generated_at"] >= later["generated_at"]:
            raise HistoryValidationError("history timestamps are not strictly increasing")
        if earlier["repository"] != later["repository"]:
            raise HistoryValidationError("history repository identity changes within the chain")
    latest = ordered[-1]
    for field in ("assessment_id", "generated_at", "repository", "snapshot_path", "previous_snapshot_sha256"):
        if pointer.get(field) != latest.get(field):
            raise HistoryValidationError(f"latest pointer {field} does not match the chain tip")
    return ordered


def read_snapshot_chain(root: str | Path) -> list[dict[str, Any]]:
    history_root = Path(root).resolve()
    latest = _safe_target(history_root, "evidence/latest.json")
    snapshots_root = _safe_target(history_root, "evidence/snapshots")
    snapshot_files: list[Path] = []
    if snapshots_root.exists():
        if not snapshots_root.is_dir() or snapshots_root.is_symlink():
            raise HistoryValidationError("evidence/snapshots must be a real directory")
        for path in sorted(snapshots_root.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            if not path.is_file() or path.is_symlink():
                raise HistoryValidationError(f"history contains a non-regular snapshot entry: {path}")
            relative = path.relative_to(history_root).as_posix()
            if re.fullmatch(r"evidence/snapshots/[0-9]{4}/[0-9]{2}/RHA-[A-Za-z0-9.-]+\.json", relative) is None:
                raise HistoryValidationError(f"history contains an unexpected snapshot path: {relative}")
            snapshot_files.append(path)
    if not latest.exists() and not snapshot_files:
        return []
    if not latest.exists() or not snapshot_files:
        raise HistoryValidationError("history is partial: latest pointer and snapshots must both exist")
    for path in snapshot_files:
        relative = path.relative_to(history_root).as_posix()
        snapshot = validate_snapshot_bytes(path.read_bytes(), expected_path=relative)
        if snapshot["snapshot_path"] != relative:
            raise HistoryValidationError(f"snapshot is stored at an unexpected path: {relative}")
    return validate_chain(snapshot_files, latest)


def merge_snapshot_chain(root: str | Path, candidate: Mapping[str, Any]) -> Path:
    history_root = Path(root).resolve()
    existing = read_snapshot_chain(history_root)
    previous_bytes: bytes | None = None
    if existing:
        previous_path = _safe_target(history_root, existing[-1]["snapshot_path"])
        previous_bytes = previous_path.read_bytes()
    snapshot_bytes = finalize_snapshot(candidate, previous_bytes)
    snapshot = validate_snapshot_bytes(snapshot_bytes)
    target = _safe_target(history_root, snapshot["snapshot_path"])
    if target.exists():
        raise HistoryValidationError(f"immutable snapshot already exists: {snapshot['snapshot_path']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(snapshot_bytes)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise HistoryValidationError(f"immutable snapshot already exists: {snapshot['snapshot_path']}") from error
    latest = _safe_target(history_root, "evidence/latest.json")
    latest.parent.mkdir(parents=True, exist_ok=True)
    temporary = latest.with_name(f".{latest.name}.{os.getpid()}.tmp")
    temporary.write_bytes(build_latest_pointer(snapshot_bytes))
    temporary.replace(latest)
    read_snapshot_chain(history_root)
    return target


def write_transfer_package(
    assessment_path: str | Path,
    report_directory: str | Path,
    candidate_path: str | Path,
    checksums_path: str | Path,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    report_root = Path(report_directory).resolve()
    candidate_target = Path(candidate_path).resolve()
    checksums_target = Path(checksums_path).resolve()
    if candidate_target != report_root / "history-candidate.json":
        raise HistoryValidationError("history candidate must use the stable report-directory filename")
    if checksums_target != report_root / "HISTORY_SHA256SUMS":
        raise HistoryValidationError("history checksums must use the stable report-directory filename")
    candidate = build_snapshot_candidate(assessment_path, report_root, provenance)
    candidate_target.write_bytes(_json_bytes(candidate))
    lines: list[str] = []
    for name in TRANSFER_NAMES:
        path = report_root / name
        if not path.is_file() or path.is_symlink():
            raise HistoryValidationError(f"transfer file is missing, not regular, or a symlink: {name}")
        lines.append(f"{sha256_bytes(path.read_bytes())}  {name}\n")
    checksums_target.write_text("".join(lines), encoding="utf-8")
    return {
        "assessment_id": candidate["assessment_id"],
        "candidate_path": str(candidate_target),
        "candidate_sha256": sha256_bytes(candidate_target.read_bytes()),
        "checksums_path": str(checksums_target),
        "snapshot_path": candidate["snapshot_path"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-health-history")
    subparsers = parser.add_subparsers(dest="command", required=True)
    package = subparsers.add_parser("package", help="create a checksummed evidence-history transfer candidate")
    package.add_argument("--assessment", required=True)
    package.add_argument("--report-directory", required=True)
    package.add_argument("--candidate", required=True)
    package.add_argument("--checksums", required=True)
    package.add_argument("--repository", required=True)
    package.add_argument("--workflow", required=True)
    package.add_argument("--workflow-ref", required=True)
    package.add_argument("--workflow-sha", required=True)
    package.add_argument("--source-ref", required=True)
    package.add_argument("--source-sha", required=True)
    package.add_argument("--run-id", required=True)
    package.add_argument("--run-attempt", required=True, type=int)
    package.add_argument("--run-url", required=True)
    package.add_argument("--event-name", required=True)
    validate = subparsers.add_parser("validate", help="validate a local evidence branch snapshot chain")
    validate.add_argument("root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "package":
            provenance = {
                "event_name": args.event_name,
                "repository": args.repository,
                "run_attempt": args.run_attempt,
                "run_id": args.run_id,
                "run_url": args.run_url,
                "source_ref": args.source_ref,
                "source_sha": args.source_sha,
                "workflow": args.workflow,
                "workflow_ref": args.workflow_ref,
                "workflow_sha": args.workflow_sha,
            }
            result = write_transfer_package(
                args.assessment,
                args.report_directory,
                args.candidate,
                args.checksums,
                provenance,
            )
        else:
            chain = read_snapshot_chain(args.root)
            result = {
                "count": len(chain),
                "latest_assessment_id": chain[-1]["assessment_id"] if chain else None,
                "valid": True,
            }
    except (HistoryValidationError, OSError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Create and validate bounded repository-health evidence statements.

This module is deliberately independent from the assessment collectors.  It
serializes an outcome supplied by a caller and validates the binding metadata;
it never executes, discovers, or infers the assessed validation, security,
release, or deployment work.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCHEMA_VERSION = "repository-health-evidence-statement/v1"
PRODUCER_NAME = "repository-health-evidence-producer"
PRODUCER_VERSION = "0.1.0"
DEFAULT_MAX_FUTURE_SECONDS = 300
MAX_STATEMENT_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 4096

KINDS = frozenset({"validation", "security", "release", "deployment"})
RESULTS = frozenset({"success", "failure", "unknown"})

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
)
_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_UNIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,255}$")
_OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATEMENT_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "statement_id",
        "repository",
        "unit_id",
        "subject",
        "workflow",
        "observed_at",
        "kind",
        "result",
        "categories",
        "artifact_digests",
        "source_evidence_ids",
        "producer",
    }
)
_SUBJECT_KEYS = frozenset({"ref", "sha", "digests"})
_WORKFLOW_KEYS = frozenset({"ref", "sha", "run_id", "run_attempt"})
_DIGEST_KEYS = frozenset({"name", "algorithm", "value"})
_PRODUCER_KEYS = frozenset(
    {"name", "version", "producer_invoked_assessed_code"}
)


class EvidenceStatementError(ValueError):
    """Raised when evidence cannot be represented without ambiguity."""


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing {', '.join(missing)}")
    if extra:
        details.append(f"unexpected {', '.join(extra)}")
    raise EvidenceStatementError(f"{label} has invalid fields ({'; '.join(details)})")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceStatementError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise EvidenceStatementError(f"{label} keys must be strings")
    return value


def _require_string(value: Any, label: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise EvidenceStatementError(f"{label} must be a non-empty string of at most {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise EvidenceStatementError(f"{label} must not contain control characters")
    return value


def _require_positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvidenceStatementError(f"{label} must be a positive integer")
    return value


def _validate_json_values(value: Any, label: str = "statement") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceStatementError(f"{label} contains a non-finite number")
        raise EvidenceStatementError(f"{label} contains an unsupported floating-point number")
    if isinstance(value, Mapping):
        for key, member in value.items():
            if not isinstance(key, str):
                raise EvidenceStatementError(f"{label} has a non-string object key")
            _validate_json_values(member, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, member in enumerate(value):
            _validate_json_values(member, f"{label}[{index}]")
        return
    raise EvidenceStatementError(f"{label} contains an unsupported value type")


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceStatementError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise EvidenceStatementError(f"non-finite JSON number is not permitted: {value}")


def _load_json_text(text: str, label: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except EvidenceStatementError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise EvidenceStatementError(f"{label} is not valid JSON: {error}") from error
    _validate_json_values(value, label)
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise EvidenceStatementError(f"statement is not canonical JSON: {error}") from error


def _payload_statement_id(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def _normal_timestamp(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = _require_string(value, "observed_at", maximum=64)
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError as error:
            raise EvidenceStatementError("observed_at must be a valid ISO 8601 timestamp") from error
    else:
        raise EvidenceStatementError("observed_at must be an ISO 8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceStatementError("observed_at must include a UTC offset")
    utc = parsed.astimezone(timezone.utc)
    if utc.microsecond:
        rendered = utc.isoformat(timespec="microseconds")
    else:
        rendered = utc.isoformat(timespec="seconds")
    return rendered.replace("+00:00", "Z")


def _aware_now(now: datetime | None) -> datetime:
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceStatementError("now must include a UTC offset")
    return value.astimezone(timezone.utc)


def _validate_timestamp(
    value: Any,
    *,
    now: datetime | None,
    max_future_seconds: int,
) -> str:
    if isinstance(max_future_seconds, bool) or not isinstance(max_future_seconds, int) or max_future_seconds < 0:
        raise EvidenceStatementError("max_future_seconds must be a non-negative integer")
    raw = _require_string(value, "observed_at", maximum=64)
    canonical = _normal_timestamp(raw)
    if canonical != raw:
        raise EvidenceStatementError("observed_at must use canonical UTC ISO 8601 form ending in Z")
    parsed = datetime.fromisoformat(canonical[:-1] + "+00:00")
    if parsed > _aware_now(now) + timedelta(seconds=max_future_seconds):
        raise EvidenceStatementError("observed_at is unreasonably far in the future")
    return canonical


def _validate_repository(value: Any) -> str:
    repository = _require_string(value, "repository", maximum=140)
    if not _REPOSITORY_PATTERN.fullmatch(repository) or repository.endswith("."):
        raise EvidenceStatementError("repository must be an exact GitHub owner/name identifier")
    return repository


def _validate_git_sha(value: Any, label: str) -> str:
    sha = _require_string(value, label, maximum=40)
    if not _SHA_PATTERN.fullmatch(sha):
        raise EvidenceStatementError(f"{label} must be a lowercase 40-character Git SHA")
    return sha


def _validate_ref(value: Any, label: str) -> str:
    ref = _require_string(value, label, maximum=1024)
    if not ref.startswith("refs/") or ".." in ref or ref.endswith("/") or "//" in ref:
        raise EvidenceStatementError(f"{label} must be an unambiguous full refs/... name")
    if any(character in ref for character in (" ", "~", "^", ":", "?", "*", "[", "\\")):
        raise EvidenceStatementError(f"{label} contains characters Git does not permit in a ref")
    return ref


def _validate_workflow_ref(value: Any, repository: str) -> str:
    workflow_ref = _require_string(value, "workflow.ref", maximum=1200)
    prefix = f"{repository}/.github/workflows/"
    if not workflow_ref.startswith(prefix) or "@" not in workflow_ref[len(prefix) :]:
        raise EvidenceStatementError(
            "workflow.ref must name a workflow in the exact repository and include its @ref"
        )
    path, source_ref = workflow_ref[len(repository) + 1 :].rsplit("@", 1)
    if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
        raise EvidenceStatementError("workflow.ref must name a YAML file under .github/workflows")
    workflow_name = path.removeprefix(".github/workflows/")
    if not workflow_name or ".." in workflow_name or "//" in workflow_name or "\\" in workflow_name:
        raise EvidenceStatementError("workflow.ref contains an ambiguous workflow path")
    if source_ref.startswith("refs/"):
        _validate_ref(source_ref, "workflow.ref source ref")
    elif not _SHA_PATTERN.fullmatch(source_ref):
        raise EvidenceStatementError("workflow.ref @ref must be a full refs/... name or exact Git SHA")
    return workflow_ref


def _validate_digest_records(value: Any, label: str, *, required: bool) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise EvidenceStatementError(f"{label} must be an array")
    if required and not value:
        raise EvidenceStatementError(f"{label} must contain at least one SHA-256 digest")
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    for index, member in enumerate(value):
        record = _require_mapping(member, f"{label}[{index}]")
        _require_exact_keys(record, _DIGEST_KEYS, f"{label}[{index}]")
        name = _require_string(record["name"], f"{label}[{index}].name", maximum=128)
        if not _DIGEST_NAME_PATTERN.fullmatch(name) or name in {".", ".."}:
            raise EvidenceStatementError(f"{label}[{index}].name is not a safe logical identifier")
        if name in names:
            raise EvidenceStatementError(f"{label} contains duplicate digest name: {name}")
        names.add(name)
        algorithm = _require_string(record["algorithm"], f"{label}[{index}].algorithm", maximum=16)
        if algorithm != "sha256":
            raise EvidenceStatementError(f"{label}[{index}].algorithm must be sha256")
        digest = _require_string(record["value"], f"{label}[{index}].value", maximum=64)
        if not _SHA256_PATTERN.fullmatch(digest):
            raise EvidenceStatementError(f"{label}[{index}].value must be a lowercase SHA-256 digest")
        normalized.append({"name": name, "algorithm": algorithm, "value": digest})
    expected = sorted(normalized, key=lambda item: item["name"])
    if normalized != expected:
        raise EvidenceStatementError(f"{label} must be sorted by name")
    return normalized


def _normal_digest_records(value: Iterable[Mapping[str, Any]], label: str) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)):
        raise EvidenceStatementError(f"{label} must be an array of digest objects")
    try:
        members = list(value)
    except TypeError as error:
        raise EvidenceStatementError(f"{label} must be an array of digest objects") from error
    materialized: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        record = _require_mapping(member, f"{label}[{index}]")
        materialized.append(dict(record))
    materialized.sort(
        key=lambda member: member.get("name")
        if isinstance(member.get("name"), str)
        else ""
    )
    return _validate_digest_records(materialized, label, required=(label == "subject.digests"))


def _validate_string_set(
    value: Any,
    label: str,
    pattern: re.Pattern[str],
    *,
    maximum: int,
) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvidenceStatementError(f"{label} must be a non-empty array")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, member in enumerate(value):
        item = _require_string(member, f"{label}[{index}]", maximum=maximum)
        if not pattern.fullmatch(item) or item in {".", ".."}:
            raise EvidenceStatementError(f"{label}[{index}] is not a safe identifier")
        if item in seen:
            raise EvidenceStatementError(f"{label} contains a duplicate value: {item}")
        seen.add(item)
        normalized.append(item)
    if normalized != sorted(normalized):
        raise EvidenceStatementError(f"{label} must be sorted")
    return normalized


def _normal_string_set(
    value: Iterable[str],
    label: str,
    pattern: re.Pattern[str],
    *,
    maximum: int,
) -> list[str]:
    if isinstance(value, (str, bytes)):
        raise EvidenceStatementError(f"{label} must be an array")
    try:
        members = list(value)
    except TypeError as error:
        raise EvidenceStatementError(f"{label} must be an array") from error
    normalized: list[str] = []
    seen: set[str] = set()
    for index, member in enumerate(members):
        item = _require_string(member, f"{label}[{index}]", maximum=maximum)
        if not pattern.fullmatch(item) or item in {".", ".."}:
            raise EvidenceStatementError(f"{label}[{index}] is not a safe identifier")
        if item in seen:
            raise EvidenceStatementError(f"{label} contains a duplicate value: {item}")
        seen.add(item)
        normalized.append(item)
    return _validate_string_set(sorted(normalized), label, pattern, maximum=maximum)


def create_evidence_statement(
    *,
    repository: str,
    unit_id: str,
    subject_ref: str,
    subject_sha: str,
    subject_digests: Iterable[Mapping[str, Any]],
    workflow_ref: str,
    workflow_sha: str,
    run_id: int,
    run_attempt: int,
    kind: str,
    result: str,
    categories: Iterable[str],
    artifact_digests: Iterable[Mapping[str, Any]],
    source_evidence_ids: Iterable[str],
    observed_at: str | datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a canonical statement from an explicitly supplied job outcome.

    ``result`` is required and has no inferred default.  Release/deployment
    success also requires at least one artifact digest.
    """

    observed = _normal_timestamp(observed_at if observed_at is not None else _aware_now(now))
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "unit_id": unit_id,
        "subject": {
            "ref": subject_ref,
            "sha": subject_sha,
            "digests": _normal_digest_records(subject_digests, "subject.digests"),
        },
        "workflow": {
            "ref": workflow_ref,
            "sha": workflow_sha,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "observed_at": observed,
        "kind": kind,
        "result": result,
        "categories": _normal_string_set(
            categories, "categories", _CATEGORY_PATTERN, maximum=64
        ),
        "artifact_digests": _normal_digest_records(
            artifact_digests, "artifact_digests"
        ),
        "source_evidence_ids": _normal_string_set(
            source_evidence_ids,
            "source_evidence_ids",
            _SOURCE_ID_PATTERN,
            maximum=256,
        ),
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
            "producer_invoked_assessed_code": False,
        },
    }
    statement = {"statement_id": _payload_statement_id(payload), **payload}
    return validate_evidence_statement(statement, now=now)


def validate_evidence_statement(
    raw_statement: Mapping[str, Any],
    *,
    expected_repository: str | None = None,
    expected_unit_id: str | None = None,
    expected_subject_sha: str | None = None,
    expected_workflow_ref: str | None = None,
    expected_workflow_sha: str | None = None,
    expected_run_id: int | None = None,
    expected_run_attempt: int | None = None,
    now: datetime | None = None,
    max_future_seconds: int = DEFAULT_MAX_FUTURE_SECONDS,
) -> dict[str, Any]:
    """Validate one statement and optional caller-known identity bindings."""

    _validate_json_values(raw_statement)
    statement = dict(_require_mapping(raw_statement, "statement"))
    _require_exact_keys(statement, _TOP_LEVEL_KEYS, "statement")
    if statement["schema_version"] != SCHEMA_VERSION:
        raise EvidenceStatementError(f"unsupported schema_version: {statement['schema_version']!r}")

    statement_id = _require_string(statement["statement_id"], "statement_id", maximum=71)
    if not _STATEMENT_ID_PATTERN.fullmatch(statement_id):
        raise EvidenceStatementError("statement_id must be a sha256: content identifier")

    repository = _validate_repository(statement["repository"])
    unit_id = _require_string(statement["unit_id"], "unit_id", maximum=128)
    if not _UNIT_ID_PATTERN.fullmatch(unit_id) or unit_id in {".", ".."}:
        raise EvidenceStatementError("unit_id must be a safe controlled unit identifier")
    subject = dict(_require_mapping(statement["subject"], "subject"))
    _require_exact_keys(subject, _SUBJECT_KEYS, "subject")
    subject_ref = _validate_ref(subject["ref"], "subject.ref")
    subject_sha = _validate_git_sha(subject["sha"], "subject.sha")
    subject_digests = _validate_digest_records(subject["digests"], "subject.digests", required=True)

    workflow = dict(_require_mapping(statement["workflow"], "workflow"))
    _require_exact_keys(workflow, _WORKFLOW_KEYS, "workflow")
    workflow_ref = _validate_workflow_ref(workflow["ref"], repository)
    workflow_sha = _validate_git_sha(workflow["sha"], "workflow.sha")
    run_id = _require_positive_integer(workflow["run_id"], "workflow.run_id")
    run_attempt = _require_positive_integer(workflow["run_attempt"], "workflow.run_attempt")

    observed_at = _validate_timestamp(
        statement["observed_at"],
        now=now,
        max_future_seconds=max_future_seconds,
    )
    kind = _require_string(statement["kind"], "kind", maximum=16)
    if kind not in KINDS:
        raise EvidenceStatementError(f"kind must be one of: {', '.join(sorted(KINDS))}")
    result = _require_string(statement["result"], "result", maximum=16)
    if result not in RESULTS:
        raise EvidenceStatementError(f"result must be one of: {', '.join(sorted(RESULTS))}")
    categories = _validate_string_set(
        statement["categories"], "categories", _CATEGORY_PATTERN, maximum=64
    )
    artifact_digests = _validate_digest_records(
        statement["artifact_digests"], "artifact_digests", required=False
    )
    source_evidence_ids = _validate_string_set(
        statement["source_evidence_ids"],
        "source_evidence_ids",
        _SOURCE_ID_PATTERN,
        maximum=256,
    )
    if result == "success" and kind in {"release", "deployment"} and not artifact_digests:
        raise EvidenceStatementError(
            f"{kind} success requires at least one artifact_digests entry"
        )

    producer = dict(_require_mapping(statement["producer"], "producer"))
    _require_exact_keys(producer, _PRODUCER_KEYS, "producer")
    if producer != {
        "name": PRODUCER_NAME,
        "version": PRODUCER_VERSION,
        "producer_invoked_assessed_code": False,
    }:
        raise EvidenceStatementError(
            "producer metadata must identify this bounded producer and "
            "producer_invoked_assessed_code=false"
        )

    canonical: dict[str, Any] = {
        "statement_id": statement_id,
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "unit_id": unit_id,
        "subject": {
            "ref": subject_ref,
            "sha": subject_sha,
            "digests": subject_digests,
        },
        "workflow": {
            "ref": workflow_ref,
            "sha": workflow_sha,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "observed_at": observed_at,
        "kind": kind,
        "result": result,
        "categories": categories,
        "artifact_digests": artifact_digests,
        "source_evidence_ids": source_evidence_ids,
        "producer": producer,
    }
    payload = dict(canonical)
    payload.pop("statement_id")
    expected_id = _payload_statement_id(payload)
    if statement_id != expected_id:
        raise EvidenceStatementError("statement_id does not match the canonical statement payload")

    normalized_expected_repository = (
        _validate_repository(expected_repository)
        if expected_repository is not None
        else None
    )
    normalized_expected_unit_id: str | None = None
    if expected_unit_id is not None:
        normalized_expected_unit_id = _require_string(
            expected_unit_id, "expected_unit_id", maximum=128
        )
        if (
            not _UNIT_ID_PATTERN.fullmatch(normalized_expected_unit_id)
            or normalized_expected_unit_id in {".", ".."}
        ):
            raise EvidenceStatementError(
                "expected_unit_id must be a safe controlled unit identifier"
            )
    normalized_expected_subject_sha = (
        _validate_git_sha(expected_subject_sha, "expected_subject_sha")
        if expected_subject_sha is not None
        else None
    )
    normalized_expected_workflow_ref = (
        _validate_workflow_ref(expected_workflow_ref, repository)
        if expected_workflow_ref is not None
        else None
    )
    normalized_expected_workflow_sha = (
        _validate_git_sha(expected_workflow_sha, "expected_workflow_sha")
        if expected_workflow_sha is not None
        else None
    )
    normalized_expected_run_id = (
        _require_positive_integer(expected_run_id, "expected_run_id")
        if expected_run_id is not None
        else None
    )
    normalized_expected_run_attempt = (
        _require_positive_integer(expected_run_attempt, "expected_run_attempt")
        if expected_run_attempt is not None
        else None
    )
    expected_values = (
        ("repository", normalized_expected_repository, repository),
        ("unit_id", normalized_expected_unit_id, unit_id),
        ("subject.sha", normalized_expected_subject_sha, subject_sha),
        ("workflow.ref", normalized_expected_workflow_ref, workflow_ref),
        ("workflow.sha", normalized_expected_workflow_sha, workflow_sha),
        ("workflow.run_id", normalized_expected_run_id, run_id),
        ("workflow.run_attempt", normalized_expected_run_attempt, run_attempt),
    )
    for label, expected, actual in expected_values:
        if expected is not None and expected != actual:
            raise EvidenceStatementError(f"{label} does not match the expected identity")
    return canonical


def validate_evidence_bundle(
    statements: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_future_seconds: int = DEFAULT_MAX_FUTURE_SECONDS,
) -> list[dict[str, Any]]:
    """Validate a set and reject repeated content-addressed statements."""

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, statement in enumerate(statements):
        try:
            item = validate_evidence_statement(
                statement,
                now=now,
                max_future_seconds=max_future_seconds,
            )
        except EvidenceStatementError as error:
            raise EvidenceStatementError(f"statements[{index}]: {error}") from error
        if item["statement_id"] in seen:
            raise EvidenceStatementError(
                f"statements contains duplicate statement_id: {item['statement_id']}"
            )
        seen.add(item["statement_id"])
        validated.append(item)
    return validated


def load_evidence_statement(
    path: str | os.PathLike[str],
    **validation_options: Any,
) -> dict[str, Any]:
    """Load duplicate-safe JSON from disk and validate the statement."""

    source = Path(path)
    try:
        content = source.read_bytes()
    except (OSError, UnicodeError) as error:
        raise EvidenceStatementError(f"could not read evidence statement {source}: {error}") from error
    return _validate_statement_bytes(content, str(source), **validation_options)


def _validate_statement_bytes(
    content: bytes,
    label: str,
    **validation_options: Any,
) -> dict[str, Any]:
    """Validate the exact bytes already obtained at a transfer boundary."""

    if len(content) > MAX_STATEMENT_BYTES:
        raise EvidenceStatementError(
            f"evidence statement exceeds the {MAX_STATEMENT_BYTES}-byte limit"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeError as error:
        raise EvidenceStatementError(f"evidence statement is not UTF-8: {error}") from error
    value = _load_json_text(text, label)
    return validate_evidence_statement(
        _require_mapping(value, "statement"), **validation_options
    )


def _safe_output_path(value: str | os.PathLike[str], label: str) -> Path:
    path = Path(value)
    if not _OUTPUT_NAME_PATTERN.fullmatch(path.name) or path.name in {".", ".."}:
        raise EvidenceStatementError(f"{label} filename is not safe")
    if path.exists() and path.is_symlink():
        raise EvidenceStatementError(f"{label} must not overwrite a symbolic link")
    return path


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def write_evidence_package(
    statement: Mapping[str, Any],
    *,
    output_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    now: datetime | None = None,
) -> dict[str, str]:
    """Write canonical JSON plus a strict single-file SHA-256 manifest."""

    output = _safe_output_path(output_path, "output_path")
    manifest = _safe_output_path(manifest_path, "manifest_path")
    if output.absolute() == manifest.absolute():
        raise EvidenceStatementError("output_path and manifest_path must be different")
    validated = validate_evidence_statement(statement, now=now)
    content = _canonical_bytes(validated)
    digest = hashlib.sha256(content).hexdigest()
    manifest_content = f"{digest}  {output.name}\n".encode("ascii")
    _atomic_write(output, content)
    _atomic_write(manifest, manifest_content)
    return {
        "statement_id": validated["statement_id"],
        "evidence_path": str(output.resolve()),
        "manifest_path": str(manifest.resolve()),
        "sha256": digest,
    }


def verify_evidence_package(
    *,
    input_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    **validation_options: Any,
) -> dict[str, Any]:
    """Verify the manifest and then parse and validate its single statement."""

    source = Path(input_path)
    manifest = Path(manifest_path)
    try:
        content = source.read_bytes()
        manifest_content = manifest.read_bytes()
    except (OSError, UnicodeError) as error:
        raise EvidenceStatementError(f"could not read evidence package: {error}") from error
    if len(content) > MAX_STATEMENT_BYTES:
        raise EvidenceStatementError(
            f"evidence statement exceeds the {MAX_STATEMENT_BYTES}-byte limit"
        )
    if len(manifest_content) > MAX_MANIFEST_BYTES:
        raise EvidenceStatementError("manifest exceeds the size limit")
    try:
        manifest_text = manifest_content.decode("ascii")
    except UnicodeError as error:
        raise EvidenceStatementError(f"manifest is not ASCII: {error}") from error
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]{0,127})\n", manifest_text)
    if match is None:
        raise EvidenceStatementError("manifest must contain one strict SHA-256 entry")
    if match.group(2) != source.name:
        raise EvidenceStatementError("manifest filename does not match the evidence statement")
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(match.group(1), actual):
        raise EvidenceStatementError("manifest SHA-256 does not match the evidence statement")
    # Parse the same bytes whose digest was checked; do not reopen a mutable
    # path between integrity verification and statement validation.
    return _validate_statement_bytes(content, str(source), **validation_options)


def _digest_argument(value: str) -> dict[str, str]:
    name, separator, digest = value.partition("=")
    if not separator:
        raise EvidenceStatementError("digest arguments must use NAME=SHA256")
    return {"name": name, "algorithm": "sha256", "value": digest}


def _array_argument(value: str | None, label: str) -> list[Any]:
    if value is None:
        return []
    parsed = _load_json_text(value, label)
    if not isinstance(parsed, list):
        raise EvidenceStatementError(f"{label} must be a JSON array")
    return parsed


def _integer_argument(value: str, label: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise EvidenceStatementError(f"{label} must be a positive base-10 integer")
    return int(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repository-health-evidence",
        description="Create or validate bounded repository-health evidence statements.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create JSON evidence and a SHA-256 manifest")
    create.add_argument("--repository", required=True)
    create.add_argument("--unit-id", required=True)
    create.add_argument("--subject-ref", required=True)
    create.add_argument("--subject-sha", required=True)
    create.add_argument("--subject-digest", action="append", default=[])
    create.add_argument("--subject-digests-json")
    create.add_argument("--workflow-ref", required=True)
    create.add_argument("--workflow-sha", required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--run-attempt", required=True)
    create.add_argument("--observed-at")
    create.add_argument("--kind", required=True, choices=sorted(KINDS))
    create.add_argument("--result", required=True, choices=sorted(RESULTS))
    create.add_argument("--category", action="append", default=[])
    create.add_argument("--categories-json")
    create.add_argument("--artifact-digest", action="append", default=[])
    create.add_argument("--artifact-digests-json")
    create.add_argument("--source-evidence-id", action="append", default=[])
    create.add_argument("--source-evidence-ids-json")
    create.add_argument("--output", required=True)
    create.add_argument("--manifest", required=True)

    validate = commands.add_parser("validate", help="validate evidence JSON and optional manifest")
    validate.add_argument("--input", required=True)
    validate.add_argument("--manifest")
    validate.add_argument("--expected-repository")
    validate.add_argument("--expected-unit-id")
    validate.add_argument("--expected-subject-sha")
    validate.add_argument("--expected-workflow-ref")
    validate.add_argument("--expected-workflow-sha")
    validate.add_argument("--expected-run-id")
    validate.add_argument("--expected-run-attempt")
    validate.add_argument(
        "--max-future-seconds", type=int, default=DEFAULT_MAX_FUTURE_SECONDS
    )
    return parser


def _run_create(arguments: argparse.Namespace) -> dict[str, str]:
    subject_digests = _array_argument(
        arguments.subject_digests_json, "subject_digests_json"
    ) + [_digest_argument(value) for value in arguments.subject_digest]
    artifact_digests = _array_argument(
        arguments.artifact_digests_json, "artifact_digests_json"
    ) + [_digest_argument(value) for value in arguments.artifact_digest]
    categories = _array_argument(arguments.categories_json, "categories_json") + list(
        arguments.category
    )
    source_ids = _array_argument(
        arguments.source_evidence_ids_json, "source_evidence_ids_json"
    ) + list(arguments.source_evidence_id)
    statement = create_evidence_statement(
        repository=arguments.repository,
        unit_id=arguments.unit_id,
        subject_ref=arguments.subject_ref,
        subject_sha=arguments.subject_sha,
        subject_digests=subject_digests,
        workflow_ref=arguments.workflow_ref,
        workflow_sha=arguments.workflow_sha,
        run_id=_integer_argument(arguments.run_id, "run_id"),
        run_attempt=_integer_argument(arguments.run_attempt, "run_attempt"),
        observed_at=arguments.observed_at,
        kind=arguments.kind,
        result=arguments.result,
        categories=categories,
        artifact_digests=artifact_digests,
        source_evidence_ids=source_ids,
    )
    return write_evidence_package(
        statement,
        output_path=arguments.output,
        manifest_path=arguments.manifest,
    )


def _validation_options(arguments: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "expected_repository": arguments.expected_repository,
        "expected_unit_id": arguments.expected_unit_id,
        "expected_subject_sha": arguments.expected_subject_sha,
        "expected_workflow_ref": arguments.expected_workflow_ref,
        "expected_workflow_sha": arguments.expected_workflow_sha,
        "max_future_seconds": arguments.max_future_seconds,
    }
    if arguments.expected_run_id is not None:
        options["expected_run_id"] = _integer_argument(
            arguments.expected_run_id, "expected_run_id"
        )
    if arguments.expected_run_attempt is not None:
        options["expected_run_attempt"] = _integer_argument(
            arguments.expected_run_attempt, "expected_run_attempt"
        )
    return options


def _run_validate(arguments: argparse.Namespace) -> dict[str, Any]:
    options = _validation_options(arguments)
    if arguments.manifest:
        statement = verify_evidence_package(
            input_path=arguments.input,
            manifest_path=arguments.manifest,
            **options,
        )
    else:
        statement = load_evidence_statement(arguments.input, **options)
    return {"valid": True, "statement_id": statement["statement_id"]}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``python -m ...evidence_producer``."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = _run_create(arguments) if arguments.command == "create" else _run_validate(arguments)
    except (EvidenceStatementError, OSError) as error:
        print(f"repository-health-evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

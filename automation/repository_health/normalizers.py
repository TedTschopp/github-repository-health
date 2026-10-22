"""Normalize collected evidence into metric-ready observations.

This module is intentionally read-only.  It may inspect Git objects with a
small allow-listed set of ``git`` commands, but it never checks out a revision,
invokes a hook, evaluates repository configuration, imports repository code, or
executes a repository-owned command.  Missing linkage is represented as an
incomplete normalized observation so the measurement layer returns Unknown.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any, Iterable, Mapping, Sequence


OBSERVATION_SCHEMA = "RH-GITHUB-OBSERVATIONS-1.0"
NORMALIZATION_SCHEMA = "RH-NORMALIZATION-1.0"
PRODUCTION_SCHEMA = "RH-PRODUCTION-IDENTITY-1.0"
GENERIC_PRODUCTION_SCHEMA = "RH-PRODUCTION-IDENTITY-2.0"

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SEMVER_DRAFT_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")

SUCCESS_CONCLUSIONS = {"success"}
FAILURE_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "action_required",
    "startup_failure",
    "stale",
}


class NormalizationError(ValueError):
    """Raised when a declared machine-readable identity is structurally unsafe."""


def _duplicate_safe_json(data: bytes, label: str) -> dict[str, Any]:
    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise NormalizationError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise NormalizationError(f"{label} contains non-finite number {value}")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=object_hook, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NormalizationError(f"{label} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise NormalizationError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise NormalizationError(f"{label} is missing required keys: {', '.join(sorted(missing))}")
    if unknown:
        raise NormalizationError(f"{label} contains unknown keys: {', '.join(sorted(unknown))}")


def _nonempty_string(value: Any, label: str, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise NormalizationError(f"{label} must be a nonempty bounded string")
    return value


def _strict_sha(value: Any, label: str) -> str:
    text = _nonempty_string(value, label, 40)
    if SHA_PATTERN.fullmatch(text) is None:
        raise NormalizationError(f"{label} must be a lowercase 40-character Git SHA")
    return text


def _strict_digest(value: Any, label: str) -> str:
    text = _nonempty_string(value, label, 64)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise NormalizationError(f"{label} must be a lowercase SHA-256 digest")
    return text


def validate_production_identity(
    value: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    """Strictly validate a supported production identity schema."""

    if isinstance(value, Mapping) and value.get("schema_version") != PRODUCTION_SCHEMA:
        # Keep the legacy validator below byte-for-byte in behavior while
        # allowing the generic schema to share this exact-Main loading seam.
        from .production_identity import (
            GENERIC_PRODUCTION_SCHEMA,
            ProductionIdentityError,
            validate_generic_production_identity,
        )

        if value.get("schema_version") == GENERIC_PRODUCTION_SCHEMA:
            try:
                return validate_generic_production_identity(
                    value,
                    config=config,
                    repository=repository,
                )
            except ProductionIdentityError as error:
                raise NormalizationError(str(error)) from error

    record = dict(value)
    _exact_keys(
        record,
        {"schema_version", "standard_version", "repository", "units"},
        {"schema_version", "standard_version", "repository", "units"},
        "production identity",
    )
    if record["schema_version"] != PRODUCTION_SCHEMA:
        raise NormalizationError(f"unsupported production identity schema: {record['schema_version']!r}")
    standard = config.get("standard")
    repository_config = config.get("repository")
    if not isinstance(standard, Mapping) or not isinstance(repository_config, Mapping):
        raise NormalizationError("loaded configuration lacks standard/repository tables")
    version = _nonempty_string(standard.get("version"), "config.standard.version", 128)
    if SEMVER_DRAFT_PATTERN.fullmatch(version) is None:
        raise NormalizationError("config.standard.version is not a supported controlled version")
    if record.get("standard_version") != version:
        raise NormalizationError("production identity standard_version conflicts with configuration")
    if record.get("repository") != repository or REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise NormalizationError("production identity repository conflicts with the observed repository")
    units = record.get("units")
    if not isinstance(units, list) or not units:
        raise NormalizationError("production identity units must be a nonempty array")
    declared_units = repository_config.get("deployable_units")
    if not isinstance(declared_units, list) or not all(isinstance(item, str) and item for item in declared_units):
        raise NormalizationError("repository.deployable_units must be a nonempty string array")

    seen_units: set[str] = set()
    normalized_units: list[dict[str, Any]] = []
    for index, raw_unit in enumerate(units):
        label = f"production identity units[{index}]"
        if not isinstance(raw_unit, Mapping):
            raise NormalizationError(f"{label} must be an object")
        unit = dict(raw_unit)
        _exact_keys(
            unit,
            {"unit_id", "kind", "correspondence", "selection", "current", "validation", "limitations"},
            {"unit_id", "kind", "correspondence", "selection", "current", "validation", "limitations"},
            label,
        )
        unit_id = _nonempty_string(unit.get("unit_id"), f"{label}.unit_id", 256)
        if unit_id in seen_units:
            raise NormalizationError(f"duplicate production unit: {unit_id}")
        seen_units.add(unit_id)
        if unit.get("kind") != "github-release":
            raise NormalizationError(f"{label}.kind must be github-release")
        if unit.get("correspondence") not in {"Exact-Main", "Releasable-Main", "Production-Ref"}:
            raise NormalizationError(f"{label}.correspondence is unsupported")

        selection = unit.get("selection")
        if not isinstance(selection, Mapping):
            raise NormalizationError(f"{label}.selection must be an object")
        selection = dict(selection)
        _exact_keys(
            selection,
            {"strategy", "tag_template", "allow_prerelease", "allow_draft", "allow_latest_alias"},
            {"strategy", "tag_template", "allow_prerelease", "allow_draft", "allow_latest_alias"},
            f"{label}.selection",
        )
        if selection.get("strategy") != "controlled-standard-version" or selection.get("tag_template") != "v{standard.version}":
            raise NormalizationError(f"{label}.selection must derive the protected tag from the controlled version")
        for key in ("allow_prerelease", "allow_draft", "allow_latest_alias"):
            if not isinstance(selection.get(key), bool):
                raise NormalizationError(f"{label}.selection.{key} must be boolean")

        current = unit.get("current")
        if not isinstance(current, Mapping):
            raise NormalizationError(f"{label}.current must be an object")
        current = dict(current)
        current_required = {
            "supported",
            "release_id",
            "release_url",
            "published_at",
            "immutable",
            "tag",
            "tag_object_sha",
            "source_sha",
            "artifacts",
            "attestations",
        }
        _exact_keys(current, current_required, current_required, f"{label}.current")
        if current.get("supported") is not True or not isinstance(current.get("immutable"), bool):
            raise NormalizationError(f"{label}.current support/immutability declarations are invalid")
        if not isinstance(current.get("release_id"), int) or isinstance(current.get("release_id"), bool) or current["release_id"] < 1:
            raise NormalizationError(f"{label}.current.release_id must be positive")
        _nonempty_string(current.get("release_url"), f"{label}.current.release_url")
        published_at = _nonempty_string(current.get("published_at"), f"{label}.current.published_at", 40)
        try:
            parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise NormalizationError(f"{label}.current.published_at is invalid") from error
        if parsed.tzinfo is None:
            raise NormalizationError(f"{label}.current.published_at must be timezone-aware")
        expected_tag = f"v{version}"
        if current.get("tag") != expected_tag:
            raise NormalizationError(f"{label}.current.tag does not match controlled standard version")
        _strict_sha(current.get("tag_object_sha"), f"{label}.current.tag_object_sha")
        _strict_sha(current.get("source_sha"), f"{label}.current.source_sha")

        artifacts = current.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise NormalizationError(f"{label}.current.artifacts must be nonempty")
        artifact_names: set[str] = set()
        artifact_roles: set[str] = set()
        primary_count = 0
        normalized_artifacts: list[dict[str, Any]] = []
        for artifact_index, raw_artifact in enumerate(artifacts):
            artifact_label = f"{label}.current.artifacts[{artifact_index}]"
            if not isinstance(raw_artifact, Mapping):
                raise NormalizationError(f"{artifact_label} must be an object")
            artifact = dict(raw_artifact)
            _exact_keys(artifact, {"name", "role", "primary", "sha256"}, {"name", "role", "primary", "sha256"}, artifact_label)
            name = _nonempty_string(artifact.get("name"), f"{artifact_label}.name", 256)
            role = _nonempty_string(artifact.get("role"), f"{artifact_label}.role", 80)
            if name in artifact_names or role in artifact_roles:
                raise NormalizationError(f"{artifact_label} duplicates an artifact name or role")
            artifact_names.add(name)
            artifact_roles.add(role)
            if not isinstance(artifact.get("primary"), bool):
                raise NormalizationError(f"{artifact_label}.primary must be boolean")
            primary_count += int(artifact["primary"])
            _strict_digest(artifact.get("sha256"), f"{artifact_label}.sha256")
            normalized_artifacts.append(artifact)
        required_roles = {"source-package", "sbom", "release-identity", "checksum-manifest", "sbom-attestation-bundle"}
        if artifact_roles != required_roles or primary_count != 1:
            raise NormalizationError(f"{label}.current.artifacts must contain the five controlled roles and one primary")

        attestations = current.get("attestations")
        if not isinstance(attestations, list) or not attestations or not all(isinstance(item, Mapping) for item in attestations):
            raise NormalizationError(f"{label}.current.attestations must be a nonempty object array")
        normalized_attestations: list[dict[str, Any]] = []
        for attestation_index, raw_attestation in enumerate(attestations):
            attestation_label = f"{label}.current.attestations[{attestation_index}]"
            attestation = dict(raw_attestation)
            kind = attestation.get("kind")
            if kind == "github-immutable-release":
                _exact_keys(attestation, {"kind", "covers"}, {"kind", "covers"}, attestation_label)
                _nonempty_string(attestation.get("covers"), f"{attestation_label}.covers")
            elif kind == "sigstore-sbom":
                keys = {
                    "kind",
                    "url",
                    "predicate_type",
                    "subject_name",
                    "subject_sha256",
                    "signer_workflow",
                    "signer_ref",
                    "signer_sha",
                }
                _exact_keys(attestation, keys, keys, attestation_label)
                for key in ("url", "predicate_type", "subject_name", "signer_workflow", "signer_ref"):
                    _nonempty_string(attestation.get(key), f"{attestation_label}.{key}")
                _strict_digest(attestation.get("subject_sha256"), f"{attestation_label}.subject_sha256")
                _strict_sha(attestation.get("signer_sha"), f"{attestation_label}.signer_sha")
            else:
                raise NormalizationError(f"{attestation_label}.kind is unsupported")
            normalized_attestations.append(attestation)
        kinds = {item.get("kind") for item in normalized_attestations}
        if "github-immutable-release" not in kinds or "sigstore-sbom" not in kinds:
            raise NormalizationError(f"{label}.current.attestations lacks required kinds")
        current["attestations"] = normalized_attestations

        validation = unit.get("validation")
        if not isinstance(validation, Mapping):
            raise NormalizationError(f"{label}.validation must be an object")
        validation = dict(validation)
        validation_keys = {
            "authoritative_checks",
            "source_must_be_reachable_from_main",
            "main_ahead_policy",
            "incomplete_history_result",
        }
        _exact_keys(validation, validation_keys, validation_keys, f"{label}.validation")
        checks = validation.get("authoritative_checks")
        configured_checks = repository_config.get("authoritative_checks")
        if not isinstance(checks, list) or checks != configured_checks or not all(isinstance(item, str) and item for item in checks):
            raise NormalizationError(f"{label}.validation.authoritative_checks conflicts with configuration")
        if validation.get("source_must_be_reachable_from_main") is not True:
            raise NormalizationError(f"{label}.validation requires Main reachability")
        if validation.get("main_ahead_policy") != "every-intervening-accepted-main-revision-must-pass-authoritative-checks":
            raise NormalizationError(f"{label}.validation main-ahead policy is unsupported")
        if validation.get("incomplete_history_result") != "Unknown":
            raise NormalizationError(f"{label}.validation must fail incomplete history closed")
        limitations = unit.get("limitations")
        if not isinstance(limitations, list) or not all(isinstance(item, str) and item and len(item) <= 4096 for item in limitations):
            raise NormalizationError(f"{label}.limitations must be a string array")

        current["artifacts"] = normalized_artifacts
        unit.update({"selection": selection, "current": current, "validation": validation, "limitations": list(limitations)})
        normalized_units.append(unit)

    if seen_units != set(declared_units):
        raise NormalizationError("production identity unit IDs conflict with repository.deployable_units")
    if any(unit["correspondence"] != repository_config.get("production_correspondence") for unit in normalized_units):
        raise NormalizationError("production identity correspondence conflicts with configuration")
    record["units"] = normalized_units
    return record


def load_production_identity(
    source: str | Path | bytes | Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    """Load and strictly validate a production identity record."""

    if isinstance(source, Mapping):
        value = deepcopy(dict(source))
    elif isinstance(source, bytes):
        value = _duplicate_safe_json(source, "production identity")
    else:
        path = Path(source)
        if not path.is_file() or path.is_symlink():
            raise NormalizationError("production identity path must be a regular non-symlink file")
        value = _duplicate_safe_json(path.read_bytes(), str(path))
    return validate_production_identity(value, config=config, repository=repository)


def _git(root: Path, *arguments: str) -> tuple[str, str | None]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
    }
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "pager.branch=false",
                "-c",
                "pager.log=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return "", type(error).__name__
    if result.returncode != 0:
        return result.stdout.strip(), result.stderr.strip() or f"git exited {result.returncode}"
    return result.stdout.strip(), None


def _git_ancestry(root: Path | None, ancestor: str, descendant: str) -> bool | None:
    if root is None or SHA_PATTERN.fullmatch(ancestor) is None or SHA_PATTERN.fullmatch(descendant) is None:
        return None
    _, error = _git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    if error is None:
        return True
    # ``merge-base --is-ancestor`` returns 1 without a diagnostic for a known
    # non-ancestor.  The wrapper converts that to a stable exit message.
    if error == "git exited 1":
        return False
    return None


def _intervening_revisions(root: Path | None, source_sha: str, main_sha: str) -> list[str] | None:
    if root is None:
        return None
    output, error = _git(root, "rev-list", "--first-parent", "--reverse", f"{source_sha}..{main_sha}")
    if error is not None:
        return None
    revisions = [line for line in output.splitlines() if SHA_PATTERN.fullmatch(line)]
    return revisions if len(revisions) == len([line for line in output.splitlines() if line]) else None


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _first_parent_history(root: Path | None, main_sha: str) -> tuple[list[dict[str, Any]], bool]:
    if root is None or SHA_PATTERN.fullmatch(main_sha) is None:
        return [], False
    output, error = _git(
        root,
        "log",
        "--first-parent",
        "--reverse",
        "-n",
        "5001",
        "--format=%H%x09%cI",
        main_sha,
    )
    if error is not None:
        return [], False
    lines = [line for line in output.splitlines() if line]
    complete = len(lines) <= 5000
    rows: list[dict[str, Any]] = []
    for line in lines[:5000]:
        sha, separator, timestamp = line.partition("\t")
        instant = _parse_instant(timestamp)
        if not separator or SHA_PATTERN.fullmatch(sha) is None or instant is None:
            return [], False
        rows.append({"sha": sha, "accepted_at": instant, "accepted_at_text": timestamp})
    if not rows or rows[-1]["sha"] != main_sha:
        return [], False
    return rows, complete


def _main_invalid_duration_population(
    *,
    root: Path | None,
    main_sha: str,
    observed_at: Any,
    check_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    authoritative_checks: Sequence[str],
    w365_complete: bool,
) -> tuple[dict[str, Any], bool, list[str]]:
    """Reconstruct W90 invalid intervals from first-parent Main and check events."""

    now = _parse_instant(observed_at)
    revisions, first_parent_complete = _first_parent_history(root, main_sha)
    if now is None or not first_parent_complete or not revisions or not w365_complete:
        return {"items": []}, False, [
            "Complete W365 Actions and exact first-parent Main history are required for invalid-duration reconstruction."
        ]
    if any(row["accepted_at"] > now for row in revisions):
        return {"items": []}, False, ["Main history contains a future acceptance timestamp."]

    window_start = now - timedelta(days=90)
    changes_in_window = [row for row in revisions if row["accepted_at"] > window_start]
    if not changes_in_window:
        state, _ = _check_state(check_index, main_sha, authoritative_checks)
        if state != "success":
            return {"items": []}, False, [
                "No Main change occurred in W90, but complete successful current telemetry is unavailable."
            ]
        return {
            "items": [],
            "no_events": True,
            "observable_minutes": 90 * 24 * 60,
            "window": {
                "kind": "rolling",
                "days": 90,
                "start": window_start.isoformat(),
                "end": now.isoformat(),
            },
        }, True, []

    active_before = [row for row in revisions if row["accepted_at"] <= window_start]
    selected = ([active_before[-1]] if active_before else []) + changes_in_window
    if not selected:
        return {"items": []}, False, ["No observable first-parent Main interval is available."]

    observable_start = window_start if active_before else selected[0]["accepted_at"]
    invalid_intervals: list[dict[str, Any]] = []
    invalid_minutes = 0.0
    for index, revision in enumerate(selected):
        interval_start = max(observable_start, revision["accepted_at"])
        interval_end = (
            min(now, selected[index + 1]["accepted_at"])
            if index + 1 < len(selected)
            else now
        )
        if interval_end <= interval_start:
            continue

        states: dict[str, str] = {}
        events: list[tuple[datetime, str, str]] = []
        for check_name in authoritative_checks:
            records = check_index.get((revision["sha"], check_name), ())
            if not records:
                return {"items": invalid_intervals}, False, [
                    f"Authoritative check history is missing for first-parent Main revision {revision['sha']}."
                ]
            for record in records:
                completed = _parse_instant(record.get("completed_at"))
                conclusion = str(record.get("conclusion") or "").lower()
                status = record.get("status")
                if completed is None or status != "completed" or conclusion not in SUCCESS_CONCLUSIONS | FAILURE_CONCLUSIONS:
                    return {"items": invalid_intervals}, False, [
                        f"Authoritative check history is nonterminal or untimed for revision {revision['sha']}."
                    ]
                event_state = "success" if conclusion in SUCCESS_CONCLUSIONS else "failure"
                if completed <= interval_start:
                    states[check_name] = event_state
                elif completed < interval_end:
                    events.append((completed, check_name, event_state))

        cursor = interval_start
        invalid_since = interval_start if not all(states.get(name) == "success" for name in authoritative_checks) else None
        for event_time, check_name, event_state in sorted(events, key=lambda item: item[0]):
            was_invalid = not all(states.get(name) == "success" for name in authoritative_checks)
            if was_invalid:
                invalid_minutes += (event_time - cursor).total_seconds() / 60.0
            states[check_name] = event_state
            is_invalid = not all(states.get(name) == "success" for name in authoritative_checks)
            if not was_invalid and is_invalid:
                invalid_since = event_time
            elif was_invalid and not is_invalid and invalid_since is not None:
                invalid_intervals.append(
                    {
                        "id": f"{revision['sha']}:{invalid_since.isoformat()}",
                        "main_sha": revision["sha"],
                        "started_at": invalid_since.isoformat(),
                        "ended_at": event_time.isoformat(),
                        "duration_minutes": (event_time - invalid_since).total_seconds() / 60.0,
                    }
                )
                invalid_since = None
            cursor = event_time
        remains_invalid = not all(states.get(name) == "success" for name in authoritative_checks)
        if remains_invalid:
            invalid_minutes += (interval_end - cursor).total_seconds() / 60.0
            start = invalid_since or cursor
            invalid_intervals.append(
                {
                    "id": f"{revision['sha']}:{start.isoformat()}",
                    "main_sha": revision["sha"],
                    "started_at": start.isoformat(),
                    "ended_at": interval_end.isoformat(),
                    "duration_minutes": (interval_end - start).total_seconds() / 60.0,
                }
            )

    observable_minutes = (now - observable_start).total_seconds() / 60.0
    if observable_minutes <= 0 or invalid_minutes < 0 or invalid_minutes > observable_minutes:
        return {"items": invalid_intervals}, False, ["Reconstructed invalid-duration totals are inconsistent."]
    return {
        "items": invalid_intervals,
        "invalid_minutes": invalid_minutes,
        "observable_minutes": observable_minutes,
        "no_events": False,
        "window": {
            "kind": "rolling",
            "days": 90,
            "start": observable_start.isoformat(),
            "end": now.isoformat(),
        },
    }, True, []


def _tagged_configuration(root: Path | None, source_sha: str) -> tuple[dict[str, Any] | None, str | None]:
    if root is None:
        return None, "Local Git history is unavailable for tagged configuration inspection."
    content, error = _git(root, "show", f"{source_sha}:.github/repository-health.toml")
    if error is not None:
        return None, "Tagged repository-health configuration is unavailable."
    try:
        value = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, TypeError) as parse_error:
        return None, f"Tagged repository-health configuration is invalid: {type(parse_error).__name__}."
    return value if isinstance(value, dict) else None, None


def _raw_group(bundle: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    observations = bundle.get("observations")
    if not isinstance(observations, Mapping):
        return None
    value = observations.get(name)
    return dict(value) if isinstance(value, Mapping) else None


def _group_complete(group: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(group, Mapping)
        and group.get("state") == "observed"
        and group.get("complete") is True
        and group.get("population_complete") is True
        and not group.get("gaps")
    )


def _group_data(group: Mapping[str, Any] | None) -> dict[str, Any]:
    data = group.get("data") if isinstance(group, Mapping) else None
    return dict(data) if isinstance(data, Mapping) else {}


def _purpose_group(
    metric_id: str,
    bundle: Mapping[str, Any],
    data: Mapping[str, Any],
    *,
    complete: bool,
    evidence_ids: Iterable[str],
    limitations: Iterable[str] = (),
    gaps: Iterable[str] = (),
) -> dict[str, Any]:
    gap_list = [
        {
            "kind": "normalization_gap",
            "status": None,
            "endpoint": None,
            "source": "repository-health-normalizer",
            "message": message,
        }
        for message in dict.fromkeys(gaps)
        if message
    ]
    ids = [item for item in dict.fromkeys(evidence_ids) if isinstance(item, str) and item]
    source_ids = "+".join(ids) if ids else "unresolved"
    return {
        "evidence_id": f"E-NORMALIZED-{metric_id}",
        "evidence_ids": ids,
        "observation_id": f"N-{metric_id}-{str(bundle.get('subject_sha') or '')[:12]}",
        "observed_at": bundle.get("observed_at"),
        "source": f"repository-health-normalizer:{source_ids}",
        "subject_sha": bundle.get("subject_sha"),
        "unit": None,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else ("partial" if data else "unknown"),
        "complete": complete,
        "population_complete": complete,
        "data": dict(data),
        "gaps": gap_list,
        "request": {"complete": complete, "population_complete": complete, "truncated": False},
        "limitations": list(dict.fromkeys(item for item in limitations if item)),
    }


def _evidence_ids(*groups: Mapping[str, Any] | None, extra: Iterable[str] = ()) -> list[str]:
    values = [group.get("evidence_id") for group in groups if isinstance(group, Mapping)]
    values.extend(extra)
    return [item for item in dict.fromkeys(values) if isinstance(item, str) and item]


def _record_time(record: Mapping[str, Any]) -> str:
    for key in ("completed_at", "updated_at", "started_at", "created_at"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    identifier = record.get("id")
    return f"{identifier:020d}" if isinstance(identifier, int) else ""


def _check_index(
    bundle: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, bool], list[str]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    limitations: list[str] = []
    completeness = {"current": False, "w90": False, "w365": False}

    current_group = _raw_group(bundle, "check_runs")
    if _group_complete(current_group):
        completeness["current"] = True
        current_sha = current_group.get("subject_sha") or bundle.get("subject_sha")
        runs = _group_data(current_group).get("check_runs")
        if isinstance(current_sha, str) and isinstance(runs, list):
            for run in runs:
                if not isinstance(run, Mapping) or not isinstance(run.get("name"), str):
                    continue
                sha = run.get("head_sha") if isinstance(run.get("head_sha"), str) else current_sha
                record = dict(run)
                record["automatic"] = True
                record["source_group"] = "check_runs"
                index.setdefault((sha, run["name"]), []).append(record)
    elif current_group is not None:
        limitations.append("Exact Main check-run population is incomplete.")

    for group_name in ("actions_w365", "actions_w90"):
        group = _raw_group(bundle, group_name)
        if group is None:
            continue
        if not _group_complete(group):
            limitations.append(f"{group_name} action history is incomplete.")
            continue
        completeness["w365" if group_name == "actions_w365" else "w90"] = True
        data = _group_data(group)
        attempts = data.get("run_attempts")
        if not isinstance(attempts, list):
            continue
        latest_attempts: dict[int, Mapping[str, Any]] = {}
        for attempt in attempts:
            if not isinstance(attempt, Mapping) or not isinstance(attempt.get("run_id"), int):
                continue
            run_id = attempt["run_id"]
            if run_id not in latest_attempts or int(attempt.get("attempt") or 0) > int(latest_attempts[run_id].get("attempt") or 0):
                latest_attempts[run_id] = attempt
        for attempt in latest_attempts.values():
            run = attempt.get("run")
            if not isinstance(run, Mapping):
                continue
            sha = run.get("head_sha")
            jobs = attempt.get("jobs")
            if not isinstance(sha, str) or not isinstance(jobs, list):
                continue
            for job in jobs:
                if not isinstance(job, Mapping) or not isinstance(job.get("name"), str):
                    continue
                record = dict(job)
                record.update(
                    {
                        "automatic": str(run.get("event") or "").lower() not in {"workflow_dispatch", "repository_dispatch"},
                        "event": run.get("event"),
                        "run_created_at": run.get("created_at"),
                        "run_id": run.get("id") or attempt.get("run_id"),
                        "source_group": group_name,
                    }
                )
                index.setdefault((sha, job["name"]), []).append(record)

    for records in index.values():
        records.sort(key=_record_time)
    return index, completeness, limitations


def _check_state(index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]], sha: str, names: Sequence[str]) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    states: list[str] = []
    for name in names:
        records = index.get((sha, name), ())
        if not records:
            details[name] = {"state": "missing"}
            states.append("unknown")
            continue
        latest = records[-1]
        status = latest.get("status")
        conclusion = str(latest.get("conclusion") or "").lower()
        if status != "completed" or conclusion not in SUCCESS_CONCLUSIONS | FAILURE_CONCLUSIONS:
            state = "unknown"
        elif conclusion in SUCCESS_CONCLUSIONS:
            state = "success"
        else:
            state = "failure"
        details[name] = {
            "state": state,
            "conclusion": conclusion or None,
            "completed_at": latest.get("completed_at"),
            "automatic": latest.get("automatic"),
            "run_created_at": latest.get("run_created_at"),
            "source_group": latest.get("source_group"),
        }
        states.append(state)
    if "failure" in states:
        return "failure", details
    if states and all(state == "success" for state in states):
        return "success", details
    return "unknown", details


def _safe_root(local: Mapping[str, Any]) -> Path | None:
    value = local.get("root")
    if not isinstance(value, str):
        return None
    root = Path(value).resolve()
    return root if root.is_dir() and local.get("is_git_repository") is True else None


def _change_transport_complete(
    group: Mapping[str, Any] | None,
    data: Mapping[str, Any],
) -> bool:
    """Return whether the API portions needed to enrich local Main history completed.

    The GitHub collector deliberately marks ``change_history`` incomplete because
    reachable commits do not prove accepted-Main revisions or historical bypass.
    The normalizer replaces only the former with exact local first-parent history;
    it must still reject every unrelated API, pagination, or identity gap.
    """

    if not isinstance(group, Mapping):
        return False
    if isinstance(data.get("commits"), list):
        # Backward-compatible fixture/consumer shape.  This path is intentionally
        # stricter than the current collector and requires the whole group.
        return _group_complete(group)
    if not isinstance(data.get("reachable_commits"), list):
        return False
    basis = data.get("most_recent_commit_basis")
    if not isinstance(basis, Mapping) or basis.get("complete") is not True:
        return False
    if basis.get("window_population_complete") is not True:
        return False
    if basis.get("window_commit_identity_complete") is not True:
        return False
    if basis.get("most_recent_commit_complete") is not True:
        return False

    allowed_gaps = {"accepted_main_revision_population_unavailable"}
    gaps = group.get("gaps")
    if not isinstance(gaps, list):
        return False
    if any(
        not isinstance(gap, Mapping) or gap.get("kind") not in allowed_gaps
        for gap in gaps
    ):
        return False
    request = group.get("request")
    endpoints = request.get("endpoints") if isinstance(request, Mapping) else None
    if not isinstance(endpoints, list) or not endpoints:
        return False
    return all(
        isinstance(endpoint, Mapping) and endpoint.get("complete") is True
        for endpoint in endpoints
    )


def _historical_bypass(
    data: Mapping[str, Any],
    sha: str,
) -> tuple[bool | None, dict[str, Any], bool]:
    """Resolve bypass use only from a complete historical event population.

    Current rules describe current enforcement.  They are never used to infer
    that an older accepted revision did not use a bypass.
    """

    if data.get("historical_bypass_complete") is not True:
        return None, {}, False
    events = data.get("historical_bypass_events")
    if not isinstance(events, list):
        return None, {}, False
    matches = [
        event
        for event in events
        if isinstance(event, Mapping)
        and (event.get("final_revision") or event.get("commit_sha") or event.get("sha")) == sha
    ]
    if not matches:
        return False, {}, True

    # Multiple events are allowed, but every event must be independently
    # accountable before the accepted-change record is classifiable.
    required_aliases = {
        "affected_control_or_ref": ("affected_control_or_ref", "ref", "affected_ref"),
        "bypass_reason": ("bypass_reason", "reason"),
        "change_or_incident_link": ("change_or_incident_link", "change_link", "incident_link"),
        "bypass_approval_or_review": ("bypass_approval_or_review", "approval", "retrospective_review"),
    }
    normalized: dict[str, Any] = {}
    for output_key, aliases in required_aliases.items():
        values = [
            event.get(alias)
            for event in matches
            for alias in aliases
            if event.get(alias) is not None and event.get(alias) != ""
        ]
        if not values:
            return True, {}, False
        normalized[output_key] = values[0]
    temporary = any(event.get("temporary_access") is True for event in matches)
    if temporary:
        expiries = [event.get("access_expiry") for event in matches if event.get("access_expiry")]
        if not expiries:
            return True, normalized, False
        normalized.update({"temporary_access": True, "access_expiry": expiries[0]})
    normalized["bypass_event_count"] = len(matches)
    return True, normalized, True


def _asset_contents(local: Mapping[str, Any], refs_group: Mapping[str, Any] | None) -> dict[str, bytes]:
    sources: list[Any] = [local.get("release_asset_contents")]
    refs_data = _group_data(refs_group)
    sources.append(refs_data.get("asset_contents"))
    result: dict[str, bytes] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for name, value in source.items():
            if not isinstance(name, str) or name in result:
                continue
            if isinstance(value, bytes):
                result[name] = value
            elif isinstance(value, str):
                result[name] = value.encode("utf-8")
    return result


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _asset_digest(asset: Mapping[str, Any]) -> str | None:
    value = asset.get("digest")
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.split(":", 1)[1]
    return normalized if SHA256_PATTERN.fullmatch(normalized) else None


def _parse_checksum_manifest(content: bytes) -> dict[str, str] | None:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    result: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\\x00\r\n]+)", line)
        if match is None or match.group(2) in result:
            return None
        result[match.group(2)] = match.group(1)
    return result if result else None


def _validate_release_identity_content(
    content: bytes,
    *,
    repository: str,
    version: str,
    unit: Mapping[str, Any],
    correspondence: str | None = None,
) -> tuple[bool, list[str]]:
    problems: list[str] = []
    try:
        identity = _duplicate_safe_json(content, "downloaded release identity")
    except NormalizationError as error:
        return False, [str(error)]
    current = unit["current"]
    expected = {
        "schema_version": "RH-RELEASE-IDENTITY-1.0",
        "source_repository": f"https://github.com/{repository}",
        "source_ref": f"refs/tags/{current['tag']}",
        "source_sha": current["source_sha"],
        "standard_version": version,
        "production_correspondence": correspondence or unit["correspondence"],
        "tag": current["tag"],
    }
    for key, expected_value in expected.items():
        if identity.get(key) != expected_value:
            problems.append(f"release identity {key} conflicts with expected value")
    artifacts = identity.get("artifacts")
    if not isinstance(artifacts, list):
        problems.append("release identity artifacts are missing")
    else:
        observed = {
            item.get("role"): (item.get("name"), item.get("sha256"))
            for item in artifacts
            if isinstance(item, Mapping)
        }
        for artifact in current["artifacts"]:
            if artifact["role"] in {"source-package", "sbom"} and observed.get(artifact["role"]) != (artifact["name"], artifact["sha256"]):
                problems.append(f"release identity does not bind {artifact['role']}")
    return not problems, problems


def _attestation_index(group: Mapping[str, Any] | None) -> dict[tuple[Any, Any], bool]:
    result: dict[tuple[Any, Any], bool] = {}
    assets = _group_data(group).get("assets")
    if not isinstance(assets, list):
        return result
    for asset in assets:
        if isinstance(asset, Mapping):
            attestations = asset.get("attestations")
            result[(asset.get("release_id"), asset.get("asset_id"))] = isinstance(attestations, list) and bool(attestations)
    return result


def _ruleset_matches(detail: Mapping[str, Any], ref: str, main_ref: str) -> bool:
    # GitHub's evaluate mode reports what a ruleset *would* do; it does not
    # establish an enforced source-control boundary.
    if detail.get("enforcement") != "active":
        return False
    conditions = detail.get("conditions")
    ref_names = conditions.get("ref_name") if isinstance(conditions, Mapping) else None
    if not isinstance(ref_names, Mapping):
        return False
    includes = ref_names.get("include")
    excludes = ref_names.get("exclude")
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        return False
    excludes = excludes if isinstance(excludes, list) else []

    def matches(pattern: str) -> bool:
        if pattern == "~DEFAULT_BRANCH":
            return ref == main_ref
        if pattern == "~ALL":
            return True
        return fnmatch.fnmatchcase(ref, pattern)

    return any(matches(pattern) for pattern in includes) and not any(matches(pattern) for pattern in excludes if isinstance(pattern, str))


def _ref_assertions(
    rules_group: Mapping[str, Any] | None,
    *,
    ref: str,
    main_ref: str,
    authoritative_checks: Sequence[str],
    immutable_release: bool = False,
    validated_release: bool = False,
) -> tuple[dict[str, bool | None], bool | None]:
    if not _group_complete(rules_group):
        return {key: None for key in ("restricted_update", "deletion_protection", "force_push_protection", "required_acceptance_checks", "controlled_audited_bypass")}, None
    data = _group_data(rules_group)
    matching: list[Mapping[str, Any]] = []
    rulesets = data.get("rulesets")
    if isinstance(rulesets, list):
        for record in rulesets:
            detail = record.get("detail") if isinstance(record, Mapping) else None
            if isinstance(detail, Mapping) and _ruleset_matches(detail, ref, main_ref):
                matching.append(detail)
    rule_types: set[str] = set()
    required_names: set[str] = set()
    bypass_known = bool(matching)
    bypass_impossible = bool(matching)
    for ruleset in matching:
        rules = ruleset.get("rules")
        if not isinstance(rules, list):
            bypass_known = False
            continue
        for rule in rules:
            if not isinstance(rule, Mapping) or not isinstance(rule.get("type"), str):
                continue
            rule_types.add(rule["type"])
            parameters = rule.get("parameters")
            checks = parameters.get("required_status_checks") if isinstance(parameters, Mapping) else None
            if isinstance(checks, list):
                for check in checks:
                    if isinstance(check, Mapping) and isinstance(check.get("context"), str):
                        required_names.add(check["context"])
        bypass = ruleset.get("bypass_actors")
        if not isinstance(bypass, list):
            bypass_known = False
            bypass_impossible = False
        elif bypass:
            # A nonempty configured bypass list is not proof that its use is
            # fully logged, approved, and retained.  That requires audit-event
            # evidence not supplied by the rules APIs.
            bypass_impossible = False

    if ref == main_ref:
        effective = data.get("effective_branch_rules")
        if isinstance(effective, list):
            for rule in effective:
                if isinstance(rule, Mapping) and isinstance(rule.get("type"), str):
                    rule_types.add(rule["type"])
                    parameters = rule.get("parameters")
                    checks = parameters.get("required_status_checks") if isinstance(parameters, Mapping) else None
                    if isinstance(checks, list):
                        required_names.update(
                            check.get("context")
                            for check in checks
                            if isinstance(check, Mapping) and isinstance(check.get("context"), str)
                        )
        protection = data.get("branch_protection")
        if isinstance(protection, Mapping):
            if protection.get("required_pull_request_reviews") is not None:
                rule_types.add("pull_request")
            status_checks = protection.get("required_status_checks")
            contexts = status_checks.get("contexts") if isinstance(status_checks, Mapping) else None
            if isinstance(contexts, list):
                rule_types.add("required_status_checks")
                required_names.update(item for item in contexts if isinstance(item, str))
            deletions = protection.get("allow_deletions")
            if isinstance(deletions, Mapping) and deletions.get("enabled") is False:
                rule_types.add("deletion")
            force = protection.get("allow_force_pushes")
            if isinstance(force, Mapping) and force.get("enabled") is False:
                rule_types.add("non_fast_forward")

    restricted = "pull_request" in rule_types or "update" in rule_types or (ref.startswith("refs/tags/") and "non_fast_forward" in rule_types)
    deletion = "deletion" in rule_types
    non_fast_forward = "non_fast_forward" in rule_types
    required_checks = (set(authoritative_checks) <= required_names if authoritative_checks else False) or (bool(matching) and immutable_release and validated_release)
    has_enforcement_evidence = bool(matching) or ref == main_ref
    bypass_assertion = True if bypass_known and bypass_impossible else None
    return {
        "restricted_update": restricted if has_enforcement_evidence else None,
        "deletion_protection": deletion if has_enforcement_evidence else None,
        "force_push_protection": non_fast_forward if has_enforcement_evidence else None,
        "required_acceptance_checks": required_checks if has_enforcement_evidence else None,
        "controlled_audited_bypass": bypass_assertion,
    }, bypass_assertion


def _workflow_contract(root: Path | None, main_sha: str, authoritative_checks: Sequence[str]) -> bool | None:
    if root is None or SHA_PATTERN.fullmatch(main_sha) is None or not authoritative_checks:
        return None
    names_output, names_error = _git(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        main_sha,
        "--",
        ".github/workflows",
    )
    if names_error is not None:
        return None
    paths = sorted(
        path
        for path in names_output.splitlines()
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    )
    if not paths:
        return None
    texts: list[str] = []
    for path in paths:
        content, error = _git(root, "show", f"{main_sha}:{path}")
        if error is not None:
            return None
        texts.append(content)
    job_blocks: list[tuple[str, str]] = []
    for text in texts:
        if "\t" in text:
            return None
        lines = text.splitlines()
        jobs_indices = [index for index, line in enumerate(lines) if re.fullmatch(r"jobs:\s*", line)]
        if len(jobs_indices) != 1:
            return None
        jobs_index = jobs_indices[0]
        starts: list[tuple[int, str]] = []
        for index in range(jobs_index + 1, len(lines)):
            line = lines[index]
            if line and not line.startswith(" "):
                break
            match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
            if match is not None:
                starts.append((index, match.group(1)))
        for position, (start, job_id) in enumerate(starts):
            end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            for index in range(start + 1, len(lines)):
                if lines[index] and not lines[index].startswith(" "):
                    end = min(end, index)
                    break
            job_blocks.append((job_id, "\n".join(lines[start:end])))

    for name in authoritative_checks:
        candidates: list[str] = []
        for job_id, block in job_blocks:
            explicit_name = re.search(r"(?m)^    name:\s*['\"]?([^'\"#]+?)['\"]?\s*(?:#.*)?$", block)
            rendered_name = explicit_name.group(1).strip() if explicit_name is not None else job_id
            if rendered_name == name:
                candidates.append(block)
        if len(candidates) != 1:
            return None
        text = candidates[0]
        checkout_steps: list[str] = []
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)-\s*uses:\s*actions/checkout@([^\s#]+)(?:\s*#.*)?$", line)
            if match is None:
                continue
            indentation = len(match.group(1))
            step_lines = [line]
            for following in lines[index + 1 :]:
                list_item = re.match(r"^(\s*)-\s+", following)
                if list_item is not None and len(list_item.group(1)) <= indentation:
                    break
                step_lines.append(following)
            checkout_steps.append("\n".join(step_lines))
        if not checkout_steps:
            # A non-standard or expression-based checkout declaration cannot be
            # classified safely with the standard-library-only parser.
            if "actions/checkout@" in text:
                return None
            return False
        for checkout_step in checkout_steps:
            checkout = re.search(r"(?m)^\s*-\s*uses:\s*actions/checkout@[0-9a-f]{40}(?:\s*#.*)?$", checkout_step)
            full_history = re.search(r"(?m)^\s*fetch-depth:\s*0\s*$", checkout_step)
            no_credentials = re.search(r"(?m)^\s*persist-credentials:\s*false\s*$", checkout_step)
            if not (checkout and full_history and no_credentials):
                return False
    return True


def _main_configuration_matches(
    root: Path | None,
    main_sha: str,
    config: Mapping[str, Any],
) -> tuple[bool, str | None]:
    exact, error = _tagged_configuration(root, main_sha)
    if error is not None or not isinstance(exact, Mapping):
        return False, error or "Exact-Main repository-health configuration is unavailable."
    configured_standard = config.get("standard")
    configured_repository = config.get("repository")
    exact_standard = exact.get("standard")
    exact_repository = exact.get("repository")
    if not all(
        isinstance(item, Mapping)
        for item in (configured_standard, configured_repository, exact_standard, exact_repository)
    ):
        return False, "Repository-health configuration tables are incomplete."
    if configured_standard.get("version") != exact_standard.get("version"):
        return False, "Configured standard version differs from exact Main."
    for key in (
        "main_branch",
        "authoritative_checks",
        "deployable_units",
        "production_correspondence",
    ):
        if configured_repository.get(key) != exact_repository.get(key):
            return False, f"Configured repository.{key} differs from exact Main."
    return True, None


def _history_metric_records(prior_history: Any, metric_id: str) -> list[dict[str, Any]]:
    if not isinstance(prior_history, list):
        return []
    records: list[dict[str, Any]] = []
    for snapshot in prior_history:
        if not isinstance(snapshot, Mapping):
            continue
        assessment = snapshot.get("assessment") if isinstance(snapshot.get("assessment"), Mapping) else snapshot
        snapshot_generated_at = (
            assessment.get("generated_at")
            if isinstance(assessment, Mapping)
            else snapshot.get("generated_at")
        )
        candidates = (
            assessment.get("measurements")
            or assessment.get("metric_results")
            or assessment.get("metrics")
            if isinstance(assessment, Mapping)
            else None
        )
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, Mapping) or item.get("metric_id") != metric_id:
                    continue
                record = dict(item)
                record["__snapshot_generated_at"] = snapshot_generated_at
                records.append(record)
        elif isinstance(candidates, Mapping):
            item = candidates.get(metric_id)
            if isinstance(item, Mapping):
                record = dict(item)
                record.setdefault("metric_id", metric_id)
                record["__snapshot_generated_at"] = snapshot_generated_at
                records.append(record)
    return records


def _release_rows(
    refs_group: Mapping[str, Any] | None,
    attestations_group: Mapping[str, Any] | None,
    root: Path | None,
    main_sha: str,
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    limitations: list[str] = []
    if not _group_complete(refs_group):
        return [], False, ["Release/ref population is incomplete."]
    releases = _group_data(refs_group).get("releases")
    if not isinstance(releases, list):
        return [], False, ["Release population is not an array."]
    attested = _attestation_index(attestations_group)
    attestation_complete = _group_complete(attestations_group)
    rows: list[dict[str, Any]] = []
    complete = True
    for release in releases:
        if not isinstance(release, Mapping):
            complete = False
            continue
        target = release.get("tag_target")
        source_sha = target.get("peeled_sha") if isinstance(target, Mapping) else None
        ancestry = _git_ancestry(root, source_sha, main_sha) if isinstance(source_sha, str) else None
        assets = release.get("assets")
        stable_digest = isinstance(assets, list) and bool(assets) and all(isinstance(asset, Mapping) and _asset_digest(asset) is not None for asset in assets)
        all_attested = (
            attestation_complete
            and isinstance(assets, list)
            and bool(assets)
            and all(isinstance(asset, Mapping) and attested.get((release.get("id"), asset.get("id"))) is True for asset in assets)
        )
        if ancestry is None or not isinstance(source_sha, str):
            complete = False
        rows.append(
            {
                "id": release.get("id"),
                "release_id": release.get("id"),
                "tag": release.get("tag_name"),
                "source_sha": source_sha,
                "source_reachable_from_main": ancestry,
                "immutable_artifact_identity": bool(release.get("immutable") is True and stable_digest),
                "traceable": (
                    bool(release.get("immutable") is True and stable_digest and ancestry)
                    if ancestry is not None and isinstance(source_sha, str)
                    else None
                ),
                "immutable_identity": (
                    bool(release.get("immutable") is True and stable_digest and all_attested)
                    if attestation_complete
                    else None
                ),
                "overwritten": release.get("immutable") is False,
                "published_at": release.get("published_at"),
                "unit": None,
            }
        )
    if not attestation_complete:
        limitations.append("Artifact-attestation population is incomplete.")
    return rows, complete, limitations


def normalize_observations(
    raw_bundle: Mapping[str, Any],
    local_facts: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    production_identity: str | Path | bytes | Mapping[str, Any] | None = None,
    prior_history: Any = None,
) -> dict[str, Any]:
    """Augment raw observations with conservative metric-specific groups."""

    bundle = deepcopy(dict(raw_bundle))
    observations = bundle.get("observations")
    if bundle.get("schema_version") != OBSERVATION_SCHEMA or not isinstance(observations, Mapping):
        raise NormalizationError("raw observations use an unsupported or incomplete schema")
    observations = deepcopy(dict(observations))
    bundle["observations"] = observations
    repository = bundle.get("repository")
    main_sha = bundle.get("subject_sha")
    if not isinstance(repository, str) or REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise NormalizationError("raw observation repository identity is invalid")
    if not isinstance(main_sha, str) or SHA_PATTERN.fullmatch(main_sha) is None:
        raise NormalizationError("raw observation Main SHA is invalid")
    repository_config = config.get("repository")
    standard = config.get("standard")
    if not isinstance(repository_config, Mapping) or not isinstance(standard, Mapping):
        raise NormalizationError("loaded configuration lacks repository/standard tables")
    authoritative_checks = repository_config.get("authoritative_checks")
    units = repository_config.get("deployable_units")
    if not isinstance(authoritative_checks, list) or not authoritative_checks or not all(isinstance(item, str) and item for item in authoritative_checks):
        raise NormalizationError("repository.authoritative_checks must be nonempty")
    if not isinstance(units, list) or not units or not all(isinstance(item, str) and item for item in units):
        raise NormalizationError("repository.deployable_units must be nonempty")
    bundle["units"] = list(units)

    root = _safe_root(local_facts)
    normalization_conflicts: list[str] = []
    normalization_limitations: list[str] = []
    local_main = local_facts.get("main_sha")
    if isinstance(local_main, str) and local_main != main_sha:
        normalization_conflicts.append("Local Main SHA conflicts with the GitHub observation subject SHA.")
        root = None
    config_matches_main, config_binding_error = _main_configuration_matches(root, main_sha, config)
    if not config_matches_main:
        normalization_conflicts.append(
            config_binding_error or "Metric policy inputs are not bound to the exact assessed Main revision."
        )

    check_index, check_completeness, check_limitations = _check_index(bundle)
    normalization_limitations.extend(check_limitations)
    main_state, main_check_details = _check_state(check_index, main_sha, authoritative_checks)
    main_complete = (
        (check_completeness["current"] or check_completeness["w365"])
        and main_state in {"success", "failure"}
        and not normalization_conflicts
    )
    observations["M-SPI-01"] = _purpose_group(
        "M-SPI-01",
        bundle,
        {
            "items": [
                {
                    "id": main_sha,
                    "unit": unit,
                    "valid": main_state == "success" if main_state in {"success", "failure"} else None,
                    "exact_main_sha": True,
                    "authoritative_results_terminal": main_state in {"success", "failure"},
                    "all_required_checks_succeeded": main_state == "success" if main_state in {"success", "failure"} else None,
                    "type_contract_satisfied": main_state == "success" if main_state in {"success", "failure"} else None,
                    "checks": main_check_details,
                }
                for unit in units
            ]
        },
        complete=main_complete,
        evidence_ids=_evidence_ids(_raw_group(bundle, "check_runs"), _raw_group(bundle, "actions_w90"), _raw_group(bundle, "actions_w365"), extra=["E-CONFIG-AUTHORITATIVE-CHECKS"]),
        gaps=[] if main_complete else ["Exact Main authoritative-check evidence is incomplete or nonterminal."],
    )

    # Strict production identity loading is itself evidence.  Invalid or absent
    # declarations do not stop the report; they make production metrics Unknown.
    production: dict[str, Any] | None = None
    production_error: str | None = None
    exact_main_source: bytes | None = None
    if root is not None:
        content, content_error = _git(
            root,
            "show",
            f"{main_sha}:.github/repository-health-production.json",
        )
        if content_error is None:
            exact_main_source = content.encode("utf-8")
        else:
            production_error = "Exact-Main machine-readable production identity is unavailable."
    source = exact_main_source if production_identity is None else production_identity
    if production_identity is not None:
        if exact_main_source is None:
            normalization_conflicts.append(
                "Caller-supplied production identity cannot be bound to the exact assessed Main revision."
            )
        else:
            try:
                supplied_identity = load_production_identity(
                    production_identity,
                    config=config,
                    repository=repository,
                )
                exact_identity = load_production_identity(
                    exact_main_source,
                    config=config,
                    repository=repository,
                )
                if supplied_identity != exact_identity:
                    normalization_conflicts.append(
                        "Caller-supplied production identity differs from exact Main."
                    )
            except (NormalizationError, OSError) as error:
                normalization_conflicts.append(
                    f"Caller-supplied production identity cannot be matched to exact Main: {error}"
                )
    if source is not None:
        try:
            production = load_production_identity(source, config=config, repository=repository)
        except (NormalizationError, OSError) as error:
            production_error = str(error)
            normalization_conflicts.append(f"Production identity is invalid: {error}")
    else:
        production_error = "Machine-readable production identity is unavailable."

    refs_group = _raw_group(bundle, "refs_releases")
    attestations_group = _raw_group(bundle, "attestations")
    rules_group = _raw_group(bundle, "rules")
    release_rows, release_rows_complete, release_limitations = _release_rows(refs_group, attestations_group, root, main_sha)
    normalization_limitations.extend(release_limitations)
    contents = _asset_contents(local_facts, refs_group)
    raw_releases = _group_data(refs_group).get("releases")
    raw_releases = raw_releases if isinstance(raw_releases, list) else []
    # Repository configuration and an empty GitHub Releases response are not
    # enough to prove that a unit has no deployed, published, distributed, or
    # supported output.  A type-appropriate governance/portfolio/delivery
    # resolver must establish that N/A independently; until that adapter is
    # available this normalized metric remains Unknown.
    explicitly_no_current_output = False
    has_current_output = repository_config.get("has_current_output")
    if (
        (has_current_output is False or str(has_current_output).lower() == "false")
        and repository_config.get("production_correspondence") == "N/A"
        and _group_complete(refs_group)
        and not raw_releases
    ):
        normalization_limitations.append(
            "The no-current-output declaration and empty GitHub Releases population require "
            "independent governance, consumer, and delivery-system verification before N/A can be awarded."
        )

    current_rows: list[dict[str, Any]] = []
    correspondence_rows: list[dict[str, Any]] = []
    current_complete = production is not None and _group_complete(refs_group) and _group_complete(attestations_group) and root is not None
    current_reasons: list[str] = []
    current_validated_by_unit: dict[str, bool | None] = {}
    current_release_by_unit: dict[str, Mapping[str, Any]] = {}

    if production is None:
        current_complete = False
        current_reasons.append(production_error or "Production identity is unavailable.")
    else:
        version = str(standard.get("version"))
        attested_assets = _attestation_index(attestations_group)
        for unit in production["units"]:
            unit_id = unit["unit_id"]
            if production.get("schema_version") == GENERIC_PRODUCTION_SCHEMA:
                profile = unit["profile"]
                normalization_limitations.extend(unit.get("limitations", []))
                if profile == "package-github-release":
                    reason = (
                        f"{unit_id} declares exact GitHub release assets, but the generic resolver does not yet "
                        "establish observed source-to-artifact provenance."
                    )
                elif profile in {
                    "application-github-deployment",
                    "gitops-production-ref",
                    "documentation-publication",
                }:
                    reason = (
                        f"{unit_id} uses {profile}; its delivery system-of-record resolver is not yet available."
                    )
                elif profile == "approved-no-current-output":
                    reason = (
                        f"{unit_id} has a declarative no-current-output decision whose authority, applicability, "
                        "and review-date freshness have not been independently verified."
                    )
                else:
                    reason = (
                        f"{unit_id} has a declarative archive disposition whose authority, effective state, "
                        "write protection, and last-known source reachability have not been independently verified."
                    )
                row_reasons = [reason]
                normalization_limitations.extend(row_reasons)
                current_reasons.extend(row_reasons)
                current_complete = False
                current_validated_by_unit[unit_id] = None
                current_rows.append(
                    {
                        "id": f"current-{unit_id}",
                        "unit": unit_id,
                        "profile": profile,
                        "immutable_source_revision": None,
                        "source_reachable_from_main": None,
                        "immutable_artifact_identity": None,
                        "successful_current_status": None,
                        "traceable": None,
                        "reasons": row_reasons,
                    }
                )
                correspondence_rows.append(
                    {
                        "id": f"current-{unit_id}",
                        "unit": unit_id,
                        "profile": profile,
                        "is_current": True,
                        "contract": unit["correspondence"],
                        "production_sha": unit["source_sha"],
                        "main_sha": main_sha,
                        "reachable_from_main": None,
                        "intervening_gates_passed": None,
                        "conforming": None,
                        "source_checks": {},
                        "intervening_revisions": {},
                    }
                )
                continue
            expected = unit["current"]
            normalization_limitations.extend(unit.get("limitations", []))
            matches = [
                release
                for release in raw_releases
                if isinstance(release, Mapping)
                and (release.get("id") == expected["release_id"] or release.get("tag_name") == expected["tag"])
            ]
            row_reasons: list[str] = []
            traceable: bool | None
            if len(matches) != 1:
                traceable = False if _group_complete(refs_group) else None
                row_reasons.append("Expected current release is missing or ambiguous.")
                release: Mapping[str, Any] = {}
            else:
                release = matches[0]
                current_release_by_unit[unit_id] = release
                target = release.get("tag_target")
                target = target if isinstance(target, Mapping) else {}
                source_sha = target.get("peeled_sha")
                tag_object_sha = target.get("object_sha")
                ancestry = _git_ancestry(root, expected["source_sha"], main_sha)
                revisions = _intervening_revisions(root, expected["source_sha"], main_sha)
                source_state, source_checks = _check_state(check_index, expected["source_sha"], authoritative_checks)
                intervening_states: dict[str, Any] = {}
                if revisions is not None:
                    for revision in revisions:
                        state, detail = _check_state(check_index, revision, authoritative_checks)
                        intervening_states[revision] = {"state": state, "checks": detail}
                intervening_known = revisions is not None and all(item["state"] in {"success", "failure"} for item in intervening_states.values())
                intervening_passed = intervening_known and all(item["state"] == "success" for item in intervening_states.values())
                source_validated = source_state == "success" if source_state in {"success", "failure"} else None
                current_validated_by_unit[unit_id] = source_validated

                live_assets = release.get("assets")
                live_assets = live_assets if isinstance(live_assets, list) else []
                live_by_name = {asset.get("name"): asset for asset in live_assets if isinstance(asset, Mapping) and isinstance(asset.get("name"), str)}
                expected_names = {artifact["name"] for artifact in expected["artifacts"]}
                assets_match = set(live_by_name) == expected_names
                if set(live_by_name) != expected_names:
                    row_reasons.append("Live release asset inventory conflicts with the controlled five-asset set.")
                for artifact in expected["artifacts"]:
                    live = live_by_name.get(artifact["name"])
                    if not isinstance(live, Mapping) or _asset_digest(live) != artifact["sha256"]:
                        assets_match = False
                        row_reasons.append(f"Release asset identity mismatch: {artifact['name']}")
                all_assets_attested = all(
                    isinstance(live_by_name.get(artifact["name"]), Mapping)
                    and attested_assets.get(
                        (release.get("id"), live_by_name[artifact["name"]].get("id"))
                    )
                    is True
                    for artifact in expected["artifacts"]
                )

                identity_artifact = next(artifact for artifact in expected["artifacts"] if artifact["role"] == "release-identity")
                checksum_artifact = next(artifact for artifact in expected["artifacts"] if artifact["role"] == "checksum-manifest")
                identity_content = contents.get(identity_artifact["name"])
                checksum_content = contents.get(checksum_artifact["name"])
                tagged_config, tagged_error = _tagged_configuration(root, expected["source_sha"])
                tagged_version_valid: bool | None = None
                tagged_correspondence: str | None = None
                disclosed_unknown_migration = False
                if tagged_config is not None:
                    tagged_version_valid = tagged_config.get("standard", {}).get("version") == version
                    tagged_correspondence_value = tagged_config.get("repository", {}).get("production_correspondence")
                    tagged_correspondence = tagged_correspondence_value if isinstance(tagged_correspondence_value, str) else None
                    if tagged_correspondence == "Unknown":
                        message = (
                            f"{unit_id} release source declared production correspondence Unknown; "
                            "current Main establishes Releasable-Main after publication."
                        )
                        normalization_limitations.append(message)
                        row_reasons.append(message)
                        disclosed_unknown_migration = any(
                            "production correspondence Unknown" in limitation
                            for limitation in unit.get("limitations", [])
                            if isinstance(limitation, str)
                        )
                elif tagged_error:
                    row_reasons.append(tagged_error)

                # Download every controlled asset and independently hash its
                # bytes.  API-reported digest metadata alone is not treated as
                # content verification.
                content_known = all(artifact["name"] in contents for artifact in expected["artifacts"])
                content_valid = False
                if content_known and identity_content is not None and checksum_content is not None:
                    accepted_correspondence = (
                        "Unknown"
                        if tagged_correspondence == "Unknown" and disclosed_unknown_migration
                        else unit["correspondence"]
                    )
                    identity_valid, identity_problems = _validate_release_identity_content(
                        identity_content,
                        repository=repository,
                        version=version,
                        unit=unit,
                        correspondence=accepted_correspondence,
                    )
                    manifest = _parse_checksum_manifest(checksum_content)
                    expected_manifest = {
                        artifact["name"]: artifact["sha256"]
                        for artifact in expected["artifacts"]
                        if artifact["role"] in {"source-package", "sbom", "release-identity"}
                    }
                    manifest_valid = manifest == expected_manifest
                    content_digest_valid = all(
                        _digest(contents[artifact["name"]]) == artifact["sha256"]
                        for artifact in expected["artifacts"]
                    )
                    content_valid = identity_valid and manifest_valid and content_digest_valid
                    row_reasons.extend(identity_problems)
                    if not manifest_valid:
                        row_reasons.append("Downloaded SHA256SUMS conflicts with the controlled artifacts.")
                    if not content_digest_valid:
                        row_reasons.append("Downloaded release bytes conflict with one or more controlled asset digests.")
                else:
                    row_reasons.append("The complete controlled release asset set was not downloaded for verification.")

                exact_matches = [
                    release.get("id") == expected["release_id"],
                    release.get("tag_name") == expected["tag"],
                    release.get("html_url") == expected["release_url"],
                    release.get("published_at") == expected["published_at"],
                    isinstance(release.get("published_at"), str),
                    (release.get("draft") is False or unit["selection"]["allow_draft"] is True),
                    (release.get("prerelease") is False or unit["selection"]["allow_prerelease"] is True),
                    release.get("immutable") is expected["immutable"] is True,
                    target.get("annotated") is True,
                    target.get("peel_complete") is True,
                    target.get("peeled_type") == "commit",
                    source_sha == expected["source_sha"],
                    tag_object_sha == expected["tag_object_sha"],
                    assets_match,
                    all_assets_attested,
                    content_valid,
                    tagged_version_valid is True,
                    ancestry is True,
                    source_validated is True,
                    intervening_passed,
                ]
                unknown_inputs = any(
                    value is None
                    for value in (ancestry, source_validated, tagged_version_valid)
                ) or tagged_correspondence is None or not intervening_known or not content_known or not _group_complete(attestations_group)
                traceable = None if unknown_inputs else all(exact_matches)
                if source_state == "failure" or ancestry is False or any(item["state"] == "failure" for item in intervening_states.values()):
                    traceable = False
                tag_assertions, _ = _ref_assertions(
                    rules_group,
                    ref=f"refs/tags/{expected['tag']}",
                    main_ref=f"refs/heads/{repository_config.get('main_branch')}",
                    authoritative_checks=authoritative_checks,
                    immutable_release=release.get("immutable") is True,
                    validated_release=source_validated is True,
                )
                tag_protected = all(value is True for key, value in tag_assertions.items() if key in {"restricted_update", "deletion_protection", "force_push_protection"})
                if not tag_protected:
                    traceable = None if any(tag_assertions[key] is None for key in ("restricted_update", "deletion_protection", "force_push_protection")) else False
                    row_reasons.append("Current release tag protection is incomplete.")

                correspondence = None
                if ancestry is not None and intervening_known:
                    if unit["correspondence"] == "Exact-Main":
                        correspondence = expected["source_sha"] == main_sha
                    elif unit["correspondence"] == "Releasable-Main":
                        correspondence = ancestry and intervening_passed
                    else:
                        correspondence = None
                correspondence_rows.append(
                    {
                        "id": f"current-{unit_id}",
                        "unit": unit_id,
                        "is_current": True,
                        "contract": unit["correspondence"],
                        "production_sha": expected["source_sha"],
                        "main_sha": main_sha,
                        "reachable_from_main": ancestry,
                        "intervening_gates_passed": intervening_passed if intervening_known else None,
                        "conforming": correspondence,
                        "source_checks": source_checks,
                        "intervening_revisions": intervening_states,
                    }
                )

            if row_reasons:
                normalization_limitations.extend(row_reasons)
            current_rows.append(
                {
                    "id": f"current-{unit_id}",
                    "unit": unit_id,
                    "immutable_source_revision": traceable if traceable is not None else None,
                    "source_reachable_from_main": traceable if traceable is not None else None,
                    "immutable_artifact_identity": traceable if traceable is not None else None,
                    "successful_current_status": traceable if traceable is not None else None,
                    "traceable": traceable,
                    "reasons": row_reasons,
                }
            )
            if traceable is None:
                current_complete = False

    observations["M-SPI-02S"] = _purpose_group(
        "M-SPI-02S",
        bundle,
        {"items": current_rows},
        complete=current_complete and bool(current_rows),
        evidence_ids=_evidence_ids(refs_group, attestations_group, rules_group, extra=["E-PRODUCTION-IDENTITY", "E-LOCAL-GIT", "E-RELEASE-CONTENT"]),
        limitations=normalization_limitations,
        gaps=[] if current_complete and current_rows else current_reasons or ["Current publication identity cannot be completely resolved."],
    )

    for row in release_rows:
        for unit in units:
            row.setdefault("unit", unit if len(units) == 1 else None)
    observations["M-SPI-02"] = _purpose_group(
        "M-SPI-02",
        bundle,
        {"items": release_rows, "no_events": not release_rows},
        complete=release_rows_complete,
        evidence_ids=_evidence_ids(refs_group, extra=["E-LOCAL-GIT"]),
        limitations=release_limitations,
        gaps=[] if release_rows_complete else release_limitations,
    )
    observations["M-SPI-03"] = _purpose_group(
        "M-SPI-03",
        bundle,
        {
            "items": release_rows,
            "inventory_complete": release_rows_complete and _group_complete(attestations_group),
            "no_current_supported_release": explicitly_no_current_output,
            "no_w365_releases": not release_rows,
        },
        complete=release_rows_complete and _group_complete(attestations_group),
        evidence_ids=_evidence_ids(refs_group, attestations_group, rules_group),
        limitations=release_limitations,
        gaps=[] if release_rows_complete and _group_complete(attestations_group) else ["Release identity/provenance population is incomplete."],
    )

    history_correspondence = _history_metric_records(prior_history, "M-SPI-04")
    daily_rows: list[dict[str, Any]] = []
    history_complete_by_unit: dict[str, bool] = {}
    current_instant = _parse_instant(bundle.get("observed_at"))
    for unit_id in units:
        by_date: dict[Any, tuple[datetime, dict[str, Any]]] = {}
        for index, record in enumerate(history_correspondence):
            record_unit = record.get("unit_id")
            if record_unit not in {unit_id, None} or (len(units) > 1 and record_unit is None):
                continue
            components = record.get("components")
            current_conforms = components.get("current_conforms") if isinstance(components, Mapping) else None
            current_assurance = components.get("current_evidence_assurance") if isinstance(components, Mapping) else None
            snapshot_instant = _parse_instant(record.get("__snapshot_generated_at"))
            if not isinstance(current_conforms, bool) or current_assurance not in {"E3", "E4"} or snapshot_instant is None:
                continue
            row = {
                "id": f"history-{unit_id}-{index}",
                "unit": unit_id,
                "conforming": current_conforms,
                "is_current": False,
                "observed_at": snapshot_instant.isoformat(),
            }
            prior = by_date.get(snapshot_instant.date())
            if prior is None or snapshot_instant > prior[0]:
                by_date[snapshot_instant.date()] = (snapshot_instant, row)
        expected_dates = (
            [current_instant.date() - timedelta(days=offset) for offset in range(1, 91)]
            if current_instant is not None
            else []
        )
        unit_complete = bool(expected_dates) and all(day in by_date for day in expected_dates)
        history_complete_by_unit[unit_id] = unit_complete
        if unit_complete:
            daily_rows.extend(by_date[day][1] for day in sorted(expected_dates))
    current_correspondence_complete = bool(correspondence_rows) and all(
        isinstance(row.get("conforming"), bool) for row in correspondence_rows
    )
    correspondence_history_complete = all(history_complete_by_unit.get(unit) is True for unit in units)
    observations["M-SPI-04"] = _purpose_group(
        "M-SPI-04",
        bundle,
        {
            "items": [*daily_rows, *correspondence_rows],
            "history_complete": correspondence_history_complete,
            "required_daily_snapshots": 90,
            "history_complete_by_unit": history_complete_by_unit,
        },
        complete=current_correspondence_complete,
        evidence_ids=_evidence_ids(refs_group, extra=["E-PRODUCTION-IDENTITY", "E-LOCAL-GIT", "E-EVIDENCE-HISTORY"]),
        limitations=normalization_limitations,
        gaps=[] if current_correspondence_complete else [
            "Current production correspondence cannot be resolved."
        ],
    )

    # Main and critical-ref governance.
    main_ref = f"refs/heads/{repository_config.get('main_branch')}"
    main_assertions, bypass_impossible = _ref_assertions(
        rules_group,
        ref=main_ref,
        main_ref=main_ref,
        authoritative_checks=authoritative_checks,
    )
    critical_rows = [{"ref": main_ref, "unit": unit, "assertions": main_assertions} for unit in units]
    unresolved_generic_ref_inventory = False
    for unit in production["units"] if production else []:
        if production.get("schema_version") == PRODUCTION_SCHEMA:
            critical_ref = f"refs/tags/{unit['current']['tag']}"
        elif unit["profile"] == "package-github-release":
            critical_ref = f"refs/tags/{unit['selector']['tag']}"
        elif unit["profile"] == "gitops-production-ref":
            critical_ref = unit["selector"]["production_ref"]
        else:
            # Deployment/publication targets and governance dispositions need
            # profile-specific authoritative inventory proof before the set of
            # production-critical references can be called complete.
            unresolved_generic_ref_inventory = True
            continue
        release = current_release_by_unit.get(unit["unit_id"], {})
        assertions, _ = _ref_assertions(
            rules_group,
            ref=critical_ref,
            main_ref=main_ref,
            authoritative_checks=authoritative_checks,
            immutable_release=release.get("immutable") is True,
            validated_release=current_validated_by_unit.get(unit["unit_id"]) is True,
        )
        critical_rows.append({"ref": critical_ref, "unit": unit["unit_id"], "assertions": assertions})
    production_ref_inventory_complete = (
        (production is not None and not unresolved_generic_ref_inventory)
        or (explicitly_no_current_output and production is None)
    )
    critical_complete = _group_complete(rules_group) and production_ref_inventory_complete and all(
        isinstance(value, bool)
        for row in critical_rows
        for value in row["assertions"].values()
    )
    observations["M-CGD-02"] = _purpose_group(
        "M-CGD-02",
        bundle,
        {"items": critical_rows},
        complete=critical_complete,
        evidence_ids=_evidence_ids(rules_group, refs_group, extra=["E-PRODUCTION-IDENTITY"]),
        gaps=[] if critical_complete else [
            "Effective rules are partial, the production-critical-ref inventory is incomplete, or an assertion is unresolved."
        ],
    )

    change_group = _raw_group(bundle, "change_history")
    change_data = _group_data(change_group)
    reachable_commits = change_data.get("reachable_commits")
    if not isinstance(reachable_commits, list):
        # Retain compatibility with the pre-topology collector shape while
        # never treating that list as authoritative when the new shape exists.
        reachable_commits = change_data.get("commits")
    links = change_data.get("commit_pr_links")
    pull_requests = change_data.get("associated_pull_requests")
    reviews = change_data.get("reviews")
    reachable_commits = reachable_commits if isinstance(reachable_commits, list) else []
    links = links if isinstance(links, list) else []
    pull_requests = pull_requests if isinstance(pull_requests, list) else []
    reviews = reviews if isinstance(reviews, list) else []
    reachable_by_sha = {
        item.get("sha"): item
        for item in reachable_commits
        if isinstance(item, Mapping) and isinstance(item.get("sha"), str)
    }
    most_recent_commit = change_data.get("most_recent_commit")
    if isinstance(most_recent_commit, Mapping) and isinstance(most_recent_commit.get("sha"), str):
        reachable_by_sha.setdefault(most_recent_commit["sha"], most_recent_commit)
    link_by_sha = {item.get("commit_sha"): item.get("pull_numbers") for item in links if isinstance(item, Mapping)}
    pull_by_number = {item.get("number"): item for item in pull_requests if isinstance(item, Mapping)}
    reviews_by_number = {item.get("pull_number"): item for item in reviews if isinstance(item, Mapping)}

    first_parent, first_parent_complete = _first_parent_history(root, main_sha)
    observed_instant = _parse_instant(bundle.get("observed_at"))
    local_main_matches = local_facts.get("main_sha") == main_sha
    history_time_complete = bool(
        observed_instant is not None
        and first_parent
        and all(row["accepted_at"] <= observed_instant for row in first_parent)
    )
    window_90_start = observed_instant - timedelta(days=90) if observed_instant else None
    window_365_start = observed_instant - timedelta(days=365) if observed_instant else None
    w90_revisions = (
        [row for row in first_parent if row["accepted_at"] > window_90_start]
        if window_90_start is not None
        else []
    )
    w365_revisions = (
        [row for row in first_parent if row["accepted_at"] > window_365_start]
        if window_365_start is not None
        else []
    )
    if w90_revisions:
        selected_revisions = w90_revisions
        selected_window_days = 90
    elif w365_revisions:
        selected_revisions = w365_revisions
        selected_window_days = 365
    else:
        selected_revisions = []
        selected_window_days = 90

    change_transport_complete = _change_transport_complete(change_group, change_data)
    most_recent_basis = change_data.get("most_recent_commit_basis")
    low_activity_basis_complete = bool(
        isinstance(most_recent_basis, Mapping)
        and most_recent_basis.get("complete") is True
        and most_recent_basis.get("no_reachable_commits_w365") is True
        and most_recent_basis.get("older_than_w365") is True
        and first_parent
        and isinstance(most_recent_commit, Mapping)
        and most_recent_commit.get("sha") == first_parent[-1]["sha"]
    )

    change_rows: list[dict[str, Any]] = []
    enforcement_rows: list[dict[str, Any]] = []

    def audit_revision(revision: Mapping[str, Any]) -> tuple[dict[str, Any], bool | None, bool | None]:
        sha = revision.get("sha")
        if not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None:
            return {"id": sha, "complete": None}, None, None
        api_commit = reachable_by_sha.get(sha)
        numbers = link_by_sha.get(sha)
        numbers = numbers if isinstance(numbers, list) else []
        pulls = [pull_by_number.get(number) for number in numbers]
        pulls = [pull for pull in pulls if isinstance(pull, Mapping)]
        exact_pulls: list[Mapping[str, Any]] = []
        for pull in pulls:
            base = pull.get("base")
            base_ref = base.get("ref") if isinstance(base, Mapping) else None
            if (
                pull.get("merge_commit_sha") == sha
                and _parse_instant(pull.get("merged_at")) is not None
                and base_ref == repository_config.get("main_branch")
            ):
                exact_pulls.append(pull)
        check_state, details = _check_state(check_index, sha, authoritative_checks)
        exact_pr = len(exact_pulls) == 1
        actor: str | None = None
        acceptance: str | None = None
        authorization: dict[str, Any] | None = None
        review_population_complete = False
        historical_enforcement: bool | None = None
        if exact_pr:
            pull = exact_pulls[0]
            merged_by = pull.get("merged_by")
            actor = merged_by.get("login") if isinstance(merged_by, Mapping) else None
            acceptance = pull.get("merged_at") if isinstance(pull.get("merged_at"), str) else None
            review_record = reviews_by_number.get(pull.get("number"))
            review_items = review_record.get("reviews") if isinstance(review_record, Mapping) else None
            review_population_complete = bool(
                isinstance(review_record, Mapping)
                and review_record.get("complete") is True
                and review_record.get("population_complete") is True
                and isinstance(review_items, list)
            )
            if review_population_complete:
                authorization = {
                    "kind": "merged_pull_request",
                    "pull_number": pull.get("number"),
                    "review_count": len(review_items),
                    "merged_by": actor,
                }
            explicit_enforcement = pull.get("blocked_until_final_checks_succeeded")
            historical_enforcement = explicit_enforcement if isinstance(explicit_enforcement, bool) else None

        detail_sources = {
            detail.get("source_group")
            for detail in details.values()
            if isinstance(detail, Mapping)
        }
        check_population_complete = check_state in {"success", "failure"} and all(
            source == "check_runs" and check_completeness.get("current") is True
            or source == "actions_w90" and check_completeness.get("w90") is True
            or source == "actions_w365" and check_completeness.get("w365") is True
            for source in detail_sources
        ) and len(detail_sources) > 0

        bypass_used, bypass_fields, bypass_complete = _historical_bypass(change_data, sha)
        resolved = all(
            (
                isinstance(api_commit, Mapping),
                exact_pr,
                isinstance(actor, str) and bool(actor),
                isinstance(acceptance, str) and bool(acceptance),
                authorization is not None,
                review_population_complete,
                check_population_complete,
                isinstance(bypass_used, bool),
                bypass_complete,
            )
        )
        row: dict[str, Any] = {
            "id": sha,
            "unit": units[0] if len(units) == 1 else None,
            "complete": True if resolved else None,
            "final_revision": sha,
            "actor": actor,
            "authorization": authorization,
            "required_checks": details if check_population_complete else None,
            "acceptance_event": acceptance,
            "bypass_used": bypass_used,
            "first_parent": True,
            "first_parent_position": next(
                (index for index, item in enumerate(first_parent) if item["sha"] == sha),
                None,
            ),
        }
        row.update(bypass_fields)
        return row, row["complete"], historical_enforcement

    selected_audits: list[tuple[dict[str, Any], bool | None, bool | None]] = [
        audit_revision(revision) for revision in selected_revisions
    ]
    change_rows = [row for row, _, _ in selected_audits]
    enforcement_rows = [
        {
            "id": row.get("id"),
            "unit": row.get("unit"),
            "accepted": True,
            "blocked_until_final_checks_succeeded": historical_enforcement,
        }
        for row, _, historical_enforcement in selected_audits
    ]

    last_audit: tuple[dict[str, Any], bool | None, bool | None] | None = None
    if not selected_revisions and first_parent:
        last_audit = audit_revision(first_parent[-1])

    current_enforcement = all(value is True for value in main_assertions.values()) if all(isinstance(value, bool) for value in main_assertions.values()) else None
    base_population_complete = bool(
        first_parent_complete
        and history_time_complete
        and local_main_matches
        and change_transport_complete
    )
    if selected_revisions:
        historical_population_complete = base_population_complete and all(
            complete is not None for _, complete, _ in selected_audits
        )
        last_complete = selected_audits[-1][1]
    else:
        historical_population_complete = bool(
            base_population_complete
            and low_activity_basis_complete
            and last_audit is not None
            and last_audit[1] is not None
        )
        last_complete = last_audit[1] if last_audit else None

    change_observation_complete = historical_population_complete and current_enforcement is not None
    # Downstream BTC normalizers consume the same accepted-revision population;
    # keep their completeness predicate bound to the reconstructed first-parent
    # history rather than the raw reachable-commit API list.
    change_complete = historical_population_complete
    change_payload: dict[str, Any] = {
        "items": change_rows,
        "current_enforcement": current_enforcement,
        "last_accepted_change_complete": last_complete,
        "accepted_main_population_source": "local_git_first_parent",
        "accepted_main_revisions_complete": first_parent_complete and local_main_matches,
        "historical_bypass_complete": change_data.get("historical_bypass_complete") is True,
        "window": {
            "kind": "rolling",
            "days": selected_window_days,
            "start": (
                (window_90_start if selected_window_days == 90 else window_365_start).isoformat()
                if observed_instant is not None
                else None
            ),
            "end": observed_instant.isoformat() if observed_instant else None,
        },
        "no_events": not selected_revisions,
        "no_changes_w90": not w90_revisions,
        "low_activity_basis_complete": low_activity_basis_complete,
    }
    if last_audit is not None:
        change_payload["most_recent_accepted_revision"] = last_audit[0]

    governance_group = _purpose_group(
        "M-CGD-01",
        bundle,
        change_payload,
        complete=change_observation_complete,
        evidence_ids=_evidence_ids(change_group, rules_group, _raw_group(bundle, "actions_w365"), extra=["E-LOCAL-GIT-FIRST-PARENT"]),
        gaps=[] if change_observation_complete else [
            "Exact first-parent Main population, API audit linkage, historical bypass accountability, or current enforcement is incomplete."
        ],
    )
    governance_group["assurance"] = "E3" if change_observation_complete else "E2"
    observations["M-CGD-01"] = governance_group

    enforcement_tested = local_facts.get("enforcement_tested")
    if selected_revisions:
        enforcement_history_complete = base_population_complete and all(
            isinstance(row.get("blocked_until_final_checks_succeeded"), bool)
            for row in enforcement_rows
        )
    else:
        enforcement_history_complete = bool(
            base_population_complete
            and low_activity_basis_complete
            and isinstance(enforcement_tested, bool)
        )
    enforcement_group = _purpose_group(
        "M-CGD-04",
        bundle,
        {
            "changes": enforcement_rows,
            "tested_enforcement": enforcement_tested is True,
            "no_events": not selected_revisions,
            "no_changes_w90": not w90_revisions,
        },
        complete=enforcement_history_complete and current_enforcement is True,
        evidence_ids=_evidence_ids(change_group, rules_group, _raw_group(bundle, "actions_w365"), extra=["E-LOCAL-GIT-FIRST-PARENT"]),
        gaps=[] if enforcement_history_complete and current_enforcement is True else [
            "Historical required-check enforcement is not demonstrated, or no-change enforcement was not locally tested."
        ],
    )
    enforcement_group["assurance"] = (
        "E3" if enforcement_history_complete and current_enforcement is True else "E2"
    )
    observations["M-CGD-04"] = enforcement_group

    # Build and change-CI metrics.
    workflow_contract = _workflow_contract(root, main_sha, authoritative_checks)
    build_rows: list[dict[str, Any]] = []
    known_shas = sorted({sha for sha, name in check_index if name in authoritative_checks})
    for sha in known_shas:
        state, detail = _check_state(check_index, sha, authoritative_checks)
        if state == "unknown":
            continue
        completed = [
            record.get("completed_at")
            for check in detail.values()
            if isinstance(check, Mapping) and isinstance(record := check, Mapping) and isinstance(record.get("completed_at"), str)
        ]
        build_rows.append(
            {
                "id": sha,
                "main_sha": sha,
                "unit": units[0] if len(units) == 1 else None,
                "eligible": True,
                "authoritative_replay": True,
                "clean_checkout": workflow_contract,
                "non_interactive": workflow_contract,
                "declared_inputs": workflow_contract,
                "successful": state == "success",
                "completed_at": max(completed) if completed else None,
            }
        )
    build_complete = check_completeness["w365"] and workflow_contract is not None and bool(build_rows)
    observations["M-BTC-01"] = _purpose_group(
        "M-BTC-01",
        bundle,
        {"replays": build_rows},
        complete=build_complete,
        evidence_ids=_evidence_ids(_raw_group(bundle, "actions_w365"), _raw_group(bundle, "check_runs"), extra=["E-LOCAL-WORKFLOW-CONTRACT"]),
        gaps=[] if build_complete else ["Clean authoritative replay classification is incomplete."],
    )

    ci_rows: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []
    for row in change_rows:
        sha = row["final_revision"]
        state, details = _check_state(check_index, sha, authoritative_checks)
        automatic_values = [detail.get("automatic") for detail in details.values() if isinstance(detail, Mapping)]
        automatic = bool(automatic_values) and all(value is True for value in automatic_values)
        ci_rows.append(
            {
                "id": sha,
                "unit": row.get("unit"),
                "all_applicable_workflows_triggered": state == "success" and automatic if state != "unknown" else None,
            }
        )
        created_values = [detail.get("run_created_at") for detail in details.values() if isinstance(detail, Mapping) and isinstance(detail.get("run_created_at"), str)]
        completed_values = [detail.get("completed_at") for detail in details.values() if isinstance(detail, Mapping) and isinstance(detail.get("completed_at"), str)]
        if created_values and len(completed_values) == len(authoritative_checks):
            try:
                start = min(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in created_values)
                end = max(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in completed_values)
                latency = max(0.0, (end - start).total_seconds() / 60.0)
            except ValueError:
                latency = None
            latency_rows.append({"id": sha, "unit": row.get("unit"), "latency_minutes": latency, "completed_at": max(completed_values)})
    ci_complete = change_complete and all(row.get("all_applicable_workflows_triggered") is not None for row in ci_rows)
    observations["M-BTC-02"] = _purpose_group(
        "M-BTC-02",
        bundle,
        {"changes": ci_rows, "current_trigger_enforcement": main_assertions.get("required_acceptance_checks")},
        complete=ci_complete,
        evidence_ids=_evidence_ids(change_group, _raw_group(bundle, "actions_w365"), rules_group),
        gaps=[] if ci_complete else ["Per-change automatic final-revision CI linkage is incomplete."],
    )

    category_basis = local_facts.get("validation_categories")
    category_rows: list[dict[str, Any]] = []
    if isinstance(category_basis, list) and category_basis and all(isinstance(item, str) and item for item in category_basis):
        for change in ci_rows:
            for category in category_basis:
                category_rows.append({"id": f"{change['id']}:{category}", "unit": change.get("unit"), "category": category, "mapping_complete": True, "successful": change.get("all_applicable_workflows_triggered")})
    category_complete = bool(category_rows) and all(row.get("successful") is not None for row in category_rows)
    observations["M-BTC-03"] = _purpose_group(
        "M-BTC-03",
        bundle,
        {"category_pairs": category_rows},
        complete=category_complete,
        evidence_ids=_evidence_ids(change_group, _raw_group(bundle, "actions_w365"), extra=["E-VALIDATION-CATEGORY-BASIS"]),
        gaps=[] if category_complete else ["A complete versioned validation-category basis is unavailable."],
    )

    latency_complete = change_complete and bool(latency_rows) and all(isinstance(row.get("latency_minutes"), (int, float)) for row in latency_rows)
    observations["M-BTC-04"] = _purpose_group(
        "M-BTC-04",
        bundle,
        {"latencies": latency_rows, "slo_minutes": local_facts.get("feedback_slo_minutes", 30)},
        complete=latency_complete,
        evidence_ids=_evidence_ids(change_group, _raw_group(bundle, "actions_w365")),
        gaps=[] if latency_complete else ["Comparable proposed-revision feedback timestamps are incomplete."],
    )

    actions_group = _raw_group(bundle, "actions_w365")
    attempts = _group_data(actions_group).get("run_attempts")
    attempts = attempts if isinstance(attempts, list) else []
    attempts_by_run: dict[int, list[Mapping[str, Any]]] = {}
    for attempt in attempts:
        if isinstance(attempt, Mapping) and isinstance(attempt.get("run_id"), int):
            attempts_by_run.setdefault(attempt["run_id"], []).append(attempt)
    rerun_rows: list[dict[str, Any]] = []
    stable_inputs = local_facts.get("workflow_inputs_stable") is True
    for run_id, run_attempts in attempts_by_run.items():
        if len(run_attempts) < 2:
            continue
        ordered = sorted(run_attempts, key=lambda item: int(item.get("attempt") or 0))
        conclusions = []
        for attempt in ordered:
            run = attempt.get("run")
            conclusions.append(run.get("conclusion") if isinstance(run, Mapping) else None)
        terminal = all(isinstance(value, str) and value in SUCCESS_CONCLUSIONS | FAILURE_CONCLUSIONS for value in conclusions)
        rerun_rows.append({"id": run_id, "unit": units[0] if len(units) == 1 else None, "comparable": stable_inputs if terminal else None, "outcome_changed": len(set(conclusions)) > 1 if terminal else None})
    flaky_complete = _group_complete(actions_group) and stable_inputs and all(row.get("outcome_changed") is not None for row in rerun_rows)
    observations["M-BTC-05"] = _purpose_group(
        "M-BTC-05",
        bundle,
        {"rerun_groups": rerun_rows, "retry_capture_enabled": _group_complete(actions_group) and stable_inputs},
        complete=flaky_complete,
        evidence_ids=_evidence_ids(actions_group, extra=["E-WORKFLOW-INPUT-IDENTITY"]),
        gaps=[] if flaky_complete else ["Retry capture or material-input identity is incomplete."],
    )

    invalid_data, invalid_complete, invalid_gaps = _main_invalid_duration_population(
        root=root,
        main_sha=main_sha,
        observed_at=bundle.get("observed_at"),
        check_index=check_index,
        authoritative_checks=authoritative_checks,
        w365_complete=check_completeness["w365"],
    )
    observations["M-SPI-01T"] = _purpose_group(
        "M-SPI-01T",
        bundle,
        invalid_data,
        complete=invalid_complete,
        evidence_ids=_evidence_ids(
            _raw_group(bundle, "actions_w365"),
            _raw_group(bundle, "check_runs"),
            extra=["E-LOCAL-GIT"],
        ),
        gaps=[] if invalid_complete else invalid_gaps or [
            "Complete reconstructable Main invalid-duration history is unavailable."
        ],
    )

    if normalization_conflicts:
        conflict_message = " ".join(dict.fromkeys(normalization_conflicts))
        for metric_id in (
            "M-SPI-01",
            "M-SPI-02S",
            "M-SPI-03",
            "M-SPI-04",
            "M-CGD-01",
            "M-CGD-02",
            "M-SPI-01T",
            "M-SPI-02",
            "M-BTC-01",
            "M-BTC-02",
            "M-BTC-03",
            "M-BTC-04",
            "M-BTC-05",
            "M-CGD-04",
        ):
            group = observations.get(metric_id)
            if not isinstance(group, dict):
                continue
            group["state"] = "unknown"
            group["completeness"] = "partial" if group.get("data") else "unknown"
            group["complete"] = False
            group["population_complete"] = False
            request = group.get("request") if isinstance(group.get("request"), dict) else {}
            request.update({"complete": False, "population_complete": False})
            group["request"] = request
            group.setdefault("gaps", []).append(
                {
                    "kind": "exact_main_binding_conflict",
                    "status": None,
                    "endpoint": None,
                    "source": "repository-health-normalizer",
                    "message": conflict_message,
                }
            )

    bundle["normalization"] = {
        "schema_version": NORMALIZATION_SCHEMA,
        "production_identity_valid": production is not None,
        "conflicts": list(dict.fromkeys(normalization_conflicts)),
        "limitations": list(dict.fromkeys(normalization_limitations)),
        "assessed_repository_build_code_executed": False,
        "git_commands_read_only": True,
    }
    return bundle


__all__ = [
    "NORMALIZATION_SCHEMA",
    "PRODUCTION_SCHEMA",
    "GENERIC_PRODUCTION_SCHEMA",
    "NormalizationError",
    "load_production_identity",
    "normalize_observations",
    "validate_production_identity",
]

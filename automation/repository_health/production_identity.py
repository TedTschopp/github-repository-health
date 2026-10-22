"""Strict production-unit identity declarations for heterogeneous repositories.

The declaration is a resolver and expected-identity contract.  It is never
runtime, release, publication, or governance proof by itself.  A downstream
normalizer must resolve the named system of record and return Unknown whenever
that proof is unavailable, incomplete, stale, or contradictory.

``RH-PRODUCTION-IDENTITY-1.0`` remains delegated to the original validator so
its intentionally narrow GitHub-release contract is unchanged.  The generic
``RH-PRODUCTION-IDENTITY-2.0`` schema adds explicit, discriminator-based
profiles without allowing one profile's fields to leak into another.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import urlparse


LEGACY_PRODUCTION_SCHEMA = "RH-PRODUCTION-IDENTITY-1.0"
GENERIC_PRODUCTION_SCHEMA = "RH-PRODUCTION-IDENTITY-2.0"

ACTIVE_PROFILES = {
    "application-github-deployment",
    "package-github-release",
    "gitops-production-ref",
    "documentation-publication",
}
INACTIVE_PROFILES = {
    "approved-no-current-output",
    "archived-retired",
}
PROFILES = ACTIVE_PROFILES | INACTIVE_PROFILES
ACTIVE_CORRESPONDENCE = {"Exact-Main", "Releasable-Main", "Production-Ref"}
MAIN_RELEASE_CORRESPONDENCE = {"Exact-Main", "Releasable-Main"}
ACTIVE_LIFECYCLES = {"Active", "Stable-supported", "Experimental", "Mirrored"}
NO_OUTPUT_LIFECYCLES = {"Active", "Stable-supported", "Experimental", "Mirrored"}
ARCHIVE_LIFECYCLES = {"Archived", "Retired"}

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PAGES_DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SEMVER_NUMBER = r"(?:0|[1-9][0-9]*)"
SEMVER_PRERELEASE_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
STANDARD_VERSION_PATTERN = re.compile(
    rf"^{SEMVER_NUMBER}\.{SEMVER_NUMBER}\.{SEMVER_NUMBER}"
    rf"(?:-{SEMVER_PRERELEASE_IDENTIFIER}(?:\.{SEMVER_PRERELEASE_IDENTIFIER})*)?$"
)

MAIN_AHEAD_POLICY = "every-intervening-accepted-main-revision-must-pass-authoritative-checks"
NO_OUTPUT_MAIN_POLICY = "not-applicable-no-current-output"
ARCHIVE_MAIN_POLICY = "archive-disposition-controls-current-state"


class ProductionIdentityError(ValueError):
    """Raised when a production identity declaration is unsafe or ambiguous."""


def _duplicate_safe_json(data: bytes, label: str) -> dict[str, Any]:
    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProductionIdentityError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ProductionIdentityError(f"{label} contains non-finite JSON number {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ProductionIdentityError(f"{label} contains an out-of-range JSON number {value}")
        return parsed

    try:
        decoded = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=object_hook,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProductionIdentityError(f"{label} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise ProductionIdentityError(f"{label} must be a JSON object")
    return decoded


def _exact_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    label: str,
) -> None:
    keys = set(value)
    if not all(isinstance(key, str) for key in keys):
        raise ProductionIdentityError(f"{label} keys must be strings")
    missing = required - keys
    unknown = keys - allowed
    if missing:
        raise ProductionIdentityError(f"{label} is missing required keys: {', '.join(sorted(missing))}")
    if unknown:
        raise ProductionIdentityError(f"{label} contains unknown keys: {', '.join(sorted(unknown))}")


def _plain_text(value: Any, label: str, maximum: int = 2048) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ProductionIdentityError(f"{label} must be a nonempty bounded single-line string")
    return value


def _strict_sha(value: Any, label: str) -> str:
    text = _plain_text(value, label, 40)
    if SHA_PATTERN.fullmatch(text) is None:
        raise ProductionIdentityError(f"{label} must be a lowercase 40-character Git SHA")
    return text


def _strict_digest(value: Any, label: str) -> str:
    text = _plain_text(value, label, 64)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise ProductionIdentityError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProductionIdentityError(f"{label} must be a positive integer")
    return value


def _iso_date(value: Any, label: str) -> date:
    text = _plain_text(value, label, 10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ProductionIdentityError(f"{label} must use ISO 8601 YYYY-MM-DD") from error
    if parsed.isoformat() != text:
        raise ProductionIdentityError(f"{label} must use canonical ISO 8601 YYYY-MM-DD")
    return parsed


def _https_url(value: Any, label: str) -> str:
    text = _plain_text(value, label)
    try:
        parsed = urlparse(text)
        hostname = parsed.hostname
    except ValueError as error:
        raise ProductionIdentityError(f"{label} is not a valid URL") from error
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProductionIdentityError(f"{label} must be an HTTPS URL without credentials or a fragment")
    return text


def _git_ref(value: Any, label: str) -> str:
    text = _plain_text(value, label, 512)
    parts = text.split("/")
    if not text.startswith("refs/") or text.count("/") < 2:
        raise ProductionIdentityError(f"{label} must be a fully qualified Git ref")
    if (
        text.endswith(("/", ".", ".lock"))
        or "//" in text
        or ".." in text
        or "@{" in text
        or any(character in text for character in " ~^:?*[\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
        or any(part.startswith(".") or part.endswith(".lock") or not part for part in parts)
    ):
        raise ProductionIdentityError(f"{label} contains an unsafe or ambiguous Git ref")
    return text


def _tag(value: Any, label: str) -> str:
    tag = _plain_text(value, label, 256)
    _git_ref(f"refs/tags/{tag}", label)
    if tag.casefold() in {"latest", "current", "stable"}:
        raise ProductionIdentityError(f"{label} must not use a mutable channel alias")
    return tag


def _repository_path(value: Any, label: str) -> str:
    text = _plain_text(value, label, 1024)
    if text == ".":
        return text
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or "\\" in text
        or "//" in text
        or text.startswith("./")
        or "/./" in text
        or text.endswith("/.")
    ):
        raise ProductionIdentityError(f"{label} must be a safe repository-relative POSIX path")
    return path.as_posix()


def _string_array(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ProductionIdentityError(f"{label} must be a string array")
    normalized = [_plain_text(item, f"{label}[{index}]", 4096) for index, item in enumerate(value)]
    if len(normalized) != len(set(normalized)):
        raise ProductionIdentityError(f"{label} must not contain duplicate values")
    return normalized


def _repository_contract(
    config: Mapping[str, Any],
    repository: str,
) -> tuple[str, dict[str, Any], list[str], list[str], str]:
    standard = config.get("standard")
    repository_config = config.get("repository")
    if not isinstance(standard, Mapping) or not isinstance(repository_config, Mapping):
        raise ProductionIdentityError("loaded configuration lacks standard/repository tables")
    version = _plain_text(standard.get("version"), "config.standard.version", 128)
    if STANDARD_VERSION_PATTERN.fullmatch(version) is None:
        raise ProductionIdentityError("config.standard.version is not a supported controlled version")
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ProductionIdentityError("observed repository must use GitHub owner/name form")
    declared_units = repository_config.get("deployable_units")
    if not isinstance(declared_units, list) or not declared_units:
        raise ProductionIdentityError("repository.deployable_units must be a nonempty string array")
    unit_ids = [
        _plain_text(item, f"repository.deployable_units[{index}]", 256)
        for index, item in enumerate(declared_units)
    ]
    if len(unit_ids) != len(set(unit_ids)):
        raise ProductionIdentityError("repository.deployable_units must not contain duplicates")
    checks = _string_array(
        repository_config.get("authoritative_checks"),
        "repository.authoritative_checks",
        allow_empty=False,
    )
    correspondence = repository_config.get("production_correspondence")
    supported_correspondence = ACTIVE_CORRESPONDENCE | {"N/A", "Per-unit combination"}
    if not isinstance(correspondence, str) or correspondence not in supported_correspondence:
        raise ProductionIdentityError(
            "repository.production_correspondence must be active, N/A, or Per-unit combination"
        )
    return version, dict(repository_config), unit_ids, checks, str(correspondence)


def _validate_common_validation(
    value: Any,
    *,
    label: str,
    checks: list[str],
    profile: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    validation = dict(value)
    keys = {
        "authoritative_checks",
        "source_must_be_reachable_from_main",
        "main_ahead_policy",
        "system_of_record_proof_required",
        "incomplete_system_of_record_result",
    }
    _exact_keys(validation, keys, keys, label)
    declared_checks = _string_array(validation.get("authoritative_checks"), f"{label}.authoritative_checks")
    if declared_checks != checks:
        raise ProductionIdentityError(f"{label}.authoritative_checks conflicts with configuration")
    if validation.get("system_of_record_proof_required") is not True:
        raise ProductionIdentityError(f"{label} must require independent system-of-record proof")
    if validation.get("incomplete_system_of_record_result") != "Unknown":
        raise ProductionIdentityError(f"{label} must fail incomplete system-of-record proof closed")

    if profile in ACTIVE_PROFILES:
        expected_reachability = True
        expected_policy = MAIN_AHEAD_POLICY
    elif profile == "archived-retired":
        expected_reachability = True
        expected_policy = ARCHIVE_MAIN_POLICY
    else:
        expected_reachability = False
        expected_policy = NO_OUTPUT_MAIN_POLICY
    if validation.get("source_must_be_reachable_from_main") is not expected_reachability:
        raise ProductionIdentityError(f"{label} has an invalid Main-reachability requirement")
    if validation.get("main_ahead_policy") != expected_policy:
        raise ProductionIdentityError(f"{label}.main_ahead_policy is invalid for {profile}")
    return validation


def _validate_deployment_selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {
        "system",
        "strategy",
        "environment",
        "deployment_id",
        "required_status",
        "artifact",
    }
    _exact_keys(selector, keys, keys, label)
    if selector.get("system") != "github-deployments" or selector.get("strategy") != "exact-deployment-id":
        raise ProductionIdentityError(f"{label} must select one exact GitHub deployment ID")
    _plain_text(selector.get("environment"), f"{label}.environment", 255)
    _positive_integer(selector.get("deployment_id"), f"{label}.deployment_id")
    if selector.get("required_status") != "success":
        raise ProductionIdentityError(f"{label}.required_status must be success")
    artifact = selector.get("artifact")
    if not isinstance(artifact, Mapping):
        raise ProductionIdentityError(f"{label}.artifact must be an object")
    artifact = dict(artifact)
    artifact_keys = {"reference", "sha256"}
    _exact_keys(artifact, artifact_keys, artifact_keys, f"{label}.artifact")
    _plain_text(artifact.get("reference"), f"{label}.artifact.reference", 2048)
    _strict_digest(artifact.get("sha256"), f"{label}.artifact.sha256")
    selector["artifact"] = artifact
    return selector


def _validate_release_selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {
        "system",
        "strategy",
        "release_id",
        "tag",
        "allow_draft",
        "allow_prerelease",
        "artifacts",
    }
    _exact_keys(selector, keys, keys, label)
    if selector.get("system") != "github-releases" or selector.get("strategy") != "exact-release-id-and-tag":
        raise ProductionIdentityError(f"{label} must select one exact GitHub release ID and tag")
    _positive_integer(selector.get("release_id"), f"{label}.release_id")
    _tag(selector.get("tag"), f"{label}.tag")
    if selector.get("allow_draft") is not False or not isinstance(selector.get("allow_prerelease"), bool):
        raise ProductionIdentityError(f"{label} draft/prerelease declarations are invalid")

    artifacts = selector.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ProductionIdentityError(f"{label}.artifacts must be a nonempty array")
    names: set[str] = set()
    primary_count = 0
    normalized_artifacts: list[dict[str, Any]] = []
    for index, raw_artifact in enumerate(artifacts):
        artifact_label = f"{label}.artifacts[{index}]"
        if not isinstance(raw_artifact, Mapping):
            raise ProductionIdentityError(f"{artifact_label} must be an object")
        artifact = dict(raw_artifact)
        artifact_keys = {"name", "sha256", "primary"}
        _exact_keys(artifact, artifact_keys, artifact_keys, artifact_label)
        name = _plain_text(artifact.get("name"), f"{artifact_label}.name", 256)
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ProductionIdentityError(f"{artifact_label}.name must be a plain asset name")
        if name in names:
            raise ProductionIdentityError(f"{artifact_label}.name is duplicated")
        names.add(name)
        _strict_digest(artifact.get("sha256"), f"{artifact_label}.sha256")
        if not isinstance(artifact.get("primary"), bool):
            raise ProductionIdentityError(f"{artifact_label}.primary must be boolean")
        primary_count += int(artifact["primary"])
        normalized_artifacts.append(artifact)
    if primary_count != 1:
        raise ProductionIdentityError(f"{label}.artifacts must contain exactly one primary asset")
    selector["artifacts"] = normalized_artifacts
    return selector


def _validate_gitops_selector(value: Any, label: str, source_sha: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {"system", "strategy", "production_ref", "ref_commit_sha", "path", "content_sha256"}
    _exact_keys(selector, keys, keys, label)
    if selector.get("system") != "git" or selector.get("strategy") != "exact-ref-commit-and-path":
        raise ProductionIdentityError(f"{label} must select one exact Git ref commit and path")
    _git_ref(selector.get("production_ref"), f"{label}.production_ref")
    ref_commit_sha = _strict_sha(selector.get("ref_commit_sha"), f"{label}.ref_commit_sha")
    if ref_commit_sha != source_sha:
        raise ProductionIdentityError(f"{label}.ref_commit_sha must equal the unit source_sha")
    selector["path"] = _repository_path(selector.get("path"), f"{label}.path")
    _strict_digest(selector.get("content_sha256"), f"{label}.content_sha256")
    return selector


def _validate_documentation_selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {
        "system",
        "strategy",
        "environment",
        "deployment_id",
        "publication_url",
        "content_sha256",
        "required_status",
    }
    _exact_keys(selector, keys, keys, label)
    system = selector.get("system")
    strategy = selector.get("strategy")
    if system == "github-pages":
        if strategy != "exact-pages-deployment-id" or selector.get("environment") != "github-pages":
            raise ProductionIdentityError(f"{label} has an invalid GitHub Pages selector")
        deployment_id = selector.get("deployment_id")
        if not (
            (
                isinstance(deployment_id, int)
                and not isinstance(deployment_id, bool)
                and deployment_id > 0
            )
            or (
                isinstance(deployment_id, str)
                and PAGES_DEPLOYMENT_ID_PATTERN.fullmatch(deployment_id) is not None
            )
        ):
            raise ProductionIdentityError(
                f"{label}.deployment_id must be a positive integer or safe GitHub Pages deployment ID"
            )
    elif system == "github-deployments":
        if strategy != "exact-deployment-id":
            raise ProductionIdentityError(f"{label} has an invalid GitHub deployment selector")
        _plain_text(selector.get("environment"), f"{label}.environment", 255)
        _positive_integer(selector.get("deployment_id"), f"{label}.deployment_id")
    else:
        raise ProductionIdentityError(f"{label}.system must be github-pages or github-deployments")
    _https_url(selector.get("publication_url"), f"{label}.publication_url")
    _strict_digest(selector.get("content_sha256"), f"{label}.content_sha256")
    if selector.get("required_status") != "success":
        raise ProductionIdentityError(f"{label}.required_status must be success")
    return selector


def _validate_no_output_selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {
        "system",
        "strategy",
        "decision_id",
        "approved_by",
        "approved_at",
        "review_date",
        "reason",
        "consumer_discovery",
    }
    _exact_keys(selector, keys, keys, label)
    if selector.get("system") != "governance-decision" or selector.get("strategy") != "approved-no-current-output":
        raise ProductionIdentityError(f"{label} must identify an approved no-current-output decision")
    _plain_text(selector.get("decision_id"), f"{label}.decision_id", 256)
    _plain_text(selector.get("approved_by"), f"{label}.approved_by", 256)
    approved_at = _iso_date(selector.get("approved_at"), f"{label}.approved_at")
    review_date = _iso_date(selector.get("review_date"), f"{label}.review_date")
    if review_date < approved_at:
        raise ProductionIdentityError(f"{label}.review_date must not precede approved_at")
    _plain_text(selector.get("reason"), f"{label}.reason", 4096)
    _plain_text(selector.get("consumer_discovery"), f"{label}.consumer_discovery", 4096)
    return selector


def _validate_last_known_output(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    output = dict(value)
    keys = {"status", "kind", "identity", "reason"}
    _exact_keys(output, keys, keys, label)
    status = output.get("status")
    if status == "identified":
        kind = output.get("kind")
        if not isinstance(kind, str) or kind not in {"deployment", "release", "git-ref", "publication", "artifact"}:
            raise ProductionIdentityError(f"{label}.kind is unsupported")
        _plain_text(output.get("identity"), f"{label}.identity")
        if output.get("reason") is not None:
            raise ProductionIdentityError(f"{label}.reason must be null when an output is identified")
    elif status == "none":
        if output.get("kind") is not None or output.get("identity") is not None:
            raise ProductionIdentityError(f"{label} must not identify an output when status is none")
        _plain_text(output.get("reason"), f"{label}.reason", 4096)
    else:
        raise ProductionIdentityError(f"{label}.status must be identified or none")
    return output


def _validate_archive_selector(value: Any, label: str, lifecycle: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionIdentityError(f"{label} must be an object")
    selector = dict(value)
    keys = {
        "system",
        "strategy",
        "disposition",
        "decision_id",
        "approved_by",
        "effective_at",
        "last_known_source_sha",
        "last_known_output",
        "write_protected",
    }
    _exact_keys(selector, keys, keys, label)
    if selector.get("system") != "governance-decision" or selector.get("strategy") != "archive-disposition":
        raise ProductionIdentityError(f"{label} must identify an approved archive disposition")
    if selector.get("disposition") != lifecycle:
        raise ProductionIdentityError(f"{label}.disposition must match the unit lifecycle")
    _plain_text(selector.get("decision_id"), f"{label}.decision_id", 256)
    _plain_text(selector.get("approved_by"), f"{label}.approved_by", 256)
    _iso_date(selector.get("effective_at"), f"{label}.effective_at")
    _strict_sha(selector.get("last_known_source_sha"), f"{label}.last_known_source_sha")
    selector["last_known_output"] = _validate_last_known_output(
        selector.get("last_known_output"),
        f"{label}.last_known_output",
    )
    if selector.get("write_protected") is not True:
        raise ProductionIdentityError(f"{label}.write_protected must be true")
    return selector


def validate_generic_production_identity(
    value: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    """Validate and normalize ``RH-PRODUCTION-IDENTITY-2.0``."""

    record = deepcopy(dict(value))
    top_keys = {"schema_version", "standard_version", "repository", "units"}
    _exact_keys(record, top_keys, top_keys, "production identity")
    if record.get("schema_version") != GENERIC_PRODUCTION_SCHEMA:
        raise ProductionIdentityError(f"unsupported generic production identity schema: {record.get('schema_version')!r}")

    version, _repository_config, declared_units, checks, configured_correspondence = _repository_contract(
        config,
        repository,
    )
    if record.get("standard_version") != version:
        raise ProductionIdentityError("production identity standard_version conflicts with configuration")
    if record.get("repository") != repository:
        raise ProductionIdentityError("production identity repository conflicts with the observed repository")

    units = record.get("units")
    if not isinstance(units, list) or not units:
        raise ProductionIdentityError("production identity units must be a nonempty array")
    normalized_units: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    correspondences: set[str] = set()
    unit_keys = {
        "unit_id",
        "profile",
        "lifecycle",
        "correspondence",
        "source_sha",
        "selector",
        "validation",
        "limitations",
    }
    for index, raw_unit in enumerate(units):
        label = f"production identity units[{index}]"
        if not isinstance(raw_unit, Mapping):
            raise ProductionIdentityError(f"{label} must be an object")
        unit = deepcopy(dict(raw_unit))
        _exact_keys(unit, unit_keys, unit_keys, label)
        unit_id = _plain_text(unit.get("unit_id"), f"{label}.unit_id", 256)
        if unit_id in seen_units:
            raise ProductionIdentityError(f"duplicate production unit: {unit_id}")
        seen_units.add(unit_id)

        profile = unit.get("profile")
        if not isinstance(profile, str) or profile not in PROFILES:
            raise ProductionIdentityError(f"{label}.profile is unsupported")
        lifecycle = unit.get("lifecycle")
        correspondence = unit.get("correspondence")
        source_sha = unit.get("source_sha")
        selector_label = f"{label}.selector"

        if profile in ACTIVE_PROFILES:
            if not isinstance(lifecycle, str) or lifecycle not in ACTIVE_LIFECYCLES:
                raise ProductionIdentityError(f"{label}.lifecycle is invalid for an active output")
            if not isinstance(correspondence, str) or correspondence not in ACTIVE_CORRESPONDENCE:
                raise ProductionIdentityError(f"{label}.correspondence must bind active output to Main")
            if profile == "gitops-production-ref" and correspondence != "Production-Ref":
                raise ProductionIdentityError(
                    f"{label}.correspondence must be Production-Ref for a GitOps production ref"
                )
            if profile != "gitops-production-ref" and correspondence not in MAIN_RELEASE_CORRESPONDENCE:
                raise ProductionIdentityError(
                    f"{label}.correspondence must be Exact-Main or Releasable-Main for {profile}"
                )
            source_sha = _strict_sha(source_sha, f"{label}.source_sha")
            if profile == "application-github-deployment":
                selector = _validate_deployment_selector(unit.get("selector"), selector_label)
            elif profile == "package-github-release":
                selector = _validate_release_selector(unit.get("selector"), selector_label)
            elif profile == "gitops-production-ref":
                selector = _validate_gitops_selector(unit.get("selector"), selector_label, source_sha)
            else:
                selector = _validate_documentation_selector(unit.get("selector"), selector_label)
        elif profile == "approved-no-current-output":
            if not isinstance(lifecycle, str) or lifecycle not in NO_OUTPUT_LIFECYCLES:
                raise ProductionIdentityError(f"{label}.lifecycle is invalid for no current output")
            if correspondence != "N/A" or source_sha is not None:
                raise ProductionIdentityError(f"{label} with no current output must use N/A and null source_sha")
            selector = _validate_no_output_selector(unit.get("selector"), selector_label)
        else:
            if not isinstance(lifecycle, str) or lifecycle not in ARCHIVE_LIFECYCLES:
                raise ProductionIdentityError(f"{label}.lifecycle must be Archived or Retired")
            if correspondence != "N/A" or source_sha is not None:
                raise ProductionIdentityError(f"{label} archive disposition must use N/A and null source_sha")
            selector = _validate_archive_selector(unit.get("selector"), selector_label, str(lifecycle))

        validation = _validate_common_validation(
            unit.get("validation"),
            label=f"{label}.validation",
            checks=checks,
            profile=str(profile),
        )
        limitations = _string_array(unit.get("limitations"), f"{label}.limitations")
        unit.update(
            {
                "source_sha": source_sha,
                "selector": selector,
                "validation": validation,
                "limitations": limitations,
            }
        )
        correspondences.add(str(correspondence))
        normalized_units.append(unit)

    if seen_units != set(declared_units) or len(seen_units) != len(declared_units):
        raise ProductionIdentityError("production identity unit IDs conflict with repository.deployable_units")
    if configured_correspondence == "Per-unit combination":
        if len(correspondences) < 2:
            raise ProductionIdentityError("Per-unit combination requires at least two distinct unit correspondence contracts")
    elif correspondences != {configured_correspondence}:
        raise ProductionIdentityError("production identity correspondence conflicts with configuration")
    record["units"] = normalized_units
    return record


def declared_release_asset_names(value: Mapping[str, Any]) -> list[str]:
    """Return only exact GitHub-release asset names from a validated record.

    The returned names are a download allowlist, not evidence.  Callers must
    validate the record before invoking this helper and must independently
    verify the downloaded bytes against the declaration.
    """

    if not isinstance(value, Mapping) or not isinstance(value.get("units"), list):
        return []
    schema = value.get("schema_version")
    names: list[str] = []
    if schema == LEGACY_PRODUCTION_SCHEMA:
        for unit in value["units"]:
            if not isinstance(unit, Mapping):
                return []
            current = unit.get("current")
            artifacts = current.get("artifacts") if isinstance(current, Mapping) else None
            if not isinstance(artifacts, list):
                return []
            for artifact in artifacts:
                name = artifact.get("name") if isinstance(artifact, Mapping) else None
                if not isinstance(name, str):
                    return []
                names.append(name)
    elif schema == GENERIC_PRODUCTION_SCHEMA:
        for unit in value["units"]:
            if not isinstance(unit, Mapping) or unit.get("profile") != "package-github-release":
                continue
            selector = unit.get("selector")
            artifacts = selector.get("artifacts") if isinstance(selector, Mapping) else None
            if not isinstance(artifacts, list):
                return []
            for artifact in artifacts:
                name = artifact.get("name") if isinstance(artifact, Mapping) else None
                if not isinstance(name, str):
                    return []
                names.append(name)
    return list(dict.fromkeys(names))


def _validate_legacy_production_identity(
    value: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    # The import is deliberately lazy: normalizers can later dispatch the generic
    # schema to this module without creating an import cycle.  Keeping v1 in its
    # original validator preserves its exact release-specific checks.
    from .normalizers import validate_production_identity as validate_legacy

    try:
        return validate_legacy(value, config=config, repository=repository)
    except ValueError as error:
        raise ProductionIdentityError(str(error)) from error


def validate_production_identity(
    value: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    """Dispatch a production identity record by its exact schema version."""

    if not isinstance(value, Mapping):
        raise ProductionIdentityError("production identity must be an object")
    schema = value.get("schema_version")
    if schema == LEGACY_PRODUCTION_SCHEMA:
        return _validate_legacy_production_identity(value, config=config, repository=repository)
    if schema == GENERIC_PRODUCTION_SCHEMA:
        return validate_generic_production_identity(value, config=config, repository=repository)
    raise ProductionIdentityError(f"unsupported production identity schema: {schema!r}")


def load_production_identity(
    source: str | Path | bytes | Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    repository: str,
) -> dict[str, Any]:
    """Load duplicate-safe JSON and dispatch its production identity schema."""

    if isinstance(source, Mapping):
        value = deepcopy(dict(source))
    elif isinstance(source, bytes):
        value = _duplicate_safe_json(source, "production identity")
    else:
        path = Path(source)
        if not path.is_file() or path.is_symlink():
            raise ProductionIdentityError("production identity path must be a regular non-symlink file")
        value = _duplicate_safe_json(path.read_bytes(), str(path))
    return validate_production_identity(value, config=config, repository=repository)


__all__ = [
    "ACTIVE_PROFILES",
    "GENERIC_PRODUCTION_SCHEMA",
    "INACTIVE_PROFILES",
    "LEGACY_PRODUCTION_SCHEMA",
    "PROFILES",
    "ProductionIdentityError",
    "declared_release_asset_names",
    "load_production_identity",
    "validate_generic_production_identity",
    "validate_production_identity",
]

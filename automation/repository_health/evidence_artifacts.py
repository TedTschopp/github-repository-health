"""Bounded, read-only collection of repository-health Actions artifacts.

Uploaded artifacts are untrusted transfer packages.  This module enumerates an
exactly named population, downloads bounded ZIP bytes, validates the two-file
package, and compares every claim with authoritative GitHub records.  It does
not execute artifact content, assign assurance, or map categories to scores.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
import hashlib
import io
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request
import zipfile

from .evidence_producer import (
    EvidenceStatementError,
    verify_evidence_package,
)
from .delivery_collectors import DEPLOYMENT_PAYLOAD_SCHEMA
from .github_client import GitHubRESTClient


SCHEMA_VERSION = "RH-EVIDENCE-ARTIFACTS-1.0"
STATEMENT_VERIFICATION_SCHEMA = "RH-EVIDENCE-STATEMENT-VERIFICATION-1.0"
EVIDENCE_ARTIFACT_NAME_PREFIX = "repository-health-evidence--"
REQUIRED_ZIP_FILES = frozenset({"evidence-statement.json", "SHA256SUMS"})

DEFAULT_MAX_ELIGIBLE_POPULATIONS = 20
DEFAULT_MAX_ARTIFACTS_PER_POPULATION = 2
DEFAULT_MAX_ZIP_BYTES = 512 * 1024
DEFAULT_MAX_ENTRY_BYTES = 256 * 1024
DEFAULT_MAX_EXPANDED_BYTES = 384 * 1024
DEFAULT_MAX_SOURCE_RECORDS = 8
DEFAULT_MAX_METADATA_REQUESTS = 128

HARD_MAX_ELIGIBLE_POPULATIONS = 50
HARD_MAX_ARTIFACTS_PER_POPULATION = 5
HARD_MAX_ZIP_BYTES = 1024 * 1024
HARD_MAX_ENTRY_BYTES = 1024 * 1024
HARD_MAX_EXPANDED_BYTES = 2 * 1024 * 1024
HARD_MAX_SOURCE_RECORDS = 16
HARD_MAX_METADATA_REQUESTS = 256
MAX_ARTIFACT_PAGES = 10
MAX_ARTIFACT_REDIRECTS = 5

_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
)
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
_ACTIONS_RUN_SOURCE = re.compile(r"^github-actions-run:([1-9][0-9]*):([1-9][0-9]*)$")
_CHECK_RUN_SOURCE = re.compile(r"^github-check-run:([1-9][0-9]*)$")
_DEPLOYMENT_SOURCE = re.compile(
    r"^github-deployment-status:([1-9][0-9]*):([1-9][0-9]*)$"
)
_PAGES_DEPLOYMENT_SOURCE = re.compile(
    r"^github-pages-deployment:([A-Za-z0-9][A-Za-z0-9._-]{0,127})$"
)
_RELEASE_SOURCE = re.compile(r"^github-release:([1-9][0-9]*)$")
_ACTIONS_BLOB_HOST = re.compile(
    r"^productionresultssa[0-9]+\.blob\.core\.windows\.net$"
)
_UNIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEPLOYMENT_PAYLOAD_KEYS = frozenset({"schema_version", "unit_id", "artifact"})
_DEPLOYMENT_ARTIFACT_KEYS = frozenset({"reference", "sha256"})

_SUCCESS_STATES = frozenset({"success"})
_FAILURE_STATES = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "error"}
)


class EvidenceArtifactError(ValueError):
    """Raised for invalid collector configuration, never for remote gaps."""


def evidence_artifact_name(unit_id: str) -> str:
    """Return the one exact Actions artifact name for a controlled unit."""

    if (
        not isinstance(unit_id, str)
        or not _UNIT_ID_PATTERN.fullmatch(unit_id)
        or unit_id in {".", ".."}
    ):
        raise EvidenceArtifactError("unit_id is not a safe controlled unit identifier")
    return f"{EVIDENCE_ARTIFACT_NAME_PREFIX}{unit_id}"


def _positive_bounded(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise EvidenceArtifactError(f"{label} must be from 1 through {maximum}")
    return value


def _validate_repository(repository: str) -> str:
    if (
        not isinstance(repository, str)
        or not _REPOSITORY_PATTERN.fullmatch(repository)
        or repository.endswith(".")
    ):
        raise EvidenceArtifactError("repository must be an exact GitHub owner/name identifier")
    return repository


def _deployment_artifact_binding(
    value: Any,
    *,
    statement: Mapping[str, Any],
) -> dict[str, str] | None:
    """Validate the canonical deployment payload and bind its one digest.

    The deployment collector independently joins ``artifact.reference`` to the
    declared production selector.  At this boundary the evidence collector can
    authoritatively establish the unit, exact payload shape, controlled
    reference, and the single SHA-256 digest carried by the statement.  It does
    not infer a reference from an artifact name or accept the former parallel
    ``artifact_digests`` payload schema.
    """

    if isinstance(value, Mapping):
        payload: Mapping[str, Any] = value
    elif isinstance(value, str):
        try:
            def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                parsed: dict[str, Any] = {}
                for key, member in pairs:
                    if key in parsed:
                        raise ValueError("duplicate deployment payload key")
                    parsed[key] = member
                return parsed

            decoded = json.loads(value, object_pairs_hook=reject_duplicate)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(decoded, Mapping):
            return None
        payload = decoded
    else:
        return None

    if (
        any(not isinstance(key, str) for key in payload)
        or set(payload) != _DEPLOYMENT_PAYLOAD_KEYS
        or payload.get("schema_version") != DEPLOYMENT_PAYLOAD_SCHEMA
        or payload.get("unit_id") != statement.get("unit_id")
    ):
        return None
    artifact = payload.get("artifact")
    if (
        not isinstance(artifact, Mapping)
        or any(not isinstance(key, str) for key in artifact)
        or set(artifact) != _DEPLOYMENT_ARTIFACT_KEYS
    ):
        return None
    reference = artifact.get("reference")
    digest = artifact.get("sha256")
    if (
        not isinstance(reference, str)
        or not reference
        or reference != reference.strip()
        or len(reference) > 2048
        or any(ord(character) < 32 or ord(character) == 127 for character in reference)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        return None
    statement_digests = statement.get("artifact_digests")
    if not isinstance(statement_digests, list) or len(statement_digests) != 1:
        return None
    statement_digest = statement_digests[0]
    if (
        not isinstance(statement_digest, Mapping)
        or statement_digest.get("algorithm") != "sha256"
        or statement_digest.get("value") != digest
    ):
        return None
    return {"reference": reference, "sha256": digest}


def _endpoint(repository: str, suffix: str, query: Mapping[str, Any] | None = None) -> str:
    path = f"/repos/{repository}{suffix}"
    return f"{path}?{urlencode(query)}" if query else path


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as error:
        raise EvidenceArtifactError("artifact URL has an invalid port") from error
    if port is None:
        port = 443 if parts.scheme.lower() == "https" else 80 if parts.scheme.lower() == "http" else None
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


def _safe_actions_redirect(target: str, *, api_origin: tuple[str, str, int | None]) -> str:
    parts = urlsplit(target)
    if parts.username or parts.password:
        raise EvidenceArtifactError("Actions artifact redirect must not contain credentials")
    origin = _url_origin(target)
    if origin == api_origin:
        return target
    scheme, host, port = origin
    if scheme != "https" or port != 443 or not host:
        raise EvidenceArtifactError("Actions artifact cross-origin redirects require HTTPS on port 443")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise EvidenceArtifactError("Actions artifact redirects must not target an IP literal")
    if api_origin[:2] != ("https", "api.github.com"):
        raise EvidenceArtifactError(
            "Enterprise Actions artifact redirects require same-origin handling or an explicit enterprise policy"
        )
    actions_host = host.endswith(".actions.githubusercontent.com") and host != "actions.githubusercontent.com"
    if not actions_host and not _ACTIONS_BLOB_HOST.fullmatch(host):
        raise EvidenceArtifactError("Actions artifact redirect host is not in the controlled allowlist")
    return target


def _binary_unknown(
    endpoint: str,
    *,
    error: str,
    error_kind: str,
    status: int | None = None,
    redirects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "state": "unknown",
        "ok": False,
        "status": status,
        "data": None,
        "size": None,
        "error": error,
        "error_kind": error_kind,
        "url": endpoint,
        "redirects": list(redirects or []),
    }


def download_actions_artifact(
    client: GitHubRESTClient,
    endpoint: str,
    *,
    max_bytes: int = DEFAULT_MAX_ZIP_BYTES,
) -> dict[str, Any]:
    """Download an Actions artifact through a narrowly allowed redirect chain.

    Authentication is sent only to the configured API origin and is stripped
    before an approved cross-origin Actions/Azure storage request.
    """

    _positive_bounded(max_bytes, "max_bytes", HARD_MAX_ZIP_BYTES)
    custom = getattr(client, "get_actions_artifact_binary", None)
    if callable(custom):
        return custom(endpoint, max_bytes=max_bytes)
    api_url = getattr(client, "api_url", None)
    if not isinstance(api_url, str):
        return _binary_unknown(
            endpoint,
            error="Client does not expose a controlled GitHub API origin",
            error_kind="invalid_client",
        )
    api_origin = _url_origin(api_url)
    if api_origin[0] != "https":
        return _binary_unknown(
            endpoint,
            error="Actions artifact API origin must use HTTPS",
            error_kind="unsafe_origin",
        )
    current = urljoin(api_url.rstrip("/") + "/", endpoint.lstrip("/"))
    if _url_origin(current) != api_origin:
        return _binary_unknown(
            endpoint,
            error="Initial Actions artifact endpoint is not on the configured API origin",
            error_kind="unsafe_origin",
        )
    transport = getattr(client, "binary_transport", None)
    if not callable(transport):
        return _binary_unknown(
            endpoint,
            error="Client does not expose a bounded binary transport",
            error_kind="invalid_client",
        )
    timeout = getattr(client, "timeout", 15)
    redirects: list[dict[str, Any]] = []
    visited = {current}
    while True:
        same_origin = _url_origin(current) == api_origin
        headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "repository-health-assessment/0.1",
        }
        if same_origin:
            api_version = getattr(client, "api_version", None)
            if isinstance(api_version, str) and api_version:
                headers["X-GitHub-Api-Version"] = api_version
            token = getattr(client, "token", "")
            if isinstance(token, str) and token:
                headers["Authorization"] = f"Bearer {token}"
        request = Request(current, headers=headers, method="GET")
        response: Any | None = None
        status: int | None = None
        response_headers: Mapping[str, Any] = {}
        try:
            response = transport(request, timeout=timeout)
            status = getattr(response, "status", 200)
            response_headers = getattr(response, "headers", {}) or {}
        except HTTPError as error:
            status = error.code
            response_headers = getattr(error, "headers", {}) or {}
            error.close()
            if status not in {301, 302, 303, 307, 308}:
                return _binary_unknown(
                    endpoint,
                    error=f"HTTP {status}",
                    error_kind="permission_or_api_gap" if status in {403, 404, 410} else "http_error",
                    status=status,
                    redirects=redirects,
                )
        except (URLError, TimeoutError, OSError) as error:
            return _binary_unknown(
                endpoint,
                error=type(error).__name__,
                error_kind="network_error",
                redirects=redirects,
            )
        if status in {301, 302, 303, 307, 308}:
            if response is not None:
                response.close()
            location = None
            for key, value in response_headers.items():
                if str(key).lower() == "location":
                    location = str(value)
                    break
            if not location:
                return _binary_unknown(
                    endpoint,
                    error="Actions artifact redirect has no Location header",
                    error_kind="invalid_redirect",
                    status=status,
                    redirects=redirects,
                )
            if len(redirects) >= MAX_ARTIFACT_REDIRECTS:
                return _binary_unknown(
                    endpoint,
                    error=f"Actions artifact redirect cap reached ({MAX_ARTIFACT_REDIRECTS})",
                    error_kind="redirect_cap",
                    status=status,
                    redirects=redirects,
                )
            try:
                target = _safe_actions_redirect(urljoin(current, location), api_origin=api_origin)
            except EvidenceArtifactError as error:
                return _binary_unknown(
                    endpoint,
                    error=str(error),
                    error_kind="unsafe_redirect",
                    status=status,
                    redirects=redirects,
                )
            if target in visited:
                return _binary_unknown(
                    endpoint,
                    error="Actions artifact redirect loop detected",
                    error_kind="redirect_loop",
                    status=status,
                    redirects=redirects,
                )
            redirects.append({"from": current, "to": target, "status": status})
            visited.add(target)
            current = target
            continue
        if response is None or status is None or status < 200 or status >= 300:
            if response is not None:
                response.close()
            return _binary_unknown(
                endpoint,
                error=f"HTTP {status}",
                error_kind="http_error",
                status=status,
                redirects=redirects,
            )
        with response:
            response_url = getattr(response, "geturl", lambda: current)()
            if response_url != current:
                return _binary_unknown(
                    endpoint,
                    error="Binary transport followed an unvalidated redirect",
                    error_kind="unvalidated_redirect",
                    status=status,
                    redirects=redirects,
                )
            content_length: int | None = None
            for key, value in response_headers.items():
                if str(key).lower() == "content-length":
                    try:
                        content_length = int(value)
                    except (TypeError, ValueError):
                        return _binary_unknown(
                            endpoint,
                            error="Actions artifact Content-Length is invalid",
                            error_kind="invalid_content_length",
                            status=status,
                            redirects=redirects,
                        )
                    break
            if content_length is not None and (content_length < 0 or content_length > max_bytes):
                return _binary_unknown(
                    endpoint,
                    error=f"Actions artifact Content-Length exceeds the {max_bytes}-byte cap",
                    error_kind="response_too_large",
                    status=status,
                    redirects=redirects,
                )
            body = response.read(max_bytes + 1)
        if not isinstance(body, bytes) or len(body) > max_bytes:
            return _binary_unknown(
                endpoint,
                error=f"Actions artifact response exceeds the {max_bytes}-byte cap",
                error_kind="response_too_large",
                status=status,
                redirects=redirects,
            )
        if content_length is not None and content_length != len(body):
            return _binary_unknown(
                endpoint,
                error="Actions artifact Content-Length does not match downloaded bytes",
                error_kind="size_mismatch",
                status=status,
                redirects=redirects,
            )
        return {
            "state": "observed",
            "ok": True,
            "status": status,
            "data": body,
            "size": len(body),
            "error": None,
            "error_kind": None,
            "url": endpoint,
            "final_url": current,
            "redirects": redirects,
        }


def _gap(
    kind: str,
    message: str,
    *,
    artifact_id: int | None = None,
    endpoint: str | None = None,
    source_evidence_id: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "message": message,
        "artifact_id": artifact_id,
        "endpoint": endpoint,
        "source_evidence_id": source_evidence_id,
    }


def _candidate(
    index: int,
    artifact: Any,
    artifact_id: int | None = None,
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    if isinstance(artifact, Mapping):
        for key in (
            "id",
            "name",
            "size_in_bytes",
            "expired",
            "created_at",
            "updated_at",
            "expires_at",
            "digest",
        ):
            value = artifact.get(key)
            if value is None or isinstance(value, (str, int, bool)):
                selected[key] = value
    return {
        "artifact_index": index,
        "artifact_id": artifact_id,
        "artifact": selected,
        "state": "unknown",
        "package_valid": False,
        "identity_complete": False,
        "authoritative_workflow_valid": False,
        "source_records_complete": False,
        "result_source_valid": False,
        "category_policy_valid": False,
        "artifact_sha256": None,
        "zip": None,
        "statement": None,
        "authoritative_run": None,
        "source_records": [],
        "gaps": [],
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }


def _zip_name_gap(name: str) -> tuple[str, str] | None:
    if not name or "\x00" in name or "\\" in name:
        return "unsafe_zip_entry", "ZIP entry has an empty, NUL, or backslash name"
    path = PurePosixPath(name)
    if path.is_absolute() or name.startswith("/"):
        return "unsafe_zip_entry", f"ZIP entry is absolute: {name!r}"
    if any(part in {"", ".", ".."} for part in path.parts):
        return "unsafe_zip_entry", f"ZIP entry has an ambiguous path: {name!r}"
    return None


def _read_evidence_zip(
    content: bytes,
    *,
    max_entry_bytes: int,
    max_expanded_bytes: int,
) -> tuple[dict[str, bytes] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    gaps: list[dict[str, Any]] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(content), mode="r")
    except (zipfile.BadZipFile, OSError, ValueError) as error:
        return None, None, [_gap("invalid_zip", f"Artifact is not a valid ZIP: {type(error).__name__}")]

    with archive:
        try:
            entries = archive.infolist()
        except (zipfile.BadZipFile, OSError, ValueError) as error:
            return None, None, [_gap("invalid_zip", f"ZIP directory cannot be read: {type(error).__name__}")]
        if len(entries) != len(REQUIRED_ZIP_FILES):
            gaps.append(
                _gap(
                    "unexpected_zip_population",
                    "ZIP must contain exactly evidence-statement.json and SHA256SUMS",
                )
            )
        names = [entry.filename for entry in entries]
        duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicate_names:
            gaps.append(
                _gap(
                    "duplicate_zip_entry",
                    f"ZIP contains duplicate entry names: {duplicate_names}",
                )
            )
        for entry in entries:
            unsafe = _zip_name_gap(entry.filename)
            if unsafe is not None:
                gaps.append(_gap(unsafe[0], unsafe[1]))
            mode = (entry.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if entry.is_dir() or file_type not in {0, stat.S_IFREG}:
                gaps.append(
                    _gap(
                        "unsafe_zip_entry_type",
                        f"ZIP entry is not a regular file: {entry.filename!r}",
                    )
                )
            if entry.flag_bits & 0x1:
                gaps.append(
                    _gap("encrypted_zip_entry", f"ZIP entry is encrypted: {entry.filename!r}")
                )
            if entry.file_size < 0 or entry.file_size > max_entry_bytes:
                gaps.append(
                    _gap(
                        "zip_entry_size_cap",
                        f"ZIP entry exceeds the {max_entry_bytes}-byte cap: {entry.filename!r}",
                    )
                )
        if set(names) != REQUIRED_ZIP_FILES:
            gaps.append(
                _gap(
                    "unexpected_zip_files",
                    "ZIP file names do not match the exact evidence package contract",
                )
            )
        declared_total = sum(max(0, entry.file_size) for entry in entries)
        if declared_total > max_expanded_bytes:
            gaps.append(
                _gap(
                    "zip_expanded_size_cap",
                    f"ZIP declared expansion exceeds the {max_expanded_bytes}-byte cap",
                )
            )
        if gaps:
            return None, {
                "entry_count": len(entries),
                "entry_names": names,
                "declared_expanded_bytes": declared_total,
            }, gaps

        files: dict[str, bytes] = {}
        expanded = 0
        try:
            for entry in entries:
                remaining = min(max_entry_bytes, max_expanded_bytes - expanded)
                with archive.open(entry, mode="r") as handle:
                    data = handle.read(remaining + 1)
                if len(data) > remaining:
                    gaps.append(
                        _gap(
                            "zip_expanded_size_cap",
                            f"ZIP expansion exceeded a bounded read at {entry.filename!r}",
                        )
                    )
                    break
                expanded += len(data)
                files[entry.filename] = data
        except (zipfile.BadZipFile, RuntimeError, OSError, ValueError) as error:
            gaps.append(
                _gap("invalid_zip_content", f"ZIP entry cannot be read safely: {type(error).__name__}")
            )
        details = {
            "entry_count": len(entries),
            "entry_names": names,
            "declared_expanded_bytes": declared_total,
            "observed_expanded_bytes": expanded,
        }
        return (files if not gaps else None), details, gaps


def _validate_package_files(
    files: Mapping[str, bytes],
    *,
    repository: str,
    now: datetime | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        with tempfile.TemporaryDirectory(prefix="rh-evidence-") as temporary:
            root = Path(temporary)
            statement_path = root / "evidence-statement.json"
            manifest_path = root / "SHA256SUMS"
            statement_path.write_bytes(files["evidence-statement.json"])
            manifest_path.write_bytes(files["SHA256SUMS"])
            statement = verify_evidence_package(
                input_path=statement_path,
                manifest_path=manifest_path,
                expected_repository=repository,
                now=now,
            )
    except (EvidenceStatementError, OSError, KeyError) as error:
        return None, [_gap("invalid_evidence_package", str(error))]
    return statement, []


def _safe_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _safe_sha(value: Any) -> str | None:
    return value if isinstance(value, str) and _SHA_PATTERN.fullmatch(value) else None


def _outcome(value: Any) -> str:
    if value in _SUCCESS_STATES:
        return "success"
    if value in _FAILURE_STATES:
        return "failure"
    return "unknown"


def _category_policy_matches(
    statement: Mapping[str, Any],
    category_policy: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(category_policy, Mapping):
        return False
    unit_policy = category_policy.get(statement["unit_id"])
    if not isinstance(unit_policy, Mapping):
        return False
    kind_policy = unit_policy.get(statement["kind"])
    if not isinstance(kind_policy, Mapping) or set(kind_policy) != {
        "categories",
        "workflow_refs",
    }:
        return False
    categories = kind_policy.get("categories")
    workflow_refs = kind_policy.get("workflow_refs")
    if (
        not isinstance(categories, list)
        or not categories
        or any(not isinstance(item, str) for item in categories)
        or len(categories) != len(set(categories))
        or categories != sorted(categories)
        or not isinstance(workflow_refs, list)
        or not workflow_refs
        or any(not isinstance(item, str) for item in workflow_refs)
        or len(workflow_refs) != len(set(workflow_refs))
    ):
        return False
    return (
        statement["categories"] == categories
        and statement["workflow"]["ref"] in workflow_refs
    )


def _workflow_ref_parts(repository: str, workflow_ref: str) -> tuple[str, str, str]:
    relative_with_ref = workflow_ref[len(repository) + 1 :]
    path, full_ref = relative_with_ref.rsplit("@", 1)
    short_ref = full_ref
    for prefix in ("refs/heads/", "refs/tags/"):
        if full_ref.startswith(prefix):
            short_ref = full_ref[len(prefix) :]
            break
    return path, full_ref, short_ref


def _run_path_parts(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, None
    if "@" not in value:
        return value, None
    path, ref = value.rsplit("@", 1)
    return (path or None), (ref or None)


def _workflow_identity_matches(
    run: Mapping[str, Any], statement: Mapping[str, Any]
) -> tuple[bool, str | None]:
    workflow = statement["workflow"]
    expected_ref = workflow["ref"]
    expected_sha = workflow["sha"]
    if run.get("workflow_ref") == expected_ref and run.get("workflow_sha") == expected_sha:
        return True, "exact-run-fields"
    referenced = run.get("referenced_workflows")
    if isinstance(referenced, list):
        for item in referenced:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path")
            sha = item.get("sha")
            if path == expected_ref and sha == expected_sha:
                return True, "referenced-workflow-record"

    repository = statement["repository"]
    expected_path, full_ref, short_ref = _workflow_ref_parts(repository, expected_ref)
    run_path, run_ref = _run_path_parts(run.get("path"))
    same_revision_events = {"push", "workflow_dispatch", "schedule"}
    official_shape_match = (
        run_path == expected_path
        and run_ref in {full_ref, short_ref}
        and run.get("event") in same_revision_events
        and run.get("head_sha") == expected_sha
        and statement["subject"]["sha"] == expected_sha
        and run.get("head_branch") == short_ref
    )
    if official_shape_match:
        return True, "same-revision-official-run"
    return False, None


def _validate_run_identity(
    run: Any,
    *,
    repository: str,
    statement: Mapping[str, Any],
    artifact_workflow_run: Any,
    endpoint: str,
    artifact_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    gaps: list[dict[str, Any]] = []
    workflow = statement["workflow"]
    subject = statement["subject"]
    if not isinstance(run, Mapping):
        return None, [_gap("invalid_run_record", "Actions run response is not an object", artifact_id=artifact_id, endpoint=endpoint)]
    repository_record = run.get("repository")
    repository_name = repository_record.get("full_name") if isinstance(repository_record, Mapping) else None
    expected_path, _, _ = _workflow_ref_parts(repository, workflow["ref"])
    run_path, _ = _run_path_parts(run.get("path"))
    comparisons = (
        ("run id", run.get("id"), workflow["run_id"]),
        ("run attempt", run.get("run_attempt"), workflow["run_attempt"]),
        ("subject SHA", run.get("head_sha"), subject["sha"]),
        ("repository", repository_name, repository),
        ("workflow path", run_path, expected_path),
    )
    for label, actual, expected in comparisons:
        if actual != expected:
            gaps.append(
                _gap(
                    "run_identity_mismatch",
                    f"Authoritative {label} does not match the statement",
                    artifact_id=artifact_id,
                    endpoint=endpoint,
                )
            )
    workflow_identity_valid, workflow_identity_basis = _workflow_identity_matches(
        run, statement
    )
    if not workflow_identity_valid:
        gaps.append(
            _gap(
                "workflow_identity_unavailable",
                "Actions metadata does not bind the exact workflow ref and workflow SHA",
                artifact_id=artifact_id,
                endpoint=endpoint,
            )
        )
    if not isinstance(artifact_workflow_run, Mapping):
        gaps.append(
            _gap(
                "artifact_run_identity_missing",
                "Artifact metadata does not contain a workflow_run object",
                artifact_id=artifact_id,
            )
        )
    else:
        if artifact_workflow_run.get("id") != workflow["run_id"]:
            gaps.append(
                _gap(
                    "artifact_run_identity_mismatch",
                    "Artifact workflow run id does not match the statement",
                    artifact_id=artifact_id,
                )
            )
        if artifact_workflow_run.get("head_sha") != subject["sha"]:
            gaps.append(
                _gap(
                    "artifact_run_identity_mismatch",
                    "Artifact workflow run subject SHA does not match the statement",
                    artifact_id=artifact_id,
                )
            )
    selected = {
        "id": run.get("id"),
        "run_attempt": run.get("run_attempt"),
        "head_sha": run.get("head_sha"),
        "path": run.get("path"),
        "workflow_ref": statement["workflow"]["ref"] if workflow_identity_valid else None,
        "workflow_sha": statement["workflow"]["sha"] if workflow_identity_valid else None,
        "workflow_identity_basis": workflow_identity_basis,
        "event": run.get("event"),
        "head_branch": run.get("head_branch"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "repository": repository_name,
    }
    return selected, gaps


class _MetadataReader:
    def __init__(self, client: GitHubRESTClient, maximum: int) -> None:
        self.client = client
        self.maximum = maximum
        self.requests = 0
        self.cache: dict[str, dict[str, Any]] = {}

    def get(self, endpoint: str) -> dict[str, Any]:
        if endpoint in self.cache:
            return self.cache[endpoint]
        if self.requests >= self.maximum:
            result = {
                "state": "unknown",
                "ok": False,
                "status": None,
                "data": None,
                "error": f"Metadata request cap reached ({self.maximum})",
                "error_kind": "metadata_request_cap",
                "url": endpoint,
            }
            self.cache[endpoint] = result
            return result
        self.requests += 1
        result = self.client.get(endpoint)
        self.cache[endpoint] = result
        return result


def _response_gap(
    result: Mapping[str, Any],
    *,
    label: str,
    artifact_id: int,
    endpoint: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    kind = result.get("error_kind")
    return _gap(
        str(kind) if isinstance(kind, str) and kind else "source_record_unavailable",
        f"{label} is unavailable: {result.get('error') or 'unknown API response'}",
        artifact_id=artifact_id,
        endpoint=endpoint,
        source_evidence_id=source_id,
    )


def _source_actions_run(
    source_id: str,
    match: re.Match[str],
    *,
    run: Mapping[str, Any],
    statement: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_id = int(match.group(1))
    attempt = int(match.group(2))
    expected = statement["workflow"]
    gaps: list[dict[str, Any]] = []
    if run_id != expected["run_id"] or attempt != expected["run_attempt"]:
        gaps.append(_gap("source_identity_mismatch", "Actions-run source ID does not match the statement run", source_evidence_id=source_id))
    classification = _outcome(run.get("conclusion"))
    return {
        "source_evidence_id": source_id,
        "source_type": "github-actions-run",
        "state": "observed" if not gaps else "unknown",
        "classification": classification,
        "record": {
            "id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
        },
    }, gaps


def _source_check_run(
    source_id: str,
    match: re.Match[str],
    *,
    repository: str,
    statement: Mapping[str, Any],
    reader: _MetadataReader,
    artifact_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    check_id = int(match.group(1))
    endpoint = _endpoint(repository, f"/check-runs/{check_id}")
    result = reader.get(endpoint)
    if not result.get("ok"):
        return {
            "source_evidence_id": source_id,
            "source_type": "github-check-run",
            "state": "unknown",
            "classification": "unknown",
            "record": None,
        }, [_response_gap(result, label="Check-run source record", artifact_id=artifact_id, endpoint=endpoint, source_id=source_id)]
    data = result.get("data")
    gaps: list[dict[str, Any]] = []
    if not isinstance(data, Mapping):
        gaps.append(_gap("invalid_source_record", "Check-run source record is not an object", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
        data = {}
    if data.get("id") != check_id or data.get("head_sha") != statement["subject"]["sha"]:
        gaps.append(_gap("source_identity_mismatch", "Check-run id or subject SHA does not match the statement", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
    if data.get("status") != "completed":
        gaps.append(_gap("source_record_incomplete", "Check run is not completed", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
    classification = _outcome(data.get("conclusion"))
    return {
        "source_evidence_id": source_id,
        "source_type": "github-check-run",
        "state": "observed" if not gaps else "unknown",
        "classification": classification,
        "record": {
            "id": data.get("id"),
            "head_sha": data.get("head_sha"),
            "status": data.get("status"),
            "conclusion": data.get("conclusion"),
            "name": data.get("name"),
        },
    }, gaps


def _source_deployment(
    source_id: str,
    match: re.Match[str],
    *,
    repository: str,
    statement: Mapping[str, Any],
    reader: _MetadataReader,
    artifact_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deployment_id = int(match.group(1))
    status_id = int(match.group(2))
    deployment_endpoint = _endpoint(repository, f"/deployments/{deployment_id}")
    status_endpoint = _endpoint(repository, f"/deployments/{deployment_id}/statuses/{status_id}")
    deployment_result = reader.get(deployment_endpoint)
    status_result = reader.get(status_endpoint)
    gaps: list[dict[str, Any]] = []
    if not deployment_result.get("ok"):
        gaps.append(_response_gap(deployment_result, label="Deployment source record", artifact_id=artifact_id, endpoint=deployment_endpoint, source_id=source_id))
    if not status_result.get("ok"):
        gaps.append(_response_gap(status_result, label="Deployment-status source record", artifact_id=artifact_id, endpoint=status_endpoint, source_id=source_id))
    deployment = deployment_result.get("data") if deployment_result.get("ok") else None
    status_record = status_result.get("data") if status_result.get("ok") else None
    if not isinstance(deployment, Mapping) or not isinstance(status_record, Mapping):
        if not gaps:
            gaps.append(_gap("invalid_source_record", "Deployment source records are not objects", artifact_id=artifact_id, source_evidence_id=source_id))
        deployment = deployment if isinstance(deployment, Mapping) else {}
        status_record = status_record if isinstance(status_record, Mapping) else {}
    if deployment.get("id") != deployment_id or deployment.get("sha") != statement["subject"]["sha"]:
        gaps.append(_gap("source_identity_mismatch", "Deployment id or subject SHA does not match the statement", artifact_id=artifact_id, source_evidence_id=source_id))
    if status_record.get("id") != status_id:
        gaps.append(_gap("source_identity_mismatch", "Deployment status id does not match its source ID", artifact_id=artifact_id, source_evidence_id=source_id))
    artifact_binding = _deployment_artifact_binding(
        deployment.get("payload"), statement=statement
    )
    artifact_binding_complete = artifact_binding is not None
    if not artifact_binding_complete:
        gaps.append(
            _gap(
                "deployment_artifact_binding_incomplete",
                "Deployment does not use the canonical artifact-binding schema or bind the exact statement unit and SHA-256 digest",
                artifact_id=artifact_id,
                source_evidence_id=source_id,
            )
        )
    classification = _outcome(status_record.get("state"))
    return {
        "source_evidence_id": source_id,
        "source_type": "github-deployment-status",
        "state": "observed" if not gaps else "unknown",
        "classification": classification,
        "record": {
            "deployment_id": deployment.get("id"),
            "deployment_sha": deployment.get("sha"),
            "environment": deployment.get("environment"),
            "status_id": status_record.get("id"),
            "status": status_record.get("state"),
            "artifact_reference": (
                artifact_binding["reference"] if artifact_binding is not None else None
            ),
            "artifact_sha256": (
                artifact_binding["sha256"] if artifact_binding is not None else None
            ),
            "artifact_binding_complete": artifact_binding_complete,
        },
    }, gaps


def _source_pages_deployment(
    source_id: str,
    match: re.Match[str],
    *,
    repository: str,
    reader: _MetadataReader,
    artifact_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve only the official Pages deployment status object.

    This endpoint exposes ``{"status": ...}`` but no subject SHA, artifact
    digest, or independent status ID. Those absent bindings remain explicit.
    """

    deployment_id_text = match.group(1)
    deployment_id: int | str = (
        int(deployment_id_text)
        if deployment_id_text.isdigit() and not deployment_id_text.startswith("0")
        else deployment_id_text
    )
    endpoint = _endpoint(repository, f"/pages/deployments/{deployment_id}")
    result = reader.get(endpoint)
    if not result.get("ok"):
        return {
            "source_evidence_id": source_id,
            "source_type": "github-pages-deployment",
            "state": "unknown",
            "classification": "unknown",
            "record": None,
        }, [
            _response_gap(
                result,
                label="GitHub Pages deployment source record",
                artifact_id=artifact_id,
                endpoint=endpoint,
                source_id=source_id,
            )
        ]
    data = result.get("data")
    if (
        not isinstance(data, Mapping)
        or set(data) != {"status"}
        or not isinstance(data.get("status"), str)
        or not data.get("status")
    ):
        return {
            "source_evidence_id": source_id,
            "source_type": "github-pages-deployment",
            "state": "unknown",
            "classification": "unknown",
            "record": None,
        }, [
            _gap(
                "invalid_source_record",
                "GitHub Pages deployment record must be the official status-only object",
                artifact_id=artifact_id,
                endpoint=endpoint,
                source_evidence_id=source_id,
            )
        ]
    status = data["status"]
    classification = "success" if status == "succeed" else "unknown"
    return {
        "source_evidence_id": source_id,
        "source_type": "github-pages-deployment",
        "state": "observed",
        "classification": classification,
        "record": {
            "pages_deployment_id": deployment_id,
            "status": status,
            "subject_binding_complete": False,
            "artifact_binding_complete": False,
        },
    }, []


def _release_assets_match(
    release: Mapping[str, Any], statement: Mapping[str, Any]
) -> bool:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return False
    observed: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            return False
        name = asset.get("name")
        digest = asset.get("digest")
        if not isinstance(name, str) or not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            return False
        if name in observed:
            return False
        observed[name] = digest.removeprefix("sha256:")
    expected = {item["name"]: item["value"] for item in statement["artifact_digests"]}
    return bool(expected) and observed == expected


def _source_release(
    source_id: str,
    match: re.Match[str],
    *,
    repository: str,
    statement: Mapping[str, Any],
    reader: _MetadataReader,
    artifact_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    release_id = int(match.group(1))
    endpoint = _endpoint(repository, f"/releases/{release_id}")
    result = reader.get(endpoint)
    if not result.get("ok"):
        return {
            "source_evidence_id": source_id,
            "source_type": "github-release",
            "state": "unknown",
            "classification": "unknown",
            "record": None,
        }, [_response_gap(result, label="Release source record", artifact_id=artifact_id, endpoint=endpoint, source_id=source_id)]
    data = result.get("data")
    gaps: list[dict[str, Any]] = []
    if not isinstance(data, Mapping):
        gaps.append(_gap("invalid_source_record", "Release source record is not an object", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
        data = {}
    if data.get("id") != release_id:
        gaps.append(_gap("source_identity_mismatch", "Release id does not match its source ID", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
    tag_name = data.get("tag_name")
    expected_tag_ref = (
        f"refs/tags/{tag_name}" if isinstance(tag_name, str) and tag_name else None
    )
    tag_binding_complete = False
    tag_object_chain: list[dict[str, Any]] = []
    if expected_tag_ref is None or statement["subject"]["ref"] != expected_tag_ref:
        gaps.append(
            _gap(
                "release_tag_identity_mismatch",
                "Release tag does not match the statement subject ref",
                artifact_id=artifact_id,
                endpoint=endpoint,
                source_evidence_id=source_id,
            )
        )
    else:
        ref_endpoint = _endpoint(
            repository,
            f"/git/ref/{quote(f'tags/{tag_name}', safe='/')}",
        )
        ref_result = reader.get(ref_endpoint)
        if not ref_result.get("ok"):
            gaps.append(
                _response_gap(
                    ref_result,
                    label="Release tag ref",
                    artifact_id=artifact_id,
                    endpoint=ref_endpoint,
                    source_id=source_id,
                )
            )
        else:
            ref_record = ref_result.get("data")
            if not isinstance(ref_record, Mapping):
                gaps.append(
                    _gap(
                        "invalid_source_record",
                        "Release tag ref record is not an object",
                        artifact_id=artifact_id,
                        endpoint=ref_endpoint,
                        source_evidence_id=source_id,
                    )
                )
            else:
                ref_object = ref_record.get("object")
                if (
                    ref_record.get("ref") != expected_tag_ref
                    or not isinstance(ref_object, Mapping)
                ):
                    gaps.append(
                        _gap(
                            "release_tag_identity_mismatch",
                            "Authoritative release tag ref is missing or mismatched",
                            artifact_id=artifact_id,
                            endpoint=ref_endpoint,
                            source_evidence_id=source_id,
                        )
                    )
                else:
                    object_type = ref_object.get("type")
                    object_sha = _safe_sha(ref_object.get("sha"))
                    tag_object_chain.append(
                        {"type": object_type, "sha": object_sha, "endpoint": ref_endpoint}
                    )
                    for _ in range(4):
                        if object_type == "commit" and object_sha is not None:
                            tag_binding_complete = object_sha == statement["subject"]["sha"]
                            break
                        if object_type != "tag" or object_sha is None:
                            break
                        tag_endpoint = _endpoint(repository, f"/git/tags/{object_sha}")
                        tag_result = reader.get(tag_endpoint)
                        if not tag_result.get("ok"):
                            gaps.append(
                                _response_gap(
                                    tag_result,
                                    label="Annotated release tag object",
                                    artifact_id=artifact_id,
                                    endpoint=tag_endpoint,
                                    source_id=source_id,
                                )
                            )
                            break
                        tag_record = tag_result.get("data")
                        tag_object = (
                            tag_record.get("object")
                            if isinstance(tag_record, Mapping)
                            and tag_record.get("sha") == object_sha
                            else None
                        )
                        if not isinstance(tag_object, Mapping):
                            gaps.append(
                                _gap(
                                    "invalid_source_record",
                                    "Annotated tag object is missing or mismatched",
                                    artifact_id=artifact_id,
                                    endpoint=tag_endpoint,
                                    source_evidence_id=source_id,
                                )
                            )
                            break
                        object_type = tag_object.get("type")
                        object_sha = _safe_sha(tag_object.get("sha"))
                        tag_object_chain.append(
                            {"type": object_type, "sha": object_sha, "endpoint": tag_endpoint}
                        )
    if not tag_binding_complete:
        gaps.append(
            _gap(
                "release_subject_binding_incomplete",
                "The immutable release tag was not authoritatively peeled to the statement subject SHA",
                artifact_id=artifact_id,
                source_evidence_id=source_id,
            )
        )
    published = data.get("draft") is False and isinstance(data.get("published_at"), str)
    artifact_binding_complete = published and _release_assets_match(data, statement)
    if published and not artifact_binding_complete:
        gaps.append(_gap("release_artifact_identity_mismatch", "Release assets do not match every statement artifact digest", artifact_id=artifact_id, endpoint=endpoint, source_evidence_id=source_id))
    classification = "success" if published else "unknown"
    return {
        "source_evidence_id": source_id,
        "source_type": "github-release",
        "state": "observed" if not gaps else "unknown",
        "classification": classification,
        "record": {
            "id": data.get("id"),
            "tag_name": data.get("tag_name"),
            "target_commitish": data.get("target_commitish"),
            "tag_binding_complete": tag_binding_complete,
            "artifact_binding_complete": artifact_binding_complete,
            "tag_object_chain": tag_object_chain,
            "draft": data.get("draft"),
            "published_at": data.get("published_at"),
        },
    }, gaps


def _validate_source_records(
    statement: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    repository: str,
    reader: _MetadataReader,
    artifact_id: int,
    max_source_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, bool]:
    source_ids = statement["source_evidence_ids"]
    if len(source_ids) > max_source_records:
        return [], [_gap("source_record_cap", f"Statement has {len(source_ids)} source records; cap is {max_source_records}", artifact_id=artifact_id)], False, False
    records: list[dict[str, Any]] = []
    record_gaps: list[dict[str, Any]] = []
    result_gaps: list[dict[str, Any]] = []
    source_types: set[str] = set()
    for source_id in source_ids:
        match = _ACTIONS_RUN_SOURCE.fullmatch(source_id)
        if match:
            record, local_gaps = _source_actions_run(source_id, match, run=run, statement=statement)
        else:
            match = _CHECK_RUN_SOURCE.fullmatch(source_id)
            if match:
                record, local_gaps = _source_check_run(source_id, match, repository=repository, statement=statement, reader=reader, artifact_id=artifact_id)
            else:
                match = _DEPLOYMENT_SOURCE.fullmatch(source_id)
                if match:
                    record, local_gaps = _source_deployment(source_id, match, repository=repository, statement=statement, reader=reader, artifact_id=artifact_id)
                else:
                    match = _PAGES_DEPLOYMENT_SOURCE.fullmatch(source_id)
                    if match:
                        record, local_gaps = _source_pages_deployment(
                            source_id,
                            match,
                            repository=repository,
                            reader=reader,
                            artifact_id=artifact_id,
                        )
                    else:
                        match = _RELEASE_SOURCE.fullmatch(source_id)
                        if match:
                            record, local_gaps = _source_release(source_id, match, repository=repository, statement=statement, reader=reader, artifact_id=artifact_id)
                        else:
                            record = {
                                "source_evidence_id": source_id,
                                "source_type": "unsupported",
                                "state": "unknown",
                                "classification": "unknown",
                                "record": None,
                            }
                            local_gaps = [_gap("unsupported_source_evidence_id", "Source evidence ID has no controlled resolver", artifact_id=artifact_id, source_evidence_id=source_id)]
        records.append(record)
        source_types.add(record["source_type"])
        record_gaps.extend(local_gaps)

    claim = statement["result"]
    for record in records:
        if record["state"] != "observed":
            continue
        classification = record["classification"]
        if claim in {"success", "failure"} and classification != claim:
            result_gaps.append(_gap("source_result_mismatch", f"Source record {record['source_evidence_id']!r} does not support result {claim!r}", artifact_id=artifact_id, source_evidence_id=record["source_evidence_id"]))
    if claim in {"success", "failure"} and not any(
        record["state"] == "observed" and record["classification"] == claim
        for record in records
    ):
        result_gaps.append(_gap("source_result_unproven", "No authoritative source record supports the claimed result", artifact_id=artifact_id))
    if statement["kind"] == "release" and claim == "success" and "github-release" not in source_types:
        result_gaps.append(_gap("release_source_required", "Release success requires a github-release source record", artifact_id=artifact_id))
    if (
        statement["kind"] == "deployment"
        and claim in {"success", "failure"}
        and not source_types.intersection(
            {"github-deployment-status", "github-pages-deployment"}
        )
    ):
        result_gaps.append(_gap("deployment_source_required", "Deployment success/failure requires a controlled deployment source record", artifact_id=artifact_id))
    for record in records:
        if record["source_type"] != "github-pages-deployment" or record["state"] != "observed":
            continue
        pages_record = record.get("record")
        if not isinstance(pages_record, Mapping) or pages_record.get(
            "subject_binding_complete"
        ) is not True:
            result_gaps.append(
                _gap(
                    "pages_deployment_subject_binding_incomplete",
                    "Pages deployment status does not bind the statement subject SHA",
                    artifact_id=artifact_id,
                    source_evidence_id=record["source_evidence_id"],
                )
            )
        if not isinstance(pages_record, Mapping) or pages_record.get(
            "artifact_binding_complete"
        ) is not True:
            result_gaps.append(
                _gap(
                    "pages_deployment_artifact_binding_incomplete",
                    "Pages deployment status does not bind the statement artifact digests",
                    artifact_id=artifact_id,
                    source_evidence_id=record["source_evidence_id"],
                )
            )
    source_records_complete = not record_gaps and all(
        record["state"] == "observed" for record in records
    )
    result_source_valid = source_records_complete and not result_gaps
    return records, [*record_gaps, *result_gaps], source_records_complete, result_source_valid


def _artifact_metadata(
    artifact: Any,
    *,
    expected_name: str,
    max_zip_bytes: int,
) -> tuple[int | None, int | None, list[dict[str, Any]]]:
    if not isinstance(artifact, Mapping):
        return None, None, [_gap("invalid_artifact_record", "Artifact record is not an object")]
    artifact_id = _safe_int(artifact.get("id"))
    gaps: list[dict[str, Any]] = []
    if artifact_id is None:
        gaps.append(_gap("invalid_artifact_id", "Artifact id is not a positive integer"))
    if artifact.get("name") != expected_name:
        gaps.append(_gap("unexpected_artifact_name", "Artifact does not match the exact evidence name convention", artifact_id=artifact_id))
    expired = artifact.get("expired")
    if expired is not False:
        gaps.append(_gap("artifact_expired_or_unknown", "Artifact is expired or its expiry state is unavailable", artifact_id=artifact_id))
    size = artifact.get("size_in_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        gaps.append(_gap("invalid_artifact_size", "Artifact declared size is not a positive integer", artifact_id=artifact_id))
        size = None
    elif size > max_zip_bytes:
        gaps.append(_gap("artifact_size_cap", f"Artifact declared size exceeds the {max_zip_bytes}-byte cap", artifact_id=artifact_id))
    return artifact_id, size, gaps


def _claim_key(statement: Mapping[str, Any]) -> tuple[Any, ...]:
    workflow = statement["workflow"]
    return (
        statement["repository"],
        statement["unit_id"],
        statement["subject"]["ref"],
        statement["subject"]["sha"],
        workflow["ref"],
        workflow["sha"],
        workflow["run_id"],
        workflow["run_attempt"],
        statement["kind"],
        tuple(statement["categories"]),
    )


def _mark_duplicates_and_conflicts(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    by_statement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_claim: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        statement = candidate.get("statement")
        if not isinstance(statement, Mapping):
            continue
        by_statement[statement["statement_id"]].append(candidate)
        by_claim[_claim_key(statement)].append(candidate)
    for statement_id, items in by_statement.items():
        if len(items) < 2:
            continue
        artifact_ids = [item.get("artifact_id") for item in items]
        duplicate = {
            "kind": "duplicate_statement_id",
            "statement_id": statement_id,
            "artifact_ids": artifact_ids,
        }
        duplicates.append(duplicate)
        for item in items:
            item["state"] = "unknown"
            item["gaps"].append(_gap("duplicate_statement_id", f"Statement appears in artifacts {artifact_ids}", artifact_id=item.get("artifact_id")))
    for key, items in by_claim.items():
        fingerprints = {
            (
                item["statement"]["result"],
                tuple(
                    (entry["name"], entry["value"])
                    for entry in item["statement"]["subject"]["digests"]
                ),
                tuple((entry["name"], entry["value"]) for entry in item["statement"]["artifact_digests"]),
                tuple(item["statement"]["source_evidence_ids"]),
            )
            for item in items
        }
        if len(fingerprints) < 2:
            continue
        artifact_ids = [item.get("artifact_id") for item in items]
        conflict = {
            "kind": "conflicting_claims",
            "claim_key_sha256": hashlib.sha256(repr(key).encode("utf-8")).hexdigest(),
            "artifact_ids": artifact_ids,
            "statement_ids": [item["statement"]["statement_id"] for item in items],
        }
        conflicts.append(conflict)
        for item in items:
            item["state"] = "unknown"
            item["gaps"].append(_gap("conflicting_claims", f"Conflicting claims appear in artifacts {artifact_ids}", artifact_id=item.get("artifact_id")))
    return duplicates, conflicts


def _eligible_run_population(
    value: Mapping[int, Any], *, maximum_populations: int
) -> dict[int, tuple[str, ...]]:
    if not isinstance(value, Mapping) or not value:
        raise EvidenceArtifactError(
            "eligible_runs must map at least one authoritative run id to unit IDs"
        )
    normalized: dict[int, tuple[str, ...]] = {}
    population_count = 0
    for run_id, raw_units in value.items():
        if _safe_int(run_id) is None:
            raise EvidenceArtifactError("eligible_runs keys must be positive integer run IDs")
        if not isinstance(raw_units, (list, tuple)) or not raw_units:
            raise EvidenceArtifactError(
                f"eligible_runs[{run_id}] must be a non-empty unit ID array"
            )
        population_count += len(raw_units)
        if population_count > maximum_populations:
            raise EvidenceArtifactError(
                f"eligible_runs contains more than {maximum_populations} run/unit "
                "populations"
            )
        units: list[str] = []
        for unit_id in raw_units:
            if (
                not isinstance(unit_id, str)
                or not _UNIT_ID_PATTERN.fullmatch(unit_id)
                or unit_id in {".", ".."}
            ):
                raise EvidenceArtifactError(
                    f"eligible_runs[{run_id}] contains an invalid unit ID"
                )
            if unit_id in units:
                raise EvidenceArtifactError(
                    f"eligible_runs[{run_id}] contains duplicate unit ID {unit_id!r}"
                )
            units.append(unit_id)
        normalized[run_id] = tuple(sorted(units))
    return dict(sorted(normalized.items()))


def collect_evidence_artifacts(
    repository: str,
    *,
    client: GitHubRESTClient,
    eligible_runs: Mapping[int, Any],
    category_policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_eligible_populations: int = DEFAULT_MAX_ELIGIBLE_POPULATIONS,
    max_artifacts_per_population: int = DEFAULT_MAX_ARTIFACTS_PER_POPULATION,
    max_zip_bytes: int = DEFAULT_MAX_ZIP_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
    max_source_records: int = DEFAULT_MAX_SOURCE_RECORDS,
    max_metadata_requests: int = DEFAULT_MAX_METADATA_REQUESTS,
) -> dict[str, Any]:
    """Collect and validate the exact repository-health evidence artifact set.

    Returned ``observed`` candidates are identity- and source-record-validated
    evidence inputs, not control passes or E3 assignments.
    """

    repository = _validate_repository(repository)
    max_eligible_populations = _positive_bounded(
        max_eligible_populations,
        "max_eligible_populations",
        HARD_MAX_ELIGIBLE_POPULATIONS,
    )
    max_artifacts_per_population = _positive_bounded(
        max_artifacts_per_population,
        "max_artifacts_per_population",
        HARD_MAX_ARTIFACTS_PER_POPULATION,
    )
    max_zip_bytes = _positive_bounded(max_zip_bytes, "max_zip_bytes", HARD_MAX_ZIP_BYTES)
    max_entry_bytes = _positive_bounded(max_entry_bytes, "max_entry_bytes", HARD_MAX_ENTRY_BYTES)
    max_expanded_bytes = _positive_bounded(max_expanded_bytes, "max_expanded_bytes", HARD_MAX_EXPANDED_BYTES)
    max_source_records = _positive_bounded(max_source_records, "max_source_records", HARD_MAX_SOURCE_RECORDS)
    max_metadata_requests = _positive_bounded(max_metadata_requests, "max_metadata_requests", HARD_MAX_METADATA_REQUESTS)

    eligible = _eligible_run_population(
        eligible_runs,
        maximum_populations=max_eligible_populations,
    )
    bundle_gaps: list[dict[str, Any]] = []
    listings: list[dict[str, Any]] = []
    enumerated: list[tuple[int, str, bool, Any]] = []
    for eligible_run_id, eligible_units in eligible.items():
        for eligible_unit_id in eligible_units:
            exact_name = evidence_artifact_name(eligible_unit_id)
            listing_endpoint = _endpoint(
                repository,
                f"/actions/runs/{eligible_run_id}/artifacts",
                {"name": exact_name, "per_page": 100},
            )
            listing = client.paginate(
                listing_endpoint,
                "artifacts",
                max_pages=MAX_ARTIFACT_PAGES,
                max_items=max_artifacts_per_population,
            )
            if not isinstance(listing, Mapping):
                listing = {
                    "population_complete": False,
                    "complete": False,
                    "items": [],
                    "gap": "invalid_artifact_population",
                    "error": "Artifact pagination result is not an object",
                }
            raw_items = listing.get("items")
            items = list(raw_items) if isinstance(raw_items, list) else []
            listing_complete = listing.get("population_complete") is True
            listing_gap = listing.get("gap")
            if len(items) > max_artifacts_per_population:
                items = items[:max_artifacts_per_population]
                listing_complete = False
                listing_gap = "item_cap"
                bundle_gaps.append(
                    _gap(
                        "item_cap",
                        f"Eligible run/unit {eligible_run_id}/{eligible_unit_id} "
                        f"returned more than the {max_artifacts_per_population}-artifact cap",
                        endpoint=listing_endpoint,
                    )
                )
            reported_total = listing.get("reported_total_count")
            if (
                listing_complete
                and (
                    isinstance(reported_total, bool)
                    or not isinstance(reported_total, int)
                    or reported_total < 0
                    or reported_total != len(items)
                )
            ):
                listing_complete = False
                listing_gap = "artifact_population_count_mismatch"
                bundle_gaps.append(
                    _gap(
                        "artifact_population_count_mismatch",
                        f"Eligible run/unit {eligible_run_id}/{eligible_unit_id} "
                        "reported a total that does not match the enumerated population",
                        endpoint=listing_endpoint,
                    )
                )
            listings.append(
                {
                    "run_id": eligible_run_id,
                    "unit_id": eligible_unit_id,
                    "artifact_name": exact_name,
                    "endpoint": listing_endpoint,
                    "page_count": listing.get("page_count"),
                    "item_count": listing.get("item_count"),
                    "reported_total_count": reported_total,
                    "complete": listing.get("complete"),
                    "population_complete": listing_complete,
                    "gap": listing_gap,
                    "observed_at": listing.get("observed_at"),
                }
            )
            if not listing_complete and not any(
                gap.get("endpoint") == listing_endpoint
                and gap.get("kind")
                in {"item_cap", "artifact_population_count_mismatch"}
                for gap in bundle_gaps
            ):
                bundle_gaps.append(
                    _gap(
                        str(listing_gap or "artifact_population_incomplete"),
                        f"Eligible run/unit {eligible_run_id}/{eligible_unit_id} "
                        "artifact population is incomplete: "
                        f"{listing.get('error') or 'unknown pagination gap'}",
                        endpoint=listing_endpoint,
                    )
                )
            if not items and listing_complete:
                bundle_gaps.append(
                    _gap(
                        "evidence_artifact_missing",
                        f"Eligible run/unit {eligible_run_id}/{eligible_unit_id} has no "
                        f"exact {exact_name!r} artifact",
                        endpoint=listing_endpoint,
                    )
                )
            enumerated.extend(
                (eligible_run_id, eligible_unit_id, listing_complete, artifact)
                for artifact in items
            )

    artifact_ids = [
        _safe_int(item.get("id")) if isinstance(item, Mapping) else None
        for _, _, _, item in enumerated
    ]
    duplicate_artifact_ids = {
        artifact_id for artifact_id, count in Counter(artifact_ids).items() if artifact_id is not None and count > 1
    }
    duplicates: list[dict[str, Any]] = [
        {
            "kind": "duplicate_artifact_id",
            "artifact_id": artifact_id,
            "occurrences": artifact_ids.count(artifact_id),
        }
        for artifact_id in sorted(duplicate_artifact_ids)
    ]

    reader = _MetadataReader(client, max_metadata_requests)
    candidates: list[dict[str, Any]] = []
    for index, (
        eligible_run_id,
        eligible_unit_id,
        eligible_population_complete,
        artifact,
    ) in enumerate(enumerated):
        artifact_id, declared_size, metadata_gaps = _artifact_metadata(
            artifact,
            expected_name=evidence_artifact_name(eligible_unit_id),
            max_zip_bytes=max_zip_bytes,
        )
        candidate = _candidate(index, artifact, artifact_id)
        candidate["eligible_run_id"] = eligible_run_id
        candidate["eligible_unit_id"] = eligible_unit_id
        candidate["eligible_population_complete"] = eligible_population_complete
        candidate["gaps"].extend(metadata_gaps)
        if not eligible_population_complete:
            candidate["gaps"].append(
                _gap(
                    "artifact_population_incomplete",
                    f"Eligible run {eligible_run_id} artifact population is incomplete",
                    artifact_id=artifact_id,
                )
            )
        candidates.append(candidate)
        if artifact_id in duplicate_artifact_ids:
            candidate["gaps"].append(
                _gap(
                    "duplicate_artifact_id",
                    "Artifact id occurs more than once in the enumerated population",
                    artifact_id=artifact_id,
                )
            )
        if candidate["gaps"] or artifact_id is None or declared_size is None:
            continue

        download_endpoint = _endpoint(repository, f"/actions/artifacts/{artifact_id}/zip")
        download = download_actions_artifact(
            client,
            download_endpoint,
            max_bytes=max_zip_bytes,
        )
        if not download.get("ok") or not isinstance(download.get("data"), bytes):
            candidate["gaps"].append(
                _response_gap(
                    download,
                    label="Evidence artifact download",
                    artifact_id=artifact_id,
                    endpoint=download_endpoint,
                )
            )
            continue
        content = download["data"]
        candidate["artifact_sha256"] = hashlib.sha256(content).hexdigest()
        metadata_digest = artifact.get("digest") if isinstance(artifact, Mapping) else None
        if metadata_digest is not None:
            match = _SHA256_PATTERN.fullmatch(metadata_digest) if isinstance(metadata_digest, str) else None
            if match is None or match.group(1) != candidate["artifact_sha256"]:
                candidate["gaps"].append(
                    _gap(
                        "artifact_digest_mismatch",
                        "Artifact metadata digest is invalid or does not match downloaded ZIP bytes",
                        artifact_id=artifact_id,
                        endpoint=download_endpoint,
                    )
                )
                continue

        files, zip_details, zip_gaps = _read_evidence_zip(
            content,
            max_entry_bytes=max_entry_bytes,
            max_expanded_bytes=max_expanded_bytes,
        )
        candidate["zip"] = zip_details
        candidate["gaps"].extend(
            {**gap, "artifact_id": artifact_id} for gap in zip_gaps
        )
        if files is None:
            continue
        statement, package_gaps = _validate_package_files(
            files,
            repository=repository,
            now=now,
        )
        candidate["gaps"].extend(
            {**gap, "artifact_id": artifact_id} for gap in package_gaps
        )
        if statement is None:
            continue
        candidate["package_valid"] = True
        candidate["statement"] = statement
        if statement["unit_id"] != eligible_unit_id:
            candidate["gaps"].append(
                _gap(
                    "ineligible_unit_id",
                    f"Statement unit {statement['unit_id']!r} does not match eligible "
                    f"run/unit {eligible_run_id}/{eligible_unit_id}",
                    artifact_id=artifact_id,
                )
            )
        candidate["category_policy_valid"] = _category_policy_matches(
            statement, category_policy
        )
        if not candidate["category_policy_valid"]:
            candidate["gaps"].append(
                _gap(
                    "category_policy_unverified",
                    "No controlled unit/kind/workflow policy authorizes the exact categories",
                    artifact_id=artifact_id,
                )
            )

        workflow = statement["workflow"]
        run_endpoint = _endpoint(
            repository,
            f"/actions/runs/{eligible_run_id}/attempts/{workflow['run_attempt']}",
        )
        run_result = reader.get(run_endpoint)
        if not run_result.get("ok"):
            candidate["gaps"].append(
                _response_gap(
                    run_result,
                    label="Authoritative Actions run attempt",
                    artifact_id=artifact_id,
                    endpoint=run_endpoint,
                )
            )
            continue
        run = run_result.get("data")
        selected_run, identity_gaps = _validate_run_identity(
            run,
            repository=repository,
            statement=statement,
            artifact_workflow_run=artifact.get("workflow_run") if isinstance(artifact, Mapping) else None,
            endpoint=run_endpoint,
            artifact_id=artifact_id,
        )
        candidate["authoritative_run"] = selected_run
        candidate["gaps"].extend(identity_gaps)
        candidate["identity_complete"] = not identity_gaps
        candidate["authoritative_workflow_valid"] = bool(
            selected_run and selected_run.get("workflow_identity_basis")
        )
        if identity_gaps or not isinstance(run, Mapping):
            continue

        (
            source_records,
            source_gaps,
            source_records_complete,
            result_source_valid,
        ) = _validate_source_records(
            statement,
            run=run,
            repository=repository,
            reader=reader,
            artifact_id=artifact_id,
            max_source_records=max_source_records,
        )
        candidate["source_records"] = source_records
        candidate["gaps"].extend(source_gaps)
        candidate["source_records_complete"] = source_records_complete
        candidate["result_source_valid"] = result_source_valid
        if (
            not candidate["gaps"]
            and source_records_complete
            and result_source_valid
            and candidate["category_policy_valid"]
            and candidate["authoritative_workflow_valid"]
        ):
            candidate["state"] = "observed"

    for eligible_run_id, eligible_units in eligible.items():
        for unit_id in eligible_units:
            matching = [
                candidate
                for candidate in candidates
                if candidate.get("eligible_run_id") == eligible_run_id
                and isinstance(candidate.get("statement"), Mapping)
                and candidate["statement"].get("unit_id") == unit_id
            ]
            if not matching:
                bundle_gaps.append(
                    _gap(
                        "eligible_unit_evidence_missing",
                        f"Eligible run {eligible_run_id} has no valid statement for unit "
                        f"{unit_id!r}",
                    )
                )

    statement_duplicates, conflicts = _mark_duplicates_and_conflicts(candidates)
    duplicates.extend(statement_duplicates)
    if duplicates:
        bundle_gaps.append(
            _gap("duplicate_evidence", "Duplicate artifact or statement identities remain unresolved")
        )
    if conflicts:
        bundle_gaps.append(
            _gap("conflicting_evidence", "Conflicting evidence claims remain unresolved")
        )
    candidate_gaps = [gap for candidate in candidates for gap in candidate["gaps"]]
    overall_state = (
        "observed"
        if all(item["population_complete"] for item in listings)
        and candidates
        and all(candidate["state"] == "observed" for candidate in candidates)
        and not bundle_gaps
        else "unknown"
    )
    verifications = _statement_verifications(candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "artifact_name_convention": f"{EVIDENCE_ARTIFACT_NAME_PREFIX}<unit_id>",
        "eligible_runs": [
            {"run_id": run_id, "unit_ids": list(unit_ids)}
            for run_id, unit_ids in eligible.items()
        ],
        "state": overall_state,
        "population_complete": all(
            item["population_complete"] for item in listings
        ),
        "observed_at": max(
            (
                item["observed_at"]
                for item in listings
                if isinstance(item.get("observed_at"), str)
            ),
            default=None,
        ),
        "listings": listings,
        "limits": {
            "max_eligible_populations": max_eligible_populations,
            "max_artifacts_per_population": max_artifacts_per_population,
            "max_zip_bytes": max_zip_bytes,
            "max_entry_bytes": max_entry_bytes,
            "max_expanded_bytes": max_expanded_bytes,
            "max_source_records": max_source_records,
            "max_metadata_requests": max_metadata_requests,
            "metadata_requests_used": reader.requests,
        },
        "candidates": candidates,
        "statement_verifications": verifications,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "gaps": [*bundle_gaps, *candidate_gaps],
        "assurance_assigned": False,
        "score_mapping_applied": False,
        "limitations": [
            "Artifact validation does not assign E3 or a control result.",
            "Category policy validation is separate from source-result validation; no category is mapped to a measure or score.",
            "Unsupported or inaccessible source records remain Unknown.",
        ],
    }


def _statement_verifications(candidates: list[Any]) -> list[dict[str, Any]]:
    """Project collector-owned candidates into the resolver schema.

    This is a trust-boundary projection, not a new evaluation. A verification
    is emitted only when at least one authoritative source record was resolved.
    Release/deployment artifact binding remains separate from package, workflow,
    result, and category-policy validation.
    """

    verifications: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        statement = candidate.get("statement")
        records = candidate.get("source_records")
        if not isinstance(statement, Mapping) or not isinstance(records, list):
            continue
        observed_records = [
            record
            for record in records
            if isinstance(record, Mapping)
            and record.get("state") == "observed"
            and isinstance(record.get("source_evidence_id"), str)
        ]
        matched_ids = sorted(
            {record["source_evidence_id"] for record in observed_records}
        )
        if not matched_ids:
            continue
        kind = statement.get("kind")
        artifact_binding_complete = kind not in {"release", "deployment"}
        if kind == "release":
            artifact_binding_complete = any(
                record.get("source_type") == "github-release"
                and isinstance(record.get("record"), Mapping)
                and record["record"].get("tag_binding_complete") is True
                and record["record"].get("artifact_binding_complete") is True
                and bool(statement.get("artifact_digests"))
                for record in observed_records
            )
        elif kind == "deployment":
            artifact_binding_complete = any(
                record.get("source_type") == "github-deployment-status"
                and isinstance(record.get("record"), Mapping)
                and record["record"].get("artifact_binding_complete") is True
                and bool(statement.get("artifact_digests"))
                for record in observed_records
            )
        population_complete = candidate.get("eligible_population_complete") is True
        source_binding_complete = bool(
            candidate.get("identity_complete") is True
            and candidate.get("source_records_complete") is True
        )
        result_binding_complete = candidate.get("result_source_valid") is True
        category_policy_verified = candidate.get("category_policy_valid") is True
        gap_kinds = {
            gap.get("kind")
            for gap in candidate.get("gaps", [])
            if isinstance(gap, Mapping)
        }
        conflict = bool(
            gap_kinds.intersection(
                {
                    "duplicate_artifact_id",
                    "duplicate_statement_id",
                    "conflicting_claims",
                }
            )
        )
        verified = all(
            (
                population_complete,
                source_binding_complete,
                result_binding_complete,
                artifact_binding_complete,
                category_policy_verified,
                candidate.get("state") == "observed",
            )
        )
        subject = statement.get("subject")
        verifications.append(
            {
                "schema_version": STATEMENT_VERIFICATION_SCHEMA,
                "statement_id": statement.get("statement_id"),
                "repository": statement.get("repository"),
                "unit_id": statement.get("unit_id"),
                "source_sha": subject.get("sha") if isinstance(subject, Mapping) else None,
                "state": "conflict" if conflict else ("verified" if verified else "unknown"),
                "population_complete": population_complete,
                "source_binding_complete": source_binding_complete,
                "result_binding_complete": result_binding_complete,
                "artifact_binding_complete": artifact_binding_complete,
                "category_policy_verified": category_policy_verified,
                "matched_authoritative_source_ids": matched_ids,
            }
        )
    return verifications


__all__ = [
    "EVIDENCE_ARTIFACT_NAME_PREFIX",
    "EvidenceArtifactError",
    "SCHEMA_VERSION",
    "STATEMENT_VERIFICATION_SCHEMA",
    "collect_evidence_artifacts",
    "download_actions_artifact",
    "evidence_artifact_name",
]

"""Read and validate durable repository-health history from GitHub.

The evidence branch is treated as an untrusted byte store.  This collector
resolves one immutable branch commit, enumerates its complete recursive tree,
downloads only the controlled latest pointer and bounded newest snapshot
segment, and then runs the network-free history validator over the exact
decoded bytes.  Invalid or partial state inside that segment is never returned
as prior history; an unselected prefix is represented only by an opaque digest.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Mapping
from urllib.parse import quote

from .github_client import GitHubRESTClient, utc_now
from .history import (
    HistoryValidationError,
    _validate_latest_pointer,
    sha256_bytes,
    validate_snapshot_bytes,
)


EVIDENCE_ID = "E-GH-DURABLE-HISTORY"
EVIDENCE_SOURCE = "github-rest:durable-history"
DEFAULT_MAX_LATEST_BYTES = 64 * 1024
DEFAULT_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TREE_ENTRIES = 100_000
DEFAULT_MAX_MATCHING_REFS = 10_000
DEFAULT_MAX_MATCHING_REF_PAGES = 100
REQUIRED_DAILY_WINDOW_SNAPSHOTS = 366

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SNAPSHOT_PATH_PATTERN = re.compile(
    r"^evidence/snapshots/(?P<year>[0-9]{4})/(?P<month>[0-9]{2})/"
    r"(?P<assessment_id>RHA-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}(?:-run[0-9]+)?)\.json$"
)
_LATEST_PATH = "evidence/latest.json"
_BLOB_MODE = "100644"
_TREE_MODE = "040000"


class _RemoteHistoryError(ValueError):
    """Internal structured failure converted to an explicit Unknown result."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        endpoint: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.endpoint = endpoint
        self.status = status


def _validate_branch(branch: Any) -> str:
    if not isinstance(branch, str) or not branch or len(branch) > 255:
        raise ValueError("branch must be a non-empty string no longer than 255 characters")
    if (
        branch == "@"
        or branch.startswith(("/", "."))
        or branch.endswith(("/", "."))
        or "//" in branch
        or ".." in branch
        or "@{" in branch
        or any(character in branch for character in " ~^:?*[\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in branch)
        or any(part.endswith(".lock") or part.startswith(".") for part in branch.split("/"))
    ):
        raise ValueError("branch is not a safe Git branch name")
    return branch


def _safe_message(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return value[:512]


def _request_record(label: str, endpoint: str, result: Mapping[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    state = result.get("state") if isinstance(result.get("state"), str) else "unknown"
    valid_status = isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300
    return {
        "label": label,
        "endpoint": endpoint,
        "status": status if isinstance(status, int) and not isinstance(status, bool) else None,
        "state": state,
        "complete": result.get("ok") is True and state == "observed" and valid_status,
    }


def _request(client: GitHubRESTClient, label: str, endpoint: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw_result = client.get(endpoint)
    except Exception as error:  # A transport/client exception is evidence unavailability.
        result: dict[str, Any] = {
            "ok": False,
            "state": "unknown",
            "status": None,
            "data": None,
            "error": f"GitHub client raised {type(error).__name__}",
            "error_kind": "client_exception",
        }
    else:
        if isinstance(raw_result, Mapping):
            result = dict(raw_result)
        else:
            result = {
                "ok": False,
                "state": "unknown",
                "status": None,
                "data": None,
                "error": "GitHub client returned a non-object result",
                "error_kind": "malformed_api_response",
            }
    return result, _request_record(label, endpoint, result)


def _matching_refs_request(
    client: GitHubRESTClient,
    endpoint: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw_result = client.paginate(
            endpoint,
            max_pages=DEFAULT_MAX_MATCHING_REF_PAGES,
            max_items=DEFAULT_MAX_MATCHING_REFS,
        )
    except Exception as error:
        result: dict[str, Any] = {
            "state": "unknown",
            "complete": False,
            "population_complete": False,
            "items": [],
            "error": f"GitHub client raised {type(error).__name__}",
            "gap": "client_exception",
            "page_count": 0,
            "item_count": 0,
        }
    else:
        result = dict(raw_result) if isinstance(raw_result, Mapping) else {
            "state": "unknown",
            "complete": False,
            "population_complete": False,
            "items": [],
            "error": "GitHub client returned a non-object pagination result",
            "gap": "malformed_api_response",
            "page_count": 0,
            "item_count": 0,
        }
    complete = (
        result.get("state") == "observed"
        and result.get("complete") is True
        and result.get("population_complete") is True
        and isinstance(result.get("items"), list)
    )
    record = {
        "label": "matching_evidence_refs",
        "endpoint": endpoint,
        "status": None,
        "state": "observed" if complete else "unknown",
        "complete": complete,
        "page_count": result.get("page_count"),
        "item_count": result.get("item_count"),
    }
    return result, record


def _authenticated_client(client: GitHubRESTClient) -> bool:
    token = getattr(client, "token", None)
    return isinstance(token, str) and bool(token.strip())


def _observed_payload(result: Mapping[str, Any], endpoint: str, label: str) -> dict[str, Any]:
    status = result.get("status")
    valid_status = isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300
    if result.get("ok") is not True or result.get("state") != "observed" or not valid_status:
        raise _RemoteHistoryError(
            str(result.get("error_kind") or "api_request_failed"),
            _safe_message(result.get("error"), f"GitHub did not return complete {label} evidence"),
            endpoint=endpoint,
            status=status if isinstance(status, int) and not isinstance(status, bool) else None,
        )
    payload = result.get("data")
    if not isinstance(payload, dict):
        raise _RemoteHistoryError(
            "malformed_api_response",
            f"GitHub {label} response must be an object",
            endpoint=endpoint,
            status=status,
        )
    return payload


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object identity is SHA-1.


def _decode_blob(
    payload: Mapping[str, Any],
    *,
    expected_sha: str,
    expected_size: int,
    maximum_size: int,
    endpoint: str,
) -> bytes:
    if payload.get("sha") != expected_sha:
        raise _RemoteHistoryError(
            "blob_identity_conflict",
            "GitHub blob identity conflicts with the selected tree entry",
            endpoint=endpoint,
        )
    size = payload.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size != expected_size:
        raise _RemoteHistoryError(
            "blob_size_conflict",
            "GitHub blob size conflicts with the selected tree entry",
            endpoint=endpoint,
        )
    if size < 1 or size > maximum_size:
        raise _RemoteHistoryError(
            "blob_size_cap",
            f"GitHub blob exceeds the controlled {maximum_size}-byte limit",
            endpoint=endpoint,
        )
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise _RemoteHistoryError(
            "malformed_blob",
            "GitHub blob must contain base64-encoded content",
            endpoint=endpoint,
        )
    content = payload["content"]
    expected_encoded_size = 4 * ((size + 2) // 3)
    # GitHub wraps base64 with LF characters.  Bound the encoded representation
    # before normalization as well as the decoded byte population.
    if len(content) > expected_encoded_size + (expected_encoded_size // 60) + 2:
        raise _RemoteHistoryError(
            "blob_size_cap",
            "GitHub blob base64 representation exceeds its declared size",
            endpoint=endpoint,
        )
    compact = content.replace("\n", "")
    if len(compact) != expected_encoded_size:
        raise _RemoteHistoryError(
            "malformed_blob",
            "GitHub blob base64 length conflicts with its declared size",
            endpoint=endpoint,
        )
    try:
        data = base64.b64decode(compact.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise _RemoteHistoryError(
            "malformed_blob",
            "GitHub blob content is not valid base64",
            endpoint=endpoint,
        ) from error
    if len(data) != size:
        raise _RemoteHistoryError(
            "blob_size_conflict",
            "Decoded GitHub blob length conflicts with its declared size",
            endpoint=endpoint,
        )
    if _git_blob_sha(data) != expected_sha:
        raise _RemoteHistoryError(
            "blob_identity_conflict",
            "Decoded bytes do not match the Git blob identity selected by the tree",
            endpoint=endpoint,
        )
    return data


def _tree_blobs(
    payload: Mapping[str, Any],
    *,
    expected_tree_sha: str,
    endpoint: str,
) -> dict[str, dict[str, Any]]:
    if payload.get("sha") != expected_tree_sha:
        raise _RemoteHistoryError(
            "tree_identity_conflict",
            "GitHub tree identity conflicts with the selected evidence commit",
            endpoint=endpoint,
        )
    if payload.get("truncated") is not False:
        raise _RemoteHistoryError(
            "tree_truncated",
            "GitHub did not return a complete recursive evidence tree",
            endpoint=endpoint,
        )
    raw_entries = payload.get("tree")
    if not isinstance(raw_entries, list):
        raise _RemoteHistoryError(
            "malformed_api_response",
            "GitHub recursive tree response must contain an entry array",
            endpoint=endpoint,
        )
    if len(raw_entries) > DEFAULT_MAX_TREE_ENTRIES:
        raise _RemoteHistoryError(
            "tree_entry_cap",
            f"Evidence tree exceeds the controlled {DEFAULT_MAX_TREE_ENTRIES}-entry limit",
            endpoint=endpoint,
        )

    entries: dict[str, dict[str, Any]] = {}
    blobs: dict[str, dict[str, Any]] = {}
    directories: set[str] = set()
    snapshot_paths: list[str] = []
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise _RemoteHistoryError(
                "malformed_api_response",
                f"GitHub tree entry {index} must be an object",
                endpoint=endpoint,
            )
        path = raw_entry.get("path")
        if not isinstance(path, str) or not path or len(path) > 512 or path in entries:
            raise _RemoteHistoryError(
                "tree_path_conflict",
                "Evidence tree contains an invalid or duplicate path",
                endpoint=endpoint,
            )
        entry_type = raw_entry.get("type")
        mode = raw_entry.get("mode")
        sha = raw_entry.get("sha")
        if not isinstance(sha, str) or _GIT_SHA_PATTERN.fullmatch(sha) is None:
            raise _RemoteHistoryError(
                "malformed_api_response",
                f"Evidence tree entry {path!r} lacks a controlled Git identity",
                endpoint=endpoint,
            )
        entries[path] = raw_entry
        if entry_type == "tree" and mode == _TREE_MODE:
            directories.add(path)
            continue
        if entry_type != "blob" or mode != _BLOB_MODE:
            raise _RemoteHistoryError(
                "unexpected_tree_entry",
                f"Evidence branch contains unsupported entry {path!r}",
                endpoint=endpoint,
            )
        if path == _LATEST_PATH:
            pass
        else:
            match = _SNAPSHOT_PATH_PATTERN.fullmatch(path)
            if match is None or len(match.group("assessment_id")) > 160:
                raise _RemoteHistoryError(
                    "unexpected_tree_entry",
                    f"Evidence branch contains uncontrolled blob path {path!r}",
                    endpoint=endpoint,
                )
            snapshot_paths.append(path)
        size = raw_entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise _RemoteHistoryError(
                "malformed_api_response",
                f"Evidence blob {path!r} lacks a positive declared size",
                endpoint=endpoint,
            )
        blobs[path] = raw_entry

    if _LATEST_PATH not in blobs or not snapshot_paths:
        raise _RemoteHistoryError(
            "partial_history",
            "Existing evidence branch must contain latest.json and at least one snapshot",
            endpoint=endpoint,
        )
    expected_directories = {"evidence", "evidence/snapshots"}
    for path in snapshot_paths:
        match = _SNAPSHOT_PATH_PATTERN.fullmatch(path)
        if match is None:  # Defensive: snapshot_paths is populated only after this match.
            raise _RemoteHistoryError(
                "unexpected_tree_entry",
                f"Evidence branch contains uncontrolled blob path {path!r}",
                endpoint=endpoint,
            )
        expected_directories.add(f"evidence/snapshots/{match.group('year')}")
        expected_directories.add(
            f"evidence/snapshots/{match.group('year')}/{match.group('month')}"
        )
    if directories != expected_directories:
        raise _RemoteHistoryError(
            "unexpected_tree_entry",
            "Evidence branch directory structure is missing or contains uncontrolled paths",
            endpoint=endpoint,
        )
    return blobs


def _validate_remote_segment(
    blob_bytes: Mapping[str, bytes],
    repository: str,
    *,
    total_snapshot_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None, bool]:
    """Validate one newest, hash-linked segment without asserting its opaque prefix.

    Every selected snapshot is parsed by the network-free history validator.
    A segment may terminate at one unavailable predecessor digest only when the
    complete tree proves that older snapshot paths exist.  That digest is an
    opaque anchor, not evidence that the unselected prefix is valid.
    """

    snapshot_paths = sorted(path for path in blob_bytes if path != _LATEST_PATH)
    if not snapshot_paths:
        raise HistoryValidationError("history segment has a latest pointer but no snapshots")
    if total_snapshot_count < len(snapshot_paths):
        raise HistoryValidationError("history segment exceeds the complete tree population")

    records: dict[str, tuple[str, dict[str, Any]]] = {}
    identities: set[str] = set()
    for path in snapshot_paths:
        snapshot = validate_snapshot_bytes(blob_bytes[path], expected_path=path)
        if snapshot.get("repository") != repository:
            raise HistoryValidationError(
                "history repository identity conflicts with the requested repository"
            )
        digest = sha256_bytes(blob_bytes[path])
        if digest in records:
            raise HistoryValidationError("history segment contains duplicate snapshot bytes")
        if snapshot["assessment_id"] in identities:
            raise HistoryValidationError("history segment contains a duplicate assessment_id")
        records[digest] = (path, snapshot)
        identities.add(snapshot["assessment_id"])

    latest = _validate_latest_pointer(blob_bytes[_LATEST_PATH])
    if latest.get("repository") != repository:
        raise HistoryValidationError("latest pointer repository conflicts with the requested repository")

    current_digest: str | None = latest["snapshot_sha256"]
    ordered_reversed: list[dict[str, Any]] = []
    visited: set[str] = set()
    while current_digest in records:
        if current_digest in visited:
            raise HistoryValidationError("history segment contains a hash cycle")
        _, snapshot = records[current_digest]
        visited.add(current_digest)
        ordered_reversed.append(snapshot)
        current_digest = snapshot["previous_snapshot_sha256"]

    if visited != set(records):
        raise HistoryValidationError(
            "history segment contains a missing, mutated, orphaned, or conflicting snapshot"
        )

    ordered = list(reversed(ordered_reversed))
    if [snapshot["snapshot_path"] for snapshot in ordered] != snapshot_paths:
        raise HistoryValidationError("history segment path order conflicts with its hash order")
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier["generated_at"] >= later["generated_at"]:
            raise HistoryValidationError("history segment timestamps are not strictly increasing")
        if earlier["repository"] != later["repository"]:
            raise HistoryValidationError("history repository identity changes within the segment")

    tip = ordered[-1]
    for field in (
        "assessment_id",
        "generated_at",
        "repository",
        "snapshot_path",
        "previous_snapshot_sha256",
    ):
        if latest.get(field) != tip.get(field):
            raise HistoryValidationError(f"latest pointer {field} does not match the segment tip")

    has_unselected_prefix = total_snapshot_count > len(records)
    if has_unselected_prefix and current_digest is None:
        raise HistoryValidationError(
            "history tree contains older snapshots but the selected segment declares genesis"
        )
    if not has_unselected_prefix and current_digest is not None:
        raise HistoryValidationError("complete history chain has a missing or mutated predecessor")
    opaque_predecessor_sha256 = current_digest if has_unselected_prefix else None
    return ordered, latest, opaque_predecessor_sha256, not has_unselected_prefix


def _daily_window_status(
    snapshots: list[dict[str, Any]],
    *,
    reference_instant: datetime,
) -> dict[str, Any]:
    """Describe coverage for every required W365 UTC calendar day.

    The current day plus the preceding 365 UTC calendar days requires 366
    distinct daily observations.  Extra runs on a day do not mask a missing
    day.
    """

    reference = reference_instant.astimezone(timezone.utc)
    reference_date = reference.date()
    required_dates = {
        reference_date - timedelta(days=offset)
        for offset in range(REQUIRED_DAILY_WINDOW_SNAPSHOTS)
    }
    observed_dates: set[Any] = set()
    tip_date = None
    try:
        observed_dates = {
            datetime.fromisoformat(snapshot["generated_at"]).astimezone(timezone.utc).date()
            for snapshot in snapshots
        }
        if snapshots:
            tip_date = (
                datetime.fromisoformat(snapshots[-1]["generated_at"])
                .astimezone(timezone.utc)
                .date()
            )
    except (KeyError, TypeError, ValueError):
        observed_dates = set()
        tip_date = None
    missing_dates = sorted(required_dates - observed_dates)
    future_tip = tip_date is not None and tip_date > reference_date
    freshness_days = (reference_date - tip_date).days if tip_date is not None else None
    return {
        "complete": (
            len(snapshots) >= REQUIRED_DAILY_WINDOW_SNAPSHOTS
            and not missing_dates
            and not future_tip
        ),
        "reference_date": reference_date.isoformat(),
        "start_date": min(required_dates).isoformat(),
        "end_date": max(required_dates).isoformat(),
        "missing_dates": [day.isoformat() for day in missing_dates],
        "tip_freshness_days": freshness_days,
    }


def _base_result(
    *,
    repository: str,
    branch: str,
    observed_at: str,
    branch_sha: str | None,
    tree_sha: str | None,
    state: str,
    complete: bool,
    no_history: bool,
    snapshots: list[dict[str, Any]],
    latest: dict[str, Any] | None,
    gaps: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    max_snapshots: int,
    total_snapshot_count: int = 0,
    segment_complete: bool = False,
    window_complete: bool = False,
    full_chain_complete: bool = False,
    opaque_predecessor_sha256: str | None = None,
    window_reference_date: str | None = None,
    window_start_date: str | None = None,
    window_end_date: str | None = None,
    missing_daily_dates: list[str] | None = None,
    freshness_days: int | None = None,
) -> dict[str, Any]:
    any_observed = any(record.get("state") == "observed" for record in requests)
    completeness = "complete" if complete else ("partial" if any_observed else "unknown")
    validation_scope = (
        "no_history"
        if no_history
        else (
            "full_chain"
            if full_chain_complete
            else ("bounded_newest_segment" if segment_complete else "unavailable")
        )
    )
    return {
        "evidence_id": EVIDENCE_ID,
        "observed_at": observed_at,
        "source": EVIDENCE_SOURCE,
        "repository": repository,
        "branch": branch,
        "branch_sha": branch_sha,
        "tree_sha": tree_sha,
        "state": state,
        "completeness": completeness,
        "complete": complete,
        "population_complete": complete,
        "no_history": no_history,
        "validation_scope": validation_scope,
        "segment_complete": segment_complete,
        "window_complete": window_complete,
        "window_reference_date": window_reference_date,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "missing_daily_dates": list(missing_daily_dates or []),
        "freshness_days": freshness_days,
        "full_chain_complete": full_chain_complete,
        "opaque_predecessor_sha256": opaque_predecessor_sha256,
        "snapshots": snapshots,
        "latest": latest,
        "data": {
            "snapshot_count": len(snapshots),
            "selected_snapshot_count": len(snapshots),
            "total_snapshot_count": total_snapshot_count,
            "snapshot_paths": [snapshot["snapshot_path"] for snapshot in snapshots],
            "validation_scope": validation_scope,
            "segment_complete": segment_complete,
            "window_complete": window_complete,
            "required_daily_window_snapshots": REQUIRED_DAILY_WINDOW_SNAPSHOTS,
            "window_reference_date": window_reference_date,
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
            "missing_daily_dates": list(missing_daily_dates or []),
            "tip_freshness_days": freshness_days,
            "full_chain_complete": full_chain_complete,
            "opaque_predecessor_sha256": opaque_predecessor_sha256,
        },
        "gaps": gaps,
        "request": {
            "endpoints": requests,
            "limits": {
                "max_snapshots": max_snapshots,
                "max_latest_bytes": DEFAULT_MAX_LATEST_BYTES,
                "max_snapshot_bytes": DEFAULT_MAX_SNAPSHOT_BYTES,
                "max_total_bytes": DEFAULT_MAX_TOTAL_BYTES,
                "max_tree_entries": DEFAULT_MAX_TREE_ENTRIES,
            },
        },
    }


def collect_remote_history(
    repository: str,
    client: GitHubRESTClient,
    branch: str = "repository-health-evidence",
    max_snapshots: int = 400,
) -> dict[str, Any]:
    """Return a validated newest durable-history segment from one commit.

    Successful callers pass ``result["snapshots"]`` directly as
    ``normalize_observations(..., prior_history=...)``.  If any API response,
    tree entry, selected blob, or in-segment chain validation is incomplete,
    the result is ``unknown`` and ``snapshots`` is empty.  Histories longer
    than ``max_snapshots`` retain the oldest selected row's predecessor digest
    as an opaque anchor; they never claim genesis validation.  A 404 for the
    exact evidence ref returns ``state == "no_history"`` only when a separate,
    complete authenticated matching-ref inventory proves that exact ref absent.
    """

    if not isinstance(repository, str) or _REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ValueError("repository must use GitHub owner/name form")
    selected_branch = _validate_branch(branch)
    if not isinstance(max_snapshots, int) or isinstance(max_snapshots, bool) or max_snapshots < 1:
        raise ValueError("max_snapshots must be a positive integer")

    observed_at = utc_now()
    try:
        reference_instant = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("GitHub client clock must return an ISO 8601 instant") from error
    if reference_instant.tzinfo is None:
        raise ValueError("GitHub client clock must return an offset-aware instant")
    reference_instant = reference_instant.astimezone(timezone.utc)
    branch_sha: str | None = None
    tree_sha: str | None = None
    total_snapshot_count = 0
    requests: list[dict[str, Any]] = []
    ref_endpoint = f"/repos/{repository}/git/ref/heads/{quote(selected_branch, safe='')}"
    ref_result, ref_request = _request(client, "evidence_branch", ref_endpoint)
    requests.append(ref_request)
    if ref_result.get("ok") is not True and ref_result.get("status") == 404:
        absence_kind = "unverified_branch_absence"
        absence_message = (
            "A 404 for the exact evidence ref is ambiguous without a complete authenticated ref inventory"
        )
        absence_endpoint = ref_endpoint
        if _authenticated_client(client):
            matching_endpoint = (
                f"/repos/{repository}/git/matching-refs/heads/"
                f"{quote(selected_branch, safe='')}"
            )
            matching_result, matching_request = _matching_refs_request(
                client, matching_endpoint
            )
            requests.append(matching_request)
            matching_complete = matching_request["complete"] is True
            items = matching_result.get("items") if matching_complete else None
            malformed = False
            exact_ref_present = False
            seen_refs: set[str] = set()
            expected_ref = f"refs/heads/{selected_branch}"
            if isinstance(items, list):
                for item in items:
                    ref_object = item.get("object") if isinstance(item, Mapping) else None
                    ref_name = item.get("ref") if isinstance(item, Mapping) else None
                    if (
                        not isinstance(ref_name, str)
                        or not ref_name.startswith(expected_ref)
                        or ref_name in seen_refs
                        or not isinstance(ref_object, Mapping)
                        or ref_object.get("type") != "commit"
                        or not isinstance(ref_object.get("sha"), str)
                        or _GIT_SHA_PATTERN.fullmatch(ref_object["sha"]) is None
                    ):
                        malformed = True
                        break
                    seen_refs.add(ref_name)
                    exact_ref_present = exact_ref_present or ref_name == expected_ref
            if matching_complete and isinstance(items, list) and not malformed and not exact_ref_present:
                requests[0] = {
                    **requests[0],
                    "state": "absent",
                    "complete": True,
                }
                return _base_result(
                    repository=repository,
                    branch=selected_branch,
                    observed_at=observed_at,
                    branch_sha=None,
                    tree_sha=None,
                    state="no_history",
                    complete=True,
                    no_history=True,
                    snapshots=[],
                    latest=None,
                    gaps=[],
                    requests=requests,
                    max_snapshots=max_snapshots,
                )
            if malformed:
                absence_kind = "malformed_ref_inventory"
                absence_message = "GitHub returned a malformed or conflicting matching-ref population"
                absence_endpoint = matching_endpoint
            elif exact_ref_present:
                absence_kind = "ref_absence_conflict"
                absence_message = "Exact-ref 404 conflicts with the complete matching-ref population"
                absence_endpoint = matching_endpoint
            else:
                absence_kind = str(
                    matching_result.get("gap") or "ref_inventory_incomplete"
                )
                absence_message = _safe_message(
                    matching_result.get("error"),
                    "The matching-ref population is incomplete",
                )
                absence_endpoint = matching_endpoint
        return _base_result(
            repository=repository,
            branch=selected_branch,
            observed_at=observed_at,
            branch_sha=None,
            tree_sha=None,
            state="unknown",
            complete=False,
            no_history=False,
            snapshots=[],
            latest=None,
            gaps=[
                {
                    "kind": absence_kind,
                    "status": 404,
                    "endpoint": absence_endpoint,
                    "source": EVIDENCE_SOURCE,
                    "message": absence_message,
                }
            ],
            requests=requests,
            max_snapshots=max_snapshots,
        )

    try:
        ref = _observed_payload(ref_result, ref_endpoint, "evidence branch")
        ref_object = ref.get("object")
        expected_ref = f"refs/heads/{selected_branch}"
        if (
            ref.get("ref") != expected_ref
            or not isinstance(ref_object, dict)
            or ref_object.get("type") != "commit"
            or not isinstance(ref_object.get("sha"), str)
            or _GIT_SHA_PATTERN.fullmatch(ref_object["sha"]) is None
        ):
            raise _RemoteHistoryError(
                "malformed_api_response",
                "Evidence branch does not resolve exactly to a commit",
                endpoint=ref_endpoint,
                status=ref_result.get("status"),
            )
        branch_sha = ref_object["sha"]

        commit_endpoint = f"/repos/{repository}/git/commits/{branch_sha}"
        commit_result, commit_request = _request(client, "evidence_commit", commit_endpoint)
        requests.append(commit_request)
        commit = _observed_payload(commit_result, commit_endpoint, "evidence commit")
        commit_tree = commit.get("tree")
        if (
            commit.get("sha") != branch_sha
            or not isinstance(commit_tree, dict)
            or not isinstance(commit_tree.get("sha"), str)
            or _GIT_SHA_PATTERN.fullmatch(commit_tree["sha"]) is None
        ):
            raise _RemoteHistoryError(
                "commit_identity_conflict",
                "Evidence commit identity or tree is inconsistent",
                endpoint=commit_endpoint,
                status=commit_result.get("status"),
            )
        tree_sha = commit_tree["sha"]

        tree_endpoint = f"/repos/{repository}/git/trees/{tree_sha}?recursive=1"
        tree_result, tree_request = _request(client, "evidence_tree", tree_endpoint)
        requests.append(tree_request)
        tree = _observed_payload(tree_result, tree_endpoint, "evidence tree")
        blobs = _tree_blobs(
            tree,
            expected_tree_sha=tree_sha,
            endpoint=tree_endpoint,
        )
        all_snapshot_paths = sorted(path for path in blobs if path != _LATEST_PATH)
        total_snapshot_count = len(all_snapshot_paths)
        selected_snapshot_paths = all_snapshot_paths[-max_snapshots:]

        latest_size = blobs[_LATEST_PATH]["size"]
        if latest_size > DEFAULT_MAX_LATEST_BYTES:
            raise _RemoteHistoryError(
                "blob_size_cap",
                "Evidence latest pointer exceeds its controlled size limit",
                endpoint=tree_endpoint,
            )
        for path, entry in blobs.items():
            if path != _LATEST_PATH and entry["size"] > DEFAULT_MAX_SNAPSHOT_BYTES:
                raise _RemoteHistoryError(
                    "blob_size_cap",
                    f"Evidence snapshot {path!r} exceeds its controlled size limit",
                    endpoint=tree_endpoint,
                )
        selected_paths = [_LATEST_PATH, *selected_snapshot_paths]
        declared_total = sum(blobs[path]["size"] for path in selected_paths)
        if declared_total > DEFAULT_MAX_TOTAL_BYTES:
            raise _RemoteHistoryError(
                "history_size_cap",
                "Selected evidence-history segment exceeds the controlled aggregate size limit",
                endpoint=tree_endpoint,
            )

        blob_bytes: dict[str, bytes] = {}
        for path in selected_paths:
            entry = blobs[path]
            blob_sha = entry["sha"]
            blob_endpoint = f"/repos/{repository}/git/blobs/{blob_sha}"
            blob_result, blob_request = _request(client, f"evidence_blob:{path}", blob_endpoint)
            blob_request["declared_size"] = entry["size"]
            requests.append(blob_request)
            blob = _observed_payload(blob_result, blob_endpoint, f"evidence blob {path}")
            maximum_size = DEFAULT_MAX_LATEST_BYTES if path == _LATEST_PATH else DEFAULT_MAX_SNAPSHOT_BYTES
            blob_bytes[path] = _decode_blob(
                blob,
                expected_sha=blob_sha,
                expected_size=entry["size"],
                maximum_size=maximum_size,
                endpoint=blob_endpoint,
            )

        ordered, latest, opaque_anchor, full_chain_complete = _validate_remote_segment(
            blob_bytes,
            repository,
            total_snapshot_count=total_snapshot_count,
        )
        window_status = _daily_window_status(
            ordered,
            reference_instant=reference_instant,
        )
        window_complete = bool(window_status["complete"])
    except (HistoryValidationError, _RemoteHistoryError) as error:
        if isinstance(error, _RemoteHistoryError):
            kind = error.kind
            endpoint = error.endpoint
            status = error.status
        else:
            kind = "history_validation_failed"
            endpoint = None
            status = None
        return _base_result(
            repository=repository,
            branch=selected_branch,
            observed_at=observed_at,
            branch_sha=branch_sha,
            tree_sha=tree_sha,
            state="unknown",
            complete=False,
            no_history=False,
            snapshots=[],
            latest=None,
            gaps=[
                {
                    "kind": kind,
                    "status": status,
                    "endpoint": endpoint,
                    "source": EVIDENCE_SOURCE,
                    "message": _safe_message(str(error), "Durable history validation failed"),
                }
            ],
            requests=requests,
            max_snapshots=max_snapshots,
            total_snapshot_count=total_snapshot_count,
        )

    return _base_result(
        repository=repository,
        branch=selected_branch,
        observed_at=observed_at,
        branch_sha=branch_sha,
        tree_sha=tree_sha,
        state="observed",
        complete=True,
        no_history=False,
        snapshots=ordered,
        latest=latest,
        gaps=[],
        requests=requests,
        max_snapshots=max_snapshots,
        total_snapshot_count=total_snapshot_count,
        segment_complete=True,
        window_complete=window_complete,
        full_chain_complete=full_chain_complete,
        opaque_predecessor_sha256=opaque_anchor,
        window_reference_date=window_status["reference_date"],
        window_start_date=window_status["start_date"],
        window_end_date=window_status["end_date"],
        missing_daily_dates=window_status["missing_dates"],
        freshness_days=window_status["tip_freshness_days"],
    )

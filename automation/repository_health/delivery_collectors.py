"""Selector-bound GitHub delivery evidence collection for generic identities.

The collector only reads exact GitHub REST resources and consumes explicitly
authenticated adapter records.  It does not execute repository code, invoke
Git, follow arbitrary URLs, or infer an artifact/content binding from a name.
Every permission, population, identity, or binding gap remains explicit.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote, urlsplit

from .delivery_resolution import DELIVERY_INVENTORY_SCHEMA
from .github_client import (
    DEFAULT_MAX_BINARY_BYTES,
    GitHubRESTClient,
    parse_link_header,
    utc_now,
)
from .production_identity import (
    ACTIVE_PROFILES,
    GENERIC_PRODUCTION_SCHEMA,
    ProductionIdentityError,
    validate_generic_production_identity,
)


COLLECTOR_SCHEMA = "RH-DELIVERY-COLLECTOR-1.0"
AUTHENTICATED_ADAPTER_SCHEMA = "RH-AUTHENTICATED-DELIVERY-ADAPTER-1.0"
ADAPTER_BATCH_VERIFICATION_SCHEMA = (
    "RH-AUTHENTICATED-ADAPTER-BATCH-VERIFICATION-1.0"
)
DEPLOYMENT_PAYLOAD_SCHEMA = "repository-health-deployment-artifact-binding/v1"
MAX_TAG_DEPTH = 5
MAX_ADAPTER_RECORDS = 1_000
HARD_MAX_ASSET_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TOTAL_ASSET_BYTES = 64 * 1024 * 1024
HARD_MAX_TOTAL_ASSET_BYTES = 256 * 1024 * 1024

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_UNIT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,255}$")

_ADAPTER_KEYS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "record_id",
        "repository",
        "unit_id",
        "profile",
        "source_sha",
        "state",
        "population_complete",
        "authoritative_source_id",
        "authentication",
        "binding",
    }
)
_AUTHENTICATION_KEYS = frozenset({"state", "verifier", "evidence_ids"})
_GITOPS_BINDING_KEYS = frozenset(
    {"production_ref", "path", "content_sha256"}
)
_PAGES_BINDING_KEYS = frozenset(
    {
        "deployment_id",
        "build_id",
        "publication_url",
        "content_sha256",
    }
)
_DEPLOYMENT_PAYLOAD_KEYS = frozenset({"schema_version", "unit_id", "artifact"})
_DEPLOYMENT_ARTIFACT_KEYS = frozenset({"reference", "sha256"})
_ADAPTER_BATCH_VERIFICATION_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "population_complete",
        "verifier",
        "records_sha256",
        "matched_record_ids",
    }
)


class DeliveryCollectorError(ValueError):
    """Raised when a caller violates the validated collector contract."""


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str]) -> bool:
    return all(isinstance(key, str) for key in value) and set(value) == expected


def _endpoint(repository: str, suffix: str) -> str:
    return f"/repos/{repository}{suffix}"


def _gap(
    unit_id: str | None,
    code: str,
    source: str,
    message: str,
    *,
    endpoint: str | None = None,
    status: int | None = None,
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "code": code,
        "source": source,
        "message": message,
        "endpoint": endpoint,
        "status": status,
    }


def _response_gap(
    unit_id: str,
    source: str,
    endpoint: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    code = result.get("gap") or result.get("error_kind") or "github_evidence_unavailable"
    return _gap(
        unit_id,
        str(code),
        source,
        "GitHub did not return a complete authoritative response",
        endpoint=endpoint,
        status=result.get("status") if isinstance(result.get("status"), int) else None,
    )


def _request_record(
    unit_id: str,
    source: str,
    endpoint: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "source": source,
        "endpoint": endpoint,
        "state": result.get("state"),
        "status": result.get("status"),
        "population_complete": result.get("population_complete", result.get("ok")) is True,
        "error_kind": result.get("gap") or result.get("error_kind"),
    }


def _header(headers: Any, name: str) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    expected = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == expected and isinstance(value, str):
            return value
    return None


def _paginate_cursor_collection(
    client: GitHubRESTClient,
    path: str,
    collection_key: str,
) -> dict[str, Any]:
    """Read an official cursor collection that intentionally has no total_count."""

    items: list[Any] = []
    pages: list[dict[str, Any]] = []
    visited: set[str] = set()
    next_reference: str | None = path
    error: str | None = None
    gap: str | None = None
    while next_reference is not None and error is None:
        if len(pages) >= client.max_pages:
            error = f"Pagination page cap reached ({client.max_pages})"
            gap = "page_cap"
            break
        result = client.get(next_reference)
        observed_url = result.get("url")
        visit_key = observed_url if isinstance(observed_url, str) else next_reference
        if visit_key in visited:
            error = "Pagination Link loop detected"
            gap = "pagination_loop"
            break
        visited.add(visit_key)
        if not result.get("ok"):
            error = str(result.get("error") or "request failed")
            gap = str(result.get("error_kind") or "request_failed")
            pages.append(
                {
                    "url": visit_key,
                    "status": result.get("status"),
                    "item_count": 0,
                    "state": "unknown",
                }
            )
            break
        payload = result.get("data")
        page_items = payload.get(collection_key) if isinstance(payload, Mapping) else None
        if not isinstance(page_items, list):
            error = f"Response does not contain list collection {collection_key}"
            gap = "invalid_collection"
            pages.append(
                {
                    "url": visit_key,
                    "status": result.get("status"),
                    "item_count": 0,
                    "state": "unknown",
                }
            )
            break
        remaining = client.max_items - len(items)
        accepted = page_items[:remaining]
        items.extend(accepted)
        pages.append(
            {
                "url": visit_key,
                "status": result.get("status"),
                "item_count": len(accepted),
                "state": "observed",
            }
        )
        if len(accepted) != len(page_items):
            error = f"Pagination item cap reached ({client.max_items})"
            gap = "item_cap"
            break
        next_reference = parse_link_header(_header(result.get("headers"), "Link")).get(
            "next"
        )
    complete = error is None
    return {
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else ("partial" if items else "unknown"),
        "items": items,
        "pages": pages,
        "page_count": len(pages),
        "item_count": len(items),
        "reported_total_count": None,
        "complete": complete,
        "population_complete": complete,
        "truncated": gap in {"page_cap", "item_cap"},
        "error": error,
        "gap": gap,
        "observed_at": utc_now(),
    }


def _controlled_text(value: Any, maximum: int = 2048) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _validate_identity(
    production_identity: Mapping[str, Any],
    *,
    repository: str,
    subject_main_sha: str,
) -> list[dict[str, Any]]:
    if not isinstance(production_identity, Mapping):
        raise DeliveryCollectorError("production_identity must be a validated object")
    if production_identity.get("schema_version") != GENERIC_PRODUCTION_SCHEMA:
        raise DeliveryCollectorError(
            f"production_identity must use {GENERIC_PRODUCTION_SCHEMA}"
        )
    if (
        not isinstance(repository, str)
        or _REPOSITORY.fullmatch(repository) is None
        or any(component in {".", ".."} for component in repository.split("/"))
    ):
        raise DeliveryCollectorError("repository must use exact owner/name form")
    if production_identity.get("repository") != repository:
        raise DeliveryCollectorError("production identity repository does not match")
    if not _is_sha(subject_main_sha):
        raise DeliveryCollectorError("subject_main_sha must be a lowercase full Git SHA")
    raw_units = production_identity.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise DeliveryCollectorError("production identity has no units")
    unit_ids: list[str] = []
    correspondences: list[str] = []
    authoritative_checks: list[str] | None = None
    for index, raw in enumerate(raw_units):
        if not isinstance(raw, Mapping):
            raise DeliveryCollectorError(f"production identity unit {index} is invalid")
        unit_id = raw.get("unit_id")
        correspondence = raw.get("correspondence")
        validation = raw.get("validation")
        checks = (
            validation.get("authoritative_checks")
            if isinstance(validation, Mapping)
            else None
        )
        if (
            not isinstance(unit_id, str)
            or _UNIT_ID.fullmatch(unit_id) is None
            or unit_id in unit_ids
            or not isinstance(correspondence, str)
            or not isinstance(checks, list)
            or not checks
            or not all(isinstance(check, str) for check in checks)
        ):
            raise DeliveryCollectorError(
                "production identity has an unsafe or incomplete unit contract"
            )
        if authoritative_checks is None:
            authoritative_checks = list(checks)
        elif checks != authoritative_checks:
            raise DeliveryCollectorError(
                "production identity units disagree on authoritative checks"
            )
        unit_ids.append(unit_id)
        correspondences.append(correspondence)
    configured_correspondence = (
        correspondences[0]
        if len(set(correspondences)) == 1
        else "Per-unit combination"
    )
    reconstructed_config = {
        "standard": {"version": production_identity.get("standard_version")},
        "repository": {
            "authoritative_checks": authoritative_checks,
            "deployable_units": unit_ids,
            "production_correspondence": configured_correspondence,
        },
    }
    try:
        normalized = validate_generic_production_identity(
            production_identity,
            config=reconstructed_config,
            repository=repository,
        )
    except (ProductionIdentityError, KeyError, TypeError, ValueError) as error:
        raise DeliveryCollectorError(
            f"production_identity is not a fully validated v2 contract: {error}"
        ) from error
    return [dict(unit) for unit in normalized["units"]]


def _selector_key(unit: Mapping[str, Any]) -> tuple[Any, ...] | None:
    profile = unit.get("profile")
    selector = unit.get("selector")
    if profile not in ACTIVE_PROFILES or not isinstance(selector, Mapping):
        return None
    if profile in {"application-github-deployment", "documentation-publication"}:
        return (selector.get("system"), selector.get("deployment_id"))
    if profile == "package-github-release":
        return ("github-releases", selector.get("release_id"), selector.get("tag"))
    return ("git", selector.get("production_ref"), selector.get("path"))


def _adapter_record_set_digest(values: Sequence[Mapping[str, Any]]) -> str | None:
    try:
        canonical = json.dumps(
            [dict(value) for value in values],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical).hexdigest()


def _verify_adapter_batch(
    values: Sequence[Mapping[str, Any]],
    verification: Mapping[str, Any] | None,
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    if not values and verification is None:
        return True, None, []
    digest = _adapter_record_set_digest(values)
    record_ids = [
        value.get("record_id") if isinstance(value, Mapping) else None
        for value in values
    ]
    valid = (
        isinstance(verification, Mapping)
        and _exact_keys(verification, _ADAPTER_BATCH_VERIFICATION_KEYS)
        and verification.get("schema_version") == ADAPTER_BATCH_VERIFICATION_SCHEMA
        and verification.get("state") == "verified"
        and verification.get("population_complete") is True
        and _controlled_text(verification.get("verifier"), 256)
        and digest is not None
        and verification.get("records_sha256") == digest
        and all(_controlled_text(record_id, 256) for record_id in record_ids)
        and len(record_ids) == len(set(record_ids))
        and isinstance(verification.get("matched_record_ids"), list)
        and verification.get("matched_record_ids") == sorted(record_ids)
    )
    if valid:
        return True, digest, []
    return False, digest, [
        _gap(
            None,
            "authenticated_adapter_batch_unverified",
            "authenticated-adapter",
            "Adapter records lack an exact independent batch-verification result",
        )
    ]


def _normalize_adapter_records(
    values: Sequence[Mapping[str, Any]],
    *,
    repository: str,
    declared_units: Mapping[str, str],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise DeliveryCollectorError("authenticated_adapter_records must be a sequence")
    if len(values) > MAX_ADAPTER_RECORDS:
        raise DeliveryCollectorError(
            f"authenticated_adapter_records exceeds {MAX_ADAPTER_RECORDS} records"
        )
    by_unit: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    gaps: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        unit_id = raw.get("unit_id") if isinstance(raw, Mapping) else None
        if not isinstance(raw, Mapping) or not _exact_keys(raw, _ADAPTER_KEYS):
            gaps.append(
                _gap(
                    (
                        unit_id
                        if isinstance(unit_id, str) and unit_id in declared_units
                        else None
                    ),
                    "invalid_authenticated_adapter_record",
                    "authenticated-adapter",
                    f"Adapter record {index} does not use the exact controlled schema",
                )
            )
            continue
        value = dict(raw)
        adapter_id = value.get("adapter_id")
        authentication = value.get("authentication")
        binding = value.get("binding")
        if adapter_id == "gitops-reconciliation":
            binding_keys = _GITOPS_BINDING_KEYS
            expected_profile = "gitops-production-ref"
        elif adapter_id == "pages-publication":
            binding_keys = _PAGES_BINDING_KEYS
            expected_profile = "documentation-publication"
        else:
            binding_keys = frozenset()
            expected_profile = None
        evidence_ids = (
            authentication.get("evidence_ids")
            if isinstance(authentication, Mapping)
            else None
        )
        valid = (
            value.get("schema_version") == AUTHENTICATED_ADAPTER_SCHEMA
            and adapter_id in {"gitops-reconciliation", "pages-publication"}
            and _controlled_text(value.get("record_id"), 256)
            and value.get("repository") == repository
            and isinstance(unit_id, str)
            and _UNIT_ID.fullmatch(unit_id) is not None
            and unit_id in declared_units
            and value.get("profile") == declared_units.get(unit_id)
            and value.get("profile") == expected_profile
            and _is_sha(value.get("source_sha"))
            and value.get("state") == "verified"
            and value.get("population_complete") is True
            and isinstance(value.get("authoritative_source_id"), str)
            and _SOURCE_ID.fullmatch(value["authoritative_source_id"]) is not None
            and isinstance(authentication, Mapping)
            and _exact_keys(authentication, _AUTHENTICATION_KEYS)
            and authentication.get("state") == "verified"
            and _controlled_text(authentication.get("verifier"), 256)
            and isinstance(evidence_ids, list)
            and bool(evidence_ids)
            and all(
                isinstance(item, str) and _SOURCE_ID.fullmatch(item) is not None
                for item in evidence_ids
            )
            and evidence_ids == sorted(set(evidence_ids))
            and value.get("authoritative_source_id") in evidence_ids
            and isinstance(binding, Mapping)
            and _exact_keys(binding, binding_keys)
        )
        if not valid:
            gaps.append(
                _gap(
                    (
                        unit_id
                        if isinstance(unit_id, str) and unit_id in declared_units
                        else None
                    ),
                    "invalid_authenticated_adapter_record",
                    "authenticated-adapter",
                    f"Adapter record {index} is incomplete, unauthenticated, or mis-scoped",
                )
            )
            continue
        by_unit[(unit_id, str(adapter_id))].append(value)
    return by_unit, gaps


def _adapter_for_unit(
    records: Mapping[tuple[str, str], list[dict[str, Any]]],
    *,
    unit: Mapping[str, Any],
    adapter_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    unit_id = str(unit["unit_id"])
    candidates = records.get((unit_id, adapter_id), [])
    if len(candidates) != 1:
        return None, [
            _gap(
                unit_id,
                "authenticated_adapter_ambiguous",
                "authenticated-adapter",
                f"Expected exactly one authenticated {adapter_id!r} record",
            )
        ]
    record = candidates[0]
    if record["source_sha"] != unit["source_sha"]:
        return None, [
            _gap(
                unit_id,
                "authenticated_adapter_source_mismatch",
                "authenticated-adapter",
                "Authenticated adapter record does not bind the declared source SHA",
            )
        ]
    return record, []


def _load_deployment_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        payload = dict(value)
    elif isinstance(value, str):
        try:
            def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, member in pairs:
                    if key in result:
                        raise ValueError("duplicate deployment payload key")
                    result[key] = member
                return result

            parsed = json.loads(value, object_pairs_hook=reject_duplicate)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        payload = parsed
    else:
        return None
    if not _exact_keys(payload, _DEPLOYMENT_PAYLOAD_KEYS):
        return None
    artifact = payload.get("artifact")
    if (
        payload.get("schema_version") != DEPLOYMENT_PAYLOAD_SCHEMA
        or not isinstance(payload.get("unit_id"), str)
        or not isinstance(artifact, Mapping)
        or not _exact_keys(artifact, _DEPLOYMENT_ARTIFACT_KEYS)
        or not _controlled_text(artifact.get("reference"))
        or not _is_sha256(artifact.get("sha256"))
    ):
        return None
    return {
        "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
        "unit_id": payload["unit_id"],
        "artifact": {
            "reference": artifact["reference"],
            "sha256": artifact["sha256"],
        },
    }


def _collect_application(
    unit: Mapping[str, Any],
    *,
    repository: str,
    subject_main_sha: str,
    client: GitHubRESTClient,
) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    selector = unit["selector"]
    deployment_id = selector["deployment_id"]
    deployment_endpoint = _endpoint(repository, f"/deployments/{deployment_id}")
    status_endpoint = _endpoint(
        repository, f"/deployments/{deployment_id}/statuses?per_page=100"
    )
    deployment_result = client.get(deployment_endpoint)
    statuses_result = client.paginate(status_endpoint)
    requests = [
        _request_record(unit_id, "github-deployment", deployment_endpoint, deployment_result),
        _request_record(unit_id, "github-deployment-statuses", status_endpoint, statuses_result),
    ]
    gaps: list[dict[str, Any]] = []
    api_complete = bool(deployment_result.get("ok")) and bool(
        statuses_result.get("population_complete")
    )
    if not deployment_result.get("ok"):
        gaps.append(
            _response_gap(unit_id, "github-deployment", deployment_endpoint, deployment_result)
        )
    if not statuses_result.get("population_complete"):
        gaps.append(
            _response_gap(
                unit_id, "github-deployment-statuses", status_endpoint, statuses_result
            )
        )
    deployment = deployment_result.get("data")
    statuses = statuses_result.get("items")
    item: dict[str, Any] | None = None
    if isinstance(deployment, Mapping):
        payload = _load_deployment_payload(deployment.get("payload"))
        identity_ok = (
            deployment.get("id") == deployment_id
            and deployment.get("sha") == unit["source_sha"]
            and deployment.get("environment") == selector["environment"]
        )
        if not identity_ok:
            gaps.append(
                _gap(
                    unit_id,
                    "deployment_identity_mismatch",
                    "github-deployment",
                    "Deployment ID, source SHA, or environment does not match the declaration",
                    endpoint=deployment_endpoint,
                )
            )
        artifact: dict[str, str] | None = None
        if payload is not None and payload["unit_id"] == unit_id:
            # Preserve a controlled, explicitly unit-bound artifact claim even
            # when it contradicts the declaration.  The pure resolver must be
            # able to distinguish that authoritative contradiction from an
            # absent or malformed binding.
            artifact = payload["artifact"]
        if (
            payload is None
            or payload["unit_id"] != unit_id
            or payload["artifact"] != dict(selector["artifact"])
        ):
            gaps.append(
                _gap(
                    unit_id,
                    "deployment_artifact_binding_missing",
                    "github-deployment",
                    "Deployment payload does not contain the exact controlled unit/artifact binding",
                    endpoint=deployment_endpoint,
                )
            )
        terminal: Mapping[str, Any] | None = None
        if isinstance(statuses, list) and statuses:
            first = statuses[0]
            status_ids = [
                row.get("id")
                for row in statuses
                if isinstance(row, Mapping) and _positive_int(row.get("id"))
            ]
            if (
                isinstance(first, Mapping)
                and _positive_int(first.get("id"))
                and len(status_ids) == len(statuses)
                and len(status_ids) == len(set(status_ids))
                and first.get("environment") == selector["environment"]
            ):
                terminal = first
        if terminal is None:
            gaps.append(
                _gap(
                    unit_id,
                    "deployment_terminal_status_ambiguous",
                    "github-deployment-statuses",
                    "Deployment status population has no unique ordered terminal record",
                    endpoint=status_endpoint,
                )
            )
        elif terminal.get("state") != selector["required_status"]:
            gaps.append(
                _gap(
                    unit_id,
                    "deployment_terminal_status_not_success",
                    "github-deployment-statuses",
                    "The authoritative terminal deployment status is not successful",
                    endpoint=status_endpoint,
                )
            )

        source_id = (
            f"github-deployment-status:{deployment_id}:{terminal['id']}"
            if terminal is not None
            else None
        )
        item = {
            "inventory_id": f"github-deployments:{deployment_id}",
            "adapter_id": "github-deployments",
            "delivery_kind": "deployment",
            "repository": repository,
            "unit_selector": unit_id,
            "selectors": {
                # Keep the ID returned by the exact endpoint.  Substituting the
                # declared ID here would launder a contradictory response into
                # an apparently matching selector.
                "deployment_id": deployment.get("id"),
                "environment": deployment.get("environment"),
                "ref": deployment.get("ref"),
                "task": deployment.get("task"),
            },
            "observed_subject_sha": subject_main_sha,
            "source_sha": deployment.get("sha"),
            "matches_subject": deployment.get("sha") == subject_main_sha,
            "status": {
                "terminal_state": terminal.get("state") if terminal else None,
                "terminal_status_id": terminal.get("id") if terminal else None,
                "population_complete": statuses_result.get("population_complete") is True,
            },
            "artifact": artifact,
            "authoritative_source_id": source_id,
        }
    elif deployment_result.get("ok"):
        gaps.append(
            _gap(
                unit_id,
                "malformed_deployment_response",
                "github-deployment",
                "Deployment response is not an object",
                endpoint=deployment_endpoint,
            )
        )
    return {
        "unit_id": unit_id,
        "profile": unit["profile"],
        "api_population_complete": api_complete,
        "state": "observed" if api_complete and not gaps else "unknown",
        "delivery_items": [item] if item is not None else [],
        "remote_refs": [],
        "releases": [],
        "asset_contents": {},
        "attestation_assets": [],
        "attestation_population_complete": True,
        "requests": requests,
        "gaps": gaps,
    }


def _safe_bundle_url_presence(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)


def _attestation_metadata(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        record: dict[str, Any] = {
            "id": value.get("id") if isinstance(value.get("id"), (int, str)) else None,
            "repository_id": (
                value.get("repository_id")
                if _positive_int(value.get("repository_id"))
                else None
            ),
            "bundle_url_present": _safe_bundle_url_presence(value.get("bundle_url")),
        }
        result.append(record)
    return result


def _peel_tag(
    repository: str,
    tag: str,
    *,
    unit_id: str,
    client: GitHubRESTClient,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], bool]:
    ref_name = f"tags/{tag}"
    ref_endpoint = _endpoint(repository, f"/git/ref/{quote(ref_name, safe='/')}")
    result = client.get(ref_endpoint)
    requests = [_request_record(unit_id, "github-tag-ref", ref_endpoint, result)]
    gaps: list[dict[str, Any]] = []
    if not result.get("ok"):
        gaps.append(_response_gap(unit_id, "github-tag-ref", ref_endpoint, result))
        return {
            "ref": f"refs/tags/{tag}",
            "object": None,
            "peel_complete": False,
            "peeled_sha": None,
        }, requests, gaps, False
    ref = result.get("data")
    if not isinstance(ref, Mapping) or ref.get("ref") != f"refs/tags/{tag}":
        gaps.append(
            _gap(
                unit_id,
                "tag_ref_identity_mismatch",
                "github-tag-ref",
                "Git tag response does not identify the exact declared tag",
                endpoint=ref_endpoint,
            )
        )
        return {
            "ref": f"refs/tags/{tag}",
            "object": None,
            "peel_complete": False,
            "peeled_sha": None,
        }, requests, gaps, True
    current = ref.get("object")
    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    api_complete = True
    depth = 0
    while isinstance(current, Mapping) and current.get("type") == "tag" and depth < MAX_TAG_DEPTH:
        tag_sha = current.get("sha")
        if not _is_sha(tag_sha) or tag_sha in visited:
            gaps.append(
                _gap(
                    unit_id,
                    "annotated_tag_cycle_or_identity_gap",
                    "github-tag-object",
                    "Annotated tag chain has an invalid or repeated object SHA",
                )
            )
            break
        visited.add(tag_sha)
        endpoint = _endpoint(repository, f"/git/tags/{tag_sha}")
        tag_result = client.get(endpoint)
        requests.append(_request_record(unit_id, "github-tag-object", endpoint, tag_result))
        if not tag_result.get("ok"):
            gaps.append(_response_gap(unit_id, "github-tag-object", endpoint, tag_result))
            api_complete = False
            break
        tag_object = tag_result.get("data")
        if not isinstance(tag_object, Mapping) or tag_object.get("sha") != tag_sha:
            gaps.append(
                _gap(
                    unit_id,
                    "annotated_tag_identity_mismatch",
                    "github-tag-object",
                    "Annotated tag object does not match the requested SHA",
                    endpoint=endpoint,
                )
            )
            break
        chain.append({"sha": tag_sha, "object": tag_object.get("object")})
        current = tag_object.get("object")
        depth += 1
    if isinstance(current, Mapping) and current.get("type") == "tag":
        gaps.append(
            _gap(
                unit_id,
                "annotated_tag_depth_cap",
                "github-tag-object",
                f"Annotated tag chain exceeded {MAX_TAG_DEPTH} objects",
            )
        )
    peeled_sha = (
        current.get("sha")
        if isinstance(current, Mapping)
        and current.get("type") == "commit"
        and _is_sha(current.get("sha"))
        else None
    )
    if peeled_sha is None:
        gaps.append(
            _gap(
                unit_id,
                "tag_not_peeled_to_commit",
                "github-tag-ref",
                "Declared release tag did not peel to one exact commit",
            )
        )
    return {
        "ref": f"refs/tags/{tag}",
        "object": ref.get("object"),
        "annotation_chain": chain,
        "peel_complete": peeled_sha is not None,
        "peeled_sha": peeled_sha,
    }, requests, gaps, api_complete


def _collect_package(
    unit: Mapping[str, Any],
    *,
    repository: str,
    client: GitHubRESTClient,
    max_asset_bytes: int,
    binary_budget: dict[str, int],
) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    selector = unit["selector"]
    release_id = selector["release_id"]
    release_endpoint = _endpoint(repository, f"/releases/{release_id}")
    assets_endpoint = _endpoint(
        repository, f"/releases/{release_id}/assets?per_page=100"
    )
    release_result = client.get(release_endpoint)
    assets_result = client.paginate(assets_endpoint)
    requests = [
        _request_record(unit_id, "github-release", release_endpoint, release_result),
        _request_record(unit_id, "github-release-assets", assets_endpoint, assets_result),
    ]
    gaps: list[dict[str, Any]] = []
    api_complete = bool(release_result.get("ok")) and bool(
        assets_result.get("population_complete")
    )
    if not release_result.get("ok"):
        gaps.append(_response_gap(unit_id, "github-release", release_endpoint, release_result))
    if not assets_result.get("population_complete"):
        gaps.append(
            _response_gap(unit_id, "github-release-assets", assets_endpoint, assets_result)
        )
    tag_target, tag_requests, tag_gaps, tag_api_complete = _peel_tag(
        repository, selector["tag"], unit_id=unit_id, client=client
    )
    requests.extend(tag_requests)
    gaps.extend(tag_gaps)
    api_complete = api_complete and tag_api_complete

    raw_release = release_result.get("data")
    assets = assets_result.get("items")
    normalized_assets: list[dict[str, Any]] = []
    if isinstance(assets, list):
        for index, asset in enumerate(assets):
            if not isinstance(asset, Mapping):
                gaps.append(
                    _gap(
                        unit_id,
                        "malformed_release_asset",
                        "github-release-assets",
                        f"Release asset {index} is not an object",
                        endpoint=assets_endpoint,
                    )
                )
                continue
            normalized_assets.append(
                {
                    "asset_key": f"{release_id}:{asset.get('name')}",
                    "release_id": release_id,
                    "id": asset.get("id"),
                    "name": asset.get("name"),
                    "digest": asset.get("digest"),
                    "size": asset.get("size"),
                    "state": asset.get("state"),
                }
            )
    release: dict[str, Any] | None = None
    if isinstance(raw_release, Mapping):
        release = {
            "id": raw_release.get("id"),
            "unit_selector": unit_id,
            "tag_name": raw_release.get("tag_name"),
            "target_commitish": raw_release.get("target_commitish"),
            "draft": raw_release.get("draft"),
            "prerelease": raw_release.get("prerelease"),
            "immutable": raw_release.get("immutable"),
            "published_at": raw_release.get("published_at"),
            "tag_target": tag_target,
            "assets": normalized_assets,
            "authoritative_source_id": f"github-release:{release_id}",
        }
        if raw_release.get("id") != release_id or raw_release.get("tag_name") != selector["tag"]:
            gaps.append(
                _gap(
                    unit_id,
                    "release_identity_mismatch",
                    "github-release",
                    "Release ID or tag does not match the exact declaration",
                    endpoint=release_endpoint,
                )
            )
        if tag_target.get("peeled_sha") != unit["source_sha"]:
            gaps.append(
                _gap(
                    unit_id,
                    "release_source_mismatch",
                    "github-tag-ref",
                    "Release tag does not peel to the declared source SHA",
                )
            )
    elif release_result.get("ok"):
        gaps.append(
            _gap(
                unit_id,
                "malformed_release_response",
                "github-release",
                "Release response is not an object",
                endpoint=release_endpoint,
            )
        )

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in normalized_assets:
        if isinstance(asset.get("name"), str):
            by_name[asset["name"]].append(asset)
    asset_contents: dict[str, bytes] = {}
    attestation_assets: list[dict[str, Any]] = []
    for declared in selector["artifacts"]:
        name = declared["name"]
        candidates = by_name.get(name, [])
        if len(candidates) != 1:
            gaps.append(
                _gap(
                    unit_id,
                    "release_asset_ambiguous",
                    "github-release-assets",
                    f"Declared release asset {name!r} did not select exactly one asset",
                    endpoint=assets_endpoint,
                )
            )
            continue
        asset = candidates[0]
        digest = asset.get("digest")
        normalized_digest = (
            digest.removeprefix("sha256:").lower() if isinstance(digest, str) else None
        )
        asset_id = asset.get("id")
        size = asset.get("size")
        asset_valid = (
            _positive_int(asset_id)
            and isinstance(size, int)
            and not isinstance(size, bool)
            and size >= 0
            and asset.get("state") == "uploaded"
            and _is_sha256(normalized_digest)
            and normalized_digest == declared["sha256"]
        )
        if not asset_valid:
            gaps.append(
                _gap(
                    unit_id,
                    "release_asset_identity_mismatch",
                    "github-release-assets",
                    f"Release asset {name!r} lacks the exact ID, uploaded state, size, or digest",
                    endpoint=assets_endpoint,
                )
            )
            continue
        binary_endpoint = _endpoint(repository, f"/releases/assets/{asset_id}")
        remaining_bytes = binary_budget["remaining"]
        if remaining_bytes < 1 or size > remaining_bytes:
            gaps.append(
                _gap(
                    unit_id,
                    "binary_collection_budget_exhausted",
                    "github-release-asset-bytes",
                    "The bounded aggregate release-asset byte budget cannot cover this asset",
                    endpoint=binary_endpoint,
                )
            )
            api_complete = False
            continue
        binary = client.get_binary(
            binary_endpoint,
            declared_size=size,
            max_bytes=min(max_asset_bytes, remaining_bytes),
        )
        requests.append(
            _request_record(unit_id, "github-release-asset-bytes", binary_endpoint, binary)
        )
        if not binary.get("ok") or not isinstance(binary.get("data"), bytes):
            gaps.append(
                _response_gap(
                    unit_id, "github-release-asset-bytes", binary_endpoint, binary
                )
            )
            api_complete = False
            continue
        content = binary["data"]
        binary_budget["remaining"] -= len(content)
        if hashlib.sha256(content).hexdigest() != declared["sha256"]:
            gaps.append(
                _gap(
                    unit_id,
                    "release_asset_bytes_mismatch",
                    "github-release-asset-bytes",
                    f"Downloaded bytes for {name!r} do not match the declared SHA-256",
                    endpoint=binary_endpoint,
                )
            )
            continue
        asset_contents[name] = content

        attestation_endpoint = _endpoint(
            repository,
            f"/attestations/{quote('sha256:' + declared['sha256'], safe=':')}?per_page=100",
        )
        attestation = _paginate_cursor_collection(
            client, attestation_endpoint, "attestations"
        )
        requests.append(
            _request_record(
                unit_id, "github-attestations", attestation_endpoint, attestation
            )
        )
        attestation_complete = attestation.get("population_complete") is True
        if not attestation_complete:
            gaps.append(
                _response_gap(
                    unit_id, "github-attestations", attestation_endpoint, attestation
                )
            )
        attestation_assets.append(
            {
                "asset_key": f"{release_id}:{name}",
                "release_id": release_id,
                "asset_id": asset_id,
                "name": name,
                "digest": f"sha256:{declared['sha256']}",
                "attestations": _attestation_metadata(attestation.get("items")),
                "complete": attestation_complete,
                "unit_selector": unit_id,
                "source_binding": None,
            }
        )
    return {
        "unit_id": unit_id,
        "profile": unit["profile"],
        "api_population_complete": api_complete,
        "state": "observed" if api_complete and not gaps else "unknown",
        "delivery_items": [],
        "remote_refs": [
            {
                "ref": tag_target["ref"],
                "object": tag_target.get("object"),
                "source": "tag_ref",
                "unit_selector": unit_id,
            }
        ],
        "releases": [release] if release is not None else [],
        "asset_contents": asset_contents,
        "attestation_assets": attestation_assets,
        "attestation_population_complete": all(
            row.get("complete") is True for row in attestation_assets
        )
        and len(attestation_assets) == len(selector["artifacts"]),
        "requests": requests,
        "gaps": gaps,
    }


def _collect_gitops(
    unit: Mapping[str, Any],
    *,
    repository: str,
    client: GitHubRESTClient,
    adapter_records: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    selector = unit["selector"]
    relative_ref = selector["production_ref"].removeprefix("refs/")
    endpoint = _endpoint(repository, f"/git/ref/{quote(relative_ref, safe='/')}")
    result = client.get(endpoint)
    requests = [_request_record(unit_id, "github-production-ref", endpoint, result)]
    gaps: list[dict[str, Any]] = []
    api_complete = bool(result.get("ok"))
    if not result.get("ok"):
        gaps.append(_response_gap(unit_id, "github-production-ref", endpoint, result))
    ref = result.get("data")
    if not isinstance(ref, Mapping):
        ref = {
            "ref": selector["production_ref"],
            "object": None,
        }
        if result.get("ok"):
            gaps.append(
                _gap(
                    unit_id,
                    "malformed_production_ref",
                    "github-production-ref",
                    "Production ref response is not an object",
                    endpoint=endpoint,
                )
            )
    elif (
        ref.get("ref") != selector["production_ref"]
        or not isinstance(ref.get("object"), Mapping)
        or ref["object"].get("type") != "commit"
        or ref["object"].get("sha") != unit["source_sha"]
    ):
        gaps.append(
            _gap(
                unit_id,
                "production_ref_identity_mismatch",
                "github-production-ref",
                "Production ref does not identify the declared exact commit",
                endpoint=endpoint,
            )
        )
    adapter, adapter_gaps = _adapter_for_unit(
        adapter_records, unit=unit, adapter_id="gitops-reconciliation"
    )
    gaps.extend(adapter_gaps)
    content: dict[str, Any] | None = None
    reconciliation: dict[str, Any] | None = None
    expected_source_id = f"gitops-reconciliation:{unit_id}:{unit['source_sha']}"
    if adapter is not None:
        binding = adapter["binding"]
        binding_ok = (
            binding["production_ref"] == selector["production_ref"]
            and binding["path"] == selector["path"]
            and binding["content_sha256"] == selector["content_sha256"]
            and adapter["authoritative_source_id"] == expected_source_id
        )
        if binding_ok:
            content = {
                "path": binding["path"],
                "sha256": binding["content_sha256"],
            }
            reconciliation = {
                "state": "success",
                "population_complete": True,
                "authoritative_source_id": expected_source_id,
            }
        else:
            gaps.append(
                _gap(
                    unit_id,
                    "gitops_adapter_binding_mismatch",
                    "authenticated-adapter",
                    "Authenticated GitOps record does not match ref, path, digest, and source identity",
                )
            )
    row = {
        "ref": ref.get("ref"),
        "object": ref.get("object"),
        "source": "exact-github-ref",
        "unit_selector": unit_id,
        "content": content,
        "reconciliation": reconciliation,
    }
    return {
        "unit_id": unit_id,
        "profile": unit["profile"],
        "api_population_complete": api_complete,
        "state": "observed" if api_complete and not gaps else "unknown",
        "delivery_items": [],
        "remote_refs": [row],
        "releases": [],
        "asset_contents": {},
        "attestation_assets": [],
        "attestation_population_complete": True,
        "requests": requests,
        "gaps": gaps,
    }


def _collect_pages(
    unit: Mapping[str, Any],
    *,
    repository: str,
    subject_main_sha: str,
    client: GitHubRESTClient,
    adapter_records: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    selector = unit["selector"]
    deployment_id = selector["deployment_id"]
    adapter, adapter_gaps = _adapter_for_unit(
        adapter_records, unit=unit, adapter_id="pages-publication"
    )
    build_id = (
        adapter["binding"].get("build_id")
        if adapter is not None and isinstance(adapter.get("binding"), Mapping)
        else None
    )
    status_endpoint = _endpoint(
        repository,
        f"/pages/deployments/{quote(str(deployment_id), safe='')}",
    )
    site_endpoint = _endpoint(repository, "/pages")
    status_result = client.get(status_endpoint)
    site_result = client.get(site_endpoint)
    requests = [
        _request_record(unit_id, "github-pages-deployment", status_endpoint, status_result),
        _request_record(unit_id, "github-pages-site", site_endpoint, site_result),
    ]
    gaps = list(adapter_gaps)
    api_complete = bool(status_result.get("ok")) and bool(site_result.get("ok"))
    if not status_result.get("ok"):
        gaps.append(
            _response_gap(unit_id, "github-pages-deployment", status_endpoint, status_result)
        )
    if not site_result.get("ok"):
        gaps.append(_response_gap(unit_id, "github-pages-site", site_endpoint, site_result))

    build: Mapping[str, Any] | None = None
    if _positive_int(build_id):
        build_endpoint = _endpoint(repository, f"/pages/builds/{build_id}")
        build_result = client.get(build_endpoint)
        requests.append(
            _request_record(unit_id, "github-pages-build", build_endpoint, build_result)
        )
        api_complete = api_complete and bool(build_result.get("ok"))
        if not build_result.get("ok"):
            gaps.append(
                _response_gap(unit_id, "github-pages-build", build_endpoint, build_result)
            )
        elif isinstance(build_result.get("data"), Mapping):
            build = build_result["data"]
        else:
            gaps.append(
                _gap(
                    unit_id,
                    "malformed_pages_build",
                    "github-pages-build",
                    "Pages build response is not an object",
                    endpoint=build_endpoint,
                )
            )
    else:
        gaps.append(
            _gap(
                unit_id,
                "pages_build_binding_missing",
                "authenticated-adapter",
                "Authenticated Pages publication record does not identify an exact build ID",
            )
        )

    status = status_result.get("data")
    site = site_result.get("data")
    if not (
        isinstance(status, Mapping)
        and set(status) == {"status"}
        and status.get("status") == "succeed"
    ):
        gaps.append(
            _gap(
                unit_id,
                "pages_deployment_not_successful",
                "github-pages-deployment",
                "Pages deployment status is not the exact successful official response",
                endpoint=status_endpoint,
            )
        )
    if not isinstance(site, Mapping) or site.get("html_url") != selector["publication_url"]:
        gaps.append(
            _gap(
                unit_id,
                "pages_site_identity_mismatch",
                "github-pages-site",
                "Pages site URL does not match the declared publication URL",
                endpoint=site_endpoint,
            )
        )
    expected_build_url = (
        f"{client.api_url}{_endpoint(repository, f'/pages/builds/{build_id}')}"
        if _positive_int(build_id)
        else None
    )
    if build is not None and (
        build.get("url") != expected_build_url
        or build.get("status") != "built"
        or build.get("commit") != unit["source_sha"]
    ):
        gaps.append(
            _gap(
                unit_id,
                "pages_build_source_mismatch",
                "github-pages-build",
                "Pages build URL, status, or source SHA does not match the exact requested build",
            )
        )

    publication: dict[str, str] | None = None
    if adapter is not None:
        binding = adapter["binding"]
        expected_binding_source = f"pages-publication:{unit_id}:{unit['source_sha']}"
        binding_ok = (
            binding["deployment_id"] == deployment_id
            and _positive_int(binding["build_id"])
            and binding["publication_url"] == selector["publication_url"]
            and binding["content_sha256"] == selector["content_sha256"]
            and adapter["authoritative_source_id"] == expected_binding_source
        )
        if binding_ok:
            publication = {
                "url": binding["publication_url"],
                "content_sha256": binding["content_sha256"],
            }
        else:
            gaps.append(
                _gap(
                    unit_id,
                    "pages_publication_binding_mismatch",
                    "authenticated-adapter",
                    "Authenticated Pages record does not match deployment, build, URL, and digest",
                )
            )
    item = {
        "inventory_id": f"github-pages:{deployment_id}",
        "adapter_id": "github-pages",
        "delivery_kind": "pages",
        "repository": repository,
        "unit_selector": unit_id,
        "selectors": {
            "deployment_id": deployment_id,
            "environment": selector["environment"],
        },
        "observed_subject_sha": subject_main_sha,
        "source_sha": build.get("commit") if build is not None else None,
        "matches_subject": (
            build.get("commit") == subject_main_sha if build is not None else None
        ),
        "status": {"status": status.get("status") if isinstance(status, Mapping) else None},
        "publication": publication,
        "authoritative_source_id": f"github-pages-deployment:{deployment_id}",
        "publication_binding_source_id": (
            adapter["authoritative_source_id"] if adapter is not None else None
        ),
    }
    return {
        "unit_id": unit_id,
        "profile": unit["profile"],
        "api_population_complete": api_complete,
        "state": "observed" if api_complete and not gaps else "unknown",
        "delivery_items": [item],
        "remote_refs": [],
        "releases": [],
        "asset_contents": {},
        "attestation_assets": [],
        "attestation_population_complete": True,
        "requests": requests,
        "gaps": gaps,
    }


def _unsupported_unit(unit: Mapping[str, Any]) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    return {
        "unit_id": unit_id,
        "profile": unit.get("profile"),
        "api_population_complete": True,
        "state": "unknown",
        "delivery_items": [],
        "remote_refs": [],
        "releases": [],
        "asset_contents": {},
        "attestation_assets": [],
        "attestation_population_complete": True,
        "requests": [],
        "gaps": [
            _gap(
                unit_id,
                "governance_adapter_required",
                "delivery-collector",
                "Inactive production dispositions require a separate governance adapter",
            )
        ],
    }


def _observation(
    *,
    evidence_id: str,
    source: str,
    data: Mapping[str, Any],
    population_complete: bool,
    gaps: Sequence[Mapping[str, Any]],
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "observed_at": utc_now(),
        "source": source,
        "state": (
            "observed" if population_complete and not gaps else "unknown"
        ),
        "population_complete": population_complete,
        "data": dict(data),
        "gaps": [dict(gap) for gap in gaps],
        "requests": [dict(request) for request in requests],
    }


def collect_delivery_observations(
    production_identity: Mapping[str, Any],
    *,
    repository: str,
    subject_main_sha: str,
    client: GitHubRESTClient,
    authenticated_adapter_records: Sequence[Mapping[str, Any]] = (),
    adapter_batch_verification: Mapping[str, Any] | None = None,
    max_asset_bytes: int = DEFAULT_MAX_BINARY_BYTES,
    max_total_asset_bytes: int = DEFAULT_MAX_TOTAL_ASSET_BYTES,
) -> dict[str, Any]:
    """Collect exact selector-bound raw observations for every v2 unit.

    The returned ``delivery_observation``, ``refs_releases_observation``, and
    ``attestation_observation`` use the shapes consumed by
    :func:`delivery_resolution.resolve_delivery`.  Unit results retain their
    own requests and gaps so aggregate uncertainty cannot hide its source.
    Adapter records are accepted only with a separate exact batch-verification
    result; the named verifier is the caller's explicit trusted-channel
    boundary, and this collector never treats fields inside a record as proof
    that the record itself was authenticated.
    """

    if not isinstance(client, GitHubRESTClient):
        raise DeliveryCollectorError("client must be a GitHubRESTClient")
    if (
        not isinstance(max_asset_bytes, int)
        or isinstance(max_asset_bytes, bool)
        or max_asset_bytes < 1
        or max_asset_bytes > HARD_MAX_ASSET_BYTES
    ):
        raise DeliveryCollectorError(
            f"max_asset_bytes must be between 1 and {HARD_MAX_ASSET_BYTES}"
        )
    if (
        not isinstance(max_total_asset_bytes, int)
        or isinstance(max_total_asset_bytes, bool)
        or max_total_asset_bytes < 1
        or max_total_asset_bytes > HARD_MAX_TOTAL_ASSET_BYTES
    ):
        raise DeliveryCollectorError(
            "max_total_asset_bytes must be between 1 and "
            f"{HARD_MAX_TOTAL_ASSET_BYTES}"
        )
    units = _validate_identity(
        production_identity,
        repository=repository,
        subject_main_sha=subject_main_sha,
    )
    if (
        isinstance(authenticated_adapter_records, (str, bytes))
        or not isinstance(authenticated_adapter_records, Sequence)
        or len(authenticated_adapter_records) > MAX_ADAPTER_RECORDS
    ):
        raise DeliveryCollectorError(
            "authenticated_adapter_records must be a bounded sequence"
        )
    adapter_batch_verified, adapter_batch_digest, adapter_batch_gaps = (
        _verify_adapter_batch(
            authenticated_adapter_records,
            adapter_batch_verification,
        )
    )
    if adapter_batch_verified:
        adapter_records, adapter_input_gaps = _normalize_adapter_records(
            authenticated_adapter_records,
            repository=repository,
            declared_units={
                str(unit["unit_id"]): str(unit.get("profile")) for unit in units
            },
        )
    else:
        adapter_records = {}
        adapter_input_gaps = adapter_batch_gaps
    selector_counts = Counter(
        key for unit in units if (key := _selector_key(unit)) is not None
    )
    binary_budget = {
        "limit": max_total_asset_bytes,
        "remaining": max_total_asset_bytes,
    }
    results: list[dict[str, Any]] = []
    for unit in units:
        unit_id = str(unit["unit_id"])
        profile = unit.get("profile")
        selector_key = _selector_key(unit)
        if selector_key is not None and selector_counts[selector_key] != 1:
            result = _unsupported_unit(unit)
            result["api_population_complete"] = True
            result["gaps"] = [
                _gap(
                    unit_id,
                    "declared_selector_ambiguous",
                    "production-identity",
                    "Multiple units declare the same exact system selector",
                )
            ]
        elif profile == "application-github-deployment":
            result = _collect_application(
                unit,
                repository=repository,
                subject_main_sha=subject_main_sha,
                client=client,
            )
        elif profile == "package-github-release":
            result = _collect_package(
                unit,
                repository=repository,
                client=client,
                max_asset_bytes=max_asset_bytes,
                binary_budget=binary_budget,
            )
        elif profile == "gitops-production-ref":
            result = _collect_gitops(
                unit,
                repository=repository,
                client=client,
                adapter_records=adapter_records,
            )
        elif (
            profile == "documentation-publication"
            and unit["selector"].get("system") == "github-pages"
        ):
            result = _collect_pages(
                unit,
                repository=repository,
                subject_main_sha=subject_main_sha,
                client=client,
                adapter_records=adapter_records,
            )
        elif profile == "documentation-publication":
            result = _unsupported_unit(unit)
            result["gaps"] = [
                _gap(
                    unit_id,
                    "documentation_delivery_system_unsupported",
                    "delivery-collector",
                    "This collector supports documentation publication only through an exact GitHub Pages selector",
                )
            ]
        else:
            result = _unsupported_unit(unit)
        result["gaps"] = [
            *[
                gap
                for gap in adapter_input_gaps
                if gap["unit_id"] in {None, unit_id}
            ],
            *result["gaps"],
        ]
        if result["gaps"]:
            result["state"] = "unknown"
        results.append(result)

    delivery_items = [item for result in results for item in result["delivery_items"]]
    app_results = [
        result
        for result in results
        if result["profile"] == "application-github-deployment"
    ]
    pages_results = [
        result for result in results if result["profile"] == "documentation-publication"
    ]
    pages_adapter_results = [
        result
        for result in pages_results
        if any(
            item.get("adapter_id") == "github-pages"
            for item in result["delivery_items"]
        )
    ]
    delivery_adapters: list[dict[str, Any]] = []
    for adapter_id, kind, selected in (
        ("github-deployments", "deployment", app_results),
        ("github-pages", "pages", pages_adapter_results),
    ):
        for result in selected:
            unit_id = result["unit_id"]
            complete = result["api_population_complete"] is True
            item_count = sum(
                1
                for item in delivery_items
                if item.get("adapter_id") == adapter_id
                and item.get("unit_selector") == unit_id
            )
            delivery_adapters.append(
                {
                    "adapter_id": adapter_id,
                    "unit_selector": unit_id,
                    "delivery_kind": kind,
                    "state": "observed" if complete else "unknown",
                    "population_complete": complete,
                    "repository_scope": "exact",
                    "selector_fields": ["deployment_id", "environment"],
                    "item_count": item_count,
                }
            )
    delivery_relevant = [*app_results, *pages_results]
    delivery_complete = all(
        result["api_population_complete"] for result in delivery_relevant
    )
    delivery_gaps = [
        gap for result in delivery_relevant for gap in result["gaps"]
    ]
    delivery_requests = [
        request for result in delivery_relevant for request in result["requests"]
    ]
    delivery_observation = _observation(
        evidence_id="E-GH-DELIVERY-SELECTORS",
        source="github-rest:selector-bound-delivery",
        data={
            "inventory": {
                "schema_version": DELIVERY_INVENTORY_SCHEMA,
                "repository": repository,
                "observed_subject_sha": subject_main_sha,
                "population_scope": "per-unit",
                "adapters": delivery_adapters,
                "items": delivery_items,
            }
        },
        population_complete=delivery_complete,
        gaps=delivery_gaps,
        requests=delivery_requests,
    )

    refs_results = [
        result
        for result in results
        if result["profile"] in {"package-github-release", "gitops-production-ref"}
    ]
    refs_complete = all(
        result["api_population_complete"] for result in refs_results
    )
    remote_refs = [row for result in refs_results for row in result["remote_refs"]]
    releases = [row for result in refs_results for row in result["releases"]]
    refs_gaps = [gap for result in refs_results for gap in result["gaps"]]
    refs_requests = [request for result in refs_results for request in result["requests"]]
    refs_observation = _observation(
        evidence_id="E-GH-REFS-RELEASES-SELECTORS",
        source="github-rest:selector-bound-refs-releases",
        data={
            "remote_refs": remote_refs,
            "releases": releases,
            # Flat filename keys are intentionally never populated: filenames
            # are not unique across releases.  Consumers must use the exact
            # release ID + filename + declared digest key below.
            "asset_contents": {},
            "asset_contents_by_release": {
                (
                    f"{result['releases'][0]['id']}:{name}:"
                    f"{hashlib.sha256(content).hexdigest()}"
                ): content
                for result in refs_results
                for name, content in result["asset_contents"].items()
                if result["releases"]
            },
            "unit_populations": [
                {
                    "unit_id": result["unit_id"],
                    "state": (
                        "observed"
                        if result["api_population_complete"]
                        else "unknown"
                    ),
                    "population_complete": result["api_population_complete"] is True,
                }
                for result in refs_results
            ],
        },
        population_complete=refs_complete,
        gaps=refs_gaps,
        requests=refs_requests,
    )

    package_results = [
        result for result in results if result["profile"] == "package-github-release"
    ]
    attestation_assets = [
        row for result in package_results for row in result["attestation_assets"]
    ]
    attestation_complete = all(
        result["attestation_population_complete"] for result in package_results
    )
    attestation_gaps = [
        gap
        for result in package_results
        for gap in result["gaps"]
        if gap["source"] == "github-attestations"
    ]
    attestation_observation = _observation(
        evidence_id="E-GH-ATTESTATIONS-SELECTORS",
        source="github-rest:selector-bound-attestations",
        data={
            "assets": attestation_assets,
            "unit_populations": [
                {
                    "unit_id": result["unit_id"],
                    "state": (
                        "observed"
                        if result["attestation_population_complete"]
                        else "unknown"
                    ),
                    "population_complete": (
                        result["attestation_population_complete"] is True
                    ),
                }
                for result in package_results
            ],
        },
        population_complete=attestation_complete,
        gaps=attestation_gaps,
        requests=[
            request
            for result in package_results
            for request in result["requests"]
            if request["source"] == "github-attestations"
        ],
    )

    aggregate_gaps: list[dict[str, Any]] = []
    all_gaps = [
        *[gap for result in results for gap in result["gaps"]],
        *aggregate_gaps,
    ]
    return {
        "schema_version": COLLECTOR_SCHEMA,
        "repository": repository,
        "subject_main_sha": subject_main_sha,
        "state": (
            "observed"
            if results
            and not aggregate_gaps
            and all(result["state"] == "observed" for result in results)
            else "unknown"
        ),
        "population_complete": bool(results)
        and all(result["api_population_complete"] for result in results)
        and all(result["attestation_population_complete"] for result in results)
        and delivery_complete
        and refs_complete
        and attestation_complete,
        "binary_collection": {
            "per_asset_limit": max_asset_bytes,
            "total_limit": binary_budget["limit"],
            "bytes_collected": binary_budget["limit"] - binary_budget["remaining"],
        },
        "adapter_trust": {
            "state": (
                "not_applicable"
                if not authenticated_adapter_records
                else ("verified" if adapter_batch_verified else "unknown")
            ),
            "records_sha256": adapter_batch_digest,
            "record_count": len(authenticated_adapter_records),
        },
        "units": results,
        "delivery_observation": delivery_observation,
        "refs_releases_observation": refs_observation,
        "attestation_observation": attestation_observation,
        "gaps": all_gaps,
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }


__all__ = [
    "ADAPTER_BATCH_VERIFICATION_SCHEMA",
    "AUTHENTICATED_ADAPTER_SCHEMA",
    "COLLECTOR_SCHEMA",
    "DEFAULT_MAX_TOTAL_ASSET_BYTES",
    "DEPLOYMENT_PAYLOAD_SCHEMA",
    "DeliveryCollectorError",
    "HARD_MAX_ASSET_BYTES",
    "HARD_MAX_TOTAL_ASSET_BYTES",
    "collect_delivery_observations",
]

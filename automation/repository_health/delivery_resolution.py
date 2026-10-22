"""Fail-closed resolution of declared production units to live delivery evidence.

This module is deliberately pure: it performs no network, filesystem, Git, or
workflow execution.  A declaration is not proof.  A producer statement is not
proof either.  Resolution requires an exact live system record and an explicit
collector verification which binds that record to the statement, unit, source
revision, category policy, and immutable artifact/content identity.

The resolver consumes the generic ``RH-PRODUCTION-IDENTITY-2.0`` contract only.
Legacy production identities continue to use their existing resolver.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import re
from types import MappingProxyType
from typing import Any

from .evidence_producer import EvidenceStatementError, validate_evidence_statement
from .production_identity import (
    ACTIVE_PROFILES,
    GENERIC_PRODUCTION_SCHEMA,
    INACTIVE_PROFILES,
)


RESOLUTION_SCHEMA = "RH-DELIVERY-RESOLUTION-1.0"
POLICY_VERSION = "RH-DELIVERY-RESOLUTION-POLICY-1.0"
DELIVERY_INVENTORY_SCHEMA = "RH-GITHUB-DELIVERY-INVENTORY-1.0"
STATEMENT_VERIFICATION_SCHEMA = "RH-EVIDENCE-STATEMENT-VERIFICATION-1.0"
ANCESTRY_FACT_SCHEMA = "RH-MAIN-ANCESTRY-FACT-1.0"
INTERVENING_CHECK_FACT_SCHEMA = "RH-INTERVENING-CHECK-FACT-1.0"
ATTESTATION_BINDING_SCHEMA = "RH-ATTESTATION-SOURCE-BINDING-1.0"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATEMENT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,255}$")


def _profile_policy(**values: Any) -> Mapping[str, Any]:
    return MappingProxyType(values)


# This is a controlled policy, rather than a heuristic mapping.  A profile may
# only consume the declared statement kind/category and named system adapter.
PROFILE_POLICY: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "application-github-deployment": _profile_policy(
            active=True,
            system="github-deployments",
            statement_kind="deployment",
            statement_category="repository-health.application-production",
            artifact_name="application-artifact",
        ),
        "package-github-release": _profile_policy(
            active=True,
            system="github-releases",
            statement_kind="release",
            statement_category="repository-health.package-release",
            artifact_name=None,
        ),
        "gitops-production-ref": _profile_policy(
            active=True,
            system="git",
            statement_kind="deployment",
            statement_category="repository-health.gitops-reconciliation",
            artifact_name="production-content",
        ),
        "documentation-publication": _profile_policy(
            active=True,
            system="declared",
            statement_kind="deployment",
            statement_category="repository-health.documentation-publication",
            artifact_name="published-content",
        ),
        "approved-no-current-output": _profile_policy(
            active=False,
            system="governance-decision",
            statement_kind=None,
            statement_category=None,
            artifact_name=None,
        ),
        "archived-retired": _profile_policy(
            active=False,
            system="governance-decision",
            statement_kind=None,
            statement_category=None,
            artifact_name=None,
        ),
    }
)

_VERIFICATION_KEYS = frozenset(
    {
        "schema_version",
        "statement_id",
        "repository",
        "unit_id",
        "source_sha",
        "state",
        "population_complete",
        "matched_authoritative_source_ids",
        "source_binding_complete",
        "result_binding_complete",
        "artifact_binding_complete",
        "category_policy_verified",
    }
)
_ANCESTRY_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "unit_id",
        "source_sha",
        "main_sha",
        "state",
        "population_complete",
        "reachable_from_main",
    }
)
_INTERVENING_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "unit_id",
        "source_sha",
        "main_sha",
        "state",
        "population_complete",
        "revisions",
    }
)
_REVISION_KEYS = frozenset({"sha", "checks"})
_CHECK_KEYS = frozenset({"name", "conclusion"})
_ATTESTATION_BINDING_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "repository",
        "unit_id",
        "release_id",
        "asset_name",
        "artifact_sha256",
        "source_sha",
        "population_complete",
        "source_binding_complete",
        "artifact_binding_complete",
        "category_policy_verified",
        "matched_authoritative_source_ids",
    }
)
_UNIT_POPULATION_KEYS = frozenset(
    {"unit_id", "state", "population_complete"}
)


class DeliveryResolutionError(ValueError):
    """Raised when the caller violates the pure resolver input contract."""


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str]) -> bool:
    return all(isinstance(key, str) for key in value) and set(value) == expected


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _gap(unit_id: str | None, code: str, component: str, message: str) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "code": code,
        "component": component,
        "message": message,
    }


def _component_template() -> dict[str, str]:
    return {
        "authoritative_population": "unknown",
        "selector_unique": "unknown",
        "system_record_matches": "unknown",
        "source_sha_matches": "unknown",
        "terminal_status_success": "unknown",
        "artifact_identity_matches": "unknown",
        "statement_or_attestation_verified": "unknown",
        "main_reachable": "unknown",
        "intervening_checks_passed": "unknown",
    }


def _mark_fail(components: dict[str, str], component: str) -> None:
    """Record a known authoritative contradiction without masking it as Unknown."""

    components[component] = "fail"


def _unit_population(
    observation: Mapping[str, Any] | None,
    *,
    unit_id: str,
    component: str,
    legacy_message: str,
) -> tuple[bool, bool, list[dict[str, Any]]]:
    """Return (complete, per_unit_mode, gaps) for one scoped population.

    Older hand-built observations use the top-level state.  Collector output
    carries exact unit populations so an incomplete sibling cannot poison this
    unit.  An unscoped malformed row can conceal any unit and therefore remains
    a fail-all Unknown gap.
    """

    if not isinstance(observation, Mapping):
        return False, False, [
            _gap(unit_id, f"{component}_observation_missing", component, legacy_message)
        ]
    data = observation.get("data")
    populations = data.get("unit_populations") if isinstance(data, Mapping) else None
    if populations is None:
        complete = (
            observation.get("state") == "observed"
            and observation.get("population_complete") is True
        )
        return complete, False, ([] if complete else [
            _gap(unit_id, f"{component}_population_incomplete", component, legacy_message)
        ])
    if not isinstance(populations, list):
        return False, True, [
            _gap(None, "unit_population_malformed", component, "Per-unit population metadata is malformed")
        ]
    matches: list[Mapping[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for row in populations:
        scoped_id = row.get("unit_id") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not isinstance(scoped_id, str) or not scoped_id:
            gaps.append(
                _gap(None, "unit_population_unscoped", component, "A per-unit population row is malformed or unscoped")
            )
            continue
        if not _exact_keys(row, _UNIT_POPULATION_KEYS):
            if scoped_id == unit_id:
                gaps.append(
                    _gap(scoped_id, "unit_population_malformed", component, "A per-unit population row does not use the controlled shape")
                )
            continue
        if scoped_id == unit_id:
            matches.append(row)
    if len(matches) != 1:
        gaps.append(
            _gap(unit_id, "unit_population_ambiguous", component, "The unit has no unique authoritative population record")
        )
        return False, True, gaps
    row = matches[0]
    complete = row.get("state") == "observed" and row.get("population_complete") is True
    if not complete:
        gaps.append(
            _gap(unit_id, f"{component}_population_incomplete", component, legacy_message)
        )
    return complete, True, gaps


def _unscoped_observation_gaps(
    observation: Mapping[str, Any] | None,
    *,
    component: str,
) -> list[dict[str, Any]]:
    """Preserve fail-all semantics for collector-declared unscoped gaps."""

    if not isinstance(observation, Mapping) or "gaps" not in observation:
        return []
    raw_gaps = observation.get("gaps")
    if not isinstance(raw_gaps, list):
        return [
            _gap(None, "observation_gaps_malformed", component, "Observation gaps are malformed")
        ]
    result: list[dict[str, Any]] = []
    for raw in raw_gaps:
        if not isinstance(raw, Mapping):
            result.append(
                _gap(None, "observation_gap_unscoped", component, "An observation gap is malformed and unscoped")
            )
        elif raw.get("unit_id") is None:
            result.append(
                _gap(
                    None,
                    "unscoped_authoritative_population_gap",
                    component,
                    str(raw.get("message") or "An unscoped authoritative population gap affects every unit"),
                )
            )
    return result


def _unscoped_population_integrity_gaps(
    *,
    delivery_observation: Mapping[str, Any] | None,
    refs_releases_observation: Mapping[str, Any] | None,
    attestation_observation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Find malformed rows that cannot be safely assigned to one unit."""

    gaps: list[dict[str, Any]] = []
    delivery_data = (
        delivery_observation.get("data")
        if isinstance(delivery_observation, Mapping)
        else None
    )
    inventory = (
        delivery_data.get("inventory") if isinstance(delivery_data, Mapping) else None
    )
    if isinstance(inventory, Mapping) and inventory.get("population_scope") == "per-unit":
        for collection_name in ("adapters", "items"):
            rows = inventory.get(collection_name)
            if not isinstance(rows, list):
                gaps.append(
                    _gap(None, "delivery_population_malformed", "delivery", f"Per-unit delivery {collection_name} are malformed")
                )
                continue
            if any(
                not isinstance(row, Mapping)
                or not isinstance(row.get("unit_selector"), str)
                or not row.get("unit_selector")
                for row in rows
            ):
                gaps.append(
                    _gap(None, "delivery_population_unscoped", "delivery", f"Per-unit delivery {collection_name} contain an unscoped row")
                )

    for observation, component, collections in (
        (refs_releases_observation, "delivery", ("remote_refs", "releases")),
        (attestation_observation, "evidence", ("assets",)),
    ):
        data = observation.get("data") if isinstance(observation, Mapping) else None
        populations = data.get("unit_populations") if isinstance(data, Mapping) else None
        if populations is None:
            continue
        if not isinstance(populations, list) or any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("unit_id"), str)
            or not row.get("unit_id")
            for row in populations
        ):
            gaps.append(
                _gap(None, "unit_population_unscoped", component, "Per-unit population metadata contains an unscoped row")
            )
        for collection_name in collections:
            rows = data.get(collection_name) if isinstance(data, Mapping) else None
            if not isinstance(rows, list):
                gaps.append(
                    _gap(None, "authoritative_population_malformed", component, f"Per-unit {collection_name} population is malformed")
                )
            elif any(
                not isinstance(row, Mapping)
                or not isinstance(row.get("unit_selector"), str)
                or not row.get("unit_selector")
                for row in rows
            ):
                gaps.append(
                    _gap(None, "authoritative_population_unscoped", component, f"Per-unit {collection_name} contains an unscoped row")
                )
    return gaps


def _validated_identity_contract(identity: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(identity, Mapping):
        raise DeliveryResolutionError("production_identity must be a validated mapping")
    if identity.get("schema_version") != GENERIC_PRODUCTION_SCHEMA:
        raise DeliveryResolutionError(
            f"production_identity must use {GENERIC_PRODUCTION_SCHEMA}"
        )
    repository = identity.get("repository")
    units = identity.get("units")
    if not isinstance(repository, str) or not repository or not isinstance(units, list) or not units:
        raise DeliveryResolutionError("production_identity lacks repository or units")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(units):
        if not isinstance(raw, Mapping):
            raise DeliveryResolutionError(f"production_identity.units[{index}] is not an object")
        unit = deepcopy(dict(raw))
        unit_id = unit.get("unit_id")
        profile = unit.get("profile")
        if not isinstance(unit_id, str) or not unit_id or unit_id in seen:
            raise DeliveryResolutionError("production_identity has a missing or duplicate unit_id")
        if profile not in PROFILE_POLICY:
            raise DeliveryResolutionError(f"production_identity unit {unit_id!r} has no policy")
        if profile in ACTIVE_PROFILES:
            if not _is_sha(unit.get("source_sha")) or not isinstance(unit.get("selector"), Mapping):
                raise DeliveryResolutionError(
                    f"production_identity active unit {unit_id!r} is not validated"
                )
            if unit.get("correspondence") not in {
                "Exact-Main",
                "Releasable-Main",
                "Production-Ref",
            }:
                raise DeliveryResolutionError(
                    f"production_identity unit {unit_id!r} has invalid correspondence"
                )
        elif profile in INACTIVE_PROFILES:
            if unit.get("source_sha") is not None or unit.get("correspondence") != "N/A":
                raise DeliveryResolutionError(
                    f"production_identity inactive unit {unit_id!r} is not validated"
                )
        seen.add(unit_id)
        normalized.append(unit)
    return repository, normalized


def _normalize_statements(
    values: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise DeliveryResolutionError("evidence_statements must be a sequence")
    statements: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        try:
            observed_at = raw.get("observed_at") if isinstance(raw, Mapping) else None
            if not isinstance(observed_at, str):
                raise EvidenceStatementError("observed_at is unavailable")
            validation_now = datetime.fromisoformat(
                observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at
            )
            statement = validate_evidence_statement(raw, now=validation_now)
        except (EvidenceStatementError, TypeError, ValueError) as error:
            unit_id = raw.get("unit_id") if isinstance(raw, Mapping) else None
            gaps.append(
                _gap(
                    unit_id if isinstance(unit_id, str) else None,
                    "invalid_evidence_statement",
                    "evidence",
                    f"Evidence statement {index} is invalid: {error}",
                )
            )
            continue
        statements.append(statement)
    duplicates = {
        statement_id
        for statement_id, count in Counter(item["statement_id"] for item in statements).items()
        if count > 1
    }
    for statement_id in sorted(duplicates):
        for statement in statements:
            if statement["statement_id"] == statement_id:
                gaps.append(
                    _gap(
                        statement["unit_id"],
                        "duplicate_evidence_statement",
                        "evidence",
                        f"Statement {statement_id} occurs more than once",
                    )
                )
    return statements, gaps


def _normalize_verifications(
    values: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise DeliveryResolutionError("statement_verifications must be a sequence")
    verifications: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        unit_id = raw.get("unit_id") if isinstance(raw, Mapping) else None
        if not isinstance(raw, Mapping) or not _exact_keys(raw, _VERIFICATION_KEYS):
            gaps.append(
                _gap(
                    unit_id if isinstance(unit_id, str) else None,
                    "invalid_statement_verification",
                    "evidence",
                    f"Statement verification {index} does not use the exact controlled schema",
                )
            )
            continue
        value = dict(raw)
        source_ids = value["matched_authoritative_source_ids"]
        valid = (
            value["schema_version"] == STATEMENT_VERIFICATION_SCHEMA
            and isinstance(value["statement_id"], str)
            and _STATEMENT_ID.fullmatch(value["statement_id"]) is not None
            and isinstance(value["repository"], str)
            and bool(value["repository"])
            and isinstance(value["unit_id"], str)
            and bool(value["unit_id"])
            and _is_sha(value["source_sha"])
            and isinstance(value["state"], str)
            and value["state"] in {"verified", "unknown", "conflict"}
            and isinstance(value["population_complete"], bool)
            and isinstance(source_ids, list)
            and bool(source_ids)
            and all(
                isinstance(item, str) and _SOURCE_ID.fullmatch(item) is not None
                for item in source_ids
            )
            and source_ids == sorted(set(source_ids))
            and all(
                isinstance(value[key], bool)
                for key in (
                    "source_binding_complete",
                    "result_binding_complete",
                    "artifact_binding_complete",
                    "category_policy_verified",
                )
            )
        )
        if not valid:
            gaps.append(
                _gap(
                    value.get("unit_id") if isinstance(value.get("unit_id"), str) else None,
                    "invalid_statement_verification",
                    "evidence",
                    f"Statement verification {index} contains invalid controlled values",
                )
            )
            continue
        verifications.append(value)
    return verifications, gaps


def _unit_gaps(gaps: Sequence[dict[str, Any]], unit_id: str) -> list[dict[str, Any]]:
    # An unscoped malformed row can conceal a claim for any unit and therefore
    # fails all active units closed.  A well-scoped problem remains isolated.
    return [gap for gap in gaps if gap["unit_id"] in {None, unit_id}]


def _delivery_inventory(
    observation: Mapping[str, Any] | None,
    *,
    repository: str,
    adapter_id: str,
    unit_id: str,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    gaps: list[dict[str, Any]] = []
    data = observation.get("data") if isinstance(observation, Mapping) else None
    inventory = data.get("inventory") if isinstance(data, Mapping) else None
    if not isinstance(inventory, Mapping):
        return [], [
            _gap(unit_id, "delivery_inventory_missing", "delivery", "Delivery inventory is unavailable")
        ]
    if (
        inventory.get("schema_version") != DELIVERY_INVENTORY_SCHEMA
        or inventory.get("repository") != repository
    ):
        return [], [
            _gap(
                unit_id,
                "delivery_inventory_identity_mismatch",
                "delivery",
                "Delivery inventory schema or repository does not match",
            )
        ]
    adapters = inventory.get("adapters")
    items = inventory.get("items")
    if not isinstance(adapters, list) or not isinstance(items, list):
        return [], [
            _gap(unit_id, "delivery_inventory_malformed", "delivery", "Delivery inventory populations are malformed")
        ]
    population_scope = inventory.get("population_scope")
    per_unit = population_scope == "per-unit"
    if population_scope not in {None, "per-unit"}:
        gaps.append(
            _gap(
                None,
                "delivery_population_scope_invalid",
                "delivery",
                "Delivery population scope is neither legacy nor per-unit",
            )
        )
    if per_unit:
        for adapter in adapters:
            if (
                not isinstance(adapter, Mapping)
                or not isinstance(adapter.get("unit_selector"), str)
                or not adapter.get("unit_selector")
            ):
                gaps.append(
                    _gap(
                        None,
                        "delivery_adapter_unscoped",
                        "delivery",
                        "A per-unit delivery adapter row is malformed or unscoped",
                    )
                )
        for item in items:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("unit_selector"), str)
                or not item.get("unit_selector")
            ):
                gaps.append(
                    _gap(
                        None,
                        "delivery_item_unscoped",
                        "delivery",
                        "A per-unit delivery item is malformed or unscoped",
                    )
                )
        matching_adapters = [
            adapter
            for adapter in adapters
            if isinstance(adapter, Mapping)
            and adapter.get("adapter_id") == adapter_id
            and adapter.get("unit_selector") == unit_id
        ]
    else:
        matching_adapters = [
            adapter
            for adapter in adapters
            if isinstance(adapter, Mapping) and adapter.get("adapter_id") == adapter_id
        ]
    if len(matching_adapters) != 1:
        return [], [
            _gap(
                unit_id,
                "delivery_adapter_ambiguous",
                "delivery",
                f"Expected exactly one {adapter_id!r} adapter population",
            )
        ]
    adapter = matching_adapters[0]
    if (
        adapter.get("state") != "observed"
        or adapter.get("population_complete") is not True
        or adapter.get("repository_scope") != "exact"
    ):
        gaps.append(
            _gap(
                unit_id,
                "delivery_adapter_incomplete",
                "delivery",
                f"The {adapter_id!r} adapter population is incomplete or unscoped",
            )
        )
    adapter_items = [
        item
        for item in items
        if isinstance(item, Mapping)
        and item.get("adapter_id") == adapter_id
        and (not per_unit or item.get("unit_selector") == unit_id)
    ]
    if adapter.get("item_count") != len(adapter_items):
        gaps.append(
            _gap(
                unit_id,
                "delivery_adapter_count_mismatch",
                "delivery",
                "Adapter item_count does not equal its enumerated population",
            )
        )
    return adapter_items, gaps


def _exact_deployment_record(
    unit: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    *,
    repository: str,
    documentation: bool,
    declaration_unique: bool,
) -> tuple[str | None, dict[str, str], list[dict[str, Any]], dict[str, str]]:
    unit_id = unit["unit_id"]
    selector = unit["selector"]
    adapter_id = selector["system"]
    items, gaps = _delivery_inventory(
        observation, repository=repository, adapter_id=adapter_id, unit_id=unit_id
    )
    components: dict[str, str] = {}
    if not gaps:
        components["authoritative_population"] = "pass"
    deployment_id = selector["deployment_id"]
    selector_matches = [
        item
        for item in items
        if isinstance(item.get("selectors"), Mapping)
        and item["selectors"].get("deployment_id") == deployment_id
    ]
    if len(selector_matches) != 1:
        gaps.append(
            _gap(
                unit_id,
                "deployment_selector_ambiguous",
                "delivery",
                "The exact deployment ID did not select exactly one live record",
            )
        )
        return None, {}, gaps, components
    item = selector_matches[0]
    authoritative_complete = (
        components.get("authoritative_population") == "pass"
        and declaration_unique
    )
    explicit_unit = item.get("unit_selector")
    if not declaration_unique:
        gaps.append(
            _gap(
                unit_id,
                "declared_selector_ambiguous",
                "delivery",
                "Multiple declared units claim this exact delivery selector",
            )
        )
    if explicit_unit is not None and explicit_unit != unit_id:
        gaps.append(
            _gap(
                unit_id,
                "deployment_unit_conflict",
                "delivery",
                "The selected delivery row is explicitly bound to another unit",
            )
        )
        if authoritative_complete and isinstance(explicit_unit, str):
            _mark_fail(components, "system_record_matches")
    elif item.get("repository") != repository:
        gaps.append(
            _gap(unit_id, "deployment_repository_mismatch", "delivery", "The delivery row belongs to another repository")
        )
        if authoritative_complete and isinstance(item.get("repository"), str):
            _mark_fail(components, "system_record_matches")
    elif declaration_unique:
        components["selector_unique"] = "pass"
    if item.get("source_sha") != unit["source_sha"]:
        gaps.append(
            _gap(unit_id, "deployment_source_mismatch", "delivery", "Deployment source does not equal the declared immutable source SHA")
        )
        if authoritative_complete and _is_sha(item.get("source_sha")):
            _mark_fail(components, "source_sha_matches")
    else:
        components["source_sha_matches"] = "pass"
    selectors = item.get("selectors")
    if not isinstance(selectors, Mapping) or selectors.get("environment") != selector["environment"]:
        gaps.append(
            _gap(unit_id, "deployment_environment_mismatch", "delivery", "Deployment environment does not match the declaration")
        )
        if (
            authoritative_complete
            and isinstance(selectors, Mapping)
            and isinstance(selectors.get("environment"), str)
        ):
            _mark_fail(components, "system_record_matches")
    status = item.get("status")
    status_id = status.get("terminal_status_id") if isinstance(status, Mapping) else None
    if adapter_id == "github-pages":
        # The official Pages deployment endpoint returns only a controlled
        # status value; unlike deployment statuses, it has no status-record ID.
        status_ok = isinstance(status, Mapping) and (
            status.get("status") == "succeed"
            or status.get("terminal_state") == selector["required_status"]
        )
    else:
        status_ok = (
            isinstance(status, Mapping)
            and status.get("terminal_state") == selector["required_status"]
            and status.get("population_complete") is True
            and _is_positive_int(status_id)
        )
    if not status_ok:
        status_requirement = (
            "Exact successful Pages deployment status is unavailable"
            if adapter_id == "github-pages"
            else "Exact terminal deployment status and status ID are unavailable"
        )
        gaps.append(
            _gap(
                unit_id,
                "deployment_terminal_status_unverified",
                "delivery",
                status_requirement,
            )
        )
        if adapter_id == "github-pages":
            status_contradiction = (
                authoritative_complete
                and isinstance(status, Mapping)
                and isinstance(status.get("status"), str)
            )
        else:
            status_contradiction = (
                authoritative_complete
                and isinstance(status, Mapping)
                and isinstance(status.get("terminal_state"), str)
                and status.get("population_complete") is True
                and _is_positive_int(status_id)
            )
        if status_contradiction:
            _mark_fail(components, "terminal_status_success")
        source_id = (
            f"github-deployment-status:{deployment_id}:{status_id}"
            if adapter_id == "github-deployments" and _is_positive_int(status_id)
            else (
                f"github-pages-deployment:{deployment_id}"
                if adapter_id == "github-pages" and isinstance(status, Mapping)
                else None
            )
        )
    elif adapter_id == "github-deployments":
        source_id = f"github-deployment-status:{deployment_id}:{status_id}"
        components["terminal_status_success"] = "pass"
    else:
        source_id = f"github-pages-deployment:{deployment_id}"
        components["terminal_status_success"] = "pass"
    if item.get("authoritative_source_id") != source_id:
        gaps.append(
            _gap(unit_id, "deployment_source_id_unverified", "delivery", "Delivery row lacks the exact authoritative status source ID")
        )

    expected_digests: dict[str, str]
    if documentation:
        publication = item.get("publication")
        expected_digests = {"published-content": selector["content_sha256"]}
        publication_ok = (
            isinstance(publication, Mapping)
            and publication.get("url") == selector["publication_url"]
            and publication.get("content_sha256") == selector["content_sha256"]
        )
        if not publication_ok:
            gaps.append(
                _gap(unit_id, "publication_identity_mismatch", "artifact", "Publication URL or immutable content digest does not match")
            )
            if (
                authoritative_complete
                and isinstance(publication, Mapping)
                and isinstance(publication.get("url"), str)
                and _is_sha256(publication.get("content_sha256"))
            ):
                _mark_fail(components, "artifact_identity_matches")
    else:
        artifact = item.get("artifact")
        declared = selector["artifact"]
        expected_digests = {"application-artifact": declared["sha256"]}
        artifact_ok = (
            isinstance(artifact, Mapping)
            and artifact.get("reference") == declared["reference"]
            and artifact.get("sha256") == declared["sha256"]
        )
        if not artifact_ok:
            gaps.append(
                _gap(unit_id, "deployment_artifact_mismatch", "artifact", "Deployment artifact reference or immutable digest does not match")
            )
            if (
                authoritative_complete
                and isinstance(artifact, Mapping)
                and isinstance(artifact.get("reference"), str)
                and _is_sha256(artifact.get("sha256"))
            ):
                _mark_fail(components, "artifact_identity_matches")
    if not any(gap["component"] == "artifact" for gap in gaps):
        components["artifact_identity_matches"] = "pass"
    if not any(gap["component"] == "delivery" for gap in gaps):
        components["system_record_matches"] = "pass"
    return source_id, expected_digests, gaps, components


def _exact_gitops_record(
    unit: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    *,
    repository: str,
    declaration_unique: bool,
) -> tuple[str | None, dict[str, str], list[dict[str, Any]], dict[str, str]]:
    unit_id = unit["unit_id"]
    selector = unit["selector"]
    gaps: list[dict[str, Any]] = []
    components: dict[str, str] = {}
    population_complete, per_unit, population_gaps = _unit_population(
        observation,
        unit_id=unit_id,
        component="delivery",
        legacy_message="The authoritative Git ref population is incomplete",
    )
    gaps.extend(population_gaps)
    if not isinstance(observation, Mapping):
        return None, {}, gaps, components
    data = observation.get("data")
    rows = data.get("remote_refs") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        gaps.append(
            _gap(
                None if per_unit else unit_id,
                "refs_population_malformed",
                "delivery",
                "The authoritative Git ref population is malformed",
            )
        )
        rows = []
    if per_unit:
        if any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("unit_selector"), str)
            or not row.get("unit_selector")
            for row in rows
        ):
            gaps.append(
                _gap(
                    None,
                    "production_ref_population_unscoped",
                    "delivery",
                    "A per-unit production-ref row is malformed or unscoped",
                )
            )
        rows = [
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("unit_selector") == unit_id
        ]
    if population_complete and not gaps:
        components["authoritative_population"] = "pass"
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("ref") == selector["production_ref"]
        and isinstance(row.get("content"), Mapping)
        and row["content"].get("path") == selector["path"]
    ]
    if len(matches) != 1:
        gaps.append(
            _gap(unit_id, "production_ref_ambiguous", "delivery", "The exact production ref did not select exactly one record")
        )
        return None, {"production-content": selector["content_sha256"]}, gaps, components
    row = matches[0]
    authoritative_complete = (
        components.get("authoritative_population") == "pass"
        and declaration_unique
    )
    explicit_unit = row.get("unit_selector")
    if not declaration_unique:
        gaps.append(
            _gap(unit_id, "declared_selector_ambiguous", "delivery", "Multiple declared units claim this exact production ref and path")
        )
    if explicit_unit is not None and explicit_unit != unit_id:
        gaps.append(
            _gap(unit_id, "production_ref_unit_conflict", "delivery", "The production ref row is explicitly bound to another unit")
        )
        if authoritative_complete and isinstance(explicit_unit, str):
            _mark_fail(components, "system_record_matches")
    elif declaration_unique:
        components["selector_unique"] = "pass"
    object_record = row.get("object")
    source_ok = (
        isinstance(object_record, Mapping)
        and object_record.get("type") == "commit"
        and object_record.get("sha") == unit["source_sha"]
        and selector["ref_commit_sha"] == unit["source_sha"]
    )
    if not source_ok:
        gaps.append(
            _gap(unit_id, "production_ref_source_mismatch", "delivery", "Production ref does not point at the declared exact commit")
        )
        if (
            authoritative_complete
            and isinstance(object_record, Mapping)
            and object_record.get("type") == "commit"
            and _is_sha(object_record.get("sha"))
        ):
            _mark_fail(components, "source_sha_matches")
    else:
        components["source_sha_matches"] = "pass"
    content = row.get("content")
    if not (
        isinstance(content, Mapping)
        and content.get("path") == selector["path"]
        and content.get("sha256") == selector["content_sha256"]
    ):
        gaps.append(
            _gap(unit_id, "production_ref_content_mismatch", "artifact", "Production path or immutable content digest does not match")
        )
        if (
            authoritative_complete
            and isinstance(content, Mapping)
            and isinstance(content.get("path"), str)
            and _is_sha256(content.get("sha256"))
        ):
            _mark_fail(components, "artifact_identity_matches")
    else:
        components["artifact_identity_matches"] = "pass"
    reconciliation = row.get("reconciliation")
    source_id = f"gitops-reconciliation:{unit_id}:{unit['source_sha']}"
    if not (
        isinstance(reconciliation, Mapping)
        and reconciliation.get("state") == "success"
        and reconciliation.get("population_complete") is True
        and reconciliation.get("authoritative_source_id") == source_id
    ):
        gaps.append(
            _gap(unit_id, "reconciliation_unverified", "delivery", "Exact successful reconciliation proof is unavailable")
        )
        if (
            authoritative_complete
            and isinstance(reconciliation, Mapping)
            and isinstance(reconciliation.get("state"), str)
            and reconciliation.get("population_complete") is True
        ):
            _mark_fail(components, "terminal_status_success")
    else:
        components["terminal_status_success"] = "pass"
    if not any(gap["component"] == "delivery" for gap in gaps):
        components["system_record_matches"] = "pass"
    return source_id, {"production-content": selector["content_sha256"]}, gaps, components


def _asset_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.removeprefix("sha256:").lower()
    return normalized if _is_sha256(normalized) else None


def _exact_release_record(
    unit: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    *,
    declaration_unique: bool,
) -> tuple[str | None, dict[str, str], list[dict[str, Any]], dict[str, str]]:
    unit_id = unit["unit_id"]
    selector = unit["selector"]
    expected = {item["name"]: item["sha256"] for item in selector["artifacts"]}
    gaps: list[dict[str, Any]] = []
    components: dict[str, str] = {}
    population_complete, per_unit, population_gaps = _unit_population(
        observation,
        unit_id=unit_id,
        component="delivery",
        legacy_message="Release, tag, or asset-content population is incomplete",
    )
    gaps.extend(population_gaps)
    data = observation.get("data") if isinstance(observation, Mapping) else None
    releases = data.get("releases") if isinstance(data, Mapping) else None
    if not isinstance(releases, list):
        gaps.append(
            _gap(
                None if per_unit else unit_id,
                "release_population_malformed",
                "delivery",
                "The release population is malformed",
            )
        )
        releases = []
    if per_unit:
        if any(
            not isinstance(release, Mapping)
            or not isinstance(release.get("unit_selector"), str)
            or not release.get("unit_selector")
            for release in releases
        ):
            gaps.append(
                _gap(
                    None,
                    "release_population_unscoped",
                    "delivery",
                    "A per-unit release row is malformed or unscoped",
                )
            )
        releases = [
            release
            for release in releases
            if isinstance(release, Mapping) and release.get("unit_selector") == unit_id
        ]
        contents = data.get("asset_contents_by_release") if isinstance(data, Mapping) else None
        if not isinstance(contents, Mapping) or any(
            not isinstance(key, str) or not isinstance(content, bytes)
            for key, content in contents.items()
        ):
            gaps.append(
                _gap(
                    None,
                    "release_asset_content_population_unscoped",
                    "artifact",
                    "Release asset bytes are malformed or lack exact release-scoped keys",
                )
            )
            contents = {}
    else:
        contents = data.get("asset_contents") if isinstance(data, Mapping) else None
        if not isinstance(contents, Mapping):
            gaps.append(
                _gap(
                    unit_id,
                    "release_asset_content_population_missing",
                    "artifact",
                    "Release asset bytes are unavailable",
                )
            )
            contents = {}
    if population_complete and not any(
        gap["unit_id"] in {None, unit_id} for gap in gaps
    ):
        components["authoritative_population"] = "pass"
    matches = [
        release
        for release in releases
        if isinstance(release, Mapping) and release.get("id") == selector["release_id"]
    ]
    if len(matches) != 1:
        gaps.append(
            _gap(unit_id, "release_selector_ambiguous", "delivery", "The exact release ID did not select exactly one live record")
        )
        return None, expected, gaps, components
    release = matches[0]
    authoritative_complete = (
        components.get("authoritative_population") == "pass"
        and declaration_unique
    )
    explicit_unit = release.get("unit_selector")
    if not declaration_unique:
        gaps.append(
            _gap(unit_id, "declared_selector_ambiguous", "delivery", "Multiple declared units claim this exact release ID and tag")
        )
    if explicit_unit is not None and explicit_unit != unit_id:
        gaps.append(
            _gap(unit_id, "release_unit_conflict", "delivery", "The release row is explicitly bound to another unit")
        )
        if authoritative_complete and isinstance(explicit_unit, str):
            _mark_fail(components, "system_record_matches")
    elif declaration_unique:
        components["selector_unique"] = "pass"
    tag_target = release.get("tag_target")
    source_ok = (
        release.get("tag_name") == selector["tag"]
        and isinstance(tag_target, Mapping)
        and tag_target.get("peel_complete") is True
        and tag_target.get("peeled_sha") == unit["source_sha"]
    )
    if not source_ok:
        gaps.append(
            _gap(unit_id, "release_source_mismatch", "delivery", "Release tag does not peel to the declared exact source SHA")
        )
        if (
            authoritative_complete
            and isinstance(tag_target, Mapping)
            and tag_target.get("peel_complete") is True
            and _is_sha(tag_target.get("peeled_sha"))
            and tag_target.get("peeled_sha") != unit["source_sha"]
        ):
            _mark_fail(components, "source_sha_matches")
        if (
            authoritative_complete
            and isinstance(release.get("tag_name"), str)
            and release.get("tag_name") != selector["tag"]
        ):
            _mark_fail(components, "system_record_matches")
    else:
        components["source_sha_matches"] = "pass"
    published = (
        release.get("draft") is False
        and isinstance(release.get("published_at"), str)
        and bool(release.get("published_at"))
        and (selector["allow_prerelease"] is True or release.get("prerelease") is False)
    )
    if not published:
        gaps.append(
            _gap(unit_id, "release_not_published", "delivery", "Release is draft, unpublished, or an unapproved prerelease")
        )
        publication_fields_complete = (
            authoritative_complete
            and all(
                key in release for key in ("draft", "prerelease", "published_at")
            )
            and isinstance(release.get("draft"), bool)
            and isinstance(release.get("prerelease"), bool)
            and isinstance(release.get("published_at"), (str, type(None)))
        )
        if publication_fields_complete:
            _mark_fail(components, "terminal_status_success")
    else:
        components["terminal_status_success"] = "pass"
    assets = release.get("assets")
    observed: dict[str, str] = {}
    duplicate_names: set[str] = set()
    invalid_digest_names: set[str] = set()
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, Mapping) or not isinstance(asset.get("name"), str):
                duplicate_names.add("<invalid>")
                continue
            name = asset["name"]
            if name in observed:
                duplicate_names.add(name)
            digest = _asset_digest(asset.get("digest"))
            if digest is None:
                invalid_digest_names.add(name)
            else:
                observed[name] = digest
    else:
        duplicate_names.add("<missing>")
    downloaded: dict[str, str] = {}
    missing_downloads: set[str] = set()
    for name, expected_digest in expected.items():
        content_key = (
            f"{selector['release_id']}:{name}:{expected_digest}"
            if per_unit
            else name
        )
        content = contents.get(content_key)
        if isinstance(content, bytes):
            downloaded[name] = hashlib.sha256(content).hexdigest()
        else:
            missing_downloads.add(name)
    asset_population_exact = (
        not duplicate_names
        and not invalid_digest_names
        and set(observed) == set(expected)
        and not missing_downloads
    )
    artifact_contradiction = (
        authoritative_complete
        and asset_population_exact
        and (observed != expected or downloaded != expected)
    )
    if (
        duplicate_names
        or invalid_digest_names
        or set(observed) != set(expected)
        or missing_downloads
        or observed != expected
        or downloaded != expected
    ):
        gaps.append(
            _gap(unit_id, "release_artifact_mismatch", "artifact", "Exact release assets, API digests, and downloaded-byte digests do not all match")
        )
        if artifact_contradiction:
            _mark_fail(components, "artifact_identity_matches")
    else:
        components["artifact_identity_matches"] = "pass"
    source_id = f"github-release:{selector['release_id']}"
    if release.get("authoritative_source_id") != source_id:
        gaps.append(
            _gap(unit_id, "release_source_id_unverified", "delivery", "Release row lacks its exact authoritative source ID")
        )
    if not any(gap["component"] == "delivery" for gap in gaps):
        components["system_record_matches"] = "pass"
    return source_id, expected, gaps, components


def _relevant_statements(
    statements: Sequence[Mapping[str, Any]], unit: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    expected_kind = policy["statement_kind"]
    expected_category = policy["statement_category"]
    return [
        statement
        for statement in statements
        if statement.get("unit_id") == unit["unit_id"]
        and (
            statement.get("kind") == expected_kind
            or expected_category in statement.get("categories", [])
        )
    ]


def _statement_proof(
    *,
    unit: Mapping[str, Any],
    repository: str,
    policy: Mapping[str, Any],
    expected_digests: Mapping[str, str],
    authoritative_source_id: str | None,
    statements: Sequence[Mapping[str, Any]],
    verifications: Sequence[Mapping[str, Any]],
    optional: bool = False,
) -> tuple[bool, bool, list[dict[str, Any]], list[str]]:
    """Return (passed, relevant_present, gaps, statement_ids)."""

    unit_id = unit["unit_id"]
    relevant = _relevant_statements(statements, unit, policy)
    if not relevant:
        if optional:
            return False, False, [], []
        return False, False, [
            _gap(unit_id, "production_statement_missing", "evidence", "No exact production evidence statement was supplied")
        ], []
    if len(relevant) != 1:
        return False, True, [
            _gap(unit_id, "production_statement_ambiguous", "evidence", "Production evidence contains duplicate or conflicting claims")
        ], [item["statement_id"] for item in relevant]
    statement = relevant[0]
    statement_id = statement["statement_id"]
    gaps: list[dict[str, Any]] = []
    expected_ref = None
    if unit["profile"] == "package-github-release":
        expected_ref = f"refs/tags/{unit['selector']['tag']}"
    elif unit["profile"] == "gitops-production-ref":
        expected_ref = unit["selector"]["production_ref"]
    artifact_digests = {
        item["name"]: item["value"] for item in statement["artifact_digests"]
    }
    if (
        statement["repository"] != repository
        or statement["unit_id"] != unit_id
        or statement["subject"]["sha"] != unit["source_sha"]
        or (expected_ref is not None and statement["subject"]["ref"] != expected_ref)
        or statement["kind"] != policy["statement_kind"]
        or statement["categories"] != [policy["statement_category"]]
        or statement["result"] != "success"
        or artifact_digests != dict(expected_digests)
        or authoritative_source_id is None
        or authoritative_source_id not in statement["source_evidence_ids"]
    ):
        gaps.append(
            _gap(unit_id, "production_statement_mismatch", "evidence", "Statement does not exactly match profile, unit, source, category, result, artifact identity, and system source")
        )
    matching_verifications = [
        value for value in verifications if value["statement_id"] == statement_id
    ]
    if len(matching_verifications) != 1:
        gaps.append(
            _gap(unit_id, "statement_verification_ambiguous", "evidence", "Statement has no unique collector verification")
        )
    else:
        verification = matching_verifications[0]
        verification_ok = (
            verification["repository"] == repository
            and verification["unit_id"] == unit_id
            and verification["source_sha"] == unit["source_sha"]
            and verification["state"] == "verified"
            and verification["population_complete"] is True
            and verification["source_binding_complete"] is True
            and verification["result_binding_complete"] is True
            and verification["artifact_binding_complete"] is True
            and verification["category_policy_verified"] is True
            and authoritative_source_id in verification["matched_authoritative_source_ids"]
            and set(verification["matched_authoritative_source_ids"]).issubset(
                set(statement["source_evidence_ids"])
            )
        )
        if not verification_ok:
            gaps.append(
                _gap(unit_id, "statement_verification_incomplete", "evidence", "Collector did not authenticate the statement's source, result, category, and artifact bindings")
            )
    return not gaps, True, gaps, [statement_id]


def _attestation_proof(
    *,
    unit: Mapping[str, Any],
    repository: str,
    expected_digests: Mapping[str, str],
    observation: Mapping[str, Any] | None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    unit_id = unit["unit_id"]
    population_complete, per_unit, population_gaps = _unit_population(
        observation,
        unit_id=unit_id,
        component="evidence",
        legacy_message="Verified source-binding attestation population is incomplete",
    )
    data = observation.get("data") if isinstance(observation, Mapping) else None
    assets = data.get("assets") if isinstance(data, Mapping) else None
    gaps = list(population_gaps)
    if not isinstance(assets, list):
        gaps.append(
            _gap(
                None if per_unit else unit_id,
                "attestation_population_malformed",
                "evidence",
                "The attestation asset population is malformed",
            )
        )
        assets = []
    if per_unit:
        if any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("unit_selector"), str)
            or not row.get("unit_selector")
            for row in assets
        ):
            gaps.append(
                _gap(
                    None,
                    "attestation_population_unscoped",
                    "evidence",
                    "A per-unit attestation row is malformed or unscoped",
                )
            )
        assets = [
            row
            for row in assets
            if isinstance(row, Mapping) and row.get("unit_selector") == unit_id
        ]
    if not population_complete or gaps:
        return False, gaps, []
    release_id = unit["selector"]["release_id"]
    relevant = [
        row
        for row in assets
        if isinstance(row, Mapping)
        and row.get("release_id") == release_id
        and isinstance(row.get("name"), str)
        and row.get("name") in expected_digests
    ]
    by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in relevant:
        by_name[str(row["name"])].append(row)
    source_ids: list[str] = []
    if set(by_name) != set(expected_digests) or any(len(rows) != 1 for rows in by_name.values()):
        gaps.append(
            _gap(unit_id, "attestation_asset_population_ambiguous", "evidence", "Attestation assets do not match the exact declared asset population")
        )
        return False, gaps, source_ids
    for name, expected_digest in expected_digests.items():
        row = by_name[name][0]
        binding = row.get("source_binding")
        if row.get("unit_selector") != unit_id:
            gaps.append(
                _gap(unit_id, "attestation_unit_unbound", "evidence", f"Attestation for {name!r} is not bound to this unit")
            )
            continue
        if (
            row.get("complete") is not True
            or _asset_digest(row.get("digest")) != expected_digest
            or not isinstance(binding, Mapping)
            or not _exact_keys(binding, _ATTESTATION_BINDING_KEYS)
        ):
            gaps.append(
                _gap(unit_id, "attestation_binding_invalid", "evidence", f"Attestation binding for {name!r} is incomplete")
            )
            continue
        matched_ids = binding["matched_authoritative_source_ids"]
        binding_ok = (
            binding["schema_version"] == ATTESTATION_BINDING_SCHEMA
            and binding["state"] == "verified"
            and binding["repository"] == repository
            and binding["unit_id"] == unit_id
            and binding["release_id"] == release_id
            and binding["asset_name"] == name
            and binding["artifact_sha256"] == expected_digest
            and binding["source_sha"] == unit["source_sha"]
            and binding["population_complete"] is True
            and binding["source_binding_complete"] is True
            and binding["artifact_binding_complete"] is True
            and binding["category_policy_verified"] is True
            and isinstance(matched_ids, list)
            and bool(matched_ids)
            and all(isinstance(item, str) and _SOURCE_ID.fullmatch(item) for item in matched_ids)
            and matched_ids == sorted(set(matched_ids))
        )
        if not binding_ok:
            gaps.append(
                _gap(unit_id, "attestation_binding_unverified", "evidence", f"Attestation for {name!r} does not prove exact repository, unit, source, and artifact bindings")
            )
        else:
            source_ids.extend(matched_ids)
    return not gaps, gaps, sorted(set(source_ids))


def _verified_attestation_conflicts(
    *,
    unit: Mapping[str, Any],
    repository: str,
    expected_digests: Mapping[str, str],
    observation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Expose contradictory verified claims without requiring this optional path."""

    data = observation.get("data") if isinstance(observation, Mapping) else None
    assets = data.get("assets") if isinstance(data, Mapping) else None
    if not isinstance(assets, list):
        return []
    unit_id = unit["unit_id"]
    release_id = unit["selector"]["release_id"]
    verified_by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    gaps: list[dict[str, Any]] = []
    for row in assets:
        if (
            not isinstance(row, Mapping)
            or row.get("release_id") != release_id
            or not isinstance(row.get("name"), str)
            or row.get("name") not in expected_digests
        ):
            continue
        binding = row.get("source_binding")
        if not isinstance(binding, Mapping) or binding.get("state") != "verified":
            continue
        name = row["name"]
        verified_by_name[name].append(binding)
        binding_matches = (
            _exact_keys(binding, _ATTESTATION_BINDING_KEYS)
            and binding.get("schema_version") == ATTESTATION_BINDING_SCHEMA
            and binding.get("repository") == repository
            and binding.get("unit_id") == unit_id
            and binding.get("release_id") == release_id
            and binding.get("asset_name") == name
            and binding.get("artifact_sha256") == expected_digests[name]
            and binding.get("source_sha") == unit["source_sha"]
            and _asset_digest(row.get("digest")) == expected_digests[name]
        )
        if not binding_matches:
            gaps.append(
                _gap(
                    unit_id,
                    "conflicting_verified_attestation",
                    "evidence",
                    f"A verified attestation contradicts the declared binding for {name!r}",
                )
            )
    for name, claims in verified_by_name.items():
        if len(claims) > 1:
            gaps.append(
                _gap(
                    unit_id,
                    "conflicting_verified_attestation",
                    "evidence",
                    f"Multiple verified attestation claims exist for {name!r}",
                )
            )
    return gaps


def _main_proof(
    *,
    unit: Mapping[str, Any],
    repository: str,
    exact_main_sha: str | None,
    ancestry_facts: Sequence[Mapping[str, Any]],
    intervening_check_facts: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    unit_id = unit["unit_id"]
    source_sha = unit["source_sha"]
    gaps: list[dict[str, Any]] = []
    components: dict[str, str] = {}
    if not _is_sha(exact_main_sha):
        return [
            _gap(unit_id, "main_sha_unknown", "main", "Exact Main SHA is unavailable")
        ], components
    if unit["correspondence"] == "Exact-Main" and source_sha != exact_main_sha:
        gaps.append(
            _gap(unit_id, "exact_main_mismatch", "main", "Exact-Main unit source does not equal exact Main SHA")
        )
    matching = [
        fact
        for fact in ancestry_facts
        if isinstance(fact, Mapping) and fact.get("unit_id") == unit_id
    ]
    if len(matching) != 1 or not _exact_keys(matching[0], _ANCESTRY_KEYS):
        gaps.append(
            _gap(unit_id, "main_ancestry_ambiguous", "main", "Main ancestry has no unique controlled fact")
        )
    else:
        fact = matching[0]
        ancestry_ok = (
            fact["schema_version"] == ANCESTRY_FACT_SCHEMA
            and fact["repository"] == repository
            and fact["source_sha"] == source_sha
            and fact["main_sha"] == exact_main_sha
            and fact["state"] == "verified"
            and fact["population_complete"] is True
            and fact["reachable_from_main"] is True
        )
        if ancestry_ok:
            components["main_reachable"] = "pass"
        else:
            gaps.append(
                _gap(unit_id, "main_ancestry_unverified", "main", "Declared source is not verified reachable from exact Main")
            )

    if unit["correspondence"] != "Releasable-Main":
        if not any(gap["component"] == "main" for gap in gaps):
            components["intervening_checks_passed"] = "pass"
        return gaps, components

    check_facts = [
        fact
        for fact in intervening_check_facts
        if isinstance(fact, Mapping) and fact.get("unit_id") == unit_id
    ]
    if len(check_facts) != 1 or not _exact_keys(check_facts[0], _INTERVENING_KEYS):
        gaps.append(
            _gap(unit_id, "intervening_checks_ambiguous", "main", "Intervening Main revisions have no unique controlled fact")
        )
        return gaps, components
    fact = check_facts[0]
    revisions = fact["revisions"]
    checks = unit.get("validation", {}).get("authoritative_checks")
    valid = (
        fact["schema_version"] == INTERVENING_CHECK_FACT_SCHEMA
        and fact["repository"] == repository
        and fact["source_sha"] == source_sha
        and fact["main_sha"] == exact_main_sha
        and fact["state"] == "verified"
        and fact["population_complete"] is True
        and isinstance(revisions, list)
        and isinstance(checks, list)
        and bool(checks)
        and len(checks) == len(set(checks))
    )
    revision_shas: list[str] = []
    if valid:
        for revision in revisions:
            if not isinstance(revision, Mapping) or not _exact_keys(revision, _REVISION_KEYS):
                valid = False
                break
            revision_sha = revision["sha"]
            check_rows = revision["checks"]
            if not _is_sha(revision_sha) or not isinstance(check_rows, list):
                valid = False
                break
            names: list[str] = []
            for check in check_rows:
                if not isinstance(check, Mapping) or not _exact_keys(check, _CHECK_KEYS):
                    valid = False
                    break
                if not isinstance(check["name"], str) or not isinstance(
                    check["conclusion"], str
                ):
                    valid = False
                    break
                names.append(check["name"])
                if check["conclusion"] != "success":
                    valid = False
            if names != checks or len(names) != len(set(names)):
                valid = False
            revision_shas.append(revision_sha)
    if len(revision_shas) != len(set(revision_shas)) or source_sha in revision_shas:
        valid = False
    if source_sha != exact_main_sha and (not revision_shas or revision_shas[-1] != exact_main_sha):
        valid = False
    if valid:
        components["intervening_checks_passed"] = "pass"
    else:
        gaps.append(
            _gap(unit_id, "intervening_checks_unverified", "main", "Every intervening Main revision was not proven to pass every authoritative check")
        )
    return gaps, components


def _declared_selector_key(unit: Mapping[str, Any]) -> tuple[Any, ...] | None:
    profile = unit["profile"]
    if profile in INACTIVE_PROFILES:
        return None
    selector = unit["selector"]
    if profile in {"application-github-deployment", "documentation-publication"}:
        return (selector["system"], selector["deployment_id"])
    if profile == "package-github-release":
        return ("github-releases", selector["release_id"], selector["tag"])
    if profile == "gitops-production-ref":
        return ("git", selector["production_ref"], selector["path"])
    raise DeliveryResolutionError(f"unit {unit['unit_id']!r} has no selector policy")


def resolve_delivery(
    production_identity: Mapping[str, Any],
    *,
    delivery_observation: Mapping[str, Any] | None,
    refs_releases_observation: Mapping[str, Any] | None,
    attestation_observation: Mapping[str, Any] | None,
    evidence_statements: Sequence[Mapping[str, Any]],
    statement_verifications: Sequence[Mapping[str, Any]],
    exact_main_sha: str | None,
    ancestry_facts: Sequence[Mapping[str, Any]],
    intervening_check_facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve each generic production unit without inferring missing proof.

    Malformed raw observations become explicit Unknown gaps.  Only violation of
    the caller contract that the production identity is already validated (or
    non-sequence fact arguments) raises ``DeliveryResolutionError``.
    """

    repository, units = _validated_identity_contract(production_identity)
    for name, facts in (
        ("ancestry_facts", ancestry_facts),
        ("intervening_check_facts", intervening_check_facts),
    ):
        if isinstance(facts, (str, bytes)) or not isinstance(facts, Sequence):
            raise DeliveryResolutionError(f"{name} must be a sequence")
    statements, statement_input_gaps = _normalize_statements(evidence_statements)
    verifications, verification_input_gaps = _normalize_verifications(statement_verifications)
    shared_input_gaps = [
        *statement_input_gaps,
        *verification_input_gaps,
        *_unscoped_observation_gaps(
            delivery_observation,
            component="delivery",
        ),
        *_unscoped_observation_gaps(
            refs_releases_observation,
            component="delivery",
        ),
        *_unscoped_observation_gaps(
            attestation_observation,
            component="evidence",
        ),
        *_unscoped_population_integrity_gaps(
            delivery_observation=delivery_observation,
            refs_releases_observation=refs_releases_observation,
            attestation_observation=attestation_observation,
        ),
    ]
    selector_counts = Counter(
        key for unit in units if (key := _declared_selector_key(unit)) is not None
    )

    results: list[dict[str, Any]] = []
    for unit in units:
        unit_id = unit["unit_id"]
        profile = unit["profile"]
        components = _component_template()
        gaps = _unit_gaps(shared_input_gaps, unit_id)
        source_ids: list[str] = []
        statement_ids: list[str] = []
        if profile in INACTIVE_PROFILES:
            gaps.append(
                _gap(
                    unit_id,
                    "governance_adapter_pending",
                    "governance",
                    "Inactive output dispositions remain Unknown until an authoritative governance adapter verifies applicability and freshness",
                )
            )
        else:
            policy = PROFILE_POLICY[profile]
            selector_key = _declared_selector_key(unit)
            declaration_unique = selector_key is not None and selector_counts[selector_key] == 1
            if profile == "application-github-deployment":
                source_id, digests, local_gaps, passed_components = _exact_deployment_record(
                    unit,
                    delivery_observation,
                    repository=repository,
                    documentation=False,
                    declaration_unique=declaration_unique,
                )
            elif profile == "documentation-publication":
                source_id, digests, local_gaps, passed_components = _exact_deployment_record(
                    unit,
                    delivery_observation,
                    repository=repository,
                    documentation=True,
                    declaration_unique=declaration_unique,
                )
            elif profile == "gitops-production-ref":
                source_id, digests, local_gaps, passed_components = _exact_gitops_record(
                    unit,
                    refs_releases_observation,
                    repository=repository,
                    declaration_unique=declaration_unique,
                )
            else:
                source_id, digests, local_gaps, passed_components = _exact_release_record(
                    unit,
                    refs_releases_observation,
                    declaration_unique=declaration_unique,
                )
            gaps.extend(local_gaps)
            components.update(passed_components)

            if profile == "package-github-release":
                statement_passed, statement_present, proof_gaps, proof_ids = _statement_proof(
                    unit=unit,
                    repository=repository,
                    policy=policy,
                    expected_digests=digests,
                    authoritative_source_id=source_id,
                    statements=statements,
                    verifications=verifications,
                    optional=True,
                )
                statement_ids.extend(proof_ids)
                if statement_present:
                    gaps.extend(proof_gaps)
                    attestation_conflicts = _verified_attestation_conflicts(
                        unit=unit,
                        repository=repository,
                        expected_digests=digests,
                        observation=attestation_observation,
                    )
                    gaps.extend(attestation_conflicts)
                    proof_passed = statement_passed and not attestation_conflicts
                else:
                    attested, attestation_gaps, attestation_ids = _attestation_proof(
                        unit=unit,
                        repository=repository,
                        expected_digests=digests,
                        observation=attestation_observation,
                    )
                    gaps.extend(attestation_gaps)
                    source_ids.extend(attestation_ids)
                    proof_passed = attested
            else:
                proof_passed, _present, proof_gaps, proof_ids = _statement_proof(
                    unit=unit,
                    repository=repository,
                    policy=policy,
                    expected_digests=digests,
                    authoritative_source_id=source_id,
                    statements=statements,
                    verifications=verifications,
                )
                gaps.extend(proof_gaps)
                statement_ids.extend(proof_ids)
            if proof_passed:
                components["statement_or_attestation_verified"] = "pass"
                if source_id is not None:
                    source_ids.append(source_id)

            main_gaps, main_components = _main_proof(
                unit=unit,
                repository=repository,
                exact_main_sha=exact_main_sha,
                ancestry_facts=ancestry_facts,
                intervening_check_facts=intervening_check_facts,
            )
            gaps.extend(main_gaps)
            components.update(main_components)

        if any(value == "fail" for value in components.values()):
            state = "nonconforming"
        elif not gaps and all(value == "pass" for value in components.values()):
            state = "resolved"
        else:
            state = "unknown"
        results.append(
            {
                "unit_id": unit_id,
                "profile": profile,
                "correspondence": unit["correspondence"],
                "source_sha": unit.get("source_sha"),
                "state": state,
                "traceable": (
                    True
                    if state == "resolved"
                    else (False if state == "nonconforming" else None)
                ),
                "authoritative_source_ids": sorted(set(source_ids)) if state == "resolved" else [],
                "evidence_statement_ids": sorted(set(statement_ids)) if state == "resolved" else [],
                "components": components,
                "gaps": gaps,
            }
        )

    all_gaps = [gap for result in results for gap in result["gaps"]]
    return {
        "schema_version": RESOLUTION_SCHEMA,
        "policy_version": POLICY_VERSION,
        "repository": repository,
        "main_sha": exact_main_sha if _is_sha(exact_main_sha) else None,
        "complete": bool(results) and all(result["state"] == "resolved" for result in results),
        "units": results,
        "gaps": all_gaps,
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }


__all__ = [
    "ANCESTRY_FACT_SCHEMA",
    "ATTESTATION_BINDING_SCHEMA",
    "DeliveryResolutionError",
    "INTERVENING_CHECK_FACT_SCHEMA",
    "POLICY_VERSION",
    "PROFILE_POLICY",
    "RESOLUTION_SCHEMA",
    "STATEMENT_VERIFICATION_SCHEMA",
    "resolve_delivery",
]

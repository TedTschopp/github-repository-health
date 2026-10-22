"""Pure mapping from delivery resolution to normalized metric observations.

The delivery resolver answers whether each declared production unit has enough
authoritative evidence to be traced.  This module translates that answer into
the existing M-SPI-02S and M-SPI-04 observation contracts.  It performs no
collection, does not mutate its inputs, and does not aggregate units; the
measurement layer retains its existing worst-unit and 90-day-history rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .delivery_resolution import RESOLUTION_SCHEMA
from .models import OBSERVATION_SCHEMA_VERSION
from .production_identity import GENERIC_PRODUCTION_SCHEMA


DELIVERY_METRIC_SOURCE = "repository-health-delivery-resolution"
REQUIRED_CORRESPONDENCE_SNAPSHOTS = 90
_RESOLUTION_STATES = frozenset({"resolved", "nonconforming", "unknown"})
_KNOWN_COMPONENT_TRUE = frozenset({"pass", "passed", "verified", "conforming"})
_KNOWN_COMPONENT_FALSE = frozenset({"fail", "failed", "nonconforming"})


class DeliveryMetricsError(ValueError):
    """Raised when the caller violates the validated bridge contract."""


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeliveryMetricsError(f"{label} must be a nonempty string")
    return value


def _unit_ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DeliveryMetricsError(f"{label} must be a nonempty list")
    result: list[str] = []
    for index, member in enumerate(value):
        if isinstance(member, str):
            unit_id = _string(member, f"{label}[{index}]")
        elif isinstance(member, Mapping):
            unit_id = _string(
                member.get("unit_id") or member.get("unit"),
                f"{label}[{index}].unit_id",
            )
        else:
            raise DeliveryMetricsError(f"{label}[{index}] is not a unit identifier")
        if unit_id in result:
            raise DeliveryMetricsError(f"{label} contains duplicate unit {unit_id!r}")
        result.append(unit_id)
    return result


def _validated_inputs(
    bundle: Mapping[str, Any],
    production_identity: Mapping[str, Any],
    delivery_resolution: Mapping[str, Any],
) -> tuple[str, str, list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if bundle.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise DeliveryMetricsError("bundle must use RH-GITHUB-OBSERVATIONS-1.0")
    observations = bundle.get("observations")
    if not isinstance(observations, Mapping):
        raise DeliveryMetricsError("bundle observations must be an object")
    repository = _string(bundle.get("repository"), "bundle.repository")
    main_sha = _string(bundle.get("subject_sha"), "bundle.subject_sha")

    if production_identity.get("schema_version") != GENERIC_PRODUCTION_SCHEMA:
        raise DeliveryMetricsError("production identity must use RH-PRODUCTION-IDENTITY-2.0")
    if production_identity.get("repository") != repository:
        raise DeliveryMetricsError("production identity repository does not match the bundle")
    identity_units_raw = production_identity.get("units")
    if not isinstance(identity_units_raw, list) or not identity_units_raw:
        raise DeliveryMetricsError("production identity units must be a nonempty list")
    identity_units: list[Mapping[str, Any]] = []
    identity_ids: list[str] = []
    for index, raw in enumerate(identity_units_raw):
        if not isinstance(raw, Mapping):
            raise DeliveryMetricsError(f"production identity units[{index}] must be an object")
        unit_id = _string(raw.get("unit_id"), f"production identity units[{index}].unit_id")
        if unit_id in identity_ids:
            raise DeliveryMetricsError(f"production identity contains duplicate unit {unit_id!r}")
        _string(raw.get("profile"), f"production identity unit {unit_id!r}.profile")
        _string(raw.get("correspondence"), f"production identity unit {unit_id!r}.correspondence")
        identity_ids.append(unit_id)
        identity_units.append(raw)

    bundle_ids = _unit_ids(bundle.get("units"), "bundle.units")
    if set(bundle_ids) != set(identity_ids):
        raise DeliveryMetricsError("bundle units do not exactly match the validated production identity")

    if delivery_resolution.get("schema_version") != RESOLUTION_SCHEMA:
        raise DeliveryMetricsError("delivery resolution must use RH-DELIVERY-RESOLUTION-1.0")
    if delivery_resolution.get("repository") != repository:
        raise DeliveryMetricsError("delivery resolution repository does not match the bundle")
    if delivery_resolution.get("main_sha") != main_sha:
        raise DeliveryMetricsError("delivery resolution Main SHA does not match the bundle")
    resolution_units = delivery_resolution.get("units")
    if not isinstance(resolution_units, list):
        raise DeliveryMetricsError("delivery resolution units must be a list")
    by_unit: dict[str, Mapping[str, Any]] = {}
    identity_by_unit = {str(unit["unit_id"]): unit for unit in identity_units}
    for index, raw in enumerate(resolution_units):
        if not isinstance(raw, Mapping):
            raise DeliveryMetricsError(f"delivery resolution units[{index}] must be an object")
        unit_id = _string(raw.get("unit_id"), f"delivery resolution units[{index}].unit_id")
        if unit_id in by_unit:
            raise DeliveryMetricsError(f"delivery resolution contains duplicate unit {unit_id!r}")
        identity = identity_by_unit.get(unit_id)
        if identity is None:
            raise DeliveryMetricsError(f"delivery resolution has undeclared unit {unit_id!r}")
        if (
            raw.get("profile") != identity.get("profile")
            or raw.get("correspondence") != identity.get("correspondence")
            or raw.get("source_sha") != identity.get("source_sha")
        ):
            raise DeliveryMetricsError(
                f"delivery resolution identity fields conflict for unit {unit_id!r}"
            )
        if raw.get("state") not in _RESOLUTION_STATES:
            raise DeliveryMetricsError(
                f"delivery resolution state is unsupported for unit {unit_id!r}"
            )
        by_unit[unit_id] = raw
    if set(by_unit) != set(identity_ids):
        raise DeliveryMetricsError("delivery resolution units do not exactly match the production identity")
    return repository, main_sha, identity_units, by_unit


def _component_truth(components: Mapping[str, Any], name: str) -> bool | None:
    value = components.get(name)
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in _KNOWN_COMPONENT_TRUE:
        return True
    if normalized in _KNOWN_COMPONENT_FALSE:
        return False
    return None


def _relevant_gap_false(
    resolution: Mapping[str, Any],
    *,
    components: set[str],
    codes: set[str],
) -> bool:
    if resolution.get("state") != "nonconforming":
        return False
    gaps = resolution.get("gaps")
    if not isinstance(gaps, list):
        return False
    return any(
        isinstance(gap, Mapping)
        and (gap.get("component") in components or gap.get("code") in codes)
        for gap in gaps
    )


def _resolved_component(
    resolution: Mapping[str, Any],
    name: str,
    *,
    gap_components: set[str],
    gap_codes: set[str],
) -> bool | None:
    components = resolution.get("components")
    value = _component_truth(components, name) if isinstance(components, Mapping) else None
    if value is not None:
        return value
    if _relevant_gap_false(
        resolution, components=gap_components, codes=gap_codes
    ):
        return False
    return None


def _correspondence_row(
    identity: Mapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    main_sha: str,
) -> tuple[dict[str, Any], bool | None]:
    unit_id = str(identity["unit_id"])
    contract = str(identity["correspondence"])
    production_sha = identity.get("source_sha")
    source_bound = _resolved_component(
        resolution,
        "source_sha_matches",
        gap_components=set(),
        gap_codes={
            "deployment_source_mismatch",
            "production_ref_source_mismatch",
            "release_source_mismatch",
        },
    )
    reachable = _resolved_component(
        resolution,
        "main_reachable",
        gap_components=set(),
        gap_codes={"main_ancestry_unverified", "main_ancestry_ambiguous"},
    )
    intervening = _resolved_component(
        resolution,
        "intervening_checks_passed",
        gap_components=set(),
        gap_codes={"intervening_checks_unverified", "intervening_checks_ambiguous"},
    )

    production_ref_sha: str | None = None
    if contract == "Exact-Main":
        rule = "bound production source SHA must equal assessed Main SHA"
        conforming = (
            None
            if source_bound is None
            else False
            if source_bound is False
            else production_sha == main_sha
        )
    elif contract == "Releasable-Main":
        rule = (
            "bound production source may trail Main only when it is reachable "
            "and every intervening accepted Main revision passed authoritative checks"
        )
        if source_bound is None:
            conforming = None
        elif source_bound is False:
            conforming = False
        elif production_sha == main_sha:
            conforming = True
            reachable = True
            intervening = True
        elif reachable is False or intervening is False:
            conforming = False
        elif reachable is True and intervening is True:
            conforming = True
        else:
            conforming = None
    elif contract == "Production-Ref":
        rule = (
            "bound production source SHA must equal the declared production-ref "
            "SHA and be reachable from assessed Main"
        )
        selector = identity.get("selector")
        production_ref_sha = (
            selector.get("ref_commit_sha") if isinstance(selector, Mapping) else None
        )
        if source_bound is None or reachable is None:
            conforming = None
        elif source_bound is False or reachable is False:
            conforming = False
        else:
            conforming = (
                isinstance(production_sha, str)
                and isinstance(production_ref_sha, str)
                and production_sha == production_ref_sha
            )
    else:
        rule = "unsupported correspondence contract"
        conforming = None

    row = {
        "id": f"current-{unit_id}",
        "unit": unit_id,
        "is_current": True,
        "contract": contract,
        "contract_rule": rule,
        "production_sha": production_sha,
        "main_sha": main_sha,
        "production_ref_sha": production_ref_sha,
        "source_binding_verified": source_bound,
        "reachable_from_main": reachable,
        "intervening_gates_passed": intervening,
        "conforming": conforming,
        "resolution_state": resolution.get("state"),
        "resolution_components": deepcopy(resolution.get("components", {})),
        "resolution_gaps": deepcopy(resolution.get("gaps", [])),
    }
    return row, conforming


def _group_values(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _history_for_unit(
    value: Any,
    unit_id: str,
    *,
    multiple_units: bool,
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    completeness_flags: list[bool] = []
    for group in _group_values(value):
        group_unit = group.get("unit_id") or group.get("unit")
        if isinstance(group_unit, str) and group_unit != unit_id:
            continue
        data = group.get("data")
        if not isinstance(data, Mapping):
            continue
        by_unit = data.get("history_complete_by_unit")
        if isinstance(by_unit, Mapping) and isinstance(by_unit.get(unit_id), bool):
            completeness_flags.append(by_unit[unit_id])
        elif (group_unit == unit_id or not multiple_units) and isinstance(
            data.get("history_complete"), bool
        ):
            completeness_flags.append(data["history_complete"])
        candidates = data.get("items")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            if candidate.get("is_current") is True or candidate.get("current") is True:
                continue
            row_unit = candidate.get("unit_id") or candidate.get("unit")
            if isinstance(row_unit, str) and row_unit != unit_id:
                continue
            if row_unit in {None, ""} and multiple_units and group_unit != unit_id:
                continue
            row = deepcopy(dict(candidate))
            row["unit"] = unit_id
            rows.append(row)
    history_complete = bool(completeness_flags) and all(completeness_flags)
    return rows, history_complete


def _evidence_ids(resolution: Mapping[str, Any], unit_id: str) -> list[str]:
    result = [f"E-DELIVERY-RESOLUTION-{unit_id}"]
    for key in ("authoritative_source_ids", "evidence_statement_ids"):
        values = resolution.get(key)
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, str) and item)
    return list(dict.fromkeys(result))


def _observation_group(
    metric_id: str,
    *,
    bundle: Mapping[str, Any],
    unit_id: str,
    data: Mapping[str, Any],
    complete: bool,
    assurance: str,
    evidence_ids: list[str],
    gaps: list[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_gaps = [
        {
            "kind": str(gap.get("code") or gap.get("kind") or "delivery_resolution_unknown"),
            "source": DELIVERY_METRIC_SOURCE,
            "message": str(
                gap.get("message")
                or "Delivery resolution did not provide complete authoritative evidence."
            ),
        }
        for gap in gaps
    ]
    if not complete and not normalized_gaps:
        normalized_gaps.append(
            {
                "kind": "delivery_resolution_unknown",
                "source": DELIVERY_METRIC_SOURCE,
                "message": "Delivery resolution is Unknown for this unit.",
            }
        )
    return {
        "evidence_id": f"E-DELIVERY-{metric_id}-{unit_id}",
        "evidence_ids": evidence_ids,
        "observation_id": f"N-DELIVERY-{metric_id}-{unit_id}-{str(bundle.get('subject_sha'))[:12]}",
        "observed_at": bundle.get("observed_at"),
        "source": DELIVERY_METRIC_SOURCE,
        "source_codes": [RESOLUTION_SCHEMA],
        "subject_sha": bundle.get("subject_sha"),
        "unit_id": unit_id,
        "unit": unit_id,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else "partial",
        "complete": complete,
        "population_complete": complete,
        "assurance": assurance,
        "data": deepcopy(dict(data)),
        "gaps": [] if complete else normalized_gaps,
        "request": {
            "complete": complete,
            "population_complete": complete,
            "truncated": False,
        },
        "coverage": {"complete": complete, "population_complete": complete},
        "freshness": {"complete": complete, "fresh": complete, "max_age_hours": 24},
        "limitations": [],
    }


def apply_delivery_metrics(
    normalized_bundle: Mapping[str, Any],
    production_identity: Mapping[str, Any],
    delivery_resolution: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deep-copied bundle with unit-scoped delivery metric groups.

    ``resolved`` and ``nonconforming`` are complete E3 observations of true
    and false traceability respectively. ``unknown`` is incomplete E0 evidence.
    Correspondence is evaluated independently from the resolution's artifact
    outcome, using only the bound production source and the declared Main
    contract. Existing per-unit daily history is retained for M-SPI-04.
    """

    if not isinstance(normalized_bundle, Mapping):
        raise DeliveryMetricsError("normalized_bundle must be an object")
    if not isinstance(production_identity, Mapping):
        raise DeliveryMetricsError("production_identity must be an object")
    if not isinstance(delivery_resolution, Mapping):
        raise DeliveryMetricsError("delivery_resolution must be an object")
    _repository, main_sha, identity_units, resolutions = _validated_inputs(
        normalized_bundle, production_identity, delivery_resolution
    )
    result = deepcopy(dict(normalized_bundle))
    observations = result["observations"]
    if not isinstance(observations, dict):
        observations = dict(observations)
        result["observations"] = observations
    prior_correspondence = deepcopy(observations.get("M-SPI-04"))
    traceability_groups: list[dict[str, Any]] = []
    correspondence_groups: list[dict[str, Any]] = []
    multiple_units = len(identity_units) > 1

    for identity in identity_units:
        unit_id = str(identity["unit_id"])
        resolution = resolutions[unit_id]
        state = str(resolution["state"])
        traceable = True if state == "resolved" else False if state == "nonconforming" else None
        trace_complete = traceable is not None
        evidence_ids = _evidence_ids(resolution, unit_id)
        raw_gaps = resolution.get("gaps")
        resolution_gaps = (
            [gap for gap in raw_gaps if isinstance(gap, Mapping)]
            if isinstance(raw_gaps, list)
            else []
        )
        traceability_groups.append(
            _observation_group(
                "M-SPI-02S",
                bundle=result,
                unit_id=unit_id,
                data={
                    "items": [
                        {
                            "id": f"current-{unit_id}",
                            "unit": unit_id,
                            "traceable": traceable,
                            "resolution_state": state,
                            "authoritative_source_ids": deepcopy(
                                resolution.get("authoritative_source_ids", [])
                            ),
                            "evidence_statement_ids": deepcopy(
                                resolution.get("evidence_statement_ids", [])
                            ),
                            "resolution_components": deepcopy(
                                resolution.get("components", {})
                            ),
                            "resolution_gaps": deepcopy(resolution.get("gaps", [])),
                        }
                    ]
                },
                complete=trace_complete,
                assurance="E3" if trace_complete else "E0",
                evidence_ids=evidence_ids,
                gaps=resolution_gaps,
            )
        )

        history_rows, history_complete = _history_for_unit(
            prior_correspondence, unit_id, multiple_units=multiple_units
        )
        current_row, conforming = _correspondence_row(
            identity, resolution, main_sha=main_sha
        )
        correspondence_complete = isinstance(conforming, bool)
        correspondence_groups.append(
            _observation_group(
                "M-SPI-04",
                bundle=result,
                unit_id=unit_id,
                data={
                    "items": [*history_rows, current_row],
                    "history_complete": history_complete,
                    "required_daily_snapshots": REQUIRED_CORRESPONDENCE_SNAPSHOTS,
                    "history_complete_by_unit": {unit_id: history_complete},
                },
                complete=correspondence_complete,
                assurance="E3" if correspondence_complete else "E0",
                evidence_ids=evidence_ids,
                gaps=[] if correspondence_complete else resolution_gaps,
            )
        )

    observations["M-SPI-02S"] = traceability_groups
    observations["M-SPI-04"] = correspondence_groups
    return result


__all__ = [
    "DELIVERY_METRIC_SOURCE",
    "DeliveryMetricsError",
    "REQUIRED_CORRESPONDENCE_SNAPSHOTS",
    "apply_delivery_metrics",
]

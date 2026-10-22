"""Fail-closed repository-health metric calculations.

The preferred input is an ``RH-GITHUB-OBSERVATIONS-1.0`` bundle parsed by
:class:`~automation.repository_health.models.ObservationBundle`.  Collector
groups may contain raw GitHub records, but a metric can pass only when the
group also carries enough normalized facts to evaluate the metric definition.
Missing classifications are not guessed from names or branch conventions.

Metric-specific groups can use the metric ID as their key and place records in
``data.items``.  A record may provide the metric's explicit outcome field (for
example ``valid``, ``traceable``, ``complete``, or ``conforming``) or all of the
atomic fields documented in the calculator below.  Raw collector group aliases
are accepted where their data is sufficient; otherwise their result is
Unknown, while the partial records remain visible in ``components``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import statistics
from typing import Any, Callable, Iterable, Mapping, Sequence

from .models import (
    METRIC_SCHEMA_VERSION,
    METRIC_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    THRESHOLD_VERSION,
    MetricResult,
    Observation,
    ObservationBundle,
)


METRIC_IDS = (
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
)

CURRENT_METRICS = frozenset({"M-SPI-01", "M-SPI-02S", "M-SPI-03", "M-SPI-04", "M-CGD-01", "M-CGD-02"})
HISTORY_METRICS = frozenset(set(METRIC_IDS) - CURRENT_METRICS)

GATE_METRICS = {
    "G-01": "M-SPI-01",
    "G-02": "M-SPI-02S",
    "G-03": "M-CGD-01",
    "G-04": "M-CGD-02",
}

GROUP_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    # Each inner tuple is a priority tier.  A purpose-built normalized group
    # wins over raw collector groups so an unrelated raw gap does not erase a
    # complete metric observation.
    "M-SPI-01": (("main_validity",), ("check_runs",)),
    "M-SPI-01T": (("main_validity_history",), ("actions_w90",), ("actions_w365",)),
    "M-SPI-02S": (("current_outputs", "production_identity"), ("delivery", "refs_releases")),
    "M-SPI-02": (("release_traceability",), ("refs_releases",)),
    "M-SPI-03": (("release_identity",), ("refs_releases", "attestations")),
    "M-SPI-04": (("production_correspondence", "correspondence_snapshots"),),
    "M-CGD-01": (("audited_main_changes",), ("change_history", "rules")),
    "M-CGD-02": (("critical_ref_protection",), ("rules",)),
    "M-BTC-01": (("build_replays",), ("actions_w365",), ("actions_w90",)),
    "M-BTC-02": (("per_change_ci",), ("change_history", "actions_w90", "actions_w365")),
    "M-BTC-03": (("validation_categories",), ("change_history", "actions_w90", "actions_w365")),
    "M-BTC-04": (("feedback_latency",), ("actions_w90", "actions_w365", "change_history")),
    "M-BTC-05": (("flaky_reruns",), ("actions_w90", "actions_w365")),
    "M-CGD-04": (("required_check_enforcement",), ("change_history", "rules")),
}

DEFAULT_WINDOWS: dict[str, dict[str, Any]] = {
    "M-SPI-01": {"kind": "current"},
    "M-SPI-02S": {"kind": "current"},
    "M-SPI-03": {"kind": "rolling", "days": 365, "includes_current_supported": True},
    "M-SPI-04": {"kind": "daily_snapshots", "days": 90, "includes_current": True},
    "M-CGD-01": {"kind": "rolling", "days": 90, "extension_days": 365, "includes_current": True},
    "M-CGD-02": {"kind": "current"},
    "M-SPI-01T": {"kind": "rolling", "days": 90},
    "M-SPI-02": {"kind": "rolling", "days": 90, "extension_days": 365},
    "M-BTC-01": {"kind": "latest_distinct_main_sha", "limit": 10, "days": 365},
    "M-BTC-02": {"kind": "rolling", "days": 90, "extension_days": 365},
    "M-BTC-03": {"kind": "rolling", "days": 90, "extension_days": 365},
    "M-BTC-04": {"kind": "selected_revisions", "days": 90, "extension_days": 365, "limit": 30},
    "M-BTC-05": {"kind": "rolling", "days": 90, "extension_days": 365},
    "M-CGD-04": {"kind": "rolling", "days": 90, "extension_days": 365, "includes_current": True},
}

ASSURANCE_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}
BAND_ORDER = {"Pass": 0, "Concern": 1, "Fail": 2}

SUCCESS_CONCLUSIONS = {"success", "successful", "passed", "pass"}
FAILURE_CONCLUSIONS = {"failure", "failed", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}


def _as_bundle(raw: ObservationBundle | Mapping[str, Any]) -> ObservationBundle:
    if isinstance(raw, ObservationBundle):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError("observation bundle must be a mapping or ObservationBundle")
    return ObservationBundle.from_mapping(raw)


def _norm_name(value: str) -> str:
    return value.lower().replace("-", "_")


def _select_observations(bundle: ObservationBundle, metric_id: str) -> list[Observation]:
    exact = [item for item in bundle.observations if _norm_name(item.name) == _norm_name(metric_id)]
    if exact:
        return exact
    for tier in GROUP_ALIASES.get(metric_id, ()):
        names = {_norm_name(name) for name in tier}
        selected = [item for item in bundle.observations if _norm_name(item.name) in names]
        if selected:
            return selected
    return []


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Evidence timestamps must identify their offset.  Treating an
        # unspecified local time as UTC can make stale or future evidence look
        # current, so an offset-free timestamp is unusable.
        return None
    return parsed.astimezone(timezone.utc)


def _is_fresh(observation: Observation, bundle: ObservationBundle, metric_id: str) -> tuple[bool, dict[str, Any]]:
    observed = _iso(observation.observed_at)
    assessed = _iso(bundle.observed_at)
    if observed is None or assessed is None:
        return False, {"fresh": False, "reason": "Observation or assessment timestamp is missing or invalid."}
    age_hours = (assessed - observed).total_seconds() / 3600.0
    if age_hours < 0:
        return False, {
            "fresh": False,
            "age_hours": round(age_hours, 3),
            "reason": "Observation timestamp is later than the assessment timestamp.",
        }

    explicit = observation.freshness
    if explicit:
        maximum = explicit.get("max_age_hours", 24.0)
        maximum = (
            float(maximum)
            if not isinstance(maximum, bool) and isinstance(maximum, (int, float)) and maximum >= 0
            else 24.0
        )
        fresh = explicit.get("fresh") is True and age_hours <= maximum
        if explicit.get("complete") is False:
            fresh = False
        return fresh, {**explicit, "fresh": fresh, "age_hours": round(age_hours, 3), "max_age_hours": maximum}

    # Current configuration/extract freshness is 24 hours.  Historical groups
    # are also expected to be extracted through no more than 24 hours before T.
    maximum = 24.0
    return age_hours <= maximum, {"fresh": age_hours <= maximum, "age_hours": round(age_hours, 3), "max_age_hours": maximum}


def _nested_population_complete(data: Any) -> bool:
    if not isinstance(data, Mapping):
        return True
    if data.get("complete") is False or data.get("population_complete") is False or data.get("truncated") is True:
        return False
    state = data.get("state")
    if isinstance(state, str) and state.lower() in {"unknown", "partial", "error", "unavailable"}:
        return False
    return True


def _observation_diagnostics(
    bundle: ObservationBundle,
    observations: Sequence[Observation],
    metric_id: str,
) -> tuple[bool, dict[str, Any], dict[str, Any], list[str], list[str]]:
    limitations: list[str] = []
    conflicts: list[str] = []
    fresh_records: list[dict[str, Any]] = []
    complete_count = 0
    for item in observations:
        fresh, detail = _is_fresh(item, bundle, metric_id)
        fresh_records.append({"observation": item.name, **detail})
        if item.usable and _nested_population_complete(item.data):
            complete_count += 1
        else:
            limitations.append(f"Observation group {item.name} is incomplete, partial, truncated, gapped, or unavailable.")
        if not fresh:
            limitations.append(f"Observation group {item.name} is not demonstrably fresh for {metric_id}.")
        limitations.extend(item.limitations)
        conflicts.extend(item.conflicts)
        for gap in item.gaps:
            message = gap.get("message") or gap.get("endpoint") or gap.get("kind")
            if message:
                limitations.append(f"{item.name}: {message}")
        if metric_id in CURRENT_METRICS and item.subject_sha and bundle.subject_sha and item.subject_sha != bundle.subject_sha:
            conflicts.append(
                f"{item.name} subject SHA {item.subject_sha} does not match assessed Main SHA {bundle.subject_sha}."
            )

    coverage = {
        "complete": bool(observations) and complete_count == len(observations),
        "observed_groups": len(observations),
        "complete_groups": complete_count,
        "population_complete": bool(observations) and all(item.population_complete for item in observations),
    }
    freshness = {
        "fresh": bool(observations) and all(record.get("fresh") is True for record in fresh_records),
        "observations": fresh_records,
    }
    usable = coverage["complete"] and freshness["fresh"] and not conflicts
    return usable, coverage, freshness, list(dict.fromkeys(limitations)), list(dict.fromkeys(conflicts))


def _metadata(observations: Sequence[Observation]) -> dict[str, Any]:
    evidence_ids: list[str] = []
    observation_ids: list[str] = []
    source_codes: list[str] = []
    exceptions: list[Any] = []
    assurances: list[str] = []
    for item in observations:
        evidence_ids.extend(item.evidence_ids)
        if item.observation_id:
            observation_ids.append(item.observation_id)
        source_codes.extend(item.source_codes)
        exceptions.extend(item.exceptions)
        if item.assurance:
            assurances.append(item.assurance)
    return {
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "observation_ids": list(dict.fromkeys(observation_ids)),
        "source_codes": list(dict.fromkeys(source_codes)),
        "exceptions": exceptions,
        "explicit_assurance": min(assurances, key=ASSURANCE_ORDER.__getitem__) if assurances else None,
    }


def _window(metric_id: str, observations: Sequence[Observation], bundle: ObservationBundle) -> dict[str, Any]:
    result = dict(DEFAULT_WINDOWS[metric_id])
    if result.get("kind") == "current":
        result["as_of"] = bundle.observed_at
    for item in observations:
        data = item.data
        if isinstance(data, Mapping) and isinstance(data.get("window"), Mapping):
            result.update(data["window"])
    return result


def _base_result(
    metric_id: str,
    bundle: ObservationBundle,
    unit_id: str | None,
    observations: Sequence[Observation],
    *,
    state: str,
    band: str | None = None,
    value: float | int | bool | None = None,
    unit: str | None = None,
    numerator: float | int | None = None,
    denominator: float | int | None = None,
    components: Mapping[str, Any] | None = None,
    sample_size: int = 0,
    sample_class: str | None = None,
    coverage: Mapping[str, Any] | None = None,
    freshness: Mapping[str, Any] | None = None,
    assurance: str | None = None,
    carried_band_from: str | None = None,
    limitations: Iterable[str] = (),
    conflicts: Iterable[str] = (),
) -> MetricResult:
    meta = _metadata(observations)
    if assurance is None:
        default = "E0" if state == "unknown" else "E2" if state == "n_a" else "E3"
        explicit = meta["explicit_assurance"]
        assurance = min((default, explicit), key=ASSURANCE_ORDER.__getitem__) if explicit else default
    return MetricResult(
        metric_id=metric_id,
        repository=bundle.repository,
        unit_id=unit_id,
        main_sha=bundle.subject_sha,
        state=state,
        band=band,
        value=value,
        unit=unit,
        numerator=numerator,
        denominator=denominator,
        components=dict(components or {}),
        sample_size=sample_size,
        sample_class=sample_class or ("Unknown" if state == "unknown" else "Current" if metric_id in CURRENT_METRICS else "Standard"),
        window=_window(metric_id, observations, bundle),
        coverage=dict(coverage or {"complete": False}),
        freshness=dict(freshness or {"fresh": False}),
        assurance=assurance,
        evidence_ids=meta["evidence_ids"],
        observation_ids=meta["observation_ids"],
        source_codes=meta["source_codes"],
        threshold_version=THRESHOLD_VERSION,
        carried_band_from=carried_band_from,
        limitations=list(dict.fromkeys([*bundle.limitations, *limitations])),
        conflicts=list(dict.fromkeys([*bundle.conflicts, *conflicts])),
        exceptions=[*bundle.exceptions, *meta["exceptions"]],
    )


def _unknown(
    metric_id: str,
    bundle: ObservationBundle,
    unit_id: str | None,
    observations: Sequence[Observation],
    reason: str,
    *,
    coverage: Mapping[str, Any] | None = None,
    freshness: Mapping[str, Any] | None = None,
    components: Mapping[str, Any] | None = None,
    limitations: Iterable[str] = (),
    conflicts: Iterable[str] = (),
) -> MetricResult:
    return _base_result(
        metric_id,
        bundle,
        unit_id,
        observations,
        state="unknown",
        components=components,
        coverage=coverage,
        freshness=freshness,
        limitations=[reason, *limitations],
        conflicts=conflicts,
    )


def _observation_rows(observations: Sequence[Observation], keys: Sequence[str] = ()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    common_keys = (
        "items",
        "records",
        "outputs",
        "snapshots",
        "releases",
        "changes",
        "refs",
        "replays",
        "category_pairs",
        "latencies",
        "rerun_groups",
    )
    for item in observations:
        data = item.data
        candidates: Any = None
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, Mapping):
            for key in (*keys, *common_keys):
                if isinstance(data.get(key), list):
                    candidates = data[key]
                    break
            if candidates is None:
                candidates = [data]
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            row = dict(candidate)
            row["__observation_name"] = item.name
            row["__observation_id"] = item.observation_id
            rows.append(row)
    return rows


def _unit_rows(
    rows: Sequence[dict[str, Any]],
    unit_id: str | None,
    units: Sequence[str] = (),
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    multiple_units = len(units) > 1
    for row in rows:
        row_unit = row.get("unit_id") or row.get("unit")
        if unit_id is None:
            if not isinstance(row_unit, str) or not row_unit:
                selected.append(row)
        elif row_unit == unit_id or (not multiple_units and row_unit in {None, ""}):
            selected.append(row)
    return selected


def _bool_field(row: Mapping[str, Any], *keys: str) -> bool | None:
    seen: list[bool] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            seen.append(value)
    if not seen:
        return None
    if len(set(seen)) > 1:
        return None
    return seen[0]


def _required_truth(row: Mapping[str, Any], fields: Sequence[Sequence[str]]) -> bool | None:
    values = [_bool_field(row, *aliases) for aliases in fields]
    if any(value is None for value in values):
        return None
    return all(values)


def _identity(row: Mapping[str, Any], index: int) -> str:
    for key in ("id", "observation_key", "sha", "source_sha", "commit_sha", "name", "ref", "tag", "release_id"):
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value):
            return f"{key}:{value}"
    return f"row:{index}"


def _truth_conflicts(rows: Sequence[Mapping[str, Any]], values: Sequence[bool | None]) -> list[str]:
    by_identity: dict[str, set[bool]] = {}
    for index, (row, value) in enumerate(zip(rows, values)):
        if value is None:
            continue
        by_identity.setdefault(_identity(row, index), set()).add(value)
    return [f"Conflicting outcomes were observed for {identity}." for identity, outcomes in by_identity.items() if len(outcomes) > 1]


def _ratio_band(value: float, concern_floor: float = 95.0) -> str:
    if math.isclose(value, 100.0, abs_tol=1e-9):
        return "Pass"
    if value >= concern_floor:
        return "Concern"
    return "Fail"


def _percent_result(
    metric_id: str,
    bundle: ObservationBundle,
    unit_id: str | None,
    observations: Sequence[Observation],
    truths: Sequence[bool],
    *,
    concern_floor: float = 95.0,
    no_concern: bool = False,
    coverage: Mapping[str, Any],
    freshness: Mapping[str, Any],
    components: Mapping[str, Any] | None = None,
    sample_class: str | None = None,
    force_fail: bool = False,
) -> MetricResult:
    denominator = len(truths)
    numerator = sum(truths)
    value = numerator / denominator * 100.0
    band = "Pass" if math.isclose(value, 100.0, abs_tol=1e-9) else "Fail" if no_concern else _ratio_band(value, concern_floor)
    if force_fail:
        band = "Fail"
    return _base_result(
        metric_id,
        bundle,
        unit_id,
        observations,
        state="measured",
        band=band,
        value=round(value, 4),
        unit="percent",
        numerator=numerator,
        denominator=denominator,
        components=components,
        sample_size=denominator,
        sample_class=sample_class,
        coverage=coverage,
        freshness=freshness,
    )


def _explicit_n_a(data: Any) -> tuple[bool, str | None]:
    if not isinstance(data, Mapping):
        return False, None
    state = str(data.get("state") or "").lower()
    applicable = data.get("applicable")
    reason = data.get("n_a_reason") or data.get("reason")
    evidenced = data.get("n_a_evidence") is True or data.get("inventory_complete") is True
    return (state == "n_a" or applicable is False) and evidenced and isinstance(reason, str) and bool(reason), reason if isinstance(reason, str) else None


def _prepare(
    metric_id: str,
    bundle: ObservationBundle,
    unit_id: str | None,
) -> tuple[list[Observation], list[dict[str, Any]], dict[str, Any], dict[str, Any], MetricResult | None]:
    observations = _select_observations(bundle, metric_id)
    if unit_id is not None:
        scoped = [item for item in observations if item.unit_id in {None, unit_id}]
        observations = scoped
    if not observations:
        result = _unknown(metric_id, bundle, unit_id, (), "No applicable normalized observation group was supplied.")
        return [], [], result.coverage, result.freshness, result
    usable, coverage, freshness, limitations, conflicts = _observation_diagnostics(bundle, observations, metric_id)
    rows = _unit_rows(_observation_rows(observations), unit_id, bundle.units)
    if not usable:
        result = _unknown(
            metric_id,
            bundle,
            unit_id,
            observations,
            "Complete, fresh, conflict-free eligible-population evidence is required.",
            coverage=coverage,
            freshness=freshness,
            components={"partial_row_count": len(rows)},
            limitations=limitations,
            conflicts=conflicts,
        )
        return observations, rows, coverage, freshness, result
    return observations, rows, coverage, freshness, None


def _main_validity(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-SPI-01"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    truths: list[bool | None] = []
    for row in rows:
        explicit = _bool_field(row, "valid", "main_valid", "satisfied")
        if explicit is not None:
            truths.append(explicit)
            continue
        truths.append(
            _required_truth(
                row,
                (
                    ("exact_main_sha", "exact_sha"),
                    ("authoritative_results_terminal", "terminal"),
                    ("all_required_checks_succeeded", "checks_succeeded"),
                    ("type_contract_satisfied", "releasable", "archive_disposition_satisfied"),
                ),
            )
        )
    if not rows:
        return _unknown(metric_id, bundle, unit_id, observations, "No Main-validity assertion for the exact Main SHA was supplied.", coverage=coverage, freshness=freshness)
    conflicts = _truth_conflicts(rows, truths)
    if conflicts or any(value is None for value in truths):
        return _unknown(
            metric_id,
            bundle,
            unit_id,
            observations,
            "A Main-validity assertion is missing, unclassifiable, or contradictory.",
            coverage=coverage,
            freshness=freshness,
            components={"assertions": len(rows), "classified": sum(value is not None for value in truths)},
            conflicts=conflicts,
        )
    valid = all(bool(value) for value in truths)
    return _base_result(
        metric_id,
        bundle,
        unit_id,
        observations,
        state="measured",
        band="Pass" if valid else "Fail",
        value=1 if valid else 0,
        unit="binary",
        numerator=1 if valid else 0,
        denominator=1,
        components={"assertion_count": len(truths)},
        sample_size=1,
        coverage=coverage,
        freshness=freshness,
    )


def _traceable_output(row: Mapping[str, Any]) -> bool | None:
    explicit = _bool_field(row, "traceable", "satisfied", "conforming")
    if explicit is not None:
        return explicit
    return _required_truth(
        row,
        (
            ("immutable_source_revision", "source_immutable"),
            ("source_reachable_from_main", "reachable_from_main", "is_ancestor"),
            ("immutable_artifact_identity", "artifact_immutable", "stable_digest"),
            ("successful_current_status", "current_status_successful", "healthy"),
        ),
    )


def _current_traceability(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-SPI-02S"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    if not rows:
        for item in observations:
            n_a, reason = _explicit_n_a(item.data)
            if n_a:
                return _base_result(
                    metric_id,
                    bundle,
                    unit_id,
                    observations,
                    state="n_a",
                    sample_class="Evidence-backed N/A",
                    coverage=coverage,
                    freshness=freshness,
                    limitations=[reason or "No applicable current output."],
                )
        return _unknown(metric_id, bundle, unit_id, observations, "The current output inventory is empty without evidence-backed N/A classification.", coverage=coverage, freshness=freshness)
    truths = [_traceable_output(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    if conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "A current output identity or ancestry assertion is unresolved.", coverage=coverage, freshness=freshness, components={"outputs": len(rows)}, conflicts=conflicts)
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], no_concern=True, coverage=coverage, freshness=freshness)


def _release_identity_truth(row: Mapping[str, Any]) -> bool | None:
    if row.get("overwritten") is True:
        return False
    explicit = _bool_field(row, "immutable_identity", "identity_compliant", "satisfied")
    if explicit is not None:
        return explicit
    protected = _bool_field(row, "ref_protected", "tag_protected", "protected", "immutable")
    digest = _bool_field(row, "stable_digest", "artifact_digest_present")
    if digest is None:
        digest_value = row.get("artifact_digest") or row.get("digest")
        assets = row.get("assets")
        if isinstance(digest_value, str) and digest_value:
            digest = True
        elif isinstance(assets, list) and assets:
            digest = all(isinstance(asset, Mapping) and isinstance(asset.get("digest"), str) and bool(asset.get("digest")) for asset in assets)
    provenance = _bool_field(row, "provenance_link", "build_link", "attested")
    if provenance is None and isinstance(row.get("attestations"), list):
        provenance = bool(row["attestations"])
    if protected is None or digest is None or provenance is None:
        return None
    return protected and digest and provenance


def _raw_release_identity_rows(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    """Join raw release assets to digest-scoped GitHub attestations."""

    attested_assets: dict[tuple[Any, Any], bool] = {}
    for item in observations:
        if _norm_name(item.name) != "attestations" or not isinstance(item.data, Mapping):
            continue
        assets = item.data.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            release_id = asset.get("release_id")
            asset_id = asset.get("asset_id")
            attestations = asset.get("attestations")
            attested_assets[(release_id, asset_id)] = isinstance(attestations, list) and bool(attestations)

    rows: list[dict[str, Any]] = []
    for item in observations:
        if _norm_name(item.name) != "refs_releases" or not isinstance(item.data, Mapping):
            continue
        releases = item.data.get("releases")
        if not isinstance(releases, list):
            continue
        for raw_release in releases:
            if not isinstance(raw_release, Mapping):
                continue
            release = dict(raw_release)
            assets = release.get("assets")
            release_id = release.get("id")
            if isinstance(assets, list) and assets:
                release["artifact_digest_present"] = all(
                    isinstance(asset, Mapping)
                    and isinstance(asset.get("digest"), str)
                    and str(asset.get("digest")).startswith("sha256:")
                    for asset in assets
                )
                release["attested"] = all(
                    isinstance(asset, Mapping) and attested_assets.get((release_id, asset.get("id"))) is True
                    for asset in assets
                )
            rows.append(release)
    return rows


def _release_identity(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-SPI-03"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    # Raw GitHub release and attestation groups are joined by immutable release
    # and asset IDs.  Purpose-built metric rows need no such adaptation.
    if any(_norm_name(item.name) == "refs_releases" for item in observations):
        rows = _unit_rows(_raw_release_identity_rows(observations), unit_id, bundle.units)
    if not rows:
        for item in observations:
            data = item.data
            if isinstance(data, Mapping) and data.get("inventory_complete") is True and data.get("no_current_supported_release") is True and data.get("no_w365_releases") is True:
                return _base_result(metric_id, bundle, unit_id, observations, state="n_a", sample_class="Evidence-backed N/A", coverage=coverage, freshness=freshness)
        return _unknown(metric_id, bundle, unit_id, observations, "No eligible release population or evidence-backed N/A result was supplied.", coverage=coverage, freshness=freshness)
    truths = [_release_identity_truth(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    if conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Release protection, digest, or provenance/build linkage is unresolved.", coverage=coverage, freshness=freshness, components={"releases": len(rows)}, conflicts=conflicts)
    overwritten = any(row.get("overwritten") is True for row in rows)
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=95.0, coverage=coverage, freshness=freshness, force_fail=overwritten)


def _correspondence_truth(row: Mapping[str, Any]) -> bool | None:
    explicit = _bool_field(row, "conforming", "correspondence_satisfied", "satisfied")
    if explicit is not None:
        return explicit
    contract = row.get("contract") or row.get("correspondence")
    if contract == "Exact-Main":
        production = row.get("production_sha") or row.get("prod_sha")
        main = row.get("main_sha")
        return production == main if isinstance(production, str) and isinstance(main, str) else None
    if contract == "Releasable-Main":
        production = row.get("production_sha") or row.get("prod_sha")
        main = row.get("main_sha")
        if isinstance(production, str) and production and production == main:
            return True
        reachable = _bool_field(row, "production_reachable_from_main", "reachable_from_main", "is_ancestor")
        intervening = _bool_field(row, "intervening_gates_passed", "intervening_revisions_valid")
        if reachable is None or intervening is None:
            return None
        return reachable and intervening
    if contract == "Production-Ref":
        production = row.get("production_sha") or row.get("prod_sha")
        production_ref = row.get("production_ref_sha") or row.get("prod_ref_sha")
        reachable = _bool_field(row, "production_reachable_from_main", "reachable_from_main", "is_ancestor")
        if not isinstance(production, str) or not isinstance(production_ref, str) or reachable is None:
            return None
        return production == production_ref and reachable
    return None


def _correspondence(bundle: ObservationBundle, unit_id: str | None, current_traceability: MetricResult) -> MetricResult:
    metric_id = "M-SPI-04"
    if current_traceability.state == "n_a":
        return _base_result(metric_id, bundle, unit_id, (), state="n_a", sample_class="N/A carried from M-SPI-02S", coverage=current_traceability.coverage, freshness=current_traceability.freshness, limitations=["Applicability follows M-SPI-02S."], assurance=current_traceability.assurance)
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    # A canonical group can carry the current row separately from snapshots.
    for item in observations:
        if isinstance(item.data, Mapping) and isinstance(item.data.get("current"), Mapping):
            current = dict(item.data["current"])
            current["is_current"] = True
            current["__observation_name"] = item.name
            rows.append(current)
    if not rows:
        return _unknown(metric_id, bundle, unit_id, observations, "No current or daily correspondence snapshots were supplied.", coverage=coverage, freshness=freshness)
    truths = [_correspondence_truth(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    current_indices = [index for index, row in enumerate(rows) if row.get("is_current") is True or row.get("current") is True]
    if not current_indices:
        return _unknown(metric_id, bundle, unit_id, observations, "A distinct current correspondence observation is required.", coverage=coverage, freshness=freshness, components={"snapshots": len(rows)})
    if conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "A correspondence contract, ancestry relation, or intervening-gate result is unresolved.", coverage=coverage, freshness=freshness, components={"snapshots": len(rows)}, conflicts=conflicts)
    current_conforms = all(bool(truths[index]) for index in current_indices)
    historical_indices = [index for index in range(len(rows)) if index not in current_indices]
    current_components = {
        "current_conforms": current_conforms,
        "current_evidence_assurance": current_traceability.assurance,
        "current_observations": len(current_indices),
        "daily_snapshots": len(historical_indices),
    }
    history_complete = _data_flag(observations, "history_complete") is True
    required_snapshots = next(
        (
            int(item.data["required_daily_snapshots"])
            for item in observations
            if isinstance(item.data, Mapping)
            and isinstance(item.data.get("required_daily_snapshots"), int)
            and not isinstance(item.data.get("required_daily_snapshots"), bool)
        ),
        90,
    )
    if not current_conforms:
        return _base_result(
            metric_id,
            bundle,
            unit_id,
            observations,
            state="measured",
            band="Fail",
            value=0.0,
            unit="percent",
            numerator=0,
            denominator=len(historical_indices) or None,
            components=current_components,
            sample_size=len(historical_indices),
            sample_class="Low Sample" if len(historical_indices) < required_snapshots else "Standard",
            coverage=coverage,
            freshness=freshness,
        )
    if not history_complete or len(historical_indices) < required_snapshots:
        return _unknown(
            metric_id,
            bundle,
            unit_id,
            observations,
            f"Complete daily correspondence history requires {required_snapshots} prior snapshots.",
            coverage=coverage,
            freshness=freshness,
            components=current_components,
        )
    rate_truths = [bool(truths[index]) for index in historical_indices[-required_snapshots:]]
    result = _percent_result(metric_id, bundle, unit_id, observations, rate_truths, concern_floor=95.0, coverage=coverage, freshness=freshness, components=current_components, force_fail=False)
    return result


def _change_complete(row: Mapping[str, Any]) -> bool | None:
    explicit = _bool_field(row, "complete", "audit_complete", "satisfied")
    if explicit is not None:
        return explicit
    required = ("final_revision", "actor", "authorization", "required_checks", "acceptance_event", "bypass_used")
    if any(key not in row or row.get(key) is None or row.get(key) == "" for key in required):
        return None
    bypass = row.get("bypass_used")
    if not isinstance(bypass, bool):
        return None
    if bypass:
        bypass_required = ("affected_control_or_ref", "bypass_reason", "change_or_incident_link", "bypass_approval_or_review")
        if any(key not in row or row.get(key) is None or row.get(key) == "" for key in bypass_required):
            return False
        if row.get("temporary_access") is True and not row.get("access_expiry"):
            return False
    return True


def _data_flag(observations: Sequence[Observation], *keys: str) -> bool | None:
    values: list[bool] = []
    for item in observations:
        if not isinstance(item.data, Mapping):
            continue
        for key in keys:
            if isinstance(item.data.get(key), bool):
                values.append(item.data[key])
    if not values or len(set(values)) > 1:
        return None
    return values[0]


def _audited_changes(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-CGD-01"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    if any(_norm_name(item.name) == "change_history" for item in observations):
        rows = [row for row in rows if row.get("final_revision") or row.get("commit_sha") or row.get("bypass_used") is not None]
    enforcement = _data_flag(observations, "current_enforcement", "acceptance_enforced")
    if not rows:
        last_complete = _data_flag(observations, "last_accepted_change_complete", "last_change_complete")
        if enforcement is True and last_complete is True:
            return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Pass", value=100.0, unit="percent", numerator=0, denominator=0, components={"no_changes": True, "current_enforcement": True, "last_change_complete": True}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
        if enforcement is False:
            return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Fail", value=0.0, unit="percent", numerator=0, denominator=0, components={"no_changes": True, "current_enforcement": False}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
        return _unknown(metric_id, bundle, unit_id, observations, "No-change evaluation requires current enforcement and last accepted-change evidence.", coverage=coverage, freshness=freshness)
    truths = [_change_complete(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    if enforcement is None or conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Complete change enumeration, audit fields, and current enforcement state are required.", coverage=coverage, freshness=freshness, components={"changes": len(rows), "current_enforcement": enforcement}, conflicts=conflicts)
    values = [bool(value) for value in truths]
    return _percent_result(metric_id, bundle, unit_id, observations, values, no_concern=True, coverage=coverage, freshness=freshness, components={"eligible_changes": len(rows), "current_enforcement": enforcement}, force_fail=enforcement is False)


PROTECTION_ASSERTIONS = (
    ("restricted_update", "updates_restricted"),
    ("deletion_protection", "deletion_blocked"),
    ("force_push_protection", "history_rewrite_blocked", "non_fast_forward_blocked"),
    ("required_acceptance_checks", "required_checks_enforced"),
    ("controlled_audited_bypass", "bypass_controlled"),
)


def _critical_refs(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-CGD-02"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    if any(_norm_name(item.name) == "rules" for item in observations):
        rows = [row for row in rows if row.get("critical") is True or row.get("ref") or row.get("assertions")]
    if not rows:
        return _unknown(metric_id, bundle, unit_id, observations, "No complete inventory of active production-critical refs was supplied.", coverage=coverage, freshness=freshness)
    truths: list[bool | None] = []
    for row in rows:
        assertions = row.get("assertions") if isinstance(row.get("assertions"), Mapping) else row
        for aliases in PROTECTION_ASSERTIONS:
            truths.append(_bool_field(assertions, *aliases))
    if any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Every critical ref requires all five effective protection assertions.", coverage=coverage, freshness=freshness, components={"critical_refs": len(rows), "assertion_pairs": len(truths), "classified_pairs": sum(value is not None for value in truths)})
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], no_concern=True, coverage=coverage, freshness=freshness, components={"critical_refs": len(rows)})


def _main_invalid_trend(bundle: ObservationBundle, unit_id: str | None, current: MetricResult) -> MetricResult:
    metric_id = "M-SPI-01T"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    invalid_minutes: float | None = None
    observable_minutes: float | None = None
    durations: list[float] = []
    for item in observations:
        if isinstance(item.data, Mapping):
            if isinstance(item.data.get("invalid_minutes"), (int, float)):
                invalid_minutes = float(item.data["invalid_minutes"])
            if isinstance(item.data.get("observable_minutes"), (int, float)):
                observable_minutes = float(item.data["observable_minutes"])
    for row in rows:
        if isinstance(row.get("duration_minutes"), (int, float)):
            duration = float(row["duration_minutes"])
            if duration < 0:
                return _unknown(metric_id, bundle, unit_id, observations, "Invalid intervals cannot have negative duration.", coverage=coverage, freshness=freshness)
            durations.append(duration)
    no_events = _data_flag(observations, "no_events", "no_main_events") is True
    if no_events:
        return _base_result(metric_id, bundle, unit_id, observations, state="no_events", band=current.band, value=0.0 if current.band == "Pass" else None, unit="percent", numerator=0, denominator=observable_minutes, components={"current_metric_state": current.state}, sample_size=0, sample_class="No Events", coverage=coverage, freshness=freshness, assurance=current.assurance, carried_band_from="M-SPI-01")
    if invalid_minutes is None and durations:
        invalid_minutes = sum(durations)
    if invalid_minutes is None or observable_minutes is None or observable_minutes <= 0 or invalid_minutes < 0 or invalid_minutes > observable_minutes:
        return _unknown(metric_id, bundle, unit_id, observations, "Complete invalid and observable minute totals are required.", coverage=coverage, freshness=freshness, components={"interval_count": len(durations)})
    value = invalid_minutes / observable_minutes * 100.0
    band = "Pass" if value <= 1.0 else "Concern" if value <= 5.0 else "Fail"
    components: dict[str, Any] = {"invalid_interval_count": len(durations)}
    if durations:
        ordered = sorted(durations)
        components["median_interval_minutes"] = statistics.median(ordered)
        components["p95_interval_minutes"] = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return _base_result(metric_id, bundle, unit_id, observations, state="measured", band=band, value=round(value, 4), unit="percent", numerator=invalid_minutes, denominator=observable_minutes, components=components, sample_size=len(durations), coverage=coverage, freshness=freshness)


def _release_traceability_truth(row: Mapping[str, Any]) -> bool | None:
    explicit = _bool_field(row, "traceable", "release_traceable", "satisfied")
    if explicit is not None:
        return explicit
    source = row.get("source_sha") or row.get("source_revision")
    immutable_source = isinstance(source, str) and bool(source)
    reachable = _bool_field(row, "source_reachable_from_main", "reachable_from_main", "is_ancestor")
    artifact = _bool_field(row, "immutable_artifact_identity", "artifact_immutable", "stable_digest")
    if artifact is None:
        digest = row.get("artifact_digest") or row.get("digest")
        artifact = True if isinstance(digest, str) and bool(digest) else None
    if reachable is None or artifact is None or not immutable_source:
        return None
    return reachable and artifact


def _release_traceability(bundle: ObservationBundle, unit_id: str | None, current: MetricResult) -> MetricResult:
    metric_id = "M-SPI-02"
    observations, rows, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    if any(_norm_name(item.name) == "refs_releases" for item in observations):
        rows = [row for row in rows if row.get("tag_name") or row.get("release_id") or row.get("role") == "release"]
    if not rows:
        no_events = _data_flag(observations, "no_events", "no_releases") is True
        if no_events:
            return _base_result(metric_id, bundle, unit_id, observations, state="no_events", band=current.band, value=None, unit="percent", components={"current_metric_state": current.state}, sample_size=0, sample_class="No Events", coverage=coverage, freshness=freshness, assurance=current.assurance, carried_band_from="M-SPI-02S")
        return _unknown(metric_id, bundle, unit_id, observations, "No eligible release population or explicit No Events observation was supplied.", coverage=coverage, freshness=freshness)
    truths = [_release_traceability_truth(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    if conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Historical release source ancestry or artifact identity is unresolved.", coverage=coverage, freshness=freshness, components={"releases": len(rows)}, conflicts=conflicts)
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=95.0, coverage=coverage, freshness=freshness)


def _simple_truth_metric(
    metric_id: str,
    bundle: ObservationBundle,
    unit_id: str | None,
    truth: Callable[[Mapping[str, Any]], bool | None],
    *,
    concern_floor: float,
    no_concern: bool = False,
    row_keys: Sequence[str] = (),
) -> MetricResult:
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, row_keys), unit_id, bundle.units)
    if not rows:
        return _unknown(metric_id, bundle, unit_id, observations, "No eligible observations were supplied.", coverage=coverage, freshness=freshness)
    truths = [truth(row) for row in rows]
    conflicts = _truth_conflicts(rows, truths)
    if conflicts or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "One or more eligible observations cannot be classified from complete evidence.", coverage=coverage, freshness=freshness, components={"eligible": len(rows), "classified": sum(value is not None for value in truths)}, conflicts=conflicts)
    sample_class = "Low Sample" if len(rows) < 5 else "Standard"
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=concern_floor, no_concern=no_concern, coverage=coverage, freshness=freshness, sample_class=sample_class)


def _build_replay_truth(row: Mapping[str, Any]) -> bool | None:
    eligible = _bool_field(row, "eligible", "authoritative_replay")
    if eligible is False:
        return None
    clean = _bool_field(row, "clean_checkout", "clean")
    noninteractive = _bool_field(row, "non_interactive", "noninteractive")
    declared = _bool_field(row, "declared_inputs", "inputs_declared")
    success = _bool_field(row, "successful", "success", "satisfied")
    if success is None and isinstance(row.get("conclusion"), str):
        conclusion = row["conclusion"].lower()
        success = True if conclusion in SUCCESS_CONCLUSIONS else False if conclusion in FAILURE_CONCLUSIONS else None
    if any(value is None for value in (clean, noninteractive, declared, success)):
        return None
    return bool(clean and noninteractive and declared and success)


def _build_replays(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-BTC-01"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("replays", "workflow_runs")), unit_id, bundle.units)
    rows = [row for row in rows if row.get("eligible") is not False]
    # The metric selects at most ten latest replays, preferring distinct Main
    # SHAs.  Normalized rows can provide ``completed_at`` for ordering.
    rows.sort(key=lambda row: str(row.get("completed_at") or row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    selected: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for row in rows:
        sha = row.get("main_sha") or row.get("head_sha") or row.get("sha")
        if isinstance(sha, str) and sha:
            if sha in seen_sha:
                duplicates.append(row)
                continue
            seen_sha.add(sha)
        selected.append(row)
        if len(selected) == 10:
            break
    for row in duplicates:
        if len(selected) == 10:
            break
        selected.append(row)
    if not selected:
        return _unknown(metric_id, bundle, unit_id, observations, "No clean authoritative replay was observed.", coverage=coverage, freshness=freshness)
    truths = [_build_replay_truth(row) for row in selected]
    if any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Replay cleanliness, input declaration, authority, or terminal result is unresolved.", coverage=coverage, freshness=freshness, components={"selected_replays": len(selected)})
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=90.0, coverage=coverage, freshness=freshness, sample_class="Low Sample" if len(selected) < 5 else "Standard", components={"selected_distinct_shas": len(seen_sha)})


def _per_change_ci_truth(row: Mapping[str, Any]) -> bool | None:
    explicit = _bool_field(row, "all_applicable_workflows_triggered", "automatically_triggered", "satisfied")
    if explicit is not None:
        return explicit
    automatic = _bool_field(row, "automatic")
    applicable_complete = _bool_field(row, "applicable_workflows_complete", "workflow_classification_complete")
    final_revision = _bool_field(row, "final_revision_linked", "exact_final_revision")
    if any(value is None for value in (automatic, applicable_complete, final_revision)):
        return None
    return bool(automatic and applicable_complete and final_revision)


def _per_change_ci(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-BTC-02"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("changes",)), unit_id, bundle.units)
    rows = [
        row
        for row in rows
        if not (
            row.get("applicable") is False
            and row.get("n_a_approved") is True
        )
    ]
    if not rows:
        enforcement = _data_flag(observations, "current_trigger_enforcement", "current_enforcement")
        if enforcement is True:
            return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Pass", value=100.0, unit="percent", numerator=0, denominator=0, components={"no_changes": True, "current_enforcement": True}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
        return _unknown(metric_id, bundle, unit_id, observations, "No-change evaluation requires demonstrably enforced automatic triggering.", coverage=coverage, freshness=freshness)
    truths = [_per_change_ci_truth(row) for row in rows]
    if any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Final-revision workflow applicability or trigger linkage is unresolved.", coverage=coverage, freshness=freshness, components={"changes": len(rows)})
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=95.0, coverage=coverage, freshness=freshness, sample_class="Low Sample" if len(rows) < 5 else "Standard")


def _category_truth(row: Mapping[str, Any]) -> bool | None:
    mapped = _bool_field(row, "mapping_complete", "classified")
    if mapped is False:
        return None
    return _bool_field(row, "successful", "satisfied", "passed")


def _validation_categories(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-BTC-03"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("category_pairs",)), unit_id, bundle.units)
    rows = [
        row
        for row in rows
        if not (
            row.get("applicable") is False
            and row.get("n_a_approved") is True
        )
    ]
    if not rows:
        return _unknown(metric_id, bundle, unit_id, observations, "No required change-category population was supplied.", coverage=coverage, freshness=freshness)
    truths = [_category_truth(row) for row in rows]
    if any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Change classification or validation-matrix mapping is unresolved.", coverage=coverage, freshness=freshness, components={"category_pairs": len(rows)})
    skipped_critical = any(row.get("critical") is True and value is False for row, value in zip(rows, truths))
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], concern_floor=95.0, coverage=coverage, freshness=freshness, sample_class="Low Sample" if len(rows) < 5 else "Standard", force_fail=skipped_critical, components={"critical_category_failed": skipped_critical})


def _feedback_latency(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-BTC-04"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("latencies", "revisions")), unit_id, bundle.units)
    rows = [
        row
        for row in rows
        if row.get("eligible") is not False
        and str(row.get("proposal_status") or "").lower() not in {"cancelled", "canceled", "abandoned"}
    ]
    if rows and any(row.get("completed_at") or row.get("terminal_at") for row in rows):
        rows.sort(
            key=lambda row: str(row.get("completed_at") or row.get("terminal_at") or row.get("created_at") or ""),
            reverse=True,
        )
        rows = rows[:30]
    latencies: list[float] = []
    for row in rows:
        value = row.get("latency_minutes")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            return _unknown(metric_id, bundle, unit_id, observations, "Every selected revision requires a comparable nonnegative feedback latency.", coverage=coverage, freshness=freshness, components={"eligible_revisions": len(rows)})
        latencies.append(float(value))
    if not latencies:
        return _unknown(metric_id, bundle, unit_id, observations, "No eligible final-revision latency was observed.", coverage=coverage, freshness=freshness)
    latencies = latencies[:30]
    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    median = statistics.median(ordered)
    slo_values = [item.data.get("slo_minutes") for item in observations if isinstance(item.data, Mapping) and isinstance(item.data.get("slo_minutes"), (int, float))]
    if slo_values and len(set(float(value) for value in slo_values)) > 1:
        return _unknown(metric_id, bundle, unit_id, observations, "Conflicting feedback SLOs were supplied.", coverage=coverage, freshness=freshness, conflicts=["Multiple SLO values apply to the selected sample."])
    slo = float(slo_values[0]) if slo_values else 30.0
    if slo <= 0:
        return _unknown(metric_id, bundle, unit_id, observations, "Feedback SLO must be positive.", coverage=coverage, freshness=freshness)
    band = "Pass" if p95 <= slo else "Concern" if p95 <= 2 * slo else "Fail"
    return _base_result(metric_id, bundle, unit_id, observations, state="measured", band=band, value=round(p95, 4), unit="minutes", components={"median_minutes": round(median, 4), "p95_minutes": round(p95, 4), "slo_minutes": slo}, sample_size=len(ordered), sample_class="Low Sample" if len(ordered) < 5 else "Standard", coverage=coverage, freshness=freshness)


def _flaky_reruns(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-BTC-05"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("rerun_groups",)), unit_id, bundle.units)
    retry_capture = _data_flag(observations, "retry_capture_enabled", "rerun_capture_complete")
    if not rows:
        if retry_capture is True:
            return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Pass", value=0.0, unit="percent", numerator=0, denominator=0, components={"zero_reruns": True, "retry_capture_enabled": True}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
        return _unknown(metric_id, bundle, unit_id, observations, "Zero reruns can be measured only when retry capture is enabled and complete.", coverage=coverage, freshness=freshness)
    truths: list[bool | None] = []
    comparable_rows: list[dict[str, Any]] = []
    for row in rows:
        comparable = _bool_field(row, "comparable", "material_inputs_identical")
        changed = _bool_field(row, "outcome_changed", "flaky")
        if comparable is False:
            continue
        comparable_rows.append(row)
        if comparable is None or changed is None:
            truths.append(None)
        else:
            truths.append(changed)
    if retry_capture is not True or any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Comparable rerun identity or complete retry capture is unresolved.", coverage=coverage, freshness=freshness, components={"rerun_groups": len(rows), "comparable_groups": len(comparable_rows)})
    if not comparable_rows:
        return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Pass", value=0.0, unit="percent", numerator=0, denominator=0, components={"rerun_groups": len(rows), "comparable_groups": 0, "retry_capture_enabled": True}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
    numerator = sum(bool(value) for value in truths)
    denominator = len(truths)
    value = numerator / denominator * 100.0
    band = "Pass" if value <= 1.0 else "Concern" if value <= 3.0 else "Fail"
    return _base_result(metric_id, bundle, unit_id, observations, state="measured", band=band, value=round(value, 4), unit="percent", numerator=numerator, denominator=denominator, sample_size=denominator, sample_class="Low Sample" if denominator < 5 else "Standard", coverage=coverage, freshness=freshness)


def _required_check_enforcement(bundle: ObservationBundle, unit_id: str | None) -> MetricResult:
    metric_id = "M-CGD-04"
    observations, _, coverage, freshness, blocked = _prepare(metric_id, bundle, unit_id)
    if blocked:
        return blocked
    rows = _unit_rows(_observation_rows(observations, ("changes",)), unit_id, bundle.units)
    rows = [row for row in rows if row.get("accepted") is not False]
    if not rows:
        tested = _data_flag(observations, "tested_enforcement", "current_enforcement_tested")
        if tested is True:
            return _base_result(metric_id, bundle, unit_id, observations, state="measured", band="Pass", value=100.0, unit="percent", numerator=0, denominator=0, components={"no_changes": True, "tested_enforcement": True}, sample_size=0, sample_class="Low Sample", coverage=coverage, freshness=freshness)
        return _unknown(metric_id, bundle, unit_id, observations, "No-change evaluation requires tested required-check enforcement.", coverage=coverage, freshness=freshness)
    truths = [_bool_field(row, "blocked_until_final_checks_succeeded", "enforced", "satisfied") for row in rows]
    if any(value is None for value in truths):
        return _unknown(metric_id, bundle, unit_id, observations, "Final-revision source-control enforcement is unresolved for an accepted change.", coverage=coverage, freshness=freshness, components={"accepted_changes": len(rows)})
    return _percent_result(metric_id, bundle, unit_id, observations, [bool(value) for value in truths], no_concern=True, coverage=coverage, freshness=freshness, sample_class="Low Sample" if len(rows) < 5 else "Standard")


def _calculate_unit_metrics(bundle: ObservationBundle, unit_id: str | None) -> dict[str, MetricResult]:
    results: dict[str, MetricResult] = {}
    if bundle.schema_version != OBSERVATION_SCHEMA_VERSION:
        reason = f"Unsupported or missing observation schema: {bundle.schema_version!r}."
        for metric_id in METRIC_IDS:
            results[metric_id] = _unknown(metric_id, bundle, unit_id, (), reason)
        return results
    if not bundle.repository or not bundle.subject_sha:
        missing = "repository identity" if not bundle.repository else "assessed Main SHA"
        for metric_id in METRIC_IDS:
            results[metric_id] = _unknown(metric_id, bundle, unit_id, (), f"The bundle is missing its {missing}.")
        return results

    results["M-SPI-01"] = _main_validity(bundle, unit_id)
    results["M-SPI-02S"] = _current_traceability(bundle, unit_id)
    results["M-SPI-03"] = _release_identity(bundle, unit_id)
    results["M-SPI-04"] = _correspondence(bundle, unit_id, results["M-SPI-02S"])
    results["M-CGD-01"] = _audited_changes(bundle, unit_id)
    results["M-CGD-02"] = _critical_refs(bundle, unit_id)
    results["M-SPI-01T"] = _main_invalid_trend(bundle, unit_id, results["M-SPI-01"])
    results["M-SPI-02"] = _release_traceability(bundle, unit_id, results["M-SPI-02S"])
    results["M-BTC-01"] = _build_replays(bundle, unit_id)
    results["M-BTC-02"] = _per_change_ci(bundle, unit_id)
    results["M-BTC-03"] = _validation_categories(bundle, unit_id)
    results["M-BTC-04"] = _feedback_latency(bundle, unit_id)
    results["M-BTC-05"] = _flaky_reruns(bundle, unit_id)
    results["M-CGD-04"] = _required_check_enforcement(bundle, unit_id)
    return results


def _aggregate_metric(metric_id: str, bundle: ObservationBundle, unit_results: Sequence[MetricResult]) -> MetricResult:
    if not unit_results:
        return _unknown(metric_id, bundle, None, (), "No applicable unit was available for repository aggregation.")
    components = {"per_unit": {str(result.unit_id): result.to_dict() for result in unit_results}}
    coverage = {
        "complete": all(result.coverage.get("complete") is True for result in unit_results),
        "applicable_units": len(unit_results),
        "complete_units": sum(result.coverage.get("complete") is True for result in unit_results),
    }
    freshness = {
        "fresh": all(result.freshness.get("fresh") is True for result in unit_results),
        "fresh_units": sum(result.freshness.get("fresh") is True for result in unit_results),
        "applicable_units": len(unit_results),
    }
    observations: list[Observation] = []
    evidence_ids = list(dict.fromkeys(item for result in unit_results for item in result.evidence_ids))
    observation_ids = list(dict.fromkeys(item for result in unit_results for item in result.observation_ids))
    source_codes = list(dict.fromkeys(item for result in unit_results for item in result.source_codes))
    limitations = list(dict.fromkeys(item for result in unit_results for item in result.limitations))
    conflicts = list(dict.fromkeys(item for result in unit_results for item in result.conflicts))
    exceptions = [item for result in unit_results for item in result.exceptions]
    assurance = min((result.assurance for result in unit_results), key=ASSURANCE_ORDER.__getitem__)

    # Unknown dominates a known failure because the stated repository rule is
    # that any applicable Unknown unit makes the repository metric Unknown.
    if any(result.state == "unknown" for result in unit_results):
        aggregate = _base_result(metric_id, bundle, None, observations, state="unknown", components=components, coverage=coverage, freshness=freshness, assurance="E0", limitations=["At least one applicable unit is Unknown.", *limitations], conflicts=conflicts)
    else:
        applicable = [result for result in unit_results if result.state != "n_a"]
        if not applicable:
            aggregate = _base_result(metric_id, bundle, None, observations, state="n_a", components=components, sample_class="Evidence-backed N/A", coverage=coverage, freshness=freshness, assurance=assurance, limitations=limitations, conflicts=conflicts)
        elif all(result.state == "no_events" for result in applicable):
            bands = [result.band for result in applicable if result.band]
            band = max(bands, key=BAND_ORDER.__getitem__) if bands else None
            sources = list(dict.fromkeys(result.carried_band_from for result in applicable if result.carried_band_from))
            aggregate = _base_result(metric_id, bundle, None, observations, state="no_events", band=band, components=components, sample_size=0, sample_class="No Events", coverage=coverage, freshness=freshness, assurance=assurance, carried_band_from=sources[0] if len(sources) == 1 else "multiple-current-metrics" if sources else None, limitations=limitations, conflicts=conflicts)
        else:
            bands = [result.band for result in applicable if result.band]
            band = max(bands, key=BAND_ORDER.__getitem__) if bands else None
            denominators = [result.denominator for result in applicable if isinstance(result.denominator, (int, float))]
            numerators = [result.numerator for result in applicable if isinstance(result.numerator, (int, float))]
            denominator = sum(denominators) if denominators else None
            numerator = sum(numerators) if numerators else None
            if metric_id == "M-SPI-01":
                value: float | int | None = 1 if band == "Pass" else 0
                numerator, denominator = value, 1
            elif metric_id == "M-BTC-04":
                values = [float(result.value) for result in applicable if isinstance(result.value, (int, float))]
                value = max(values) if values else None
                numerator = denominator = None
            elif denominator not in {None, 0} and numerator is not None:
                value = round(numerator / denominator * 100.0, 4)
            else:
                values = [float(result.value) for result in applicable if isinstance(result.value, (int, float))]
                value = min(values) if values else None
            aggregate = _base_result(metric_id, bundle, None, observations, state="measured", band=band, value=value, unit=applicable[0].unit, numerator=numerator, denominator=denominator, components=components, sample_size=sum(result.sample_size for result in applicable), sample_class="Low Sample" if any(result.sample_class == "Low Sample" for result in applicable) else "Standard", coverage=coverage, freshness=freshness, assurance=assurance, limitations=limitations, conflicts=conflicts)

    aggregate.evidence_ids = evidence_ids
    aggregate.observation_ids = observation_ids
    aggregate.source_codes = source_codes
    aggregate.exceptions = exceptions
    return aggregate


def calculate_metric_results(
    raw_bundle: ObservationBundle | Mapping[str, Any],
    *,
    include_unit_results: bool = False,
) -> list[MetricResult]:
    """Calculate all supported metrics from one normalized observation bundle.

    By default this returns one repository-level result per metric.  Passing
    ``include_unit_results=True`` appends the unit-level records after the
    repository records.  Repository aggregation is logical/worst-unit for
    bands and is always Unknown when any applicable unit is Unknown.
    """

    bundle = _as_bundle(raw_bundle)
    units = list(bundle.units)
    if not units:
        units = [None]
    unit_maps = [(unit_id, _calculate_unit_metrics(bundle, unit_id)) for unit_id in units]

    repository_results: list[MetricResult] = []
    for metric_id in METRIC_IDS:
        results = [mapping[metric_id] for _, mapping in unit_maps]
        if units == [None]:
            repository_results.append(results[0])
        else:
            repository_results.append(_aggregate_metric(metric_id, bundle, results))

    if not include_unit_results or units == [None]:
        return repository_results
    return [*repository_results, *(mapping[metric_id] for _, mapping in unit_maps for metric_id in METRIC_IDS)]


def calculate_metrics(
    raw_bundle: ObservationBundle | Mapping[str, Any],
    *,
    include_unit_results: bool = False,
) -> list[dict[str, Any]]:
    """JSON-ready wrapper around :func:`calculate_metric_results`."""

    return [result.to_dict() for result in calculate_metric_results(raw_bundle, include_unit_results=include_unit_results)]


def gate_results(results: Sequence[MetricResult | Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map only the four foundational current metrics to their gates."""

    by_metric: dict[str, MetricResult | Mapping[str, Any]] = {}
    for result in results:
        metric_id = result.metric_id if isinstance(result, MetricResult) else result.get("metric_id")
        unit_id = result.unit_id if isinstance(result, MetricResult) else result.get("unit_id")
        if isinstance(metric_id, str) and unit_id is None:
            by_metric[metric_id] = result

    gates: dict[str, dict[str, Any]] = {}
    for gate_id, metric_id in GATE_METRICS.items():
        result = by_metric.get(metric_id)
        if result is None:
            gates[gate_id] = {"metric_id": metric_id, "status": "Unknown", "reason": "Repository-level metric result is missing."}
            continue
        state = result.state if isinstance(result, MetricResult) else result.get("state")
        band = result.band if isinstance(result, MetricResult) else result.get("band")
        assurance = result.assurance if isinstance(result, MetricResult) else result.get("assurance")
        if state == "n_a":
            status = "N/A"
        elif state != "measured" or band is None:
            status = "Unknown"
        elif band == "Pass" and ASSURANCE_ORDER.get(str(assurance), 0) >= ASSURANCE_ORDER["E3"]:
            status = "Pass"
        elif band == "Pass":
            status = "Unknown"
        else:
            status = "Fail"
        gates[gate_id] = {"metric_id": metric_id, "status": status, "band": band, "state": state, "assurance": assurance}
    return gates


# A descriptive alias for callers that think in terms of evaluating a bundle.
evaluate_observations = calculate_metrics


__all__ = [
    "METRIC_IDS",
    "CURRENT_METRICS",
    "HISTORY_METRICS",
    "GATE_METRICS",
    "calculate_metric_results",
    "calculate_metrics",
    "evaluate_observations",
    "gate_results",
    "METRIC_SCHEMA_VERSION",
    "METRIC_VERSION",
]

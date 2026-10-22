"""Normalized observation and metric-result contracts.

The collectors deliberately retain partial responses for diagnosis.  The
measurement layer, however, only treats an observation as usable when both the
observation and its eligible population are explicitly complete.  These small
models keep that boundary visible without adding a third-party dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


OBSERVATION_SCHEMA_VERSION = "RH-GITHUB-OBSERVATIONS-1.0"
METRIC_SCHEMA_VERSION = "RH-METRIC-RESULT-1.0"
METRIC_VERSION = "RH-METRICS-0.1"
THRESHOLD_VERSION = "RH-THRESHOLDS-0.1"

METRIC_STATES = frozenset({"measured", "unknown", "no_events", "n_a"})
METRIC_BANDS = frozenset({"Pass", "Concern", "Fail"})
ASSURANCE_LEVELS = frozenset({"E0", "E1", "E2", "E3", "E4"})


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class Observation:
    """One normalized collector group.

    ``data`` is intentionally metric-specific.  Everything around it describes
    whether the data is safe to use: source identity, exact subject revision,
    completeness, pagination, gaps, and evidence identity.
    """

    name: str
    evidence_id: str | None
    observed_at: str | None
    source: str | None
    subject_sha: str | None
    unit_id: str | None
    state: str
    completeness: str
    complete: bool
    population_complete: bool
    data: Any
    gaps: tuple[dict[str, Any], ...] = ()
    request: dict[str, Any] = field(default_factory=dict)
    assurance: str | None = None
    evidence_ids: tuple[str, ...] = ()
    observation_id: str | None = None
    source_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    exceptions: tuple[Any, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Return whether this observation can contribute to a passing metric."""

        request_complete = self.request.get("complete", True) is not False
        request_population = self.request.get("population_complete", True) is not False
        not_truncated = self.request.get("truncated", False) is not True
        return (
            self.state == "observed"
            and self.completeness == "complete"
            and self.complete
            and self.population_complete
            and bool(self.evidence_id)
            and bool(self.source)
            and request_complete
            and request_population
            and not_truncated
            and not self.gaps
            and not self.conflicts
        )

    @classmethod
    def from_mapping(
        cls,
        name: str,
        raw: Mapping[str, Any],
        *,
        default_subject_sha: str | None = None,
        default_unit_id: str | None = None,
    ) -> "Observation":
        evidence_id = raw.get("evidence_id")
        observation_id = raw.get("observation_id") or evidence_id
        evidence_ids = _string_list(raw.get("evidence_ids"))
        if isinstance(evidence_id, str) and evidence_id and evidence_id not in evidence_ids:
            evidence_ids.insert(0, evidence_id)
        source = raw.get("source")
        source_codes = _string_list(raw.get("source_codes"))
        if isinstance(source, str) and source and source not in source_codes:
            source_codes.insert(0, source)

        gaps_raw = raw.get("gaps", [])
        gaps = tuple(_mapping(item) for item in gaps_raw if isinstance(item, Mapping)) if isinstance(gaps_raw, list) else ()
        conflicts = _string_list(raw.get("conflicts"))
        for gap in gaps:
            if str(gap.get("kind", "")).lower() == "conflict":
                conflicts.append(str(gap.get("message") or "Conflicting observation evidence."))

        complete = raw.get("complete") is True
        population_complete = raw.get("population_complete") is True
        completeness = str(raw.get("completeness") or ("complete" if complete else "unknown")).lower()
        state = str(raw.get("state") or "unknown").lower()

        return cls(
            name=name,
            evidence_id=evidence_id if isinstance(evidence_id, str) else None,
            observed_at=raw.get("observed_at") if isinstance(raw.get("observed_at"), str) else None,
            source=source if isinstance(source, str) else None,
            subject_sha=(raw.get("subject_sha") if isinstance(raw.get("subject_sha"), str) else default_subject_sha),
            unit_id=(
                raw.get("unit_id")
                if isinstance(raw.get("unit_id"), str)
                else raw.get("unit")
                if isinstance(raw.get("unit"), str)
                else default_unit_id
            ),
            state=state,
            completeness=completeness,
            complete=complete,
            population_complete=population_complete,
            data=raw.get("data"),
            gaps=gaps,
            request=_mapping(raw.get("request")),
            assurance=raw.get("assurance") if raw.get("assurance") in ASSURANCE_LEVELS else None,
            evidence_ids=tuple(evidence_ids),
            observation_id=observation_id if isinstance(observation_id, str) else None,
            source_codes=tuple(source_codes),
            limitations=tuple(_string_list(raw.get("limitations"))),
            conflicts=tuple(dict.fromkeys(conflicts)),
            exceptions=tuple(raw.get("exceptions", [])) if isinstance(raw.get("exceptions"), list) else (),
            coverage=_mapping(raw.get("coverage")),
            freshness=_mapping(raw.get("freshness")),
        )


@dataclass(frozen=True)
class ObservationBundle:
    """Defensively parsed normalized observation bundle."""

    schema_version: str | None
    observed_at: str | None
    repository: str | None
    subject_sha: str | None
    unit_id: str | None
    units: tuple[str, ...]
    complete: bool
    population_complete: bool
    observations: tuple[Observation, ...]
    gaps: tuple[dict[str, Any], ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    exceptions: tuple[Any, ...] = ()

    @property
    def usable(self) -> bool:
        return self.complete and self.population_complete and not self.gaps and not self.conflicts

    def for_metric(self, metric_id: str, aliases: tuple[str, ...] = ()) -> list[Observation]:
        names = {metric_id, metric_id.lower(), *aliases}
        normalized = {name.lower().replace("-", "_") for name in names}
        return [
            item
            for item in self.observations
            if item.name in names or item.name.lower().replace("-", "_") in normalized
        ]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ObservationBundle":
        subject_sha = raw.get("subject_sha") or raw.get("main_sha")
        subject_sha = subject_sha if isinstance(subject_sha, str) else None
        default_unit = raw.get("unit") or raw.get("unit_id")
        default_unit = default_unit if isinstance(default_unit, str) else None

        units: list[str] = []
        units_raw = raw.get("units") or raw.get("applicable_units")
        if isinstance(units_raw, list):
            for item in units_raw:
                if isinstance(item, str) and item:
                    units.append(item)
                elif isinstance(item, Mapping):
                    candidate = item.get("unit_id") or item.get("unit")
                    if isinstance(candidate, str) and candidate:
                        units.append(candidate)
        if default_unit and default_unit not in units:
            units.append(default_unit)

        observations: list[Observation] = []
        observations_raw = raw.get("observations", {})
        if isinstance(observations_raw, Mapping):
            for name, value in observations_raw.items():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, Mapping):
                        observations.append(
                            Observation.from_mapping(
                                str(name), item, default_subject_sha=subject_sha, default_unit_id=default_unit
                            )
                        )
        elif isinstance(observations_raw, list):
            for index, item in enumerate(observations_raw):
                if not isinstance(item, Mapping):
                    continue
                name = item.get("metric_id") or item.get("name") or item.get("kind") or f"observation_{index}"
                observations.append(
                    Observation.from_mapping(
                        str(name), item, default_subject_sha=subject_sha, default_unit_id=default_unit
                    )
                )

        # A metric-keyed convenience map is accepted as an alias for
        # ``observations``.  The canonical collector still emits the latter.
        metrics_raw = raw.get("metrics")
        if isinstance(metrics_raw, Mapping):
            for name, value in metrics_raw.items():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, Mapping):
                        observations.append(
                            Observation.from_mapping(
                                str(name), item, default_subject_sha=subject_sha, default_unit_id=default_unit
                            )
                        )

        for item in observations:
            if item.unit_id and item.unit_id not in units:
                units.append(item.unit_id)

        gaps_raw = raw.get("gaps", [])
        gaps = tuple(_mapping(item) for item in gaps_raw if isinstance(item, Mapping)) if isinstance(gaps_raw, list) else ()
        conflicts = _string_list(raw.get("conflicts"))
        for gap in gaps:
            if str(gap.get("kind", "")).lower() == "conflict":
                conflicts.append(str(gap.get("message") or "Conflicting bundle evidence."))

        return cls(
            schema_version=raw.get("schema_version") if isinstance(raw.get("schema_version"), str) else None,
            observed_at=raw.get("observed_at") if isinstance(raw.get("observed_at"), str) else None,
            repository=raw.get("repository") if isinstance(raw.get("repository"), str) else None,
            subject_sha=subject_sha,
            unit_id=default_unit,
            units=tuple(dict.fromkeys(units)),
            complete=raw.get("complete") is True,
            population_complete=raw.get("population_complete") is True,
            observations=tuple(observations),
            gaps=gaps,
            coverage=_mapping(raw.get("coverage")),
            freshness=_mapping(raw.get("freshness")),
            conflicts=tuple(dict.fromkeys(conflicts)),
            limitations=tuple(_string_list(raw.get("limitations"))),
            exceptions=tuple(raw.get("exceptions", [])) if isinstance(raw.get("exceptions"), list) else (),
        )


@dataclass
class MetricResult:
    """Stable ``RH-METRIC-RESULT-1.0`` exchange record."""

    metric_id: str
    repository: str | None
    unit_id: str | None
    main_sha: str | None
    state: str = "unknown"
    band: str | None = None
    value: float | int | bool | None = None
    unit: str | None = None
    numerator: float | int | None = None
    denominator: float | int | None = None
    components: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    sample_class: str = "Unknown"
    window: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    assurance: str = "E0"
    evidence_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    source_codes: list[str] = field(default_factory=list)
    threshold_version: str = THRESHOLD_VERSION
    carried_band_from: str | None = None
    limitations: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    exceptions: list[Any] = field(default_factory=list)
    schema_version: str = METRIC_SCHEMA_VERSION
    metric_version: str = METRIC_VERSION

    def __post_init__(self) -> None:
        if self.state not in METRIC_STATES:
            raise ValueError(f"Invalid metric state: {self.state}")
        if self.band is not None and self.band not in METRIC_BANDS:
            raise ValueError(f"Invalid metric band: {self.band}")
        if self.assurance not in ASSURANCE_LEVELS:
            raise ValueError(f"Invalid assurance level: {self.assurance}")
        if self.state == "measured" and self.band is None:
            raise ValueError("A measured metric must carry a conformance band")
        if self.state in {"unknown", "n_a"} and self.band is not None:
            raise ValueError(f"{self.state} metrics cannot carry a conformance band")
        if self.state == "no_events" and self.band is not None and not self.carried_band_from:
            raise ValueError("A No Events band must identify the current metric it carries")

    def to_dict(self) -> dict[str, Any]:
        """Return the exact stable JSON-serializable field contract."""

        return {
            "schema_version": self.schema_version,
            "metric_version": self.metric_version,
            "metric_id": self.metric_id,
            "repository": self.repository,
            "unit_id": self.unit_id,
            "main_sha": self.main_sha,
            "state": self.state,
            "band": self.band,
            "value": self.value,
            "unit": self.unit,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "components": self.components,
            "sample_size": self.sample_size,
            "sample_class": self.sample_class,
            "window": self.window,
            "coverage": self.coverage,
            "freshness": self.freshness,
            "assurance": self.assurance,
            "evidence_ids": self.evidence_ids,
            "observation_ids": self.observation_ids,
            "source_codes": self.source_codes,
            "threshold_version": self.threshold_version,
            "carried_band_from": self.carried_band_from,
            "limitations": self.limitations,
            "conflicts": self.conflicts,
            "exceptions": self.exceptions,
        }

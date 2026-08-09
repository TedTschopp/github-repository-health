"""Load and validate repository-specific TOML assessment configuration."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import tomllib
from typing import Any


RISK_TIERS = {"Baseline", "Elevated", "Critical"}
LIFECYCLES = {
    "Active",
    "Stable-supported",
    "Experimental",
    "Mirrored",
    "Archived",
    "Retired",
    "Unknown",
}
REPOSITORY_TYPES = {
    "Deployable application",
    "Library/package",
    "Monorepo",
    "Infrastructure-as-code/GitOps",
    "Data/analytics/model",
    "Documentation/content",
    "Template/scaffold",
    "Sandbox/experimental",
    "Mirror/fork",
    "Archived/retired",
    "Unknown",
}
CONFORMANCE = {"Met", "Partially met", "Unmet", "Unknown", "N/A"}
ASSURANCE = {"E0", "E1", "E2", "E3", "E4"}
METHODOLOGIES = {
    "Trunk-based",
    "GitHub Flow/short-lived feature branches",
    "GitFlow",
    "Environment-branch flow",
    "Release train/multi-version maintenance",
    "GitOps promotion",
    "Fork/integration-manager",
    "Direct gated trunk",
    "Custom/hybrid",
    "Unknown",
    "Unclassified",
}
METHODOLOGY_CONFIDENCE = {"High", "Moderate", "Low"}
METHODOLOGY_AXES = (
    "canonical_integration_topology",
    "change_ingress",
    "branch_purpose_and_lifetime",
    "integration_cadence",
    "release_source",
    "promotion_mechanism",
    "parallel_support",
    "control_placement",
    "repository_topology",
)
PRODUCTION_CORRESPONDENCE = {"Unknown", "Exact-Main", "Releasable-Main", "Production-Ref", "Per-unit combination", "N/A"}
DORA_METRICS = {
    "change_lead_time",
    "deployment_frequency",
    "failed_deployment_recovery_time",
    "change_fail_rate",
    "deployment_rework_rate",
}
TRI_STATE_KEYS = (
    "has_current_output",
    "publishes_artifacts",
    "has_dependencies",
    "has_automation",
    "has_proposed_change_validation",
    "multi_contributor",
    "supported",
    "has_critical_paths",
    "has_produced_artifacts",
    "automated_deployment",
    "operated_service",
    "portfolio_managed",
    "has_work_refs",
)
TOP_LEVEL_KEYS = {"standard", "repository", "assessment", "methodology_axes", "controls", "dora", "exceptions"}
CONTROL_OVERRIDE_KEYS = {
    "conformance",
    "assurance",
    "rationale",
    "evidence_ids",
    "evidence_location",
    "population_coverage",
    "freshness_days",
    "collector",
    "gate_status",
    "gate_rationale",
    "n_a_approved_by",
    "n_a_approved_at",
    "n_a_review_date",
    "decision_id",
    "scope",
    "risk_owner",
    "compensating_control",
    "status",
}
DORA_KEYS = {"available", "reason", "service", "period_start", "period_end", "evidence_ids", "context", "limitations", "metrics"}
DORA_METRIC_KEYS = {"value", "unit", "source", "coverage", "limitations", "formula"}


DEFAULT_CONFIG: dict[str, Any] = {
    "standard": {"version": "0.1.0-draft"},
    "repository": {
        "type": "Unknown",
        "lifecycle": "Active",
        "risk_tier": "Baseline",
        "main_branch": "",
        "owner": "",
        "methodology": "Unclassified",
        "observed_methodology": "Unclassified",
        "methodology_confidence": "Low",
        "methodology_evidence_ids": [],
        "methodology_contradictions": [],
        "authoritative_checks": [],
        "deployable_units": [],
        "production_correspondence": "Unknown",
        **{key: "unknown" for key in TRI_STATE_KEYS},
    },
    "assessment": {
        "observation_days": 90,
        "low_activity_days": 365,
        "assessor": "repository-health automation",
        "reviewer": "",
        "next_review": "",
    },
    "methodology_axes": {key: "Unknown" for key in METHODOLOGY_AXES},
    "controls": {},
    "exceptions": [],
    "dora": {"available": False, "reason": "No reliable product-level DORA inputs were supplied."},
}


def default_config_path() -> Path:
    return Path(__file__).with_name("config") / "v0.1.toml"


def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate(config: dict[str, Any]) -> None:
    unknown_top = set(config) - TOP_LEVEL_KEYS
    if unknown_top:
        raise ValueError(f"Unknown top-level configuration keys: {', '.join(sorted(unknown_top))}")
    for table in ("standard", "repository", "assessment", "methodology_axes", "controls", "dora"):
        if not isinstance(config.get(table), dict):
            raise ValueError(f"{table} must be a TOML table")
    standard = config["standard"]
    if set(standard) != {"version"} or not isinstance(standard.get("version"), str) or not standard["version"].strip():
        raise ValueError("standard must contain only one nonempty string field: version")
    repository = config["repository"]
    unknown_repository = set(repository) - set(DEFAULT_CONFIG["repository"])
    if unknown_repository:
        raise ValueError(f"Unknown repository configuration keys: {', '.join(sorted(unknown_repository))}")
    if not isinstance(repository["risk_tier"], str) or repository["risk_tier"] not in RISK_TIERS:
        raise ValueError(f"Invalid repository.risk_tier: {repository['risk_tier']}")
    if not isinstance(repository["lifecycle"], str) or repository["lifecycle"] not in LIFECYCLES:
        raise ValueError(f"Invalid repository.lifecycle: {repository['lifecycle']}")
    if not isinstance(repository["type"], str) or repository["type"] not in REPOSITORY_TYPES:
        raise ValueError(f"Invalid repository.type: {repository['type']}")
    for key in ("main_branch", "owner"):
        if not isinstance(repository.get(key), str):
            raise ValueError(f"repository.{key} must be a string")
    for key in ("methodology", "observed_methodology"):
        if not isinstance(repository.get(key), str) or repository.get(key) not in METHODOLOGIES:
            raise ValueError(f"repository.{key} must be a canonical methodology profile, Unknown, or Unclassified")
    if not isinstance(repository.get("methodology_confidence"), str) or repository.get("methodology_confidence") not in METHODOLOGY_CONFIDENCE:
        raise ValueError("repository.methodology_confidence must be High, Moderate, or Low")
    for key in ("methodology_evidence_ids", "methodology_contradictions"):
        values = repository.get(key, [])
        if not isinstance(values, list) or not all(isinstance(item, str) and item.strip() for item in values):
            raise ValueError(f"repository.{key} must be an array of nonempty strings")
    axes = config.get("methodology_axes", {})
    if not isinstance(axes, dict) or set(axes) - set(METHODOLOGY_AXES):
        raise ValueError("methodology_axes contains unknown canonical axis keys")
    if not all(isinstance(value, str) and value.strip() for value in axes.values()):
        raise ValueError("methodology_axes values must be nonempty strings")
    for key in TRI_STATE_KEYS:
        value = repository.get(key, "unknown")
        if isinstance(value, bool):
            continue
        if str(value).lower() not in {"true", "false", "auto", "unknown"}:
            raise ValueError(f"repository.{key} must be true, false, auto, or unknown")
    checks = repository.get("authoritative_checks", [])
    if not isinstance(checks, list) or not all(isinstance(item, str) and item.strip() for item in checks):
        raise ValueError("repository.authoritative_checks must be an array of nonempty check names")
    units = repository.get("deployable_units", [])
    if not isinstance(units, list) or not all(isinstance(item, str) and item.strip() for item in units):
        raise ValueError("repository.deployable_units must be an array of nonempty unit identifiers")
    if not isinstance(repository.get("production_correspondence"), str) or repository.get("production_correspondence") not in PRODUCTION_CORRESPONDENCE:
        raise ValueError("repository.production_correspondence must be a canonical contract, N/A, or Unknown")
    assessment = config["assessment"]
    unknown_assessment = set(assessment) - set(DEFAULT_CONFIG["assessment"])
    if unknown_assessment:
        raise ValueError(f"Unknown assessment configuration keys: {', '.join(sorted(unknown_assessment))}")
    for key in ("observation_days", "low_activity_days"):
        if isinstance(assessment[key], bool) or not isinstance(assessment[key], int) or assessment[key] <= 0:
            raise ValueError(f"assessment.{key} must be a positive integer")
    if not str(assessment.get("assessor", "")).strip():
        raise ValueError("assessment.assessor is required")
    if assessment.get("next_review"):
        try:
            date.fromisoformat(str(assessment["next_review"]))
        except ValueError as error:
            raise ValueError("assessment.next_review must use ISO 8601 YYYY-MM-DD") from error
    for control_id, override in config.get("controls", {}).items():
        if not isinstance(override, dict):
            raise ValueError(f"controls.{control_id} must be a table")
        unknown_override = set(override) - CONTROL_OVERRIDE_KEYS
        if unknown_override:
            raise ValueError(f"controls.{control_id} contains unknown keys: {', '.join(sorted(unknown_override))}")
        conformance = override.get("conformance")
        assurance = override.get("assurance")
        if conformance not in CONFORMANCE:
            raise ValueError(f"controls.{control_id}.conformance is invalid")
        if assurance not in ASSURANCE:
            raise ValueError(f"controls.{control_id}.assurance is invalid")
        if override.get("gate_status") not in {None, "Pass", "Fail", "Unknown", "N/A"}:
            raise ValueError(f"controls.{control_id}.gate_status is invalid")
        if not str(override.get("rationale", "")).strip():
            raise ValueError(f"controls.{control_id}.rationale is required")
        evidence_ids = override.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids or not all(isinstance(item, str) and item.strip() for item in evidence_ids):
            raise ValueError(f"controls.{control_id}.evidence_ids must contain at least one evidence reference")
        freshness_days = override.get("freshness_days", 0)
        if isinstance(freshness_days, bool) or not isinstance(freshness_days, int) or freshness_days < 0:
            raise ValueError(f"controls.{control_id}.freshness_days must be a nonnegative integer")
        if conformance == "N/A" and not str(override.get("n_a_approved_by", "")).strip():
            raise ValueError(f"controls.{control_id}.n_a_approved_by is required for N/A")
        if conformance == "N/A" and not str(override.get("n_a_approved_at", "")).strip():
            raise ValueError(f"controls.{control_id}.n_a_approved_at is required for N/A")
        if conformance == "N/A" and not str(override.get("n_a_review_date", "")).strip():
            raise ValueError(f"controls.{control_id}.n_a_review_date is required for N/A")
        if conformance == "N/A":
            if assurance == "E0":
                raise ValueError(
                    f"controls.{control_id}.assurance must be E1 or stronger for an evidence-backed N/A determination"
                )
            try:
                approved_at = date.fromisoformat(str(override["n_a_approved_at"]))
                review_date = date.fromisoformat(str(override["n_a_review_date"]))
            except ValueError as error:
                raise ValueError(f"controls.{control_id} N/A dates must use ISO 8601 YYYY-MM-DD") from error
            if review_date < approved_at:
                raise ValueError(f"controls.{control_id}.n_a_review_date must not precede approval")
    decisions = config.get("exceptions", [])
    if not isinstance(decisions, list):
        raise ValueError("exceptions must be an array of tables")
    for index, decision in enumerate(decisions):
        required = {"exception_id", "type", "control_ids", "scope", "risk_owner", "rationale", "approver", "approved_at", "review_date", "status"}
        if not isinstance(decision, dict) or any(not decision.get(key) for key in required):
            raise ValueError(f"exceptions[{index}] is missing required decision fields")
        if decision["type"] not in {"N/A determination", "Equivalent control", "Temporary waiver"}:
            raise ValueError(f"exceptions[{index}].type is invalid")
        if decision["type"] == "Temporary waiver" and not decision.get("expires_at"):
            raise ValueError(f"exceptions[{index}].expires_at is required for Temporary waiver")
        if decision["type"] == "Temporary waiver" and not decision.get("compensating_control"):
            raise ValueError(f"exceptions[{index}].compensating_control is required for Temporary waiver")
        try:
            approved_at = date.fromisoformat(str(decision["approved_at"]))
            date.fromisoformat(str(decision["review_date"]))
            if decision["type"] == "Temporary waiver":
                expires_at = date.fromisoformat(str(decision["expires_at"]))
                duration = (expires_at - approved_at).days
                maximum = 180 if repository["risk_tier"] == "Baseline" else 90
                if duration <= 0 or duration > maximum:
                    raise ValueError(f"exceptions[{index}] duration must be 1 through {maximum} days for {repository['risk_tier']}")
        except ValueError as error:
            if "duration must" in str(error):
                raise
            raise ValueError(f"exceptions[{index}] dates must use ISO 8601 YYYY-MM-DD") from error
    dora = config.get("dora", {})
    unknown_dora = set(dora) - DORA_KEYS
    if unknown_dora:
        raise ValueError(f"Unknown dora configuration keys: {', '.join(sorted(unknown_dora))}")
    if not isinstance(dora.get("available"), bool):
        raise ValueError("dora.available must be true or false")
    if dora.get("available"):
        required = ("service", "period_start", "period_end", "evidence_ids", "context", "limitations")
        if any(not dora.get(key) for key in required):
            raise ValueError("Available DORA input requires service, period_start, period_end, evidence_ids, context, and limitations")
        if not isinstance(dora["evidence_ids"], list) or not all(isinstance(item, str) and item.strip() for item in dora["evidence_ids"]):
            raise ValueError("dora.evidence_ids must be a nonempty array")
        metrics = dora.get("metrics", {})
        required_metric_fields = {"value", "unit", "source", "coverage", "limitations", "formula"}
        if set(metrics) != DORA_METRICS or any(
            not isinstance(value, dict)
            or any(field not in value or value[field] is None or value[field] == "" for field in required_metric_fields)
            for value in metrics.values()
        ):
            raise ValueError(
                "Available DORA input requires exactly five metric tables with value, unit, source, formula, coverage, and limitations"
            )
        for metric_id, metric in metrics.items():
            unknown_metric = set(metric) - DORA_METRIC_KEYS
            if unknown_metric:
                raise ValueError(f"dora.metrics.{metric_id} contains unknown keys: {', '.join(sorted(unknown_metric))}")
        try:
            period_start = date.fromisoformat(str(dora["period_start"]))
            period_end = date.fromisoformat(str(dora["period_end"]))
        except ValueError as error:
            raise ValueError("DORA period_start and period_end must use ISO 8601 YYYY-MM-DD") from error
        if period_end < period_start:
            raise ValueError("DORA period_end must not precede period_start")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the conservative defaults overlaid by a repository TOML file."""

    chosen = Path(path).resolve() if path else default_config_path().resolve()
    supplied = tomllib.loads(chosen.read_text(encoding="utf-8"))
    config = _merge(DEFAULT_CONFIG, supplied)
    _validate(config)
    config["_config_path"] = str(chosen)
    return config


def tri_state(value: Any, auto_value: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    if normalized == "auto":
        return auto_value
    return None

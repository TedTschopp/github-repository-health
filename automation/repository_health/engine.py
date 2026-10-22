"""Orchestrate collection, evaluation, scoring, and JSON serialization."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .catalog import parse_catalog
from .collectors import (
    GitHubClient,
    collect_github,
    collect_local,
    github_check_state,
    github_protection_state,
    read_git_bytes,
)
from .configuration import load_config, load_config_bytes
from .evidence_artifacts import (
    EvidenceArtifactError,
    collect_evidence_artifacts,
)
from .evidence_policy import (
    EvidencePolicyError,
    load_evidence_policy,
    select_eligible_runs,
)
from .evaluator import evaluate_controls, findings_from_controls, resolved_repository_facts, summarize
from .github_client import GitHubRESTClient
from .github_collectors import collect_github_observations
from .history_collectors import collect_remote_history
from .measurements import METRIC_SCHEMA_VERSION, METRIC_VERSION, calculate_metrics
from .normalizers import NormalizationError, load_production_identity, normalize_observations
from .production_identity import declared_release_asset_names
from .workflow_dependencies import collect_workflow_dependencies


SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "0.2.0"


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "control-catalog.md"


def _iso_now(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _production_subjects(identity: dict[str, Any] | None, main_branch: str) -> dict[str, dict[str, str]]:
    """Return exact evidence subjects without inventing missing source identity."""

    if not isinstance(identity, dict) or not isinstance(identity.get("units"), list):
        return {}
    subjects: dict[str, dict[str, str]] = {}
    for unit in identity["units"]:
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
            continue
        unit_id = unit["unit_id"]
        if identity.get("schema_version") == "RH-PRODUCTION-IDENTITY-1.0":
            current = unit.get("current")
            source_sha = current.get("source_sha") if isinstance(current, dict) else None
            tag = current.get("tag") if isinstance(current, dict) else None
            if isinstance(source_sha, str) and isinstance(tag, str):
                subjects[unit_id] = {"sha": source_sha, "ref": f"refs/tags/{tag}"}
            continue
        source_sha = unit.get("source_sha")
        selector = unit.get("selector") if isinstance(unit.get("selector"), dict) else {}
        profile = unit.get("profile")
        source_ref: str | None = None
        if profile == "package-github-release" and isinstance(selector.get("tag"), str):
            source_ref = f"refs/tags/{selector['tag']}"
        elif profile == "gitops-production-ref" and isinstance(selector.get("production_ref"), str):
            source_ref = selector["production_ref"]
        elif profile in {"application-github-deployment", "documentation-publication"}:
            source_ref = f"refs/heads/{main_branch}"
        if isinstance(source_sha, str) and isinstance(source_ref, str):
            subjects[unit_id] = {"sha": source_sha, "ref": source_ref}
    return subjects


def _unknown_observation_bundle(
    repository: str | None,
    subject_sha: str | None,
    generated_at: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
        "observed_at": generated_at,
        "repository": repository,
        "subject_sha": subject_sha,
        "unit": None,
        "units": [],
        "state": "unknown",
        "completeness": "unknown",
        "complete": False,
        "population_complete": False,
        "observations": {},
        "gaps": [
            {
                "kind": "evidence_unavailable",
                "status": None,
                "endpoint": None,
                "source": "github-rest",
                "message": reason,
            }
        ],
    }


def _legacy_github_view(bundle: dict[str, Any]) -> dict[str, Any]:
    """Adapt normalized observations for controls not yet metric-backed."""

    observations = bundle.get("observations") if isinstance(bundle.get("observations"), dict) else {}

    def group_data(name: str) -> dict[str, Any]:
        group = observations.get(name)
        if not isinstance(group, dict) or not isinstance(group.get("data"), dict):
            return {}
        return group["data"]

    identity = group_data("repository_identity")
    rules = group_data("rules")
    changes = group_data("change_history")
    refs = group_data("refs_releases")
    checks = group_data("check_runs")
    data: dict[str, Any] = {}
    candidates = {
        "repository": identity.get("repository_record"),
        "branch": identity.get("branch"),
        "protection": rules.get("branch_protection"),
        "rulesets": [
            item.get("detail") or item.get("summary")
            for item in rules.get("rulesets", [])
            if isinstance(item, dict) and (item.get("detail") or item.get("summary"))
        ],
        "check_runs": checks if checks else None,
        "pull_requests": changes.get("associated_pull_requests"),
        "releases": refs.get("releases"),
        "tags": refs.get("tags"),
    }
    for name, value in candidates.items():
        if value is not None:
            data[name] = value

    statuses: dict[str, int | None] = {}
    for name, group in observations.items():
        if not isinstance(group, dict):
            continue
        endpoints = group.get("request", {}).get("endpoints", []) if isinstance(group.get("request"), dict) else []
        observed_statuses = [
            endpoint.get("status")
            for endpoint in endpoints
            if isinstance(endpoint, dict) and endpoint.get("status") is not None
        ]
        statuses[str(name)] = observed_statuses[-1] if observed_statuses else None

    gaps = []
    for gap in bundle.get("gaps", []):
        if not isinstance(gap, dict):
            continue
        source = gap.get("observation") or gap.get("source") or "GitHub"
        message = gap.get("message") or gap.get("kind") or "Evidence unavailable"
        gaps.append(f"{source}: {message}")
    return {
        "available": bool(data),
        "repository": bundle.get("repository"),
        "main_sha": bundle.get("subject_sha") or identity.get("main_sha"),
        "collected_at": bundle.get("observed_at"),
        "data": data,
        "endpoint_status": statuses,
        "gaps": list(dict.fromkeys(gaps)),
    }


def _observation_evidence_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    observations = bundle.get("observations") if isinstance(bundle.get("observations"), dict) else {}
    control_map = {
        "repository_identity": ["SPI-01", "RLP-01"],
        "check_runs": ["SPI-01", "BTC-01", "BTC-02", "BTC-03"],
        "actions_w90": ["SPI-01", "BTC-02", "BTC-03", "BTC-04", "BTC-05"],
        "actions_w365": ["BTC-01", "BTC-02", "BTC-03", "BTC-04", "BTC-05"],
        "change_history": ["CGD-01", "CGD-03", "CGD-04", "CGD-05"],
        "rules": ["CGD-01", "CGD-02", "CGD-04"],
        "refs_releases": ["SPI-02", "SPI-03", "RRO-01", "RLP-02"],
        "delivery": ["SPI-02", "SPI-04", "RRO-01", "RRO-03"],
        "security": ["SSC-01", "SSC-02", "SSC-03"],
        "attestations": ["SPI-02", "SPI-03", "SSC-02", "RRO-01"],
    }
    source_type_map = {
        "check_runs": "CI",
        "actions_w90": "CI",
        "actions_w365": "CI",
        "change_history": "Git",
        "rules": "host settings",
        "refs_releases": "release",
        "delivery": "deployment",
        "security": "security",
        "attestations": "provenance",
    }
    records: list[dict[str, Any]] = []
    for name, group in observations.items():
        if not isinstance(group, dict):
            continue
        evidence_id = group.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        endpoints = group.get("request", {}).get("endpoints", []) if isinstance(group.get("request"), dict) else []
        locations = [
            endpoint.get("endpoint")
            for endpoint in endpoints
            if isinstance(endpoint, dict) and isinstance(endpoint.get("endpoint"), str)
        ]
        gaps = [
            str(gap.get("message") or gap.get("kind"))
            for gap in group.get("gaps", [])
            if isinstance(gap, dict)
        ]
        complete = group.get("complete") is True and group.get("population_complete") is True and not gaps
        data = group.get("data") if isinstance(group.get("data"), dict) else {}
        window = data.get("window") if isinstance(data.get("window"), dict) else {}
        assurance = "E0"
        if complete:
            # Repository identity and effective-rule records prove configured
            # state. Event, execution, release, deployment, alert, attestation,
            # and normalized measurement populations demonstrate observed
            # behavior. Sustained effectiveness is never inferred merely from
            # a complete current API response.
            assurance = "E2" if name in {"repository_identity", "rules"} else "E3"
        records.append(
            {
                "evidence_id": evidence_id,
                "control_ids": control_map.get(str(name), []),
                "source_type": source_type_map.get(str(name), "GitHub"),
                "system": group.get("source") or f"GitHub {name}",
                "location": "; ".join(dict.fromkeys(locations)) or f"GitHub REST observation: {name}",
                "observed_at": group.get("observed_at") or bundle.get("observed_at"),
                "period_start": window.get("start"),
                "period_end": window.get("end") or group.get("observed_at") or bundle.get("observed_at"),
                "population_coverage": "Complete eligible population." if complete else "Incomplete or inaccessible eligible population.",
                "freshness_days": 0,
                "assurance": assurance,
                "collector": "repository-health GitHub observation collector",
                "notes": "Complete read-only GitHub observation." if complete else "; ".join(dict.fromkeys(gaps)) or "Observation completeness was not demonstrated.",
            }
        )
    return records


def _evidence_records(
    config: dict[str, Any],
    local: dict[str, Any],
    github: dict[str, Any],
    generated_at: str,
    observation_bundle: dict[str, Any] | None = None,
    workflow_dependencies: dict[str, Any] | None = None,
    durable_history: dict[str, Any] | None = None,
    produced_evidence: dict[str, Any] | None = None,
    produced_verifications: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    root = local["root"]
    exact_main_content = local.get("working_tree_clean") is True and local.get("head_is_main") is True
    local_content_assurance = "E2" if exact_main_content else "E1"
    records: list[dict[str, Any]] = [
        {
            "evidence_id": "E-CONFIG-CLASSIFICATION",
            "control_ids": ["CGD-05", "OWM-01", "RLP-01"],
            "source_type": "attestation",
            "system": "repository-health TOML configuration",
            "location": config["_config_path"],
            "observed_at": generated_at,
            "period_start": None,
            "period_end": generated_at,
            "population_coverage": "Repository classification declarations supplied to this assessment.",
            "freshness_days": 0,
            "assurance": "E1",
            "collector": "repository-health engine",
            "notes": "A declaration alone does not establish configured or demonstrated behavior.",
        },
        {
            "evidence_id": "E-LOCAL-GIT",
            "control_ids": ["SPI-01", "RLP-02"],
            "source_type": "Git",
            "system": "local Git",
            "location": root,
            "observed_at": generated_at,
            "period_start": None,
            "period_end": generated_at,
            "population_coverage": "Current checkout, Main-role ref when resolvable, and local refs.",
            "freshness_days": 0,
            "assurance": "E2" if local.get("is_git_repository") else "E0",
            "collector": "repository-health engine",
            "notes": "Local source state is distinct from pushed, release, and production state.",
        },
        {
            "evidence_id": "E-LOCAL-DOCS",
            "control_ids": ["OWM-01", "OWM-02", "DCR-01", "DCR-02", "DCR-03", "DCR-04"],
            "source_type": "documentation",
            "system": "working tree file inventory",
            "location": root,
            "observed_at": generated_at,
            "period_start": None,
            "period_end": generated_at,
            "population_coverage": "Bounded inventory of canonical root and .github documentation filenames.",
            "freshness_days": 0,
            "assurance": local_content_assurance,
            "collector": "repository-health engine",
            "notes": (
                "Filename presence does not prove topic completeness, link health, route monitoring, or successful command execution. "
                + ("Files are from the clean exact Main checkout." if exact_main_content else "Files are source-state observations not proven to be the clean exact Main revision.")
            ),
        },
        {
            "evidence_id": "E-LOCAL-WORKFLOWS",
            "control_ids": ["BTC-01", "BTC-02", "BTC-03", "SSC-04"],
            "source_type": "CI",
            "system": "working tree workflow inventory",
            "location": f"{root}/.github/workflows",
            "observed_at": generated_at,
            "period_start": None,
            "period_end": generated_at,
            "population_coverage": "Version-controlled GitHub Actions YAML files at the assessed revision.",
            "freshness_days": 0,
            "assurance": local_content_assurance,
            "collector": "repository-health engine",
            "notes": "Workflows were inventoried, not executed or semantically certified. " + (
                "Files are from the clean exact Main checkout." if exact_main_content else "Files are source-state observations not proven to be the clean exact Main revision."
            ),
        },
        {
            "evidence_id": "E-LOCAL-DEPS",
            "control_ids": ["SSC-02", "SSC-03"],
            "source_type": "security",
            "system": "working tree dependency-file inventory",
            "location": root,
            "observed_at": generated_at,
            "period_start": None,
            "period_end": generated_at,
            "population_coverage": "Known dependency and lockfile names found without executing repository-owned code.",
            "freshness_days": 0,
            "assurance": local_content_assurance,
            "collector": "repository-health engine",
            "notes": "This bounded inventory is not a dependency discovery, SBOM, or vulnerability scan. " + (
                "Files are from the clean exact Main checkout." if exact_main_content else "Files are source-state observations not proven to be the clean exact Main revision."
            ),
        },
    ]

    if observation_bundle is not None:
        records.extend(_observation_evidence_records(observation_bundle))
    else:
        github_records = (
            ("E-GH-PROTECTION", ["CGD-01", "CGD-02", "CGD-04"], "host settings", "GitHub branch/ruleset protection", "protection"),
            ("E-GH-CHECKS", ["SPI-01", "BTC-01", "BTC-02", "BTC-03"], "CI", "GitHub check runs", "check_runs"),
            ("E-GH-PRS", ["BTC-02", "CGD-01", "CGD-03", "CGD-05"], "Git", "GitHub pull requests", "pull_requests"),
            ("E-GH-RELEASES", ["SPI-03", "DCR-04", "RRO-01"], "release", "GitHub releases", "releases"),
        )
        for evidence_id, control_ids, source_type, system, endpoint in github_records:
            available = endpoint in github.get("data", {})
            records.append(
                {
                    "evidence_id": evidence_id,
                    "control_ids": control_ids,
                    "source_type": source_type,
                    "system": system,
                    "location": f"GitHub REST: {github.get('repository') or 'unresolved'} / {endpoint}",
                    "observed_at": generated_at,
                    "period_start": None,
                    "period_end": generated_at,
                    "population_coverage": "Endpoint response available to the assessment token." if available else "No accessible endpoint population.",
                    "freshness_days": 0,
                    "assurance": "E3" if endpoint in {"check_runs", "pull_requests", "releases"} and available else "E2" if available else "E0",
                    "collector": "repository-health engine",
                    "notes": "Inaccessible host evidence remains Unknown; HTTP 403/404 is not interpreted as an absent control.",
                }
            )

    if workflow_dependencies is not None:
        dependency_gaps = [
            str(gap.get("message") or gap.get("kind"))
            for gap in workflow_dependencies.get("gaps", [])
            if isinstance(gap, dict)
        ]
        complete_dependencies = workflow_dependencies.get("complete") is True and workflow_dependencies.get("population_complete") is True
        records.append(
            {
                "evidence_id": str(workflow_dependencies.get("evidence_id") or "E-REPO-WORKFLOW-DEPS"),
                "control_ids": ["SSC-02", "SSC-03", "SSC-04"],
                "source_type": "dependency inventory",
                "system": "version-controlled GitHub Actions dependency inventory",
                "location": f"{local['root']}/.github/workflows",
                "observed_at": workflow_dependencies.get("observed_at") or generated_at,
                "period_start": None,
                "period_end": generated_at,
                "population_coverage": "Every statically visible uses reference, including followed local actions." if complete_dependencies else "Partial workflow dependency population.",
                "freshness_days": 0,
                "assurance": "E2" if complete_dependencies else "E1",
                "collector": "repository-health workflow dependency collector",
                "notes": "; ".join(dict.fromkeys(dependency_gaps)) or "Inventory only; it does not establish vulnerability or provenance status.",
            }
        )

    if durable_history is not None:
        history_gaps = [
            str(gap.get("message") or gap.get("kind"))
            for gap in durable_history.get("gaps", [])
            if isinstance(gap, dict)
        ]
        history_state = durable_history.get("state")
        history_complete = durable_history.get("complete") is True
        segment_complete = durable_history.get("segment_complete") is True
        window_complete = durable_history.get("window_complete") is True
        full_chain_complete = durable_history.get("full_chain_complete") is True
        if history_state == "observed" and history_complete:
            if full_chain_complete:
                history_coverage = "Complete validated snapshot chain from genesis through the current tip."
            elif segment_complete and window_complete:
                history_coverage = (
                    "Validated bounded newest segment covering every required W365 UTC day; "
                    "the earlier predecessor is an opaque anchor."
                )
            elif segment_complete:
                history_coverage = (
                    "Validated bounded newest segment; the required daily measurement window is incomplete "
                    "and any earlier predecessor remains opaque."
                )
            else:
                history_coverage = "Durable-history completeness was not demonstrated."
        elif history_state == "no_history" and history_complete:
            history_coverage = "Complete observation that no evidence branch exists yet."
        else:
            history_coverage = "Incomplete or invalid durable history."
        records.append(
            {
                "evidence_id": str(durable_history.get("evidence_id") or "E-GH-DURABLE-HISTORY"),
                "control_ids": ["SPI-01", "SPI-04"],
                "source_type": "evidence history",
                "system": "hash-linked repository health evidence branch",
                "location": f"GitHub branch: {durable_history.get('branch') or 'repository-health-evidence'}",
                "observed_at": durable_history.get("observed_at") or generated_at,
                "period_start": (
                    durable_history.get("snapshots", [{}])[0].get("generated_at")
                    if durable_history.get("snapshots")
                    else None
                ),
                "period_end": (
                    durable_history.get("snapshots", [{}])[-1].get("generated_at")
                    if durable_history.get("snapshots")
                    else generated_at
                ),
                "population_coverage": history_coverage,
                "freshness_days": 0,
                "assurance": "E3" if history_state == "observed" and history_complete else "E2" if history_state == "no_history" and history_complete else "E0",
                "collector": "repository-health durable-history collector",
                "notes": "; ".join(dict.fromkeys(history_gaps)) or (
                    history_coverage
                    if history_state == "observed"
                    else "No prior history exists; trend measures remain Unknown until the required observation window accrues."
                ),
            }
        )

    if produced_evidence is not None:
        candidates = produced_evidence.get("candidates", [])
        verified = [
            item
            for item in (produced_verifications or [])
            if isinstance(item, dict) and item.get("state") == "verified"
        ]
        statement_kinds = {
            candidate.get("statement", {}).get("kind")
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("statement"), dict)
        }
        control_ids: set[str] = set()
        if "validation" in statement_kinds:
            control_ids.update({"SPI-01", "BTC-01", "BTC-02", "BTC-03", "BTC-04"})
        if "security" in statement_kinds:
            control_ids.update({"SSC-01", "SSC-02", "SSC-03", "SSC-04"})
        if "release" in statement_kinds:
            control_ids.update({"SPI-02", "SPI-03", "RRO-01"})
        if "deployment" in statement_kinds:
            control_ids.update({"SPI-02", "SPI-04", "RRO-03"})
        evidence_gaps = [
            str(gap.get("message") or gap.get("kind"))
            for gap in produced_evidence.get("gaps", [])
            if isinstance(gap, dict)
        ]
        records.append(
            {
                "evidence_id": "E-GH-PRODUCED-EVIDENCE",
                "control_ids": sorted(control_ids),
                "source_type": "workflow evidence",
                "system": "schema-bound repository workflow evidence",
                "location": "GitHub Actions exact run/unit artifacts",
                "observed_at": produced_evidence.get("observed_at") or generated_at,
                "period_start": None,
                "period_end": produced_evidence.get("observed_at") or generated_at,
                "population_coverage": (
                    "Every explicitly eligible run/unit population was collected."
                    if produced_evidence.get("population_complete") is True
                    else "One or more eligible run/unit populations is incomplete."
                ),
                "freshness_days": 0,
                "assurance": "E3" if verified else "E0",
                "collector": "repository-health evidence artifact collector",
                "notes": (
                    f"{len(verified)} independently verified statement(s); statements do not map to a control until a metric-specific resolver consumes them."
                    if verified
                    else "; ".join(dict.fromkeys(evidence_gaps))
                    or "No statement completed source, result, artifact, category-policy, and population verification."
                ),
            }
        )

    existing = {record["evidence_id"] for record in records}
    for evidence_id in config["repository"].get("methodology_evidence_ids", []):
        if evidence_id in existing:
            continue
        records.append(
            {
                "evidence_id": evidence_id,
                "control_ids": ["CGD-05"],
                "source_type": "attestation",
                "system": "methodology classification evidence reference",
                "location": config["_config_path"],
                "observed_at": generated_at,
                "period_start": None,
                "period_end": generated_at,
                "population_coverage": "Declared workflow axes and observed-profile classification.",
                "freshness_days": 0,
                "assurance": "E2",
                "collector": "repository configuration owner",
                "notes": "Classification evidence is separate from control conformance and assessment assurance.",
            }
        )
        existing.add(evidence_id)
    if config.get("dora", {}).get("available"):
        for evidence_id in config["dora"].get("evidence_ids", []):
            if evidence_id in existing:
                continue
            records.append(
                {
                    "evidence_id": evidence_id,
                    "control_ids": [],
                    "source_type": "operations",
                    "system": "DORA outcome evidence reference",
                    "location": config["_config_path"],
                    "observed_at": generated_at,
                    "period_start": config["dora"].get("period_start"),
                    "period_end": config["dora"].get("period_end"),
                    "population_coverage": str(config["dora"].get("service")),
                    "freshness_days": 0,
                    "assurance": "E1",
                    "collector": "repository configuration owner",
                    "notes": "Informative-only outcome evidence; it does not contribute to the repository-control score.",
                }
            )
            existing.add(evidence_id)
    for control_id, override in config.get("controls", {}).items():
        for evidence_id in override.get("evidence_ids", []):
            if evidence_id in existing:
                continue
            records.append(
                {
                    "evidence_id": evidence_id,
                    "control_ids": [control_id],
                    "source_type": "attestation",
                    "system": "repository-supplied evidence reference",
                    "location": str(override.get("evidence_location", config["_config_path"])),
                    "observed_at": generated_at,
                    "period_start": None,
                    "period_end": generated_at,
                    "population_coverage": str(override.get("population_coverage", "As stated in the repository-specific control rationale.")),
                    "freshness_days": int(override.get("freshness_days", 0)),
                    "assurance": override["assurance"],
                    "collector": str(override.get("collector", "repository configuration owner")),
                    "notes": "Repository-supplied evidence reference; downstream assurance depends on the referenced record remaining reviewable.",
                }
            )
            existing.add(evidence_id)
    return records


def _dora_panel(config: dict[str, Any]) -> dict[str, Any]:
    source = config.get("dora", {})
    available = bool(source.get("available", False))
    metrics = source.get("metrics", {})
    if not isinstance(metrics, dict):
        raise ValueError("dora.metrics must be a TOML table")
    return {
        "informative_only": True,
        "available": available,
        "reason": source.get("reason") if not available else None,
        "service": source.get("service") if available else None,
        "period_start": source.get("period_start") if available else None,
        "period_end": source.get("period_end") if available else None,
        "evidence_ids": list(source.get("evidence_ids", [])) if available else [],
        "context": source.get("context") if available else None,
        "limitations": source.get("limitations") if available else None,
        "metrics": metrics if available else {},
    }


def _decision_records(config: dict[str, Any], repository_identity: str) -> list[dict[str, Any]]:
    decisions = [dict(item) for item in config.get("exceptions", [])]
    for control_id, override in config.get("controls", {}).items():
        if override.get("conformance") != "N/A":
            continue
        identifier = str(override.get("decision_id", f"NA-{control_id}"))
        decisions.append(
            {
                "exception_id": identifier,
                "decision_id": identifier,
                "type": "N/A determination",
                "control_ids": [control_id],
                "scope": str(override.get("scope", repository_identity)),
                "risk_owner": str(override.get("risk_owner", config["repository"].get("owner", ""))),
                "rationale": override["rationale"],
                "compensating_control": override.get("compensating_control"),
                "approver": override["n_a_approved_by"],
                "approved_at": override["n_a_approved_at"],
                "expires_at": None,
                "review_date": override["n_a_review_date"],
                "status": str(override.get("status", "active")),
                "evidence_ids": list(override.get("evidence_ids", [])),
            }
        )
    return decisions


def assess_repository(
    repository: str | Path = ".",
    catalog_path: str | Path | None = None,
    config_path: str | Path | None = None,
    github_repository: str | None = None,
    github_token: str | None = None,
    github_client: GitHubClient | None = None,
    github_observation_client: GitHubRESTClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess a repository and return the stable schema-versioned dictionary."""

    catalog = parse_catalog(catalog_path or default_catalog_path())
    bootstrap_config = load_config(config_path)
    generated_at = _iso_now(now)
    local = collect_local(repository, str(bootstrap_config["repository"].get("main_branch", "")))
    config = bootstrap_config
    config_source_path = Path(bootstrap_config["_config_path"])
    repository_root = Path(local["root"])
    main_sha = local.get("main_sha")
    if local.get("is_git_repository") is True and isinstance(main_sha, str):
        try:
            config_relative_path = config_source_path.resolve().relative_to(repository_root.resolve()).as_posix()
        except ValueError as error:
            raise ValueError(
                "Repository health configuration must be versioned inside the assessed repository so scoring inputs can be bound to exact Main."
            ) from error
        config_ok, config_bytes = read_git_bytes(repository_root, main_sha, config_relative_path)
        if not config_ok:
            raise ValueError(
                f"Exact-Main repository health configuration is unavailable at {config_relative_path}: {config_bytes}"
            )
        config = load_config_bytes(
            bytes(config_bytes),
            source=f"git:{main_sha}:{config_relative_path}",
        )
        if config["repository"].get("main_branch") != local.get("main_branch"):
            raise ValueError("Exact-Main configuration changes the bootstrap Main branch and cannot be assessed safely.")
    if config["standard"]["version"] != catalog.standard_version:
        raise ValueError(
            f"Configuration standard version {config['standard']['version']} does not match catalog {catalog.standard_version}"
        )
    known_control_ids = {control.control_id for control in catalog.controls}
    for index, decision in enumerate(config.get("exceptions", [])):
        control_ids = decision.get("control_ids")
        if not isinstance(control_ids, list) or not control_ids or not all(item in known_control_ids for item in control_ids):
            raise ValueError(f"exceptions[{index}].control_ids must name one or more catalog controls")
    workflow_dependencies = collect_workflow_dependencies(
        repository,
        subject_sha=local.get("main_sha"),
        observed_at=generated_at,
    )
    local["workflow_dependencies"] = workflow_dependencies
    visible_workflow_dependencies = [
        item
        for item in workflow_dependencies.get("observations", [])
        if isinstance(item, dict)
    ]
    if visible_workflow_dependencies:
        local["dependency_files"] = sorted(
            {
                *local.get("dependency_files", []),
                *(
                    f"workflow:{item.get('identity') or item.get('raw') or item.get('dependency_id')}"
                    for item in visible_workflow_dependencies
                ),
            }
        )
    repo_name = github_repository or local.get("github_repository")
    token = github_token if github_token is not None else os.environ.get("GITHUB_TOKEN", "")
    production_identity: dict[str, Any] | None = None
    release_asset_names: list[str] = []
    evidence_policy: dict[str, Any] | None = None
    evidence_policy_error: str | None = None
    if repo_name and isinstance(local.get("main_sha"), str):
        try:
            production_ok, production_bytes = read_git_bytes(
                local["root"],
                local["main_sha"],
                ".github/repository-health-production.json",
            )
            if not production_ok:
                raise NormalizationError(str(production_bytes))
            production_identity = load_production_identity(
                bytes(production_bytes),
                config=config,
                repository=repo_name,
            )
            release_asset_names = declared_release_asset_names(production_identity)
        except (NormalizationError, OSError, KeyError, TypeError):
            # The normalizer records the exact conflict. Collection simply
            # declines to download any undeclared or unvalidated asset name.
            production_identity = None
            release_asset_names = []
        try:
            policy_ok, policy_bytes = read_git_bytes(
                local["root"],
                local["main_sha"],
                ".github/repository-health-evidence-policy.json",
            )
            if not policy_ok:
                raise EvidencePolicyError(str(policy_bytes))
            evidence_policy = load_evidence_policy(
                bytes(policy_bytes),
                repository=repo_name,
                unit_ids=config["repository"].get("deployable_units", []),
                source_sha=local["main_sha"],
                source_path=".github/repository-health-evidence-policy.json",
            )
        except (EvidencePolicyError, OSError, KeyError, TypeError) as error:
            evidence_policy_error = str(error)
            evidence_policy = None
    observation_bundle: dict[str, Any]
    durable_history: dict[str, Any] | None = None
    rest_client: GitHubRESTClient | None = None
    if repo_name and (token or github_observation_client is not None):
        rest_client = github_observation_client or GitHubRESTClient(token=token)
        observation_bundle = collect_github_observations(
            repo_name,
            main_branch=local["main_branch"],
            subject_sha=local.get("main_sha"),
            client=rest_client,
            now=now,
            release_asset_names=release_asset_names,
        )
        durable_history = collect_remote_history(repo_name, rest_client)
        github = _legacy_github_view(observation_bundle)
    elif repo_name and github_client is not None:
        # Preserve the original injectable client as a compatibility seam for
        # callers that have not yet moved to the normalized observation API.
        client = github_client or GitHubClient(token=token)
        github = collect_github(repo_name, local["main_branch"], local.get("main_sha"), client)
        observation_bundle = _unknown_observation_bundle(
            repo_name,
            github.get("main_sha") or local.get("main_sha"),
            generated_at,
            "A legacy GitHub client was supplied; normalized populations were not collected.",
        )
    else:
        reason = "GitHub token unavailable." if repo_name else "GitHub repository identity unavailable."
        github = {"available": False, "repository": repo_name, "data": {}, "endpoint_status": {}, "gaps": [reason]}
        observation_bundle = _unknown_observation_bundle(repo_name, local.get("main_sha"), generated_at, reason)

    evidence_selection: dict[str, Any] = {
        "schema_version": "RH-EVIDENCE-POLICY-SELECTION-1.0",
        "repository": repo_name,
        "main_sha": local.get("main_sha"),
        "state": "unknown",
        "complete": False,
        "population_complete": False,
        "eligible_runs": {},
        "category_policy": {},
        "selections": [],
        "gaps": [
            {
                "kind": "evidence_policy_unavailable",
                "unit_id": None,
                "evidence_kind": None,
                "message": evidence_policy_error or "No exact-Main evidence policy was loaded.",
            }
        ],
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }
    produced_evidence: dict[str, Any] | None = None
    produced_verifications: list[dict[str, Any]] = []
    if (
        evidence_policy is not None
        and rest_client is not None
        and isinstance(local.get("main_sha"), str)
    ):
        actions_group = observation_bundle.get("observations", {}).get("actions_w365")
        try:
            evidence_selection = select_eligible_runs(
                evidence_policy,
                actions_observation=actions_group,
                main_sha=local["main_sha"],
                main_branch=local["main_branch"],
                production_subjects=_production_subjects(
                    production_identity,
                    local["main_branch"],
                ),
            )
            if evidence_selection.get("eligible_runs"):
                produced_evidence = collect_evidence_artifacts(
                    repo_name,
                    client=rest_client,
                    eligible_runs=evidence_selection["eligible_runs"],
                    category_policy=evidence_selection["category_policy"],
                    now=now,
                )
                produced_verifications = list(
                    produced_evidence.get("statement_verifications", [])
                )
        except (EvidencePolicyError, EvidenceArtifactError, OSError, ValueError) as error:
            evidence_selection = {
                **evidence_selection,
                "state": "unknown",
                "complete": False,
                "gaps": [
                    *evidence_selection.get("gaps", []),
                    {
                        "kind": "produced_evidence_collection_failed",
                        "unit_id": None,
                        "evidence_kind": None,
                        "message": str(error),
                    },
                ],
            }

    facts = resolved_repository_facts(config, local)
    observation_bundle["units"] = list(facts.get("deployable_units", []))
    normalization_error: str | None = None
    try:
        if repo_name and local.get("main_sha"):
            observation_bundle = normalize_observations(
                observation_bundle,
                local,
                config,
                prior_history=(
                    durable_history.get("snapshots", [])
                    if isinstance(durable_history, dict) and durable_history.get("state") == "observed"
                    else []
                ),
            )
    except (NormalizationError, OSError, ValueError) as error:
        # A malformed declaration or insufficient prerequisite is an evidence
        # gap, never a reason to discard the raw observations or assume a pass.
        normalization_error = str(error)
        observation_bundle.setdefault("gaps", []).append(
            {
                "kind": "normalization_failed",
                "status": None,
                "endpoint": None,
                "source": "repository-health normalizer",
                "message": normalization_error,
            }
        )
    measurements = calculate_metrics(observation_bundle, include_unit_results=True)
    controls = evaluate_controls(catalog, config, local, github, measurements)
    dimensions, gates, score, assurance = summarize(controls)
    evidence = _evidence_records(
        config,
        local,
        github,
        generated_at,
        observation_bundle=observation_bundle,
        workflow_dependencies=workflow_dependencies,
        durable_history=durable_history,
        produced_evidence=produced_evidence,
        produced_verifications=produced_verifications,
    )
    check_state, observed_checks = github_check_state(github, list(facts.get("authoritative_checks", [])))
    github_summary = {
        "available": github.get("available", False),
        "repository": github.get("repository"),
        "main_sha": github.get("main_sha"),
        "endpoint_status": github.get("endpoint_status", {}),
        "gaps": github.get("gaps", []),
        "main_protection_state": github_protection_state(github),
        "authoritative_check_state": check_state,
        "observed_authoritative_checks": observed_checks,
        "pull_request_count_observed": len(github.get("data", {}).get("pull_requests", [])) if isinstance(github.get("data", {}).get("pull_requests"), list) else None,
        "release_count_observed": len(github.get("data", {}).get("releases", [])) if isinstance(github.get("data", {}).get("releases"), list) else None,
        "observation_schema_version": observation_bundle.get("schema_version"),
        "observation_completeness": observation_bundle.get("completeness"),
        "observation_group_count": len(observation_bundle.get("observations", {})),
        "observation_gap_count": len(observation_bundle.get("gaps", [])),
        "normalization": observation_bundle.get("normalization"),
        "durable_history": (
            {
                "state": durable_history.get("state"),
                "complete": durable_history.get("complete"),
                "branch": durable_history.get("branch"),
                "branch_sha": durable_history.get("branch_sha"),
                "snapshot_count": len(durable_history.get("snapshots", [])),
                "validation_scope": durable_history.get("validation_scope"),
                "segment_complete": durable_history.get("segment_complete"),
                "window_complete": durable_history.get("window_complete"),
                "full_chain_complete": durable_history.get("full_chain_complete"),
                "opaque_predecessor_sha256": durable_history.get("opaque_predecessor_sha256"),
                "gaps": durable_history.get("gaps", []),
            }
            if isinstance(durable_history, dict)
            else {
                "state": "unknown",
                "complete": False,
                "branch": "repository-health-evidence",
                "branch_sha": None,
                "snapshot_count": 0,
                "gaps": ["Durable history was not collected in this assessment mode."],
            }
        ),
        "produced_evidence": {
            "policy_loaded": evidence_policy is not None,
            "policy_schema_version": (
                evidence_policy.get("schema_version") if evidence_policy else None
            ),
            "selection": evidence_selection,
            "artifact_bundle": produced_evidence,
            "statement_verifications": produced_verifications,
        },
    }
    limitations = list(github.get("gaps", []))
    if normalization_error:
        limitations.append(f"GitHub evidence normalization failed closed: {normalization_error}")
    if evidence_policy is None:
        limitations.append(
            "No valid exact-Main workflow-evidence policy was available; producer artifacts were not selected."
        )
    else:
        limitations.extend(
            str(gap.get("message") or gap.get("kind"))
            for gap in evidence_selection.get("gaps", [])
            if isinstance(gap, dict)
        )
    if produced_evidence is not None:
        limitations.extend(
            str(gap.get("message") or gap.get("kind"))
            for gap in produced_evidence.get("gaps", [])
            if isinstance(gap, dict)
        )
    normalization = observation_bundle.get("normalization")
    if isinstance(normalization, dict):
        limitations.extend(str(item) for item in normalization.get("limitations", []) if item)
        limitations.extend(str(item) for item in normalization.get("conflicts", []) if item)
    limitations.extend(
        [
            "This result applies provisional standard 0.1.0-draft and is not field-calibrated.",
            "The bounded collector does not execute repository-owned build, test, deployment, rollback, secret-scanning, or binary-analysis code.",
            "Local source state, pushed host state, release evidence, and observed production state are reported as distinct evidence layers.",
            "Unknown evidence contributes zero points and is never assumed to pass.",
        ]
    )
    if config["repository"]["type"] == "Unknown":
        limitations.append("Repository type is Unknown; conditional applicability remains conservative.")
    if local.get("working_tree_clean") is False:
        limitations.append("The local working tree has uncommitted changes; file evidence describes observed source state and is not treated as exact-Main evidence.")
    elif local.get("working_tree_clean") is None:
        limitations.append("Working-tree cleanliness could not be established; file evidence is not treated as exact-Main evidence.")
    elif local.get("head_is_main") is not True:
        limitations.append("The clean checkout was not proven to equal Main; file evidence is retained as committed source state rather than exact-Main evidence.")
    if not str(config["assessment"].get("reviewer", "")).strip():
        limitations.append("No independent assessment reviewer is recorded; the result is not issuance-ready.")
    if not str(config["assessment"].get("next_review", "")).strip():
        limitations.append("No next review date is recorded; schedule one before formal issuance.")
    if not facts.get("deployable_units") and facts.get("has_current_output") is not False:
        limitations.append("No deployable-unit inventory or approved no-output determination is recorded.")

    effective_main_sha = local.get("main_sha") or github.get("main_sha")
    head_fragment = (effective_main_sha or local.get("head_sha") or "unknown")[:8]
    timestamp_fragment = generated_at.replace("+00:00", "Z").replace("-", "").replace(":", "")
    run_fragment = os.environ.get("GITHUB_RUN_ID", "").strip()
    assessment_id = f"RHA-{timestamp_fragment}-{head_fragment}" + (f"-run{run_fragment}" if run_fragment else "")
    return {
        "schema_version": SCHEMA_VERSION,
        "standard_version": catalog.standard_version,
        "standard_status": "provisional-draft-not-calibrated",
        "assessment_id": assessment_id,
        "generated_at": generated_at,
        "automation": {
            "engine_version": ENGINE_VERSION,
            "observation_schema_version": observation_bundle.get("schema_version"),
            "metric_schema_version": METRIC_SCHEMA_VERSION,
            "metric_version": METRIC_VERSION,
            "catalog_sha256": _sha256(catalog.path),
            "config_sha256": config.get("_config_sha256") or _sha256(config["_config_path"]),
            "collector_mode": "local+github" if github.get("available") else "local-only",
            "read_only_collection": True,
            "assessed_repository_build_code_executed": False,
        },
        "assessment": {
            "assessor": config["assessment"].get("assessor"),
            "reviewer": config["assessment"].get("reviewer") or None,
            "evidence_cutoff": generated_at,
            "issue_date": generated_at[:10],
            "next_review": config["assessment"].get("next_review") or None,
            "provisional_status_disclosure": "Uses provisional 0.1.0-draft; pilot-ready, not field-calibrated or a compliance/release gate.",
        },
        "repository": {
            "identity": repo_name or local["root"],
            "path": local["root"],
            "default_branch": local["main_branch"],
            "head_sha": effective_main_sha,
            "main_sha": effective_main_sha,
            "assessed_checkout_sha": local.get("head_sha"),
            "main_ref_source": local.get("main_ref_source") or ("github" if github.get("main_sha") else None),
            "assessed_revision_is_local_head": (
                bool(local.get("head_sha") == effective_main_sha)
                if local.get("head_sha") and effective_main_sha
                else local.get("head_is_main")
            ),
            "deployable_units": list(facts.get("deployable_units", [])),
            "production_correspondence": facts.get("production_correspondence"),
        },
        "classification": {
            "type": facts["type"],
            "lifecycle": facts["lifecycle"],
            "risk_tier": facts["risk_tier"],
            "owner": facts["owner"] or None,
            "declared_methodology": facts["methodology"],
            "observed_methodology": facts["observed_methodology"],
            "methodology_confidence": facts["methodology_confidence"],
            "methodology_assurance": "E2" if facts.get("methodology_evidence_ids") else "E1",
            "methodology_evidence_ids": list(facts.get("methodology_evidence_ids", [])),
            "axes": dict(config.get("methodology_axes", {})),
            "contradictions": list(facts.get("methodology_contradictions", [])),
        },
        "facts": {"local": local, "github": github_summary, "resolved_declarations": facts},
        "evidence": evidence,
        "measurements": measurements,
        "controls": controls,
        "dimensions": dimensions,
        "gates": gates,
        "score": score,
        "assurance": assurance,
        "findings": findings_from_controls(controls),
        "exceptions": _decision_records(config, repo_name or local["root"]),
        "limitations": list(dict.fromkeys(limitations)),
        "dora": _dora_panel(config),
    }


def write_assessment(assessment: dict[str, Any], output: str | Path) -> Path:
    """Atomically write an assessment JSON document."""

    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(assessment, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target

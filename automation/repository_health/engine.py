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
)
from .configuration import load_config
from .evaluator import evaluate_controls, findings_from_controls, resolved_repository_facts, summarize


SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "0.1.0"


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


def _evidence_records(
    config: dict[str, Any],
    local: dict[str, Any],
    github: dict[str, Any],
    generated_at: str,
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
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess a repository and return the stable schema-versioned dictionary."""

    catalog = parse_catalog(catalog_path or default_catalog_path())
    config = load_config(config_path)
    if config["standard"]["version"] != catalog.standard_version:
        raise ValueError(
            f"Configuration standard version {config['standard']['version']} does not match catalog {catalog.standard_version}"
        )
    known_control_ids = {control.control_id for control in catalog.controls}
    for index, decision in enumerate(config.get("exceptions", [])):
        control_ids = decision.get("control_ids")
        if not isinstance(control_ids, list) or not control_ids or not all(item in known_control_ids for item in control_ids):
            raise ValueError(f"exceptions[{index}].control_ids must name one or more catalog controls")
    local = collect_local(repository, str(config["repository"].get("main_branch", "")))
    repo_name = github_repository or local.get("github_repository")
    token = github_token if github_token is not None else os.environ.get("GITHUB_TOKEN", "")
    if repo_name and (token or github_client is not None):
        client = github_client or GitHubClient(token=token)
        github = collect_github(repo_name, local["main_branch"], local.get("main_sha"), client)
    else:
        reason = "GitHub token unavailable." if repo_name else "GitHub repository identity unavailable."
        github = {"available": False, "repository": repo_name, "data": {}, "endpoint_status": {}, "gaps": [reason]}

    generated_at = _iso_now(now)
    facts = resolved_repository_facts(config, local)
    controls = evaluate_controls(catalog, config, local, github)
    dimensions, gates, score, assurance = summarize(controls)
    evidence = _evidence_records(config, local, github, generated_at)
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
    }
    limitations = list(github.get("gaps", []))
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
            "catalog_sha256": _sha256(catalog.path),
            "config_sha256": _sha256(config["_config_path"]),
            "collector_mode": "local+github" if github.get("available") else "local-only",
            "read_only_collection": True,
            "repository_owned_code_executed": False,
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

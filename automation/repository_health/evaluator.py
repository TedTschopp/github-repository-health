"""Applicability, conformance, assurance, gate, and score evaluation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .catalog import Catalog, Control
from .collectors import github_check_state, github_protection_state
from .configuration import tri_state


DIMENSIONS = {
    "SPI": "Source-to-production integrity",
    "BTC": "Build, test, and CI health",
    "CGD": "Change governance and branch discipline",
    "SSC": "Security and software-supply-chain health",
    "OWM": "Ownership and maintainability",
    "DCR": "Documentation and contributor readiness",
    "RRO": "Release, rollback, and operational readiness",
    "RLP": "Repository lifecycle and portfolio hygiene",
}
RISK_ORDER = {"Baseline": 0, "Elevated": 1, "Critical": 2}
ASSURANCE_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}
ASSURANCE_POINTS = {"E0": 0, "E1": 25, "E2": 50, "E3": 75, "E4": 100}
CONFORMANCE_POINTS = {"Met": 100.0, "Partially met": 50.0, "Unmet": 0.0, "Unknown": 0.0, "N/A": None}
ACTIVE_LIFECYCLES = {"Active", "Stable-supported", "Experimental", "Mirrored", "Unknown"}

# Full-control N/A is possible only where the catalog defines a complete
# repository/unit exclusion. Item-level exclusions (for example one change
# category or one documentation topic) do not remove the whole control.
FULL_CONTROL_NA_ALLOWED = {
    "SPI-02",
    "SPI-03",
    "SPI-04",
    "BTC-04",
    "CGD-03",
    "CGD-06",
    "SSC-02",
    "SSC-03",
    "SSC-04",
    "OWM-02",
    "DCR-03",
    "RRO-01",
    "RRO-02",
    "RRO-03",
    "RRO-04",
    "RLP-02",
    "RLP-03",
}


def resolved_repository_facts(config: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """Resolve configured tri-state declarations against safely observed facts."""

    repository = config["repository"]
    automatic = {
        "has_dependencies": bool(local.get("dependency_files")),
        "has_automation": bool(local.get("workflows")),
        "has_proposed_change_validation": bool(local.get("workflows")),
        "multi_contributor": (local.get("contributor_count") or 0) > 1 if local.get("contributor_count") is not None else None,
        "has_work_refs": (local.get("branch_count") or 0) > 1 if local.get("branch_count") is not None else None,
    }
    result: dict[str, Any] = {}
    for key, configured in repository.items():
        if key.startswith("has_") or key in {"publishes_artifacts", "multi_contributor", "supported", "automated_deployment", "operated_service", "portfolio_managed"}:
            result[key] = tri_state(configured, automatic.get(key))
        else:
            result[key] = configured
    return result


def applicability(control_id: str, facts: dict[str, Any]) -> tuple[bool, str]:
    """Apply catalog tier/type/lifecycle conditions without guessing unknowns."""

    risk = facts["risk_tier"]
    elevated = RISK_ORDER[risk] >= RISK_ORDER["Elevated"]
    lifecycle = facts["lifecycle"]
    active = lifecycle in ACTIVE_LIFECYCLES

    condition: bool | None = True
    reason = "Universal catalog applicability for the classified repository."
    if control_id == "SPI-02":
        condition, reason = facts.get("has_current_output"), "Requires a current deployed, published, distributed, applied, or supported output."
    elif control_id == "SPI-03":
        condition, reason = (True if elevated else facts.get("publishes_artifacts")), "Elevated/Critical or a Baseline reusable-artifact publisher."
    elif control_id == "SPI-04":
        condition, reason = (True if elevated else facts.get("has_current_output")), "Elevated/Critical or a Baseline repository with deployed/published output."
    elif control_id in {"BTC-01", "BTC-02", "BTC-03", "CGD-04", "CGD-05", "SSC-01", "OWM-01", "OWM-03", "DCR-01", "DCR-02"}:
        condition, reason = active, "Applies to active repositories under the catalog lifecycle rule."
    elif control_id == "BTC-04":
        condition, reason = facts.get("has_proposed_change_validation"), "Requires proposed-change validation."
    elif control_id == "BTC-05":
        condition, reason = facts.get("has_automation"), "Requires automated validation."
    elif control_id == "CGD-03":
        condition, reason = (True if elevated else facts.get("multi_contributor")), "Required at Elevated/Critical and expected where Baseline has multiple trusted contributors."
    elif control_id == "SSC-02":
        condition, reason = facts.get("has_dependencies"), "Requires direct software, action, image, module, plugin, model, or data dependencies."
    elif control_id == "SSC-03":
        dependencies = facts.get("has_dependencies")
        artifacts = facts.get("has_produced_artifacts")
        condition = True if dependencies is True or artifacts is True else False if dependencies is False and artifacts is False else None
        reason = "Requires dependencies or produced software artifacts."
    elif control_id == "SSC-04":
        condition, reason = facts.get("has_automation"), "Requires repository automation."
    elif control_id == "OWM-02":
        condition, reason = (True if elevated else facts.get("has_critical_paths")), "Required at Elevated/Critical and for designated Baseline critical paths."
    elif control_id == "DCR-03":
        condition, reason = facts.get("supported"), "Requires a supported repository or continuing security-response obligation."
    elif control_id == "RRO-01":
        current = facts.get("has_current_output")
        published = facts.get("publishes_artifacts")
        condition = True if elevated or current is True or published is True else False if current is False and published is False else None
        reason = "Elevated/Critical or a Baseline repository with a current/recent supported output."
    elif control_id == "RRO-02":
        condition, reason = facts.get("has_current_output"), "Requires a current operational or supported output."
    elif control_id == "RRO-03":
        condition, reason = (True if elevated else facts.get("automated_deployment")), "Elevated/Critical or Baseline automated deployment/publication."
    elif control_id == "RRO-04":
        operated = facts.get("operated_service")
        current = facts.get("has_current_output")
        condition = True if elevated or operated is True else False if operated is False and current is False else None
        reason = "Elevated/Critical or an operated service, pipeline, infrastructure, or supported package."
    elif control_id == "RLP-02":
        condition = facts.get("has_work_refs") if active else False
        reason = "Active repository with work, release, environment, or maintenance refs."
    elif control_id == "RLP-03":
        condition = (
            True
            if lifecycle in {"Archived", "Retired"}
            else False
            if lifecycle in {"Active", "Stable-supported", "Experimental", "Mirrored"}
            else None
        )
        reason = "Applies only to archived or retired lifecycle states."
    elif control_id == "RLP-04":
        condition, reason = facts.get("portfolio_managed"), "Requires portfolio-managed scope; unknown scope remains assessable rather than presumed N/A."

    if condition is False and control_id == "RLP-03":
        # The catalog explicitly declares active repositories N/A for the
        # retirement-only control. Other conditional exclusions still require
        # an approved, evidence-backed N/A record rather than a lone boolean.
        return False, f"N/A under explicit catalog lifecycle rule: {reason}"
    if condition is False:
        return True, f"The repository declaration indicates a possible catalog exclusion, but N/A requires an approved evidence record. {reason}"
    if condition is None:
        return True, f"Applicability evidence is Unknown; retained in scope. {reason}"
    return True, reason


def _result(
    conformance: str,
    assurance: str,
    rationale: str,
    evidence_ids: list[str] | tuple[str, ...] = (),
    source: str = "automated",
    gate_status: str | None = None,
    gate_rationale: str | None = None,
) -> dict[str, Any]:
    return {
        "conformance": conformance,
        "assurance": assurance,
        "rationale": rationale,
        "evidence_ids": list(evidence_ids),
        "source": source,
        "gate_status": gate_status,
        "gate_rationale": gate_rationale,
    }


def _github_prs(github: dict[str, Any]) -> list[dict[str, Any]] | None:
    pulls = github.get("data", {}).get("pull_requests")
    return pulls if isinstance(pulls, list) else None


def _github_releases(github: dict[str, Any]) -> list[dict[str, Any]] | None:
    releases = github.get("data", {}).get("releases")
    return releases if isinstance(releases, list) else None


def automatic_control_result(control: Control, local: dict[str, Any], github: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Evaluate what the collected evidence actually establishes.

    Most catalog controls require demonstrated operational evidence (E3). File
    presence and a configured GitHub setting are therefore commonly Partial,
    never inflated to Met merely because a similarly named file exists.
    """

    cid = control.control_id
    docs = local.get("documents", {})
    workflows = local.get("workflows", [])
    check_state, check_names = github_check_state(github, list(facts.get("authoritative_checks", [])))
    protection = github_protection_state(github)
    prs = _github_prs(github)
    releases = _github_releases(github)

    if cid == "SPI-01":
        if check_state == "failed":
            return _result(
                "Unmet",
                "E3",
                "One or more authoritative checks for the assessed Main revision failed.",
                ["E-GH-CHECKS"],
                gate_status="Fail",
                gate_rationale="The exact current Main revision failed authoritative validation.",
            )
        if check_state == "successful" and check_names:
            return _result(
                "Unknown",
                "E3",
                "The exact Main revision passed its configured authoritative checks, but Main invalid-duration trend evidence was unavailable for the full control score.",
                ["E-LOCAL-GIT", "E-GH-CHECKS"],
                gate_status="Pass",
                gate_rationale="All configured authoritative build, validation, and type-specific releasability checks succeeded for the exact current Main revision.",
            )
        if check_state == "pending":
            return _result("Unknown", "E0", "Checks for the assessed Main revision have not reached a terminal state.", gate_status="Unknown")
        return _result("Unknown", "E0", "No authoritative successful result bound to the exact assessed Main revision was available.", gate_status="Unknown")

    if cid in {"SPI-02", "SPI-04", "RRO-02", "RRO-03", "RRO-04"}:
        return _result("Unknown", "E0", "The repository and GitHub source evidence do not establish current runtime/publication identity or operational exercise evidence.")

    if cid == "SPI-03":
        if releases:
            immutable = all(release.get("tag_name") and not release.get("draft") for release in releases)
            if immutable:
                return _result("Partially met", "E2", "Release identities are visible, but artifact immutability and provenance were not demonstrated.", ["E-GH-RELEASES"])
        return _result("Unknown", "E0", "No complete release identity, artifact digest, and provenance chain was available.")

    if cid == "BTC-01":
        if not workflows:
            return _result("Unknown", "E0", "No GitHub Actions workflow was found, but the bounded collector cannot exclude another version-controlled authoritative validation path.")
        if check_state == "successful":
            return _result("Met", "E3", "Version-controlled automation has a successful exact-revision execution.", ["E-LOCAL-WORKFLOWS", "E-GH-CHECKS"])
        return _result("Partially met", "E2", "Version-controlled automation exists, but a successful clean replay was not demonstrated.", ["E-LOCAL-WORKFLOWS"])

    if cid in {"BTC-02", "BTC-03"}:
        if not workflows:
            return _result("Unknown", "E0", "No GitHub Actions validation workflow was found, but external or alternate per-change validation was not assessed.")
        if prs and check_state == "successful":
            return _result("Partially met", "E3", "Change and exact-revision evidence exists, but complete event/category coverage was not established.", ["E-LOCAL-WORKFLOWS", "E-GH-PRS", "E-GH-CHECKS"])
        return _result("Partially met", "E2", "Validation automation is configured, but complete per-change demonstrated coverage is unavailable.", ["E-LOCAL-WORKFLOWS"])

    if cid in {"BTC-04", "BTC-05"}:
        return _result("Unknown", "E0", "Comparable CI timing/rerun event history needed by the threshold was not collected.")

    if cid == "CGD-01":
        if protection == "unprotected":
            return _result("Unmet", "E2", "Main is reported unprotected, so the controlled acceptance path is not enforced at the host boundary.", ["E-GH-PROTECTION"])
        if protection == "configured" and prs:
            return _result("Partially met", "E3", "Protected configuration and accepted-change records exist, but complete Main-change and bypass coverage was not established.", ["E-GH-PROTECTION", "E-GH-PRS"])
        return _result("Unknown", "E0", "Complete accepted-change and bypass audit evidence is unavailable.")

    if cid == "CGD-02":
        if protection == "unprotected":
            return _result("Unmet", "E2", "GitHub reports Main is not protected.", ["E-GH-PROTECTION"])
        if protection in {"configured", "protected_details_unknown"}:
            return _result("Partially met", "E2", "Main protection is configured, but complete critical-ref coverage and tested effective behavior were not demonstrated.", ["E-GH-PROTECTION"])
        return _result("Unknown", "E0", "Protection details are inaccessible; absence is not inferred from a 403/404 or network gap.")

    if cid == "CGD-03":
        if prs:
            reviewed = [pr for pr in prs if pr.get("merged_at")]
            if reviewed:
                return _result("Partially met", "E3", "Merged pull requests are visible, but final-revision independent approval coverage was not completely established.", ["E-GH-PRS"])
        return _result("Unknown", "E0", "Final-revision authorship and independent approval evidence is unavailable.")

    if cid == "CGD-04":
        if protection == "unprotected":
            return _result("Unmet", "E2", "Main is unprotected, so required checks cannot be relied upon as an enforced acceptance boundary.", ["E-GH-PROTECTION"])
        if protection == "configured":
            return _result("Partially met", "E2", "Required-check configuration is visible, but complete final-revision enforcement history was not demonstrated.", ["E-GH-PROTECTION"])
        return _result("Unknown", "E0", "Effective required-check enforcement and bypass evidence is unavailable.")

    if cid == "CGD-05":
        if facts.get("methodology") in {"", "Unknown", "Unclassified"}:
            return _result("Unknown", "E1", "No classified methodology contract is declared.", ["E-CONFIG-CLASSIFICATION"])
        if prs is not None:
            return _result("Partially met", "E2", "A methodology is declared and branch/merge events are visible, but complete profile-rule and reconciliation conformance was not measured.", ["E-CONFIG-CLASSIFICATION", "E-GH-PRS"])
        return _result("Partially met", "E1", "A methodology is declared without demonstrated event-conformance evidence.", ["E-CONFIG-CLASSIFICATION"])

    if cid == "CGD-06":
        return _result("Unknown", "E0", "GitHub repository APIs do not provide a complete privileged-event and audit-log population to this collector.")

    if cid == "SSC-01":
        return _result("Unknown", "E0", "Current and reachable-history secret scanning plus response records were not available as a complete population.")

    if cid == "SSC-02":
        dependencies = local.get("dependency_files", [])
        locks = local.get("lock_files", [])
        if dependencies and locks:
            return _result("Partially met", "E2", "Dependency manifests and lock inventories exist, but fresh discovery reconciliation and release-linked inventory were not demonstrated.", ["E-LOCAL-DEPS"])
        if dependencies:
            return _result("Partially met", "E2", "Dependency declarations exist without a complete discovered/locked inventory.", ["E-LOCAL-DEPS"])
        return _result("Unknown", "E0", "No fresh dependency discovery scan is available to prove either inventory coverage or N/A.")

    if cid == "SSC-03":
        return _result("Unknown", "E0", "A complete vulnerability finding population, ownership, due dates, and dispositions was not available.")

    if cid == "SSC-04":
        if workflows:
            return _result("Partially met", "E2", "Version-controlled workflows were found, but exact-revision permission, pinning, and secret-release analysis was not demonstrated.", ["E-LOCAL-WORKFLOWS"])
        return _result("Unknown", "E0", "Automation is applicable, but no GitHub Actions workflow was found and alternate automation was not available to inspect.")

    if cid == "OWM-01":
        owner = str(facts.get("owner", "")).strip()
        if owner and docs.get("ownership") and facts.get("lifecycle") != "Unknown" and facts.get("risk_tier"):
            return _result("Partially met", "E2", "Technical ownership, lifecycle, and risk are declared, but support/business ownership and successful identity resolution are incomplete.", ["E-CONFIG-CLASSIFICATION", "E-LOCAL-DOCS"])
        if not owner and not docs.get("ownership"):
            return _result("Unmet", "E2", "No active technical owner declaration or ownership file was found.", ["E-CONFIG-CLASSIFICATION", "E-LOCAL-DOCS"])
        return _result("Partially met", "E1", "Some ownership metadata exists, but the complete resolvable ownership record is unavailable.", ["E-CONFIG-CLASSIFICATION"])

    if cid == "OWM-02":
        if docs.get("codeowners"):
            return _result("Partially met", "E2", "CODEOWNERS exists, but critical-path classification and active membership/continuity were not fully established.", ["E-LOCAL-DOCS"])
        return _result("Unknown", "E0", "No complete critical-path inventory, owner mapping, and active membership evidence was available.")

    if cid == "OWM-03":
        return _result("Unknown", "E0", "A current owner-resolved toolchain and technical-obligation register was not identified by the bounded collector.")

    if cid == "OWM-04":
        return _result("Unknown", "E0", "No exact-revision binary/generated-artifact classification scan was run; repository-owned content was not executed.")

    if cid == "DCR-01":
        if not docs.get("readme"):
            return _result("Unmet", "E2", "No root orientation README was found, so purpose and validation instructions cannot be established.", ["E-LOCAL-DOCS"])
        return _result("Partially met", "E2", "A README exists, but all required orientation topics and a verified validation command were not established.", ["E-LOCAL-DOCS"])

    if cid == "DCR-02":
        if docs.get("contributing"):
            return _result("Partially met", "E2", "Contribution guidance exists, but all methodology, release, backport, and bypass topics were not reconciled with enforcement.", ["E-LOCAL-DOCS"])
        return _result("Unmet", "E2", "No contribution/change-path guide was found.", ["E-LOCAL-DOCS"])

    if cid == "DCR-03":
        if docs.get("security") and (docs.get("support") or docs.get("readme")):
            return _result("Partially met", "E2", "Support/security route documents exist, but monitored ownership and successful route tests were not demonstrated.", ["E-LOCAL-DOCS"])
        return _result("Unmet", "E2", "One or more required support/private-security route documents were not found.", ["E-LOCAL-DOCS"])

    if cid == "DCR-04":
        if not docs.get("license"):
            return _result("Unmet", "E2", "No usage-rights declaration was found; rights are never N/A.", ["E-LOCAL-DOCS"])
        if releases and not docs.get("changelog"):
            return _result("Partially met", "E2", "Rights are declared, but release-change documentation is incomplete.", ["E-LOCAL-DOCS", "E-GH-RELEASES"])
        return _result("Partially met", "E2", "Rights are declared, but full versioning/compatibility/release documentation applicability was not established.", ["E-LOCAL-DOCS"])

    if cid == "RRO-01":
        if releases:
            return _result("Partially met", "E3", "Durable release records exist, but complete source/artifact/approval/deployment field coverage was not established.", ["E-GH-RELEASES"])
        return _result("Unknown", "E0", "No complete eligible release/deployment/publication record population was available.")

    if cid == "RLP-01":
        required = [facts.get("type"), facts.get("lifecycle"), facts.get("risk_tier"), facts.get("owner")]
        known = sum(bool(value and value != "Unknown") for value in required)
        if known == len(required) and facts.get("portfolio_managed") is True:
            return _result("Partially met", "E2", "Core classification is present, but a complete owner-confirmed portfolio record and output inventory were not established.", ["E-CONFIG-CLASSIFICATION"])
        if known < 3:
            return _result("Unmet", "E1", "Authoritative repository, type/owner, lifecycle, or risk classification is materially incomplete.", ["E-CONFIG-CLASSIFICATION"])
        return _result("Partially met", "E1", "Repository classification is declared but not reconciled to a complete portfolio record.", ["E-CONFIG-CLASSIFICATION"])

    if cid == "RLP-02":
        branches = local.get("branches")
        if isinstance(branches, list):
            return _result("Partially met", "E2", "A current local ref inventory is available, but approved profile SLOs and complete event/EOL dispositions were not demonstrated.", ["E-LOCAL-GIT"])
        return _result("Unknown", "E0", "A complete current ref inventory and profile SLO are unavailable.")

    if cid == "RLP-03":
        return _result("Unknown", "E0", "Retirement notice, consumers, credentials, automation, and retention evidence were not completely established.")

    if cid == "RLP-04":
        return _result("Unknown", "E0", "The local repository and GitHub API cannot establish portfolio-wide authority uniqueness or every copy relationship.")

    return _result("Unknown", "E0", "No bounded automated evidence rule establishes this control.")


def _apply_override(control: Control, override: dict[str, Any]) -> dict[str, Any]:
    conformance = override["conformance"]
    assurance = override["assurance"]
    rationale = override["rationale"].strip()
    evidence_ids = list(override.get("evidence_ids", []))
    if conformance == "Met" and ASSURANCE_ORDER[assurance] < ASSURANCE_ORDER[control.minimum_assurance]:
        if assurance == "E0":
            conformance = "Unknown"
            rationale += f" Evidence is below the {control.minimum_assurance} floor and cannot establish conformance."
        else:
            conformance = "Partially met"
            rationale += f" Evidence is below the {control.minimum_assurance} floor required for Met."
    elif conformance in {"Unmet", "Partially met"} and assurance == "E0":
        conformance = "Unknown"
        rationale += " E0 cannot establish a positive or negative observed condition."
    return _result(
        conformance,
        assurance,
        rationale,
        evidence_ids,
        "configured",
        override.get("gate_status"),
        override.get("gate_rationale"),
    )


def evaluate_controls(catalog: Catalog, config: dict[str, Any], local: dict[str, Any], github: dict[str, Any]) -> list[dict[str, Any]]:
    facts = resolved_repository_facts(config, local)
    known_ids = {control.control_id for control in catalog.controls}
    extra_overrides = set(config.get("controls", {})) - known_ids
    if extra_overrides:
        raise ValueError(f"Unknown control override IDs: {', '.join(sorted(extra_overrides))}")

    results: list[dict[str, Any]] = []
    for control in catalog.controls:
        applies, applicability_reason = applicability(control.control_id, facts)
        override = config.get("controls", {}).get(control.control_id)
        if override:
            catalog_exclusion = (
                not applies
                or applicability_reason.startswith(
                    "The repository declaration indicates a possible catalog exclusion"
                )
            )
            if (
                override.get("conformance") == "N/A"
                and not catalog_exclusion
                and control.control_id not in FULL_CONTROL_NA_ALLOWED
            ):
                raise ValueError(
                    f"{control.control_id} does not permit a whole-control N/A determination for this repository; use Unknown or an item-level result"
                )
            if override.get("gate_status") and not control.gate:
                raise ValueError(f"{control.control_id} is not a foundational gate and cannot set gate_status")
            if override.get("gate_status") == "N/A" and override.get("conformance") != "N/A":
                raise ValueError(f"{control.control_id} gate_status N/A requires an approved N/A control result")
            observed = _apply_override(control, override)
            if override["conformance"] == "N/A":
                applies = False
                applicability_reason = f"Approved N/A by {override['n_a_approved_by']}: {override['rationale']}"
            elif not applies:
                # A configured evidence result is allowed to demonstrate that
                # the repository is actually in scope, avoiding a false N/A.
                applies = True
                applicability_reason = "Repository-specific evidence override establishes applicability."
        elif not applies:
            observed = _result("N/A", "E0", applicability_reason)
        elif applicability_reason.startswith("The repository declaration indicates a possible catalog exclusion"):
            observed = _result(
                "Unknown",
                "E1",
                "A possible applicability exclusion is declared, but no approved evidence-backed N/A determination was supplied.",
                ["E-CONFIG-CLASSIFICATION"],
            )
        else:
            observed = automatic_control_result(control, local, github, facts)

        content_evidence = {"E-LOCAL-DOCS", "E-LOCAL-WORKFLOWS", "E-LOCAL-DEPS"}
        exact_main_content = local.get("working_tree_clean") is True and local.get("head_is_main") is True
        if (
            observed["source"] == "automated"
            and observed["assurance"] == "E2"
            and content_evidence.intersection(observed["evidence_ids"])
            and not exact_main_content
        ):
            observed["assurance"] = "E1"
            observed["rationale"] += " Local file evidence was not proven to be the clean exact Main revision."
            if observed["conformance"] == "Unmet":
                observed["conformance"] = "Unknown"

        points = CONFORMANCE_POINTS[observed["conformance"]]
        results.append(
            {
                "control_id": control.control_id,
                "title": control.title,
                "dimension": control.dimension,
                "gate": control.gate,
                "applicable": applies,
                "applicability_reason": applicability_reason,
                "conformance": observed["conformance"],
                "points": points,
                "assurance": observed["assurance"],
                "minimum_assurance": control.minimum_assurance,
                "evidence_ids": observed["evidence_ids"],
                "rationale": observed["rationale"],
                "remediation": control.remediation,
                "source": observed["source"],
                "gate_status": observed.get("gate_status"),
                "gate_rationale": observed.get("gate_rationale"),
                "measurement_ids": list(control.measurement_ids),
                "source_ids": list(control.source_ids),
            }
        )
    return results


def grade_maturity(score: float) -> tuple[str, str]:
    if score >= 90:
        return "A", "M4 — Leading"
    if score >= 80:
        return "B", "M3 — Managed"
    if score >= 70:
        return "C", "M2 — Defined"
    if score >= 60:
        return "D", "M1 — Developing"
    return "F", "M0 — At Risk"


def summarize(controls: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Calculate equal-dimension scores, gates, final score, and assurance."""

    dimensions: dict[str, Any] = {}
    dimension_unrounded: list[float] = []
    for code, name in DIMENSIONS.items():
        all_in_dimension = [item for item in controls if item["dimension"] == code]
        applicable_controls = [item for item in all_in_dimension if item["applicable"]]
        if applicable_controls:
            value = sum(float(item["points"]) for item in applicable_controls) / len(applicable_controls)
            dimension_unrounded.append(value)
            score: float | None = round(value, 1)
        else:
            score = None
        dimensions[code] = {
            "name": name,
            "score": score,
            "applicable_controls": len(applicable_controls),
            "total_controls": len(all_in_dimension),
            "applicability_coverage": round(len(applicable_controls) / len(all_in_dimension) * 100, 1) if all_in_dimension else 0.0,
            "evidence_coverage": round(
                sum(control["assurance"] != "E0" for control in applicable_controls) / len(applicable_controls) * 100,
                1,
            )
            if applicable_controls
            else None,
        }
        dimensions[code]["coverage"] = dimensions[code]["evidence_coverage"]

    raw_unrounded = sum(dimension_unrounded) / len(dimension_unrounded) if dimension_unrounded else 0.0
    gates: dict[str, Any] = {}
    for control in controls:
        gate = control.get("gate")
        if not gate:
            continue
        explicit_gate_status = control.get("gate_status")
        if explicit_gate_status:
            status = explicit_gate_status
            if status == "Pass" and ASSURANCE_ORDER[control["assurance"]] < ASSURANCE_ORDER[control["minimum_assurance"]]:
                status = "Unknown"
        elif not control["applicable"] or control["conformance"] == "N/A":
            status = "N/A"
        elif control["conformance"] == "Unknown":
            status = "Unknown"
        elif control["conformance"] == "Met" and ASSURANCE_ORDER[control["assurance"]] >= ASSURANCE_ORDER[control["minimum_assurance"]]:
            status = "Pass"
        else:
            status = "Fail"
        gates[gate] = {
            "control_id": control["control_id"],
            "status": status,
            "assurance": control["assurance"],
            "rationale": control.get("gate_rationale") or control["rationale"],
        }

    failed_gates = [gate for gate, value in gates.items() if value["status"] in {"Fail", "Unknown"}]
    effective_unrounded = min(raw_unrounded, 69.0) if failed_gates else raw_unrounded
    calculated_grade, calculated_maturity = grade_maturity(raw_unrounded)
    effective_grade, effective_maturity = grade_maturity(effective_unrounded)
    score = {
        "raw": round(raw_unrounded, 1),
        "effective": round(effective_unrounded, 1),
        "cap_active": bool(failed_gates),
        "cap_applied": bool(failed_gates),
        "numeric_cap_changed_score": bool(failed_gates and raw_unrounded > 69.0),
        "cap_reason": f"Foundational gates failed or Unknown: {', '.join(failed_gates)}" if failed_gates else None,
        "calculated_grade": calculated_grade,
        "effective_grade": effective_grade,
        "calculated_maturity": calculated_maturity,
        "effective_maturity": effective_maturity,
    }

    applicable = [control for control in controls if control["applicable"]]
    distribution = Counter(control["assurance"] for control in applicable)
    assurance_index = (
        sum(ASSURANCE_POINTS[control["assurance"]] for control in applicable) / len(applicable)
        if applicable
        else 0.0
    )
    gate_assurance_high = all(
        gate["status"] == "N/A" or ASSURANCE_ORDER[gate["assurance"]] >= ASSURANCE_ORDER["E3"]
        for gate in gates.values()
    )
    assurance_label = "High" if assurance_index >= 75 and gate_assurance_high else "Moderate" if assurance_index >= 50 else "Low"
    assurance = {
        "index": round(assurance_index, 1),
        "label": assurance_label,
        "distribution": {level: distribution.get(level, 0) for level in ASSURANCE_ORDER},
    }
    return dimensions, gates, score, assurance


def findings_from_controls(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    sequence = 1
    for control in controls:
        if not control["applicable"] or control["conformance"] == "Met":
            continue
        if control["gate"] and control.get("gate_status") in {None, "Fail", "Unknown"}:
            priority = "Critical"
        elif control["conformance"] == "Unmet":
            priority = "High"
        elif control["conformance"] == "Unknown":
            priority = "High" if control["assurance"] == "E0" else "Moderate"
        else:
            priority = "Moderate"
        findings.append(
            {
                "finding_id": f"F-{sequence:03d}",
                "control_id": control["control_id"],
                "dimension": control["dimension"],
                "condition": control["rationale"],
                "priority": priority,
                "remediation": control["remediation"],
                "assurance": control["assurance"],
                "gate": control["gate"],
                "gate_status": control.get("gate_status"),
            }
        )
        sequence += 1
    return findings

"""Validate evidence policy and select exact workflow-run populations.

The policy is committed on Main.  It authorizes a workflow, evidence kind, and
exact category set for one repository unit.  Selection is intentionally
separate from artifact validation: this module identifies the one terminal run
whose artifacts may be inspected, but it never authenticates the statement or
assigns assurance.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


POLICY_SCHEMA = "RH-EVIDENCE-POLICY-1.0"
SELECTION_SCHEMA = "RH-EVIDENCE-POLICY-SELECTION-1.0"
RUN_POPULATION_SCHEMA = "RH-ACTIONS-RUN-POPULATION-1.0"
SELECTION_RULE = "latest-completed-exact-subject"

KINDS = frozenset({"validation", "security", "release", "deployment"})
SUBJECT_SOURCES = frozenset({"assessed-main", "production-unit"})
EVENTS = frozenset({"push", "workflow_dispatch", "schedule", "release", "deployment"})

_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CATEGORY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_WORKFLOW = re.compile(r"^\.github/workflows/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:yml|yaml)$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class EvidencePolicyError(ValueError):
    """The committed evidence policy is malformed or conflicts with scope."""


def _valid_ref(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("refs/")
        and ".." not in value
        and not value.endswith("/")
        and "//" not in value
        and not any(character in value for character in (" ", "~", "^", ":", "?", "*", "[", "\\"))
    )


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidencePolicyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_json_bytes(data: bytes, label: str) -> Mapping[str, Any]:
    if len(data) > 256 * 1024:
        raise EvidencePolicyError(f"{label} exceeds the 256 KiB policy limit")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                EvidencePolicyError(f"non-finite JSON value: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidencePolicyError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise EvidencePolicyError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        raise EvidencePolicyError(
            f"{label} fields do not match the schema; missing={missing}, extra={extra}"
        )


def validate_evidence_policy(
    value: Mapping[str, Any],
    *,
    repository: str,
    unit_ids: Sequence[str],
) -> dict[str, Any]:
    """Return a normalized, strict evidence policy for the assessed repository."""

    if not isinstance(value, Mapping):
        raise EvidencePolicyError("evidence policy must be an object")
    if (
        not isinstance(repository, str)
        or _REPOSITORY.fullmatch(repository) is None
        or repository.endswith(".")
    ):
        raise EvidencePolicyError("repository must use owner/name")
    _exact_keys(value, {"schema_version", "repository", "units"}, "policy")
    if value["schema_version"] != POLICY_SCHEMA:
        raise EvidencePolicyError(f"unsupported evidence policy schema: {value['schema_version']!r}")
    if value["repository"] != repository:
        raise EvidencePolicyError("evidence policy repository does not match the assessment")
    declared_units = list(unit_ids)
    if (
        not declared_units
        or any(not isinstance(item, str) or _UNIT.fullmatch(item) is None for item in declared_units)
        or len(declared_units) != len(set(declared_units))
    ):
        raise EvidencePolicyError("unit_ids must contain unique controlled unit identifiers")
    units = value["units"]
    if not isinstance(units, list) or not units:
        raise EvidencePolicyError("policy.units must be a non-empty array")

    normalized_units: list[dict[str, Any]] = []
    observed_unit_ids: list[str] = []
    for unit_index, raw_unit in enumerate(units):
        label = f"policy.units[{unit_index}]"
        if not isinstance(raw_unit, Mapping):
            raise EvidencePolicyError(f"{label} must be an object")
        _exact_keys(raw_unit, {"unit_id", "statements"}, label)
        unit_id = raw_unit["unit_id"]
        if not isinstance(unit_id, str) or _UNIT.fullmatch(unit_id) is None:
            raise EvidencePolicyError(f"{label}.unit_id is invalid")
        if unit_id not in declared_units:
            raise EvidencePolicyError(f"{label}.unit_id is not a declared repository unit")
        observed_unit_ids.append(unit_id)
        statements = raw_unit["statements"]
        if not isinstance(statements, list) or not statements:
            raise EvidencePolicyError(f"{label}.statements must be a non-empty array")
        normalized_statements: list[dict[str, Any]] = []
        kinds: list[str] = []
        for statement_index, raw_statement in enumerate(statements):
            statement_label = f"{label}.statements[{statement_index}]"
            if not isinstance(raw_statement, Mapping):
                raise EvidencePolicyError(f"{statement_label} must be an object")
            _exact_keys(
                raw_statement,
                {
                    "kind",
                    "categories",
                    "workflow_path",
                    "subject_source",
                    "events",
                    "selection",
                },
                statement_label,
            )
            kind = raw_statement["kind"]
            categories = raw_statement["categories"]
            workflow_path = raw_statement["workflow_path"]
            subject_source = raw_statement["subject_source"]
            events = raw_statement["events"]
            selection = raw_statement["selection"]
            if kind not in KINDS:
                raise EvidencePolicyError(f"{statement_label}.kind is invalid")
            kinds.append(kind)
            if (
                not isinstance(categories, list)
                or not categories
                or any(not isinstance(item, str) or _CATEGORY.fullmatch(item) is None for item in categories)
                or categories != sorted(set(categories))
            ):
                raise EvidencePolicyError(
                    f"{statement_label}.categories must be sorted unique controlled identifiers"
                )
            if (
                not isinstance(workflow_path, str)
                or _WORKFLOW.fullmatch(workflow_path) is None
                or ".." in Path(workflow_path).parts
            ):
                raise EvidencePolicyError(f"{statement_label}.workflow_path is invalid")
            if subject_source not in SUBJECT_SOURCES:
                raise EvidencePolicyError(f"{statement_label}.subject_source is invalid")
            if (
                not isinstance(events, list)
                or not events
                or events != sorted(set(events))
                or any(item not in EVENTS for item in events)
            ):
                raise EvidencePolicyError(
                    f"{statement_label}.events must be a sorted unique supported event list"
                )
            if selection != SELECTION_RULE:
                raise EvidencePolicyError(
                    f"{statement_label}.selection must be {SELECTION_RULE!r}"
                )
            normalized_statements.append(
                {
                    "kind": kind,
                    "categories": list(categories),
                    "workflow_path": workflow_path,
                    "subject_source": subject_source,
                    "events": list(events),
                    "selection": selection,
                }
            )
        if len(kinds) != len(set(kinds)):
            raise EvidencePolicyError(
                f"{label} may declare at most one statement policy per evidence kind"
            )
        normalized_units.append(
            {"unit_id": unit_id, "statements": sorted(normalized_statements, key=lambda item: item["kind"])}
        )
    if len(observed_unit_ids) != len(set(observed_unit_ids)):
        raise EvidencePolicyError("policy.units contains a duplicate unit_id")
    return {
        "schema_version": POLICY_SCHEMA,
        "repository": repository,
        "units": sorted(normalized_units, key=lambda item: item["unit_id"]),
    }


def load_evidence_policy(
    source: str | Path | bytes,
    *,
    repository: str,
    unit_ids: Sequence[str],
    source_sha: str,
    source_path: str = ".github/repository-health-evidence-policy.json",
) -> dict[str, Any]:
    """Load strict JSON and bind it to the authoritative assessed-Main blob."""

    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    if not isinstance(source_sha, str) or _SHA.fullmatch(source_sha) is None:
        raise EvidencePolicyError("source_sha must bind the policy to a lowercase full Git SHA")
    if (
        not isinstance(source_path, str)
        or not source_path
        or source_path.startswith("/")
        or ".." in Path(source_path).parts
        or "\\" in source_path
    ):
        raise EvidencePolicyError("source_path must be a safe repository-relative path")
    policy = validate_evidence_policy(
        _load_json_bytes(data, "evidence policy"),
        repository=repository,
        unit_ids=unit_ids,
    )
    policy["_source"] = {
        "sha": source_sha,
        "path": source_path,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    return policy


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _run_path(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, None
    if "@" not in value:
        return (value if _WORKFLOW.fullmatch(value) is not None else None), None
    path, ref = value.rsplit("@", 1)
    return (path if _WORKFLOW.fullmatch(path) is not None else None), (ref or None)


def _short_ref(ref: str) -> str:
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    return ref


def _run_matches_workflow(
    run: Mapping[str, Any],
    *,
    repository: str,
    workflow_path: str,
    subject_ref: str,
    subject_sha: str,
) -> bool:
    expected_workflow_ref = f"{repository}/{workflow_path}@{subject_ref}"
    if (
        run.get("workflow_ref") == expected_workflow_ref
        and run.get("workflow_sha") == subject_sha
    ):
        return True
    path, run_ref = _run_path(run.get("path"))
    short_ref = _short_ref(subject_ref)
    return bool(
        path == workflow_path
        and run_ref in {subject_ref, short_ref}
        and run.get("head_branch") == short_ref
    )


def _population_covers(
    data: Mapping[str, Any],
    *,
    subject_source: str,
    subject_sha: str,
    subject_ref: str,
) -> bool:
    contract = data.get("population_contract")
    if not isinstance(contract, Mapping) or set(contract) != {
        "schema_version",
        "scope",
        "branch_ref",
        "subjects",
    }:
        return False
    if contract.get("schema_version") != RUN_POPULATION_SCHEMA:
        return False
    subjects = contract.get("subjects")
    if not isinstance(subjects, list):
        return False
    if subject_source == "assessed-main":
        return bool(
            contract.get("scope") == "branch-window"
            and contract.get("branch_ref") == subject_ref
        )
    return bool(
        contract.get("scope") == "exact-subjects"
        and contract.get("branch_ref") is None
        and {"sha": subject_sha, "ref": subject_ref} in subjects
    )


def _subject(
    unit_id: str,
    subject_source: str,
    *,
    main_sha: str,
    main_branch: str,
    production_subjects: Mapping[str, Any],
) -> tuple[str, str] | None:
    if subject_source == "assessed-main":
        return main_sha, f"refs/heads/{main_branch}"
    raw = production_subjects.get(unit_id)
    if not isinstance(raw, Mapping):
        return None
    sha = raw.get("sha")
    ref = raw.get("ref")
    if (
        not isinstance(sha, str)
        or _SHA.fullmatch(sha) is None
        or not _valid_ref(ref)
    ):
        return None
    return sha, ref


def select_eligible_runs(
    policy: Mapping[str, Any],
    *,
    actions_observation: Mapping[str, Any] | None,
    main_sha: str,
    main_branch: str,
    production_subjects: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select one unambiguous terminal workflow run for each policy entry.

    ``policy`` must already have passed :func:`validate_evidence_policy`.
    ``actions_observation`` is a complete collector group whose
    ``data.workflow_runs`` population covers every declared subject.  A caller
    that supplies only Main-filtered history cannot select production-tag runs;
    those entries remain Unknown until a targeted complete population is joined.
    """

    repository = policy.get("repository") if isinstance(policy, Mapping) else None
    source_binding = policy.get("_source") if isinstance(policy, Mapping) else None
    if (
        policy.get("schema_version") != POLICY_SCHEMA
        or not isinstance(repository, str)
        or _REPOSITORY.fullmatch(repository) is None
        or not isinstance(policy.get("units"), list)
        or not isinstance(source_binding, Mapping)
    ):
        raise EvidencePolicyError("policy must be validated and bound to an exact Main blob")
    if not isinstance(main_sha, str) or _SHA.fullmatch(main_sha) is None:
        raise EvidencePolicyError("main_sha must be a lowercase full Git SHA")
    if source_binding.get("sha") != main_sha:
        raise EvidencePolicyError("policy source SHA does not match the assessed Main SHA")
    main_ref = f"refs/heads/{main_branch}" if isinstance(main_branch, str) else None
    if not _valid_ref(main_ref):
        raise EvidencePolicyError("main_branch is invalid")
    production_subjects = production_subjects or {}
    gaps: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    eligible: dict[int, set[str]] = defaultdict(set)
    category_policy: dict[str, dict[str, dict[str, list[str]]]] = {}

    group_complete = (
        isinstance(actions_observation, Mapping)
        and actions_observation.get("complete") is True
        and actions_observation.get("population_complete") is True
        and isinstance(actions_observation.get("data"), Mapping)
        and isinstance(actions_observation["data"].get("workflow_runs"), list)
    )
    runs = actions_observation["data"]["workflow_runs"] if group_complete else []
    actions_data = actions_observation["data"] if group_complete else {}
    if not group_complete:
        gaps.append(
            {
                "kind": "actions_population_incomplete",
                "unit_id": None,
                "evidence_kind": None,
                "message": "A complete Actions run population is required before selecting eligible evidence runs.",
            }
        )

    selected_claims: list[tuple[int, str]] = []
    for unit in policy["units"]:
        unit_id = unit["unit_id"]
        category_policy[unit_id] = {}
        for statement in unit["statements"]:
            kind = statement["kind"]
            resolved_subject = _subject(
                unit_id,
                statement["subject_source"],
                main_sha=main_sha,
                main_branch=main_branch,
                production_subjects=production_subjects,
            )
            if resolved_subject is None:
                gaps.append(
                    {
                        "kind": "subject_identity_unavailable",
                        "unit_id": unit_id,
                        "evidence_kind": kind,
                        "message": "The declared evidence subject could not be resolved to an exact ref and SHA.",
                    }
                )
                continue
            subject_sha, subject_ref = resolved_subject
            workflow_ref = f"{repository}/{statement['workflow_path']}@{subject_ref}"
            category_policy[unit_id][kind] = {
                "categories": list(statement["categories"]),
                "workflow_refs": [workflow_ref],
            }
            candidates: list[tuple[datetime, Mapping[str, Any]]] = []
            population_covers = group_complete and _population_covers(
                actions_data,
                subject_source=statement["subject_source"],
                subject_sha=subject_sha,
                subject_ref=subject_ref,
            )
            if not population_covers:
                gaps.append(
                    {
                        "kind": "actions_subject_population_incomplete",
                        "unit_id": unit_id,
                        "evidence_kind": kind,
                        "message": "The Actions population contract does not completely cover the declared subject.",
                    }
                )
            if population_covers:
                for run in runs:
                    if not isinstance(run, Mapping):
                        continue
                    timestamp = _instant(run.get("updated_at") or run.get("run_started_at") or run.get("created_at"))
                    if (
                        run.get("head_sha") != subject_sha
                        or not _run_matches_workflow(
                            run,
                            repository=repository,
                            workflow_path=statement["workflow_path"],
                            subject_ref=subject_ref,
                            subject_sha=subject_sha,
                        )
                        or run.get("event") not in statement["events"]
                        or run.get("status") != "completed"
                        or not isinstance(run.get("conclusion"), str)
                        or not run.get("conclusion")
                        or isinstance(run.get("id"), bool)
                        or not isinstance(run.get("id"), int)
                        or run.get("id") < 1
                        or isinstance(run.get("run_attempt"), bool)
                        or not isinstance(run.get("run_attempt"), int)
                        or run.get("run_attempt") < 1
                        or timestamp is None
                    ):
                        continue
                    candidates.append((timestamp, run))
            if not candidates and population_covers:
                gaps.append(
                    {
                        "kind": "eligible_run_missing",
                        "unit_id": unit_id,
                        "evidence_kind": kind,
                        "message": "No terminal run exactly matches the controlled workflow, event, and subject.",
                    }
                )
            if not candidates:
                continue
            newest = max(timestamp for timestamp, _ in candidates)
            latest = [run for timestamp, run in candidates if timestamp == newest]
            if len(latest) != 1:
                gaps.append(
                    {
                        "kind": "eligible_run_ambiguous",
                        "unit_id": unit_id,
                        "evidence_kind": kind,
                        "message": "More than one matching run has the newest terminal timestamp.",
                    }
                )
                continue
            run = latest[0]
            run_id = run["id"]
            eligible[run_id].add(unit_id)
            selected_claims.append((run_id, unit_id))
            selections.append(
                {
                    "unit_id": unit_id,
                    "kind": kind,
                    "run_id": run_id,
                    "run_attempt": run["run_attempt"],
                    "subject_sha": subject_sha,
                    "subject_ref": subject_ref,
                    "workflow_ref": workflow_ref,
                    "event": run["event"],
                    "conclusion": run["conclusion"],
                    "completed_at": newest.isoformat().replace("+00:00", "Z"),
                }
            )

    collisions = [claim for claim, count in Counter(selected_claims).items() if count > 1]
    for run_id, unit_id in collisions:
        gaps.append(
            {
                "kind": "run_unit_artifact_collision",
                "unit_id": unit_id,
                "evidence_kind": None,
                "message": (
                    f"Run {run_id} was selected for more than one evidence kind for unit {unit_id}; "
                    "the per-unit artifact name cannot represent both statements."
                ),
            }
        )
        eligible[run_id].discard(unit_id)
    if collisions:
        selections = [
            item for item in selections if (item["run_id"], item["unit_id"]) not in collisions
        ]

    eligible_runs = {
        run_id: sorted(unit_ids)
        for run_id, unit_ids in sorted(eligible.items())
        if unit_ids
    }
    complete = not gaps and bool(selections)
    return {
        "schema_version": SELECTION_SCHEMA,
        "policy_schema_version": POLICY_SCHEMA,
        "policy_source": deepcopy(dict(source_binding)),
        "repository": repository,
        "main_sha": main_sha,
        "state": "selected" if complete else "unknown",
        "complete": complete,
        "population_complete": group_complete,
        "eligible_runs": eligible_runs,
        "category_policy": deepcopy(category_policy),
        "selections": sorted(selections, key=lambda item: (item["unit_id"], item["kind"])),
        "gaps": gaps,
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }


__all__ = [
    "EvidencePolicyError",
    "POLICY_SCHEMA",
    "RUN_POPULATION_SCHEMA",
    "SELECTION_SCHEMA",
    "SELECTION_RULE",
    "load_evidence_policy",
    "select_eligible_runs",
    "validate_evidence_policy",
]

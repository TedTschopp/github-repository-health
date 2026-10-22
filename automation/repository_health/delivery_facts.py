"""Trusted, read-only construction of Main delivery facts.

The delivery resolver deliberately accepts only small controlled facts for Git
ancestry and intervening Main checks.  Those facts must not be supplied by a
repository-authored evidence statement.  This module constructs them inside
the assessor from an exact local Git object graph and a complete GitHub Actions
observation.

No assessed repository code is imported or executed.  Git is invoked only for
read operations, with hooks, the filesystem monitor, replacement objects,
system/global configuration, prompts, pagers, and optional locks disabled.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
import os
import re
import subprocess
from typing import Any

from .delivery_resolution import ANCESTRY_FACT_SCHEMA, INTERVENING_CHECK_FACT_SCHEMA


FACT_BUILDER_SCHEMA = "RH-DELIVERY-FACT-BUILDER-1.0"
ACTIONS_RUN_POPULATION_SCHEMA = "RH-ACTIONS-RUN-POPULATION-1.0"
DEFAULT_MAX_REVISIONS = 5_000
DEFAULT_GIT_TIMEOUT_SECONDS = 20

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_WORKFLOW_PATH = re.compile(r"^\.github/workflows/[A-Za-z0-9_.\-/]+\.ya?ml$")
_TERMINAL_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
    "success",
    "timed_out",
}
_IDENTITY_KEYS = frozenset(
    {"workflow_id", "workflow_path", "workflow_ref", "job"}
)


class DeliveryFactError(ValueError):
    """Raised for an unsafe caller contract, never for incomplete evidence."""


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_workflow_ref(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value.startswith("refs/heads/")
        or len(value) > 512
        or value.endswith(("/", ".", ".lock"))
        or "//" in value
        or ".." in value
        or "@" in value
        or any(character in value for character in " ~^:?*[\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    parts = value.split("/")
    return bool(
        len(parts) >= 3
        and all(part and not part.startswith(".") and not part.endswith(".lock") for part in parts)
    )


def _parse_run_workflow_path(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    workflow_path, separator, workflow_ref = value.rpartition("@")
    if (
        separator != "@"
        or _WORKFLOW_PATH.fullmatch(workflow_path) is None
        or ".." in workflow_path.split("/")
        or not _valid_workflow_ref(workflow_ref)
    ):
        return None
    return workflow_path, workflow_ref


def _gap(unit_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {"unit_id": unit_id, "code": code, "message": message}


def _ancestry_fact(
    repository: str,
    unit_id: str,
    source_sha: str,
    main_sha: str,
    *,
    state: str = "unknown",
    complete: bool = False,
    reachable: bool | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ANCESTRY_FACT_SCHEMA,
        "repository": repository,
        "unit_id": unit_id,
        "source_sha": source_sha,
        "main_sha": main_sha,
        "state": state,
        "population_complete": complete,
        "reachable_from_main": reachable,
    }


def _intervening_fact(
    repository: str,
    unit_id: str,
    source_sha: str,
    main_sha: str,
    *,
    state: str = "unknown",
    complete: bool = False,
    revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": INTERVENING_CHECK_FACT_SCHEMA,
        "repository": repository,
        "unit_id": unit_id,
        "source_sha": source_sha,
        "main_sha": main_sha,
        "state": state,
        "population_complete": complete,
        "revisions": list(revisions or []),
    }


def _git(
    root: Path,
    *arguments: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str] | None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "PAGER": "cat",
    }
    try:
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.commitGraph=false",
                "-c",
                "pager.log=false",
                "-c",
                "pager.show=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _known_commit(root: Path, sha: str, *, timeout_seconds: int) -> bool:
    result = _git(
        root,
        "rev-parse",
        "--verify",
        f"{sha}^{{commit}}",
        timeout_seconds=timeout_seconds,
    )
    return bool(
        result is not None
        and result.returncode == 0
        and result.stdout.strip() == sha
    )


def _is_shallow(root: Path, *, timeout_seconds: int) -> bool | None:
    result = _git(
        root,
        "rev-parse",
        "--is-shallow-repository",
        timeout_seconds=timeout_seconds,
    )
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _reachable(
    root: Path,
    source_sha: str,
    main_sha: str,
    *,
    timeout_seconds: int,
) -> bool | None:
    result = _git(
        root,
        "merge-base",
        "--is-ancestor",
        source_sha,
        main_sha,
        timeout_seconds=timeout_seconds,
    )
    if result is None:
        return None
    if result.returncode == 0:
        return True
    # ``merge-base --is-ancestor`` reserves status 1 for a known
    # non-ancestor.  Git may still emit platform warnings on stderr; operational
    # failures use another status and must remain Unknown.
    if result.returncode == 1:
        return False
    return None


def _first_parent_range(
    root: Path,
    source_sha: str,
    main_sha: str,
    *,
    max_revisions: int,
    timeout_seconds: int,
) -> tuple[list[str] | None, str | None]:
    if source_sha == main_sha:
        return [], None
    result = _git(
        root,
        "rev-list",
        "--first-parent",
        "--reverse",
        "--parents",
        f"--max-count={max_revisions + 1}",
        f"{source_sha}..{main_sha}",
        timeout_seconds=timeout_seconds,
    )
    if result is None or result.returncode != 0:
        return None, "first_parent_unavailable"
    lines = [line for line in result.stdout.splitlines() if line]
    if len(lines) > max_revisions:
        return None, "first_parent_budget"
    expected_parent = source_sha
    revisions: list[str] = []
    for line in lines:
        parts = line.split()
        if not parts or not all(_is_sha(part) for part in parts):
            return None, "first_parent_malformed"
        revision = parts[0]
        if len(parts) < 2 or parts[1] != expected_parent:
            # Reachability through a non-first-parent merge is not sufficient
            # to reconstruct accepted Main revisions after the source.
            return None, "source_not_on_first_parent"
        revisions.append(revision)
        expected_parent = revision
    if not revisions or revisions[-1] != main_sha:
        return None, "first_parent_incomplete"
    if len(revisions) != len(set(revisions)):
        return None, "first_parent_duplicate"
    return revisions, None


def _configured_checks(config: Mapping[str, Any]) -> tuple[list[str] | None, str | None]:
    repository = config.get("repository") if isinstance(config, Mapping) else None
    checks = repository.get("authoritative_checks") if isinstance(repository, Mapping) else None
    if (
        not isinstance(checks, list)
        or not checks
        or not all(isinstance(item, str) and item and item == item.strip() for item in checks)
        or len(checks) != len(set(checks))
    ):
        return None, "authoritative_checks_invalid"
    return list(checks), None


def _check_identities(
    config: Mapping[str, Any],
    checks: Sequence[str],
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    repository = config.get("repository") if isinstance(config, Mapping) else None
    raw = (
        repository.get("authoritative_check_identities")
        if isinstance(repository, Mapping)
        else None
    )
    if raw is None:
        return {}, None
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        return None, "check_identities_invalid"
    if not set(raw).issubset(set(checks)):
        return None, "check_identity_not_authoritative"
    identities: dict[str, dict[str, Any]] = {}
    selected_jobs: set[tuple[int, str, str, str]] = set()
    for name, value in raw.items():
        if not isinstance(value, Mapping) or set(value) != _IDENTITY_KEYS:
            return None, "check_identity_invalid"
        workflow_id = value.get("workflow_id")
        workflow_path = value.get("workflow_path")
        workflow_ref = value.get("workflow_ref")
        job = value.get("job")
        if (
            not _positive_int(workflow_id)
            or not isinstance(workflow_path, str)
            or _WORKFLOW_PATH.fullmatch(workflow_path) is None
            or ".." in workflow_path.split("/")
            or not _valid_workflow_ref(workflow_ref)
            or not isinstance(job, str)
            or not job
            or job != job.strip()
        ):
            return None, "check_identity_invalid"
        selector = (workflow_id, workflow_path, workflow_ref, job)
        if selector in selected_jobs:
            return None, "check_identity_duplicate"
        selected_jobs.add(selector)
        identities[name] = {
            "workflow_id": workflow_id,
            "workflow_path": workflow_path,
            "workflow_ref": workflow_ref,
            "job": job,
        }
    return identities, None


def _units(
    production_identity: Mapping[str, Any],
    checks: Sequence[str],
) -> tuple[list[dict[str, str]] | None, str | None]:
    raw_units = production_identity.get("units") if isinstance(production_identity, Mapping) else None
    if not isinstance(raw_units, list) or not raw_units:
        return None, "production_units_invalid"
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_units:
        if not isinstance(raw, Mapping):
            return None, "production_unit_invalid"
        unit_id = raw.get("unit_id")
        correspondence = raw.get("correspondence")
        source_sha = raw.get("source_sha")
        if source_sha is None and isinstance(raw.get("current"), Mapping):
            source_sha = raw["current"].get("source_sha")
        if correspondence == "N/A" and source_sha is None:
            continue
        validation = raw.get("validation")
        declared_checks = (
            validation.get("authoritative_checks")
            if isinstance(validation, Mapping)
            else None
        )
        if (
            not isinstance(unit_id, str)
            or not unit_id
            or unit_id in seen
            or correspondence not in {"Exact-Main", "Releasable-Main", "Production-Ref"}
            or not _is_sha(source_sha)
            or declared_checks != list(checks)
        ):
            return None, "production_unit_contract_invalid"
        seen.add(unit_id)
        result.append(
            {
                "unit_id": unit_id,
                "source_sha": source_sha,
                "correspondence": correspondence,
            }
        )
    if not result:
        return None, "active_production_units_missing"
    return result, None


def _actions_group(observations: Mapping[str, Any]) -> Mapping[str, Any] | None:
    values = observations.get("observations") if isinstance(observations, Mapping) else None
    groups = values if isinstance(values, Mapping) else observations
    group = groups.get("actions_w365") if isinstance(groups, Mapping) else None
    return group if isinstance(group, Mapping) else None


def _complete_action_population(
    observations: Mapping[str, Any],
    *,
    exact_main_sha: str,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]] | None, str | None]:
    group = _actions_group(observations)
    if group is None:
        return None, "actions_population_missing"
    data = group.get("data")
    gaps = group.get("gaps")
    if (
        group.get("state") != "observed"
        or group.get("complete") is not True
        or group.get("population_complete") is not True
        or group.get("subject_sha") != exact_main_sha
        or not isinstance(data, Mapping)
        or not isinstance(gaps, list)
        or gaps
    ):
        return None, "actions_population_incomplete"
    population = data.get("population_contract")
    if (
        not isinstance(population, Mapping)
        or population.get("schema_version") != ACTIONS_RUN_POPULATION_SCHEMA
        or population.get("scope") != "branch-window"
        or not isinstance(population.get("branch_ref"), str)
        or not population["branch_ref"].startswith("refs/heads/")
        or not isinstance(population.get("subjects"), list)
    ):
        return None, "actions_population_contract_invalid"
    budget = data.get("request_budget")
    if (
        not isinstance(budget, Mapping)
        or not _positive_int(budget.get("maximum"))
        or not isinstance(budget.get("used"), int)
        or isinstance(budget.get("used"), bool)
        or budget["used"] < 0
        or budget["used"] > budget["maximum"]
    ):
        return None, "actions_request_budget_unverified"

    workflow_runs = data.get("workflow_runs")
    attempts = data.get("run_attempts")
    if not isinstance(workflow_runs, list) or not isinstance(attempts, list):
        return None, "actions_population_malformed"
    runs_by_id: dict[int, Mapping[str, Any]] = {}
    for raw in workflow_runs:
        if not isinstance(raw, Mapping) or not _positive_int(raw.get("id")):
            return None, "workflow_run_invalid"
        run_id = raw["id"]
        if run_id in runs_by_id:
            return None, "workflow_run_duplicate"
        if (
            not _positive_int(raw.get("run_attempt"))
            or not _is_sha(raw.get("head_sha"))
            or not _positive_int(raw.get("workflow_id"))
            or _parse_run_workflow_path(raw.get("path")) is None
        ):
            return None, "workflow_run_invalid"
        runs_by_id[run_id] = raw

    attempts_by_run: dict[int, dict[int, Mapping[str, Any]]] = defaultdict(dict)
    for raw in attempts:
        if (
            not isinstance(raw, Mapping)
            or not _positive_int(raw.get("run_id"))
            or not _positive_int(raw.get("attempt"))
        ):
            return None, "workflow_attempt_invalid"
        run_id = raw["run_id"]
        attempt_number = raw["attempt"]
        if run_id not in runs_by_id:
            return None, "workflow_attempt_orphan"
        if attempt_number in attempts_by_run[run_id]:
            return None, "workflow_attempt_duplicate"
        run = raw.get("run")
        jobs = raw.get("jobs")
        if (
            raw.get("complete") is not True
            or raw.get("population_complete") is not True
            or not isinstance(run, Mapping)
            or not isinstance(jobs, list)
            or run.get("id") != run_id
            or run.get("run_attempt") != attempt_number
            or run.get("head_sha") != runs_by_id[run_id].get("head_sha")
            or run.get("workflow_id") != runs_by_id[run_id].get("workflow_id")
            or run.get("path") != runs_by_id[run_id].get("path")
            or not isinstance(run.get("status"), str)
        ):
            return None, "workflow_attempt_unverified"
        attempts_by_run[run_id][attempt_number] = raw

    latest_attempts: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for run_id, summary in runs_by_id.items():
        expected = summary["run_attempt"]
        observed = attempts_by_run.get(run_id, {})
        if set(observed) != set(range(1, expected + 1)):
            return None, "workflow_attempt_population_incomplete"
        latest = observed[expected]
        run = latest.get("run")
        jobs = latest.get("jobs")
        if (
            latest.get("complete") is not True
            or latest.get("population_complete") is not True
            or not isinstance(run, Mapping)
            or not isinstance(jobs, list)
            or run.get("id") != run_id
            or run.get("run_attempt") != expected
            or run.get("head_sha") != summary.get("head_sha")
        ):
            return None, "workflow_latest_attempt_unverified"
        latest_attempts.append((run, latest))

    # Keyed by exact revision and visible job name.  A configured identity may
    # select a different visible job name, but the output remains keyed to the
    # configured authoritative check.
    records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run, attempt in latest_attempts:
        run_id = run["id"]
        run_sha = run["head_sha"]
        jobs = attempt["jobs"]
        job_ids: set[int] = set()
        job_names: list[str] = []
        for job in jobs:
            if (
                not isinstance(job, Mapping)
                or not _positive_int(job.get("id"))
                or not isinstance(job.get("name"), str)
                or not job["name"]
            ):
                return None, "workflow_job_invalid"
            if job["id"] in job_ids:
                return None, "workflow_job_duplicate"
            job_ids.add(job["id"])
            job_names.append(job["name"])
            job_sha = job.get("head_sha")
            job_run_id = job.get("run_id")
            job_attempt = job.get("run_attempt")
            if (
                job_sha != run_sha
                or (job_run_id is not None and job_run_id != run_id)
                or (job_attempt is not None and job_attempt != run["run_attempt"])
            ):
                return None, "workflow_job_subject_mismatch"
            records[(run_sha, job["name"])].append(
                {"run_id": run_id, "run": run, "job": job}
            )
        if len(job_names) != len(set(job_names)):
            return None, "workflow_job_name_duplicate"
    return records, None


def _identity_matches(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    run = candidate["run"]
    job = candidate["job"]
    parsed_path = _parse_run_workflow_path(run.get("path"))
    return bool(
        parsed_path is not None
        and run.get("workflow_id") == expected["workflow_id"]
        and parsed_path == (expected["workflow_path"], expected["workflow_ref"])
        and job.get("name") == expected["job"]
    )


def _revision_checks(
    revisions: Sequence[str],
    checks: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]],
    records: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    rows: list[dict[str, Any]] = []
    for revision in revisions:
        check_rows: list[dict[str, str]] = []
        for check in checks:
            expected = identities.get(check)
            job_name = expected["job"] if expected is not None else check
            candidates = list(records.get((revision, job_name), ()))
            if not candidates:
                return None, "authoritative_check_missing"
            counts = Counter(candidate.get("run_id") for candidate in candidates)
            if any(not _positive_int(run_id) or count != 1 for run_id, count in counts.items()):
                return None, "authoritative_check_duplicate"
            latest_run_id = max(counts)
            latest = [candidate for candidate in candidates if candidate["run_id"] == latest_run_id]
            if len(latest) != 1:
                return None, "authoritative_check_latest_ambiguous"
            candidate = latest[0]
            if expected is not None and not _identity_matches(candidate, expected):
                return None, "authoritative_check_identity_mismatch"
            run = candidate["run"]
            job = candidate["job"]
            conclusion = job.get("conclusion")
            if (
                run.get("status") != "completed"
                or run.get("conclusion") not in _TERMINAL_CONCLUSIONS
                or job.get("status") != "completed"
                or conclusion not in _TERMINAL_CONCLUSIONS
            ):
                return None, "authoritative_check_nonterminal"
            check_rows.append({"name": check, "conclusion": conclusion})
        rows.append({"sha": revision, "checks": check_rows})
    return rows, None


def build_delivery_facts(
    repository_root: str | Path,
    *,
    repository: str,
    exact_main_sha: str,
    production_identity: Mapping[str, Any],
    github_observations: Mapping[str, Any],
    config: Mapping[str, Any],
    max_revisions: int = DEFAULT_MAX_REVISIONS,
    git_timeout_seconds: int = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Build controlled ancestry and intervening-check facts.

    Input-shape problems that would let a caller escape the intended bounded
    read-only operation raise ``DeliveryFactError``.  Evidence gaps are normal
    assessment outcomes and are returned as Unknown facts with explicit gaps.
    """

    root = Path(repository_root).resolve()
    if (
        not root.is_dir()
        or not isinstance(repository, str)
        or _REPOSITORY.fullmatch(repository) is None
        or not _is_sha(exact_main_sha)
        or not isinstance(production_identity, Mapping)
        or not isinstance(github_observations, Mapping)
        or not isinstance(config, Mapping)
        or not _positive_int(max_revisions)
        or not _positive_int(git_timeout_seconds)
    ):
        raise DeliveryFactError("delivery fact builder inputs are unsafe or malformed")

    checks, check_error = _configured_checks(config)
    if checks is None:
        raise DeliveryFactError(check_error or "authoritative checks are invalid")
    identities, identity_error = _check_identities(config, checks)
    units, unit_error = _units(production_identity, checks)
    if units is None:
        raise DeliveryFactError(unit_error or "production units are invalid")

    ancestry_facts: list[dict[str, Any]] = []
    intervening_facts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    ranges: dict[str, list[str]] = {}

    shallow = _is_shallow(root, timeout_seconds=git_timeout_seconds)
    main_known = _known_commit(root, exact_main_sha, timeout_seconds=git_timeout_seconds)
    local_error = (
        "git_repository_unverified"
        if shallow is None
        else "shallow_repository"
        if shallow
        else "main_object_missing"
        if not main_known
        else None
    )

    for unit in units:
        unit_id = unit["unit_id"]
        source_sha = unit["source_sha"]
        ancestry = _ancestry_fact(repository, unit_id, source_sha, exact_main_sha)
        intervening = _intervening_fact(repository, unit_id, source_sha, exact_main_sha)
        if local_error is not None:
            gaps.append(_gap(unit_id, local_error, "Exact local Git history is unavailable"))
            ancestry_facts.append(ancestry)
            intervening_facts.append(intervening)
            continue
        if not _known_commit(root, source_sha, timeout_seconds=git_timeout_seconds):
            gaps.append(_gap(unit_id, "source_object_missing", "The declared source commit is unavailable"))
            ancestry_facts.append(ancestry)
            intervening_facts.append(intervening)
            continue
        reachable = _reachable(
            root,
            source_sha,
            exact_main_sha,
            timeout_seconds=git_timeout_seconds,
        )
        if reachable is None:
            gaps.append(_gap(unit_id, "ancestry_unverified", "Git could not verify exact Main ancestry"))
            ancestry_facts.append(ancestry)
            intervening_facts.append(intervening)
            continue
        ancestry = _ancestry_fact(
            repository,
            unit_id,
            source_sha,
            exact_main_sha,
            state="verified",
            complete=True,
            reachable=reachable,
        )
        ancestry_facts.append(ancestry)
        if not reachable:
            gaps.append(_gap(unit_id, "source_not_reachable", "The source is not reachable from exact Main"))
            intervening_facts.append(intervening)
            continue
        revisions, range_error = _first_parent_range(
            root,
            source_sha,
            exact_main_sha,
            max_revisions=max_revisions,
            timeout_seconds=git_timeout_seconds,
        )
        if revisions is None:
            gaps.append(
                _gap(
                    unit_id,
                    range_error or "first_parent_unverified",
                    "The ordered first-parent range is incomplete",
                )
            )
            intervening_facts.append(intervening)
            continue
        ranges[unit_id] = revisions
        if unit["correspondence"] != "Releasable-Main" or not revisions:
            intervening_facts.append(
                _intervening_fact(
                    repository,
                    unit_id,
                    source_sha,
                    exact_main_sha,
                    state="verified",
                    complete=True,
                    revisions=[],
                )
            )
        else:
            intervening_facts.append(intervening)

    requires_checks = any(
        unit["correspondence"] == "Releasable-Main" and ranges.get(unit["unit_id"])
        for unit in units
    )
    records: dict[tuple[str, str], list[dict[str, Any]]] | None = {}
    population_error: str | None = identity_error
    if (
        requires_checks
        and population_error is None
        and (identities is None or set(identities) != set(checks))
    ):
        # Name-only job matching can be spoofed by another workflow.  Every
        # configured check therefore needs one complete controlled identity
        # whenever an intervening Main range must be assessed.
        population_error = "check_identities_incomplete"
    if requires_checks and population_error is None:
        records, population_error = _complete_action_population(
            github_observations,
            exact_main_sha=exact_main_sha,
        )

    if requires_checks:
        by_unit = {fact["unit_id"]: index for index, fact in enumerate(intervening_facts)}
        for unit in units:
            unit_id = unit["unit_id"]
            revisions = ranges.get(unit_id)
            if unit["correspondence"] != "Releasable-Main" or not revisions:
                continue
            index = by_unit[unit_id]
            if population_error is not None or records is None or identities is None:
                gaps.append(
                    _gap(
                        unit_id,
                        population_error or "actions_population_unverified",
                        "The authoritative check population is incomplete",
                    )
                )
                continue
            rows, check_error = _revision_checks(
                revisions,
                checks,
                identities,
                records,
            )
            if rows is None:
                gaps.append(
                    _gap(
                        unit_id,
                        check_error or "authoritative_checks_unverified",
                        "Every intervening revision was not proven by the latest terminal authoritative checks",
                    )
                )
                continue
            intervening_facts[index] = _intervening_fact(
                repository,
                unit_id,
                unit["source_sha"],
                exact_main_sha,
                state="verified",
                complete=True,
                revisions=rows,
            )

    return {
        "schema_version": FACT_BUILDER_SCHEMA,
        "repository": repository,
        "main_sha": exact_main_sha,
        "ancestry_facts": ancestry_facts,
        "intervening_check_facts": intervening_facts,
        "gaps": gaps,
    }


__all__ = [
    "ACTIONS_RUN_POPULATION_SCHEMA",
    "DEFAULT_MAX_REVISIONS",
    "FACT_BUILDER_SCHEMA",
    "DeliveryFactError",
    "build_delivery_facts",
]

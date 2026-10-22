"""GitHub-native repository health evidence observations.

Collectors in this module are intentionally read-only and preserve the
difference between an observed empty population and evidence GitHub would not
allow the token to read.  Each result is suitable for later metric evaluation;
this layer does not make control-conformance decisions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Iterable
from urllib.parse import quote, urlencode

from .github_client import GitHubRESTClient, utc_now


REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
DEFAULT_MAX_ASSET_CONTENT_BYTES = 1024 * 1024
DEFAULT_MAX_ASSET_CONTENT_NAMES = 100
DEFAULT_ACTION_REQUEST_BUDGET = 1_000
DELIVERY_INVENTORY_SCHEMA = "RH-GITHUB-DELIVERY-INVENTORY-1.0"
ACTIONS_RUN_POPULATION_SCHEMA = "RH-ACTIONS-RUN-POPULATION-1.0"


def _as_utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _api_path(repository: str, suffix: str = "", parameters: dict[str, Any] | None = None) -> str:
    path = f"/repos/{repository}{suffix}"
    if parameters:
        path = f"{path}?{urlencode(parameters, doseq=True)}"
    return path


def _result_complete(result: dict[str, Any]) -> bool:
    if "population_complete" in result:
        return bool(result.get("complete")) and bool(result.get("population_complete"))
    return bool(result.get("ok"))


def _result_observed(result: dict[str, Any]) -> bool:
    if "items" in result:
        return bool(result.get("pages")) and any(page.get("state") == "observed" for page in result["pages"])
    return bool(result.get("ok"))


def _request_record(label: str, endpoint: str, result: dict[str, Any]) -> dict[str, Any]:
    record = {
        "label": label,
        "endpoint": endpoint,
        "status": result.get("status"),
        "state": result.get("state", "observed" if result.get("ok") else "unknown"),
        "complete": _result_complete(result),
    }
    if "page_count" in result:
        record.update(
            {
                "page_count": result.get("page_count"),
                "item_count": result.get("item_count"),
                "reported_total_count": result.get("reported_total_count"),
                "truncated": bool(result.get("truncated")),
            }
        )
    return record


def _gap_record(label: str, endpoint: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": result.get("gap") or result.get("error_kind") or "evidence_unavailable",
        "status": result.get("status"),
        "endpoint": endpoint,
        "source": label,
        "message": result.get("error") or "Population completeness could not be demonstrated",
    }


def _make_group(
    *,
    evidence_id: str,
    source: str,
    subject_sha: str | None,
    unit: str | None,
    data: Any,
    checks: Iterable[tuple[str, str, dict[str, Any]]] = (),
    gaps: Iterable[dict[str, Any]] = (),
    observed_at: str | None = None,
) -> dict[str, Any]:
    check_list = list(checks)
    gap_list = list(gaps)
    for label, endpoint, result in check_list:
        if not _result_complete(result):
            gap_list.append(_gap_record(label, endpoint, result))
    complete = not gap_list and all(_result_complete(result) for _, _, result in check_list)
    any_observed = any(_result_observed(result) for _, _, result in check_list)
    if not check_list and not gap_list:
        any_observed = True
    return {
        "evidence_id": evidence_id,
        "observed_at": observed_at or utc_now(),
        "source": source,
        "subject_sha": subject_sha,
        "unit": unit,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else ("partial" if any_observed else "unknown"),
        "complete": complete,
        "population_complete": complete,
        "data": data,
        "gaps": gap_list,
        "request": {
            "endpoints": [_request_record(label, endpoint, result) for label, endpoint, result in check_list]
        },
    }


def _unknown_group(
    evidence_id: str,
    source: str,
    subject_sha: str | None,
    unit: str | None,
    message: str,
    *,
    kind: str = "missing_prerequisite",
    observed_at: str | None = None,
) -> dict[str, Any]:
    return _make_group(
        evidence_id=evidence_id,
        source=source,
        subject_sha=subject_sha,
        unit=unit,
        data={},
        gaps=[{"kind": kind, "status": None, "endpoint": None, "source": source, "message": message}],
        observed_at=observed_at,
    )


def collect_repository_identity(
    repository: str,
    *,
    main_branch: str | None,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    observed_at: str | None = None,
) -> dict[str, Any]:
    repository_endpoint = _api_path(repository)
    repository_result = client.get(repository_endpoint)
    repository_record = repository_result.get("data") if repository_result.get("ok") else None
    default_branch = repository_record.get("default_branch") if isinstance(repository_record, dict) else None
    selected_branch = (main_branch or default_branch or "").strip()
    checks: list[tuple[str, str, dict[str, Any]]] = [
        ("repository", repository_endpoint, repository_result)
    ]
    branch_record: dict[str, Any] | None = None
    branch_result: dict[str, Any] | None = None
    if selected_branch:
        branch_endpoint = _api_path(repository, f"/branches/{quote(selected_branch, safe='')}")
        branch_result = client.get(branch_endpoint)
        checks.append(("default_or_main_branch", branch_endpoint, branch_result))
        if branch_result.get("ok") and isinstance(branch_result.get("data"), dict):
            branch_record = branch_result["data"]
    else:
        branch_endpoint = ""

    supplied_sha = subject_sha if isinstance(subject_sha, str) and SHA_PATTERN.fullmatch(subject_sha) else None
    live_branch_sha: str | None = None
    if isinstance(branch_record, dict):
        commit = branch_record.get("commit")
        candidate = commit.get("sha") if isinstance(commit, dict) else None
        if isinstance(candidate, str) and SHA_PATTERN.fullmatch(candidate):
            live_branch_sha = candidate
    resolved_sha = supplied_sha or live_branch_sha
    extra_gaps: list[dict[str, Any]] = []
    if subject_sha and not (isinstance(subject_sha, str) and SHA_PATTERN.fullmatch(subject_sha)):
        extra_gaps.append(
            {
                "kind": "invalid_subject_sha",
                "status": None,
                "endpoint": repository_endpoint,
                "source": "configured_subject",
                "message": "The configured subject is not a full 40-character commit SHA",
            }
        )
    if supplied_sha and live_branch_sha and supplied_sha.lower() != live_branch_sha.lower():
        extra_gaps.append(
            {
                "kind": "subject_sha_mismatch",
                "status": branch_result.get("status") if branch_result else None,
                "endpoint": branch_endpoint or repository_endpoint,
                "source": "default_or_main_branch",
                "message": (
                    "The supplied assessment SHA does not match the live selected-branch commit; "
                    "the observation may be stale"
                ),
            }
        )
    if not selected_branch:
        extra_gaps.append(
            {
                "kind": "main_branch_unknown",
                "status": None,
                "endpoint": repository_endpoint,
                "source": "repository",
                "message": "Neither a configured Main role nor GitHub default branch was observable",
            }
        )
    if not resolved_sha:
        extra_gaps.append(
            {
                "kind": "main_sha_unknown",
                "status": branch_result.get("status") if branch_result else None,
                "endpoint": branch_endpoint or repository_endpoint,
                "source": "default_or_main_branch",
                "message": "The exact Main revision could not be resolved",
            }
        )
    return _make_group(
        evidence_id="E-GH-REPOSITORY",
        source="github-rest:repository",
        subject_sha=resolved_sha,
        unit=unit,
        data={
            "repository": repository,
            "default_branch": default_branch,
            "main_branch": selected_branch or None,
            "main_sha": resolved_sha,
            "live_main_sha": live_branch_sha,
            "repository_record": repository_record,
            "branch": branch_record,
        },
        checks=checks,
        gaps=extra_gaps,
        observed_at=observed_at,
    )


def collect_check_runs(
    repository: str,
    *,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if not subject_sha or not SHA_PATTERN.fullmatch(subject_sha):
        return _unknown_group(
            "E-GH-CHECK-RUNS",
            "github-rest:check-runs",
            subject_sha,
            unit,
            "Exact-SHA checks require a full 40-character Main revision",
            kind="invalid_subject_sha" if subject_sha else "missing_prerequisite",
            observed_at=observed_at,
        )
    endpoint = _api_path(
        repository,
        f"/commits/{quote(subject_sha, safe='')}/check-runs",
        {"filter": "all", "per_page": 100},
    )
    result = client.paginate(endpoint, "check_runs")
    return _make_group(
        evidence_id="E-GH-CHECK-RUNS",
        source="github-rest:check-runs",
        subject_sha=subject_sha,
        unit=unit,
        data={"check_runs": result["items"]},
        checks=[("check_runs", endpoint, result)],
        observed_at=observed_at,
    )


def collect_action_history(
    repository: str,
    *,
    main_branch: str,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    days: int,
    now: datetime | None = None,
    max_runs_for_jobs: int = 1_000,
    max_attempts_per_run: int = 20,
    max_request_budget: int = DEFAULT_ACTION_REQUEST_BUDGET,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if days < 1 or max_runs_for_jobs < 1 or max_attempts_per_run < 1 or max_request_budget < 1:
        raise ValueError("Action-history windows and collection caps must be positive")
    end = _as_utc(now)
    start = end - timedelta(days=days)
    endpoint = _api_path(
        repository,
        "/actions/runs",
        {
            "branch": main_branch,
            "created": f"{_iso_z(start)}..{_iso_z(end)}",
            "per_page": 100,
        },
    )
    runs_result = client.paginate(
        endpoint,
        "workflow_runs",
        max_pages=min(client.max_pages, max_request_budget),
    )
    checks: list[tuple[str, str, dict[str, Any]]] = [("workflow_runs", endpoint, runs_result)]
    gaps: list[dict[str, Any]] = []
    run_attempts: list[dict[str, Any]] = []
    runs = runs_result["items"]
    request_count = int(runs_result.get("page_count") or 0)
    run_by_id: dict[int, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("id"), int) or isinstance(run.get("id"), bool):
            gaps.append(
                {
                    "kind": "invalid_workflow_run",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "workflow_run_jobs",
                    "message": "A workflow run did not contain an integer id",
                }
            )
            continue
        run_id = run["id"]
        existing = run_by_id.get(run_id)
        if existing is not None and existing != run:
            gaps.append(
                {
                    "kind": "duplicate_workflow_run_conflict",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "workflow_run_jobs",
                    "message": f"Workflow run {run_id} appeared more than once with conflicting data",
                }
            )
            continue
        run_by_id.setdefault(run_id, run)
    unique_runs = list(run_by_id.values())
    if len(unique_runs) > max_runs_for_jobs:
        gaps.append(
            {
                "kind": "run_job_cap",
                "status": None,
                "endpoint": endpoint,
                "source": "workflow_run_jobs",
                "message": f"Job collection capped at {max_runs_for_jobs} of {len(unique_runs)} runs",
            }
        )
    budget_gap_added = False
    attempt_cache: dict[tuple[int, int], dict[str, Any]] = {}

    def add_budget_gap() -> None:
        nonlocal budget_gap_added
        if budget_gap_added:
            return
        budget_gap_added = True
        gaps.append(
            {
                "kind": "action_request_budget",
                "status": None,
                "endpoint": endpoint,
                "source": "workflow_run_jobs",
                "message": f"Action-history collection reached its {max_request_budget}-request budget",
            }
        )

    stop_collection = False
    for run in unique_runs[:max_runs_for_jobs]:
        run_id = run["id"]
        raw_attempts = run.get("run_attempt", 1)
        attempt_count = raw_attempts if isinstance(raw_attempts, int) and raw_attempts > 0 else 1
        if attempt_count > max_attempts_per_run:
            gaps.append(
                {
                    "kind": "run_attempt_cap",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "workflow_run_jobs",
                    "message": f"Run {run_id} attempts capped at {max_attempts_per_run} of {attempt_count}",
                }
            )
        for attempt in range(1, min(attempt_count, max_attempts_per_run) + 1):
            cache_key = (run_id, attempt)
            if cache_key in attempt_cache:
                run_attempts.append(attempt_cache[cache_key])
                continue
            if request_count >= max_request_budget:
                add_budget_gap()
                stop_collection = True
                break
            attempt_endpoint = _api_path(repository, f"/actions/runs/{run_id}/attempts/{attempt}")
            attempt_result = client.get(attempt_endpoint)
            request_count += 1
            checks.append((f"run_{run_id}_attempt_{attempt}", attempt_endpoint, attempt_result))
            jobs_endpoint = _api_path(
                repository,
                f"/actions/runs/{run_id}/attempts/{attempt}/jobs",
                {"per_page": 100},
            )
            remaining_requests = max_request_budget - request_count
            if remaining_requests < 1:
                add_budget_gap()
                stop_collection = True
                break
            jobs_result = client.paginate(
                jobs_endpoint,
                "jobs",
                max_pages=min(client.max_pages, remaining_requests),
            )
            request_count += int(jobs_result.get("page_count") or 0)
            checks.append((f"run_{run_id}_attempt_{attempt}_jobs", jobs_endpoint, jobs_result))
            detail = {
                "run_id": run_id,
                "attempt": attempt,
                "run": attempt_result.get("data") if attempt_result.get("ok") else None,
                "jobs": jobs_result["items"],
                "complete": bool(attempt_result.get("ok")) and jobs_result["complete"],
                "population_complete": bool(attempt_result.get("ok")) and jobs_result["population_complete"],
            }
            attempt_cache[cache_key] = detail
            run_attempts.append(detail)
        if stop_collection:
            break
    return _make_group(
        evidence_id=f"E-GH-ACTIONS-W{days}",
        source=f"github-rest:actions-w{days}",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "window": {"start": _iso_z(start), "end": _iso_z(end), "days": days},
            "population_contract": {
                "schema_version": ACTIONS_RUN_POPULATION_SCHEMA,
                "scope": "branch-window",
                "branch_ref": f"refs/heads/{main_branch}",
                "subjects": [],
            },
            "workflow_runs": unique_runs,
            "run_attempts": run_attempts,
            "request_budget": {"maximum": max_request_budget, "used": request_count},
        },
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )


def _action_run_datetime(run: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "run_started_at"):
        value = run.get(key)
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    return None


def slice_action_history(
    history: dict[str, Any],
    *,
    days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive a shorter complete window without making another GitHub request."""

    if days < 1:
        raise ValueError("Action-history window must be positive")
    end = _as_utc(now)
    start = end - timedelta(days=days)
    raw_data = history.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    raw_runs = data.get("workflow_runs")
    runs = raw_runs if isinstance(raw_runs, list) else []
    selected_runs: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    slice_gaps: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            slice_gaps.append(
                {
                    "kind": "run_timestamp_unavailable",
                    "status": None,
                    "endpoint": None,
                    "source": "derived_action_window",
                    "message": "A workflow run could not be assigned to the derived time window",
                }
            )
            continue
        created_at = _action_run_datetime(run)
        if created_at is None:
            slice_gaps.append(
                {
                    "kind": "run_timestamp_unavailable",
                    "status": None,
                    "endpoint": None,
                    "source": "derived_action_window",
                    "message": f"Workflow run {run.get('id')} has no usable creation timestamp",
                }
            )
            continue
        if start <= created_at <= end:
            selected_runs.append(run)
            run_id = run.get("id")
            if isinstance(run_id, int) and not isinstance(run_id, bool):
                selected_ids.add(run_id)
    attempts = data.get("run_attempts")
    selected_attempts = (
        [
            attempt
            for attempt in attempts
            if isinstance(attempt, dict) and attempt.get("run_id") in selected_ids
        ]
        if isinstance(attempts, list)
        else []
    )
    gaps = list(history.get("gaps", [])) + slice_gaps
    complete = history.get("complete") is True and not slice_gaps
    request = (
        history.get("request")
        if isinstance(history.get("request"), dict)
        else {"endpoints": []}
    )
    return {
        **history,
        "evidence_id": f"E-GH-ACTIONS-W{days}",
        "source": f"github-rest:actions-w{days}-derived",
        "state": "observed" if complete else "unknown",
        "completeness": (
            "complete"
            if complete
            else ("partial" if history.get("completeness") != "unknown" else "unknown")
        ),
        "complete": complete,
        "population_complete": complete,
        "data": {
            "window": {"start": _iso_z(start), "end": _iso_z(end), "days": days},
            "population_contract": data.get("population_contract"),
            "workflow_runs": selected_runs,
            "run_attempts": selected_attempts,
            "request_budget": data.get("request_budget"),
        },
        "gaps": gaps,
        "request": {**request, "derived_from": history.get("evidence_id")},
    }


def _commit_datetime(commit: dict[str, Any]) -> datetime | None:
    nested = commit.get("commit")
    if not isinstance(nested, dict):
        return None
    for identity_key in ("committer", "author"):
        identity = nested.get(identity_key)
        value = identity.get("date") if isinstance(identity, dict) else None
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    return None


def _reachable_commit_record(commit: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Preserve commit-object topology without asserting Main acceptance."""

    record = dict(commit)
    parents = commit.get("parents")
    if not isinstance(parents, list):
        parent_shas: list[str] = []
        parents_complete = False
    else:
        parent_shas = [
            parent.get("sha")
            for parent in parents
            if isinstance(parent, dict)
            and isinstance(parent.get("sha"), str)
            and SHA_PATTERN.fullmatch(parent["sha"])
        ]
        parents_complete = len(parent_shas) == len(parents)
    record.update(
        {
            "history_role": "reachable_from_selected_ref",
            "accepted_main_revision": None,
            "parent_shas": parent_shas,
            "first_parent_sha": parent_shas[0] if parent_shas else None,
            "first_parent_source": "commit_object_parent_order" if parents_complete else None,
            "parent_identity_complete": parents_complete,
        }
    )
    sha = record.get("sha")
    complete = (
        isinstance(sha, str)
        and SHA_PATTERN.fullmatch(sha) is not None
        and parents_complete
        and _commit_datetime(record) is not None
    )
    return record, complete


def collect_change_history(
    repository: str,
    *,
    main_branch: str,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    now: datetime | None = None,
    days: int = 365,
    max_commits_for_pulls: int = 1_000,
    max_pull_requests_for_reviews: int = 1_000,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if days < 1 or max_commits_for_pulls < 1 or max_pull_requests_for_reviews < 1:
        raise ValueError("Change-history windows and collection caps must be positive")
    end = _as_utc(now)
    start = end - timedelta(days=days)
    endpoint = _api_path(
        repository,
        "/commits",
        {"sha": main_branch, "since": _iso_z(start), "until": _iso_z(end), "per_page": 100},
    )
    most_recent_endpoint = _api_path(
        repository,
        f"/commits/{quote(main_branch, safe='')}",
    )
    commits_result = client.paginate(endpoint)
    most_recent_result = client.get(most_recent_endpoint)
    checks: list[tuple[str, str, dict[str, Any]]] = [
        ("reachable_commits_w365", endpoint, commits_result),
        ("most_recent_selected_ref_commit", most_recent_endpoint, most_recent_result),
    ]
    gaps: list[dict[str, Any]] = []
    raw_commits = commits_result["items"]
    reachable_commits: list[dict[str, Any]] = []
    reachable_population_identity_complete = True
    for commit in raw_commits:
        if not isinstance(commit, dict):
            reachable_population_identity_complete = False
            gaps.append(
                {
                    "kind": "invalid_reachable_commit",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "reachable_commit_topology",
                    "message": "A reachable-history record was not a commit object",
                }
            )
            continue
        shaped, shape_complete = _reachable_commit_record(commit)
        reachable_commits.append(shaped)
        if not shape_complete:
            reachable_population_identity_complete = False
            gaps.append(
                {
                    "kind": "incomplete_reachable_commit_identity",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "reachable_commit_topology",
                    "message": f"Reachable commit {commit.get('sha')} lacks complete SHA, date, or parent identity",
                }
            )

    most_recent_commit: dict[str, Any] | None = None
    most_recent_complete = False
    most_recent_raw = most_recent_result.get("data")
    if most_recent_result.get("ok") and isinstance(most_recent_raw, dict):
        most_recent_commit, most_recent_complete = _reachable_commit_record(most_recent_raw)
    if most_recent_result.get("ok") and not most_recent_complete:
        gaps.append(
            {
                "kind": "invalid_most_recent_commit",
                "status": most_recent_result.get("status"),
                "endpoint": most_recent_endpoint,
                "source": "most_recent_selected_ref_commit",
                "message": "The selected ref did not resolve to a complete commit identity",
            }
        )

    window_population_complete = _result_complete(commits_result)
    no_reachable_commits_in_window = (
        not raw_commits if window_population_complete else None
    )
    most_recent_time = _commit_datetime(most_recent_commit) if most_recent_commit else None
    most_recent_older_than_window = (
        most_recent_time < start
        if window_population_complete and most_recent_complete and most_recent_time is not None
        else None
    )
    low_activity_basis_complete = (
        window_population_complete
        and reachable_population_identity_complete
        and most_recent_complete
        and isinstance(no_reachable_commits_in_window, bool)
        and isinstance(most_recent_older_than_window, bool)
    )

    link_candidates = list(reachable_commits)
    most_recent_sha = most_recent_commit.get("sha") if most_recent_commit else None
    if (
        isinstance(most_recent_sha, str)
        and all(commit.get("sha") != most_recent_sha for commit in link_candidates)
    ):
        link_candidates.append(most_recent_commit)
    if len(link_candidates) > max_commits_for_pulls:
        gaps.append(
            {
                "kind": "commit_pull_cap",
                "status": None,
                "endpoint": endpoint,
                "source": "associated_pull_requests",
                "message": (
                    f"Associated-PR collection capped at {max_commits_for_pulls} "
                    f"of {len(link_candidates)} reachable or most-recent commits"
                ),
            }
        )
    pull_requests: dict[int, dict[str, Any]] = {}
    commit_pr_links: list[dict[str, Any]] = []
    window_shas = {
        commit.get("sha")
        for commit in reachable_commits
        if isinstance(commit.get("sha"), str)
    }
    for commit in link_candidates[:max_commits_for_pulls]:
        sha = commit.get("sha")
        if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
            gaps.append(
                {
                    "kind": "invalid_commit",
                    "status": None,
                    "endpoint": endpoint,
                    "source": "associated_pull_requests",
                    "message": "A reachable commit did not contain a full SHA",
                }
            )
            continue
        pulls_endpoint = _api_path(repository, f"/commits/{sha}/pulls", {"per_page": 100})
        pulls_result = client.paginate(pulls_endpoint)
        checks.append((f"commit_{sha}_pulls", pulls_endpoint, pulls_result))
        numbers: list[int] = []
        for pull in pulls_result["items"]:
            number = pull.get("number") if isinstance(pull, dict) else None
            if isinstance(number, int):
                numbers.append(number)
                pull_requests.setdefault(number, pull)
        commit_pr_links.append(
            {
                "commit_sha": sha,
                "pull_numbers": sorted(set(numbers)),
                "reachability_scope": "window" if sha in window_shas else "most_recent",
                "accepted_main_revision": None,
            }
        )

    reviews: list[dict[str, Any]] = []
    pull_numbers = sorted(pull_requests)
    if len(pull_numbers) > max_pull_requests_for_reviews:
        gaps.append(
            {
                "kind": "pull_review_cap",
                "status": None,
                "endpoint": endpoint,
                "source": "pull_request_reviews",
                "message": (
                    f"Review collection capped at {max_pull_requests_for_reviews} "
                    f"of {len(pull_numbers)} pull requests"
                ),
            }
        )
    for number in pull_numbers[:max_pull_requests_for_reviews]:
        reviews_endpoint = _api_path(repository, f"/pulls/{number}/reviews", {"per_page": 100})
        reviews_result = client.paginate(reviews_endpoint)
        checks.append((f"pull_{number}_reviews", reviews_endpoint, reviews_result))
        reviews.append(
            {
                "pull_number": number,
                "reviews": reviews_result["items"],
                "complete": reviews_result["complete"],
                "population_complete": reviews_result["population_complete"],
            }
        )
    gaps.append(
        {
            "kind": "accepted_main_revision_population_unavailable",
            "status": None,
            "endpoint": endpoint,
            "source": "acceptance_history",
            "message": (
                "GitHub reachable-history APIs do not establish which revisions were accepted "
                "onto Main or whether historical bypass occurred"
            ),
        }
    )
    return _make_group(
        evidence_id="E-GH-CHANGE-HISTORY",
        source="github-rest:change-history",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "window": {"start": _iso_z(start), "end": _iso_z(end), "days": days},
            "reachable_commits": reachable_commits,
            "accepted_main_revisions": [],
            "accepted_main_revisions_complete": False,
            "historical_bypass_events": [],
            "historical_bypass_complete": False,
            "most_recent_commit": most_recent_commit,
            "most_recent_commit_basis": {
                "complete": low_activity_basis_complete,
                "window_days": days,
                "window_population_complete": window_population_complete,
                "window_commit_identity_complete": reachable_population_identity_complete,
                "most_recent_commit_complete": most_recent_complete,
                "no_reachable_commits_in_window": no_reachable_commits_in_window,
                "older_than_window": most_recent_older_than_window,
                "no_reachable_commits_w365": (
                    no_reachable_commits_in_window if days == 365 else None
                ),
                "older_than_w365": (
                    most_recent_older_than_window if days == 365 else None
                ),
                "source_endpoint": most_recent_endpoint,
            },
            "associated_pull_requests": [pull_requests[number] for number in sorted(pull_requests)],
            "commit_pr_links": commit_pr_links,
            "reviews": reviews,
        },
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )


def _tag_target(
    repository: str,
    tag_name: str,
    client: GitHubRESTClient,
    checks: list[tuple[str, str, dict[str, Any]]],
    *,
    max_tag_depth: int = 5,
) -> dict[str, Any]:
    ref_endpoint = _api_path(repository, f"/git/ref/tags/{quote(tag_name, safe='')}")
    ref_result = client.get(ref_endpoint)
    checks.append((f"tag_{tag_name}_ref", ref_endpoint, ref_result))
    ref_record = ref_result.get("data") if ref_result.get("ok") and isinstance(ref_result.get("data"), dict) else None
    target = ref_record.get("object") if isinstance(ref_record, dict) else None
    object_type = target.get("type") if isinstance(target, dict) else None
    object_sha = target.get("sha") if isinstance(target, dict) else None
    chain: list[dict[str, Any]] = []
    current_type = object_type
    current_sha = object_sha
    depth = 0
    while current_type == "tag" and isinstance(current_sha, str) and depth < max_tag_depth:
        tag_endpoint = _api_path(repository, f"/git/tags/{quote(current_sha, safe='')}")
        tag_result = client.get(tag_endpoint)
        checks.append((f"tag_{tag_name}_object_{depth + 1}", tag_endpoint, tag_result))
        if not tag_result.get("ok") or not isinstance(tag_result.get("data"), dict):
            break
        annotated = tag_result["data"]
        chain.append(annotated)
        nested = annotated.get("object")
        if not isinstance(nested, dict):
            current_type = None
            current_sha = None
            break
        current_type = nested.get("type")
        current_sha = nested.get("sha")
        depth += 1
    return {
        "ref": ref_record,
        "object_type": object_type,
        "object_sha": object_sha,
        "annotated": object_type == "tag",
        "annotated_tag": chain[0] if chain else None,
        "annotation_chain": chain,
        "peeled_type": current_type,
        "peeled_sha": current_sha if current_type == "commit" else None,
        "peel_complete": current_type == "commit",
        "depth_capped": current_type == "tag" and depth >= max_tag_depth,
    }


def collect_refs_and_releases(
    repository: str,
    *,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    release_asset_names: Iterable[str] = (),
    max_asset_content_bytes: int = DEFAULT_MAX_ASSET_CONTENT_BYTES,
    max_asset_content_names: int = DEFAULT_MAX_ASSET_CONTENT_NAMES,
    max_tags_for_resolution: int = 1_000,
    max_releases_for_assets: int = 1_000,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if max_asset_content_bytes < 1 or max_asset_content_names < 1:
        raise ValueError("Release asset content caps must be positive")
    branches_endpoint = _api_path(repository, "/branches", {"per_page": 100})
    tags_endpoint = _api_path(repository, "/tags", {"per_page": 100})
    releases_endpoint = _api_path(repository, "/releases", {"per_page": 100})
    branches_result = client.paginate(branches_endpoint)
    tags_result = client.paginate(tags_endpoint)
    releases_result = client.paginate(releases_endpoint)
    checks: list[tuple[str, str, dict[str, Any]]] = [
        ("branches", branches_endpoint, branches_result),
        ("tags", tags_endpoint, tags_result),
        ("releases", releases_endpoint, releases_result),
    ]
    gaps: list[dict[str, Any]] = []
    allowlisted_names: set[str] = set()
    allowlist_capped = False
    for index, value in enumerate(release_asset_names):
        if index >= max_asset_content_names:
            allowlist_capped = True
            break
        if not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value:
            gaps.append(
                {
                    "kind": "invalid_asset_content_allowlist",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": "Release asset content allowlist contains an invalid exact name",
                }
            )
            continue
        allowlisted_names.add(value)
    if allowlist_capped:
        gaps.append(
            {
                "kind": "asset_content_allowlist_cap",
                "status": None,
                "endpoint": releases_endpoint,
                "source": "release_asset_content",
                "message": f"Release asset content allowlist exceeded {max_asset_content_names} names",
            }
        )
    if len(tags_result["items"]) > max_tags_for_resolution:
        gaps.append(
            {
                "kind": "tag_resolution_cap",
                "status": None,
                "endpoint": tags_endpoint,
                "source": "tag_refs",
                "message": f"Tag resolution capped at {max_tags_for_resolution} of {len(tags_result['items'])} tags",
            }
        )
    resolved_tags: list[dict[str, Any]] = []
    target_by_name: dict[str, dict[str, Any]] = {}
    for tag in tags_result["items"][:max_tags_for_resolution]:
        record = dict(tag) if isinstance(tag, dict) else {"raw": tag}
        name = record.get("name")
        if not isinstance(name, str) or not name:
            gaps.append(
                {
                    "kind": "invalid_tag",
                    "status": None,
                    "endpoint": tags_endpoint,
                    "source": "tag_refs",
                    "message": "A tag did not contain a name",
                }
            )
            resolved_tags.append(record)
            continue
        target = _tag_target(repository, name, client, checks)
        record["tag_target"] = target
        record["ref"] = target["ref"]
        record["annotated_tag"] = target["annotated_tag"]
        record["peeled_sha"] = target["peeled_sha"]
        resolved_tags.append(record)
        target_by_name[name] = target
        if target["depth_capped"]:
            gaps.append(
                {
                    "kind": "annotated_tag_depth_cap",
                    "status": None,
                    "endpoint": tags_endpoint,
                    "source": "tag_refs",
                    "message": f"Annotated tag {name} exceeded the peel depth cap",
                }
            )

    if len(releases_result["items"]) > max_releases_for_assets:
        gaps.append(
            {
                "kind": "release_asset_cap",
                "status": None,
                "endpoint": releases_endpoint,
                "source": "release_assets",
                "message": (
                    f"Asset collection capped at {max_releases_for_assets} "
                    f"of {len(releases_result['items'])} releases"
                ),
            }
        )
    releases: list[dict[str, Any]] = []
    content_candidates: dict[str, list[tuple[int, dict[str, Any]]]] = {
        name: [] for name in allowlisted_names
    }
    for release in releases_result["items"][:max_releases_for_assets]:
        record = dict(release) if isinstance(release, dict) else {"raw": release}
        release_id = record.get("id")
        if not isinstance(release_id, int):
            gaps.append(
                {
                    "kind": "invalid_release",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_assets",
                    "message": "A release did not contain an integer id",
                }
            )
            releases.append(record)
            continue
        assets_endpoint = _api_path(repository, f"/releases/{release_id}/assets", {"per_page": 100})
        assets_result = client.paginate(assets_endpoint)
        checks.append((f"release_{release_id}_assets", assets_endpoint, assets_result))
        record["assets"] = assets_result["items"]
        for asset in assets_result["items"]:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            if isinstance(name, str) and name in content_candidates:
                content_candidates[name].append((release_id, asset))
        tag_name = record.get("tag_name")
        record["tag_target"] = target_by_name.get(tag_name) if isinstance(tag_name, str) else None
        releases.append(record)

    asset_contents: dict[str, bytes] = {}
    for name in sorted(allowlisted_names):
        candidates = content_candidates[name]
        if not candidates:
            gaps.append(
                {
                    "kind": "allowlisted_asset_missing",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": f"Allowlisted release asset {name!r} was not observed",
                }
            )
            continue
        if len(candidates) != 1:
            release_ids = sorted({release_id for release_id, _ in candidates})
            gaps.append(
                {
                    "kind": "duplicate_release_asset_name",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": (
                        f"Allowlisted release asset {name!r} is ambiguous across "
                        f"{len(candidates)} records in releases {release_ids}"
                    ),
                }
            )
            continue
        release_id, asset = candidates[0]
        asset_id = asset.get("id")
        declared_size = asset.get("size")
        digest = asset.get("digest")
        if not isinstance(asset_id, int) or isinstance(asset_id, bool) or asset_id < 1:
            gaps.append(
                {
                    "kind": "invalid_release_asset_id",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": f"Allowlisted release asset {name!r} has no positive integer id",
                }
            )
            continue
        if (
            not isinstance(declared_size, int)
            or isinstance(declared_size, bool)
            or declared_size < 0
        ):
            gaps.append(
                {
                    "kind": "asset_size_unavailable",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": f"Allowlisted release asset {name!r} has no valid declared size",
                }
            )
            continue
        if not isinstance(digest, str) or not SHA256_DIGEST_PATTERN.fullmatch(digest):
            gaps.append(
                {
                    "kind": "asset_digest_unavailable",
                    "status": None,
                    "endpoint": releases_endpoint,
                    "source": "release_asset_content",
                    "message": f"Allowlisted release asset {name!r} has no SHA-256 digest",
                }
            )
            continue
        content_endpoint = _api_path(repository, f"/releases/assets/{asset_id}")
        content_result = client.get_binary(
            content_endpoint,
            declared_size=declared_size,
            max_bytes=max_asset_content_bytes,
        )
        checks.append(
            (
                f"release_{release_id}_asset_{asset_id}_content",
                content_endpoint,
                content_result,
            )
        )
        if not content_result.get("ok") or not isinstance(content_result.get("data"), bytes):
            continue
        content = content_result["data"]
        observed_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if observed_digest != digest.lower():
            gaps.append(
                {
                    "kind": "asset_digest_mismatch",
                    "status": content_result.get("status"),
                    "endpoint": content_endpoint,
                    "source": "release_asset_content",
                    "message": f"Downloaded bytes for {name!r} do not match the live asset digest",
                }
            )
            continue
        asset_contents[name] = content
    remote_refs: list[dict[str, Any]] = []
    for branch in branches_result["items"]:
        if not isinstance(branch, dict) or not isinstance(branch.get("name"), str):
            continue
        commit = branch.get("commit")
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        remote_refs.append(
            {
                "ref": f"refs/heads/{branch['name']}",
                "object": {"type": "commit", "sha": commit_sha},
                "source": "branches",
            }
        )
    for tag in resolved_tags:
        tag_ref = tag.get("ref")
        if isinstance(tag_ref, dict):
            remote_refs.append({**tag_ref, "source": "tag_ref"})
    return _make_group(
        evidence_id="E-GH-REFS-RELEASES",
        source="github-rest:refs-releases",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "remote_refs": remote_refs,
            "branches": branches_result["items"],
            "tags": resolved_tags,
            "releases": releases,
            "asset_contents": asset_contents,
        },
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )


def collect_delivery(
    repository: str,
    *,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    max_deployments_for_statuses: int = 1_000,
    observed_at: str | None = None,
) -> dict[str, Any]:
    deployments_endpoint = _api_path(repository, "/deployments", {"per_page": 100})
    environments_endpoint = _api_path(repository, "/environments", {"per_page": 100})
    deployments_result = client.paginate(deployments_endpoint)
    environments_result = client.paginate(environments_endpoint, "environments")
    deployment_checks: list[tuple[str, str, dict[str, Any]]] = [
        ("deployments", deployments_endpoint, deployments_result),
        ("environments", environments_endpoint, environments_result),
    ]
    gaps: list[dict[str, Any]] = []
    deployment_validation_gaps: list[dict[str, Any]] = []
    if len(deployments_result["items"]) > max_deployments_for_statuses:
        deployment_validation_gaps.append(
            {
                "kind": "deployment_status_cap",
                "status": None,
                "endpoint": deployments_endpoint,
                "source": "deployment_statuses",
                "message": (
                    f"Status collection capped at {max_deployments_for_statuses} "
                    f"of {len(deployments_result['items'])} deployments"
                ),
            }
        )
    deployments: list[dict[str, Any]] = []
    inventory_items: list[dict[str, Any]] = []
    for deployment in deployments_result["items"][:max_deployments_for_statuses]:
        record = dict(deployment) if isinstance(deployment, dict) else {"raw": deployment}
        deployment_id = record.get("id")
        if not isinstance(deployment_id, int):
            deployment_validation_gaps.append(
                {
                    "kind": "invalid_deployment",
                    "status": None,
                    "endpoint": deployments_endpoint,
                    "source": "deployment_statuses",
                    "message": "A deployment did not contain an integer id",
                }
            )
            deployments.append(record)
            continue
        status_endpoint = _api_path(repository, f"/deployments/{deployment_id}/statuses", {"per_page": 100})
        status_result = client.paginate(status_endpoint)
        deployment_checks.append((f"deployment_{deployment_id}_statuses", status_endpoint, status_result))
        record["statuses"] = status_result["items"]
        record["statuses_complete"] = status_result["complete"]
        deployments.append(record)

        deployment_sha = record.get("sha")
        if not isinstance(deployment_sha, str) or not SHA_PATTERN.fullmatch(deployment_sha):
            deployment_validation_gaps.append(
                {
                    "kind": "invalid_delivery_identity",
                    "status": None,
                    "endpoint": deployments_endpoint,
                    "source": "deployments",
                    "message": (
                        f"Deployment {deployment_id} does not expose an exact 40-character source SHA"
                    ),
                }
            )
            continue
        normalized_sha = deployment_sha.lower()
        normalized_subject = (
            subject_sha.lower()
            if isinstance(subject_sha, str) and SHA_PATTERN.fullmatch(subject_sha)
            else None
        )
        selectors: dict[str, Any] = {"deployment_id": deployment_id}
        for selector_name in ("environment", "ref", "task"):
            selector_value = record.get(selector_name)
            if isinstance(selector_value, str) and selector_value:
                selectors[selector_name] = selector_value
        status_states = [
            status.get("state")
            for status in status_result["items"]
            if isinstance(status, dict) and isinstance(status.get("state"), str)
        ]
        inventory_items.append(
            {
                "inventory_id": f"github-deployments:{deployment_id}",
                "adapter_id": "github-deployments",
                "delivery_kind": "deployment",
                "repository": repository,
                "unit_selector": None,
                "selectors": selectors,
                "observed_subject_sha": normalized_subject,
                "source_sha": normalized_sha,
                "matches_subject": (
                    normalized_sha == normalized_subject if normalized_subject is not None else None
                ),
                "status": {
                    "states": status_states,
                    "population_complete": bool(status_result.get("population_complete")),
                },
            }
        )

    gaps.extend(deployment_validation_gaps)
    deployment_complete = not deployment_validation_gaps and all(
        _result_complete(result) for _, _, result in deployment_checks
    )

    pages_endpoint = _api_path(repository, "/pages")
    pages_builds_endpoint = _api_path(repository, "/pages/builds", {"per_page": 100})
    pages_site_result = client.get(pages_endpoint)
    pages_builds_result = client.paginate(pages_builds_endpoint)
    pages_checks: list[tuple[str, str, dict[str, Any]]] = [
        ("pages_site", pages_endpoint, pages_site_result),
        ("pages_builds", pages_builds_endpoint, pages_builds_result),
    ]
    pages_validation_gaps: list[dict[str, Any]] = []

    normalized_subject = (
        subject_sha.lower()
        if isinstance(subject_sha, str) and SHA_PATTERN.fullmatch(subject_sha)
        else None
    )
    pages_subject_status: dict[str, Any] | None = None
    if normalized_subject is None:
        pages_validation_gaps.append(
            {
                "kind": "invalid_subject_sha",
                "status": None,
                "endpoint": pages_endpoint,
                "source": "pages_subject_deployment_status",
                "message": "Pages publication evidence cannot be stamped without a full subject SHA",
            }
        )
    else:
        pages_subject_endpoint = _api_path(
            repository,
            f"/pages/deployments/{quote(normalized_subject, safe='')}",
        )
        pages_subject_result = client.get(pages_subject_endpoint)
        pages_checks.append(
            ("pages_subject_deployment_status", pages_subject_endpoint, pages_subject_result)
        )
        if pages_subject_result.get("ok"):
            raw_subject_status = pages_subject_result.get("data")
            if (
                not isinstance(raw_subject_status, dict)
                or not isinstance(raw_subject_status.get("status"), str)
                or not raw_subject_status["status"]
            ):
                pages_validation_gaps.append(
                    {
                        "kind": "malformed_pages_status",
                        "status": pages_subject_result.get("status"),
                        "endpoint": pages_subject_endpoint,
                        "source": "pages_subject_deployment_status",
                        "message": "GitHub returned a Pages deployment status without a status value",
                    }
                )
            else:
                pages_subject_status = {
                    **raw_subject_status,
                    "observed_subject_sha": normalized_subject,
                    "matches_subject": True,
                }

    pages_site: dict[str, Any] | None = None
    if pages_site_result.get("ok"):
        raw_site = pages_site_result.get("data")
        if (
            not isinstance(raw_site, dict)
            or not isinstance(raw_site.get("status"), str)
            or not raw_site["status"]
        ):
            pages_validation_gaps.append(
                {
                    "kind": "malformed_pages_site",
                    "status": pages_site_result.get("status"),
                    "endpoint": pages_endpoint,
                    "source": "pages_site",
                    "message": "GitHub returned a Pages site without a current status value",
                }
            )
        else:
            pages_site = dict(raw_site)

    normalized_builds: list[dict[str, Any]] = []
    for index, build in enumerate(pages_builds_result["items"]):
        if not isinstance(build, dict):
            pages_validation_gaps.append(
                {
                    "kind": "malformed_pages_build",
                    "status": None,
                    "endpoint": pages_builds_endpoint,
                    "source": "pages_builds",
                    "message": f"Pages build row {index} is not an object",
                }
            )
            continue
        build_url = build.get("url")
        build_sha = build.get("commit")
        build_status = build.get("status")
        if (
            not isinstance(build_url, str)
            or not build_url
            or not isinstance(build_sha, str)
            or not SHA_PATTERN.fullmatch(build_sha)
            or not isinstance(build_status, str)
            or not build_status
        ):
            pages_validation_gaps.append(
                {
                    "kind": "malformed_pages_build",
                    "status": None,
                    "endpoint": pages_builds_endpoint,
                    "source": "pages_builds",
                    "message": (
                        f"Pages build row {index} lacks an exact URL, commit SHA, or status"
                    ),
                }
            )
            continue
        normalized_builds.append(
            {
                **build,
                "commit": build_sha.lower(),
                "observed_subject_sha": normalized_subject,
                "matches_subject": (
                    build_sha.lower() == normalized_subject if normalized_subject is not None else None
                ),
            }
        )

    pages_current_build: dict[str, Any] | None = None
    pages_latest_endpoint: str | None = None
    if pages_builds_result["items"]:
        pages_latest_endpoint = _api_path(repository, "/pages/builds/latest")
        pages_latest_result = client.get(pages_latest_endpoint)
        pages_checks.append(("pages_latest_build", pages_latest_endpoint, pages_latest_result))
        if pages_latest_result.get("ok"):
            raw_latest = pages_latest_result.get("data")
            latest_url = raw_latest.get("url") if isinstance(raw_latest, dict) else None
            latest_sha = raw_latest.get("commit") if isinstance(raw_latest, dict) else None
            latest_status = raw_latest.get("status") if isinstance(raw_latest, dict) else None
            if (
                not isinstance(raw_latest, dict)
                or not isinstance(latest_url, str)
                or not latest_url
                or not isinstance(latest_sha, str)
                or not SHA_PATTERN.fullmatch(latest_sha)
                or not isinstance(latest_status, str)
                or not latest_status
            ):
                pages_validation_gaps.append(
                    {
                        "kind": "malformed_pages_build",
                        "status": pages_latest_result.get("status"),
                        "endpoint": pages_latest_endpoint,
                        "source": "pages_latest_build",
                        "message": "GitHub returned a latest Pages build without exact identity fields",
                    }
                )
            else:
                pages_current_build = {
                    **raw_latest,
                    "commit": latest_sha.lower(),
                    "observed_subject_sha": normalized_subject,
                    "matches_subject": (
                        latest_sha.lower() == normalized_subject
                        if normalized_subject is not None
                        else None
                    ),
                }
                matching_history_rows = [
                    build
                    for build in normalized_builds
                    if build.get("url") == latest_url
                    and build.get("commit") == latest_sha.lower()
                    and build.get("created_at") == raw_latest.get("created_at")
                ]
                if len(matching_history_rows) != 1:
                    pages_validation_gaps.append(
                        {
                            "kind": "pages_latest_history_mismatch",
                            "status": pages_latest_result.get("status"),
                            "endpoint": pages_latest_endpoint,
                            "source": "pages_latest_build",
                            "message": (
                                "The current Pages build does not occur exactly once in the "
                                "complete build-history population"
                            ),
                        }
                    )

    gaps.extend(pages_validation_gaps)
    pages_complete = not pages_validation_gaps and all(
        _result_complete(result) for _, _, result in pages_checks
    )

    page_selectors: dict[str, Any] = {}
    if pages_site is not None:
        for selector_name in ("html_url", "cname"):
            selector_value = pages_site.get(selector_name)
            if isinstance(selector_value, str) and selector_value:
                page_selectors[selector_name] = selector_value
        source = pages_site.get("source")
        if isinstance(source, dict):
            for source_name in ("branch", "path"):
                source_value = source.get(source_name)
                if isinstance(source_value, str) and source_value:
                    page_selectors[f"source_{source_name}"] = source_value
    if pages_site is not None or pages_current_build is not None:
        current_sha = pages_current_build.get("commit") if pages_current_build else None
        inventory_items.append(
            {
                "inventory_id": "github-pages:site",
                "adapter_id": "github-pages",
                "delivery_kind": "pages",
                "repository": repository,
                "unit_selector": None,
                "selectors": page_selectors,
                "observed_subject_sha": normalized_subject,
                "source_sha": current_sha,
                "matches_subject": (
                    current_sha == normalized_subject
                    if isinstance(current_sha, str) and normalized_subject is not None
                    else None
                ),
                "status": {
                    "site": pages_site.get("status") if pages_site else None,
                    "current_build": pages_current_build.get("status") if pages_current_build else None,
                    "subject_deployment": (
                        pages_subject_status.get("status") if pages_subject_status else None
                    ),
                },
            }
        )

    inventory_adapters = [
        {
            "adapter_id": "github-deployments",
            "delivery_kind": "deployment",
            "state": "observed" if deployment_complete else "unknown",
            "population_complete": deployment_complete,
            "repository_scope": "exact",
            "selector_fields": ["deployment_id", "environment", "ref", "task"],
            "item_count": sum(
                1 for item in inventory_items if item["adapter_id"] == "github-deployments"
            ),
        },
        {
            "adapter_id": "github-pages",
            "delivery_kind": "pages",
            "state": "observed" if pages_complete else "unknown",
            "population_complete": pages_complete,
            "repository_scope": "exact",
            "required_repository_permission": "pages:read",
            "selector_fields": ["html_url", "cname", "source_branch", "source_path"],
            "item_count": sum(
                1 for item in inventory_items if item["adapter_id"] == "github-pages"
            ),
        },
        {
            "adapter_id": "github-packages",
            "delivery_kind": "package",
            "state": "unsupported",
            "population_complete": False,
            "repository_scope": "unsupported",
            "selector_fields": [],
            "item_count": 0,
            "reason": (
                "Official GitHub REST package-list endpoints are owner scoped; "
                "this repository-scoped collector does not call them or infer package identity"
            ),
        },
    ]

    checks = deployment_checks + pages_checks
    return _make_group(
        evidence_id="E-GH-DELIVERY",
        source="github-rest:delivery",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "deployments": deployments,
            "environments": environments_result["items"],
            "pages": {
                "state": "observed" if pages_complete else "unknown",
                "site": pages_site,
                "builds": normalized_builds,
                "current_build": pages_current_build,
                "subject_deployment_status": pages_subject_status,
                "observed_subject_sha": normalized_subject,
                "current_build_source_sha": (
                    pages_current_build.get("commit") if pages_current_build else None
                ),
                "current_build_matches_subject": (
                    pages_current_build.get("matches_subject") if pages_current_build else None
                ),
                "population_complete": pages_complete,
            },
            "inventory": {
                "schema_version": DELIVERY_INVENTORY_SCHEMA,
                "repository": repository,
                "observed_subject_sha": normalized_subject,
                "adapters": inventory_adapters,
                "items": inventory_items,
            },
        },
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )


def collect_rules(
    repository: str,
    *,
    main_branch: str,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    max_rulesets_for_details: int = 1_000,
    observed_at: str | None = None,
) -> dict[str, Any]:
    rulesets_endpoint = _api_path(repository, "/rulesets", {"includes_parents": "true", "per_page": 100})
    effective_endpoint = _api_path(
        repository,
        f"/rules/branches/{quote(main_branch, safe='')}",
        {"per_page": 100},
    )
    protection_endpoint = _api_path(repository, f"/branches/{quote(main_branch, safe='')}/protection")
    rulesets_result = client.paginate(rulesets_endpoint)
    effective_result = client.paginate(effective_endpoint)
    protection_result = client.get(protection_endpoint)
    checks: list[tuple[str, str, dict[str, Any]]] = [
        ("rulesets", rulesets_endpoint, rulesets_result),
        ("effective_branch_rules", effective_endpoint, effective_result),
    ]
    gaps: list[dict[str, Any]] = []
    if len(rulesets_result["items"]) > max_rulesets_for_details:
        gaps.append(
            {
                "kind": "ruleset_detail_cap",
                "status": None,
                "endpoint": rulesets_endpoint,
                "source": "ruleset_details",
                "message": (
                    f"Ruleset detail collection capped at {max_rulesets_for_details} "
                    f"of {len(rulesets_result['items'])} rulesets"
                ),
            }
        )
    rulesets: list[dict[str, Any]] = []
    detail_results: list[dict[str, Any]] = []
    for summary in rulesets_result["items"][:max_rulesets_for_details]:
        ruleset_id = summary.get("id") if isinstance(summary, dict) else None
        if not isinstance(ruleset_id, int):
            gaps.append(
                {
                    "kind": "invalid_ruleset",
                    "status": None,
                    "endpoint": rulesets_endpoint,
                    "source": "ruleset_details",
                    "message": "A ruleset did not contain an integer id",
                }
            )
            rulesets.append({"summary": summary, "detail": None})
            continue
        detail_endpoint = _api_path(repository, f"/rulesets/{ruleset_id}")
        detail_result = client.get(detail_endpoint)
        detail_results.append(detail_result)
        checks.append((f"ruleset_{ruleset_id}_detail", detail_endpoint, detail_result))
        rulesets.append(
            {
                "summary": summary,
                "detail": detail_result.get("data") if detail_result.get("ok") else None,
            }
        )
    equivalent_rules_complete = (
        _result_complete(rulesets_result)
        and _result_complete(effective_result)
        and bool(rulesets_result["items"])
        and bool(effective_result["items"])
        and len(detail_results) == len(rulesets_result["items"])
        and all(_result_complete(result) for result in detail_results)
    )
    limitations: list[dict[str, Any]] = []
    protection_is_optional = (
        protection_result.get("status") == 403 and equivalent_rules_complete
    )
    if protection_is_optional:
        limitations.append(
            {
                "kind": "classic_branch_protection_unavailable",
                "status": 403,
                "endpoint": protection_endpoint,
                "source": "branch_protection",
                "message": (
                    "Classic branch-protection detail was not readable; complete effective rules "
                    "and ruleset detail are retained as equivalent assertions"
                ),
            }
        )
    else:
        checks.append(("branch_protection", protection_endpoint, protection_result))
    group = _make_group(
        evidence_id="E-GH-RULES",
        source="github-rest:rules",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "rulesets": rulesets,
            "effective_branch_rules": effective_result["items"],
            "branch_protection": protection_result.get("data") if protection_result.get("ok") else None,
        },
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )
    group["limitations"] = limitations
    if protection_is_optional:
        group["request"]["endpoints"].append(
            _request_record("branch_protection", protection_endpoint, protection_result)
        )
    return group


def collect_security(
    repository: str,
    *,
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    observed_at: str | None = None,
) -> dict[str, Any]:
    scan_history_endpoint = _api_path(repository, "/secret-scanning/scan-history")
    secret_alerts_endpoint = _api_path(repository, "/secret-scanning/alerts", {"per_page": 100})
    dependabot_endpoint = _api_path(repository, "/dependabot/alerts", {"per_page": 100})
    code_scanning_endpoint = _api_path(repository, "/code-scanning/alerts", {"per_page": 100})
    sbom_endpoint = _api_path(repository, "/dependency-graph/sbom")
    scan_history_result = client.get(scan_history_endpoint)
    secret_alerts_result = client.paginate(secret_alerts_endpoint)
    dependabot_result = client.paginate(dependabot_endpoint)
    code_scanning_result = client.paginate(code_scanning_endpoint)
    sbom_result = client.get(sbom_endpoint)
    checks = [
        ("secret_scanning_scan_history", scan_history_endpoint, scan_history_result),
        ("secret_scanning_alerts", secret_alerts_endpoint, secret_alerts_result),
        ("dependabot_alerts", dependabot_endpoint, dependabot_result),
        ("code_scanning_alerts", code_scanning_endpoint, code_scanning_result),
        ("dependency_graph_sbom", sbom_endpoint, sbom_result),
    ]
    return _make_group(
        evidence_id="E-GH-SECURITY",
        source="github-rest:security",
        subject_sha=subject_sha,
        unit=unit,
        data={
            "secret_scanning_scan_history": (
                scan_history_result.get("data") if scan_history_result.get("ok") else None
            ),
            "secret_scanning_alerts": secret_alerts_result["items"],
            "dependabot_alerts": dependabot_result["items"],
            "code_scanning_alerts": code_scanning_result["items"],
            "sbom": sbom_result.get("data") if sbom_result.get("ok") else None,
        },
        checks=checks,
        observed_at=observed_at,
    )


def collect_attestations(
    repository: str,
    *,
    releases: Iterable[dict[str, Any]],
    subject_sha: str | None,
    unit: str | None,
    client: GitHubRESTClient,
    observed_at: str | None = None,
) -> dict[str, Any]:
    checks: list[tuple[str, str, dict[str, Any]]] = []
    gaps: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    seen_digests: set[str] = set()
    for release in releases:
        if not isinstance(release, dict):
            continue
        release_id = release.get("id")
        release_assets = release.get("assets")
        if not isinstance(release_assets, list):
            continue
        for asset in release_assets:
            if not isinstance(asset, dict):
                continue
            digest = asset.get("digest")
            record = {
                "release_id": release_id,
                "asset_id": asset.get("id"),
                "name": asset.get("name"),
                "digest": digest,
                "attestations": [],
            }
            if not isinstance(digest, str) or not SHA256_DIGEST_PATTERN.fullmatch(digest):
                gaps.append(
                    {
                        "kind": "asset_digest_unavailable",
                        "status": None,
                        "endpoint": None,
                        "source": "release_asset",
                        "message": f"Release asset {asset.get('name') or asset.get('id')} has no SHA-256 digest",
                    }
                )
                assets.append(record)
                continue
            normalized_digest = digest.lower()
            if normalized_digest in seen_digests:
                record["duplicate_digest"] = True
                assets.append(record)
                continue
            seen_digests.add(normalized_digest)
            endpoint = _api_path(
                repository,
                f"/attestations/{quote(normalized_digest, safe=':')}",
                {"per_page": 100},
            )
            result = client.paginate(endpoint, "attestations")
            checks.append((f"attestations_{normalized_digest}", endpoint, result))
            record["attestations"] = result["items"]
            record["complete"] = result["complete"]
            assets.append(record)
    return _make_group(
        evidence_id="E-GH-ATTESTATIONS",
        source="github-rest:attestations",
        subject_sha=subject_sha,
        unit=unit,
        data={"assets": assets},
        checks=checks,
        gaps=gaps,
        observed_at=observed_at,
    )


def collect_github_observations(
    repository: str,
    *,
    main_branch: str | None = None,
    subject_sha: str | None = None,
    unit: str | None = None,
    release_asset_names: Iterable[str] = (),
    client: GitHubRESTClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect the GitHub-native observation bundle used by health metrics."""

    timestamp = _iso_z(_as_utc(now))
    owner_repo = repository.strip("/")
    if not REPOSITORY_PATTERN.fullmatch(owner_repo):
        gap = {
            "kind": "invalid_repository",
            "status": None,
            "endpoint": None,
            "source": "github-rest",
            "message": "GitHub repository identity must be owner/name",
        }
        return {
            "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
            "observed_at": timestamp,
            "repository": owner_repo,
            "subject_sha": subject_sha,
            "unit": unit,
            "state": "unknown",
            "completeness": "unknown",
            "complete": False,
            "population_complete": False,
            "observations": {},
            "gaps": [gap],
        }
    github = client or GitHubRESTClient()
    identity = collect_repository_identity(
        owner_repo,
        main_branch=main_branch,
        subject_sha=subject_sha,
        unit=unit,
        client=github,
        observed_at=timestamp,
    )
    identity_data = identity.get("data", {})
    resolved_branch = identity_data.get("main_branch") or main_branch
    resolved_sha = identity_data.get("main_sha") or subject_sha
    observations: dict[str, dict[str, Any]] = {"repository_identity": identity}
    if not isinstance(resolved_branch, str) or not resolved_branch:
        for key, evidence_id, source in (
            ("check_runs", "E-GH-CHECK-RUNS", "github-rest:check-runs"),
            ("actions_w90", "E-GH-ACTIONS-W90", "github-rest:actions-w90"),
            ("actions_w365", "E-GH-ACTIONS-W365", "github-rest:actions-w365"),
            ("change_history", "E-GH-CHANGE-HISTORY", "github-rest:change-history"),
            ("rules", "E-GH-RULES", "github-rest:rules"),
        ):
            observations[key] = _unknown_group(
                evidence_id,
                source,
                resolved_sha,
                unit,
                "A resolved Main branch is required for this observation",
                observed_at=timestamp,
            )
    else:
        observations["check_runs"] = collect_check_runs(
            owner_repo,
            subject_sha=resolved_sha,
            unit=unit,
            client=github,
            observed_at=timestamp,
        )
        actions_w365 = collect_action_history(
            owner_repo,
            main_branch=resolved_branch,
            subject_sha=resolved_sha,
            unit=unit,
            client=github,
            days=365,
            now=now,
            observed_at=timestamp,
        )
        observations["actions_w365"] = actions_w365
        observations["actions_w90"] = slice_action_history(actions_w365, days=90, now=now)
        observations["change_history"] = collect_change_history(
            owner_repo,
            main_branch=resolved_branch,
            subject_sha=resolved_sha,
            unit=unit,
            client=github,
            now=now,
            observed_at=timestamp,
        )
        observations["rules"] = collect_rules(
            owner_repo,
            main_branch=resolved_branch,
            subject_sha=resolved_sha,
            unit=unit,
            client=github,
            observed_at=timestamp,
        )
    refs_releases = collect_refs_and_releases(
        owner_repo,
        subject_sha=resolved_sha,
        unit=unit,
        client=github,
        release_asset_names=release_asset_names,
        observed_at=timestamp,
    )
    observations["refs_releases"] = refs_releases
    observations["delivery"] = collect_delivery(
        owner_repo,
        subject_sha=resolved_sha,
        unit=unit,
        client=github,
        observed_at=timestamp,
    )
    observations["security"] = collect_security(
        owner_repo,
        subject_sha=resolved_sha,
        unit=unit,
        client=github,
        observed_at=timestamp,
    )
    observations["attestations"] = collect_attestations(
        owner_repo,
        releases=refs_releases.get("data", {}).get("releases", []),
        subject_sha=resolved_sha,
        unit=unit,
        client=github,
        observed_at=timestamp,
    )
    complete = all(group.get("complete") is True for group in observations.values())
    gaps = [
        {"observation": name, **gap}
        for name, group in observations.items()
        for gap in group.get("gaps", [])
    ]
    any_observed = any(group.get("completeness") in {"complete", "partial"} for group in observations.values())
    return {
        "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
        "observed_at": timestamp,
        "repository": owner_repo,
        "subject_sha": resolved_sha,
        "unit": unit,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else ("partial" if any_observed else "unknown"),
        "complete": complete,
        "population_complete": complete,
        "observations": observations,
        "gaps": gaps,
    }

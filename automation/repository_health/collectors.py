"""Read-only local Git and GitHub REST evidence collectors."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "Gemfile",
    "Gemfile.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "composer.lock",
    "packages.lock.json",
    "*.csproj",
    ".gitmodules",
}
LOCK_FILES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Gemfile.lock",
    "go.sum",
    "Cargo.lock",
    "composer.lock",
    "packages.lock.json",
}
SUCCESS_CONCLUSIONS = {"success"}
FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}


def _git(repository: Path, *args: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return result.returncode == 0, (result.stdout if result.returncode == 0 else result.stderr).strip()


def _exists_any(repository: Path, names: set[str]) -> list[str]:
    found: list[str] = []
    for candidate in names:
        if "*" in candidate:
            found.extend(str(path.relative_to(repository)) for path in repository.glob(candidate) if path.is_file())
        else:
            found.extend(
                str(path.relative_to(repository))
                for path in repository.rglob(candidate)
                if path.is_file() and ".git" not in path.parts
            )
    return sorted(set(found))


def _first_existing(repository: Path, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        path = repository / candidate
        if path.is_file():
            return candidate
    return None


def infer_github_repository(repository: Path) -> str | None:
    env_name = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if re.fullmatch(r"[^/\s]+/[^/\s]+", env_name):
        return env_name
    success, remote = _git(repository, "remote", "get-url", "origin")
    if not success:
        return None
    match = re.search(r"github\.com(?::|/)([^/\s]+)/([^/\s]+?)(?:\.git)?$", remote)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def collect_local(repository: str | Path, configured_main: str = "") -> dict[str, Any]:
    """Collect local facts without executing repository-owned code."""

    root = Path(repository).resolve()
    is_git, _ = _git(root, "rev-parse", "--git-dir")
    head_ok, head_sha = _git(root, "rev-parse", "HEAD") if is_git else (False, "")
    branch_ok, current_branch = _git(root, "branch", "--show-current") if is_git else (False, "")

    main_branch = configured_main.strip()
    if not main_branch and is_git:
        default_ok, remote_head = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if default_ok and "/" in remote_head:
            main_branch = remote_head.split("/", 1)[1]
        else:
            for candidate in ("main", "master"):
                exists, _ = _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}")
                if exists:
                    main_branch = candidate
                    break
    if not main_branch:
        main_branch = current_branch if branch_ok and current_branch else "main"

    main_ok, main_sha = _git(root, "rev-parse", main_branch) if is_git else (False, "")
    main_ref_source = "local" if main_ok else None
    if is_git and not main_ok:
        main_ok, main_sha = _git(root, "rev-parse", f"refs/remotes/origin/{main_branch}")
        if main_ok:
            main_ref_source = "origin"
    clean_ok, status = _git(root, "status", "--porcelain") if is_git else (False, "")
    commits_ok, commit_count_text = _git(root, "rev-list", "--count", "HEAD") if head_ok else (False, "")
    contributor_ok, contributors_text = _git(root, "shortlog", "-sne", "HEAD") if head_ok else (False, "")
    branches_ok, branches_text = _git(root, "for-each-ref", "--format=%(refname:short)|%(committerdate:iso8601)", "refs/heads") if is_git else (False, "")
    tags_ok, tags_text = _git(root, "tag", "--list") if is_git else (False, "")
    last_ok, last_commit = _git(root, "log", "-1", "--format=%cI") if head_ok else (False, "")

    workflows = sorted(
        str(path.relative_to(root))
        for pattern in ("*.yml", "*.yaml")
        for path in (root / ".github" / "workflows").glob(pattern)
        if path.is_file()
    )
    dependency_files = _exists_any(root, DEPENDENCY_FILES)
    lock_files = [path for path in dependency_files if Path(path).name in LOCK_FILES]
    codeowners = _first_existing(root, ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"))
    readme = _first_existing(root, ("README.md", "README.rst", "README.txt", "README"))
    license_file = _first_existing(root, ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"))
    contributing = _first_existing(root, ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"))
    security = _first_existing(root, ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"))
    support = _first_existing(root, ("SUPPORT.md", ".github/SUPPORT.md", "docs/SUPPORT.md"))
    changelog = _first_existing(root, ("CHANGELOG.md", "CHANGES.md", "HISTORY.md"))
    owners = _first_existing(root, ("OWNERS", ".github/OWNERS", "MAINTAINERS.md", ".github/CODEOWNERS", "CODEOWNERS"))

    branch_records = []
    if branches_ok:
        for line in branches_text.splitlines():
            name, _, date = line.partition("|")
            branch_records.append({"name": name, "last_commit_at": date or None})
    contributor_count = len([line for line in contributors_text.splitlines() if line.strip()]) if contributor_ok else None

    return {
        "root": str(root),
        "is_git_repository": is_git,
        "head_sha": head_sha if head_ok else None,
        "current_branch": current_branch if branch_ok else None,
        "main_branch": main_branch,
        "main_sha": main_sha if main_ok else None,
        "main_ref_source": main_ref_source,
        "head_is_main": (bool(head_sha == main_sha) if head_ok and main_ok else None),
        "working_tree_clean": (not bool(status)) if clean_ok else None,
        "commit_count": int(commit_count_text) if commits_ok and commit_count_text.isdigit() else None,
        "contributor_count": contributor_count,
        "last_commit_at": last_commit if last_ok else None,
        "branches": branch_records,
        "branch_count": len(branch_records) if branches_ok else None,
        "tags": [line for line in tags_text.splitlines() if line] if tags_ok else [],
        "tag_count": len([line for line in tags_text.splitlines() if line]) if tags_ok else None,
        "workflows": workflows,
        "dependency_files": dependency_files,
        "lock_files": lock_files,
        "documents": {
            "readme": readme,
            "license": license_file,
            "contributing": contributing,
            "security": security,
            "support": support,
            "changelog": changelog,
            "ownership": owners,
            "codeowners": codeowners,
        },
        "github_repository": infer_github_repository(root),
    }


class GitHubClient:
    """Minimal, failure-tolerant GitHub REST client."""

    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.token = token or ""
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.transport = transport or urlopen

    def get(self, path: str, accept: str = "application/vnd.github+json") -> dict[str, Any]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "repository-health-assessment/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.api_url}{path}", headers=headers)
        try:
            with self.transport(request, timeout=15) as response:
                body = response.read()
                return {
                    "ok": True,
                    "status": getattr(response, "status", 200),
                    "data": json.loads(body.decode("utf-8")) if body else None,
                    "error": None,
                }
        except HTTPError as error:
            # 403/404 frequently mean the token cannot see a protected setting,
            # not that the setting is absent. Preserve the gap as Unknown.
            status = error.code
            error.close()
            return {"ok": False, "status": status, "data": None, "error": f"HTTP {status}"}
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            return {"ok": False, "status": None, "data": None, "error": type(error).__name__}


def collect_github(repository_name: str | None, main_branch: str, head_sha: str | None, client: GitHubClient) -> dict[str, Any]:
    """Collect GitHub evidence; inaccessible endpoints become explicit gaps."""

    if not repository_name:
        return {"available": False, "repository": None, "data": {}, "gaps": ["GitHub repository identity unavailable."]}
    owner_repo = repository_name.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", owner_repo):
        return {"available": False, "repository": owner_repo, "data": {}, "gaps": ["GitHub repository identity is invalid."]}
    encoded_main = quote(main_branch, safe="")
    endpoints: dict[str, str] = {
        "repository": f"/repos/{owner_repo}",
        "branch": f"/repos/{owner_repo}/branches/{encoded_main}",
        "protection": f"/repos/{owner_repo}/branches/{encoded_main}/protection",
        "workflows": f"/repos/{owner_repo}/actions/workflows?per_page=100",
        "pull_requests": f"/repos/{owner_repo}/pulls?state=closed&base={encoded_main}&per_page=100&sort=updated&direction=desc",
        "releases": f"/repos/{owner_repo}/releases?per_page=100",
        "tags": f"/repos/{owner_repo}/tags?per_page=100",
        "rulesets": f"/repos/{owner_repo}/rulesets?includes_parents=true&per_page=100",
    }
    if head_sha:
        endpoints["check_runs"] = f"/repos/{owner_repo}/commits/{head_sha}/check-runs?per_page=100"
    data: dict[str, Any] = {}
    gaps: list[str] = []
    statuses: dict[str, int | None] = {}
    for name, path in endpoints.items():
        result = client.get(path)
        statuses[name] = result["status"]
        if result["ok"]:
            data[name] = result["data"]
        else:
            gaps.append(f"GitHub {name} evidence unavailable ({result['error']}).")
    resolved_main_sha = head_sha
    branch_data = data.get("branch")
    if not resolved_main_sha and isinstance(branch_data, dict):
        commit = branch_data.get("commit")
        if isinstance(commit, dict) and re.fullmatch(r"[0-9a-fA-F]{40}", str(commit.get("sha", ""))):
            resolved_main_sha = str(commit["sha"])
    if resolved_main_sha and "check_runs" not in endpoints:
        result = client.get(f"/repos/{owner_repo}/commits/{resolved_main_sha}/check-runs?per_page=100")
        statuses["check_runs"] = result["status"]
        if result["ok"]:
            data["check_runs"] = result["data"]
        else:
            gaps.append(f"GitHub check_runs evidence unavailable ({result['error']}).")
    return {
        "available": bool(data),
        "repository": owner_repo,
        "main_sha": resolved_main_sha,
        "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "data": data,
        "endpoint_status": statuses,
        "gaps": gaps,
    }


def github_check_state(github: dict[str, Any], authoritative_checks: list[str] | None = None) -> tuple[str, list[str]]:
    check_data = github.get("data", {}).get("check_runs")
    if not isinstance(check_data, dict):
        return "unknown", []
    runs = check_data.get("check_runs")
    if not isinstance(runs, list) or not runs:
        return "unknown", []
    selected = set(authoritative_checks or [])
    if not selected:
        return "unknown", []
    runs = [run for run in runs if str(run.get("name", "")) in selected]
    observed = {str(run.get("name", "")) for run in runs}
    if not runs or observed != selected:
        return "unknown", sorted(observed)
    names = [str(run.get("name", "unnamed")) for run in runs]
    if any(run.get("status") != "completed" for run in runs):
        return "pending", names
    conclusions = {str(run.get("conclusion")) for run in runs}
    if conclusions & FAILURE_CONCLUSIONS:
        return "failed", names
    if conclusions and conclusions <= SUCCESS_CONCLUSIONS:
        return "successful", names
    return "unknown", names


def github_protection_state(github: dict[str, Any]) -> str:
    protection = github.get("data", {}).get("protection")
    if isinstance(protection, dict):
        return "configured"
    branch = github.get("data", {}).get("branch")
    if isinstance(branch, dict) and branch.get("protected") is False:
        return "unprotected"
    if isinstance(branch, dict) and branch.get("protected") is True:
        return "protected_details_unknown"
    return "unknown"

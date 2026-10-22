from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from automation.repository_health.github_client import DEFAULT_API_VERSION, GitHubRESTClient
from automation.repository_health.github_collectors import (
    collect_action_history,
    collect_attestations,
    collect_change_history,
    collect_delivery,
    collect_github_observations,
    collect_refs_and_releases,
    collect_repository_identity,
    collect_rules,
    collect_security,
)
from automation.repository_health.workflow_dependencies import collect_workflow_dependencies


API = "https://api.example"
REPOSITORY = "octo/health"
MAIN_SHA = "1" * 40


def git_commit_fixture(root: Path) -> str:
    commands = (
        ("init", "-b", "main"),
        ("config", "user.name", "GitHub Collector Test"),
        ("config", "user.email", "collector@example.invalid"),
        ("add", "-A"),
        ("commit", "-m", "Fixture"),
    )
    for arguments in commands:
        subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class FixtureResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        url: str | None = None,
    ) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.url = url
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        body = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode("utf-8")
        return body if amount < 0 else body[:amount]

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str | None:
        return self.url

    def __enter__(self) -> "FixtureResponse":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        self.close()
        return False


class FixtureTransport:
    def __init__(self, routes: dict[str, object], default: object | None = None) -> None:
        self.routes = routes
        self.default = default
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: int) -> FixtureResponse:
        self.requests.append(request)
        url = request.full_url  # type: ignore[attr-defined]
        route = self.routes.get(url, self.default)
        if route is None:
            raise AssertionError(f"Unexpected fixture URL: {url}")
        if isinstance(route, BaseException):
            raise route
        if callable(route):
            route = route(request, timeout)
        if isinstance(route, BaseException):
            raise route
        if not isinstance(route, FixtureResponse):
            raise AssertionError(f"Invalid fixture for {url}: {route!r}")
        return route


def http_error(url: str, status: int) -> HTTPError:
    return HTTPError(url, status, f"fixture {status}", {}, None)


def api(path: str) -> str:
    return f"{API}{path}"


class GitHubClientTests(unittest.TestCase):
    def test_same_origin_rfc_link_pagination_and_version_header(self) -> None:
        first = api("/repos/octo/health/items?per_page=1")
        second = api("/repos/octo/health/items?per_page=1&page=2")
        transport = FixtureTransport(
            {
                first: FixtureResponse(
                    [{"id": 1}],
                    headers={
                        "Link": (
                            f'<{second}>; rel="next", '
                            f'<{second}>; rel="last"'
                        )
                    },
                ),
                second: FixtureResponse([{"id": 2}]),
            }
        )
        client = GitHubRESTClient(token="fixture-token", api_url=API, transport=transport)

        result = client.paginate("/repos/octo/health/items?per_page=1")

        self.assertEqual("observed", result["state"])
        self.assertEqual([{"id": 1}, {"id": 2}], result["items"])
        self.assertEqual(2, result["page_count"])
        self.assertTrue(result["population_complete"])
        request = transport.requests[0]
        self.assertEqual(DEFAULT_API_VERSION, request.get_header("X-github-api-version"))  # type: ignore[attr-defined]
        self.assertEqual("Bearer fixture-token", request.get_header("Authorization"))  # type: ignore[attr-defined]
        self.assertEqual("2026-03-10", DEFAULT_API_VERSION)

    def test_authenticated_json_client_rejects_http_api_origin(self) -> None:
        with self.assertRaisesRegex(ValueError, "require HTTPS"):
            GitHubRESTClient(token="must-not-cross-http", api_url="http://api.example")

    def test_json_redirect_is_not_followed_or_sent_bearer_cross_origin(self) -> None:
        endpoint = api("/repos/octo/health/redirect")
        transport = FixtureTransport(
            {
                endpoint: FixtureResponse(
                    b"",
                    status=302,
                    headers={"Location": "https://evil.example/steal"},
                    url=endpoint,
                )
            }
        )
        result = GitHubRESTClient(
            token="must-not-leak",
            api_url=API,
            transport=transport,
        ).get("/repos/octo/health/redirect")

        self.assertEqual("unknown", result["state"])
        self.assertEqual("unsafe_redirect", result["error_kind"])
        self.assertEqual(1, len(transport.requests))
        self.assertEqual("Bearer must-not-leak", transport.requests[0].get_header("Authorization"))  # type: ignore[attr-defined]

    def test_cross_origin_next_link_is_rejected_and_partial_rows_retained(self) -> None:
        first = api("/repos/octo/health/items")
        transport = FixtureTransport(
            {
                first: FixtureResponse(
                    [{"id": 1}],
                    headers={"Link": '<https://evil.example/steal>; rel="next"'},
                )
            }
        )
        result = GitHubRESTClient(token="secret", api_url=API, transport=transport).paginate(
            "/repos/octo/health/items"
        )

        self.assertEqual("unknown", result["state"])
        self.assertEqual("partial", result["completeness"])
        self.assertEqual([{"id": 1}], result["items"])
        self.assertEqual("unsafe_origin", result["gap"])
        self.assertEqual(1, len(transport.requests))

    def test_failed_later_page_is_explicit_unknown_with_partial_population(self) -> None:
        first = api("/repos/octo/health/items")
        second = api("/repos/octo/health/items?page=2")
        transport = FixtureTransport(
            {
                first: FixtureResponse([{"id": 1}], headers={"Link": f'<{second}>; rel="next"'}),
                second: http_error(second, 403),
            }
        )
        result = GitHubRESTClient(api_url=API, transport=transport).paginate("/repos/octo/health/items")

        self.assertEqual([{"id": 1}], result["items"])
        self.assertFalse(result["complete"])
        self.assertEqual("permission_or_api_gap", result["gap"])
        self.assertEqual(403, result["pages"][-1]["status"])

    def test_population_count_mismatch_and_caps_fail_closed(self) -> None:
        count_url = api("/repos/octo/health/runs")
        count_transport = FixtureTransport(
            {count_url: FixtureResponse({"total_count": 3, "workflow_runs": [{"id": 1}]})}
        )
        mismatch = GitHubRESTClient(api_url=API, transport=count_transport).paginate(
            "/repos/octo/health/runs", "workflow_runs"
        )
        self.assertEqual("population_mismatch", mismatch["gap"])
        self.assertFalse(mismatch["population_complete"])

        first = api("/repos/octo/health/items")
        second = api("/repos/octo/health/items?page=2")
        cap_transport = FixtureTransport(
            {first: FixtureResponse([1], headers={"Link": f'<{second}>; rel="next"'})}
        )
        capped = GitHubRESTClient(api_url=API, transport=cap_transport, max_pages=1).paginate(
            "/repos/octo/health/items"
        )
        self.assertTrue(capped["truncated"])
        self.assertEqual("page_cap", capped["gap"])
        self.assertEqual([1], capped["items"])

    def test_keyed_pagination_requires_exact_integer_total_count(self) -> None:
        fixtures = (
            ("missing", {"check_runs": []}, "invalid_collection"),
            ("boolean", {"total_count": True, "check_runs": []}, "invalid_collection"),
            ("malformed", {"total_count": "0", "check_runs": []}, "invalid_collection"),
            ("too-small", {"total_count": 0, "check_runs": [{"id": 1}]}, "population_mismatch"),
        )
        for label, payload, expected_gap in fixtures:
            with self.subTest(label=label):
                endpoint = api(f"/repos/octo/health/check-runs/{label}")
                transport = FixtureTransport({endpoint: FixtureResponse(payload)})

                result = GitHubRESTClient(api_url=API, transport=transport).paginate(
                    f"/repos/octo/health/check-runs/{label}",
                    "check_runs",
                )

                self.assertEqual("unknown", result["state"])
                self.assertFalse(result["complete"])
                self.assertFalse(result["population_complete"])
                self.assertEqual(expected_gap, result["gap"])

    def test_404_and_network_failures_are_unknown_not_absent(self) -> None:
        missing = api("/repos/octo/health/protected")
        offline = api("/repos/octo/health/offline")
        transport = FixtureTransport(
            {
                missing: http_error(missing, 404),
                offline: URLError("fixture offline"),
            }
        )
        client = GitHubRESTClient(api_url=API, transport=transport)
        missing_result = client.get("/repos/octo/health/protected")
        offline_result = client.get("/repos/octo/health/offline")

        self.assertEqual("unknown", missing_result["state"])
        self.assertEqual("permission_or_api_gap", missing_result["error_kind"])
        self.assertEqual("unknown", offline_result["state"])
        self.assertEqual("network_error", offline_result["error_kind"])

    def test_bounded_binary_get_validates_declared_and_actual_size(self) -> None:
        endpoint = api(f"/repos/{REPOSITORY}/releases/assets/70")
        content = b"controlled release bytes"
        transport = FixtureTransport(
            {
                endpoint: FixtureResponse(
                    content,
                    headers={"Content-Length": str(len(content))},
                    url=endpoint,
                )
            }
        )
        client = GitHubRESTClient(token="secret", api_url=API, transport=transport)

        result = client.get_binary(
            f"/repos/{REPOSITORY}/releases/assets/70",
            declared_size=len(content),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(content, result["data"])
        self.assertEqual(len(content), result["size"])
        request = transport.requests[0]
        self.assertEqual("application/octet-stream", request.get_header("Accept"))  # type: ignore[attr-defined]
        self.assertEqual(DEFAULT_API_VERSION, request.get_header("X-github-api-version"))  # type: ignore[attr-defined]

    def test_binary_get_fails_closed_on_declared_or_actual_size_cap(self) -> None:
        endpoint = api(f"/repos/{REPOSITORY}/releases/assets/70")
        declared_transport = FixtureTransport({})
        declared = GitHubRESTClient(api_url=API, transport=declared_transport).get_binary(
            f"/repos/{REPOSITORY}/releases/assets/70",
            declared_size=5,
            max_bytes=4,
        )
        self.assertEqual("response_too_large", declared["error_kind"])
        self.assertEqual([], declared_transport.requests)

        actual_transport = FixtureTransport(
            {endpoint: FixtureResponse(b"12345", url=endpoint)}
        )
        actual = GitHubRESTClient(api_url=API, transport=actual_transport).get_binary(
            f"/repos/{REPOSITORY}/releases/assets/70",
            max_bytes=4,
        )
        self.assertEqual("response_too_large", actual["error_kind"])
        self.assertIsNone(actual["data"])

    def test_binary_redirect_is_bounded_and_strips_authorization_cross_origin(self) -> None:
        api_root = "https://api.github.com"
        endpoint = f"{api_root}/repos/octo/health/releases/assets/70"
        download = "https://release-assets.githubusercontent.com/controlled.bin"

        def download_response(request: object, timeout: int) -> FixtureResponse:
            self.assertIsNone(request.get_header("Authorization"))  # type: ignore[attr-defined]
            self.assertEqual("application/octet-stream", request.get_header("Accept"))  # type: ignore[attr-defined]
            return FixtureResponse(b"safe", headers={"Content-Length": "4"}, url=download)

        transport = FixtureTransport(
            {
                endpoint: FixtureResponse(b"", status=302, headers={"Location": download}, url=endpoint),
                download: download_response,
            }
        )
        result = GitHubRESTClient(
            token="must-not-leak",
            api_url=api_root,
            transport=transport,
        ).get_binary("/repos/octo/health/releases/assets/70", declared_size=4)

        self.assertTrue(result["ok"])
        self.assertEqual(b"safe", result["data"])
        self.assertEqual(1, len(result["redirects"]))
        self.assertEqual("Bearer must-not-leak", transport.requests[0].get_header("Authorization"))  # type: ignore[attr-defined]

    def test_binary_get_rejects_unsafe_initial_and_redirect_origins(self) -> None:
        client = GitHubRESTClient(api_url=API, transport=FixtureTransport({}))
        initial = client.get_binary("https://evil.example/asset")
        self.assertEqual("unsafe_origin", initial["error_kind"])

        api_root = "https://api.github.com"
        endpoint = f"{api_root}/repos/octo/health/releases/assets/70"
        transport = FixtureTransport(
            {
                endpoint: FixtureResponse(
                    b"",
                    status=302,
                    headers={"Location": "https://evil.example/asset"},
                    url=endpoint,
                )
            }
        )
        redirected = GitHubRESTClient(
            token="secret",
            api_url=api_root,
            transport=transport,
        ).get_binary("/repos/octo/health/releases/assets/70")
        self.assertEqual("unsafe_redirect", redirected["error_kind"])
        self.assertEqual(1, len(transport.requests))

    def test_binary_http_and_transport_failures_preserve_unknown_gap_kinds(self) -> None:
        forbidden = api(f"/repos/{REPOSITORY}/releases/assets/70")
        offline = api(f"/repos/{REPOSITORY}/releases/assets/71")
        transport = FixtureTransport(
            {
                forbidden: http_error(forbidden, 403),
                offline: URLError("fixture offline"),
            }
        )
        client = GitHubRESTClient(api_url=API, transport=transport)

        forbidden_result = client.get_binary(f"/repos/{REPOSITORY}/releases/assets/70")
        offline_result = client.get_binary(f"/repos/{REPOSITORY}/releases/assets/71")

        self.assertEqual("unknown", forbidden_result["state"])
        self.assertEqual("permission_or_api_gap", forbidden_result["error_kind"])
        self.assertEqual(403, forbidden_result["status"])
        self.assertEqual("unknown", offline_result["state"])
        self.assertEqual("network_error", offline_result["error_kind"])


class GitHubObservationTests(unittest.TestCase):
    @staticmethod
    def _commit_fixture(
        sha: str,
        *,
        committed_at: str,
        parents: list[str],
    ) -> dict[str, object]:
        return {
            "sha": sha,
            "commit": {
                "author": {"name": "Fixture", "date": committed_at},
                "committer": {"name": "Fixture", "date": committed_at},
                "message": "fixture",
            },
            "author": {"login": "fixture-author"},
            "committer": {"login": "fixture-committer"},
            "parents": [{"sha": parent} for parent in parents],
        }

    def test_repository_default_branch_resolves_exact_subject_sha(self) -> None:
        repository_url = api("/repos/octo/health")
        branch_url = api("/repos/octo/health/branches/main")
        transport = FixtureTransport(
            {
                repository_url: FixtureResponse({"full_name": REPOSITORY, "default_branch": "main"}),
                branch_url: FixtureResponse({"name": "main", "commit": {"sha": MAIN_SHA}}),
            }
        )
        group = collect_repository_identity(
            REPOSITORY,
            main_branch=None,
            subject_sha=None,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            observed_at="2026-08-09T12:00:00Z",
        )

        self.assertTrue(group["complete"])
        self.assertEqual(MAIN_SHA, group["subject_sha"])
        self.assertEqual("main", group["data"]["default_branch"])
        self.assertEqual("documentation-suite", group["unit"])
        self.assertEqual("E-GH-REPOSITORY", group["evidence_id"])

    def test_repository_identity_marks_stale_supplied_sha_unknown(self) -> None:
        stale_sha = "2" * 40
        repository_url = api("/repos/octo/health")
        branch_url = api("/repos/octo/health/branches/main")
        group = collect_repository_identity(
            REPOSITORY,
            main_branch="main",
            subject_sha=stale_sha,
            unit="documentation-suite",
            client=GitHubRESTClient(
                api_url=API,
                transport=FixtureTransport(
                    {
                        repository_url: FixtureResponse(
                            {"full_name": REPOSITORY, "default_branch": "main"}
                        ),
                        branch_url: FixtureResponse(
                            {"name": "main", "commit": {"sha": MAIN_SHA}}
                        ),
                    }
                ),
            ),
        )

        self.assertFalse(group["complete"])
        self.assertEqual("unknown", group["state"])
        self.assertEqual(stale_sha, group["subject_sha"])
        self.assertEqual(MAIN_SHA, group["data"]["live_main_sha"])
        self.assertIn("subject_sha_mismatch", {gap["kind"] for gap in group["gaps"]})

    def test_action_history_collects_every_observed_attempt_and_job(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        start = now - timedelta(days=90)
        runs_query = urlencode(
            {
                "branch": "main",
                "created": (
                    f"{start.isoformat().replace('+00:00', 'Z')}.."
                    f"{now.isoformat().replace('+00:00', 'Z')}"
                ),
                "per_page": 100,
            }
        )
        runs_url = api(f"/repos/{REPOSITORY}/actions/runs?{runs_query}")
        attempt_one = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/1")
        attempt_two = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/2")
        jobs_one = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/1/jobs?per_page=100")
        jobs_two = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/2/jobs?per_page=100")
        transport = FixtureTransport(
            {
                runs_url: FixtureResponse(
                    {"total_count": 1, "workflow_runs": [{"id": 42, "run_attempt": 2, "head_sha": MAIN_SHA}]}
                ),
                attempt_one: FixtureResponse({"id": 42, "run_attempt": 1, "conclusion": "failure"}),
                attempt_two: FixtureResponse({"id": 42, "run_attempt": 2, "conclusion": "success"}),
                jobs_one: FixtureResponse({"total_count": 1, "jobs": [{"id": 100, "conclusion": "failure"}]}),
                jobs_two: FixtureResponse({"total_count": 1, "jobs": [{"id": 101, "conclusion": "success"}]}),
            }
        )
        group = collect_action_history(
            REPOSITORY,
            main_branch="main",
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            days=90,
            now=now,
        )

        self.assertTrue(group["complete"])
        self.assertEqual([1, 2], [item["attempt"] for item in group["data"]["run_attempts"]])
        self.assertEqual("failure", group["data"]["run_attempts"][0]["run"]["conclusion"])
        self.assertEqual("failure", group["data"]["run_attempts"][0]["jobs"][0]["conclusion"])
        self.assertEqual("success", group["data"]["run_attempts"][1]["jobs"][0]["conclusion"])
        self.assertEqual(
            {
                "schema_version": "RH-ACTIONS-RUN-POPULATION-1.0",
                "scope": "branch-window",
                "branch_ref": "refs/heads/main",
                "subjects": [],
            },
            group["data"]["population_contract"],
        )

    def test_action_history_request_budget_bounds_high_volume_detail_calls(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        start = now - timedelta(days=365)
        runs_query = urlencode(
            {
                "branch": "main",
                "created": (
                    f"{start.isoformat().replace('+00:00', 'Z')}.."
                    f"{now.isoformat().replace('+00:00', 'Z')}"
                ),
                "per_page": 100,
            }
        )
        runs_url = api(f"/repos/{REPOSITORY}/actions/runs?{runs_query}")
        runs = [
            {
                "id": run_id,
                "run_attempt": 1,
                "head_sha": MAIN_SHA,
                "created_at": "2026-08-01T12:00:00Z",
            }
            for run_id in range(1, 11)
        ]

        def detail_response(request: object, timeout: int) -> FixtureResponse:
            if request.full_url.endswith("/jobs?per_page=100"):  # type: ignore[attr-defined]
                return FixtureResponse({"total_count": 0, "jobs": []})
            return FixtureResponse({"id": 1, "run_attempt": 1, "conclusion": "success"})

        transport = FixtureTransport(
            {runs_url: FixtureResponse({"total_count": len(runs), "workflow_runs": runs})},
            default=detail_response,
        )
        group = collect_action_history(
            REPOSITORY,
            main_branch="main",
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            days=365,
            now=now,
            max_request_budget=5,
        )

        self.assertLessEqual(len(transport.requests), 5)
        self.assertEqual(5, group["data"]["request_budget"]["used"])
        self.assertIn("action_request_budget", {gap["kind"] for gap in group["gaps"]})
        self.assertFalse(group["complete"])

    def test_action_history_deduplicates_attempt_and_job_requests_for_duplicate_runs(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        start = now - timedelta(days=365)
        runs_query = urlencode(
            {
                "branch": "main",
                "created": (
                    f"{start.isoformat().replace('+00:00', 'Z')}.."
                    f"{now.isoformat().replace('+00:00', 'Z')}"
                ),
                "per_page": 100,
            }
        )
        runs_url = api(f"/repos/{REPOSITORY}/actions/runs?{runs_query}")
        attempt_url = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/1")
        jobs_url = api(f"/repos/{REPOSITORY}/actions/runs/42/attempts/1/jobs?per_page=100")
        duplicate = {
            "id": 42,
            "run_attempt": 1,
            "head_sha": MAIN_SHA,
            "created_at": "2026-08-01T12:00:00Z",
        }
        transport = FixtureTransport(
            {
                runs_url: FixtureResponse(
                    {"total_count": 2, "workflow_runs": [duplicate, dict(duplicate)]}
                ),
                attempt_url: FixtureResponse({**duplicate, "conclusion": "success"}),
                jobs_url: FixtureResponse({"total_count": 0, "jobs": []}),
            }
        )

        group = collect_action_history(
            REPOSITORY,
            main_branch="main",
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            days=365,
            now=now,
        )

        self.assertEqual(3, len(transport.requests))
        self.assertEqual(1, len(group["data"]["workflow_runs"]))
        self.assertEqual(1, len(group["data"]["run_attempts"]))
        self.assertTrue(group["complete"])

    def test_observation_bundle_collects_actions_once_and_derives_w90(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        repository_url = api(f"/repos/{REPOSITORY}")
        branch_url = api(f"/repos/{REPOSITORY}/branches/main")

        def empty_response(request: object, timeout: int) -> FixtureResponse:
            url = request.full_url  # type: ignore[attr-defined]
            if "/check-runs?" in url:
                return FixtureResponse({"total_count": 0, "check_runs": []})
            if "/actions/runs?" in url:
                return FixtureResponse(
                    {
                        "total_count": 2,
                        "workflow_runs": [
                            {
                                "id": 1,
                                "run_attempt": 1,
                                "head_sha": MAIN_SHA,
                                "created_at": "2026-08-01T12:00:00Z",
                            },
                            {
                                "id": 2,
                                "run_attempt": 1,
                                "head_sha": MAIN_SHA,
                                "created_at": "2026-01-01T12:00:00Z",
                            },
                        ],
                    }
                )
            if "/actions/runs/" in url and "/jobs?" in url:
                return FixtureResponse({"total_count": 0, "jobs": []})
            if "/actions/runs/" in url:
                return FixtureResponse(
                    {
                        "id": 1,
                        "run_attempt": 1,
                        "head_sha": MAIN_SHA,
                        "conclusion": "success",
                    }
                )
            if "/environments?" in url:
                return FixtureResponse({"total_count": 0, "environments": []})
            return FixtureResponse([])

        transport = FixtureTransport(
            {
                repository_url: FixtureResponse(
                    {"full_name": REPOSITORY, "default_branch": "main"}
                ),
                branch_url: FixtureResponse(
                    {"name": "main", "commit": {"sha": MAIN_SHA}}
                ),
            },
            default=empty_response,
        )
        bundle = collect_github_observations(
            REPOSITORY,
            main_branch="main",
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            now=now,
        )

        action_requests = [
            request for request in transport.requests if "/actions/runs?" in request.full_url  # type: ignore[attr-defined]
        ]
        self.assertEqual(1, len(action_requests))
        w365 = bundle["observations"]["actions_w365"]
        w90 = bundle["observations"]["actions_w90"]
        self.assertEqual(365, w365["data"]["window"]["days"])
        self.assertEqual(90, w90["data"]["window"]["days"])
        self.assertEqual([1, 2], [run["id"] for run in w365["data"]["workflow_runs"]])
        self.assertEqual([1], [run["id"] for run in w90["data"]["workflow_runs"]])
        self.assertEqual([1], [item["run_id"] for item in w90["data"]["run_attempts"]])
        self.assertEqual(w365["data"]["population_contract"], w90["data"]["population_contract"])
        self.assertEqual("E-GH-ACTIONS-W365", w90["request"]["derived_from"])

    def test_complete_rulesets_make_classic_protection_403_an_optional_limitation(self) -> None:
        rulesets = api(f"/repos/{REPOSITORY}/rulesets?includes_parents=true&per_page=100")
        effective = api(f"/repos/{REPOSITORY}/rules/branches/main?per_page=100")
        protection = api(f"/repos/{REPOSITORY}/branches/main/protection")
        detail = api(f"/repos/{REPOSITORY}/rulesets/9")
        group = collect_rules(
            REPOSITORY,
            main_branch="main",
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(
                api_url=API,
                transport=FixtureTransport(
                    {
                        rulesets: FixtureResponse([{"id": 9, "name": "Main health"}]),
                        effective: FixtureResponse([{"type": "pull_request"}]),
                        protection: http_error(protection, 403),
                        detail: FixtureResponse(
                            {"id": 9, "enforcement": "active", "rules": [{"type": "pull_request"}]}
                        ),
                    }
                ),
            ),
        )

        self.assertTrue(group["complete"])
        self.assertEqual([], group["gaps"])
        self.assertEqual("classic_branch_protection_unavailable", group["limitations"][0]["kind"])
        protection_request = next(
            item for item in group["request"]["endpoints"] if item["label"] == "branch_protection"
        )
        self.assertFalse(protection_request["complete"])

    def test_change_history_preserves_merge_parents_without_claiming_side_commit_acceptance(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        start = now - timedelta(days=365)
        query = urlencode(
            {
                "sha": "main",
                "since": start.isoformat().replace("+00:00", "Z"),
                "until": now.isoformat().replace("+00:00", "Z"),
                "per_page": 100,
            }
        )
        merge_sha = "a" * 40
        main_parent_sha = "b" * 40
        side_sha = "c" * 40
        side_parent_sha = "d" * 40
        merge = self._commit_fixture(
            merge_sha,
            committed_at="2026-08-01T12:00:00Z",
            parents=[main_parent_sha, side_sha],
        )
        side = self._commit_fixture(
            side_sha,
            committed_at="2026-07-31T12:00:00Z",
            parents=[side_parent_sha],
        )
        history_url = api(f"/repos/{REPOSITORY}/commits?{query}")
        most_recent_url = api(f"/repos/{REPOSITORY}/commits/main")
        merge_pulls_url = api(f"/repos/{REPOSITORY}/commits/{merge_sha}/pulls?per_page=100")
        side_pulls_url = api(f"/repos/{REPOSITORY}/commits/{side_sha}/pulls?per_page=100")
        reviews_url = api(f"/repos/{REPOSITORY}/pulls/7/reviews?per_page=100")
        pull = {
            "number": 7,
            "merge_commit_sha": merge_sha,
            "merged_at": "2026-08-01T12:00:00Z",
            "base": {"ref": "main"},
        }
        group = collect_change_history(
            REPOSITORY,
            main_branch="main",
            subject_sha=merge_sha,
            unit="documentation-suite",
            client=GitHubRESTClient(
                api_url=API,
                transport=FixtureTransport(
                    {
                        history_url: FixtureResponse([merge, side]),
                        most_recent_url: FixtureResponse(merge),
                        merge_pulls_url: FixtureResponse([pull]),
                        side_pulls_url: FixtureResponse([pull]),
                        reviews_url: FixtureResponse([]),
                    }
                ),
            ),
            now=now,
        )

        self.assertNotIn("commits", group["data"])
        self.assertEqual([], group["data"]["accepted_main_revisions"])
        self.assertFalse(group["data"]["accepted_main_revisions_complete"])
        reachable = {item["sha"]: item for item in group["data"]["reachable_commits"]}
        self.assertEqual([main_parent_sha, side_sha], reachable[merge_sha]["parent_shas"])
        self.assertEqual(main_parent_sha, reachable[merge_sha]["first_parent_sha"])
        self.assertEqual("commit_object_parent_order", reachable[merge_sha]["first_parent_source"])
        self.assertIsNone(reachable[merge_sha]["accepted_main_revision"])
        self.assertIsNone(reachable[side_sha]["accepted_main_revision"])
        self.assertTrue(all(link["accepted_main_revision"] is None for link in group["data"]["commit_pr_links"]))
        self.assertEqual([], group["data"]["historical_bypass_events"])
        self.assertFalse(group["data"]["historical_bypass_complete"])
        self.assertIn(
            "accepted_main_revision_population_unavailable",
            {gap["kind"] for gap in group["gaps"]},
        )
        self.assertFalse(group["complete"])

    def test_change_history_retains_complete_older_than_w365_basis_for_quiet_main(self) -> None:
        now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        start = now - timedelta(days=365)
        query = urlencode(
            {
                "sha": "main",
                "since": start.isoformat().replace("+00:00", "Z"),
                "until": now.isoformat().replace("+00:00", "Z"),
                "per_page": 100,
            }
        )
        old_sha = "e" * 40
        old_parent_sha = "f" * 40
        old_head = self._commit_fixture(
            old_sha,
            committed_at="2024-01-01T12:00:00Z",
            parents=[old_parent_sha],
        )
        history_url = api(f"/repos/{REPOSITORY}/commits?{query}")
        most_recent_url = api(f"/repos/{REPOSITORY}/commits/main")
        pulls_url = api(f"/repos/{REPOSITORY}/commits/{old_sha}/pulls?per_page=100")
        group = collect_change_history(
            REPOSITORY,
            main_branch="main",
            subject_sha=old_sha,
            unit="documentation-suite",
            client=GitHubRESTClient(
                api_url=API,
                transport=FixtureTransport(
                    {
                        history_url: FixtureResponse([]),
                        most_recent_url: FixtureResponse(old_head),
                        pulls_url: FixtureResponse([]),
                    }
                ),
            ),
            now=now,
        )

        basis = group["data"]["most_recent_commit_basis"]
        self.assertTrue(basis["complete"])
        self.assertEqual(365, basis["window_days"])
        self.assertTrue(basis["window_population_complete"])
        self.assertTrue(basis["window_commit_identity_complete"])
        self.assertTrue(basis["most_recent_commit_complete"])
        self.assertTrue(basis["no_reachable_commits_in_window"])
        self.assertTrue(basis["older_than_window"])
        self.assertTrue(basis["no_reachable_commits_w365"])
        self.assertTrue(basis["older_than_w365"])
        self.assertEqual(old_sha, group["data"]["most_recent_commit"]["sha"])
        self.assertEqual("most_recent", group["data"]["commit_pr_links"][0]["reachability_scope"])
        self.assertEqual([], group["data"]["reachable_commits"])

    def test_annotated_tag_is_peeled_and_release_assets_are_explicitly_collected(self) -> None:
        tag_object_sha = "a" * 40
        commit_sha = "b" * 40
        routes = {
            api(f"/repos/{REPOSITORY}/branches?per_page=100"): FixtureResponse(
                [{"name": "main", "commit": {"sha": MAIN_SHA}}]
            ),
            api(f"/repos/{REPOSITORY}/tags?per_page=100"): FixtureResponse(
                [{"name": "v1.0.0", "commit": {"sha": commit_sha}}]
            ),
            api(f"/repos/{REPOSITORY}/releases?per_page=100"): FixtureResponse(
                [{"id": 7, "tag_name": "v1.0.0", "immutable": True, "assets": []}]
            ),
            api(f"/repos/{REPOSITORY}/git/ref/tags/v1.0.0"): FixtureResponse(
                {"ref": "refs/tags/v1.0.0", "object": {"type": "tag", "sha": tag_object_sha}}
            ),
            api(f"/repos/{REPOSITORY}/git/tags/{tag_object_sha}"): FixtureResponse(
                {
                    "sha": tag_object_sha,
                    "tag": "v1.0.0",
                    "message": "release",
                    "object": {"type": "commit", "sha": commit_sha},
                }
            ),
            api(f"/repos/{REPOSITORY}/releases/7/assets?per_page=100"): FixtureResponse(
                [{"id": 70, "name": "standard.zip", "digest": f"sha256:{'c' * 64}"}]
            ),
        }
        group = collect_refs_and_releases(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=FixtureTransport(routes)),
        )

        self.assertTrue(group["complete"])
        tag = group["data"]["tags"][0]
        self.assertTrue(tag["tag_target"]["annotated"])
        self.assertEqual(commit_sha, tag["peeled_sha"])
        self.assertEqual("release", tag["annotated_tag"]["message"])
        release = group["data"]["releases"][0]
        self.assertTrue(release["immutable"])
        self.assertEqual("standard.zip", release["assets"][0]["name"])
        self.assertEqual(commit_sha, release["tag_target"]["peeled_sha"])

    def _release_asset_routes(self, content: bytes, digest: str) -> dict[str, FixtureResponse]:
        return {
            api(f"/repos/{REPOSITORY}/branches?per_page=100"): FixtureResponse([]),
            api(f"/repos/{REPOSITORY}/tags?per_page=100"): FixtureResponse([]),
            api(f"/repos/{REPOSITORY}/releases?per_page=100"): FixtureResponse(
                [{"id": 7, "tag_name": "v1.0.0", "immutable": True}]
            ),
            api(f"/repos/{REPOSITORY}/releases/7/assets?per_page=100"): FixtureResponse(
                [
                    {
                        "id": 70,
                        "name": "standard.zip",
                        "size": len(content),
                        "digest": digest,
                    }
                ]
            ),
            api(f"/repos/{REPOSITORY}/releases/assets/70"): FixtureResponse(
                content,
                headers={"Content-Length": str(len(content))},
                url=api(f"/repos/{REPOSITORY}/releases/assets/70"),
            ),
        }

    def test_allowlisted_release_asset_bytes_are_downloaded_and_digest_verified(self) -> None:
        content = b"controlled artifact content"
        digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        transport = FixtureTransport(self._release_asset_routes(content, digest))

        group = collect_refs_and_releases(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            release_asset_names=["standard.zip"],
        )

        self.assertTrue(group["complete"])
        self.assertEqual({"standard.zip": content}, group["data"]["asset_contents"])
        content_request = transport.requests[-1]
        self.assertEqual("application/octet-stream", content_request.get_header("Accept"))  # type: ignore[attr-defined]
        endpoints = {item["endpoint"] for item in group["request"]["endpoints"]}
        self.assertIn(f"/repos/{REPOSITORY}/releases/assets/70", endpoints)

    def test_release_asset_digest_mismatch_is_unknown_and_bytes_are_discarded(self) -> None:
        content = b"tampered artifact content"
        routes = self._release_asset_routes(content, f"sha256:{'0' * 64}")

        group = collect_refs_and_releases(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=FixtureTransport(routes)),
            release_asset_names=["standard.zip"],
        )

        self.assertFalse(group["complete"])
        self.assertEqual({}, group["data"]["asset_contents"])
        self.assertIn("asset_digest_mismatch", {gap["kind"] for gap in group["gaps"]})

    def test_unallowlisted_release_asset_is_never_downloaded(self) -> None:
        content = b"content that must not be fetched"
        digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        routes = self._release_asset_routes(content, digest)
        routes.pop(api(f"/repos/{REPOSITORY}/releases/assets/70"))
        transport = FixtureTransport(routes)

        group = collect_refs_and_releases(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            release_asset_names=[],
        )

        self.assertTrue(group["complete"])
        self.assertEqual({}, group["data"]["asset_contents"])
        self.assertFalse(any("/releases/assets/70" in request.full_url for request in transport.requests))  # type: ignore[attr-defined]

    def test_duplicate_allowlisted_asset_names_fail_closed_without_download(self) -> None:
        content = b"ambiguous"
        digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        routes = self._release_asset_routes(content, digest)
        routes[api(f"/repos/{REPOSITORY}/releases?per_page=100")] = FixtureResponse(
            [{"id": 7, "tag_name": "v1"}, {"id": 8, "tag_name": "v2"}]
        )
        routes[api(f"/repos/{REPOSITORY}/releases/8/assets?per_page=100")] = FixtureResponse(
            [{"id": 80, "name": "standard.zip", "size": len(content), "digest": digest}]
        )
        routes.pop(api(f"/repos/{REPOSITORY}/releases/assets/70"))
        transport = FixtureTransport(routes)

        group = collect_refs_and_releases(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            release_asset_names=["standard.zip"],
        )

        self.assertEqual({}, group["data"]["asset_contents"])
        self.assertIn("duplicate_release_asset_name", {gap["kind"] for gap in group["gaps"]})
        self.assertFalse(any("/releases/assets/" in request.full_url for request in transport.requests))  # type: ignore[attr-defined]

    def test_security_permission_and_network_gaps_remain_unknown(self) -> None:
        scan_history = api(f"/repos/{REPOSITORY}/secret-scanning/scan-history")
        secret_alerts = api(f"/repos/{REPOSITORY}/secret-scanning/alerts?per_page=100")
        dependabot = api(f"/repos/{REPOSITORY}/dependabot/alerts?per_page=100")
        code_scanning = api(f"/repos/{REPOSITORY}/code-scanning/alerts?per_page=100")
        sbom = api(f"/repos/{REPOSITORY}/dependency-graph/sbom")
        transport = FixtureTransport(
            {
                scan_history: http_error(scan_history, 403),
                secret_alerts: http_error(secret_alerts, 404),
                dependabot: URLError("fixture offline"),
                code_scanning: FixtureResponse([]),
                sbom: FixtureResponse({"sbom": {"packages": []}}),
            }
        )
        group = collect_security(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
        )

        self.assertEqual("unknown", group["state"])
        self.assertEqual("partial", group["completeness"])
        self.assertFalse(group["population_complete"])
        kinds = {gap["kind"] for gap in group["gaps"]}
        self.assertIn("permission_or_api_gap", kinds)
        self.assertIn("network_error", kinds)
        self.assertEqual([], group["data"]["code_scanning_alerts"])

    def test_attestation_403_is_unknown_not_no_attestation(self) -> None:
        digest = f"sha256:{'d' * 64}"
        endpoint = api(f"/repos/{REPOSITORY}/attestations/{digest}?per_page=100")
        group = collect_attestations(
            REPOSITORY,
            releases=[{"id": 8, "assets": [{"id": 80, "name": "bundle.zip", "digest": digest}]}],
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(
                api_url=API,
                transport=FixtureTransport({endpoint: http_error(endpoint, 403)}),
            ),
        )

        self.assertEqual("unknown", group["state"])
        self.assertEqual("permission_or_api_gap", group["gaps"][0]["kind"])
        self.assertEqual([], group["data"]["assets"][0]["attestations"])


class DeliveryCollectorTests(unittest.TestCase):
    def _base_routes(self) -> dict[str, object]:
        return {
            api(f"/repos/{REPOSITORY}/deployments?per_page=100"): FixtureResponse([]),
            api(f"/repos/{REPOSITORY}/environments?per_page=100"): FixtureResponse(
                {"total_count": 0, "environments": []}
            ),
        }

    @staticmethod
    def _site() -> dict[str, object]:
        return {
            "status": "built",
            "html_url": "https://octo.example/health/",
            "cname": "octo.example",
            "source": {"branch": "main", "path": "/docs"},
        }

    @staticmethod
    def _build(commit: str, suffix: str, created_at: str) -> dict[str, object]:
        return {
            "url": f"https://api.github.com/repos/{REPOSITORY}/pages/builds/{suffix}",
            "status": "built",
            "commit": commit,
            "created_at": created_at,
            "updated_at": created_at,
        }

    def _collect(self, routes: dict[str, object]) -> tuple[dict[str, object], FixtureTransport]:
        transport = FixtureTransport(routes)
        group = collect_delivery(
            REPOSITORY,
            subject_sha=MAIN_SHA,
            unit="documentation-suite",
            client=GitHubRESTClient(api_url=API, transport=transport),
            observed_at="2026-08-09T21:00:00Z",
        )
        return group, transport

    def test_pages_build_history_is_paginated_and_stamped_to_exact_subject(self) -> None:
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        builds_page_2 = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100&page=2")
        latest = api(f"/repos/{REPOSITORY}/pages/builds/latest")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        current = self._build(MAIN_SHA, "current", "2026-08-09T20:00:00Z")
        previous = self._build("2" * 40, "previous", "2026-08-08T20:00:00Z")
        routes = self._base_routes()
        routes.update(
            {
                pages: FixtureResponse(self._site()),
                builds: FixtureResponse(
                    [current], headers={"Link": f'<{builds_page_2}>; rel="next"'}
                ),
                builds_page_2: FixtureResponse([previous]),
                latest: FixtureResponse(current),
                subject_status: FixtureResponse({"status": "succeed"}),
            }
        )

        group, transport = self._collect(routes)

        self.assertTrue(group["complete"])
        self.assertEqual("observed", group["state"])
        self.assertEqual(2, len(group["data"]["pages"]["builds"]))
        self.assertEqual(MAIN_SHA, group["data"]["pages"]["current_build_source_sha"])
        self.assertTrue(group["data"]["pages"]["current_build_matches_subject"])
        builds_check = next(
            item for item in group["request"]["endpoints"] if item["label"] == "pages_builds"
        )
        self.assertEqual(2, builds_check["page_count"])
        pages_item = next(
            item
            for item in group["data"]["inventory"]["items"]
            if item["adapter_id"] == "github-pages"
        )
        self.assertEqual(MAIN_SHA, pages_item["source_sha"])
        self.assertTrue(pages_item["matches_subject"])
        self.assertIsNone(pages_item["unit_selector"])
        self.assertEqual("main", pages_item["selectors"]["source_branch"])
        self.assertFalse(any("/packages" in request.full_url for request in transport.requests))
        package_adapter = next(
            adapter
            for adapter in group["data"]["inventory"]["adapters"]
            if adapter["adapter_id"] == "github-packages"
        )
        self.assertEqual("unsupported", package_adapter["state"])
        self.assertFalse(package_adapter["population_complete"])

    def test_pages_permission_failures_remain_explicit_unknown(self) -> None:
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        routes = self._base_routes()
        routes.update(
            {
                pages: http_error(pages, 403),
                builds: http_error(builds, 403),
                subject_status: http_error(subject_status, 403),
            }
        )

        group, _ = self._collect(routes)

        self.assertEqual("unknown", group["state"])
        self.assertEqual("partial", group["completeness"])
        self.assertFalse(group["data"]["pages"]["population_complete"])
        page_gaps = [gap for gap in group["gaps"] if gap["source"].startswith("pages_")]
        self.assertEqual(3, len(page_gaps))
        self.assertEqual({"permission_or_api_gap"}, {gap["kind"] for gap in page_gaps})

    def test_empty_pages_build_population_is_complete_without_latest_request(self) -> None:
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        routes = self._base_routes()
        routes.update(
            {
                pages: FixtureResponse(self._site()),
                builds: FixtureResponse([]),
                subject_status: FixtureResponse({"status": "deployment_cancelled"}),
            }
        )

        group, transport = self._collect(routes)

        self.assertTrue(group["complete"])
        self.assertEqual([], group["data"]["pages"]["builds"])
        self.assertIsNone(group["data"]["pages"]["current_build"])
        self.assertFalse(any(request.full_url.endswith("/pages/builds/latest") for request in transport.requests))

    def test_current_pages_build_subject_mismatch_is_observed_not_guessed(self) -> None:
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        latest = api(f"/repos/{REPOSITORY}/pages/builds/latest")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        current = self._build("2" * 40, "current", "2026-08-09T20:00:00Z")
        routes = self._base_routes()
        routes.update(
            {
                pages: FixtureResponse(self._site()),
                builds: FixtureResponse([current]),
                latest: FixtureResponse(current),
                subject_status: FixtureResponse({"status": "succeed"}),
            }
        )

        group, _ = self._collect(routes)

        self.assertTrue(group["complete"])
        self.assertFalse(group["data"]["pages"]["current_build_matches_subject"])
        pages_item = next(
            item
            for item in group["data"]["inventory"]["items"]
            if item["adapter_id"] == "github-pages"
        )
        self.assertFalse(pages_item["matches_subject"])
        self.assertEqual(MAIN_SHA, pages_item["observed_subject_sha"])

    def test_latest_build_must_be_present_once_in_complete_history(self) -> None:
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        latest = api(f"/repos/{REPOSITORY}/pages/builds/latest")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        listed = self._build(MAIN_SHA, "listed", "2026-08-09T20:00:00Z")
        current = self._build(MAIN_SHA, "current", "2026-08-09T20:01:00Z")
        routes = self._base_routes()
        routes.update(
            {
                pages: FixtureResponse(self._site()),
                builds: FixtureResponse([listed]),
                latest: FixtureResponse(current),
                subject_status: FixtureResponse({"status": "succeed"}),
            }
        )

        group, _ = self._collect(routes)

        self.assertEqual("unknown", group["state"])
        self.assertIn("pages_latest_history_mismatch", {gap["kind"] for gap in group["gaps"]})

    def test_existing_deployment_evidence_is_preserved_and_added_to_inventory(self) -> None:
        deployment_sha = "3" * 40
        deployments = api(f"/repos/{REPOSITORY}/deployments?per_page=100")
        statuses = api(f"/repos/{REPOSITORY}/deployments/7/statuses?per_page=100")
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        routes = self._base_routes()
        routes.update(
            {
                deployments: FixtureResponse(
                    [
                        {
                            "id": 7,
                            "sha": deployment_sha,
                            "environment": "production",
                            "ref": "main",
                            "task": "deploy",
                        }
                    ]
                ),
                statuses: FixtureResponse([{"id": 70, "state": "success"}]),
                pages: FixtureResponse(self._site()),
                builds: FixtureResponse([]),
                subject_status: FixtureResponse({"status": "succeed"}),
            }
        )

        group, _ = self._collect(routes)

        self.assertTrue(group["complete"])
        self.assertEqual([{"id": 70, "state": "success"}], group["data"]["deployments"][0]["statuses"])
        deployment_item = next(
            item
            for item in group["data"]["inventory"]["items"]
            if item["adapter_id"] == "github-deployments"
        )
        self.assertEqual(deployment_sha, deployment_item["source_sha"])
        self.assertEqual("production", deployment_item["selectors"]["environment"])
        self.assertIsNone(deployment_item["unit_selector"])

    def test_pages_404_does_not_erase_complete_deployment_adapter(self) -> None:
        deployment_sha = "3" * 40
        deployments = api(f"/repos/{REPOSITORY}/deployments?per_page=100")
        statuses = api(f"/repos/{REPOSITORY}/deployments/7/statuses?per_page=100")
        pages = api(f"/repos/{REPOSITORY}/pages")
        builds = api(f"/repos/{REPOSITORY}/pages/builds?per_page=100")
        subject_status = api(f"/repos/{REPOSITORY}/pages/deployments/{MAIN_SHA}")
        routes = self._base_routes()
        routes.update(
            {
                deployments: FixtureResponse(
                    [{"id": 7, "sha": deployment_sha, "environment": "production"}]
                ),
                statuses: FixtureResponse([{"id": 70, "state": "success"}]),
                pages: http_error(pages, 404),
                builds: http_error(builds, 404),
                subject_status: http_error(subject_status, 404),
            }
        )

        group, _ = self._collect(routes)

        self.assertEqual("unknown", group["state"])
        self.assertEqual("unknown", group["data"]["pages"]["state"])
        deployment_adapter = next(
            adapter
            for adapter in group["data"]["inventory"]["adapters"]
            if adapter["adapter_id"] == "github-deployments"
        )
        self.assertEqual("observed", deployment_adapter["state"])
        self.assertTrue(deployment_adapter["population_complete"])
        self.assertEqual(1, deployment_adapter["item_count"])
        self.assertEqual(
            ["github-deployments:7"],
            [
                item["inventory_id"]
                for item in group["data"]["inventory"]["items"]
                if item["adapter_id"] == "github-deployments"
            ],
        )


class WorkflowDependencyTests(unittest.TestCase):
    def test_workflow_uses_dependencies_classify_immutable_mutable_local_and_dynamic(self) -> None:
        pinned = "e" * 40
        docker_digest = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "health.yml"
            local_action = root / ".github" / "actions" / "local" / "action.yml"
            workflow.parent.mkdir(parents=True)
            local_action.parent.mkdir(parents=True)
            workflow.write_text(
                "\n".join(
                    [
                        "name: fixture",
                        "jobs:",
                        "  health:",
                        "    steps:",
                        f"      - uses: actions/checkout@{pinned}",
                        "      - uses: 'actions/setup-python@v5' # mutable tag",
                        f"      - uses: docker://ghcr.io/octo/check@sha256:{docker_digest}",
                        "      - uses: docker://alpine:3.20",
                        "      - uses: ./.github/actions/local",
                        f"      - uses: octo/shared/.github/workflows/scan.yml@{pinned}",
                        "      - uses: ${{ matrix.health_action }}",
                    ]
                ),
                encoding="utf-8",
            )
            local_action.write_text(
                "\n".join(
                    [
                        "name: local",
                        "runs:",
                        "  using: composite",
                        "  steps:",
                        "    - uses: octo/nested@v2",
                    ]
                ),
                encoding="utf-8",
            )
            subject_sha = git_commit_fixture(root)

            result = collect_workflow_dependencies(
                root,
                subject_sha=subject_sha,
                unit="documentation-suite",
                observed_at="2026-08-09T12:00:00Z",
            )

        by_raw = {item["raw"]: item for item in result["observations"]}
        self.assertTrue(by_raw[f"actions/checkout@{pinned}"]["immutable"])
        self.assertEqual("commit_sha", by_raw[f"actions/checkout@{pinned}"]["ref_kind"])
        self.assertTrue(by_raw["actions/setup-python@v5"]["mutable"])
        self.assertTrue(by_raw[f"docker://ghcr.io/octo/check@sha256:{docker_digest}"]["immutable"])
        self.assertTrue(by_raw["docker://alpine:3.20"]["mutable"])
        self.assertEqual(".github/actions/local/action.yml", by_raw["./.github/actions/local"]["local_target"])
        self.assertEqual("reusable-workflow", by_raw[f"octo/shared/.github/workflows/scan.yml@{pinned}"]["kind"])
        self.assertEqual("dynamic", by_raw["${{ matrix.health_action }}"]["kind"])
        self.assertEqual("github-action", by_raw["octo/nested@v2"]["kind"])
        self.assertEqual("unknown", result["state"])
        self.assertEqual("partial", result["completeness"])
        self.assertEqual(
            [".github/actions/local/action.yml", ".github/workflows/health.yml"],
            result["files_scanned"],
        )
        for observation in result["observations"]:
            self.assertIn("E-WORKFLOW-DEP-", observation["evidence_id"])
            self.assertEqual("2026-08-09T12:00:00Z", observation["observed_at"])
            self.assertEqual(subject_sha, observation["subject_sha"])

    def test_missing_local_action_is_an_explicit_completeness_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "health.yaml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("steps:\n  - uses: ./missing-action\n", encoding="utf-8")
            subject_sha = git_commit_fixture(root)
            result = collect_workflow_dependencies(root, subject_sha=subject_sha)

        self.assertFalse(result["population_complete"])
        self.assertEqual("unknown", result["observations"][0]["completeness"])
        self.assertEqual("local_dependency_gap", result["gaps"][0]["kind"])


if __name__ == "__main__":
    unittest.main()

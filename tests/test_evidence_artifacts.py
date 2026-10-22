"""Offline adversarial tests for bounded Actions evidence collection."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import tempfile
import unittest
import warnings
import zipfile
from urllib.parse import parse_qs, urlsplit

from automation.repository_health.evidence_artifacts import (
    EVIDENCE_ARTIFACT_NAME_PREFIX,
    EvidenceArtifactError,
    collect_evidence_artifacts,
    download_actions_artifact,
    evidence_artifact_name,
)
from automation.repository_health.delivery_collectors import DEPLOYMENT_PAYLOAD_SCHEMA
from automation.repository_health.evidence_producer import (
    create_evidence_statement,
    write_evidence_package,
)
from automation.repository_health.github_client import GitHubRESTClient


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "automation" / "repository_health" / "evidence_artifacts.py"
NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
REPOSITORY = "TedTschopp/github-repository-health"
UNIT_ID = "repository-health-standard"
SUBJECT_SHA = "a" * 40
WORKFLOW_SHA = SUBJECT_SHA
SOURCE_DIGEST = "c" * 64
ARTIFACT_DIGEST = "d" * 64
RUN_ID = 123456789
RUN_ATTEMPT = 2
WORKFLOW_REF = (
    f"{REPOSITORY}/.github/workflows/repository-validation.yml@refs/heads/main"
)


def _digest(name: str, value: str) -> dict[str, str]:
    return {"name": name, "algorithm": "sha256", "value": value}


def _statement(
    *,
    kind: str = "validation",
    result: str = "success",
    source_ids: list[str] | None = None,
    subject_sha: str = SUBJECT_SHA,
    subject_ref: str = "refs/heads/main",
    unit_id: str = UNIT_ID,
    workflow_sha: str = WORKFLOW_SHA,
) -> dict[str, object]:
    if source_ids is None:
        source_ids = [f"github-actions-run:{RUN_ID}:{RUN_ATTEMPT}"]
    artifact_digests = (
        [_digest("package", ARTIFACT_DIGEST)]
        if kind in {"release", "deployment"}
        else []
    )
    return create_evidence_statement(
        repository=REPOSITORY,
        unit_id=unit_id,
        subject_ref=subject_ref,
        subject_sha=subject_sha,
        subject_digests=[_digest("source-input", SOURCE_DIGEST)],
        workflow_ref=WORKFLOW_REF,
        workflow_sha=workflow_sha,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        observed_at="2026-08-09T12:00:00Z",
        kind=kind,
        result=result,
        categories=[kind],
        artifact_digests=artifact_digests,
        source_evidence_ids=source_ids,
        now=NOW,
    )


def _package_files(statement: dict[str, object]) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        evidence = root / "evidence-statement.json"
        manifest = root / "SHA256SUMS"
        write_evidence_package(
            statement,
            output_path=evidence,
            manifest_path=manifest,
            now=NOW,
        )
        return {
            "evidence-statement.json": evidence.read_bytes(),
            "SHA256SUMS": manifest.read_bytes(),
        }


def _zip_files(
    files: list[tuple[str, bytes]],
    *,
    symlinks: set[str] | None = None,
) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in files:
                if symlinks and name in symlinks:
                    entry = zipfile.ZipInfo(name)
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(entry, content)
                else:
                    archive.writestr(name, content)
    return output.getvalue()


def _package_zip(statement: dict[str, object]) -> bytes:
    return _zip_files(list(_package_files(statement).items()))


def _run(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": SUBJECT_SHA,
        "path": ".github/workflows/repository-validation.yml@main",
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
    }
    value.update(overrides)
    return value


def _artifact(
    artifact_id: int,
    content: bytes,
    *,
    name: str = evidence_artifact_name(UNIT_ID),
    expired: bool = False,
    workflow_run_id: int = RUN_ID,
    head_sha: str = SUBJECT_SHA,
    digest: str | None = None,
    size: int | None = None,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "size_in_bytes": len(content) if size is None else size,
        "expired": expired,
        "digest": digest,
        "created_at": "2026-08-09T12:01:00Z",
        "workflow_run": {"id": workflow_run_id, "head_sha": head_sha},
    }


class FakeClient:
    def __init__(
        self,
        *,
        artifacts: list[object],
        binaries: dict[int, bytes | dict[str, object]] | None = None,
        records: dict[str, dict[str, object]] | None = None,
        population_complete: bool = True,
        listing_gap: str | None = None,
        artifacts_by_run: dict[int, list[object]] | None = None,
        respect_name_filter: bool = True,
    ) -> None:
        self.artifacts = artifacts
        self.binaries = binaries or {}
        self.records = records or {}
        self.population_complete = population_complete
        self.listing_gap = listing_gap
        self.artifacts_by_run = artifacts_by_run
        self.respect_name_filter = respect_name_filter
        self.paginate_calls: list[tuple[str, str | None, dict[str, object]]] = []
        self.binary_calls: list[tuple[str, int]] = []
        self.get_calls: list[str] = []

    def paginate(
        self,
        endpoint: str,
        collection_key: str | None = None,
        **options: object,
    ) -> dict[str, object]:
        self.paginate_calls.append((endpoint, collection_key, options))
        run_id_match = re.search(r"/actions/runs/([1-9][0-9]*)/artifacts", endpoint)
        run_id = int(run_id_match.group(1)) if run_id_match else RUN_ID
        if self.artifacts_by_run is not None:
            all_items = list(self.artifacts_by_run.get(run_id, []))
        elif run_id == RUN_ID:
            all_items = list(self.artifacts)
        else:
            all_items = []
        requested_names = parse_qs(urlsplit(endpoint).query).get("name", [])
        if self.respect_name_filter and len(requested_names) == 1:
            requested_name = requested_names[0]
            all_items = [
                item
                for item in all_items
                if isinstance(item, dict) and item.get("name") == requested_name
            ]
        requested_cap = options.get("max_items")
        over_cap = (
            isinstance(requested_cap, int)
            and not isinstance(requested_cap, bool)
            and len(all_items) > requested_cap
        )
        items = all_items[:requested_cap] if over_cap else all_items
        complete = self.population_complete and not over_cap
        return {
            "state": "observed" if complete else "unknown",
            "items": items,
            "population_complete": complete,
            "complete": complete,
            "page_count": 1,
            "item_count": len(items),
            "reported_total_count": len(all_items),
            "gap": self.listing_gap or ("item_cap" if over_cap else None),
            "error": "partial fixture" if not complete else None,
            "observed_at": "2026-08-09T12:05:00Z",
        }

    def get_actions_artifact_binary(
        self,
        endpoint: str,
        *,
        max_bytes: int,
    ) -> dict[str, object]:
        self.binary_calls.append((endpoint, max_bytes))
        artifact_id = int(endpoint.rsplit("/", 2)[1])
        fixture = self.binaries.get(artifact_id)
        if isinstance(fixture, dict):
            return fixture
        if not isinstance(fixture, bytes):
            return {
                "ok": False,
                "state": "unknown",
                "data": None,
                "error": "missing binary fixture",
                "error_kind": "network_error",
                "status": None,
            }
        if len(fixture) > max_bytes:
            return {
                "ok": False,
                "state": "unknown",
                "data": None,
                "error": "size mismatch",
                "error_kind": "size_mismatch",
                "status": 200,
            }
        return {
            "ok": True,
            "state": "observed",
            "data": fixture,
            "error": None,
            "error_kind": None,
            "status": 200,
        }

    def get(self, endpoint: str) -> dict[str, object]:
        self.get_calls.append(endpoint)
        return self.records.get(
            endpoint,
            {
                "ok": False,
                "state": "unknown",
                "data": None,
                "error": "missing record fixture",
                "error_kind": "permission_or_api_gap",
                "status": 404,
            },
        )


def _policy(*unit_ids: str) -> dict[str, object]:
    return {
        unit_id: {
            kind: {
                "categories": [kind],
                "workflow_refs": [WORKFLOW_REF],
            }
            for kind in ("deployment", "release", "security", "validation")
        }
        for unit_id in unit_ids
    }


def _collect(
    client: FakeClient,
    *,
    eligible_runs: dict[int, list[str]] | None = None,
    category_policy: dict[str, object] | None = None,
    **options: object,
) -> dict[str, object]:
    return collect_evidence_artifacts(
        REPOSITORY,
        client=client,
        eligible_runs=eligible_runs or {RUN_ID: [UNIT_ID]},
        category_policy=category_policy or _policy(UNIT_ID),
        now=NOW,
        **options,
    )


def _observed(data: object) -> dict[str, object]:
    return {
        "ok": True,
        "state": "observed",
        "data": data,
        "error": None,
        "error_kind": None,
        "status": 200,
    }


class FixtureResponse:
    def __init__(
        self,
        *,
        url: str,
        status: int,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FixtureResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class FixtureTransport:
    def __init__(self, responses: list[FixtureResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object, *, timeout: int) -> FixtureResponse:
        del timeout
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


def _run_endpoint() -> str:
    return f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}"


def _client_for(
    statement: dict[str, object] | None = None,
    *,
    artifact_id: int = 10,
    run: dict[str, object] | None = None,
    records: dict[str, dict[str, object]] | None = None,
) -> tuple[FakeClient, bytes]:
    content = _package_zip(statement or _statement())
    all_records = {_run_endpoint(): _observed(run or _run())}
    all_records.update(records or {})
    client = FakeClient(
        artifacts=[_artifact(artifact_id, content)],
        binaries={artifact_id: content},
        records=all_records,
    )
    return client, content


class EvidenceArtifactDownloadTests(unittest.TestCase):
    def test_actions_blob_redirect_is_https_bounded_and_strips_authorization(self) -> None:
        api_url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/10/zip"
        blob_url = (
            "https://productionresultssa1.blob.core.windows.net/"
            "actions-results/evidence.zip?sig=redacted"
        )
        body = b"bounded-zip"
        transport = FixtureTransport(
            [
                FixtureResponse(
                    url=api_url,
                    status=302,
                    headers={"Location": blob_url},
                ),
                FixtureResponse(
                    url=blob_url,
                    status=200,
                    headers={"Content-Length": str(len(body))},
                    body=body,
                ),
            ]
        )
        client = GitHubRESTClient(token="test-token", transport=transport)
        result = download_actions_artifact(
            client,
            f"/repos/{REPOSITORY}/actions/artifacts/10/zip",
            max_bytes=64,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(body, result["data"])
        first_headers = {
            key.lower(): value for key, value in transport.requests[0].header_items()
        }
        second_headers = {
            key.lower(): value for key, value in transport.requests[1].header_items()
        }
        self.assertEqual("Bearer test-token", first_headers["authorization"])
        self.assertNotIn("authorization", second_headers)
        self.assertEqual(blob_url, transport.requests[1].full_url)

    def test_unsafe_actions_redirect_targets_are_rejected_before_request(self) -> None:
        api_url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/10/zip"
        targets = (
            "http://productionresultssa1.blob.core.windows.net/evidence.zip",
            "https://127.0.0.1/evidence.zip",
            "https://user:secret@productionresultssa1.blob.core.windows.net/evidence.zip",
            "https://evil.blob.core.windows.net/evidence.zip",
            "https://actions.githubusercontent.com/evidence.zip",
        )
        for target in targets:
            with self.subTest(target=target):
                transport = FixtureTransport(
                    [
                        FixtureResponse(
                            url=api_url,
                            status=302,
                            headers={"Location": target},
                        )
                    ]
                )
                client = GitHubRESTClient(token="test-token", transport=transport)
                result = download_actions_artifact(
                    client,
                    f"/repos/{REPOSITORY}/actions/artifacts/10/zip",
                    max_bytes=64,
                )
                self.assertFalse(result["ok"])
                self.assertEqual("unsafe_redirect", result["error_kind"])
                self.assertEqual(1, len(transport.requests))

    def test_actions_download_content_and_redirect_caps_fail_closed(self) -> None:
        api_url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/10/zip"
        blob_url = "https://results-receiver.actions.githubusercontent.com/evidence.zip"
        transport = FixtureTransport(
            [
                FixtureResponse(
                    url=api_url,
                    status=302,
                    headers={"Location": blob_url},
                ),
                FixtureResponse(
                    url=blob_url,
                    status=200,
                    headers={"Content-Length": "65"},
                    body=b"x" * 65,
                ),
            ]
        )
        client = GitHubRESTClient(transport=transport)
        result = download_actions_artifact(
            client,
            f"/repos/{REPOSITORY}/actions/artifacts/10/zip",
            max_bytes=64,
        )
        self.assertEqual("response_too_large", result["error_kind"])

        urls = [api_url, *[f"https://api.github.com/redirect/{index}" for index in range(1, 7)]]
        redirects = FixtureTransport(
            [
                FixtureResponse(
                    url=current,
                    status=302,
                    headers={"Location": following},
                )
                for current, following in zip(urls, urls[1:])
            ]
        )
        client = GitHubRESTClient(transport=redirects)
        result = download_actions_artifact(
            client,
            f"/repos/{REPOSITORY}/actions/artifacts/10/zip",
            max_bytes=64,
        )
        self.assertEqual("redirect_cap", result["error_kind"])
        self.assertEqual(6, len(redirects.requests))


class EvidenceArtifactCollectorTests(unittest.TestCase):
    def test_valid_artifact_is_bound_but_never_assigned_assurance_or_score(self) -> None:
        client, _ = _client_for()
        result = _collect(client)

        self.assertEqual("observed", result["state"])
        self.assertTrue(result["population_complete"])
        self.assertEqual(
            f"{EVIDENCE_ARTIFACT_NAME_PREFIX}<unit_id>",
            result["artifact_name_convention"],
        )
        self.assertFalse(result["assurance_assigned"])
        self.assertFalse(result["score_mapping_applied"])
        self.assertEqual("verified", result["statement_verifications"][0]["state"])
        self.assertTrue(
            result["statement_verifications"][0]["artifact_binding_complete"]
        )
        candidate = result["candidates"][0]
        self.assertEqual("observed", candidate["state"])
        self.assertTrue(candidate["package_valid"])
        self.assertTrue(candidate["identity_complete"])
        self.assertTrue(candidate["authoritative_workflow_valid"])
        self.assertTrue(candidate["source_records_complete"])
        self.assertTrue(candidate["result_source_valid"])
        self.assertTrue(candidate["category_policy_valid"])
        self.assertFalse(candidate["assurance_assigned"])
        self.assertFalse(candidate["score_mapping_applied"])
        self.assertEqual("observed", candidate["source_records"][0]["state"])
        endpoint, key, options = client.paginate_calls[0]
        self.assertIn(
            "name=repository-health-evidence--repository-health-standard",
            endpoint,
        )
        self.assertEqual("artifacts", key)
        self.assertLessEqual(options["max_pages"], 10)
        self.assertEqual(2, options["max_items"])

    def test_partial_and_missing_populations_remain_unknown(self) -> None:
        complete_client, content = _client_for()
        partial = FakeClient(
            artifacts=complete_client.artifacts,
            binaries={10: content},
            records={_run_endpoint(): _observed(_run())},
            population_complete=False,
            listing_gap="page_cap",
        )
        result = _collect(partial)
        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["population_complete"])
        self.assertEqual("unknown", result["candidates"][0]["state"])
        self.assertFalse(result["candidates"][0]["eligible_population_complete"])
        self.assertIn("page_cap", {gap["kind"] for gap in result["gaps"]})

        missing = _collect(FakeClient(artifacts=[]))
        self.assertEqual("unknown", missing["state"])
        self.assertIn("evidence_artifact_missing", {gap["kind"] for gap in missing["gaps"]})

    def test_per_run_population_over_cap_is_never_treated_as_a_recent_subset(self) -> None:
        content = _package_zip(_statement())
        artifacts = [_artifact(index, content) for index in range(1, 4)]
        client = FakeClient(
            artifacts=artifacts,
            binaries={index: content for index in range(1, 4)},
        )
        result = _collect(client, max_artifacts_per_population=2)

        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["population_complete"])
        self.assertEqual(3, result["listings"][0]["reported_total_count"])
        self.assertEqual(2, len(result["candidates"]))
        self.assertTrue(
            all(candidate["state"] == "unknown" for candidate in result["candidates"])
        )
        self.assertEqual([], client.binary_calls)
        self.assertIn("item_cap", {gap["kind"] for gap in result["gaps"]})

    def test_category_policy_is_independent_from_valid_run_result_source(self) -> None:
        client, _ = _client_for()
        result = collect_evidence_artifacts(
            REPOSITORY,
            client=client,
            eligible_runs={RUN_ID: [UNIT_ID]},
            category_policy=None,
            now=NOW,
        )
        candidate = result["candidates"][0]
        self.assertTrue(candidate["identity_complete"])
        self.assertTrue(candidate["result_source_valid"])
        self.assertFalse(candidate["category_policy_valid"])
        self.assertEqual("unknown", candidate["state"])
        self.assertIn(
            "category_policy_unverified",
            {gap["kind"] for gap in candidate["gaps"]},
        )

    def test_units_in_same_run_are_neither_conflicts_nor_interchangeable(self) -> None:
        units = ("service-a", "service-b")
        statements = [_statement(unit_id=unit_id) for unit_id in units]
        contents = [_package_zip(statement) for statement in statements]
        client = FakeClient(
            artifacts=[
                _artifact(10, contents[0], name=evidence_artifact_name(units[0])),
                _artifact(11, contents[1], name=evidence_artifact_name(units[1])),
            ],
            binaries={10: contents[0], 11: contents[1]},
            records={_run_endpoint(): _observed(_run())},
        )
        result = _collect(
            client,
            eligible_runs={RUN_ID: list(units)},
            category_policy=_policy(*units),
        )
        self.assertEqual("observed", result["state"])
        self.assertEqual([], result["conflicts"])
        self.assertEqual(
            set(units),
            {candidate["statement"]["unit_id"] for candidate in result["candidates"]},
        )

        forged = FakeClient(
            artifacts=[
                _artifact(
                    12,
                    contents[1],
                    name=evidence_artifact_name("service-a"),
                )
            ],
            binaries={12: contents[1]},
            records={_run_endpoint(): _observed(_run())},
        )
        only_a = _collect(
            forged,
            eligible_runs={RUN_ID: ["service-a"]},
            category_policy=_policy(*units),
        )
        self.assertEqual("unknown", only_a["state"])
        self.assertIn("ineligible_unit_id", {gap["kind"] for gap in only_a["gaps"]})

    def test_expired_wrong_named_and_oversized_artifacts_are_not_downloaded(self) -> None:
        valid_content = _package_zip(_statement())
        artifacts = [
            _artifact(1, valid_content, expired=True),
            _artifact(2, valid_content, name="repository-health-evidence-forged"),
            _artifact(3, valid_content, size=600_000),
        ]
        client = FakeClient(
            artifacts=artifacts,
            binaries={1: valid_content, 2: valid_content, 3: valid_content},
            respect_name_filter=False,
        )
        result = _collect(client, max_artifacts_per_population=3)
        self.assertEqual([], client.binary_calls)
        self.assertEqual("unknown", result["state"])
        kinds = {gap["kind"] for gap in result["gaps"]}
        self.assertIn("artifact_expired_or_unknown", kinds)
        self.assertIn("unexpected_artifact_name", kinds)
        self.assertIn("artifact_size_cap", kinds)

    def test_download_and_metadata_digest_failures_remain_unknown(self) -> None:
        content = _package_zip(_statement())
        failure = {
            "ok": False,
            "state": "unknown",
            "data": None,
            "error": "expired during download",
            "error_kind": "permission_or_api_gap",
            "status": 404,
        }
        client = FakeClient(
            artifacts=[_artifact(10, content)],
            binaries={10: failure},
        )
        result = _collect(client)
        self.assertIn("permission_or_api_gap", {gap["kind"] for gap in result["gaps"]})

        mismatch = FakeClient(
            artifacts=[_artifact(11, content, digest=f"sha256:{'0' * 64}")],
            binaries={11: content},
        )
        result = _collect(mismatch)
        self.assertIn("artifact_digest_mismatch", {gap["kind"] for gap in result["gaps"]})

    def test_malicious_and_ambiguous_zip_shapes_are_rejected_without_extraction(self) -> None:
        files = _package_files(_statement())
        fixtures = {
            "traversal": _zip_files(
                [("../evidence-statement.json", files["evidence-statement.json"]), ("SHA256SUMS", files["SHA256SUMS"])]
            ),
            "absolute": _zip_files(
                [("/evidence-statement.json", files["evidence-statement.json"]), ("SHA256SUMS", files["SHA256SUMS"])]
            ),
            "symlink": _zip_files(
                list(files.items()), symlinks={"evidence-statement.json"}
            ),
            "duplicate": _zip_files(
                [
                    ("evidence-statement.json", files["evidence-statement.json"]),
                    ("evidence-statement.json", files["evidence-statement.json"]),
                    ("SHA256SUMS", files["SHA256SUMS"]),
                ]
            ),
            "extra": _zip_files([*files.items(), ("extra.txt", b"payload")]),
        }
        expected = {
            "traversal": "unsafe_zip_entry",
            "absolute": "unsafe_zip_entry",
            "symlink": "unsafe_zip_entry_type",
            "duplicate": "duplicate_zip_entry",
            "extra": "unexpected_zip_population",
        }
        for index, (name, content) in enumerate(fixtures.items(), start=1):
            with self.subTest(name=name):
                client = FakeClient(
                    artifacts=[_artifact(index, content)],
                    binaries={index: content},
                )
                result = _collect(client)
                candidate = result["candidates"][0]
                self.assertFalse(candidate["package_valid"])
                self.assertIn(expected[name], {gap["kind"] for gap in candidate["gaps"]})

    def test_zip_entry_and_expanded_byte_caps_fail_closed(self) -> None:
        content = _zip_files(
            [("evidence-statement.json", b"x" * 2000), ("SHA256SUMS", b"y" * 100)]
        )
        client = FakeClient(
            artifacts=[_artifact(10, content)],
            binaries={10: content},
        )
        result = _collect(
            client,
            max_entry_bytes=1024,
            max_expanded_bytes=1500,
        )
        kinds = {gap["kind"] for gap in result["gaps"]}
        self.assertIn("zip_entry_size_cap", kinds)
        self.assertIn("zip_expanded_size_cap", kinds)

    def test_duplicate_key_statement_inside_valid_two_file_zip_is_unknown(self) -> None:
        statement_bytes = b'{"schema_version":"one","schema_version":"two"}\n'
        digest = hashlib.sha256(statement_bytes).hexdigest()
        content = _zip_files(
            [
                ("evidence-statement.json", statement_bytes),
                ("SHA256SUMS", f"{digest}  evidence-statement.json\n".encode("ascii")),
            ]
        )
        client = FakeClient(
            artifacts=[_artifact(10, content)],
            binaries={10: content},
        )
        result = _collect(client)
        self.assertIn("invalid_evidence_package", {gap["kind"] for gap in result["gaps"]})
        self.assertIsNone(result["candidates"][0]["statement"])

    def test_every_run_identity_component_must_match_authoritative_metadata(self) -> None:
        cases = {
            "run-id": {"id": RUN_ID + 1},
            "attempt": {"run_attempt": RUN_ATTEMPT + 1},
            "subject": {"head_sha": "f" * 40},
            "path": {"path": ".github/workflows/other.yml@main"},
            "workflow-ref": {
                "path": ".github/workflows/repository-validation.yml@other"
            },
            "workflow-sha": {"head_sha": "e" * 40},
            "repository": {"repository": {"full_name": "attacker/repository"}},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                client, _ = _client_for(run=_run(**changes))
                result = _collect(client)
                candidate = result["candidates"][0]
                self.assertFalse(candidate["identity_complete"])
                self.assertEqual("unknown", candidate["state"])
                self.assertTrue(
                    {"run_identity_mismatch", "workflow_identity_unavailable"}
                    & {gap["kind"] for gap in candidate["gaps"]}
                )

        client, content = _client_for()
        client.artifacts = [_artifact(10, content, workflow_run_id=RUN_ID + 1)]
        result = _collect(client)
        self.assertIn("artifact_run_identity_mismatch", {gap["kind"] for gap in result["gaps"]})

    def test_unsupported_event_cannot_supply_same_revision_workflow_identity(self) -> None:
        run = _run(event="pull_request_target")
        client, _ = _client_for(run=run)
        result = _collect(client)
        candidate = result["candidates"][0]
        self.assertFalse(candidate["identity_complete"])
        self.assertIn("workflow_identity_unavailable", {gap["kind"] for gap in candidate["gaps"]})

    def test_source_ids_are_unknown_until_supported_records_join(self) -> None:
        unsupported = _statement(source_ids=["scanner-report:opaque-17"])
        client, _ = _client_for(unsupported)
        result = _collect(client)
        candidate = result["candidates"][0]
        self.assertTrue(candidate["package_valid"])
        self.assertTrue(candidate["identity_complete"])
        self.assertFalse(candidate["source_records_complete"])
        self.assertEqual("unknown", candidate["source_records"][0]["state"])
        self.assertIn("unsupported_source_evidence_id", {gap["kind"] for gap in candidate["gaps"]})

        check_statement = _statement(kind="security", source_ids=["github-check-run:77"])
        check_endpoint = f"/repos/{REPOSITORY}/check-runs/77"
        check_record = {
            "id": 77,
            "head_sha": SUBJECT_SHA,
            "status": "completed",
            "conclusion": "success",
            "name": "security-scan",
        }
        client, _ = _client_for(
            check_statement,
            records={check_endpoint: _observed(check_record)},
        )
        result = _collect(client)
        self.assertEqual("observed", result["candidates"][0]["state"])
        self.assertEqual("verified", result["statement_verifications"][0]["state"])
        self.assertEqual("github-check-run", result["candidates"][0]["source_records"][0]["source_type"])

    def test_source_result_mismatch_and_metadata_request_caps_remain_unknown(self) -> None:
        client, _ = _client_for(run=_run(conclusion="failure"))
        result = _collect(client)
        self.assertIn("source_result_mismatch", {gap["kind"] for gap in result["gaps"]})

        check_statement = _statement(source_ids=["github-check-run:77"])
        client, _ = _client_for(check_statement)
        result = _collect(
            client,
            max_metadata_requests=1,
        )
        self.assertIn("metadata_request_cap", {gap["kind"] for gap in result["gaps"]})

    def test_release_success_requires_exact_release_and_asset_records(self) -> None:
        statement = _statement(
            kind="release",
            source_ids=["github-release:55"],
            subject_ref="refs/tags/v1.0.0",
        )
        endpoint = f"/repos/{REPOSITORY}/releases/55"
        tag_endpoint = f"/repos/{REPOSITORY}/git/ref/tags/v1.0.0"
        release = {
            "id": 55,
            "tag_name": "v1.0.0",
            "target_commitish": SUBJECT_SHA,
            "draft": False,
            "published_at": "2026-08-09T12:02:00Z",
            "assets": [
                {"name": "package", "digest": f"sha256:{ARTIFACT_DIGEST}"}
            ],
        }
        tag = {
            "ref": "refs/tags/v1.0.0",
            "object": {"type": "commit", "sha": SUBJECT_SHA},
        }
        client, _ = _client_for(
            statement,
            records={endpoint: _observed(release), tag_endpoint: _observed(tag)},
        )
        result = _collect(client)
        self.assertEqual("observed", result["candidates"][0]["state"])
        self.assertTrue(
            result["candidates"][0]["source_records"][0]["record"]["artifact_binding_complete"]
        )
        self.assertEqual("verified", result["statement_verifications"][0]["state"])

        annotated_sha = "e" * 40
        annotated_endpoint = f"/repos/{REPOSITORY}/git/tags/{annotated_sha}"
        tag["object"] = {"type": "tag", "sha": annotated_sha}
        annotated = {
            "sha": annotated_sha,
            "object": {"type": "commit", "sha": SUBJECT_SHA},
        }
        client, _ = _client_for(
            statement,
            records={
                endpoint: _observed(release),
                tag_endpoint: _observed(tag),
                annotated_endpoint: _observed(annotated),
            },
        )
        self.assertEqual("observed", _collect(client)["candidates"][0]["state"])

        release["target_commitish"] = "main"
        tag["object"] = {"type": "commit", "sha": SUBJECT_SHA}
        client, _ = _client_for(
            statement,
            records={endpoint: _observed(release), tag_endpoint: _observed(tag)},
        )
        self.assertEqual("observed", _collect(client)["candidates"][0]["state"])

        tag["object"] = {"type": "commit", "sha": "f" * 40}
        client, _ = _client_for(
            statement,
            records={endpoint: _observed(release), tag_endpoint: _observed(tag)},
        )
        result = _collect(client)
        self.assertIn(
            "release_subject_binding_incomplete",
            {gap["kind"] for gap in result["gaps"]},
        )

        release["assets"].append(
            {"name": "uncontrolled-extra", "digest": f"sha256:{'e' * 64}"}
        )
        tag["object"] = {"type": "commit", "sha": SUBJECT_SHA}
        client, _ = _client_for(
            statement,
            records={endpoint: _observed(release), tag_endpoint: _observed(tag)},
        )
        result = _collect(client)
        self.assertIn(
            "release_artifact_identity_mismatch",
            {gap["kind"] for gap in result["gaps"]},
        )
        self.assertEqual([], result["statement_verifications"])

    def test_deployment_claim_requires_exact_deployment_status(self) -> None:
        source_id = "github-deployment-status:77:88"
        statement = _statement(kind="deployment", source_ids=[source_id])
        artifact_reference = (
            f"ghcr.io/tedtschopp/github-repository-health@sha256:{ARTIFACT_DIGEST}"
        )
        deployment_endpoint = f"/repos/{REPOSITORY}/deployments/77"
        status_endpoint = f"/repos/{REPOSITORY}/deployments/77/statuses/88"
        records = {
            deployment_endpoint: _observed(
                {
                    "id": 77,
                    "sha": SUBJECT_SHA,
                    "environment": "production",
                    "payload": {
                        "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                        "unit_id": UNIT_ID,
                        "artifact": {
                            "reference": artifact_reference,
                            "sha256": ARTIFACT_DIGEST,
                        },
                    },
                }
            ),
            status_endpoint: _observed({"id": 88, "state": "success"}),
        }
        client, _ = _client_for(statement, records=records)
        result = _collect(client)
        self.assertEqual("observed", result["candidates"][0]["state"])
        self.assertEqual("github-deployment-status", result["candidates"][0]["source_records"][0]["source_type"])
        source_record = result["candidates"][0]["source_records"][0]["record"]
        self.assertEqual(artifact_reference, source_record["artifact_reference"])
        self.assertEqual(ARTIFACT_DIGEST, source_record["artifact_sha256"])
        self.assertTrue(source_record["artifact_binding_complete"])
        self.assertEqual("verified", result["statement_verifications"][0]["state"])

        invalid_payloads = {
            "missing": None,
            "legacy": {
                "schema_version": "repository-health-deployment-artifacts/v1",
                "unit_id": UNIT_ID,
                "artifact_digests": statement["artifact_digests"],
            },
            "extra-key": {
                "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                "unit_id": UNIT_ID,
                "artifact": {
                    "reference": artifact_reference,
                    "sha256": ARTIFACT_DIGEST,
                    "name": "forged",
                },
            },
            "wrong-unit": {
                "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                "unit_id": "different-unit",
                "artifact": {
                    "reference": artifact_reference,
                    "sha256": ARTIFACT_DIGEST,
                },
            },
            "wrong-digest": {
                "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                "unit_id": UNIT_ID,
                "artifact": {
                    "reference": artifact_reference,
                    "sha256": "e" * 64,
                },
            },
            "invalid-reference": {
                "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                "unit_id": UNIT_ID,
                "artifact": {
                    "reference": f" {artifact_reference}",
                    "sha256": ARTIFACT_DIGEST,
                },
            },
        }
        deployment = records[deployment_endpoint]["data"]
        self.assertIsInstance(deployment, dict)
        for label, payload in invalid_payloads.items():
            with self.subTest(payload=label):
                deployment["payload"] = payload
                client, _ = _client_for(statement, records=records)
                result = _collect(client)
                self.assertEqual("unknown", result["candidates"][0]["state"])
                self.assertNotIn(
                    "verified",
                    {
                        verification["state"]
                        for verification in result["statement_verifications"]
                    },
                )
                self.assertIn(
                    "deployment_artifact_binding_incomplete",
                    {gap["kind"] for gap in result["gaps"]},
                )

    def test_pages_deployment_status_is_exact_but_cannot_self_bind_content(self) -> None:
        source_id = "github-pages-deployment:77"
        statement = _statement(kind="deployment", source_ids=[source_id])
        endpoint = f"/repos/{REPOSITORY}/pages/deployments/77"
        client, _ = _client_for(
            statement,
            records={endpoint: _observed({"status": "succeed"})},
        )
        result = _collect(client)
        candidate = result["candidates"][0]
        record = candidate["source_records"][0]
        self.assertTrue(candidate["source_records_complete"])
        self.assertFalse(candidate["result_source_valid"])
        self.assertEqual("github-pages-deployment", record["source_type"])
        self.assertEqual("success", record["classification"])
        self.assertFalse(record["record"]["subject_binding_complete"])
        self.assertFalse(record["record"]["artifact_binding_complete"])
        kinds = {gap["kind"] for gap in candidate["gaps"]}
        self.assertNotIn("source_result_mismatch", kinds)
        self.assertIn("pages_deployment_subject_binding_incomplete", kinds)
        self.assertIn("pages_deployment_artifact_binding_incomplete", kinds)

        sha_source_id = f"github-pages-deployment:{SUBJECT_SHA}"
        sha_statement = _statement(kind="deployment", source_ids=[sha_source_id])
        sha_endpoint = f"/repos/{REPOSITORY}/pages/deployments/{SUBJECT_SHA}"
        sha_client, _ = _client_for(
            sha_statement,
            records={sha_endpoint: _observed({"status": "succeed"})},
        )
        sha_candidate = _collect(sha_client)["candidates"][0]
        self.assertEqual(
            SUBJECT_SHA,
            sha_candidate["source_records"][0]["record"]["pages_deployment_id"],
        )

        malformed = {"status": "succeed", "id": 77}
        client, _ = _client_for(
            statement,
            records={endpoint: _observed(malformed)},
        )
        candidate = _collect(client)["candidates"][0]
        self.assertFalse(candidate["source_records_complete"])
        self.assertIn(
            "invalid_source_record", {gap["kind"] for gap in candidate["gaps"]}
        )

        nonexistent_status_id = _statement(
            kind="deployment",
            source_ids=["github-pages-deployment:77:88"],
        )
        client, _ = _client_for(nonexistent_status_id)
        candidate = _collect(client)["candidates"][0]
        self.assertEqual("unsupported", candidate["source_records"][0]["source_type"])

    def test_duplicate_artifact_and_statement_ids_remain_visible_and_unresolved(self) -> None:
        content = _package_zip(_statement())
        duplicated_artifact = _artifact(10, content)
        client = FakeClient(
            artifacts=[duplicated_artifact, dict(duplicated_artifact)],
            binaries={10: content},
            records={_run_endpoint(): _observed(_run())},
        )
        result = _collect(client)
        self.assertEqual([], client.binary_calls)
        self.assertIn("duplicate_artifact_id", {item["kind"] for item in result["duplicates"]})
        self.assertTrue(all(candidate["state"] == "unknown" for candidate in result["candidates"]))

        client = FakeClient(
            artifacts=[_artifact(10, content), _artifact(11, content)],
            binaries={10: content, 11: content},
            records={_run_endpoint(): _observed(_run())},
        )
        result = _collect(client)
        self.assertIn("duplicate_statement_id", {item["kind"] for item in result["duplicates"]})
        self.assertTrue(all(candidate["state"] == "unknown" for candidate in result["candidates"]))

    def test_conflicting_claims_are_retained_and_not_resolved_by_order(self) -> None:
        success = _statement(result="success")
        unknown = _statement(result="unknown")
        success_zip = _package_zip(success)
        unknown_zip = _package_zip(unknown)
        client = FakeClient(
            artifacts=[_artifact(10, success_zip), _artifact(11, unknown_zip)],
            binaries={10: success_zip, 11: unknown_zip},
            records={_run_endpoint(): _observed(_run())},
        )
        result = _collect(client)
        self.assertEqual(1, len(result["conflicts"]))
        self.assertEqual({10, 11}, set(result["conflicts"][0]["artifact_ids"]))
        self.assertTrue(all(candidate["state"] == "unknown" for candidate in result["candidates"]))
        self.assertEqual(
            {success["statement_id"], unknown["statement_id"]},
            {candidate["statement"]["statement_id"] for candidate in result["candidates"]},
        )

    def test_configuration_bounds_and_repository_identity_are_strict(self) -> None:
        client = FakeClient(artifacts=[])
        for repository in ("owner", "../owner/repo", "owner/repo\nforged"):
            with self.subTest(repository=repository):
                with self.assertRaises(EvidenceArtifactError):
                    collect_evidence_artifacts(
                        repository,
                        client=client,
                        eligible_runs={RUN_ID: [UNIT_ID]},
                        now=NOW,
                    )
        for option, value in (
            ("max_artifacts_per_population", 6),
            ("max_eligible_populations", 51),
            ("max_zip_bytes", 1_048_577),
            ("max_source_records", 17),
        ):
            with self.subTest(option=option):
                with self.assertRaises(EvidenceArtifactError):
                    collect_evidence_artifacts(
                        REPOSITORY,
                        client=client,
                        eligible_runs={RUN_ID: [UNIT_ID]},
                        now=NOW,
                        **{option: value},
                    )
        with self.assertRaisesRegex(EvidenceArtifactError, "run/unit populations"):
            collect_evidence_artifacts(
                REPOSITORY,
                client=client,
                eligible_runs={RUN_ID: [f"unit-{index}" for index in range(21)]},
                max_eligible_populations=20,
                now=NOW,
            )

    def test_collector_has_no_process_or_dynamic_execution_path(self) -> None:
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        self.assertNotIn("subprocess", imports)
        self.assertTrue({"exec", "eval", "system", "popen", "spawn", "extract", "extractall"}.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
